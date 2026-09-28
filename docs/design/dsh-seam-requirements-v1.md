---
title: "dsh seam requirements v1 — A3 runtime model override + A4 headless session continuation hook"
category: design
tags:
  - dsh
  - upstream requirement
  - headless
  - settings
status: active
updated: 2026-09-28
---

# dsh seam requirements v1 — A3 runtime model override + A4 headless session continuation hook

> A requirements document for filing an upstream issue against dsh (DeepSeek Harness)
> or for self-adaptation by reference.
> Consumers: `notes/debts/sandbar-m0-dsh-touchpoints.md` (sandbar M0 debt inventory ①).
> The two upstream resolutions of the qualitative items: A3 (a settings-layer override
> workaround), A4 (a patch assembled inside the headless runner, a historical debt named
> by the epic proposal). Grounds = sandbar key decision 4, "zero dsh patches, follow
> upstream versions".
> Options and trade-offs are recorded in `notes/discussions/260901-dsh-seam-需求书v1-方案.md`.

## Problem (shared background and factual baseline for both items)

As an orchestrator of dsh (the Temporal ticket flow dispatches work to headless agents by
(workflow, stage)), sandbar has two legitimate needs toward dsh — pinning the runtime model
at every spawn, and carrying a session across spawns — but dsh 0.1.1-rc.2 exposes no public
entry point for either, so sandbar can only hold the line with workarounds that "touch dsh
internal implementation details", and any relevant dsh change silently breaks them. Factual
baseline (all identified by first-hand measurement on the local dsh 0.1.1-rc.2 install tree,
not speculation):

1. **A3 layering order**: resolve in `@deepseek-ai/dsh-settings` =
   `mergeLayers(base, section)` (from `dsh-settings/lib/types/index.js:175`,
   a plain-object recursive merge in which `over` overwrites) — the settings.yaml user
   layer overwrites the cordis patch composite layer. Consequence: an orchestrator pinning
   `agent-default-model` via `--patch` gets overwritten by the same section written by the
   user through the GUI. This is exactly the sandbar 260826 incident: routing-table switches
   to kimi-coding/zai all missed, agents actually ran scnet, and everything died once the
   quota was exhausted. Current workaround = double write (declare the layer via patch +
   extract the section as text lines and rewrite the settings.yaml user layer,
   `server/engine/agent_activities.py:226-248`, call site :641).
2. **A4 headless has no resume**: the stock runner (cordis id = `headless-runner`,
   `@deepseek-ai/dsh-headless/lib/index.js`, inject = `[agentDefaultModel,
   agents, sessions]`) hardcodes `sessionId: SessionId(\`session-${randomUUID()}\`)`
   (same file, :71) and offers no create-or-resume entry point at all. sandbar's current
   workaround = generate a one-off patch on every spawn: disable the stock runner + insert
   a homegrown create-or-resume runner (`server/headless-resume/node.ts`), relying on three
   internal details — the stock runner's cordis id, the `headlessStartup` injection point,
   and the `!!js ctx.headlessStartup.task` evaluation context
   (`agent_activities.py:644-665`). If any one of them changes, the patch is void — session
   continuation is silently lost (falling back to stock is not a hard failure, the hardest
   kind of breakage to notice).
3. The `DSH_HEADLESS_SESSION` environment variable has zero hits inside the dsh install tree
   (measured by grep) — it is a sandbar-defined convention consumed only by the homegrown
   runner, not a dsh capability.

## Requirement chapter 1 (A3): the runtime model override must beat the GUI user layer

### Use case

The orchestration system decides (provider, model) for every spawn from the routing table
(model-routes.yaml); on the same machine the user may have written `agent-default-model`
into settings.yaml through the console GUI. Expectation: the orchestrator's runtime
decision takes precedence over the user's GUI default, without rewriting the user's file.

### Desired API (two candidates, with a stated preference)

1. **Explicit spawn-level override parameter (preferred)**: `dsh --profile headless --model
   <provider>/<model>` (the env form `DSH_AGENT_MODEL` is also acceptable). Semantics =
   a one-off model selection at the highest priority: not written to disk, does not modify
   settings.yaml, does not affect later processes.
2. **Layered declaration**: cordis patch entries support a `precedence: above-user` style
   marker, so that the section is resolved after overwriting the user layer. This keeps the
   two-file mechanism, but the precedence between "orchestrator override" and "manual user
   edit" then still depends implicitly on layering order and is less direct than option 1 —
   hence the preference for option 1.

### Behavioral contract

- Total order of precedence, hardcoded: **CLI/env override > cordis patch composite layer >
  settings.yaml user layer > built-in defaults**;
- The override path taken is observable: the selection actually in effect (provider/model and
  the layer it comes from) is printed as one line to stderr/log at startup;
- Zero changes to user files: settings.yaml is never written under any circumstance;
- Backward compatible: when no override parameter is supplied, behavior is byte-for-byte
  identical to today.

### Failure-mode trade-offs against the workaround (reference implementation = `_pin_default_model`)

| Current failure mode | After the seam lands | Rationale |
| --- | --- | --- |
| settings.yaml missing → silently skipped, routing misses (silent failure) | **Eliminated** | spawn parameters do not depend on user files; a missing settings does not stop the override from taking effect |
| Extract the section as text lines and rewrite; any dsh change to the section format silently mismatches (root of the debt-inventory A3 re-review trigger condition) | **Eliminated** | sandbar deletes the `_pin_default_model` double write and no longer parses settings.yaml — this is precisely the debt this seam exists to dissolve |
| Window in which a re-copy overwrites after the user manually changes the default model in the GUI and before the next spawn | **Eliminated** | spawn parameters are not written to disk, so the window no longer exists |
| Override value invalid (typo in provider, etc.) → today silently runs the wrong model | **Eliminated** | the contract requires an invalid value to fail loudly and refuse the spawn (see acceptance sample 2-4) |

### Acceptance samples (expected behavior hardcoded, no blanks left to upstream)

1. **happy path**: on a DSH_HOME whose settings.yaml carries a user-layer
   `agent-default-model`, after actually running
   `dsh --profile headless --model foo/bar "say hi"`, the provider/model attribution in
   the session events `request/context` and `request/header` = foo/bar, and both the mtime
   and the contents of settings.yaml are unchanged;
2. **malformed (no `/`)**: `--model bar` → error at startup, non-zero exit code, a
   plain-language hint on stderr (stating the required `<provider>/<model>` form), no
   silent ignore;
3. **malformed (unknown provider)**: `--model nosuch/bar` → likewise fails loudly and
   refuses the spawn, and **does not fall back to the default model and keep running** —
   silent fallback is exactly the 260826 incident shape, and the contract does not allow
   it back;
4. **malformed (empty value)**: `--model ""` → usage error, non-zero exit code
   (explicitly passing empty = caller bug; not swallowed, not treated as absent).

## Requirement chapter 2 (A4): a session continuation hook exposed by the headless runner

### Use case

The orchestration system reuses one dsh session across multiple dispatches for "the same
ticket, the same role" (the person who writes the plan is the person who implements it;
rework comments arrive in the original session and the work continues there, instead of
rebuilding context from scratch on every spawn), with the session id given deterministically
by the orchestrator (e.g. `<ticket>-<role>`).

### Desired API (preference for promoting CLI/env to first class; no need to expose internal services)

`dsh --profile headless --session <id>` (or `DSH_HEADLESS_SESSION=<id>` officially adopted
by dsh as a convention), with the semantics of the stock `headless-runner` changed from
"always a fixed new random session" to **create-or-resume**. dsh is not required to expose
the internal agents/sessions services to external plugins.

### Behavioral contract (6 items)

1. The id exists and is resolvable → resume that session;
2. resume fails (session does not exist / is not resolvable) → fall back to creating a **new
   session with the same id**, with one plain-language line on stderr;
3. creating anew with the same id also fails (typically a torn session file) → fall back to
   a **brand-new random id**, loudly reporting "context not recoverable" on stderr; not
   silent, not a hard failure (the flow stays alive, but the loss must be visible);
4. no id supplied → current behavior unchanged (a new random session, one-off);
5. exit only after the task finishes and `sessions.flush` has run (the semantics of flushing
   the session file first under SIGTERM are unchanged — the related debt-inventory D1
   re-review condition);
6. the exit code follows the turn outcome: completed → 0, anything else (including error) →
   non-zero (the orchestration side judges liveness by rc; related debt-inventory D2).

### Failure-mode trade-offs against the reference implementation (reference implementation = the homegrown runner `server/headless-resume/node.ts`)

| Failure mode | node.ts current behavior (line no.) | Carried into the seam? | Rationale |
| --- | --- | --- | --- |
| blank id (empty string / whitespace only) | after trim, treated as unset (:99) | **Not carried** — changed to a usage error with a non-zero exit (contract item 4 refers only to "parameter not supplied") | a blank id is usually a caller bug; treating "blank = unset" swallows the bug into a one-off session and the continuation is silently lost. Echoes acceptance sample 3. **This is a deliberate tightening, not an oversight**: sandbar always generates ids of the form `<ticket>-<role>`, never blank, so there is no practical impact |
| launcher does not provide ctx.appExit | hard throw, refusing to mount (:157-160) | Not applicable (dsh-internal assembly semantics) | once the seam is promoted, assembly goes through the stock runner and appExit is guaranteed by dsh itself; that defense is left to the upstream implementation to decide by its own discipline |
| all errors go to stderr with a uniform `dsh: ` prefix (resume failure / fallback / exit reason) | :82, :106-107, :120-123 | **Carried** — contract items 2/3 spell out the stderr notes in this idiom | observability: whether continuation took effect must be readable from process output, never silent |
| torn session (bad zstd frame) kills both resume and same-id create | switch to a brand-new random id and report loudly (:118-124) | **Carried** (= contract item 3) | infrastructure failure should not kill the flow, but context loss must be stated loudly |
| turn outcome other than completed → non-zero exit code | :150-153 | **Carried** (= contract item 6) | the orchestration side judges liveness by rc (debt D2) |

### Acceptance samples (executed under the same DSH_HOME; including the missing state and malformed-id states)

1. **happy path**: two spawns with the same `--session <id>`; the second session's event
   stream contains the first round's events (seq contiguous);
2. **malformed disk input**: after pre-seeding a bad session file with a truncated zstd
   frame, spawn → no crash, a quarantine hint on stderr, exit code following the turn
   outcome (contract items 3/6);
3. **malformed id (empty/whitespace)**: `--session ""` or `--session "  "` → usage error,
   non-zero exit code (not treated as unset — see the trade-off table's first row);
4. **malformed id (path separators / over-long / non-ASCII)**: `--session "../x"`, 65+
   characters, containing non-ASCII → usage error, non-zero exit code. The session id
   whitelist semantics must be hardcoded; this requirements document suggests
   `[A-Za-z0-9_-]{1,64}` — which also guards against the id being interpolated into a
   session file path (the path traversal surface);
5. **missing state**: no `--session` → current behavior unchanged (a new random session,
   one-off).

## Nongoal (shared by both items)

- dsh is not asked to change the session on-disk format/path (the debt-inventory C1 tracking
  surface is not dissolved here);
- dsh is not asked to be aware of "project/ticket" concepts — the seam only takes a bare id
  and a model string; orchestration semantics stay with the caller;
- No promise that the sandbar side switches immediately: the double-write workaround stays
  until the upstream release. Deprecation condition = once the corresponding dsh version
  lands, sandbar opens a separate ticket to delete the `_pin_default_model` double write and
  the resume_patch generation block (this requirements document is that ticket's
  requirement input);
- **Concurrent spawn races on the same id are not part of the contract**: the sandbar
  orchestration side guarantees serial spawns for the same ticket and the same role (Temporal
  activity single-flight); the seam promises nothing about concurrently resuming the same
  session (concurrent resume is undefined; the caller serializes on its own) and asks
  upstream for no locking.

## Proposal (migration path on the sandbar side, for upstream to assess impact)

- The two upstream items can be delivered independently, with no dependency on each other;
  once A4 lands, sandbar deletes the resume_patch generation block and
  `server/headless-resume/` (the homegrown runner retires); once A3 lands, it deletes
  `_pin_default_model` and the model_patch generation block — the `--patch` path is then
  left with only role presets (A1, a legitimate consumption);
- Completing the migration fulfills decision 4's "zero dsh patches" standard for A3/A4:
  sandbar's dependence on all dsh internal implementation details (settings layering
  order, runner assembly, headlessStartup evaluation context) drops to zero, and upgrades
  look only at the public CLI/env contract;
- This requirements document's factual baseline is anchored to dsh 0.1.1-rc.2; after a dsh
  version bump, re-scan and re-verify per the debt inventory's "must-check items on dsh
  upgrade".
