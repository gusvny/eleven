# t260929-22 — executor entry + grants producer + named 400 text

Two scenarios, registered in `run_scenarios.py` SCENARIOS (delivery of the
design_integration_tests stage; they RUN at the integration gate per the
260921 rule):

- `sc_executor_entry_console.mjs` — GAP A on an isolated stage console
  (browser legs, pool `browser-free`): project name row is the executor entry;
  clicking it opens the panel in the center column; `Executor / Chat`
  switcher flips both ways; no separate Tick row / open-conversation button
  (design negative face); board view icon zero-regression; zero pageerror.
- `sc_grants_upstream_400_text.mjs` — GAP B+C offline via the panel harness
  seam (`sameOriginWorkbench` mode = production shape: zero base config,
  workbench endpoint on the same server; pool `ro`, serial): grants must never
  degrade with a missing-config reason (B1); with the same-origin stub plus a
  fixture watchdog declaration it must serve the derived list `degraded:false`
  (B2); malformed/absent project 400 text must name parameter + requirement +
  what was received, never a bare colon (C1–C4); unknown-op 422 names op +
  allowed set (C5, sibling-branch anchor).

## Anti-proof (scope 4d — red against pre-fix code)

Verified in the dev stage against the pre-fix tree (unit-level rods, recorded
in the implement handover evidence):

- `server/plugins/executor-panel/tests/grants-upstream.test.mjs` failed at
  "origin-default: NOT degraded" pre-fix (api.ts gated on
  `SANDBAR_WORKBENCH_BASE` only; the `workbenchBase` dep was dead wiring).
- `server/plugins/executor-panel/tests/malformed-project-text.test.mjs` failed
  at "absent project names the check" pre-fix (message ended in a bare colon).
- `server/plugins/workbench/tests/executor-entry-model.mjs` failed at import
  pre-fix (executor-view-model.ts did not exist).
- The rods above are red pre-fix by construction: the pre-fix sidebar has zero
  `executor` anchors (E1/E2/E3 fail at the behavior) and the pre-fix grants
  endpoint answers `degraded:true` with the "SANDBAR_WORKBENCH_BASE unset"
  reason in the same-origin shape (B1) — confirmed live: pre-fix tree run of
  this scenario shows `B1 no missing-config degradation` FAIL with reason
  `workbench endpoint base not wired (SANDBAR_WORKBENCH_BASE unset)…`.
