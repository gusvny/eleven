# t261005-02 acceptance walkthrough (gen1, integration)

Second walkthrough pass after arbitration ruled tests-fault (gen0 findings) and the
three lane scenarios were fixed and committed (2c6b5bd). Walkthrough base: lane HEAD
`67b4136` (main@e446fb1 merged), working tree clean.

**Verdict: status=ok.** All three ticket scenarios pass on the current tree, the
product face satisfies all four host requirements (verified at the seam), the
scenario fixes are contract precision with no weakening, and the gate's single
remaining red is a pre-existing main-side condition outside this ticket's face
(attribution proven below).

## 1. Per-scenario conclusions

| Scenario | Result | Timing (targeted) | Evidence |
|---|---|---|---|
| `sc_watchdog_self_heal_fires_once` | PASS 8/0 | 0.14s | one cancel naming the session; `status.self_heal` state=fired with `last_cancel` (session/ask/threshold/cancel_accepted/brief_accepted); `self_heal_cancel` alert row; no cancel loop; receipt persists across ticks |
| `sc_watchdog_self_heal_holds` | PASS 11/0 | 0.15s | healthy long turn never cancelled; inside-threshold hold; consumed-briefing hold; no-signal-mirror hold; prose-marker branch fires exactly once; declared off switch → state=off |
| `sc_watchdog_self_heal_config_and_failure` | PASS 17/0 | 0.14s | factory defaults named on read face; malformed values → config_error naming the knob; cross-knob guard (park 45 vs declared long_turn 60, top-level) → config_error naming BOTH knobs; cancel refusal → state=failed + named alert + brief still delivered + no retry; absent-host → held with named no-signal reason |

Independent product probe (my own harness drive on the current tree):
`status.self_heal = {state:"fired", last_cancel:{session_id, ask_id:a1,
ask_source:ledger-ask, ask_has_default:false, threshold_minutes:2,
silence_minutes:3, attempt:1, cancel_accepted:true, brief_accepted:true},
config:{enabled,park_minutes}}` — requirements 1, 2, 4 confirmed green at the
reader's face. Requirement 3 remains charter-level discipline
(`server/session_charter.md` ask-discipline section) + read-only `ask_has_default`
observation; mechanical enforcement on the ask write face is out of this ticket's
write set (executor-panel) — carried as residual risk, unchanged from gen0.

## 2. Test-asset change review (gen0 → gen1, commit 2c6b5bd)

Hunk-by-hunk review of all three scenario diffs. Verdict: contract precision, no
green-light shortcuts.

- `status` now carries `project=` (seam contract; matches all t260928-28 usage).
- `holds`/`sh_state` take `h`+`project` (fixes gen0's NameError).
- `cancels(h, project)` filters the seam-global cancel log BY SESSION — this is the
  correct fix for gen0's cross-branch shared-clock pollution, and it is STRICTER
  than a per-branch reset would have been: branch B's late legitimate fire stays in
  the log and F6 still proves E's fire is the only cross-branch cancel.
- `seed_ask` uses the real ledger vocabulary (`raised_by`, `status:"waiting"` —
  the seam normalizes both, colloquial `pending` never enters the real ledger).
- `config_and_failure` A4: `long_turn_minutes: 60` is now a TOP-LEVEL config key
  (gen0 finding: it was nested under `self_heal` where the loader ignores it), so
  the cross-knob guard is fed a real declaration and genuinely fires.
- C1 re-anchored from `state=unsupported` to "held, never fired/failed + reason
  names the no-signal read". Justified: with the host absent, `hostGone()` nulls
  `ourBriefPending` too, so guard (c) correctly holds before any cancel — the
  product's fail-closed behavior. No coverage lost: the `unsupported` branch
  (cancelTurn face not injected) is locked at L1
  (`tests/self-heal-t261005-02.test.mjs` case 3d: state=unsupported, exactly one
  attempt, receipt kept). I checked the assertion still rejects fired/failed —
  not a silent pass.

## 3. Gate's single red: `t260928-29-executor-charter-identity` — NOT this ticket's face

Gate receipt: 385 run / 384 pass / 1 fail; the fail is B1 "通用模板无执行器身份标记".
This ticket DID touch `server/session_charter.md` (in its write set), so I proved
attribution instead of assuming:

- The scenario's regex split puts the "## 当前在案授权" block (containing `执行器`
  markers) in the GENERIC template section. That block sits before
  `## project:sandbar` at `422d755` (line 122) and `e446fb1` (line 122) — i.e. on
  PRE-ticket main. Static reproduction of B1's exact predicate
  (`"执行器" in generic` under the scenario's split) returns True at `422d755`,
  `e446fb1`, and HEAD alike.
- This ticket's charter addition (English ask-discipline section) contains no
  `执行器` marker; it only shifted the block down 12 lines.
- Conclusion: pre-existing main-side condition, already flagged 歧义 in the gate
  ledger for its own settlement. Not caused by t261005-02; does not block this
  ticket. (Watchdog unit suite also re-run: 31/31 pass.)

## 4. Contrast evidence (gate receipt vs targeted re-run)

Gate receipt for the three scenario names: all green this round but `output_tail`
is empty — no gate-side per-scenario timings exist. Stated as a gap, not
substituted. Targeted re-runs (this segment): fires_once 0.14s, holds 0.15s,
config_and_failure 0.14s (see §1). Targeted runs only; no full suite in this
segment (gate receipt is the full-suite evidence; exactly one targeted batch, per
t260924-09).

## 5. Residual and risks

- Requirement 3 is advisory (charter) at the ask write face; a mechanical
  `default_action` gate would need an executor-panel ticket.
- KI-198 (declared config not hot-reloaded) untouched, consistent with the family;
  KI-196/197 remain open on their own exit paths (bridge status face, named deliver
  refusal) — this ticket delivers the recovery side only, as scoped.
- `t260928-29-executor-charter-identity` B1 red persists on main (pre-existing);
  its owner ticket should settle it — flagged here so it is not lost.
- UI/泳道图渲染: 不适用 — no UI or lane-graph rendering in this ticket; the new
  read face is the watchdog status JSON (verified §1).

## 6. Acceptance checklist

- Per-scenario verdicts: §1. Sediment question: `doc_sediment` want=true, pre-filled
  in the stage JSON. Reverse-sync gate: docs actually read — `docs/README.md`,
  `server/session_charter.md`, `notes/debts/known-issues.md` (KI-196/197/198),
  repo-root `CLAUDE.md`; no claim I read is overturned → `doc_conflicts=[]`.
