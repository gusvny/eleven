#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101104_wiring_stamp_drift_face.py — the operator drift face names the
wiring modules (ticket t261011-04 / KI-01M4KH2QR5BRQ..., grey-box L3, offline
seconds, zero docker / Temporal-server / browser, never touches 3099/7233).

intent (the user-perceivable behaviour under guard): on 261011 a central worker
had been running since 2026-10-09 while `workflows.py` / `activities.py` changed
on 2026-10-10 (line-round wiring, d4837baf). A fired dispatcher-scan produced a
complete plausible scan with NO `line_rounds` key, and the drift face said
`stale=none` — the wiring was invisible on the code-stamp module list, so a
worker stale ONLY on the wiring would have been a silent stale worker. After the
fix, the operator face must NAME the wiring modules: a worker whose loaded
`workflows.py` / `activities.py` / `develop_certify.py` / `develop_line.py`
predates those files on disk is reported stale, by name, in the
`engine_ops drift` alert — not as a bare count — and a fresh worker is NOT
reported stale (no false red).

High-level steps:
  W0 real-tree coverage guard: `shared.CODE_STAMP_MODULES` in the tree under
     test contains the four wiring modules. (One cheap guard; the fixture legs
     below carry the behaviour.)
  W1 naming leg: fixture repo + lane worktree + a LIVE process whose cwd is the
     fixture tree, pidfile started_at one hour in the past, all stamp-module
     files touched now. `engine_ops drift` must exit 1 (alert) AND the alert
     text and `result.lane_worker.stamp.stale` must contain each of the four
     module names. A count-only alert ("7 stale") fails this leg — naming is
     the ticket.
  W2 no-false-red leg: same fixture, every stamp-module file older than the
     worker baseline. No stamp alert; none of the four names in stale.
  W3 missing-file leg (external-input three-state): `develop_line.py` deleted
     from the fixture with an old baseline. The tool must not crash, must not
     fake a stale for the unreadable module (contract: unreadable mtime is
     never stale), and its mtime field stays empty (named, not guessed).
  W4 exclusion reasoning is written down: shared.py in the tree under test
     states, next to the list, why worker-loaded modules stay OUT (the ticket's
     "say out loud which modules stay out of it and why"), so the next reviewer
     does not re-litigate the list — the exact relapse shape of t261004-07.

Intent split (no duplication with the global scenario list):
  - engine-ops-offline-faces owns the general offline drift face (lane file
    drift, .md non-alert, sync, who, poller unavailability); this entry owns
    ONLY the wiring-module staleness naming.
  - t261008-29-stale-worker-visibility owns the fingerprint-v2
    running-worker-vs-HEAD/activity-set comparison; not re-asserted here.
  - t261009-48-preflight-refuse owns the restart pre-flight stamp display.
  - the pure stamp truth table belongs to developer L1 (injectable
    mtime/started_at); this scenario exercises the operator face end to end.

Three states: 0 = green; 1 = behaviour red (pre-implementation tree is EXPECTED
red on W0/W1/W4 — TDD signal, t261008-24 discipline; green required at the
integration gate); 2 = ENV_FAIL (git, python, or engine module unimportable).
Zero production contact: --repo points at the fixture tree, --host at a dead
port, pidfiles live in the fixture tmp.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")
SHARED = os.path.join(ENGINE, "shared.py")
DEAD_HOST = "127.0.0.1:1"
TID = "t-wiring-drift-%d" % os.getpid()

WIRING_MODULES = ("workflows", "activities", "develop_certify", "develop_line")


def fail(msg):
    sys.stderr.write("FAIL: %s\n" % msg)
    sys.exit(1)


def env_fail(msg):
    sys.stderr.write("ENV_FAIL: %s\n" % msg)
    sys.exit(2)


def pick_python():
    # engine venv first, interpreter fallback; the retired dsh-side wrapper
    # venv path is deliberately NOT referenced (five-layer layout guard,
    # t260907-10)
    for cand in (os.path.join(ENGINE, ".venv", "bin", "python"),
                 sys.executable):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


def stamp_module_relpaths():
    """(name, rel path) pairs straight from the real CODE_STAMP_MODULES."""
    sys.path.insert(0, ENGINE)
    import shared  # noqa: E402
    return list(shared.CODE_STAMP_MODULES)


def touch(path, epoch):
    os.utime(path, (epoch, epoch))


def build_fixture(root, engine_modules):
    """Minimal fixture tree: server/engine/worker.py + every stamp module file,
    enough for repo_root_from_tree() and the stamp stat walk. No git needed for
    the stamp legs; the drift lane needs a git worktree (built by the caller)."""
    eng = os.path.join(root, "server", "engine")
    os.makedirs(eng)
    shutil.copy2(os.path.join(ENGINE, "worker.py"), os.path.join(eng, "worker.py"))
    for _name, rel in engine_modules:
        src = os.path.join(REPO, rel)
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def write_pidfile(root, tid, pid, ts_epoch):
    data = os.path.join(root, "server", "engine", "data")
    os.makedirs(data, exist_ok=True)
    pf = os.path.join(data, "worker-%s.pid" % tid)
    with open(pf, "w", encoding="utf-8") as f:
        f.write("%d\n" % pid)
    with open(pf + ".meta", "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "repo_root": root, "ts": int(ts_epoch),
                   "version": 1}, f)
    return pf


def run_drift(repo, tid):
    py = pick_python()
    argv = [py, os.path.join(REPO, "server", "tools", "engine_ops.py"),
            "drift", tid, "--repo", repo, "--host", DEAD_HOST]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=REPO)
    out = (p.stdout or "").strip()
    try:
        payload = json.loads(out) if out else {}
    except ValueError:
        payload = {"_raw": out[:400]}
    return p.returncode, payload, (p.stderr or "")[-400:]


def main():
    if not os.path.isfile(SHARED):
        env_fail("engine shared.py missing under the tree under test")
    if shutil.which("git") is None:
        env_fail("git not on PATH (fixture lane worktree needs it)")
    if pick_python() == "":
        env_fail("no runnable python found (venv fallback chain empty)")
    sys.path.insert(0, ENGINE)
    try:
        import shared  # noqa: F401
    except Exception as e:  # noqa: BLE001
        env_fail("engine shared module unimportable: %s: %s" % (type(e).__name__, e))
    engine_modules = stamp_module_relpaths()
    tracked = {name for name, _rel in engine_modules}

    # ---- W0 real-tree coverage guard -------------------------------------
    missing = [m for m in WIRING_MODULES if m not in tracked]
    if missing:
        fail("W0: wiring modules absent from CODE_STAMP_MODULES in the tree "
             "under test: %s (this is the ticket's fix; pre-implementation "
             "tree is expected red here)" % ", ".join(missing))

    now = time.time()
    old_ts = now - 3600
    tmp = tempfile.mkdtemp(prefix="sc-wiring-drift-")
    try:
        root = os.path.join(tmp, "fixture")
        build_fixture(root, engine_modules)

        # lane worktree (drift needs merge-base/main; keep main == lane so the
        # ONLY alert source in W1/W2 is the worker stamp)
        lane = os.path.join(root, ".lane", TID)
        env = dict(os.environ)
        env.setdefault("GIT_AUTHOR_NAME", "t")
        env.setdefault("GIT_AUTHOR_EMAIL", "t@example.invalid")
        env.setdefault("GIT_COMMITTER_NAME", "t")
        env.setdefault("GIT_COMMITTER_EMAIL", "t@example.invalid")

        def git(*args):
            return subprocess.run(["git", "-C", root] + list(args), env=env,
                                  capture_output=True, text=True, timeout=60)

        for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"],
                    ["branch", "-m", "main"], ["branch", "lane/%s" % TID, "main"],
                    ["worktree", "add", "-q", "--detach", lane, "main"]):
            r = git(*cmd)
            if r.returncode != 0:
                env_fail("git %s failed: %s" % (cmd[0], (r.stderr or r.stdout)[-200:]))

        # ---- W1 naming leg ------------------------------------------------
        # all stamp-module files freshly touched; worker baseline one hour ago
        for _name, rel in engine_modules:
            touch(os.path.join(root, rel), now)
        proc = subprocess.Popen(["sleep", "120"], cwd=root,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            write_pidfile(root, TID, proc.pid, old_ts)
            rc, payload, err = run_drift(root, TID)
            if rc != 1:
                fail("W1: drift exit=%r (want 1 alert) stderr=%s raw=%s"
                     % (rc, err, json.dumps(payload)[:300]))
            result = payload.get("result") or {}
            stamp = (result.get("lane_worker") or {}).get("stamp") or {}
            stale = stamp.get("stale") or []
            alerts = " | ".join(payload.get("alerts") or []) + " " + str(payload.get("error") or "")
            for name in WIRING_MODULES:
                if name not in stale:
                    fail("W1: stale list does not name %r: %s" % (name, stale))
                if name not in alerts:
                    fail("W1: operator alert does not name %r (a count-only "
                         "alert is exactly the incident): %s" % (name, alerts[:300]))
        finally:
            proc.terminate()
            proc.wait(timeout=30)

        # ---- W2 no-false-red leg ------------------------------------------
        fresh_ts = now + 5
        for _name, rel in engine_modules:
            touch(os.path.join(root, rel), now - 7200)  # two hours ago
        proc = subprocess.Popen(["sleep", "120"], cwd=root,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            write_pidfile(root, TID, proc.pid, fresh_ts)  # baseline = now
            rc, payload, err = run_drift(root, TID)
            if rc != 1:
                fail("W2: drift exit=%r (poller-unavailable alert on a dead "
                     "host is expected, crash/env-red is not) stderr=%s" % (rc, err))
            result = payload.get("result") or {}
            stamp = (result.get("lane_worker") or {}).get("stamp") or {}
            stale = stamp.get("stale") or []
            if stale:
                fail("W2: fresh worker reported stale: %s (false red)" % stale)
            stamp_alerts = [a for a in (payload.get("alerts") or [])
                            if "stale" in str(a) and any(
                                m in str(a) for m in WIRING_MODULES)]
            if stamp_alerts:
                fail("W2: stamp alert on a fresh worker: %s" % stamp_alerts)
        finally:
            proc.terminate()
            proc.wait(timeout=30)

        # ---- W3 missing-file leg ------------------------------------------
        os.remove(os.path.join(root, "server", "engine", "develop_line.py"))
        for _name, rel in engine_modules:
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                touch(p, now)
        proc = subprocess.Popen(["sleep", "120"], cwd=root,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            write_pidfile(root, TID, proc.pid, old_ts)
            rc, payload, err = run_drift(root, TID)
            if rc == 2:
                fail("W3: drift returned ENV exit on a missing module file "
                     "(must degrade named, not env-red): %s" % err)
            result = payload.get("result") or {}
            stamp = (result.get("lane_worker") or {}).get("stamp") or {}
            stale = stamp.get("stale") or []
            if "develop_line" in stale:
                fail("W3: unreadable module faked as stale (contract: "
                     "unreadable mtime is never stale): %s" % stale)
            mods = stamp.get("modules") or {}
            dl = mods.get("develop_line") or {}
            if dl and dl.get("mtime"):
                fail("W3: missing module reported an mtime (%r) — must stay "
                     "empty/named" % dl.get("mtime"))
            for name in ("workflows", "activities", "develop_certify"):
                if name not in stale:
                    fail("W3: the readable wiring modules must still be named "
                         "stale (got %s)" % stale)
        finally:
            proc.terminate()
            proc.wait(timeout=30)

        # ---- W4 exclusion reasoning is written down -----------------------
        with open(SHARED, "r", encoding="utf-8") as f:
            src = f.read()
        idx = src.find("CODE_STAMP_MODULES")
        if idx < 0:
            fail("W4: CODE_STAMP_MODULES not found in shared.py")
        head = src[max(0, idx - 4000):idx]
        # the ticket demands the out-list reasoning live next to the list so
        # the next reviewer does not re-litigate it; a bare list with no
        # documented omission reasoning is the t261004-07 relapse shape.
        # Wording-independent judge: the comment region naming the list must
        # call out, by module name, at least two worker-loaded modules that
        # stay OUT of the list.
        engine_stems = {fn[:-3] for fn in os.listdir(ENGINE)
                        if fn.endswith(".py")}
        named_out = {stem for stem in engine_stems
                     if stem not in tracked and stem in head}
        if len(named_out) < 2:
            fail("W4: no written exclusion reasoning next to "
                 "CODE_STAMP_MODULES (expected it to name untracked "
                 "worker-loaded modules; found only %s)" % sorted(named_out))
    finally:
        subprocess.run(["git", "-C", os.path.join(tmp, "fixture"), "worktree",
                        "prune"], capture_output=True, timeout=60)
        shutil.rmtree(tmp, ignore_errors=True)

    print("PASS t261011-04-wiring-stamp-drift-face: drift face names the "
          "wiring modules (W1), fresh worker not stale (W2), missing module "
          "degrades named (W3), exclusion reasoning written (W4)")
    sys.exit(0)


if __name__ == "__main__":
    main()
