#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⑤a 回归锁（宿主令 260927 选项 i）：dir 型工作区缺省必须落在**项目注册目录内**。

实案：nusuyou content-studio 票建票当场被拒——「workspace 路径 /tmp/sandbar-ws/tXXXX 不在
项目 nusuyou 的注册目录内」。根因是**引擎自相矛盾**：`derive_lane_workspace` /
`base._init` 用缺省基准 `/tmp/sandbar-ws` 自己派生出绝对路径，随后创建链
（`client.py` ticket-start）把这个「引擎派生值」当成「调用方显式传参」送进
`check_paths_under_project` ⇒ 判它不在项目注册目录内 ⇒ 拒收。宿主只能手工传项目内路径。

修法：缺省基准改为项目内 `<项目根>/.ticket-ws/<票号>`（`shared.ws_dir_default`，纯函数、
运行期不读 env），env `SANDBAR_WS_DIR_BASE` 仍可覆盖（自检/隔离台）。

本锁钉四点：①派生路径在项目内；②`check_paths_under_project` 必须放行该派生值（原 bug 点）；
③env 覆盖语义逐字保持；④函数纯度（调用期不读 env，workflow 沙箱安全）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shared  # noqa: E402


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "repo").mkdir(parents=True)
    return {"key": "acme", "dirs": [str(root), str(root / "repo")]}


def test_default_dir_workspace_lands_inside_project(project):
    ws = shared.derive_lane_workspace(
        "t-1", "main", template_workspace_dir=True, project_root=project["dirs"][0])
    path = ws[1]["path"]
    assert ws[1]["type"] == "dir"
    assert path.startswith(project["dirs"][0].rstrip("/") + "/" + shared.WS_DIR_REL + "/"), path
    assert path.endswith("/t-1"), path


def test_derived_workspace_passes_the_in_project_gate(project):
    """原 bug 点：派生值必须能过创建链的项目内闸（老实现 /tmp/sandbar-ws 必被拒）。"""
    ws = shared.derive_lane_workspace(
        "t-1", "main", template_workspace_dir=True, project_root=project["dirs"][0])
    shared.check_paths_under_project(project, ws[1], "")            # 不抛=放行


def test_legacy_base_would_be_refused_by_that_gate(project):
    """反证（可执行证据）：老缺省基准确实会被同一道闸拒——这才是宿主遇到的建票失败。"""
    legacy = {"type": "dir", "path": "/tmp/sandbar-ws/t-1"}
    with pytest.raises(ValueError) as ei:
        shared.check_paths_under_project(project, legacy, "")
    assert "不在项目" in str(ei.value)


def test_env_override_still_wins(monkeypatch, project):
    """自检/隔离台面：显式 env 覆盖语义逐字保持（覆盖时不再拼项目内子目录）。"""
    monkeypatch.setattr(shared, "WS_DIR_BASE_OVERRIDE", "/tmp/selftest-ws")
    assert shared.ws_dir_default(project["dirs"][0], "t-9") == "/tmp/selftest-ws/t-9"


def test_no_project_root_falls_back_to_legacy_base(monkeypatch):
    """无项目上下文（老自检/遗留调用面）：回落老基准，向后兼容不断链。"""
    monkeypatch.setattr(shared, "WS_DIR_BASE_OVERRIDE", "")
    monkeypatch.setattr(shared, "WS_DIR_BASE", "/tmp/legacy-ws")
    assert shared.ws_dir_default("", "t-9") == "/tmp/legacy-ws/t-9"
    assert shared.ws_dir_path("t-9") == "/tmp/legacy-ws/t-9"


def test_ws_dir_default_is_pure_wrt_environment(project):
    """纯度锁：调用期**不读 env**（workflow 沙箱里读 os.environ 属违规访问，KI-135 教训）。"""
    before = shared.ws_dir_default(project["dirs"][0], "t-1")
    os.environ["SANDBAR_WS_DIR_BASE"] = "/tmp/mutated-after-import"
    try:
        assert shared.ws_dir_default(project["dirs"][0], "t-1") == before
    finally:
        os.environ.pop("SANDBAR_WS_DIR_BASE", None)


def test_workflow_side_uses_the_same_single_source(project):
    """单源锁：workflow 侧（base._init）与创建链（derive_lane_workspace）必须同一条派生。"""
    src = (Path(__file__).resolve().parents[1] / "base.py").read_text(encoding="utf-8")
    assert "ws_dir_default(inp.project_root, inp.ticket_id)" in src, \
        "workflow 侧必须调 shared.ws_dir_default（不许自己拼路径、不许退回 WS_DIR_BASE）"


if __name__ == "__main__":                                      # 允许单文件直跑（诊断面）
    sys.exit(pytest.main([__file__, "-q"]))
