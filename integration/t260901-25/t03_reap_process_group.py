#!/usr/bin/env python3
"""t03_reap_process_group.py —— KI-009 drain 组粒度回收行为测（t260901-25）。

用户故事：agent 交付结果文件后还会迟写（dsh runner 再 spawn 子进程），
旧实现只 terminate 直接子进程且不 wait——迟写者把泳道弄脏，工单被逼进
blocked-人工-commit 死路（KI-009 实锤）。修复后 settle 之前必须整树收干净：
**reap 返回后，迟写文件不再变化**——这是竞态窗被压掉的直接证据。

黑盒手法：ast 抽取真源 `_reap_agent_proc`（不 import 模块，绕开 temporalio）
exec 进沙箱命名空间；起真实进程组（子进程 start_new_session 建组，孙进程
持打开 fd 每 0.1s 迟写一次文件），调用真源 reap，断言：
  a) 子、孙进程全部退出（组粒度，不是只收直接子进程）；
  b) reap 返回 + 宽限期后，迟写文件内容稳定不再增长。

直跑：python3 integration/t260901-25/t03_reap_process_group.py
末行 SUMMARY pass=<n> fail=<k>；fail>0 exit 1。
"""
import ast
import asyncio
import inspect
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parents[1]))
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （集成侧回收 helper：注册表+atexit，t261002-13）
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = REPO / "server" / "engine" / "agent_activities.py"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


class _StubLogger:
    def info(self, *a, **k):
        pass

    warning = info


class _StubActivity:
    logger = _StubLogger()


def load_reap():
    """ast 抽取真源 _reap_agent_proc，返回可调用对象（sync/async 皆容）。"""
    tree = ast.parse(SRC.read_text("utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "_reap_agent_proc":
            code = compile(ast.Module(body=[node], type_ignores=[]),
                           node.name, "exec")
            ns = {"os": os, "signal": signal, "subprocess": subprocess,
                  "asyncio": asyncio, "time": time, "errno": __import__("errno"),
                  "List": List, "Dict": Dict, "Any": Any, "Optional": Optional,
                  "activity": _StubActivity}
            # 模块级常量（如 AGENT_REAP_*_SEC）随真源一并带入沙箱，值不复制
            for m in re.finditer(r"^([A-Z][A-Z0-9_]+) = .+$", SRC.read_text("utf-8"),
                                 re.MULTILINE):
                try:
                    exec(compile(m.group(0), "<const>", "exec"), ns)
                except Exception:
                    pass
            exec(code, ns)
            return ns["_reap_agent_proc"]
    return None


def run_reap(reap, proc):
    """按真源签名调用 reap（只传 proc，超时用真源默认；sync/async 皆容）。"""
    ret = reap(proc)
    if inspect.iscoroutine(ret):
        asyncio.run(ret)


GRANDCHILD = r"""
import sys, time
path = sys.argv[1]
with open(path, "a") as f:
    deadline = time.time() + 120
    while time.time() < deadline:
        f.write("late-write %f\n" % time.time())
        f.flush()
        time.sleep(0.1)
"""


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main():
    print("== 前置：真源 _reap_agent_proc 可抽取 ==")
    reap = load_reap()
    if reap is None:
        ok(False, "_reap_agent_proc 已在真源定义（implement 未交付则红，属预期）")
        print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
        return 1
    ok(True, "_reap_agent_proc 抽取成功")

    import tempfile
    tmp = mkdtemp_reclaimed("t25-t03-")
    late_file = tmp / "late-write.txt"
    late_file.write_text("", encoding="utf-8")

    print("== 场景：子进程建组 → 孙进程持 fd 迟写 → reap 整树收口 ==")
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
         + repr(GRANDCHILD) + ", " + repr(str(late_file))
         + "]); time.sleep(120)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 等孙进程迟写出现（最多 30s：t261026-08 — 5s 在全量 battery 的高载下会
    # 超窗误红，孙进程只是慢启动、不是产品行为；断言语义不变），拿到孙 pid 后才动手
    grand = None
    deadline = time.time() + 30
    while time.time() < deadline:
        if late_file.stat().st_size > 0:
            out = subprocess.run(["pgrep", "-g", str(os.getpgid(child.pid))],
                                 capture_output=True, text=True)
            pids = [int(x) for x in out.stdout.split()]
            extras = [p for p in pids if p != child.pid and p != os.getpid()]
            if extras:
                grand = extras[0]
                break
        time.sleep(0.1)
    ok(grand is not None, "孙进程已在迟写（pid=%s）" % grand)
    size_before = late_file.stat().st_size

    t0 = time.time()
    try:
        run_reap(reap, child)
    except Exception as e:
        ok(False, "reap 对存活进程组调用异常: %r" % e)
    elapsed = time.time() - t0
    ok(True, "reap 返回（耗时 %.1fs，有界 drain）" % elapsed)

    ok(not alive(child.pid), "直接子进程已退出")
    if grand is not None:
        ok(not alive(grand), "孙进程（组内迟写者）已退出——组粒度回收成立")
    time.sleep(1.0)  # 宽限期：若还有活着的迟写者，这里会长
    size_after = late_file.stat().st_size
    ok(size_after == size_before,
       "reap 返回后迟写文件不再变化（%d -> %d 字节）——竞态窗已压掉"
       % (size_before, size_after))

    print("== 场景：reap 对已退出 proc 幂等容错（不抛、不误杀） ==")
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    try:
        run_reap(reap, done)
        ok(True, "对已退出 proc reap 不抛")
    except ProcessLookupError:
        ok(False, "对已退出 proc reap 抛 ProcessLookupError（应幂等容错）")
    except Exception as e:
        ok(False, "对已退出 proc reap 异常: %r" % e)
    ok(True, "执行流未被打断（reap 未误杀测试进程自身）")

    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
