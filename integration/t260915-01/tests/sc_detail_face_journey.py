#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_detail_face_journey.py — 详情数据面全链旅程（t260915-01 ①②③，灰盒 L3＋契约锁）。

Intent（用户可感知面，验收 1/2/3 的一张真票旅程）：
  ① 受阻陈旧态清除：路径闸拒绝落盘 → 票 blocked，票面受阻原因=闸拒绝回执（不是
     「agent 活动故障」这类与 stage_state 自相矛盾的脏文案）→ 人发 retry_qc → 票面
     blocked_reason 清空且 blocked_detail 清空（与 stage_state 自洽）；**timeline 里
     原 blocked 条目仍在**（机械断言，留痕不丢）＋ retry-requested 留痕在册。
  ② 结构化红灯明细上票面：blocked_detail={check_id,item,red,reason_code,files 全量,
     next_action,evidence=note 原文}——引擎 snapshot 顶层可达，正规入口 ticket.py show
     投影面同可达（跨组件缝）。
  ③ 轮次与分支维度：timeline 条目带 gen（重跑后 create_plan=第 2 轮，snapshot.gens
     同读）、分叉期条目带 phase、meta.parallel_phase 在场（两个分叉点
     parallel_impl_design / arb_acc_parallel 各采样一次）、离场相位键同删、handoff 带 gen。
  契约锁（stdlib 恒跑，docker 台外可守的面）：门判定只在 _init 求值一次、snapshot 函数体
  零 workflow.patched（query 只读硬约束）、_blocked wake 清两字段且 _mark blocked 留痕
  写点仍在、_enter 清 detail、snapshot 透传面（KI-048 三键＋gens）、set_parallel_stages
  相位键、ticket.py 投影白名单带 gens。

分工（防 intent 级重复）：t260908-01 三条（超限复活/重放兼容/pause 旅程）intent=仲裁
超限与暂停语义，本条=详情数据面三件事的用户旅程，不互替；t260911-05 锁 merge_check/merge
分类与 KI-048 状态卡（本条不碰 merge 面，只在契约锁里守其透传面不回归）；t260911-03 系
锁闸的 settle 执法终态（本条只用其判定器当 oracle 制造真实拒绝）；developer L1
（test_t260915_01_detail_face 壳驱动门两态/清点矩阵）不同层不互替。门对新部署后新建票
恒 True、对在途实例恒 False——本条的 blocked→唤醒清态断言只在新建票上成立（C8 前提）。

执行契约（t260910-13 三态）：stdlib 契约锁恒跑；docker/镜像/舞台/隔离台库缺供=exit 2
ENV_FAIL（旅程子用例不跑，锁已跑）；被测行为破面=exit 1。pool=engine（真起台+真 workflow）。
红线：一切 git/票写入只发生在 tempfile 夹具与一次性隔离台；对仓库工作区零写入；
被测子进程 Temporal 地址只指一次性舞台；审计钩子自证零生产面接触（7233/8233/3099）。

Bench migration (host order 261022): the journey no longer buys a docker stage. It
runs on integration/process_bench.py's plain-process Temporal dev server (up in
~0.2 s, kernel-picked free port, private SQLite file, reaped by process group) and
pins SANDBAR_TARGET_HOST/SANDBAR_NAMESPACE at that endpoint; every other env key the
case sets is unchanged. The preconditions are probed FIRST (the endpoint answers a
real gRPC round trip, the worker process is alive, the ticket read face answers), so
a missing precondition is a NAMED red in seconds instead of a three-minute silence.
The state ceilings are graded (CASE_S / the per-state constants below) and an
expired ceiling names the state, the seconds and the last snapshot. Teardown judges
the residue from the outside: the port refuses, no pid survives, the group is empty,
the private temp dir is gone.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.dirname(HERE))                    # 票目录根（lib）
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260908-01"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

from lib_gate import (Fail, accepted, poc_python, read_audit_jsonl, require_bench,  # noqa: E402
                      run_poc_client)
import lib_bench_stage as bench_stage                                  # noqa: E402
from lib_ki061 import (make_fixture_repo, stage_env, spawn_worker, send_signal,  # noqa: E402
                       query_snapshot, poll, wait_worker_alive)
from lib_detail_journey import (DETAIL_STUB, blocked_timeline_entries,  # noqa: E402
                                delete_tracked, judge_violation_set,
                                last_snapshot_text, restore_tracked,
                                ticket_show_face, wait_blocked, wait_fork_left,
                                wait_fork_window, wait_stage_running,
                                wait_unblocked)

TID = "t26091501j1"
PROJ = "t26091501j"
WRITE_SET = ["docs/"]

#: Per-state ceilings in SECONDS, graded by the measured normal path on the
#: process bench (host order 261022). The docker stage's own boot plus the host
#: contention it bought is what used to force 240-300 s ceilings; with the bench
#: the whole journey is a few tens of seconds, so these ceilings catch a stuck
#: state in under a minute and name it with its last snapshot.
STAGE_S = 60        # create_plan running, with a known workspace
BLOCK_S = 60        # blocked carrying the path-gate receipt
WAKE_S = 60         # the wake-up leaving blocked after retry_qc
FORK_S = 90         # the impl||design fork window (the stub holds it 6 s)
LEAVE_S = 60        # leaving that fork window
ARB_S = 60          # the arbitrate fork (live meta, or the post-hoc timeline)


# ---------------- stdlib 契约锁（docker 台外可守的面，恒跑） ----------------

def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def _between(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + 1)
    return src[i:j] if j > i else src[i:]


def _q(s):
    """引号归一（断言语义不锚引号风格）。"""
    return s.replace("'", '"')


def stdlib_locks(fail):
    import re
    dl = _read(os.path.join("server", "engine", "dev_lane.py"))
    fail.check("DETAIL_FACE_PATCH_ID =" in dl, "契约锁：详情面 patch 门常量在位")
    fail.check(len(re.findall(r"self\._detail_face_on\s*=\s*(?:bool\()?\s*"
                              r"workflow\.patched\(", dl)) == 1,
               "契约锁：门判定全文件只求值一次（_init 缓存位；SDK query 只读硬约束）")
    snap = _between(dl, "def snapshot(", "def sign_face(")
    fail.check(bool(snap) and "workflow.patched" not in snap,
               "契约锁：snapshot（query）函数体零 workflow.patched（ReadOnlyContext 回归闸）")
    blk = _q(_between(dl, "async def _blocked(", "async def _blocked_over_limit("))
    i_wait = blk.find("wait_condition")
    i_r = blk.find('self.meta["blocked_reason"] = ""')
    i_d = blk.find('self.meta["blocked_detail"] = None')
    fail.check(bool(blk) and i_wait > 0 and i_r > i_wait and i_d > i_wait,
               "契约锁：_blocked 在 wait_condition 返回处清 blocked_reason+blocked_detail"
               "（retry_qc/rework 两出路唯一汇合点；验收①）")
    fail.check('self._mark(step_id, "blocked", why)' in _q(blk),
               "契约锁：_mark 的 blocked 留痕写点原样在场（审计面不可丢）")
    ent = _q(_between(dl, "def _enter(", "def _finish("))
    fail.check('self.meta["blocked_detail"] = None' in ent,
               "契约锁：_enter 清 blocked_detail（非 blocked 推进不挂红卡——生命周期口径）")
    fail.check('"blocked_reason": str(self.meta.get("blocked_reason") or "")' in snap
               and '"blocked_detail": self.meta.get("blocked_detail")' in snap,
               "契约锁：snapshot 透传面不回归（KI-048 票面横幅/状态卡数据源）")
    fail.check('"gens"' in snap, "契约锁：snapshot 新顶层 gens 段在位（③）")
    sp = _q(dl[dl.find("def set_parallel_stages("): dl.find("def set_parallel_stages(") + 2600])
    fail.check('phase: str = ""' in sp and sp.count('"parallel_phase"') >= 2,
               "契约锁：set_parallel_stages 相位键三态（写/保/删）在位（③）")
    tp = _q(_read(os.path.join("server", "tools", "ticket.py")))
    i_wl = tp.find("for k in (")
    wl_line = [ln for ln in tp.splitlines()
               if "for k in (" in ln and "gate_runs" in ln]
    fail.check(bool(wl_line) and i_wl > 0 and "gens" in tp[i_wl:i_wl + 400],
               "契约锁：ticket.py 投影白名单带 gens（引擎→台面跨组件缝）")


# ---------------- 旅程子用例（真进程台 + 真票 + 真 worker） ----------------

def _stop_worker(worker):
    """Terminate the ticket's worker (TERM first, KILL as the bounded fallback)."""
    if worker is None or worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=15)
    except subprocess.TimeoutExpired:
        worker.kill()


def journey(fail, bench):
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091501j-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    pstage = None
    worker = None
    probes = []
    try:
        # Host order 261022: no docker stage. The Temporal server is this
        # process's own child, up in ~0.2 s on a kernel-picked free port.
        pstage = bench_stage.up(fail, facts=print)
        repo = make_fixture_repo(tmp)
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ, repo)
        env = stage_env(pstage.state(), reg_dir, audit_env)
        stub_path = os.path.join(tmp, "detail_stub.py")
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(DETAIL_STUB)
        stub_log = os.path.join(tmp, "stub.jsonl")
        worker = spawn_worker(py, TID, env, os.path.join(tmp, "worker.log"),
                              stub_path, stub_log)
        wlog = os.path.join(tmp, "worker.log")
        fail.check(worker.poll() is None, "旅程 worker 已拉起 pid=%s" % worker.pid)

        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ,
            "title": "t260915-01 详情数据面旅程", "write_set": list(WRITE_SET),
            # 260927（KI-142）：受理路径必须声明调用方项目（==夹具项目自身）。
            "caller_project": PROJ}, env)
        _ok, _why = accepted(out, TID)
        fail.check(rc == 0 and _ok, "ticket-start 受理（%s）" % _why)

        # ---- preconditions first (seconds), then the state waits below
        bench_stage.preflight(fail, pstage, worker=worker, wlog=wlog,
                              probe=lambda: query_snapshot(py, env, TID),
                              what="create_plan/running")

        # ---- 造真实闸拒绝：create_plan 运行中往泳道写越权探针 → settle 拒绝 → blocked
        snap0 = wait_stage_running(py, env, TID, worker, wlog, fail,
                                   "create_plan", STAGE_S)
        fail.check((snap0.get("meta") or {}).get("path_gate") is True,
                   "本票 path_gate 开（dev-lane 模板默认）——闸子用例前提")
        # The probe is a DELETION of the lane's tracked README.md, a path outside
        # the write set. Why a deletion: the settle auto-disposes an untracked new
        # file (quarantine) and an out-of-write-set unstaged M (archive + restore),
        # so those shapes never reach a refusal; a deletion is left for a human by
        # design (t260916-19 ② / t261016-19 matrix) and so still refuses by name.
        # The oracle stays the real judge, never a copy of its rule table.
        rel = "README.md"
        violations, reason = judge_violation_set("create_plan", WRITE_SET,
                                                 [rel], ticket_id=TID)
        fail.check(bool(violations), "真判定器给出必拒探针（reason=%s violations=%r）"
                   % (reason, violations))
        if not violations:
            fail.bail("无必拒探针可造，闸子用例无法成立")
        # M4 workspace 字段={type,path} dict——探针落点=path（原实现直传 dict=TypeError）
        ws0 = snap0.get("workspace")
        ws_root = ws0.get("path") if isinstance(ws0, dict) else ws0
        probes.append(delete_tracked(ws_root, rel))

        snap_b = wait_blocked(py, env, TID, worker, wlog, fail, BLOCK_S,
                              marker="path_gate_reason=")
        br = snap_b.get("blocked_reason") or ""
        bd = snap_b.get("blocked_detail") or {}
        fail.check("path_gate_reason=" in br,
                   "①票面受阻原因=闸拒绝回执（不是与 stage_state 矛盾的活动故障文案）：%r"
                   % br[:120])
        fail.check(bd.get("reason_code") == reason and rel in (bd.get("files") or []),
                   "②结构化明细：reason_code=%r 与真判定一致、files 点名探针（files=%r）"
                   % (bd.get("reason_code"), bd.get("files")))
        fail.check(bool(bd.get("next_action")) and bd.get("red") is True
                   and str(bd.get("check_id") or "").startswith("path_gate@")
                   and bool(bd.get("item")),
                   "②结构化明细：check_id/item/red/next_action 人话面齐备（%r）"
                   % {k: bd.get(k) for k in ("check_id", "item", "red", "next_action")})
        fail.check(bd.get("evidence") in br,
                   "②证据指针=worker 回执原文（同一字符串进票面，不美化不丢）")
        blocked_before = blocked_timeline_entries(snap_b)
        fail.check(any(e[1] == "create_plan" for e in blocked_before),
                   "①timeline 已留 blocked 条目（wake 前基线，%d 条）" % len(blocked_before))
        rc2, face, raw = ticket_show_face(py, env, TID,
                                          admin_log=os.path.join(tmp, "admin.log"))
        fail.check(rc2 == 0 and isinstance(face, dict)
                   and "path_gate_reason=" in str(face.get("blocked_reason") or ""),
                   "②正规入口投影面同可达（ticket.py show 的 blocked_reason；rc=%s raw尾=%s）"
                   % (rc2, (raw or "")[-200:]))

        # ---- retry_qc 唤醒：当前态字段清空、留痕仍在
        # The refused violation must be gone before the wake-up, otherwise the
        # rework re-refuses on the same deletion (probes = tracked paths to restore).
        for rel_probe in probes:
            restore_tracked(ws_root, rel_probe)
        rc3, _o = send_signal(py, pstage.state(), TID, "retry_qc",
                              "t260915-01 集成场景")
        fail.check(rc3 == 0, "retry_qc 发信受理（rc=%s）" % rc3)
        snap_a = wait_unblocked(py, env, TID, worker, wlog, fail, WAKE_S)
        fail.check((snap_a.get("blocked_reason") or "") == "",
                   "①唤醒后票面 blocked_reason 清空（与 stage_state 自洽）：%r"
                   % (snap_a.get("blocked_reason") or "")[:120])
        fail.check(snap_a.get("blocked_detail") is None,
                   "①唤醒后 blocked_detail 清空（陈旧态清零）：%r"
                   % (snap_a.get("blocked_detail"),))
        tl_after = blocked_timeline_entries(snap_a)
        fail.check(bool(blocked_before) and all(e in tl_after for e in blocked_before),
                   "①timeline 的 blocked 留痕仍在（%d→%d 条，机械断言）"
                   % (len(blocked_before), len(tl_after)))
        fail.check(any(e.get("state") == "retry-requested"
                       for e in (snap_a.get("timeline") or [])),
                   "①唤醒留痕 retry-requested 在 timeline")

        # ---- ③轮次与分支维度：两个分叉点各采样一次
        snap_f = wait_fork_window(py, env, TID, worker, wlog, fail, FORK_S)
        if snap_f is None:
            fail.check(False, "③ did not reach the impl||design fork window "
                       "(meta.parallel_stages non-empty) in %ds — last snapshot: %s"
                       % (FORK_S, last_snapshot_text()))
        else:
            meta = snap_f.get("meta") or {}
            fail.check(meta.get("parallel_phase") == "parallel_impl_design",
                       "③分叉期相位键在票面（parallel_phase=%r）"
                       % meta.get("parallel_phase"))
            run_entries = [e for e in (snap_f.get("timeline") or [])
                           if e.get("state") == "running"]
            fail.check(bool(run_entries) and all(
                isinstance(e.get("gen"), int) and e.get("gen", 0) >= 1
                for e in run_entries),
                "③timeline 条目带轮次 gen（%s）"
                % [(e.get("stage"), e.get("gen")) for e in run_entries])
            fail.check(any(e.get("phase") == "parallel_impl_design"
                           for e in run_entries),
                       "③分叉期条目带相位归属（哪条分支在第几轮）")
            gens = snap_f.get("gens") or {}
            fail.check((gens.get("create_plan") or 0) >= 2,
                       "③snapshot.gens 读 段→第几轮（create_plan=第 %s 轮，重跑后递增）"
                       % gens.get("create_plan"))
            hand = snap_f.get("handoffs") or []
            fail.check(bool(hand) and all("gen" in h for h in hand),
                       "③handoff 条目带 gen（%d 条）" % len(hand))
        snap_l = wait_fork_left(py, env, TID, worker, wlog, fail, LEAVE_S)
        if snap_l is not None:
            fail.check("parallel_phase" not in (snap_l.get("meta") or {}),
                       "③离场相位键同删（不残留钉死已完工分叉）")
        else:
            fail.check(False, "③ did not reach the fork's exit window "
                       "(meta.parallel_stages empty) in %ds — last snapshot: %s"
                       % (LEAVE_S, last_snapshot_text()))
        # ---- ③arb 分叉点相位：活采样优先，事后 timeline 证据兜底（仲裁回执不可解析的
        # 桩票会 blocked 在分叉内——相位证据常驻 timeline 的 running 条目，不依赖活采样）
        arb_trace = []

        def _arb_probe():
            s = query_snapshot(py, env, TID)
            meta = (s or {}).get("meta") or {}
            arb_trace.append((meta.get("parallel_stages") or [],
                              meta.get("parallel_phase")))
            if "arbitrate" in (meta.get("parallel_stages") or []):
                return s
            tl = (s or {}).get("timeline") or []
            if any(e.get("stage") == "arbitrate" and e.get("state") == "running"
                   for e in tl):
                return {"__posthoc__": True, "timeline": tl}
            return None
        snap_f2 = poll(_arb_probe, ARB_S)
        if snap_f2 is not None and snap_f2.get("__posthoc__"):
            arb_entries = [e for e in snap_f2["timeline"]
                           if e.get("stage") == "arbitrate"
                           and e.get("state") == "running"]
            fail.check(any(e.get("phase") == "arb_acc_parallel" for e in arb_entries),
                       "③arb 分叉点相位（事后证据=timeline arbitrate 条目 phase=%r；"
                       "活采样尾=%r）"
                       % ([e.get("phase") for e in arb_entries], arb_trace[-3:]))
        elif snap_f2 is not None:
            fail.check((snap_f2.get("meta") or {}).get("parallel_phase")
                       == "arb_acc_parallel",
                       "③第二分叉点相位 arb_acc_parallel 同样在票面（%r）"
                       % (snap_f2.get("meta") or {}).get("parallel_phase"))
        else:
            fail.check(False,
                       "③ did not reach the arbitrate fork (meta.parallel_stages "
                       "carrying arbitrate, or an arbitrate running timeline "
                       "entry) in %ds — sampling trace tail=%r; last snapshot: %s"
                       % (ARB_S, arb_trace[-5:], last_snapshot_text()))

        # ---- teardown: the worker first, then the bench; residue judged from
        # outside (the port refuses, no pid, empty group, temp dir reclaimed).
        _stop_worker(worker)
        worker = None
        bench_stage.down(pstage, fail, tag="journey bench")
        pstage = None

        audit = read_audit_jsonl(audit_log)
        fail.check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条"
                   % len(audit))
    finally:
        _stop_worker(worker)
        if pstage is not None:
            # Best effort on every failing path: the process group is reaped and
            # the private temp dir removed; process_bench's atexit is the backstop.
            try:
                pstage.down()
            except Exception:                                       # noqa: BLE001
                pass
        if os.environ.get("T26091501_KEEP_TMP") == "1":
            print("TMP preserved（T26091501_KEEP_TMP=1）: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    fail = Fail("t260915-01 详情数据面旅程（blocked 唤醒清态＋结构化红灯票面＋轮次/分支维度）")
    stdlib_locks(fail)
    try:
        bench = require_bench(fail)
        journey(fail, bench)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code in (2, 3):
            print("ENV_FAIL 进程台/台库缺供（exit %s）——旅程子用例不跑，stdlib 契约锁已跑"
                  % code, flush=True)
        raise
    fail.finish()


if __name__ == "__main__":
    main()
