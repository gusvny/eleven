# t261004-44 plan — Make the silent delivery faces loud (KI-196, KI-197)

Stage: create_plan (developer, gen0). No code changed in this stage; worktree left clean.

## Problem restated

Two delivery faces fail silently on the live path:

- **KI-196** — the question bridge (t261001-23) has never fired in production: a session
  called `ask_user_question`, nothing mirrored into the ledger, no panel card, no watchdog
  alert; the session sat parked 35 minutes. Hard evidence: zero bridge-written rows ever
  (bridge rows always carry `group_id`; the single `question` row was hand-posted without
  one). There is no state face that can answer "is the bridge mounted, has it ever fired".
- **KI-197** — `client.py deliver` (`server/engine/client.py::cmd_deliver`, ~line 3324)
  does `await handle.result()` with **no deadline**. A worker started before
  `ExecutorDeliveryWorkflow` was registered retries `NotFoundError` forever; both caller
  attempts (60 s and 900 s caps upstream) returned neither receipt nor row, and the caller
  could not tell "slow" from "this face is dead".

## Design decisions

### D1. Worker registration fingerprint face (KI-197 root enabler)

`server/engine/worker.py` writes a fingerprint file at startup and on graceful stop:
`<sandbar_dir>/worker-fingerprint.json` = `{pid, started_at_ms, code_fingerprint (sha of
workflows.py), registered: [workflow class names]}`. Written atomically (tmp+rename, same
discipline as other engine faces); a crash leaves the previous file, which `deliver` treats
as "stale, unverified" — never as healthy.

`cmd_deliver` reads it **before** starting the workflow:

- class present → proceed as today;
- file readable and class **absent** → immediate named refusal, rc != 0, no workflow
  started, no hang: `"deliver: workflow class ExecutorDeliveryWorkflow is not registered on
  the running worker (worker pid N started <ts>, registered: [...]) — the delivery face is
  dead until the worker is restarted on current code"` (names the failed check and the
  registered set; review checklist B5). Refusal is appended to the audit ledger (same face
  the grant gate uses, `kind="deliver_refused"`) so the watchdog can see it;
- file missing/unreadable → proceed, but the bounded wait below still bounds the face; the
  refusal on timeout says the fingerprint face was absent (degradation named, never silent).

### D2. Bounded wait in cmd_deliver (KI-197 backstop)

Wrap connect+start+result in `asyncio.wait_for(..., timeout=SANDBAR_DELIVER_TIMEOUT_S`,
default 60, env-overridable, floor 5 s)`. On timeout: cancel the workflow handle
(`client.get_workflow_handle(wf_id).cancel()` — otherwise Temporal retries forever and the
next caller in the bucket inherits the zombie), then return a named refusal rc != 0:
`"deliver: timed out after Ns waiting for ExecutorDeliveryWorkflow — either the worker does
not have this workflow class registered or the engine is wedged; nothing was delivered"`,
kind a new `KIND_DELIVER_REFUSED = "deliver_refused"`, and append the same audit row as D1.
Timers/handles have a single cleanup path on success, refusal, and cancellation.

### D3. Bridge state face (KI-196 observability)

`question-bridge.ts`: the bridge already emits typed events; add a bounded status sink —
`createBridgeStatus()` returning `{mounted: boolean, counters: Record<kind, number>,
last_events: BridgeEvent[] (last 50, newest first)}`; the listener records into it (same
kinds as today; counters monotonic). `node.ts` creates one sink, passes it into
`createQuestionBridge` and registers a new panel route `GET
/sandbar-executor-panel/api/bridge/status` in the existing `PANEL_API_ROUTES` table (route-
parity UT keeps table==reachable). Panel page: a small badge line on the Requests tab
("question bridge: mounted, N mirrored / M refused, last event <kind> at <time>") — English
UI copy per host order 261004. `mounted` flips true only when `ctx.on` registration
succeeded (today's warn path sets mounted=false explicitly).

### D4. Live-path case for the bridge (KI-196, the required seam case)

`integration/t261004-44/sc_question_bridge_live_path.mjs` — offline seconds, zero
docker/Temporal/browser, never touches 3099/7233:

- boot a **real cordis app**: `new Context` from the cordis package inside the installed
  dsh tree (`~/.sandbar/dsh-015/lib/node_modules/@deepseek-ai/dsh/node_modules/cordis`,
  resolved via `createRequire`); if absent → `ENV_FAIL` exit 2 naming the dependency
  (never a fake pass; the integration gate decides);
- run the plugin's **real `node.ts apply(ctx)`** on that context with `HOME`/`SANDBAR_PROJECTS_DIR`
  pointing at a temp instance root seeded with a real project registry (`project.yaml` with
  `dirs:`) — real `fsLedgerIo`, real registry resolver;
- dispatch a genuine agent-scoped event: `ctx.emit('user-questions/request', {questions:
  [q1, q2], agent: {id, cwd: <project dir>}})` — the real cordis dispatch, not a direct
  function call;
- assert: two rows land in `<root>/<key>/requests.jsonl` (under the instance projects
  root) with one `group_id`, `kind='question'`, `raised_by` = the agent id; then answer via
  the **real panel HTTP surface** (harness `startPluginHarness`-style server is not needed —
  the real `webServer.register` routes are collected from the same context) and assert the
  bridge resolves the emitted event's promise with both answers in question order — the
  row ids round-trip back to the asking session;
- P-faces also assert the new state face: `GET /api/bridge/status` reports mounted=true,
  counters.mirrored=2, and the events list shows `mirrored` then `answered-by-ledger`.

Injected-deps unit cases already in `tests/` stay; this is the seam's outermost case per
docs/reference/test-tiers-and-e2e-admission.md (offline gray-box L2, not an expensive e2e).

### D5. Watchdog judgement (both KIs)

`server/plugins/watchdog/`:

- **Rule `ask_unmirrored` (KI-196)**: independent of the bridge — tail the executor
  session file for a recent `ask_user_question` tool_use with no following result (the
  watchdog already reads session files); if no `question` row for that session appears in
  the project ledger within `ask_mirror_deadline_s` (config, default 120), raise redline
  `"session <sid> is waiting on ask_user_question but no question row landed in ledger
  within Ns — question bridge did not fire"` (names session and face). Bridge-unmounted
  (from D3's status face read) escalates the same rule with that fact in the detail.
- **Rule `deliver_refused` (KI-197)**: tail the audit ledger for `kind=deliver_refused`
  rows → redline `"delivery face refused for session <sid>: <refusal one-line>"` (names
  session and face), within the existing alert dedup/once-per-row discipline.
- Both rules go through the existing `raise()` path so night policy/redline list applies;
  add both rule names to the default `alerts.redline` list (they are exactly the
  "must be loud at night" class).

## Steps (one commit each)

1. **Worker fingerprint + deliver bounded refusal** — `worker.py`, `client.py`,
   `shared.py` (dir helper), `server/engine/tests/test_deliver_refusal.py` (fingerprint
   present/absent/stale × class present/absent; timeout path with a stub client that never
   resolves; malformed fingerprint file = named degradation; rc/JSON shape). Verify:
   `pytest server/engine/tests/test_deliver_refusal.py`, `py_compile` touched files,
   `python3 integration/lint_tests.py`.
2. **Bridge status face + live-path scenario** — `question-bridge.ts`, `node.ts`, `api.ts`,
   `panel-page.ts`, panel tests (`bridge-status.test.mjs`: counters, ring bound 50,
   mounted=false path, route parity), `sc_question_bridge_live_path.mjs`. Verify:
   `node server/plugins/executor-panel/run_tests.mjs`, `node --check` on touched .mjs;
   scenario NOT executed (integration gate runs it).
3. **Watchdog rules** — `alert rules + core + config`, tests
   (`ask-unmirrored-t261004-44.test.mjs`, `deliver-refused-t261004-44.test.mjs`: pending
   ask past deadline → redline naming session+face; row landed in time → clear;
   bridge unmounted → detail names it; refusal row → redline; malformed ledger row → no
   crash, named skip). Verify: `node server/plugins/watchdog/run_tests.mjs`, then full
   touched-surface pytest + both run_tests once before handoff.

## Alternative decompositions (considered, rejected)

- **Watchdog KI-196 judgement sourced only from the bridge status face** (no session-file
  tail): fewer moving parts, but rejected — when the bridge never fires the face is exactly
  the thing that is silent; the judgement needs a source independent of the component it
  polices.
- **KI-197 refusal via describe/poll of workflow task pickup** instead of a worker
  fingerprint file: rejected — no face exposes the worker's registered set that way, and
  the fingerprint file also retires KI-197出路② (code-newer-than-worker must be checkable).
- **One combined commit** instead of three: rejected — three independent faces (engine CLI,
  panel plugin, watchdog plugin) with separate test runners; three commits keep review and
  rework slices small.

## Acceptance mapping

- Ticket A(1): D4 live-path scenario (real cordis app, agent-scoped event, real ledger io,
  id round-trip). A(2): D3 state face + D5 watchdog read of it.
- Ticket B: D1+D2 — named refusal naming class and registered set, rc != 0, bounded, no hang.
- Ticket C: D5 — both redlines name the session and the face.

## Verification discipline for the implementation stage

Unit tests runnable in-stage (pytest targeted files, both plugin `run_tests.mjs`,
`lint_tests.py`, `py_compile`, `node --check`). Integration entry points
(`run_scenarios.py`, `sc_*`) NOT executed in-stage — the gate runs them; the live-path
scenario's ENV_FAIL contract makes a missing cordis an honest exit 2, not a fake pass.

## Implement-stage amendments (review_plan conditional pass, all adopted)

- **C1 (duplicate-id fallback bounded)**: the `already started` branch's second
  `result()` is inside the same `asyncio.wait_for` shape; timeout there = named refusal
  (`delivery-deadline-first-receipt`) + zombie cancel. UT: stub client raising
  already-started then hanging → refusal, wall-capped.
- **C2 (audit append fail-open)**: `_record_deliver_refusal` never blocks the caller's
  refusal; an append failure is named inside the refusal text (`audit row not filed: ...`).
  UT covers both the raising-append path and the landed-row shape.
- **C3 (stale-fingerprint semantics, one named rule)**: stated in
  `worker_registry.delivery_registration_check` — the fingerprint is a fast-path refusal
  enabler, NOT a health certificate: class listed → proceed under the bounded wait even if
  the file is provably stale (dead pid / old code sha); class absent → immediate refusal;
  file absent/malformed → named degradation to the bounded wait. UT rows for all three.
- **C4 (malformed external input)**: implemented against the designed source surfaces —
  malformed **ledger rows** (unparsable line; `deliver_refused` row without session
  attribution) are counted and named, never crash, clear stays clear. The planned
  session-file tail was REPLACED by the pending-interaction provider (`pendingProvider`,
  the same source the self-lock face reads): no new session-file parser was introduced, so
  the session-file garbage-tail case does not apply to what shipped (the malformed-input
  cases moved to the ledger-row side, all covered).
- **Deviation vs plan D5 (source of the deliver_refused redline)**: the designed scenario
  (integration/t261004-44, written by the design stage) pins the refusal row in the
  **event ledger** (`kind=deliver_refused`, `session`, `error`), and the watchdog judges
  exactly that. The caller-side refusal also appends to the grants audit file
  (`executor-grants-audit.jsonl`, fail-open) for operator visibility. Residual gap: a
  caller-side refusal alone does not yet reach the event ledger (the engine process is the
  ledger writer and is precisely the thing that is wedged in the KI-197 shape) — the
  audit-file source for the watchdog is left as a follow-up, named in the handoff report.
- **Live-path dispatch**: the real installed cordis (`@deepseek-ai/cordis` under the dsh
  tree) exposes `waterfall`/`bail`; the scenario dispatches through
  `app.waterfall('user-questions/request', payload, noAnswerer)` with a NO_PROVIDER
  fallback — the exact KI-181 production shape (no UI responder). Probe evidence:
  `bail`/`waterfall`/`on`/`effect`/`get` all present, waterfall returns a Promise that
  resolves to the bridge listener's return (answers round-trip).
