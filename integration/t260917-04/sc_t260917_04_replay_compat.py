#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-04 场景：仲裁闸拒分支的 patched 门——事故本体复现＋在飞回放兼容（灰盒 L3，docker 台）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
t260917-01（373741c）在 dev_lane 仲裁段新增的 settle 闸拒直落分支未过 workflow.patched
门，在飞 t260916-19/-21 重放即 NondeterminismError（TMPRL1100：查询/推进全拒、stage 变
None、worker 日志 Failing legacy query request）。main 侧紧急收口 2c1b4ee 补了常量 id
门。本场景在 docker 测试台**精确复刻事故旅程**再用现行树断言修复契约——不依赖任何测试
开关（main 形态无 DISABLE 开关；pre-fix 形态由更早历史代码直接构造）：
  子用例一（事故 history 形态 × 现行代码的重放＝回归闸）：`git archive 1bf8d15`（分支尚不
    存在的历史代码）起 worker A 驱动票连收闸拒回执 → 旧路径把闸拒计入格式轮次（「N 次
    verdict= 标记」误导脸 blocked——这正是 -19/-21 的旅程与现形态：他们的 history 早于
    分支存在，格式脸只属于这类老历史票；373741c 出生的票当场走诚实脸，v3 试跑实证）
    → replay_check 用**现行树代码**只读回放该 history 断言 ok=true。
    机制注记（v4 实证取证）：本 history 走并行汇合路径（fork memo=True），373741c 未落
    门时纠正用例分支（:1994）在重放中**命令巧合**——分支 continue 后重排的下一命令与旧
    路径重合、终局双方皆零命令 wait 任务，重放只核命令流 → 未落门树回放同样 ok=true；
    事故的命令可见分歧面在**串行仲裁分支**（fork memo=False 老票的 :1769：分支跳过本
    应发生的纠正活动命令＝事故报错「No command scheduled for event 201」形态），该面
    由 implement 段 S4（真票 -19/-21 replay_check）与 L1 源码锁承接——本条不构造上古
    ref 的串行票（老引擎兼容面过宽，脆）。落门后（main 形态：老历史无 marker→门恒
    False→旧路径逐字）语义不变，本子用例两态皆绿。
  子用例二（换代码唤醒＝事故痛点面）：换现行树 worker B → retry_qc 发信被受理（不再被
    Temporal 拒绝）→ 唤醒穿越老 history＋（树上已带门时）patched 求值，仲裁边真重跑 →
    票仍可查且回到连贯 blocked → replay_check 回放全 history（老历史＋换码续段）再断
    ok=true——在飞票跨代码边界的完整形态。

断言边界（防 rot 与防钉缺陷）：激活语义（闸拒直落诚实脸/机读键上票面/计数解耦）**不在
本场景断言**——main 常量 id 形态存在已知「唤醒不激活」缺陷（KI-094：在飞票首评落重放
段 memo 固化 False，救治语义对停环票未达，follow-up 票门升级 `base#seq` per-entry），
钉住＝把缺陷行为写进契约；patched marker 只作诊断不作断言锚（SDK 事件形态防漂移）。
本票收敛范围（gen3 方案 S1-S5＋review R1-R5）的回放证据由子用例一/子用例二与 implement 段 S4
（真票 -19/-21 replay_check）双路承担。

造拒刺激（披露）：桩回执 summary 直带机读键 path_gate_reason=unauthorized_path——
shared.arbitrate_settle_refusal 判序 2 的文本兜底契约面（无结构化 gate_refusal 的老回
执形态），亦即 t260917-01 除名场景 L1 rogue 手法命中后的回执文本形态；非物理 rogue
文件。settle 路径闸对 lane 实际 dirty 文件的判定面归 t260917-01 UT 与其 L1 场景，本条
只消费 workflow 侧分支语义（分支判据=summary/gate_refusal，与回执 status 无关）。

分工（intent 级不重复）：与 t260908-01-ki061-replay-compat 不同面——彼锁 KI-061 唤醒
重置 patch 的重放兼容（tests-fault 超限路由），本条锁仲裁闸拒 patch 的重放兼容＋换码唤
醒连贯（闸拒/格式计数路由），互为不同 patch 族；与 developer 源码锁
（server/engine/tests/test_t260917_04_replay_gate_lock.py，L1 形态/语义锁）不同层；
t260917-01 场景已除名（nestedGuard 自守），本条承接其「闸拒≠缺 verdict」痛点面的留证
半边（激活半边归 follow-up 票场景）。

三态：docker/镜像/舞台缺件、git archive 归档失败＝ENV_FAIL exit 2（require_bench/
require_stage/归档校验单点出口）；replay_check 自身基建面（results 空且 error 在场＝
连接/取历史失败）同 ENV_FAIL exit 2（R1 三态细则：不记票红也不记票过）；回放分歧/断言
破面＝exit 1。两子用例核心对「树未落门/已落门」两态皆绿（机制见上），arb/merge 期必须绿。
零碰 3099/7233/8233（舞台＝本场景专属一次性 docker 工程）。pool=engine。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (os.path.join(REPO, "integration"),
          os.path.join(REPO, "integration", "t260904-02"),
          os.path.join(REPO, "integration", "t260908-01")):
    if p not in sys.path:
        sys.path.insert(0, p)
import lib_ki061 as lk  # noqa: E402  （spawn_worker 的 POC_DIR 走模块全局，按子用例切换）
from lib_gate import (Fail, poc_python, require_bench, require_stage,  # noqa: E402
                      run_poc_client, stage_down)
from lib_ki061 import (arb_gens, make_fixture_repo, poll,  # noqa: E402
                       query_snapshot, read_stub_log, send_signal, stage_env,
                       wait_worker_alive)

TID = "t26091704-replay"
PROJ_KEY = "t26091704"
PRE_BRANCH_REF = "1bf8d15"  # t260916-28 收口＝闸拒分支尚不存在的历史代码（事故 history 形态）

# 本场景桩的回执模式与拒绝文案（worker 环境读定；两代 worker 各自装配）。
ENV_STUB_MODE = "SANDBAR_T26091704_SC_ARB"          # refusal（缺省）| pass
ENV_STUB_REFUSAL = "SANDBAR_T26091704_SC_REFUSAL"   # 拒绝 summary 全文
ROGUE_REL = "integration/baselines/e2e-gate-probe-t26091704.txt"
REFUSAL_SUMMARY = ("settle 被路径闸拒绝：path_gate_reason=unauthorized_path；越界文件 "
                   + ROGUE_REL + " 不在本段允许面（integration/baselines 为受保护共享"
                   "资产）；合法出路：把改动收回本段允许面/写集内，或拆票走正式流程；"
                   "越权文件不落盘")

# 引擎 spawn 命令桩（骨架抄 lib_ki061.ARB_STUB，账本 env 同名 KI061_STUB_LOG 复用）：
# ①prompt 原样落 JSONL 账本（仲裁派单代数断言面＝agent 实收 prompt）；
# ②arbitrate 桩按 ENV_STUB_MODE 回执——refusal=带机读键无判定标记的闸拒回执（老回执
#   文本形态，判序 2 可辨）、pass=正常判定；
# ③其余段回合法 ok（秒过）。files_changed 恒带 docs 改动（settle 有物可落且在写集内，
#   不触发任何真实路径闸——本条刺激只在回执文本层）。
ARB04_STUB = r"""
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
    if stage == "arbitrate" and os.environ.get("SANDBAR_T26091704_SC_ARB") == "pass":
        body = {"status": "ok",
                "summary": "集成测试三态判定：verdict=pass（arb04 桩：机械检查全通过）",
                "report": "[arb04-stub] pass 回执",
                "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "arb04-stub"}
    elif stage == "arbitrate":
        body = {"status": "ok",
                "summary": os.environ.get("SANDBAR_T26091704_SC_REFUSAL", ""),
                "report": "[arb04-stub] 闸拒回执（无判定标记）",
                "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "arb04-stub"}
    else:
        body = {"status": "ok", "summary": "[arb04-stub] %s 完成" % stage,
                "report": "[arb04-stub] 桩回执",
                "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "arb04-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


def run_replay_check(py, state, tid):
    """replay_check 只读回放指定工单（指向测试台，零写；ki061 场景同款）。

    只用**现行树**代码（POC_DIR=lane）——回放器带「被测树的新代码」是本契约的另一半
    （树=被合并代码，闸门落在谁的树上就测谁）。
    payload 口径（replay_check 自身契约＋review R1 三态细则）：results 非空＝逐票重放
    判定在（分歧/兼容都算「判到了」）；results 空且 error 在场＝replay_check 自身基建
    面（连接/取历史失败）——调用方按环境红归类，不得记票红也不得记票过。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = state["namespace"]
    try:
        p = subprocess.run([py, os.path.join(lk.POC_DIR, "replay_check.py"),
                            "--workflow", tid],
                           capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return 1, {"ok": False, "error": "replay_check 300s 超时（基建面）",
                   "results": []}
    try:
        payload = json.loads(p.stdout or "{}")
    except ValueError:
        payload = {"ok": False, "results": [],
                   "error": "replay_check 非 JSON 输出（rc=%s）：%s"
                            % (p.returncode,
                               ((p.stdout or "") + (p.stderr or ""))[:300])}
    return p.returncode, payload


def _replay_infra_fail(payload):
    """replay_check 自身基建面（无逐票判定结果）＝环境红语义。"""
    return not (payload.get("results") or []) and bool(payload.get("error"))


def _arb_blocked_entries(snap):
    """仲裁边上 blocked 时间线条目数（fork 显示 caveat 口径：条目自带真段名）。"""
    return len([e for e in (snap.get("timeline") or [])
                if e.get("state") == "blocked" and e.get("stage") == "arbitrate"])


def _unpack_history_tree(fail, tmp, ref):
    """git archive <ref> 的 server/engine → tmp/<ref>/server/engine（只读 git 操作）。"""
    root = os.path.join(tmp, "ref-%s" % ref)
    os.makedirs(root, exist_ok=True)
    arc = os.path.join(tmp, "ref-%s.tar" % ref)
    with open(arc, "wb") as f:
        p = subprocess.run(["git", "archive", ref, "server/engine"],
                           stdout=f, stderr=subprocess.PIPE, cwd=REPO)
    if p.returncode != 0:
        fail.bail("git archive %s 失败（ENV）：%s" % (ref,
                  p.stderr.decode(errors="replace")[:200]), 2)
    with tarfile.open(arc) as t:
        t.extractall(root)
    engine = os.path.join(root, "server", "engine")
    if not os.path.isfile(os.path.join(engine, "worker.py")):
        fail.bail("归档树缺 worker.py（ENV）：%s 归档解包不完整" % ref, 2)
    return engine


def main():
    fail = Fail("t260917-04 仲裁闸拒 patched 门：事故本体复现＋在飞回放兼容")
    bench = require_bench(fail)
    py = poc_python(bench)
    lane_poc = lk.POC_DIR
    tmp = tempfile.mkdtemp(prefix="t26091704-")
    stage_mod = None
    worker_a = None
    worker_b = None
    try:
        stage_mod, state = require_stage(fail, "%s-%d" % (PROJ_KEY, os.getpid()),
                                         PROJ_KEY)
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        env = stage_env(state, reg_dir)
        env[ENV_STUB_MODE] = "refusal"
        env[ENV_STUB_REFUSAL] = REFUSAL_SUMMARY
        stub_path = os.path.join(tmp, "arb04_stub.py")
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(ARB04_STUB)
        stub_log = os.path.join(tmp, "stub.jsonl")

        # ---------- 子用例一：分支尚不存在的历史代码 worker → 事故 history → 现行树只读回放
        pre_engine = _unpack_history_tree(fail, tmp, PRE_BRANCH_REF)
        lk.POC_DIR = pre_engine  # worker A 用归档树（分支不存在的历史代码；调用点读模块全局）
        wlog_a = os.path.join(tmp, "workerA.log")
        worker_a = lk.spawn_worker(py, TID, env, wlog_a, stub_path, stub_log,
                                   disable_ki061=False, arb_verdict="refusal")
        lk.POC_DIR = lane_poc  # 客户端/回放器恢复现行树（回放器带被测树的新代码＝契约另一半）
        fail.check(worker_a.poll() is None,
                   "子用例一 worker（%s 归档树＝闸拒分支尚不存在的历史代码，零开关依赖）已拉起"
                   " pid=%s" % (PRE_BRANCH_REF, worker_a.pid))

        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "t260917-04 仲裁闸拒回放兼容两代 worker 闸",
            "write_set": ["docs/"]}, env)
        fail.check(rc == 0 and TID in out,
                   "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))

        def _old_blocked():
            if worker_a.poll() is not None:
                wait_worker_alive(fail, worker_a, wlog_a)  # 即时点名并终止
            s = query_snapshot(py, env, TID)
            if (s.get("stage") in ("arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
                    and s.get("stage_state") == "blocked"):
                return s
            return None
        snap1 = poll(_old_blocked, 420)
        if snap1 is None:
            wait_worker_alive(fail, worker_a, wlog_a)
            s = query_snapshot(py, env, TID)
            fail.bail("子用例一未在 420s 内到达仲裁边 blocked（现 stage=%s state=%s）——"
                      "历史代码 worker 未复刻事故旅程或驱动链断"
                      % (s.get("stage"), s.get("stage_state")))
        why1 = str(snap1.get("blocked_reason") or "")
        fail.check("次缺 verdict= 标记" in why1,
                   "子用例一前提：闸拒按旧路径计入格式轮次（-19/-21 现形态误导脸留证）：%s"
                   % why1[:120])
        gens1 = arb_gens(read_stub_log(stub_log))
        fail.check(len(gens1) >= 2,
                   "子用例一前提：格式纠正真迭代过（arbitrate 派单数=%d）" % len(gens1))

        rc, payload = run_replay_check(py, state, TID)
        if _replay_infra_fail(payload):
            fail.bail("replay_check 自身基建面无法核回放（ENV，非产品红；R1 细则②）：%s"
                      % json.dumps(payload, ensure_ascii=False)[:400], 2)
        r = (payload.get("results") or [{}])
        r0 = r[0] if r else {}
        fail.check(rc == 0 and payload.get("ok") is True and r0.get("ok") is True,
                   "子用例一核心：现行树代码只读回放事故 history 零分歧 ok=true（rc=%s ok=%s "
                   "r0=%s；未落门/已落门两态皆绿：join 路径分支重放命令巧合，见 docstring "
                   "机制注记）"
                   % (rc, payload.get("ok"), json.dumps(r0, ensure_ascii=False)[:300]))

        # ---------- 子用例二：换现行树 worker → retry_qc 唤醒（事故痛点面）→ 全 history 回放
        worker_a.terminate()
        try:
            worker_a.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker_a.kill()
        wlog_b = os.path.join(tmp, "workerB.log")
        worker_b = lk.spawn_worker(py, TID, env, wlog_b, stub_path, stub_log,
                                   disable_ki061=False, arb_verdict="refusal")
        fail.check(worker_b.poll() is None,
                   "子用例二 worker（现行树代码）已拉起 pid=%s" % worker_b.pid)

        rc, out = send_signal(py, state, TID, "retry_qc", "宿主")
        fail.check(rc == 0, "子用例二 retry_qc 发信被受理（rc=%s）——事故痛点面：唤醒不再被 "
                            "Temporal 拒绝" % rc)
        gens_before_wake = len(gens1)

        def _woke():
            rows = read_stub_log(stub_log)
            return rows if len(arb_gens(rows)) > gens_before_wake else None
        if poll(_woke, 300) is None:
            wait_worker_alive(fail, worker_b, wlog_b)
            fail.bail("子用例二 300s 未见 retry_qc 后仲裁重派——换码 worker 穿越老 history 的"
                      "任务失败或唤醒未被消费（见 workerB.log；若树上刚落门，核对门的"
                      "重放语义）")
        fail.check(True, "子用例二事故痛点面：换代码后老票仍可唤醒且仲裁边真重跑"
                         "（唤醒穿越老 history＋patched 求值）")

        def _blocked_again():
            s = query_snapshot(py, env, TID)
            return s if s.get("stage_state") == "blocked" else None
        if poll(_blocked_again, 300) is None:
            wait_worker_alive(fail, worker_b, wlog_b)
            s = query_snapshot(py, env, TID)
            fail.bail("子用例二唤醒后未在 300s 内回到连贯 blocked（现 stage=%s state=%s）"
                      % (s.get("stage"), s.get("stage_state")))
        time.sleep(10)  # 事件落定窗

        rc, payload = run_replay_check(py, state, TID)
        if _replay_infra_fail(payload):
            fail.bail("replay_check 自身基建面无法核回放（ENV，非产品红；R1 细则②）：%s"
                      % json.dumps(payload, ensure_ascii=False)[:400], 2)
        r = (payload.get("results") or [{}])
        r0 = r[0] if r else {}
        fail.check(rc == 0 and payload.get("ok") is True and r0.get("ok") is True,
                   "子用例二核心：全 history（老历史＋换码续段）回放零分歧 ok=true"
                   "（rc=%s ok=%s r0=%s）"
                   % (rc, payload.get("ok"), json.dumps(r0, ensure_ascii=False)[:300]))

        s3 = query_snapshot(py, env, TID)
        fail.check(bool(s3) and s3.get("stage_state") == "blocked",
                   "事故痛点面收口：两代 worker 换代码＋唤醒后 snapshot 仍可查且状态可辨")
    finally:
        lk.POC_DIR = lane_poc
        for w in (worker_a, worker_b):
            if w is not None and w.poll() is None:
                w.kill()
        if stage_mod is not None:
            stage_down(stage_mod, "%s-%d" % (PROJ_KEY, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
