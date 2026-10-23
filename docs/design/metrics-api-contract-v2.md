---
title: metrics Definitions and API Contract v2
category: design
tags:
  - metrics
  - contract
  - API
status: active
updated: 2026-10-21
---

# metrics Definitions and API Contract v2

> This document is the frozen contract for the metrics v2 data layer (ticket t261021-06).
> It **extends** [metrics-api-contract-v1.md](metrics-api-contract-v1.md); v1 stays frozen as the
> historical document and every rule it does not contradict carries over. Per v1 block 6, a field
> addition "must not be rewritten in place", so this delta lives in a new file.
> Every new field below states: source of truth, formula, known approximation, and degrade
> behavior. The consuming layout is the approved mock (host 261021,
> `metrics-tab-mock.html`); that file fixes the content, not the transport.

## Version discipline (comment C1 of the plan review)

- The response field `cache.source_version` and the per-ticket cache record field
  `source_version` follow **this document's version from here on**: after this bump both are
  `v3`. The bump voids the whole per-ticket cache once and it is recomputed on demand (v1 block 3
  explicitly allows the cache to be discarded and rebuilt).
- Historical mapping, written down so nobody "fixes" one side to match the other:
  `source_version` was `'v2'` while the contract document title was v1 — the t260904-09 ticket
  bumped the counter for the settle-snapshot semantics change without retitling the document.
  From v2 of this document onward the counter and the document title move together (`'v3'` at
  this freeze). Treat `source_version` as a monotonic cache-generation counter in this
  document's lineage.

## What v2 adds

Additive top-level response keys on the three data views (`view=time|delivery|token`):
`workflows`, `stages`, `project_sessions`, `epics`, and additive fields inside `kpis`.
No existing field changes name, position, or meaning. The `health` view keeps its direct-query
contract: each new key there is `null` plus a reason string ("not in the health direct-query
path") — a named degrade, never zero-fill. The two front doors (HTTP
`GET /sandbar-workbench/api/wf/metrics` and `metrics-cli.mjs`) share one implementation, so both
stay byte-identical; the two-front-door golden baselines are re-baselined by the integration
stage because the body gains keys by design.

### Aggregate population (one rule, all new blocks)

The new blocks are computed over the **window population**: ticket rows anchored into the
request window by the v1 single-anchor rule (closed tickets by `closed_ms`, open tickets by
`created_ms`), grouped **per workflow** by the row's `workflow` field. Rows with an empty
workflow field never enter the per-workflow grouping (a row without a chain cannot be keyed).
Chains are never mixed: every per-stage row is keyed `(workflow, stage)` and every per-workflow
aggregate only sums its own chain's stages. `kpis` keeps its v1 population (the selected
`template`'s records) so existing KPI numbers do not move; the cross-workflow blocks are the
addition, not a redefinition.

In `mode=fast` the per-workflow population is served from cache only; a cache-miss ticket
shortens its workflow's aggregates and the shortfall is counted in the response `reason`
(notices) — a partial answer is always labeled, never silent.

## Block: `workflows[]`

Per workflow present in the window population (one entry per workflow id):

| Field | Type | Source of truth / formula | Degrade |
|---|---|---|---|
| `workflow` | string | the ticket row's `workflow` value | — |
| `tickets` | number | count of population rows of this workflow | 0 only when the workflow genuinely has zero in-window rows (then the entry is omitted instead) |
| `elapsed_ms` | number | sum over the workflow's population records of the sum of `durations.by_stage` values — the same stage windows the time view already uses (v1 handoff approximation, last window closed per v1 block 1) | follows the v1 duration degrades; a ticket with no running timeline contributes 0 windows and is counted in notices |
| `stage_runs` | number | sum over records of `stage_runs` values (see cache record below) | `null` + reason when no record of this workflow has a readable history (`rounds_ok`) |
| `rounds_per_ticket` | number | `stage_runs / tickets_with_readable_history` (see below) | `null` + reason when the denominator is 0 |

`tickets_with_readable_history` = records whose history was readable (`rounds_ok=true`).
**Missing rounds never becomes 0**: a ticket whose history cannot be read is excluded from the
rounds denominator and counted in notices.

**Rounds source of truth and known approximation.** The workbench read path has no direct
Temporal event-history access today; the reachable truth is the ticket timeline (the same
`state==='running'` entries the time view windows on). `stage_runs[stage]` = the count of
running entries for that stage in one ticket's timeline. A stage that executed more than once
for one ticket counts its executions — rework re-entry counts; a retry that produces a new
running mark counts; **a silent retry that does not re-mark `running` is invisible** — this is a
declared known approximation, to be replaced when an engine-side event-history face exists.

## Block: `stages[]`

Per `(workflow, stage)`, the stage axis being that workflow's own stages chain in chain order:

| Field | Type | Source of truth / formula | Degrade |
|---|---|---|---|
| `workflow`, `stage` | string | the key; a stage row always names both — chains are never mixed | — |
| `runs` | number | sum of `stage_runs[stage]` over the workflow's population records | `null` + reason when no record has a readable history |
| `tickets_reached` | number | records of this workflow whose `stage_runs[stage] >= 1` | — |
| `avg_rounds_per_ticket` | number | `runs / tickets_reached` — the ticket spec's "runs / tickets that reached that stage" | `null` + reason when `tickets_reached` is 0 |
| `elapsed_ms` | number | sum of `durations.by_stage[stage]` over the workflow's population records (same windows as the time view) | follows v1 duration degrades |

## Block: `project_sessions`

Token spend of sessions that carry **no ticket id**, discovered under the **project root's**
`.dsh/sessions` (the registry primary directory, not a ticket worktree).

- **Discovery face (new)**: `resolveProjectSessionFiles(repoRoot, listedTicketIds)` in
  `agent-usage.ts`. It traverses `<repoRoot>/.dsh/sessions/<slug>/<name>/`, keeps only session
  directories whose name does **not** match a listed ticket id and does not carry the
  `t<digits>-<digits>` ticket-id shape, picks the newest session file per directory
  (`pickNewestSessionFile`, two-generation naming aware), and **refuses any resolved path
  outside the workspace root** exactly like `resolveAllSessionFiles` (`refused=true` + reason →
  the whole block degrades to `null` + that reason).
- **Parsing**: the same `aggregateTicketUsage` as the per-ticket path, called with empty stage
  windows (totals only; no per-stage split exists for project sessions).
- **Attribution**: by session slug. The slug directory name is the bucket key; the mock's two
  buckets are `executor` and `global`; any other slug becomes its own bucket named verbatim.

| Field | Type | Source of truth / formula | Degrade |
|---|---|---|---|
| `buckets` | object | per slug: `{in, out, cache_read, files}` summed from `assistant/message` usage events | — |
| `total` | object | `{in, out, cache_read}` = sum of buckets | `null` + reason when every file was unreadable / produced no usage |
| `reason` | string | present when: the sessions directory does not exist; the discovery set is empty (a project with no project-level sessions → the whole block is `null` + reason); any file was unreadable or suspect (the per-file reason is carried up, never swallowed) | — |

`null` block (with reason) is the named degrade for "a project with no project-level
sessions"; it is never zero-filled into buckets.

## Block: extended `kpis` (additive fields, names verbatim from the ticket spec)

Population = the v1 KPI population (selected template, single-anchor window rule).

| Field | Type | Formula / source | Degrade (null + reason, never zero-fill) |
|---|---|---|---|
| `rework_rate` | number 0..1 | closed tickets with at least one stage run count > 1, divided by closed tickets with a readable history | `null` when no closed ticket in window has a readable history |
| `throughput_per_day` | number | closed-in-window tickets / window days; for `window=all` the span is `now − earliest created_ms` in the population, floored at 1 day (known approximation: the window span is data-derived there) | `null` when no closed ticket in window |
| `median_lead_time` | number | median of `closed_ms − created_ms` over closed tickets with both anchors; **unit is milliseconds** (the name carries no unit by spec; this line is the unit's home) | `null` when no such ticket |
| `human_wait_share` | number 0..1 | Σ `durations.human_wait` / Σ all stage window durations over population records | `null` when the denominator is 0 |
| `tokens_total` | number | unchanged v1 field (kept, position unchanged) | — |
| `tokens_in_tickets` | number | Σ `tokens.in + tokens.out` over population records | 0 with reason only when every record lacks token data (counted in notices) |
| `tokens_outside_tickets` | number | `project_sessions.total` in+out; `null` when `project_sessions` is `null` | follows `project_sessions` degrade |
| `tokens_per_closed_ticket` | number | `tokens_in_tickets / closed` | `null` when closed = 0 |
| `cache_hit` | number 0..1 | Σ cacheRead / (Σ in + Σ out + Σ cacheRead) over records with token data | `null` when the denominator is 0 |

**No money.** There is no price table, so no cost field is added anywhere in v2.

## Block: `epics[]`

Per epic present in the window population (rows grouped by the row's `epic` field; empty-epic
rows are not an epic). Ordering is the consumer's choice; the payload carries
`last_activity_ms` so the tab can default to it.

| Field | Type | Source of truth / formula | Degrade |
|---|---|---|---|
| `epic` | string | the row's `epic` value | — |
| `tickets` | number | population rows of this epic | an epic with no in-window rows does not appear; `epics: null` + reason when the whole window has no epic rows |
| `elapsed_ms` | number | Σ stage window durations of the epic's records (same windows as the time view) | follows v1 duration degrades |
| `tokens` | number | Σ `tokens.in + tokens.out` of the epic's records | `null` + reason when no record of the epic has token data (never 0-filled) |
| `last_activity_ms` | number | **source of truth**: the `updated` column of the epic's most recently updated ticket list row — a declared approximation of "the modify time of the epic's most recently modified ticket"; the metrics read path has no ticket-file mtimes | `null` + reason when no row carries a parseable `updated` value |

## Cache record additions (and the bump)

The per-ticket cache record gains two additive fields:

- `stage_runs: Record<string, number>` — per-stage running-entry counts (see the rounds source
  of truth above); computed in the same pass that derives the stage windows.
- `rounds_ok: boolean` — true when the ticket's timeline was readable (an array was present).
  False means "rounds unknown": the ticket is excluded from all rounds denominators and counted
  in notices. Unknown is never coerced to a run count of 0.

Both fields ride the `source_version='v3'` bump: older records are voided wholesale and
recomputed, so no read-side back-compat shims are needed.

## Failure-mode tradeoff table (review comment C2; reuse discipline)

The project-sessions face reuses two existing implementations. Their handled failure modes,
item by item:

| Failure mode | Brought by | Disposition in v2 |
|---|---|---|
| sessions directory does not exist | `resolveAllSessionFiles` | **Brought** — discovery returns empty + reason; block degrades `null` + reason |
| session directory unreadable (readdir throws) | `resolveAllSessionFiles` | **Brought** — reason string carried into the block |
| unreadable/corrupt session file (decompress/parse) | `aggregateTicketUsage` per-file reason collection | **Brought** — one bad file never destroys the totals of good files; the reason surfaces in `project_sessions.reason` and suspect files surface via the existing S1 flag |
| out-of-workspace path (path traversal) | `resolveAllSessionFiles` double guard (isWithin + refused) | **Brought verbatim** — `refused=true` + reason → block `null` + reason |
| no usage events in a file | `aggregateTicketUsage` | **Brought** — file contributes 0 with a reason, totals of the rest stand |
| format not recognized (S1 suspect) | `aggregateTicketUsage` / `judgeSessionLines` | **Brought** — totals from good files stand, bad files named in reason |
| uncovered record types (newer dsh generation) | `aggregateTicketUsage` | **Brought** — union surfaced, totals still accumulate |
| empty stage windows | `aggregateTicketUsage` signature | **Adapted** — called with `[]` intentionally: project sessions have no stage windows, totals only |
| per-stage token split | per-ticket path only | **Not applicable** — no stage axis exists for project sessions |
| rounds unknown (unreadable history) | new in v2 | **New** — exclusion from denominators + notice; never 0 |

## Degrade summary (all named, never zero-filled)

1. Ticket with no session files → existing v1 SKIP (tokens `null` + reason).
2. Epic with no (in-window) tickets → no entry; whole-block `null` + reason when the window has
   no epic rows at all.
3. Unreadable session file → per-file reason surfaced in `project_sessions.reason`; good files
   still counted.
4. Project with no project-level sessions → `project_sessions: null` + reason.
5. Ticket with unreadable history → excluded from rounds denominators, counted in notices
   (`rounds_ok=false`).
6. `health` view → each new block/field `null` + reason "not in the health direct-query path".

## Closing the loop

The mock's data asks are each answered by exactly one block with one source of truth:
stage runs → `stages[]`/cache `stage_runs`; per-workflow totals → `workflows[]`; no-ticket
session spend → `project_sessions`; rework/throughput/lead-time/token KPIs → extended `kpis`;
per-epic rollups → `epics[]`. Degrade behavior is named per field; the contract is frozen so
implementation and acceptance take it as the single source of truth.
