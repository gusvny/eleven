#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-24 场景②：零执行供给红 STOP → 修复供给 → retry_qc 真跑本票场景 → 合并闸绿跑前置（灰盒 L3，真 docker 台）。

KI-220 端到端用户旅程（工单正文 t261008-07 实案的戏剧重演）：
  相一（注入供给装配失败）：夹具仓 integration 声明带 supply 项（marker 缺席时
     exit 7）→ 闸零执行（ran=0）供给红 ⇒ 票 STOP blocked（旧行为=豁免照走、
     arbitrate pass 直进 merge 假绿）——断言：终态 blocked、封据点名供给面
     （SUPPLY_SIDE_RED + need 名）、出路 retry_qc 在场、arbitrate 桩账本 0 轮
     （拦阻在路由决策点，arbitrate 从未被咨询 ⇒ 无假判决、轮预算未被消费）；
  相二（docker 恢复模拟 + retry_qc）：落 marker（供给恢复）→ 人 op=retry_qc 唤醒
     → 闸真跑本票场景 ran=1 绿 → arbitrate 桩 pass（仅此 1 轮）→ merge_check 新
     检查项（验收场景本树绿跑）绿 ⇒ 票推进 merge 段挂人审——「至少一次绿跑」
     成为合并闸可见前置（KI-217 出口①与 KI-220 同一机制）；相一被拦时票从未
     到达 merge（反面已由相一 blocked 断言承担）。

与既有资产 intent 分工（防重复声明）：
  · 同票 sc_supply_zero_run_blocker（ro，离线）锁「真出口 err × 分类器 × 停止
    路由 × 计轮账本 × merge_check 项真值表」五环接缝——本条锁**真 worker 工作流
    全旅程**（STOP→恢复→retry_qc→merge awaiting-human），接缝场景无法观测
    retry_qc 唤醒与 merge 推进；
  · t260917-09 两场景锁连续语义复位边与抖动/环境红豁免（判决序列桩）——本条
    注入的是**闸回执形态**（供给红，非 tests-fault 判决），彼族无此注入面；
  · t260908-01 sc_ki061_* 锁超限 blocked 复活，非本面。
驱动形态：lib_ki061/lib_gate 台架 + t260917-09 序列桩（本票 verdict 恒 pass——
  相一 STOP 发生在 arbitrate 之前，相二恢复后一判即过）；夹具仓 verify.yaml 带
  supply 项（marker 文件经 worker→activity→verify_lane→supply 继承 env 指路，
  T09_FIXTURE_MODE 同款继承链）。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台缺件=环境红
  点名，不写 SKIP）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B integration/t261008-24/tests/sc_zero_run_gate_stop.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (os.path.join(REPO, "integration"),
           os.path.join(REPO, "integration", "t260904-02"),
           os.path.join(REPO, "integration", "t260908-01"),
           os.path.join(REPO, "integration", "t260917-09")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib_gate import (Fail, accepted, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_ki061 import (make_fixture_repo as k061_fixture, poll,  # noqa: E402
                       query_snapshot, spawn_worker, stage_env, wait_worker_alive)
import lib_t26091709 as t09

TID = "t26100824-gate-stop"
KEY = "t26100824"
NEED_NAME = "测试台供给（t261008-24 场景桩）"
WHO = "宿主"
POLL_DRIVE = 300   # 单相驱动预算（秒）
ADVANCED_STAGES = ("merge_check", "merge")

# 供给闸门脚本：marker（绝对路径经 env 继承）缺席=exit 7（供给装配失败态）；
# 在场=exit 0（docker 恢复模拟态）。integration cmd 桩恒绿（t260920-01 D 对照
# 同款 SCENARIOS 汇总行契约）——恢复后真跑 ran=1>0，喂 merge_check 绿跑前置。
VERIFY_YAML = (
    "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: %s\n      cmd: python3 supply_gate.py\n" % NEED_NAME)
SUPPLY_GATE = (
    "import os, sys\n"
    "ok = os.environ.get('T24_SUPPLY_OK', '')\n"
    "if ok and os.path.exists(ok):\n"
    "    sys.exit(0)\n"
    "print('boom：docker test stage 不可达（供给装配失败注入）')\n"
    "sys.exit(7)\n")
PASS_STUB = ("print('PASS [t24 对照桩]')\n"
             "print('SCENARIOS ran=1 pass=1 fail=0 env'+'_fail=0 na=0 (0s)')\n"
             "import sys; sys.exit(0)\n")

STATS = {"ok": 0, "fail": 0}


def check_fn(fail):
    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r
    return check


def make_t24_fixture(tmp):
    """夹具项目仓：k061 骨架 git init + verify.yaml（integration+supply）+ 桩入库。"""
    repo = k061_fixture(tmp)
    with open(os.path.join(repo, "verify.yaml"), "w", encoding="utf-8") as f:
        f.write(VERIFY_YAML)
    with open(os.path.join(repo, "supply_gate.py"), "w", encoding="utf-8") as f:
        f.write(SUPPLY_GATE)
    with open(os.path.join(repo, "integ_stub.py"), "w", encoding="utf-8") as f:
        f.write(PASS_STUB)

    def g(*a):
        import subprocess
        subprocess.run(["git", "-C", repo] + list(a), check=True,
                       capture_output=True, text=True)
    g("add", "-A")
    g("commit", "-qm", "t24 fixture: integration + supply gate")
    return repo


def wait_terminal(py, env, tid, worker, wlog, stub_log, fail, budget):
    """poll 到「blocked（任意封面）」或「推进（仲裁通过 handoff＋stage 到 merge 族挂人审）」。
    返回 ("blocked", snap) | ("advanced", snap) | (None, 末次 snap)。"""
    def _probe():
        if worker.poll() is not None:
            return None
        s = query_snapshot(py, env, tid)
        if s.get("stage_state") == "blocked":
            return ("blocked", s)
        if ("仲裁通过" in t09.handoff_text(s)
                and s.get("stage") in ADVANCED_STAGES):
            return ("advanced", s)
        return None
    got = poll(_probe, budget)
    if got is None:
        wait_worker_alive(fail, worker, wlog)
        got = (None, query_snapshot(py, env, tid))
    return got


def main():
    fail = Fail("t261008-24 零执行供给红 STOP→恢复→retry_qc→合并闸绿跑前置端到端")
    check = check_fn(fail)
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26100824b-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    stage_name = "t26100824b-%d" % os.getpid()
    stage_downed = False
    marker = os.path.join(tmp, "supply-ok.marker")
    worker = None
    try:
        stage_mod, stage = require_stage(fail, stage_name, TID)
        repo = make_t24_fixture(os.path.join(tmp, "repo"))
        stub_path, stub_log = t09.write_stub(tmp, KEY)
        reg_dir = bench.write_registry(os.path.join(tmp, "reg"), KEY, repo)
        env = stage_env(stage, reg_dir, audit_env)
        env["SANDBAR_CALLER_PROJECT"] = KEY
        env["T09_STUB_LOG"] = stub_log
        env = t09.arb_seq_env(env, ["pass"])   # 恢复后一判即过；STOP 面它根本不该被咨询
        env["T24_SUPPLY_OK"] = marker          # 相一：marker 缺席=供给装配失败
        wlog = os.path.join(tmp, "worker.log")
        worker = spawn_worker(py, TID, env, wlog, stub_path, stub_log,
                              disable_ki061=False, arb_verdict="pass")
        check(worker.poll() is None, "worker 已拉起 pid=%s" % worker.pid)
        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": KEY,
            "title": "t261008-24 e2e: zero-run supply stop then recovery",
            "write_set": ["docs/"]}, env)
        _ok, _why = accepted(out, TID)
        check(rc == 0 and _ok, "ticket-start 受理（%s）" % _why)

        # ---- 相一：注入供给装配失败 → 零执行回执 ⇒ STOP blocked（命名封据） ----
        kind, snap = wait_terminal(py, env, TID, worker, wlog, stub_log, fail,
                                            POLL_DRIVE)
        txt = t09.snap_text(snap)
        rounds1 = t09.arb_rounds(stub_log)
        print("  相一 终态=%s stage=%s state=%s arb_rounds=%d"
              % (kind, snap.get("stage"), snap.get("stage_state"), rounds1),
              flush=True)
        check(kind == "blocked",
              "相一 零执行供给红 ⇒ 票 STOP blocked（旧行为=豁免照走 arbitrate 假绿；"
              "kind=%s stage=%s state=%s）" % (kind, snap.get("stage"),
                                              snap.get("stage_state")))
        check("SUPPLY_SIDE_RED" in txt,
              "相一 封据点名供给面：SUPPLY_SIDE_RED token 原样在场（不静音）")
        check(NEED_NAME.split("（")[0] in txt,
              "相一 封据点名 need（供给物不静默）")
        check("retry_qc" in txt,
              "相一 封据带出路 retry_qc（修供给后唤醒）")
        check(rounds1 == 0,
              "相一 arbitrate 桩账本 0 轮（拦阻在路由决策点：arbitrate 未被咨询、"
              "无假判决、轮预算未被消费；got=%d）" % rounds1)

        # ---- 相二：docker 恢复模拟（marker 落地）→ retry_qc → 真跑 ran=1 绿 → merge 前置 ----
        with open(marker, "w", encoding="utf-8") as f:
            f.write("recovered\n")
        # 261009：retry_qc 的 workflow 契约**只收裸 who**——带 note 会被显式拒收
        # （client.py:1527 原文「retry_qc 不收 note（workflow 契约只收 who）」；
        # 想带话要走 op=update 的 pending_add 或 ruling）。本场景此前带 note，
        # 于是相二第一步就被拒、后面三项全塌（实测 rc=0 ok=False）。
        rc, out = run_poc_client(py, "ticket", {
            "op": "retry_qc", "ticket_id": TID, "who": WHO}, env)
        doc = parse_out_json(out)
        check(rc == 0 and doc.get("ok") is True,
              "相二 op=retry_qc 受理（rc=%s ok=%s out尾=%s）"
              % (rc, doc.get("ok"), (out or "")[-140:]))
        kind2, snap2 = wait_terminal(py, env, TID, worker, wlog, stub_log, fail,
                                              POLL_DRIVE)
        rounds2 = t09.arb_rounds(stub_log)
        print("  相二 终态=%s stage=%s state=%s arb_rounds=%d"
              % (kind2, snap2.get("stage"), snap2.get("stage_state"), rounds2),
              flush=True)
        check(kind2 == "advanced",
              "相二 恢复+retry_qc → 闸真跑 ran=1 绿 → 推进 merge 族挂人审"
              "（kind=%s stage=%s state=%s）"
              % (kind2, snap2.get("stage"), snap2.get("stage_state")))
        check(rounds2 == 1,
              "相二 arbitrate 恰 1 轮（恢复轮一判即过，无额外空转；got=%d）" % rounds2)
        ho = t09.handoff_text(snap2)
        check("仲裁通过" in ho, "相二 handoff 含仲裁通过（真判非借位）")

        audit = read_audit_jsonl(audit_log)
        check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条"
              % len(audit))
        down = stage_down(stage_mod, stage_name)
        stage_downed = True
        resid = (down or {}).get("residue") if isinstance(down, dict) else down
        check(not resid, "拆台零残留（residue=%s）" % (resid,))
    finally:
        if worker is not None:
            t09.kill_tree(worker)
        if stage_mod is not None and not stage_downed:
            try:
                stage_down(stage_mod, stage_name)
            except Exception:
                pass
        if os.environ.get("T09_KEEP_TMP") == "1":
            print("TMP preserved（T09_KEEP_TMP=1）: %s" % tmp, flush=True)
        else:
            t09.cleanup_tmp(tmp)
    print("SC sc_zero_run_gate_stop pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
