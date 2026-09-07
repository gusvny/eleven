#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-02 场景①：工单专属 worker 进程生命周期——起/退/异常输入（工单正文行为 1）。

intent（守护的用户可感知行为）：
- 起：worker 起跑自报归属 meta（SANDBAR_WORKER_META 指路，JSON {version,pid,repo_root,ts}）
  限期可读且形状可辨——pid=真 pid、repo_root=realpath(引擎仓)、ts 可解析（KI-033
  契约的数据源面）；
- 退：SIGTERM → 限期优雅退出（退出码 0，非崩溃形态）、meta 自清（资源回收）、
  TERM 二连幂等不炸；
- 异常输入：SANDBAR_WORKER_META 指向不可写路径（父路径是文件）→ 写失败不阻断
  启动（shared.write_worker_meta best-effort 契约：写失败不阻断 worker 启动）、
  起跑痕迹可查（stderr 归属指纹行在文）、路径上不冒出 meta，TERM 后照常干净退。

intent 分工（防 intent 级重复）：
- t260904-02-worker-fingerprint-gate＝ensure 消费侧三态判定（同仓/异仓/未知）
  与异仓拒接；本条＝worker 进程侧自身生命周期（外部信号主动停）。「TERM 后
  meta 被清」一面两处观测（彼自 ensure 侧读、本条自进程侧验），登记两处不互替；
- t260905-02-ticket-worker-watch-exit＝watch 联动自退（worker 自己决定走），
  本条＝外部信号停（被叫走）。

三态契约：docker 台缺席=ENV_FAIL exit 2（require_stage 直译）；被测子进程零连
生产（审计钩子先记后抛+自证腿证明钩子活着）；断言全落公开行为输出（meta 文件/
进程终态/stderr 日志行），日志锚兼容正则锚语义不锁措辞（KI-051）。
"""
import json
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "t260904-02"))                    # lib_gate
sys.path.insert(0, os.path.dirname(_HERE))                                     # integration/（stage_docker）
sys.path.insert(0, _HERE)                                                      # lib_t26090502
from lib_gate import (Fail, cleanup, port_listening, poc_python,  # noqa: E402
                      read_audit_jsonl, require_bench, require_stage,
                      stage_down, wait_port_released)
import stage_docker  # noqa: E402
from lib_t26090502 import (KNOB, KNOB_FAST, child_env, close_logf,  # noqa: E402
                           pid_alive, spawn_worker, wait_exit, wait_marker)

TAG = "lc-%d" % os.getpid()
QUEUE = "suyou-ticket-t26090502-lc"  # naming-compat


def main():
    fail = Fail("t260905-02 ①worker 生命周期（起/退/异常输入）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26090502-lc-")
    stage_state = None
    workers = []
    try:
        # ---------- ① 起台（temporal-only；env 缺席=exit 2 直译） ----------
        _, state = require_stage(fail, "t26090502-%s" % TAG, "lc-%s" % TAG)
        stage_state = state
        host = "127.0.0.1:%d" % state["ports"]["temporal"]
        fail.check(port_listening(state["ports"]["temporal"]),
                   "舞台 temporal 探活（%s）" % host)
        fail.check(state["ports"]["temporal"] not in bench.PROD_PORTS,
                   "舞台端口不在生产禁区面（%d）" % state["ports"]["temporal"])

        audit_env, audit_log = bench.audit_hook_env(os.path.join(tmp, "audit"))
        meta = os.path.join(tmp, "worker-lc.meta")
        log1 = os.path.join(tmp, "worker-lc.log")

        # ---------- ② 起腿：meta 限期可读 + 形状可辨 ----------
        env1 = child_env(host, state["namespace"], audit_env,
                         {"SANDBAR_TASK_QUEUE": QUEUE, "SANDBAR_WORKER_META": meta,
                          KNOB: KNOB_FAST})
        w1 = spawn_worker(py, log1, env1)
        workers.append(w1)
        meta_body = None
        deadline = time.time() + 20
        while time.time() < deadline:
            if os.path.isfile(meta):
                try:
                    with open(meta, encoding="utf-8") as f:
                        meta_body = json.load(f)
                    break
                except Exception:
                    pass
            time.sleep(0.25)
        fail.check(meta_body is not None,
                   "起跑 meta 限期落盘可解析（≤20s，路径=%s）" % meta)
        if isinstance(meta_body, dict):
            fail.check(meta_body.get("pid") == w1.pid,
                       "meta.pid=真 pid（期望 %d 实得 %r）" % (w1.pid, meta_body.get("pid")))
            fail.check(meta_body.get("repo_root") == os.path.realpath(
                           os.path.join(_HERE, "..", "..")),
                       "meta.repo_root=realpath(引擎仓)（实得 %r）" % meta_body.get("repo_root"))
            fail.check(bool(meta_body.get("version")),
                       "meta.version 非空（实得 %r）" % meta_body.get("version"))
            try:
                float(meta_body.get("ts"))
                ok_ts = True
            except (TypeError, ValueError):
                ok_ts = False
            fail.check(ok_ts, "meta.ts 可解析为数值（实得 %r）" % meta_body.get("ts"))
        fail.check(wait_marker(log1, r"归属指纹", 10),
                   "起跑痕迹在文：stderr 含归属指纹行（语义锚）")

        # ---------- ③ 退腿：TERM 二连幂等 → 优雅退 + meta 自清 ----------
        fail.check(wait_marker(log1, r"worker 起来了", 40),
                   "worker 就绪在文（起来了标记，≤40s）再发信号——防信号早于处理装配")
        w1.terminate()
        time.sleep(0.3)
        if pid_alive(w1.pid):
            w1.terminate()  # 二连：优雅停进行中再收 TERM 必须幂等不炸
        fail.check(wait_exit(w1, 60), "SIGTERM 后限期退出（≤60s）")
        fail.check(w1.returncode == 0,
                   "退出码 0 非崩溃形态（实得 %s；负值=被信号杀）" % w1.returncode)
        fail.check(not os.path.exists(meta),
                   "优雅退后 meta 自清（%s 不在）" % meta)
        fail.check(wait_marker(log1, r"优雅停|优雅止|已优雅", 1),
                   "优雅停痕迹在文（stderr 语义锚）")
        close_logf(w1)

        # ---------- ④ 异常输入腿：meta 指向不可写路径（父路径是文件） ----------
        blocker = os.path.join(tmp, "blocker")
        with open(blocker, "w") as f:
            f.write("占用父路径的普通文件\n")
        bad_meta = os.path.join(blocker, "worker-lc.meta")  # 父是文件→mkdir/open 必败
        log2 = os.path.join(tmp, "worker-lc-badmeta.log")
        env2 = child_env(host, state["namespace"], audit_env,
                         {"SANDBAR_TASK_QUEUE": QUEUE, "SANDBAR_WORKER_META": bad_meta,
                          KNOB: KNOB_FAST})
        w2 = spawn_worker(py, log2, env2)
        workers.append(w2)
        fail.check(wait_marker(log2, r"归属指纹", 30),
                   "写失败不阻断：起跑照常推进（归属指纹行在文=痕迹可查）")
        fail.check(wait_marker(log2, r"worker 起来了", 40),
                   "写失败不阻断启动：worker 就绪（起来了标记在文）")
        time.sleep(2)
        fail.check(pid_alive(w2.pid), "meta 写失败后进程持续存活（best-effort 契约）")
        fail.check(not os.path.exists(bad_meta),
                   "不可写路径上不冒出 meta（%s 不在）" % bad_meta)
        w2.terminate()
        fail.check(wait_exit(w2, 60) and w2.returncode == 0,
                   "异常输入腿 TERM 后照常干净退（rc=%s）" % w2.returncode)
        close_logf(w2)

        # ---------- ⑤ 红线：被测子进程零连生产 + 审计钩子自证 ----------
        hits = read_audit_jsonl(audit_log)
        fail.check(not hits,
                   "被测 worker 子进程零生产连接尝试（审计记录 %d 条：%s）"
                   % (len(hits), json.dumps(hits, ensure_ascii=False)[:120]))
        self_env = dict(os.environ)
        self_env.update(audit_env)
        self_env["SANDBAR_AUDIT_SELFTEST"] = "1"
        import subprocess
        p = subprocess.run([py, "-c",
                            "import socket; socket.create_connection(('127.0.0.1', 7233), timeout=2)"],
                           env=self_env, capture_output=True, text=True, timeout=30)
        self_hits = read_audit_jsonl(audit_log)
        fail.check(p.returncode != 0 and any("7233" in json.dumps(h) for h in self_hits),
                   "审计钩子自证：故意连 7233 被阻断（rc=%s）且留记录（%d 条）——"
                   "钩子活着，上一条「零记录」才是真证据" % (p.returncode, len(self_hits)))

        # ---------- ⑥ teardown：拆台零残留 ----------
        d = stage_down(stage_docker, state["project"])
        stage_state = None
        fail.check(d.get("residue") == [],
                   "舞台 down 后零残留容器（实得 %s）" % (d.get("residue"),))
        released, held = wait_port_released(state["ports"]["temporal"])
        fail.check(released,
                   "舞台 temporal 端口已释放（%s）" %
                   ("已释放" if released else "仍被占用 pid=%s" % held))
    finally:
        for w in workers:
            if w is not None and w.poll() is None:
                try:
                    w.terminate()
                    w.wait(timeout=10)
                except Exception:
                    try:
                        w.kill()
                    except Exception:
                        pass
            close_logf(w)
        if stage_state is not None:
            try:
                stage_docker.do_down(stage_state["project"])
            except Exception:
                pass
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
