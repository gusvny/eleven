#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 环境自愈·孤儿自动清扫（260923 宿主直修令，不开票）回归棒。

背景：挂点孤儿清扫因 F1 红线（真拆须宿主点头+必须有半径）缺省关；宿主直修令
260923 把「孤儿自动清扫」列入 C 交付=点头语义兑现。本文件钉四层：
- orphan_prefix 逗号族扩展：单值行为与旧版逐字节一致；多前缀任一命中即在半径内；
  空/畸形=None（不限半径语义不变）。
- orphan_condemn_projects 判死矩阵：半径外不拆（点名「前缀外」）、年龄阀内不拆、
  CreatedAt 不可解析 fail-closed 不拆、开关显式关=全部不拆（F1 负锁不许回退）。
- 挂点缺省关红线不动：env 未设时 sweep_orphans_enabled(default=False) 仍为关。
- 结构锁：引擎侧显式启用注入在位且**只在未设时注入**（操作员显式 off 不被覆盖）。
跑法：python3 integration/tests/test_t260923_orphan_autosweep.py（stdlib-only，秒级）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import stage_docker as sd  # noqa: E402

_ORIG_ENV = dict(os.environ)


def _restore_env():
    for k in list(os.environ):
        if k not in _ORIG_ENV:
            del os.environ[k]
    os.environ.update(_ORIG_ENV)


def test_orphan_prefix_comma_family():
    try:
        os.environ.pop("SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX", None)
        assert sd.orphan_prefix() is None
        os.environ["SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX"] = "sandbar-test"
        assert sd.orphan_prefix() == "sandbar-test"      # 单值=旧版逐字节语义
        os.environ["SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX"] = "t26,sandbar-test,stage-console"
        assert sd.orphan_prefix() == ("t26", "sandbar-test", "stage-console")
        os.environ["SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX"] = "a, ,b,"
        assert sd.orphan_prefix() == ("a", "b")
        os.environ["SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX"] = " , "
        assert sd.orphan_prefix() is None                # 全空项=不限半径，不猜
    finally:
        _restore_env()


def test_condemn_matrix():
    inv = {"stages": [
        {"project": "t260912-99-x", "orphan": True, "age_s": 5000.0},
        {"project": "sandbar-test-integ", "orphan": True, "age_s": 5000.0},
        {"project": "host-prod-app", "orphan": True, "age_s": 5000.0},
        {"project": "t260912-99-young", "orphan": True, "age_s": 60.0},
        {"project": "t260912-99-noage", "orphan": True, "age_s": None},
        {"project": "t260912-99-alive", "orphan": False, "age_s": 5000.0},
    ]}
    try:
        os.environ.pop("SANDBAR_STAGE_ORPHAN_MIN_AGE_S", None)
        condemn, held = sd.orphan_condemn_projects(
            inv=inv, enabled=True, prefix=("t26", "sandbar-test", "stage-console"))
        assert sorted(condemn) == ["sandbar-test-integ", "t260912-99-x"]
        whys = {s["project"]: s["why"] for s in held}
        assert "前缀外" in whys["host-prod-app"]          # 半径外不拆=宿主存量保护
        assert "年龄" in whys["t260912-99-young"]         # 年龄阀第二道保守阀
        assert "fail-closed 不拆" in whys["t260912-99-noage"]
        assert "t260912-99-alive" not in whys             # 在用（非孤儿）不入面
        # F1 负锁：开关显式关=全部不拆且逐条点名
        condemn2, held2 = sd.orphan_condemn_projects(
            inv=inv, enabled=False, prefix=("t26",))
        assert condemn2 == []
        assert all("显式关闭" in s["why"] for s in held2)
    finally:
        _restore_env()


def test_hook_default_off_redline_intact():
    """F1 红线不动：env 未设时挂点清扫缺省关（只有 sweep CLI 缺省开）。"""
    try:
        os.environ.pop("SANDBAR_STAGE_SWEEP_ORPHANS", None)
        assert sd.sweep_orphans_enabled(default=False) is False   # 挂点缺省关
        assert sd.sweep_orphans_enabled(default=True) is True     # CLI 缺省开
    finally:
        _restore_env()


def test_engine_enablement_injection_wiring():
    act = (ROOT.parent / "server" / "engine" / "agent_activities.py").read_text(
        encoding="utf-8")
    assert "SANDBAR_STAGE_SWEEP_ORPHANS" in act
    assert '"t26,sandbar-test,stage-console"' in act
    # 只在未设时注入（显式 off 逃生语义不许被覆盖）——两旋钮各有守卫
    assert act.count('if "SANDBAR_STAGE_SWEEP_ORPHANS" not in os.environ:') == 1
    assert act.count('if "SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX" not in os.environ:') == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
