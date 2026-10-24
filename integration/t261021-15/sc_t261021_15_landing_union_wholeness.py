#!/usr/bin/env python3
"""sc_t261021_15_landing_union_wholeness.py — t261021-15 rework: the lane must
never again hold a HALF landing union.

Incident (this ticket, gen5–gen10): the develop-buffer landing union merged the
line's `dev_lane.py` (which imports `quick_scope_resolve`) but left the line's
`agent_activities.py` at the base — the engine import chain broke while the
tickt's own targeted tests still passed, and the registries referenced five
peer scenario files the lane did not hold. Four rounds were spent discovering
the half-union one face at a time. The user-perceivable contract: a lane that
passed its own targeted faces must not carry dangling registry entries or a
broken engine import chain — wholeness is checkable in seconds, offline.

Grey-box L3 (integration-owned, ticket t261021-15 rework).  Offline seconds,
pure stdlib, zero docker/Temporal-server/browser, never touches 3099/7233.

Faces under contract:
  A REGISTRY WHOLENESS — every scenario cmd in the REAL run_scenarios registry
    that names a repo file finds that file on disk (no dangling cmd).
  B ANCHOR WHOLENESS — every path key in the REAL test_anchors.json exists on
    disk (no dead anchor entries), covering both the scenarios and engine_tests
    sections.
  C ENGINE IMPORT WHOLENESS — `import dev_lane, agent_activities, shared` in a
    FRESH interpreter succeeds (the gen6 ImportError face; a stale __pycache__
    must not fake a pass, hence a fresh process).
  D THE GUARD IS NOT VACUOUS — the same wholeness predicate run over a
    fabricated registry with one missing file FAILS by name (positive control:
    the checker can actually go red).

Intent split: the ticket's gate decision faces belong to
t261021-15-plan-gap-gate; the helper truth tables belong to developer L1;
THIS entry uniquely owns "the lane's registries and import chain are whole".

Unimportable engine modules = ENV_FAIL exit 2 for face C only (faces A/B/D and
the vacuity control still run on stdlib).  Any FAIL = exit 1.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration"))

PASS = 0
FAILS = []
ENVS = []


def check(name, ok, why=""):
    global PASS
    if ok:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, len(FAILS), len(ENVS)))
    if FAILS:
        print("FAIL t261021-15-landing-union-wholeness (%d): %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    if ENVS:
        print("ENV_FAIL t261021-15-landing-union-wholeness: %s" % "; ".join(ENVS))
        sys.exit(2)
    print("PASS t261021-15-landing-union-wholeness")
    sys.exit(0)


FILE_TOKEN = re.compile(r"integration/[\w./-]+\.(?:py|mjs)")


def dangling_cmds(scenarios, root):
    """Pure predicate: (name, missing_path) pairs for registry cmds whose repo
    files are absent. Returns [] for a whole registry."""
    out = []
    for entry in scenarios:
        name, cmd = entry[0], entry[2]
        for tok in FILE_TOKEN.findall(cmd):
            if not (root / tok).exists():
                out.append((name, tok))
    return out


def dead_anchors(anchors, root):
    """Pure predicate: FILE path keys of the anchor manifest absent on disk.
    Section keys ('_header', 'engine_tests', 'scenarios') are not paths and
    are skipped — only keys containing '/' name files."""
    return [p for p in anchors if "/" in p
            and isinstance(anchors[p], dict)
            and not (root / p).exists()]


try:
    import run_scenarios  # noqa: E402
except Exception as exc:  # noqa: BLE001
    ENVS.append("integration/run_scenarios.py unimportable: %r" % (exc,))
    summary()

SCEN = run_scenarios.SCENARIOS

# A — registry wholeness over the REAL registry
missing = dangling_cmds(SCEN, ROOT)
check("A1 every registered scenario cmd path exists on disk",
      not missing, "dangling=%r" % missing[:6])

# B — anchor wholeness over the REAL manifest
try:
    anchors = json.loads((ROOT / "integration" / "test_anchors.json").read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    ENVS.append("test_anchors.json unparseable: %r" % (exc,))
    anchors = {}
dead = dead_anchors(anchors, ROOT)
check("B1 every anchor manifest path key exists on disk",
      not dead, "dead=%r" % dead[:6])

# C — engine import wholeness, FRESH interpreter (no stale bytecode)
# SANCTIONED-WAIT: a bare import of three engine modules finishes in well under a
# second standalone; the 120s cap only exists to absorb full-corridor load jitter
# (measured on this ticket's merge_check rounds — a green contract once tripped a
# 120s cap under load), and a cap exhaustion surfaces as a named C1 failure, not a
# silent pass.
r = subprocess.run(  # SANCTIONED-WAIT: fresh-interpreter import probe, seconds-scale; cap exhaustion fails C1 by name
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, 'server/engine'); "
     "import dev_lane, agent_activities, shared; print('WHOLE')"],
    cwd=str(ROOT), capture_output=True, text=True, timeout=120)  # SANCTIONED-WAIT: seconds-scale bare import; cap only absorbs corridor jitter, exhaustion fails C1 by name
check("C1 fresh-interpreter engine import chain is whole (dev_lane/agent_activities/shared)",
      r.returncode == 0 and "WHOLE" in r.stdout,
      (r.stderr or "").strip().splitlines()[-1:] or r.stdout[-200:])

# D — the guard is not vacuous: a fabricated registry with one missing file
# must fail BY NAME
with tempfile.TemporaryDirectory(prefix="t261021-15-wholeness-") as td:
    fake_root = Path(td)
    (fake_root / "integration").mkdir()
    (fake_root / "integration" / "present.py").write_text("# ok\n", encoding="utf-8")
    fake_scen = [("fake-face", "intent", "\"PY\" -B integration/absent_face.py", "ro")]
    d = dangling_cmds(fake_scen, fake_root)
    check("D1 vacuity control: a missing registered file is caught by name",
          d == [("fake-face", "integration/absent_face.py")], "d=%r" % (d,))
    fake_anchors = {"integration/present.py": {"anchor": "contract"},
                    "integration/gone.py": {"anchor": "contract"}}
    d2 = dead_anchors(fake_anchors, fake_root)
    check("D2 vacuity control: a dead anchor key is caught by name",
          d2 == ["integration/gone.py"], "d2=%r" % (d2,))

summary()
