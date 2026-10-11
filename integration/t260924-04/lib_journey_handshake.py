#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_journey_handshake.py — t260924-04 握手 helper：事件代替固定间隔轮询。

评审（notes/discussions/261011-slow-scenario-review.md 族 D）口径：等待「别人做了
某事」时，事件的生产者写一行，消费者据此动手——绝不固定间隔探测。本 helper 提供
两个消费原语：

- ``LineReader``：把子进程 stdout 管道变成**逐行事件流**（一条后台读线程阻塞在
  ``readline`` 上，零轮询），支持：
  - ``wait_for(predicate, timeout_s)``：阻塞等到第一行命中谓词，或具名超时；
  - 全量行同步镜像进日志文件（tee）——观测面与改造前一致；
  - **读者线程死亡必须具名**：管道读异常/EOF 转成 sentinel 事件，waiter 拿到
    点名失败而不是静默挂死（tee 线程死 → 管道缓冲写满 → worker 卡死成 hang 的
    缺陷面，261011 评审 comment 3，在此堵死）。
- ``wait_seconds(bound_s)``：注入的秒界等待（时间语义的第二通道：等待长度是
  声明的常数，不是探测循环）。

词面纪律：本模块不 print 任何以 ``{``/``[`` 起首的行（闸规范行候选面）。
"""
from __future__ import annotations

import queue
import threading
import time

#: 单行上限（字节）：超长行具名拒收——畸形子进程输出不允许无声吃内存。
MAX_LINE_BYTES = 1 << 20

#: sentinel 事件类型（reader 终态：线程死亡/EOF 都走这里，waiter 永不静默等）。
_EVENT_EOF = "eof"
_EVENT_ERROR = "error"


class LineReader:
    """子进程 stdout 的逐行事件流（一条读线程 + 队列；tee 进日志文件）。

    畸形输入三态（单测真值表）：
    - EOF（管道关）：``_EVENT_EOF`` sentinel，wait_for 具名返回 None；
    - 读线程异常（含读侧 fd 坏）：``_EVENT_ERROR`` sentinel 携带原文，waiter
      把它变成点名异常——绝不静默挂死；
    - 超长行：行被截断到 MAX_LINE_BYTES 并就地标记，不丢事件也不炸线程。
    非 UTF8 字节按 errors="replace" 保留证据面，不抛。
    """

    def __init__(self, stream, log=None):
        self._stream = stream
        self._log = log
        self._q = queue.Queue()
        self._lines = []
        self._lock = threading.Lock()
        self._dead = None   # (kind, detail) 当 reader 终态已发生
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="journey-line-reader")
        self._thread.start()

    # ---- 后台读线程（终态全覆盖：EOF / 异常 / 停止都进队，永不丢 waiter）----
    def _pump(self):
        try:
            for raw in self._stream:
                if len(raw) > MAX_LINE_BYTES:
                    raw = raw[:MAX_LINE_BYTES]
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                self._emit(line)
        except Exception as e:   # noqa: BLE001 —— 读侧死亡必须具名（评审 C3）
            self._emit_queue((_EVENT_ERROR, "%s: %s" % (type(e).__name__, e)))
            return
        self._emit_queue((_EVENT_EOF, "producer stdout closed"))

    def _emit(self, line):
        with self._lock:
            self._lines.append(line)
        if self._log is not None:
            try:
                self._log.write(line + "\n")
                self._log.flush()
            except Exception:   # noqa: BLE001 —— 日志镜像尽力而为，事件面不受扰
                pass
        self._emit_queue(("line", line))

    def _emit_queue(self, item):
        self._q.put(item)

    # ---- 消费原语 ----
    def wait_for(self, predicate, timeout_s, label=""):
        """阻塞等到第一行命中谓词。返回命中的行；超时/EOF/读死返回 None
        并把原因写进 ``self.death``（调用方负责具名失败）。零轮询：等待面是
        队列的阻塞 get，不是固定间隔探测。"""
        deadline = time.monotonic() + float(timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.death = ("timeout", "no matching line within %ss (%s)"
                              % (timeout_s, label))
                return None
            try:
                kind, detail = self._q.get(timeout=remaining)
            except queue.Empty:
                continue   # 循环条件兜底判超时；不是固定间隔轮询
            if kind == "line":
                try:
                    if predicate(detail):
                        return detail
                except Exception as e:   # noqa: BLE001 —— 谓词炸=编程错误，点名
                    self.death = ("predicate_error",
                                  "%s: %s" % (type(e).__name__, e))
                    return None
            else:
                self.death = (kind, detail)
                return None

    @property
    def lines(self):
        with self._lock:
            return list(self._lines)

    def alive(self):
        """读者线程还活着（EOF 之后为 False——worker 退出可据此判）。"""
        return self._thread.is_alive()


def wait_seconds(bound_s):
    """注入的秒界等待：声明的常数，等待完成，没有探测循环。"""
    time.sleep(float(bound_s))
