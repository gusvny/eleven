# -*- coding: utf-8 -*-
"""pr_flow -- the optional GitHub review-request delivery flow.

Design: docs/design/github-pr-flow-v1.md. This module ships all four steps:
(a) the switch and the credential (requirement 1 and 2), (b) the delivery act
that opens one request per changed repository and parks the ticket (3, 4 and 6),
(c) the poll that reads the platform, ends the ticket on a merge and turns a
comment round into rework (4 and 5), and (d) the post-merge reconciliation of the
local target branch (7). A project that does not set the switch keeps today's
behaviour byte for byte: every entry point below answers "not applicable" or
"land locally" before it reads a credential, a branch or a network.

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

6. Reconciliation (step (d)). The platform's merge settles the delivery; it does
   not catch this machine's target branch up. `reconcile_after_merge` is the only
   thing here that touches the local target branch, and the only advance it
   allows is a fast-forward, verified against the content the platform reported
   as merged. A branch that carries other work, a branch whose content differs
   from the reported merge, an unreadable remote and an absent branch are each a
   NAMED stop that leaves the branch alone and hands the decision to a person.
   One module-wide chokepoint (`_git_argv`) builds every git command line, so the
   promise "no path rewrites history, forces an update or discards work" is
   mechanical rather than a comment.

7. The wiring (t261103-13). Step (d) is not optional advice: the step (c)
   close-out asks the act for an answer BEFORE it closes a ticket, and only a
   receipt that says every declared repository reconciled may close. Every other
   answer - the act's named stops, a partial reconciliation, a switch that was
   turned off while the ticket was parked, an unreadable receipt - keeps the
   ticket open with its named reason and remedy on the ticket face. The wiring
   calls the act; it never builds a git command line of its own.

8. Per-project park options (t261103-13). The `github_pr:` block may also carry
   `beat_seconds` (how often the platform is asked) and `wake_entry` (the one
   command an outside poller runs to wake a parked ticket). The values this module
   shipped with are the defaults, so a declaration that names neither behaves
   exactly as before; a value that is present but unusable is a named refusal
   naming its own key.

Light-import discipline: stdlib only, no temporalio, no `shared` import (this face
must stay importable from a bare interpreter, and the registry root is mirrored
from `shared.registry_root` by reading the same env, the way audit.py and
event_ledger.py read their own additive sections).

Tests: server/engine/tests/test_t261004_44_deliver_refusal.py (the delivery
named-refusal carrier), section "PR flow step (a)"; steps (b), (c), (d) and the
close-out wiring are covered in server/engine/tests/test_t261022_merge_slot_release.py
(sections "t261103-05", "t261103-07", "t261103-08" and "t261103-13").
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

# ---- the park's per-project options (t261103-13) ----------------------------
#
# Step (c) left two park values as module constants: how often the platform is
# asked (the beat), and which command an outside poller runs to wake a parked
# ticket (the wake entry). Both are choices a PROJECT makes - one project wants a
# faster beat, another has its own poller entry - so the same declaration block
# may carry them, and the values this module shipped with stay the defaults: a
# declaration that names neither behaves exactly as before. A value that is
# present but unusable is refused by name (never read as "use the default",
# which would decide a project's cadence on a typo).

#: The two declaration keys, inside the `github_pr:` block.
DECLARATION_BEAT_KEY = "beat_seconds"
DECLARATION_WAKE_KEY = "wake_entry"
#: One refusal per key, so the reason a reader sees names the field it must fix.
STOP_DECLARATION_BEAT_INVALID = "github_pr_declaration_beat_invalid"
STOP_DECLARATION_WAKE_INVALID = "github_pr_declaration_wake_invalid"
#: The accepted beat range (seconds): below the floor the platform is hammered,
#: above the ceiling a missed beat costs more than the ticket can wait.
MIN_BEAT_SECONDS = 60
MAX_BEAT_SECONDS = 86400
#: A wake entry is one command line, not a script: bounded so a face stays readable.
MAX_WAKE_ENTRY_CHARS = 400
#: The defaults - the values step (c) shipped with (the beat constant keeps its
#: historical name below; the wake entry is client.py's documented invocation).
DEFAULT_BEAT_SECONDS = 300
DEFAULT_WAKE_ENTRY = ("python3 -c \"import asyncio, client; print(asyncio.run("
                      "client.remote_review_wake('<ticket_id>', '<note>')))\"")

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
    # t261103-13: the park's two per-project options. Each names its own key,
    # because "the declaration is malformed" would not tell a reader which field
    # to fix (an unusable value is never read as "keep the default").
    STOP_DECLARATION_BEAT_INVALID: "the declared beat interval is not usable",
    STOP_DECLARATION_WAKE_INVALID: "the declared wake entry is not usable",
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
class FlowOptions:
    """What a park needs to know about a project's OWN choices.

    Not a secret and not a credential: a beat interval and one command line. The
    defaults are this module's shipped values, so a declaration that declares
    neither answer is the historical answer.
    """

    beat_seconds: int = DEFAULT_BEAT_SECONDS
    wake_entry: str = DEFAULT_WAKE_ENTRY
    source: str = "default"          # "default" | "declaration" | a fallback note

    def face(self) -> Dict[str, Any]:
        return {"beat_seconds": int(self.beat_seconds),
                "wake_entry": redact(str(self.wake_entry)),
                "source": str(self.source)}


@dataclass(frozen=True)
class SwitchDecision:
    """The switch as read from the declaration. Pure data, no secret."""

    enabled: bool
    reason: str                      # "absent" | "off" | "on"
    repositories: Tuple[str, ...] = ()
    declaration: str = ""
    # t261103-13: the park's per-project options. 0 / "" mean "not declared", so
    # `options()` - not this dataclass - is where the defaults are applied (the
    # default values must stay single-sourced).
    beat_seconds: int = 0
    wake_entry: str = ""

    def face(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "reason": self.reason,
                "repositories": list(self.repositories),
                "declaration": redact(self.declaration)}

    def options(self) -> FlowOptions:
        """The park's options, with the shipped values as the defaults."""
        declared = bool(self.beat_seconds) or bool(self.wake_entry)
        return FlowOptions(beat_seconds=self.beat_seconds or DEFAULT_BEAT_SECONDS,
                           wake_entry=self.wake_entry or DEFAULT_WAKE_ENTRY,
                           source="declaration" if declared else "default")


def flow_options(switch: Any) -> FlowOptions:
    """The park's options for whatever decision a caller holds.

    A decision that carries no options (an OFF switch, a decision object from a
    caller that predates this seam) answers the shipped defaults: the park never
    runs without a beat and never runs without a wake entry.
    """
    getter = getattr(switch, "options", None)
    if callable(getter):
        return getter()
    return FlowOptions()


def flow_options_from(raw: Any) -> FlowOptions:
    """The park's options as recorded on the ticket face or on a receipt.

    Absent options mean "a history/receipt recorded before this seam existed":
    that ticket parks on exactly today's beat and wake entry, so absent is the
    default, not a refusal. A value that is present but unusable cannot come from
    a declaration (the read refuses it by name before it reaches here); it falls
    back to the default AND says so in `source`, so a reader can see it happened.
    """
    block = raw if isinstance(raw, Mapping) else {}
    opts = block.get("options")
    if not isinstance(opts, Mapping) or not opts:
        return FlowOptions()
    notes: List[str] = []
    beat = DEFAULT_BEAT_SECONDS
    raw_beat = opts.get("beat_seconds")
    try:
        candidate = int(raw_beat)
    except (TypeError, ValueError):
        candidate = 0
    if MIN_BEAT_SECONDS <= candidate <= MAX_BEAT_SECONDS:
        beat = candidate
    else:
        notes.append("beat %r -> default" % (raw_beat,))
    wake = str(opts.get("wake_entry") or "").strip()
    if not wake or len(wake) > MAX_WAKE_ENTRY_CHARS or _has_control_chars(wake):
        if wake:
            notes.append("wake entry unusable -> default")
        wake = DEFAULT_WAKE_ENTRY
    return FlowOptions(beat_seconds=beat, wake_entry=wake,
                       source=("default(fallback: %s)" % "; ".join(notes)) if notes
                       else "recorded")


def _has_control_chars(text: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in str(text or ""))


def _unquote(value: str) -> str:
    """Strip ONE layer of matching YAML quotes (a value keeps its own text)."""
    text = str(value or "")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


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

    The two park options (t261103-13) are additive and optional: when present,
    `beat_seconds` must be a whole number of seconds inside the accepted range
    and `wake_entry` one non-empty command line. Each refusal names its own key,
    because a reader must not have to guess which field to fix.
    """
    lines = str(text or "").split("\n")
    block = _switch_block(lines, label)
    if block is None:
        return SwitchDecision(enabled=False, reason="absent", declaration=label)

    enabled_raw = None      # type: Optional[str]
    repositories = []       # type: List[str]
    beat_seconds = 0
    wake_entry = ""
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
        if key == DECLARATION_BEAT_KEY:
            if beat_seconds:
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "%s:%d duplicate %s:"
                                 % (label, lineno, DECLARATION_BEAT_KEY), path=label)
            beat_seconds = _beat_seconds_value(value, label=label, lineno=lineno)
            continue
        if key == DECLARATION_WAKE_KEY:
            if wake_entry:
                raise PrFlowStop(STOP_DECLARATION_MALFORMED,
                                 "%s:%d duplicate %s:"
                                 % (label, lineno, DECLARATION_WAKE_KEY), path=label)
            wake_entry = _wake_entry_value(value, label=label, lineno=lineno)
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
                              repositories=tuple(repositories), declaration=label,
                              beat_seconds=beat_seconds, wake_entry=wake_entry)
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
                          repositories=tuple(repositories), declaration=label,
                          beat_seconds=beat_seconds, wake_entry=wake_entry)


def _beat_seconds_value(value: str, *, label: str, lineno: int) -> int:
    """One declared beat -> seconds, or a refusal naming the key and the range."""
    text = _unquote(value)
    if not re.match(r"^\d+$", text):
        raise PrFlowStop(
            STOP_DECLARATION_BEAT_INVALID,
            "%s:%d %s.%s is %r, which is not a whole number of seconds (accepted: "
            "%d..%d)" % (label, lineno, SECTION, DECLARATION_BEAT_KEY, value,
                         MIN_BEAT_SECONDS, MAX_BEAT_SECONDS), path=label)
    seconds = int(text)
    if not MIN_BEAT_SECONDS <= seconds <= MAX_BEAT_SECONDS:
        raise PrFlowStop(
            STOP_DECLARATION_BEAT_INVALID,
            "%s:%d %s.%s is %d seconds, outside the accepted range %d..%d"
            % (label, lineno, SECTION, DECLARATION_BEAT_KEY, seconds,
               MIN_BEAT_SECONDS, MAX_BEAT_SECONDS), path=label)
    return seconds


def _wake_entry_value(value: str, *, label: str, lineno: int) -> str:
    """One declared wake entry -> the command line, or a refusal naming the key."""
    text = _unquote(value).strip()
    if not text:
        raise PrFlowStop(
            STOP_DECLARATION_WAKE_INVALID,
            "%s:%d %s.%s is empty; an empty wake entry cannot wake a parked ticket"
            % (label, lineno, SECTION, DECLARATION_WAKE_KEY), path=label)
    if len(text) > MAX_WAKE_ENTRY_CHARS:
        raise PrFlowStop(
            STOP_DECLARATION_WAKE_INVALID,
            "%s:%d %s.%s is %d characters; a wake entry is one command line, at "
            "most %d characters"
            % (label, lineno, SECTION, DECLARATION_WAKE_KEY, len(text),
               MAX_WAKE_ENTRY_CHARS), path=label)
    if _has_control_chars(text):
        raise PrFlowStop(
            STOP_DECLARATION_WAKE_INVALID,
            "%s:%d %s.%s carries a newline or a control character; a wake entry is "
            "ONE command line" % (label, lineno, SECTION, DECLARATION_WAKE_KEY),
            path=label)
    return text


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

#: The two park-option refusals get their own remedy line: the generic
#: declaration remedy would send a reader to `enabled`/`repositories` when the
#: broken field is the beat or the wake entry (a wrong diagnosis costs more than
#: no diagnosis).
_PARK_OPTION_REMEDY = {
    STOP_DECLARATION_BEAT_INVALID:
        "set github_pr.%s to a whole number of seconds between %d and %d, or remove "
        "the key to keep the default (%d s) - nothing was published"
        % (DECLARATION_BEAT_KEY, MIN_BEAT_SECONDS, MAX_BEAT_SECONDS,
           DEFAULT_BEAT_SECONDS),
    STOP_DECLARATION_WAKE_INVALID:
        "set github_pr.%s to ONE command line of at most %d characters, or remove "
        "the key to keep the default entry - nothing was published"
        % (DECLARATION_WAKE_KEY, MAX_WAKE_ENTRY_CHARS),
}


def is_delivery_stop(code: Any) -> bool:
    """True for every stop the delivery act raises (retry-safe by construction)."""
    return str(code or "") in DELIVERY_STOP_TABLE


def stop_remedy(code: Any) -> str:
    """The remedy line for any stop code this module can report.

    Four families, one entry point: step (c)'s poll stops (defined further down in
    this module), step (b)'s delivery stops, step (d)'s reconciliation stops and
    step (a)'s precondition stops. Every named face of the flow therefore carries a
    remedy a reader can act on.
    """
    name = str(code or "")
    if name in _PARK_OPTION_REMEDY:
        return _PARK_OPTION_REMEDY[name]
    if name in POLL_STOP_REMEDY:
        return POLL_STOP_REMEDY[name]
    if name in DELIVERY_STOP_REMEDY:
        return DELIVERY_STOP_REMEDY[name]
    if name in RECONCILE_STOP_REMEDY:
        return RECONCILE_STOP_REMEDY[name]
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
    # t261103-13: the park's declared options (beat interval, wake entry) ride
    # the delivery receipt, because a workflow may not read a declaration file.
    # Empty means "no options recorded" - the park then uses the shipped defaults.
    options: Dict[str, Any] = field(default_factory=dict)

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
            "options": dict(self.options),
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
        requests=[dict(r) for r in (raw.get("requests") or []) if isinstance(r, dict)],
        options=dict(raw.get("options") or {})
        if isinstance(raw.get("options"), Mapping) else {})


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


# ===========================================================================
# STEP (c) - the poll, the verdict, and the comment round
# ===========================================================================
#
# Step (b) above parks the ticket and accepts only the poller's wake. This half
# says what an answer MEANS. The engine asks the platform ONCE per slow beat and
# the platform's answer drives the ticket:
#
#   every parked request merged   -> the ticket closes, citing the platform merge
#                                    per repository (that merge is the acceptance
#                                    record, not a local signature)
#   a request closed WITHOUT merge -> a named NON-ACCEPTANCE. The ticket is never
#                                    closed here, even when a sibling merged.
#   new comments since our push   -> exactly ONE rework round carrying the text
#   still open                    -> wait quietly (nothing moves, no slot is held)
#
# Two rules carry the whole judgement:
#
#   * Only "all declared repositories merged" accepts a delivery. A partly merged
#     delivery is a named, non-terminal state; a closed request is a
#     non-acceptance even beside a merged one.
#   * A comment round is a ROUND, not an event. Everything that arrived after our
#     last push counts - human OR bot - except the words of our own credential and
#     everything a previous round already carried. Nothing selected = no move.
#
# Bounds (deliberate, and the reason a poll can never spin):
#   * one port call per parked request per beat, never a second attempt inside a
#     beat;
#   * the workflow side runs one activity attempt per beat (maximum_attempts=1),
#     so a failed beat waits for the next beat instead of retrying in place;
#   * the number of parked requests is the number of repositories the project
#     declared, so the beat's cost is bounded by the declaration, not by time.
#
# Port contract for step (c) (a fake in a test is a few lines):
#   poll_request(scope, number) -> {"status": "open"|"merged"|"closed"|"absent"
#                                            |"ambiguous"|"unreachable"
#                                            |"rate_limited",
#                                   "merged_at": iso, "merge_commit": sha,
#                                   "url": str,
#                                   "branch": "present"|"deleted"|"",
#                                   "comments": [{"id", "author", "body",
#                                                 "created_at", "is_bot"}],
#                                   "detail": str}
#   viewer_login()             -> the login our own credential posts as ("" when
#                                 the port cannot say). An empty login is NOT
#                                 papered over: the round would then be unable to
#                                 tell our own words apart, so the answer is read
#                                 as ambiguous, never as a round.
# An implementation may raise `PrFlowStop` instead of returning a status; the
# stop code is carried through unchanged and stays named.

#: Replay gate for the workflow side of step (c). A history recorded before this
#: marker replays step (b)'s park verbatim: record the wake, re-park, no timer.
PR_FLOW_POLL_PATCH_ID = "dev-lane-pr-flow-poll-v1"

#: The beat: one platform question per beat, on a slow timer. One beat does not
#: loop and does not retry; a beat that cannot answer is a named state and the
#: NEXT beat asks again (a missed beat costs minutes, never the ticket).
#: t261103-13: this is the DEFAULT now - a project declaration may declare its own
#: `beat_seconds`, and `SwitchDecision.options()` is where the two are resolved.
POLL_BEAT_SECONDS = DEFAULT_BEAT_SECONDS

#: The poll's judgement outcomes. One word each, and only POLL_MERGED may end the
#: ticket.
POLL_MERGED = "merged"
POLL_COMMENT_ROUND = "comment_round"
POLL_STILL_OPEN = "still_open"
POLL_PARTLY_MERGED = "partly_merged"
#: The beat produced no action at all: it stopped, and `stop` names why.
POLL_STOP = "stop"

#: What the platform answered about ONE parked request. This is the whole
#: vocabulary; anything else is `ambiguous`, never a guess.
REQUEST_OPEN = "open"
REQUEST_MERGED = "merged"
REQUEST_CLOSED = "closed"
REQUEST_ABSENT = "absent"
REQUEST_AMBIGUOUS = "ambiguous"
REQUEST_UNREACHABLE = "unreachable"
REQUEST_RATE_LIMITED = "rate_limited"
REQUEST_STATUSES = (REQUEST_OPEN, REQUEST_MERGED, REQUEST_CLOSED, REQUEST_ABSENT,
                    REQUEST_AMBIGUOUS, REQUEST_UNREACHABLE, REQUEST_RATE_LIMITED)
#: The answers that actually settled the question (the rest are a failed beat).
REQUEST_ANSWERED = (REQUEST_OPEN, REQUEST_MERGED, REQUEST_CLOSED, REQUEST_ABSENT)

#: The branch face of one parked request.
BRANCH_PRESENT = "present"
BRANCH_DELETED = "deleted"

# ---- the poll's named stops (one table, the whole vocabulary) --------------

POLL_STOP_PLATFORM_UNREACHABLE = "github_pr_poll_platform_unreachable"
POLL_STOP_RATE_LIMITED = "github_pr_poll_rate_limited"
POLL_STOP_ANSWER_AMBIGUOUS = "github_pr_poll_answer_ambiguous"
POLL_STOP_REQUEST_CLOSED_UNMERGED = "github_pr_poll_request_closed_unmerged"
POLL_STOP_BRANCH_DELETED = "github_pr_poll_branch_deleted"
POLL_STOP_REQUEST_MISSING = "github_pr_poll_request_missing"
POLL_STOP_COMMENT_ROUND_EMPTY = "github_pr_poll_comment_round_empty"
POLL_STOP_PARTLY_MERGED = "github_pr_poll_partly_merged"
POLL_STOP_NO_PARKED_REQUEST = "github_pr_poll_no_parked_request"
POLL_STOP_SWITCH_OFF = "github_pr_poll_switch_off"

#: code -> what the stop means, in one line. No entry may be read as a merge:
#: the only acceptance face of this flow is POLL_MERGED.
POLL_STOP_TABLE = {
    POLL_STOP_PLATFORM_UNREACHABLE:
        "the platform could not be reached on this beat",
    POLL_STOP_RATE_LIMITED:
        "the platform rate limited this beat",
    POLL_STOP_ANSWER_AMBIGUOUS:
        "the platform answer was ambiguous (the poll cannot read it)",
    POLL_STOP_REQUEST_CLOSED_UNMERGED:
        "the platform CLOSED the request without merging it (non-acceptance)",
    POLL_STOP_BRANCH_DELETED:
        "the branch under the request no longer exists on the platform",
    POLL_STOP_REQUEST_MISSING:
        "a request recorded on the ticket face is gone from the platform",
    POLL_STOP_COMMENT_ROUND_EMPTY:
        "there is nothing to deliver as a round (no new comment)",
    POLL_STOP_PARTLY_MERGED:
        "part of the delivery is merged and part is not (non-terminal)",
    POLL_STOP_NO_PARKED_REQUEST:
        "the parked ticket names no request, so there is nothing to poll",
    POLL_STOP_SWITCH_OFF:
        "the project switch was turned off while the ticket was parked",
}

#: code -> the remedy a reader can act on (one line, no jargon).
POLL_STOP_REMEDY = {
    POLL_STOP_PLATFORM_UNREACHABLE:
        "nothing is lost: the next beat asks again; check the platform status "
        "page if the beats keep failing",
    POLL_STOP_RATE_LIMITED:
        "nothing is lost: the next beat asks again; lower the beat rate or the "
        "credential's request volume if this repeats",
    POLL_STOP_ANSWER_AMBIGUOUS:
        "the next beat asks again; if it repeats, read the request on the "
        "platform and decide by hand (the ticket face names what was asked)",
    POLL_STOP_REQUEST_CLOSED_UNMERGED:
        "the delivery was not accepted: reopen the request on the platform, or "
        "send rework(to_stage=work) to deliver again - the ticket stays open",
    POLL_STOP_BRANCH_DELETED:
        "push the branch again (the delivery act republishes it) and retry, or "
        "cancel the ticket if the work is dropped",
    POLL_STOP_REQUEST_MISSING:
        "open the request again (the delivery act rewrites it in place when the "
        "branch is still there), or cancel the ticket if the work is dropped",
    POLL_STOP_COMMENT_ROUND_EMPTY:
        "nothing moves: every comment seen was ours or already handled; the next "
        "beat asks again",
    POLL_STOP_PARTLY_MERGED:
        "read the merged repositories on the ticket face and merge the rest, or "
        "send rework(to_stage=work) for the open ones",
    POLL_STOP_NO_PARKED_REQUEST:
        "a human inspects the ticket face: the park recorded no request, so the "
        "poll has nothing to ask about",
    POLL_STOP_SWITCH_OFF:
        "decide by hand: turn the switch back on and retry, or cancel the "
        "ticket (the request stays on the platform)",
}

#: The stops that mean "this beat failed, the next beat asks again". The park
#: STAYS, nothing moves, no slot is held.
POLL_BEAT_STOPS = frozenset((
    POLL_STOP_PLATFORM_UNREACHABLE,
    POLL_STOP_RATE_LIMITED,
    POLL_STOP_ANSWER_AMBIGUOUS,
    POLL_STOP_COMMENT_ROUND_EMPTY,
    POLL_STOP_PARTLY_MERGED,
))

#: The stops a beat cannot remove: a human decides. The ticket is blocked BY
#: NAME with its remedy (never closed, never silently re-parked).
POLL_TERMINAL_STOPS = frozenset((
    POLL_STOP_REQUEST_CLOSED_UNMERGED,
    POLL_STOP_BRANCH_DELETED,
    POLL_STOP_REQUEST_MISSING,
    POLL_STOP_NO_PARKED_REQUEST,
    POLL_STOP_SWITCH_OFF,
))


def is_poll_stop(code: Any) -> bool:
    """True for every stop this step can report."""
    return str(code or "") in POLL_STOP_TABLE


def poll_stop_keeps_waiting(code: Any) -> bool:
    """True when the named stop is a failed beat: the park stays and the next
    beat asks again. False means a human must act (blocked by name)."""
    return str(code or "") in POLL_BEAT_STOPS


# ---- the comment round ----------------------------------------------------

#: How many comments one round may carry on the ticket face (the round itself is
#: delivered whole; the FACE is what stays bounded).
COMMENT_ROUND_FACE_LIMIT = 40
#: How much of one comment body the face keeps.
COMMENT_BODY_FACE_LIMIT = 1200


def parse_iso(value: Any) -> float:
    """Epoch seconds for an ISO-8601 timestamp, or -1.0 when it cannot be read.

    One format for both sides (the platform answers "...Z", the engine records
    "...+00:00"), so "after our last push" is a number comparison, never a string
    comparison of two different spellings.
    """
    text = str(value or "").strip()
    if not text:
        return -1.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        import datetime as _dt  # noqa: PLC0415 - local on purpose
        return _dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return -1.0


def normalize_comment(raw: Any) -> Dict[str, Any]:
    """One platform comment in this module's shape ({} when it is not a comment).

    `is_bot` is recorded as a FACT, not a filter: the round's rule is "human or
    bot alike, except our own words" (design requirement 5).
    """
    if not isinstance(raw, Mapping):
        return {}
    ident = str(raw.get("id") or "").strip()
    author = str(raw.get("author") or raw.get("login") or "").strip()
    body = str(raw.get("body") or "").strip()
    if isinstance(raw.get("user"), Mapping):
        author = str(raw["user"].get("login") or author).strip()
        is_bot = str(raw["user"].get("type") or "").lower() == "bot"
    else:
        is_bot = bool(raw.get("is_bot"))
    if author.lower().endswith("[bot]"):
        is_bot = True
    if not ident and not body:
        return {}
    return {
        "id": ident,
        "author": author,
        "body": body,
        "created_at": str(raw.get("created_at") or "").strip(),
        "is_bot": is_bot,
    }


def _is_own_comment(author: str, own_logins: Iterable[Any]) -> bool:
    """True when a comment was written by OUR credential.

    The comparison is on the login, lower-cased; a bot suffix is tolerated so an
    "our-bot[bot]" credential is still recognized as ours (the engine's own words
    must never send a ticket back).
    """
    name = str(author or "").strip().lower()
    if not name:
        return False
    bare = name[:-5] if name.endswith("[bot]") else name
    for raw in own_logins or ():
        mine = str(raw or "").strip().lower()
        if not mine:
            continue
        mine_bare = mine[:-5] if mine.endswith("[bot]") else mine
        if name == mine or bare == mine_bare:
            return True
    return False


def select_comment_round(comments: Iterable[Any], *, own_logins: Iterable[Any] = (),
                         handled_ids: Iterable[Any] = (),
                         since_iso: Any = "") -> List[Dict[str, Any]]:
    """The comments that form ONE round: arrived after our last push, not ours,
    not already carried by an earlier round.

    Rules, in the design's words (requirement 5): every comment that arrived after
    our last push counts, human or bot alike, except the ones our own credential
    wrote and the ones a previous round already handled.

    A comment whose timestamp cannot be read is KEPT (showing a reviewer's words
    twice is a smaller fault than silently dropping them); one whose id repeats
    inside one answer is kept once.
    """
    mine = tuple(x for x in (own_logins or ()) if str(x or "").strip())
    handled = {str(x) for x in (handled_ids or ()) if str(x or "").strip()}
    since = parse_iso(since_iso)
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in comments or ():
        c = normalize_comment(raw)
        if not c:
            continue
        ident = c["id"]
        if ident and (ident in seen or ident in handled):
            continue
        if _is_own_comment(c["author"], mine):
            continue
        created = parse_iso(c["created_at"])
        if since >= 0 and created >= 0 and created <= since:
            continue
        if ident:
            seen.add(ident)
        out.append(c)
    return out


def handled_comment_ids(rounds: Iterable[Any]) -> List[str]:
    """Every comment id a previous round already carried (the ticket face is the
    source: `meta["pr_comment_rounds"]`)."""
    out: List[str] = []
    for raw in rounds or ():
        if not isinstance(raw, Mapping):
            continue
        ids = raw.get("ids")
        if isinstance(ids, (list, tuple)):
            out.extend(str(x) for x in ids if str(x or "").strip())
        for c in (raw.get("comments") or []):
            if isinstance(c, Mapping) and str(c.get("id") or "").strip():
                out.append(str(c["id"]))
    seen = set()
    uniq = []
    for i in out:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


def round_text(record: Mapping[str, Any]) -> str:
    """The round as text, carried to the work stage (the comments are the work)."""
    rows = [c for c in (record.get("comments") or []) if isinstance(c, Mapping)]
    head = ("Review comments, round %s: %d comment(s) arrived on the review "
            "request after our last push." % (record.get("round") or "?", len(rows)))
    lines = [head, ""]
    for c in rows:
        who = str(c.get("author") or "(unknown author)")
        if c.get("is_bot"):
            who += " [bot]"
        where = str(c.get("url") or "")
        lines.append("- %s at %s%s:" % (who, c.get("created_at") or "(time unknown)",
                                        (" (%s)" % where) if where else ""))
        body = str(c.get("body") or "").strip() or "(empty comment)"
        for line in body.split("\n"):
            lines.append("  > %s" % line)
        lines.append("")
    lines.append("Address these in the lane, then deliver again: the request is "
                 "rewritten in place, so the same thread carries the next round.")
    return "\n".join(lines).strip()


def round_face_record(comments: Iterable[Any], *, round_no: int, at_iso: str,
                      since_iso: str = "") -> Dict[str, Any]:
    """The ticket-face record of one comment round (bounded, scrubbed).

    The round number makes "once per round" auditable: a second round needs new
    comments, never the same ones.
    """
    rows: List[Dict[str, Any]] = []
    for c in list(comments or [])[:COMMENT_ROUND_FACE_LIMIT]:
        cc_ = normalize_comment(c)
        if not cc_:
            continue
        body = cc_["body"]
        if len(body) > COMMENT_BODY_FACE_LIMIT:
            body = body[:COMMENT_BODY_FACE_LIMIT - 3].rstrip() + "..."
        rows.append({"id": cc_["id"], "author": cc_["author"], "body": body,
                     "created_at": cc_["created_at"], "is_bot": cc_["is_bot"]})
    record = {
        "round": int(round_no),
        "at": str(at_iso or ""),
        "since": str(since_iso or ""),
        "count": len(rows),
        "ids": [r["id"] for r in rows if r["id"]],
        "comments": rows,
    }
    return scrub(dict(record, text=round_text(record)))


# ---- the verdict ----------------------------------------------------------

@dataclass
class PollVerdict:
    """One beat's judgement: what the platform said, and what it means.

    `action` is one of POLL_MERGED / POLL_COMMENT_ROUND / POLL_STILL_OPEN /
    POLL_PARTLY_MERGED, or "" when the beat stopped (`stop` names it). Only
    POLL_MERGED closes a ticket; every stop names its remedy in `stop_remedy`.
    """
    action: str = ""
    stop: str = ""
    detail: str = ""
    beat: int = 0
    observations: List[Dict[str, Any]] = field(default_factory=list)
    merged: List[Dict[str, Any]] = field(default_factory=list)
    round: Dict[str, Any] = field(default_factory=dict)

    def face(self) -> Dict[str, Any]:
        return scrub({
            "action": self.action,
            "stop": self.stop,
            "detail": self.detail,
            "beat": int(self.beat),
            "remedy": stop_remedy(self.stop) if self.stop else "",
            "requests": [dict(o) for o in self.observations],
            "merged": [dict(m) for m in self.merged],
            "round": dict(self.round),
        })

    def to_dict(self) -> Dict[str, Any]:
        """The activity receipt. Scrubbed: no secret can ride out on it."""
        return self.face()


def poll_verdict_from(raw: Any) -> PollVerdict:
    """Decode a poll receipt (the workflow side's entry point)."""
    if isinstance(raw, PollVerdict):
        return raw
    if not isinstance(raw, Mapping):
        return PollVerdict(action="", stop=POLL_STOP_ANSWER_AMBIGUOUS,
                           detail="the poll returned %r, not a receipt"
                                  % type(raw).__name__)
    try:
        beat = int(raw.get("beat") or 0)
    except (TypeError, ValueError):
        beat = 0
    if not raw.get("action") and not raw.get("stop"):
        return poll_stop_verdict(
            POLL_STOP_ANSWER_AMBIGUOUS,
            "the poll receipt names neither an action nor a stop (beat %d): nothing "
            "was judged and nothing moved" % beat, beat=beat)
    return PollVerdict(
        action=str(raw.get("action") or ""),
        stop=str(raw.get("stop") or ""),
        detail=str(raw.get("detail") or ""),
        beat=beat,
        observations=[dict(o) for o in (raw.get("requests") or [])
                      if isinstance(o, Mapping)],
        merged=[dict(m) for m in (raw.get("merged") or [])
                if isinstance(m, Mapping)],
        round=dict(raw.get("round") or {}) if isinstance(raw.get("round"), Mapping) else {})


def poll_stop_verdict(code: Any, detail: Any = "", *, beat: int = 0,
                      observations: Iterable[Any] = ()) -> PollVerdict:
    """A named stop of the poll (never a merge, never a close)."""
    return PollVerdict(action="", stop=redact(code), detail=redact(detail),
                       beat=int(beat),
                       observations=[dict(o) for o in (observations or ())
                                     if isinstance(o, Mapping)])


def merged_citations(observations: Iterable[Any]) -> List[Dict[str, Any]]:
    """The platform merge, cited per repository (the acceptance record)."""
    out: List[Dict[str, Any]] = []
    for o in observations or ():
        if not isinstance(o, Mapping):
            continue
        if str(o.get("status") or "") != REQUEST_MERGED:
            continue
        out.append(scrub({
            "repo": str(o.get("repo") or ""),
            "name": str(o.get("name") or ""),
            "identity": str(o.get("identity") or ""),
            "branch": str(o.get("branch") or ""),
            "number": int(o.get("number") or 0),
            "url": str(o.get("url") or ""),
            "merged_at": str(o.get("merged_at") or ""),
            "merge_commit": str(o.get("merge_commit") or ""),
            "platform_merge": True,
        }))
    return out


def acceptance_record(verdict: PollVerdict, *, ticket_id: str,
                      at_iso: str) -> Dict[str, Any]:
    """The ticket-face record of an accepted delivery: which platform merge
    accepted which repository. This IS the acceptance record of the ticket.

    Not to be confused with the platform port's `merge_record` (step (d) reads
    the platform's own merge report for one repository): this is the ticket's
    record of the acceptance, that one is a platform read.
    """
    rows = [dict(m) for m in verdict.merged] or merged_citations(verdict.observations)
    cited = ["%s#%s merged at %s%s"
             % (m.get("identity") or m.get("repo") or "?", m.get("number") or "?",
                m.get("merged_at") or "(time not reported)",
                (" (commit %s)" % m.get("merge_commit")) if m.get("merge_commit") else "")
             for m in rows]
    return scrub({
        "state": POLL_MERGED,
        "ticket": str(ticket_id or ""),
        "at": str(at_iso or ""),
        "beats": int(verdict.beat or 0),
        "requests": rows,
        "cited": cited,
    })


def poll_text(verdict: PollVerdict, ticket_id: str = "") -> str:
    """The one-line status of a beat, or the blocked text of a named stop.

    A stop always carries its remedy and the promise that nothing was lost, and it
    says in words that it is not a merge (a non-acceptance must never read as an
    acceptance).
    """
    if verdict.action == POLL_PARTLY_MERGED or verdict.stop == POLL_STOP_PARTLY_MERGED:
        return ("review-request poll: part of the delivery is merged, part is not - "
                "%s | remedy: %s | the ticket does not move and this is NOT a merge "
                "of the delivery" % (verdict.detail or "the open requests are named on "
                                     "the ticket face",
                                     stop_remedy(POLL_STOP_PARTLY_MERGED)))
    if verdict.stop:
        return ("review-request poll stopped (%s%s): %s%s | remedy: %s | this is NOT a "
                "merge and the ticket is not closed"
                % (verdict.stop, (", ticket " + str(ticket_id)) if ticket_id else "",
                   verdict.detail or "no detail recorded",
                   poll_stop_keeps_waiting(verdict.stop)
                   and " | the park stays, the next beat asks again" or "",
                   stop_remedy(verdict.stop)))
    if verdict.action == POLL_MERGED:
        return ("review-request poll: every request is merged on the platform (%s) - "
                "the platform merge is the acceptance record"
                % ", ".join("%s#%s" % (m.get("identity") or m.get("repo") or "?",
                                       m.get("number") or "?")
                            for m in (verdict.merged or merged_citations(
                                verdict.observations)) or []) or "(no request named)")
    if verdict.action == POLL_COMMENT_ROUND:
        return ("review-request poll: one comment round (%d comment(s)) - the ticket "
                "goes back for rework with the comment text"
                % int(verdict.round.get("count") or len(verdict.round.get("comments") or [])))
    if verdict.action == POLL_STILL_OPEN:
        return "review-request poll: still open on the platform - nothing moves"
    return ("review-request poll answered %r: no judgement was made and nothing "
            "moved (a named read, never a close)" % (verdict.action or "(absent)",))


# ---- normalizing one port answer -----------------------------------------

def _observation(request: Mapping[str, Any], answer: Mapping[str, Any]) -> Dict[str, Any]:
    """One parked request + one port answer -> one observation row.

    An answer outside the vocabulary is read as `ambiguous` (the engine does not
    know the state), never as open and never as merged.
    """
    req = request if isinstance(request, Mapping) else {}
    raw = answer if isinstance(answer, Mapping) else {}
    status = str(raw.get("status") or "").strip().lower()
    if status not in REQUEST_STATUSES:
        status = REQUEST_AMBIGUOUS
    branch = str(raw.get("branch") or "").strip().lower()
    if branch not in (BRANCH_PRESENT, BRANCH_DELETED):
        branch = ""
    comments = []
    for c in (raw.get("comments") or []):
        cc_ = normalize_comment(c)
        if cc_:
            comments.append(cc_)
    try:
        number = int(req.get("number") or raw.get("number") or 0)
    except (TypeError, ValueError):
        number = 0
    return scrub({
        "repo": str(req.get("repo") or ""),
        "name": str(req.get("name") or req.get("repo") or ""),
        "identity": str(req.get("identity") or ""),
        "branch": str(req.get("branch") or ""),
        "number": number,
        "url": str(raw.get("url") or req.get("url") or ""),
        "status": status,
        "merged_at": str(raw.get("merged_at") or "") if status == REQUEST_MERGED else "",
        "merge_commit": str(raw.get("merge_commit") or "") if status == REQUEST_MERGED else "",
        "branch_state": branch,
        "comments": comments,
        "detail": str(raw.get("detail") or "")[:300],
    })


def _asked_scope(request: Mapping[str, Any]) -> Dict[str, Any]:
    """The scope a port implementation needs to ask about one parked request."""
    req = request if isinstance(request, Mapping) else {}
    return {"repo": str(req.get("repo") or ""),
            "name": str(req.get("name") or ""),
            "identity": str(req.get("identity") or ""),
            "branch": str(req.get("branch") or ""),
            "tree": "", "remote": "", "changed": True}


# ---- the poll ------------------------------------------------------------

def poll_parked(platform: Any, requests: Iterable[Any], *, own_logins: Iterable[Any] = (),
                handled_ids: Iterable[Any] = (), since_iso: Any = "",
                beat: int = 0) -> PollVerdict:
    """One beat: ask the platform about every parked request, then judge ONE answer.

    Bounded by construction: one `poll_request` call per parked request, no retry
    inside the beat, and the beat stops asking as soon as the platform cannot
    answer (a rate-limited or unreachable platform is not asked again inside the
    same beat). Every failure is a named stop, never a guess.

    A step (a) credential stop is NOT a beat: it is raised to the caller, which
    names it on the ticket face (a rejected token cannot heal on the next beat).
    """
    parked = [r for r in (requests or ()) if isinstance(r, Mapping)]
    if not parked:
        return poll_stop_verdict(
            POLL_STOP_NO_PARKED_REQUEST,
            "the parked ticket face names no request: there is nothing to ask the "
            "platform about", beat=beat)
    observations: List[Dict[str, Any]] = []
    for req in parked:
        observations.append(_ask_one(platform, req))
        if observations[-1].get("status") in (REQUEST_UNREACHABLE, REQUEST_RATE_LIMITED):
            break          # do not hammer a platform that just refused to talk
    return judge_poll(observations, own_logins=own_logins, handled_ids=handled_ids,
                      since_iso=since_iso, beat=beat)


def _status_for_stop(code: Any) -> str:
    """A raised stop -> the observation status it means.

    Rate limiting and an unreachable platform keep their own faces; everything
    else is `ambiguous` (the read did not answer), which the next beat asks again.
    """
    name = str(code or "")
    if name == POLL_STOP_RATE_LIMITED:
        return REQUEST_RATE_LIMITED
    if name == DELIVERY_STOP_PLATFORM_UNREACHABLE:
        return REQUEST_UNREACHABLE
    return REQUEST_AMBIGUOUS


def _ask_one(platform: Any, request: Mapping[str, Any]) -> Dict[str, Any]:
    """ONE question about ONE parked request, translated to one observation.

    Never retried here: the caller's beat is the retry unit.
    """
    req = request if isinstance(request, Mapping) else {}
    try:
        number = int(req.get("number") or 0)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        return _observation(req, {"status": REQUEST_AMBIGUOUS,
                                  "detail": "the parked record carries no request "
                                            "number, so the request cannot be asked "
                                            "about"})
    try:
        answer = platform.poll_request(_asked_scope(req), number)
    except PrFlowStop as e:
        if str(e.code or "").startswith("github_pr_credential_"):
            raise          # a precondition, not a beat: the caller names it
        return _observation(req, {"status": _status_for_stop(e.code),
                                  "detail": e.message()})
    except Exception as e:  # noqa: BLE001 - an unclassified fault is a failed beat
        return _observation(req, {
            "status": REQUEST_AMBIGUOUS,
            "detail": "poll_request raised %s: %s" % (type(e).__name__, e)})
    return _observation(req, answer if isinstance(answer, Mapping) else {})


def judge_poll(observations: Iterable[Any], *, own_logins: Iterable[Any] = (),
               handled_ids: Iterable[Any] = (), since_iso: Any = "",
               beat: int = 0) -> PollVerdict:
    """Judge one beat's observations. This function is the truth table.

    Order matters, and it is fail-closed at every step:
      1. a beat that could not answer      -> its named stop, nothing moves;
      2. a request closed WITHOUT a merge  -> non-acceptance (never a close);
      3. a request gone from the platform  -> named stop;
      4. a deleted branch                  -> named stop;
      5. EVERY parked request merged       -> the only acceptance;
      6. some merged, some open            -> named non-terminal state (a human
                                              decides; a rework here could not
                                              republish an already merged branch);
      7. new comments (own/handled removed) -> ONE round;
      8. comments seen but all excluded    -> named "nothing to deliver" (no move);
      9. otherwise                          -> still open, wait quietly.
    """
    obs = [dict(o) for o in (observations or ()) if isinstance(o, Mapping)]
    statuses = [str(o.get("status") or "") for o in obs]
    if not obs:
        return poll_stop_verdict(POLL_STOP_ANSWER_AMBIGUOUS,
                                 "the beat produced no observation at all", beat=beat)
    if REQUEST_UNREACHABLE in statuses:
        return poll_stop_verdict(
            POLL_STOP_PLATFORM_UNREACHABLE,
            "the platform could not be reached for: %s"
            % ", ".join(o.get("name") or o.get("repo") or "?"
                        for o in obs if o.get("status") == REQUEST_UNREACHABLE),
            beat=beat, observations=obs)
    if REQUEST_RATE_LIMITED in statuses:
        return poll_stop_verdict(
            POLL_STOP_RATE_LIMITED,
            "the platform rate limited the beat for: %s"
            % ", ".join(o.get("name") or o.get("repo") or "?"
                        for o in obs if o.get("status") == REQUEST_RATE_LIMITED),
            beat=beat, observations=obs)
    unknown = [o for o in obs if str(o.get("status") or "") not in REQUEST_ANSWERED]
    if unknown:
        return poll_stop_verdict(
            POLL_STOP_ANSWER_AMBIGUOUS,
            "; ".join("%s: %s" % (o.get("name") or o.get("repo") or "?",
                                  o.get("detail") or ("status %r"
                                                      % (o.get("status"),)))
                      for o in unknown)[:400],
            beat=beat, observations=obs)
    closed = [o for o in obs if o.get("status") == REQUEST_CLOSED]
    if closed:
        return poll_stop_verdict(
            POLL_STOP_REQUEST_CLOSED_UNMERGED,
            "the platform closed %s WITHOUT a merge: the delivery was not accepted "
            "(a rejection is not an acceptance and the ticket is not closed)"
            % ", ".join("%s#%s" % (o.get("identity") or o.get("repo") or "?",
                                   o.get("number") or "?") for o in closed),
            beat=beat, observations=obs)
    missing = [o for o in obs if o.get("status") == REQUEST_ABSENT]
    if missing:
        return poll_stop_verdict(
            POLL_STOP_REQUEST_MISSING,
            "the platform no longer has %s"
            % ", ".join("%s#%s" % (o.get("identity") or o.get("repo") or "?",
                                   o.get("number") or "?") for o in missing),
            beat=beat, observations=obs)
    deleted = [o for o in obs if o.get("branch_state") == BRANCH_DELETED]
    if deleted:
        return poll_stop_verdict(
            POLL_STOP_BRANCH_DELETED,
            "the branch is gone on the platform for: %s"
            % ", ".join(o.get("name") or o.get("repo") or "?" for o in deleted),
            beat=beat, observations=obs)
    merged = [o for o in obs if o.get("status") == REQUEST_MERGED]
    if merged and len(merged) == len(obs):
        return PollVerdict(action=POLL_MERGED, beat=beat, observations=obs,
                           merged=merged_citations(obs))
    if merged:
        # A named, NON-TERMINAL state: neither a merge (it would close the ticket)
        # nor a stop a human must clear. The park stays and the next beat asks.
        partly = poll_stop_verdict(
            POLL_STOP_PARTLY_MERGED,
            "merged: %s | still open: %s (the delivery ends only when every "
            "declared repository is merged)"
            % (", ".join("%s#%s" % (o.get("identity") or o.get("repo") or "?",
                                    o.get("number") or "?") for o in merged),
               ", ".join("%s#%s" % (o.get("identity") or o.get("repo") or "?",
                                    o.get("number") or "?")
                         for o in obs if o.get("status") == REQUEST_OPEN) or "(none)"),
            beat=beat, observations=obs)
        partly.action = POLL_PARTLY_MERGED
        partly.merged = merged_citations(obs)
        return partly
    seen_comments = [c for o in obs for c in (o.get("comments") or [])]
    own = [str(x) for x in (own_logins or ()) if str(x or "").strip()]
    if seen_comments and not own:
        # The exclusion rule needs to know which comments are OURS. Without that
        # identity the round could bounce the engine's own words back at the
        # lane, so the beat is read as ambiguous and the next beat asks again.
        return poll_stop_verdict(
            POLL_STOP_ANSWER_AMBIGUOUS,
            "%d comment(s) on the request but the platform did not report the "
            "credential's login, so our own comments cannot be told apart"
            % len(seen_comments), beat=beat, observations=obs)
    selected = select_comment_round(seen_comments, own_logins=own,
                                    handled_ids=handled_ids, since_iso=since_iso)
    if selected:
        return PollVerdict(action=POLL_COMMENT_ROUND, beat=beat, observations=obs,
                           round={"count": len(selected),
                                  "ids": [c["id"] for c in selected if c["id"]],
                                  "comments": selected})
    if seen_comments:
        return poll_stop_verdict(
            POLL_STOP_COMMENT_ROUND_EMPTY,
            "%d comment(s) on the request, none of them new for this ticket: our "
            "own words (%s) and the ones an earlier round already carried (%s) do "
            "not move a ticket"
            % (len(seen_comments),
               ", ".join(sorted({str(x) for x in (own_logins or ())})) or "(none recorded)",
               len(list(handled_ids or ()))),
            beat=beat, observations=obs)
    return PollVerdict(action=POLL_STILL_OPEN, beat=beat, observations=obs)


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

    def merge_record(self, scope: Dict[str, Any]) -> Dict[str, Any]:
        """What the platform reports as merged on the target branch (step (d)'s
        content check, a pure read).

        Answers `merged` with the commit sha and its tree sha, or `absent` when
        the platform carries no such commit. The tree sha is what makes the
        content check exact: a git tree id is a digest of the whole tree, so
        "same tree" is "same content". Nothing is written, and an answer that
        cannot be read is a stop (never an assumed merge).
        """
        ident = self._identity(scope)
        target = str(scope.get("target_branch") or DEFAULT_TARGET_BRANCH)
        status, payload = self._call(
            "GET", "/repos/%s/commits/%s" % (ident, quote(target, safe="")))
        if status == 404:
            return {"status": "absent", "sha": "", "tree": "", "target": target,
                    "detail": redact(self._message(payload))
                    or "the platform answered 404"}
        self._raise_for_status(status, payload, "the merged-content read")
        body = payload if isinstance(payload, dict) else {}
        commit = body.get("commit") if isinstance(body.get("commit"), dict) else {}
        tree = commit.get("tree") if isinstance(commit.get("tree"), dict) else {}
        sha = str(body.get("sha") or "")
        tree_sha = str(tree.get("sha") or "")
        if not sha or not tree_sha:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                             "the merged-content read of %r branch %r answered "
                             "without a commit sha and a tree sha"
                             % (ident, target))
        return {"status": "merged", "sha": sha, "tree": tree_sha,
                "target": target, "detail": ""}

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
        argv = _git_argv(tree, "push", "--porcelain", self._remote,
                         "refs/heads/%s:refs/heads/%s" % (branch, branch))
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

    # ---- step (c): the read-only poll face ----
    def _poll_status(self, status: int, payload: Any, what: str) -> None:
        """Map one status of a READ-ONLY poll call onto one named stop.

        A read has no side effect, so the mapping is different from the delivery
        act's: rate limiting is its own named face (the next beat asks again),
        5xx/transport is unreachable, 401 is the credential (terminal), and
        anything else is ambiguous (the poll cannot read the answer).
        """
        if status in (200, 201, 204):
            return
        if status == 401:
            raise PrFlowStop(STOP_CREDENTIAL_REJECTED,
                             "the platform refused the credential (401) on %s: %s"
                             % (what, self._message(payload)))
        if status == 429:
            raise PrFlowStop(POLL_STOP_RATE_LIMITED,
                             "the platform rate limited %s (429): %s"
                             % (what, self._message(payload)))
        if status == 403:
            text = self._message(payload).lower()
            if "rate limit" in text or "secondary rate" in text:
                raise PrFlowStop(POLL_STOP_RATE_LIMITED,
                                 "the platform rate limited %s (403): %s"
                                 % (what, self._message(payload)))
            raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                             "the platform refused %s (403) outside the rate limit: %s"
                             % (what, self._message(payload)))
        if status >= 500:
            raise PrFlowStop(DELIVERY_STOP_PLATFORM_UNREACHABLE,
                             "the platform could not serve %s (%d): %s"
                             % (what, status, self._message(payload)))
        raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                         "unexpected platform status %d on %s: %s"
                         % (status, what, self._message(payload)))

    def viewer_login(self) -> str:
        """The login our own credential posts as (step (c)'s exclusion rule).

        One read per beat. An empty login is returned as "" and NOT invented: the
        judgement then reads the round as ambiguous instead of mistaking our own
        words for a reviewer's.
        """
        status, payload = self._call("GET", "/user")
        self._poll_status(status, payload, "the credential lookup")
        if not isinstance(payload, Mapping):
            raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                             "the credential lookup answered %r, not an object"
                             % type(payload).__name__)
        return str(payload.get("login") or "")

    def _branch_state(self, ident: str, ref: str) -> str:
        """present / deleted / "" (unknown) for one branch on the platform.

        Only asked when the request is still open, because a closed or merged
        request cannot be reviewed again and the branch no longer matters."""
        if not ref:
            return ""
        status, payload = self._call(
            "GET", "/repos/%s/branches/%s" % (ident, quote(ref, safe="")))
        if status == 404:
            return BRANCH_DELETED
        if status == 200:
            return BRANCH_PRESENT
        return ""

    def poll_request(self, scope: Dict[str, Any], number: int) -> Dict[str, Any]:
        """Ask the platform about ONE parked request (step (c), read-only).

        Calls, in order and only as far as the answer needs them:
          1. the request itself (state, merge facts);
          2. the discussion comments, when the request is still open;
          3. the branch, when the request is still open (a deleted branch is a
             named face of the poll, not a guess from a closed request).
        No write, no retry, no rate-limit dance: a failed call is a named stop and
        the next beat asks again.
        """
        ident = self._identity(scope)
        n = _request_number(number)
        if not n:
            raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                             "the parked record carries no request number")
        status, payload = self._call("GET", "/repos/%s/pulls/%d" % (ident, n))
        if status == 404:
            return {"status": REQUEST_ABSENT, "number": n, "url": "",
                    "detail": "the platform has no request #%d in %s" % (n, ident)}
        self._poll_status(status, payload, "the request state")
        if not isinstance(payload, Mapping):
            raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                             "the request state answered %r, not an object"
                             % type(payload).__name__)
        url = str(payload.get("html_url") or "")
        merged_at = str(payload.get("merged_at") or "")
        state = str(payload.get("state") or "").lower()
        if merged_at or payload.get("merged"):
            return {"status": REQUEST_MERGED, "number": n, "url": url,
                    "merged_at": merged_at,
                    "merge_commit": str(payload.get("merge_commit_sha") or ""),
                    "branch": "", "comments": [], "detail": ""}
        if state == "closed":
            return {"status": REQUEST_CLOSED, "number": n, "url": url,
                    "branch": "", "comments": [], "detail": ""}
        if state != "open":
            raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                             "the request state %r is not one this poll can read"
                             % (state or "(absent)",))
        head = payload.get("head")
        ref = str((head or {}).get("ref") or "") if isinstance(head, Mapping) else ""
        comments = self._comments(ident, n)
        return {"status": REQUEST_OPEN, "number": n, "url": url,
                "branch": self._branch_state(ident, ref),
                "comments": comments, "detail": ""}

    def _comments(self, ident: str, number: int) -> List[Dict[str, Any]]:
        """The request's discussion comments, normalized to this module's shape."""
        status, payload = self._call(
            "GET", "/repos/%s/issues/%d/comments?per_page=100" % (ident, number))
        self._poll_status(status, payload, "the request comments")
        if not isinstance(payload, list):
            raise PrFlowStop(POLL_STOP_ANSWER_AMBIGUOUS,
                             "the comments answer is %r, not a list"
                             % type(payload).__name__)
        out: List[Dict[str, Any]] = []
        for raw in payload:
            if not isinstance(raw, Mapping):
                continue
            out.append({
                "id": str(raw.get("id") or ""),
                "author": str((raw.get("user") or {}).get("login") or "")
                if isinstance(raw.get("user"), Mapping) else "",
                "body": str(raw.get("body") or ""),
                "created_at": str(raw.get("created_at") or ""),
                "is_bot": (isinstance(raw.get("user"), Mapping)
                           and str(raw["user"].get("type") or "").lower() == "bot"),
            })
        return out


def platform_from_credential(credential: Any, *,
                             transport: Optional[Callable[..., Any]] = None,
                             git_runner: Optional[Callable[..., Any]] = None,
                             ) -> "GitHubPlatform":
    """Build the live platform from step (a)'s resolved credential. Called by the
    activity only: `Credential.reveal()` is the one explicit way to the value."""
    return GitHubPlatform(token=credential.reveal(), transport=transport,
                          git_runner=git_runner)


# ---- step (d): reconcile the local target branch after a platform merge -----
#
# Design requirement 7. The platform's merge settles the delivery, but this
# machine's target branch still has to catch up before the next ticket is judged
# against it. Catching up is NOT a merge: the only lawful advance is a
# fast-forward, and it is verified by comparing the content the platform reported
# as merged with the content the local branch now carries.
#
# The act, per repository, always in this order - verify, act, verify the act:
#
#   1. the local target branch exists                    -> branch_missing
#   2. the platform is asked what it merged on that branch -> branch_missing,
#                                                            remote_unreachable
#   3. the declared remote is fetched. The fetch writes FETCH_HEAD and the
#      remote's tracking cache and NOTHING else: no local branch moves, so a
#      refusal after this point still leaves the branch exactly where it was
#                                                        -> branch_missing,
#                                                           remote_unreachable
#   4. the local branch is proven an ancestor of the fetched head
#                                                        -> local_drift
#   5. the fetched head's tree is proven equal to the tree the platform reported
#      as merged                                         -> content_mismatch
#   6. the branch advances with a fast-forward-only merge, to that one commit
#   7. the branch and its tree are read back: they must be that commit and that
#      reported tree                                     -> local_drift,
#                                                           content_mismatch
#
# Nothing else is ever issued. There is no history rewriting, no forced update,
# no ref overwrite and no worktree discard on any path: the module builds every
# git command line in exactly one place (`_git_argv`), which refuses such a shape
# before it can run. A refusal names the check that failed, says whether the
# branch was left alone, and carries a remedy line. A refusal never "repairs" the
# branch to make the check pass - a person decides.
#
# Every declared repository is reconciled INDEPENDENTLY: one repository's stop
# neither hides another repository's success nor blocks it. A delivery whose
# repositories reconciled only in part is the named NON-TERMINAL state
# `partial_reconciliation` - never a success, and the ticket stays open.

#: The git remote NAME the act fetches. It is a name configured in the local
#: repository ("origin"), never a URL and never a credential: the act reads the
#: remote the clone already trusts and adds no secret of its own to git.
DEFAULT_REMOTE = "origin"
#: One git call's budget: a fetch of one branch is small, and a hung remote must
#: not hold a worker slot.
DEFAULT_GIT_TIMEOUT = 180.0

#: The reconciliation act's named stops. Each is a refusal a person acts on; none
#: is retried in a loop, and none changes the branch to become satisfiable.
RECONCILE_STOP_REMOTE_UNREACHABLE = "github_pr_reconcile_remote_unreachable"
RECONCILE_STOP_LOCAL_DRIFT = "github_pr_reconcile_local_drift"
RECONCILE_STOP_CONTENT_MISMATCH = "github_pr_reconcile_content_mismatch"
RECONCILE_STOP_PARTIAL_RECONCILIATION = "github_pr_reconcile_partial_reconciliation"
RECONCILE_STOP_BRANCH_MISSING = "github_pr_reconcile_branch_missing"
RECONCILE_STOP_SET_UNUSABLE = "github_pr_reconcile_repository_set_unusable"
#: The two stops of the close-out's own judgement (t261103-13). They are not the
#: act's answers: they are what the wiring says when the act cannot even be
#: asked a meaningful question - the project turned the flow off between the
#: merge and the close-out, or the act's receipt cannot be read. Both keep the
#: ticket open, because "cannot prove the local branch caught up" is never "it
#: did".
RECONCILE_STOP_SWITCH_OFF = "github_pr_reconcile_switch_off"
RECONCILE_STOP_RECEIPT_UNREADABLE = "github_pr_reconcile_receipt_unreadable"

#: code -> what the stop means, in one line. `remote_unreachable` covers every
#: state the act reads but cannot get an answer for (the remote, the platform, or
#: git's own reading of the fetched state): the detail always names which command
#: failed, so "unreachable" never becomes a vague bucket.
RECONCILE_STOP_TABLE = {
    RECONCILE_STOP_REMOTE_UNREACHABLE:
        "a state the act reads could not be read (the remote or the platform)",
    RECONCILE_STOP_LOCAL_DRIFT:
        "the local branch is not an ancestor of the fetched remote head",
    RECONCILE_STOP_CONTENT_MISMATCH:
        "the local content is not the content the platform reported as merged",
    RECONCILE_STOP_PARTIAL_RECONCILIATION:
        "some declared repositories reconciled and others stopped",
    RECONCILE_STOP_BRANCH_MISSING:
        "the target branch is absent locally or on the remote",
    RECONCILE_STOP_SET_UNUSABLE:
        "the repository set handed to the act is absent, empty or malformed",
    RECONCILE_STOP_SWITCH_OFF:
        "the project declaration no longer enables the review-request flow",
    RECONCILE_STOP_RECEIPT_UNREADABLE:
        "the reconciliation answered something that is not a receipt",
}

#: code -> the remedy a reader can act on (one line, no jargon).
RECONCILE_STOP_REMEDY = {
    RECONCILE_STOP_REMOTE_UNREACHABLE:
        "check the repository's remote configuration and the platform credential, "
        "then retry - a retry reads the remote again and adopts nothing it cannot "
        "verify",
    RECONCILE_STOP_LOCAL_DRIFT:
        "a person compares the local branch with the merged work; the branch is "
        "untouched, because the engine never rewrites, discards or merges across "
        "a divergence",
    RECONCILE_STOP_CONTENT_MISMATCH:
        "a person compares the local branch with the platform's merge commit "
        "(nothing was rewritten); only content equal to the reported merge is "
        "ever adopted",
    RECONCILE_STOP_PARTIAL_RECONCILIATION:
        "a person resolves the named repositories that stopped, then retries - the "
        "reconciled repositories are already caught up, so a retry advances only "
        "the ones still behind",
    RECONCILE_STOP_BRANCH_MISSING:
        "check the declared target branch name, and that the clone carries the "
        "platform's branch, then retry - the act creates no branch",
    RECONCILE_STOP_SET_UNUSABLE:
        "hand the act the delivery's repository set (what step (b) published) - "
        "nothing was reconciled",
    RECONCILE_STOP_SWITCH_OFF:
        "restore the project declaration's github_pr: switch (or land this delivery "
        "by hand), then retry - the ticket closes only after the local target "
        "branch is proved to carry the merged content",
    RECONCILE_STOP_RECEIPT_UNREADABLE:
        "retry - a receipt that cannot be read is not a reconciliation, and the "
        "ticket closes only on a receipt that says every repository reconciled",
}

#: The act's outcomes. Only `reconciled` closes the reconciliation; a partial
#: reconciliation and a stop both keep the ticket open.
RECONCILE_RECONCILED = "reconciled"
RECONCILE_PARTIAL = "partial_reconciliation"
RECONCILE_OFF = "not_applicable"

#: One repository's row state inside the receipt.
REPO_STATE_RECONCILED = "reconciled"
REPO_STATE_STOPPED = "stopped"


def is_reconcile_stop(code: Any) -> bool:
    """True for every stop the reconciliation act can report."""
    return str(code or "") in RECONCILE_STOP_TABLE


# ---- the one git chokepoint ------------------------------------------------

#: The git verbs this module may issue. Every one is additive: it reads state, it
#: advances a fast-forward, or it publishes a branch without a forced update.
ALLOWED_GIT_VERBS = ("fetch", "rev-parse", "merge-base", "merge", "push")

#: Command words no path in this module may ever build: history rewriting, forced
#: updates, ref overwrites and worktree discards.
FORBIDDEN_GIT_VERBS = ("am", "checkout", "cherry-pick", "clean", "filter-branch",
                       "gc", "prune", "rebase", "reset", "restore", "revert",
                       "stash", "switch", "update-ref", "worktree")
#: Arguments with the same effect, spelled as flags.
FORBIDDEN_GIT_ARGS = ("-f", "-B", "-D", "--force", "--force-with-lease",
                      "--force-if-includes", "--hard", "--keep", "--mirror",
                      "--prune")
#: Any argument with this prefix is a forced update, whatever follows it.
FORCED_UPDATE_PREFIX = "--force"
#: The guard words that are ALSO ordinary English and therefore cannot be judged
#: from a source scan ("the github_pr switch block", "a clean sync"): the
#: command-line chokepoint still refuses every one of them as a git verb, and the
#: source scan judges the rest of the list - the spellings that can only mean the
#: destructive action.
FORBIDDEN_GIT_VERBS_COMMON_WORDS = ("am", "clean", "gc", "prune", "restore",
                                    "revert", "stash", "switch", "worktree")


def _git_argv(repo: Any, *args: str) -> List[str]:
    """Build the ONE git command line this module may run, or refuse the shape.

    Every git call in this module goes through here (the reconciliation act and
    the branch publish alike), so "no path rewrites history, forces an update or
    discards work" is mechanical rather than a comment. A refused shape is a
    programming error, not a delivery state: it raises ValueError, and the test
    suite proves both halves (the refusal, and that no other string in the module
    can spell such a command).
    """
    if not args:
        raise ValueError("a git command needs a verb (allowed: %s)"
                         % ", ".join(ALLOWED_GIT_VERBS))
    verb = str(args[0])
    if verb not in ALLOWED_GIT_VERBS:
        raise ValueError(
            "this module never issues the git verb %r: it may only read, "
            "fast-forward and publish a branch (allowed: %s)"
            % (verb, ", ".join(ALLOWED_GIT_VERBS)))
    bad = [str(a) for a in args
           if str(a) in FORBIDDEN_GIT_VERBS or str(a) in FORBIDDEN_GIT_ARGS
           or str(a).startswith(FORCED_UPDATE_PREFIX)]
    if bad:
        raise ValueError(
            "this module never builds the git argument %r: it would rewrite "
            "history, force an update or discard work (allowed verbs: %s)"
            % (bad[0], ", ".join(ALLOWED_GIT_VERBS)))
    return ["git", "-C", str(repo or ".")] + [str(a) for a in args]


def _git_env(extra: Optional[Mapping[str, Any]] = None) -> Dict[str, str]:
    """The environment one git call runs in.

    An inherited environment plus one rule: git must fail rather than block on a
    terminal prompt (an unattended worker has nobody to answer it). No secret is
    added here - the fetch reads the remote the clone already trusts.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    for key, value in (extra or {}).items():
        env[str(key)] = str(value)
    return env


def _run_git(git_runner: Callable[..., Any], argv: List[str], env: Dict[str, str],
             timeout: float) -> Tuple[int, str]:
    """Run one git command line through the injected runner.

    The runner answers (exit code, combined output). Anything else - a raised
    exception, a non-pair, a non-numeric exit code - means the act cannot know
    what git did, so it is the named `remote_unreachable` stop with the runner's
    own words in the detail. The output is redacted before it can reach a receipt.
    """
    shown = " ".join(argv[3:]) or "(no verb)"
    try:
        answer = git_runner(argv, dict(env), timeout)
    except PrFlowStop:
        raise
    except Exception as e:  # noqa: BLE001 - an unclassified runner fault is a stop
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the git runner raised %s on %r: %s"
                         % (type(e).__name__, shown, e))
    if not (isinstance(answer, (tuple, list)) and len(answer) == 2):
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the git runner answered %r for %r instead of "
                         "(exit code, output)"
                         % (type(answer).__name__, shown))
    code, text = answer
    try:
        code = int(code)
    except (TypeError, ValueError):
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the git runner answered the exit code %r for %r"
                         % (code, shown))
    return code, redact(str(text if text is not None else ""))


def _git_read(git_runner: Callable[..., Any], env: Dict[str, str],
              timeout: float, repo: str, *args: str) -> Tuple[int, str]:
    """One git call through the chokepoint, as (exit code, redacted output)."""
    return _run_git(git_runner, _git_argv(repo, *args), env, timeout)


def _require_sha(git_runner: Callable[..., Any], env: Dict[str, str],
                 timeout: float, repo: str, rev: str, *,
                 stop: str, what: str) -> str:
    """Resolve one revision to a sha, or report the named stop with the reason.

    A read that answers nothing is NEVER read as "nothing to do": it is the stop
    the caller names, with the command, the exit code and git's own words.
    """
    code, text = _git_read(git_runner, env, timeout, repo,
                           "rev-parse", "--verify", rev)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sha = lines[0] if (code == 0 and lines) else ""
    if not sha:
        raise PrFlowStop(stop, "%s: git could not resolve %r in %r (exit %s): %s"
                         % (what, rev, repo or "?", code, text.strip()[:200]))
    return sha


#: The git error texts that mean "the remote does not carry that ref" rather than
#: "the remote could not be reached".
_MISSING_REF_MARKERS = ("couldn't find remote ref", "no such ref",
                        "not our ref", "unable to find ref",
                        "could not find remote ref")


def _fetch_stop(code: int, text: str) -> str:
    """Classify a failed fetch: a missing ref, or an unreachable remote."""
    low = text.lower()
    if any(marker in low for marker in _MISSING_REF_MARKERS):
        return RECONCILE_STOP_BRANCH_MISSING
    return RECONCILE_STOP_REMOTE_UNREACHABLE


def _merge_report(platform: Any, scope: Dict[str, Any]) -> Dict[str, str]:
    """Ask the platform what it merged on the target branch (a pure read).

    Returns {"sha", "tree", "detail"}. `absent` is the named `branch_missing`
    stop (the platform reports no commit on that branch); any other unusable
    answer is `remote_unreachable` - the act must never invent a merge it could
    not read, because the content check is the whole point of this step.
    """
    identity = str(scope.get("identity") or "")
    target = str(scope.get("target_branch") or DEFAULT_TARGET_BRANCH)
    try:
        answer = platform.merge_record(scope)
    except PrFlowStop:
        raise
    except Exception as e:  # noqa: BLE001
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the platform merge record raised %s for %r branch %r: %s"
                         % (type(e).__name__, identity or "?", target, e))
    if not isinstance(answer, Mapping):
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the platform merge record for %r branch %r is %r, not a "
                         "receipt" % (identity or "?", target,
                                      type(answer).__name__))
    status = str(answer.get("status") or "")
    detail = redact(str(answer.get("detail") or ""))
    if status == "merged":
        return {"sha": str(answer.get("sha") or ""),
                "tree": str(answer.get("tree") or ""),
                "detail": detail}
    if status == "absent":
        raise PrFlowStop(RECONCILE_STOP_BRANCH_MISSING,
                         "the platform reports no commit on %r branch %r (%s)"
                         % (identity or "?", target,
                            detail or "no detail recorded"))
    raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                     "the platform merge record for %r branch %r answered status "
                     "%r, which cannot verify the content (%s)"
                     % (identity or "?", target, status or "(absent)",
                        detail or "no detail recorded"))


def _advance_one(row: Dict[str, Any], *, repo: str, identity: str,
                 platform: Any, git_runner: Callable[..., Any],
                 git_timeout: float, env: Dict[str, str], target: str,
                 remote: str) -> None:
    """Reconcile one repository: verify, act, verify the act.

    Raises PrFlowStop on every refusal. The only mutating command in the whole
    function is the fast-forward-only merge at step 6; every earlier refusal
    therefore leaves the branch byte-identical, and the steps after it read the
    result rather than changing it again.
    """
    if not identity:
        raise PrFlowStop(DELIVERY_STOP_REPOSITORY_UNIDENTIFIED,
                         "repository %r has no platform identity (an entry needs "
                         "its declared owner/name or its GitHub remote), so the "
                         "platform merge cannot be read" % (row.get("name"),))
    branch = "refs/heads/%s" % target

    # 1. the local branch, before anything else is read
    local = _require_sha(git_runner, env, git_timeout, repo, branch,
                         stop=RECONCILE_STOP_BRANCH_MISSING,
                         what="the local target branch is absent")
    row["before"] = local

    # 2. what the platform says it merged on that branch
    report = _merge_report(platform, {"repo": repo, "name": row.get("name"),
                                      "identity": identity,
                                      "target_branch": target, "remote": remote})
    row["reported_sha"] = report["sha"]
    row["reported_tree"] = report["tree"]
    if not row["reported_tree"]:
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the platform merge record for %r carries no tree, so the "
                         "content check cannot be made - nothing was advanced"
                         % (identity,))

    # 3. fetch the declared remote. Measured: a targeted fetch writes FETCH_HEAD
    # and the remote's tracking cache (refs/remotes/<remote>/<branch>) - a read
    # cache, not the local branch - so refs/heads/<target> cannot move here.
    code, text = _git_read(git_runner, env, git_timeout, repo,
                           "fetch", "--no-tags", remote, branch)
    if code != 0:
        raise PrFlowStop(_fetch_stop(code, text),
                         "the fetch of %r from the remote %r failed (git exit %s) "
                         "- no local branch was changed: %s"
                         % (branch, remote, code, text.strip()[:200]))
    head = _require_sha(git_runner, env, git_timeout, repo, "FETCH_HEAD",
                        stop=RECONCILE_STOP_BRANCH_MISSING,
                        what="the fetched remote head is absent")
    row["head"] = head
    row["head_matches_reported"] = bool(row["reported_sha"]) and \
        head == row["reported_sha"]

    # 4. the only lawful advance is a fast-forward
    code, text = _git_read(git_runner, env, git_timeout, repo,
                           "merge-base", "--is-ancestor", local, head)
    if code == 1:
        raise PrFlowStop(RECONCILE_STOP_LOCAL_DRIFT,
                         "the local branch %r (%s) is not an ancestor of the "
                         "fetched head %s: the branch carries work the merged "
                         "remote state does not, or the histories diverged, so no "
                         "fast-forward exists - the branch was left untouched"
                         % (branch, local[:12], head[:12]))
    if code != 0:
        raise PrFlowStop(RECONCILE_STOP_REMOTE_UNREACHABLE,
                         "the ancestry check of %r could not be answered (git "
                         "exit %s) - the branch was left untouched: %s"
                         % (branch, code, text.strip()[:200]))

    # 5. the content check BEFORE the act: the fetched head IS the reported merge
    head_tree = _require_sha(git_runner, env, git_timeout, repo,
                             "%s^{tree}" % head,
                             stop=RECONCILE_STOP_REMOTE_UNREACHABLE,
                             what="the fetched head's tree could not be read")
    row["local_tree"] = head_tree
    if head_tree != row["reported_tree"]:
        raise PrFlowStop(RECONCILE_STOP_CONTENT_MISMATCH,
                         "the fetched head %s carries tree %s while the platform "
                         "reported tree %s as merged: the local branch was NOT "
                         "advanced, and nothing was rewritten to make it match"
                         % (head[:12], head_tree[:12],
                            row["reported_tree"][:12]))

    # 6. the act: a fast-forward to exactly that commit, never a merge commit
    code, text = _git_read(git_runner, env, git_timeout, repo,
                           "merge", "--ff-only", head)
    if code != 0:
        raise PrFlowStop(RECONCILE_STOP_LOCAL_DRIFT,
                         "the fast-forward to %s was refused (git exit %s), so "
                         "git left the branch where it was: %s"
                         % (head[:12], code, text.strip()[:200]))

    # 7. verify the act: the branch and its tree are read back, never assumed
    after = _require_sha(git_runner, env, git_timeout, repo, branch,
                         stop=RECONCILE_STOP_LOCAL_DRIFT,
                         what="the branch cannot be read after the fast-forward")
    row["after"] = after
    if after != head:
        raise PrFlowStop(RECONCILE_STOP_LOCAL_DRIFT,
                         "the fast-forward did not land %r on the fetched head "
                         "(branch %s, head %s): nothing further is attempted"
                         % (branch, after[:12], head[:12]))
    after_tree = _require_sha(git_runner, env, git_timeout, repo,
                              "%s^{tree}" % after,
                              stop=RECONCILE_STOP_CONTENT_MISMATCH,
                              what="the branch tree cannot be read after the "
                                   "fast-forward")
    row["local_tree"] = after_tree
    if after_tree != row["reported_tree"]:
        raise PrFlowStop(RECONCILE_STOP_CONTENT_MISMATCH,
                         "after the fast-forward the local tree is %s while the "
                         "platform reported %s: nothing is rewritten to hide it"
                         % (after_tree[:12], row["reported_tree"][:12]))

    row["state"] = REPO_STATE_RECONCILED
    row["advanced"] = local != after
    note = ""
    if not row["head_matches_reported"]:
        note = (" (the fetched head differs from the reported merge commit %s, "
                "which can happen when the remote advanced further; the CONTENT "
                "is equal)" % ((row["reported_sha"] or "?")[:12],))
    row["detail"] = ("fast-forwarded %r from %s to %s; tree %s equals the "
                     "platform-reported tree%s"
                     % (branch, local[:12], after[:12], after_tree[:12], note))


def _reconcile_one(entry: Mapping, *, platform: Any,
                   git_runner: Callable[..., Any], git_timeout: float,
                   env: Dict[str, str], target: str, remote: str) -> Dict[str, Any]:
    """One repository's receipt row. A stop never escapes: it is recorded on the
    row, so the act can reconcile every other repository independently."""
    repo = str(entry.get("repo") or "")
    identity = str(entry.get("identity") or "") or \
        parse_repo_identity(entry.get("remote"))
    row = scrub({
        "repo": repo,
        "name": str(entry.get("name") or repo or "root"),
        "identity": identity,
        "target": target,
        "remote": remote,
        "state": REPO_STATE_STOPPED,
        "stop": "",
        "detail": "",
        "remedy": "",
        "before": "",
        "head": "",
        "after": "",
        "reported_sha": "",
        "reported_tree": "",
        "local_tree": "",
        "advanced": False,
        "head_matches_reported": False,
    })
    try:
        _advance_one(row, repo=repo, identity=identity, platform=platform,
                     git_runner=git_runner, git_timeout=git_timeout, env=env,
                     target=target, remote=remote)
    except PrFlowStop as e:
        row["state"] = REPO_STATE_STOPPED
        row["stop"] = e.code
        row["detail"] = e.message()
        row["remedy"] = stop_remedy(e.code)
    return row


def _reconcile_entries(args: Mapping) -> Tuple[List[Mapping], str]:
    """The repository set handed to the act, or the reason it is unusable.

    Accepts either the field name (`repositories`) or step (b)'s park record
    (`requests`, whose entries already carry the repository path and identity),
    so the caller does not have to reshape what step (b) produced. An absent,
    empty or malformed set is a named stop, never a silent "nothing to do".
    """
    raw = args.get("repositories")
    if not isinstance(raw, (list, tuple)) or not raw:
        raw = args.get("requests")
    if not isinstance(raw, (list, tuple)) or not raw:
        return [], ("the payload carries neither the delivery's repositories nor "
                    "the requests step (b) published, so there is nothing to "
                    "reconcile")
    out: List[Mapping] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            return [], ("entry %d of the repository set is %r, not an object "
                        "carrying the repository path"
                        % (index, type(item).__name__))
        repo = item.get("repo")
        if not isinstance(repo, str) or not repo.strip():
            return [], ("entry %d of the repository set carries no local "
                        "repository path ('repo'), so its branch cannot be "
                        "found" % index)
        out.append(item)
    return out, ""


@dataclass
class ReconcileVerdict:
    """The reconciliation act's answer.

    `state` is one of `RECONCILE_RECONCILED` (the only success),
    `RECONCILE_PARTIAL` (the named NON-TERMINAL state), `ACTION_STOP` (named, no
    repository adopted) or `RECONCILE_OFF` (the switch is off: nothing to do).
    `keeps_ticket_open` is the fact the caller must act on: only a fully
    reconciled delivery may close the ticket. `repositories` names every
    repository the act looked at, reconciled or stopped.
    """
    state: str = RECONCILE_OFF
    stop: str = ""
    detail: str = ""
    terminal: bool = False
    keeps_ticket_open: bool = False
    retryable: bool = False
    repositories: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """The activity receipt. Scrubbed: no secret can ride out on it."""
        return scrub({
            "state": self.state,
            "stop": self.stop,
            "detail": self.detail,
            "terminal": bool(self.terminal),
            "keeps_ticket_open": bool(self.keeps_ticket_open),
            "retryable": bool(self.retryable),
            "repositories": [dict(row) for row in self.repositories],
        })


def _summarize(rows: List[Dict[str, Any]]) -> ReconcileVerdict:
    """Fold the per-repository rows into the act's answer."""
    done = [r for r in rows if r.get("state") == REPO_STATE_RECONCILED]
    stopped = [r for r in rows if r.get("state") != REPO_STATE_RECONCILED]
    names = ", ".join(str(r.get("name") or r.get("repo")) for r in done) or "(none)"
    if not stopped:
        return ReconcileVerdict(
            state=RECONCILE_RECONCILED, terminal=True, keeps_ticket_open=False,
            retryable=False, repositories=rows,
            detail="%d of %d repositories fast-forwarded and content-verified: %s"
                   % (len(done), len(rows), names))
    stops = ", ".join("%s: %s" % (r.get("name") or r.get("repo"),
                                  r.get("stop") or "unnamed") for r in stopped)
    if done:
        return ReconcileVerdict(
            state=RECONCILE_PARTIAL, stop=RECONCILE_STOP_PARTIAL_RECONCILIATION,
            terminal=False, keeps_ticket_open=True, retryable=True,
            repositories=rows,
            detail="%d of %d repositories reconciled (%s) and %d stopped (%s) - "
                   "the ticket stays open until every declared repository is "
                   "reconciled" % (len(done), len(rows), names, len(stopped), stops))
    return ReconcileVerdict(
        state=ACTION_STOP,
        stop=str(stopped[0].get("stop") or RECONCILE_STOP_SET_UNUSABLE),
        terminal=False, keeps_ticket_open=True, retryable=True, repositories=rows,
        detail="none of the %d repositories reconciled (%s) - nothing was adopted"
               % (len(rows), stops))


def reconcile_after_merge(payload: Any, switch: Any = None, *,
                          platform: Any = None,
                          platform_factory: Optional[Callable[[], Any]] = None,
                          git_runner: Optional[Callable[..., Any]] = None,
                          git_timeout: float = DEFAULT_GIT_TIMEOUT,
                          git_env: Optional[Mapping[str, Any]] = None,
                          ) -> ReconcileVerdict:
    """Reconcile the local target branch after the platform merged (design step d).

    `switch` is step (a)'s decision. OFF (including "no switch read at all", the
    same default `run_delivery` uses) answers NOT APPLICABLE and touches nothing -
    the design's default-off promise, which is why this act never fetches for a
    project that did not enable the flow.

    payload keys (all read defensively): `repositories` (the delivery's declared
    repositories: entries carry `repo` = the local repository path, plus optional
    `name`, `identity`, `remote` = the GitHub remote URL, `remote_name`,
    `target_branch`) or step (b)'s `requests`; plus optional `target_branch` and
    `remote_name` defaults.

    Per repository the act fetches the declared remote, allows only a
    fast-forward, and verifies the content against the platform's reported merge.
    A partial reconciliation is the named non-terminal state that keeps the
    ticket open. Nothing here changes how a ticket closes (that is step (c)).
    """
    if not bool(getattr(switch, "enabled", False)):
        return ReconcileVerdict(
            state=RECONCILE_OFF,
            detail="the project switch is off (%s), so the delivery did not go "
                   "through the platform and there is nothing to reconcile"
                   % (str(getattr(switch, "reason", "") or "absent")))
    args = payload if isinstance(payload, Mapping) else {}
    entries, problem = _reconcile_entries(args)
    if problem:
        return ReconcileVerdict(state=ACTION_STOP, stop=RECONCILE_STOP_SET_UNUSABLE,
                                detail=problem, terminal=False,
                                keeps_ticket_open=True, retryable=False)
    if platform is None and platform_factory is not None:
        try:
            platform = platform_factory()
        except PrFlowStop as e:
            return ReconcileVerdict(state=ACTION_STOP, stop=e.code,
                                    detail=e.message(), terminal=False,
                                    keeps_ticket_open=True, retryable=True)
        except Exception as e:  # noqa: BLE001
            return ReconcileVerdict(
                state=ACTION_STOP, stop=RECONCILE_STOP_REMOTE_UNREACHABLE,
                detail="the platform client could not be built: %s: %s"
                       % (type(e).__name__, e),
                terminal=False, keeps_ticket_open=True, retryable=True)
    if platform is None:
        return ReconcileVerdict(
            state=ACTION_STOP, stop=RECONCILE_STOP_REMOTE_UNREACHABLE,
            detail="no platform client is configured, so what was merged cannot "
                   "be read", terminal=False, keeps_ticket_open=True,
            retryable=False)
    runner = git_runner or _default_git_runner
    env = _git_env(git_env)
    default_target = str(args.get("target_branch") or DEFAULT_TARGET_BRANCH)
    default_remote = str(args.get("remote_name") or DEFAULT_REMOTE)
    rows: List[Dict[str, Any]] = []
    for entry in entries:
        rows.append(_reconcile_one(
            entry, platform=platform, git_runner=runner,
            git_timeout=float(git_timeout), env=env,
            target=str(entry.get("target_branch") or default_target),
            remote=str(entry.get("remote_name") or default_remote)))
    return _summarize(rows)


def reconcile_text(verdict: ReconcileVerdict, ticket_id: str = "") -> str:
    """The receipt/blocked text for a reconciliation: the state, every repository
    by name, the stop that failed and its remedy. Always redacted - a person must
    be able to read what happened without reading this console."""
    parts = ["post-merge reconciliation %s%s: %s"
             % (verdict.state or "(no state)",
                (", ticket " + str(ticket_id)) if ticket_id else "",
                verdict.detail or "no detail recorded")]
    if verdict.stop:
        parts.append("stop %s" % verdict.stop)
        parts.append("remedy: %s" % stop_remedy(verdict.stop))
    if verdict.keeps_ticket_open:
        parts.append("the ticket stays open")
    for row in verdict.repositories:
        parts.append("%s (%s) %s: %s"
                     % (row.get("name") or row.get("repo") or "?",
                        row.get("identity") or "no identity",
                        row.get("state") or "?",
                        row.get("detail") or "no detail recorded"))
    return redact(" | ".join(parts))


# ===========================================================================
# STEP (d) WIRED INTO THE STEP (c) CLOSE-OUT (t261103-13)
# ===========================================================================
#
# Step (d) shipped the reconciliation act with nothing calling it, so a platform
# merge could end a ticket while this machine's target branch stayed behind: the
# NEXT ticket is then judged against a tree that does not contain what the
# platform merged. This section is the wiring's brain, and it has three jobs:
#
#   1. decode the act's receipt (the workflow only ever holds a dict);
#   2. decide whether a merged delivery may close - and only a receipt that says
#      EVERY repository reconciled may. A stop, a partial reconciliation, a
#      switch that was turned off while parked, an unreadable receipt: each keeps
#      the ticket open with its named reason and the act's own remedy line;
#   3. name every reconciled repository in the close-out's receipt.
#
# It CALLS the act (`reconcile_after_merge`). It does not re-derive a
# fast-forward, does not read git and does not decide what "caught up" means:
# that judgement stays in one place, so the never-force / never-reset property
# has exactly one implementation to be true of.

#: Replay gate for the workflow side of this wiring. A history recorded before
#: this marker replays step (c)'s close-out verbatim: no reconciliation command
#: is scheduled, and the ticket closes exactly the way that history recorded.
PR_FLOW_RECONCILE_PATCH_ID = "dev-lane-pr-flow-reconcile-v1"


def reconcile_verdict_from(raw: Any) -> ReconcileVerdict:
    """Decode the reconciliation activity's receipt (the workflow's entry point).

    Fail-closed by construction: a receipt that is not an object, or that names
    no reconcilable state, is NOT read as "reconciled". It becomes a named refusal
    that keeps the ticket open - the close-out must never close on silence.
    """
    if isinstance(raw, ReconcileVerdict):
        return raw
    if not isinstance(raw, Mapping):
        return ReconcileVerdict(
            state=ACTION_STOP, stop=RECONCILE_STOP_RECEIPT_UNREADABLE,
            detail="the reconciliation returned %r, not a receipt, so it is not "
                   "taken as a reconciliation" % type(raw).__name__,
            terminal=False, keeps_ticket_open=True, retryable=True)
    state = str(raw.get("state") or "")
    stop = str(raw.get("stop") or "")
    detail = str(raw.get("detail") or "")
    rows = [dict(r) for r in (raw.get("repositories") or []) if isinstance(r, Mapping)]
    if state not in (RECONCILE_RECONCILED, RECONCILE_PARTIAL, RECONCILE_OFF,
                     ACTION_STOP):
        return ReconcileVerdict(
            state=ACTION_STOP, stop=stop or RECONCILE_STOP_RECEIPT_UNREADABLE,
            detail=("the reconciliation answered state %r, which this engine cannot "
                    "read, so nothing is taken as reconciled%s"
                    % (state or "(absent)", (" (%s)" % detail) if detail else "")),
            terminal=False, keeps_ticket_open=True, retryable=True, repositories=rows)
    return ReconcileVerdict(
        state=state, stop=stop, detail=detail,
        terminal=bool(raw.get("terminal")),
        keeps_ticket_open=bool(raw.get("keeps_ticket_open")),
        retryable=bool(raw.get("retryable")), repositories=rows)


def reconcile_allows_close(verdict: ReconcileVerdict) -> bool:
    """True only for a delivery whose every repository is proved caught up.

    Deliberately narrow: the act's own success state AND its `keeps_ticket_open`
    flag must agree, so a receipt that says "reconciled" while also saying "keep
    me open" cannot close a ticket. The `not_applicable` answer (the switch is
    off) is NOT a close permission either - the delivery reached the close-out
    because the flow was on, so "nothing to reconcile" means the engine lost the
    ability to prove the branch caught up, not that it did.
    """
    return verdict.state == RECONCILE_RECONCILED and not verdict.keeps_ticket_open


def reconciled_citations(verdict: ReconcileVerdict) -> List[Dict[str, Any]]:
    """The repositories the act reconciled, one row each, for the receipt."""
    out: List[Dict[str, Any]] = []
    for row in verdict.repositories:
        if str(row.get("state") or "") != REPO_STATE_RECONCILED:
            continue
        out.append(scrub({
            "name": str(row.get("name") or row.get("repo") or ""),
            "identity": str(row.get("identity") or ""),
            "target": str(row.get("target") or ""),
            "before": str(row.get("before") or ""),
            "after": str(row.get("after") or ""),
            "advanced": bool(row.get("advanced")),
        }))
    return out


def reconcile_record(verdict: ReconcileVerdict, *, ticket_id: str,
                     at_iso: str) -> Dict[str, Any]:
    """The ticket-face record of one reconciliation attempt.

    Everything a later reader needs without the console: the state, the stop with
    its remedy, whether the ticket may close, every repository by name, and the
    citations the close-out repeats.
    """
    rows = [dict(r) for r in verdict.repositories]
    cited = ["%s (%s) %s %s -> %s"
             % (c["name"] or "?", c["identity"] or "no identity",
                c["target"] or "the target branch",
                (c["before"] or "?")[:12], (c["after"] or "?")[:12])
             for c in reconciled_citations(verdict)]
    return scrub({
        "ticket": str(ticket_id or ""),
        "at": str(at_iso or ""),
        "state": verdict.state,
        "stop": verdict.stop,
        "detail": verdict.detail,
        "remedy": stop_remedy(verdict.stop) if verdict.stop else "",
        "reconciled": reconcile_allows_close(verdict),
        "keeps_ticket_open": not reconcile_allows_close(verdict),
        "repositories": rows,
        "cited": cited,
    })


def reconcile_citation(record: Any) -> str:
    """One line naming every reconciled repository (the close-out's receipt line).

    Reads the record `reconcile_record` wrote, so the close-out cannot cite
    repositories the reconciliation did not actually confirm: an empty citation
    is the honest answer when nothing reconciled.
    """
    src = record if isinstance(record, Mapping) else {}
    cited = [str(x) for x in (src.get("cited") or []) if str(x).strip()]
    return "; ".join(cited)
