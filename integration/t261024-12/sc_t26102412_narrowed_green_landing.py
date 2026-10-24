#!/usr/bin/env python3
"""t261024-12 — a narrowed green gate round re-anchors the landing face
honestly, and the stale-revision refusal names the run that satisfies it
(grey-box L3, offline seconds, zero docker/Temporal-server/browser, never
touches 3099/7233).

User need (ticket t261024-12, KI-350, root of KI-343): two tickets sat at
merge/blocked forever — the lane gate runs narrowed by construction
(fast_proof_plan's run_only = own scenarios + fast set), the green-run
recorder ignored targeted-only rounds, so `meta.last_green_run` kept an old
sha; as soon as the lane synced main the landing guard
(`land_to_line`'s proven-revision contains-main check) refused every landing,
forever. The accepted fix records an HONEST narrowed face (declared marker +
the sha it ran on) and judges that marker by name; the refusal becomes
actionable (names which run would satisfy it). This scenario judges the
READER side of that contract:

  A. a narrowed green round records the face with the declared narrowed
     marker + sha + at, and merge_check's public item judges it green BY NAME
     (reason code names narrowed; the detail says it is NOT a full close —
     a targeted round is never minted into a full proof, t260923 D);
  B. after a main sync the OLD narrowed face is stale — the check item is red
     with an actionable detail naming the remedy run, and the real
     `land_to_line` act over a real git fixture refuses naming which run
     (kind + sha) would satisfy the precondition — never an unconditional
     bare stale-revision refusal;
  C. the wedge is escapable: after the lane syncs main and ONE fresh narrowed
     green round re-anchors the face on the new tree, the contains-main guard
     is passed (the refusal moves PAST the current-main guard — the landing
     act itself and the line store belong to the t261009-46 family);
  D. a FULL closing green round is unchanged: face WITHOUT the marker,
     judged green with the plain full-close reason code as today;
  E. invariants intact: a zero-run targeted round records NO face
     (fail-closed, KI-220), and an unpatched replay is inert (no face, no
     lane_head_sha activity call — replay-safety patch ids stay effective).

Intent split (no intent-level duplication): the face-builder and check-item
truth tables, the patch-gate mechanics and the miss-note matrix belong to
developer L1 (server/engine/tests) and to the t261011-17 scenarios; the full
landing act journey belongs to t261019-41/t261009-46; THIS entry uniquely
owns the KI-350 escape journey — narrowed green round -> main sync -> landing
no longer wedged, judged from the reader side (public check item + the real
landing act's refusal text over a real git fixture).

Implementation absent (no narrowed marker on the face / no narrowed reason
code / refusal does not name the satisfying run) = FAIL named (pre-implement
tree red = the TDD signal). git, the engine tree or temporalio unimportable
= ENV_FAIL exit 2.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(ROOT, "server", "engine")
if not os.path.isdir(ENGINE):
    print("ENV_FAIL: engine tree missing: %s" % ENGINE)
    sys.exit(2)
sys.path.insert(0, ENGINE)

try:
    import dev_lane  # noqa: E402
    import shared  # noqa: E402
    import agent_activities  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: engine modules unimportable: %s: %s"
          % (type(e).__name__, e))
    sys.exit(2)

PASS = 0
FAIL = 0
ENV_FAIL = 0


def _fail(msg):
    global FAIL
    FAIL += 1
    print("FAIL: %s" % msg)


def _pass(msg):
    global PASS
    PASS += 1
    print("PASS %s" % msg)


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 0)
        self.passed = kw.get("passed", 0)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


class _StubWf:
    """Stubbed workflow facade (the t261011-17 seam): patched flag + the sha
    the lane_head_sha activity returns (the fixture repo's HEAD)."""
    flag = True
    sha = ""
    calls = 0
    result_ok = True

    @staticmethod
    def patched(_pid):
        return _StubWf.flag

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        _StubWf.calls += 1
        if not _StubWf.result_ok:
            raise RuntimeError("lane_head_sha boom")
        return {"ok": True, "sha": _StubWf.sha}


def _make_wf():
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"worktree": "wt", "branch": "lane/x"}
    wf.ticket_id = "t261024-12"
    wf._log = lambda *a, **k: None
    wf._now_epoch = lambda: 1700000000
    return wf


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=cwd,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, p.stderr.strip()))
    return p.stdout.strip()


def make_fixture_repo():
    """main at c0 -> lane at c1 -> main advances to c2. c1 (proven) does NOT
    contain current main (c2) — the KI-350 wedge shape."""
    d = tempfile.mkdtemp(prefix="t26102412-repo-")
    env = dict(os.environ)
    _git("init", "-b", "main", cwd=d)
    _git("config", "user.email", "t@sandbar.test", cwd=d)
    _git("config", "user.name", "t", cwd=d)
    open(os.path.join(d, "a.txt"), "w").write("base\n")
    _git("add", "a.txt", cwd=d)
    _git("commit", "-m", "c0", cwd=d)
    _git("checkout", "-b", "lane/x", cwd=d)
    open(os.path.join(d, "b.txt"), "w").write("ticket\n")
    _git("add", "b.txt", cwd=d)
    _git("commit", "-m", "c1", cwd=d)
    proven = _git("rev-parse", "HEAD", cwd=d)
    _git("checkout", "main", cwd=d)
    open(os.path.join(d, "c.txt"), "w").write("main moved\n")
    _git("add", "c.txt", cwd=d)
    _git("commit", "-m", "c2", cwd=d)
    main_new = _git("rev-parse", "main", cwd=d)
    return d, proven, main_new


def _record(targeted, ran=3):
    wf = _make_wf()
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=ran), targeted))
    return wf


def main():
    dev_lane.workflow = _StubWf
    repo, proven, main_new = make_fixture_repo()
    try:
        # ---------- A: narrowed green round -> honest face, judged by name
        _StubWf.sha = proven
        wf = _record(True, ran=3)
        face = wf.meta.get("last_green_run")
        if not isinstance(face, dict) or not face.get("sha"):
            _fail("A: narrowed green round recorded NO face (the KI-350 "
                  "wedge shape): %s" % json.dumps(wf.meta, default=str))
        else:
            if face.get("narrowed") is not True:
                _fail("A: face lacks the declared narrowed marker: %s" % face)
            if face.get("sha") != proven or not face.get("at"):
                _fail("A: face does not carry the sha it ran on + at: %s" % face)
            item = shared.green_run_check_item(face, proven)
            if not item.get("green"):
                _fail("A: merge_check item is not green on the narrowed "
                      "face: %s" % item)
            elif "narrowed" not in str(item.get("reason_code", "")).lower():
                _fail("A: green is not judged BY NAME (reason_code=%r must "
                      "name narrowed, never the plain full-close code)"
                      % item.get("reason_code"))
            else:
                blob = json.dumps(item, default=str).lower()
                if "full close" not in blob and "not a full" not in blob \
                        and "no_scenarios" not in blob:
                    _fail("A: narrowed green detail does not declare it is "
                          "not a full close: %s" % item)
                else:
                    _pass("A: narrowed green round records an honest face "
                          "(marker+sha+at) and the check item judges it "
                          "green by name")
        # the marker must be readable on the ticket face without the log
        if face and "narrowed" not in json.dumps(wf.meta, default=str):
            _fail("A: narrowed marker invisible on the ticket face")

        # ---------- B: stale after main sync -> actionable named refusal
        item = shared.green_run_check_item(face, main_new)
        if item.get("green"):
            _fail("B: a narrowed face on a tree that does not contain "
                  "current main judged GREEN (silent green)")
        else:
            blob = json.dumps(item, default=str)
            if item.get("reason_code") != "stale":
                _fail("B: stale face judged with reason_code=%r, expected "
                      "stale" % item.get("reason_code"))
            elif "narrowed" not in blob.lower() and "gate round" not in blob.lower():
                _fail("B: stale detail does not name WHICH run satisfies the "
                      "precondition: %s" % blob)
            else:
                _pass("B1: stale narrowed face is red with a detail naming "
                      "the satisfying run")
        res = asyncio.run(agent_activities.land_to_line(
            agent_activities.LandToLineArgs(
                ticket_id="t261024-12", project_key="p", line_id="l",
                worktree=repo, proven_sha=proven)))
        if res.ok:
            _fail("B2: landing with a proven revision below current main was "
                  "allowed (guard gone)")
        else:
            err = res.error or ""
            if "does not contain current main" not in err:
                _fail("B2: refusal lost the contains-main diagnosis: %s" % err)
            elif main_new[:12] not in err and proven[:12] not in err:
                _fail("B2: refusal does not name WHICH run/sha would satisfy "
                      "it (bare stale-revision refusal): %s" % err)
            else:
                _pass("B2: land_to_line refusal is actionable (names the "
                      "run/sha that satisfies the precondition)")

        # ---------- C: the escape journey — sync main, one fresh narrowed
        # round, the guard passes
        _git("checkout", "lane/x", cwd=repo)
        _git("merge", "main", "-m", "sync main", cwd=repo)
        head = _git("rev-parse", "HEAD", cwd=repo)
        _StubWf.sha = head
        wf2 = _record(True, ran=2)
        face2 = wf2.meta.get("last_green_run") or {}
        item = shared.green_run_check_item(face2, head)
        if not item.get("green"):
            _fail("C: a fresh narrowed round on the synced tree did not "
                  "re-anchor the face green: %s" % item)
        else:
            res = asyncio.run(agent_activities.land_to_line(
                agent_activities.LandToLineArgs(
                    ticket_id="t261024-12", project_key="p", line_id="l",
                    worktree=repo, proven_sha=head)))
            if res.ok:
                _pass("C: narrowed green round after the main sync lands")
            elif "does not contain current main" in (res.error or ""):
                _fail("C: still wedged at the contains-main guard after the "
                      "fresh narrowed round: %s" % res.error)
            else:
                # guard passed; the fixture has no real develop line, the
                # named line-store refusal proves the precondition was met
                _pass("C: contains-main guard passed after the fresh narrowed "
                      "round (refusal moved past it: %s)"
                      % (res.error or "")[:120])
            if "narrowed" not in json.dumps(face2, default=str):
                _fail("C: re-anchoring face lost the narrowed marker: %s" % face2)

        # ---------- D: full closing round unchanged
        _StubWf.sha = head
        wf3 = _record(False, ran=5)
        face3 = wf3.meta.get("last_green_run") or {}
        if face3.get("narrowed") is True:
            _fail("D: a FULL closing round was marked narrowed")
        item = shared.green_run_check_item(face3, head)
        if not item.get("green") or item.get("reason_code") != "ok":
            _fail("D: full closing face verdict changed: %s" % item)
        else:
            _pass("D: full closing green round judged exactly as today "
                  "(reason_code=ok, no narrowed marker)")

        # ---------- E: invariants
        wf4 = _make_wf()
        asyncio.run(wf4._ki220_record_green_run(_Receipt(ran=0), True))
        if "last_green_run" in wf4.meta:
            _fail("E1: a zero-run targeted round minted a face (KI-220 "
                  "fail-closed broken): %s" % wf4.meta["last_green_run"])
        else:
            _pass("E1: zero-run targeted round stays faceless (fail-closed)")
        before = _StubWf.calls
        _StubWf.flag = False
        wf5 = _make_wf()
        asyncio.run(wf5._ki220_record_green_run(_Receipt(ran=3), True))
        _StubWf.flag = True
        if wf5.meta.get("last_green_run") or wf5.meta.get("green_run_note") \
                or _StubWf.calls != before:
            _fail("E2: unpatched replay is not inert (meta=%s, calls %d->%d)"
                  % (wf5.meta, before, _StubWf.calls))
        else:
            _pass("E2: unpatched replay is inert (no face, no lane_head_sha "
                  "call — replay-safety patch ids intact)")

    finally:
        shutil.rmtree(repo, ignore_errors=True)

    if FAIL:
        print("FAIL t26102412-narrowed-green-landing: %d leg(s) red" % FAIL)
        sys.exit(1)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % PASS)
    print("PASS t26102412-narrowed-green-landing: the KI-350 wedge has a "
          "reader-visible, honest escape")
    sys.exit(0)


if __name__ == "__main__":
    main()
