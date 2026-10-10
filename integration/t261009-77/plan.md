# Plan — t261009-77: the line round's declared runner

Stage: create_plan (developer, gen 0). Code changes land in the implement
stage; this file is the plan of record for that stage.

## What exists already (read from the tree, not assumed)

- `server/engine/develop_certify.py:1465-1540` — the contract side is DONE:
  `resolve_runner` reads `SANDBAR_LINE_ROUND_RUNNER` (timeout
  `SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S`, default 3600), runs the command with
  `SANDBAR_LINE_ROUND_CANDIDATES` (JSON list of `{"repo","revision"}`) in its
  env, in a tree of its own; success = one JSON header on stdout; nonzero
  exit / malformed header / timeout / OSError = `CouldNotRun` (the round's
  range-growth path, never a freeze).
- `integration/run_scenarios.py` (t261009-11 driver half) — the top driver
  ALREADY mints a run id, writes case rows then ONE header through
  `integration/scenario_ledger.py` (validated against the same recount the
  `INTEG_SUMMARY` line carries — no second counting anywhere), and adds the
  additive `run_id` key to `INTEG_SUMMARY`. A red round still completes this
  write; the run record is written before the exit-code decision.
- `integration/scenario_ledger.py` — `read_runs()`, `rows_for_run()`,
  `SANDBAR_SCENARIO_LEDGER_DIR` isolation seam, retention.
- The engine's decision side refuses a header with `ran == 0` ("ran: 0 is
  never a proof") and refuses counts-shaped evidence on the certification —
  so the runner's ONE output line must be the real ledger header, verbatim.

## Design: `integration/line_round_runner.py` (new, shared infra — no `sc_`
prefix, so it is not a registry entry)

One command, `python3 integration/line_round_runner.py`, satisfying
`resolve_runner`'s docstring exactly:

1. **Candidates in.** Read `SANDBAR_LINE_ROUND_CANDIDATES`; parse as JSON.
   Malformed (missing env, not JSON, not a list, empty list, a member without
   `repo`/`revision`) → named error on stderr, exit 2, NEVER a fabricated
   header. This is the malformed-input face (unit-tested with fixed bad
   payloads, no real external source).
2. **Own tree(s).** For each candidate repo, `git clone --no-hardlinks
   <source> <runroot>/<repo>` then checkout the candidate revision. Source
   resolution: `SANDBAR_LINE_ROUND_REPO_PATH_<NAME>` env per repo name, with
   the runner's own enclosing checkout as the fallback for the primary repo
   (the one carrying `integration/run_scenarios.py` — discovered by walking
   up from `__file__`'s packaged location, i.e. the clone, never the source).
   A repo with no resolvable source path → named exit 2: the runner never
   produces a partial-candidate proof ("the candidates set is what runs").
   The clone makes "own tree" true by construction, so
   `refuse_delivered_checkout`'s concern is structurally met; the runner
   still refuses (realpath compare) cloning INTO the source checkout.
3. **Run the declared full suite there.** Default suite command
   `python3 integration/run_scenarios.py`, override knob
   `SANDBAR_LINE_ROUND_SUITE_CMD` (the seam the tests and the scenario use;
   the production declaration keeps the default). The runner exports into the
   suite env: `SANDBAR_LEDGER_REUSE=0` (a line round is a proof — a fully
   reused round would mint a `ran == 0` header, which the engine refuses;
   better to not offer the trap), `SANDBAR_SCENARIO_LEDGER_DIR` pointed at
   the run's OWN ledger dir under the runroot (the run record must be
   self-consistent — rows + header of exactly this round — and never
   intermix with the worker's interactive ledger), plus
   `SANDBAR_GIT_SHA` pinned to the primary candidate revision.
4. **Header out — one JSON line.** A completed-but-RED suite round is a
   valid proof of red: the runner distinguishes "could not run" from "ran
   and failed cases" mechanically by the presence of an `INTEG_SUMMARY` line
   with a `run_id` key. On completion it reads the header back from the run
   ledger (`read_runs()`, filter by `run_id`) and prints
   `json.dumps(header)` — one line, stdout, then exit 0 (whatever the
   verdict). Every could-not-run path exits nonzero with the named reason on
   stderr: suite rc != 0 with no parseable `INTEG_SUMMARY` (top-level env
   fail), `run_id` absent from the summary, header missing from the ledger
   (interrupted run — a state to see, never invented), clone failure, suite
   command unreachable. The runner imposes no second timeout of its own —
   the engine's `SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S` bounds the whole
   command — but every spawn path carries try/finally reclamation and the
   runroot is removed in a `finally` on ALL paths (success, error, signal).
5. **Suite spillover containment.** The suite subprocess gets
   `start_new_session=True` and, on the runner's own SIGTERM/SIGINT, the
   process group is terminated before cleanup (a killed runner must not
   orphan a half-running suite writing into a deleted ledger dir).

## Declaration (spec 3): `integration/t261009-77/runner-declaration.md`

The operator-facing statement, exact and copy-pastable:

- What: `SANDBAR_LINE_ROUND_RUNNER` = the runner command line, e.g.
  `python3 /path/to/sandbar/integration/line_round_runner.py`.
- Where: the environment of the process that runs the scan tick — the
  engine worker's environment (`scan_schedule.py trigger` inherits it), NOT
  the shell of whoever happens to be watching.
- Restart rule: `resolve_runner` reads the env once per tick from
  `os.environ` — the value takes effect only when the worker process is
  restarted after the change. Same for
  `SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S` (default 3600 s).
- What the runner needs on the worker: `git` available; repo source paths
  resolvable (declared `SANDBAR_LINE_ROUND_REPO_PATH_<NAME>` for anything
  beyond the primary repo).
- Honest limits: with the runner declared but the worker not restarted, the
  round still reports `runner_missing` — absence is named, never silent;
  the end-to-end round on the real line is an ops action (steward/host
  applies the env + restart); this ticket proves the contract end to end at
  the scenario level and hands over the declaration.

## Tests

### L1 unit battery — `integration/tests/test_t261009_77_line_round_runner.py`
(runnable in the developer stage)

Matrix (fake suite command via `SANDBAR_LINE_ROUND_SUITE_CMD`, temp git
fixture repo, temp ledger dir — offline seconds, zero docker/Temporal/port/
console, never touches 3099):

- A header contract: a stub suite that prints an `INTEG_SUMMARY` with
  `run_id` and pre-seeds a matching header + rows in the run ledger → runner
  prints EXACTLY one JSON line equal to that header, exit 0.
- B red-is-a-proof: the same with the header's verdict red → still one
  header, exit 0 (never CouldNotRun).
- C candidates-are-what-runs: the stub suite receives
  `SANDBAR_LINE_ROUND_CANDIDATES` byte-equal to the input set, cwd is the
  clone (asserts the clone's HEAD revision == the candidate revision), and
  `SANDBAR_LEDGER_REUSE=0` is in its env; the source checkout's working
  tree is untouched (mtime/dirty-check guard).
- D malformed-input matrix (fixed payloads): unset env, non-JSON, JSON but
  not a list, empty list, member missing `repo`/`revision` → each exits 2
  with a NAMED distinct reason, zero stdout lines.
- E could-not-run paths: suite exits 2 with no summary; summary without
  `run_id`; `run_id` named but header absent from the ledger; clone fails
  (bad source path); suite command unresolvable → each exit != 0, no stdout
  JSON line.
- F cleanup: after success AND after each failure path the runroot is gone
  and no child process outlives the runner (suite stub writes a pidfile; the
  test asserts the pid is gone after the runner is SIGTERM'd mid-run —
  process-group termination face).
- G own-tree refusal: source path == runroot parent trick — the runner
  refuses to clone into the source checkout by name.

### Scenario — `integration/t261009-77/sc_t26100977_line_round_runner.py`
(registered in `run_scenarios.py` SCENARIOS, pool `ro`; integration-gate
executed, NOT run in the developer stage)

Real `develop_certify.resolve_runner` (the production seam, subprocess with
the real env contract) over a real clean git fixture tree and a stub suite:

- H header contract end to end: env declares the runner →
  `resolve_runner(...)("candidate")` returns the header dict with
  `{"id","cases"}` shape, one stdout line, exit 0.
- I timeout path: a slow stub suite + `SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S=1`
  → `CouldNotRun` named `runner_timeout`.
- J could-not-run honesty: stub suite exits nonzero with stderr text →
  `CouldNotRun` carrying that stderr tail (the round's record names it).
- K the whole-round face at engine level: `run_line_round` with the real
  runner over a temp delivery ledger lands one certification citing the run
  id (green stub) — the same shape tonight's real line will produce.

## Steps (implement stage)

1. `integration/line_round_runner.py` + L1 unit file; verify:
   `python3 -m py_compile` both, then
   `python3 -m pytest integration/tests/test_t261009_77_line_round_runner.py -q`.
2. Register the scenario in `integration/run_scenarios.py` (one registry
   tuple append, pool `ro`); scenario file under
   `integration/t261009-77/`. Verify: `python3 -m py_compile`;
   `python3 integration/lint_tests.py`; registry L5 orphan rule satisfied by
   the sc_ file being registered (lint check).
3. `integration/t261009-77/runner-declaration.md` (the spec-3 declaration).
4. Report + self-iteration notes in the stage result; the real-line round
   (spec 4's live half) is explicitly handed to ops in the declaration.

## Verification discipline

Developer stage runs: py_compile, the new unit battery, lint_tests.py, and
read-only recon only. Integration entries are NOT executed here (engine
integration gate runs them).

## Alternative decompositions (considered, not chosen)

1. **Runner recounts case lines itself** (parse the suite's stdout spec
   lines, emit its own header) — rejected: that is a second counting,
   spec (2) forbids it, and it would bypass the ledger's recount-vs-header
   consistency check (the exact seam that caught real bugs).
2. **Teach `run_scenarios.py` a `--print-run-header` stdout flag and let the
   runner just relay it** — rejected: it widens the executor's public stdout
   contract, which the gate parses strictly; reading the header back from
   the ledger the suite already wrote keeps the executor untouched.
3. **Declare the runner per line in `lines.json`** instead of the worker env
   — rejected: `resolve_runner` reads env only and
   `server/engine/develop_certify.py` is outside this ticket's write set;
   changing the engine is a separate ticket.

## Acceptance criteria

- Runner exists, satisfies the contract; every failure path exits nonzero
  with a named reason and never prints a header.
- Header printed is the ledger's own header (same recount, run id on rows).
- Declaration document names env var, value shape, worker-env placement and
  the restart rule.
- Unit battery green in the developer stage; scenario registered and green
  at the integration gate covering header contract + timeout +
  candidates-are-what-runs.
- No changes to the round's decision logic, no weakening of "could not run
  is not red", no production worker env change from this ticket.
