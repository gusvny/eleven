# Acceptance walkthrough — t261004-29 (gen 1, after arbitrate round 1 + implement rework)

Role: integration, stage `acceptance_walkthrough`, round 2. Lane HEAD `ac73b89`
(main@081ef0a merged; t261004-34 landed on main inside this round).

## Verdict: OK — all four t261004-29 L3 scenarios green; walkthrough passes with notes

### How the gen0 blockers were resolved

Gen0 verdict was failed with two attributed defects. Both are now closed, each by the
right owner:

1. **Receipt-semantics divergence (gen0 Defect 2) — fixed by developer** (commit
   `bb55d82`): a guard-suppressed push is now receipted `attempted=false, woke=false`
   with a named reason, matching the L3 contract (consistent with D3 refusal and
   sc_wake_on_answer A3). The developer L1 battery was updated to the same semantics
   (suppressed ⇒ `attempted=false`, `prompts.length===0`) — this is **contract
   precision, not a green-light shortcut**: the changed UT strengthens the assertion
   (previously it allowed one prompt through; now zero) and adds a new case
   (③b mirror-first suppression with no brief id on record).
2. **Fixture never arms the guard (gen0 Defect 1) — the test-asset bug was mine;
   fixed in this round by integration** (the only write-set change this stage). Two
   edits to integration-owned scenarios, assertions unchanged or strengthened:
   - `sc_wake_self_feed_guard.mjs` D1: the old precondition cranked a tick, but the
     seeded row is consumed as the `start()` baseline, so the tick delivered nothing
     and the guard journey never armed. The first brief now arrives the way
     production briefs arrive — an accepted push delivery (which sets `lastRequestId`
     and turns the mirror face on) — then the second answer is suppressed on top of
     the undigested brief. All four D1 assertions now pass at equal strength
     (`attempted=false` named, `woke=false`, exactly one prompt total).
   - `sc_wake_on_answer.mjs`: since KI-193's credentialed-write gate landed on main
     (t261004-18/-34), every panel write requires the console session credential.
     The journey now presents the same-shaped credentialed cookie (pattern shared
     with t260929-03/t261004-18 — shared-fixture reuse, not duplicated intent; the
     uncredentialed-write-refusal face is t261004-18's dedicated scenario). A5 still
     exercises malformed inputs past the gate and they still get named 4xx and never
     reach the wake face.

### Per-scenario conclusions (targeted rerun receipt, this stage)

| Scenario | Conclusion | Evidence |
|---|---|---|
| t261004-29-wake-on-answer | PASS 13/13 — answer 200 + `wake.attempted=true` once with the answered id; refused second answer wakes nobody; wake-transport failure leaves the answer 200/persisted with `attempted=false` named; garbage receipt normalized; malformed inputs named 4xx, zero wake calls | receipt out/integration-report-261004-212701.json, 0.12s |
| t261004-29-wake-route-receipt | PASS — headless mounts nothing; webServer arrival mounts status+wake with working disposers; non-JSON/missing-field bodies named 4xx | same receipt, 0.094s |
| t261004-29-alert-clear-wake | PASS — clear wakes exactly once per episode; re-fire→clear wakes once more; restart on clear state = no phantom clear | same receipt, 0.089s |
| t261004-29-wake-self-feed-guard | PASS 12/12 — undigested brief suppresses the answer-driven push (`attempted=false`, named reason, no second prompt); clear path delivers queue-mode to the declared session; refusing ensure quoted; malformed args honest; receipts ring auditable | same receipt, 0.087s |

Developer L1 batteries re-verified by me: `wake-sources-t261004-29` +
`wake-on-answer-t261004-29` → 0 fail (implement gen6 additionally reports the wider
watchdog battery 5/5 and panel battery 9/9 green on this tree).

### 对照证据 (gate receipt vs targeted rerun)

The mechanical gate this round produced **no full receipt**: supply assembly failed on
the docker test bench (`SUPPLY_ASSEMBLY_FAILED … STAGE_WAIT … project=sandbar-test-integ`;
dsh container `Exited (1)`, `ERR_INVALID_TYPESCRIPT_SYNTAX`) — a supply-side red, named,
0 scenarios ran, not this ticket's product surface (all four scenarios here are offline
ro-pool, zero docker). Gate-side per-scenario timings are therefore unavailable this
round; no cross-scenario numbers are substituted. The targeted rerun receipt above is
the standing evidence, and the previous full-gate receipt (gen0,
out/integration-report-261004-205821.json) is on file for trend comparison. Handover
for the mechanical worker: re-run the gate with the standard口径 once the bench
recovers (command in handover_runs).

### Test-asset changes review (vs previous rounds)

- `bb55d82` (developer): L1 semantics aligned to the arbitrated contract, one new
  guard case added — reviewed line by line, no weakening.
- `integration/t261004-29/sc_wake_self_feed_guard.mjs`, `sc_wake_on_answer.mjs`
  (this stage, by me): fixture-only corrections described above; no assertion was
  deleted or loosened; the check names are unchanged except D1-precondition, which
  now asserts the stronger shape (`attempted===true && woke===true && prompts===1`).
- Anchor manifest union verified intact: 8 entries (4 × t261004-29, 4 × t261004-34)
  in `integration/test_anchors.json`; scenario registry entries unchanged in
  `integration/run_scenarios.py`.

### 并行期 UI 呈现

不适用 — this ticket touches no UI / lane-graph rendering (wake plumbing only).

### 新故障模式登记建议 (for the KI registrar, not written by me)

- Cross-ticket contract collision class: a merged security gate (KI-193 credentialed
  writes) silently 401'd every L3 scenario that drives panel writes through the API
  handle without credentials; the scenarios failed with the gate's own message, which
  made attribution easy, but no cross-lane check forces scenarios to re-run against a
  new main contract before merge. Worth a debt note: "panel-write L3 fixtures must
  share one credentialed-request helper so future gate changes land in one place".

### doc_sediment (收口一问)

want=true (prefill): target=`docs/design/executor-wake-sources.md` (category design),
reason: two wake source families (ledger transitions + alert clears) plus the HTTP
push face (`requestWake`) with the receipt contract (`attempted/woke/reason`) and
guard rules ①②③ + the mirror-first leg are cross-ticket engine behavior a new agent
needs before changing watchdog/executor-panel code; today it lives only in code
comments and a notes/ discussion page.

### doc_conflicts (反向同步闸)

None. Docs actually read: `docs/README.md` (gen0, full); this round a targeted sweep
over `docs/` for `requestWake` / `wake-worthy` / `alert clear` /
`sandbar-watchdog/api/wake` — zero hits, so no doc makes a claim this implementation
could overturn. No pending-doc-sync entries.

### 遗留与风险

- The docker bench supply failure is the segment-level red to clear before the next
  full gate; the dsh container's `ERR_INVALID_TYPESCRIPT_SYNTAX` looks like a stale
  image vs current tree, i.e. a supply rebuild, not a lane defect.
- Stale lane-level integ lock (dead pid) had to be cleared twice this round before
  targeted runs could start — recurring harness wart, worth a debt note.
- Wake receipts (`attempted=true/false`) now have a single arbitrated meaning across
  L1/L3; downstream consumers should read `attempted` as "delivery reached the prompt
  face".
