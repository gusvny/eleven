#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-24 场景②：版本与预期不符的执行面——spawn 缝上响亮点名 + STRICT 硬闸。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
工单验收③「版本与预期不符→响亮」的执行半边（用户承诺=「升级切错版本不可能
悄悄跑」）。真 docker 台+真工单链（dsh 版本桩作 agent 脑，秒回合法回执）双腿：
- 缺省不拦腿（SANDBAR_DSH_STRICT 缺省 off）：桩版本(9.9.9-stub)≠
  SANDBAR_DSH_EXPECTED_VERSION(0.1.1-rc.2) → spawn 照走（桩被真调 ≥1 次）、
  段照常完成（回执合法 → create_plan 出结果），且 worker 日志出现同时点名
  actual/expected 两个版本字面量的响亮行——「带病跑但喊得出来」；
- STRICT 硬闸腿（SANDBAR_DSH_STRICT=1）：同 mismatch → 版本桩的 agent 形态
  调用恒为 0（spawn 在执行被钉二进制前被拒）+ 日志出现点名两版本的硬闸红
  ——「宁可停也不悄悄跑错版本」。不另设 snapshot「不出结果」腿：闸挂点在
  worker 启动时票队列即无人服务，查询通道随 worker 一起死，该观测结构性
  不可达；闸语义由「响亮红+调用恒 0」双腿完备证明。
判定不锚 boot/spawn 哪个挂点（实现在任一挂点响都算兑现用户承诺），锚的是
组合语义：缺省=跑+点名；STRICT=不跑+点名。两腿合取才能同时抓住
「静默跑错版本」与「静默拒跑」两个方向的腐烂。

intent 分工（防 intent 级重复）：
- sc_t260916_24_dsh_face_meta（场景①）＝启动记录面（meta 里 dsh face 的内容
  契约）；本条＝spawn 执行面（响亮+闸语义），同旋钮不同行为面；
- t260905-10-host-ruling-injection＝SANDBAR_AGENT_CMD 桩脑改道下的宿主裁决
  注入链路；本条只借它的真票链手法（fixture 仓+专属 worker+snapshot 轮询），
  被测契约是版本面，不是裁决面；
- developer L1 UT（test_t260916_24_dsh_pin）锚 check_expected 函数语义；
  本条锚真工作流链上的用户可感知终态（日志行/桩账本/票进度）。

三态契约：docker/镜像/bench 缺席=ENV_FAIL exit 2。实现段落地前红属预期（TDD
信号：mismatch 无点名行/STRICT 不拒=FAIL 点名），arbitrate/merge 期必须绿。

红线（testing-guide）：被测 worker/client 子进程经 bench.audit_hook_env 审计
钩子护体，终局断言审计账本为空；一切状态写临时目录；进程 TERM→KILL 兜底。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
sys.path.insert(0, HERE)
from lib_gate import (Fail, poc_python, read_audit_jsonl, require_bench,  # noqa: E402
                      require_stage, run_poc_client, stage_down)
from lib_t26091624 import (STUB_VERSION, make_fixture_repo, make_stub,  # noqa: E402
                           log_hits_literal_pair, parse_json_loose, poll,
                           spawn_worker, stage_env, stub_calls, terminate_worker)

EXPECTED_OK = "0.1.1-rc.2"   # expected（宿主现装版）
TID_LOUD = "t26091624-loud"
TID_STRICT = "t26091624-strict"
PROJ_KEY = "t26091624-loud"
STAGE_BUDGET = 300           # 真票链每腿轮询上限（秒）


def query_snapshot(py, env, tid):
    rc, out = run_poc_client(py, "ticket", {"op": "query", "ticket_id": tid}, env)
    return ((parse_json_loose(out).get("result") or {}).get("snapshot")) or {}


def main():
    fail = Fail("t260916-24 ②版本预期不符执行面（缺省响亮不拦 + STRICT 硬闸）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26091624-loud-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stub, stub_log = make_stub(tmp)
    stage_mod = None
    stage = None
    workers = []
    try:
        stage_mod, stage = require_stage(fail, "t26091624-loud-%d" % os.getpid(),
                                         "t26091624-loud")
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        env = stage_env(stage, registry_dir=reg_dir, audit_env=audit_env)

        def boot_worker(tid, extra):
            """工单专属 worker（新前缀队列 poll；夹具票全新开号无旧前缀工作流，
            旧前缀兜底属存量面勿新增——宿主令 260904 旧名退役）。"""
            meta_path = os.path.join(tmp, "%s.meta" % tid)
            log_path = os.path.join(tmp, "%s.worker.log" % tid)
            wenv = stage_env(stage, registry_dir=reg_dir, audit_env=audit_env, extra={
                "SANDBAR_TASK_QUEUES": "sandbar-ticket-%s" % tid,
                "SANDBAR_WATCH_WORKFLOW": tid,
                "SANDBAR_WATCH_INTERVAL_SEC": "2",
                "SANDBAR_WORKER_META": meta_path,
                "SANDBAR_AGENT_CMD": stub,  # 自执行单 token：引擎以 cmd[0] 为被钉二进制
                "SANDBAR_DSH_EXPECTED_VERSION": EXPECTED_OK,
                "DSH_STUB_LOG": stub_log,
            })
            for k in ("SANDBAR_DSH_STRICT",):
                wenv.pop(k, None)
            wenv.update(extra or {})
            w = spawn_worker(py, wenv, log_path)
            workers.append(w)
            return w, log_path

        def start_ticket(tid):
            rc, out = run_poc_client(py, "ticket-start", {
                "ticket_id": tid, "template_id": "dev-lane", "project": PROJ_KEY,
                "title": "dsh 版本预期不符执行面", "write_set": ["docs/"]}, env)
            return rc == 0 and tid in out, "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:])

        # ---------- 腿① 缺省 off：带病跑但喊得出来 ----------
        # 计数只认 agent 形态调用（worker 启动的 face 探测也会记 version 行，
        # 不过滤会把「探测了桩」误当「spawn 走了桩」）
        def agent_rows():
            return [r for r in stub_calls(stub_log) if r.get("mode") == "agent"]
        n0 = len(agent_rows())
        w1, log1 = boot_worker(TID_LOUD, None)
        ok, msg = start_ticket(TID_LOUD)
        fail.check(ok, "腿①：%s" % msg)

        def _spawned():
            return agent_rows()[n0:] or None
        spawned = poll(_spawned, STAGE_BUDGET)
        if spawned is None and w1.poll() is not None:
            fail.check(False, "腿①：worker 提前退出（rc=%s）——日志尾：%s"
                       % (w1.returncode, ""))
        fail.check(spawned is not None,
                   "腿①：expected 不符（缺省 off）spawn 照走——版本桩被真调（新增 %d 次调用）"
                   % len(spawned or []))

        def _stage_done():
            s = query_snapshot(py, env, TID_LOUD)
            return s if "create_plan" in (s.get("results") or {}) else None
        done = poll(_stage_done, STAGE_BUDGET)
        fail.check(done is not None,
                   "腿①：段照常完成（create_plan 出结果）——缺省不拦的正面证据")

        hits = log_hits_literal_pair(log1, STUB_VERSION, EXPECTED_OK)
        fail.check(bool(hits),
                   "腿①：worker 日志有同时点名 actual(%s)/expected(%s) 的响亮行（实得 %d 行）"
                   "——版本与预期不符喊得出来" % (STUB_VERSION, EXPECTED_OK, len(hits)))
        terminate_worker(w1)

        # ---------- 腿② STRICT=1：宁可停也不悄悄跑错版本 ----------
        n1 = len(agent_rows())
        w2, log2 = boot_worker(TID_STRICT, {"SANDBAR_DSH_STRICT": "1"})
        ok, msg = start_ticket(TID_STRICT)
        fail.check(ok, "腿②：%s" % msg)

        def _strict_named():
            return log_hits_literal_pair(log2, STUB_VERSION, EXPECTED_OK) or None
        named = poll(_strict_named, STAGE_BUDGET)
        fail.check(named is not None,
                   "腿②：STRICT 硬闸红点名两版本字面量（日志 %d 行）——响亮语义在闸上"
                   % len(named or []))
        n2 = len(agent_rows())
        fail.check(n2 == n1,
                   "腿②：版本桩 agent 形态调用恒 0（%d→%d）——spawn 在执行被钉二进制前被拒，"
                   "不悄悄跑错版本" % (n1, n2))
        # 注：不另设「snapshot 无 create_plan 结果」腿——闸挂点在 worker 启动时
        # （实现取 boot 拒启），票队列从此无人服务，snapshot 查询通道随 worker
        # 一起死，该观测结构性不可达；闸语义已由「响亮红 + agent 调用恒 0」双腿
        # 完备证明（STRICT 只告警不拒的腐烂会被「调用恒 0」当场抓住）。

        terminate_worker(w2)

        # ---------- 红线：被测子进程零触碰生产端口 ----------
        rows = read_audit_jsonl(audit_log)
        fail.check(not rows, "审计账本为空：被测子进程零连生产端口（实得 %d 条）" % len(rows))
    finally:
        for w in workers:
            terminate_worker(w)
        if stage is not None:
            try:
                stage_down(stage_mod, stage["project"])
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
