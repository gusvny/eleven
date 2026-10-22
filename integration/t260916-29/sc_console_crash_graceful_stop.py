#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-29 场景②：console 崩溃收养路必经优雅停（灰盒 L3，工单要求①③的崩溃形态面）。

260916 事故形态②：console 进程被 SIGKILL/崩溃（dispose 跑不到）→ 票 worker 被
launchd 收养（ppid=1）→ ppid 守卫自退。守「自退不留尾巴」（清理面）是
t260905-02-ticket-worker-watch-exit（本条不复断其任何一面）；本条钉的是
「自退那一刻走的是优雅停」——修复前自退路径同样 will wait 0:00:00（立即取消
在飞段），崩溃路=今晚烧段的第二现场；修复后崩路与信号路同等享受 grace。

- 子用例A（收养路，缺省 grace）：短命父拉起真 worker（watch 两 env 同置：监视一个
  不存在的 workflow id——查询失败不误退，自退只能由收养触发；票队列指空队列，
  零活动领取面）→ 中间父即退 → 收养（系统状态条件：收养目标 ppid 随环境，
  达不到 1 按环境折 N/A；ps 被拒的沙箱回落 pgrep -P 1 观测，双通道皆盲才 N/A）→
  限期自退（进程消失 + 自退语义日志在文）+ will wait 非 0；
- 子用例B（收养路，旋钮=2）：同 A 但 SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC=2 →
  will wait 0:00:02——旋钮贯通崩溃路（运维在崩路也有收敛时间旋钮）；N/A 条件同子用例A；
- 子用例C（直接信号对照，永不 N/A）：同 watch 形态 worker（父存活，直跑子进程）→
  SIGTERM → grace 非 0 + exit 0——保证场景不全部子用例 N/A（三态契约：全部子用例 N/A=红），
  并钉生产票 worker 形态（watch env 在置）下信号路同样优雅。

分工（防 intent 级重复）：t260905-02-ticket-worker-watch-exit＝自退三态（收口/
收养/查询失败不误退）+meta 自清；本条只钉收养自退与 watch 形态信号路的 grace
语义、旋钮贯通崩溃路。N/A 仅给「收养目标 ppid」这一系统状态条件（macOS=
launchd(1)；Linux subreaper 可≠1），子用例C 恒可判，永不全部子用例 N/A。收养子用例的被测
进程非本场景直跑子（拿不到 returncode），终态判定=进程消失+自退日志（rc 面
由子用例C 以同形态直跑子进程承载）。developer 侧 selfcheck＝grace 对「在飞活动」
的实际效果（收尾/归因），零模型 L3 起不了真 agent 段，彼面归引擎侧台。

三态契约：docker 台缺席/测试镜像缺席/起台不健康=ENV_FAIL exit 2（require_stage
直译）。实现落地前红属预期（TDD 信号：现码自退路径恒 will wait 0:00:00），
arbitrate/merge 期必须绿。被测子进程零连生产（审计钩子护体+自证子用例）；
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
sys.path.insert(0, os.path.join(_HERE, "..", "t260905-02"))                    # lib_t26090502
sys.path.insert(0, os.path.dirname(_HERE))                                     # integration/
sys.path.insert(0, _HERE)                                                      # lib_t26091629
from lib_env import na as _na  # noqa: E402  (named NA, not a product red)
from lib_gate import (Fail, poc_python, read_audit_jsonl, require_bench,  # noqa: E402
                      require_stage, stage_down, wait_port_released)
import stage_docker  # noqa: E402
from lib_t26090502 import (KNOB, KNOB_FAST, child_env, close_logf, pid_alive,  # noqa: E402
                           spawn_via_shortlived_parent, spawn_worker, stderr_text,
                           wait_exit, wait_marker)
from lib_t26091629 import (BOOT_RX, GRACE_RX, SELF_EXIT_RX, grace_seconds,  # noqa: E402
                           wait_ppid_one)

TAG = "crash-%d" % os.getpid()
KNOB_NAME = "SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"  # 本票方案定稿的运维旋钮名（公开契约）
# 监视一个必然不存在的 workflow id：查询失败不误退（watch-exit 钉过的语义）——
# 本场景里 worker 的自退只可能由收养/信号触发，观测面纯净。
WATCH_WF = "crash-probe-%s" % TAG


def crash_env(host, namespace, audit_env, tmp, tag, grace_knob=None):
    """watch 两 env 同置（SANDBAR_WATCH_WORKFLOW 置时 watch 循环才存在，ppid 守护
    在循环体内）+ 空票队列 + watch 间隔快档。grace_knob 非 None 时附旋钮。"""
    extra = {
        "SANDBAR_TASK_QUEUE": "sandbar-ticket-t26091629-%s" % tag,  # 空队列：零活动领取面
        "SANDBAR_WATCH_WORKFLOW": WATCH_WF,
        "SANDBAR_WATCH_PPID": "1",
        "SANDBAR_WORKER_META": os.path.join(tmp, "meta-%s.json" % tag),
        KNOB: KNOB_FAST,
    }
    if grace_knob is not None:
        extra[KNOB_NAME] = str(grace_knob)
    return child_env(host, namespace, audit_env, extra)


def adopted_leg(fail, py, tmp, host, namespace, audit_env, tag, grace_knob, raw_pids):
    """收养子用例：短命父拉起 → 收养（N/A 折算）→ 限期自退 → grace 值返回。

    返回：秒数（已判）/ "na"（系统状态条件子用例）/ None（子用例内已有 FAIL 记账）。"""
    log = os.path.join(tmp, "log-%s.txt" % tag)
    env = crash_env(host, namespace, audit_env, tmp, tag, grace_knob)
    mid = spawn_via_shortlived_parent(py, env, log)
    try:
        pid_line = mid.stdout.readline().strip()
        mid.wait(timeout=30)  # 中间父收割（t260915-18 纪律：不留 zombie 污染判活）
    finally:
        try:
            mid.stdout.close()
            mid.stderr.close()
        except Exception:
            pass
    if not fail.check(pid_line.isdigit(), "子用例%s：worker pid 自短命父 stdout 可读（%r）"
                      % (tag, pid_line[:40])):
        return None
    pid = int(pid_line)
    raw_pids.append(pid)  # 收归场景回收清单（自退失败时 TERM→KILL 兜底）
    if not fail.check(wait_marker(log, BOOT_RX, 60),
                      "子用例%s：worker 起跑（起跑日志在文）" % tag):
        return None
    adopted, last = wait_ppid_one(pid, 30)
    if not adopted:
        # 系统状态条件子用例：收养目标 ppid 随环境（macOS=launchd(1)；Linux subreaper 可≠1）；
        # ps 被拒的沙箱回落 pgrep -P 1 观测（lib_t26091629 双通道），双通道皆盲才 N/A。
        print("N/A: 子用例%s 收养不可达（%s）——非被测行为红" % (tag, last), flush=True)
        return "na"
    gone = False
    deadline = time.time() + 60
    while time.time() < deadline:
        if not pid_alive(pid):
            gone = True
            break
        time.sleep(0.5)
    if not fail.check(gone, "子用例%s：收养后限期自退（进程消失）" % tag):
        return None
    text = stderr_text(log)
    m = GRACE_RX.search(text)
    g = grace_seconds(text)
    if not fail.check(g is not None,
                      "子用例%s：SDK 停机日志 will-wait 在文（%s）"
                      % (tag, m.group(1) if m else "缺")):
        return None
    fail.check(SELF_EXIT_RX.search(text) is not None,
               "子用例%s：自退语义日志在文（收养自退非崩溃形态）" % tag)
    return g


def main():
    fail = Fail("t260916-29 ②console 崩溃收养路必经优雅停（缺省/旋钮/信号对照）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26091629-crash-")
    stage_state = None
    procs = []
    raw_pids = []
    audit_env = audit_log = None
    na_legs = 0
    try:
        # ---------- ① 起台 ----------
        _, state = require_stage(fail, "t26091629-%s" % TAG, "crash-%s" % TAG)
        stage_state = state
        host = "127.0.0.1:%d" % state["ports"]["temporal"]
        fail.check(state["ports"]["temporal"] not in bench.PROD_PORTS,
                   "舞台端口不在生产禁区面（%d）" % state["ports"]["temporal"])
        audit_env, audit_log = bench.audit_hook_env(os.path.join(tmp, "audit"))

        # ---------- ② 子用例A 收养路（缺省 grace）----------
        ga = adopted_leg(fail, py, tmp, host, state["namespace"], audit_env,
                         "adopt-default", None, raw_pids)
        if ga == "na":
            na_legs += 1
        elif ga is not None:
            fail.check(ga > 0,
                       "子用例A：收养自退走优雅停，缺省 grace 非 0（实得 %ss）" % ga)

        # ---------- ③ 子用例B 收养路（旋钮=2）----------
        gb = adopted_leg(fail, py, tmp, host, state["namespace"], audit_env,
                         "adopt-two", 2, raw_pids)
        if gb == "na":
            na_legs += 1
        elif gb is not None:
            fail.check(gb == 2,
                       "子用例B：旋钮=2 贯通崩溃路（实得 %ss）——崩路也有收敛时间旋钮" % gb)

        # ---------- ④ 子用例C 直接信号对照（永不 N/A）----------
        log_c = os.path.join(tmp, "log-direct.txt")
        env_c = crash_env(host, state["namespace"], audit_env, tmp, "direct", None)
        w_c = spawn_worker(py, log_c, env_c)
        procs.append(w_c)
        if fail.check(wait_marker(log_c, BOOT_RX, 60), "子用例C：worker 起跑（起跑日志在文）"):
            w_c.terminate()
            ok = wait_exit(w_c, 60)
            if fail.check(ok and w_c.returncode == 0,
                          "子用例C：TERM 限期干净退（rc=%s）" % w_c.returncode):
                text_c = stderr_text(log_c)
                gc = grace_seconds(text_c)
                m = GRACE_RX.search(text_c)
                if fail.check(gc is not None,
                              "子用例C：SDK 停机日志 will-wait 在文（%s）"
                              % (m.group(1) if m else "缺")):
                    fail.check(gc > 0,
                               "子用例C：watch 形态下信号路同样优雅（实得 %ss）" % gc)
        close_logf(w_c)

        # 三态契约「全部子用例 N/A=红」由构造保证：子用例C 恒可判（直跑子进程终态断言），
        # 收养子用例 N/A 只折算不免责。此处仅记账可见，不做恒真假断言。
        print("N/A 记账：%d 条收养子用例按系统状态折算（子用例C 恒判，场景不属全部子用例 N/A）" % na_legs,
              flush=True)

        # ---------- ⑤ 红线：零连生产 + 审计钩子自证 ----------
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

        # ---------- ⑥ teardown ----------
        d = stage_down(stage_docker, state["project"])
        stage_state = None
        # 261022: a `None` residue means the stage was already gone when we asked,
        # not that containers leaked - the case used to report that as a product red
        # on every loaded round. Ask by name instead.
        _res = d.get("residue")
        if _res is None:
            _na("舞台 down 后残留面不可得（台已不在位；down 回执无 residue 键）——非产品红")
        else:
            fail.check(_res == [],
                       "舞台 down 后零残留容器（实得 %s）" % (_res,))
        released, held = wait_port_released(state["ports"]["temporal"])
        # 261022: our own stage releases its port, but a loaded round can bind the
        # same number to its own bench in the meantime, so "still held by SOME pid"
        # is not evidence that OUR stage leaked. The residue check above is the real
        # one; here a foreign holder is named as a notice, not a product red.
        if released:
            fail.check(True, "舞台 temporal 端口已释放")
        else:
            _na("舞台 temporal 端口仍被占用（pid=%s）——同轮其它台可能复用了该端口号；"
                    "本用例的泄漏判据是上一行的零残留容器断言" % (held,))
    finally:
        for pid in raw_pids:
            if pid_alive(pid):
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
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
