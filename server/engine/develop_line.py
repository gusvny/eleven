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
  - The LANDING RECORD (ledger-record-models-v1): one append-only JSONL row per
    landing — ULID-family id, integer-millisecond ``at``, the repository revision
    set, who performed it.

Coexistence (rule 13): nothing on the running flow imports this module yet. The
new behaviour becomes reachable only through the new lane version (a follow-up
ticket wires it); today's tickets are byte-for-byte unaffected.

Reuse discipline: the add/commit sequence is NEVER copied here — the landing
imports ``_settle_merge_core`` from agent_activities (the single implementation
of MERGE_HEAD check → staging → conflict-marker scan → merge commit) and only
parameterises the base ref. The full fault-mode trade-off list for that borrowed
implementation is in the create_plan gen1 evidence (7 items).
"""
import fcntl
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import shared
# The single add/commit implementation (t261006-07 discipline) — imported, never
# re-implemented. _git is the same bounded-timeout subprocess family.
from agent_activities import _git, _settle_merge_core  # noqa: E402

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


def _record_path(project_key: str) -> Path:
    return shared.develop_dir(project_key) / "landings.jsonl"


def load_landings(project_key: str) -> List[Dict[str, Any]]:
    """Read the landing ledger. Append-only file, strict read: a malformed row or
    an unknown record version raises LandingError — the ledger is never read as
    "empty" through a parse failure (fact-ledger goal 8)."""
    path = _record_path(project_key)
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except ValueError as e:
            raise LandingError("landing ledger row %d malformed (%s): %s" % (i + 1, e, path))
        if not isinstance(row, dict) or row.get("version") != RECORD_VERSION:
            raise LandingError("landing ledger row %d unknown record version: %s" % (i + 1, path))
        rows.append(row)
    return rows


def _append_record(project_key: str, row: Dict[str, Any]) -> None:
    """Append one record row. Called under the landing lock. The duplicate-id
    check runs on append: a ULID makes it almost never fire — which is exactly
    why the check stays (ledger-record-models)."""
    path = _record_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {r.get("id") for r in load_landings(project_key)}
    if row["id"] in existing_ids:
        raise LandingError("duplicate landing id %r — refusing to append" % row["id"])
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def has_landing(project_key: str, ticket_id: str, line_id: str) -> bool:
    """One landing per ticket (goal 7): is there already a record?"""
    return any(r.get("ticket") == ticket_id and r.get("line_id") == line_id
               for r in load_landings(project_key))


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


def _land_locked(line: DevelopLine, project_key: str, repo_paths: Dict[str, Path],
                 ticket_id: str, performed_by: str, result: LandingResult) -> LandingResult:
    wt_root = shared.develop_dir(project_key) / "wt"
    base_map: Dict[str, str] = {}
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
            base_map[name] = start_sha
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
            base_map[name] = mb.stdout.strip()
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
                base_map[name] = mb.stdout.strip()
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
    record = {
        "id": "ldg-" + mint_ulid(now_ms=at_ms),
        "ticket": ticket_id,
        "line_id": line.line_id,
        "revisions": dict(rev_map),
        "base": dict(base_map),
        "at": at_ms,
        "by": performed_by,
        "version": RECORD_VERSION,
    }
    if result.seeded_branches:
        record["seeded_branches"] = list(result.seeded_branches)
    try:
        _append_record(project_key, record)
    except (OSError, LandingError) as e:
        for r2 in line.repositories:
            result.faces.setdefault(r2.name, "untouched")
        raise LandingError("landing record append failed — landing NOT recorded: %s" % e)
    result.ok = True
    result.record = record
    result.revisions = dict(rev_map)
    return result
