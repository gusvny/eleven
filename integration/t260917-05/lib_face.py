# -*- coding: utf-8 -*-
"""t260917-05 场景族共享夹具（本票目录自含，不跨票目录 import——t260913-03
资产闭包守卫只认同目录/integration 顶层可解析者）。

提供：
- EXIT_OK / EXIT_FAIL / EXIT_ENV：三态契约退出码（闸内无中间态——环境缺失一律
  ENV_FAIL=2，绝不装绿；t260904-12）。
- ensure_poc_python()：temporalio 缺席时按回落链重执行（t260905-10/lib_lane 同款：
  POC/.venv → 主树 .venv；重跑目标=调用方入口脚本 sys.argv[0]，不是本 lib）。
- zstd_available() / zstd_bytes()：zstd CLI 探针与多帧 zstd 拼接构造
  （真实会话档形态，workbench/node.ts 实证）。
- tmp_dir()：进程内文件夹具。
- Fail：行式断言收集器（lib_gate.Fail 同款口径：失败输出自明，执行器只取尾部）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


class Fail:
    """行式断言收集器（失败清单自明，exit 码只看有无失败）。"""

    def __init__(self, title: str):
        self.title = title
        self.passed = 0
        self.fails = []

    def check(self, cond, msg: str) -> bool:
        cond = bool(cond)
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if cond:
            self.passed += 1
        else:
            self.fails.append(msg)
        return cond

    def exit_code(self) -> int:
        print("\n%s：ok=%d FAIL=%d" % (self.title, self.passed, len(self.fails)), flush=True)
        return EXIT_FAIL if self.fails else EXIT_OK


def ensure_poc_python() -> None:
    """temporalio 不可导入时按回落链重执行；无候选 → ENV_FAIL exit 2 点名。
    重执行目标=调用方入口脚本（sys.argv[0]，不是本 lib 的 __file__——把 lib 当
    脚本重跑=无 main 守卫静默 exit 0=假绿，比崩溃更毒）。"""
    try:
        import temporalio  # noqa: F401
        return
    except ImportError:
        pass
    entry = Path(sys.argv[0]).resolve() if sys.argv[0] else None
    if entry is None or not entry.exists() or entry.suffix != ".py":
        print("ENV_FAIL: temporalio 不可导入且入口脚本不可辨（argv0=%r）——无法回落重执行"
              % (sys.argv[0],), flush=True)
        sys.exit(EXIT_ENV)
    cands = []
    poc_venv = REPO / "server/engine/.venv/bin/python"
    if poc_venv.exists():
        cands.append(poc_venv)
    parts = REPO.parts
    for marker in (".lane", ".worktrees"):
        if marker in parts:
            main = Path(*parts[: parts.index(marker)])
            cands.append(main / "server/engine/.venv/bin/python")
            break
    for c in cands:
        if c.exists() and str(c) != sys.executable:
            os.execv(str(c), [str(c), str(entry)] + sys.argv[1:])
    print("ENV_FAIL: temporalio 不可导入且回落链无候选解释器"
          "（试过 %s）——先在主树建 server/engine/.venv" % [str(c) for c in cands],
          flush=True)
    sys.exit(EXIT_ENV)


def zstd_available() -> bool:
    return shutil.which("zstd") is not None


def zstd_bytes(chunks) -> bytes:
    """把多段字节各自压成 zstd 帧后拼接（多帧拼接=真实会话档形态）。"""
    outs = []
    for ch in chunks:
        p = subprocess.run(["zstd", "-q", "-f", "-c", "-"],
                           input=ch, capture_output=True, timeout=30)
        if p.returncode != 0:
            raise RuntimeError("zstd 压缩失败：%s" % (p.stderr or b"")[:200])
        outs.append(bytes(p.stdout))
    return b"".join(outs)


def tmp_dir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
