# Line round runner — operator declaration (t261009-77)

This document is the WRITTEN DECLARATION an operator needs to turn the
develop buffer's line round on. Without it the mechanism exists but nobody
can switch it on. The runner asset is
`integration/line_round_runner.py`; the engine seam it satisfies is
`develop_certify.resolve_runner` (`server/engine/develop_certify.py`).

## What to set

| Env var | Value | Set where |
|---|---|---|
| `SANDBAR_LINE_ROUND_RUNNER` | the runner command line, e.g. `python3 /path/to/sandbar/integration/line_round_runner.py` | the environment of the process that runs the scan tick — the ENGINE WORKER's environment (the tick inherits it; an operator shell does not matter) |
| `SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S` | wall-clock bound for one whole round, seconds (engine default 3600) | the same worker environment |
| `SANDBAR_LINE_ROUND_REPO_PATH_<NAME>` | source checkout for candidate repo `<NAME>` (name upper-cased, non-alphanumeric → `_`; e.g. `SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR`) | the same worker environment; optional — a repo without one falls back to the checkout the runner file itself lives in |

**Restart rule: changing any of these requires a worker restart to take
effect.** `resolve_runner` reads `os.environ` at tick time; a worker that
started before the change keeps reporting the named `runner_missing` entry
(absence is named on the operator surface, never silent, never a
delivery-ledger row).

## What the runner needs on the worker

- `git` on PATH (the runner clones; it never runs the suite in the delivered
  checkout — own tree by construction).
- Enough disk for a clone plus a run-scoped ledger, under the system temp
  dir (override: `SANDBAR_LINE_ROUND_RUN_ROOT`).
- The declared suite must work from a CLEAN CHECKOUT: the run tree is a
  fresh clone carrying tracked state only, so any scenario that quietly
  relies on untracked local state in the delivered tree will fail there —
  that is the honest face of the clean checkout (the t261009-01 finding),
  not a runner defect.

## Cost (what a round costs and what the timeout should be)

- The default suite command is the FULL registry
  (`integration/run_scenarios.py`): 8–12 minutes wall clock on this
  project's registry (108 expensive-pool entries included), plus clone
  time. Ledger reuse is force-disabled for the round (`SANDBAR_LEDGER_REUSE=0`):
  a fully reused round would mint a `ran == 0` header, which the engine
  refuses — the proof must actually run.
- Recommended worker setting: `SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S=3600`
  (the engine default already fits the full suite with headroom). A line
  that chronically exceeds it reports `runner_timeout` — a named
  could-not-run (range growth, nothing opened), never a red.

## Failure semantics (what the operator will see)

- Success — including a completed-but-RED round — prints ONE JSON run header
  (the run record the suite wrote into the round's own ledger, counts from
  the same recount as the case rows, run id on the rows) and exits 0. A red
  verdict routes to the freeze path; it is a proof, not "could not run".
- Every could-not-run path exits nonzero with a named reason on stderr
  (`runner_timeout`, `runner_failed_exit_N:<stderr tail>` at the engine, or
  the runner's own `LINE_ROUND_RUNNER could_not_run: <reason>`: malformed
  candidates, clone/checkout failure, suite unreachable, interrupted run —
  rows without a header). The round records range growth and opens nothing
  ("could not run" is not "red", design goal 24).
- The worker env's `SANDBAR_INTEG_LEDGER_OWNER=gate` knob is neutralized for
  the round: the proof round must write its own run record (single-writer
  discipline applies per round, not across purposes).

## Known vocabulary debt (honest limits)

- The run record's `source` is recorded as `lane:line-round` because the
  ledger store's source vocabulary is closed today (`baseline` /
  `inspection` / `lane:<x>`); the record model's `scheduled` value is
  proposed but not implemented. Widening the vocabulary is a store-schema
  change for a separate ticket.
- The live end-to-end proof on the declared line (`develop-buffer`) is an
  OPS action: apply the env above to the worker process and restart it; the
  next scan tick then either lands a certification row for the line or an
  honest `could_not_run` naming the runner's stderr. This ticket's own
  verification covers the contract end to end at the scenario level
  (`t261009-77-line-round-runner`) and developer L1
  (`integration/tests/test_t261009_77_line_round_runner.py`).
