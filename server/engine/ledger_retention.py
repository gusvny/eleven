# -*- coding: utf-8 -*-
"""ledger_retention（t261004-11 仲裁轮抽出）：事件账/执行器动作账共用的
保留策略助手（rolling rename 轮转 + keep_days 清扫 + 归档命名面）。

为什么存在：event_ledger.py 模块级 `from temporalio import activity`（活动装饰器
所需），而 executor_actions 被 client.py（temporalio-free 轻导入纪律，见
client.py 头注「import temporalio inside functions」）模块级引入——executor_actions
不得连带 temporalio。本模块只依赖 stdlib，两侧单一真源；event_ledger 以同名
import 回接（`_maybe_rotate/_sweep/_day_key/_parse_archive_day/_ARCH_SUFFIX_RE`
名字不变，既有引用面零漂移）。

搬运纪律（仲裁令「byte-compatible」）：四个函数逐字节搬运自 event_ledger.py
（_sweep 含 t261004-11 的 base_path 参数），语义/命名/注释不变。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict

_ARCH_SUFFIX_RE = re.compile(r'^(\d{8})(?:-(\d{6}))?(?:-([0-9a-f]{1,8}))?$')


def _day_key(ts=None):
    return time.strftime('%Y%m%d', time.localtime(time.time() if ts is None else ts))


def _parse_archive_day(name: str, base: str):
    """归档名 → 当日 day-key（借镜 audit 命名面：<base>.<YYYYMMDD>[-<HHMMSS>[-hex]]）；
    命名面外 → None（清扫面跳过）。"""
    if not name.startswith(base + '.'):
        return None
    suf = name[len(base) + 1:]
    m = _ARCH_SUFFIX_RE.match(suf)
    return m.group(1) if m else None


def _maybe_rotate(path: Path, cfg: Dict[str, Any]) -> None:
    """rolling：活动文件 ≥ max_mb → rename 到 <name>.<YYYYMMDD>-<HHMMSS>-<hex6>
    （纯命名面；O_APPEND 语义下对并发写者安全）。≤0=关。重名碰撞补 hex 重试
    三次，仍撞=本轮放弃轮转（下轮再试，事件照写不丢）。"""
    mb = int(cfg.get('max_mb') or 0)
    if mb <= 0:
        return
    try:
        st = path.stat()
    except OSError:
        return      # 活动文件还不存在：无需轮转
    if st.st_size < mb * 1024 * 1024:
        return
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for _ in range(3):
        dst = path.with_name('%s.%s-%s' % (path.name, stamp, os.urandom(3).hex()))
        if not dst.exists():
            try:
                os.rename(path, dst)
            except OSError:
                pass    # 轮转失败不阻断事件写（下轮再试）
            return
    # 三次全撞（概率≈0）：放弃本轮轮转，活动文件继续追加。


def sweep_archives(cfg: Dict[str, Any], active_path: Path) -> None:
    """保留窗清扫（活动文件路径显式给定）：只删 <today - keep_days> 的归档；
    活动文件与 gaps 永不碰。keep_days ≤0=永不删。归档日解析不出=命名面外，跳过。
    （event_ledger._sweep / executor_actions 的共用体：活动文件定位留在各自模块
    ——events 账从 ledger_path 推导，executor-actions 账直接持有路径——删除策略
    本体在此单一真源。）"""
    keep = int(cfg.get('keep_days') or 0)
    if keep <= 0:
        return
    d = active_path.parent
    base = active_path.name   # 归档名跟活动文件名走（events.jsonl.* / <project>.jsonl.*）
    try:
        names = os.listdir(d)
    except OSError:
        return
    today = time.strftime('%Y%m%d', time.localtime())
    for name in names:
        day = _parse_archive_day(name, base)
        if day is None or day >= today:
            continue
        try:
            import datetime as _dt
            age = (_dt.datetime.strptime(today, '%Y%m%d')
                   - _dt.datetime.strptime(day, '%Y%m%d')).days
        except ValueError:
            continue
        if age > keep:
            try:
                (d / name).unlink()
            except OSError:
                pass    # 删不掉留给下轮清扫，不阻断事件写
