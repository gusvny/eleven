#!/usr/bin/env python3
"""Unit battery for the explicit plant handshake (t261011-22 spec §5).

The parent scenario (integration/t261009-52/sc_fixture_leak_brakes.py) acts on
the brake's one-line `PLANTED:` handshake instead of polling the tree. The
line-parser and the bounded waiter are unit-owned here with stub streams —
no real subprocess, no repo writes.

Ordering contract (review comment 3): the brake writes the file, flushes it
to disk, and only THEN prints the line — the parent acting on the line can
never observe a half-written fixture. The waiter also DRAINS the child's
stdout (the old face left the PIPE undrained: minutes of polling plus a
latent pipe-full block).
"""
import importlib.util
import io
import sys
import unittest
from pathlib import Path

INTEG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INTEG))

_spec = importlib.util.spec_from_file_location(
    "sc_fixture_leak_brakes",
    str(INTEG / "t261009-52" / "sc_fixture_leak_brakes.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class FakeProc:
    def __init__(self, text=""):
        self.stdout = io.StringIO(text)

    def poll(self):
        return 0


class FakeClock:
    """Deterministic clock: each call advances by `step`."""

    def __init__(self, start=0.0, step=0.0):
        self.now = start
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


class ParsePlantLine(unittest.TestCase):
    def test_valid_line(self):
        self.assertEqual(mod.parse_plant_line("PLANTED: integration/x/f.py\n"),
                         "integration/x/f.py")

    def test_chatty_output_never_parses(self):
        for line in ("ok    L17 some finding", "ERROR something",
                     "LINT done: 0 error / 0 warn", "", "\n", None, 42,
                     "PLANTED-FORMATTED: x", "planted: x", "PLANTED: "):
            self.assertIsNone(mod.parse_plant_line(line), repr(line))

    def test_prefix_only_line_is_none_not_crash(self):
        self.assertIsNone(mod.parse_plant_line("PLANTED:\n"))


class WaitForPlant(unittest.TestCase):
    def test_acts_on_the_line(self):
        hit, reason = mod.wait_for_plant(
            FakeProc("baseline output\nLINT scoped run\n"
                     "PLANTED: server/engine/tests/test_zz_x.py\nmore\n"))
        self.assertIsNone(reason)
        self.assertEqual(hit, "server/engine/tests/test_zz_x.py")

    def test_child_exit_before_line_is_named(self):
        hit, reason = mod.wait_for_plant(FakeProc("only baseline\n"))
        self.assertIsNone(hit)
        self.assertIn("child-exited", reason)

    def test_injectable_bound_fires_and_is_named(self):
        # a child that keeps talking (or hangs) but never plants: the clock
        # steps past the bound while chatter lines still arrive, and the
        # failure NAMES the bound that fired
        hit, reason = mod.wait_for_plant(
            FakeProc("chatter\nchatter\nchatter\n"),
            clock=FakeClock(step=10.0), bound_s=30)
        self.assertIsNone(hit)
        self.assertIn("bound-expired after 30s", reason)

    def test_zero_bound_fires_immediately(self):
        hit, reason = mod.wait_for_plant(FakeProc("PLANTED: x\n"),
                                         clock=FakeClock(step=1.0), bound_s=0)
        self.assertIsNone(hit)
        self.assertIn("bound-expired after 0s", reason)

    def test_empty_stream_is_child_exit_not_hang(self):
        hit, reason = mod.wait_for_plant(FakeProc(""))
        self.assertIsNone(hit)
        self.assertIn("child-exited", reason)


if __name__ == "__main__":
    unittest.main()
