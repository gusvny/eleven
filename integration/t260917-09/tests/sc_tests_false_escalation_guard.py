#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-09 集成场景：假封防护——抖动/环境红轮不计入 + 不在册保守计轮 + 豁免超限出路（真 docker 台）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
  tests-fault 判决但该轮红属「负载抖动」（红项当轮串行复跑全绿，KI-072 同族：
  并发假红、单跑全绿）或「环境面红」（env_fail>0 且产品红=0 且闸拦=0）时，该轮
  不计入 tests-fault 上限（t260916-21 的「6 闸拦复跑 6/6 全绿」与 t260916-19/-04
  的「余红=环境/供给」两形态的直击面）；红项名不在注册表（基线改名/闸拦面遗留的
  陈旧名）时探针 fail-closed → 保守计轮并点名（封死「死源静默当全绿」复发，
  C1 钉子）；连续豁免撞独立上限时封面出路可执行——authorize 接受本判决有真消费点
  （复位计数+推进验收，t260916-19/-04 的真实出路），不写死路文案（要求④）。

三子用例（顺序执行，各子用例单票单 worker 单舞台，夹具仓带 integration 声明面）：
  抖动子用例（T09_FIXTURE_MODE=JITTER）：夹具案 flaky_sc 首跑造记并红、复跑绿
        （marker 确定性形）→ 首轮 tests-fault 因红项复跑全绿不计入（票面留痕
        「不计入」并点名红项），其后 6 轮红项已绿照计 → 第 8 判决撞上限 blocked
        （计 6>5；若无豁免第 7 判决即封——计数算术强断言）。
  不在册子用例（=GHOST）：恒绿案 + 陈旧红项名 ghost_stale_name（刻意不在注册表）
        → 每轮保守计轮 → 第 7 判决 blocked（计数与旧语义同形=回归稳定面），
        票面点名「不在册」——封死死源静默（新行为钉子，实现前红属预期）。
  环境失败分支（=ENV）：夹具案 env_sc 确定性环境红（not-checked+external）→ 每轮
        豁免不计入 → 第 6 轮连续豁免撞独立上限 blocked（出路文案在）→ 人
        op=authorize 接受本判决 + retry_qc 唤醒 → 复位计数并推进 acceptance
        （授权 uses≥1，handoff 点名接受与豁免面）——授权在该封面是真出路。

与既有资产 intent 分工（防重复声明）：
  · sc_tests_streak_reset（同票）锁「连续语义复位边」（code-fault/rework 重入
    清零 + 上限对照）——本条锁「不计轮豁免面」，不同面不互替；
  · t260912-03 sc_authz_overlimit_accept 锁 cap 面 authorize 通道——本条环境失败分支
    锁**豁免超限面**的 authorize 消费（C2 新消费点），不同面；
  · t260908-01 sc_ki061_* 锁唤醒复活机制本体——本条只消费其守卫。
驱动形态：lib_ki061 台架同形 + 本票自有常量桩（判决恒 tests-fault）；夹具
  迷你执行器=真注册表形状（SCENARIOS 三元组 + /bin/sh -c），verify.yaml 声明
  integration.cmd，机械链走真 verify_lane integ 道（规范行+INTEG_SUMMARY 契约）。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台缺件=环境红
  点名，不写 SKIP）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import json
import os
import sys
import tempfile
import time

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
from lib_ki061 import (LAST_Q, poll, query_snapshot, spawn_worker,  # noqa: E402
                       stage_env, wait_worker_alive)
import lib_t26091709 as t09

PHASES = [
    {"tid": "t26091709d-jitter", "key": "t26091709d", "mode": "JITTER",
     "title": "t260917-09 抖动子用例：红项复跑全绿不计入"},
    {"tid": "t26091709e-ghost", "key": "t26091709e", "mode": "GHOST",
     "title": "t260917-09 不在册子用例：陈旧红项名保守计轮"},
    {"tid": "t26091709f-env", "key": "t26091709f", "mode": "ENV",
     "title": "t260917-09 环境失败分支：豁免不计入与豁免超限出路"},
]
OVER_LIMIT_STAGES = ("arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
AFTER_STAGES = ("acceptance_walkthrough", "merge_check", "merge")
POLL_DRIVE = 240
WHO = "宿主"
REASON = "t260917-09 场景：产品面已收口、余红属环境面（连续豁免超限），接受本判决推进验收"
ACCEPT_MARK = "接受仲裁判决"

STATS = {"ok": 0, "fail": 0}


def check_fn(fail):
    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r
    return check


def authz_items(snap):
    for holder in (snap or {}, (snap or {}).get("meta") or {}):
        items = holder.get("authorizations")
        if isinstance(items, list):
            return items
    return []


def uses_total(snap):
    n = 0
    for it in authz_items(snap):
        if isinstance(it, dict) and isinstance(it.get("uses"), list):
            n += len(it["uses"])
    return n


def retry_events(snap):
    return len([e for e in ((snap or {}).get("timeline") or [])
                if str(e.get("state") or "") == "retry-requested"])


def wait_cap_blocked(py, env, tid, worker, wlog, fail, budget):
    def _probe():
        if worker.poll() is not None:
            return None
        s = query_snapshot(py, env, tid)
        if (s.get("stage") in OVER_LIMIT_STAGES
                and s.get("stage_state") == "blocked" and "超限" in t09.snap_text(s)):
            return s
        return None
    snap = poll(_probe, budget)
    if snap is None:
        wait_worker_alive(fail, worker, wlog)
        s = query_snapshot(py, env, tid)
        fail.bail("未在 %ds 内到达 blocked（stage=%s state=%s；末次 query rc=%s）"
                  % (budget, s.get("stage"), s.get("stage_state"), LAST_Q.get("rc")))
    return snap


def wait_advanced(py, env, tid, worker, wlog, fail, budget, mark):
    def _probe():
        if worker.poll() is not None:
            return None
        s = query_snapshot(py, env, tid)
        st = s.get("stage")
        # merge_check/merge 桩票转 blocked=合法挂起终态（sc_authz 同款宽口径：
        # 等人签字=blocked；验收推进断言只锚 handoff 留痕＋stage 已过仲裁边）
        unblocked = (s.get("stage_state") != "blocked"
                     or st in ("merge_check", "merge"))
        if mark in t09.handoff_text(s) and st in AFTER_STAGES and unblocked:
            return s
        return None
    snap = poll(_probe, budget)
    if snap is None:
        wait_worker_alive(fail, worker, wlog)
        snap = query_snapshot(py, env, tid)
    return snap


def run_phase(py, bench, fail, check, stage, audit_env, tmp, ph):
    tid, key, mode = ph["tid"], ph["key"], ph["mode"]
    # 每相独立桩账本（桩判决序号=账本行数，跨相共享会串相——同 streak_reset 修法）；
    # 恒 tests-fault 用长序列表达（单元素序列第 2 判决即耗尽回落 pass）。
    stub_path, stub_log = t09.write_stub(tmp, key)
    wlog = os.path.join(tmp, "%s-worker.log" % tid)
    repo = t09.make_fixture_repo(tmp, name="repo-%s" % key, with_integration=True)
    reg_dir = bench.write_registry(os.path.join(tmp, "reg-%s" % key), key, repo)
    env = stage_env(stage, reg_dir, audit_env)
    # 260927（KI-142）：本 env 后面还有 gated 写（authorize / retry_qc），且 key 每相不同
    # （PHASES[i].key）——env 级 + 变量值声明调用方身份。
    env["SANDBAR_CALLER_PROJECT"] = key
    env["T09_STUB_LOG"] = stub_log
    env = t09.fixture_mode_env(env, mode)
    env = t09.arb_seq_env(env, ["tests-fault"] * 40)
    worker = spawn_worker(py, tid, env, wlog, stub_path, stub_log,
                          disable_ki061=False, arb_verdict="tests-fault")
    check(worker.poll() is None, "%s worker 已拉起 pid=%s" % (tid, worker.pid))
    rc, out = run_poc_client(py, "ticket-start", {
        "ticket_id": tid, "template_id": "dev-lane", "project": key,
        "title": ph["title"], "write_set": ["docs/"]}, env)
    _ok, _why = accepted(out, tid)              # 260927（KI-142）：受理只认 ok=true
    check(rc == 0 and _ok, "%s ticket-start 受理（%s）" % (tid, _why))
    try:
        if mode == "JITTER":
            return phase_jitter(py, env, tid, worker, wlog, stub_log, fail, check)
        if mode == "GHOST":
            return phase_ghost(py, env, tid, worker, wlog, stub_log, fail, check)
        return phase_env(py, env, tid, worker, wlog, stub_log, fail, check)
    finally:
        t09.kill_tree(worker)


def phase_jitter(py, env, tid, worker, wlog, stub_log, fail, check):
    """首轮红项复跑全绿不计入；其后绿照计 → 第 8 判决封（计数算术强断言）。"""
    snap = wait_cap_blocked(py, env, tid, worker, wlog, fail, POLL_DRIVE)
    rounds = t09.arb_rounds(stub_log)
    txt = t09.snap_text(snap)
    print("  %s blocked: stage=%s arb_rounds=%d" % (tid, snap.get("stage"), rounds),
          flush=True)
    check(snap.get("stage_state") == "blocked",
          "抖动子用例 最终仍撞上限（豁免不拆上限；state=%s）" % snap.get("stage_state"))
    check(rounds == 8,
          "抖动子用例 计数算术：首轮豁免不计入 → 第 8 判决（计 6>5）才封，实际 arb=%d"
          "（旧口径无豁免第 7 判决即封）" % rounds)
    check("不计入" in txt,
          "抖动子用例 票面留痕「不计入」（豁免轮可观测）")
    check("flaky_sc" in txt,
          "抖动子用例 留痕点名红项 flaky_sc（复跑全绿证据随留痕）")


def phase_ghost(py, env, tid, worker, wlog, stub_log, fail, check):
    """陈旧红项名不在册 → 探针 fail-closed → 保守计轮点名（死源静默的钉子）。"""
    snap = wait_cap_blocked(py, env, tid, worker, wlog, fail, POLL_DRIVE)
    rounds = t09.arb_rounds(stub_log)
    txt = t09.snap_text(snap)
    print("  %s blocked: stage=%s arb_rounds=%d" % (tid, snap.get("stage"), rounds),
          flush=True)
    check(snap.get("stage_state") == "blocked",
          "不在册子用例 保守计轮照常撞上限（state=%s）" % snap.get("stage_state"))
    check(rounds == 7,
          "不在册子用例 计数算术：不在册=保守计轮（无豁免）→ 第 7 判决封，实际 arb=%d"
          % rounds)
    check("不在册" in txt,
          "不在册子用例 票面点名「不在册」（fail-closed 可见，绝不静默当全绿）")
    check("ghost_stale_name" in txt,
          "不在册子用例 点名陈旧红项名 ghost_stale_name")


def cli_authorize(py, env, tid):
    return run_poc_client(py, "ticket", {
        "op": "authorize", "ticket_id": tid,
        "input": {"who": WHO, "kind": "arbitration_verdict", "scope": [tid],
                  "reason": REASON, "expires": int(time.time()) + 3600}}, env)


def phase_env(py, env, tid, worker, wlog, stub_log, fail, check):
    """环境红轮豁免 → 连续豁免撞独立上限 → authorize 接受=真出路（C2 消费点）。"""
    snap = wait_cap_blocked(py, env, tid, worker, wlog, fail, POLL_DRIVE)
    rounds = t09.arb_rounds(stub_log)
    txt = t09.snap_text(snap)
    print("  %s blocked: stage=%s arb_rounds=%d" % (tid, snap.get("stage"), rounds),
          flush=True)
    check(rounds == 6,
          "环境失败分支 连续豁免算术：5 轮豁免后第 6 轮撞豁免上限，实际 arb=%d"
          "（旧口径无豁免第 7 判决封）" % rounds)
    check("超限" in txt and "authorize" in txt and "rework" in txt,
          "环境失败分支 豁免超限封面出路文案在（authorize/rework）")
    base_retry = retry_events(snap)
    rc, out = cli_authorize(py, env, tid)
    doc = parse_out_json(out)
    check(rc == 0 and doc.get("ok") is True,
          "环境失败分支 op=authorize 送达（rc=%s ok=%s out尾=%s）"
          % (rc, doc.get("ok"), (out or "")[-140:]))
    got = poll(lambda: (lambda s: s if any(
        str(it.get("kind") or "") == "arbitration_verdict"
        for it in authz_items(s)) else None)(
        query_snapshot(py, env, tid)), 120)
    if got is None:
        wait_worker_alive(fail, worker, wlog)
        fail.bail("环境失败分支 生效授权未入 meta（authorizations=%d）"
                  % len(authz_items(query_snapshot(py, env, tid))))
    rc2, out2 = run_poc_client(py, "ticket", {
        "op": "retry_qc", "ticket_id": tid, "who": WHO}, env)
    check(rc2 == 0, "环境失败分支 retry_qc 唤醒（rc=%s out尾=%s）" % (rc2, (out2 or "")[-120:]))
    adv = wait_advanced(py, env, tid, worker, wlog, fail, 240, ACCEPT_MARK)
    ho = t09.handoff_text(adv)
    print("  %s 唤醒后: stage=%s state=%s uses=%d"
          % (tid, adv.get("stage"), adv.get("stage_state"), uses_total(adv)),
          flush=True)
    check(adv.get("stage") in AFTER_STAGES
          and (adv.get("stage_state") != "blocked"
               or adv.get("stage") in ("merge_check", "merge")),
          "环境失败分支 豁免封面 authorize 接受 → 复位并推进 acceptance（stage=%s "
          "state=%s；授权在该封面必须是真出路；merge 段 blocked=等签字合法终态）"
          % (adv.get("stage"), adv.get("stage_state")))
    check(ACCEPT_MARK in ho and "豁免" in ho,
          "环境失败分支 handoff 点名接受判决与豁免面（留痕可读）")
    check("tests-fault" in ho, "环境失败分支 handoff 带判决三态 verdict=tests-fault")
    check(uses_total(adv) >= 1,
          "环境失败分支 该授权 uses ≥1（消费留痕=%d）" % uses_total(adv))


def main():
    fail = Fail("t260917-09 假封防护（抖动/环境红不计入 + 不在册保守计轮 + 豁免出路）")

    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091709d-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    stage_name = "t26091709d-%d" % os.getpid()
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
    print("SC sc_tests_false_escalation_guard pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
