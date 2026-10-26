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
    """Map of new-file line numbers added in one path (unified diff input) to
    the REMOVED text each replaced (None = a pure addition). Removed and added
    runs inside a hunk are paired index-wise, so a -/+ pair at the same
    position counts as a replacement and carries its old text."""
    out = {}
    path = None
    old_lineno = 0
    new_lineno = 0
    removed = []          # [(old_lineno, text)] buffered run
    added = []            # [(new_lineno, text)] buffered run

    def flush():
        if path == rel_path:
            for i, (nl, ntext) in enumerate(added):
                out[nl] = removed[i][1] if i < len(removed) else None
        del removed[:], added[:]

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            flush()
            path = line[6:]
            continue
        if line.startswith("+++ "):
            flush()
            path = None
            continue
        if line.startswith("@@"):
            flush()
            m = re.search(r"-(\d+)", line)
            old_lineno = int(m.group(1)) - 1 if m else 0
            m2 = re.search(r"\+(\d+)", line)
            new_lineno = int(m2.group(1)) - 1 if m2 else 0
            continue
        if path is None:
            continue
        if line.startswith("-") and not line.startswith("---"):
            old_lineno += 1
            removed.append((old_lineno, line[1:]))
        elif line.startswith("+") and not line.startswith("+++"):
            new_lineno += 1
            added.append((new_lineno, line[1:]))
        elif line.startswith("\\"):
            continue
        else:
            flush()
            old_lineno += 1
            new_lineno += 1
    flush()
    return out


#: Launch-prefix tokens whose change is a MECHANICAL interpreter swap, never a
#: tier-relevant change (t261026-35: migrating the registry's python legs to
#: integration/py_interp.sh must not demand tier markers from ~50 legacy
#: expensive entries — the tier page: cleanup is its own ticket). A -/+ line
#: pair that differs ONLY in these tokens is not a "changed entry"; a changed
#: script path, pool token or intent still is.
_LAUNCH_TOKENS = [
    r'PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || ',
    r'PY=../../server/engine/.venv/bin/python; [ -x \"$PY\" ] || ',
    r'PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || ',
    'PY=python3; ',
    r'\"$PY\" -B ',
    r'\"$PY\" ',
    'sh integration/py_interp.sh ',
    'PYTHONPYCACHEPREFIX=out/pycache ',
    'python3 -B ',
    'python3 ',
    '-B ',
]


def strip_launch_prefix(line):
    """The line with every known interpreter launch token removed (repeatedly,
    any order). Equality of two stripped lines = the swap was mechanical."""
    s = line
    again = True
    while again:
        again = False
        for tok in _LAUNCH_TOKENS:
            if tok in s:
                s = s.replace(tok, "")
                again = True
    return s.strip()


def changed_entry_names(file_text, diff_text, rel_path=REGISTRY_REL):
    """Names of registry entries whose source lines were added or changed.

    Entries are the 4-space-indented `("name",` tuples of SCENARIOS; an entry
    counts as changed when ANY of its lines (start line up to the next entry
    start) is an added line in the diff whose content really changed — a -/+
    pair differing only in interpreter launch tokens (strip_launch_prefix) is
    a mechanical swap, not a change (t261026-35). Garbage diff text yields an
    empty set (no crash, nothing invented)."""
    added = added_lines_in_path(diff_text, rel_path)
    if not added:
        return set()
    lines = file_text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r'^ {4}\("[^"]+",', ln)]
    changed = set()
    for idx, i in enumerate(starts):
        m = re.match(r'^ {4}\("([^"]+)",', lines[i])
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        for n in range(i, end):
            if (n + 1) not in added:
                continue
            old_text = added[n + 1]          # None = a pure addition
            if old_text is not None and \
                    strip_launch_prefix(old_text) == \
                    strip_launch_prefix(lines[n]):
                continue
            changed.add(m.group(1))
            break
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
