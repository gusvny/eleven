# -*- coding: utf-8 -*-
"""t261009-55 UT: console boot generation + named no-poller repair in the ensure.

Drives the REAL exported decision path (node.ts ensureTicketWorkersOnce) via a node
subprocess with injected deps (same contract the integration gate probe uses — the
pure decision face, no Temporal, no console, no ports).

Pinned behaviours (dispatch spec 1/2/5, plan R1-R4):
- foreign boot generation + exact pid  -> replaced-foreign-boot (slot cleared, spawn),
  so a console restart hands over in ONE ensure tick without the old worker writing
  state='draining' (SIGKILL-proof);
- foreign boot + pid mismatch          -> stale-meta-cleared: meta only, pidfile (the
  slot authority) untouched, no spawn;
- same boot / boot-less meta           -> held-same (transitional limitation R6);
- foreign REPO worker                  -> held-foreign even with a foreign boot
  (kill-processes-belong-to-humans is never bypassed by the boot rule);
- meta polling=false + PROVEN zero     -> replaced-no-poller (the named repairable
  state, t261009-52 measured case);
- probe raises / unprovable / absent   -> held + no_poller_unproven, slot NEVER
  cleared (an unproven face never clears a slot — plan R2);
- probe proven live>0                  -> held (stale self-report, refresher heals);
- per-tick probe budget (cap)          -> excess tickets held + named, no probe;
- spawn-dependency absent              -> clear-only for every replaced-* action
  (borrowed t261005-03 mode carried over);
- draining / missing-meta paths        -> byte-identical legacy behaviour.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
NODE_TS = REPO / "server" / "plugins" / "temporal-tools" / "node.ts"

_NODE_BODY = r"""
import { pathToFileURL } from 'node:url'
const mod = await import(pathToFileURL(process.env.NODE_TS).href)
const deps = JSON.parse(process.env.DEPS)
if (process.env.SPAWN === '1') deps.spawn = () => ({ pid: -1 })
const probe = process.env.PROBE
if (probe === 'zero') deps.probePollers = async () => ({ proven: true, live: 0 })
else if (probe === 'two') deps.probePollers = async () => ({ proven: true, live: 2 })
else if (probe === 'raise') deps.probePollers = async () => { throw new Error('probe down') }
else if (probe === 'unprovable') deps.probePollers = async () => ({ proven: false, live: -1, detail: 'temporalio unavailable' })
if (process.env.CAP) deps.probeConcurrency = Number(process.env.CAP)
const out = await mod.ensureTicketWorkersOnce(deps)
console.log(JSON.stringify(out))
"""


def _run_once(files, running, own_boot=None, probe=None, spawn=True, cap=None):
    """One ensureTicketWorkersOnce call against a fresh temp dir. `files` maps
    filenames -> text (pidfile/meta fixtures). Returns (decisions, dir)."""
    d = tempfile.mkdtemp(prefix="t261009-55-ensure-")
    for name, text in files.items():
        (Path(d) / name).write_text(text, encoding="utf-8")
    deps = {"dataDir": d, "repoRoot": "/repo", "running": running}
    if own_boot is not None:
        deps["ownBoot"] = own_boot
    env = dict(os.environ, NODE_TS=str(NODE_TS), DEPS=json.dumps(deps))
    if probe:
        env["PROBE"] = probe
    if spawn:
        env["SPAWN"] = "1"
    if cap:
        env["CAP"] = str(cap)
    p = subprocess.run(["node", "--input-type=module", "-e", _NODE_BODY],
                       capture_output=True, text=True, env=env, timeout=60)
    if p.returncode != 0:
        raise AssertionError("node probe failed rc=%s stderr=%s" % (p.returncode, p.stderr[-500:]))
    return json.loads(p.stdout)["decisions"], d


def _meta(pid, extra=None):
    m = {"version": 1, "pid": pid, "repo_root": "/repo", "ts": 1}
    m.update(extra or {})
    return json.dumps(m)


def _reaped_dead_pid():
    """A pid that is genuinely not alive: run a child to exit, reap it, reuse ITS
    pid (the OS will not hand the same pid out again until wraparound)."""
    import subprocess as sp
    proc = sp.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    pid = proc.pid
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return pid
    except PermissionError:
        pass
    raise AssertionError("could not obtain a dead pid (pid=%d still probeable)" % pid)


class EnsureHandoverTest(unittest.TestCase):
    ALIVE = os.getpid()   # a genuinely live pid for the pidfile fixtures

    def test_foreign_boot_replaces_in_one_tick(self):
        decisions, d = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "old-boot", "polling": True})},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["replaced-foreign-boot"])
        self.assertIn("old-boot", decisions[0]["reason"])
        self.assertFalse((Path(d) / "worker-t1.pid").exists())   # slot cleared
        self.assertFalse((Path(d) / "worker-t1.meta").exists())

    def test_same_boot_holds(self):
        decisions, d = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "new-boot", "polling": True})},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["held-same"])
        self.assertTrue((Path(d) / "worker-t1.pid").exists())

    def test_bootless_meta_keeps_legacy_path(self):
        # Plan R6: a meta without console_boot (pre-upgrade worker / failed merge)
        # stays on the pre-t261009-55 rules — held, never replaced by boot.
        decisions, _ = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE)},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["held-same"])

    def test_stale_foreign_boot_meta_clears_meta_only(self):
        # Plan R4: foreign boot but meta names another pid -> stale fingerprint;
        # the pidfile is the slot authority and must survive untouched.
        decisions, d = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE + 1, {"console_boot": "old-boot"})},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["stale-meta-cleared"])
        self.assertTrue((Path(d) / "worker-t1.pid").exists())
        self.assertFalse((Path(d) / "worker-t1.meta").exists())

    def test_foreign_repo_never_replaced_even_with_foreign_boot(self):
        decisions, d = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"repo_root": "/other-repo",
                                                  "console_boot": "old-boot"})},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["held-foreign"])
        self.assertTrue((Path(d) / "worker-t1.pid").exists())

    def test_proven_zero_poller_replaces(self):
        decisions, d = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "b", "polling": False})},
            [{"id": "t1", "queue": "q1"}], own_boot="b", probe="zero")
        self.assertEqual([x["action"] for x in decisions], ["replaced-no-poller"])
        self.assertIn("no_poller_alive_pid", decisions[0]["reason"])
        self.assertIn("q1", decisions[0]["reason"])
        self.assertFalse((Path(d) / "worker-t1.pid").exists())

    def test_probe_failure_never_clears_slot(self):
        # Plan R2: probe raise AND unprovable face -> held + named, files intact.
        for probe in ("raise", "unprovable"):
            decisions, d = _run_once(
                {"worker-t1.pid": str(self.ALIVE),
                 "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "b", "polling": False})},
                [{"id": "t1", "queue": "q1"}], own_boot="b", probe=probe)
            self.assertEqual([x["action"] for x in decisions], ["held-same"], probe)
            self.assertIn("no_poller_unproven", decisions[0]["reason"], probe)
            self.assertTrue((Path(d) / "worker-t1.pid").exists(), probe)
            self.assertTrue((Path(d) / "worker-t1.meta").exists(), probe)

    def test_no_probe_dependency_holds_and_names(self):
        decisions, _ = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "b", "polling": False})},
            [{"id": "t1", "queue": "q1"}], own_boot="b", probe=None)
        self.assertEqual([x["action"] for x in decisions], ["held-same"])
        self.assertIn("no_poller_unproven", decisions[0]["reason"])

    def test_contradicted_poller_report_holds(self):
        decisions, d = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "b", "polling": False})},
            [{"id": "t1", "queue": "q1"}], own_boot="b", probe="two")
        self.assertEqual([x["action"] for x in decisions], ["held-same"])
        self.assertIn("live=2", decisions[0]["reason"])
        self.assertTrue((Path(d) / "worker-t1.meta").exists())

    def test_probe_budget_cap(self):
        files = {}
        for i in range(2):
            files["worker-t%d.pid" % i] = str(self.ALIVE)
            files["worker-t%d.meta" % i] = _meta(self.ALIVE, {"console_boot": "b",
                                                              "polling": False})
        decisions, _ = _run_once(files, [{"id": "t0", "queue": "q"}, {"id": "t1", "queue": "q"}],
                                 own_boot="b", probe="zero", cap=1)
        acts = {x["tid"]: x["action"] for x in decisions}
        self.assertEqual(acts["t0"], "replaced-no-poller")
        self.assertEqual(acts["t1"], "held-same")
        self.assertIn("cap", next(x["reason"] for x in decisions if x["tid"] == "t1"))

    def test_clear_only_when_spawn_absent(self):
        decisions, _ = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"console_boot": "old-boot"})},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot", spawn=False)
        self.assertEqual([x["action"] for x in decisions], ["replaced-foreign-boot"])
        self.assertIn("spawn", decisions[0]["reason"])

    def test_draining_path_unchanged(self):
        decisions, _ = _run_once(
            {"worker-t1.pid": str(self.ALIVE),
             "worker-t1.meta": _meta(self.ALIVE, {"state": "draining"})},
            [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["replaced-draining"])

    def test_missing_meta_with_live_pid_held_unknown(self):
        decisions, _ = _run_once(
            {"worker-t1.pid": str(self.ALIVE)}, [{"id": "t1", "queue": "q1"}],
            own_boot="new-boot")
        self.assertEqual([x["action"] for x in decisions], ["held-unknown"])
        self.assertIn("worker-t1.meta", decisions[0]["reason"])
        self.assertIn(str(self.ALIVE), decisions[0]["reason"])

    def test_junk_meta_shapes_fail_conservative(self):
        for junk in ("{not json", "[]", json.dumps({"pid": "x", "repo_root": "/repo"})):
            decisions, _ = _run_once(
                {"worker-t1.pid": str(self.ALIVE), "worker-t1.meta": junk},
                [{"id": "t1", "queue": "q1"}], own_boot="new-boot")
            self.assertEqual([x["action"] for x in decisions], ["held-unknown"], junk)

    def test_dead_pid_spawns_as_before(self):
        # A dead pidfile pid takes today's stale-clear + spawn path — untouched.
        pid = _reaped_dead_pid()
        decisions, _ = _run_once(
            {"worker-t1.pid": str(pid)}, [{"id": "t1", "queue": "q1"}], own_boot="b")
        self.assertEqual([x["action"] for x in decisions], ["spawned"])

    def test_exports_present(self):
        # C1-style contract face: the new decision surface is exported (the
        # integration scenarios import these names directly).
        body = ("import { pathToFileURL } from 'node:url'\n"
                "const mod = await import(pathToFileURL(process.env.NODE_TS).href)\n"
                "const need = ['ensureTicketWorkersOnce','readWorkerMeta',"
                "'judgeTicketWorkerMeta','consoleBootId']\n"
                "console.log(JSON.stringify({missing: need.filter(n => typeof mod[n] !== 'function')}))\n")
        env = dict(os.environ, NODE_TS=str(NODE_TS))
        p = subprocess.run(["node", "--input-type=module", "-e", body],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr[-300:])
        self.assertEqual(json.loads(p.stdout)["missing"], [])


if __name__ == "__main__":
    unittest.main()
