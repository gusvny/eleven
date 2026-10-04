# Acceptance walkthrough — t261004-29 (gen 2, final confirmation round)

Role: integration, stage `acceptance_walkthrough`, round 3. Lane HEAD `e3c5374`
(main@38a6219 merged; t261004-28 landed on main inside this round). Working tree
clean; the gen1 fixture corrections are settled in HEAD (commit 2380d7a).

## Verdict: OK — this ticket is green on every receipt this round; walkthrough passes

### Per-scenario conclusions

| Scenario | Gate receipt (221046, 367 ran) | Handover targeted (224735) | This stage targeted (224908) |
|---|---|---|---|
| t261004-29-wake-on-answer | PASS 0.1s | PASS | PASS 0.093s |
| t261004-29-wake-route-receipt | PASS 0.1s | PASS | PASS 0.088s |
| t261004-29-alert-clear-wake | PASS 0.1s | PASS | PASS 0.09s |
| t261004-29-wake-self-feed-guard | PASS 0.1s | PASS | PASS 0.088s |

All four journey families hold on the settled tree: answer→wake with the additive
receipt; refused second answer wakes nobody; alert-clear wakes once per episode with
no phantom clear on restart; the wake route validates and degrades honestly; the
self-feed guard (ledger rule ③ + the mirror-first push leg) suppresses re-delivery
onto an undigested brief with a named reason. Developer batteries re-confirmed green
by implement gen8 on this same tree (watchdog 5/5, panel 9/9, caps violations=0).

### The reds this round — none belong to this ticket (attribution)

- Gate receipt's single FAIL: `t260907-10-engine-layout` (0.7s) — the ledger already
  carries it as the one ambiguous item (歧义); other ticket's lane, not ours.
- The handover full-gate re-run (224734, exit 1, serial-recheck authoritative) shows
  10 FAILs + 1 ENV_FAIL across 414 entries — a **wider口径 than the gate's 367**
  (it picked up the registry union from main's new landings) and it **raced the
  concurrent gate** (its own footer notes the race; gate timings show −1267s
  unattributed queueing). Cross-check against the gate receipt: 8 of the 10 red names
  are not even in the gate's口径; the two that are (`metrics-donut-dom`,
  `t260907-10-engine-layout`) PASS / stay-known-ambiguous respectively under the
  gate's own serial-ish execution. All 10 names are browser/DOM/engine-family
  scenarios owned by other tickets; zero `t261004-29-*` entries are red on any
  receipt. Disposition of those reds belongs to their owning lanes, not this
  acceptance; I flag the race (a handover full run should not fire while the gate is
  executing) as a harness debt in 遗留与风险.

### Test-asset changes review (vs previous rounds)

No test file changed this round: `git status` clean; the only delta vs gen1 is the
worker-settled main-sync commit `e3c5374` (anchors union), verified intact — 4 ×
t261004-29 scenario anchors present alongside main's t261004-28 union (scenarios 496,
engine_tests 201 per implement gen8). No weakening, no green-light shortcuts.

### 并行期 UI 呈现

不适用 — this ticket touches no UI / lane-graph rendering (wake plumbing only).

### doc_sediment (收口一问)

want=true (unchanged prefill from gen1): target=`docs/design/executor-wake-sources.md`
(category design), reason: two wake source families (ledger transitions + alert
clears), the HTTP push face `requestWake`, the arbitrated receipt contract
(`attempted` = delivery reached the prompt face; suppressed ⇒ `attempted=false` +
named reason), and guard rules ①②③ + the mirror-first leg are cross-ticket engine
behavior a new agent needs before changing watchdog/executor-panel code; today it
lives only in code comments and a notes/ discussion page.

### doc_conflicts (反向同步闸)

None. Docs actually read: `docs/README.md` (gen0, full); targeted sweeps in gen1 and
this round over `docs/` for `requestWake` / `wake-worthy` / `alert clear` /
`sandbar-watchdog/api/wake` — zero hits; no doc makes a claim this implementation
could overturn. No pending-doc-sync entries.

### 遗留与风险

- Harness debt: the handover full-gate re-run raced the concurrent gate and ran a
  wider口径 than the gate — its 10 reds are un-attributable noise for this ticket but
  poisoned the receipt; a serialized, gate-口径 handover run is the fix (mechanical
  segment owns it).
- `t260907-10-engine-layout` remains the ledger's single ambiguous red — other
  ticket's disposition.
- The docker-bench supply failure of the previous round did not recur (gate ran 367
  with zero env-red this round).

参考 docs：docs/README.md（gen0 全读）；gen1/gen2 定向清扫无命中。
