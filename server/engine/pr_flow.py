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
