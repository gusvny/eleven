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

## Batch A follow-up (t261027-11, 261027): the t260910-12 lease/queue family moved

Host order 261027 took the five t260910-12 cases (cwd-independence, full-capacity-queue,
herd-no-crosstalk, holder-kill-reclaim, idempotent-reup) off the docker stage. Unlike the
t260905-02 family above, no assertion had to be dropped: the family's subject is stage_docker's
lease/queue machinery (lock root, lease files, TTL reclaim, capacity fuse, band allocation, hold
child), which is plain process/flock code — only the up payload was docker. The migration is a
named adaptation of the prescribed `ensure(modules=...)` pattern:

- `stage_docker.py` gained `SANDBAR_STAGE_BACKEND=process` (t261027-11): the shared
  lease/queue/fuse/hold path is verbatim; only the up payload (process_bench dev server on the
  band-allocated port, `proc_ids` identity face instead of `container_ids`) and the
  down/residue leg (process_bench.stop + residue block) are swapped. Default (env unset) stays
  docker byte-for-byte — the reason the bare-bench `ensure(modules=...)` pattern of
  t260915-20/t260916-02 was NOT used here: those cases only need a Temporal frontend and hold no
  stage contract; re-expressing lease/queue contracts against a bare endpoint would have deleted
  exactly the assertions acceptance item 3 protects.
- Docker-face assertions were renamed, not deleted (container cross-checks -> process_bench.py
  status /proc start time; docker-present gates -> temporal-binary gate). Assertion counts are
  unchanged: 8/14/11/15/12.
- The five rows left batch_stage_exceptions.json (30 -> 25) and the generator ROWS in lockstep;
  the t260921-06 window-form guard now reds any new t26091012-* compose project — that is the
  runner-side "zero containers" observation for this family.
- The t260905-02 fork above is untouched: those three cases keep their docker teardown
  assertions and stay put, pending the user decision recorded there.
