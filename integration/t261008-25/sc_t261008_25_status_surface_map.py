#!/usr/bin/env python3
"""t261008-25 scenario 2: exhaustive status-to-surface declaration (registry:
t261008-25-status-surface-map-exhaustive).

User-facing contract (KI-223 outcome 2): the failure behind KI-223 was a status class
(FAILED) silently landing outside every collection pass — each terminal class got its
own face except one, and nothing forced the faces to tile the status space. The fix
declares the status-to-surface mapping in ONE place, exhaustive, so a future terminal
class cannot silently fall through the gap again, and the docstring drift (the old
"TERMINATED is not collected" note, silent on FAILED) is dead.

Public-contract pins (gray-box source lock + behavior lock; offline seconds):
  M1 the declared map covers EVERY status Temporal can report — the key set equals
     the full WorkflowExecutionStatus name set (hardcoded in this scenario; a new
     engine status class missing from the map turns red, per the ticket's evidence
     requirement).
  M2 every terminal-but-not-completed class carries a terminal-archive exit face —
     FAILED, TERMINATED, CANCELED, TIMED_OUT are reachable by a designed disposition,
     not by nothing.
  M3 CONTINUED_AS_NEW never carries a terminal-class exit (KI-025 regression pin:
     never report live as terminal; board-only is declared, not accidental).
  M4 the collection queries actually implement the declared faces: every
     ExecutionStatus="<NAME>" literal in client.py names a status in the map (no
     rogue query that the declaration does not know about), and each filtered face
     (archive_cleanup / running / cancel_audit) keeps its declared status literal in
     a query — a face silently widened or narrowed turns red.
  M5 the docstring drift is dead: the archive-cleanup collection's docstring no
     longer declares "TERMINATED is not collected" as the whole story — it names the
     exhaustive declaration as the truth source.

Intent split: the map's unit-level truth table and the archive exit's parameter
matrix belong to developer L1 (integration/t261008-25 pytest files per the plan);
this entry owns the ENGINE-WIDE exhaustiveness face (a rogue literal or a missing
status class anywhere in client.py is exactly the KI-223 failure shape, and only a
whole-file scan sees it) plus the docstring-drift death. Pre-implement red expected
is N/A for M1–M3 (Step 1 landed first by design); M4/M5 must be green now, all legs
green at arbitrate/merge.
Run: PY=server/engine/.venv/bin/python; "$PY" -B integration/t261008-25/sc_t261008_25_status_surface_map.py (cwd=repo root)
"""
import inspect
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import lib_t26100825 as fx  # noqa: E402
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

# The full set of ExecutionStatus names Temporal's API defines (hardcoded: a NEW
# engine status class not in the map must turn this red — deriving the expectation
# from the map itself would make the test unfalsifiable).
ALL_TEMPORAL_STATUSES = {
    'COMPLETED', 'FAILED', 'CANCELED', 'TERMINATED', 'TIMED_OUT',
    'CONTINUED_AS_NEW', 'RUNNING',
}
TERMINAL_NOT_COMPLETED = {'FAILED', 'TERMINATED', 'CANCELED', 'TIMED_OUT'}

LEGS = []


def check(name, cond, detail=''):
    LEGS.append(bool(cond))
    print('[%s] %s%s' % ('PASS' if cond else 'FAIL', name, ('：' + detail) if detail else ''))


def main():
    m = getattr(fx.client_mod, '_STATUS_SURFACE_MAP', None)

    # ---- M1 exhaustiveness ----
    check('M1 status-to-surface map exists and is exhaustive over every Temporal status',
          isinstance(m, dict) and set(m.keys()) == ALL_TEMPORAL_STATUSES,
          'map_keys=%r missing=%r' % (sorted(m or {}), ALL_TEMPORAL_STATUSES - set(m or {})))

    # ---- M2 terminal classes all have a designed disposition ----
    check('M2 every terminal-but-not-completed class carries a terminal_archive face',
          bool(m) and all('terminal_archive' in m.get(s, ()) for s in TERMINAL_NOT_COMPLETED),
          'faces=%r' % {s: m.get(s) for s in TERMINAL_NOT_COMPLETED} if m else {})
    check('M2b the eligibility set is derived from the map (one truth)',
          getattr(fx.client_mod, '_ARCHIVE_TERMINAL_ELIGIBLE', None) ==
          (frozenset(s for s, f in (m or {}).items() if 'terminal_archive' in f)
           if m else None))

    # ---- M3 CONTINUED_AS_NEW never laundered into a terminal exit ----
    check('M3 CONTINUED_AS_NEW is board-only and declared as such (KI-025 pin)',
          bool(m) and set(m.get('CONTINUED_AS_NEW', ())) == {'board'})

    # ---- M4 the queries implement the declared faces ----
    try:
        src = inspect.getsource(fx.client_mod)
    except (OSError, TypeError) as e:
        print('ENV_FAIL: client.py source unreadable: %s: %s' % (type(e).__name__, e))
        return 2
    # Map keys are the canonical upper-case status names; Temporal wire query
    # literals are Title-case ("Completed") — compare case-insensitively, one truth.
    literals = {s.upper()
                for s in re.findall(r'ExecutionStatus="([A-Za-z_]+)"', src)}
    check('M4a no rogue status literal outside the declared map',
          literals <= set(m or {}), 'rogue=%r' % (literals - set(m or {}),))
    filtered_faces = {'COMPLETED': 'archive_cleanup', 'RUNNING': 'running',
                      'TERMINATED': 'cancel_audit'}
    for st, face in filtered_faces.items():
        check('M4b face=%s keeps its declared status literal ("%s") in a collection query'
              % (face, st),
              st in literals and face in (m or {}).get(st, ()),
              'literal_present=%s faces=%r' % (st in literals, (m or {}).get(st)))

    # ---- M5 docstring drift dead ----
    doc = fx.client_mod._closed_ticket_entries.__doc__ if hasattr(
        fx.client_mod, '_closed_ticket_entries') else ''
    check('M5 archive-cleanup docstring names the exhaustive declaration (drift dead)',
          ('_STATUS_SURFACE_MAP' in (doc or '')) and ('KI-223' in (doc or '')),
          'doc_head=%r' % ((doc or '').strip()[:200]))

    if all(LEGS):
        print('ALL GREEN (%d legs)' % len(LEGS))
        return EXIT_PASS
    print('RED legs=%d/%d' % (LEGS.count(False), len(LEGS)))
    return EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
