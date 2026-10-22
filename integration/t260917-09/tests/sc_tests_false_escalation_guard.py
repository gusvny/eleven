#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-09 集成场景：假封防护——环境红具名不重跑 + 不在册/抖动保守计轮（真 docker 台）。

## 语义变更声明（B2，宿主 260929 令，「集成门判据收口」）

出处：宿主 260929 直修令（原话口径）「门只对本票新增产品红 + 未挂账产品红判红；环境红
具名记录、不拦、不重跑；任何红都不许被静默」。理由（本场景旧期望被推翻的直接原因）：
B1 落地前环境红只有计数没有名单，引擎只能靠**计数差**猜环境面（`env_fail>0 且 failed==0
且闸拦 0`），混合轮（真实形状：11 败 + 11 环境红）识别不出 → 保守计轮 → 每轮烧 ~30 分钟
整轮套件、5–6 轮后「假封」转人工。B1 把环境红**具名**（闸回执 `env_red`，判据面=
`not-checked × external` 的权威判决），B2 起引擎按具名通道分区：环境红**具名**轮
⇒ 不重跑、直接进验收（本场景环境失败分支的新期望）；**只有本票新增产品红**才计轮/重跑
（本场景新增的守护面，见下「新守护面」）。旧期望「环境红→豁免不计入→第 6 轮撞豁免上限
blocked→人 authorize」随语义收口作废（豁免上限机制本体仍在，兜底其余形态：抖动/未具名/
在册已知红）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
  · **新守护面（B2）**：环境红**具名**⇒ 不重跑、直接进验收（票面逐条点名红名）；
    环境红**不构成 tests-fault 的迭代理由**（红项具名 + 无本票新增产品红时判 pass）；
  · 抖动红（红项当轮串行复跑全绿，KI-072 同族）⇒ 不计入上限（旧语义保留，回滚稳定面）；
  · 红项名不在注册表（基线改名/闸拦面遗留的陈旧名）⇒ 探针 fail-closed ⇒ **计轮**并点名
    （「只有新增产品红才计轮」的直击面：死源静默当全绿的钉子，C1）；
  · 环境红**未具名**（老回执形态）⇒ 退回旧保守口径（此形态在真闸下已不可达——B1 起
    not-checked×external 一律具名；该半边归 L1
    `server/engine/tests/test_260929_integ_gate_settlement.py::test_case4_*`，本场景不假造）。

三子用例（顺序执行，各子用例单票单 worker 单舞台，夹具仓带 integration 声明面）：
  抖动子用例（T09_FIXTURE_MODE=JITTER）：夹具案 flaky_sc 首跑造记并红、复跑绿
        （marker 确定性形）→ 首轮 tests-fault 因红项复跑全绿不计入（票面留痕
        「不计入」并点名红项），其后 6 轮红项已绿照计 → 第 8 判决撞上限 blocked
        （计 6>5；若无豁免第 7 判决即封——计数算术强断言，旧语义逐字保留）。
  不在册子用例（=GHOST）：恒绿案 + 陈旧红项名 ghost_stale_name（刻意不在注册表）
        → 每轮保守计轮 → 第 7 判决 blocked（B2 新守护面的另一半：**新增产品红照计轮**），
        票面点名「不在册」——封死死源静默。
  环境失败分支（=ENV，**B2 重写**）：夹具案 env_sc 确定性环境红（not-checked+external
        ⇒ 闸回执 env_red 具名）→ 第 1 判决即**不重跑整轮**、直接进验收（arb 判决恒
        tests-fault 也只烧 1 轮：不重跑＝不复发）→ handoff 点名具名环境红；**不再**撞
        豁免上限 blocked、**不再**消费 authorize（旧期望语义已被 B2 收口）。

与既有资产 intent 分工（防重复声明）：
  · sc_tests_streak_reset（同票）锁「连续语义复位边」（code-fault/rework 重入
    清零 + 上限对照）——本条锁「不计轮豁免面」，不同面不互替；
  · t260912-03 sc_authz_overlimit_accept 锁 cap 面 authorize 通道——本条环境失败分支
    锁**豁免超限面**的 authorize 消费（C2 新消费点），不同面；
  · t260908-01 sc_ki061_* 锁唤醒复活机制本体——本条只消费其守卫。
驱动形态：lib_ki061 台架同形 + 本票自有常量桩（判决恒 tests-fault）；夹具
  迷你执行器=真注册表形状（SCENARIOS 三元组 + /bin/sh -c），verify.yaml 声明
  integration.cmd，机械链走真 verify_lane integ 道（规范行+INTEG_SUMMARY 契约）。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（进程台缺供=环境红点名，不写
  SKIP）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

Bench migration (host order 261022): the three phases share ONE
integration/process_bench.py Temporal dev server instead of a leased docker stage -
a plain process on a kernel-picked free port with a private SQLite file, up in
~0.2 s, reaped by process group. SANDBAR_TARGET_HOST/SANDBAR_NAMESPACE point at that
endpoint and every other env key the case sets is unchanged; the per-phase ticket
id, registry, stub ledger and worker are untouched, so the phases stay isolated.
Preconditions are probed FIRST per phase (endpoint answers a real gRPC round trip,
worker alive, the ticket read face answers): a missing precondition is a NAMED red
in seconds. The drive ceilings are graded (CAP_S / ADVANCE_S) and an expired
ceiling names the state, the seconds and the last snapshot. Teardown judges the
residue from outside (port refuses, no pid, empty group, temp dir reclaimed).
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
                      require_bench, run_poc_client)
import lib_bench_stage as bench_stage                                # noqa: E402
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

#: Drive ceilings in SECONDS, graded by the measured normal path on the process
#: bench (host order 261022). The old 240 s figure was the docker stage's floor,
#: not the work: one phase is now a few tens of seconds. An expired ceiling names
#: the state it waited for and appends the last snapshot.
CAP_S = 120        # the cap-blocked terminal (8 arb rounds, each with its suite)
ADVANCE_S = 120    # the env-red re-route reaching the post-arbitration stage
WHO = "宿主"
REASON = "t260917-09 场景：产品面已收口、余红属环境面（连续豁免超限），接受本判决推进验收"
ACCEPT_MARK = "接受仲裁判决"       # 旧语义（超限封面 authorize 接受）留痕锚：本场景不再断言
REROUTE_MARK = "环境面/已知红面，不重跑"   # B2（260929）新归宿留痕锚（环境红具名轮直进验收）

STATS = {"ok": 0, "fail": 0}


def snapshot_text(snap, limit=600):
    """The last snapshot as one compact line (expiry evidence, host order 261022)."""
    try:
        text = json.dumps(snap or {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(snap)
    return text if len(text) <= limit else text[:limit] + "…"


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
    """Wait for the cap-blocked terminal; a CONTRADICTORY block is a red AT ONCE.

    Fail fast, then wait (host order 261022): a ticket already blocked with a
    different receipt cannot become the expected terminal without a wake signal,
    so spending the ceiling on it only hides the finding. The assertion is
    unchanged (still a red) and names the receipt it did see. A blocked reading
    is confirmed by a second probe half a second later, so a momentary blocked
    face in a fork is not read as terminal."""
    t0 = time.time()
    deadline = t0 + budget
    while time.time() < deadline:
        if worker.poll() is not None:
            break
        s = query_snapshot(py, env, tid)
        hits = (s.get("stage") in OVER_LIMIT_STAGES
                and s.get("stage_state") == "blocked"
                and "exceed the cap" in t09.snap_text(s))
        if hits:
            return s
        if s.get("stage_state") == "blocked":
            time.sleep(0.5)
            again = query_snapshot(py, env, tid)
            if again.get("stage_state") == "blocked":
                fail.bail(
                    "did not reach the cap-blocked terminal (stage in %s, receipt "
                    "carrying 'exceed the cap') - the ticket is BLOCKED after "
                    "%.1fs with a different receipt: %r (stage=%s; a wake signal "
                    "would be needed to move it, so the ceiling is not waited out)"
                    " - last snapshot: %s"
                    % ("/".join(OVER_LIMIT_STAGES), time.time() - t0,
                       str(again.get("blocked_reason") or "")[:300],
                       again.get("stage"), snapshot_text(again)))
            continue
        time.sleep(1.0)
    wait_worker_alive(fail, worker, wlog)
    s = query_snapshot(py, env, tid)
    fail.bail("did not reach the cap-blocked terminal (stage in %s, "
              "stage_state=blocked, receipt carrying 'exceed the cap') in %ds "
              "- last snapshot: %s (last query rc=%s)"
              % ("/".join(OVER_LIMIT_STAGES), budget, snapshot_text(s),
                 LAST_Q.get("rc")))


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
        # Fail fast, then wait (host order 261022): a ticket parked BLOCKED outside
        # the legal merge stages cannot reach the advance terminal without a wake
        # signal, so the red lands now, naming the receipt it actually saw.
        if (snap.get("stage_state") == "blocked"
                and snap.get("stage") not in ("merge_check", "merge")):
            fail.bail("did not reach the post-arbitration stage (stage in %s "
                      "carrying the handoff mark %r) - the ticket is BLOCKED with "
                      "a different receipt: %r (stage=%s) - last snapshot: %s"
                      % ("/".join(AFTER_STAGES), mark,
                         str(snap.get("blocked_reason") or "")[:300],
                         snap.get("stage"), snapshot_text(snap)))
        fail.bail("did not reach the post-arbitration stage (stage in %s carrying "
                  "the handoff mark %r, not blocked unless merge_check/merge) in "
                  "%ds - last snapshot: %s (last query rc=%s)"
                  % ("/".join(AFTER_STAGES), mark, budget, snapshot_text(snap),
                     LAST_Q.get("rc")))
    return snap


def run_phase(py, bench, fail, check, pstage, audit_env, tmp, ph):
    tid, key, mode = ph["tid"], ph["key"], ph["mode"]
    # 每相独立桩账本（桩判决序号=账本行数，跨相共享会串相——同 streak_reset 修法）；
    # 恒 tests-fault 用长序列表达（单元素序列第 2 判决即耗尽回落 pass）。
    stub_path, stub_log = t09.write_stub(tmp, key)
    wlog = os.path.join(tmp, "%s-worker.log" % tid)
    repo = t09.make_fixture_repo(tmp, name="repo-%s" % key, with_integration=True)
    reg_dir = bench.write_registry(os.path.join(tmp, "reg-%s" % key), key, repo)
    env = stage_env(pstage.state(), reg_dir, audit_env)
    # 260927（KI-142）：本 env 后面还有 gated 写（authorize / retry_qc），且 key 每相不同
    # （PHASES[i].key）——env 级 + 变量值声明调用方身份。
    env["SANDBAR_CALLER_PROJECT"] = key
    env["T09_STUB_LOG"] = stub_log
    env = t09.fixture_mode_env(env, mode)
    # 判决序列（每相独立账本，桩按调用序取）：**ENV 相用 ["tests-fault","pass"]**——
    # B2 后第一判决即「环境面/已知红面，不重跑」进验收，若该轮走查（平行边）也回了
    # failed，引擎会作废走查、回路收敛后**重走查**（此时不需要第二个 tests-fault 判决，
    # 恒 tests-fault 会把票拖进「重判→再作废」的活动循环）；其余两相仍用长序列
    # （它们的终态就是撞上限 blocked，第 8/第 7 判决落 blocked，序列长度不受影响）。
    env = t09.arb_seq_env(env, ["tests-fault", "pass"] if mode == "ENV"
                           else ["tests-fault"] * 40)
    worker = spawn_worker(py, tid, env, wlog, stub_path, stub_log,
                          disable_ki061=False, arb_verdict="tests-fault")
    check(worker.poll() is None, "%s worker 已拉起 pid=%s" % (tid, worker.pid))
    rc, out = run_poc_client(py, "ticket-start", {
        "ticket_id": tid, "template_id": "dev-lane", "project": key,
        "title": ph["title"], "write_set": ["docs/"]}, env)
    _ok, _why = accepted(out, tid)              # 260927（KI-142）：受理只认 ok=true
    check(rc == 0 and _ok, "%s ticket-start 受理（%s）" % (tid, _why))
    # Fail fast (host order 261022): the preconditions in seconds, before any
    # ceiling is spent waiting for the state under test.
    bench_stage.preflight(fail, pstage, worker=worker, wlog=wlog,
                          probe=lambda: query_snapshot(py, env, tid),
                          what="the cap-blocked / advance terminal")
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
    snap = wait_cap_blocked(py, env, tid, worker, wlog, fail, CAP_S)
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
    """陈旧红项名不在册 → 探针 fail-closed → 留痕点名（死源静默的钉子）。

    B2 视角：本相是「**环境红具名轮不重跑**」之外的对照面——红面照旧收敛到上限封面
    （上限与转人工触发**不因 B2 而拆除**）。本夹具轮的闸拦为空，故归宿是**已知红豁免
    车道**（260923 语义：blockers 空=零新增红，不计轮）而非保守计轮；探针与留痕同面
    是这一相真正的守护面（见本函数末两条断言）。"""
    snap = wait_cap_blocked(py, env, tid, worker, wlog, fail, CAP_S)
    rounds = t09.arb_rounds(stub_log)
    txt = t09.snap_text(snap)
    print("  %s blocked: stage=%s arb_rounds=%d" % (tid, snap.get("stage"), rounds),
          flush=True)
    check(snap.get("stage_state") == "blocked",
          "不在册子用例 保守计轮照常撞上限（state=%s）" % snap.get("stage_state"))
    check(rounds == 6,
          "不在册子用例 计数算术：闸拦为空 ⇒ 已知红豁免车道（不计轮）→ 第 6 判决撞"
          "**豁免上限**封（上限本体不拆），实际 arb=%d" % rounds)
    # 静默守卫（本相的真语义面，B2 前后一致）：本轮走**已知红豁免车道**（闸拦为空 ⇒
    # 零新增红，260923 口径），故不发抖动探针（探针只服务「红项名单非空且不在已知红
    # 车道」的轮）——真正要守的是**留痕同面**：豁免结论（「不计入」）、「不在册」结论
    # 与陈旧红项名三者都必须可读，死源绝不静默当全绿。
    check("不计入" in txt and "outside the known-red roster" in txt and "ghost_stale_name" in txt,
          "不在册子用例 豁免轮留痕同面（不计入 + 不在册 + 红项名，死源不静默）")
    check("outside the known-red roster" in txt,
          "不在册子用例 票面点名「不在册」（fail-closed 可见，绝不静默当全绿）；本夹具轮"
          "闸拦为空 ⇒ 红面走已知红豁免车道（不计轮），上限照旧兜底——留痕不因外置道而减")
    check("ghost_stale_name" in txt,
          "不在册子用例 点名陈旧红项名 ghost_stale_name")


def cli_authorize(py, env, tid):
    return run_poc_client(py, "ticket", {
        "op": "authorize", "ticket_id": tid,
        "input": {"who": WHO, "kind": "arbitration_verdict", "scope": [tid],
                  "reason": REASON, "expires": int(time.time()) + 3600}}, env)


def phase_env(py, env, tid, worker, wlog, stub_log, fail, check):
    """B2（260929）新期望：环境红**具名** ⇒ 不重跑整轮、直接进验收；不撞豁免上限、
    不消费 authorize。守护面=「只有本票新增产品红才计轮/重跑」。"""
    # 等推进（不设「等 blocked」预算——新语义下本子用例**不该**走到超限封面）
    adv = wait_advanced(py, env, tid, worker, wlog, fail, ADVANCE_S, REROUTE_MARK)
    rounds = t09.arb_rounds(stub_log)
    ho = t09.handoff_text(adv)
    print("  %s 推进后: stage=%s state=%s arb_rounds=%d"
          % (tid, adv.get("stage"), adv.get("stage_state"), rounds), flush=True)
    check(rounds == 1,
          "环境失败分支 具名环境红**不重跑整轮**：arb 判决只烧 1 轮（实际 arb=%d；"
          "旧语义此处恒 6 轮＝每轮重跑整趟套件后撞豁免上限）" % rounds)
    check(adv.get("stage") in AFTER_STAGES
          and (adv.get("stage_state") != "blocked"
               or adv.get("stage") in ("merge_check", "merge")),
          "环境失败分支 具名环境红 → 直接进验收（stage=%s state=%s；merge 段 blocked="
          "等签字合法终态，不是超限封）" % (adv.get("stage"), adv.get("stage_state")))
    check("环境面/已知红面，不重跑" in ho,
          "环境失败分支 handoff 点名环境面归宿（「不重跑」留痕可读）")
    check("环境红（不拦·具名）" in ho and "env_sc" in ho,
          "环境失败分支 handoff 逐条点名具名环境红（不拦但不许静默）")
    check("tests-fault" in ho, "环境失败分支 handoff 带判决三态 verdict=tests-fault")
    check(uses_total(adv) == 0,
          "环境失败分支 不再消费 authorize 授权（uses=%d；旧语义的封面已随 B2 收口）"
          % uses_total(adv))
    # 超限封面的判据只落在**交接留痕**上（ticket 快照文本含 arbitrate 提示词原文，
    # 那里本来就有「烧轮次到超限转人工」的措辞——用 snap_text 全文包含「超限」判会
    # 误报，报错精确纪律）。两条上限文案的**逐字前缀**才是超限封据面。
    ho_sum = " ".join(str(h.get("summary") or "") for h in (adv.get("handoffs") or [])
                      if isinstance(h, dict))
    check("consecutive-exemption over cap" not in ho_sum and "exceed the cap" not in ho_sum,
          "环境失败分支 不再撞豁免超限封面（交接留痕无上限文案；summary 面=%r）"
          % ho_sum[-160:])


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
    pstage = None
    try:
        # Host order 261022: one plain-process Temporal server shared by the three
        # phases instead of a leased docker stage (~0.2 s up, not minutes).
        pstage = bench_stage.up(fail, facts=print)
        for ph in PHASES:
            print("== %s ==" % ph["tid"], flush=True)
            run_phase(py, bench, fail, check, pstage, audit_env, tmp, ph)
        audit = read_audit_jsonl(audit_log)
        check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条"
              % len(audit))
        # Residue, judged from the outside: the port refuses, no pid survives,
        # the process group is empty, the private temp dir is reclaimed.
        bench_stage.down(pstage, fail, tag="t260917-09 bench")
        pstage = None
    finally:
        if pstage is not None:
            # Best effort on every failing path (process_bench's atexit backstop
            # would otherwise only reap at interpreter exit).
            try:
                pstage.down()
            except Exception:                                       # noqa: BLE001
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
