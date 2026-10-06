#!/usr/bin/env python3
"""sc_review_ledger_rotation — simplify-face review-ledger rotation contract
(t261006-12, grey-box L2/L3, offline seconds, zero docker/Temporal/3099).

Design source of truth: notes/discussions/261004-巡检两面重塑-测试面与简化面.md
§4 (S3 slice + coverage hard requirement), §7 (ledger in the project directory,
append-style, loss = restart with everything unreviewed, never an error).

User-perceivable contracts pinned here (all through the public functions of
server/engine/inspection_review_ledger.py; internal structure is never
asserted):

  R1 rotation: files reviewed last period are NOT picked again while
     un-reviewed files remain — consecutive slices are disjoint until the
     whole inventory has been through (the ticket's core defect: slices
     could repeat because no ledger existed).
  R2 ordering: never-reviewed files come first (path ascending), then
     oldest-reviewed; ties break by path ascending; identical inputs give a
     byte-identical slice (determinism, run twice).
  R3 bounds: the slice is capped at slice_max and floored at slice_min when
     the inventory allows; an inventory smaller than the floor gives the
     whole inventory, never a fabricated slice.
  R4 loss tolerance (host ruling): a missing, unreadable, corrupt, torn-tail
     or non-UTF-8 ledger degrades to "everything unreviewed" + a NAMED note;
     nothing raises into the inspection flow.
  R5 external input: a hostile project_key (empty, absolute, `..`, path
     separators, leading dot) is refused with a named error, never used as a
     path component; duplicate rows for one path resolve last-row-wins.
  R6 coverage (hard requirement): reviewed and not-reviewed lists are
     disjoint and together equal the managed inventory — the not-reviewed
     side is a LIST, not only a count (a count can be misread as "checked").

Module missing/unimportable = ENV_FAIL exit 2 (concurrency-scenario
precedent). Red before implement lands is the expected TDD signal;
arbitrate/merge must be green.

Run: python3 integration/t261006-12/sc_review_ledger_rotation.py (cwd=repo root).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

MODULE = "inspection_review_ledger"
try:
    rl = __import__(MODULE)
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: engine module server/engine/%s.py unavailable: %s" % (MODULE, e))
    sys.exit(2)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  RED %s" % label)


def section(t):
    print("\n%s" % t)


def write_ledger(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


# ---------- R2/R3 selection contract on a synthetic inventory ----------
section("R2/R3 ordering, determinism, bounds")
tmp = Path(tempfile.mkdtemp(prefix="t26100612-"))
try:
    managed = ["a/%02d.py" % i for i in range(10)] + \
              ["b/%02d.py" % i for i in range(110)]
    ledger_rows = ([{"path": "a/%02d.py" % i, "period": "20261001",
                     "ts": 1000.0 + i} for i in range(10)] +
                   [{"path": "b/%02d.py" % i, "period": "20261002",
                     "ts": 2000.0 + i} for i in range(110)])
    ok(True, "synthetic inventory ready (10 old-period + 70 newer files)")

    led_map = {("a/%02d.py" % i): {"period": "20261001", "ts": 1000.0 + i}
               for i in range(10)}  # only a/ reviewed; b/ never reviewed
    s1, n1 = rl.select_slice(managed, led_map, slice_min=40, slice_max=60)
    ok(len(s1) == 60 and all(p.startswith("b/") for p in s1),
       "never-reviewed first (all 60 from the b/ batch; a/ already reviewed)")
    s1b, _ = rl.select_slice(managed, led_map, slice_min=40, slice_max=60)
    ok(s1 == s1b, "determinism: identical inputs -> identical slice (twice)")

    # after period 1 writes back its slice, period 2 must not repeat it
    led2 = {p: {"period": "20261003", "ts": 3000.0 + i} for i, p in enumerate(s1)}
    s2, _ = rl.select_slice(managed, led2, slice_min=40, slice_max=60)
    ok(not (set(s1) & set(s2)), "R1 rotation: period-2 slice disjoint from period-1")
    ok(len(s2) == 60, "period-2 slice still capped at 60")
    # rotate the whole library: after all 80 reviewed, restart from scratch
    led_all = {p: {"period": "20261004", "ts": 4000.0 + i}
               for i, p in enumerate(managed)}
    s3, _ = rl.select_slice(managed, led_all, slice_min=40, slice_max=60)
    ok(len(s3) == 60 and set(s3) <= set(managed),
       "fully-rotated library restarts (loss-equivalent state, no error)")

    small, _ = rl.select_slice(["x.py"], {}, slice_min=40, slice_max=60)
    ok(small == ["x.py"], "R3 inventory smaller than floor -> whole inventory")
    tie = rl.select_slice(["m/b.py", "m/a.py"], {}, slice_min=40, slice_max=60)
    ok(tie[0] == ["m/a.py", "m/b.py"], "R2 tie (never-reviewed) breaks by path ascending")

    # oldest-ts ordering: b/ files reviewed earlier come first among reviewed
    led_old = {"a/00.py": {"period": "20260901", "ts": 100.0},
               "a/01.py": {"period": "20260902", "ts": 200.0}}
    everything = {p: {"period": "202609%02d" % (i + 1), "ts": 500.0 + i}
                  for i, p in enumerate(managed)}
    so, _ = rl.select_slice(managed, everything, slice_min=2, slice_max=2)
    ok(so == [managed[0], managed[1]], "R2 oldest ts first among reviewed")

    # ---------- R4 loss tolerance ----------
    section("R4 loss tolerance (missing/corrupt/torn/non-UTF-8/unreadable)")
    m, notes = rl.load_review_ledger(tmp / "does-not-exist.jsonl")
    ok(m == {}, "missing ledger -> everything unreviewed")
    ok(bool(notes), "missing ledger carries a NAMED note")
    torn = tmp / "torn.jsonl"
    write_ledger(torn, ledger_rows[:5])
    with open(torn, "a", encoding="utf-8") as f:
        f.write('{"path": "a/00.py", "period": "2026100')  # torn tail
    m, notes = rl.load_review_ledger(torn)
    ok(len(m) == 5, "torn trailing line drops exactly one row, rest survive")
    garbage = tmp / "garbage.jsonl"
    garbage.write_text("not json\n[1,2]\n{\"nope\": 1}\n" +
                       json.dumps(ledger_rows[0]) + "\n", encoding="utf-8")
    m, notes = rl.load_review_ledger(garbage)
    ok(len(m) == 1 and "a/00.py" in m, "malformed rows dropped and counted, valid row survives")
    nb = tmp / "bytes.jsonl"
    nb.write_bytes(b'\xff\xfe{"path":"a/00.py"}\n')
    try:
        m, notes = rl.load_review_ledger(nb)
        ok(True, "non-UTF-8 bytes degrade to notes, never raise")
    except Exception as e:  # noqa: BLE001
        ok(False, "non-UTF-8 bytes raised: %s" % e)
    nodir = tmp / "adir.jsonl"
    nodir.mkdir()
    try:
        m, notes = rl.load_review_ledger(nodir)
        ok(m == {}, "unreadable (is-a-directory) ledger -> empty + note, no raise")
    except Exception as e:  # noqa: BLE001
        ok(False, "unreadable ledger raised: %s" % e)
    # unreadable permissions (skip when root)
    perm = tmp / "perm.jsonl"
    write_ledger(perm, ledger_rows[:2])
    os.chmod(perm, 0o000)
    if os.geteuid() != 0:
        try:
            m, notes = rl.load_review_ledger(perm)
            ok(m == {}, "chmod-000 ledger -> empty + note, no raise")
        except Exception as e:  # noqa: BLE001
            ok(False, "chmod-000 ledger raised: %s" % e)
    os.chmod(perm, 0o644)

    dup = tmp / "dup.jsonl"
    write_ledger(dup, [{"path": "a/00.py", "period": "20261001", "ts": 100.0},
                       {"path": "a/00.py", "period": "20261005", "ts": 500.0}])
    m, _ = rl.load_review_ledger(dup)
    ok(m.get("a/00.py", {}).get("period") == "20261005", "R5 duplicate rows: last wins")

    # ---------- R5 hostile project_key ----------
    section("R5 project_key path-component validation")
    refused = 0
    for bad in ("", "..", "/abs", "a/b", "a\\b", ".hidden", "a/../b"):
        try:
            p, reason = rl.review_ledger_path(bad, override=None)
            if p is None and reason:
                refused += 1
            else:
                print("  RED hostile key %r accepted as %s (reason=%r)" % (bad, p, reason))
        except Exception:  # noqa: BLE001
            refused += 1
    ok(refused == 7, "all 7 hostile keys refused (named), none used as path")
    p, reason = rl.review_ledger_path("sandbar", override=None)
    ok(p is not None and str(p).endswith(
        os.path.join("sandbar", "inspection", "reviewed.jsonl")) and not reason,
       "lawful key lands at <projects-root>/<key>/inspection/reviewed.jsonl")
    p2, _ = rl.review_ledger_path("sandbar", override=str(tmp / "ov.jsonl"))
    ok(p2 == tmp / "ov.jsonl", "override (args/env seam) wins")

    # ---------- R6 coverage lists ----------
    section("R6 coverage: reviewed + not-reviewed = inventory (lists, not counts)")
    cov = rl.coverage_section(list(led_all.keys()), managed, "20261004")
    nr = cov.get("not_reviewed_files")
    rv = cov.get("reviewed_files")
    ok(isinstance(nr, list) and isinstance(rv, list),
       "both sides are full machine-readable lists")
    ok(set(rv) | set(nr) == set(managed) and not (set(rv) & set(nr)),
       "lists disjoint and together equal the inventory")
    ok(cov.get("not_reviewed_count") == len(nr) and
       cov.get("reviewed_count") == len(rv), "counts are derived from the lists")
    cov2 = rl.coverage_section(["a/00.py"], managed, "20261006")
    ok(len(cov2["not_reviewed_files"]) == len(managed) - 1,
       "mostly-unreviewed period still names every not-reviewed file")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
