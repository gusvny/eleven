#!/usr/bin/env python3
"""Wait-bound lint core (L25, t261011-22): a test may not buy its evidence with
real wall-clock minutes.

Source rule: host order 261011 (round budget analysis — one line round spent
59.6 minutes serial across 688 scenarios, and its biggest items were tests
whose evidence was "I waited the real timeout": a 600 s real-time wait for an
arbitration state, a full-tree lint run twice, a 300 s poll for a planted
fixture). A waited bound must be INJECTABLE (the engine's `wait_bound_ms` on
`ticket_wait_state` is the precedent): a scenario sets the bound it waits on to
seconds and asserts that the bound fired and the refusal NAMED the failing
check — it never sleeps the production bound.

Mechanical face (per-diff, copy-gate construction — mirrors L15/L21): an ADDED
line under `integration/` that declares a large real-time bound is a defect
naming file:line and WHICH pattern matched, unless the line (or the line
directly above it) carries the explicit exemption marker `SANCTIONED-WAIT:`
with a reason — the `L10-allow:` precedent (silent != exempt). Deleted and
context lines are never judged; legacy bounds already on the tree are
grandfathered exactly like the other per-diff rules.

Borrowed-implementation fault-mode ledger (review discipline, t261011-22):
  - `parse_added_lines` (lib_lint_diff): malformed/short diff text — TOTAL,
    never raises, context/deleted lines never yield (carried; battery owns a
    malformed-input case);
  - base unresolvable — NOT handled here; the wrapper in lint_tests.py owns
    the fail-closed warn-and-skip with a visible line (same shape as L21);
  - strings that merely LOOK like bounds
    # SANCTIONED-WAIT: docstring quoting the judged shape, not a real bound
    (a docstring quoting `timeout=1200`, a comment) — judged the same as code
    (the rule is textual by design); the SANCTIONED-WAIT escape is reachable
    for those too, on the same line or the line above.

Pure functions only (zero IO, zero git): the unit battery owns the truth
table; the L25 wrapper in lint_tests.py owns base resolution and the diff.
"""
import re

from lib_lint_diff import parse_added_lines

#: The exemption marker. Must carry a reason after it (shape-only: non-empty
#: rest-of-line is checked by `sanctioned`).
SANCTION = "SANCTIONED-WAIT:"

#: Only scenario/test assets under integration/ are in scope; engine tests are
#: pytest territory with their own bound conventions (`wait_bound_ms`), and
#: product code never waits on test bounds.
SCOPE_PREFIX = "integration/"

#: The wait shapes judged. Names are printed verbatim in the defect line so a
#: reader sees WHICH pattern matched, not a bare "no sanctioned wait found".
#:
#: - `deadline=` / `timeout=` with a literal of 3+ digits (>= 100 s): a
#:   ceiling on a real-time wait measured in minutes. A sanctioned child-process
#:   ceiling (a subprocess hard kill after N s) is exactly what the escape is
#:   for; a poll bound the test then SLEEPS to is the defect.
#: - `sleep(<2-digit literal>` / `sleep(<3-digit literal>`: a literal sleep of
#:   10+ seconds inside a test is patience posing as evidence.
WAIT_PATTERNS = (
    ("deadline", re.compile(r"\bdeadline\s*=\s*\d{3,}\b")),
    ("timeout", re.compile(r"\btimeout\s*=\s*\d{3,}\b")),
    ("sleep", re.compile(r"\bsleep\(\s*\d{2,}\b")),
)


def sanctioned(line, prev_line=None):
    """True when the line carries the exemption, or the line directly above
    it does (whole-line reason comment convention, like L10-allow)."""
    return SANCTION in (line or "") or SANCTION in (prev_line or "")


def wait_bound_hits(line, prev_line=None):
    """Return the list of pattern names matching one line (empty = clean).

    Total on None/empty input; a sanctioned line is clean by construction."""
    if sanctioned(line, prev_line):
        return []
    return [name for name, rx in WAIT_PATTERNS if rx.search(line or "")]


def added_wait_defects(diff_text):
    """Yield (path, lineno, pattern_name, line_text) for ADDED lines under
    integration/ that declare a real-time wait without a sanction.

    Malformed diff text is total input (parse_added_lines never raises); a
    diff with no integration/ hunks yields nothing."""
    prev = {}
    for path, lineno, text in parse_added_lines(diff_text or ""):
        if not path.startswith(SCOPE_PREFIX):
            prev[path] = text
            continue
        for name in wait_bound_hits(text, prev.get(path)):
            yield path, lineno, name, text
        prev[path] = text
