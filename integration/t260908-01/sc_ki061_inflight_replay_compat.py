#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260908-01 场景②：在飞 workflow 重放兼容（KI-061 验收②的机械面，99809 重放炸族回归闸）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
在 docker 测试台上先**制造修复前形态的在飞 history**（DISABLE=1 worker 驱动 6 轮超限
blocked → retry_qc 唤醒一次 → settle→再 blocked＝t260907-10 现形态），然后用
replay_check（只读 list/fetch history → temporalio Replayer 用**当前修复后代码**回放）
断言两子用例：
  子用例一（唤醒穿越点回放）：blocked 等待中的在飞票回放 ok=true——修复代码对「含历史唤醒
  穿越＋patched 求值」的旧形态 history 命令序列零分歧，workflow task 不 failing
  （044c692 裸改重放炸 99809 的同族故障回归闸）；
  子用例二（marker 消费回放）：修复 worker 复活票（retry → arbitrate 真 respawn、KI-061
  marker 写入 history）后再回放 ok=true——marker 在 history 的重放消费路径（notify 先行
  →同位 True）确定性稳定。

与场景①分工：彼锁 live 复活旅程（用户可感知面），本条锁重放确定性契约（部署兼容面）；
与 developer selfcheck（L2 两相闸，时间加速测试环境内）不同层：本条用真 docker 台
history 走 Replayer 离线回放。replay_check 只读（list_workflows/fetch_history），零写。

三态：docker/镜像/舞台缺件＝exit 2 ENV_FAIL；回放炸/断言破面＝exit 1。pool=exclusive。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
from lib_gate import (Fail, poc_python, require_bench, require_stage,  # noqa: E402
                      stage_down)
from lib_ki061 import (POC_DIR, arb_gens, drive_to_overlimit_blocked,  # noqa: E402
                       make_fixture_repo, poll, query_snapshot, read_stub_log,
                       send_signal, spawn_worker, wait_worker_alive)

TID = "t26090801b-replay"
PROJ_KEY = "t26090801b"


def run_replay_check(py, state, tid):
    """replay_check 只读回放指定工单（指向测试台，不碰任何真环境）。返回 (rc, payload)。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = state["namespace"]
    p = subprocess.run([py, os.path.join(POC_DIR, "replay_check.py"),
                        "--workflow", tid],
                       capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, json.loads(p.stdout or "{}")


def main():
    fail = Fail("t260908-01 ②在飞 workflow 重放兼容（KI-061）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26090801b-")
    stage_mod = None
    workerA = None
    workerB = None
    try:
        stage_mod, stage = require_stage(fail, "%s-%d" % (PROJ_KEY, os.getpid()),
                                         "t26090801b")
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        os.environ["_KI061_REG_DIR"] = reg_dir
        workerA, env, stub_log = drive_to_overlimit_blocked(
            py, fail, tmp, TID, stage, PROJ_KEY, None)

        # ---------- 子用例一：pre-fix 形态在飞 history 的重放 ----------
        def _retry_count():
            s = query_snapshot(py, env, TID)
            tl = s.get("timeline") or []
            return s, len([e for e in tl
                           if str(e.get("state") or "") == "retry-requested"])
        _, n_retry0 = _retry_count()  # 基线（首发前=0；旧口径写死 >=2 是
        # 与场景①同源的计数错觉，260908 一并修正）
        rc, out = send_signal(py, stage, TID, "retry_qc", "宿主")
        fail.check(rc == 0, "相一 retry_qc 发信（rc=%s）" % rc)

        def _wake_done():
            s, n = _retry_count()
            return s if n > n_retry0 else None
        s2 = poll(_wake_done, 120)
        if s2 is None:
            wait_worker_alive(fail, workerA, os.path.join(tmp, "workerA.log"))
            fail.bail("唤醒未被消费（timeline 未见新增 retry-requested）")
        time.sleep(8)  # settle→再 blocked 转变窗，history 定形
        wait_worker_alive(fail, workerA, os.path.join(tmp, "workerA.log"))
        fail.check((query_snapshot(py, env, TID)).get("stage_state") == "blocked",
                   "相一唤醒后再 blocked（在飞 history＝唤醒穿越点形态）")

        rc, payload = run_replay_check(py, stage, TID)
        r = (payload.get("results") or [{}])
        r0 = r[0] if r else {}
        fail.check(rc == 0 and payload.get("ok") is True and r0.get("ok") is True,
                   "子用例一：修复代码回放 pre-fix 形态 history ok（rc=%s ok=%s r0=%s）"
                   % (rc, payload.get("ok"), json.dumps(r0, ensure_ascii=False)[:200]))

        # ---------- 子用例二：复活（marker 入 history）后再回放 ----------
        workerA.terminate()
        try:
            workerA.wait(timeout=15)
        except subprocess.TimeoutExpired:
            workerA.kill()
        workerB = spawn_worker(py, TID, env, os.path.join(tmp, "workerB.log"),
                               os.path.join(tmp, "ki061_stub.py"), stub_log,
                               disable_ki061=False, arb_verdict="pass")
        fail.check(workerB.poll() is None, "相二 worker（修复启用）已拉起 pid=%s" % workerB.pid)
        rc, out = send_signal(py, stage, TID, "retry_qc", "宿主")
        fail.check(rc == 0, "相二 retry_qc 发信（rc=%s）" % rc)

        gens_before = arb_gens(read_stub_log(stub_log))

        def _respawned():
            return arb_gens(read_stub_log(stub_log)) if \
                len(arb_gens(read_stub_log(stub_log))) > len(gens_before) else None
        if poll(_respawned, 300) is None:
            wait_worker_alive(fail, workerB, os.path.join(tmp, "workerB.log"))
            fail.bail("相二 300s 未见 arbitrate respawn（marker 未入 history，子用例二前提缺失）")
        fail.check(True, "相二 arbitrate respawn（KI-061 marker 已入 history）")
        time.sleep(15)  # 事件落定窗：marker/arbitrate activity 事件入 history

        rc, payload = run_replay_check(py, stage, TID)
        r = (payload.get("results") or [{}])
        r0 = r[0] if r else {}
        fail.check(rc == 0 and payload.get("ok") is True and r0.get("ok") is True,
                   "子用例二：含 marker 的 post-fix history 回放 ok（rc=%s ok=%s r0=%s）"
                   % (rc, payload.get("ok"), json.dumps(r0, ensure_ascii=False)[:200]))
    finally:
        for w in (workerA, workerB):
            if w is not None and w.poll() is None:
                w.kill()
        if stage_mod is not None:
            stage_down(stage_mod, "%s-%d" % (PROJ_KEY, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
