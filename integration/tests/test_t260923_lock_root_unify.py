#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 环境自愈·锁根统一（260923 宿主直修令，不开票）回归棒。

病灶：lock_root() 降级回落到 tempfile.gettempdir()/sandbar-test-stages——macOS 上
gettempdir()=TMPDIR 随机目录，而 verify.yaml supply 与场景族钉 /tmp/sandbar-test-stages。
同机两锁根 → 租约/孤儿判定劈叉（实证：dry-run 把共享供给误判成孤儿、并发守卫把
在飞台判成「外来工程」）。本文件钉三层：
- 结构锁：降级根钉死 /tmp/sandbar-test-stages（与供给同根），不再取 gettempdir()。
- 行为三态（子进程真跑 lock_root()）：HOME 不可建 → ①输出=/tmp/sandbar-test-stages
  （钉根成功）或 ②StageError 点名「均不可写」（fail-closed）；**绝不**是第三条路径
  （换根=又一处分裂，两种口径都不许出现）。
- env 指路不受影响（SANDBAR_STAGE_LOCK_DIR 优先序在场）。
跑法：python3 integration/tests/test_t260923_lock_root_unify.py（stdlib-only，秒级）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import stage_docker as sd  # noqa: E402


def _lock_root_via_sub(env_extra):
    """子进程真跑 lock_root()（进程内缓存/沙箱差异不污染判定）。"""
    env = {k: v for k, v in os.environ.items() if k != "SANDBAR_STAGE_LOCK_DIR"}
    env["HOME"] = "/dev/null/nonexistent-home-260923"
    env.update(env_extra or {})
    code = ("import sys; sys.path.insert(0, %r); import stage_docker;"
            "print(stage_docker.lock_root())" % str(ROOT))
    return subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=60)


def test_fallback_root_pinned_or_failclosed():
    p = _lock_root_via_sub({})
    out = (p.stdout or "").strip()
    err = (p.stderr or "")
    if p.returncode == 0:
        assert out == "/tmp/sandbar-test-stages", ("换根=分裂", out)
    else:
        # fail-closed 允许：点名两个根 + 指路旋钮；不许静默换根或含 gettempdir 路径
        assert "均不可写" in err, err[-300:]
        assert "SANDBAR_STAGE_LOCK_DIR" in err, err[-300:]
        assert "/var/folders" not in err and "/var/folders" not in out


def test_env_pointer_takes_precedence():
    p = _lock_root_via_sub({"SANDBAR_STAGE_LOCK_DIR": "/tmp/sd-lock-260923-sub"})
    if p.returncode == 0:
        assert (p.stdout or "").strip() == "/tmp/sd-lock-260923-sub"
    else:
        # env 指路不可写=usage 红点名（既有语义）
        assert "SANDBAR_STAGE_LOCK_DIR" in (p.stderr or "")


def test_source_structure_locks():
    src = (ROOT / "stage_docker.py").read_text(encoding="utf-8")
    assert 'pathlib.Path("/tmp/sandbar-test-stages")' in src
    assert "与供给同根" in src
    # 降级块代码（剔注释行）不再取 gettempdir；注释里的病灶引用与其它用途不受限
    fallback = src[src.index("降级根钉死"):src.index("return root", src.index("降级根钉死"))]
    code_lines = [ln for ln in fallback.splitlines() if not ln.lstrip().startswith("#")]
    assert "gettempdir" not in "".join(code_lines)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
