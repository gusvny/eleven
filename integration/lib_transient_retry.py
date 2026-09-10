#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""瞬态故障白名单判定 + 一次重试（t260910-12 目标④，review R9 单源）。

背景（260910 实证）：多票并发时三类瞬态——台内 502 Bad Gateway、端口拒连、
起台面繁忙——把健康场景追成假红，逼仲裁改分类器。纪律：**场景侧**命中白名单
自动重试一次，重试仍红才原样上报（不吞不改文案）。

单一真源：分类逻辑只有本文件一份。mjs 场景经 lib_transient_retry.mjs spawn
本文件的 `is-transient` 子命令判定（零双实现——stage_docker.mjs 头注教训：
两份逻辑必漂移，且漂移发生过）。

公开契约（integration/t260910-12/sc_transient_retry_contract.py 锚定面）：
- is_transient(message) -> bool（纯布尔；诊断原因走 _classify）；
- CLI `judge <msg>` 打印 transient|fatal、exit 0（py 消费缝）；
- CLI `is-transient`（stdin 读文案）瞬态 exit 0 / 其余 exit 1（shell/mjs 桥，
  兼容保留）；
- retry_transient_once(fn)：命中白名单的异常自动重试恰一次，重试仍红原样
  抛出（文案逐字节保留）；非瞬态不重试。

白名单边界：**互斥等待超时（同项目并发 ensure 撞锁）属终态红**，不重试——
重试会再次撞锁（重试是有害面：对编排层错误重试=洗红温床）；起台面「礼让」
类文案已随租约化退役，不入列。

畸形输入纪律（岗位钩子B）：None/非字符串/空串/超长行一律判非瞬态（fatal），
绝不抛异常、绝不误判瞬态——分类器本身失败时向 fatal 侧倒。
"""
from __future__ import annotations

import re
import sys
import time

# (编译正则, 人类可读标签)。全部锚定已知瞬态的具体文案，不做宽泛匹配。
TRANSIENT_PATTERNS = [
    (re.compile(r"502\s*bad\s*gateway", re.IGNORECASE), "台内 502 Bad Gateway"),
    (re.compile(r"ERR_CONNECTION_REFUSED"), "浏览器侧连接被拒"),
    (re.compile(r"ECONNREFUSED"), "node 侧连接被拒"),
    (re.compile(r"(?:connection|connect)\s+refused", re.IGNORECASE), "TCP 连接被拒"),
    # 实证补族（t260910-12 arbitrate gen2）：两条不带空格的拒连文案形态——
    # Rust tonic 驼峰 ConnectionRefused、temporalio python SDK 的 tcp connect
    # error（schedule 场景三腿实测红文案；与 refused 族同根：端口就绪缝隙/
    # 台瞬断），不入列则该消费面的瞬态重试永不命中。
    (re.compile(r"connectionrefused", re.IGNORECASE), "Rust/OS 层连接被拒（驼峰形态）"),
    (re.compile(r"tcp\s+connect\s+error", re.IGNORECASE), "temporalio SDK 连接失败"),
    (re.compile(r"满员"), "起台面满员（排队超预算/闸竞争）"),
    (re.compile(r"端口段耗尽"), "端口段耗尽"),
]

_MAX_SCAN_LEN = 20000          # 超长截断扫描（防畸形/攻击性输入拖垮判定）
_EXIT_TRANSIENT, _EXIT_FATAL = 0, 1


def _classify(message):
    """分类一条错误文案，返回 (bool, reason)。任何畸形输入 → (False, 说明)，
    绝不抛异常。"""
    if not isinstance(message, str) or not message.strip():
        return False, "非瞬态（空或非字符串输入）"
    text = message[:_MAX_SCAN_LEN]
    for pat, label in TRANSIENT_PATTERNS:
        if pat.search(text):
            return True, label
    return False, "非瞬态（白名单未命中）"


def is_transient(message):
    """判定一条错误文案是否属于已知瞬态。返回纯 bool（公开契约——仲裁分类器
    直接消费的形状；诊断原因走 _classify）。畸形输入安全落 False。"""
    return _classify(message)[0]


def retry_transient_once(fn, sleep_s=2.0, classify=None):
    """跑 fn 一次；命中白名单的异常自动重试一次，重试仍红原样抛出（文案
    逐字节保留——仲裁分类器看到的就是真实第二跳）。非瞬态异常原样抛出。"""
    judge = classify if classify is not None else (lambda e: _classify(_exc_text(e))[0])
    try:
        return fn()
    except Exception as e:      # noqa: BLE001 场景侧收口面：分类后必须重抛
        if not judge(e):
            raise
        time.sleep(sleep_s)
        return fn()


def _exc_text(e):
    try:
        return str(e)
    except Exception:          # noqa: BLE001 畸形异常对象（str 都会炸的）
        return ""


def main(argv):
    """两个子命令：
    - `judge <msg>`：stdout 打印 transient|fatal、exit 0（py 消费缝，契约面）；
    - `is-transient`：stdin 读错误文案，瞬态 exit 0 / 其余 exit 1，原因落
      stdout（shell/mjs 桥，兼容保留）。"""
    if argv and argv[0] == "judge":
        if len(argv) < 2:
            print("fatal", flush=True)
            print("usage: lib_transient_retry.py judge <message>", file=sys.stderr)
            return 64
        ok, _ = _classify(argv[1])
        print("transient" if ok else "fatal", flush=True)
        return 0
    if argv and argv[0] == "is-transient":
        message = sys.stdin.read()
        ok, reason = _classify(message)
        print(reason, flush=True)
        return _EXIT_TRANSIENT if ok else _EXIT_FATAL
    print("usage: lib_transient_retry.py judge <message>\n"
          "       lib_transient_retry.py is-transient < message.txt",
          file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
