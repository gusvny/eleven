#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100955_one_tick_handover.py — a console restart hands every ticket worker
over in ONE ensure tick, not in one drain (t261009-55, KI-01M4GF5R8NHQNATH7WD7SKF94X
addendum; grey-box L2, offline seconds, zero docker/Temporal/3099).

intent (user-perceivable contract):
  Tonight a console restart strands every in-flight ticket: the old worker stops
  polling and drains up to 1800 s; if its meta is missing/malformed the new console
  refuses to spawn a substitute (held-unknown) and the queue stays poller-less for
  the whole drain; an alive worker that shed its poller is indistinguishable from a
  dead one and is never repaired. After this ticket a restart must NOT depend on the
  old worker reaching state='draining': a worker whose ownership meta carries a
  foreign console boot generation is replaceable in the same tick, and an alive
  worker with a PROVEN zero-live-poller queue is a named, repairable state.

faces asserted (through the public decision seam of
server/plugins/temporal-tools/node.ts, ensureTicketWorkersOnce, with fixture
pidfile/meta dirs and injectable spawn + poller probe — no production contact):
  H1 foreign boot + exact pid match => decision replaced-foreign-boot; pidfile AND
     meta cleared; substitute spawned — all in one call, no draining write needed.
  H2 same boot => held-same, no spawn (the non-regression half).
  H3 boot-less meta (pre-upgrade worker / failed merge) => today's rules only
     (held-* or draining paths); never a foreign-boot replacement (named
     transitional limitation R6).
  H4 alive + meta polling:false => two-stage detection: the probe CONFIRMS;
     confirmed zero live pollers + established ownership => replaced-no-poller
     (same slot-clearing path as draining, named alert no_poller_alive_pid with
     pid/queue/count).
  H5 UNPROVEN probe face (probe raises / probe unavailable / probe errors) =>
     NO replacement: the slot is held and the alert names no_poller_unproven
     (a caller never upgrades an unproven face into a no_poller claim — the
     client.py discipline, plan review item R2).
  H6 meta missing/malformed + pid alive => fail-closed: no kill, no spawn,
     held-unknown naming pid + meta path + poller evidence (spec item 2 edge).
  H7 spawn dependency absent => clear-only for both new actions, said in the
     decision reason (t261005-03 carried guarantee).
  H8 foreign boot but meta.pid != pidfile pid => stale-meta-cleared (meta only,
     pidfile untouched) — the exact-pid guard makes a stale rewrite harmless
     (plan review item R4).
  H9 malformed inputs (junk meta JSON, negative pid, missing pidfile) => named
     decisions, never a crash, never a blind spawn (external-input three-state).

seam binding note (grey-box, kept shallow): the scenario drives
ensureTicketWorkersOnce(deps) and reads decisions; it passes the current console
boot identity as deps.ownBoot and the poller probe as deps.probePollers
(injectable per plan step 2, result shape {proven, live, detail}). Action names asserted are the plan-declared public decision
records (replaced-foreign-boot / replaced-no-poller / stale-meta-cleared) — the
same surface the supervisor log lines emit.

Red expected pre-implement (TDD signal); green by arbitrate/merge.
node missing or node.ts unimportable = ENV_FAIL exit 2.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NODE_TS = REPO / "server" / "plugins" / "temporal-tools" / "node.ts"

fails = []
n = 0


def check(cond, label, detail=""):
    global n
    n += 1
    if cond:
        print("ok   H%d %s" % (n, label))
    else:
        fails.append("H%d %s %s" % (n, label, detail))
        print("FAIL H%d %s %s" % (n, label, detail))


_NODE_BODY = """
import { readFileSync, existsSync, rmSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const mod = await import(pathToFileURL(process.env.NODE_TS).href)
if (typeof mod.ensureTicketWorkersOnce !== 'function') {
  console.log(JSON.stringify({ error: 'missing_export', missing: ['ensureTicketWorkersOnce'] }))
  process.exit(4)
}
const deps = JSON.parse(process.env.GATE_DEPS)
const calls = []
if (process.env.GATE_SPAWN !== 'absent') {
  deps.spawn = (tid, queue) => { calls.push({ tid, queue }); return { pid: 424242 } }
}
if (process.env.GATE_PROBE === 'zero') {
  deps.probePollers = async (tid, queue) => ({ proven: true, live: 0, detail: 'fixture zero' })
} else if (process.env.GATE_PROBE === 'raise') {
  deps.probePollers = async () => { throw new Error('probe boom') }
} else if (process.env.GATE_PROBE === 'unproven') {
  deps.probePollers = async () => ({ proven: false, live: -1, detail: 'temporalio unavailable' })
} else if (process.env.GATE_PROBE === 'live') {
  deps.probePollers = async (tid, queue) => ({ proven: true, live: 1, detail: 'fixture live' })
}
const res = await mod.ensureTicketWorkersOnce(deps)
const decisions = (res && res.decisions) ? res.decisions : res
console.log(JSON.stringify({
  decisions,
  spawnCalls: calls,
  pidfileGone: deps.running.every((r) => !existsSync(deps.dataDir + '/worker-' + r.id + '.pid')),
  metaGone: deps.running.every((r) => !existsSync(deps.dataDir + '/worker-' + r.id + '.meta')),
}))
"""


def node_ensure(deps, probe=None, spawn_absent=False):
    """Run ensureTicketWorkersOnce through node with fixture deps. Returns parsed
    JSON or None (already counted as a failure by the caller's ENV_FAIL path)."""
    env = dict(os.environ)
    env["NODE_TS"] = str(NODE_TS)
    env["GATE_DEPS"] = json.dumps(deps)
    if spawn_absent:
        env["GATE_SPAWN"] = "absent"
    if probe:
        env["GATE_PROBE"] = probe
    p = subprocess.run(["node", "--input-type=module", "-e", _NODE_BODY],
                       capture_output=True, text=True, timeout=90, env=env)
    if p.returncode == 4 or "missing_export" in p.stdout:
        print("FAIL seam ensureTicketWorkersOnce not exported/absent: %s %s"
              % (p.stdout.strip(), p.stderr.strip()[:200]))
        fails.append("sear ensureTicketWorkersOnce export missing")
        return None
    if p.returncode != 0:
        return {"_node_error": p.stderr.strip()[-300:]}
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"_node_error": "unparseable stdout: " + p.stdout[-200:]}


def slot(d, tid, meta_obj=None, pid=None, meta_text=None, pidfile=True):
    """Lay down a fixture worker slot (pidfile + meta) under data dir d.

    meta fixtures always carry the t260904-02 shape gate fields (version / pid:int
    / repo_root:str) so a well-formed fixture is judged on its boot/polling keys,
    not rejected as malformed before the new rules are reached."""
    os.makedirs(d, exist_ok=True)
    pf = os.path.join(d, "worker-%s.pid" % tid)
    mf = os.path.join(d, "worker-%s.meta" % tid)
    if pidfile:
        with open(pf, "w") as f:
            f.write(str(pid if pid is not None else os.getpid()))
    if meta_obj is not None:
        base = {"version": "1", "pid": pid if pid is not None else os.getpid(),
                "repo_root": str(REPO)}
        base.update(meta_obj)
        with open(mf, "w") as f:
            json.dump(base, f)
    elif meta_text is not None:
        with open(mf, "w") as f:
            f.write(meta_text)
    return pf, mf


def deps_for(d, tid, boot="boot-new-2"):
    return {"dataDir": d, "repoRoot": str(REPO),
            "running": [{"id": tid, "queue": "ticket-%s" % tid}],
            "ownBoot": boot}


TID = "t26100955-h"
ME = os.getpid()


def decisions_for(res):
    if not res or "_node_error" in res:
        return []
    return res.get("decisions") or []


def first_action(res):
    ds = decisions_for(res)
    return str(ds[0].get("action") or "") if ds else ""


def blob(res):
    return json.dumps(res, default=str)


def main():
    if not NODE_TS.exists():
        print("ENV_FAIL: node.ts missing at %s" % NODE_TS)
        return 2
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=20)
    except Exception as exc:
        print("ENV_FAIL: node missing: %r" % exc)
        return 2
    d = tempfile.mkdtemp(prefix="sc-t26100955-")

    # ---- H1 foreign boot + exact pid => one-tick replace
    slot(d, TID, meta_obj={"pid": ME, "state": "running", "console_boot": "boot-old-1"},
         pid=ME)
    r = node_ensure(deps_for(d, TID), probe=None)
    check(r is not None and first_action(r) == "replaced-foreign-boot",
          "H1 foreign boot is replaced", blob(r))
    check(r is not None and r.get("spawnCalls") and r["spawnCalls"][0]["tid"] == TID,
          "H1 substitute spawned in the same tick", blob(r))
    check(r is not None and r.get("pidfileGone") and r.get("metaGone"),
          "H1 slot cleared (pidfile+meta) before/at spawn", blob(r))

    # ---- H2 same boot => held-same, no spawn
    d2 = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d2, TID, meta_obj={"pid": ME, "state": "running", "console_boot": "boot-new-2"},
         pid=ME)
    r = node_ensure(deps_for(d2, TID))
    check(r is not None and first_action(r) == "held-same",
          "H2 same boot stays held-same", blob(r))
    check(r is not None and not r.get("spawnCalls"), "H2 no re-spawn", blob(r))

    # ---- H3 boot-less meta => today's rules, never foreign-boot replace
    d3 = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d3, TID, meta_obj={"pid": ME, "state": "running"}, pid=ME)
    r = node_ensure(deps_for(d3, TID))
    act = first_action(r)
    check(r is not None and act in ("held-same", "held-foreign", "held-unknown"),
          "H3 boot-less meta keeps today's rules (R6 transitional)", blob(r))
    check(act != "replaced-foreign-boot",
          "H3 boot-less is NOT treated as foreign boot", blob(r))

    # ---- H4a alive + polling:false + confirmed zero pollers => replace
    d4 = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d4, TID, meta_obj={"pid": ME, "state": "running",
                            "console_boot": "boot-new-2", "polling": False}, pid=ME)
    r = node_ensure(deps_for(d4, TID), probe="zero")
    ds = decisions_for(r)
    check(r is not None and first_action(r) == "replaced-no-poller",
          "H4a confirmed zero-poller alive worker replaced", blob(r))
    check(any("no_poller_alive_pid" in blob(x) or "no_poller" in str(x.get("reason", ""))
              for x in ds),
          "H4a alert names no_poller_alive_pid", blob(ds))
    check(r is not None and r.get("spawnCalls"), "H4a substitute spawned", blob(r))

    # ---- H4b control: probe says a live poller exists => no replacement
    # (fresh slot: H4a's replace cleared the d4 slot — a held-leg needs a live slot)
    d4b = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d4b, TID, meta_obj={"pid": ME, "state": "running",
                             "console_boot": "boot-new-2", "polling": False}, pid=ME)
    r = node_ensure(deps_for(d4b, TID), probe="live")
    check(str(first_action(r)).startswith("held"),
          "H4b proven live poller is not replaced", blob(r))
    check(not (r or {}).get("spawnCalls"), "H4b nothing spawned", blob(r))

    # ---- H5 unproven probe => hold + name, never replace
    for probe, tag in (("raise", "raises"), ("unproven", "unproven")):
        d4c = tempfile.mkdtemp(prefix="sc-t26100955-")
        slot(d4c, TID, meta_obj={"pid": ME, "state": "running",
                                 "console_boot": "boot-new-2", "polling": False},
             pid=ME)
        r = node_ensure(deps_for(d4c, TID), probe=probe)
        act = first_action(r)
        check(act in ("held-same", "held-unknown"),
              "H5 unproven face (%s) holds the slot" % tag, blob(r))
        check(not (r or {}).get("spawnCalls"),
              "H5 unproven face (%s) spawns nothing" % tag, blob(r))
        check("unproven" in blob(r).lower(),
              "H5 unproven face (%s) is named on the decision" % tag, blob(r))

    # ---- H6 meta missing/malformed + pid alive => fail-closed refusal, named
    d6 = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d6, TID, meta_obj=None, pid=ME)  # pidfile alive, meta absent
    r = node_ensure(deps_for(d6, TID), probe="zero")
    check(first_action(r) == "held-unknown",
          "H6 unknown ownership refuses (no kill, no spawn)", blob(r))
    check(not (r or {}).get("spawnCalls"), "H6 no silent substitute", blob(r))
    rb = blob(r)
    check(str(ME) in rb and "worker-%s.meta" % TID in rb,
          "H6 refusal names pid + meta path", rb)

    d6b = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d6b, TID, meta_text="{ not json !!!", pid=ME)
    r = node_ensure(deps_for(d6b, TID), probe="zero")
    check(first_action(r) == "held-unknown",
          "H6b junk meta refuses, no crash", blob(r))

    # ---- H7 spawn absent => clear-only, said in the reason
    d7 = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d7, TID, meta_obj={"pid": ME, "state": "running", "console_boot": "boot-old-1"},
         pid=ME)
    r = node_ensure(deps_for(d7, TID), spawn_absent=True)
    ds = decisions_for(r)
    check(first_action(r) == "replaced-foreign-boot",
          "H7 foreign boot decision fires without spawn dep", blob(r))
    check(not (r or {}).get("spawnCalls"), "H7 nothing spawned", blob(r))
    check(r is not None and r.get("pidfileGone") and r.get("metaGone"),
          "H7 slot still cleared (clear-only)", blob(r))
    check(any("clear" in str(x.get("reason", "")).lower()
              or "spawn" in str(x.get("reason", "")).lower() for x in ds),
          "H7 reason says clear-only", blob(ds))

    # ---- H8 foreign boot + pid mismatch => stale meta cleared, pidfile untouched
    d8 = tempfile.mkdtemp(prefix="sc-t26100955-")
    pf, mf = slot(d8, TID, meta_obj={"pid": os.getppid(), "state": "running",
                                     "console_boot": "boot-old-1"}, pid=ME)
    r = node_ensure(deps_for(d8, TID))
    check(first_action(r) == "stale-meta-cleared",
          "H8 pid mismatch => stale-meta-cleared, not a blind replace", blob(r))
    check(os.path.exists(pf), "H8 pidfile preserved (slot authority intact)", pf)

    # ---- H9 malformed inputs never crash
    d9 = tempfile.mkdtemp(prefix="sc-t26100955-")
    slot(d9, TID, meta_obj={"pid": -5, "state": "running", "console_boot": "x"}, pid=ME)
    r = node_ensure(deps_for(d9, TID), probe="zero")
    check(r is not None and "_node_error" not in r and decisions_for(r),
          "H9 negative-pid meta gives a decision, no crash", blob(r))
    d9b = tempfile.mkdtemp(prefix="sc-t26100955-")
    r = node_ensure({"dataDir": d9b, "repoRoot": str(REPO),
                     "running": [{"id": TID, "queue": "ticket-%s" % TID}],
                     "ownBoot": "boot-new-2"}, probe=None)
    check(r is not None and "_node_error" not in r,
          "H9b missing pidfile => today's spawn path, no crash", blob(r))

    print("SUMMARY %d checks, %d failures" % (n, len(fails)))
    if fails:
        for f in fails:
            print("FAILED: %s" % f)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
