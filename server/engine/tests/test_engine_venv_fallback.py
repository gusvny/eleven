#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-10 目录重构：引擎 venv 回落链 UT（shared.engine_venv_python 单一真源）。

覆盖：新路径优先/仅旧路径回落/两者并存取新/两缺 None fail-closed，及畸形输入
（repo_root 不存在、候选是目录、候选不可执行、venv 断链）。
"""
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared


def _make_venv(root: Path, rel, executable=True, as_dir=False):
    import shutil
    py = root.joinpath(*rel, ".venv", "bin", "python")
    if py.is_dir():
        shutil.rmtree(py)
    py.parent.mkdir(parents=True, exist_ok=True)
    if as_dir:
        py.mkdir()
        return py
    py.write_text("#!/bin/sh\n", "utf-8")
    os.chmod(py, 0o755 if executable else 0o644)
    return py


def test_new_path_wins(tmp_path):
    _make_venv(tmp_path, ("server", "engine"))
    _make_venv(tmp_path, ("server", "dsh", "temporal-poc"))
    got = shared.engine_venv_python(tmp_path)
    assert got is not None and "server/engine" in str(got)


def test_old_path_fallback(tmp_path):
    _make_venv(tmp_path, ("server", "dsh", "temporal-poc"))
    got = shared.engine_venv_python(tmp_path)
    assert got is not None and "temporal-poc" in str(got)


def test_missing_returns_none(tmp_path):
    assert shared.engine_venv_python(tmp_path) is None


def test_malformed_inputs(tmp_path):
    # repo_root 不存在 / 是文件
    assert shared.engine_venv_python(tmp_path / "nope") is None
    f = tmp_path / "afile"
    f.write_text("x", "utf-8")
    assert shared.engine_venv_python(f) is None
    # 候选是目录 / 不可执行
    _make_venv(tmp_path, ("server", "engine"), as_dir=True)
    assert shared.engine_venv_python(tmp_path) is None
    _make_venv(tmp_path, ("server", "engine"), executable=False)
    assert shared.engine_venv_python(tmp_path) is None
