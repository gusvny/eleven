#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-02 场景①：裸入口开票硬闸 + 隔离台并发隔离端到端（epic 验收 1/4/5）。

intent（守护的用户可感知行为）：
- 裸 client.py ticket-start 带 project → 落在 Temporal 里的工单 payload
  workspace.path 为绝对路径且锚 <注册项目主目录>/.lane/（worktree 同锚）——
  落仓不再由执行 worker 的 REPO_ROOT 决定（KI-032 修复回归）；
- 缺 project / 未知 project key = 创建即拒收，两条红因文案互辨（不静默相对路径）；
- 双 docker 舞台两路并发开票（时间重叠）：ticket-list 互不见对方工单、跨台 describe
  not_found —— 零数据串台（宿主红线①）；
- 被测子进程零连生产 7233/8233（审计钩子先记后抛=连接被阻断；含自证拦截腿证明
  钩子活着）+ 舞台端口面显式核验（端口互异、不在禁区面）——绝不影响生产
  temporal（宿主红线②）；
- teardown：down 零残留（docker ps 无本工程容器）、端口释放、down 幂等二连、
  同工程名可立即 re-up（资源可复用——t260904-19 起 docker 台语义，替代原
  槽位制 flock 复抢/kill-9 崩溃腿：容器由 daemon 持有，无锁可崩，取舍见
  stage_docker.py 头注对照表）。

t260904-19：temporal 引擎台从 bench.py 槽位制迁移到 docker 测试台
（integration/stage_docker.py 单点入口，lib_gate.require_stage 直译三态）。
红线：本场景自身绝不 connect 生产端口（探活只打舞台端口）；不 touch 3099。
"""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # integration/（stage_docker 所在）
from lib_gate import (Fail, cleanup, parse_out_json, port_listening,  # noqa: E402
                      poc_python, read_audit_jsonl, require_bench, require_stage,
                      run_poc_client, stage_down, wait_port_released)
import stage_docker  # noqa: E402

TID_A = "t26090402-anchor-a"
TID_B = "t26090402-anchor-b"
PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_wf_input.py")


def stage_env(state, registry_dir, audit_env):
    """被测 client 子进程 env：连舞台 temporal/舞台 namespace/注册表/审计钩子。"""
    env = dict(os.environ)
    env["SUYOU_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SUYOU_NAMESPACE"] = state["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = registry_dir
    if audit_env:
        env.update(audit_env)
    return env


def open_ticket_thread(barrier, out, key, py, env, tid):
    barrier.wait()  # 两路时间真重叠（非先后存在）
    rc, stdout = run_poc_client(py, "ticket-start", {
        "ticket_id": tid, "template_id": "dev-lane", "project": key,
        "title": "anchor 硬闸场景票", "write_set": ["docs/"]}, env)
    out[tid] = (rc, stdout)


def main():
    fail = Fail("t260904-02 ①裸入口开票硬闸+隔离台并发隔离")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26090402-anchor-")
    stage_a = stage_b = None
    try:
        # ---------- ① 库自证：生产守卫红绿（fail-closed 面） ----------
        guard_hit = {}
        for port in bench.PROD_PORTS:
            try:
                bench.assert_not_production("127.0.0.1:%d" % port)
                guard_hit[port] = "未拒"
            except bench.ProductionGuardError as e:
                guard_hit[port] = "拒（%s…）" % str(e)[:40]
            except Exception as e:  # 其它异常=契约面错
                guard_hit[port] = "异常类型错：%s" % type(e).__name__
        for port in bench.PROD_PORTS:
            fail.check(guard_hit[port].startswith("拒"),
                       "生产守卫拒 127.0.0.1:%d（实得：%s）" % (port, guard_hit[port]))
        try:
            bench.assert_not_production("127.0.0.1:21001")
            ok_base = True
        except Exception as e:
            ok_base = False
            fail.check(False, "舞台端口基址须过生产守卫（实得异常：%s）" % e)
        if ok_base:
            fail.check(True, "生产守卫放行舞台端口基址（fail-closed 不误伤隔离台）")

        # ---------- ② 起双 docker 舞台（独立工程名+独立 namespace，真并发隔离面） ----------
        tag = "%d" % os.getpid()
        _, sa = require_stage(fail, "t26090402-a-%s" % tag, "stage-a-%s" % tag)
        _, sb = require_stage(fail, "t26090402-b-%s" % tag, "stage-b-%s" % tag)
        stage_a, stage_b = sa, sb
        pa, pb = sa["ports"], sb["ports"]
        fail.check(sa["project"] != sb["project"], "双台工程名互异（%s / %s）"
                   % (sa["project"], sb["project"]))
        fail.check(set(pa.values()).isdisjoint(set(pb.values())),
                   "双台端口零交集（A=%s B=%s）" % (pa, pb))
        fail.check(sa["namespace"] != sb["namespace"], "双台 namespace 互异")
        for label, ports in (("台A", pa), ("台B", pb)):
            for name, p in ports.items():
                fail.check(p not in stage_docker.FORBIDDEN_PORTS,
                           "%s %s 端口 %d 不在禁区面（3099/3199/7233/8233/17233/18233）"
                           % (label, name, p))
                fail.check(port_listening(p), "%s %s 端口 %d 探活" % (label, name, p))
            for pp in bench.PROD_PORTS:
                fail.check(pp not in ports.values(),
                           "%s 端口面不含生产端口 %d" % (label, pp))

        # ---------- ③ fixture 注册表（每台独立项目主目录） ----------
        proj_a = os.path.join(tmp, "proj-a"); proj_b = os.path.join(tmp, "proj-b")
        os.makedirs(proj_a, exist_ok=True); os.makedirs(proj_b, exist_ok=True)
        reg_a = bench.write_registry(os.path.join(tmp, "reg-a"), "bench-anchor-a", proj_a)
        reg_b = bench.write_registry(os.path.join(tmp, "reg-b"), "bench-anchor-b", proj_b)

        # ---------- ④ 审计钩子 + 两路并发开票（时间重叠） ----------
        audit_env_a, log_a = bench.audit_hook_env(os.path.join(tmp, "audit-a"))
        audit_env_b, log_b = bench.audit_hook_env(os.path.join(tmp, "audit-b"))
        env_a = stage_env(sa, reg_a, audit_env_a)
        env_b = stage_env(sb, reg_b, audit_env_b)
        barrier = threading.Barrier(2)
        out = {}
        th = [threading.Thread(target=open_ticket_thread,
                               args=(barrier, out, "bench-anchor-a", py, env_a, TID_A)),
              threading.Thread(target=open_ticket_thread,
                               args=(barrier, out, "bench-anchor-b", py, env_b, TID_B))]
        for t in th:
            t.start()
        for t in th:
            t.join()
        for tid in (TID_A, TID_B):
            rc, stdout = out.get(tid, (-1, ""))
            j = parse_out_json(stdout)
            fail.check(rc == 0 and j.get("ok") is True,
                       "并发开票 %s 成功（rc=%s ok=%s out=%s）"
                       % (tid, rc, j.get("ok"), stdout.strip()[:120]))

        # ---------- ⑤ payload 锚定断言（KI-032 修复回归主断言） ----------
        import subprocess
        for tid, state, proj, env, label in ((TID_A, sa, proj_a, env_a, "台A"),
                                             (TID_B, sb, proj_b, env_b, "台B")):
            p = subprocess.run([py, PROBE, "127.0.0.1:%d" % state["ports"]["temporal"],
                                state["namespace"], tid],
                               capture_output=True, text=True, timeout=60)
            r = parse_out_json(p.stdout)
            fail.check(r.get("found") is True,
                       "%s describe 取到 workflow input（reason=%s）" % (label, r.get("reason")))
            ws = ((r.get("input") or {}).get("workspace") or {})
            wpath = str(ws.get("path") or "")
            lane_root = os.path.join(proj, ".lane") + os.sep
            fail.check(os.path.isabs(wpath),
                       "%s workspace.path 为绝对路径（实得 %r）" % (label, wpath))
            fail.check(wpath.startswith(lane_root),
                       "%s workspace.path 锚项目主目录 .lane/（期望前缀 %s，实得 %r）"
                       % (label, lane_root, wpath))
            wtree = str((r.get("input") or {}).get("worktree") or "")
            fail.check(wtree.startswith(lane_root),
                       "%s worktree 同锚项目主目录 .lane/（实得 %r）" % (label, wtree))

        # ---------- ⑥ 负向：缺 project / 未知 key 拒收且红因互辨 ----------
        rc_u, out_u = run_poc_client(py, "ticket-start", {
            "ticket_id": "t26090402-anchor-u", "template_id": "dev-lane",
            "project": "bench-nope", "title": "未知 key 腿", "write_set": ["docs/"]}, env_a)
        j_u = parse_out_json(out_u)
        fail.check(j_u.get("ok") is not True and "未知项目" in out_u,
                   "未知 project key 拒收且回执点名「未知项目」（rc=%s out=%s）"
                   % (rc_u, out_u.strip()[:100]))
        rc_m, out_m = run_poc_client(py, "ticket-start", {
            "ticket_id": "t26090402-anchor-m", "template_id": "dev-lane",
            "title": "缺 project 腿", "write_set": ["docs/"]}, env_a)
        j_m = parse_out_json(out_m)
        fail.check(j_m.get("ok") is not True and "project" in out_m,
                   "缺 project 拒收且回执点名 project（rc=%s out=%s）"
                   % (rc_m, out_m.strip()[:100]))
        fail.check(out_m.strip() != out_u.strip(),
                   "两红因文案互辨（缺 project ≠ 未知 key，非同一句拒收）")

        # ---------- ⑦ 隔离断言：双台互不见对方工单 ----------
        _, list_a = run_poc_client(py, "ticket-list", {}, env_a)
        _, list_b = run_poc_client(py, "ticket-list", {}, env_b)
        fail.check(TID_A in list_a and TID_B not in list_a,
                   "台A ticket-list 只见本台工单（A in=%s B in=%s）"
                   % (TID_A in list_a, TID_B in list_a))
        fail.check(TID_B in list_b and TID_A not in list_b,
                   "台B ticket-list 只见本台工单（B in=%s A in=%s）"
                   % (TID_B in list_b, TID_A in list_b))
        p = subprocess.run([py, PROBE, "127.0.0.1:%d" % sb["ports"]["temporal"],
                            sb["namespace"], TID_A],
                           capture_output=True, text=True, timeout=60)
        cross = parse_out_json(p.stdout)
        fail.check(cross.get("found") is False,
                   "台B 上 describe 台A 工单=not found（零数据串台，reason=%s）"
                   % cross.get("reason"))

        # ---------- ⑧ 审计断言：零连生产 + 自证拦截腿 ----------
        for log_path, label in ((log_a, "台A腿"), (log_b, "台B腿")):
            hits = read_audit_jsonl(log_path)
            fail.check(not hits,
                       "%s 被测子进程零生产连接尝试（审计记录 %d 条：%s）"
                       % (label, len(hits), json.dumps(hits, ensure_ascii=False)[:120]))
        self_env = dict(os.environ)
        self_env.update(audit_env_a)
        self_env["SUYOU_AUDIT_SELFTEST"] = "1"
        p = subprocess.run([py, "-c",
                            "import socket; socket.create_connection(('127.0.0.1', 7233), timeout=2)"],
                           env=self_env, capture_output=True, text=True, timeout=30)
        self_hits = read_audit_jsonl(log_a)
        fail.check(p.returncode != 0 and any("7233" in json.dumps(h) for h in self_hits),
                   "审计钩子自证：故意连 7233 被阻断（rc=%s）且留记录（%d 条）——钩子活着，"
                   "上两条「零记录」才是真证据" % (p.returncode, len(self_hits)))

        # ---------- ⑨ teardown：零残留/幂等/可复用（docker 台语义） ----------
        proj_a_name, ns_a = sa["project"], sa["namespace"]
        d = stage_down(stage_docker, proj_a_name)
        fail.check(d.get("residue") == [],
                   "台A down 后零残留容器（实得 %s）" % (d.get("residue"),))
        released, held = wait_port_released(pa["temporal"])
        fail.check(released,
                   "台A temporal 端口已释放（10s 宽限窗；%s）"
                   % ("已释放" if released else
                      "仍被占用 pid=%s——拆台未回收需归因" % held))
        try:
            stage_down(stage_docker, proj_a_name)
            fail.check(True, "down 幂等二连不抛")
        except Exception as e:
            fail.check(False, "down 幂等二连不抛（实得异常：%s）" % e)
        # 同工程名+同 namespace 立即可 re-up（替代槽位制 flock 复抢/kill-9 腿：
        # docker 台无锁可崩——容器由 daemon 持有，取舍见 stage_docker 头注对照表）
        _, sa2 = require_stage(fail, proj_a_name, ns_a)
        fail.check(sa2["ports"]["temporal"] not in pb.values(),
                   "re-up 同工程名复用成功且端口不串在跑台B（实得 %s）" % sa2["ports"])
        stage_a = sa2  # finally 统一拆
    finally:
        for state in (stage_a, stage_b):
            if state is not None:
                try:
                    stage_docker.do_down(state["project"])
                except Exception:
                    pass
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
