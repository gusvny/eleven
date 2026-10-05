# t261005-02 acceptance walkthrough (gen2, integration)

Third walkthrough pass. Base: lane HEAD `1423a4f` (main@3fcdef8 merged via ca97c6c),
working tree clean. New since gen1: main brought t261004-30 (one-shot executor
sessions), which touches the SAME watchdog files this ticket changed (config.ts,
node.ts, harness.mjs) — the conflict resolution is the main thing this pass verifies.

**Verdict: status=ok.** All three ticket scenarios pass on the merged tree, the
self-heal semantics survived the merge byte-for-byte where it matters, the merged-in
one-shot face is orthogonal to self-heal (no shared state, no shared fire path), and
the gate's single red remains the proven pre-existing main-side charter-identity
condition.

## 1. Per-scenario conclusions

| Scenario | Result | Timing (targeted) | Evidence |
|---|---|---|---|
| `sc_watchdog_self_heal_fires_once` | PASS 8/0 | 0.17s | one cancel naming the session; `status.self_heal` state=fired, `last_cancel` names session/ask/threshold with cancel/brief accepted; alert row; no cancel loop; receipt persists |
| `sc_watchdog_self_heal_holds` | PASS 11/0 | 0.16s | healthy long turn never cancelled; inside-threshold hold; consumed-briefing hold; no-signal hold; prose-marker branch fires exactly once; off switch → state=off |
| `sc_watchdog_self_heal_config_and_failure` | PASS 17/0 | 0.16s | defaults named on read face; malformed values → config_error naming the knob; cross-knob guard (park vs declared long_turn) fires naming both; cancel refusal → failed + named alert + brief delivered + no retry; absent host → explicit named hold |

Independent product probe on the merged tree: `status.self_heal = {state:"fired",
last_cancel:{session_id, ask_id:a1, ask_source:ledger-ask, ask_has_default:false,
threshold_minutes:2, ...cancel_accepted:true, brief_accepted:true}, config:{...}}`.
Requirements 1/2/4 confirmed at the reader's face; requirement 3 remains charter
discipline + read-only `ask_has_default` (unchanged residual).

## 2. Merge-conflict review (67b4136 → 1423a4f) — self-heal vs one-shot

- `config.ts`: merge ADDS the `one_shot` block (own parse, own fail-closed unknown-key
  guard) and appends `one_shot` to the top-level unknown-key whitelist. The `self_heal`
  block, its parse rules, and the cross-knob guard (`park_minutes` vs declared
  `long_turn_minutes`) are untouched — verified by reading the full config diff and by
  the still-green config scenario (A2/A3/A4 all pass through the REAL
  `parseWatchdogConfig` via the harness seam).
- `node.ts`: additions are one-shot-only (makeOneShotRunner, session-create IO, the
  one-shot turn prompt). `cancelTurn` / `ourBriefPending` / `hasDefault` (the
  self-heal IO face from this ticket) show no changes in the diff.
- `one-shot.ts` never references `self_heal`/`selfHeal`; `self-heal.ts`/`core.ts`
  never reference `one_shot`. The two faces share only the config family and the
  watchdog process — no shared fire path, so one cannot trigger or suppress the other.
  Interaction risk noted: a one-shot session is NOT the declared `executor_session`,
  so guard (a)'s attribution filter means self-heal will never cancel a one-shot unit —
  correct by construction (one-shot units are bounded by their own lock/prompt timeout).
- Charter: main's 3fcdef8 rewrote the pre-sign protected-path check (b); this ticket's
  ask-discipline section is intact. The new one-shot persona paragraph landed inside a
  `## project:` section, NOT the generic template.

## 3. Test-asset change review (gen1 → gen2)

- Arbitrate commit `3ef68f6` added only `acceptance-walkthrough-gen1.md` (my own
  gen0/gen1 reports are now tracked in the lane tree). No test-asset code changed.
- New upstream test files (`t261004-30/sc_executor_one_shot_session.py`,
  `one-shot.test.mjs`, `test_t261004_30_executor_oneshot.py`) are another ticket's
  face — not reviewed in depth, not touched by this lane.
- Watchdog unit suite on the merged tree: 32/32 pass (31 prior + 1 from the one-shot
  merge batch).

## 4. Gate's single red — attribution unchanged

Gate: 386 run / 385 pass / 1 fail (`t260928-29-executor-charter-identity` B1, ledger
歧义). Re-checked on the merged tree: the scenario's exact predicate (`执行器` in the
generic template section under its regex split) is still True, caused by the
pre-existing `## 当前在案授权` block sitting before `## project:sandbar` (now line
145) — present on pre-ticket main (422d755/e446fb1, gen1 evidence) and brought in by
main, not by this ticket. The one-shot charter addition did NOT enter the generic
template (verified: `一次性执行器会话` not in generic split). Not this ticket's face.

## 5. Contrast evidence (gate receipt vs targeted re-run)

Gate receipt for the three names: green with empty `output_tail` — no gate-side
per-scenario timings exist; gap stated, not substituted. This segment's targeted
timed runs: fires_once 0.17s, holds 0.16s, config_and_failure 0.16s. Targeted runs
only, one batch, no full suite in this segment.

## 6. Residual and risks

- Requirement 3 is advisory at the ask write face (charter + `ask_has_default`
  observation); a mechanical `default_action` gate needs an executor-panel ticket.
- KI-198 untouched (consistent config-family behavior); KI-196/197 open on their own
  exit paths, as scoped.
- `t260928-29` B1 red persists on main; owner ticket should settle it.
- UI/泳道图渲染: 不适用 — no UI or lane-graph rendering; the new read face is the
  watchdog status JSON (verified §1).

## 7. Acceptance checklist

Per-scenario verdicts §1; `doc_sediment` want=true pre-filled in the stage JSON;
reverse-sync gate: docs read this pass — `docs/README.md` (index),
`server/session_charter.md`, `notes/debts/known-issues.md` (KI-196/197/198),
`docs/reference/code-review-checklist.md` (changed by the merge — B11 added, no
claim overturned by this ticket), repo-root `CLAUDE.md`; `doc_conflicts=[]`.
