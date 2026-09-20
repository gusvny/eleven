#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-03 集成场景：仲裁上限的人授权「接受判决」（超限不阻断推进，真 docker 台）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
  仲裁连续判 tests-fault 撞上限（MAX_TESTS_FAULT_ROUNDS=5，第 6 轮）→ 票 blocked
  （**无授权时逐字节维持现状**＝零回归）；此时人经真 CLI 正规入口
  （client.py op=authorize → Signature.authorize → sign 信号面）投一张
  kind=arbitration_verdict、scope=[本票票号]、**未过期**的「接受本判决」授权 →
  retry_qc 唤醒后**不阻断**：票推进到 acceptance_walkthrough，判决原文（引擎 blocked
  文案「测试集迭代 N 轮超限（上限 5），转人工判读」）与授权人一并进 handoff 历史，
  且该授权条目 uses 记一条消费留痕。
  过期授权＝照旧 blocked（负锁，防恒真）；授权由 workflow intake 校验，
  死授权落 snapshot 的 refused（不进 meta、不进事件历史）。

与既有资产 intent 分工（防重复声明，不互替）：
  · t260908-01 sc_ki061_overlimit_wake_revive 两条锁「超限 blocked 的复活与重放兼容」
    （KI-061 唤醒复位：相一 memoized 复刻、相二 arbitrate 真 respawn；判决改判走
    host_ruling）；**本条锁的是人授权这条新通道**：接受判决 → 超限不阻断推进，外加
    无授权/过期授权负锁。共用 lib_ki061 台架，断言面与 intent 不同。
  · sc_authz_protected_path（同票）锁受保护路径面的授权通道，与本条同票不同面；
  · developer L1/L2（纯函数矩阵、载荷归一、handler 卫兵）在单测层——本条锁真
    docker 台 + 真 worker + 真 workflow 历史下的用户旅程三态。

驱动形态（为什么不用 lib_ki061.drive_to_overlimit_blocked）：那支 helper 的 worker 带
  SANDBAR_TEST_DISABLE_KI061=1（模拟修复前 worker：唤醒吃 memoized 仲裁结论、立即再
  blocked、arbitrate 零 respawn）——授权是在唤醒后新一轮 route 判定点被消费的，需要
  修复后的唤醒复位把 arbitrate 真重跑起来，故本场景自建同形驱动步骤：
  spawn_worker(disable_ki061=False, arb_verdict="tests-fault") + ticket-start +
  poll 到超限 blocked。

三条子用例（顺序执行，单票单 worker 单舞台）：
  相一（B① 无授权负锁）：tests-fault 桩 6 轮超限 → stage_state=="blocked" 且回执含
        「超限」，meta['authorizations'] 不存在或为空；
  相二（B③ 过期授权负锁）：CLI 投 expires=当前时间-10 的授权 → workflow 拒收
        （snapshot.refused 含「已过期」，meta 无该条目，uses 全零）→ retry_qc 唤醒
        真被消费并重跑仲裁后**仍 blocked**（未被放行）；
  相三（B② 授权放行）：CLI 投 expires=当前时间+3600 的授权 → meta['authorizations']
        落条目（who/scope/reason/issued/expires）→ retry_qc 唤醒 → 离开超限 blocked
        （推进到 acceptance_walkthrough 或更后）→ handoff 含「经人授权接受判决」＋
        判决原文关键词「测试集迭代」＋授权人「宿主」；该授权 uses ≥ 1。
  后续段（merge_check/merge）在 fixture 桩票里转 blocked 属预期，不判。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260912-03/tests/sc_authz_overlimit_accept.py
台架：纯本地 tmp fixture 主仓 + 真 docker 舞台（temporal-only，
test-temporal:cli-1.8.3）＋ 工单专属 worker；零生产面接触（7233/8233/3099 由审计
钩子账本与拆台 residue 双面兜底）。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台缺件=环境红点名）。
"""
import json
import os
import shutil
import signal
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (os.path.join(REPO, "integration"),
           os.path.join(REPO, "integration", "t260904-02"),
           os.path.join(REPO, "integration", "t260908-01")):
    sys.path.insert(0, _p)

from lib_gate import (Fail, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_ki061 import (ARB_STUB, LAST_Q, arb_gens, make_fixture_repo, poll,  # noqa: E402
                       query_snapshot, read_stub_log, send_signal, spawn_worker,
                       stage_env, wait_worker_alive)

TID = "t26091203b-authz-ol"
PROJ_KEY = "t26091203b"
WHO = "宿主"
REASON = "t260912-03 场景：已逐条复现并裁定接受本轮仲裁判决（测试集迭代超限），准予推进验收走查"
HANDOFF_MARK = "经人授权接受判决"
# 超限 blocked 可能挂在三条边之一（分叉期 snapshot 的 stage 字段会借位成单边名——
# lib_ki061 头注同源教训）：宽松判据集合防假红；负锁一律锚 stage_state=="blocked"，
# **不得**只锚 stage 名。
OVER_LIMIT_STAGES = ("arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
# 授权放行后允许出现的舞台（= acceptance_walkthrough 及更后）；不锚「state != blocked」
# 单条——fixture 桩票在 merge_check 段 blocked 是合法终态。
AFTER_AUTHZ_STAGES = ("acceptance_walkthrough", "merge_check", "merge")

STATS = {"ok": 0, "fail": 0}


def snap_text(snap):
    return json.dumps(snap or {}, ensure_ascii=False)


def authz_items(snap):
    """授权条目可读面（meta['authorizations']；顶层亦容，防落点演进假红）。"""
    for holder in (snap or {}, (snap or {}).get("meta") or {}):
        items = holder.get("authorizations")
        if isinstance(items, list):
            return items
    return []


def arbitration_authz(snap):
    """本票的 arbitration_verdict 条目（kind + scope=本票票号）。"""
    out = []
    for it in authz_items(snap):
        if not isinstance(it, dict) or str(it.get("kind") or "") != "arbitration_verdict":
            continue
        if TID in [str(x) for x in (it.get("scope") or [])]:
            out.append(it)
    return out


def uses_total(snap):
    n = 0
    for it in authz_items(snap):
        if isinstance(it, dict) and isinstance(it.get("uses"), list):
            n += len(it["uses"])
    return n


def retry_events(snap):
    return len([e for e in ((snap or {}).get("timeline") or [])
                if str(e.get("state") or "") == "retry-requested"])


def handoff_text(snap):
    return json.dumps((snap or {}).get("handoffs") or [], ensure_ascii=False)


def refused_text(snap):
    return json.dumps((snap or {}).get("refused") or [], ensure_ascii=False)


def cli_authorize(py, env, expires):
    """人授权唯一入口的真 CLI 通道：client.py op=authorize（= server/tools/ticket.py
    op=authorize 的同一载荷面）→ Signature(authorize=HumanAuthorization) → sign 信号。
    返回 (rc, out)；成功判据由调用方取结构化回执 ok:true（client.py 所有路径 rc=0，
    rc 不足以判成功）。"""
    return run_poc_client(py, "ticket", {
        "op": "authorize", "ticket_id": TID,
        "input": {"who": WHO, "kind": "arbitration_verdict", "scope": [TID],
                  "reason": REASON, "expires": int(expires)}}, env)


def drive_to_overlimit(py, fail, check, tmp, stage, audit_env):
    """自建同形驱动（lib_ki061.drive_to_overlimit_blocked 的修复启用版，见文件头注）：
    tests-fault 桩 + 修复后 worker → 6 轮超限 blocked。返回 (worker, env, stub_log, wlog)。"""
    stub_path = os.path.join(tmp, "ki061_stub.py")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(ARB_STUB)
    stub_log = os.path.join(tmp, "stub.jsonl")
    wlog = os.path.join(tmp, "worker.log")
    env = stage_env(stage, os.environ["_KI061_REG_DIR"], audit_env)
    worker = spawn_worker(py, TID, env, wlog, stub_path, stub_log,
                          disable_ki061=False, arb_verdict="tests-fault")
    check(worker.poll() is None, "worker（KI-061 修复启用，非 DISABLE=1）已拉起 pid=%s"
          % worker.pid)
    rc, out = run_poc_client(py, "ticket-start", {
        "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
        "title": "t260912-03 仲裁上限人授权接受判决", "write_set": ["docs/"]}, env)
    check(rc == 0 and TID in out,
          "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))
    return worker, env, stub_log, wlog


def wait_overlimit_blocked(py, env, worker, wlog, fail, poll_s=600):
    """poll 到仲裁超限 blocked（宽松 stage 判据 + 回执含「超限」）。"""
    def _blocked():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)  # bail：worker 提前退出即时点名
        s = query_snapshot(py, env, TID)
        if (s.get("stage") in OVER_LIMIT_STAGES and s.get("stage_state") == "blocked"
                and "超限" in snap_text(s)):
            return s
        return None
    snap = poll(_blocked, poll_s)
    if snap is None:
        wait_worker_alive(fail, worker, wlog)
        s = query_snapshot(py, env, TID)
        fail.bail("未在 %ds 内到达仲裁超限 blocked（现 stage=%s state=%s；末次 query "
                  "rc=%s out=%s）" % (poll_s, s.get("stage"), s.get("stage_state"),
                                      LAST_Q.get("rc"), (LAST_Q.get("out") or "")[:200]))
    return snap


def send_retry_and_wait(py, env, stage, fail, base_retry, check, who=WHO, poll_s=120):
    """发 retry_qc 并等 workflow 真消费（timeline 新增 retry-requested）。"""
    rc, out = send_signal(py, stage, TID, "retry_qc", who)
    check(rc == 0, "retry_qc 发信（rc=%s）" % rc)
    got = poll(lambda: (lambda s: s if retry_events(s) > base_retry else None)(
        query_snapshot(py, env, TID)), poll_s)
    if got is None:
        fail.bail("retry_qc 未被消费（%ds 内 timeline 未见新增 retry-requested；末次 "
                  "query rc=%s out=%s）" % (poll_s, LAST_Q.get("rc"),
                                           (LAST_Q.get("out") or "")[:200]))
    return got


def kill_worker_tree(worker):
    """worker 全终态回收：进程组 SIGKILL + 有界 wait（spawn_worker 用
    start_new_session=True，pgid==pid，故 killpg 收掉整棵 worker 树；只碰本场景
    自己 spawn 的组，绝不按名字/端口扫杀别的进程）。

    只在 worker 仍活着时用 killpg：leader 已回收后 pid/pgid 可能被系统复用，
    此时再 killpg 有误伤无关进程组的风险；worker 已退出＝其树已自然收敛
    （activity 子进程由引擎以 start_new_session 自成会话，不在本组）。"""
    if worker is None or worker.poll() is not None:
        return
    try:
        os.killpg(worker.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        worker.wait(timeout=10)
    except Exception:  # noqa: BLE001 —— 兜底再 kill 一次，绝不干等
        try:
            worker.kill()
        except Exception:  # noqa: BLE001
            pass


def cleanup_tmp(tmp):
    """临时目录回收：有界重试（子进程尾部写入/内核回收存在秒级窗口）；仍失败=可见
    点名（不静默吞残留），但不把平台层噪声判成产品红（产品红的判据是断言面）。"""
    last = ""
    for _ in range(5):
        try:
            shutil.rmtree(tmp)
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(1)
    print("  · 警告：tmp 未能回收（%s）：%s" % (last, tmp), flush=True)
    return False


def main():
    fail = Fail("t260912-03 仲裁上限人授权（超限 blocked → 授权接受判决 → 推进）")

    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091203b-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    stage_name = "%s-%d" % (PROJ_KEY, os.getpid())
    worker = None
    stage_downed = False
    try:
        stage_mod, stage = require_stage(fail, stage_name, TID)
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        os.environ["_KI061_REG_DIR"] = reg_dir
        worker, env, stub_log, wlog = drive_to_overlimit(py, fail, check, tmp, stage,
                                                        audit_env)

        # ---------------- 相一（B①）：无授权负锁 ----------------
        snap = wait_overlimit_blocked(py, env, worker, wlog, fail)
        rounds1 = len(arb_gens(read_stub_log(stub_log)))
        print("  相一 证据：stage=%s state=%s arb_rounds=%d authorizations=%d uses=%d"
              % (snap.get("stage"), snap.get("stage_state"), rounds1,
                 len(authz_items(snap)), uses_total(snap)), flush=True)
        check(snap.get("stage_state") == "blocked" and "超限" in snap_text(snap)
              and snap.get("stage") in OVER_LIMIT_STAGES,
              "B① 无授权 tests-fault 超限 → 仍 blocked（stage=%s state=%s；含「超限」）"
              % (snap.get("stage"), snap.get("stage_state")))
        # t260917-09 扩展（出路文案，同帧零成本）：超限封面必须给可执行出路，
        # 不许只写「转人工判读」（t260917-09 要求④；blocked 前缀逐字兼容由引擎
        # 单测钉，此处锚用户可读关键词）。实现落地前红属预期（TDD 信号）。
        check("authorize" in snap_text(snap) and "rework" in snap_text(snap),
              "B①+t260917-09 超限回执含出路关键词 authorize/rework（出路文案）")
        check(rounds1 >= 6, "B① arb 桩已驱动到超限（arbitrate 账本 %d 轮 ≥ 6）" % rounds1)
        check(not authz_items(snap),
              "B① 无授权：meta['authorizations'] 不存在或为空（%d 条）"
              % len(authz_items(snap)))

        # ---------------- 相二（B③）：过期授权负锁 ----------------
        exp_past = int(time.time()) - 10
        rc, out = cli_authorize(py, env, exp_past)
        doc = parse_out_json(out)
        check(rc == 0 and doc.get("ok") is True,
              "B③ CLI op=authorize（过期授权）送达（rc=%s ok=%s out尾=%s）"
              % (rc, doc.get("ok"), (out or "")[-140:]))
        ref = poll(lambda: (lambda s: s if "已过期" in refused_text(s) else None)(
            query_snapshot(py, env, TID)), 90)
        if ref is None:
            wait_worker_alive(fail, worker, wlog)
            s = query_snapshot(py, env, TID)
            fail.bail("B③ 过期授权未被 workflow 拒收登记（refused=%s）"
                      % refused_text(s)[:300])
        print("  相二 证据：refused尾=%s authorizations=%d uses=%d"
              % (refused_text(ref)[-200:], len(authz_items(ref)), uses_total(ref)),
              flush=True)
        check("已过期" in refused_text(ref),
              "B③ 过期授权落 refused 且文案含「已过期」（死授权不进事件历史）")
        check(not authz_items(ref),
              "B③ meta 里没有该授权条目（authorizations=%d）" % len(authz_items(ref)))
        check(uses_total(ref) == 0,
              "B③ uses 未被计入任何条目（uses=%d）" % uses_total(ref))
        base_retry2 = retry_events(ref)
        base_gens2 = len(arb_gens(read_stub_log(stub_log)))
        woke2 = send_retry_and_wait(py, env, stage, fail, base_retry2, check)

        def _reblocked():
            """唤醒真被消费后：arbitrate 真重跑一轮（唤醒复位已落地，是授权消费点的
            前置）→ 无生效授权 → 照旧再 blocked。用「重跑 + blocked」同帧排除「读到
            唤醒前的陈旧 blocked」这一假绿窗。"""
            s = query_snapshot(py, env, TID)
            if (s.get("stage_state") == "blocked" and s.get("stage") in OVER_LIMIT_STAGES
                    and len(arb_gens(read_stub_log(stub_log))) > base_gens2):
                return s
            return None
        back = poll(_reblocked, 300)
        if back is None:
            wait_worker_alive(fail, worker, wlog)
        time.sleep(8)  # grace：settle→再 blocked 转变窗（沿 t260908-01 口径，防早断言假绿）
        snap2 = query_snapshot(py, env, TID)
        check(back is not None and snap2.get("stage_state") == "blocked"
              and snap2.get("stage") in OVER_LIMIT_STAGES,
              "B③ 过期授权唤醒后仍 blocked（未被放行；stage=%s state=%s，arb 账本 "
              "%d→%d）" % (snap2.get("stage"), snap2.get("stage_state"), base_gens2,
                           len(arb_gens(read_stub_log(stub_log)))))
        check(HANDOFF_MARK not in handoff_text(snap2),
              "B③ 历史无授权放行记录（负锁未被误消费）")
        check(not arbitration_authz(snap2) and uses_total(snap2) == 0,
              "B③ 唤醒后仍无生效授权条目/零 uses（authorizations=%d uses=%d）"
              % (len(authz_items(snap2)), uses_total(snap2)))
        print("  相二 唤醒证据：retry 事件 %d→%d，arb 账本 %d→%d"
              % (base_retry2, retry_events(woke2), base_gens2,
                 len(arb_gens(read_stub_log(stub_log)))), flush=True)

        # ---------------- 相三（B②）：生效授权 → 不阻断推进 ----------------
        exp_future = int(time.time()) + 3600
        rc, out = cli_authorize(py, env, exp_future)
        doc = parse_out_json(out)
        check(rc == 0 and doc.get("ok") is True,
              "B② CLI op=authorize（生效授权）送达（rc=%s ok=%s out尾=%s）"
              % (rc, doc.get("ok"), (out or "")[-140:]))
        got = poll(lambda: (lambda s: s if arbitration_authz(s) else None)(
            query_snapshot(py, env, TID)), 90)
        if got is None:
            wait_worker_alive(fail, worker, wlog)
            s = query_snapshot(py, env, TID)
            fail.bail("B② 生效授权未入 meta（authorizations=%d refused=%s）"
                      % (len(authz_items(s)), refused_text(s)[:300]))
        rec = arbitration_authz(got)[-1]
        print("  相三 授权条目：who=%s kind=%s scope=%s issued=%s expires=%s uses=%d"
              % (rec.get("who"), rec.get("kind"), rec.get("scope"), rec.get("issued"),
                 rec.get("expires"), len(rec.get("uses") or [])), flush=True)
        check(str(rec.get("who") or "") == WHO, "B② 授权条目记名 who=%r" % rec.get("who"))
        check(rec.get("kind") == "arbitration_verdict",
              "B② 授权条目记类型 kind=%r" % rec.get("kind"))
        check([str(x) for x in (rec.get("scope") or [])] == [TID],
              "B② 授权条目记 scope=%r（本票票号）" % (rec.get("scope"),))
        check(str(rec.get("reason") or "") == REASON, "B② 授权条目记理由原文")
        check(int(rec.get("issued") or 0) > 0,
              "B② 授权条目记 issued（由 workflow.now() 盖写=%s，非投递值）"
              % rec.get("issued"))
        check(int(rec.get("expires") or 0) == exp_future,
              "B② 授权条目记 expires=%s" % rec.get("expires"))
        check(uses_total(got) == 0, "B② 消费前 uses 为 0（留痕只在真消费时 append）")

        base_retry3 = retry_events(got)
        woke3 = send_retry_and_wait(py, env, stage, fail, base_retry3, check)

        def _advanced():
            """推进证据＝handoff 记录（授权接受判决→acceptance_walkthrough）＋舞台到
            acceptance_walkthrough 或更后。不锚「state != blocked」单条（merge_check
            段 blocked 是桩票合法终态），也不只锚 stage 名（分叉记忆会借位假绿）——
            两条判据同时成立才收。"""
            s = query_snapshot(py, env, TID)
            if HANDOFF_MARK in handoff_text(s) and s.get("stage") in AFTER_AUTHZ_STAGES:
                return s
            return None
        adv = poll(_advanced, 300)
        wait_worker_alive(fail, worker, wlog)
        snap3 = adv or query_snapshot(py, env, TID)
        check(adv is not None,
              "B② 仲裁超限经人授权不阻断 → 离开超限 blocked，推进到 "
              "acceptance_walkthrough 或更后（现 stage=%s state=%s；末次 query rc=%s "
              "out=%s）" % (snap3.get("stage"), snap3.get("stage_state"),
                            LAST_Q.get("rc"), (LAST_Q.get("out") or "")[:200]))
        ho = handoff_text(snap3)
        hit = [h for h in (snap3.get("handoffs") or [])
               if HANDOFF_MARK in json.dumps(h, ensure_ascii=False)]
        print("  相三 授权放行 handoff：%s"
              % json.dumps(hit[-1] if hit else {}, ensure_ascii=False)[:420], flush=True)
        check(HANDOFF_MARK in ho and "acceptance_walkthrough" in ho,
              "B② handoff 含「%s」且点名 acceptance_walkthrough" % HANDOFF_MARK)
        check("测试集迭代" in ho and "超限" in ho,
              "B② handoff 带判决原文关键词（测试集迭代 / 超限）")
        check(WHO in ho, "B② handoff 点名授权人 %r" % WHO)
        check("tests-fault" in ho, "B② handoff 带判决三态 verdict=tests-fault")
        check(uses_total(snap3) >= 1,
              "B② 该授权条目 uses 记一条消费留痕（uses 合计=%d）" % uses_total(snap3))
        print("  相三 推进证据：stage=%s state=%s handoff尾=%s uses=%d"
              % (snap3.get("stage"), snap3.get("stage_state"), ho[-260:],
                 uses_total(snap3)), flush=True)

        # ---------------- 红线审计 ＋ 拆台零残留 ----------------
        audit = read_audit_jsonl(audit_log)
        check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条" % len(audit))
        kill_worker_tree(worker)
        down = stage_down(stage_mod, stage_name)
        stage_downed = True
        resid = (down or {}).get("residue") if isinstance(down, dict) else down
        check(not resid, "拆台零残留（residue=%s）" % (resid,))
    finally:
        kill_worker_tree(worker)
        if stage_mod is not None and not stage_downed:
            try:
                stage_down(stage_mod, stage_name)
            except Exception:
                pass
        if os.environ.get("KI061_KEEP_TMP") == "1":
            print("TMP preserved（KI061_KEEP_TMP=1）: %s" % tmp, flush=True)
        else:
            cleanup_tmp(tmp)
    print("SC sc_authz_overlimit_accept pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
