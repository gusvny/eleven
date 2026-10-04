# Acceptance walkthrough — t261004-29 (gen 3, confirmation round 4)

Role: integration, stage `acceptance_walkthrough`, round 4. Lane HEAD `940d3e0`
(main@d3468bf merged before verification; working tree clean).

## Verdict: OK — this ticket's faces are green on gate and targeted receipts; the round's reds are all out-of-ticket

### Per-scenario conclusions (对照证据)

| Scenario | Gate receipt (225948, 367 ran) | Targeted rerun this stage (230049) |
|---|---|---|
| t261004-29-wake-on-answer | PASS 0.1s | PASS 0.093s |
| t261004-29-wake-route-receipt | PASS 0.1s | PASS 0.09s |
| t261004-29-alert-clear-wake | PASS 0.1s | PASS 0.088s |
| t261004-29-wake-self-feed-guard | PASS 0.1s | PASS 0.088s |
| t260907-10-engine-layout (context check) | PASS (not in gate FAIL list) | PASS 0.749s |

All four wake-journey families hold on the merged tree (answer→wake with additive
receipt; refused second answer wakes nobody; alert-clear wakes once per episode, no
phantom clear on restart; wake route validates and degrades honestly; self-feed guard
suppresses re-delivery onto an undigested brief with a named reason).

### Reds this round — attribution

- Gate single FAIL: `t261004-26-panel-flake-stability` — the ledger itself names it
  ambiguous (歧义=t261004-26-panel-flake-stability, 命中红=无); other ticket's lane
  (its name is its owner), zero t261004-29 entries red anywhere.
- The previous round's `t260907-10-engine-layout` red was resolved by arbitrate round 3
  (commit 396fcd0): one line in `integration/t261004-28/sc_carrier_verbatim_port_guard.py`
  gained the declared `engine-venv-compat` marker on a lawful single-sided old-path
  fallback leg. Reviewed line by line: this is **contract precision** (the scanner's
  declared exemption marker), not a green-light shortcut — the fallback chain itself is
  unchanged. Verified: targeted rerun of engine-layout passes (0.749s).

### Test-asset changes review (vs previous rounds)

Only two tree deltas since gen2, both reviewed: the arbitrate marker line above, and
the main-sync merge `940d3e0` (t261004-29 anchors verified intact alongside main's
d3468bf notes landing — notes/, outside every test face). No weakening, no deletions.

### 并行期 UI 呈现

不适用 — this ticket touches no UI / lane-graph rendering (wake plumbing only).

### doc_sediment (收口一问)

want=true (unchanged prefill from gen1/gen2): target=`docs/design/executor-wake-sources.md`
(category design), reason: two wake source families (ledger transitions + alert
clears), the HTTP push face `requestWake`, the arbitrated receipt contract
(`attempted` = delivery reached the prompt face; suppressed ⇒ `attempted=false` +
named reason), and guard rules ①②③ + the mirror-first leg are cross-ticket engine
behavior a new agent needs before changing watchdog/executor-panel code; today it
lives only in code comments and a notes/ discussion page.

### doc_conflicts (反向同步闸)

None. Docs actually read: `docs/README.md` (gen0, full); targeted sweeps in gen1/gen2
over `docs/` for `requestWake` / `wake-worthy` / `alert clear` /
`sandbar-watchdog/api/wake` — zero hits; no doc makes a claim this implementation
could overturn. No pending-doc-sync entries.

### 遗留与风险

- Harness wart (recurring, 3rd occurrence): the lane-level integ lock is left behind
  by dead/killed processes and once by a still-alive concurrent segment run — each
  time a manual `rm` of the stale lock was needed before targeted runs could start.
  The lock message does tell the pid, but nothing auto-reaps a provably-dead holder;
  mechanical segment owns the fix.
- `t261004-26-panel-flake-stability` stays the ledger's single ambiguous red —
  that ticket's disposition, not ours.
- No full suite was run by me this stage (gate receipt + one targeted batch; 取证纪律
  t260924-09 respected).

参考 docs：docs/README.md（gen0 全读）；gen1–gen3 定向清扫无命中。
