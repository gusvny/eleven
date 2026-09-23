#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 环境自愈·端口撞口退避重试（260923 宿主直修令，不开票）回归棒。

病灶（260922-18 实证）：compose up 撞「Bind for 127.0.0.1:21060 failed: port is
already allocated」而探针期未见占口者——占口者常为已退瞬时占用，整轮 0 跑报废。
本文件钉四层：
- parse_bind_conflict_port 纯函数：从报错尾解析被撞端口；解析不出=None 不猜。
- _PORT_BIND_PAT 窄签名：只认 docker 两形态撞口文案；网段撞号/通用 compose 报错
  不误入退避重试。
- 占口者诊断降级路径不抛（诊断面缺席不吞主错误）。
- 结构锁：do_up 退避重试分支 + 终报按最后形态点名（不许把端口撞口说成网段撞号）。
跑法：python3 integration/tests/test_t260923_port_bind_retry.py（stdlib-only，秒级）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stage_docker as sd  # noqa: E402


def test_parse_bind_conflict_port():
    tail = ("Bind for 127.0.0.1:21060 failed: port is already allocated")
    assert sd.parse_bind_conflict_port(tail) == 21060
    assert sd.parse_bind_conflict_port("Bind for 0.0.0.0:17233 failed: xxx") == 17233
    # 解析不出=None（调用方降级不猜）
    assert sd.parse_bind_conflict_port("port is already allocated") is None
    assert sd.parse_bind_conflict_port("invalid reference format") is None
    assert sd.parse_bind_conflict_port(None) is None
    assert sd.parse_bind_conflict_port(123) is None


def test_port_bind_pattern_narrow():
    assert sd._PORT_BIND_PAT.search(
        "Bind for 127.0.0.1:21060 failed: port is already allocated")
    assert sd._PORT_BIND_PAT.search("Error: port is already allocated")
    # 不误入：网段撞号（走 C3 换槽道）、通用报错、配置类错误
    assert not sd._PORT_BIND_PAT.search(
        "network overlaps with another network on this address space")
    assert not sd._PORT_BIND_PAT.search("invalid reference format")
    assert not sd._PORT_BIND_PAT.search("no such service: dsh")


def test_holder_diag_degrades_without_port():
    # 被撞端口未知 → 降级文案在场、不抛（不触 docker）
    out = sd._port_holder_diag("port is already allocated")
    assert "被撞端口未知" in out


def test_do_up_retry_and_precise_final_error():
    """结构锁：退避重试分支在位；终报按最后形态点名。"""
    src = (Path(sd.__file__)).read_text(encoding="utf-8")
    assert "端口撞口退避重试" in src
    assert "_port_holder_diag(up_tail)" in src
    assert "占口者诊断" in src
    assert "撞口重试 3 次未解决" in src
    assert "不许把端口撞口说成网段撞号" in src
    # 退避重试必须是分支式（continue）而非无条件——网段撞号道不受影响
    assert re.search(r"if attempt < 2:[\s\S]{0,400}?continue", src)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
