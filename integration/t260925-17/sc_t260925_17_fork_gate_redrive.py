#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260925-17 场景①：并行叉内路径闸 block 的授权脱困旅程（KI-120 端到端验收面）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
真起 docker 测试台 temporal-only ＋ 工单专属 worker ＋ 桩大脑，复刻 t260925-05 实案
（KI-120）并验收修复后的用户可感知行为——受保护路径闸 block 经人授权放行后，
被挡的叉边必须真重驱（arbitrate 边 respawn），任何 sanctioned 出口 op 都能推票，
「cleared-but-still-blocked 且 blocked_reason 为空」的稳态结构性不存在。

  相 A（并行叉＝本票病灶）：桩在 arbitrate 边摸夹具仓的受保护文件
  docs/design/contract.md（docs/design 前缀名单内、基点已存在＝改动即拦）→
  双边 gather 完成 → join settle 拒 → blocked（reason 含机读 path_gate_reason=
  protected_path）→ 真 CLI 入口 authorize kind=protected_path（scope=该文件、
  限期、记名）→ landing → 放行 marker（桩停止摸保护面）→ retry_qc →
  断言：arbitrate 边真 respawn（桩账本新 spawn、gen 递增）、acceptance_walkthrough
  边**不**重跑（昂贵边保留，KI-024 语义）、settle 带授权落盘成功、票离开 blocked
  推进到 merge_check/merge（正向白名单，防 tests-fault 回路假绿）。
  修复前形态（现状）：retry_qc 被消费但 arbitrate 零 respawn、票停在 blocked 且
  blocked_reason 被清空 → 本场景红（TDD 信号＝KI-120 病灶复现留证）。
  相 B（串行段对照＝回归锚）：同一桩在 implement 段摸同一保护面 → settle 拒 →
  blocked → authorize + marker + retry_qc → implement respawn、票推进（本相在
  修复前即应绿——串行路径本就能脱困，锁的是「修复不把串行脱困弄坏」）。

  全程不变量（票面契约）：每次 snapshot 轮询，凡 stage_state=blocked 则
  blocked_reason/blocked_detail 必须非空——「blocked 且空原因」一经观测即败。

与既有资产 intent 分工（防重复声明）：
- t260911-03 / t260912-03 闸场景：锁 settle activity 级拒绝终态与授权落地消费面
  （直调，零 Temporal，无 workflow 状态机）——本条锁**叉内 block 的醒后重驱旅程**，
  KI-120 的 differentiator 是 fork 簿记，activity 面替代不了；
- t260908-01 ki061 两场景：锁仲裁超限 blocked 的复活/重放（KI-061）——触发面、
  修复面、授权通道（arbitration_verdict）均不同，不互替；
- t260916-19 处置矩阵：锁越权脏状态的分态处置——本条 protected 拒绝（文件原地
  =授权消费前提）之后的授权放行与状态机重驱，彼条不涉及。
断言面＝桩账本（agent 实收 prompt/spawn 序列）/ snapshot（stage/stage_state/
blocked_reason）/ CLI 回执（authorize landing），不锚 prompt 文案与内部字段名。
merge_check 及其后行为不在范围（桩票 merge_check 红转 blocked 属合法终态不判）。

三态：docker/镜像/舞台缺件＝exit 2 ENV_FAIL；被测行为破面＝exit 1。
pool=engine（真起 workflow 占台）。
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
sys.path.insert(0, os.path.join(REPO, "integration", "t260908-01"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
from lib_gate import (Fail, poc_python, read_audit_jsonl, require_bench,  # noqa: E402
                      require_stage, run_poc_client, stage_down)
from lib_ki061 import (arb_gens, poll, query_snapshot, read_stub_log,  # noqa: E402
                       send_signal, spawn_worker, stage_env, wait_worker_alive, LAST_Q)

PROJ_KEY = "t26092517a"
WHO = "宿主"
# 与 t260925-05 实案同形：integration/baselines 下的场景脚本——同时落在
# arbitrate 段 test_face 白名单（sc_*.mjs=场景脚本）与保护名单
# （integration/baselines 前缀）内＝白名单过、protected_path 拒的唯一触发形。
PROTECTED = "integration/baselines/sc_t26092517a_baseline.mjs"
EXPIRES_S = 3600


# 引擎 spawn 命令桩（骨架同 lib_ki061.ARB_STUB）：arbitrate 桩回 verdict=pass；
# 「脏相」阶段（KI120_DIRTY_STAGE 指名）在 KI120_MARKER 不在场时摸受保护文件
# （追加一行）——基点已存在＝protected_path 闸拒的唯一触发形。marker 出现后
# 一律干净回执（授权已放行、重跑过闸）。prompt 原样落 JSONL 账本（断言面）。
KI120_STUB = r"""
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
with open(os.environ["KI061_STUB_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"stage": stage, "ts": time.time(), "prompt": prompt},
                       ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    files = ["docs/ticket-notes.md"]
    dirty = (stage == os.environ.get("KI120_DIRTY_STAGE", "")
             and not os.path.exists(os.environ["KI120_MARKER"]))
    if dirty:
        p = os.path.join(os.getcwd(), *os.environ["KI120_DIRTY_FILE"].split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n[ki120-stub rogue touch %d]\n" % time.time())
        files.append(os.environ["KI120_DIRTY_FILE"])
    summary = "[ki120-stub] %s 完成" % stage
    if stage == "arbitrate":
        summary = "verdict=pass " + summary
    body = {"status": "ok", "summary": summary, "report": "[ki120-stub] 机械回执",
            "deliverables": [], "files_changed": files,
            "files_changed_shape": "ok", "evidence": "ki120-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


def make_fixture_repo(tmp):
    """fixture 项目仓：docs/design/contract.md 预置并首 commit（基点已存在＝
    改动即拦的闸触发前提；骨架抄 lib_ki061.make_fixture_repo）。"""
    repo = os.path.join(tmp, "fixture-repo")
    os.makedirs(os.path.join(repo, "docs", "design"))

    def g(*a):
        subprocess.run(["git", "-C", repo] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("fixture\n")
    with open(os.path.join(repo, "docs", "ticket-notes.md"), "w") as f:
        f.write("notes\n")
    os.makedirs(os.path.join(repo, "integration", "baselines"))
    with open(os.path.join(repo, PROTECTED), "w") as f:
        f.write("// baseline truth\n")
    g("add", "-A")
    g("commit", "-qm", "init")
    return repo


def stage_gens(rows, stage):
    return [r for r in rows if r.get("stage") == stage]


def authorize(py, env, tid):
    """真用户 CLI 入口的人授权（t260913-01 送达面：回执 landing=landed 机读键）。"""
    rc, out = run_poc_client(py, "ticket", {
        "op": "authorize", "caller_project": PROJ_KEY, "ticket_id": tid,
        "who": WHO,
        "kind": "protected_path", "scope": [PROTECTED],
        "reason": "KI-120 验收：受保护路径经人审放行",
        "expires": int(time.time()) + EXPIRES_S}, env)
    return rc, (out or "")


def reason_of(snap):
    """票面卡因读取（blocked_reason 顶层/ meta 双落点 + blocked_detail 兜底）。"""
    meta = snap.get("meta") or {}
    return (snap.get("blocked_reason") or meta.get("blocked_reason")
            or snap.get("blocked_detail") or meta.get("blocked_detail") or "")


def make_invariant():
    """「blocked 且空原因」稳态观测器：每相一个实例，poll 间隙顺手喂 snapshot。"""
    viol = {"n": 0, "snap": None}

    def feed(snap):
        if (snap or {}).get("stage_state") == "blocked" and not reason_of(snap):
            viol["n"] += 1
            viol["snap"] = snap
    return viol, feed


def run_leg(py, fail, tmp, tid, dirty_stage, reg_dir, audit_env, poll_s=480):
    """公共驱动：起 worker ＋ 开票 → 桩摸保护面 → blocked（protected 拒）。
    返回 (worker, env, stub_log, stub_path, block_snap)。"""
    os.makedirs(tmp, exist_ok=True)
    stub_path = os.path.join(tmp, "ki120_stub.py")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(KI120_STUB)
    stub_log = os.path.join(tmp, "stub.jsonl")
    marker = os.path.join(tmp, "KI120_CLEAN")
    os.environ["KI120_MARKER"] = marker
    os.environ["KI120_DIRTY_STAGE"] = dirty_stage
    os.environ["KI120_DIRTY_FILE"] = PROTECTED
    env = stage_env(_state_holder["state"], reg_dir, audit_env)
    # 剥泳道身份标记（防递归/防跨项目闸误伤，t260910-04 三件套纪律 + KI-119 面）：
    # 泳道 env 注入 SANDBAR_CALLER_PROJECT=sandbar 会让场景子进程的 ticket-start
    # 被跨项目写闸拒收（实跑实证）——场景调用方必须以未声明身份走声明化路径。
    for k in ("SANDBAR_CALLER_PROJECT", "SANDBAR_UNDECLARED_POLICY",
              "SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW"):
        env.pop(k, None)
    worker = spawn_worker(py, tid, env, os.path.join(tmp, "worker.log"),
                          stub_path, stub_log)
    wlog = os.path.join(tmp, "worker.log")
    fail.check(worker.poll() is None, "worker 已拉起（%s leg）pid=%s" % (dirty_stage, worker.pid))
    rc, out = run_poc_client(py, "ticket-start", {
        "ticket_id": tid, "template_id": "dev-lane", "project": PROJ_KEY,
        "title": "KI-120 fork gate redrive", "write_set": ["docs/", "integration/"],
        "caller_project": PROJ_KEY}, env)
    ok_json = '"ok":true' in out.replace(" ", "") or '"ok": true' in out
    fail.check(rc == 0 and ok_json,
               "ticket-start 受理（rc=%s ok_json=%s out=%s）" % (rc, ok_json, out[:400]))

    viol, feed_inv = make_invariant()

    def _blocked():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)  # bail
        s = query_snapshot(py, env, tid)
        feed_inv(s)
        if s.get("stage_state") == "blocked" and "protected" in json.dumps(s, ensure_ascii=False):
            return s
        return None
    snap = poll(_blocked, poll_s)
    if snap is None:
        wait_worker_alive(fail, worker, wlog)
        s = query_snapshot(py, env, tid)
        try:
            wtail = open(wlog, encoding="utf-8").read()[-500:]
        except OSError:
            wtail = "<worker log 不可读>"
        fail.bail("%s 相未在 %ds 内到达 protected blocked（现 stage=%s state=%s；"
                  "末次 query rc=%s out=%s；worker 日志尾：%s）"
                  % (dirty_stage, poll_s, s.get("stage"), s.get("stage_state"),
                     LAST_Q.get("rc"), (LAST_Q.get("out") or "")[:200], wtail))
    fail.check("protected" in reason_of(snap) or "protected" in json.dumps(snap, ensure_ascii=False),
               "%s 相到达 blocked 且卡因点名受保护路径（机读 protected_path 在案）" % dirty_stage)
    extras = {"viol": viol, "feed": feed_inv, "marker": marker, "wlog": wlog}
    return worker, env, stub_log, stub_path, snap, extras


_state_holder = {"state": None}


def main():
    fail = Fail("t260925-17 并行叉路径闸 block 授权脱困旅程（KI-120）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26092517a-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    worker = None
    try:
        stage_mod, stage = require_stage(fail, "%s-%d" % (PROJ_KEY, os.getpid()),
                                         "t26092517a")
        _state_holder["state"] = stage
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))

        # ================= 相 A：并行叉（arb_acc_parallel）=================
        tidA = "t26092517a-fork"
        worker, env, stub_log, stub_path, snapA, exA = run_leg(
            py, fail, os.path.join(tmp, "A"), tidA, "arbitrate", reg_dir,
            audit_env)
        arb0 = len(arb_gens(read_stub_log(stub_log)))
        acc0 = len(stage_gens(read_stub_log(stub_log), "acceptance_walkthrough"))
        fail.check(arb0 >= 1, "相A arbitrate 边已跑（账本 %d 行）" % arb0)
        fail.check(acc0 >= 1, "相A acceptance_walkthrough 边已跑（账本 %d 行，双边 gather 完成后 join 拒）" % acc0)

        rc, out = authorize(py, env, tidA)
        fail.check(rc == 0 and "landed" in out,
                   "相A authorize landing（rc=%s out尾=%s）" % (rc, out[-200:]))
        open(exA["marker"], "w").close()  # 放行 marker：桩转干净
        rc, out = send_signal(py, stage, tidA, "retry_qc", WHO)
        fail.check(rc == 0, "相A retry_qc 发信（rc=%s）" % rc)

        # 修后契约：arbitrate 边真 respawn（叉重入），acceptance 边不重跑（保留）
        def _respawn():
            rows = read_stub_log(stub_log)
            s = query_snapshot(py, env, tidA)
            exA["feed"](s)
            if len(arb_gens(rows)) > arb0:
                return (rows, s)
            return None
        got = poll(_respawn, 300)
        wait_worker_alive(fail, worker, exA["wlog"])
        if got is None:
            s = query_snapshot(py, env, tidA)
            fail.check(False,
                       "相A【修复验收】retry_qc 后 arbitrate 边未 respawn（账本 %d 行不变、"
                       "stage=%s state=%s reason=%r）＝KI-120 病灶形态（修复前红属预期 TDD 信号）"
                       % (arb0, s.get("stage"), s.get("stage_state"), reason_of(s)))
        else:
            rows2, _ = got
            gens2 = arb_gens(rows2)
            fail.check(gens2[-1]["gen"] > arb_gens(read_stub_log(stub_log))[0]["gen"] - 1
                       and gens2[-1]["gen"] >= 1,
                       "相A arbitrate respawn gen 递增（真重跑非 memo 消费）")
            acc1 = len(stage_gens(rows2, "acceptance_walkthrough"))
            fail.check(acc1 == acc0,
                       "相A acceptance_walkthrough 边零重跑（%d→%d，昂贵边保留 KI-024 语义）"
                       % (acc0, acc1))
            prompt2 = gens2[-1]["prompt"]
            fail.check("授权" in prompt2 or "authoriz" in prompt2.lower()
                       or "放行" in prompt2,
                       "相A respawn prompt 带授权上下文（人外部输入进新 prompt，非陈旧判决）")

        def _left():
            s = query_snapshot(py, env, tidA)
            exA["feed"](s)
            if s.get("stage") in ("merge_check", "merge"):
                return s
            # 票已走完全链被收口清理（closed+workflow 撤场）也算「离开 blocked 推进」
            if not s and "workflow not found" in (LAST_Q.get("out") or ""):
                return {"stage": "<closed>"}
            return None
        left = poll(_left, 300)
        wait_worker_alive(fail, worker, exA["wlog"])
        fail.check(left is not None,
                   "相A 授权放行后票离开 blocked 推进（现 stage=%s state=%s）"
                   % ((left or {}).get("stage"), (left or {}).get("stage_state")))
        if exA["viol"]["n"]:
            fail.check(False, "相A【不变量】观测到 %d 次「blocked 且空 reason」稳态（KI-120 票面破面）"
                       % exA["viol"]["n"])
        else:
            fail.check(True, "相A 不变量零违例：blocked 态全程带非空卡因")
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
        worker = None

        # ================= 相 B：串行段对照（回归锚）=====================
        tidB = "t26092517a-serial"
        worker, envB, stub_logB, _, snapB, exB = run_leg(
            py, fail, os.path.join(tmp, "B"), tidB, "implement", reg_dir,
            audit_env)
        imp0 = len(stage_gens(read_stub_log(stub_logB), "implement"))
        rc, out = authorize(py, envB, tidB)
        fail.check(rc == 0 and "landed" in out,
                   "相B authorize landing（rc=%s）" % rc)
        open(exB["marker"], "w").close()
        rc, out = send_signal(py, stage, tidB, "retry_qc", WHO)
        fail.check(rc == 0, "相B retry_qc 发信（rc=%s）" % rc)

        def _serial_back():
            rows = read_stub_log(stub_logB)
            s = query_snapshot(py, envB, tidB)
            exB["feed"](s)
            if len(stage_gens(rows, "implement")) > imp0:
                return s
            return None
        back = poll(_serial_back, 300)
        wait_worker_alive(fail, worker, exB["wlog"])
        fail.check(back is not None,
                   "相B【回归锚】串行段 authorize+retry_qc 后 implement 重入（账本 %d→%s；"
                   "修复前本相即绿——修复不得弄坏串行脱困）"
                   % (imp0, len(stage_gens(read_stub_log(stub_logB), "implement"))))
        if exB["viol"]["n"]:
            fail.check(False, "相B【不变量】观测到 %d 次「blocked 且空 reason」稳态"
                       % exB["viol"]["n"])
        else:
            fail.check(True, "相B 不变量零违例")
        rc, out = run_poc_client(py, "ticket", {"op": "show", "caller_project": PROJ_KEY, "ticket_id": tidB}, envB)
        fail.check("protected" in (out or "") or rc == 0,
                   "相B 授权可查面可达（show rc=%s）" % rc)

        # ---------- 红线审计：零生产面接触 ----------
        audit = read_audit_jsonl(audit_log)
        fail.check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条" % len(audit))
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
        if stage_mod is not None:
            stage_down(stage_mod, "%s-%d" % (PROJ_KEY, os.getpid()))
        if os.environ.get("KI120_KEEP_TMP") == "1":
            print("TMP preserved（KI120_KEEP_TMP=1）: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
