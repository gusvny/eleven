#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-38 共享夹具：真 git 泳道 + 本票声明的 build chain（bundle_pairs）。

复用 t261004-25 的夹具层（mk_lane/settle/engine_modules/run_verify_code——共享
helpers 复用纪律明文允许，跨票 sys.path import），只补两块：
- BASE_BUNDLE：基线含最小 verify.yaml（verify_lane code 道装配需要）与
  server/merge-checks.yaml（合成 build chain，不绑真实仓库路径）；
- MALFORMED_CHECKS / 缺失声明等声明态变体由场景按需覆写。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LIB25 = REPO / "integration" / "t261004-25"
if str(LIB25) not in sys.path:
    sys.path.insert(0, str(LIB25))

if str(REPO / "integration") not in sys.path:
    sys.path.insert(0, str(REPO / "integration"))

from lib_t26100425 import (  # noqa: E402,F401  (re-export)
    BASE, archive_find, check, engine_modules, env_fail, git, git_ok,
    head_sha, mk_lane, quarantine_root, rmtree, settle, summary, tmpdir,
)
from lib_t26100425 import run_verify_code  # noqa: E402,F401

# 合成 build chain（与 server/merge-checks.yaml 同形状；不绑 workbench 真路径——
# 契约锚定的是「声明 → 闸放行」这条链，不是某个具体前缀）。
SRC = "srcs/client/"
OUT = "builds/lib/"

MERGE_CHECKS_YAML = (
    "# project merge checks\n"
    "bundle_pairs:\n"
    "  - src: %s\n"
    "    out: %s\n" % (SRC, OUT)
)

MALFORMED_CHECKS_YAML = (
    "bundle_pairs:\n"
    "  - src: srcs/client/\n"
    "    not_a_known_key: oops\n"
)

VERIFY_YAML = (
    "schema: v1\n"
    "lanes:\n"
    "  code:\n"
    "    write_allow:\n"
    "      - docs/\n"
    "    checks:\n"
    "      - id: noop\n"
    "        cmd: 'true'\n"
)

BASE_BUNDLE = dict(BASE)
BASE_BUNDLE["verify.yaml"] = VERIFY_YAML
BASE_BUNDLE["server/merge-checks.yaml"] = MERGE_CHECKS_YAML
BASE_BUNDLE["srcs/client/widget.ts"] = "export const w = 1\n"
BASE_BUNDLE["builds/lib/client.js"] = "old bundle\n"

TID = "t261009-38"


def mk_bundle_lane(prefix, checks=MERGE_CHECKS_YAML):
    """基线带声明与 src/out 两个已存在文件的泳道。checks=None → 声明缺失态。"""
    base = dict(BASE_BUNDLE)
    if checks is None:
        base.pop("server/merge-checks.yaml")
    elif checks != MERGE_CHECKS_YAML:
        base["server/merge-checks.yaml"] = checks
    tmp, mainrepo, lane, fork = mk_lane(prefix, base=base)
    return tmp, mainrepo, lane, fork


def dirty(lane, rel, content):
    p = lane / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p
