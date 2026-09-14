# -*- coding: utf-8 -*-
"""sandbar_exec supervisor 单测（t260913-04 方案 D3）。

契约面：pgid 档原子落盘/退出清理、rc 透传、TERM/INT 转发子进程组、
畸形输入 fail-closed（usage 64 / cmd 不存在 127）、全终态回收。
mac/Linux 同码可跑（stdlib-only），无 docker 依赖。
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sandbar_exec  # noqa: E402

PY = sys.executable


def _run_supervisor(pgid_file: Path, cmd, **kw) -> subprocess.Popen:
    return subprocess.Popen(
        [PY, "-c",
         "import sys; sys.path.insert(0, %r); import sandbar_exec; "
         "sys.exit(sandbar_exec.main(['sandbar-exec', sys.argv[1]] + sys.argv[2:]))"
         % str(Path(sandbar_exec.__file__).resolve().parent),
         str(pgid_file)] + cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


def test_usage_红_64(tmp_path):
    p = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, %r); "
                                  "import sandbar_exec; "
                                  "sys.exit(sandbar_exec.main(sys.argv[1:]))"
                        % str(Path(sandbar_exec.__file__).resolve().parent),
                        "sandbar-exec"],
                       capture_output=True, text=True)
    assert p.returncode == 64
    assert "usage" in p.stderr.lower()


def test_pgid落盘_rc透传_退出清档(tmp_path):
    pgid_file = tmp_path / "x.pgid"
    proc = _run_supervisor(pgid_file, [PY, "-c", "import sys; sys.exit(7)"])
    # 快退子进程：pgid 档「落盘→退出即清理」——轮询窗口内若见到属正常，终态必清
    assert proc.wait(timeout=15) == 7, "rc 未透传"
    assert not pgid_file.exists(), "退出后 pgid 档未清理（陈旧句柄会误导下一次 reap）"


def test_pgid等于子进程pid且为新会话(tmp_path):
    """start_new_session：pgid == 子 pid（容器内组语义不依赖 runc 假设的根据）。"""
    pgid_file = tmp_path / "s.pgid"
    proc = _run_supervisor(pgid_file, [PY, "-c",
                                       "import os,sys,time;time.sleep(5)"])
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not pgid_file.exists():
        time.sleep(0.05)
    assert pgid_file.exists(), "存活子进程下 pgid 档必须在场"
    child_pid = int(pgid_file.read_text().strip())
    try:
        os.kill(child_pid, 0)          # 子进程存活
        assert os.getpgid(child_pid) == child_pid, "新会话：pgid==子pid"
    finally:
        proc.kill(); proc.wait(timeout=10)


def test_term转发全组_迟写被排(tmp_path):
    """KI-009 对齐：supervisor 收 TERM → 子进程组（含孙进程）全灭，迟写文件不落地。"""
    late = tmp_path / "late.txt"
    pgid_file = tmp_path / "t.pgid"
    proc = _run_supervisor(pgid_file, [
        PY, "-c",
        "import sys, time; open(sys.argv[1],'w').write('started'); time.sleep(30); "
        "open(sys.argv[2],'w').write('late')",
        str(tmp_path / "started.txt"), str(late)])
    started = tmp_path / "started.txt"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not started.exists():
        time.sleep(0.05)
    assert started.exists()
    t0 = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    rc = proc.wait(timeout=15)
    rc_norm = rc - 256 if rc > 128 else rc   # 进程退出码把 -15 归一成 241
    assert rc_norm == -signal.SIGTERM, "supervisor 应以子进程的被杀 rc 落幕"
    assert time.monotonic() - t0 < 10, "TERM 转发后应迅速落幕（组收）"
    assert not late.exists(), "迟写未被组杀排掉（KI-009 破口）"
    assert not pgid_file.exists()


def test_cmd不存在_127_不落pgid(tmp_path):
    pgid_file = tmp_path / "bad.pgid"
    proc = _run_supervisor(pgid_file, ["/nonexistent/binary/xyz"])
    assert proc.wait(timeout=15) == 127
    assert not pgid_file.exists(), "Popen 失败不得留半状态 pgid 档"


def test_pgid目录不存在_自动建(tmp_path):
    pgid_file = tmp_path / "deep/dir/x.pgid"
    proc = _run_supervisor(pgid_file, [PY, "-c", "pass"])
    assert proc.wait(timeout=15) == 0
    assert not pgid_file.exists()  # 建过、退出清了
