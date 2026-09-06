# -*- coding: utf-8 -*-
"""t260905-10 场景族共享夹具（前置与基础步骤复用；三个场景 intent 各自独立）。

提供：
- EXIT_FAIL / EXIT_ENV：三态契约退出码（闸内无跳过态——环境缺失一律 ENV_FAIL=2）。
- ensure_poc_python()：temporalio 缺席时回落链重执行（POC/.venv → 主树 .venv，
  replay_check 同款候选逻辑——泳道在 C5 落地前本就靠这条回落链跑）。
- stage_up_temporal() / stage_down()：docker 舞台单点入口（stage_docker），
  StageError 三类退出码直译（env=2 / conflict=3 / 其他=1）。
- zstd_frames()：多帧 zstd 拼接构造（workbench/node.ts:59 实证形态）。
- git_available() / run_git()：tmp 仓夹具用。
- env_guard()：GIT_CONFIG_* 环境变量保存/恢复（不污染调用方环境）。
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
PROD_PORTS = (3099, 3199, 7233, 8233, 17233, 18233)


class Fail:
    """行式断言收集器（lib_gate.Fail 同款口径：失败输出自明，执行器只取尾部）。"""

    def __init__(self, title: str):
        self.title = title
        self.passed = 0
        self.fails: list = []

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
    poc_venv = REPO / "server/dsh/temporal-poc/.venv/bin/python"
    if poc_venv.exists():
        cands.append(poc_venv)
    parts = REPO.parts
    for marker in (".lane", ".worktrees"):
        if marker in parts:
            main = Path(*parts[: parts.index(marker)])
            cands.append(main / "server/dsh/temporal-poc/.venv/bin/python")
            break
    for c in cands:
        if c.exists() and str(c) != sys.executable:
            os.execv(str(c), [str(c), str(entry)] + sys.argv[1:])
    print("ENV_FAIL: temporalio 不可导入且回落链无候选解释器"
          "（试过 %s）——先在主树建 server/dsh/temporal-poc/.venv" % [str(c) for c in cands],
          flush=True)
    sys.exit(EXIT_ENV)


def stage_up_temporal(project: str, namespace: str):
    """起 temporal-only docker 舞台（场景台，非常驻供给台）。返回 (stage_docker, state)。"""
    sys.path.insert(0, str(REPO / "integration"))
    import stage_docker  # noqa: E402
    try:
        state = stage_docker.do_up_public(project, ["temporal"],
                                          {"namespace": namespace},
                                          stage_docker.DEFAULT_TIMEOUT)
    except stage_docker.StageError as e:
        code = EXIT_ENV if e.kind == "env" else 3 if e.kind == "conflict" else 1
        print("ENV_FAIL: docker 舞台 up 失败（%s）：%s" % (e.kind, e), flush=True)
        sys.exit(code)
    return stage_docker, state


def zstd_available() -> bool:
    return shutil.which("zstd") is not None


def zstd_frames(chunks) -> bytes:
    """把多段字节各自压成 zstd 帧后拼接（多帧拼接=真实会话档形态）。"""
    outs = []
    for ch in chunks:
        p = subprocess.run(["zstd", "-q", "-f", "-c", "-"],
                           input=ch, capture_output=True, timeout=30)
        if p.returncode != 0:
            raise RuntimeError("zstd 压缩失败：%s" % p.stderr[:200])
        outs.append(bytes(p.stdout))
    return b"".join(outs)


def git_available() -> bool:
    return shutil.which("git") is not None


def run_git(args, cwd, env=None, timeout=30):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git"] + args, cwd=str(cwd), env=e,
                          capture_output=True, text=True, timeout=timeout)


class env_guard:
    """GIT_CONFIG_* / HOME 环境保存恢复上下文（夹具隔离，不碰真 HOME 配置）。"""

    KEYS = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM")

    def __init__(self, **values):
        self.values = values
        self._saved = {}

    def __enter__(self):
        for k in self.KEYS:
            self._saved[k] = os.environ.get(k)
        for k in self.KEYS:
            if k in self.values:
                if self.values[k] is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = self.values[k]
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def tmp_dir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
