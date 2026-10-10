#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-59 scenario: the failure surface at the tick's call site
(grey-box L3, offline seconds, stdlib only, zero docker/Temporal/browser,
never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
a line the tick cannot round stays a NAMED, operator-visible entry — never
a swallowed error, never a silent 'nothing to do' — one broken line never
takes the tick's other lines down, the held slot is left exactly as found,
the production configuration faces refuse malformed values by name, and the
call site adds no bookkeeping of its own to the delivery ledger. This entry
owns the reader-side journey of `develop_certify.line_round_tick` (the call
site) plus its declared configuration faces over REAL temp ledgers and REAL
guard files:

- F1 missing line declaration: a named entry comes back, nothing raises
  out of the tick (the rest of the tick keeps working).
- F2 corrupt delivery-ledger line: a named entry, no crash.
- F3 runner missing: a named runner_missing entry; the delivery ledger is
  byte-identical (a tick that cannot reach a round never writes ledger
  rows; could_not_run rows belong to a round that ran).
- F4 guard held by another holder: the guard file is left byte-identical,
  ZERO rows are appended, and the join is named on the entry (spec 3: the
  tick never starts a second round, never pre-empts).
- F5 one broken line does not kill the tick: two declared lines, the first
  ask fails loud — the second line still gets its certification row on
  disk, the broken line is recorded by name, the tick returns a whole
  result whose summary an operator can read.
- F6 malformed backstop configuration: the production env face refuses a
  non-int / non-positive value BY NAME (never guessed); and a non-int
  value that reaches the tick must not blow the whole tick up (see the
  stage report for the FINDING this check carries).
- F7 no new state: after a fully successful tick the delivery ledger holds
  only the round's own record kinds — no tick bookkeeping rows.

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). The engine module unimportable = ENV_FAIL; the tick face missing =
pre-implementation FAIL, named (TDD signal).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib_tick_fixture import (  # noqa: E402
    DeclarationMissing, FakeRunner, Ledger, entries_for, entry_texts,
    green_header, green_round, landing_row, load_module, tick, tmp_dir,
)

LINE = "develop"
OTHER = "release"
NOW = 1_700_000_000_000
BACKSTOP_MS = 3_600_000
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

    # ---- F1: missing declaration surfaces by name, raises nothing
    led = Ledger(dc, tmp, "f1.jsonl")
    try:
        res = tick(dc, led, DeclarationMissing("declaration missing: x"),
                   None, NOW, BACKSTOP_MS, gp)
        f1 = True
    except Exception as e:  # the tick must keep the rest of the tick working
        res, f1 = None, False
        print("  tick raised: %r" % (e,))
    check("F1a a missing declaration comes back as a named entry, not an "
          "exception out of the tick", f1 is True, "")
    body = str(res)
    check("F1b the entry names the declaration failure",
          "declaration" in body.lower(), body[:400])

    # ---- F2: a corrupt ledger line is named, not swallowed
    led2 = Ledger(dc, tmp, "f2.jsonl")
    led2.append([landing_row("f2", "rev0", NOW - 1_000, LINE)])
    with open(led2.path, "a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
    try:
        res2 = tick(dc, led2, [LINE], None, NOW, BACKSTOP_MS, gp)
        f2 = True
    except Exception as e:
        res2, f2 = None, False
        print("  tick raised: %r" % (e,))
    check("F2a a corrupt ledger line is a named entry, no crash out of the "
          "tick", f2 is True, "")
    check("F2b the corruption is named on the payload (malformed ledger "
          "wording)", "malformed" in str(res2).lower(), str(res2)[:400])

    # ---- F3: runner missing — named, ledger untouched
    led3 = Ledger(dc, tmp, "f3.jsonl")
    led3.append([landing_row("f3", "rev0", NOW - 1_000, LINE)])
    green_round(dc, led3, LINE, NOW)
    led3.append([landing_row("f3b", "rev1", NOW, LINE)])
    before3 = led3.bytes()
    res3 = tick(dc, led3, [LINE], None, NOW + 1, BACKSTOP_MS, gp)
    check("F3a a missing runner is a named entry on the payload",
          any("runner" in t.lower()
              for e in entries_for(res3, LINE) for t in entry_texts(e)),
          repr(entries_for(res3, LINE)))
    check("F3b the tick that cannot reach a round writes ZERO ledger rows",
          led3.bytes() == before3, "")

    # ---- F4: guard held — byte-identical guard, zero rows, named join
    led4 = Ledger(dc, tmp, "f4.jsonl")
    led4.append([landing_row("f4", "rev0", NOW - 1_000, LINE)])
    green_round(dc, led4, LINE, NOW)
    led4.append([landing_row("f4b", "rev1", NOW, LINE)])
    guard = dc.guard_acquire(gp, "someone-else")
    check("F4pre the fixture actually holds the slot", guard is not None, "")
    gf = Path(gp).parent / "delivery-guard.json"
    before4g = gf.read_bytes() if gf.is_file() else b""
    before4l = led4.bytes()
    res4 = tick(dc, led4, [LINE], {"develop": FakeRunner()}, NOW + 1,
                BACKSTOP_MS, gp)
    after4g = gf.read_bytes() if gf.is_file() else b""
    check("F4a the tick leaves the guard file byte-identical",
          after4g == before4g, "")
    check("F4b the tick appends ZERO rows while the slot is held",
          led4.bytes() == before4l, "")
    check("F4c the held slot is named on the entry (guard_held / joined)",
          any(("guard_held" in t or "joined" in t)
              for e in entries_for(res4, LINE) for t in entry_texts(e)),
          repr(entries_for(res4, LINE)))
    dc.guard_release(gp)

    # ---- F5: one broken line never kills the tick's other lines
    led5 = Ledger(dc, tmp, "f5.jsonl")
    led5.append([landing_row("f5a", "rev0", NOW - 1_000, LINE),
                 landing_row("f5b", "rev0", NOW - 1_000, OTHER)])
    green_round(dc, led5, LINE, NOW)
    green_round(dc, led5, OTHER, NOW)
    led5.append([landing_row("f5a2", "rev1", NOW, LINE),
                 landing_row("f5b2", "rev1", NOW, OTHER)])
    calls = {"n": 0}

    def runner(candidate_repos):
        calls["n"] += 1
        if calls["n"] == 1:  # the first line's ask fails loud
            raise dc.CertifyError("runner_boom_first_line")
        return green_header(rid="run-x50f5")

    res5 = tick(dc, led5, [LINE, OTHER], {"develop": runner,
                                          "release": runner},
                NOW + 1, BACKSTOP_MS, gp)
    rows5, bad5 = led5.read()
    names = {c["line"] for c in rows5 if c["kind"] == "certification"}
    check("F5a the second line still gets its certification row",
          not bad5 and OTHER in names, repr(names))
    check("F5b the broken line is recorded by name on the payload",
          any("runner_boom_first_line" in t
              for e in entries_for(res5, LINE) for t in entry_texts(e)),
          repr(entries_for(res5, LINE)))
    check("F5c the tick still returns a whole result with a readable "
          "summary", isinstance(res5, dict)
          and "line_round_tick" in str(res5.get("summary", "")),
          repr(res5)[:200] if res5 else "None")

    # ---- F6: malformed backstop configuration refused by name
    named = ""
    try:
        dc.backstop_ms_from_env({"SANDBAR_LINE_BACKSTOP_MS": "abc"})
    except dc.CertifyError as e:
        named = str(e)
    check("F6a the env face refuses a non-int backstop BY NAME",
          "backstop" in named and "int" in named, repr(named))
    named = ""
    try:
        dc.backstop_ms_from_env({"SANDBAR_LINE_BACKSTOP_MS": "-5"})
    except dc.CertifyError as e:
        named = str(e)
    check("F6b a non-positive backstop is refused BY NAME too",
          "positive" in named, repr(named))
    led6 = Ledger(dc, tmp, "f6.jsonl")
    led6.append([landing_row("f6", "rev0", NOW - 1_000, LINE)])
    green_round(dc, led6, LINE, NOW)
    try:
        res6 = tick(dc, led6, [LINE], {"develop": FakeRunner()}, NOW + 100,
                    "not-a-number", gp)
        check("F6c a non-int backstop reaching the tick does not blow the "
              "whole tick up (named per line, rest of result intact)",
              isinstance(res6, dict) and len(res6.get("lines", [])) == 1,
              repr(res6)[:300])
    except Exception as e:
        check("F6c a non-int backstop reaching the tick does not blow the "
              "whole tick up (named per line, rest of result intact)",
              False, "escaped as %r" % (e,))

    # ---- F7: no new state — the ledger holds only the round's own kinds
    led7 = Ledger(dc, tmp, "f7.jsonl")
    led7.append([landing_row("f7", "rev0", NOW, LINE)])
    r7 = FakeRunner(headers=[green_header(rid="run-x50f7")])
    tick(dc, led7, [LINE], {"develop": r7}, NOW + 1, BACKSTOP_MS, gp)
    rows7, bad7 = led7.read()
    kinds = {x["kind"] for x in rows7}
    allowed = {"landing", "certification", "range_growth", "freeze",
               "could_not_run", "freeze_change"}
    check("F7a the call site adds no bookkeeping of its own (only the "
          "round's own record kinds on the ledger)",
          not bad7 and kinds <= allowed, repr(sorted(kinds)))


if __name__ == "__main__":
    sys.exit(main())
