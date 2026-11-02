# -*- coding: utf-8 -*-
"""pr_flow -- the optional GitHub review-request delivery flow, STEP (a) only.

Design: docs/design/github-pr-flow-v1.md (requirement 1, 2 and the upfront
credential constraint). Steps (b) open the request, (c) poll and send comments
back, (d) reconcile after the platform merges. THIS module ships only the two
preconditions those steps consume, and nothing else in the engine consults it
yet -- which is exactly why a project that does not set the switch keeps today's
behaviour byte for byte.

WHAT IS HERE

1. The project switch. A project declaration (<projects_root>/<key>/project.yaml,
   the registry the engine already owns) may carry one additive top-level block:

       github_pr:
         enabled: true
         repositories:
           - owner/name

   Absent block = OFF = the historical local-signature/local-landing path. The
   read is a pure function of that one file: no credential read, no network, no
   new state, no directory created. A block that is present but unparseable is a
   NAMED stop, never silently read as "off" (a typo in a switch must not decide
   the delivery mode by accident).

2. The credential. When the switch is ON, the operator's GitHub credential is
   resolved from the per-user sandbar home -- `$SANDBAR_HOME` or `~/.sandbar` --
   at `github/credential`, i.e. OUTSIDE every repository worktree and shared by
   all projects. The placement is enforced, not merely documented: a path that
   resolves into a worktree (an ancestor carries `.git`, or the path sits under a
   declared project directory) is refused by name before a single byte is read.
   Least privilege is the operator's token choice; this face only refuses a token
   file that anybody but the owner can read (mode bits other than 0600/0400).

3. The four (plus shape) named refusals. A stop is a `PrFlowStop` carrying one
   `code` from the table below; it is raised once, never retried in a loop, and
   never downgraded to "off". The four the design names are marked REQUIRED:

       github_pr_credential_missing      REQUIRED  switch ON, no credential file
       github_pr_credential_unreadable   REQUIRED  file exists, read/decoding failed
       github_pr_credential_empty        REQUIRED  file readable, zero characters
       github_pr_credential_rejected     REQUIRED  the single validity probe said no
       github_pr_credential_permissions            group/other permission bits set
       github_pr_credential_short                  shorter than any real token (a placeholder)
       github_pr_credential_malformed              interior whitespace / newline / oversized
       github_pr_credential_in_worktree            resolves inside a repository worktree
       github_pr_credential_probe_failed           the probe could not answer
       github_pr_declaration_malformed             switch block shape is not usable
       github_pr_declaration_unreadable            the declaration file could not be read
       github_pr_switch_repositories_missing       ON without declared repositories

4. Redaction. The secret must never reach a ticket face, a receipt, a ledger row,
   a log line or an exception string. Every string this module produces goes
   through `redact`, and every surface it hands out (`PrFlowStop.face`,
   `FlowDecision.face`, `scrub` for arbitrary payloads) is redacted by
   construction. Two layers: the registered secret values (registered the moment a
   `Credential` is built, so a caller cannot forget) plus a token-shape sweep that
   catches a platform error text carrying some *other* token we never registered.
   A `Credential` prints as its fingerprint only; `reveal()` is the one explicit,
   grep-able way to get the value, and only step (b)'s HTTP call may use it.

5. Network. Nothing here opens a connection. `probe_github_token` is the single
   seam that may, it imports its HTTP client inside the function, it is injected
   (`probe=`), and both the tests and the OFF path never reach it. The default for
   every entry point is "no probe" = shape-validated only, which is the honest
   step-(a) answer: validity against the platform is step (b)'s first live call.

Light-import discipline: stdlib only, no temporalio, no `shared` import (this face
must stay importable from a bare interpreter, and the registry root is mirrored
from `shared.registry_root` by reading the same env, the way audit.py and
event_ledger.py read their own additive sections).

Tests: server/engine/tests/test_t261004_44_deliver_refusal.py (the delivery
named-refusal carrier), section "PR flow step (a)".
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote

# ---- the declaration face ---------------------------------------------------

#: The additive top-level block this face owns inside a project declaration.
SECTION = "github_pr"
#: Same registry root semantics as shared.registry_root / audit._projects_root
#: (env read fresh on every call; never cached, so a test env flip takes effect).
PROJECTS_DIR_ENV = "SANDBAR_PROJECTS_DIR"
#: The per-user sandbar home. Overridable so tests never touch the real one.
HOME_ENV = "SANDBAR_HOME"
DEFAULT_HOME_DIRNAME = ".sandbar"
#: The credential lives in the home, outside every worktree, shared by projects.
CREDENTIAL_DIRNAME = "github"
CREDENTIAL_FILENAME = "credential"
#: The project key whitelist (mirrors shared.PROJECT_KEY_RE; a key is a path
#: segment here, so a traversal attempt must be refused before any join).
PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
#: `owner/name` is the only repository form the attribute accepts (the platform's
#: own spelling; anything else would be a guess about a different platform).
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TRUE_WORDS = frozenset(("true", "yes", "on", "1"))
_FALSE_WORDS = frozenset(("false", "no", "off", "0"))

# ---- credential shape limits ------------------------------------------------

#: A real GitHub token is >= 40 chars; below this it is a placeholder or a paste
#: mistake. Above MAX it is not a token but a document.
MIN_CREDENTIAL_CHARS = 20
MAX_CREDENTIAL_CHARS = 512
#: The mode bits a credential file may carry: owner read plus owner write (0o400 is
#: a subset of this). Any group/other bit is a refusal: "readable beyond its owner"
#: is the one property this face can judge about who can see the value.
_ALLOWED_MODE_BITS = 0o600

# ---- named stops (one table, the whole vocabulary; never retried) -----------

STOP_DECLARATION_UNREADABLE = "github_pr_declaration_unreadable"
STOP_DECLARATION_MALFORMED = "github_pr_declaration_malformed"
STOP_SWITCH_REPOSITORIES_MISSING = "github_pr_switch_repositories_missing"
STOP_CREDENTIAL_MISSING = "github_pr_credential_missing"
STOP_CREDENTIAL_UNREADABLE = "github_pr_credential_unreadable"
STOP_CREDENTIAL_EMPTY = "github_pr_credential_empty"
STOP_CREDENTIAL_REJECTED = "github_pr_credential_rejected"
STOP_CREDENTIAL_PERMISSIONS = "github_pr_credential_permissions"
STOP_CREDENTIAL_SHORT = "github_pr_credential_short"
STOP_CREDENTIAL_MALFORMED = "github_pr_credential_malformed"
STOP_CREDENTIAL_IN_WORKTREE = "github_pr_credential_in_worktree"
STOP_PROBE_FAILED = "github_pr_credential_probe_failed"

#: The four the design's requirement 2 names, kept as a set so a test can prove
#: they are four DISTINCT stops rather than one reworded message.
REQUIRED_STOPS = (
    STOP_CREDENTIAL_MISSING,
    STOP_CREDENTIAL_UNREADABLE,
    STOP_CREDENTIAL_EMPTY,
    STOP_CREDENTIAL_REJECTED,
)

#: code -> what the stop means, in one line (REQUIRED marks the four the design
#: names). This table is the WHOLE vocabulary: a stop outside it is a bug, and
#: every entry is TERMINAL -- the ticket stops here once. No entry is retryable
#: (a loop would hide an absent credential behind "still trying") and no entry may
#: be reported as "off" (that would silently pick the historical delivery mode).
STOP_TABLE = {
    STOP_DECLARATION_UNREADABLE: "the project declaration could not be read",
    STOP_DECLARATION_MALFORMED: "the github_pr switch block is not usable",
    STOP_SWITCH_REPOSITORIES_MISSING: "switch on, but no repositories are declared",
    STOP_CREDENTIAL_MISSING: "REQUIRED: switch on, no credential file",
    STOP_CREDENTIAL_UNREADABLE: "REQUIRED: the credential file could not be read",
    STOP_CREDENTIAL_EMPTY: "REQUIRED: the credential file holds no value",
    STOP_CREDENTIAL_REJECTED: "REQUIRED: the platform rejected the credential",
    STOP_CREDENTIAL_PERMISSIONS: "the credential is readable beyond its owner",
    STOP_CREDENTIAL_SHORT: "the value is shorter than any real token",
    STOP_CREDENTIAL_MALFORMED: "the value is not one token on one line",
    STOP_CREDENTIAL_IN_WORKTREE: "the credential resolves inside a worktree",
    STOP_PROBE_FAILED: "the validity probe could not answer",
}


def is_named_stop(code: Any) -> bool:
    """True for every stop this face can raise. Every one of them is terminal:
    raise it once, report it by name, do not retry, never read it as "off"."""
    return str(code or "") in STOP_TABLE


# ---- redaction --------------------------------------------------------------

REDACTED = "[redacted]"
#: Below this length a "secret" would redact ordinary text; nothing a platform
#: issues is that short (MIN_CREDENTIAL_CHARS is the gate's own floor).
_MIN_SECRET_CHARS = 8
#: Shapes worth catching even when the value was never registered with us: a
#: platform error text or a third-party log line may carry a token we never saw.
_TOKEN_SHAPE_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})")
_SECRETS = set()      # type: set


def register_secret(value: Any) -> str:
    """Remember a secret value so `redact` can remove it from every later string.

    Called by `Credential.__init__`, so registration cannot be forgotten at a
    call site. Returns the stripped value (empty for a non-secret).
    """
    raw = str(value or "").strip()
    if len(raw) >= _MIN_SECRET_CHARS:
        _SECRETS.add(raw)
        # A token pasted into a URL or a query string is percent-encoded; the
        # encoded form is as sensitive as the raw one.
        _SECRETS.add(quote(raw, safe=""))
    return raw


def forget_secrets() -> None:
    """Drop the registered set (tests, and a long-lived process that rotated the
    credential and must not keep the old value redactable forever)."""
    _SECRETS.clear()


def redact(value: Any) -> str:
    """Return `value` as text with every known secret and every token-shaped
    substring replaced. This is the only way this module turns something into a
    string that can be shown, logged or written to a ledger."""
    text = str(value)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        if secret:
            text = text.replace(secret, REDACTED)
    return _TOKEN_SHAPE_RE.sub(REDACTED, text)


def scrub(value: Any) -> Any:
    """Deep-copy a payload (receipt / ledger row / handoff / exception face) with
    every string and every mapping key redacted. Non-container, non-string values
    pass through unchanged."""
    if isinstance(value, Credential):
        return REDACTED
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {scrub(k) if isinstance(k, str) else k: scrub(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return type(value)(scrub(v) for v in value)
    return value


class PrFlowStop(Exception):
    """One named stop of the PR-flow precondition face.

    Carries `code` (one of the STOP_* names), a redacted human `detail` that says
    WHICH check failed, and the non-secret `path` involved. `str(stop)` and
    `stop.face()` are redacted; the exception is raised once and never retried.
    """

    def __init__(self, code: str, detail: str = "", path: Any = "") -> None:
        self.code = str(code)
        self.detail = redact(detail)
        self.path = redact(path) if path else ""
        super().__init__(self.message())

    def message(self) -> str:
        parts = [self.code]
        if self.path:
            parts.append(str(self.path))
        msg = ": ".join(parts[:2])
        if self.detail:
            msg = "%s (%s)" % (msg, self.detail)
        return redact(msg)

    def face(self) -> Dict[str, Any]:
        """Receipt/ticket-face form. Never carries the secret."""
        out = {"ok": False, "code": self.code, "message": self.message(),
               "detail": self.detail}
        if self.path:
            out["path"] = self.path
        return out


# ---- the declaration read ---------------------------------------------------


def _strip_line(raw: str) -> Optional[str]:
    """Drop a trailing comment and whitespace (this registry's own convention:
    values never contain `#`). A blank/whole-line-comment line yields None."""
    line = re.sub(r"#.*$", "", raw).rstrip()
    return line if line.strip() else None


def projects_root(projects_root: Optional[Any] = None) -> Path:
    """Registry root: explicit argument > $SANDBAR_PROJECTS_DIR > ~/.sandbar/projects.
    Mirrors shared.registry_root instead of importing it (light-import rule)."""
    if projects_root is not None:
        return Path(projects_root)
    env = os.environ.get(PROJECTS_DIR_ENV)
    if env:
        return Path(env)
    return Path.home() / DEFAULT_HOME_DIRNAME / "projects"


def sandbar_home(home: Optional[Any] = None) -> Path:
    """Per-user sandbar home: explicit argument > $SANDBAR_HOME > ~/.sandbar."""
    if home is not None:
        return Path(home)
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env)
    return Path.home() / DEFAULT_HOME_DIRNAME


def credential_path(home: Optional[Any] = None) -> Path:
    """Where the operator's GitHub credential lives: <home>/github/credential."""
    return sandbar_home(home) / CREDENTIAL_DIRNAME / CREDENTIAL_FILENAME


def declaration_path(project_key: str, projects_root_dir: Optional[Any] = None) -> Path:
    """<projects_root>/<key>/project.yaml. A key outside the whitelist is refused
    before the join (it is a path segment; a traversal is not a project)."""
    key = str(project_key or "")
    if not PROJECT_KEY_RE.match(key):
        raise PrFlowStop(
            STOP_DECLARATION_MALFORMED,
            "project key is not a registry key (lowercase letters/digits/hyphens)",
            path=key)
    return projects_root(projects_root_dir) / key / "project.yaml"


@dataclass(frozen=True)
class SwitchDecision:
    """The switch as read from the declaration. Pure data, no secret."""

    enabled: bool
    reason: str                      # "absent" | "off" | "on"
    repositories: Tuple[str, ...] = ()
    declaration: str = ""

    def face(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "reason": self.reason,
                "repositories": list(self.repositories),
                "declaration": redact(self.declaration)}


def _switch_block(lines: List[str], label: str) -> Optional[List[Tuple[int, str]]]:
    """Collect the `github_pr:` block: the top-level opening line plus the
    indented lines under it. Returns None when the block is absent. A duplicate
    block is malformed (two switches cannot decide one delivery mode)."""
    block = None       # type: Optional[List[Tuple[int, str]]]
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = _strip_line(raw)
        if stripped is not None and not raw[:1].isspace() and stripped == SECTION + ":":
            if block is not None:
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "duplicate %s: block" % SECTION, path=label)
            block = []
            i += 1
            while i < len(lines):
                inner_raw = lines[i]
                inner = _strip_line(inner_raw)
                if inner is None:
                    i += 1
                    continue
                if not inner_raw[:1].isspace():
                    break          # the next top-level key closes the block
                block.append((i + 1, inner_raw))
                i += 1
            continue
        i += 1
    return block


def parse_switch(text: str, label: str = "project.yaml") -> SwitchDecision:
    """Judge the `github_pr:` block of one declaration text.

    Truth table: block absent -> OFF (reason "absent"); `enabled` in the false
    word set -> OFF ("off"); in the true word set -> ON ("on", repositories
    required); anything else -- unknown key, unparsable value, duplicate block,
    malformed repository entry, ON without repositories -- is a NAMED stop. An
    unusable switch is never quietly read as "off": that would let a typo pick
    the delivery mode.
    """
    lines = str(text or "").split("\n")
    block = _switch_block(lines, label)
    if block is None:
        return SwitchDecision(enabled=False, reason="absent", declaration=label)

    enabled_raw = None      # type: Optional[str]
    repositories = []       # type: List[str]
    in_repos = False
    for lineno, raw in block:
        content = raw.strip()
        if content.startswith("-"):
            item = content[1:].strip()
            if not in_repos:
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "%s:%d a list item appears outside repositories:"
                                 % (label, lineno), path=label)
            if not REPOSITORY_RE.match(item):
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "%s:%d repository is not owner/name: %r"
                                 % (label, lineno, item), path=label)
            repositories.append(item)
            continue
        m = re.match(r"^([a-z_]+):\s*(.*)$", content)
        if m is None:
            raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                             "%s:%d %s: line is not key: value" % (label, lineno, SECTION),
                             path=label)
        key, value = m.group(1), m.group(2).strip()
        if key == "repositories":
            if value:
                raise PrFlowStop(
                    STOP_DECLARATION_MALFORMED,
                    "%s:%d repositories: must be a block of `- owner/name` entries"
                    % (label, lineno), path=label)
            in_repos = True
            continue
        if key == "enabled":
            if in_repos:
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "%s:%d enabled: appears after repositories:"
                                 % (label, lineno), path=label)
            if enabled_raw is not None:
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "%s:%d duplicate enabled:" % (label, lineno),
                                 path=label)
            enabled_raw = value
            continue
        raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                         "%s:%d unrecognized %s key: %s" % (label, lineno, SECTION, key),
                         path=label)

    if enabled_raw is None:
        raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                         "%s: %s: block without enabled:" % (label, SECTION), path=label)
    word = enabled_raw.lower()
    if word in _FALSE_WORDS:
        return SwitchDecision(enabled=False, reason="off",
                              repositories=tuple(repositories), declaration=label)
    if word not in _TRUE_WORDS:
        raise PrFlowStop(
            STOP_DECLARATION_MALFORMED,
            "%s: %s.enabled is not a boolean (%r); a switch must be readable"
            % (label, SECTION, enabled_raw), path=label)
    if not repositories:
        raise PrFlowStop(
            STOP_SWITCH_REPOSITORIES_MISSING,
            "%s: %s.enabled is on but no repositories are declared (least "
            "privilege needs the declared set)" % (label, SECTION), path=label)
    return SwitchDecision(enabled=True, reason="on",
                          repositories=tuple(repositories), declaration=label)


def read_switch(project_key: str,
                projects_root_dir: Optional[Any] = None) -> SwitchDecision:
    """Read one project's switch. Absent declaration = absent switch = OFF (the
    historical path); an unreadable declaration is a named stop, because "I could
    not read the switch" must not be reported as "the switch is off"."""
    path = declaration_path(project_key, projects_root_dir)
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return SwitchDecision(enabled=False, reason="absent", declaration=str(path))
    except OSError as e:
        raise PrFlowStop(STOP_DECLARATION_UNREADABLE,
                         "declaration read failed: %s" % (e,), path=str(path))
    except UnicodeDecodeError as e:
        raise PrFlowStop(STOP_DECLARATION_UNREADABLE,
                         "declaration is not utf-8: %s" % (e,), path=str(path))
    return parse_switch(text, label=str(path))


# ---- the credential ---------------------------------------------------------


@dataclass(frozen=True)
class Credential:
    """A usable credential. The value is registered for redaction on construction
    and is only reachable through the explicit `reveal()`."""

    #: repr=False is the load-bearing bit: no auto-generated dataclass repr may
    #: ever print the value, and `__str__`/`__repr__` below print the fingerprint.
    secret: str = field(repr=False, default="")
    fingerprint: str = ""

    def __post_init__(self) -> None:
        value = register_secret(self.secret)
        object.__setattr__(self, "secret", value)
        object.__setattr__(self, "fingerprint", _fingerprint(value))

    def reveal(self) -> str:
        """The one explicit way to get the value (only the platform call uses it)."""
        return self.secret

    def __str__(self) -> str:
        return "Credential(fingerprint=%s, secret=%s)" % (self.fingerprint, REDACTED)

    def __repr__(self) -> str:
        return self.__str__()


def _fingerprint(secret: str) -> str:
    """A stable, non-secret label for audit rows: 12 hex chars of sha256."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def inside_worktree(path: Any, project_dirs: Iterable[Any] = ()) -> bool:
    """True when `path` resolves inside a repository worktree: it sits under a
    declared project directory, or one of its ancestors carries `.git` (the
    engine's own layout -- main tree, .lane/<id> worktrees, copies)."""
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    for declared in project_dirs:
        try:
            root = Path(declared).resolve()
        except OSError:
            continue
        if target == root or root in target.parents:
            return True
    for parent in target.parents:
        if (parent / ".git").exists():
            return True
    return False


def probe_github_token(token: str) -> str:
    """The single validity probe of this flow (the only network seam).

    Returns "" when the platform accepts the credential, or a short, secret-free
    rejection reason. Imported lazily so this module never binds an HTTP client
    and no test (and no OFF path) can reach a socket. Step (b) passes this
    function as `probe=`; step (a) never calls it.
    """
    import json          # noqa: PLC0415 - lazy on purpose
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "sandbar-pr-flow"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:   # noqa: S310
            body = resp.read(4096)
        json.loads(body.decode("utf-8", "replace") or "{}")
        return ""
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "platform answered HTTP %d (the credential is not accepted)" % e.code
        return "platform answered HTTP %d" % e.code
    except Exception as e:  # noqa: BLE001 - the caller turns this into a named stop
        raise RuntimeError(redact("%s: %s" % (type(e).__name__, e)))


def resolve_credential(home: Optional[Any] = None,
                       probe: Optional[Callable[[str], str]] = None,
                       project_dirs: Iterable[Any] = ()) -> Credential:
    """Resolve the operator's credential from the per-user sandbar home.

    Order matters: placement is judged before any read (a credential placed inside
    a worktree is never read at all), then existence, permissions, readability,
    then shape. With `probe` injected, the platform's verdict becomes the fourth
    required stop. Every failure raises one `PrFlowStop`; nothing is retried, and
    no failure is reported as "off".
    """
    path = credential_path(home)
    if inside_worktree(path, project_dirs):
        raise PrFlowStop(
            STOP_CREDENTIAL_IN_WORKTREE,
            "the credential resolves inside a repository worktree; it must live "
            "in the per-user sandbar home outside every worktree", path=str(path))
    if not path.is_file():
        raise PrFlowStop(STOP_CREDENTIAL_MISSING,
                         "no credential file for the enabled switch", path=str(path))
    try:
        info = path.stat()
    except OSError as e:
        raise PrFlowStop(STOP_CREDENTIAL_UNREADABLE,
                         "credential stat failed: %s" % (e,), path=str(path))
    mode = stat.S_IMODE(info.st_mode)
    if mode & ~_ALLOWED_MODE_BITS & 0o777:
        raise PrFlowStop(
            STOP_CREDENTIAL_PERMISSIONS,
            "credential mode %04o is readable beyond its owner (allowed: 0600 or "
            "0400); run chmod 600 on it" % mode, path=str(path))
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise PrFlowStop(STOP_CREDENTIAL_UNREADABLE,
                         "credential read failed: %s" % (e,), path=str(path))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PrFlowStop(STOP_CREDENTIAL_UNREADABLE,
                         "credential is not utf-8: %s" % (e,), path=str(path))
    value = text.strip()
    if not value:
        raise PrFlowStop(STOP_CREDENTIAL_EMPTY,
                         "the credential file is readable but holds no value",
                         path=str(path))
    if any(ch.isspace() for ch in value):
        raise PrFlowStop(STOP_CREDENTIAL_MALFORMED,
                         "the credential holds whitespace/newlines (expected one "
                         "token on one line)", path=str(path))
    if len(value) > MAX_CREDENTIAL_CHARS:
        raise PrFlowStop(STOP_CREDENTIAL_MALFORMED,
                         "the credential is %d chars, longer than any token (%d)"
                         % (len(value), MAX_CREDENTIAL_CHARS), path=str(path))
    if len(value) < MIN_CREDENTIAL_CHARS:
        raise PrFlowStop(STOP_CREDENTIAL_SHORT,
                         "the credential is %d chars, shorter than any token (%d): "
                         "a placeholder, not a credential"
                         % (len(value), MIN_CREDENTIAL_CHARS), path=str(path))
    credential = Credential(secret=value)      # registers the value for redaction
    if probe is not None:
        try:
            verdict = probe(credential.reveal())
        except PrFlowStop:
            raise
        except Exception as e:      # noqa: BLE001 - any probe failure is a named stop
            raise PrFlowStop(
                STOP_PROBE_FAILED,
                "the validity probe could not answer (%s: %s); the credential was "
                "not retried" % (type(e).__name__, redact(e)), path=str(path))
        reason = redact(verdict or "").strip()
        if reason:
            raise PrFlowStop(STOP_CREDENTIAL_REJECTED,
                             "the platform rejected the credential: %s" % reason,
                             path=str(path))
    return credential


# ---- the gate consumed by steps (b)-(d) -------------------------------------


@dataclass(frozen=True)
class FlowDecision:
    """The delivery-flow decision for one project.

    `enabled=False` means "use the historical path exactly as today"; the OFF
    decision carries no credential field (an empty fingerprint) so a future edit
    that starts reading the credential while the switch is off shows up as a face
    change in the L1 battery.
    """

    enabled: bool
    reason: str                       # "absent" | "off" | "on"
    repositories: Tuple[str, ...] = ()
    declaration: str = ""
    credential_fingerprint: str = ""

    def face(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "reason": self.reason,
                "repositories": list(self.repositories),
                "declaration": redact(self.declaration),
                "credential_fingerprint": self.credential_fingerprint}


def delivery_decision(project_key: str,
                      projects_root_dir: Optional[Any] = None,
                      home: Optional[Any] = None,
                      probe: Optional[Callable[[str], str]] = None,
                      project_dirs: Iterable[Any] = (),
                      credential_reader: Optional[Callable[..., Credential]] = None,
                      ) -> FlowDecision:
    """The one entry point steps (b)-(d) consult.

    OFF (the default, and every project that never touches the attribute): the
    declaration is the only file read, no credential is resolved, no probe runs,
    nothing is written -- so the historical delivery path is untouched. ON: the
    credential becomes a hard precondition; each failure raises its own named
    `PrFlowStop`.

    `credential_reader` is the injection point the L1 negative control uses: an
    OFF decision must never call it.
    """
    switch = read_switch(project_key, projects_root_dir)
    if not switch.enabled:
        return FlowDecision(enabled=False, reason=switch.reason,
                            repositories=switch.repositories,
                            declaration=switch.declaration)
    reader = credential_reader or resolve_credential
    credential = reader(home=home, probe=probe, project_dirs=project_dirs)
    return FlowDecision(enabled=True, reason="on",
                        repositories=switch.repositories,
                        declaration=switch.declaration,
                        credential_fingerprint=credential.fingerprint)


# ===========================================================================
# STEP (b) - the delivery act, the park, and the platform port
# ===========================================================================
#
# Step (a) above owns the two preconditions (the switch, the credential) and the
# redaction discipline. This half is what consumes them: with the switch ON, a
# delivery that passed the machine gate publishes ONE review request per changed
# repository instead of landing locally, and the ticket parks in the named
# awaiting-remote-review state.
#
# Two stop families, one rule each (do not fold them together):
#   * step (a)'s `STOP_*` codes: a precondition this attempt cannot satisfy. The
#     face raises one and does not retry - the CALLER's retry (a new attempt,
#     `retry_qc`) is what may succeed, after the operator fixes the credential or
#     the declaration.
#   * `DELIVERY_STOP_*` codes below: the delivery act's own named stops. Every one
#     is retry-safe BY CONSTRUCTION: the act always reads the platform state for
#     (repository, branch) before it writes, so a retry rewrites the request a
#     previous attempt created instead of opening a second one.
# A receipt may carry either family's code in its `stop` field; the ticket face
# and the blocked text name it the same way.

#: Replay gate for the workflow side: a history recorded before this marker
#: replays the old merge-gate command sequence, unchanged.
PR_FLOW_DELIVERY_PATCH_ID = "dev-lane-pr-flow-delivery-v1"

#: The named waiting state. A ticket in it holds no working slot (the release
#: cause is `remote-review-wait`) and leaves it only through the poller.
AWAITING_REMOTE_REVIEW = "awaiting-remote-review"
#: The named state a ticket enters when the poller wakes it: the park is LEFT
#: (only the poller may do that). What the platform reported - merged, a comment
#: round, still open - is step (c)'s judgement, so this step records the wake and
#: re-parks the ticket.
REMOTE_REVIEW_WAKE = "remote-review-wake"
#: The one channel that may leave the waiting state.
POLLER_SOURCE = "poller"
#: The target branch of the delivered branch (the branch a person merges into).
DEFAULT_TARGET_BRANCH = "main"

#: The delivery act's three outcomes.
ACTION_LOCAL_LANDING = "local_landing"    # the switch is off: today's path
ACTION_REQUESTS_OPEN = "requests_open"    # the switch is on: requests published
ACTION_STOP = "stop"                      # a named, retry-safe stop

# ---- the delivery act's named stops ----------------------------------------

DELIVERY_STOP_CHANGE_SET_UNREADABLE = "github_pr_delivery_change_set_unreadable"
DELIVERY_STOP_NO_CHANGED_REPOSITORY = "github_pr_delivery_no_changed_repository"
DELIVERY_STOP_NO_EVIDENCE = "github_pr_delivery_no_evidence_record"
DELIVERY_STOP_GATE_NOT_GREEN = "github_pr_delivery_gate_not_green"
DELIVERY_STOP_REPOSITORY_UNIDENTIFIED = "github_pr_delivery_repository_unidentified"
DELIVERY_STOP_REPOSITORY_NOT_DECLARED = "github_pr_delivery_repository_not_declared"
DELIVERY_STOP_PLATFORM_UNREACHABLE = "github_pr_delivery_platform_unreachable"
DELIVERY_STOP_PLATFORM_REFUSED = "github_pr_delivery_platform_refused"
DELIVERY_STOP_PLATFORM_AMBIGUOUS = "github_pr_delivery_platform_ambiguous"

#: code -> what the stop means, in one line. Every entry is retry-safe (see the
#: section comment): a retry re-reads the platform before it writes.
DELIVERY_STOP_TABLE = {
    DELIVERY_STOP_CHANGE_SET_UNREADABLE:
        "the lane's per-repository change set could not be read",
    DELIVERY_STOP_NO_CHANGED_REPOSITORY:
        "the ticket changed no repository that could carry a request",
    DELIVERY_STOP_NO_EVIDENCE:
        "no machine gate row is recorded on the ticket face",
    DELIVERY_STOP_GATE_NOT_GREEN:
        "a recorded machine gate row is not green",
    DELIVERY_STOP_REPOSITORY_UNIDENTIFIED:
        "a changed repository has no platform identity (no GitHub remote)",
    DELIVERY_STOP_REPOSITORY_NOT_DECLARED:
        "a changed repository is not in the project's declared repository set",
    DELIVERY_STOP_PLATFORM_UNREACHABLE:
        "the platform could not be reached",
    DELIVERY_STOP_PLATFORM_REFUSED:
        "the platform refused the branch publish or the request",
    DELIVERY_STOP_PLATFORM_AMBIGUOUS:
        "the platform answer was ambiguous (a request may or may not exist)",
}

#: code -> the remedy a reader can act on (one line, no jargon).
DELIVERY_STOP_REMEDY = {
    DELIVERY_STOP_CHANGE_SET_UNREADABLE:
        "repair the lane (its per-repository manifest is corrupt), then retry",
    DELIVERY_STOP_NO_CHANGED_REPOSITORY:
        "the review-request flow needs at least one changed repository; nothing "
        "was published - land through the ordinary path or fix the change set",
    DELIVERY_STOP_NO_EVIDENCE:
        "the request would claim review readiness without evidence; re-run the "
        "machine gate so its rows are recorded, then retry",
    DELIVERY_STOP_GATE_NOT_GREEN:
        "the flow starts where the machine gate ends; re-run the gate, then retry",
    DELIVERY_STOP_REPOSITORY_UNIDENTIFIED:
        "give the repository a GitHub origin remote (owner/name), then retry",
    DELIVERY_STOP_REPOSITORY_NOT_DECLARED:
        "declare the repository in the project declaration's github_pr "
        "repositories list (least privilege), then retry",
    DELIVERY_STOP_PLATFORM_UNREACHABLE:
        "retry when the platform is reachable - a retry re-reads first, so "
        "nothing is duplicated",
    DELIVERY_STOP_PLATFORM_REFUSED:
        "read the named reason, fix it, then retry (a retry rewrites the existing "
        "request instead of opening a second)",
    DELIVERY_STOP_PLATFORM_AMBIGUOUS:
        "retry - the act re-reads the platform first and rewrites the existing "
        "request instead of opening a second",
}

#: Step (a) stop families get their own remedy line (a reader must never see
#: "no remedy recorded" for the two preconditions the design names).
_PRECONDITION_REMEDY = (
    ("github_pr_credential_",
     "fix the operator credential (<sandbar home>/github/credential, one token, "
     "mode 0600) - nothing was published"),
    ("github_pr_declaration_",
     "fix the project declaration's github_pr: block (enabled + repositories) - "
     "nothing was published"),
    ("github_pr_switch_",
     "declare at least one repository in the project declaration's github_pr "
     "block - nothing was published"),
)


def is_delivery_stop(code: Any) -> bool:
    """True for every stop the delivery act raises (retry-safe by construction)."""
    return str(code or "") in DELIVERY_STOP_TABLE


def stop_remedy(code: Any) -> str:
    """The remedy line for any stop code this module can report."""
    name = str(code or "")
    if name in DELIVERY_STOP_REMEDY:
        return DELIVERY_STOP_REMEDY[name]
    for prefix, text in _PRECONDITION_REMEDY:
        if name.startswith(prefix):
            return text
    return "retry after the named condition is removed"


# ---- the per-repository change set ----------------------------------------

def changed_scopes(scopes: Any) -> List[Dict[str, Any]]:
    """The repositories the ticket actually changed, in the lane's declared order.

    Accepts the engine's per-repository change-set knowledge (the lane's
    `repo_worktrees` details / the lane manifest, as `_lane_scopes` normalizes
    it) and keeps the entries whose `changed` flag is true. A malformed entry is
    dropped (an entry without a repo or a branch cannot carry a request); the
    caller's derivation already refuses a corrupt manifest by name.
    """
    if not isinstance(scopes, (list, tuple)):
        return []
    out: List[Dict[str, Any]] = []
    for raw in scopes:
        if not isinstance(raw, dict):
            continue
        if not isinstance(raw.get("repo"), str):
            continue
        branch = raw.get("branch")
        if not (isinstance(branch, str) and branch.strip()):
            continue
        if not _truthy(raw.get("changed")):
            continue
        out.append({
            "repo": str(raw.get("repo") or ""),
            "name": str(raw.get("name") or raw.get("repo") or "root"),
            "branch": str(branch).strip(),
            "tree": str(raw.get("tree") or ""),
            "remote": str(raw.get("remote") or ""),
            "identity": str(raw.get("identity") or ""),
            "changed": True,
        })
    return out


def _truthy(value: Any) -> bool:
    """A receipt flag: True / a non-empty string that is not a false word."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in ("", "0", "false", "no", "off", "none")


_REMOTE_SSH_RE = re.compile(r"^[\w.-]+@github\.com:(?P<path>.+)$")
_REMOTE_URL_RE = re.compile(r"^(?:https?|ssh)://(?:[^@/]+@)?github\.com[:/](?P<path>.+)$")


def parse_repo_identity(remote: Any) -> str:
    """Parse a git remote URL into `owner/name`. Pure.

    Accepted shapes: https://github.com/o/n(.git), git@github.com:o/n(.git),
    ssh://git@github.com/o/n(.git), with or without a trailing slash. Anything
    else returns "" - the caller turns that into a named stop (a repository with
    no platform identity cannot get a request).
    """
    text = str(remote or "").strip().rstrip("/")
    if not text:
        return ""
    if text.endswith(".git"):
        text = text[:-4]
    m = _REMOTE_SSH_RE.match(text) or _REMOTE_URL_RE.match(text)
    if not m:
        return ""
    parts = [p for p in m.group("path").strip("/").split("/") if p]
    if len(parts) < 2:
        return ""
    return "%s/%s" % (parts[0], parts[1])


def bind_declared_identities(scopes: List[Dict[str, Any]], declared: Iterable[Any],
                             ) -> Tuple[List[Dict[str, Any]], str, str]:
    """Bind each changed repository to a DECLARED platform identity.

    Returns (bound, stop_code, detail). Least privilege: a request is only opened
    on a repository the project declaration names, so an identity outside that
    set - and a repository with no identity at all - is a named stop, never a
    guess and never a silent skip (a skipped repository would silently narrow
    what a person reviews).
    """
    wanted = tuple(str(x) for x in (declared or ()) if str(x).strip())
    bound: List[Dict[str, Any]] = []
    for scope in scopes:
        identity = str(scope.get("identity") or "") or parse_repo_identity(
            scope.get("remote"))
        if not identity:
            return ([], DELIVERY_STOP_REPOSITORY_UNIDENTIFIED,
                    "repository %r has no GitHub identity (remote %r): declare a "
                    "GitHub origin remote before a request can be opened"
                    % (scope.get("name") or scope.get("repo") or "?",
                       scope.get("remote") or ""))
        if identity not in wanted:
            return ([], DELIVERY_STOP_REPOSITORY_NOT_DECLARED,
                    "repository %r maps to %s, which is not in the project "
                    "declaration's github_pr repositories (%s)"
                    % (scope.get("name") or scope.get("repo") or "?", identity,
                       ", ".join(wanted) or "(none declared)"))
        bound.append(dict(scope, identity=identity))
    return bound, "", ""


# ---- the request body (pure text, no IO) ----------------------------------

TITLE_LIMIT = 240


def request_title(ticket_id: str, title: str) -> str:
    """The request title: the ticket id first, then the ticket title. A reviewer
    who sees only the list must be able to tell which ticket it belongs to."""
    text = "[%s] %s" % (ticket_id or "?", str(title or "").strip())
    if len(text) > TITLE_LIMIT:
        text = text[:TITLE_LIMIT - 3].rstrip() + "..."
    return text


def gate_lines(gate_rows: Any) -> Tuple[List[str], str]:
    """Normalize the recorded machine gate rows into reviewer-readable lines.

    Returns (lines, stop_code). A row that is explicitly not green is a named
    stop (the flow starts where the machine gate ends); a row without any verdict
    word is skipped - it is evidence of nothing.
    """
    lines: List[str] = []
    if not isinstance(gate_rows, (list, tuple)):
        return lines, ""
    for raw in gate_rows:
        if not isinstance(raw, dict):
            continue
        verdict = raw.get("green")
        name = str(raw.get("gate") or raw.get("check_id") or "merge_check").strip()
        item = str(raw.get("item") or "").strip()
        if verdict is False:
            return lines, DELIVERY_STOP_GATE_NOT_GREEN
        if verdict is None:
            continue
        if not _truthy(verdict):
            continue
        lines.append("- `%s` - %s" % (name, item or "(recorded green)"))
    return lines, ""


def build_request_body(*, ticket_id: str, title: str, project: str,
                       repo: str, identity: str, branch: str, target_branch: str,
                       gate_items: Iterable[Any], evidence: Iterable[Any],
                       ticket_pointer: str) -> Dict[str, str]:
    """Build one repository's review request. Pure: same inputs, same text.

    The body must stand on its own for a reviewer who never saw this console:
    which ticket, which repository, what the machine gates verified, where that
    evidence lives, and how to get back to the ticket.
    """
    gates = [str(x) for x in (gate_items or []) if str(x).strip()]
    ev = [str(x) for x in (evidence or []) if str(x).strip()]
    lines: List[str] = [
        "## Ticket",
        "",
        "- Ticket: `%s`" % (ticket_id or "?"),
        "- Title: %s" % (str(title or "").strip() or "(no title recorded)"),
        "- Project: `%s`" % (project or "?"),
        "- Repository: %s (%s)" % (repo or "(the project root repository)",
                                   identity or "identity not recorded"),
        "- Branch: `%s` -> `%s`" % (branch or "?", target_branch or DEFAULT_TARGET_BRANCH),
        "",
        "## Machine gates that passed",
        "",
    ]
    lines.extend(gates or ["- (no machine gate row was recorded)"])
    lines.extend(["", "## Evidence", ""])
    lines.extend(["- %s" % e for e in ev] or ["- (no evidence pointer was recorded)"])
    lines.extend([
        "",
        "## Where this came from",
        "",
        str(ticket_pointer or "-").strip() or "-",
        "",
        "---",
        "",
        "Opened by the engine for the ticket above, after its machine gate went "
        "green. One request per branch: re-running the delivery act rewrites this "
        "request in place instead of opening a second one. The merge of this "
        "request is the acceptance record for the ticket.",
    ])
    return {"title": request_title(ticket_id, title), "body": "\n".join(lines)}


# ---- the platform port ----------------------------------------------------

#: The port contract (a fake in a test is a handful of lines):
#:   find_request(scope)                -> {"status": "absent"|"found"|"ambiguous",
#:                                          "number": int, "url": str, "detail": str}
#:   ensure_branch(scope)               -> {"status": "present"|"pushed"|"refused"
#:                                          |"ambiguous", "detail": str}
#:   create_request(scope, title, body) -> {"status": "created"|"refused"|"ambiguous",
#:                                          "number": int, "url": str, "detail": str}
#:   update_request(scope, number, title, body)
#:                                      -> {"status": "updated"|"refused"|"ambiguous",
#:                                          "url": str, "detail": str}
#: An implementation may raise `PrFlowStop(code=DELIVERY_STOP_*)` instead of
#: returning the matching status; every detail it raises is redacted by
#: construction (PrFlowStop redacts).

def _port_call(what: str, fn: Callable[..., Any], *args, **kwargs) -> Dict[str, Any]:
    """Call one port method and translate every abnormal answer into a named stop.

    An unclassified exception becomes the AMBIGUOUS face - the engine does not
    know whether the write landed - never "unreachable", which would invite a
    blind retry that could duplicate a request.
    """
    try:
        out = fn(*args, **kwargs)
    except PrFlowStop:
        raise
    except Exception as e:  # noqa: BLE001 - an unclassified client fault is ambiguous
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         "%s raised %s: %s" % (what, type(e).__name__, e))
    if not isinstance(out, dict):
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         "%s returned %r instead of a receipt"
                         % (what, type(out).__name__))
    return out


def _request_number(value: Any) -> int:
    """A request number, or 0 when the platform did not give a usable one."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


# ---- the delivery act -----------------------------------------------------

@dataclass
class DeliveryVerdict:
    """The delivery act's answer.

    `requests` carries every request the act could confirm - including the ones
    published before a later repository stopped - so the ticket face never loses
    an already published request.
    """
    action: str = ACTION_LOCAL_LANDING
    switch: str = "off"
    switch_detail: str = ""
    stop: str = ""
    detail: str = ""
    retryable: bool = False
    requests: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """The activity receipt. Scrubbed: no secret can ride out on it."""
        return scrub({
            "action": self.action,
            "switch": self.switch,
            "switch_detail": self.switch_detail,
            "stop": self.stop,
            "detail": self.detail,
            "retryable": bool(self.retryable),
            "requests": [dict(r) for r in self.requests],
        })


def verdict_from(raw: Any) -> DeliveryVerdict:
    """Decode an activity receipt.

    A receipt that carries no action at all is read as "this act has no verdict"
    (the caller falls through to the ordinary merge gate). A receipt that carries
    an action this engine does not know is refused by the caller.
    """
    if isinstance(raw, DeliveryVerdict):
        return raw
    if not isinstance(raw, dict):
        return DeliveryVerdict(action="")
    return DeliveryVerdict(
        action=str(raw.get("action") or ""),
        switch=str(raw.get("switch") or ""),
        switch_detail=str(raw.get("switch_detail") or ""),
        stop=str(raw.get("stop") or ""),
        detail=str(raw.get("detail") or ""),
        retryable=bool(raw.get("retryable")),
        requests=[dict(r) for r in (raw.get("requests") or []) if isinstance(r, dict)])


def stop_verdict(code: Any, detail: Any = "", requests: Iterable[Any] = (),
                 switch: str = "on") -> DeliveryVerdict:
    """A named-stop receipt (either stop family; always retry-safe)."""
    return DeliveryVerdict(action=ACTION_STOP, switch=switch, stop=redact(code),
                           detail=redact(detail), retryable=True,
                           requests=[dict(r) for r in (requests or ())])


def stop_text(verdict: DeliveryVerdict, ticket_id: str = "") -> str:
    """The blocked text for a named stop: which stop, what happened, the remedy,
    and the duplicate-safety promise (a reader must not fear a retry)."""
    kind = verdict.stop or "unnamed"
    return ("review-request delivery stopped (%s%s): %s%s | remedy: %s | a retry "
            "re-reads the platform before it writes, so no second request is opened"
            % (kind, (", ticket " + str(ticket_id)) if ticket_id else "",
               verdict.detail or "no detail recorded",
               (" | already published: %d request(s)" % len(verdict.requests))
               if verdict.requests else "",
               stop_remedy(kind)))


def run_delivery(payload: Any, switch: Any = None, *,
                 platform_factory: Optional[Callable[[], Any]] = None,
                 scope_provider: Optional[Callable[[], Dict[str, Any]]] = None,
                 ) -> DeliveryVerdict:
    """The delivery act (design step (b)).

    `switch` is step (a)'s decision (`SwitchDecision` / `FlowDecision`: enabled +
    repositories). OFF - including "no switch read at all" - answers "land
    locally" and touches nothing else (no change set, no credential, no network).

    payload keys (all read defensively): ticket_id, title, project, branch,
    base_ref, target_branch, gate_rows (the machine gate rows recorded on the
    ticket face), evidence (where the evidence lives), ticket_pointer (how a
    reviewer gets back to the ticket), scopes (or `scope_provider`).

    Order matters: switch -> change set -> declared identities -> evidence ->
    credential/platform -> publish. A stop therefore never asks for a credential
    when there is nothing to publish.
    """
    args = payload if isinstance(payload, dict) else {}
    if not bool(getattr(switch, "enabled", False)):
        return DeliveryVerdict(
            action=ACTION_LOCAL_LANDING,
            switch=str(getattr(switch, "reason", "") or "absent"),
            switch_detail=str(getattr(switch, "declaration", "") or ""))
    declared = tuple(getattr(switch, "repositories", ()) or ())

    if scope_provider is not None:
        try:
            derived = scope_provider()
        except Exception as e:  # noqa: BLE001 - an unreadable lane is a named stop
            return stop_verdict(DELIVERY_STOP_CHANGE_SET_UNREADABLE,
                                "change set derivation raised %s: %s"
                                % (type(e).__name__, e))
        if not isinstance(derived, dict):
            return stop_verdict(DELIVERY_STOP_CHANGE_SET_UNREADABLE,
                                "change set derivation returned %r"
                                % type(derived).__name__)
        if derived.get("error"):
            return stop_verdict(DELIVERY_STOP_CHANGE_SET_UNREADABLE,
                                str(derived.get("error")))
        scopes = derived.get("scopes")
    else:
        scopes = args.get("scopes")

    repos = changed_scopes(scopes)
    if not repos:
        return stop_verdict(DELIVERY_STOP_NO_CHANGED_REPOSITORY,
                            "the ticket changed none of its declared repositories")

    gates, gate_stop = gate_lines(args.get("gate_rows"))
    if gate_stop:
        return stop_verdict(gate_stop, "a recorded machine gate row is not green")
    if not gates:
        return stop_verdict(DELIVERY_STOP_NO_EVIDENCE,
                            "no green machine gate row is recorded on the ticket face")

    bound, bind_stop, bind_detail = bind_declared_identities(repos, declared)
    if bind_stop:
        return stop_verdict(bind_stop, bind_detail)

    try:
        platform = platform_factory() if platform_factory is not None else None
    except PrFlowStop as e:
        return stop_verdict(e.code, e.message())
    except Exception as e:  # noqa: BLE001
        return stop_verdict(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                            "the platform client could not be built: %s: %s"
                            % (type(e).__name__, e))
    if platform is None:
        return stop_verdict(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                            "no platform client is configured for this engine")

    done: List[Dict[str, Any]] = []
    for scope in bound:
        try:
            record = _publish_one(
                platform, scope=scope,
                ticket_id=str(args.get("ticket_id") or ""),
                title=str(args.get("title") or ""),
                project=str(args.get("project") or ""),
                target=str(args.get("target_branch") or DEFAULT_TARGET_BRANCH),
                gates=gates,
                evidence=[str(x) for x in (args.get("evidence") or [])
                          if str(x).strip()],
                pointer=str(args.get("ticket_pointer") or ""))
        except PrFlowStop as e:
            return stop_verdict(e.code, "%s (%s)" % (e.message(),
                                                    scope.get("name") or "?"),
                                requests=done)
        done.append(record)
    return DeliveryVerdict(action=ACTION_REQUESTS_OPEN, switch="on", requests=done)


def _publish_one(platform: Any, *, scope: Dict[str, Any], ticket_id: str,
                 title: str, project: str, target: str, gates: Iterable[Any],
                 evidence: Iterable[Any], pointer: str) -> Dict[str, Any]:
    """One request for one repository, idempotent by branch.

    Read first, write second. `found` rewrites the existing request; `absent`
    publishes the branch and then creates; `ambiguous` is a named stop - never a
    blind create, which is exactly how a duplicate would be born.
    """
    repo = scope.get("repo") or ""
    branch = scope.get("branch") or ""
    body = build_request_body(ticket_id=ticket_id, title=title, project=project,
                              repo=repo, identity=scope.get("identity") or "",
                              branch=branch, target_branch=target,
                              gate_items=gates, evidence=evidence,
                              ticket_pointer=pointer)
    found = _port_call("find_request", platform.find_request, scope)
    status = str(found.get("status") or "")
    if status == "ambiguous":
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         found.get("detail") or
                         "the platform answer for the branch lookup is ambiguous")
    if status not in ("absent", "found"):
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         "unrecognised lookup status %r for repository %s"
                         % (status, repo or "?"))
    number = _request_number(found.get("number"))
    if status == "found":
        if not number:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                             "an existing request was reported without a number - "
                             "it cannot be rewritten")
        updated = _port_call("update_request", platform.update_request, scope,
                             number, body["title"], body["body"])
        return _record(scope, "updated", number,
                       str(updated.get("url") or found.get("url") or ""))
    pushed = _port_call("ensure_branch", platform.ensure_branch, scope)
    pstatus = str(pushed.get("status") or "")
    if pstatus == "ambiguous":
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         pushed.get("detail") or
                         "the branch publish answer is ambiguous")
    if pstatus not in ("present", "pushed"):
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_REFUSED,
                         "the branch could not be published: %s"
                         % (pushed.get("detail") or pstatus or "?"))
    created = _port_call("create_request", platform.create_request, scope,
                         body["title"], body["body"])
    cstatus = str(created.get("status") or "")
    if cstatus == "refused":
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_REFUSED,
                         created.get("detail") or "the platform refused the create")
    if cstatus != "created":
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         created.get("detail") or
                         "unrecognised create status %r (the request may exist)"
                         % cstatus)
    cnum = _request_number(created.get("number"))
    if not cnum:
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         "the platform answered 'created' without a request number "
                         "- a retry must not open a second one")
    return _record(scope, "created", cnum, str(created.get("url") or ""))


def _record(scope: Dict[str, Any], action: str, number: int, url: str) -> Dict[str, Any]:
    return {"repo": scope.get("repo") or "",
            "name": scope.get("name") or "",
            "identity": scope.get("identity") or "",
            "branch": scope.get("branch") or "",
            "number": int(number),
            "url": redact(url),
            "action": action}


# ---- the waiting state ----------------------------------------------------

def awaiting_record(verdict: DeliveryVerdict, *, ticket_id: str, project: str,
                    at_iso: str) -> Dict[str, Any]:
    """The ticket-face record of the park: which request belongs to which
    repository, and the only channel that may leave the state."""
    return scrub({
        "state": AWAITING_REMOTE_REVIEW,
        "ticket": str(ticket_id or ""),
        "project": str(project or ""),
        "entered_at": str(at_iso or ""),
        "exit_channel": POLLER_SOURCE,
        "requests": [dict(r) for r in verdict.requests],
    })


@dataclass
class ExitVerdict:
    """The park's exit judgement: accepted (the poller) or refused by name."""
    accepted: bool = False
    source: str = ""
    reason: str = ""
    record: Dict[str, Any] = field(default_factory=dict)


def remote_review_exit(payload: Any) -> ExitVerdict:
    """Judge which channel may leave the awaiting-remote-review state.

    Only the poller (step (c)) may. A signature, an advance, an empty or
    malformed payload are each refused BY NAME and the ticket stays parked: a
    delivery whose acceptance record is the platform merge must never leave
    through a local act. The accepted payload is recorded as a fact; what it
    MEANS (merged / comment round / still open) is step (c)'s judgement and is
    deliberately not made here.
    """
    if not isinstance(payload, dict):
        reason = ("the wake payload is %r, not an object carrying a source: only "
                  "the poller may wake an awaiting-remote-review ticket"
                  % type(payload).__name__)
        return ExitVerdict(accepted=False, source="", reason=reason,
                           record=scrub({"accepted": False, "source": "",
                                         "reason": reason,
                                         "payload": repr(payload)[:200]}))
    src = str(payload.get("source") or "").strip().lower()
    if src != POLLER_SOURCE:
        reason = ("wake source %r is not the poller: an awaiting-remote-review "
                  "ticket leaves its park only through the poller (step (c)); no "
                  "local act is an acceptance record" % (src or "(absent)"))
        return ExitVerdict(accepted=False, source=src, reason=reason,
                           record=scrub({"accepted": False, "source": src,
                                         "reason": reason,
                                         "note": str(payload.get("note") or "")[:300]}))
    return ExitVerdict(accepted=True, source=src, reason="",
                       record=scrub({"accepted": True, "source": src,
                                     "note": str(payload.get("note") or "")[:300],
                                     "reported": _plain(payload.get("reported"))}))


def _plain(value: Any) -> Any:
    """A JSON-safe copy of a platform answer (never a live object, never a
    secret: the caller passes only what it wants recorded)."""
    import json as _json  # noqa: PLC0415 - local on purpose (module scope stays bare)
    try:
        return scrub(_json.loads(_json.dumps(value, ensure_ascii=False, default=str)))
    except Exception:  # noqa: BLE001
        return redact(value)[:400]


# ---- GitHub: the platform port implementation -----------------------------

GITHUB_API_BASE = "https://api.github.com"
GITHUB_WEB_BASE = "https://github.com"


def _default_transport(method: str, url: str, headers: Dict[str, str],
                       body: Optional[bytes], timeout: float,
                       ) -> Tuple[int, Dict[str, str], bytes]:
    """The real HTTP transport. Imported lazily so this module binds no HTTP
    client at module scope (the same light-import rule step (a) follows: the OFF
    path must never be able to reach a socket, even by accident)."""
    import json as _json            # noqa: PLC0415 - local on purpose
    import urllib.error as _urlerr  # noqa: PLC0415
    import urllib.request as _urlreq  # noqa: PLC0415
    del _json
    req = _urlreq.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:   # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except _urlerr.HTTPError as e:
        return int(e.code), dict(getattr(e, "headers", {}) or {}), e.read() or b""
    except _urlerr.URLError as e:
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                         "the platform could not be reached: %s"
                         % (getattr(e, "reason", e),))
    except OSError as e:
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                         "the platform could not be reached: %s" % (e,))


def _default_git_runner(argv: List[str], env: Dict[str, str],
                        timeout: float) -> Tuple[int, str]:
    """The real git runner for the branch publish (lazy import, same rule)."""
    import subprocess  # noqa: PLC0415 - local on purpose
    proc = subprocess.run(argv, capture_output=True, text=True, env=env,
                          timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class GitHubPlatform:
    """GitHub as the platform port. Every external effect is injected: `transport`
    (HTTP) and `git_runner` (branch publish). The token reaches git through the
    environment (`GIT_CONFIG_*` entries), never through argv, so it does not show
    up in a process listing; every failure string goes through `redact`.
    """

    def __init__(self, *, token: str, api_base: str = GITHUB_API_BASE,
                 transport: Optional[Callable[..., Tuple[int, Dict[str, str], bytes]]] = None,
                 git_runner: Optional[Callable[..., Tuple[int, str]]] = None,
                 timeout: float = 20.0, git_timeout: float = 180.0,
                 publish_remote: str = "origin") -> None:
        if not str(token or "").strip():
            raise PrFlowStop(STOP_CREDENTIAL_EMPTY,
                             "an empty value is not a credential")
        register_secret(token)
        self._token = str(token)
        self._api = str(api_base or GITHUB_API_BASE).rstrip("/")
        self._transport = transport or _default_transport
        self._git = git_runner or _default_git_runner
        self._timeout = float(timeout)
        self._git_timeout = float(git_timeout)
        self._remote = publish_remote or "origin"

    def __repr__(self) -> str:
        return "GitHubPlatform(api=%s, token=%s)" % (redact(self._api), REDACTED)

    __str__ = __repr__

    # ---- HTTP ----
    def _call(self, method: str, path: str,
              body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        import json as _json            # noqa: PLC0415 - local on purpose
        url = self._api + path
        payload = None if body is None else _json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self._token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sandbar-engine",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        status, _hdrs, raw = self._transport(method, url, headers, payload,
                                             self._timeout)
        try:
            decoded = _json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            decoded = {}
        return int(status), decoded

    @staticmethod
    def _message(payload: Any) -> str:
        if isinstance(payload, dict):
            msg = payload.get("message") or ""
            errs = payload.get("errors")
            if errs:
                text = "%s (%s)" % (msg, errs)
                return redact(text)[:300]
            return redact(msg)[:300]
        return redact(payload)[:200]

    def _raise_for_status(self, status: int, payload: Any, what: str) -> None:
        """Map one status onto one named stop. 401 is the credential; 403/404/422
        are a platform refusal; 429/5xx are unreachable; anything else is
        ambiguous (the engine does not know what happened)."""
        if status in (200, 201, 204):
            return
        if status == 401:
            raise PrFlowStop(STOP_CREDENTIAL_REJECTED,
                             "the platform refused the credential (401) on %s: %s"
                             % (what, self._message(payload)))
        if status in (403, 404, 410, 422):
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_REFUSED,
                             "the platform refused %s (%d): %s"
                             % (what, status, self._message(payload)))
        if status == 429 or status >= 500:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                             "the platform could not serve %s (%d): %s"
                             % (what, status, self._message(payload)))
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         "unexpected platform status %d on %s: %s"
                         % (status, what, self._message(payload)))

    @staticmethod
    def _identity(scope: Dict[str, Any]) -> str:
        ident = str(scope.get("identity") or "") or parse_repo_identity(
            scope.get("remote"))
        if not ident:
            raise PrFlowStop(DELIVERY_STOP_REPOSITORY_UNIDENTIFIED,
                             "repository %r has no GitHub identity (remote %r)"
                             % (scope.get("repo") or "", scope.get("remote") or ""))
        return ident

    # ---- the port ----
    def find_request(self, scope: Dict[str, Any]) -> Dict[str, Any]:
        ident = self._identity(scope)
        head = "%s:%s" % (ident.split("/")[0], scope.get("branch") or "")
        query = "state=open&head=%s" % quote(head, safe="")
        status, payload = self._call("GET", "/repos/%s/pulls?%s" % (ident, query))
        self._raise_for_status(status, payload, "the branch lookup")
        if not isinstance(payload, list):
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                             "the branch lookup answered %r, not a list"
                             % type(payload).__name__)
        numbers = [n for n in (_request_number(p.get("number"))
                               for p in payload if isinstance(p, dict)) if n]
        if not numbers:
            return {"status": "absent", "number": 0, "url": "", "detail": ""}
        if len(numbers) > 1:
            return {"status": "ambiguous", "number": 0, "url": "",
                    "detail": ("the platform reports %d open requests for branch "
                               "%s (%s) - one request per branch is the rule, so a "
                               "human resolves this"
                               % (len(numbers), scope.get("branch") or "",
                                  ", ".join("#%d" % n for n in numbers)))}
        url = ""
        for p in payload:
            if isinstance(p, dict) and _request_number(p.get("number")) == numbers[0]:
                url = str(p.get("html_url") or "")
                break
        return {"status": "found", "number": numbers[0], "url": url, "detail": ""}

    def create_request(self, scope: Dict[str, Any], title: str,
                       body: str) -> Dict[str, Any]:
        ident = self._identity(scope)
        status, payload = self._call("POST", "/repos/%s/pulls" % ident, {
            "title": title,
            "body": body,
            "head": scope.get("branch") or "",
            "base": scope.get("target_branch") or DEFAULT_TARGET_BRANCH,
        })
        self._raise_for_status(status, payload, "the request create")
        number = _request_number((payload or {}).get("number")
                                 if isinstance(payload, dict) else 0)
        if not number:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                             "the create answered %d without a request number: %s"
                             % (status, self._message(payload)))
        return {"status": "created", "number": number,
                "url": str((payload or {}).get("html_url") or ""), "detail": ""}

    def update_request(self, scope: Dict[str, Any], number: int, title: str,
                       body: str) -> Dict[str, Any]:
        ident = self._identity(scope)
        status, payload = self._call("PATCH",
                                     "/repos/%s/pulls/%d" % (ident, int(number)),
                                     {"title": title, "body": body})
        self._raise_for_status(status, payload, "the request rewrite")
        return {"status": "updated", "number": int(number),
                "url": str((payload or {}).get("html_url") or ""), "detail": ""}

    def ensure_branch(self, scope: Dict[str, Any]) -> Dict[str, Any]:
        """Publish the lane branch to the platform: the transport leg of the
        delivery (a request can only exist for a branch the platform has)."""
        import base64 as _base64  # noqa: PLC0415 - local on purpose
        tree = str(scope.get("tree") or "")
        branch = str(scope.get("branch") or "")
        if not tree or not branch:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_REFUSED,
                             "the branch publish needs the lane tree and the branch "
                             "name (tree=%r branch=%r)" % (tree, branch))
        basic = _base64.b64encode(
            ("x-access-token:" + self._token).encode("utf-8")).decode("ascii")
        env = dict(os.environ)
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.%s/.extraheader" % GITHUB_WEB_BASE,
            "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + basic,
            "GIT_TERMINAL_PROMPT": "0",
        })
        argv = ["git", "-C", tree, "push", "--porcelain", self._remote,
                "refs/heads/%s:refs/heads/%s" % (branch, branch)]
        code, out = self._git(argv, env, self._git_timeout)
        text = redact(out)
        low = text.lower()
        if code == 0:
            up_to_date = ("everything up-to-date" in low or "up to date" in low)
            return {"status": "present" if up_to_date else "pushed",
                    "detail": text.strip()[:300]}
        if any(m in low for m in ("authentication failed", "could not read username",
                                  "permission to", " 401", " 403",
                                  "invalid username",
                                  "support for password authentication")):
            raise PrFlowStop(STOP_CREDENTIAL_REJECTED,
                             "the platform refused the credential on the branch "
                             "publish: %s" % text.strip()[:300])
        if any(m in low for m in ("could not resolve host", "connection refused",
                                  "connection timed out", "network is unreachable",
                                  "unable to access", "operation timed out",
                                  "no route to host")):
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                             "the platform could not be reached for the branch "
                             "publish: %s" % text.strip()[:300])
        if code != 0:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_REFUSED,
                             "the branch publish failed (git exit %s): %s"
                             % (code, text.strip()[:300]))
        raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                         "the branch publish answer is ambiguous: %s"
                         % text.strip()[:300])


def platform_from_credential(credential: Any, *,
                             transport: Optional[Callable[..., Any]] = None,
                             git_runner: Optional[Callable[..., Any]] = None,
                             ) -> "GitHubPlatform":
    """Build the live platform from step (a)'s resolved credential. Called by the
    activity only: `Credential.reveal()` is the one explicit way to the value."""
    return GitHubPlatform(token=credential.reveal(), transport=transport,
                          git_runner=git_runner)
