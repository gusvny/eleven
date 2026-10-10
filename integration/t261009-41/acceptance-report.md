# t261009-41 — Acceptance walkthrough report (integration, gen 6 re-walk)

Verdict: **pass.** Re-walked at HEAD `3f8c7793` (clean tree; since gen 5 only the main@cc5e2e5
sync landed — a batch of other tickets' squash close-outs and debts/docs notes — plus the
arbitrate gen 1 report commit; `2b402bac`). Zero change to this ticket's assets.

- Targeted reruns on this tree, all green: freeze-promote 16/16, face-seam 26/26, fixture
  pytest 2 passed + gate `ok`, node battery pass/fail 0.
- Gate receipt agrees (face-seam 0.2 s, freeze-promote 0.6 s, fixture-gate 0.6 s, all exit 0).
  This round's three gate blockers — `t261005-03-orphan-probe-reclaim`,
  `t261009-42-bundle-freshness-verdict`, `t260907-10-engine-layout` — are each booked known
  reds in the roster (ledger 命中绿); none is this ticket's product face. t261009-42 is the
  bundle-freshness judge fix the host ruling points at; per the ruling, no local action is
  taken (no rebuild, no entry edit, no manufactured diff).
- Test-asset change audit: none — no UT/integration asset of this ticket changed since the
  audited state.

对照证据 (gate vs targeted rerun): face-seam 0.2 s vs 26/26 ~0.1 s; freeze-promote 0.6 s vs
16/16; fixture-gate 0.6 s vs `2 passed` + `ok`. No full suite run by the walkthrough.

Residual items unchanged: Slice 2 (the actual tab) not dispatched; UI presentation check not
applicable (pure-model slice; the recurring screenshot refusal is a console-side
capture-environment failure); doc_sediment want=false, doc_conflicts none.

---

# t261009-41 — Acceptance walkthrough report (integration, gen 5 re-walk)

Verdict: **pass.** Re-walked at HEAD `6c8f8ff6` (clean tree; the gen-4 scenario call-site fix
is now committed via the arbitrate settle, together with the report addendum — exactly the two
files gen 4 said must ride the commit).

- Gate receipt agrees with the tree: freeze-promote 0.4 s exit 0, face-seam 0.1 s exit 0,
  fixture-gate 0.4 s exit 0; the only gate blocker left is `t260907-10-engine-layout`, a booked
  known red (ledger 命中绿), not this ticket's face.
- Targeted reruns on this tree, all green: freeze-promote 16/16, face-seam 26/26, fixture
  pytest 2 passed + gate `ok`, node battery pass/fail 0.
- Host ruling (bundle freshness) acknowledged and followed: no rebuild performed, no entry-file
  or cosmetic change made to force `lib/` into the diff; `certification-model.ts` is
  deliberately outside the bundle entry graph, and KI-01M4H5BJQ2Q9A0Y7R4T2NB1X8F's gate fix
  (t261009-42) is awaited. This ticket's own prior build receipts (gen 12/13, byte-identical
  digest) are retained as the honest build evidence.

对照证据 (gate vs targeted rerun): freeze-promote 0.4 s vs 16/16; face-seam 0.1 s vs 26/26;
fixture-gate 0.4 s vs `2 passed` + `ok`. No full suite run by the walkthrough.

Residual items unchanged: Slice 2 (the actual tab) not dispatched; UI presentation check not
applicable (pure-model slice); doc_sediment want=false, doc_conflicts none.

---

# t261009-41 — Acceptance walkthrough report (integration, gen 4 re-walk)

Verdict: **pass**, after auditing the round's one gate blocker and its fix.

## Root cause and audit of the gate blocker (`t261009-41-freeze-promote-contract`, exit 1)

Main@4373682 merged the t261009-29 close-out, which moved promotions into the delivery
ledger's one seq space and changed `ticket_outcome` from the two-file legacy shape
`(rows, promotions, ticket, ...)` to the one-list shape `(rows, ticket, is_green,
ticket_record)`. The committed scenario still passed `promotions` positionally, so `T_CERT`
landed in the `is_green` slot — `TypeError: ticket_outcome() got multiple values for argument
'is_green'`. A pure call-site drift from another ticket's landed API change, not a product
fault in this ticket's face.

The fix (currently uncommitted, on the settled tree) drops the dead `promotions` argument in
the scenario; the same one-line call-site migration in the fixture-contract pytest's
`build_fixture_input` is committed as `7d79dd51`, with the one-seq-space comment added.
**Audit: call-site migration, no assertion changed or weakened** — F1's assertion
(`certified_by` survives the freeze) and the fixture's outcome fields are byte-identical; the
contract pytest still passes 2/2 against the real projections, and the node seam still sees the
same fixture. The fix is in this ticket's write set and is the mechanically forced update.

## Verification on the settled tree (all green, repeated ×3 for the drifted scenario)

- freeze-promote-contract: exit 0, `{"total": 16, "failed": []}` ×3.
- face-seam: 26/26; fixture-contract pytest: 2 passed; fixture gate: `ok ... green`;
  node battery: pass 1 / fail 0.

对照证据 (gate vs targeted rerun): freeze-promote 0.4 s / exit 1 at gate time vs exit 0 ×3
post-fix; face-seam 0.1 s vs 26/26 ~0.08 s; fixture-gate 0.4 s vs `2 passed` + `ok`.
No full suite run by the walkthrough (the gate receipt is the round's one set).

## Residual items (unchanged)

Slice 2 not dispatched; UI presentation check not applicable (pure-model slice; the recurring
screenshot refusal is a console-side capture-environment failure); doc_sediment want=false,
doc_conflicts none. The uncommitted scenario call-site fix must ride the worker's commit.

---

# t261009-41 — Acceptance walkthrough report (integration, gen 3 re-walk)

Verdict: **pass.** Re-walked at HEAD `4e6f5100` (arbitrate settle `540a20d6` + main@8e6ae42
sync + round-4 conflict resolution). Asset audit since gen 2:

- `540a20d6` touched only `acceptance-report.md` (+27 lines: landing the gen 2 addendum).
- Main sync brought the t261009-37 squash (executor-panel overview-blocks restructure — it
  touches `panel-page.ts` and its tests, but adds no certification tab and no t261009-41 asset;
  Slice 2 remains unstarted).
- Zero diff on the model, golden fixture, three gate scenarios, fixture pytest, plan, slice-2
  draft.

Targeted reruns on this tree, all green: seam 26/26; fixture pytest 2 passed + gate `ok`;
freeze-promote 16/16; node battery pass/fail 0. Gate receipt agrees (face-seam 0.1 s,
fixture-gate 0.4 s, freeze-promote 0.4 s, exit 0); only gate blocker remains `t260907-10-engine-layout`
(booked known red). Receipt note: the round's `__executor__` line flagged a count fork
(fail detail 4 vs rc 5, not-checked 18 vs 17) — a mechanical receipt self-check artifact of the
round, not a t261009-41 result; all three t261009-41 rows carry explicit exit-0 receipts.

对照证据 (gate vs targeted rerun): face-seam 0.1 s vs ~0.08 s; fixture-gate 0.4 s vs `2 passed`
+ `ok`; freeze-promote 0.4 s vs 16/16. No full suite run by the walkthrough.

Residual items unchanged: Slice 2 not dispatched (the host's ask is user-visible only after it
lands); UI presentation check not applicable (pure-model slice; the recurring screenshot
refusal is a console-side capture-environment failure, not a ticket defect); doc_sediment
want=false, doc_conflicts none.

---

# t261009-41 — Acceptance walkthrough report (integration, gen 2 re-walk)

Verdict: **pass.** Re-walked at HEAD `1e24777f` (arbitrate settle `7dd1a1b5` + round-3
conflict resolution + main@a319363 sync). Nothing in this ticket's asset set changed since the
gen 1 re-walk:

- `7dd1a1b5` touched only `acceptance-report.md` (+42 lines: landing the gen 1 addendum itself).
- `1e24777f` / `a319363b` are the t261009-38 squash and its conflict resolution (engine
  path_gates / agent_activities + that ticket's scenarios) — unrelated to this ticket.
- Zero diff on `certification-model.ts`, the golden fixture, every t261009-41 scenario, the
  fixture-contract pytest and `plan.md`.

Targeted reruns on this tree, all green: seam scenario 26/26; fixture-contract pytest 2 passed +
gate `ok`; freeze-promote 16/16; node battery pass/fail 0. Gate receipt agrees (face-seam 0.1 s,
fixture-gate 0.4 s, freeze-promote 0.4 s, all exit 0); the round's only gate blocker remains
`t260907-10-engine-layout`, a booked known red, not this ticket's face.

对照证据 (gate vs targeted rerun): face-seam 0.1 s vs ~0.08 s; fixture-contract-gate 0.4 s vs
direct `2 passed` + `ok ... green`; freeze-promote 0.4 s vs 16/16. No full suite run by the
walkthrough (the gate receipt is the round's one set).

Residual items unchanged: Slice 2 (the actual tab) not yet dispatched; UI presentation check
not applicable (pure-model slice; this round's screenshot refusal is a console-side
capture-environment failure, not a ticket defect); doc_sediment want=false, doc_conflicts none.

---

# t261009-41 — Acceptance walkthrough report (integration, gen 1 re-walk)

Verdict: **pass.** Re-walked after arbitrate settle (`1592965d`) + main-sync merge (`9916ef9f`);
see the gen-0 report below for the full per-rule audit.

## What changed between gen 0 and this re-walk

1. The B2e pin gen 0 audited as uncommitted is now committed (`1592965d`), byte-identical to
   what gen 0 audited (blob fd314c14 → 38ee1b43, same edit: the partial-freeze case moved to
   B2e "never reads as green"; B6 keeps only out-of-validator-shape inputs). Audit conclusion
   unchanged: contract refinement backed by the model's declared validator, not a green shortcut.
2. Main-sync brought changes to six unrelated workbench test files (`lane-*`,
   `rework-banner-ui`, `status-card-ui`); **no change** to `certification-model.ts`, the golden
   fixture, or any t261009-41 asset.
3. Gate receipt (this round): all three t261009-41 scenarios green (face-seam 0.1 s exit 0,
   fixture-contract-gate 0.4 s exit 0, freeze-promote-contract 0.4 s exit 0). The round's only
   gate blocker is `t260907-10-engine-layout` — a booked red in the known-red roster (ledger
   命中绿), not this ticket's product face.

## 对照证据 (gate vs targeted rerun, this round)

| Scenario | Gate receipt | Targeted rerun |
|---|---|---|
| t261009-41-certification-face-seam | 0.1 s exit 0 | 0.08 s exit 0, `{"total":26,"failed":0}` |
| t261009-41-fixture-contract-gate | 0.4 s exit 0 | contract pytest `2 passed`, gate scenario `ok ... green` |
| t261009-41-freeze-promote-contract | 0.4 s exit 0 | `{"total": 16, "failed": []}` |
| developer node battery | engine pool (not in gate) | `node --test`: pass 1 / fail 0 |

No full suite run by this walkthrough (the gate receipt is the round's one set; targeted reruns
only).

## Residual items (unchanged from gen 0)

- Slice 2 (the actual tab in `executor-panel`) is the user-visible half and is not dispatched
  yet — recommend dispatching from `slice2-ticket-draft.md`.
- UI presentation check: not applicable (Slice 1 renders no UI). This round's screenshot
  refusal is a console-side capture-environment failure (sidebar view icons not found), not a
  defect of this ticket's deliverables.
- doc_sediment: want=false (unchanged). doc_conflicts: none (docs actually read: docs/README.md).

---

# t261009-41 — Acceptance walkthrough report (integration, gen 0)

Verdict: **pass, with two named items for the human reviewer** (the Slice 1 / Slice 2 split,
and an uncommitted scenario-asset edit that was being applied while this walkthrough ran).

## Scope of what was checked

The ticket landed **Slice 1 only** (per the reviewed plan `integration/t261009-41/plan.md`):
the pure face-derivation model `server/plugins/workbench/src/client/certification-model.ts`,
its node tests, the engine-fixture drift-guard pytest, and the Slice 2 ticket draft.
**No tab is rendered anywhere in the executor UI yet** — the tab, its API route and its reader
are Slice 2 (`integration/t261009-41/slice2-ticket-draft.md`), outside this ticket's write set.
Per the dispatch spec's own rule ("the tab renders what the records carry; if the mechanism is
absent, the report says so"), this is recorded here as the ticket's main user-facing fact:
**the host's original ask (a tab to view certification state and certify) is not yet user-visible;
what landed is the complete, contract-tested face model that tab will render.** This split was
reviewed and approved in plan v2 (R1); it is a host-ruling item, not a developer fault.

## Scenario conclusions

| Scenario | Gate receipt | Targeted rerun (this walkthrough) | Conclusion |
|---|---|---|---|
| t261009-41-certification-face-seam | 0.1 s, exit 1, fail×self×assert_mismatch (gate blocker) | direct `node` ×8 (incl. via `/bin/sh -c`, runner-shaped): 26/26 checks ok, exit 0, ~0.08 s | see root cause below — test-asset drift, product model green |
| t261009-41-fixture-contract-gate | 0.4 s, exit 0 | direct: contract pytest 2 passed, `ok fixture-contract gate green` | pass — engine projections and committed fixture agree |
| t261009-41-freeze-promote-contract | 0.4 s, exit 0 | direct: 16/16 checks, `{"total": 16, "failed": []}` | pass — freeze/promote truth table (promote lives through freeze) |
| developer node battery (`t261009-41-certification-model.mjs`) | (engine pool, not in gate) | `node --test`: 1 pass / 0 fail | pass |

### Root cause of the gate red — face-seam

The committed scenario pinned `{freeze: {frozen: true}}` (a freeze record with no identity
fields) as malformed input that must degrade to an empty face. The model deliberately accepts
that shape: `freezeFace` (certification-model.ts:173-183) validates *boolean `frozen` + optional
string identity fields* — the engine's real output shape — and renders it **FROZEN**, with an
empty blocker list. The old expectation was the wrong direction: `emptyFace` carries
`state: 'GREEN'`, so demanding it would read a frozen line as green — a worse failure than the
one the test feared. The current worktree amends the scenario: the partial-freeze case moved to
a new **B2e** check ("partial freeze claim never reads as green") and B6 keeps only inputs
outside the declared validator shape (`freeze: "red"`, `{frozen: true, cause: 42}`,
`{frozen: "yes"}`), each still degrading to a named empty face.

**Test-asset change audit (contract refinement, not a green shortcut):** the change is backed by
the model's declared, documented validator contract (fail-closed: an unreadable freeze record is
never silently read as "not frozen", certification-model.ts:170-172) and by the model's own unit
battery. The conservative direction is preserved and newly pinned. No assertion anywhere was
weakened to pass: B1-B6 all still bite, and the malformed matrix still covers non-boolean,
non-object and ill-typed freeze records.

**Timing note (取证纪律):** the scenario file was being edited during this walkthrough — my first
targeted rerun (18:36:22Z, via `run_scenarios.py --only`) still reported 26 checks / 1 failed;
minutes later the same file under the same runner shape reports 26/26 green, stably across 8
runs. The mid-walkthrough edit matches the arbitrate-gen-0 pin comment inside the file. The
report above judges the **final** on-disk content; the change is uncommitted and goes to the
worker's deterministic commit.

## Mock-yardstick check (rules 1-9, judged on the model's produced face and vocabulary)

- Rule 3 (counts appear once): B1 — delivered + certified + waiting == every engine outcome;
  promotable == certified count. The model subtracts the delivered set from the engine's
  still-"certified" wait states, so the certified side of the bar is exactly what one signature
  promotes — the host's "12 certified / 2 promotable" arithmetic now adds up.
- Rule 5 (the one human action): B2/B2b/B2c — promote is disabled **only** at zero, stays
  enabled while frozen, the banner names the blockers in one line, the boundary names and
  precedes the certifying round.
- Rule 4 (rounds face): B4/B4b/B4e — measured is `line <sha>`, never `main@<sha> +N` (the only
  `main@` occurrence in the model is a comment saying never); trigger is `auto`/`manual` only;
  result parts labelled and summing; red verdict carries its blocker count.
- Rule 8 (no glyph carries meaning): B5 — no emoji/glyph in any produced label; the fixed word
  list (`FACE_WORDS`) is published via `faceVocabulary()` and pinned by test.
- Rule 9 (no invented scheduler): B6 — malformed/missing inputs degrade to a named empty face
  with a reason; no throw, no fabricated data, no "next round at".

**Spec-vs-mock divergence, mock wins (recorded per dispatch contract):** the dispatch spec's
rule 2 says the fact under the bar reads "in main N"; the approved final mock (v15) renders it
as `delivered 10` with the hover explaining "already in main". The model follows the mock
(`delivered`). No action needed; noted so the Slice 2 implementer does not "correct" it back.

## Parallel-period UI presentation check

**Not applicable** — this ticket renders no UI (Slice 1 is a pure model; the tab is Slice 2).
The context-injected screenshot refusal (capture-lane rejected a stale lane build) is consistent
with that: there is no certification tab in this tree to photograph, and none was asserted.

## 对照证据 (gate vs targeted rerun, same scenario names)

| Scenario | Gate receipt | Targeted rerun |
|---|---|---|
| t261009-41-certification-face-seam | 0.1 s exit 1 (26 checks / 1 fail at gate time) | 0.08 s exit 0 (26/26), ×8 stable, final tree |
| t261009-41-fixture-contract-gate | 0.4 s exit 0 | ~0.3 s exit 0, contract pytest "2 passed" |
| t261009-41-freeze-promote-contract | 0.4 s exit 0 | 16/16 ok |
| t261009-41-certification-face-seam (first targeted rerun, mid-edit asset) | — | 0.086 s exit 1, 26/1 — superseded by the final asset, timing kept for the record |

No full-suite run was made by this walkthrough (the gate receipt is the round's one full set;
only `--only` / direct targeted reruns were used).

## 遗留与风险

1. **Slice 2 is the user-visible half and is not scheduled yet.** Until it lands, the host still
   has no tab. Recommend dispatching from `slice2-ticket-draft.md` without waiting.
2. The scenario fix is uncommitted in the worktree; the worker's commit must include it, or the
   gate blocker stays red on the committed tree.
3. The engine-side round-chaining mechanism (dispatch rule 9) is intentionally absent
   (staged separately, t261009-24 tracks the records side); the model renders only what records
   carry — verified by B6, no invented scheduler face.

## doc_sediment

want=false — the durable design facts (what a line is, the mock's ten rules, the validator
contract) live in the approved mock, plan v2 and the model's own documented contract; nothing
here overturns or extends a docs/ reference. `docs/reference/ledger-record-models-v1.md` was
consulted via the catalogue (docs/README.md); its record-family claims were consumed through the
fixture contract, which passed — no drift observed.

## doc_conflicts

Only docs actually read this round: `docs/README.md` (catalogue). No claim in it is overturned
by this ticket's implementation. Empty list.
