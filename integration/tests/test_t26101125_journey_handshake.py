#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-25 journey handshake helper — unit battery (fake streams only).

Covers ``integration/t260924-04/lib_journey_handshake.py``:
- happy path: a producer line matching the predicate is returned (blocking
  queue read, zero fixed-interval polling);
- timeout with no matching line: named ``death`` ("timeout", ...), None return;
- EOF (producer stdout closed): named sentinel death, never a hang;
- reader-thread death (read side raises): named ``error`` death carrying the
  original exception — the reviewer's dead-tee face (a dead tee thread would
  otherwise fill the pipe and deadlock the worker as a hang);
- oversized line: truncated at MAX_LINE_BYTES, event preserved, thread alive;
- non-UTF8 bytes: decoded with errors="replace" (evidence kept, no throw);
- predicate that raises: named ``predicate_error`` death;
- tee logging: matched and unmatched lines are mirrored to the log handle;
  a logging failure never breaks the event stream;
- wait_seconds: the injected bound sleeps the declared amount (clock-based).

Offline seconds, real threads on in-memory/fake streams, zero docker/Temporal/
network, never executes an integration entry.
"""
import importlib.util
import io
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lhs_t1125_under_test",
    REPO / "integration" / "t260924-04" / "lib_journey_handshake.py")
lh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lh)


class FakeStream:
    """iter-able of raw bytes lines, with an optional exception at the end."""

    def __init__(self, lines, tail_exc=None, delay=0.0, hold_open=0.0):
        self._lines = [ln if isinstance(ln, bytes) else ln.encode("utf-8")
                       for ln in lines]
        self._tail_exc = tail_exc
        self._delay = delay
        self._hold_open = hold_open

    def __iter__(self):
        return self._gen()

    def _gen(self):
        for ln in self._lines:
            if self._delay:
                time.sleep(self._delay)
            yield ln
        if self._tail_exc is not None:
            raise self._tail_exc
        if self._hold_open:
            # producer still alive, just quiet: the reader must hit its own
            # deadline, not the stream's EOF
            time.sleep(self._hold_open)


def is_started(line):
    return "JOURNEY workflow started" in line


# ---- happy path ----

def test_matching_line_returned():
    r = lh.LineReader(FakeStream(["noise\n", "JOURNEY workflow started x\n",
                                  "JOURNEY workflow finished x\n"]))
    got = r.wait_for(is_started, 5.0, "started")
    assert got == "JOURNEY workflow started x"
    fin = r.wait_for(lambda l: "workflow finished" in l, 5.0, "finished")
    assert fin == "JOURNEY workflow finished x"


def test_first_matching_line_wins_over_later_noise():
    r = lh.LineReader(FakeStream(["JOURNEY workflow started a\n",
                                  "JOURNEY workflow started b\n"]))
    assert r.wait_for(is_started, 2.0) == "JOURNEY workflow started a"


# ---- named terminal states (never a silent hang) ----

def test_timeout_names_itself():
    r = lh.LineReader(FakeStream(["unrelated\n"], hold_open=10.0))
    assert r.wait_for(is_started, 0.2, "started") is None
    assert r.death[0] == "timeout" and "started" in r.death[1]


def test_eof_is_named_not_hung():
    r = lh.LineReader(FakeStream(["unrelated\n"]))
    assert r.wait_for(is_started, 5.0) is None
    assert r.death[0] == "eof"
    assert not r.alive()


def test_reader_error_is_named_with_cause():
    r = lh.LineReader(FakeStream(["ok\n"],
                                 tail_exc=OSError("read side died")))
    assert r.wait_for(lambda l: "never" in l, 5.0) is None
    assert r.death[0] == "error" and "read side died" in r.death[1]


def test_predicate_error_is_named():
    def boom(_):
        raise ValueError("bad predicate")
    r = lh.LineReader(FakeStream(["x\n"]))
    assert r.wait_for(boom, 5.0) is None
    assert r.death[0] == "predicate_error" and "bad predicate" in r.death[1]


def test_empty_stream_eof_immediately():
    r = lh.LineReader(FakeStream([]))
    assert r.wait_for(is_started, 1.0) is None
    assert r.death[0] == "eof"


# ---- malformed input faces ----

def test_oversized_line_truncated_event_kept():
    huge = b"x" * (lh.MAX_LINE_BYTES + 10) + b"\n"
    r = lh.LineReader(FakeStream([huge, "JOURNEY workflow started\n"]))
    got = r.wait_for(is_started, 5.0)
    assert got == "JOURNEY workflow started"
    first = r.lines[0]
    assert len(first) == lh.MAX_LINE_BYTES   # truncated, thread unharmed


def test_non_utf8_bytes_replaced_not_thrown():
    r = lh.LineReader(FakeStream([b"\xff\xfe junk\n",
                                  "JOURNEY workflow started\n"]))
    assert "junk" in r.lines[0]
    assert r.wait_for(is_started, 5.0) is not None


# ---- tee logging face ----

def test_lines_mirror_to_log_and_log_failure_is_swallowed():
    log = io.StringIO()
    r = lh.LineReader(FakeStream(["a\n", "JOURNEY workflow started\n"]), log=log)
    r.wait_for(is_started, 5.0)
    assert log.getvalue() == "a\nJOURNEY workflow started\n"

    class BadLog:
        def write(self, *_):
            raise OSError("log died")
    r2 = lh.LineReader(FakeStream(["JOURNEY workflow started\n"]),
                       log=BadLog())
    assert r2.wait_for(is_started, 5.0) is not None


# ---- the injected bound ----

def test_wait_seconds_sleeps_the_declared_bound():
    t0 = time.monotonic()
    lh.wait_seconds(0.15)
    assert time.monotonic() - t0 >= 0.14
