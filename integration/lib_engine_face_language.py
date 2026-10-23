#!/usr/bin/env python3
"""Engine ticket-face language contract (t261021-11): engine-produced text that
lands on the ticket face or the console must be English (ASCII template text).

Standing rule: ticket-face text is English (host order 260924); console UI copy
is English and data is not translated (host order 260925). Engine-generated
Chinese on the ticket face is a defect, not a style choice (observed live on
t261021-05: gate refusal rendered `only 甲、乙、丙`; auto-quarantine trailer
rendered `；本轮已自动处置：%s`).

This module is the single declared contract:

- FACE_FIELD_PATHS — the declared surface list: exactly the field paths the
  engine produces and the ticket face or console displays.
- is_face_string(field_path) — the one predicate answering whether a produced
  string sits on the declared surface.
- CJK_FACE_RE / find_cjk / face_violations — the character predicate. CJK
  punctuation (U+3000 block) and fullwidth forms count: a CJK separator inside
  a joined list is a defect even when every element is English. Note that
  integration/lint_copy_language.py is deliberately punctuation-blind (it
  targets per-diff text, not typography); this contract is the wider face.
- producer_location() — module:line attribution for failure messages only.
  Per review condition (t261021-11 review_plan): attribution must never be
  asserted against, and degrades to module-name attribution when
  inspect.getsourcelines is unavailable.

Console-facing engine labels — declared covered, with the written reason the
review asked for: the engine emits only identifiers on the console label paths
(stage id, stage_state, status), and those identifiers are already English by
the engine's own tables (server/engine/path_gates.py STAGE_PATH_RULES stage
ids; the stage_state and status vocabularies). The frontend maps identifiers to
labels and is forbidden from inventing words (CLAUDE.md rule 6). Console copy
produced outside the engine is guarded per-diff by integration/lint_copy_language.py.
The identifier tables stay under the producer-module sweep of
lint_engine_face_language.py, so a Chinese identifier cannot land silently.

Data is never translated: a ticket title written by an agent, a user note, a
document excerpt and a scenario name stay exactly as written. The check design
pins this: fixtures always pass ASCII-only data and assert the produced face is
pure ASCII; a data-passthrough test asserts that with CJK data the only CJK in
the produced face is the data itself.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]

# CJK ideographs (incl. ext A and compat), kana, CJK punctuation and symbols
# (U+3000-U+303F: 、。；：「」 etc.) and fullwidth forms (U+FF00-U+FFEF：；％ etc.).
# Separators count — see module docstring.
CJK_FACE_RE = re.compile(
    "[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]")

#: Debt ticket named by the review: the engine conversion (the two named
#: sources and the rest of the defect inventory) rides as handover because the
#: write set of this ticket is integration/ only. The inventory allowlists
#: `defect` hits under this tag until the conversion lands.
DEBT_TAG = "t261021-11"

# ---------------------------------------------------------------------------
# Declared surface list
# ---------------------------------------------------------------------------
# Each entry: field path -> {"kind": human label, "producers": [anchor strings]}
# where an anchor names the engine function that produces the field. Anchors
# are attribution metadata, not assertions.
FACE_FIELD_PATHS: Dict[str, Dict[str, Any]] = {
    "log[].note": {
        "kind": "settle/verify receipts appended to the ticket timeline",
        "producers": [
            "server/engine/path_gates.py:gate_refusal_note",
            "server/engine/path_gates.py:gate_refusal_unknown",
            "server/engine/agent_activities.py:settle note joins (remediation, "
            "fresh_diag, staging and commit receipts)",
            "server/engine/authz_gates.py:authorized_passage_note",
        ],
    },
    "blocked_detail.check_id": {
        "kind": "structured red-light detail on the ticket detail page",
        "producers": ["server/engine/path_gates.py:gate_red_detail"],
    },
    "blocked_detail.item": {
        "kind": "structured red-light detail on the ticket detail page",
        "producers": ["server/engine/path_gates.py:gate_red_detail"],
    },
    "blocked_detail.reason_code": {
        "kind": "structured red-light detail on the ticket detail page",
        "producers": ["server/engine/path_gates.py:gate_red_detail"],
    },
    "blocked_detail.next_action": {
        "kind": "structured red-light detail on the ticket detail page",
        "producers": [
            "server/engine/path_gates.py:next_action_hint",
        ],
    },
    "blocked_detail.evidence": {
        "kind": "structured red-light detail (the note verbatim, so the face "
                "matches the worker log); template side must be ASCII, data "
                "passes through untranslated",
        "producers": ["server/engine/path_gates.py:gate_red_detail (evidence "
                      "= the gate refusal note verbatim)"],
    },
    "pending[].note": {
        "kind": "pending-entry note maintained by update_status",
        "producers": ["server/engine/base.py:update_status (pending_add)"],
    },
    "executor_request.question": {
        "kind": "executor request card; engine emits the envelope only — the "
                "question text is caller data and stays as written; the "
                "engine-side validation/refusal strings are internal CLI "
                "usage (stderr), not card copy",
        "producers": ["server/engine/executor_requests.py:card/payload builders"],
    },
    "executor_request.detail": {
        "kind": "executor request card; caller data, stays as written",
        "producers": ["server/engine/executor_requests.py:card/payload builders"],
    },
    "console_labels.identifiers": {
        "kind": "stage id / stage_state / status identifiers emitted by the "
                "engine and mapped to labels by the frontend (already-English "
                "identifier tables; see module docstring for the declared "
                "reason this item is covered rather than dropped)",
        "producers": [
            "server/engine/path_gates.py:STAGE_PATH_RULES (stage ids)",
            "server/engine stage_state/status vocabularies",
        ],
    },
}

#: Flat set for fast predicate lookup.
_FACE_PATHS = frozenset(FACE_FIELD_PATHS)


def is_face_string(field_path: Any) -> bool:
    """The one predicate: is a produced string on the declared ticket face?

    Accepts only exact declared field paths. Malformed input (None, empty,
    non-string) is not on the face — the predicate answers False rather than
    raising, so callers can feed it raw incoming shapes.
    """
    return isinstance(field_path, str) and field_path in _FACE_PATHS


# ---------------------------------------------------------------------------
# Character predicate + attribution
# ---------------------------------------------------------------------------

def find_cjk(text: Any) -> List[Tuple[int, str]]:
    """All CJK characters (incl. CJK punctuation / fullwidth) as (offset, char).

    Malformed input (None, non-str) yields [] — the check reports on strings,
    it does not crash on shapes.
    """
    if not isinstance(text, str):
        return []
    return [(m.start(), m.group(0)) for m in CJK_FACE_RE.finditer(text)]


def _char_name(ch: str) -> str:
    try:
        return unicodedata_name(ch)
    except Exception:  # noqa: BLE001 — attribution nicety only
        return "?"


def unicodedata_name(ch: str) -> str:
    import unicodedata
    return unicodedata.name(ch, "?")


def face_violations(text: Any, what: str = "engine face string",
                    producer: str = "") -> List[str]:
    """Human-readable violations for one produced string.

    Each violation names the offending character, its Unicode name, its offset
    and — when known — the producer anchor, so the failure points at the module
    that produced the Chinese instead of at the caller.
    """
    out = []
    for off, ch in find_cjk(text):
        out.append("%s carries CJK %r (U+%04X %s) at offset %d%s"
                   % (what, ch, ord(ch), _char_name(ch), off,
                      " (producer: %s)" % producer if producer else ""))
    return out


def producer_location(func: Any) -> str:
    """module:line attribution for a producer callable — messages only.

    Review condition 2: no assertion may depend on this; if introspection fails
    (worktree layouts, builtins, partials) degrade to the qualified name or to
    "<unknown>" without weakening the predicate.
    """
    try:
        return "%s:%d" % (func.__module__, inspect.getsourcelines(func)[1])
    except Exception:  # noqa: BLE001 — attribution degrades, never blocks
        pass
    name = getattr(func, "__qualname__", None) or getattr(func, "__name__", None)
    return "%s (%s)" % (getattr(func, "__module__", "?"), name) if name else "<unknown>"


# ---------------------------------------------------------------------------
# Static sweep helpers (shared by the lint and the source-anchored tests)
# ---------------------------------------------------------------------------

#: Producer modules swept by lint_engine_face_language.py. Exactly the modules
#: the declared surface list anchors to; console copy outside the engine is
#: lint_copy_language.py's per-diff face.
PRODUCER_MODULES = [
    "server/engine/path_gates.py",
    "server/engine/agent_activities.py",
    "server/engine/base.py",
    "server/engine/executor_requests.py",
    "server/engine/authz_gates.py",
]

#: Mechanical classification rules (the written rule the review asked for).
#: Applied in order; first match wins; everything else defaults to `defect`
#: (fail-closed bias: a string that cannot be proven off-face is treated as a
#: defect until converted or certified in the inventory).
#:
#: R1 comment            — token is a comment: out of scope per the ticket.
#: R2 docstring          — token is a module/class/function docstring: out of
#:                         scope per the ticket.
#: R3 prompt             — string inside a function whose name contains
#:                         `prompt`: text sent to models, not UI.
#: R4 internal-cli       — usage/help text of internal CLI tools (strings
#:                         assigned to *USAGE* names, argparse help=, or
#:                         inside a function whose name contains `usage`).
#: R5 log-only           — string is an argument of a logger/print call on the
#:                         same physical line AND the module's log sink never
#:                         feeds a face field (worker log only). A string that
#:                         is merely *printed later* is NOT log-only — notes
#:                         built into a variable and returned land on the face
#:                         and default to defect.
#: R6 inventory override — classification certified in
#:                         integration/engine_face_language_inventory.json
#:                         with written evidence (e.g. legitimate data).
#: R7 defect             — default.
CLASSIFICATION_RULES = ["comment", "docstring", "prompt", "internal-cli",
                        "log-only", "inventory-override", "defect"]


def strip_comment(text: str) -> str:
    """Naive in-line comment strip (code-part of a line). Good enough for the
    log-only line regex; token-level COMMENT handling in the lint is exact."""
    idx = text.find("#")
    return text if idx == -1 else text[:idx]


def cjk_in_code_line(text: str) -> bool:
    """CJK anywhere in the code part of one physical line (comment stripped
    naively). Used by the source-anchored tests to bind to surviving literals
    without depending on line numbers."""
    return bool(CJK_FACE_RE.search(strip_comment(text)))
