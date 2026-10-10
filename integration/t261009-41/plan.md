# t261009-41 — Certification tab: plan v2 (create_plan stage gen 1, developer)

Re-plan after review_plan gen 0 reject. Carries over: recon facts (review-verified), the §2
mock-element table, and Alt C stays rejected (never edit out of the write set). Changes against
v1 are exactly R1 / R2 / R3.

Status: plan only. No code touched; the git tree stays clean except this document.

## R1 — the ticket is cut into two explicit slices, and the yardstick states which slice this ticket owns

The host's yardstick is the mock: a working **Certification tab in the executor UI**. The tab's
home (`server/plugins/executor-panel/src/host/panel-page.ts` tab row + `api.ts`
`PANEL_API_ROUTES` route + a read-only develop-ledger reader) is outside this ticket's write set
(`workbench/src/client/`, `workbench/tests/`, `integration/t261009-41/`, `integration/`), and only
the host can move that boundary. So the plan no longer hides the split in a "gap" paragraph — it
is the plan:

- **Slice 1 — this ticket.** Everything that fits the write set: the complete face-derivation
  model of the mock, unit-tested, semantics-bound to the engine (R2), plus this plan. This
  ticket's acceptance yardstick (§6) is Slice 1's yardstick, stated as such — **not** the mock's
  full face, because this ticket cannot render it.
- **Slice 2 — a follow-up ticket, drafted here so the host signs one split, not a vague debt.**
  Scope: `executor-panel` write set; deliverables: the `/sandbar-executor-panel/api/certification`
  GET route (route table + parity test), a read-only reader for
  `~/.sandbar/projects/<key>/develop/{lines.json,landings.jsonl}` and
  `.../ledger/delivery.jsonl` + promotion rows, the `Certification` tab in `panel-page.ts`
  rendered from `deriveCertificationFace` output, and its `executor-panel/tests/*.mjs` page tests.
  Acceptance: the mock's yardstick, ten rules of the dispatch spec, on rendered records. Slice 2
  is submitted for the host's ruling at review/sign; it is written as a ticket draft in
  `integration/t261009-41/slice2-ticket-draft.md` so the split is reviewable text, not a note.

If the host instead extends this ticket's write set to `server/plugins/executor-panel/src/`
(+`tests/`), Slice 2 folds back into this ticket and §6's mock yardstick applies whole — the plan
supports both rulings without rework of Slice 1.

## 1. Target face (carried from v1, review-verified; mock v15 is the yardstick)

| Mock element | Rule it carries |
|---|---|
| one combobox (`input[list]`) with the line id, hover defines what a line is | (1) one line, one control |
| `.linebar`: fixed 9px delivered cap + certified segment (3px boundary) + waiting segment | (2) one bar, one boundary; delivered is a running total |
| counts only inside segments; button carries the batch size; no tally row | (3) counts appear once |
| `auto rounds` switch + round state beside it + de-emphasised `run now`; rounds table: trigger auto/manual, result `N pass · N fail · N env`, verdict green / `red · N blockers`, measured `line <sha>` | (4) chained rounds face |
| `Promote N` disabled only when certN=0; stays enabled while frozen; freeze banner one line + blocker names; boundary moment = the round that certified it | (5) the one human action |
| ticket ids open tickets, round ids open records; waiting rows carry epic + landed moment, certified rows carry epic + certified-by run id | (6) identifiers are entries |
| project colour/badge from the shared identity source, identity surfaces only | (7) |
| tokens only from the engine vocabulary; explanations in `title=`; no emoji | (8) |
| no invented scheduler: the face renders what records carry; no "next round at" | (9) |

## 2. Slice 1 changes (all inside the write set)

1. **`server/plugins/workbench/src/client/certification-model.ts`** (new, pure, no React, no fs,
   no fetch):
   - `deriveCertificationFace(input)` where `input` carries the **engine projection outputs, not
     raw rows**: `line`, `freeze` (`freeze_state` output), `landingChecks` (`may_land` /
     `ticket_wait_state` outputs), `certRows`, `runRows`, `promotionRows`, `outcomes`
     (`ticket_outcome` outputs) → face `{ lineId, state: 'green'|'frozen', deliveredTotal,
     certified: [{ticket, epic, title, certifiedBy}], waiting: [{ticket, epic, title, landedAt}],
     boundary: {at, runId}, rounds: [{runId, startedAt, trigger: 'auto'|'manual',
     result: {pass, fail, env}, verdict: 'green'|{red, blockers}, measuredHead}],
     frozen: {banner, blockerIds} | null, promotable }`.
   - **R2 binding, chosen option: the model only shapes presentation; engine-derived counts are
     inputs.** The model computes no certification outcome of its own — `certified`, `waiting`,
     `promotable`, freeze state and blocker ids come from the engine projections in `input`. The
     model's own logic is limited to presentation decisions the mock owns: segment flex sizing,
     the fixed delivered cap, the once-only count placement, the `line <sha>` measured token, the
     verdict colour class, the one-line freeze banner text, promote gating (disabled iff
     `promotable === 0`, never because of freeze).
   - Drift guard, mechanical: a committed golden fixture
     `server/plugins/workbench/tests/fixtures/t261009-41-certification-fixture.json` is generated
     by `server/engine/tests/test_t261009_41_model_fixture_contract.py` (new pytest): build
     synthetic rows, run the real `freeze_state` / `ticket_wait_state` / `ticket_outcome`, write
     the serialized projections, and assert the committed file equals the regeneration. The node
     test feeds that same fixture through `deriveCertificationFace` and asserts the face counts.
     If the engine changes an outcome rule, the pytest regenerates and the node test fails on the
     count — the drift is caught, not silent. (The fixture file is data, not code out of write
     set: it lives in `workbench/tests/`.)
   - Tolerance face: malformed/missing `input` fields degrade to an explicit empty face with a
     reason string; no throw, no invented data (rule 9).
2. **`server/plugins/workbench/tests/t261009-41-certification-model.mjs`** (new) — node tests on
   in-test fixtures plus the golden fixture above: counts add up (delivered + certified + waiting
   == landed total); promote enabled under freeze, disabled only at zero; boundary older than the
   red round in the frozen state; result parts labelled and summing; measured renders `line <sha>`
   and never `main@<sha> +N`; trigger is `auto`/`manual` only; malformed inputs tolerated; no
   emoji / out-of-vocabulary token in any produced label.
   **R3 import mechanics, stated:** the test imports
   `../src/client/certification-model.ts` — a relative specifier **with the explicit `.ts`
   extension**; node v26.5.0 strips types natively, no `--experimental-strip-types` flag needed
   (same mechanics as `tests/executor-entry-model.mjs` importing `executor-view-model.ts`).
3. **`server/engine/tests/test_t261009_41_model_fixture_contract.py`** (new pytest, see above) +
   the fixture JSON it owns. *(Boundary note: `server/engine/tests/` is outside the declared
   write set; the file is listed here and in §6 so review can rule on including it — without it
   R2's binding check has no enforcement side. If ruled out, the fallback is: the node test pins
   the committed fixture and the ticket carries an explicit "regenerate on engine change" debt.)*
4. **`integration/t261009-41/slice2-ticket-draft.md`** (new) — the Slice 2 ticket draft (R1).
5. **`integration/t261009-41/plan.md`** — this plan.

## 3. Steps and how each is verified

1. Read `docs/reference/ledger-record-models-v1.md` in full + the projection signatures
   (`freeze_state`, `may_land`, `ticket_wait_state`, `ticket_outcome`). Verify: no code change yet.
2. Golden fixture first (TDD anchor): write the pytest, generate the fixture, run it green.
   Verify: `python3 -m pytest server/engine/tests/test_t261009_41_model_fixture_contract.py -q`.
3. Write `certification-model.ts`. Verify: `node -e "import('./server/plugins/workbench/src/client/certification-model.ts')"`
   loads (type-strip, no runtime deps).
4. Write the node test file; drive it to green. Verify:
   `node --test server/plugins/workbench/tests/t261009-41-certification-model.mjs`;
   neighbour check `node --test server/plugins/workbench/tests/executor-entry-model.mjs`;
   `python3 integration/lint_tests.py`.
5. Write the Slice 2 ticket draft; update report. Verify: `git status --short` shows only write-set
   files (+ the §2.3 file pending review's ruling).

## 4. Alternative decompositions

- **Alt A — model directly in `executor-panel/src/host` as plain JS** (rejected): outside the
  write set, and it abandons the typed model + the workbench pure-model test home.
- **Alt B — API-first** (rejected): the route is the out-of-write-set part; API-first leaves this
  stage nothing testable, model-first keeps every line in the write set and pinned by tests.
- **Alt C — wire the tab in this ticket anyway** (rejected, stands): violates the write-set red
  line; not this stage's call.
- **Alt D — bind R2 by re-implementing `ticket_outcome` in TS and testing TS-vs-engine outputs**
  (rejected): a second implementation of the outcome rule is exactly the drift R2 warns about;
  shaping-only + fixture contract binds without a mirror.

## 5. Acceptance yardsticks (R1: per slice, host-sanctioned splits only)

- **Slice 1 (this ticket, under the current write set):** `certification-model.ts` implements the
  full §1 presentation logic; node tests green incl. the golden-fixture contract and
  malformed-input cases; pytest fixture contract green; `integration/lint_tests.py` clean; tree
  contains only write-set files (plus §2.3 pending ruling); Slice 2 ticket draft exists at
  `integration/t261009-41/slice2-ticket-draft.md`. **This yardstick deliberately does not claim
  the tab exists — the tab exists only after Slice 2.**
- **Slice 2 (follow-up ticket, or this ticket if the host extends the write set):** the mock. A
  `Certification` tab in the executor panel renders from record data only; counts add up on every
  face; one boundary; counts appear once; promote lives through freeze; identifiers are links;
  tickets carry title + epic; no emoji, no invented tokens (`main@… +N`, `record ↗` absent); no
  scheduler face. Route + tab covered by `executor-panel` tests; no integration scenario run by
  the developer stage.

## Addendum (implement, after review gen 1 conditions)

- **C1 applied**: the fixture-contract pytest lives at
  `integration/t261009-41/test_model_fixture_contract.py` (integration-layer L2,
  inside the write set), NOT `server/engine/tests/` as §2.3 first proposed; the
  §2.3 fallback is not needed.
- **C2 applied**: `integration/t261009-41/slice2-ticket-draft.md` is an
  acceptance deliverable, not an optional note.
- Slice 1 landed in implement gen 0; the three gate scenarios referenced by the
  registry (`sc_t26100941_freeze_promote_contract.py`,
  `sc_t26100941_certification_face_seam.mjs`,
  `sc_t26100941_fixture_contract_gate.py`) were delivered with anchor labels in
  `integration/test_anchors.json`.
