#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260908-01 场景①：仲裁超限 blocked 的两相复活旅程（KI-061 端到端，验收①②的用户可感知面）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
真起 docker 测试台 temporal-only ＋ 工单专属 worker，复刻 t260907-10 卡死并演示修复后复活——
  相一（复刻卡死＝02:12 形态）：worker 带 SANDBAR_TEST_DISABLE_KI061=1（create_plan v2 S3
  契约名：读定于 worker 构造期＝模拟修复前 worker），tests-fault 桩驱动 6 轮超限 →
  arbitrate blocked；宿主注入裁决（host_ruling）后 retry_qc 唤醒 → 断言**吃 memoized
  仲裁结论立即再 blocked、arbitrate 零 respawn**（被修故障的机械形态留证）。
  相二（复活＝验收①）：换修复后 worker（开关去除），再 retry_qc → 断言 arbitrate 真
  respawn（账本新 spawn、gen 递增）、其 prompt 含宿主终裁文本（host_rulings 注入消费）、
  桩回 verdict=pass 后票**离开 arbitrate blocked**（仲裁边过闸）。

与既有资产 intent 分工（防重复声明）：
- t260905-10 sc_host_ruling_injection（KI-053）：格式纠正路径到 blocked、单 worker、
  只证注入可见——畸形 ruling 拒收/多裁决累积归彼，本场景不重复；
- developer selfcheck_ki061_wake_reset（L2 时间加速测试环境两相闸，方案 S3）：机制锁随
  实现演化可重写；本条＝真 docker 台真进程双 worker 切换的用户旅程面，层级不同不互替。
- 实票 t260907-10 复活归宿主发 retry（红线），本条在隔离台等价复刻，不碰实票数据。

断言面＝stub 账本（agent 实收 prompt）/ snapshot（stage/stage_state/host_rulings），
不逐字节锚 prompt 文案（措辞是实现副本）。merge_check 及其后行为不在本条范围
（桩票无真泳道，过仲裁边即算旅程完成）。

三态：docker/镜像/舞台缺件＝exit 2 ENV_FAIL；被测行为破面＝exit 1。
pool=exclusive（真起 workflow 占台）。
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
from lib_gate import (Fail, poc_python, read_audit_jsonl, require_bench,  # noqa: E402
                      require_stage, run_poc_client, stage_down)
from lib_ki061 import (ARB_STUB, ENV_ARB_STUB_VERDICT, LAST_Q, arb_gens,  # noqa: E402
                       drive_to_overlimit_blocked, make_fixture_repo, poll,
                       query_snapshot, read_stub_log, send_signal, spawn_worker,
                       stage_env, wait_worker_alive)

TID = "t26090801a-wake"
PROJ_KEY = "t26090801a"
RULING_NOTE = "宿主终裁（260908）：测试集迭代到此为止，按现有测试面仲裁放行或明确降级口径"
RULING_WHO = "宿主"


def main():
    fail = Fail("t260908-01 ①超限 blocked 两相复活旅程（KI-061）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26090801a-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    workerA = None
    workerB = None
    try:
        stage_mod, stage = require_stage(fail, "%s-%d" % (PROJ_KEY, os.getpid()),
                                         "t26090801a")
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        os.environ["_KI061_REG_DIR"] = reg_dir
        workerA, env, stub_log = drive_to_overlimit_blocked(
            py, fail, tmp, TID, stage, PROJ_KEY, audit_env)
        wlogA = os.path.join(tmp, "workerA.log")

        # ---------- 相一断言：卡死形态（宿主终裁无可达消费点） ----------
        gens_at_block = arb_gens(read_stub_log(stub_log))
        fail.check(len(gens_at_block) >= 6,
                   "相一 arbitrate 已跑 %d 轮（≥6）后超限 blocked" % len(gens_at_block))
        rc, out = run_poc_client(py, "ticket", {
            "op": "ruling", "ticket_id": TID, "who": RULING_WHO,
            "note": RULING_NOTE}, env)
        fail.check(rc == 0, "host_ruling 注入受理（rc=%s out尾=%s）" % (rc, out[-120:]))
        snap = query_snapshot(py, env, TID)
        rulings = (snap.get("host_rulings")
                   or (snap.get("meta") or {}).get("host_rulings") or [])
        fail.check(any(RULING_NOTE in str(r.get("note") or "") for r in rulings),
                   "裁决入账（meta.host_rulings=%d 条）" % len(rulings))

        def _retry_count():
            s = query_snapshot(py, env, TID)
            tl = s.get("timeline") or []
            return s, len([e for e in tl
                           if str(e.get("state") or "") == "retry-requested"])
        _, n_retry0 = _retry_count()  # 基线：本票首发 retry 前通常为 0（260908 首跑
        # 实证旧口径写死 >=2 永不满足——发信前无任何 retry-requested 事件）
        rc, out = send_signal(py, stage, TID, "retry_qc", "宿主")
        fail.check(rc == 0, "相一 retry_qc 发信（rc=%s）" % rc)

        def _wake_processed():
            s, n = _retry_count()
            return s if n > n_retry0 else None
        # 等唤醒真被 workflow 消费（timeline 新增 retry-requested）＋ settle 转变窗
        s2 = poll(_wake_processed, 120)
        if s2 is None:
            wait_worker_alive(fail, workerA, wlogA)
            fail.bail("相一唤醒未被消费（timeline 未见新增 retry-requested）")
        time.sleep(8)  # grace：settle→再 blocked 转变窗，防早断言假绿
        gens_after = arb_gens(read_stub_log(stub_log))
        wait_worker_alive(fail, workerA, wlogA)
        fail.check(len(gens_after) == len(gens_at_block),
                   "相一唤醒后 arbitrate 零 respawn（%d→%d，memoized 消费复刻 02:12）"
                   % (len(gens_at_block), len(gens_after)))
        fail.check((query_snapshot(py, env, TID)).get("stage_state") == "blocked",
                   "相一唤醒后仍 blocked（宿主终裁无可达消费点＝被修故障形态）")

        # ---------- 相二：换修复后 worker（开关去除），再唤醒 ----------
        workerA.terminate()
        try:
            workerA.wait(timeout=15)
        except subprocess.TimeoutExpired:
            workerA.kill()
        workerB = spawn_worker(py, TID, env, os.path.join(tmp, "workerB.log"),
                               os.path.join(tmp, "ki061_stub.py"), stub_log,
                               disable_ki061=False, arb_verdict="pass")
        wlogB = os.path.join(tmp, "workerB.log")
        fail.check(workerB.poll() is None, "相二 worker（修复启用）已拉起 pid=%s" % workerB.pid)
        rc, out = send_signal(py, stage, TID, "retry_qc", "宿主")
        fail.check(rc == 0, "相二 retry_qc 发信（rc=%s）" % rc)

        def _revived():
            rows = arb_gens(read_stub_log(stub_log))
            if len(rows) > len(gens_after):
                s = query_snapshot(py, env, TID)
                return (rows, s) if s else (rows, {})
            return None
        got = poll(_revived, 300)
        wait_worker_alive(fail, workerB, wlogB)
        if got is None:
            s = query_snapshot(py, env, TID)
            fail.bail("相二 300s 内未见 arbitrate respawn（stage=%s state=%s 账本=%d 行）"
                      % (s.get("stage"), s.get("stage_state"),
                         len(read_stub_log(stub_log))))
        rows2, snap2 = got
        fail.check(True, "相二 arbitrate 真 respawn（账本 %d→%d 行）"
                   % (len(gens_after), len(rows2)))
        newest = rows2[-1]
        fail.check(newest["gen"] > gens_after[-1]["gen"],
                   "respawn gen 递增（%d→%d）" % (gens_after[-1]["gen"], newest["gen"]))
        fail.check(RULING_NOTE in newest["prompt"],
                   "respawn prompt 含宿主终裁（host_rulings 注入消费，len=%d）"
                   % len(newest["prompt"]))

        # pass 过仲裁边：等票进入 merge_check/merge（过仲裁边即算旅程完成；merge_check
        # 及其后不在本条范围——桩票无真泳道 commit，merge_check 红转 blocked 属预期不判）。
        # 两个反面教训（260908 首跑实证）：①不能锚 stage!="arbitrate"——分叉期超限 blocked
        # 的 snapshot stage 报分叉单边 acceptance_walkthrough，会立即假绿；②不能要求离开
        # blocked 态——merge_check blocked 是桩票合法终态。也不能接受任意出分叉段名集的
        # stage——verdict 仍 tests-fault 时 stage 会出到 run_integration_tests（假绿）；
        # 正向白名单 merge_check/merge 才锁死「pass 过闸」这一用户可感知行为。
        def _left():
            s = query_snapshot(py, env, TID)
            if s.get("stage") in ("merge_check", "merge"):
                return s
            return None
        left = poll(_left, 240)
        wait_worker_alive(fail, workerB, wlogB)
        fail.check(left is not None,
                   "verdict=pass 后票离开 arbitrate blocked（现 stage=%s state=%s；末次 query rc=%s out=%s）"
                   % ((left or {}).get("stage"), (left or {}).get("stage_state"),
                      LAST_Q.get("rc"), (LAST_Q.get("out") or "")[:200]))

        # ---------- 红线审计：零生产面接触 ----------
        audit = read_audit_jsonl(audit_log)
        fail.check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条" % len(audit))
    finally:
        for w in (workerA, workerB):
            if w is not None and w.poll() is None:
                w.kill()
        if stage_mod is not None:
            stage_down(stage_mod, "%s-%d" % (PROJ_KEY, os.getpid()))
        if os.environ.get("KI061_KEEP_TMP") == "1":
            print("TMP preserved（KI061_KEEP_TMP=1）: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
