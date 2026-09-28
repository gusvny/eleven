---
title: DeepSeek Harness and Temporal based multi-agent mechanism
category: design
tags:
  - roles
  - multi-agent
  - collaboration
  - dsh
  - infrastructure
  - temporal
status: active
updated: 2026-09-28
---

# DeepSeek Harness and Temporal based multi-agent mechanism

> Written in the four-part structure of the Design Doc Writing Guide. This document describes the multi-role
> collaboration infrastructure that the suyou project built on DeepSeek Harness (dsh) as its runtime foundation: how a group of agent roles, each with its own duties, cooperate to deliver software development, content production, operations and maintenance.
> As of 2026-08-21 the core mechanisms are implemented and have gone through many rounds of real runs (operational overview in `server/roles/README.md`).
> Implementation status is not written in this document — status always belongs to the epic proposal and to Temporal.

## Problem

### What is wrong today

A single "do-everything agent" carrying all the work (writing content, writing code, verifying, reviewing, deploying) has four classes of problem:

1. **No constraint on roles**: with no role boundaries, one agent both writes and verifies content, and "the generator verifying itself" plants hallucinations.
2. **No mechanism against overreach**: people who should not write files (e.g. read-only reviewers) can write, and errors cannot be traced to an owner.
3. **No context isolation**: an all-in-one agent holds everything at once, so the context explodes and tasks contaminate each other.
4. **Nobody gates the work**: acceptance relies on good intentions, and there is no decision chain of "who decides, who executes, who reviews".

### The process gap after implementation (260825 evidence)

Once the parallel density of development lanes rose, collisions on the same file became the norm. Evidence from 260825: two parallel tickets each added one line of comments
to adjacent lines of the same file (zero semantic conflict, purely textually close). The merge rehearsal detected the conflict and the ticket went straight to blocked, waiting
for a human to resolve it — and having resolved it, the human found it was merely two lines of comments. The gap: rework triggered by review has an agent loop, and conflicts
during the human approval signature get automatic rework-and-reverify, but **conflict resolution itself has no agent loop** — the machine can detect a conflict, yet it can only
wait for a human to act, so the autonomous chain breaks in the last mile.

### Background

- **dsh (DeepSeek Harness)**: this project's agent runtime, providing profile / preset / roster / plugin / subagent delegation mechanisms.
- **preset**: one agent configuration (persona + tool set + behavior parameters); this project's presets are derived by `server/presets/gen.py` from the upstream standard.
- **roster**: dsh's preset discovery mechanism (the proven entry point = the physical mirror at `$DSH_HOME/.agent-presets/`).
- **ticket**: one Temporal workflow (id = the ticket id, a singleton; `server/tools/ticket.py` is a thin shell plus the engine v2 template class) — the carrier for dispatching work, handoff, acceptance and audit; since 260823 projects are distinguished by the ProjectKey search attribute (the old `server/tickets/` JSON projection directory has been deleted).
- **knowledge base**: the `docs/` directory is the project's knowledge base (see Knowledge Base Design) and the shared source of truth for role context.



## Requirement



### Goals (verifiable)

The 7 items below are the user's original requirements, i.e. the acceptance criteria for this infrastructure; the verifiability and current status of each are answered item by item in the Proposal section.

1. **Multi-role collaboration**: it must be possible to freely define many different roles, along with their workflows and ways of working, so that they cooperate to deliver software development, operations and maintenance.
2. **Role self-iteration**: each role must be able to iterate on itself in the course of development iterations, including the tools it uses and its own workflow.
3. **Integration with the knowledge base**: it must integrate with our knowledge system so that every worker has sufficient and correct context.
4. **Determinism**: determinism must be very good, eliminating LLM hallucinations during execution.
5. **One role, many workers**: a role does not have to map to exactly one worker; to meet the needs of large-scale development, a single role can have multiple workers.
6. **Efficient communication**: workers must be able to communicate efficiently, achieved through sensible organization and communication mechanisms.
7. **Dynamic model selection**: different workers must be able to dynamically choose different models to work with.
8. Auditable, approvable: every worker's work must be traceable and reviewable, and important operations must be approvable.
9. Autonomous system: it must keep working and minimize human work. Human work is limited mainly to reviewing documents, choosing important technical directions, approving important operations, and so on.
10. The expectation is to build it on deepseek harness and temporal. No wrapping of temporal is needed — simply treat temporal as our first-class citizen, our infrastructure.

### Additional requirements (process improvement, t260826-01)

11. **Automatic conflict resolution**: when the merge rehearsal detects a text conflict between a lane and the trunk, the ticket does not go to blocked waiting for a human; it is
    automatically reworked back to the development stage for an agent to resolve (the list of conflicting files and the merge context travel with the rework), and once resolved the
    loop naturally returns to the merge check for re-verification.
12. **Loop prevention for resolution**: the number of resolution rounds is capped (3 rounds); if resolution keeps failing or the same batch of files conflicts repeatedly,
    the ticket goes to blocked for a human, and the log states the round count and the reason clearly.
13. **Existing behavior regression-free**: non-conflict red lights (no commit / dirty worktree / re-verification red) still go to blocked waiting for a human;
    the existing behavior of automatically reworking and re-verifying conflicts during human approval signature is unchanged.

## Nongoal

- **No automatic judgment of right and wrong in semantic conflicts**: the machine only identifies text conflicts and dispatches an agent to resolve them;
  the semantic correctness of the resolution is still backstopped by integration review (if the review fails, the existing rework loop applies).
- **No replacing the merge strategy with rebase**: keep the current rule of "merge the trunk into the lane"; conflict resolution is recorded inside the lane as a merge commit,
  and lane history is not rewritten.

> KI-006 boundary (host ruling 2026-09-01, t260901-26): the previous item governs the direction of **merging the trunk into the lane**;
> the direction of "merging a lane into the trunk" has, since this ruling, changed to a squashed merge-in with a single commit —
> a ticket's full history does not enter the trunk, the audit source of truth is the ticket workflow engine, the trunk stays readable, and reverting a ticket
> requires reverting only one commit. Small steps committed inside the lane and conflict resolution recorded as merge commits inside the lane are both
> unaffected; the two directions differ and do not contradict each other.
> The ticket console carries both replay conventions: pre-squash history and the new post-squash shape.

## Proposal



### High level

A five-layer structure carries the 7 requirements, and each layer has a clear landing point inside the repo:

1. **Role charter layer** (`server/roles/*.md`, 8 files): defines duties / boundaries / acceptance checklists — solves "no constraint on roles".
2. **Preset layer** (`server/presets/`, gen.py derives 8 presets from the upstream standard): persona baking — solves "no context isolation".
3. **Roster layer** (the physical mirror at `$DSH_HOME/.agent-presets/` + the default suyou-dispatcher): the discovery mechanism — solves "who is what role".
4. **Dispatch tool layer** (the delegation group of the `suyou-dispatcher` preset: 7 `dispatch_`* instances): one-command dispatch; for the three read-only roles toolFilter.deny=[write,edit] is **mechanically enforced** — solves "no mechanism against overreach".
5. **Decision chain and hallucination prevention layer**: acceptance checklists frozen in advance, generation separated from verification, cross-checking by a different model, red lines always human-reviewed, full traceability; the ticket system + verify_lane machine check — solves "nobody gates the work".



### Work task templates

Every role can have several work task templates, and each work task template defines how the role completes a piece of work.

A work task template is defined as a temporal-based workflow; a workflow has several steps, and each step may be executed by an agent or may be something that fixed code can handle. Whatever can be pinned down in code is pinned down in code.

That way the workflow as a whole gives strong guarantees of execution determinism and avoids llm hallucinations.

Where hallucinations are possible, the workflow steps can also be adjusted to introduce cross-checking steps, which further raises execution determinism while still making use of the large model's capabilities.

Work task templates can keep iterating based on how operations go. Such iteration requests may come from an administrator or from the agent itself. To support this, work task templates must support multi-version management, and running an old version alongside a new one must not conflict. Such coexistence of versions should not be the norm: in the end a work task template should have only one version. And if multi-version compatibility is very hard, then in most cases — as long as the task is not very heavyweight — the old task can simply be dropped and re-run with the new version.

### Workspace

Every task should have its own workspace.

For development tasks the workspace should be a worktree of the git repo the development needs. Note that multi-repo collaborative development is possible; in that case the workspace should contain several repos, and a worktree for each repo.

For non-development tasks — system operations, content operations after launch, and so on — execution should also open a separate workspace. Since these tasks usually do not involve a git repo, no worktree is needed; isolation can be done by creating a subdirectory under /tmp or some other dedicated directory.

A workspace should be guaranteed to have only one agent working in it at a time. At the same time, an agent that has finished its work should be allowed to hand the workspace over to another agent to carry on from.



### Roles

A role defines a kind of worker setup, confining the agent to a specific context and avoiding pollution by irrelevant information.

Each role has specific tools it may use, plus work task templates.

Common roles are:

- developer: understands the design documents, breaks concrete tasks down, implements the functionality the documents require, makes small adjustments and updates to the design documents, writes code unit tests, and so on.
- integration: gates the development of a feature globally from the user's point of view, reviews design documents and the developer's implementation documents, designs integration test cases, and diagnoses test problems, thereby ensuring the feature is delivered. Integration should be the role with the most complete understanding of the project.
- site operation: technical operations, maintaining third-party dependencies (e.g. the database, cache and message system a project needs), deploying the online system, checking monitoring, upgrades, and so on
- product operation: business maintenance after launch, growth, content operations, understanding customer feedback, data analysis, and so on.
- artist: work related to the music and art a project needs.



### Tickets and collaboration between roles

Every task is a Temporal workflow produced from a work task template. There are several ways it can be produced:

1. created directly by some agent
2. triggered manually by an admin (a human)
3. triggered on a schedule by some scheduled program

However it is triggered, this workflow corresponds uniquely to one ticket. Through the console, the admin has a global view of every ticket currently in progress. Agents exchange information and collaborate mainly through workflows.

For example, if an agent wants another role to do something, it triggers a workflow with the requirement as input. The workflow runs the corresponding work template; if a step in the template needs an agent of that role, the workflow starts that agent and feeds it the requirement. When that agent finishes, what it delivered is stated clearly and recorded on the workflow, and if later steps involve other roles they can carry on with that as context.

When everything is done, all work results are staged on the workflow, and the workflow enters its last activity (settled), waiting for the final delivery approval.

Integration, as the person who gates the project globally, periodically steps in to check all workflows; for workflows waiting for delivery it examines the result and approves or rejects it. If approved, the workflow ends. If not, the approval comments are stated and the workflow can be re-run (or a new workflow can be opened and simply linked to the previous one).

Approval does not necessarily happen only at the end; it can also happen on some intermediate activity, and the approver may be an agent or a human.

Given the above, multiple roles usually do not need DSH's agent-to-agent communication mechanism. So when is that mechanism needed? For instance, when a step of a task must be split across several subagents, those agents can coordinate through that mechanism. Whether such a case could also communicate through a workflow requires case-by-case analysis.

Our tickets do not need to wrap workflows: one ticket corresponding to one workflow is enough. Conversely, several workflows may correspond to one ticket (subflows, re-runs and the like). Business-related attributes can, as needed, be stored in different areas of the workflow (search attribute, memo, query handler, etc.).

Agent execution logs and workflow logs must be recordable, so that the admin can inspect and diagnose execution problems.

### Automatic conflict resolution loop

Before a development lane merges in there is a programmatic merge check gate: it rehearses merging the lane into the trunk, and a detected conflict turns it red.
The gap before this was (see the 260825 evidence in the Problem section): a detected conflict could only go to blocked for a human to resolve,
while the vast majority of parallel collisions are purely textual proximity on adjacent lines of the same file, so what the human resolves is merely a mechanical action.

This loop wires conflict resolution into the agent's autonomous chain, with the mechanism in four layers:

1. **Red-light classification**: the merge check separates a "rehearsal conflict" from the other red lights (no commit / dirty worktree / re-verification red).
   Only "everything else green, rehearsal conflict the only failure" enters the resolution loop; other red lights stay blocked
   for a human — first let the human clear the basic problems, and do not try to resolve conflicts on top of a broken state. An abnormal rehearsal itself (no conflict list
   could be produced) is also treated as a non-conflict red light, so the resolution loop does not spin idle.
2. **Automatic resolution**: a detected conflict is immediately reworked back to the development stage, without waiting for a human instruction. The rework carries the list of conflicting
   files and a summary of the merge context. Resolution reuses the existing division of labor of "the agent writes, the worker lands it on disk":
   the agent sandbox cannot touch the repository itself, so merging the trunk into the lane is run by the worker on the agent's behalf, leaving conflict
   markers in the working files; the agent only edits these files to resolve the markers, and the commit is again landed
   on disk by the worker. The resolution result goes back to integration review as the backstop (no automatic judgment of semantic right or wrong), and a passing review
   naturally returns to the merge check for re-verification.
3. **Loop prevention**: resolution rounds are counted independently, capped at 3; if the same batch of files conflicts repeatedly (identical set)
   or the cap is exceeded, the ticket goes to blocked for a human, the log states the round count and the reason clearly, and the two kinds of message are distinguishable and searchable.
4. **Human review unchanged**: the human approval signature gate and the existing behavior of "conflicts during signature are automatically reworked and re-verified" are unchanged;
   a conflict reworked during signature likewise enters this resolution loop, and conflict resolution and final release remain two separate gates.

> Source epic proposal: t260826-01 (merge_check automatic conflict resolution loop; process improvement, origin in this ticket and in the 260825 discussion of the parallel-ticket conflict evidence)

### Linking epic proposals to tickets

A ticket is the smallest execution unit. But one delivery goal is often split across several tickets; without the layer above tickets,
there is nowhere to track overall progress, and the lifecycle of "discussion → epic proposal → execution → archiving" has no carrier.
**An epic proposal (epic)** is the semantic unit above tickets: one delivery push = one epic proposal = several tickets.
An epic proposal records the goal, acceptance criteria, key decisions and an archival snapshot.

The division of labor between the epic proposal workspace and the knowledge base:

- **notes/** (process): discussion minutes, epic proposals, process records. Not a knowledge base, and not loaded as agent context.
- **docs/** (source of truth): designs, protocols, specifications — the knowledge of a system that keeps evolving. The documents you read when you change the code half a year later.

The link is carried by a **machine-checkable epic code**: every ticket carries the code of the epic it belongs to, and the attribution is guaranteed by the generation path
(when a ticket is opened from epic context the code is injected automatically) rather than by an agent's free judgment, degrading a semantic judgment into
a mechanical check. The existence of the code is strongly validated by the existence of a file.

The archival source of truth is git, not the execution engine: when an epic concludes, the ticket list and the conclusions are frozen into the epic proposal and then archived; the execution engine
carries only process state.

When a `docs/` document is added or substantially changed by an epic proposal, a source label line (`> Source epic proposal: <code>`) is appended at the end of the corresponding section,
serving as a bridge from "what it is" back to "why it is".

> Source epic proposal: epic-linkage (decision rationale in notes/epics/epic-linkage.md)

### Five-layer architecture and the reversed dependency direction

This suyou facility is to become a standalone general-purpose IDE project, sandbar (see the epic proposal). The precondition for standing alone is
**reversing the dependency direction**: today the engine lives inside the project repo (`server/`) and the engine reads the project; the target
shape is that **projects register with the IDE**, with not a single line of engine code in the project repo. The route has three steps —
**contractualize → reverse in place → physically relocate, in that order, never reversed**: first converge the contact surface between the engine and the project inside the project repo
into a contract (the engine reads the project only through the contract), then reverse, and only then physically relocate into a standalone repo.

The five-layer model divides up "who owns what", and ownership determines upgrade responsibility:

| Layer | What it holds | Ownership |
| --- | --- | --- |
| dsh platform | dsh CLI, console, client-runtime, cordis, approval seam, session persistence | upstream, **follow but never touch**: declare the compatibility range and upgrade with the version |
| sandbar itself | temporal engine, ticket system, templates such as dev-lane, worker lifecycle, observability, installer | the sandbar repo, machine-level install and upgrade |
| Built-in extensions | dsh plugin set: workbench, providers, epics, knowledge (a first-class component), role skeletons | follow sandbar, upgrade with sandbar |
| Machine-level configuration | project registry, credentials, default models, provider registration | out of the repo, into `~/.sandbar/` |
| Workspace | policy configuration (merge-checks.yaml, verify.yaml), this project's model-routes, persona overrides, epic proposal content, tool bridge | stays in the project repo, in the agreed directory `.sandbar/` |

Note the distinction from the "five-layer structure" in this document's High level section (role charter / preset / roster / dispatch tool / decision chain,
which is this facility's **internal layering**): this "five-layer architecture" is a **deployment-ownership layering**, answering "who is in charge
when something is upgraded".

The contact surface between a project and the IDE (which files, what semantics, what version) is defined entirely by
the sandbar Project Onboarding Contract v1: the five promoted items, the schema version number, the three-state shutdown semantics and
the docs context composition order are all in that document and are not repeated here. The contract surface is the upgrade burden — every promoted item
adds one more compatibility obligation to each IDE version bump, so v1 deliberately promotes only five items and leaves the rest (templates, plugin API,
the `.suyou` layout) as sandbar internals that may change at any time.

> Source epic proposal: sandbar

### Observability: the parts convention for the executing subject

For the ticket console to answer "who is doing this step", the executing subject must first be formalized out of scattered desc comments and `exit: human`
entries. The convention is as follows:

- **The unit of declaration is the activities inside a stage (parts), not a single value per stage**. Mixed execution already exists
  (e.g. the development lane's implement = agent writes code + the worker's settle script lands it on disk + the self-test/verify script gate;
  merge = human signature + script bookkeeping and lane cleanup), so a single-valued field would force the code to lie.
- **The enumeration has three combinable values**: `agent` (🤖 agent execution) / `script` (⚙️ script · programmatic) /
  `human` (👤 human), declared as an ordered tuple on `Stage.parts` (`engine/shared.py`, the enumeration constant
  `PART_KINDS`); the yaml snapshot and the ticket console's stage-chain badges are both derived from it.
  The generator hard-fails when any stage lacks parts, degrading "all declared" from good intentions to a mechanical check.
- **What counts**: scripts required to land business artifacts count (the worker landing files on disk, merge bookkeeping);
  engine plumbing does not count (result-file polling / idempotency cache, the mechanical preparation in prepare_human_gate,
  the settle that spins idle in a non-worktree lane).
- **The dynamic source of truth is still Temporal history**: parts is only a static declaration (used for console rendering and cross-checking the books),
  while actual execution is governed by history; the two are not mixed. One template exists today (**dev-lane**; 260824 deleted
  code-lane and build-workbench, and **by host order 260904 the four templates content-pipeline / proofread /
  regression / cleanup were retired** — after the ticket merges in, independent regression capability is carried by integration running it directly on the main side
  or by opening a dev-lane; the non-ticket inspection dispatcher-scan is not part of the ticket template surface and is kept. The old
  "six templates / five templates" wording predates the deletions).
- **Evolution safety**: adding only metadata fields with defaults to `Stage` does not touch determinism and needs no bump of the patched id;
  a replay run against in-flight tickets via `engine/replay_check.py` is the backstop.

> Source epic proposal: observability (executing subject visible; the conventions for progress heartbeat and token consumption are in the next two sections)

### Observability: the usage aggregation data path and degradation convention

For the ticket console to answer "how many tokens did this step / this ticket cost", the statistics add no new instrumentation and consume the lane session
events on disk directly. The convention is as follows (landed in t260828-07):

- **Two endpoints on one path**: `agent-live` (live activity) and `agent-usage` (token aggregation)
  share one set of code for "locating the lane session file + full zstd decompression + event extraction"
  (the `resolveSessionFile`/`decompressSession` in `workbench/src/host/agent-live.ts`
  + the aggregation in `agent-usage.ts`), rather than starting a separate parsing implementation, so the two tickets do not drift apart and fight each other.
- **Summation convention**: sum only the
  `data.usage{inputTokens,outputTokens,cacheReadTokens}` in `assistant/message` events. The usage of the same name in `assistant/chunk`
  (`data.chunk.type==='usage'`) is a streaming mirror of the same data and is **not counted** —
  counting both would double it. Model attribution: usage events carry no model, so a sequential scan maintains the "current model"
  (from `request/context`'s `data.{provider,model}`, with `request/header`'s
  `data.header.config.{provider,model}` as the fallback), and each usage is attributed to the model in force at that time.
- **Splitting by stage uses time windows**: a session is reused as `<ticket id>-<role>`, with one role spanning stages,
  and the windows come from `state==='running'` entries in the workflow timeline (the ISO timestamps placed by
  `base.py _mark`): window i = [from_i, from_{i+1}), with the last window open-ended. Re-entry into the same stage
  (rework) naturally produces multiple windows. Events before the first window go only into the whole-ticket total and land on no stage
  (total ≥ ΣbyStage — that is the convention). The session files of all roles, one each, are summed in full.
- **UI restraint**: inline `in/out` numbers on the agent legs of the stage chain (the model name shows only when there are several models), and a single
  summary line in the detail header (number of agent stages + total input/output + models); `cacheRead` and exact values are tucked into
  a hover. No new tab, no trend charts.
- **Degradation convention**: session directory/file missing, zstd unavailable, decompression failed, no usage event →
  the endpoint returns `200 {exists:false, reason <plain language>}` and the UI shows "—" without erroring; an illegal ticket id or
  worktree/workspace fields out of bounds → `4xx` to prevent leakage through (the same hard acceptance item as agent-live).
  For historical merged tickets, after lane cleanup there is no session file, so the executing-subject icons show without numbers — no
  pre-merge freeze is done (user ruling 2026-08-25); statistics start from the feature's launch.
- **Regression**: `workbench/smoke/agent-usage.mjs` (window derivation / double-count prevention / attribution / malformed input /
  leakage prevention / soft degrade) runs directly, node ≥22.18.

> Source epic proposal: observability (usage aggregation endpoint + inline numbers + header totals)

### Observability: the progress heartbeat and session event stream paths

For the ticket console to answer "where has it got to now, is the agent still alive", the design has two complementary paths, each answering half:
the heartbeat path answers progress and liveness, and the session event stream path answers content-level activity. The convention is as follows:

- **Heartbeat path (progress and liveness)**: the activity of an agent stage periodically
  reports a lightweight heartbeat to the engine while waiting for the result file; the payload is a progress quadruple — current phase, generation counter within the stage, polling
  count, session log size. It is attached to the Temporal pending activity instead of standing up a separate reporting channel
  because its visibility is correct by nature: a heartbeat exists only for a RUNNING execution and disappears when the ticket ends, needing no
  extra lifecycle management. The query side picks it out of the engine's pending activity information, and a failed pickup always
  degrades to "no data", never affecting the ticket query main path. Non-agent stages produce no heartbeat, and a stub-mode
  heartbeat is not structured data — both fall into the same soft degrade, with the UI showing plain language rather than an error.
- **Session event stream path (content-level activity)**: the source of truth is the agent session file written to disk inside the lane
  workspace (a zstd-compressed line-oriented event stream, read-only, whole-file rewrites strictly forbidden). It is consumed by decompressing the whole file
  and taking a few interesting events from the tail to feed the live activity panel — the tail only, because only "now" matters;
  the whole decompression, because the compressed format does not support random reads; and the decompressed output is capped to avoid blowing up memory. The panel
  is collapsed by default and does not poll — UI restraint: observability is something you look at when you open it, so no standing traffic is created for it.
- **Two endpoints on one path**: `agent-live` (live activity) and `agent-usage` (token aggregation)
  share the same "locate the lane session file + full zstd decompression + event extraction" implementation (see the previous section), rather than a separate
  parsing implementation.
- **Pulse-line UI**: one pulse line in a running ticket's detail — current phase, elapsed time for this stage, session
  size and growth rate, heartbeat age. A suspected hang (heartbeat stalled or session size no longer growing) is only flagged in red,
  shown but never acted on: automatic intervention would overreach, and the judgment is left to humans; the flagging threshold is a UI decision parameter, tunable,
  not a protocol promise.
- **Degradation convention**: session file missing, decompression tool unavailable, decompression failed, cap exceeded → the endpoint returns
  "does not exist + a plain-language reason", and the UI still shows that without erroring; ticket lookup fields out of bounds → `4xx` to prevent leakage through
  (the same hard acceptance item as the usage section). For historical merged tickets, after lane cleanup there is no session file and the heartbeat
  vanishes with the ticket's end — no pre-merge freeze is done, and observation starts from the feature's launch (the same
  decision as the usage section).

> Source epic proposal: observability (progress visible — running pulse line + live activity panel)

### Lane acceleration: the arbitrate ∥ acceptance parallel fork and conditional release on review

Most of the end-to-end ticket latency is serial round trips (measured on t260903-01: review spends 10 min purely on serial tool round trips;
arbitrate→acceptance is serial with no data dependency; a minor blemish reworking a whole plan redo costs ~20 min). Two changes
(t260903-02):

1. **arbitrate ∥ acceptance_walkthrough parallel fork**: after the mechanical integration test output is produced, arbitration
   (a three-state verdict from the technical perspective) and the acceptance walkthrough (a report from the user perspective) consume the same test result with no data dependency, and
   gather in parallel. The ordering is pinned down: gather completes → a single settle_lane point (a tests-fault change to the test set
   must be landed first, then the mechanical test re-run) → arbitrate verdict decision → routing. When arbitration is not pass, this round's
   walkthrough result is void (traced in the timeline and searchable) and the walkthrough is redone after the loop converges; a format-correction round re-runs only the arbitration edge.
   Trade-off: the walkthrough session switches to a ticket-stage-specific session id (so it does not write the same session
   file concurrently with the arbitration edge), and therefore the walkthrough session is not located by agent-live/agent-usage's ticket-role lookup — its content is still obtainable
   from the result file / logs, with no change on the observability side.
2. **review_plan's third state, "conditional release"**: the review conclusion has three states `verdict=pass|conditional|
   reject` (summary is the sole marker; **status=failed always reworks** — a contradictory state takes the conservative side, since release is a
   high-risk action). conditional = minor blemishes (wording level, not affecting the plan's structure / write-set boundary / acceptance criteria), which are not
   rework-worthy: the change requests go straight to the implement stage for execution (injected via previous_context), skipping the plan
   redo + re-review and not counting as a rework round; reject still follows the existing rework loop; the final say is backstopped by the later human review gate (merge).

Both are wrapped in the isomorphic workflow.patched boolean gate (dev-lane-review-conditional-v1 /
dev-lane-arb-acc-parallel-v1): a suspended old workflow replays down the old serial branch, without bumping
PATCH_ID. Supporting discipline: before changing the word list / counts / chain order, first grep the registered scenarios and selfcheck's exact assertions;
locks grow in step with the feature (this round the two locks sc_check_auto_rework_trace / sc_auto_rework_trace move
with the 13th main-chain phase value arb_acc_parallel from 12 to 13, and the count lock moves with the new rework point).

> Source epic proposal: t260903-02

### Worker Runtime



One worker process per ticket. The worker starts along with ticket creation, and after the ticket is closed/terminated the worker is

reclaimed by a periodic checker. Reasons for not sharing a worker process:



1. **Code hot update**: code changes made after ticket A completes affect only the workers of new tickets, not tickets already running.

2. **Fault isolation**: if the agent of one ticket crashes its worker, other tickets are unaffected.

3. **Simplicity**: no zero-downtime restart, no version management — the worker lives and dies with its ticket.



**Periodic checker** `worker_janitor` (a Temporal Schedule or cron, every 5 minutes):

- scan all closed/terminated tickets → reclaim the corresponding worker processes

- scan all worker processes → find zombie workers with no corresponding ticket → reclaim them



**How it starts**: a corresponding worker instance is created when the ticket is created. That worker serves only this ticket's workflow task. By the time the workflow is submitted the worker is already running, so activities execute directly.





---



## Related documents

- [sandbar Project Onboarding Contract v1](../design/sandbar-project-onboarding-contract-v1.md) — the five contact surfaces by which a project registers with the IDE: schema version, three-state shutdown semantics, context composition order (the contractual basis for the reversed dependency direction of the five-layer architecture)
- [ticket workflow console design](../design/ticket-workflow-console-design.md) — workflow templates / handoff / singleton / human gate / Temporal evolution (the detailed implementation of R1/R5/R6)
- [knowledge base design](../design/knowledge-base-design.md) — the docs-first master outline (the mechanism source of R2/R3/R6)
- [design doc writing guide](../design/design-doc-writing-guide.md) — the structural basis of this document
- `server/roles/README.md` — the operational overview (the source of truth for the parts of this document already implemented)

