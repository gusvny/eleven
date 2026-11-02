#!/usr/bin/env python3
"""t261102-40 own-scenario fixture: a minimal REAL suite lane whose bench-module
asset is a knob (``real`` / ``absent`` / ``broken``).

What is real: ``integration/run_scenarios.py`` copied verbatim (the ticket's mini
registry is injected before the ``__main__`` anchor, the same fail-closed anchor
check the sibling lanes use), the prelude, the test-target provision, the child
spawns and the round receipt. What is stubbed: the registry contents (two
seconds-scale scripts that print PASS and write a marker file) and
``stage_docker.py`` (the prelude's sweep leg calls it).

The nested env is built by ``lib_suite_prelude.nested_suite_env`` - one spelling
for the lane side of the contract: ``lib_env.clean_narrowing_env`` (the cleaning
point), then the inherited test-target statement is cleared (a nested suite
resolves its own target; the parent round's statement would send the nested
prelude down the ambient branch and hide the degradation this ticket proves),
then the lane-private bench registry is pinned (KI-161: never the host-wide
store).

The lane also pins its own scenario-ledger dir and its own run-lock path, so two
rounds of this scenario cannot share ledger rows or contend for the parent
round's single-flight lock.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parents[1]
if str(REPO / "integration") not in sys.path:
    sys.path.insert(0, str(REPO / "integration"))
import lib_env  # noqa: E402,F401  (260930 cleaning point; nested_suite_env calls it)
import lib_suite_prelude as PRELUDE  # noqa: E402  (t261102-40 lane prelude contract)

RUNNER = REPO / "integration" / "run_scenarios.py"
MAIN_ANCHOR = 'if __name__ == "__main__":'

#: One spelling: the shared prelude contract module owns the bound the
#: scenario holds a nested round's prelude to.
PRELUDE_BOUND_S = PRELUDE.PRELUDE_BOUND_S

#: One round's hang guard. Measured on this host: a nested round costs 2-5 s warm
#: and about 22 s in the daemon-down state (20 s bounded probe + the round). The
#: guard is a hang guard, never a performance assertion.
ROUND_WAIT_S = 60

#: The two stub entries: main and ro pools, so the batch preboot leg has zero
#: consumers (no docker stage is involved in this scenario).
MINI = (("t261102-40-fx-main", "main"), ("t261102-40-fx-ro", "ro"))

#: A module that is PRESENT but raises at import: the "code fault" wording case.
BROKEN_BENCH = ('"""Deliberately broken bench module (t261102-40 case C)."""\n'
                'raise RuntimeError("broken bench module (t261102-40 case C)")\n')


def stage_stub_text():
    """The lane's stage_docker stub: sweep is silent; ensure/down answer the
    public receipt shape the batch leg consumes (no docker, no port)."""
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


def mini_script(name, marker):
    """Seconds-scale stub entry: one PASS line and an on-disk execution marker."""
    return ("#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "print(\"PASS [%s]\")\n"
            "Path(%r).write_text('ran')\n" % (name, str(marker)))


def nested_env(lane_root, extra=None):
    """The nested round's env: cleaned, target cleared, extras, registry pinned."""
    lane_root = Path(lane_root)
    declared = {
        # A fresh lane per case: no shared ledger rows, so the reuse economy can
        # never substitute for the round this case judges.
        "SANDBAR_SCENARIO_LEDGER_DIR": str(lane_root / ".scenario-ledger"),
        # The lane's own single-flight lock (the parent round holds the lane key,
        # not this one; the explicit path keeps the two apart on every platform).
        "SANDBAR_INTEG_RUN_LOCK_PATH": str(lane_root / ".run.lock"),
        # The lane is the import root: a nested run must never resolve
        # process_bench.py from an inherited path.
        "PYTHONPATH": str(lane_root / "integration"),
    }
    declared.update({str(k): str(v) for k, v in (extra or {}).items()})
    return PRELUDE.nested_suite_env(declared, lane_root)


def build_lane(root, asset="real"):
    """Build the lane at ``root`` with the bench-module asset the case needs.

    asset: "real" (copy the prelude assets), "absent" (the incident shape: the
    lane carries the runner and the judge-face modules only), or "broken" (a
    module that is present and raises at import).
    """
    root = Path(root)
    integ = root / "integration"
    integ.mkdir(parents=True, exist_ok=True)
    (root / "server" / "engine").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "integration" / "lib_result.py", integ / "lib_result.py")
    shutil.copy2(REPO / "integration" / "lib_env.py", integ / "lib_env.py")
    shutil.copy2(REPO / "server" / "engine" / "failure_protocol.py",
                 root / "server" / "engine" / "failure_protocol.py")
    (integ / "stage_docker.py").write_text(stage_stub_text(), encoding="utf-8")
    if asset == "real":
        PRELUDE.copy_prelude_assets(integ)
    elif asset == "absent":
        pass
    elif asset == "broken":
        (integ / "process_bench.py").write_text(BROKEN_BENCH, encoding="utf-8")
    else:
        raise ValueError("build_lane: unknown bench asset %r (want real/absent/broken)"
                         % (asset,))

    entries, markers = [], {}
    for name, pool in MINI:
        marker = root / ("marker-%s" % name)
        script = integ / ("fx_%s.py" % name)
        script.write_text(mini_script(name, marker), encoding="utf-8")
        markers[name] = marker
        entries.append((name, "mini fixture entry (t261102-40)",
                        "python3 integration/fx_%s.py" % name, pool))

    src = RUNNER.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.startswith(MAIN_ANCHOR)]
    if len(hits) != 1:
        raise AssertionError("runner __main__ anchor not unique (hits=%d) - the "
                             "fixture must follow the anchor drift" % len(hits))
    lines.insert(hits[0], "SCENARIOS = %r\n\n" % (tuple(entries),))
    (integ / "run_scenarios.py").write_text("".join(lines), encoding="utf-8")

    decl = ["schema: v1", "lanes:", "  code:", "    write_allow:", "      - server/",
            "integration:", "  cmd: python3 integration/run_scenarios.py"]
    (root / "verify.yaml").write_text("\n".join(decl) + "\n", encoding="utf-8")
    return {"lane": root, "markers": markers, "env": nested_env(root)}


def markers_ran(lane):
    """Reader-side execution evidence: which stub entries left a marker on disk."""
    return sorted(n for n, p in lane["markers"].items() if p.exists())


# SANCTIONED-WAIT: bounded subprocess ceiling for one nested suite round; the
# bound is a hang guard (measured 2-5 s warm, about 22 s daemon-down) and the
# process group is SIGKILLed on expiry so no child is left behind.
def run_round(lane, extra=None, timeout=ROUND_WAIT_S):
    """Drive one nested round; returns rc / timed_out / out / err / both."""
    lane = Path(lane)
    cmd = [sys.executable, str(lane / "integration" / "run_scenarios.py")]
    proc = subprocess.Popen(cmd, cwd=str(lane), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", env=nested_env(lane, extra),
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        out, err = proc.communicate()
        return {"rc": None, "timed_out": True, "out": out or "",
                "err": err or "", "both": (out or "") + (err or "")}
    return {"rc": proc.returncode, "timed_out": False, "out": out or "",
            "err": err or "", "both": (out or "") + (err or "")}


def summary(out):
    """The round receipt (INTEG_SUMMARY JSON), or None when the line is absent."""
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


def prelude_legs(out):
    """The nested ``prelude-legs:`` line as {leg: seconds}, or None when absent."""
    for ln in out.splitlines():
        if ln.startswith("prelude-legs:"):
            legs = {}
            for tok in ln.split()[1:]:
                if "=" not in tok:
                    continue
                key, val = tok.split("=", 1)
                key = key.strip("(),")
                val = val.strip("(),")
                if not val.endswith("s"):
                    continue
                try:
                    legs[key] = float(val[:-1])
                except ValueError:
                    continue
            return legs
    return None


def traceback_free(text):
    """True when no traceback left the prelude (the incident's crash signature)."""
    return "Traceback (most recent call last)" not in (text or "")
