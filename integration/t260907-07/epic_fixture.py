#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""epic_fixture.py —— t260907-07 共享夹具（不带 sc_ 前缀=共享代码，不登记清单）。

per-key 注册表条目（<root>/<key>/project.yaml，契约①a schema v1 固定形状）+
各项目主目录 docs/epics/ 立项单落盘（t261019-12 前沿形状：front-matter code/retired/summary/started） + env 现场守卫（SANDBAR_PROJECTS_DIR 指临时根、
SANDBAR_PROJECTS_YAML 必清——legacy 模式优先级会压过 per-key 模式）。

夹具卫生（方案 C3）：两项目桶均注册临时目录，绝不往真仓 worktree 根落任何文件；
退出时 env 逐键还原（原值在位→还原，原值缺失→删键）。
"""
import os
import pathlib
import tempfile

PROJECT_YAML = (
    "schema: v1\n"
    "project:\n"
    "  - key: %s\n"
    "    name: %s\n"
    "    dirs:\n"
    "      - %s\n"
)

GUARD_KEYS = ("SANDBAR_PROJECTS_DIR", "SANDBAR_PROJECTS_YAML", "SANDBAR_EPICS_DIR")


def make_project(root, key, name=None):
    """注册一个项目条目（临时主目录 + docs/epics/ 就绪），返回主目录 Path。"""
    pdir = pathlib.Path(root) / key
    (pdir / "docs" / "epics").mkdir(parents=True, exist_ok=True)
    (pdir / "project.yaml").write_text(
        PROJECT_YAML % (key, name or (key + " 项目"), pdir), "utf-8")
    return pdir


def fm_epic(code):
    """A minimal docs/epics front-matter document (t261019-12 registry contract)."""
    return ("---\ncode: %s\nretired: false\nsummary: fixture entry %s.\nstarted: 2026-09-07\n---\n\n# %s\n" % (code, code, code))


def write_epic(pdir, code, body=None):
    """在项目主目录 docs/epics/ 落一张立项单（front-matter，retired:false 接单），返回档案 Path。"""
    p = pathlib.Path(pdir) / "docs" / "epics" / (code + ".md")
    p.write_text(body or fm_epic(code), "utf-8")
    return p


class RegistryEnv(object):
    """把 SANDBAR_PROJECTS_DIR 指向临时注册表根（with 语法）；守卫键进出逐键还原。

    SANDBAR_PROJECTS_YAML 一律摘除（legacy 单文件模式优先级最高，在位会让 per-key
    夹具整个不可见）；SANDBAR_EPICS_DIR 摘除给场景一块干净底板（env 语义子用例自行显式设）。
    """

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="t26090707-reg-")
        self._saved = {}

    def __enter__(self):
        for k in GUARD_KEYS:
            self._saved[k] = os.environ.pop(k, None)
        os.environ["SANDBAR_PROJECTS_DIR"] = self.root
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False
