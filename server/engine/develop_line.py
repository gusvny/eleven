"""develop_line — the declared develop line and its serialized landing
(t261009-18, develop-buffer slice 1; design: docs/design/develop-buffer-v1.md
goals 1, 2, 6, 7, coexistence rules 12-13).

What lives here:
  - The line DECLARATION (goal 19): an identifier, a scope, an owner and the
    repositories that realise it. A branch name is never the line's identity;
    two lines may not name the same (repository, branch) pair.
  - The LANDING (goal 7): after a lane's own proof passes, the engine merges the
    lane's HEAD into the line's branch, one landing per ticket, serialized by a
    store lock so the line's history stays linear.
  - The LANDING RECORD (t261009-28, ledger-record-models-v1): the landing act
    appends ONE row — the delivery ledger's `kind: "landing"` row — through the
    delivery ledger's own writer (`develop_certify.append_rows`), so the row
    gets its `seq` inside the shared ordering space every delivery face reads.
    The former second home (`landings.jsonl` + `load_landings`) is RETIRED: its
    only question (what content did this ticket put on the line) is exactly the
    delivery ledger's landing row, and two shapes for one fact is what this
    ticket removes. A pre-existing `landings.jsonl` is refused BY NAME at
    landing entry (`LandingLegacyLedgerError`) — never read as "no landings",
    never silently migrated; conversion is a dedicated later ticket.

Coexistence (rule 13, as wired by t261009-46): the new behaviour is reachable ONLY
through the per-ticket lane version — a ticket names its version when it is opened
(the dev_lane intake refuses an unknown/malformed name by title), and a ticket that
did not opt in runs today's flow byte-identically. The dependency stays one-way at
the module level: this module imports the running flow's settle core, and the
running flow reaches the new surface only behind the version gate (dev_lane's
``is_develop_buffer_ticket`` predicate + its gated ``_dev_buffer_*`` step methods).

Reuse discipline: the add/commit sequence is NEVER copied here — the landing
imports ``_settle_merge_core`` from agent_activities (the single implementation
of MERGE_HEAD check → staging → conflict-marker scan → merge commit) and only
parameterises the base ref. The full fault-mode trade-off list for that borrowed
implementation is in the create_plan gen1 evidence (7 items).
"""
import fcntl
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import shared
# The single add/commit implementation (t261006-07 discipline) — imported, never
# re-implemented. _git is the same bounded-timeout subprocess family.
from agent_activities import _git, _settle_merge_core  # noqa: E402
# The delivery ledger's own faces (t261009-28): validation, the single writer
# that assigns `seq` under flock, the reader, and the kind constants. No import
# cycle: develop_certify imports neither this module nor agent_activities.
from develop_certify import (  # noqa: E402
    KIND_CERT, KIND_LANDING, _of_kind, append_rows, landing_freeze_face,
    ledger_path, mint_id, read_rows,
)

# Record shape version (ledger-record-models rule 24: every record carries the
# version of its own shape; an unknown version is a loud failure, never a guess).
RECORD_VERSION = 1
DECLARATION_VERSION = 1

#: The inventory marking (one inventory, two uses — design goal 5): a scenario
#: belongs to the lane's extra proof set when the DECLARED inventory lists it
#: under this suite name (t261009-16; integration/scenario_ledger.py RUN_SUITES).
FAST_SET_SUITE = "fast-set"


class LineDeclarationError(Exception):
    """The line declaration is unreadable, malformed, or of an unknown shape
    version — loud failure, never read as "no lines" (fact-ledger goal 8)."""


class DuplicateBranchError(LineDeclarationError):
    """Two declared lines name the same (repository, branch) pair — rejected at
    load: a shared branch makes the linear-history guarantee undefinable, and
    two-lines-one-branch is exactly the branch-as-identity confusion goal 19
    bans."""


class LandingError(Exception):
    """A landing could not be completed (conflict, dirty tree, git failure,
    malformed input). Always carries a named reason; never a partial record."""


class LandingDuplicateError(LandingError):
    """This ticket already has a landing record on this line — one landing per
    ticket (goal 7); the second attempt is refused loudly, no merge attempted."""


class LandingLegacyLedgerError(LandingError):
    """A retired ``landings.jsonl`` exists in the develop dir (t261009-28).
    The landing act refuses by name: the legacy rows are NOT migrated here and
    are never read as "no landings" — conversion to the delivery ledger is a
    dedicated later ticket."""


class LandNotPinnedError(LandingError):
    """The caller could not pin the lane checkout at the PROVEN revision
    (t261009-46; the t261009-18 handover precondition). The landing refuses by
    name instead of landing the current tip — landing a different tip than the
    one the gate judged is exactly the silent wrong-delivery the handover
    warns about."""


class LineFrozenError(LandingError):
    """The line is under an open freeze and this ticket is not the structural
    exemption (t261009-67, design items 16/17/95/168). The landing refuses
    BEFORE any worktree mutation, naming the freeze episode id, the cause
    certification and the reason — a red that implicates content stops
    landings, and the exemption is judged from a recorded ``repairs``
    relation, never from anything the landing or the ticket declares about
    itself."""


# ------------------------------------------------------------------ lane version


#: The version name a ticket does NOT carry (the fleet's running flow). Absence
#: of an explicit opt-in at intake resolves here; a PRESENT-but-bad name never
#: defaults to either version — it is refused by title.
LANE_VERSION_LEGACY = "legacy-v1"
#: The develop-buffer flow's version name (the opt-in a develop-buffer ticket
#: carries; the only name the version gate routes to the landing path).
LANE_VERSION_DEVELOP_BUFFER = "develop-buffer-v1"
#: The closed registry: intake validates against exactly these, never a prefix
#: match, never a guess.
LANE_VERSIONS = (LANE_VERSION_LEGACY, LANE_VERSION_DEVELOP_BUFFER)

#: A version name is lowercase kebab of alnum segments — a malformed shape is
#: refused as malformed (not as unknown), so the face says which kind of bad.
_VERSION_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class LaneVersionError(ValueError):
    """A lane-version name is malformed — refused at intake, never defaulted."""


class UnknownLaneVersionError(LaneVersionError):
    """A well-formed lane-version name that is not in the registry."""


def parse_lane_version(name: Any) -> str:
    """Intake validation of the per-ticket opt-in (t261009-46 spec (1)).

    Returns the canonical version name. Refusals, each by name:
      - a non-string or blank value -> malformed;
      - a wrong-shape string (uppercase, spaces, underscores, leading/trailing
        dash) -> malformed;
      - a well-shaped unknown name -> unknown, with the registry listed.
    An ABSENT opt-in (``""`` / ``None``) is not refused here: absence is the
    legacy ticket's shape (it did not opt in); callers resolve it to
    ``LANE_VERSION_LEGACY``. A present-but-bad name is NEVER resolved to
    anything — the caller must refuse."""
    if name is None or (isinstance(name, str) and not name.strip()):
        return LANE_VERSION_LEGACY
    if not isinstance(name, str):
        raise LaneVersionError(
            "lane version malformed: expected a string, got %r" % (type(name).__name__,))
    stripped = name.strip()
    if stripped != name:
        raise LaneVersionError(
            "lane version malformed (surrounding whitespace): %r" % name)
    if not _VERSION_NAME_RE.match(stripped):
        raise LaneVersionError(
            "lane version malformed (lowercase kebab-case expected): %r" % name)
    if stripped not in LANE_VERSIONS:
        raise UnknownLaneVersionError(
            "unknown lane version %r (registry: %s) — refused at intake, never "
            "defaulted to either version" % (stripped, ", ".join(LANE_VERSIONS)))
    return stripped


def is_develop_buffer_version(name: Any) -> bool:
    """True iff the ticket's parsed version is the develop-buffer flow. The
    single version gate: every landing-path branch keys on this comparison and
    on nothing else (no template sniffing, no global switch)."""
    return parse_lane_version(name) == LANE_VERSION_DEVELOP_BUFFER


# ---------------------------------------------------------------- declaration


@dataclass
class LineRepository:
    """One repository member of a line: the declared branch that realises the
    line in that repository. The pair is the realisation, never the identity."""

    name: str
    branch: str


@dataclass
class DevelopLine:
    """A declared line (goal 19): identifier, scope, owner, realisation."""

    line_id: str
    scope: str
    owner: str
    repositories: List[LineRepository] = field(default_factory=list)
    #: The lane's extra proof set, DECLARED here (goal 5 / spec (d)); legitimately
    #: empty until the fast-set declaration lands — never hard-coded in this module.
    extra_scenarios: List[str] = field(default_factory=list)
    version: int = DECLARATION_VERSION


def _parse_line(raw: Any) -> DevelopLine:
    """Parse one declaration entry; malformed = loud error, no guessing."""
    if not isinstance(raw, dict):
        raise LineDeclarationError("line entry is not an object: %r" % (raw,))
    version = raw.get("version", DECLARATION_VERSION)
    if version != DECLARATION_VERSION:
        raise LineDeclarationError("unknown declaration version %r" % (version,))
    line_id = raw.get("line_id")
    if not isinstance(line_id, str) or not line_id.strip():
        raise LineDeclarationError("line_id missing or malformed: %r" % (line_id,))
    repos_raw = raw.get("repositories")
    if not isinstance(repos_raw, list) or not repos_raw:
        raise LineDeclarationError("repositories must be a non-empty list (line %s)" % line_id)
    repos = []
    for r in repos_raw:
        if not isinstance(r, dict) or not isinstance(r.get("name"), str) \
                or not isinstance(r.get("branch"), str) or not r["name"] or not r["branch"]:
            raise LineDeclarationError("repository entry malformed (line %s): %r" % (line_id, r))
        repos.append(LineRepository(name=r["name"], branch=r["branch"]))
    extras = raw.get("extra_scenarios", [])
    if not isinstance(extras, list) or not all(isinstance(x, str) for x in extras):
        raise LineDeclarationError("extra_scenarios must be a list of names (line %s)" % line_id)
    return DevelopLine(
        line_id=line_id.strip(),
        scope=str(raw.get("scope", "")),
        owner=str(raw.get("owner", "")),
        repositories=repos,
        extra_scenarios=list(extras),
        version=version,
    )


def load_lines(project_key: str) -> Dict[str, DevelopLine]:
    """Load every declared line of a project from the store declaration file
    ``<develop_dir>/lines.json`` (a DECLARED thing, hand/admin-written, read by
    the engine). Availability is explicit: an unreadable or malformed file raises
    LineDeclarationError instead of reading as "nothing declared"."""
    path = shared.develop_dir(project_key) / "lines.json"
    if not path.is_file():
        raise LineDeclarationError("line declaration missing: %s" % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LineDeclarationError("line declaration unreadable: %s (%s)" % (path, e))
    if not isinstance(data, list):
        raise LineDeclarationError("line declaration must be a list: %s" % path)
    lines: Dict[str, DevelopLine] = {}
    seen: Dict[Tuple[str, str], str] = {}
    for raw in data:
        line = _parse_line(raw)
        if line.line_id in lines:
            raise LineDeclarationError("duplicate line_id %r" % line.line_id)
        for repo in line.repositories:
            key = (repo.name, repo.branch)
            if key in seen:
                raise DuplicateBranchError(
                    "lines %r and %r both name repository %r branch %r — a branch "
                    "realises at most one line (goal 19/7)" % (seen[key], line.line_id,
                                                               repo.name, repo.branch))
            seen[key] = line.line_id
        lines[line.line_id] = line
    return lines


def load_line(project_key: str, line_id: str) -> DevelopLine:
    """One declared line by its identifier (never by a branch name)."""
    lines = load_lines(project_key)
    if line_id not in lines:
        raise LineDeclarationError("line %r not declared (have: %s)"
                                   % (line_id, sorted(lines)))
    return lines[line_id]


def fast_set_names(inventory: Any) -> List[str]:
    """The lane's extra proof set, read from the DECLARED inventory (goal 5: one
    inventory, two uses). ``inventory`` is the scenario-registry shape: a list of
    entries carrying ``name`` and a suite list. Nothing is hard-coded here: an
    inventory without fast-set members yields an empty set, which is legitimate
    until the declaration provides them (spec (d))."""
    if not isinstance(inventory, list):
        raise LineDeclarationError("inventory must be a list, got %s" % type(inventory).__name__)
    names: List[str] = []
    for entry in inventory:
        if not isinstance(entry, dict):
            raise LineDeclarationError("inventory entry malformed: %r" % (entry,))
        suites = entry.get("suites", [])
        if FAST_SET_SUITE in suites:
            names.append(entry["name"])
    return names


def extra_scenarios(line: DevelopLine, inventory: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """The lane's declared extra set: the line's own declaration, optionally
    crossed with the declared inventory's fast-set marking. The declaration is
    the only source; this module contains no scenario-name literal."""
    names = list(line.extra_scenarios)
    if inventory is not None:
        declared = set(fast_set_names(inventory))
        names = [n for n in names if n in declared]
    return names


# ------------------------------------------------------------------ record id


def mint_ulid(now_ms: Optional[int] = None, rand: Optional[bytes] = None) -> str:
    """A time-prefixed, coordination-free id (ledger-record-models): 48-bit
    millisecond timestamp + 80 bits of randomness, Crockford base32, 26 chars.
    Pure function (clock and randomness injectable) so tests can pin both."""
    ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if ms < 0 or ms >= 2 ** 48:
        raise LandingError("ulid timestamp out of range: %r" % ms)
    entropy = secrets.token_bytes(10) if rand is None else bytes(rand)
    if len(entropy) != 10:
        raise LandingError("ulid entropy must be 10 bytes, got %d" % len(entropy))
    value = (ms << 80) | int.from_bytes(entropy, "big")
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out = []
    for _ in range(26):  # the canonical ULID length: 128 bits fit in 26x5 chars
        out.append(alphabet[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def ulid_time_ms(ulid: str) -> int:
    """Decode the 48-bit millisecond timestamp back out of a minted id (the
    lexicographic order IS time order; this makes it exactly decodable)."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    if len(ulid) != 26 or any(c not in alphabet for c in ulid):
        raise LandingError("malformed ulid: %r" % (ulid,))
    value = 0
    for c in ulid:
        value = (value << 5) | alphabet.index(c)
    return value >> 80


# ------------------------------------------------------------- landing record
# (t261009-28: the landing record's ONE home is the delivery ledger. The
# former line landing ledger faces — load_landings / _record_path /
# _append_record — are retired with it; develop_certify owns the reader and
# the writer.)


def _legacy_record_path(project_key: str) -> Path:
    """The RETIRED line landing ledger's path. Used only to refuse it by name;
    never read as data."""
    return shared.develop_dir(project_key) / "landings.jsonl"


def _landing_rows(project_key: str) -> List[Dict[str, Any]]:
    """The line's landing rows, read from the delivery ledger (kind filter,
    seq order from the shared space). An absent ledger is an empty one —
    nothing has landed yet; a malformed row is the writer's named refusal,
    raised on the next append, never silently skipped here."""
    rows, _bad = read_rows(ledger_path(project_key))
    return _of_kind(rows, KIND_LANDING)


def has_landing(project_key: str, ticket_id: str, line_id: str) -> bool:
    """One landing per ticket (goal 7): is there already a landing row for
    this (ticket, line) in the delivery ledger?"""
    return any(r.get("ticket") == ticket_id and r.get("line") == line_id
               for r in _landing_rows(project_key))


# -------------------------------------------------------------------- landing


@dataclass
class LandingResult:
    """The landing receipt: per-repo faces, the appended record (None when the
    landing failed — a record is a fact about a completed act), and the named
    failure reason when ok is False."""

    ok: bool
    ticket_id: str
    line_id: str
    record: Optional[Dict[str, Any]] = None
    revisions: Dict[str, str] = field(default_factory=dict)
    seeded_branches: List[str] = field(default_factory=list)
    error: str = ""
    faces: Dict[str, str] = field(default_factory=dict)  # per-repo state on failure


def _rev(repo: Path, ref: str) -> str:
    try:
        p = _git(["rev-parse", "--verify", ref], repo)
    except (FileNotFoundError, NotADirectoryError):
        return ""  # not a checkout at all — fail-closed empty, the caller raises
    if p.returncode != 0:
        return ""
    return (p.stdout or "").strip()


def _branch_of(repo: Path) -> str:
    p = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    return (p.stdout or "").strip() if p.returncode == 0 else ""


def _ensure_line_worktree(repo: Path, repo_meta: LineRepository, wt_dir: Path,
                          result: LandingResult) -> Tuple[str, str]:
    """Materialise the engine-owned line worktree and return (branch, start_sha).
    A missing line branch is seeded at main on the first landing (the declaration
    still owns the identity; the seed is reported, not silent)."""
    branch_sha = _rev(repo, "refs/heads/%s" % repo_meta.branch)
    if not branch_sha:
        main_sha = _rev(repo, "refs/heads/main")
        if not main_sha:
            raise LandingError("repository %r has neither branch %r nor main — cannot seed"
                               % (repo_meta.name, repo_meta.branch))
        p = _git(["worktree", "add", "-b", repo_meta.branch, str(wt_dir), "main"], repo)
        if p.returncode != 0:
            raise LandingError("seeding line branch %r failed: %s"
                               % (repo_meta.branch, (p.stderr or "")[-300:]))
        result.seeded_branches.append(repo_meta.branch)
        return repo_meta.branch, main_sha
    if not wt_dir.exists():
        p = _git(["worktree", "add", str(wt_dir), repo_meta.branch], repo)
        if p.returncode != 0:
            raise LandingError("line worktree add failed for %r: %s"
                               % (repo_meta.name, (p.stderr or "")[-300:]))
    return repo_meta.branch, branch_sha


def _abort_if_merging(repo: Path, wt_dir: Path) -> None:
    """Terminal-state discipline: never leave a mid-merge worktree behind."""
    if _rev(wt_dir, "MERGE_HEAD"):
        _git(["merge", "--abort"], wt_dir)


def pin_lane_revision(wt_dir: Path, proven_sha: str) -> str:
    """Pin the lane checkout at the PROVEN revision (t261009-46 spec (3); the
    t261009-18 handover precondition). ``land_ticket`` consumes the lane
    repository's CURRENT HEAD, so the caller must guarantee the checkout sits
    at the revision the gate passed — this helper is that guarantee:
      - HEAD already == proven -> return it (the common case, zero mutation);
      - otherwise, a CLEAN tree is checked out (detached) at the proven sha;
      - a dirty tree, an unresolvable revision, or any git failure raises
        ``LandNotPinnedError`` naming both shas — the landing refuses instead
        of landing something else. Never a silent fallback to HEAD."""
    if not isinstance(proven_sha, str) or not proven_sha.strip():
        raise LandNotPinnedError("proven revision missing — refusing to land")
    proven = proven_sha.strip()
    resolved = _rev(wt_dir, proven)
    if not resolved or set(resolved) == {"0"}:
        # an all-zero sha "verifies" syntactically in git — it is not a commit
        raise LandNotPinnedError(
            "proven revision %s is not resolvable in the lane repo %s — "
            "refusing to land a revision the gate never judged"
            % (proven[:12], wt_dir))
    head = _rev(wt_dir, "HEAD")
    if head and head == proven:
        return head
    dirty = _git(["status", "--porcelain"], wt_dir)
    if dirty.returncode != 0:
        raise LandNotPinnedError(
            "cannot read the lane checkout state in %s: %s"
            % (wt_dir, (dirty.stderr or "")[-200:]))
    if (dirty.stdout or "").strip():
        raise LandNotPinnedError(
            "lane checkout %s is dirty — refusing to move it to the proven "
            "revision %s (uncommitted work would be discarded; handle by hand)"
            % (wt_dir, proven[:12]))
    co = _git(["checkout", "-q", "--detach", proven], wt_dir)
    if co.returncode != 0:
        raise LandNotPinnedError(
            "pinning the lane checkout at the proven revision %s failed: %s"
            % (proven[:12], (co.stderr or co.stdout or "")[-200:]))
    pinned = _rev(wt_dir, "HEAD")
    if pinned != proven:
        raise LandNotPinnedError(
            "pin verification failed: HEAD %s != proven %s — refusing to land"
            % ((pinned or "?")[:12], proven[:12]))
    return pinned


def _check_inputs(ticket_id: Any, performed_by: Any, repo_paths: Dict[str, Path]) -> None:
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        raise LandingError("malformed ticket_id: %r" % (ticket_id,))
    if not isinstance(performed_by, str) or not performed_by.strip():
        raise LandingError("malformed performed_by: %r" % (performed_by,))
    if not isinstance(repo_paths, dict) or not repo_paths:
        raise LandingError("repo_paths must be a non-empty mapping")
    for name, path in repo_paths.items():
        if not isinstance(name, str) or not name:
            raise LandingError("malformed repository name: %r" % (name,))
        if not isinstance(path, Path) or _rev(path, "HEAD") == "":
            raise LandingError("repository %r is not a git checkout: %r" % (name, path))


def land_ticket(line: DevelopLine, project_key: str,
                repo_paths: Dict[str, Path], ticket_id: str,
                performed_by: str, *, lock_timeout_s: int = 60) -> LandingResult:
    """Land a proven lane onto its declared line.

    Serialized by an exclusive lock on ``<develop_dir>/landings.lock`` held for
    the whole act (two landings cannot interleave — goal 7). Per repository,
    sequentially, all-or-nothing (goal 18): seed-or-checkout the line worktree →
    assert it is clean (so the settle core's ``add -A`` stages merge output only)
    → fail-closed merge-base → ``merge --no-ff --no-commit`` (MERGE_HEAD must
    survive to the settle core) → the imported ``_settle_merge_core`` performs
    the one merge commit → message amend (the settle core's conflict-resolution
    message is wrong for a landing; see the fault-mode ledger) → record the
    post-amend sha. On any failure: abort every MERGE_HEAD holder, name the
    per-repo faces, append NO record.
    """
    result = LandingResult(ok=False, ticket_id=ticket_id, line_id=line.line_id)
    _check_inputs(ticket_id, performed_by, repo_paths)
    declared = {r.name: r for r in line.repositories}
    missing = sorted(set(repo_paths) - set(declared))
    if missing:
        raise LandingError("repositories not declared on line %r: %s" % (line.line_id, missing))
    if has_landing(project_key, ticket_id, line.line_id):
        raise LandingDuplicateError(
            "ticket %r already landed on line %r — one landing per ticket" % (ticket_id, line.line_id))
    # No backward magic (t261009-28): a retired line landing ledger is refused
    # by name at entry — its rows are neither read nor migrated here.
    legacy = _legacy_record_path(project_key)
    if legacy.is_file():
        raise LandingLegacyLedgerError(
            "retired landing ledger %s exists — the landing record's one home is "
            "the delivery ledger (develop_certify.append_rows); migrate its rows "
            "with the dedicated conversion ticket, never by landing over it"
            % legacy)

    lock_path = shared.develop_dir(project_key) / "landings.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_f = open(lock_path, "w")
    try:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Blocking wait bounded by timeout: a concurrent landing must never
            # interleave, and a stuck lock must never hang the caller silently.
            import errno as _errno
            deadline = time.monotonic() + lock_timeout_s
            acquired = False
            while time.monotonic() < deadline:
                time.sleep(0.05)
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as e:
                    if e.errno not in (_errno.EACCES, _errno.EAGAIN):
                        raise LandingError("landing lock acquire failed: %s" % e)
            if not acquired:
                raise LandingError("landing lock busy for %ds — landing refused, not queued"
                                   % lock_timeout_s)
        return _land_locked(line, project_key, repo_paths, ticket_id, performed_by, result)
    finally:
        lock_f.close()  # releases the flock on every path


def _check_ancestor(wt_dir: Path, name: str, certified: Optional[str],
                    landed: str) -> None:
    """The design's per-repository ancestor check (ledger-record-models-v1,
    landing entry): the certified revision must be an ancestor of the revision
    that landed. Performed here, at act time, from the delivery ledger's own
    records — the state a landing sits on is DERIVED, so no ``base`` is stored.
    Before the line's first certification there is no derived predecessor (the
    declaration carries no starting revisions); the fail-closed merge-base
    assertion already run is the interim check for that case (``certified``
    is None). Fail-closed on an unreadable certified sha too: a ledger naming
    a revision the worktree cannot see refuses the landing by name."""
    if not certified:
        return
    known = _rev(wt_dir, certified)
    if not known:
        raise LandingError(
            "ancestor check failed in %r: the certified revision %s is not "
            "resolvable in the line worktree — refusing to land over content "
            "the ledger certifies but this line does not carry" % (name, certified[:12]))
    anc = _git(["merge-base", "--is-ancestor", certified, landed], wt_dir)
    if anc.returncode != 0:
        raise LandingError(
            "ancestor check failed in %r: certified revision %s is NOT an "
            "ancestor of the landed revision %s — the landing would skip or "
            "revert certified content" % (name, certified[:12], landed[:12]))


def _land_locked(line: DevelopLine, project_key: str, repo_paths: Dict[str, Path],
                 ticket_id: str, performed_by: str, result: LandingResult) -> LandingResult:
    wt_root = shared.develop_dir(project_key) / "wt"
    # The state each repository sits on, DERIVED once before the act: the
    # line's latest certification's revision per repository (None where the
    # line has never certified that repo). Never stored on the landing.
    rows = read_rows(ledger_path(project_key))[0]
    # The freeze consultation (t261009-67, goals 16/17/168): judged INSIDE the
    # locked region, BEFORE any worktree mutation, from the same ledger read
    # the ancestor gate consumes — so a freeze opened concurrently is already
    # in these rows and no freeze can slip between check and act. The face
    # takes no kind parameter: the only way through a frozen line is a
    # current ``repairs`` relation naming a landing on THIS line (structural,
    # never self-declared). Tests anchor on the reason + freeze/cause ids.
    face = landing_freeze_face(rows, line.line_id, ticket_id)
    if not face["allowed"]:
        raise LineFrozenError(
            "landing refused: line %r is frozen (freeze %s, cause cert %s): %s"
            % (line.line_id, face["freeze"], face["cause"], face["reason"]))
    certs = _of_kind(rows, KIND_CERT, line.line_id)
    cert_rev: Dict[str, str] = {}
    if certs:
        for r in certs[-1].get("repos", []):
            if isinstance(r, dict) and isinstance(r.get("repo"), str) \
                    and isinstance(r.get("revision"), str):
                cert_rev[r["repo"]] = r["revision"]
    rev_map: Dict[str, str] = {}
    for repo_meta in line.repositories:
        name = repo_meta.name
        lane_repo = repo_paths[name]
        wt_dir = wt_root / name
        try:
            lane_sha = _rev(lane_repo, "HEAD")
            if not lane_sha:
                raise LandingError("lane repository %r has no HEAD" % name)
            branch, start_sha = _ensure_line_worktree(lane_repo, repo_meta, wt_dir, result)
            dirty = _git(["status", "--porcelain"], wt_dir)
            if dirty.returncode != 0 or (dirty.stdout or "").strip():
                raise LandingError(
                    "line worktree %r not clean before merge (engine-owned state "
                    "corruption) — add -A must stage merge output only" % name)
            # Fail-closed merge-base (the _merge_base_ref stance, KI-010: never
            # fall back to a literal ref).
            mb = _git(["merge-base", branch, lane_sha], wt_dir)
            if mb.returncode != 0 or not (mb.stdout or "").strip():
                raise LandingError("merge-base %s %s failed in line worktree %r: %s"
                                   % (branch, lane_sha[:12], name, (mb.stderr or "")[-200:]))
            # The design's ancestor gate, BEFORE any commit: the certified
            # revision must be an ancestor of the line tip the landing builds
            # on (a landing only adds content on top, so the pre-merge tip is
            # the exact face to judge — refusing here moves no head and writes
            # no record). Before the line's first certification this is the
            # declared interim: no derived predecessor exists and the
            # fail-closed merge-base above stands in.
            line_tip = _rev(wt_dir, "HEAD")
            if not line_tip:
                raise LandingError("line worktree %r has no HEAD before merge" % name)
            _check_ancestor(wt_dir, name, cert_rev.get(name), line_tip)
            # Named "already contained" path. Two distinct faces:
            #  - a record already exists → the ticket landed before: refuse as a
            #    duplicate (nothing to land);
            #  - no record → this is the KI-213 recovery face: a crashed landing
            #    left its merge commit on the line before the record was written.
            #    Complete the landing WITHOUT amending (the commit pre-dates this
            #    call — rewriting it would corrupt a history another landing may
            #    already sit on) and append the missing record.
            anc = _git(["merge-base", "--is-ancestor", lane_sha, "HEAD"], wt_dir)
            if anc.returncode == 0:
                if has_landing(project_key, ticket_id, line.line_id):
                    result.faces[name] = "nothing to land: lane tip already recorded on the line"
                    raise LandingDuplicateError(
                        "landing of %s onto line %r in %r: nothing to land — the lane tip "
                        "%s is already recorded on the line" % (ticket_id, line.line_id,
                                                               name, lane_sha[:12]))
                head_sha = _rev(wt_dir, "HEAD")
                if not head_sha:
                    raise LandingError("recovery face: HEAD unreadable in %r" % name)
                rev_map[name] = head_sha
                result.faces[name] = ("recovered: lane tip already on the line "
                                      "(no new commit, no amend)")
                continue
            merge = _git(["merge", "--no-ff", "--no-commit", lane_sha], wt_dir)
            if merge.returncode != 0:
                _abort_if_merging(lane_repo, wt_dir)
                result.faces[name] = "conflict: bounced back to the lane (no record written)"
                raise LandingError(
                    "landing of %s onto line %r conflicts in repository %r — the lane "
                    "re-merges the line and lands again" % (ticket_id, line.line_id, name))
            settle = _settle_merge_core(wt_dir, ticket_id, 0, base_ref=branch)
            if not settle.ok:
                _abort_if_merging(lane_repo, wt_dir)
                result.faces[name] = "settle refused: %s" % settle.error
                raise LandingError("settle core refused the landing in %r: %s"
                                   % (name, settle.error))
            if getattr(settle, "already_settled", False):
                # KI-213 recovery face: the commit pre-dates this landing call —
                # amending would rewrite a pre-existing line commit. Named path:
                # refuse for re-inspection, never silently amend HEAD.
                _abort_if_merging(lane_repo, wt_dir)
                result.faces[name] = "already_settled recovery face — no new commit by this landing"
                raise LandingError(
                    "landing of %s in %r hit the already_settled face (MERGE_HEAD absent "
                    "at settle) — refuse for re-inspection" % (ticket_id, name))
            # Message stance (create_plan gen1 option c): the settle core commits
            # with its conflict-resolution message; the landing amends it under
            # the lock, before any record write. The record must never name a sha
            # the branch history no longer contains, so only the post-amend sha
            # survives here (the pre-amend hash is discarded by design).
            msg = ("landing %s onto line %s (%s): rev %s"
                   % (ticket_id, line.line_id, name, lane_sha[:12]))
            amend = _git(["commit", "--amend", "-m", msg], wt_dir)
            if amend.returncode != 0:
                result.faces[name] = "amend failed: %s" % ((amend.stderr or "")[-200:])
                raise LandingError("landing commit amend failed in %r" % name)
            new_sha = _rev(wt_dir, "HEAD")
            if not new_sha:
                raise LandingError("post-amend HEAD unreadable in %r" % name)
            rev_map[name] = new_sha
            result.faces[name] = "landed at %s" % new_sha[:12]
        except LandingError:
            # All-or-nothing: roll every repo that still holds MERGE_HEAD back to
            # a merge-clean face, name the faces, no record.
            for r2 in line.repositories:
                wt2 = wt_root / r2.name
                if wt2.exists():
                    _abort_if_merging(repo_paths[r2.name], wt2)
            for r2 in line.repositories:
                result.faces.setdefault(r2.name, "untouched")
            raise
    at_ms = int(time.time() * 1000)
    # The landing record's ONE home: the delivery ledger, written through its
    # own writer so `seq` is assigned inside the shared critical section (the
    # ordering space derive_range / ticket_wait_state / the promotion faces
    # read). Shape per validate_row's landing branch: kind / ldg- id / ticket /
    # line / repos / actor; `base` is NOT carried — what the landing sat on is
    # derived (see _check_ancestor), and a second stored answer to what the
    # certification already answers is the drift this ticket removes.
    repos_rows = [{"repo": name, "revision": sha} for name, sha in rev_map.items()]
    record = {
        "kind": KIND_LANDING,
        "id": mint_id("ldg", at_ms=at_ms),
        "ticket": ticket_id,
        "line": line.line_id,
        "repos": repos_rows,
        "at": at_ms,
        "actor": performed_by,
        "version": RECORD_VERSION,
    }
    if result.seeded_branches:
        record["seeded_branches"] = list(result.seeded_branches)
    try:
        written = append_rows([record], ledger_path(project_key))
    except Exception as e:  # named wrap: CertifyError / OSError -> LandingError
        for r2 in line.repositories:
            result.faces.setdefault(r2.name, "untouched")
        raise LandingError("delivery ledger append failed — landing NOT recorded: %s" % e)
    if written.get("written") != 1:
        # Rejected-but-not-raised (validate_row refusal, duplicate id): the
        # merges are already committed, but NO record exists — the named error
        # keeps that face loud, and the KI-213 recovery face covers the retry.
        for r2 in line.repositories:
            result.faces.setdefault(r2.name, "untouched")
        raise LandingError("delivery ledger rejected the landing row — landing NOT "
                           "recorded: %r" % (written.get("rejected"),))
    result.ok = True
    result.record = record  # carries the `seq` the writer assigned in place
    result.revisions = dict(rev_map)
    return result
