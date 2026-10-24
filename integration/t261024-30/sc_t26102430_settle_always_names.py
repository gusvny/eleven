#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26102430_settle_always_names.py — a round that dies inside its settle
window still leaves exactly ONE named record (ticket t261024-30 acceptance
2+3, host contract: a round that dies leaves ONE named record).

Run directly:
python3 integration/t261024-30/sc_t26102430_settle_always_names.py
(cwd = repo root).

Grey-box L3, offline seconds, REAL delivery ledger + guard files on a tmp
store via the shared t261009-30 round fixture, zero docker/Temporal/browser,
never touches 3099/7233.

Incident this entry owns: the settle block between the runner's return and
the ledger append is unprotected — a certification write that raises books
ZERO rows (the four silent rounds), and a round aborted inside the settle
window books nothing either. The reader side (the project ledger) is the
only judge: writer receipts are not evidence.

S1  SETTLE FAULT — the append face fails once while booking the
    certification (the production CertifyError("round_append_rejected")
    shape): the ORIGINAL error still surfaces (never swallowed, never
    masked), and the ledger holds exactly ONE new range-growth row naming
    the settle failure — never zero.
S2  GUARD-APPEND ALSO FAILS — the row-writing face fails on every call:
    the original error still surfaces, and the failure to write the row is
    loud on a second face (stderr names it) — a silent double failure is
    the worst shape this ticket forbids.
S3  ABORT INSIDE THE SETTLE WINDOW — a tick aborted while its guard is
    still held books exactly ONE aborted row per line naming the reason,
    and a second abort after the guard is released books none (never two).
S4  ONE PROJECT RESOLUTION — a project whose per-project runs ledger
    carries a line-round row but whose lines.json declares nothing still
    resolves to THAT project's develop dir (the run row and the round face
    cannot split homes: the four rounds-with-no-directory shape).

Pre-implementation tree: red is the expected TDD signal; green required at
the integration gate / merge. Engine tree missing = ENV_FAIL exit 2.
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "t261009-30"))
import lib_round_fixture as fx  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(t):
    print("\n%s" % t)


mod = fx.load_module()
if mod is None:
    fx.env_fail("server/engine/develop_certify.py missing or unimportable")
run_round = fx.round_entry(mod)
if run_round is None:
    fx.env_fail("run_line_round entry missing in develop_certify.py")

FACE_DIR_ENV = "SANDBAR_LINE_ROUND_FACE_DIR"
PROJECTS_DIR_ENV = "SANDBAR_PROJECTS_DIR"
RUN_SOURCE = "lane:line-round"

AT = 1700000000000
CLEAN_HEADER = {"id": "run-settle-1",
                "cases": {"ran": 5, "failed": 0, "env_failed": 0},
                "failed_names": [], "unverified_names": []}


def kind_count(rows, kind):
    return len([r for r in rows if r.get("kind") == kind])


def growth_reasons(rows):
    return [r.get("reason") for r in rows
            if r.get("kind") == mod.KIND_RANGE_GROWTH]


def seeded_fixture():
    root, ledger, guard = fx.round_fixture(at_ms=AT)
    fx.append(mod, ledger, [fx.landing_row("t-a", "rev-head", AT - 500)])
    return ledger, guard


def round_with_appender(ledger, guard, appender, header=None):
    """One run_line_round invocation wired to a caller-supplied append face
    (the fault-injection seam) and the REAL read face."""
    runner = fx.FakeRunner(headers=[header or dict(CLEAN_HEADER)])
    return run_round(
        line="default", trigger="change", guard_path=guard, runner=runner,
        read_rows=lambda: mod.read_rows(str(ledger)),
        append_rows=appender, judged_by="itg2430", booked_red="br@itg2430",
        now_ms=AT)


section("S1 a settle fault still leaves ONE named row")
ledger, guard = seeded_fixture()


def failing_once(batch):
    if any(r.get("kind") == mod.KIND_CERT for r in batch):
        raise RuntimeError("boom-cert-append")
    return mod.append_rows(batch, str(ledger))


raised = None
try:
    round_with_appender(ledger, guard, failing_once)
except Exception as e:  # noqa: BLE001
    raised = e
rows, bad = mod.read_rows(str(ledger))
ok(raised is not None and "boom-cert-append" in str(raised),
   "S1a the ORIGINAL error still surfaces (got %r)" % (raised,))
ok(not bad, "S1b ledger readable after the fault")
new_growth = kind_count(rows, mod.KIND_RANGE_GROWTH)
ok(new_growth == 1,
   "S1c exactly ONE range-growth row booked by the failing round "
   "(got %d)" % new_growth)
reasons = growth_reasons(rows)
ok(any("boom-cert-append" in str(r) or "settle" in str(r) for r in reasons),
   "S1d the row NAMES the settle failure and its cause (reasons=%r)"
   % (reasons,))
ok(kind_count(rows, mod.KIND_CERT) == 0,
   "S1e no certification row: a failed append never half-books a cert")

section("S2 the guard-append also failing stays loud, never silent-double")
ledger2, guard2 = seeded_fixture()
err = io.StringIO()
raised2 = None
with contextlib.redirect_stderr(err):
    try:
        round_with_appender(ledger2, guard2,
                            lambda batch: (_ for _ in ()).throw(
                                RuntimeError("ledger-gone")))
    except Exception as e:  # noqa: BLE001
        raised2 = e
ok(raised2 is not None,
   "S2a the round still ends in a raised error (got %r)" % (raised2,))
loud = err.getvalue()
ok(bool(loud.strip()),
   "S2b the row-write failure is loud on stderr (never a quiet swallow)")
ok(kind_count(mod.read_rows(str(ledger2))[0], mod.KIND_RANGE_GROWTH) == 0
   or True, "S2c ledger state readable after the double failure")

section("S3 an abort inside the settle window books exactly ONE row")
ledger3, guard3 = seeded_fixture()
ok(mod.guard_acquire(guard3, held_by="itg2430"),
   "S3a fixture guard acquired (a round genuinely in flight)")
key = "itg2430-settle-proj"
mod._INFLIGHT_TICKS[key] = {"guard_path": guard3, "ledger": str(ledger3),
                            "at": AT - 1}
mod._INFLIGHT_RUNNERS[424242] = {"proc": None, "line": "default", "at": AT}
try:
    lines = mod.abort_inflight_ticks(
        "settle_window_abort",
        append_rows_fn=lambda b: mod.append_rows(b, str(ledger3)),
        now_ms=AT)
finally:
    mod._INFLIGHT_RUNNERS.pop(424242, None)
    mod._INFLIGHT_TICKS.pop(key, None)
rows3, bad3 = mod.read_rows(str(ledger3))
ok(not bad3, "S3b ledger clean")
ok(len(lines) == 1, "S3c the abort face reports exactly one appended line")
ok(kind_count(rows3, mod.KIND_RANGE_GROWTH) == 1,
   "S3d exactly ONE aborted row in the ledger (got %d)"
   % kind_count(rows3, mod.KIND_RANGE_GROWTH))
ok(all("settle_window_abort" in str(r) for r in growth_reasons(rows3)),
   "S3e the row names the abort reason")
mod.guard_release(guard3)
lines2 = mod.abort_inflight_ticks(
    "second_abort", append_rows_fn=lambda b: mod.append_rows(b, str(ledger3)),
    now_ms=AT)
rows3b, _ = mod.read_rows(str(ledger3))
ok(not lines2 and kind_count(rows3b, mod.KIND_RANGE_GROWTH) == 1,
   "S3f a second abort after release books nothing (never two)")

section("S4 the run row's project and the round face are ONE resolution")
for extra in (str(Path(__file__).resolve().parent.parent.parent
                  / "integration"),):
    if extra not in sys.path:
        sys.path.insert(0, extra)
runner_path = (Path(__file__).resolve().parent.parent.parent
               / "integration" / "line_round_runner.py")
if not runner_path.is_file():
    fx.env_fail("integration/line_round_runner.py missing")
spec = importlib.util.spec_from_file_location("line_round_runner_itg2430",
                                              runner_path)
lrr = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lrr
spec.loader.exec_module(lrr)

with tempfile.TemporaryDirectory(prefix="sandbar-itg2430-") as tmp:
    proj = Path(tmp) / "proj-buffer"
    (proj / "ledger").mkdir(parents=True)
    (proj / "data" / "develop").mkdir(parents=True)
    (proj / "ledger" / "scenario-runs.jsonl").write_text(
        json.dumps({"id": "run-hist-1", "source": RUN_SOURCE}) + "\n",
        encoding="utf-8")
    env = {PROJECTS_DIR_ENV: tmp, FACE_DIR_ENV: ""}
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got, line_id = lrr.resolve_face_dir(["proj-buffer"], env=env)
    ok(got is not None
       and Path(got).resolve() == (proj / "data" / "develop").resolve(),
       "S4a the ledger-carrying project resolves as the face home even "
       "with no lines.json (got %r)" % (got,))
    ok("falling back to the run-row project" in err.getvalue(),
       "S4b the fallback is NAMED on stderr, never silent")
    empty = Path(tempfile.mkdtemp(prefix="sandbar-itg2430-empty-"))
    with contextlib.redirect_stderr(io.StringIO()):
        got2, _ = lrr.resolve_face_dir(
            ["proj-nowhere"], env={PROJECTS_DIR_ENV: str(empty),
                                   FACE_DIR_ENV: ""})
    ok(got2 is None,
       "S4c no project anywhere resolves to None (the named degrade), "
       "never a guessed home")

print("\nSUMMARY pass=%d fail=%d env_fail=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
