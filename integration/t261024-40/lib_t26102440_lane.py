#!/usr/bin/env python3
"""t261024-40 shared fixture: a minimal REAL lane whose fixture entries live
under integration/t261024-40/ (the path marker the runner's own-set
derivation matches), plus roster/stage stubs for the own-scenario gate-round
journey (grey-box L3, modeled on integration/t260913-03/lib_pool_exclude_lane.py).

Replacement contract with the real runner (t260913-03 discipline, kept):
only two things are stubbed - the registry contents (mini table with REAL
pool fields) and the scenario scripts (one PASS/FAIL line + a marker file
proving execution). The real run_scenarios.py source is copied verbatim into
the fixture lane with the mini registry injected before the __main__ anchor;
zero internal symbols are imported. Anchor drift = fixture red, fail-closed.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parents[1]  # _HERE is the ticket dir: parent = integration/, grandparent = repo root
sys.path.insert(0, str(REPO / "integration"))
import lib_env  # noqa: E402  (narrowing-knob cleanup single point)

RUNNER = REPO / "integration" / "run_scenarios.py"
MAIN_ANCHOR = 'if __name__ == "__main__":'

OWN_DIR_TOKEN = "integration/t261024-40/"

# The incident's declared exclusion shape: the cheap pool itself excluded.
EXCLUDE_VALUE = "browser-free,exclusive"


def mini_script(name, marker):
    """Seconds-scale stub scenario: one PASS line + marker file on execution
    (the mechanical 'it really ran' evidence face, read from disk)."""
    return ("#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "print(\"PASS [%s]\")\n"
            "Path(%r).write_text('ran')\n" % (name, str(marker)))


def stage_stub_text():
    return ("#!/usr/bin/env python3\n"
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "cmd = args[0] if args else \"\"\n"
            "proj = args[args.index(\"--project\") + 1] if \"--project\" in args else \"stub\"\n"
            "if cmd == \"ensure\":\n"
            "    print(json.dumps({\"project\": proj, \"state\": \"up\", \"reused\": False,\n"
            "                      \"services\": [\"temporal\"],\n"
            "                      \"ports\": {\"temporal\": 21101, \"ui\": 21102},\n"
            "                      \"sa_registered\": True, \"container_ids\": {\"temporal\": \"stub\"}}))\n"
            "    sys.exit(0)\n"
            "if cmd == \"down\":\n"
            "    print(json.dumps({\"ok\": True, \"residue\": []}))\n"
            "    sys.exit(0)\n"
            "sys.exit(0)\n")


def build_lane(root, spec, exclude_pools=EXCLUDE_VALUE):
    """Build a minimal lane at root. spec: [(name, pool)] - every entry green;
    reds are composed via the roster, not the script. Fixture scripts live
    under integration/t261024-40/ inside the lane so the runner's own-set
    derivation (cmd path marker) sees them as the ticket's OWN set."""
    root = Path(root)
    own_dir = root / "integration" / "t261024-40"
    own_dir.mkdir(parents=True, exist_ok=True)
    (root / "integration" / "mini").mkdir(parents=True, exist_ok=True)
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
    for i, (name, pool) in enumerate(spec):
        f = own_dir / ("fx_%s.py" % name)
        marker = root / ("marker-%s" % name)
        f.write_text(mini_script(name, marker), encoding="utf-8")
        markers[name] = marker
        entries.append((name, "mini fixture entry (t261024-40)",
                        "python3 integration/t261024-40/fx_%s.py" % name, pool))
    src = RUNNER.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.startswith(MAIN_ANCHOR)]
    if len(hits) != 1:
        raise AssertionError("runner __main__ anchor not unique (hits=%d) - "
                             "fixture must follow the anchor drift" % len(hits))
    lines.insert(hits[0], "SCENARIOS = %r\n\n" % (tuple(entries),))
    (root / "integration" / "run_scenarios.py").write_text("".join(lines),
                                                           encoding="utf-8")
    decl = ["schema: v1", "lanes:", "  code:", "    write_allow:", "      - server/",
            "integration:", "  cmd: python3 integration/run_scenarios.py"]
    if exclude_pools:
        decl.append("  exclude_pools: %s" % exclude_pools)
    (root / "verify.yaml").write_text("\n".join(decl) + "\n", encoding="utf-8")
    return {"lane": root, "entries": entries, "markers": markers}


def roster_file(root, names, verdict="booked"):
    """Fixture known-red roster (same shape as the real baseline)."""
    p = Path(root) / "roster.json"
    p.write_text(json.dumps({"entries": [{"name": n, "verdict": verdict}
                                         for n in names]}), encoding="utf-8")
    return p


# SANCTIONED-WAIT: bounded subprocess budget = the `timeout` argument above (declared communicate() ceiling).
def run_executor(lane, env=None, timeout=120):
    cmd = [sys.executable, str(Path(lane) / "integration" / "run_scenarios.py")]
    e = lib_env.clean_narrowing_env()
    e.update({k: str(v) for k, v in (env or {}).items()})
    return subprocess.run(cmd, cwd=str(lane), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env=e, start_new_session=True)


def summary_line(out):
    for ln in out.splitlines():
        if ln.startswith("SCENARIOS "):
            return ln
    return ""


def integ_summary(out):
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except Exception:
                return None
    return None


def only_plan(lane, out):
    """The round's drop-attribution face (t261024-40 `only_plan`), read from
    the round's on-disk JSON report under the lane root
    (out/integration-report-*.json, newest first). ``out`` is the captured
    stdout of the same round, kept for signature clarity and used only to
    fall back to a None verdict when the report file is absent (a report-less
    round must read as 'no attribution face', never as a fabricated one)."""
    del out
    reports = sorted((Path(lane) / "out").glob("integration-report-*.json"),
                     reverse=True)
    for rp in reports:
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("only_plan"), dict):
            return data["only_plan"]
    return None


class Checker:
    def __init__(self, title):
        self.title = title
        self.passed = 0
        self.failed = 0

    def check(self, cond, label, detail=""):
        if cond:
            self.passed += 1
            print("  ok %s" % label)
        else:
            self.failed += 1
            print("  FAIL %s  [%s]" % (label, detail))
        return bool(cond)

    def finish(self):
        print("\n%s: SUMMARY pass=%d fail=%d env_fail=0 na=0"
              % (self.title, self.passed, self.failed))
        return 1 if self.failed else 0
