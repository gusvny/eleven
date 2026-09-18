#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-09 集成场景：tests_rounds 上限「连续语义」端到端（真 docker 台）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
  tests-fault 上限的语义定为「连续 tests-fault 轮」（shared.py:287 注释口径；
  dev_lane.py:1157 旧注释 cumulative 是矛盾孤例）——任何非 tests-fault 边
  （code-fault 打回 / 人工接受 / 打回重验等重入）之后计数必须清零，长票不再被
  陈年轮次假封（260917 三票 t260916-19/-21、t260917-04 的「迭代超限转人工」
  共性机制）。上限本体不拆：连续 tests-fault 撞上限仍 blocked（对照腿）。
  与工单验收①的映射：[tf,tf,pass,tf×4] 矩阵在 L1 纯函数层（developer 交付）；
  本场景锁 L3 可观测的复位边——pass 判决直接路由 acceptance（复位只在重入时
  可观测），故 L3 钉 code-fault 复位边 + rework 重入复位边（与 pass/authz 复位
  共用同一单点收口），这是用户请求里「被外部打断的长票必然累积到上限」的直击面。

三腿（顺序执行，各腿单票单 worker 单舞台）：
  相一（code-fault 复位边）：桩判决序列 tf,tf,code-fault,tf,tf,tf,tf,tf（耗尽
        回落 pass）→ 连续语义下第 3 判决打回 implement 后计数清零，后续 5 轮
        tests-fault 计 1..5 恒迭代，第 9 判决回落 pass 进 acceptance——全程
        不 blocked；handoff「测试集迭代（第 1 轮）」出现 ≥2 次（复位签名）。
        旧累计语义下第 8 判决必 blocked（语义反转强断言）。
  相二（对照腿，上限仍在）：恒 tests-fault → 第 7 判决 blocked，回执含「超限」
        且出路关键词 authorize/rework/ruling/pause 全在（要求④：出路可执行，
        不许只写「转人工判读」）。
  相三（rework 重入复位边）：tf×5（计到上限邻界）→ 人 op=rework 打回 implement
        → 重进测试段计数清零 → 再 2 轮 tests-fault 计 1..2 + 回落 pass 进
        acceptance——不 blocked；旧语义（重入不清零）下第 7 判决必 blocked。

与既有资产 intent 分工（防重复声明）：
  · t260908-01 sc_ki061_* 锁「超限 blocked 的唤醒复活与重放兼容」（KI-061）；
  · t260912-03 sc_authz_* 锁「人授权接受判决」通道（cap 面 authorize 消费）；
  · 本票 sc_tests_false_escalation_guard 锁「假封防护」（抖动/环境红不计轮、
    不在册保守计轮、豁免超限面出路）——与本条（连续语义复位边）不同面不互替。
驱动形态：lib_ki061 台架同形 + 本票自有**序列桩**（lib_ki061.ARB_STUB 是常量
  verdict，序列耗尽确定性回落 pass——主腿确定性终态，防第 N+1 判决撞上限造成
  场景自身假红）。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台缺件=环境红
  点名，不写 SKIP）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
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

from lib_gate import (Fail, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_ki061 import (LAST_Q, make_fixture_repo as k061_fixture, poll,  # noqa: E402
                       query_snapshot, spawn_worker, stage_env, wait_worker_alive)
import lib_t26091709 as t09

# 各相独立票号/项目键（互不串台；registry 每相独立目录）
PHASES = [
    {"tid": "t26091709a-streak", "key": "t26091709a",
     "seq": ["tests-fault", "tests-fault", "code-fault",
             "tests-fault", "tests-fault", "tests-fault",
             "tests-fault", "tests-fault"],
     "title": "t260917-09 相一：code-fault 复位边连续语义"},
    {"tid": "t26091709b-cap", "key": "t26091709b",
     # 恒 tests-fault=长序列表达（桩「耗尽回落 pass」是主腿确定性终态机制；单元素
     # 序列第 2 判决即耗尽回落，恒 tf 必须用远超判决数的长度表达——blocked 会在
     # 第 7 判决停住，40 远够）
     "seq": ["tests-fault"] * 40,
     "title": "t260917-09 相二：上限仍在对照腿"},
    {"tid": "t26091709c-rework", "key": "t26091709c",
     "seq": ["tests-fault"] * 7,
     "title": "t260917-09 相三：rework 重入复位边"},
]
# 授权放行/推进后允许出现的舞台（桩票 merge_check 段 blocked 属合法终态，
# 不锚「state != blocked」单条；宽松集合防分叉期 stage 字段借位假红）
AFTER_STAGES = ("acceptance_walkthrough", "merge_check", "merge")
OVER_LIMIT_STAGES = ("arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
POLL_DRIVE = 240   # 单相驱动预算（秒）
WHO = "宿主"

STATS = {"ok": 0, "fail": 0}


def check_fn(fail):
    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r
    return check


def wait_terminal(py, env, tid, worker, wlog, stub_log, fail, budget):
    """poll 到「推进（仲裁通过后走到 merge 段挂起）」或「超限 blocked」，二选一返回。
    并行分叉期 stage 恒=acceptance_walkthrough（阶段字段借位，实测 260918）——推进
    判据只认「仲裁通过 handoff＋stage 已过走查段（merge_check/merge 挂起等签字）」，
    不认 walkthrough 面的 stage/state。返回 ("advanced", snap) | ("blocked", snap)
    | (None, 末次 snap)。"""
    def _probe():
        if worker.poll() is not None:
            return None  # 由调用方 wait_worker_alive 点名
        s = query_snapshot(py, env, tid)
        if (s.get("stage") in OVER_LIMIT_STAGES
                and s.get("stage_state") == "blocked" and "超限" in t09.snap_text(s)):
            return ("blocked", s)
        if ("仲裁通过" in t09.handoff_text(s)
                and s.get("stage") in ("merge_check", "merge")):
            return ("advanced", s)
        return None
    got = poll(_probe, budget)
    if got is None:
        wait_worker_alive(fail, worker, wlog)
        got = (None, query_snapshot(py, env, tid))
    return got


def run_phase(py, bench, fail, check, stage, audit_env, tmp, ph):
    tid, key, seq = ph["tid"], ph["key"], ph["seq"]
    # 每相独立桩账本（tag=key）：桩判决序号=账本行数，跨相共享会串相
    # （相二首判读到相一行数 → 直接回落 pass，恒 tf 腿全废）。
    stub_path, stub_log = t09.write_stub(tmp, key)
    wlog = os.path.join(tmp, "%s-worker.log" % tid)
    reg_dir = bench.write_registry(os.path.join(tmp, "reg-%s" % key), key,
                                   k061_fixture(os.path.join(tmp, "repo-%s" % key)))
    env = stage_env(stage, reg_dir, audit_env)
    env["T09_STUB_LOG"] = stub_log
    env = t09.arb_seq_env(env, seq)
    worker = spawn_worker(py, tid, env, wlog, stub_path, stub_log,
                          disable_ki061=False, arb_verdict="tests-fault")
    check(worker.poll() is None, "%s worker 已拉起 pid=%s" % (tid, worker.pid))
    rc, out = run_poc_client(py, "ticket-start", {
        "ticket_id": tid, "template_id": "dev-lane", "project": key,
        "title": ph["title"], "write_set": ["docs/"]}, env)
    check(rc == 0 and tid in out, "%s ticket-start 受理（rc=%s out尾=%s）"
          % (tid, rc, (out or "")[-140:]))
    try:
        if tid.endswith("-rework"):
            return phase_rework(py, env, tid, worker, wlog, stub_log, fail, check)
        return phase_drive(py, env, tid, worker, wlog, stub_log, fail, check)
    finally:
        t09.kill_tree(worker)


def phase_drive(py, env, tid, worker, wlog, stub_log, fail, check):
    """相一/相二共用驱动：等终态并按腿断言。"""
    is_control = tid.endswith("-cap")
    kind, snap = wait_terminal(py, env, tid, worker, wlog, stub_log, fail,
                               POLL_DRIVE)
    rounds = t09.arb_rounds(stub_log)
    print("  %s 终态=%s stage=%s state=%s arb_rounds=%d"
          % (tid, kind, snap.get("stage"), snap.get("stage_state"), rounds),
          flush=True)
    if is_control:
        txt = t09.snap_text(snap)
        check(kind == "blocked" and snap.get("stage_state") == "blocked",
              "相二 恒 tests-fault → 撞上限 blocked（第 7 判决；kind=%s state=%s）"
              % (kind, snap.get("stage_state")))
        check("超限" in txt, "相二 回执含「超限」（上限语义仍在，非拆上限）")
        for kw in ("authorize", "rework", "ruling", "pause"):
            check(kw in txt, "相二 超限回执出路关键词 %r 在（要求④出路可执行）" % kw)
        return
    # 相一：连续语义 → 推进 acceptance；旧累计语义 → 第 8 判决 blocked
    ho = t09.handoff_text(snap)
    check(kind == "advanced",
          "相一 tf,tf,code-fault,tf×5+回落 pass → 推进 acceptance 不假封"
          "（kind=%s stage=%s state=%s，arb_rounds=%d；旧累计语义第 8 判决必 blocked）"
          % (kind, snap.get("stage"), snap.get("stage_state"), rounds))
    check("超限" not in ho, "相一 全程无超限封（handoff 无「超限」）")
    check(ho.count("测试集迭代（第 1 轮）") >= 2,
          "相一 复位签名：「测试集迭代（第 1 轮）」出现 %d 次 ≥2（code-fault 后清零重计）"
          % ho.count("测试集迭代（第 1 轮）"))
    check("code-fault 打回 implement" in ho,
          "相一 code-fault 打回边在场（复位触发前提）")
    check(rounds >= 8, "相一 arbitrate 桩账本 %d 轮 ≥8（8 序列判决+回落 pass）" % rounds)


def phase_rework(py, env, tid, worker, wlog, stub_log, fail, check):
    """相三：tf×5 邻界 → 段间暂停门＋rework 打回 → 重入清零 → 再 2 轮 tf + 回落 pass。
    确定性投递：pause 让工作流在下一相位派发前停住（第 5 判决后的 integ 不会开跑），
    rework 压在暂停门口，resume 后先打回再派段（引擎暂停门注释的契约原文）——
    避免「判决已出、打回后到」的竞态假封（stage 采样对 0.3s 的 integ 窗必漏）。"""
    got = poll(lambda: (lambda n: n if n >= 5 else None)(
        t09.arb_rounds(stub_log)), POLL_DRIVE)
    if got is None:
        wait_worker_alive(fail, worker, wlog)
        fail.bail("相三 前 5 轮 tests-fault 未到位（账本=%s）" % t09.arb_rounds(stub_log))
    s5 = query_snapshot(py, env, tid)
    check(s5.get("stage_state") != "blocked",
          "相三 5 轮邻界仍未封（预增判定 ≤5 迭代；state=%s）" % s5.get("stage_state"))
    rc, out = run_poc_client(py, "ticket", {
        "op": "pause", "ticket_id": tid, "who": WHO,
        "note": "t260917-09 场景：暂停投递打回"}, env)
    doc = parse_out_json(out)
    check(rc == 0 and doc.get("ok") is True,
          "相三 op=pause 受理（rc=%s ok=%s out尾=%s）"
          % (rc, doc.get("ok"), (out or "")[-120:]))
    paused = poll(lambda: (lambda s: s if (
        s.get("paused") or (s.get("meta") or {}).get("paused")) else None)(
        query_snapshot(py, env, tid)), 120)
    if paused is None:
        s = query_snapshot(py, env, tid)
        fail.bail("相三 未进入 paused（stage=%s state=%s paused=%r）"
                  % (s.get("stage"), s.get("stage_state"), s.get("paused")))
    rc, out = run_poc_client(py, "ticket", {
        "op": "rework", "ticket_id": tid, "note": "t260917-09 场景：打回重验"
        "（rework 重入复位边）", "to_stage": "implement", "who": WHO}, env)
    doc = parse_out_json(out)
    check(rc == 0 and doc.get("ok") is True,
          "相三 op=rework 受理（rc=%s ok=%s out尾=%s）"
          % (rc, doc.get("ok"), (out or "")[-140:]))
    rc, out = run_poc_client(py, "ticket", {
        "op": "resume", "ticket_id": tid, "who": WHO}, env)
    doc = parse_out_json(out)
    check(rc == 0 and doc.get("ok") is True,
          "相三 op=resume 受理（rc=%s ok=%s out尾=%s）"
          % (rc, doc.get("ok"), (out or "")[-120:]))
    kind, snap = wait_terminal(py, env, tid, worker, wlog, stub_log, fail,
                               POLL_DRIVE)
    rounds = t09.arb_rounds(stub_log)
    stages = t09.stages_seen(stub_log)
    print("  %s 终态=%s stage=%s state=%s arb_rounds=%d implement出现=%d"
          % (tid, kind, snap.get("stage"), snap.get("stage_state"), rounds,
             stages.count("implement")), flush=True)
    ho = t09.handoff_text(snap)
    check(kind == "advanced",
          "相三 rework 重入后计数清零 → 再 2 轮 tf（计 1..2）+回落 pass 推进，不假封"
          "（kind=%s stage=%s state=%s；旧语义重入不清零第 7 判决必 blocked）"
          % (kind, snap.get("stage"), snap.get("stage_state")))
    check("超限" not in ho, "相三 全程无超限封（handoff 无「超限」）")
    check(ho.count("测试集迭代（第 1 轮）") >= 2,
          "相三 复位签名：「测试集迭代（第 1 轮）」出现 %d 次 ≥2（重入清零重计）"
          % ho.count("测试集迭代（第 1 轮）"))
    check(stages.count("implement") >= 1 and rounds >= 7,
          "相三 重入证据：implement 段在桩账本（%d 次）且 arbitrate ≥7 轮（%d）"
          % (stages.count("implement"), rounds))


def main():
    fail = Fail("t260917-09 tests_rounds 连续语义端到端（复位边 + 上限对照）")

    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091709a-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    stage_name = "t26091709a-%d" % os.getpid()
    stage_downed = False
    try:
        stage_mod, stage = require_stage(fail, stage_name, PHASES[0]["tid"])
        for ph in PHASES:
            print("== %s ==" % ph["tid"], flush=True)
            run_phase(py, bench, fail, check, stage, audit_env, tmp, ph)
        audit = read_audit_jsonl(audit_log)
        check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条"
              % len(audit))
        down = stage_down(stage_mod, stage_name)
        stage_downed = True
        resid = (down or {}).get("residue") if isinstance(down, dict) else down
        check(not resid, "拆台零残留（residue=%s）" % (resid,))
    finally:
        if stage_mod is not None and not stage_downed:
            try:
                stage_down(stage_mod, stage_name)
            except Exception:
                pass
        if os.environ.get("T09_KEEP_TMP") == "1":
            print("TMP preserved（T09_KEEP_TMP=1）: %s" % tmp, flush=True)
        else:
            t09.cleanup_tmp(tmp)
    print("SC sc_tests_streak_reset pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
