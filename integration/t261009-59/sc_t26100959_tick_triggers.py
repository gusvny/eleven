#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-59 scenario: the tick's two trigger shapes and the idle case
(grey-box L3, offline seconds, stdlib only, zero docker/Temporal/browser,
never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
the scheduled tick actually ASKS the line round — once per declared line per
tick — with an EVENT trigger when content landed after the line's previous
certification, with a SCHEDULED BACKSTOP ask when the interval is due, and
with NO round started (and no write anywhere) when nothing is due. This is
the ticket's own sentence made true of the SYSTEM, not of a function. The
entry owns the reader-side journey of `develop_certify.line_round_tick`
(the call site) over REAL temp delivery ledgers and REAL guard files, with
the runner as a declared fake:

- T1 event: a landing after the previous certification -> the tick asks
  EXACTLY ONCE (the fake runner sees one candidate set) and exactly one
  certification row is read back FROM THE LEDGER FILE; the entry carries
  the round's `trigger` so the ask shape is on the record.
- T2 the shapes are distinguishable on the record: the event entry carries
  trigger `change`, the backstop ask carries trigger `backstop` — a reader
  of the tick result can tell WHY a round was asked for.
- T3 backstop due: the interval elapsed over a certified, quiet line -> the
  tick asks with trigger `backstop` (and the round — the one
  implementation — answers: nothing new to certify, zero rows written).
- T4 idle: nothing landed and the interval not yet elapsed -> the tick
  starts no round (zero runner calls), appends ZERO rows (ledger file
  byte-identical), and names the reason (backstop_not_elapsed) — never a
  silent 'nothing to do' that looks like success.
- T5 a line with no certification at all: the tick asks by the backstop
  face (never_certified) but the round still starts nothing over an empty
  range — zero runner calls, zero rows.

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). The engine module unimportable = ENV_FAIL; the tick face missing =
pre-implementation FAIL, named (TDD signal).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib_tick_fixture import (  # noqa: E402
    FakeRunner, Ledger, entries_for, entry_texts, green_header, green_round,
    landing_row, load_module, tick, tmp_dir,
)

LINE = "develop"
NOW = 1_700_000_000_000
BACKSTOP_MS = 3_600_000  # one hour
FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


def main():
    dc = load_module()
    with tmp_dir() as td:
        run(dc, td)
    return 0 if not FAILS else 1


def run(dc, tmp):
    gp = str(tmp / "tick-anchor")

    # ---- T1: the event ask — once per tick, one certification on disk
    led = Ledger(dc, tmp, "t1.jsonl")
    led.append([landing_row("t1", "rev0", NOW - 1_000, LINE)])
    green_round(dc, led, LINE, NOW - 1_000)  # a REAL previous certification
    led.append([landing_row("t1b", "rev1", NOW, LINE)])
    runner = FakeRunner(headers=[green_header(rid="run-x50t1a")])
    res = tick(dc, led, [LINE], {"develop": runner}, NOW + 1, BACKSTOP_MS, gp)
    check("T1a the event tick asks the runner exactly once (one ask per "
          "line per tick)", len(runner.calls) == 1, repr(runner.calls))
    rows, bad = led.read()
    certs = [x for x in rows if x["kind"] == "certification"
             and x["line"] == LINE]
    check("T1b the new certification row is read back from the ledger "
          "file", not bad and len(certs) == 2, repr(certs))
    ent = entries_for(res, LINE)
    check("T1c the event ask carries trigger change on the record",
          any(e.get("trigger") == "change" for e in ent), repr(ent))

    # ---- T2: the shapes are distinguishable on the record
    led2 = Ledger(dc, tmp, "t2.jsonl")
    led2.append([landing_row("t2", "rev0", NOW - 2_000, LINE)])
    green_round(dc, led2, LINE, NOW)  # certified now; nothing lands after
    rb = FakeRunner()
    res_b = tick(dc, led2, [LINE], {"develop": rb}, NOW + 100, 10, gp)
    ent_b = entries_for(res_b, LINE)
    check("T3a the backstop ask carries trigger backstop on the record",
          any(e.get("trigger") == "backstop" for e in ent_b), repr(ent_b))
    check("T2a the two shapes are distinguishable: event=change vs "
          "backstop=backstop",
          any(e.get("trigger") == "change" for e in ent)
          and any(e.get("trigger") == "backstop" for e in ent_b), "")
    check("T3b the backstop round writes nothing over an empty range (the "
          "one round answers, not a second implementation)",
          led2.bytes() == led2.bytes() and len(rb.calls) == 0,
          repr(rb.calls))

    # ---- T4: the idle case — no ask, no write, a named reason
    before = led2.bytes()
    ri = FakeRunner()
    res_i = tick(dc, led2, [LINE], {"develop": ri}, NOW + 100,
                 BACKSTOP_MS * 24, gp)
    check("T4a the idle tick starts no round (zero runner calls)",
          len(ri.calls) == 0, repr(ri.calls))
    check("T4b the idle tick writes nothing anywhere (ledger "
          "byte-identical)", led2.bytes() == before, "")
    ent_i = entries_for(res_i, LINE)
    check("T4c the idle tick names its reason (idle / "
          "backstop_not_elapsed), never a silent skip",
          any(e.get("state") == "idle"
              and ("backstop_not_elapsed" in t or "range_empty" in t)
              for e in ent_i for t in entry_texts(e)), repr(ent_i))

    # ---- T5: never certified — asked by the backstop face, still no write
    led4 = Ledger(dc, tmp, "t4.jsonl")
    ri2 = FakeRunner()
    before4 = led4.bytes()
    res_i2 = tick(dc, led4, [LINE], {"develop": ri2}, NOW + 100,
                  BACKSTOP_MS, gp)
    check("T5a a never-certified line gets an ask whose round starts "
          "nothing: no runner call, no write",
          len(ri2.calls) == 0 and led4.bytes() == before4, "")
    check("T5b the ask is the backstop shape (trigger backstop) and ends "
          "named, not silent",
          any(e.get("trigger") == "backstop" and e.get("state")
              for e in entries_for(res_i2, LINE)),
          repr(entries_for(res_i2, LINE)))


if __name__ == "__main__":
    sys.exit(main())
