# Bench-migration fork report: t260905-02 worker-lifecycle family (ticket t261026-25, 261026)

**Status: the three cases were NOT migrated to the process bench. This report asks the user to
rule on the fork below.** Nothing else changed: the three scenario files are byte-identical to
before this ticket.

## What was found

Host order 261026 says: migrate three cases per batch, keep every assertion byte-identical, and
do NOT migrate a case that "tests the docker stage ITSELF (leases, ns-acquire, **container
residue**)". All three cases in this batch end with two teardown assertions on **their own docker
stage**:

- `stage_down(...).residue == []` ("stage down leaves zero residue containers")
- `wait_port_released(port)` ("stage temporal port is released")

Locations: `sc_worker_lifecycle.py` teardown, `sc_ticket_worker_watch_exit.py:~240-244`,
`sc_console_duplicate_guard.py:~279-283`. `integration/batch_stage_exceptions.json` carried the
same finding since 261001 (batch mode turned these assertions red exactly because the fact they
assert disappeared). Container residue is named verbatim in the do-not-migrate list, so the
order's own carve-out applies: the rows stay, with their `reason` corrected (done in this ticket)
to say what the cases actually test.

## Coverage analysis (why dropping the assertions is a real decision, not cleanup)

- `t260904-19-stage-docker-parallel-zero-residue` covers the stage **mechanism's** concurrent
  up/teardown zero-residue on its own probe projects.
- `t260913-05-*` covers **lane/worktree** teardown residue (`lib_t260913_05.residue_state` —
  repo/lane directories, not containers).
- Nothing else covers **a case-owned docker stage's full up→use→down zero-residue cycle observed
  from inside a consumer case**. These two assertions are live regression coverage; deleting them
  weakens the estate.

## The fork (user decision)

- a) Keep the three cases on docker as-is. Zero risk, zero work; docker stays in the test estate
  for this family.
- b) Authorize dropping the two teardown assertions (container residue + port release) from the
  three cases, after which the family can migrate to the process bench in a later batch. Scope of
  that batch would also include: the three intent descriptions in `integration/run_scenarios.py`
  (lines 2091, 2094, 2097) still say "docker 舞台" and would be updated.

## Bench facts relevant to (b)

- `lib_proc_bench.ensure()` pins the namespace to `default` (the bench serves `default` only);
  the cases' custom namespaces (`lc-*`, `watch-*`, `dup-*`) would be dropped. Ids are already
  pid-tagged, so no cross-run collision is expected.
- ProjectKey SA writes on the bench are asserted by `process_bench.py`'s docstring (~line 38) but
  are not proven for this family's `ticket-start`-with-project legs (watch-exit, duplicate-guard).
- Attach mode never stops a bench it did not start; teardown would have to split on
  `ensure().started`. **Design notes only, not a committed design** — if the user picks (a) these
  notes are discarded.

## Bench verdict (acceptance item)

**No defect found first-hand; no bench run was performed in this ticket.** The carve-out was
applied at plan time, before any bench leg existed to run, and developer-stage discipline forbids
executing `sc_*.py` integration entrypoints. The facts above are code/docstring readings, marked
as such; the round-1 evidence for how these cases behave on a bench comes from the 261001
batch-mode measurements already recorded in the exception table.

## Reference docs

- docs/README.md (index triage); docs/reference/test-tiers-and-e2e-admission.md (tier context).
- Truth sources for the findings: the three scenario files, `integration/batch_stage_exceptions.json`,
  `integration/lib_proc_bench.py`, `integration/process_bench.py`, `integration/run_scenarios.py`.
