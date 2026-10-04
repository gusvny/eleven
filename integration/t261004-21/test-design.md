# Test design — t261004-21 (design_integration_tests, integration)

Grey-box L3. Bases, in the required order: ① ticket user_request (fix the
retired audit-log copy so it names the project executor action record, and
restore the guard t261004-16 hollowed); ② KI — no open KI entry names this
panel copy surface; the touched known family is KI-036 (playwright-core
supply), which the chosen harness already degrades loudly (ENV_FAIL exit 2);
③ the component's outward contract: the panel page shows copy naming
`<projects_root>/<key>/ledger/executor-actions.jsonl` as the source, and
sc_t26100411 b5 promises a page free of retired audit-log wording.

## Coverage decision: zero NEW scenario files

The testable surface of this ticket is the b5 check inside the EXISTING
scenario `integration/t261004-11/sc_t26100411_panel_reads_project_record.mjs`
plus regression on the two t261004-14 scenarios. Per approved plan v2
(review_plan gen1, verdict=pass) the b5 restoration, the render-path wiring
and the planted negative are implement-stage edits to that existing scenario.
A second scenario here would be an intent-level duplicate of b5. No
registration change in run_scenarios.py SCENARIOS is needed (no new file).

## Case list (owned by implement stage, per plan v2)

- T1 — guard bites on what the user sees (defect 2). Intent: b5 checks the
  RENDERED text, not the page source. High-level steps: browser leg reusing
  `integration/t261003-06/lib_panel_seam.mjs` (PANEL_PAGE_PATH + playwright-core,
  same pattern as sc_panel_list_contract_render.mjs); stub `/api/actions` twice
  (ok:false with the backend-shaped degraded reason naming the record file;
  ok:true with empty actions and the real `source`); collect
  `document.body.innerText` each time; assert innerText contains
  `executor-actions.jsonl`, does not match `/admin\.log|audit log/i`, zero
  pageerror. playwright-core missing = ENV_FAIL exit 2 (KI-036 family), never
  a false green; scenario header updated (no longer "zero browser").
- T2 — the contract copy IS the copy (defect 1). Intent: the user reads the
  contract's `empty_copy`, not an inline duplicate. Steps: after the render
  path is wired (plan Step 2), the empty-state innerText carries the
  `overview_recent_actions` contract copy plus the record path.
- T3 — planted negative (ticket deliverable 3; lane-transient, NOT a persisted
  leg). Steps: temporarily plant "audit log" into `empty_copy`, run the
  scenario, T1 must be RED under the restored guard only; revert; GREEN. Both
  outputs verbatim in the lane handoff.
- Regression perimeter: the two t261004-14 scenarios stay green (their
  assertions bind order/cap, not wording); the API-level b5 legs in
  sc_t26100411 stay unchanged.

## Fault faces considered

- Malformed/missing input: payload stubs mirror the static reason templates in
  `recent-actions.ts`; malformed rows are covered by existing leg B8 — no new
  malformed-input face introduced by this ticket (the change is copy + guard).
- Resource lifecycle: browser is closed on every exit path via the seam's
  makeCase discipline; scenario tmpdir cleanup already registered on
  exit/SIGINT.
- Environment: playwright-core absence degrades to ENV_FAIL exit 2 (loud), per
  the t261004-14 precedent.

## Carry-back (not caused by this ticket)

`python3 integration/lint_tests.py` on the untouched worktree reports 1 error:
L7 banned-term「腿」in 6 files outside this ticket's scope (notes/debts/
known-issues.md, notes/discussions/…, server/plugins/watchdog/harness.mjs,
server/plugins/workbench/src/client/executor-view.tsx, integration/
known-red-baseline.json, integration/sc_emit_surrogate_guard.py,
integration/t260928-13/sc_registry_additive_keys.py). Pre-existing main-side
debt; flagged for the integration role / a term-sweep ticket, not edited here.
