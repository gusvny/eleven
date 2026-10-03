#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成侧「测试夹具临时物料」回收 helper（260927 磁盘泄漏全族整治）。

与引擎侧的 `server/engine/tests/_tmp_reclaim.py` 同形同纪律（两侧各自一份，因为集成
场景既可能在引擎装不上/被改坏的机器上跑，也不该 import 引擎测试包）。

背景：`$TMPDIR` 顶层只读普查（260927 一次遍历 145,719 条）里最大的几族是
**integration 自己产的**——`sandbar-integ-run-*.lock`（每泳道仓根一把同泳道单飞锁档，
`run_scenarios._run_lock_path` 建了从不回收）、`venv-compat-root-/home-*`（venv 兼容
场景的夹具仓）、以及各期场景的夹具目录。生产者侧修法=本文这一个注册表（**单源**）：
各调用点只登记，不各写一份回收（「只写半边」必然漂移，260926 的 stage_docker 即此形）。

纪律（与引擎侧逐条同）：
  - 只在**创建成功之后**登记（创建失败不登记——回收面不猜）；
  - 回收**幂等**（弹栈式取走；重复调用第二次零条；已被别人删掉不算失败）；
  - 单个条目失败**不中断**其余（清理面不抛、不把场景跑红），逐条计数上报；
  - 目录与**文件**都管（锁档=文件、夹具仓=目录、影子/凭据副本=文件）：目录 `rmtree`，
    其余 `unlink`（符号链接只删链接本身，绝不递归到别人的东西）。

终态矩阵（逐个检查过，不假设「正常退出就够」——与引擎侧同一张表）：
  - 正常完成 / 断言失败 / 异常 / `sys.exit()` / 未捕获异常 → 解释器退出必跑 `atexit`；
  - `SIGTERM`/`SIGINT` 的**缺省**处置 → 进程直接被终止、**不跑 atexit**，所以要
    `install_signal_reclaim()` 显式装钩子：先回收，再把信号**交回原处置**（原处理器可
    调用→调它；否则恢复缺省并重发信号）——「被信号杀死」的退出语义逐字不变；
  - `os._exit()` → 跳过 `atexit`，**调用点必须显式调用 `reclaim_registered()`**
    （`run_scenarios` 的「预算耗尽」与「批台信号」两条收口路径即此形）；
  - `SIGKILL`（执行器硬杀）→ 进程内物理上抓不住，**不假装兜得住**：兜底网是仓库级的
    `integration/tools/sweep_tmp_fixtures.py`（白名单前缀 + 龄 ≥6h）与引擎巡检第四判据
    「临时目录水位」。

用法（调用点两行）：
    import lib_tmp_reclaim
    p = lib_tmp_reclaim.mkdtemp_reclaimed("venv-compat-root-")     # 目录
    lib_tmp_reclaim.register_tmp_path(lock_path)                    # 文件
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import tempfile
from pathlib import Path

#: 本进程登记、尚未回收的临时物料（真源；回收后立刻出册——弹栈式取走）
REGISTERED: list = []

#: 回收失败计数（观测面；不静默——测试/收口报告可读）
REAP_FAILURES: int = 0

#: 已安装的信号钩子 {signum: 安装前的原处理器}（`install_signal_reclaim` 幂等与链式用）
_SIGNAL_PREV: dict = {}


def _entry(path) -> Path:
    return path if isinstance(path, Path) else Path(str(path))


def register_tmp_path(path, label: str = "") -> Path:
    """登记一个**本进程创建**的临时物料（目录或文件）→ 返回 `Path`。

    登记即「退出时必回收」；重复登记同一路径无害（回收逐条幂等）。`label` 只为可读性
    与失败点名（不参与判据）。
    """
    p = _entry(path)
    REGISTERED.append(p if not label else (p, label))
    return p


def _block_terminate_signals():
    """铸目/登记窗口期屏蔽 SIGINT/SIGTERM（与引擎侧 `_tmp_reclaim` 同纪律、同理由）。

    `mkdtemp` 返回到 `register` 入册之间的无保护窗口里落的信号，会让目录「已落盘、
    未在册」，退出面（atexit / `install_signal_reclaim` / 显式 `reclaim_registered`）
    全都看不见它——间歇泄漏（t261003 验收走查实测）。屏蔽后信号推迟到入册后才送达，
    处置语义逐字不变；`pthread_sigmask` 缺席/被拒时回落旧形态。
    """
    sigs = tuple(s for s in (getattr(signal, "SIGINT", None),
                             getattr(signal, "SIGTERM", None)) if s is not None)
    if not sigs or not hasattr(signal, "pthread_sigmask"):
        return None
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, sigs)
        return sigs
    except (OSError, ValueError):
        return None


def mkdtemp_reclaimed(prefix: str, root: str = None) -> Path:
    """`tempfile.mkdtemp` 的回收版：建目录 + 登记 + 本进程退出时必被回收。返回 `Path`。

    入册在**创建成功之后**——`mkdtemp` 抛异常时不留半条注册。
    铸目+登记全程屏蔽 SIGINT/SIGTERM（见 `_block_terminate_signals`）：信号落在窗口内
    也推迟到登记后才送达，KeyboardInterrupt 照常走，目录已在册、退出面必收。
    """
    blocked = _block_terminate_signals()
    try:
        p = register_tmp_path(Path(tempfile.mkdtemp(prefix=prefix, dir=root)))
    finally:
        sigs = blocked
        if sigs:
            try:
                signal.pthread_sigmask(signal.SIG_UNBLOCK, sigs)
            except (OSError, ValueError):
                pass
    return p


def live_tmp_paths() -> list:
    """当前在册（未回收）的临时物料快照（观测面；调用方不得据此改册）。"""
    return [(e[0] if isinstance(e, tuple) else e) for e in REGISTERED]


def _remove_one(p: Path) -> None:
    """删一个条目：目录递归删、文件/符号链接直接删（符号链接绝不当目录跟进去）。"""
    if p.is_symlink():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(str(p))
    elif p.exists():
        p.unlink()


def reclaim_registered() -> dict:
    """回收本进程登记的全部临时物料（幂等）→ `{"removed": [...], "failed": [...]}`。

    弹栈式取走（取走即出册），所以重复调用第二次是零条；单条失败**不抛**（清理面不把
    场景跑红）但逐条点名进 `failed` 且计数进 `REAP_FAILURES`。
    """
    global REAP_FAILURES
    out = {"removed": [], "failed": []}
    while REGISTERED:
        entry = REGISTERED.pop()
        p, label = entry if isinstance(entry, tuple) else (entry, "")
        try:
            existed = p.exists() or p.is_symlink()
            _remove_one(p)
            if existed and (p.exists() or p.is_symlink()):
                raise OSError("still present after removal")
            out["removed"].append("%s%s" % (p, (" (%s)" % label) if label else ""))
        except OSError as e:
            REAP_FAILURES += 1
            out["failed"].append("%s%s: %s: %s" % (p, (" (%s)" % label) if label else "",
                                                   type(e).__name__, e))
    return out


def reclaim_count() -> int:
    """回收（幂等）并返回本次实际尝试的条数。"""
    return len(reclaim_registered()["removed"])


def _chain_to_previous(signum: int, prev) -> None:
    """把信号交回**安装前**的处置：可调用→调它；忽略→什么都不做；否则缺省处置+重发。

    这条是「不吞别人的信号语义」的实现：`SIGINT` 的原处置通常是 Python 的
    `default_int_handler`（→ `KeyboardInterrupt`），`SIGTERM` 通常是 `SIG_DFL`
    （→ 进程被信号杀死，退出码 143）。回收只插在前面，绝不改后半段。
    """
    if callable(prev):
        prev(signum, None)
        return
    if prev == signal.SIG_IGN:
        return
    try:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    except (OSError, ValueError):
        os._exit(128 + int(signum))


def install_signal_reclaim(signals=(signal.SIGTERM, signal.SIGINT)) -> list:
    """装「信号先回收」钩子（幂等）→ 返回本次装上的信号号列表。

    只在主线程可行（`signal.signal` 的限制）：装不上就跳过并留痕（返回列表里没有它），
    绝不抛——回收面不该让调用点崩。已装过的信号号直接算已装（不重复包装，避免链式套娃）。
    """
    installed = []
    for sig in signals:
        if sig in _SIGNAL_PREV:
            installed.append(sig)
            continue

        def _handler(signum, frame, _sig=sig):
            try:
                reclaim_registered()
            except Exception:                      # noqa: BLE001 —— 回收面绝不拦信号
                pass
            _chain_to_previous(signum, _SIGNAL_PREV.get(_sig, signal.SIG_DFL))

        try:
            _SIGNAL_PREV[sig] = signal.getsignal(sig)
            signal.signal(sig, _handler)
        except (OSError, ValueError, TypeError):
            _SIGNAL_PREV.pop(sig, None)
            continue
        installed.append(sig)
    return installed


#: 进程级兜底：正常/异常/早退（凡走解释器退出）都回收。与调用点的显式回收互为冗余，
#: 重复回收无害（幂等）。
atexit.register(reclaim_registered)
