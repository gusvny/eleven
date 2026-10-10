# t261009-50 plan — the tick actually runs the line round (gen 1, rework)

Stage: create_plan (developer), 2nd pass. No code changed in this stage.
Rework against review gen 0: R1 (write-set boundary) and R2 (`tick_trigger`
duplicated `should_certify`) addressed; minor comments 1, 2 and 4 folded in.

## Problem

`run_line_round` (t261009-30) is reachable only from tests and scenarios. The
production tick — the `sandbar-dispatcher-scan` Schedule firing
`DispatcherScanWorkflow` (server/engine/workflows.py) — does nothing for any
line. This ticket puts the call site in production and pins the two trigger
shapes plus the idle case.

## What already exists (reused, never reimplemented)

- `develop_certify.run_line_round(...)` — the round, its guard, its chaining,
  its checkout refusal. The call site calls it; it is the only implementation.
- `develop_certify.should_certify(trigger, rows, line, guard_held,
  now_ms, backstop_ms)` — **the** per-tick decision (guard refusal,
  `range_non_empty` event, `never_certified`/`backstop_elapsed` backstop,
  `range_empty`/`backstop_not_elapsed` idle). Per review R2 the tick face
  calls THIS function; no new decision helper is added.
- `develop_line.load_lines(project_key)` — declared lines
  (`<develop_dir>/lines.json`); missing/unreadable raises named
  `LineDeclarationError`.
- `DispatcherScanWorkflow._ledger_note` — the engine-scope ledger surface
  an operator can already read.

## Design

### Where the hook lives, and the write-set question (review R1)

The tick body is `DispatcherScanWorkflow.run` (workflows.py). File IO and a
suite runner subprocess may not run in workflow code (that class's stated
determinism contract), so the round runs in an activity, called inside a new
`workflow.patched(LINE_ROUND_PATCH_ID)` block (same replay-safe pattern as
`WORKER_RECONCILE_PATCH_ID`).

The issued write set contains no file that hosts the tick (`scan_schedule.py`
is the governance CLI; `dispatcher_loop.py` is the dsh-side scan). The plan
therefore needs two edits outside the issued set:

- `server/engine/activities.py` — one import + one `ALL_ACTIVITIES` line;
- `server/engine/workflows.py` — the patched block (~10 lines) calling the
  activity, `line_rounds` in the return dict, one ledger-note line.

Per the review, this boundary belongs to the issuer, not to developer or
reviewer. **This plan requests the write set be widened by exactly these two
files**; if the issuer declines, the ticket as specified ("it hooks the tick
that exists") is unimplementable and goes back to the dispatcher for
re-scoping — nothing in this plan silently works around that. Everything else
below is inside the issued set and stands regardless.

To keep the out-of-set delta minimal and mechanical, the tick face's body,
pure seams, tests and docs all live in `develop_certify.py` (in set); the two
out-of-set files only wire it (registration + one patched call).

### The tick face (develop_certify.py, in-set)

One new public face `line_round_tick(...)` with injected seams
(`load_lines`, `read_rows`/`append_rows`, `runner`, `guard_path` root,
`now_ms`), plus a thin `@activity.defn line_round_tick_activity` wrapper.

Per declared line, exactly once per tick:

1. Read ledger rows; malformed lines → named entry `ledger_has_malformed_lines`,
   tick continues with the other lines.
2. Ask the one decision function:
   `go, why = should_certify("backstop", rows, line, guard_held(guard_path),
   now_ms=now_ms, backstop_ms=backstop_ms)` — `"backstop"` is the superset
   trigger, so its existing reasons already cover all three shapes:
   - `range_non_empty` → event; pass `trigger="change"` to `run_line_round`
     (the reason distinguishes the shapes on the record, alongside the
     round's own `trigger` field);
   - `never_certified` / `backstop_elapsed` → pass `trigger="backstop"`;
   - `False, range_empty` / `backstop_not_elapsed` → idle: skip the line,
     write nothing (spec 2);
   - `False, guard_held` → still call `run_line_round` (its own join rule
     returns `joined`), so the guard is left exactly as found, zero rows
     written (spec 3). Either way `run_line_round` remains the only place
     that re-runs the decision at the moment of acting.
   There is exactly one implementation of the decision in the module — this
   is a call, not a mirror.
3. `resolve_runner(line)`: returns a callable built from the declared runner
   command, or None → named `runner_missing` entry. **Operator surface only:
   the entry goes into the activity result (workflow log + the single
   per-tick ledger-note summary); it never becomes a delivery-ledger row** —
   `could_not_run` rows belong to a round that ran, not to a tick that could
   not reach one. With no runner until t261009-46, every tick carries one
   bounded summary line (one per tick, not one per line) naming the lines
   that could not run — visible, never silent, never noisy (review minor 2).
4. Each `CertifyError` from `run_line_round` (stale guard holder, unreadable
   ledger, refusal) is caught per line and returned as a named entry; one
   broken line never aborts the scan tick's other duties (spec 4).
5. The activity returns `{"lines": [...], "summary": "..."}`; the workflow
   logs it, `_ledger_note`s the one-line summary, and adds `line_rounds` to
   its return payload. That result is all the state the call site keeps
   (spec 5): no new ledger, no new Schedule, no new bookkeeping.

Backstop interval: module constant `LINE_BACKSTOP_MS` (default 24 h) with
env override `SANDBAR_LINE_BACKSTOP_MS` (non-int → named `CertifyError`,
never guessed). The line declaration is the natural per-line home but
`develop_line.py` is out of the write set — follow-up noted.

### Reader-side acceptance path (review minor 1)

An operator verifies a tick with:

```
python3 server/admin.py call event_ledger '{"op":"list","limit":5}'   # engine-scope scan notes
```

or the Temporal UI on workflow `dispatcher-scan` (schedule
`sandbar-dispatcher-scan`, `describe` via `scan_schedule.py`): each tick's
`scan/done` note names the line-round summary, and the workflow result's
`line_rounds` key carries the per-line entries. The unit tests pin the
activity's returned entries and the summary string, so the read-back face is
tested, not just produced.

## Steps

1. develop_certify.py: `LINE_BACKSTOP_MS`, `backstop_ms_from_env()`,
   `resolve_runner()`, `line_round_tick()` (calls `should_certify`, then
   `run_line_round`; never re-implements either) + activity wrapper.
2. activities.py + workflows.py: the two-file wiring named under R1
   (requires the widened write set; mechanical, review-row sized).
3. scan_schedule.py: docstring sentence — the tick now also runs the
   declared lines' rounds.
4. server/tools/dispatcher_loop.py: unchanged (dsh-side scan, not the
   Temporal tick); stated in handover.
5. Tests: `server/engine/tests/test_t261009_50_line_round_tick.py` (below).
6. Static checks: `python3 -m py_compile` on touched files;
   `python3 integration/lint_tests.py`.

## Tests (unit only; the integration gate runs scenarios elsewhere)

Pinned on the public face `line_round_tick` (per review R2 — not on internal
helpers, which no longer exist):

- event shape: landing after previous certification → round asked with
  `trigger="change"`, entry records the reason;
- backstop shapes: never certified / interval elapsed → `trigger="backstop"`;
- idle: quiet line inside the interval → zero appends anywhere, `skipped`
  entry with reason;
- guard pre-held → `joined`, guard file byte-identical, zero rows appended;
- one line failing loud (runner raises `CertifyError`) → other lines still
  run; failure recorded by name;
- missing `lines.json` / corrupt `lines.json` / corrupt delivery-ledger line
  → named entries, tick survives, never a silent skip;
- `runner_missing` → named entry in the result only, delivery ledger
  untouched, summary names the line;
- env: `SANDBAR_LINE_BACKSTOP_MS` unset / valid / non-int → named, no
  guessing;
- malformed inputs for every injected seam (rule: external-input consumers
  carry malformed-input tests).

## Acceptance criteria

- `grep -rn run_line_round server integration` matches a production call
  site reached from the scan workflow.
- Exactly one implementation of the tick decision (`should_certify`) and of
  the round (`run_line_round`) in the module — the tick face calls both, adds
  neither.
- Both trigger shapes and the idle case pinned by tests; distinguishable on
  the record (round `trigger` + reason).
- A tick with nothing due appends nothing anywhere.
- Every call-site failure has a name and a tested operator read-back
  (activity result → workflow log + one `scan/done` ledger note per tick);
  the ticket-report part of the tick still completes.
- Unit suite green; py_compile + lint_tests clean; no integration entry run
  in this segment.

## Alternative cuts (considered, rejected)

1. Hook inside `scan_tickets_report_impl` (activities.py) — no workflow
   change, but it buries the round inside a report activity: the round's
   retries/timeouts would share the report's budget and a line failure could
   distort the ticket report. Wrong layer; rejected.
2. A second scheduler loop in `server/tools/dispatcher_loop.py` — creates a
   second trigger cadence beside the Temporal Schedule, exactly what "it
   hooks the tick that exists" forbids. Rejected.
3. A new `tick_trigger()` helper deciding event/backstop before calling the
   round (the gen-0 cut) — re-implements `should_certify` and would drift;
   rejected on review R2 in favour of calling `should_certify("backstop", …)`
   and mapping its existing reasons to the trigger string passed on.

## Out of scope (spec 6)

No round-internals change, no landing/promotion, no new Temporal Schedule,
no lane-version opt-in (t261009-46). L3 tick-path scenario: integration's
asset, designed at the gate per review minor 3; the tick face stays
seam-injectable for it.
