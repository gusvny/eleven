---
title: "Sandbar test environment isolation guide"
category: reference
tags:
  - testing
  - isolation
  - docker
status: active
updated: 2026-10-04
---

# Sandbar test environment isolation guide (M17)

> **Hard rule**: development and test tickets are **never allowed to restart / stop / modify
> the dsh process running on `localhost:3099`** (that is the production console the
> supervisor/user is using), and must not touch production Temporal's `7233` (gRPC) /
> `8233` (Web UI).
> All testing goes through this repository's **Docker isolated test environment**
> (`server/docker-compose.test.yml`).

## Why isolation is needed

Production runs directly on the host (not in Docker): the dsh console on `3099`, Temporal on
`7233/8233`, and the worker running resident. If a development/test ticket connects straight
to production Temporal, or restarts the 3099 console, the two sides step on each other:
test ticket data and workflows pollute production state, and a console restart interrupts the
supervisor's/user's session.

So tests run in the Docker test environment: **its own Temporal + its own dsh instance + its
own ports + its own data volumes**, with zero overlap with production.

## Topology and ports

| Port | Purpose | Who uses it |
|------|---------|-------------|
| 3099 | Production dsh console | supervisor/user, **do not touch** |
| 7233 | Production Temporal gRPC | production worker (engine/run_server.sh), **do not touch** |
| 8233 | Production Temporal Web UI | same source as the production worker, **do not touch** |
| 3199 | **Test dsh console** | Docker test environment |
| 17233 | **Test Temporal gRPC** | Docker test environment (7233 inside the container) |
| 18233 | **Test Temporal Web UI** | Docker test environment (8233 inside the container) |

The test Temporal uses its own namespace `sandbar-test`, with data in separate volumes
(`temporal-data` / `dsh-home`).

## Starting the test environment quickly

```bash
# run from the repository root
docker compose -f server/docker-compose.test.yml up -d
```

Both service images are built locally, with no registry pulls: `sh server/build-test-temporal.sh`,
`sh server/build-test-dsh.sh` (building the images goes online once; dsh used to run `npm i`
inside the container on every start, roughly 2 minutes per stack — since 260908 it is baked into
the image). After that, `up`/`restart` use cache and data volumes and take seconds. Once started
there are two containers:

- `sandbar-test-temporal`: standalone Temporal (temporalite dev server, SQLite on disk)
- `sandbar-test-dsh`: standalone dsh test console (3199)

**One extra step after the first `up` on a fresh data volume**: register the two search
attributes — ProjectKey for multi-project support and EpicCode for epic linkage (temporalite has
no startup flag for this; the registration lands in the data volume and persists across restarts):

```bash
server/engine/bin/temporal operator search-attribute create \
  --name ProjectKey --type Keyword --namespace sandbar-test --address 127.0.0.1:17233
server/engine/bin/temporal operator search-attribute create \
  --name EpicCode --type Keyword --namespace sandbar-test --address 127.0.0.1:17233
```

If EpicCode is not registered, creating a ticket with `--epic` fails loudly (it never silently
drops the tag); just register it as shown above.

Retention works the same way (temporalite defaults to 24h — closed workflows are **physically
deleted** after 24 hours, so ticket history, audit records, and acceptance evidence evaporate):
set it once after the first `up` on a fresh data volume (it lands in the data volume and persists
across restarts):

```bash
server/engine/bin/temporal operator namespace update \
  --retention 876000h --namespace sandbar-test --address 127.0.0.1:17233
```

> Source epic: epic-linkage (rationale in notes/epics/epic-linkage.md)

## Verifying the test environment

```bash
docker compose -f server/docker-compose.test.yml ps

# test Temporal: Web UI (open in a browser, namespace=sandbar-test)
open http://localhost:18233
# or check from the command line (using the repository's temporal CLI)
server/engine/bin/temporal --address 127.0.0.1:17233 operator namespace describe -n sandbar-test

# test dsh console
open http://localhost:3199

# health probe (alive as soon as the console's HTTP port answers)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3199/
```

## Running the worker / self-testing on the host against test Temporal

The Temporal SDK tooling (`engine/.venv`) is not installed into the container; run it on the
host from the repository venv and point it at the test instance with environment variables —
`server/engine/shared.py` honours `SANDBAR_TARGET_HOST` / `SANDBAR_NAMESPACE` overrides
(the defaults are still production 7233/default).

```bash
# test worker: connect to test Temporal (17233 / sandbar-test)
SANDBAR_TARGET_HOST=127.0.0.1:17233 SANDBAR_NAMESPACE=sandbar-test \
  server/engine/.venv/bin/python server/engine/worker.py --daemon

```

> ⚠️ **Note**: always prefix the worker with `SANDBAR_TARGET_HOST=127.0.0.1:17233`, otherwise it
> connects to production `127.0.0.1:7233` (namespace default) by default — writing test state into
> production Temporal is an incident on the same level as touching 3099.

### Per-ticket dedicated worker (since 260824)

A ticket workflow does not use a shared queue: each ticket gets its own task queue
(`suyou-ticket-<ticket id>`) plus a dedicated worker process — `ticket create` starts it
automatically (pidfile/log under `engine/data/worker-<ticket id>.{pid,log}`), and once the
workflow closes, the worker notices the status is no longer RUNNING and exits gracefully
(30s polling). Inspection (dispatcher-scan) reconciles along the way: it starts a missing worker
for a running ticket and reclaims workers that failed to exit for closed tickets. The shared
queue `suyou-poc` only serves dispatcher-scan / content-pipeline (which still need one resident
shared worker).

When verifying the dedicated worker's lifecycle in the test environment, environment variables
are passed through by `ticket create` to the automatically started dedicated worker (the spawn
inherits the caller's env), so the test ticket and its worker both land on test Temporal, with
zero overlap with production.

A machine without Docker can use a second local dev server instead (equivalent isolation:
separate port + separate db file):

```bash
server/engine/bin/temporal server start-dev --ip 127.0.0.1 --port 17233 \
  --ui-port 18233 --db-filename /tmp/sandbar-test.db \
  --search-attribute ProjectKey=Keyword --search-attribute EpicCode=Keyword
# namespace can be default (the SANDBAR_NAMESPACE default); pkill it and delete the db file when done
```

> Source epic: epic-linkage (rationale in notes/epics/epic-linkage.md)

## No production tickets visible in the test console?

That is expected. Since 260823 the single source of truth for tickets is always the Temporal
workflow (the old tickets/ JSON projection directory was deleted) — the test console connects to
test Temporal (17233 / sandbar-test), fully isolated from production (7233 / default).

## Stopping / cleanup

```bash
docker compose -f server/docker-compose.test.yml down      # stop, keep data volumes
docker compose -f server/docker-compose.test.yml down -v   # also wipe test data volumes (all test ticket data/workflows gone)
```

## Troubleshooting

- **Temporal won't start**: `temporalio/temporalite` is no longer maintained; if a flag is
  incompatible, delete that service's `entrypoint`/`command` lines to fall back to the image
  defaults (namespace becomes default, data is not persisted), or switch to any dev-mode
  Temporal (the official `temporal server start-dev` CLI, same engine path).
- **3199 won't open**: the container installs dependencies on first start — check progress with
  `docker compose logs dsh`; `exec dsh` only works after installation finishes.
- **Worker cannot reach test Temporal**: confirm `sandbar-test-temporal` is running in
  `docker compose ps`; the host-side address is `127.0.0.1:17233` (not 7233).

## Test data discipline (host ruling 260904)

Background: epic-status-enum once stuffed a snapshot of real suyou-era data (a hardcoded list of
9 charters plus per-charter notes) into component unit tests — after the migration to sandbar
only 2 charters remained, so tests turned red and were chasing the real data. The ruling
separates three layers:

| Layer | Data source | What it asserts |
| --- | --- | --- |
| Component unit tests (workbench tests/) | fixture / tmp controlled data | Logic: enum validity, error copy, config-driven semantics — independent of the real repository's state |
| Real-data invariants (optional) | real repository files | **Properties**, not snapshots: everything parses, values ∈ legal enums — adding/removing source data does not turn it red, only bad data does |
| "Exactly N known items" style assertions | —— | Not allowed: the source of truth for the list is the data directory itself, and a test mirroring it guards nothing |

Rule of thumb: **adding one piece of real data (a new epic, a new ticket) must not turn any test
red**; if it does, the assertion is snapshotting reality and should be refactored into a fixture
(logic) or a property (invariant).
Exception: contract-freezing integration scenarios (contract document guards, golden baselines)
exist to pin the source of truth — the snapshot is their very semantics, so they are out of scope
here; they live in the integration/ scenario registry, not in component unit tests.

## External call-shape unit test rule (KI-046, 260904)

Background: the charter injection in t260904-07 passed a bare string to the platform's
`session.prompt(content, mode)`, while the platform wire contract requires a `PromptContentPart[]`
array of parts → apiproxy zod rejected it with `invalid payload for session prompt`, so the core
feature was 100% broken the moment it shipped. The type gate that could have caught it was erased
by an `any` type, call-shape tests were missing, and the only journey scenario was silently
SKIPped inside the merge gate — three layers all missed it. This rule turns "third-party calls
must have test coverage" from an expectation into a mechanical obligation on the developer side.

**Clause**: whenever a new call site to a **process-external interface not controlled by this
project** is added (HTTP API, CLI subprocess, platform SDK … dsh and Temporal are merely instances
of this repository), that call must carry a **mock shape assertion** in the developer's unit
tests: capture the actual arguments and validate them against the counterpart contract — import
the real schema / d.ts if importable; if not, use a **frozen in-repo mirror** (constants plus a
comment naming the true source location and the sync responsibility). The malformed-input case
discipline for external inputs (LLM output, user input, files, network data) remains unchanged
and applies in parallel. Projects with no such call sites simply have the clause lying idle. Note
two platform semantics traps (proven by KI-046): ① a platform RPC's **business failure does not
throw, it returns a result object** (e.g. `RpcResult{ok:false}`) — check the return value, don't
rely on catch alone; ② if the type surface does not narrow, tsc is not a gate.

**Reference implementation**: `server/plugins/workbench/tests/ki046-charter-prompt-shape.mjs` —
behaviour-level mock (really load the module, capture the prompt arguments with a stub, validate
against the frozen mirror contract, exercise all malformed-input paths) plus a three-way
consistency anchor (the call shape in src and in the build artifact agree, preventing "changed src
but forgot to rebuild the bundle").

**Division of labour**: shape assertions = mocks, they belong to developer unit tests, not to
integration; the integration side writes no mocks and only adds a fixed question at arbitration
time — "does this ticket add an external call? where is the shape unit test?" — it gates, it does
not do the work.

## Assertion logic of the two test layers (260910): integration asserts the end state, unit tests assert the contract

**First figure out which layer you are on** — the two layers do not test the same thing, and their
assertion logic is not interchangeable; applying unit-test rules to integration, or end-state
rules to unit tests, bends both.

| | Integration / acceptance face (scenarios, journeys) | Unit test face (developer self-test) |
| --- | --- | --- |
| Subject under test | **Behaviour once the system is assembled** | **One unit's outward contract** (input → output/exception/call shape) |
| Where assertions land | The deliverable's **end state**: assert on whoever ultimately consumes it (the page, the disk, the interface response, the rendered document) | The unit's **public contract** — it has no "one hop further out", the contract itself is the end state |
| Main enemy | Assembly breaks, **assertions written too narrow** | Results **depending on the environment** (run directory, env vars, clock, network, real data), brittle coupling, wrong mock shape |
| Cost | Expensive (spinning up stacks, opening browsers, really creating tickets); one main trunk suffices | Cheap, fast, can exhaustively cover boundaries and malformed inputs |
| Written rules in this repo | Clauses 1–6 in this section | The "test data discipline" and "external call-shape unit test rule (KI-046)" above + clauses 7–9 in this section |

**Common example (the same feature change, what each layer asserts)**:
- You changed a "list row shows status" feature — **integration** asserts: that row really renders
  that way on the page/interface; **unit test** asserts: feed the data to the row component/row
  constructor and the output's status field and button set are correct.
- You changed a "write a file to some directory" feature — **integration** asserts: the file is
  really in that directory with the right content format; **unit test** asserts: given the
  arguments, the unit called the file-writing interface with the right path and content (the
  outward call shape).
- You changed a "validate and reject" feature — **integration** asserts: the real entry point
  rejects it with the right error copy and exit code; **unit test** asserts: the validation
  function's return values/exceptions for each kind of malformed input.

## Integration / acceptance face: end-state backstop + contract layer in parallel (260910)

Background: two "all green on merge, unusable for the user" incidents in one day, plus a third of
the same family, all with the same skeleton — **assertions landed on "the thing I built", not on
"the thing you want"**:

1. **Pause feature (t260908-01)**: the deliverable = clicking pause/resume in the list; the
   scenario asserted the engine query face (`paused=True`) and engine list data (an intermediate
   face), while the real end state is the console list API + the page button. Break point: the
   host never passed the field through → scenario all green, ticket merged, no resume button in
   the UI.
2. **Multi-repo fix (t260910-03)**: the deliverable = member-repo code really moved into the
   member repo; the scenario asserted a **contract-layer** field (TicketInput.repo_worktrees
   persisted, which has to survive Temporal codec — a good assertion in itself), while the real
   end state is the member-repo workspace directory + branch + manifest file on the lane disk.
   Break point: the workflow→create-lane hop dropped the field → scenario all green, ticket
   merged, the real project still got single-repo lanes (KI-071).
3. **UI evidence gate**: the gate asserted that screenshot **files exist**, not that the
   screenshot **content captured what it was supposed to capture** — an empty-board junk image
   went into the archive with full green until a human eye caught it (KI-069).

### Clauses

**1. End-state layer (backstop, at least one per ticket)**
First write down the deliverable's "end-state face" — who ultimately consumes it: a human clicking
a button → page DOM / UI interface; another project running a ticket → the repos and directories
on disk; a document for humans → the rendered page; a downstream system → the interface response
fields. Assertions must land on that face.

**2. Contract layer (parallel, encouraged)**
Intermediate faces with a clear contract **should** be asserted: activity input/output structure,
HTTP/interface shape, file formats (e.g. manifests), state-field contracts. They are **promises**
to downstream, and a broken promise is a real regression — even if the end state happens to be
right this round. This is the only defence against "wrong in the middle, accidentally right at the
end" (otherwise it blows up only at the next consumer).

**3. Detail layer (not evidence)**
Internal variables, private functions, intermediate file layouts nobody consumes — not acceptance
evidence (they may be kept for diagnosis).

**4. Both directions must be sealed**

| Situation | Who alone can catch it |
| --- | --- |
| Contract right, end state wrong | The end-state assertion (the assembly hop broke) |
| Contract wrong, end state accidentally right | The contract assertion (the trunk happened to bypass it; the next consumer catches it) |

Keep only one layer and you keep half a blind spot. The lesson from t260910-03 is not "the
assertion was written wrong" but that it was **incomplete**: the contract layer was verified and
the end-state layer was not, and the break was exactly on the unverified layer.

**5. Two self-check questions when writing a scenario**
① Can this end-state assertion prove the user can do the thing they want to do?
② If the contract breaks, who discovers it, at which layer?

**6. Cost mix (not end-to-end everywhere)**
One end-state trunk + contract-layer coverage + detail-layer diagnosis. End-state assertions are
expensive (spinning up stacks, opening browsers, really creating tickets), so one trunk suffices;
but you also cannot let function-level direct calls impersonate the full chain (counter-example
KI-063: scenario all green at function level, real ticket creation throws TypeError — that is
using a unit test as an integration test).

**7. Gatekeeping alignment (integration sign-off stance)**
Sign-off review is not "did your assertions pass" but first "**do your assertions land on the end
state; if not, how do I verify the end state myself**". When signing off t260910-03, integration
reviewed along the same assertion face (also checking only the payload), and two pairs of eyes
missed the same blind spot — this clause exists for that.

## Unit test face: contract + isolation (260910)

**8. What unit tests assert**: the outward contract of the unit under test — return values,
exceptions, the call shape of external dependencies (counterpart contracts are covered in the
KI-046 section above). Do not assert the system's end state (disk/page) in the name of being
"more real": that turns a unit test into a slow integration test — slow, flaky, and it steals the
integration side's job.

**9. Three hard rules for unit tests**
- **Isolation determinism**: results must not depend on the run directory, environment variables,
  clock, network, or real repository data. A generic counter-example: the same test is all green
  at the repo root and turns red from another directory (it depends on cwd to locate fixtures/the
  repo) — that red is not an "environment problem", it is a test defect; conversely it can also
  mask real regressions (the t260910-08 wrap-up item is of this family).
- **No snapshots of real data**: see "test data discipline" above — assert properties, not
  "exactly N items".
- **One red points to one cause**: failure messages must name the object and the expectation;
  don't make people reverse-engineer it.

**10. A seam case must go through the outermost real entry (host order 261004)**

A seam is any place where the production path supplies something the callee cannot invent: the
process environment, the working directory, a credential, the instance root. A unit test that
injects that input proves the callee only — it says nothing about the call site that forgot to pass
it. Every seam therefore needs at least one case through its outermost real entry (the real activity
shell, the real route, the real CLI), and that case must assert an outcome tied to the environment:
an absolute path under the instance root, never a relative one.

Measured fault (261004): the delivery activity called `perform_delivery(payload, now_ms)` with no
environment. Every unit case injected `env=` explicitly, and the only case touching the activity
shell asserted registration only. The row landed under a path relative to the worker's cwd while the
receipt said `ok` — the writer declared success and the reader saw nothing. Green on paper,
invisible in production.
