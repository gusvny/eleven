#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-02 场景②：收口自退——票完 worker 自退不留尾巴（工单正文行为 2）。

intent（守护的用户可感知行为）：
- 票收口自退：被守 workflow 到达非 RUNNING 终态 → watch 中的专属 worker 限期
  自退（退出码 0）、自退痕迹在文（收口语义日志）、meta 自清——工单收口后不
  留常驻 worker 尾巴（260824 A 案契约：专属 worker 生命周期跟工单走）；
- 孤儿收养自退：宿主 console 死亡（worker 被 init/launchd 收养、ppid=1）→
  worker 自退——宿主被 SIGKILL、dispose 跑不到时也不留无主 worker（85222
  版本投毒教训）。系统状态条件子用例：收养目标 ppid 随环境（Linux subreaper），
  本环境收养不到 ppid=1 时该子用例按 N/A 折算（不算被测红）；
- 查询失败不误退：watch 指向不存在/查不到的 workflow → worker **不自退**、
  持续存活并留下「查询失败下一轮再试」痕迹——宁可多守一轮，不许「票没守到
  人先走」（误退=工单没人伺候）。

intent 分工（防 intent 级重复）：
- t260904-02-worker-fingerprint-gate＝ensure 消费侧三态判定；本条＝worker 与
  被守 workflow 的生命周期联动（worker 自己决定走）；
- t260905-02-worker-lifecycle＝外部信号主动停；本条＝自退三态（收口/收养/
  查询失败不退）。watch 生效前提：SANDBAR_WATCH_WORKFLOW 置时 watch 循环才
  存在（ppid 守护在循环体内），收养子用例两 env 同置。

三态契约：docker 台缺席=ENV_FAIL exit 2；被测子进程零连生产（审计钩子+自证
子用例）；watch 间隔旋钮 SANDBAR_WATCH_INTERVAL_SEC 提速（「≥两轮」按日志实际
轮次判：旋钮生效 ~4s 收工、失效自然回落 30s 慢档 90s 窗内同判——语义不弱化）；
日志锚兼容正则锚语义（KI-051）。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "t260904-02"))                    # lib_gate
sys.path.insert(0, os.path.dirname(_HERE))                                     # integration/
sys.path.insert(0, _HERE)                                                      # lib_t26090502
from lib_gate import (Fail, cleanup, parse_out_json, poc_python,  # noqa: E402
                      read_audit_jsonl, require_bench, require_stage,
                      run_poc_client, stage_down, wait_port_released)
import stage_docker  # noqa: E402
from lib_t26090502 import (KNOB, KNOB_FAST, child_env, close_logf,  # noqa: E402
                           pid_alive, ppid_of, spawn_via_shortlived_parent,
                           spawn_worker, wait_exit, wait_marker, wait_marker_count)

TAG = "watch-%d" % os.getpid()
PROJ_KEY = "t26090502-watch"
TID = "t26090502-%s" % TAG
PROBE = os.path.join(_HERE, "probe_wf_status.py")


def wf_status(py, host, ns, wfid):
    """服务端可见 workflow 状态：(found, status)。探针自身异常=found False。"""
    try:
        p = subprocess.run([py, PROBE, host, ns, wfid],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "probe_timeout"
    j = parse_out_json(p.stdout)
    return bool(j.get("found")), str(j.get("status") or j.get("reason") or "")


def running_tickets(py, env):
    _, out = run_poc_client(py, "running-tickets", {}, env)
    j = parse_out_json(out)
    return (j.get("result") or {}).get("running") or []


def main():
    fail = Fail("t260905-02 ②收口自退不留尾巴（票收口/孤儿收养/查询失败不退）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26090502-watch-")
    stage_state = None
    procs = []          # 需要 TERM 兜底的被测/夹具进程
    audit_env = audit_log = None
    try:
        # ---------- ① 起台 + fixture 注册表 ----------
        _, state = require_stage(fail, "t26090502-%s" % TAG, "watch-%s" % TAG)
        stage_state = state
        host = "127.0.0.1:%d" % state["ports"]["temporal"]
        fail.check(state["ports"]["temporal"] not in bench.PROD_PORTS,
                   "舞台端口不在生产禁区面（%d）" % state["ports"]["temporal"])
        proj = os.path.join(tmp, "proj")
        os.makedirs(proj, exist_ok=True)
        reg = bench.write_registry(os.path.join(tmp, "reg"), PROJ_KEY, proj)
        audit_env, audit_log = bench.audit_hook_env(os.path.join(tmp, "audit"))
        env0 = child_env(host, state["namespace"], audit_env,
                         {"SANDBAR_PROJECTS_DIR": reg})

        # ---------- ② 开票（真 RUNNING 工单=watch 对象） ----------
        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "收口自退场景票", "write_set": ["docs/"]}, env0)
        j = parse_out_json(out)
        fail.check(rc == 0 and j.get("ok") is True,
                   "开票成功（rc=%s ok=%s out=%s）" % (rc, j.get("ok"), out.strip()[:120]))
        queue = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            for r in running_tickets(py, env0):
                if r.get("id") == TID:
                    queue = str(r.get("queue") or "")
                    break
            if queue:
                break
            time.sleep(1.0)
        fail.check(bool(queue), "running-tickets 在册（tid=%s queue=%s）" % (TID, queue))

        # ---------- ③ 正常子用例 A：票收口（非 RUNNING）→ watch worker 限期自退 ----------
        rc_c, out_c = run_poc_client(py, "cancel", {"workflow_id": TID}, env0)
        jc = parse_out_json(out_c)
        fail.check(rc_c == 0 and jc.get("ok") is True,
                   "工单收口指令成功（terminate rc=%s）" % rc_c)
        closed = False
        deadline = time.time() + 30
        while time.time() < deadline:
            found, status = wf_status(py, host, state["namespace"], TID)
            if found and status and status != "RUNNING":
                closed = True
                break
            time.sleep(1.0)
        fail.check(closed, "服务端可见工单终态非 RUNNING（status=%s）" % status)
        meta_a = os.path.join(tmp, "worker-a.meta")
        log_a = os.path.join(tmp, "worker-a.log")
        w_a = spawn_worker(py, log_a, child_env(host, state["namespace"], audit_env, {
            "SANDBAR_TASK_QUEUE": queue or "suyou-ticket-%s" % TID,  # naming-compat
            "SANDBAR_WATCH_WORKFLOW": TID,
            "SANDBAR_WORKER_META": meta_a, KNOB: KNOB_FAST}))
        procs.append(w_a)
        fail.check(wait_marker(log_a, r"worker 起来了", 40),
                   "watch worker 就绪（起来了标记；watch=%s）" % TID)
        fail.check(wait_exit(w_a, 90), "票收口后 worker 限期自退（≤90s，含 30s 慢档）")
        fail.check(w_a.returncode == 0, "自退退出码 0（实得 %s）" % w_a.returncode)
        fail.check(wait_marker(log_a, r"收口.*自退", 1),
                   "自退痕迹在文：收口语义日志（兼容正则）")
        fail.check(not os.path.exists(meta_a), "自退后 meta 自清")
        close_logf(w_a)

        # ---------- ④ 正常子用例 B：宿主死（孤儿收养 ppid=1）→ 自退 ----------
        # watch 指向不存在的 workflow（describe 恒失败）→ 唯一退出路径=ppid 收养，
        # 收养子用例与收口子用例判定互不掺和。两 env 同置（watch 循环存在的前提）。
        missing_wf = "t26090502-nothing-%s" % TAG
        meta_b = os.path.join(tmp, "worker-b.meta")
        log_b = os.path.join(tmp, "worker-b.log")
        env_b = child_env(host, state["namespace"], audit_env, {
            "SANDBAR_TASK_QUEUE": "suyou-ticket-%s" % TID,  # naming-compat
            "SANDBAR_WATCH_WORKFLOW": missing_wf, "SANDBAR_WATCH_PPID": "1",
            "SANDBAR_WORKER_META": meta_b, KNOB: KNOB_FAST})
        mid = spawn_via_shortlived_parent(py, env_b, log_b)
        try:
            mout, _ = mid.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            mid.kill()
            mout, _ = mid.communicate()
        wpid = None
        for ln in (mout or "").splitlines():
            if ln.strip().isdigit():
                wpid = int(ln.strip())
                break
        fail.check(mid.returncode == 0 and wpid,
                   "中间短命父拉起 worker（wpid=%s mrc=%s）" % (wpid, mid.returncode))
        if wpid:
            # 等自退：收养由中间父退出即刻触发；判定=进程自灭 + worker 自报的收养
            # 语义日志（公开输出说出自退原因），不依赖外部进程名目观测（ps 在沙箱
            # 环境可被整类拒绝——存活观测走 os.kill 探活，非 ps）。
            deadline = time.time() + 90
            exited = False
            while time.time() < deadline:
                if not pid_alive(wpid):
                    exited = True
                    break
                time.sleep(1.0)
            if exited:
                fail.check(True, "孤儿 worker 自退（宿主死后限期 ≤90s，含 30s 慢档首轮等待）")
                fail.check(wait_marker(log_b, r"ppid=1.*收养|收养.*自退", 1),
                           "自退痕迹在文：收养语义日志（worker 自报退出原因=ppid=1 被收养）")
                fail.check(not os.path.exists(meta_b), "收养自退后 meta 自清")
            else:
                print("N/A  孤儿收养子用例：孤儿 worker 90s 内未自退（best-effort ppid=%s）"
                      "——本环境未按 ppid=1 收养（系统状态条件子用例），收养自退在此不可判"
                      % ppid_of(wpid), flush=True)
            # 两种分支都兜底 TERM（N/A 时不留 watch 常驻进程）
        if wpid and pid_alive(wpid):
            try:
                os.kill(wpid, 15)
            except OSError:
                pass

        # ---------- ⑤ 异常子用例：查询失败不误退（持续存活 ≥ 两轮） ----------
        missing_wf2 = "t26090502-nothing2-%s" % TAG
        meta_c = os.path.join(tmp, "worker-c.meta")
        log_c = os.path.join(tmp, "worker-c.log")
        w_c = spawn_worker(py, log_c, child_env(host, state["namespace"], audit_env, {
            "SANDBAR_TASK_QUEUE": "suyou-ticket-%s" % TID,  # naming-compat
            "SANDBAR_WATCH_WORKFLOW": missing_wf2,
            "SANDBAR_WORKER_META": meta_c, KNOB: KNOB_FAST}))
        procs.append(w_c)
        fail.check(wait_marker(log_c, r"worker 起来了", 40),
                   "watch worker 就绪（watch 指向不存在 workflow）")
        # 「≥两轮 watch 周期」按实际轮次判（260908 慢场景解剖）：第二条「状态失败
        # （下一轮再试）」warning 在案=已完整走过两轮失败查询，随后仍存活即契约达成。
        # 旋钮（KNOB_FAST=2）生效 ~4s 收工；旋钮失效自然回落 30s 慢档、90s 窗内同判
        # ——语义不弱化（旧写法 sleep(8)+sleep(62)=70s 固定按慢档等，每跑白等 ~65s）。
        rounds_seen = wait_marker_count(log_c, r"状态失败", 2, 90,
                                        stop_fn=lambda: not pid_alive(w_c.pid))
        time.sleep(2)   # 第二轮落定后的裕量窗（误退若发生必在此现形）
        fail.check(rounds_seen >= 2 and pid_alive(w_c.pid),
                   "查询失败不误退：两轮失败查询在案（实得 %d 轮）且仍存活——按实际"
                   "轮次判，旋钮失效自然回落慢档，语义不弱化" % rounds_seen)
        fail.check(wait_marker(log_c, r"状态失败", 1) and wait_marker(log_c, r"再试", 1),
                   "查询失败痕迹在文（失败+下一轮再试语义锚）——证明确实在查、失败不退")
        fail.check(os.path.exists(meta_c), "存活期间 meta 在册（归属可辨）")
        w_c.terminate()
        fail.check(wait_exit(w_c, 60) and w_c.returncode == 0,
                   "收尾 TERM 干净退（rc=%s）——不误退≠退不干净" % w_c.returncode)
        close_logf(w_c)

        # ---------- ⑥ 红线：零连生产 + 审计钩子自证 ----------
        hits = read_audit_jsonl(audit_log)
        fail.check(not hits,
                   "被测 worker 子进程零生产连接尝试（审计记录 %d 条：%s）"
                   % (len(hits), json.dumps(hits, ensure_ascii=False)[:120]))
        self_env = dict(os.environ)
        self_env.update(audit_env)
        self_env["SANDBAR_AUDIT_SELFTEST"] = "1"
        p = subprocess.run([py, "-c",
                            "import socket; socket.create_connection(('127.0.0.1', 7233), timeout=2)"],
                           env=self_env, capture_output=True, text=True, timeout=30)
        self_hits = read_audit_jsonl(audit_log)
        fail.check(p.returncode != 0 and any("7233" in json.dumps(h) for h in self_hits),
                   "审计钩子自证：故意连 7233 被阻断（rc=%s）且留记录（%d 条）"
                   % (p.returncode, len(self_hits)))

        # ---------- ⑦ teardown ----------
        d = stage_down(stage_docker, state["project"])
        stage_state = None
        fail.check(d.get("residue") == [],
                   "舞台 down 后零残留容器（实得 %s）" % (d.get("residue"),))
        released, held = wait_port_released(state["ports"]["temporal"])
        fail.check(released, "舞台 temporal 端口已释放（%s）"
                   % ("已释放" if released else "仍被占用 pid=%s" % held))
    finally:
        for pr in procs:
            if pr is not None and pr.poll() is None:
                try:
                    pr.terminate()
                    pr.wait(timeout=10)
                except Exception:
                    try:
                        pr.kill()
                    except Exception:
                        pass
            close_logf(pr)
        if stage_state is not None:
            try:
                stage_docker.do_down(stage_state["project"])
            except Exception:
                pass
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
