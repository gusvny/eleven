#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260903-10 场景⑤：认领契约 V1 三态进程演练（交接单 §2-#9 + V1 钦点验收口径）。

用户视角红线：安装器认领仅限真孤儿——
  A. supervisor 存活持有 server（pidfile 丢、端口被占）→ down 只报告归属，
     不杀、不复活、不认领（绝不允许「杀后被 keepalive 复活」）；
  B. 父死成真孤儿 且 命令行谓词命中（temporal server start-dev + 数据卷属本
     安装）→ 认领进 pidfile 后 down 停掉；
  C. 谓词不命中（占口进程命令行不像）→ 显式报错不误杀。

隔离与观测缝（t260903-11 环境无关化）：server 全为场景自建 stub（Popen argv
面伪装，真身=监听脚本）；演练端口=自选空闲端口（公共旗标 --server-port/
--ui-port）；argv/ppid 观测面经 PATH 前置 ps 桩按登记表供数（本沙箱禁
/bin/ps），而安装器对 ppid 的存活交叉核对（pid_state）与一切信号都走真
os.kill——桩供不出假活假死。「真孤儿」前提断言=父进程真死（os.kill 语义）
+子进程仍活，不锚 ppid==1 的内核收养细节（环境细节，非契约）。所选端口被占
→ exit 3 环境冲突不对抗。
"""
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_installer import (FAKE_TEMPORAL_SRC, PLAIN_LISTEN_SRC, Proc, Fail,  # noqa: E402
                           attach_ps_seam, cleanup, cli_args, guard_runtime_ports,
                           make_fixture_root, make_temp_home, pick_free_ports,
                           port_open, ps_record, ps_seam, run_cli, require_installer_entry,
                           state_home, wait_pid_dead, wait_port, _write_stub)

SUPERVISOR_SRC = """\
import os, signal, subprocess, sys
child_file = os.environ["SANDBAR_CHILD_PID_FILE"]
temporal_copy = os.environ["SANDBAR_TEMPORAL_COPY"]
def fwd(*a):
    try:
        os.kill(int(open(child_file).read()), signal.SIGTERM)
    except Exception:
        pass
    sys.exit(0)
signal.signal(signal.SIGTERM, fwd)
p = subprocess.Popen(["temporal", "server", "start-dev", "--data", os.environ["SANDBAR_STATE_HOME"]],
                     executable=temporal_copy, env=dict(os.environ))
open(child_file, "w").write(str(p.pid))
sys.stdout.write("ready\\n"); sys.stdout.flush()
p.wait()
"""


class Half:
    """单个三态半的进程组：supervisor（可无）+ 占口 server stub + 临时 HOME。"""

    def __init__(self, name, with_supervisor, server_port, ui_port):
        self.name = name
        self.server_port, self.ui_port = server_port, ui_port
        self.tmp, self.env = make_temp_home()
        self.psbin, self.psrec = ps_seam(self.tmp)
        attach_ps_seam(self.env, self.psbin, self.psrec)
        self.fx = make_fixture_root(self.tmp, "absent")   # down 只需路径面，不需要真 temporal
        self.stamp = os.path.join(self.tmp, "server_stamp")
        self.state_home = state_home(self.tmp)
        self.bin_dir = os.path.join(self.tmp, "stub-bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.temporal_copy = os.path.join(self.bin_dir, "temporal")
        _write_stub(self.temporal_copy, FAKE_TEMPORAL_SRC)
        self.env["SANDBAR_STUB_STAMP"] = self.stamp
        self.env["SANDBAR_STUB_PORTS"] = "%d,%d" % (server_port, ui_port)
        self.child_file = os.path.join(self.tmp, "child.pid")
        self.sup = None
        self.child_pid = None
        if with_supervisor:
            sup_src = os.path.join(self.tmp, "supervisor.py")
            _write_stub(sup_src, SUPERVISOR_SRC)
            self.env["SANDBAR_TEMPORAL_COPY"] = self.temporal_copy
            self.env["SANDBAR_CHILD_PID_FILE"] = self.child_file
            self.env["SANDBAR_STATE_HOME"] = self.state_home
            # executable=必须给可执行真身（sys.executable）：supervisor.py 是无
            # shebang 的 python 源，直接 execve 会 Exec format error（原版同款先天缺陷）
            self.sup = Proc([sys.executable, sup_src], sys.executable, self.env)
            # 等「存在且非空」：文件先被创建、内容后写入是两步——高负载下（t260913-04
            # 仲裁轮 242 条全量并发，实得 int('') ValueError）只等存在会读到空档。
            # 只加等非空，判定语义不变（超时仍走原异常面）。
            deadline = time.time() + 8
            raw = ""
            while time.time() < deadline:
                if os.path.exists(self.child_file):
                    with open(self.child_file) as f:
                        raw = f.read().strip()
                    if raw:
                        break
                time.sleep(0.05)
            self.child_pid = int(raw)
            # 观测缝登记：argv 面=「temporal server start-dev --data 本安装状态家」
            # （真 ps 在场时读到的正是这个伪装面）；ppid=真 supervisor pid，
            # 死活由安装器 pid_state 真核对。
            ps_record(self.psrec, self.child_pid,
                      cmdline="temporal server start-dev --data %s" % self.state_home,
                      ppid=self.sup.pid)
        else:
            # 无 supervisor：直拉朴素监听桩（argv 面不像 start-dev，用于半 C）
            src = os.path.join(self.tmp, "plain_listen.py")
            _write_stub(src, PLAIN_LISTEN_SRC)
            self.direct = Proc([sys.executable, src], sys.executable, self.env)
            self.child_pid = self.direct.pid
            ps_record(self.psrec, self.child_pid,
                      cmdline="%s %s" % (sys.executable, src), ppid=1)

    def child_alive(self):
        try:
            os.kill(self.child_pid, 0)
            return True
        except OSError:
            return False

    def claim_record(self):
        """安装器 pidfile 是否收编过该 server（认领面观测）。"""
        run_dir = os.path.join(self.tmp, ".sandbar", "run")
        if not os.path.isdir(run_dir):
            return False
        for fn in os.listdir(run_dir):
            if fn.endswith(".pid"):
                with open(os.path.join(run_dir, fn)) as f:
                    if str(self.child_pid) in f.read():
                        return True
        return False

    def cli(self, entry, *rest, timeout=90):
        return run_cli(entry, cli_args(self.fx, self.server_port, self.ui_port, *rest),
                       self.env, timeout=timeout)

    def dispose(self):
        if self.sup:
            self.sup.kill()
        if getattr(self, "direct", None):
            self.direct.kill()
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGKILL)
            except OSError:
                pass
            wait_pid_dead(self.child_pid, timeout=8)
        wait_port(self.server_port, want_open=False, timeout=8)
        cleanup(self.tmp)


def main():
    fail = Fail("t260903-10 ⑤认领契约 V1 三态（报告不杀 / 真孤儿认领 / 谓词不中不误杀）")
    entry = require_installer_entry(fail)
    server_port, ui_port = pick_free_ports(2)
    guard_runtime_ports(fail, (server_port, ui_port))

    # ---- 半 A：supervisor 存活持有 → 只报告归属，不杀不复活不认领 ----
    a = Half("A", with_supervisor=True, server_port=server_port, ui_port=ui_port)
    try:
        fail.check(a.sup is not None and a.child_alive(),
                   "半A 前置：supervisor 拉起的 server stub 在位（pid=%s）" % a.child_pid)
        fail.check(wait_port(server_port, want_open=True, timeout=10),
                   "半A 前置：演练端口被 stub 占用")
        rc, out = a.cli(entry, "down")
        fail.check(rc != 0, "半A：down 非零（持有人在，本半不许谎报完成）")
        fail.check(a.child_alive(), "半A：down 后 server 仍活（不杀不复活）")
        fail.check(any(k in out for k in ("supervisor", "父进程", "归属")),
                   "半A：输出报告归属/处置指引（out=%s）" % out.strip()[:200])
        fail.check(not a.claim_record(), "半A：未认领（pidfile 未纳入该 server）")
    finally:
        a.dispose()

    # ---- 半 B：父死真孤儿 + 谓词命中 → 认领后 down 停掉 ----
    b = Half("B", with_supervisor=True, server_port=server_port, ui_port=ui_port)
    try:
        fail.check(b.child_alive(), "半B 前置：server stub 在位")
        # 前置必须等监听就位：sup spawn 后子进程要自己起 python+绑端口，
        # 不等就会让 down 空转「本就未在运行」（rc=0 假绿，认领路径没被走到）
        fail.check(wait_port(server_port, want_open=True, timeout=10),
                   "半B 前置：演练端口被 stub 占用")
        os.kill(b.sup.proc.pid, signal.SIGKILL)
        b.sup.proc.wait(timeout=5)
        fail.check(wait_pid_dead(b.sup.pid, timeout=5), "半B 前置：supervisor 真死（os.kill 语义）")
        fail.check(b.child_alive(), "半B 前置：父死子活（存活真孤儿）")
        fail.check(port_open(server_port), "半B 前置：父死后监听仍在（子进程不受父死影响）")
        rc, out = b.cli(entry, "down")
        fail.check(rc == 0, "半B：down 零退出（认领成功，out=%s）" % out.strip()[:160])
        fail.check("认领" in out, "半B：输出明示走认领路径（不静默收编）")
        fail.check(wait_pid_dead(b.child_pid), "半B：真孤儿 server 被 down 停掉")
        fail.check(wait_port(server_port, want_open=False, timeout=8), "半B：演练端口释放")
    finally:
        b.dispose()

    # ---- 半 C：谓词不命中（命令行不像 start-dev）→ 显式报错不误杀 ----
    c = Half("C", with_supervisor=False, server_port=server_port, ui_port=ui_port)
    try:
        fail.check(c.child_alive(), "半C 前置：占口 stub 在位（pid=%s）" % c.child_pid)
        fail.check(wait_port(server_port, want_open=True, timeout=10), "半C 前置：演练端口被占")
        rc, out = c.cli(entry, "down")
        fail.check(rc != 0, "半C：down 非零显式报错（不静默）")
        fail.check(c.child_alive(), "半C：占口进程未被误杀")
    finally:
        c.dispose()

    fail.finish()


if __name__ == "__main__":
    main()
