#!/usr/bin/env python3
"""t261025-02 shared fixture: a minimal REAL lane for the UNPOINTED gate-round
journey (grey-box L3). Same replacement contract as
integration/t261024-40/lib_t26102440_lane.py (only the registry contents and
the scenario scripts are stubbed; the real run_scenarios.py source is copied
verbatim with a mini registry injected before the __main__ anchor; zero
internal symbols imported; anchor drift = fixture red, fail-closed). The
stub helpers are imported from that sibling lib - shared fixture helpers are
sanctioned reuse; only the lane shape below is this ticket's own (own-dir
marker integration/t261025-02/, and a spec shaped like the live witnesses:
an OWN entry in the ENGINE pool, an OWN entry in main, a NON-own entry in
exclusive)."""
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "t261024-40"))
import lib_t26102440_lane as SIB  # noqa: E402  (shared stub/fixture helpers)

REPO = SIB.REPO
RUNNER = SIB.RUNNER
MAIN_ANCHOR = SIB.MAIN_ANCHOR
# The live per-ticket gate shape: the two wholesale-excluded pools (the
# pools where the stuck witnesses' own scenarios live).
EXCLUDE_VALUE = "engine,exclusive"

# Fixture names: the engine-pool own entry mirrors t261022-12's witness.
OWN_ENGINE = "t261025-02-fx-own-engine"   # pool engine   (wholesale-excluded pool)
OWN_MAIN = "t261025-02-fx-own-main"       # pool main     (never excluded)
NONOWN_EXCL = "t261025-02-fx-nonown-excl"  # pool exclusive (non-own control)
SPEC = [(OWN_ENGINE, "engine"), (OWN_MAIN, None), (NONOWN_EXCL, "exclusive")]

# Re-exported shared helpers (single spelling across the two ticket dirs).
mini_script = SIB.mini_script
stage_stub_text = SIB.stage_stub_text
run_executor = SIB.run_executor
summary_line = SIB.summary_line
integ_summary = SIB.integ_summary
Checker = SIB.Checker


def build_lane(root, spec=SPEC, exclude_pools=EXCLUDE_VALUE):
    """Build a minimal lane at root. Fixture scripts live under
    integration/t261025-02/ inside the lane so the runner's own-set
    derivation (cmd path marker) sees the OWN entries. spec: [(name, pool)];
    None pool = main."""
    root = Path(root)
    own_dir = root / "integration" / "t261025-02"
    own_dir.mkdir(parents=True, exist_ok=True)
    (root / "server" / "engine").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "integration" / "lib_result.py",
                 root / "integration" / "lib_result.py")
    shutil.copy2(REPO / "server" / "engine" / "failure_protocol.py",
                 root / "server" / "engine" / "failure_protocol.py")
    shutil.copy2(REPO / "integration" / "lib_env.py",
                 root / "integration" / "lib_env.py")
    (root / "integration" / "stage_docker.py").write_text(stage_stub_text(),
                                                          encoding="utf-8")
    entries, markers = [], {}
    for name, pool in spec:
        f = own_dir / ("fx_%s.py" % name)
        marker = root / ("marker-%s" % name)
        f.write_text(mini_script(name, marker), encoding="utf-8")
        markers[name] = marker
        entries.append((name, "mini fixture entry (t261025-02)",
                        "python3 integration/t261025-02/fx_%s.py" % name,
                        pool or "main"))
    src = RUNNER.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.startswith(MAIN_ANCHOR)]
    if len(hits) != 1:
        raise AssertionError("runner __main__ anchor not unique (hits=%d) - "
                             "fixture must follow the anchor drift" % len(hits))
    lines.insert(hits[0], "SCENARIOS = %r\n\n" % (tuple(entries),))
    (root / "integration" / "run_scenarios.py").write_text("".join(lines),
                                                           encoding="utf-8")
    decl = ["schema: v1", "lanes:", "  code:", "    write_allow:",
            "      - server/", "integration:",
            "  cmd: python3 integration/run_scenarios.py"]
    if exclude_pools:
        decl.append("  exclude_pools: %s" % exclude_pools)
    (root / "verify.yaml").write_text("\n".join(decl) + "\n", encoding="utf-8")
    return {"lane": root, "entries": entries, "markers": markers}


def markers_ran(lane):
    """Reader-side execution evidence: which fixture markers exist on disk."""
    return sorted(n for n, p in lane["markers"].items() if p.exists())


def refused_face(out):
    """The REFUSED shape (stable substring; copy is text)."""
    return "REFUSED" in out
