#!/usr/bin/env python3
"""sc_timeline_rerun_stats.py — re-run statistics survive the copy change
(t261008-47).

Run directly: python3 integration/t261008-47/sc_timeline_rerun_stats.py (cwd =
repo root), or through the engine venv fallback chain (see the SCENARIOS entry).

Grey-box L2/L3 behaviour contract over the watchdog's public pure functions
(`facts_from_snapshot` + `lane_legs`), offline seconds, zero docker/Temporal/
browser, never touches 3099.

The feared failure mode of t261008-47: the stage-entry Chinese literal
("进入本步（第 N 次）") is the copy the engine writes on every stage entry, and
the inspection watchdog derives the per-ticket re-run round count and each
round's wall time from the timeline. If anything in that chain still keyed on
the human text, anglicizing the copy would silently zero the re-run statistics
while every suite stays green. This scenario pins the real behaviour:

  A  old format — a timeline whose running rows carry the Chinese reason AND the
     structured fields (stage/state/gen) yields the correct round count, entry
     timestamps and per-round wall deltas.
  B  new format — the SAME structured fields with English reasons
     ("Entered step (attempt N)") yield IDENTICAL numbers (round count, entries,
     wall deltas). Copy must never move a statistic.
  C  mixed old+new rows in one timeline (old tickets live on after the change) —
     statistics still derived from the structured fields.
  D  degradation is NAMED, never a silent zero — a snapshot without a timeline
     appends the named note; matched rows with unparseable `at` name it too.
  E  negative / history is data — the old Chinese rows keep working end to end:
     the rerun-rounds leg still fires over them with the same round count as the
     new-format timeline.

Pre-change tree = green already on A (the parser is structured-field-keyed
today); B/C are the regression that must stay green AFTER the copy lands. If B
or C red at the gate, the copy change broke the statistics — reject.
Engine module unimportable = ENV_FAIL exit 2.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)
    return bool(cond)


def section(title):
    print("\n== %s" % title)


def entry(stage, state, gen, reason, at):
    return {"stage": stage, "state": state, "gen": gen,
            "reason": reason, "at": at}


def at_iso(h, m):
    return "2026-10-08T%02d:%02d:00+00:00" % (h, m)


def timeline_rows(fmt, gens, start_h=10, step_min=10):
    """gens = [(gen, minutes_offset)] — reason text follows the format."""
    rows = []
    for gen, off in gens:
        h = start_h + (off // 60)
        m = off % 60
        if fmt == "old":
            reason = "进入本步（第 %d 次）" % gen
        else:
            reason = "Entered step (attempt %d)" % gen
        rows.append(entry("run_integration_tests", "running", gen, reason,
                          at_iso(h, m)))
    return rows


def snapshot_with(timeline, gens=3, extra=None):
    snap = {
        "status": "running", "stage": "run_integration_tests",
        "stage_state": "running", "paused": False, "blocked_reason": "",
        "gens": {"run_integration_tests": gens},
        "timeline": timeline, "meta": {"created": at_iso(9, 0)},
        "results": {},
    }
    if extra:
        snap.update(extra)
    return snap


def main():
    try:
        import inspection_lane_watchdog as w
    except Exception as exc:
        print("ENV_FAIL: engine watchdog module unimportable: %r" % (exc,))
        return 2

    NOW = 11 * 3600.0  # epoch-independent: only deltas matter for wall text

    # ---------- A. old format (Chinese marker rows, structured fields present) --
    section("A old-format timeline (Chinese reason, structured fields)")
    old_tl = timeline_rows("old", [(1, 0), (2, 10), (3, 25)])
    old_facts = w.facts_from_snapshot("t", "p", snapshot_with(old_tl))
    ok(old_facts["suite_rounds"] == 3,
       "old format: round count = 3, got %r" % (old_facts.get("suite_rounds"),))
    ok(len(old_facts["suite_entries"]) == 3,
       "old format: 3 suite entries with parseable at")
    old_wall, old_tail = w._wall_text(old_facts["suite_entries"],
                                      old_facts["suite_entries"][-1] + 900.0)
    ok("10.0min" in old_wall and "15.0min" in old_wall,
       "old format: per-round wall deltas 10min/15min present, got %r" % (old_wall,))

    # ---------- B. new format (English reason, SAME structured fields) ---------
    section("B new-format timeline (English reason, same structured fields)")
    new_tl = timeline_rows("new", [(1, 0), (2, 10), (3, 25)])
    new_facts = w.facts_from_snapshot("t", "p", snapshot_with(new_tl))
    ok(new_facts["suite_rounds"] == old_facts["suite_rounds"],
       "new format: round count identical to old format (%r vs %r)"
       % (new_facts.get("suite_rounds"), old_facts.get("suite_rounds")))
    ok(new_facts["suite_entries"] == old_facts["suite_entries"],
       "new format: suite entry timestamps identical to old format")
    new_wall, _ = w._wall_text(new_facts["suite_entries"],
                               new_facts["suite_entries"][-1] + 900.0)
    ok(new_wall == old_wall,
       "new format: per-round wall text identical to old format (%r)" % (new_wall,))

    # ---------- C. mixed old+new rows (history lives on beside new copy) -------
    section("C mixed old+new rows in one timeline")
    mixed_tl = timeline_rows("old", [(1, 0), (2, 10)]) + \
        timeline_rows("new", [(3, 25), (4, 40)])
    mixed_facts = w.facts_from_snapshot("t", "p", snapshot_with(mixed_tl, gens=4))
    ok(mixed_facts["suite_rounds"] == 4,
       "mixed timeline: round count = 4, got %r" % (mixed_facts.get("suite_rounds"),))
    ok(len(mixed_facts["suite_entries"]) == 4,
       "mixed timeline: 4 suite entries regardless of reason language")

    # ---------- D. degradation is named, never a silent zero -------------------
    section("D named degradation")
    no_tl = snapshot_with([])
    del no_tl["timeline"]
    f2 = w.facts_from_snapshot("t", "p", no_tl)
    ok(any("timeline absent/not a list" in n for n in f2.get("parse_notes", [])),
       "missing timeline -> named note, notes=%r" % (f2.get("parse_notes"),))
    ok(f2["suite_rounds"] == 3,
       "missing timeline: rounds still derived from snapshot.gens (=3), got %r"
       % (f2.get("suite_rounds"),))
    bad_at = timeline_rows("old", [(1, 0)])
    bad_at[0]["at"] = "not-a-timestamp"
    f3 = w.facts_from_snapshot("t", "p", snapshot_with(bad_at))
    ok(any("unparseable" in n for n in f3.get("parse_notes", [])),
       "unparseable at -> named note, notes=%r" % (f3.get("parse_notes"),))

    # ---------- E. history is data: old rows still drive the rerun leg ---------
    section("E rerun-rounds leg fires identically over old and new rows")
    # default threshold fires the rerun-rounds leg when rounds > 3 -> use 4 rows
    thr = w.resolve_thresholds(None)[0]
    old_tl4 = timeline_rows("old", [(1, 0), (2, 10), (3, 25), (4, 40)])
    new_tl4 = timeline_rows("new", [(1, 0), (2, 10), (3, 25), (4, 40)])
    for label, snap in (("old", snapshot_with(old_tl4, gens=4)),
                        ("new", snapshot_with(new_tl4, gens=4))):
        facts = w.facts_from_snapshot("t", "p", snap)
        legs = w.lane_legs(facts, NOW, thr)
        rerun = [l for l in legs if "rerun-rounds" in str(l.get("leg"))
                 or "rerun-rounds" in str(l.get("evidence"))]
        ok(bool(rerun),
           "%s format: rerun-rounds leg still fires over %s reasons"
           % (label, label))
        if rerun:
            ok("4" in str(rerun[0].get("evidence", "")) or "4" in str(rerun[0]),
               "%s format: the leg names the same round count 4" % label)

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
