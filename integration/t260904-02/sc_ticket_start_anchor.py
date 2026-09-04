#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-02 场景①：裸入口开票硬闸 + 隔离台并发隔离端到端（epic 验收 1/4/5）。

intent（守护的用户可感知行为）：
- 裸 client.py ticket-start 带 project → 落在 Temporal 里的工单 payload
  workspace.path 为绝对路径且锚 <注册项目主目录>/.lane/（worktree 同锚）——
  落仓不再由执行 worker 的 REPO_ROOT 决定（KI-032 修复回归）；
- 缺 project / 未知 project key = 创建即拒收，两条红因文案互辨（不静默相对路径）；
- 双槽隔离台两路并发开票（时间重叠）：ticket-list 互不见对方工单、跨槽 describe
  not_found —— 零数据串台（宿主红线①）；
- 被测子进程零连生产 7233/8233（审计钩子先记后抛=连接被阻断；含自证拦截腿证明
  钩子活着）+ temporalite 三端口（frontend/UI/metrics）显式起动断言（UI 默认
  =--port+1000 暗雷面）——绝不影响生产 temporal（宿主红线②）；
- teardown：槽 db/日志全清、lock 文件保留（槽锚）、端口释放、stop 幂等二连、
  kill -9 后 flock 崩溃自释可复抢（资源回收对抗面）。

bench 契约面见 lib_gate.py 头注（require_bench 为对齐真源；缺失=exit2 MISSING）。
红线：本场景自身绝不 connect 生产端口（探活只打槽端口）；不 touch 3099。
"""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_gate import (Fail, cleanup, parse_out_json, port_listening,  # noqa: E402
                      poc_python, read_audit_jsonl, require_bench,
                      run_poc_client, check_slot_contract, wait_port_released)

TID_A = "t26090402-anchor-a"
TID_B = "t26090402-anchor-b"
PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_wf_input.py")


def slot_env(bench, slot, registry_dir, audit_env):
    """被测 client 子进程 env：连槽 fe/槽 namespace/槽注册表/审计钩子。"""
    env = dict(os.environ)
    env["SUYOU_TARGET_HOST"] = "127.0.0.1:%d" % slot.frontend_port
    env["SUYOU_NAMESPACE"] = slot.namespace
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
    sa = sb = None
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
            bench.assert_not_production("127.0.0.1:19101")
            slot_ok = True
        except Exception as e:
            slot_ok = False
            fail.check(False, "槽端口基址须过生产守卫（实得异常：%s）" % e)
        if slot_ok:
            fail.check(True, "生产守卫放行槽端口基址（fail-closed 不误伤隔离台）")

        # ---------- ② 抢双槽 + 起 temporalite ----------
        sa = bench.acquire_slot()
        sb = bench.acquire_slot()
        for s, label in ((sa, "槽A"), (sb, "槽B")):
            check_slot_contract(fail, s, label)
        fail.check(sa.index != sb.index, "双槽下标互异（实得 %s/%s）" % (sa.index, sb.index))
        for s in (sa, sb):
            s.start_temporalite()
        for s, label in ((sa, "槽A"), (sb, "槽B")):
            for attr, name in (("frontend_port", "frontend"), ("ui_port", "UI"),
                               ("metrics_port", "metrics")):
                p = getattr(s, attr)
                fail.check(port_listening(p), "%s %s 端口 %d 探活" % (label, name, p))
            for pp in bench.PROD_PORTS:
                fail.check((getattr(s, "frontend_port"), getattr(s, "ui_port"),
                            getattr(s, "metrics_port")).count(pp) == 0,
                           "%s 三端口不含生产端口 %d" % (label, pp))

        # ---------- ③ temporalite 三端口显式起动断言（UI 暗雷面） ----------
        for s, label in ((sa, "槽A"), (sb, "槽B")):
            argv_txt = " ".join(str(x) for x in (s.argv or []))
            fail.check(("--port %d" % s.frontend_port) in argv_txt
                       and ("--ui-port %d" % s.ui_port) in argv_txt
                       and ("--metrics-port %d" % s.metrics_port) in argv_txt,
                       "%s temporalite 三端口全部显式（实得 argv：%s）" % (label, argv_txt[:160]))

        # ---------- ④ fixture 注册表（每槽独立项目主目录） ----------
        proj_a = os.path.join(tmp, "proj-a"); proj_b = os.path.join(tmp, "proj-b")
        os.makedirs(proj_a, exist_ok=True); os.makedirs(proj_b, exist_ok=True)
        reg_a = bench.write_registry(os.path.join(tmp, "reg-a"), "bench-anchor-a", proj_a)
        reg_b = bench.write_registry(os.path.join(tmp, "reg-b"), "bench-anchor-b", proj_b)

        # ---------- ⑤ 审计钩子 + 两路并发开票（时间重叠） ----------
        audit_env_a, log_a = bench.audit_hook_env(os.path.join(tmp, "audit-a"))
        audit_env_b, log_b = bench.audit_hook_env(os.path.join(tmp, "audit-b"))
        env_a = slot_env(bench, sa, reg_a, audit_env_a)
        env_b = slot_env(bench, sb, reg_b, audit_env_b)
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

        # ---------- ⑥ payload 锚定断言（KI-032 修复回归主断言） ----------
        import subprocess
        for tid, slot, proj, env, label in ((TID_A, sa, proj_a, env_a, "槽A"),
                                            (TID_B, sb, proj_b, env_b, "槽B")):
            p = subprocess.run([py, PROBE, "127.0.0.1:%d" % slot.frontend_port,
                                slot.namespace, tid],
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

        # ---------- ⑦ 负向：缺 project / 未知 key 拒收且红因互辨 ----------
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

        # ---------- ⑧ 隔离断言：双槽互不见对方工单 ----------
        _, list_a = run_poc_client(py, "ticket-list", {}, env_a)
        _, list_b = run_poc_client(py, "ticket-list", {}, env_b)
        fail.check(TID_A in list_a and TID_B not in list_a,
                   "槽A ticket-list 只见本槽工单（A in=%s B in=%s）"
                   % (TID_A in list_a, TID_B in list_a))
        fail.check(TID_B in list_b and TID_A not in list_b,
                   "槽B ticket-list 只见本槽工单（B in=%s A in=%s）"
                   % (TID_B in list_b, TID_A in list_b))
        p = subprocess.run([py, PROBE, "127.0.0.1:%d" % sb.frontend_port,
                            sb.namespace, TID_A],
                           capture_output=True, text=True, timeout=60)
        cross = parse_out_json(p.stdout)
        fail.check(cross.get("found") is False,
                   "槽B 上 describe 槽A 工单=not found（零数据串台，reason=%s）"
                   % cross.get("reason"))

        # ---------- ⑨ 审计断言：零连生产 + 自证拦截腿 ----------
        for log_path, label in ((log_a, "槽A腿"), (log_b, "槽B腿")):
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

        # ---------- ⑩ teardown：全清/幂等/复抢/崩溃自释 ----------
        idx_a, lock_a = sa.index, sa.lock_path
        for s in (sa, sb):
            s.stop()
        for s, label in ((sa, "槽A"), (sb, "槽B")):
            fail.check(not os.path.exists(s.db_path), "%s 槽 db 已清" % label)
            remain = sorted(os.listdir(s.slot_dir)) if os.path.isdir(s.slot_dir) else []
            fail.check(remain == [os.path.basename(s.lock_path)],
                       "%s 槽目录仅剩 lock 槽锚（实得 %s）" % (label, remain))
            released, held = wait_port_released(s.frontend_port)
            fail.check(released,
                       "%s frontend 端口已释放（10s 宽限窗；%s）"
                       % (label, "已释放" if released else
                          "仍被占用 pid=%s——teardown 未回收，bench 拆解缺陷需归因" % held))
        fail.check(os.path.isfile(lock_a), "lock 槽锚文件保留（flock 不因 unlink 假独占）")
        try:
            sa.stop()
            fail.check(True, "stop 幂等二连不抛")
        except Exception as e:
            fail.check(False, "stop 幂等二连不抛（实得异常：%s）" % e)
        # 钉自己槽复抢（t260904-09 仲裁修正）：跨池并行下他池可能占其它槽，
        # any-slot 断言（in (sa.index, sb.index)）会误红——契约是「teardown 后本槽可复抢」
        again = bench.acquire_slot(index=idx_a)
        fail.check(again.index == idx_a, "teardown 后本槽立即可复抢（index=%s，期望 %s）" % (again.index, idx_a))
        again.stop()

        # 崩溃自释：kill -9 temporalite → flock 随进程消亡自释 → 同槽可复抢
        sc = bench.acquire_slot(index=idx_a)
        sc.start_temporalite()
        pid = sc.temporalite_pid
        fail.check(isinstance(pid, int) and pid > 0, "崩溃腿：槽持有 pid 可观测（%r）" % (pid,))
        if isinstance(pid, int) and pid > 0:
            import signal
            os.kill(pid, signal.SIGKILL)
            time.sleep(1.0)
            try:
                sc2 = bench.acquire_slot(index=idx_a, deadline_s=5)
                sc2.stop()
                fail.check(True, "kill -9 后 flock 崩溃自释、同槽立即可复抢")
            except Exception as e:
                fail.check(False, "kill -9 后同槽复抢失败（锁未自释？%s）" % e)
        else:
            sc.stop()
    finally:
        for s in {id(x): x for x in (sa, sb) if x is not None}.values():
            try:
                s.stop()
            except Exception:
                pass
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
