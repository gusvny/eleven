#!/usr/bin/env python3
"""t261025-08 — an in-flight lane whose patch gate is memo-closed can still be
ENABLED by a history event, and after that event a targeted green gate round
re-anchors the landing face on the CURRENT lane HEAD (grey-box L3, offline
seconds, zero docker/Temporal-server/browser, never touches 3099/7233).

User need (ticket t261025-08, KI-356): KI-350's narrowed-face machinery is in
the tree, but its recorder arm sits behind workflow.patched(), and temporalio
memoizes the first patched() answer per workflow instance — a long-lived
in-flight lane whose first evaluation happened on replay of pre-fix history
reads False FOREVER on live rounds. Both witnesses (t261022-14, t261022-12)
ran their own scenarios green and still could not land: meta.last_green_run
kept an old sha, the landing refused 'proven revision does not contain current
main', and the remedy (one more green gate round on the current HEAD) was one
the gate could never satisfy, because every per-ticket gate round is targeted
by construction. The accepted fix (create_plan gen0): a NEW dev-lane signal
`enable_narrowed_anchor` — a history event that cannot exist in pre-fix
history, so replay-safe WITHOUT the patch gate — arms the narrowed face
recorder for in-flight lanes; the merge precondition keeps judging the
narrowed marker BY NAME; promotion/release stays read-only-full-closing-run.
This scenario judges the reader side of THAT contract:

  A. THE WEDGE, POSITIVE — patched() reads False (the memo-poisoned lane) and
     the enable event has been delivered: a targeted GREEN round (ran>=1,
     failed=0, no error, no blockers) records an honest face naming the sha
     the lane_head_sha activity returned (= the CURRENT lane HEAD), with the
     declared narrowed marker; merge_check's public item judges it green BY
     NAME; the enablement itself is observable on the ticket meta, not only
     in a log line;
  B. INERT CONTROL — the same lane WITHOUT the enable event stays byte-inert:
     no face, no lane_head_sha activity call, no note (old unpatched replays
     observe nothing; the patch ids keep their replay-safety role);
  C. IDEMPOTENCE + MALFORMED INPUT — the enable event delivered twice leaves
     the lane enabled exactly once-more-than-not (no crash, no flip), and a
     malformed/absent payload is ignored, never a crash, never a phantom arm;
  D. FAIL-CLOSED UNDER ENABLE — with the event armed, a zero-run targeted
     round records NO face (the KI-220 zero-run supply stop belongs to the
     full rounds), a red receipt records NO face, and a lane_head_sha activity
     failure records NO face plus the named miss note (never a fabricated
     green); a FULL closing round is unchanged (no narrowed marker on it);
  E. THE ESCAPE JOURNEY (the t261022-14 acceptance shape) — over a real git
     fixture (main advances past the proven revision, the lane syncs main),
     ONE enabled targeted green round re-anchors the face on the synced HEAD
     and the real land_to_line act gets PAST the contains-main guard (the
     landing act itself belongs to the t261009-46/t261019-41 family); a
     genuinely stale anchor still refuses with a detail naming the satisfying
     run (regression control — intent ownership t26102412-narrowed-green-
     landing).

Intent split (no intent-level duplication): the KI-350 patch-gated escape
journey, the face/check-item truth tables and the refusal copy belong to
t26102412-narrowed-green-landing and developer L1; the gate-round run-list
faces belong to t261024-40 / t261025-02; THIS entry uniquely owns the KI-356
reachability face — the event-gated enable un-wedging an in-flight lane that
the patch gate can never reach.

Pre-implement tree red on A/E = the named TDD signal (the enable event is
absent); green required at the integration gate/merge. git, the engine tree
or temporalio unimportable = ENV_FAIL exit 2.
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

ENABLE_SIGNAL = "enable_narrowed_anchor"
PASS = 0
FAIL = 0


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
    """Stubbed workflow facade (the t261011-17 seam). patched() models the
    memo-poisoned in-flight lane: the OLDER KI-220 patch id answers True (the
    instance predates nothing there), the KI-350 narrowed-face id answers
    False FOREVER (its first evaluation replayed pre-fix history) — plus the
    sha the lane_head_sha activity returns."""
    sha = ""
    calls = 0
    result_ok = True

    @staticmethod
    def patched(pid):
        return pid != dev_lane.KI350_NARROWED_FACE_PATCH_ID

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        _StubWf.calls += 1
        if not _StubWf.result_ok:
            raise RuntimeError("lane_head_sha boom")
        return {"ok": True, "sha": _StubWf.sha}


def _handler():
    h = getattr(dev_lane.DevLaneWorkflow, ENABLE_SIGNAL, None)
    return h


_UNSET = object()


def _enable(wf, payload=_UNSET):
    """Deliver the enable event to the workflow instance. Binds to the
    declared SIGNAL NAME (public contract), not to any private flag. A
    handler that RAISES on any delivery (including a malformed one) is a
    named FAIL — the contract says the event is idempotent and a malformed
    payload is ignored, never a crash."""
    h = _handler()
    if h is None:
        _fail("the %s signal is absent on DevLaneWorkflow (the KI-356 "
              "enable event is not implemented)" % ENABLE_SIGNAL)
        return False
    try:
        if payload is _UNSET:
            try:
                out = h(wf)
            except TypeError:
                out = h(wf, {})
        else:
            out = h(wf, payload)
        if asyncio.iscoroutine(out):
            out = asyncio.run(out)
        return out is None
    except Exception as e:  # noqa: BLE001 — a raising handler breaks the contract
        _fail("delivering %s (payload=%r) raised %s: %s — the enable event "
              "must be idempotent and malformed-input-safe, never a crash"
              % (ENABLE_SIGNAL, payload, type(e).__name__, e))
        return False


def _make_wf(ticket="t261025-08"):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"worktree": "wt", "branch": "lane/x"}
    wf.ticket_id = ticket
    wf._log = lambda *a, **k: None
    wf._now_epoch = lambda: 1700000000
    return wf


def _record(targeted, ran=3, **kw):
    """An ENABLED lane (the enable event delivered first), then the round's
    green-run recording — every D-leg runs under the event, not the patch."""
    wf = _make_wf()
    _enable(wf)
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=ran, **kw), targeted))
    return wf


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=cwd,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, p.stderr.strip()))
    return p.stdout.strip()


def make_fixture_repo():
    """main at c0 -> lane at c1 (proven) -> main advances to c2 -> lane syncs
    main. After the sync the lane HEAD contains current main."""
    d = tempfile.mkdtemp(prefix="t26102508-repo-")
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
    _git("checkout", "lane/x", cwd=d)
    _git("merge", "main", "-m", "sync main", cwd=d)
    head = _git("rev-parse", "HEAD", cwd=d)
    return d, proven, head


def main():
    dev_lane.workflow = _StubWf
    repo, proven, head = make_fixture_repo()
    try:
        # ---------- B first (inert control on the un-enabled lane)
        before = _StubWf.calls
        _StubWf.sha = head
        wf_b = _make_wf()
        asyncio.run(wf_b._ki220_record_green_run(_Receipt(ran=3), True))
        if wf_b.meta.get("last_green_run") or wf_b.meta.get("green_run_note") \
                or _StubWf.calls != before:
            _fail("B: WITHOUT the enable event the memo-closed lane is not "
                  "inert (meta=%s, calls %d->%d)"
                  % (wf_b.meta, before, _StubWf.calls))
        else:
            _pass("B: without the enable event the unpatched lane stays "
                  "byte-inert (no face, no lane_head_sha call, no note)")

        # ---------- A: THE WEDGE, POSITIVE
        wf_a = _make_wf()
        if not _enable(wf_a):
            pass  # the absence was already failed by name in _enable
        face = None
        if _handler() is not None:
            if not wf_a.meta or "narrowed" not in json.dumps(
                    wf_a.meta, default=str).lower():
                _fail("A: the enable event left NOTHING observable on the "
                      "ticket meta (a steward must see the lane was enabled "
                      "without grepping the log): %s"
                      % json.dumps(wf_a.meta, default=str))
            _StubWf.sha = head
            asyncio.run(wf_a._ki220_record_green_run(_Receipt(ran=3), True))
            face = wf_a.meta.get("last_green_run")
            if not isinstance(face, dict) or not face.get("sha"):
                _fail("A: enabled + patch-gate-memo-closed + GREEN targeted "
                      "round recorded NO face (KI-356 unwedged in the wrong "
                      "place): %s" % json.dumps(wf_a.meta, default=str))
            else:
                if face.get("narrowed") is not True:
                    _fail("A: face lacks the declared narrowed marker: %s"
                          % face)
                elif face.get("sha") != head:
                    _fail("A: face sha %r is not the CURRENT lane HEAD %r "
                          "(a stale anchor must never be minted)"
                          % (face.get("sha"), head))
                else:
                    item = shared.green_run_check_item(face, head)
                    if not item.get("green"):
                        _fail("A: merge_check item is not green on the "
                              "refreshed face: %s" % item)
                    elif "narrowed" not in str(
                            item.get("reason_code", "")).lower():
                        _fail("A: green is not judged BY NAME "
                              "(reason_code=%r)" % item.get("reason_code"))
                    else:
                        _pass("A: the enable event un-wedges the memo-closed "
                              "lane — a targeted green round re-anchors the "
                              "face on the CURRENT lane HEAD, judged green "
                              "by name")

        # ---------- C: idempotence + malformed input
        if _handler() is not None:
            wf_c = _make_wf()
            ok1 = _enable(wf_c)
            meta1 = json.dumps(wf_c.meta, sort_keys=True, default=str)
            ok2 = _enable(wf_c)
            _enable(wf_c, payload={"garbage": ["injected", 1]})
            meta2 = json.dumps(wf_c.meta, sort_keys=True, default=str)
            if not (ok1 and ok2):
                _fail("C: a repeat enable delivery was refused (idempotent "
                      "arms must accept re-delivery)")
            elif meta1 != meta2:
                _fail("C: re-delivering the enable event changed the meta "
                      "(not idempotent): %s vs %s" % (meta1, meta2))
            else:
                _pass("C: the enable event is idempotent and a malformed "
                      "payload is ignored (no crash, no phantom change)")

        # ---------- D: fail-closed under enable
        if _handler() is not None:
            wf_d1 = _record(True, ran=0)  # zero-run targeted round
            if "last_green_run" in wf_d1.meta:
                _fail("D1: a zero-run targeted round minted a face (the "
                      "KI-220 zero-run supply stop belongs to the full "
                      "rounds): %s" % wf_d1.meta["last_green_run"])
            else:
                _pass("D1: zero-run targeted round stays faceless under "
                      "enable (KI-220 supply stop intact)")
            wf_d2 = _record(True, ran=3, error="scenario boom")
            if "last_green_run" in wf_d2.meta:
                _fail("D2: a RED targeted round minted a face: %s"
                      % wf_d2.meta["last_green_run"])
            else:
                _pass("D2: a red targeted round stays faceless under enable")
            wf_d3 = _make_wf()
            _enable(wf_d3)
            _StubWf.result_ok = False
            asyncio.run(wf_d3._ki220_record_green_run(_Receipt(ran=3), True))
            _StubWf.result_ok = True
            if "last_green_run" in wf_d3.meta:
                _fail("D3: a lane_head_sha failure minted a fabricated green "
                      "face: %s" % wf_d3.meta["last_green_run"])
            elif not wf_d3.meta.get("green_run_note"):
                _fail("D3: the sha-resolution failure left NO named miss "
                      "note on the meta (the t261011-17 observability "
                      "contract): %s" % json.dumps(wf_d3.meta, default=str))
            else:
                _pass("D3: lane_head_sha failure stays fail-closed with the "
                      "named miss note")
            wf_d4 = _record(False, ran=5)  # full closing round
            face_d4 = wf_d4.meta.get("last_green_run") or {}
            if face_d4.get("narrowed") is True:
                _fail("D4: a FULL closing round was marked narrowed")
            else:
                _pass("D4: full closing rounds are unchanged under enable "
                      "(no narrowed marker — release reads only full runs)")

        # ---------- E: the escape journey over a real git fixture
        if _handler() is not None and isinstance(face, dict):
            _StubWf.sha = head
            wf_e = _make_wf()
            _enable(wf_e)
            asyncio.run(wf_e._ki220_record_green_run(_Receipt(ran=2), True))
            face_e = wf_e.meta.get("last_green_run") or {}
            item = shared.green_run_check_item(face_e, head)
            if not item.get("green"):
                _fail("E: the enabled round did not re-anchor the face green "
                      "on the synced tree: %s" % item)
            else:
                res = asyncio.run(agent_activities.land_to_line(
                    agent_activities.LandToLineArgs(
                        ticket_id="t261022-14", project_key="p", line_id="l",
                        worktree=repo, proven_sha=head)))
                if "does not contain current main" in (res.error or ""):
                    _fail("E: still wedged at the contains-main guard after "
                          "the enabled narrowed round: %s" % res.error)
                else:
                    _pass("E: the t261022-14 shape lands past the "
                          "contains-main guard after ONE enabled targeted "
                          "green round (refusal now: %s)"
                          % (res.error or "ok")[:120])
            # regression control: a genuinely stale anchor still refuses,
            # naming the satisfying run (intent ownership: t26102412)
            item = shared.green_run_check_item(face_e, proven)
            if item.get("green") or item.get("reason_code") != "stale" or \
                    not ("narrowed" in json.dumps(item, default=str).lower()
                         or "gate round" in json.dumps(
                             item, default=str).lower()):
                _fail("E-control: a genuinely stale anchor is not refused by "
                      "name naming the satisfying run: %s" % item)
            else:
                _pass("E-control: a genuinely stale anchor still refuses by "
                      "name naming the satisfying run")

    finally:
        shutil.rmtree(repo, ignore_errors=True)

    if FAIL:
        print("FAIL t26102508-narrowed-anchor-reach: %d leg(s) red" % FAIL)
        sys.exit(1)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % PASS)
    print("PASS t26102508-narrowed-anchor-reach: the KI-356 enable event "
          "reaches the in-flight lanes the patch gate never could")
    sys.exit(0)


if __name__ == "__main__":
    main()
