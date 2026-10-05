# t261005-02 acceptance walkthrough (gen0, integration)

Ticket: A session parked on an unanswered ask must self-heal (bounded cancel path +
visible state face). KIs: KI-196, KI-197, KI-198. Walkthrough done from the user's
view on lane HEAD `9b076b7` (merged with main@422d755), plus uncommitted working-tree
changes to three scenario files that appeared DURING this walkthrough (see §6 —
process finding).

**Verdict: status=failed (rework).** The product face is correct everywhere I could
reach it (manual probe evidence below), but three lane scenarios are still red on
the current tree, all attributed to integration test-asset defects, not product code.
Rework targets are named precisely in §4; they live in `integration/t261005-02/`
(this lane's own write set).

## 1. Per-scenario conclusions (user-view walkthrough)

| Scenario | Result | Evidence |
|---|---|---|
| `sc_watchdog_self_heal_fires_once` | PASS 8/0 (0.13s) | `/tmp/sc_watchdog_self_heal_fires_once.2.out`: one cancel naming the session, receipt `state=fired`, `last_cancel` names session+ask+threshold, `self_heal_cancel` alert row, briefing delivered, no cancel loop on later beats, receipt persists on the read face |
| `sc_watchdog_self_heal_holds` | FAIL 9/2 (0.14s) | C3/D4 "no cancel" assertions count a cancel that belongs to branch B's still-live instance (cross-branch clock leak, §4.1) — product behavior in that leak is CORRECT self-heal |
| `sc_watchdog_self_heal_config_and_failure` | FAIL 14/2 (0.14s) | A4: cross-knob input shape wrong (`long_turn_minutes` nested under `self_heal`, loader ignores it); C1: unreachable branch via this injection (§4.2/4.3) |

Manual product probe (my own harness drive, not a scenario; committed product code,
unmodified): all three ticket requirements verified at the seam —

- Req 1 (bounded judgement + one cancel): probe fired exactly once for
  `p-probe`/ask `a1` at 3min silence vs 2min threshold; `cancel_log` = exactly one
  entry. Hold guards verified in holds A/B (no ask → never; inside threshold → hold).
- Req 2 (visible state face, reader's side): `status.self_heal` returned
  `state=fired`, `last_cancel={session_id, ask_id:a1, ask_source:ledger-ask,
  ask_has_default:false, threshold_minutes:2, silence_minutes:3, attempt:1,
  cancel_accepted:true, brief_accepted:true}`, `config={enabled,park_minutes}` —
  a human sees that it happened, not only that the session resumed.
- Req 4 (declared config, fail-closed, named): probe with
  `self_heal.park_minutes=45` + declared `long_turn_minutes=60` (top-level, correct
  shape) → `config_error` naming BOTH knobs; malformed `park_minutes` values →
  config_error naming the knob (scenario A2/A3 pass).
- Req 3 (ask discipline): delivered as `server/session_charter.md` discipline
  section (no ask without a safe `default_action`) + read-only `ask_has_default`
  observation in the receipt. NOTE: this is advisory discipline, NOT mechanical
  enforcement on the ask write face (executor-panel is outside this ticket's write
  set). Residual risk, §5.

## 2. Test-asset change review (rework rounds → now)

`git status` was clean at walkthrough start; mid-walkthrough the three
`integration/t261005-02/sc_watchdog_self_heal_*.py` files were modified by an
external writer (mtimes 12:47–12:48, while my session owned the workspace). Hunk-by-hunk
review of the diff vs HEAD:

- `status` now passes `project=` (matches seam contract; existing t260928-28
  scenarios all pass it) — contract precision, legitimate.
- harness lifecycle: intermediate `h.stop()` calls removed (one proc, one project
  per branch) — fixes real BrokenPipeError crashes; legitimate.
- holds helpers take `h`/`project` params (fixes NameError crash); legitimate.
- new `seed_ask` uses `raised_by` + `status:"waiting"` — matches the REAL ledger
  vocabulary (seam normalizes `raised_by: r.raised_by || r.by`, status word list is
  `waiting|answered` only). This is precision, not a green-light shortcut: attribution
  is real, and E1 still requires the prose branch to genuinely fire, F6 still counts
  the global cancel log. Verified non-vacuous.
- No weakening found in the external edits. The remaining reds are pre-existing
  scenario design defects, not introduced by the edits.

## 3. Contrast evidence (gate receipt vs targeted re-run)

Gate receipt (injected context): the three scenario names appear in
`__gate_blockers__` (blocked) and `__ledger__` (歧义), with EMPTY `output_tail` and
no per-scenario timings — no gate-side timing data exists for them. Per the
forensics discipline I state that gap instead of substituting cross-scenario
numbers. Targeted re-runs (this walkthrough, same lane tree):

| Scenario | run 1 (HEAD tree) | run 2 (tree + external edits, timed) |
|---|---|---|
| fires_once | fail=4 (status w/o project) | pass=8 fail=0, 0.13s |
| holds | NameError crash | pass=9 fail=2, 0.14s |
| config_and_failure | fail=2 + BrokenPipeError crash | pass=14 fail=2, 0.14s |

Targeted runs only; no full-suite run in this segment (gate receipt is the
full-suite evidence; one targeted batch per defect, per t260924-09).

## 4. Located defects for rework (locate only — not fixed here)

1. `sc_watchdog_self_heal_holds.py` C3/D4: branches share one harness process and
   one injected clock; earlier branches' Watchdog instances KEEP BEATING during
   later `tick`s (reconcile_seconds=60), so branch B legitimately self-heals during
   C's tick and pollutes the cumulative `cancel_log` that C3/D4 assert against
   (debug evidence: C's cancel entry has `sessionId=executor-p-hold-b`). Fix shape:
   per-branch cancel-log baseline (assert deltas) or dispose/reset instances per
   branch. Product behavior in the observed leak is correct.
2. `sc_watchdog_self_heal_config_and_failure.py` A4: the override dict is placed
   under `self_heal`, so `long_turn_minutes: 60` lands INSIDE `self_heal` where the
   loader ignores it — the cross-knob guard is never fed a declared long-turn value
   and never fires. Fix shape: `long_turn_minutes` must be a TOP-LEVEL config key
   (verified in my probe: with the correct shape the guard fires and names both knobs).
3. `sc_watchdog_self_heal_config_and_failure.py` C1: `cancel_fail_next mode=absent`
   sets `stub.present=false`, which ALSO makes `ourBriefPending` return null
   (`hostGone()`), so guard (c) holds BEFORE the cancel is attempted and the face
   goes `idle`, never `unsupported`. The seam has no injection for "cancel face
   absent while the queue mirror is readable", so the scenario's intended branch is
   unreachable. Either add that seam injection or re-anchor the assertion to the
   hold-with-named-reason behavior (fail-closed, arguably the correct product
   behavior when the host is gone).

## 5. Residual risks / debt to carry

- Req 3 is charter-level discipline only; nothing mechanically requires
  `default_action` on the ask write face. If the host wants a mechanical gate, that
  is an executor-panel ticket (out of this write set).
- KI-198 (declared config not hot-reloaded) is untouched by this ticket — the new
  `self_heal` knobs have the same restart-to-apply behavior as the rest of the
  family. Consistent with the existing KI, not a regression; KI-196/197 remain open
  on their own exit paths (bridge status face, named deliver refusal) — this ticket
  delivers only the recovery side, as scoped.
- Process finding, §6.

## 6. Process finding: external writer in an exclusively-owned workspace

The workspace contract grants this stage exclusive occupancy; `git status` was clean
at start, and the three scenario files were modified mid-walkthrough (not by me).
The edits are good fixes (reviewed above) and look like a parallel implement-rework
worker. Flagging for the host: two agents wrote the same worktree inside one stage
window. No data was lost (edits reviewed and preserved; I changed none of them).

## 7. Acceptance checklist items

- 验收报告落结果文件: this file + stage JSON (per-scenario verdicts above).
- 沉淀一问: see `doc_sediment` in the stage JSON (want=true, pre-filled).
- 矛盾核对: docs actually read — `docs/README.md`, `server/session_charter.md`,
  `notes/debts/known-issues.md` (KI-196/197/198 sections), repo-root `CLAUDE.md`.
  No claim I read is overturned by this implementation → `doc_conflicts=[]`.
- UI/泳道图渲染: 不适用 — this ticket changes no UI or lane-graph rendering; the
  new read face is the watchdog status JSON (verified in §1).
