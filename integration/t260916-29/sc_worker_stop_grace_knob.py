#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-29 场景①：worker 停机 grace 旋钮契约——经真实 worker.py 进程面（灰盒 L3）。

intent（守护的用户可感知行为；工单要求①「值可配置＋取值需能覆盖到至少让活动
干净结束或明确中断」）：worker 停机宽限不再是无旋钮硬编码 0（=立即取消在飞活动，
260916 两轮全票假「agent 活动故障」的第一现场），而是一个可配置、容错、可显式
关断的运维旋钮，且旋钮值真的到达 SDK 停机路径：

- 子用例1（缺省）：不设旋钮 → SIGTERM → SDK 停机日志「will wait <非0>」（缺省宽限
  覆盖 agent 段量级；具体秒数不锁死——钉「非 0」不钉 1800，调参不破测试）；
  停机点名行在文（在飞活动点名面的空表形态：本子用例零在飞，点名行存在即契约面在场）；
- 子用例2（显式 0=逃生门）：SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC=0 → will wait 0:00:00
  ——立即取消语义保留为运维显式选择（不再是不讲理的唯一行为）；
- 子用例3（畸形三值容错）：abc / -5 / NaN → 不炸启动、不采信畸形 → 回缺省非 0
  （消费外部输入三态纪律：畸形不炸不采信；解析矩阵细节归 developer UT 不同层）；
- 子用例4（显式值透传）：=2 → will wait 0:00:02——旋钮→Worker 接线的端到端证明
  （helper 级 UT 断言不了调用点真的把 kwargs 展开进 Worker(...)，这正是本票
  缺陷的原始形态：helper 在、接线缺）。

intent 分工（防 intent 级重复）：
- t260905-02-worker-lifecycle＝worker 进程生命周期（起/退/meta/异常输入，TERM 后
  干净退），不涉 grace 取值；本条＝停机宽限的取值契约面（彼条的 TERM 干净退本条
  每子用例顺带守卫，不互替）；
- t260916-29-console-crash-graceful-stop（本票场景②）＝console 崩溃收养路的 grace
  语义（ppid 守卫自退路）；本条＝直接信号路的旋钮矩阵；
- developer 侧引擎 selfcheck（方案场景A/B，进程内桩 activity）＝grace 对「在飞
  活动」的实际效果（活动收尾/取消归因/重跑兜底）——零模型 L3 起不了真 agent 段，
  彼面归引擎侧台；本条只钉「取值经真实进程到达 SDK」的公开日志契约（工单取证
  日志逐字来源=SDK 公开日志，KI-051 正则锚）。

三态契约：docker 台缺席/测试镜像缺席/起台不健康=ENV_FAIL exit 2（require_stage
直译）。实现落地前全部子用例红属预期（TDD 信号：现码恒 will wait 0:00:00），
arbitrate/merge 期必须绿。被测子进程零连生产（审计钩子护体+自证子用例）；
日志锚兼容正则锚语义（KI-051）。
"""
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "t260904-02"))                    # lib_gate
sys.path.insert(0, os.path.join(_HERE, "..", "t260905-02"))                    # lib_t26090502
sys.path.insert(0, os.path.dirname(_HERE))                                     # integration/
sys.path.insert(0, _HERE)                                                      # lib_t26091629
from lib_gate import (Fail, poc_python, read_audit_jsonl, require_bench,  # noqa: E402
                      require_stage, stage_down, wait_port_released)
import stage_docker  # noqa: E402
from lib_t26090502 import (child_env, close_logf, spawn_worker, stderr_text,  # noqa: E402
                           wait_exit, wait_marker)
from lib_t26091629 import BOOT_RX, GRACE_RX, NAMED_RX, grace_seconds  # noqa: E402

TAG = "knob-%d" % os.getpid()
KNOB_NAME = "SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"  # 本票方案定稿的运维旋钮名（公开契约）


def main():
    fail = Fail("t260916-29 ①worker 停机 grace 旋钮契约（缺省/逃生门/畸形/透传）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26091629-knob-")
    stage_state = None
    procs = []
    audit_env = audit_log = None
    try:
        # ---------- ① 起台 ----------
        _, state = require_stage(fail, "t26091629-%s" % TAG, "knob-%s" % TAG)
        stage_state = state
        host = "127.0.0.1:%d" % state["ports"]["temporal"]
        fail.check(state["ports"]["temporal"] not in bench.PROD_PORTS,
                   "舞台端口不在生产禁区面（%d）" % state["ports"]["temporal"])
        audit_env, audit_log = bench.audit_hook_env(os.path.join(tmp, "audit"))

        def stop_leg(tag, extra=None, check_named=False):
            """起真 worker → 起跑痕迹 → SIGTERM → 限期干净退 → 返回解析的 grace 秒数。

            extra＝逐子用例附加 env（旋钮值）；票队列指空队列＝零活动领取面。"""
            log = os.path.join(tmp, "log-%s.txt" % tag)
            env = child_env(host, state["namespace"], audit_env,
                            {"SANDBAR_TASK_QUEUE": "sandbar-ticket-t26091629-%s" % tag})
            env.update(extra or {})
            w = spawn_worker(py, log, env)
            procs.append(w)
            if not fail.check(wait_marker(log, BOOT_RX, 60),
                              "子用例%s：worker 起跑（起跑日志在文）" % tag):
                return None
            w.terminate()
            ok = wait_exit(w, 60)
            if not fail.check(ok and w.returncode == 0,
                              "子用例%s：TERM 限期干净退（rc=%s）" % (tag, w.returncode)):
                return None
            close_logf(w)
            text = stderr_text(log)
            g = grace_seconds(text)
            m = GRACE_RX.search(text)
            fail.check(g is not None,
                       "子用例%s：SDK 停机日志 will-wait 在文（%s）"
                       % (tag, m.group(1) if m else "缺"))
            if check_named:
                fail.check(NAMED_RX.search(text) is not None,
                           "子用例%s：停机点名行在文（在飞活动点名面，空表形态）" % tag)
            return g

        # ---------- ② 子用例1 缺省：非 0 + 停机点名行 ----------
        g1 = stop_leg("default", check_named=True)
        if g1 is not None:
            fail.check(g1 > 0,
                       "子用例1：缺省 grace 非 0（实得 %ss）——立即取消不再是唯一行为" % g1)

        # ---------- ③ 子用例2 显式 0＝逃生门 ----------
        g2 = stop_leg("zero", {KNOB_NAME: "0"})
        if g2 is not None:
            fail.check(g2 == 0,
                       "子用例2：显式 0 透传为立即取消（实得 %ss）——逃生门保留" % g2)

        # ---------- ④ 子用例3 畸形三值容错 ----------
        for bad in ("abc", "-5", "NaN"):
            gb = stop_leg("bad-%s" % bad, {KNOB_NAME: bad})
            if gb is not None:
                fail.check(gb > 0,
                           "子用例3（%s）：畸形不炸不采信，回缺省非 0（实得 %ss）" % (bad, gb))

        # ---------- ⑤ 子用例4 显式值透传 ----------
        g4 = stop_leg("two", {KNOB_NAME: "2"})
        if g4 is not None:
            fail.check(g4 == 2,
                       "子用例4：旋钮值=2 透传 SDK（实得 %ss）——接线端到端证明" % g4)

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
    fail.finish()


if __name__ == "__main__":
    main()
