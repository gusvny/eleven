# Acceptance walkthrough — t261004-29 (executor wakes on answered request / cleared alert)

Role: integration, stage `acceptance_walkthrough` (gen 0). Mechanical gate evidence
(same source as arbitrate): 361 ran / 357 pass / 3 fail-checks / 1 env-red (named,
out of scope). Gate blockers: `t261004-29-wake-self-feed-guard` (this ticket's own
L3 scenario), plus `t261004-14-panel-cap-check-guard` and `t261004-20-test-anchor-brakes`
(attribution confidence ok — other tickets' lanes, not this ticket's red).

## Verdict: FAILED (rework) — one blocker, precisely attributed below

The user-facing journey (host answers a request → executor wakes; alert clears →
executor wakes; every outcome receipted) is implemented and verifiably wired. But the
self-feed-guard scenario — the ticket requirement "The self-feed guard stays: do not
re-deliver our own undigested brief" — is red at the gate, and the red decomposes into
two distinct defects that must be resolved before merge:

### Defect 1 (integration's own, test-asset bug): sc_wake_self_feed_guard D1 fixture never establishes the real journey

`D1-precondition-brief-delivered — prompts=0`. The D1 journey is "the watchdog first
delivers a brief via a tick, THEN the host answers". But in the fixture the seeded
ledger row is consumed as the start() baseline, so `tickOnce()` finds zero new rows and
delivers nothing (`本拍无新账本行`). Consequently `mem.lastRequestId` stays `null`, and
the real guard's rule ③ (exits.ts:222 — keyed on `mem.lastRequestId` →
`ourBriefPending(sessionId, lastRequestId)`) is never armed; the fixture's flip of
`guard.briefPending` has no product meaning (the product has no bare boolean input —
that knob only feeds the stub). D1's second and third failing checks are downstream of
this unrealized precondition. This scenario needs a rework round owned by integration:
arm the guard the way production does (a first accepted delivery that sets
`lastRequestId`, then `ourBriefPending → true`), not via a synthetic boolean.

### Defect 2 (contract divergence, needs arbitration — developer vs L3 contract): receipt semantics for a guard-suppressed wake

- Developer L1 (wake-sources-t261004-29.test.mjs, guard section) pins:
  suppressed ⇒ `attempted=true, woke=false`, reason names the pending brief.
- L3 contract (sc_wake_self_feed_guard D1, and consistent with D3 "refused ensure ⇒
  attempted=false" and sc_wake_on_answer A3 "transport failure ⇒ attempted=false")
  pins: `attempted=true` only when delivery actually reached the prompt face;
  suppressed ⇒ `attempted=false` + named reason.
- Implementation: core.ts `requestWake` wraps every `wakeExecutor` outcome with
  `attempted: true` (core.ts:428), so a suppressed wake is receipted
  `attempted=true, woke=false, reason="上一份简报仍未消化…"`.

The ticket text ("Deliver a receipt that says whether a wake was attempted and why")
admits both readings; the L2/L3 contract layer is integration's declared deliverable,
so today the implementation deviates from the registered contract. This is a one-line
semantic decision either way, but it must be made explicitly, not by loosening either
test. If arbitrate rules the developer semantics correct, the L3 scenario (and the
route/sc_on_answer receipts that build on the shape) is the file that moves; if the L3
contract stands, core.ts's receipt wrapping moves. **I did not touch either side** —
changing the scenario now to green would be the classic green-light shortcut.

### What is verified working (user view, with evidence)

- **Answer → wake**: executor-panel answer endpoint pushes to the watchdog wake route
  only after the answer has landed (api.ts; answer 200 merges the receipt additively;
  a wake failure never loses the answer — A1–A5 all green, gate PASS 0.1s / rerun 0.093s).
- **Cleared alert → wake**: alert-clear synthetic rows join the same wake cycle, once
  per episode, no phantom clear on restart (sc_alert_clear_wake green; L1 UTs
  `first clear delivered` / `re-fire then clear wakes exactly once more` /
  `restart on a clear state emits no phantom clear wake` all pass).
- **Push route + receipts ring**: watchdog `/sandbar-watchdog/api/wake` validates the
  project and request_id, returns an explicit receipt; headless mount mounts nothing and
  does not crash (sc_wake_route_receipt green, gate PASS 0.1s / rerun 0.088s).
- **Guard exists and names its reason in production wiring**: real path
  node.ts:219 `ourBriefPending` → ensureMirror, suppression reason
  `上一份简报仍未消化（我们的队列项 … 还在）——不重发` (exits.ts:225); decision-stage
  rows and redline ticks bypass rules ①② but never ③ (t260929-04 lesson carried).
- **Malformed / untrusted inputs**: panel never trusts the wake response shape
  (non-receipt bodies normalized to explicit failure); watchdog refuses malformed
  push args with named 4xx (D4, E5 green).
- Developer L1 UTs for this ticket: `node --test` on both new test files — 26 tests, 0 fail.

## Test-asset changes review (vs previous rounds)

No test files were weakened this round. The delta vs the design-stage handoff is the
main-sync merge commit a270ce9: `integration/run_scenarios.py` and
`integration/test_anchors.json` were union-merged (scenario registry + anchor manifest);
scenario bodies under `integration/t261004-29/` are byte-identical to the design round
(verified via `git show --stat 19be354` + targeted reruns reproducing the design-stage
expectations, including the deliberately-red D1). No green-light shortcuts found.

## 对照证据 (gate receipt vs targeted rerun, same scenario names)

| Scenario | Gate receipt (out/integration-report-261004-205821.json) | Targeted rerun (this stage) |
|---|---|---|
| t261004-29-wake-on-answer | PASS 0.1s | PASS 0.093s (report out/integration-report-261004-210036.json) |
| t261004-29-wake-route-receipt | PASS 0.1s | PASS 0.088s |
| t261004-29-alert-clear-wake | PASS 0.1s | PASS 0.09s |
| t261004-29-wake-self-feed-guard | FAIL 0.1s (assert_mismatch) | FAIL 0.09s, pass=9 fail=3 (report out/integration-report-261004-205844.json; direct run output in evidence) |

No full-suite rerun was performed this stage (single targeted batch + one direct node
invocation of the red scenario;取证纪律 t260924-09 respected).

## Environment red (named, non-blocking)

`t261004-23-panel-engine-row-old-door` — other ticket's lane, external-supply face,
on the in-register env-red list. Not this ticket's product red.

## 并行期 UI 呈现

不适用 — this ticket touches no UI / lane-graph rendering (wake plumbing only).

## 新故障模式登记建议 (for the KI registrar, not written by me)

- FM: receipt-semantics divergence — the same outcome ("guard-suppressed, nothing
  delivered") is receipted `attempted=true` by the product and `attempted=false` by the
  L3 contract; downstream consumers keying on `attempted` alone will misclassify.
  Repro: `node integration/t261004-29/sc_wake_self_feed_guard.mjs` (D1 checks).
- FM (test asset): a fixture guard-knob (`briefPending` boolean) that no product input
  mirrors let the scenario author believe rule ③ was armed when it was not —
  precondition checks (`D1-precondition-brief-delivered`) fired first and were
  mechanistically independent of the two later failures.

## doc_sediment (收口一问)

want=true (prefill suggestion): target=`docs/design/executor-wake-sources.md`
(category: design), reason: the engine now has two push/pull wake source families
(ledger transitions + alert clears) plus an HTTP push face (`requestWake`) with a
receipt contract (`attempted/woke/reason`) and guard rules ①②③ — cross-ticket engine
behavior a new agent must read before changing watchdog/executor-panel code; today it
exists only in code comments and a notes/ discussion page.

## doc_conflicts (反向同步闸)

None. Docs read this stage: `docs/README.md` (full), grep sweep over `docs/` for
wake/唤醒 claims — only `writing-standard.md` and `panel-list-conventions.md` mention
wake terms, neither makes a contract claim about the wake path. No doc/claim/actual
triples to report; nothing registered into pending-doc-sync.
