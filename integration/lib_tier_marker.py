#!/usr/bin/env python3
"""Tier-marker lint core (L21, t261004-42): the end-to-end admission rule made
mechanical, shape-only.

Source rule: docs/reference/test-tiers-and-e2e-admission.md — every scenario
registered in an EXPENSIVE pool (engine / browser / exclusive) whose registry
entry was ADDED or CHANGED in the diff must declare, inside its intent text:

  tier:<text>   — non-empty free text naming the seam or the journey (the
                  truth of the text is NEVER judged here; a human review row
                  and the inspection do that);
  cost:<class>  — runtime class from COST_VOCAB.

Declared cost vocabulary (condition C2 of the plan review, one readable home):
  seconds — the case runs in seconds (cheap-ish end of L3, e.g. an offline
            contract face registered in an expensive pool only for isolation);
  minutes — the case runs minutes (the page's L3 row: 0.5 to 12 minutes per
            case). Coarse cheap-vs-minutes classes on purpose; a finer class
            later is a one-line vocabulary extension plus one battery case.

Absent or malformed = defect, and each defect NAMES the scenario and which
part is missing. Added/changed-only scope mirrors the copy-language gate:
legacy entries are never inspected, so the 95 existing expensive cases stay
untouched (the page: cleanup is its own ticket).

Pure functions only (zero IO, unit battery = integration/test_tier_marker_lint.py);
the battery wrapper lives in lint_tests.py (L21).
"""
import re

EXPENSIVE_POOLS = ("engine", "browser", "exclusive")
COST_VOCAB = ("seconds", "minutes")
# The registry file that holds SCENARIOS (single registry, per run_scenarios.py).
REGISTRY_REL = "integration/run_scenarios.py"

TIER_RE = re.compile(r"\btier:[ \t]*([^\n]*)")
COST_RE = re.compile(r"\bcost:\s*([A-Za-z0-9_-]+)")


def marker_defects(intent):
    """Return the list of marker defects for one intent text (empty = clean).

    Shape-only: presence and declared shape, never the truth of the text."""
    defects = []
    m = TIER_RE.search(intent or "")
    if not m:
        defects.append("tier: token missing (name the seam or the journey)")
    else:
        value = m.group(1).strip()
        # `tier:` whose value is just the cost token that follows is empty
        # (`tier: cost: seconds`) — the justification names nothing.
        if not value or value.startswith("cost:"):
            defects.append("tier: value empty (name the seam or the journey)")
    c = COST_RE.search(intent or "")
    if not c:
        defects.append("cost: token missing (declare the runtime class)")
    elif c.group(1) not in COST_VOCAB:
        defects.append("cost: value %r outside the declared vocabulary %s"
                       % (c.group(1), "/".join(COST_VOCAB)))
    return defects


def added_lines_in_path(diff_text, rel_path):
    """Set of new-file line numbers added in one path (unified diff input)."""
    added = set()
    for path, lineno, _text in _added_lines(diff_text):
        if path == rel_path:
            added.add(lineno)
    return added


def _added_lines(diff_text):
    # Local copy of the shared parser shape (kept dependency-free so this
    # module stays pure; lint_copy_language owns the lib_lint_diff import).
    path = None
    new_lineno = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if line.startswith("+++ "):
            path = None
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_lineno = int(m.group(1)) - 1 if m else 0
            continue
        if path is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_lineno += 1
            yield path, new_lineno, line[1:]
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            new_lineno += 1


def changed_entry_names(file_text, diff_text, rel_path=REGISTRY_REL):
    """Names of registry entries whose source lines were added or changed.

    Entries are the 4-space-indented `("name",` tuples of SCENARIOS; an entry
    counts as changed when ANY of its lines (start line up to the next entry
    start) is an added line in the diff. Garbage diff text yields an empty set
    (no crash, nothing invented)."""
    added = added_lines_in_path(diff_text, rel_path)
    if not added:
        return set()
    lines = file_text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r'^ {4}\("[^"]+",', ln)]
    changed = set()
    for idx, i in enumerate(starts):
        m = re.match(r'^ {4}\("([^"]+)",', lines[i])
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        if any((n + 1) in added for n in range(i, end)):
            changed.add(m.group(1))
    return changed


def check_registry(entries, changed_names):
    """Core check over a registry table. `entries` = (name, intent, pool)
    triples (pool already resolved via pool_of semantics); `changed_names` =
    the added/changed entry names from the diff. Returns defect strings, each
    naming the scenario and the missing part."""
    out = []
    for name, intent, pool in entries:
        if pool not in EXPENSIVE_POOLS or name not in changed_names:
            continue
        for d in marker_defects(intent):
            out.append("%s: %s" % (name, d))
    return out
