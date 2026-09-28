---
title: metrics Definitions and API Contract v1
category: design
tags:
  - metrics
  - contract
  - API
status: active
updated: 2026-09-28
---

# metrics Definitions and API Contract v1

> **This is a contract document; field-level freezing is its very purpose, so it is exempt from
> the "Proposal has no API names / field names" item in the self-check list of the
> [Design Document Writing Guide](design-doc-writing-guide.md); every other self-check item still applies.**
>
> This document freezes the three-dimensional data definitions of M0 in the metrics epic
> (notes/epics/metrics.md), the `/metrics` API request/response, the cache record schema, and
> the degrade behavior. Once v1 is frozen, the implementation and acceptance of every M1a/M2/M3
> ticket take this document as the single source of truth; any field addition or removal requires
> a new ticket to bump the version (see block 6) and must not be rewritten in place.
> §6 of `docs/design/metrics-panel-ui-plan.md` keeps an illustrative copy and points back here.

## Problem

### What is wrong today

The metrics epic's M1a (read-side aggregation backend), the M2 series (the panel's four views),
and M3 (reconciliation acceptance) are several parallel tickets, and all of them consume the same
set of numbers. Today the only contract content is the 12 illustrative lines of §6 in the
*metrics Panel UI Plan*: one line of parameters, one line of ChartSpec, one line of cache schema —
field semantics, default values, invalid-value behavior, and degrade paths are all undefined.
Parallel implementations are bound to talk past each other; M3's two hard acceptance items —
"chart numbers vs manual reconciliation" and "byte-identical across the two front doors" — have no
definition in writing to stand on, and reconciliation has no basis for a red/green verdict.

### Background

- **Three sources of truth** (key decision 1 of the epic): time = Temporal timeline (the timestamps
  of entries whose `state==='running'` is a terminal state); delivery = git (lane branch
  diff/commit); token = session files persisted under `~/.dsh` (the parsing path already delivered
  by t260828-07).
- **The t260828-07 usage path** (the "usage aggregation data path" section of the mechanism doc):
  the token statistics implementation already present in the ticket console
  (`workbench/src/host/agent-usage.ts`), including window splitting, event distillation, and a set
  of failure modes already handled — this document largely follows its definitions and its
  degrade precedents.
- **Two front doors**: a single aggregation implementation serves two entry points — the workbench
  host's HTTP `GET /metrics` (serving the UI) and the node CLI (serving agents/scripts/CI);
  byte-identical to the same request is a hard acceptance item of the M3 baseline lock.
- **Multiple templates**: the aggregation key = (template, stage); the stage axis = the STAGES
  chain order of the selected template; templates are never mixed (key decision 5 of the epic).

### Evidence

- The whole contract content of UI plan §6 is only 12 lines, with no field semantics and no error
  behavior;
- M0 of the epic explicitly requires "put it in writing and freeze it, to keep the later M1a/M2
  tickets from talking past each other";
- M3 requires "sample 3 closed tickets for reconciliation", "LOC against `git diff --stat`", and
  "byte-identical across the two front doors", all three of which need the definitions to come
  first.

## Requirement

Each item is verifiable:

1. **Every one of the three dimensions has a single source of truth, an explicit formula, and a
   declared known approximation**: after reading this document, the M1a implementer needs to make
   no further definitional decision;
2. **The `/metrics` request parameter enums + default values + invalid-value behavior are defined
   item by item; the response JSON is defined field by field (including types)**, so it can be
   implemented literally;
3. **The cache record schema is put in writing field by field (including types) plus its
   invalidation rules**, consistent with key decision 2 of the epic (versioned invalidation via
   source_version/engine_version/updated_ts);
4. **The comparison surface for byte-identical behavior across the two front doors is put in
   writing**: once the M3 baseline comparison script is implemented per this document's rules, it
   will not naturally go red because of clock fields;
5. **The error and degrade paths are put in writing**: invalid parameters blocked by 4xx, missing
   credentials SKIP, discarded-and-rebuilt cache not raising errors, all including a
   malformed / missing / late three-state case table, each with its expected behavior;
6. **Anything claimed to follow an existing implementation must come with a failure-mode
   trade-off list** (the eight items of agent-usage.ts declared one by one as carried over / not
   carried over + reasons);
7. The delivery dimension's source-of-truth lifetime problem (lane branches cleaned up after
   merge vs M3 reconciling already-closed tickets) has an explicit solution written into the
   schema semantics.

## Nongoal

- **No design for precise stage durations in v2** (only its existence is registered: v2 = precise
  terminal states at 08, trigger conditions left to a future ticket);
- **No deriving the delivery dimension backwards by digging through main's history**: commits
  merged across epics cannot be attributed to a single ticket, so the freeze approach is chosen
  (see block 3);
- **The health view does not go into the cache**: it queries Temporal directly (key decision 6 of
  the epic);
- **No freezing of chart visual styling**: layout belongs to the UI plan and the mockups;
- **No normalization of stage categories** (the six-class view of plan/review/implement/... is an
  M3+ option);
- **No change to ticket engine behavior** (epic red line; the mount point for the delivery freeze
  belongs to M1a's bridge side);
- **No billing/amount**: token counts only.

## Proposal

### Block 1: Three-dimensional definitions

#### Time dimension

- **stage duration v1 = handoff approximation**: take the ISO timestamps of entries whose
  `state==='running'` from the Temporal timeline; the i-th window = [from_i, from_{i+1}), and the
  last window is open-ended; the same role across stages is split by the windows, and a rework
  re-entry = the sum of multiple windows. The window-splitting implementation reuses the window
  derivation logic of agent-usage.ts.
- **Last-window closing rule**: the right end of the last window = min(next window's from,
  closed_ts) — when a closed terminal-state entry arrives late, the closed instant closes the
  window, so the open-ended last window does not extend indefinitely.
- **human_wait** = the total window duration of human gate stages (stages with exit:human), listed
  separately; it is the data source for the orange "human review wait" block of the donut and for
  the "humans waiting vs machines" secondary chart.
- **Single-ticket delivery duration** = the closed terminal-state instant − the creation instant.
- **v2 = precise terminal states at 08**: registered only as a direction for a later version, not
  part of the v1 freeze.
- Known approximation (hover text): v1 durations include agent queueing/waiting gaps, not pure
  execution time; the definition ⓘ hover declares "duration v1 = handoff approximation / v2 = 08
  precise terminal states".

#### Delivery dimension

- **LOC** = the lane branch diff vs base additions/deletions, **listed separately and not merged
  into a net value**; the M3 reconciliation baseline command: `git diff <base>...<lane>
  --shortstat`.
- **base pinned**: base = the trunk commit at the lane creation point (equivalent to the parent of
  the lane's first commit). **A mid-flight "trunk merged into the lane" does not change base** —
  the diff is always against the creation point, and the definition does not drift with the
  computation instant. The base commit hash is frozen into the cache record's `delivery.base`, and
  both recomputation and reconciliation read that field instead of resolving merge-base on the
  spot.
- **commits** = `git rev-list --count <base>..<lane>`, including commits persisted by the worker on
  the ticket's behalf.
- Source-of-truth lifetime (Requirement 7): see the freeze semantics in block 3.

#### token dimension

Following the t260828-07 definitions:

- Only the `data.usage{inputTokens, outputTokens, cacheReadTokens}` inside `assistant/message`
  events are summed; the same-named usage of `assistant/chunk`
  (`data.chunk.type==='usage'`) is a streaming mirror of the same thing and is **not counted**
  (counting both would double it);
- **cacheRead is listed separately** and not folded into `tokens_total`; `tokens_total` = in + out
  combined;
- Model attribution: usage events carry no model, so a sequential scan maintains the "current
  model" (`data.{provider,model}` of `request/context` takes precedence, with
  `data.header.config.{provider,model}` of `request/header` as the fallback), and each usage is
  attributed to the model in effect at that moment.

### Block 2: /metrics API request/response contract (frozen)

```
GET /metrics?window=7d|30d|all&epic=<code|all|none>&project=<key>&template=<id>&view=time|delivery|token|health&mode=full|fast
```

| Parameter | Enum/type | Default | Notes |
| --- | --- | --- | --- |
| window | `7d` \| `30d` \| `all` | `7d` | time window |
| epic | epic code \| `all` \| `none` | `all` | `none`=fallback bucket for historical tickets with no code (the only enum extension this document makes to UI plan §6; rationale: attribution depends on a code injected by the generation path, and existing tickets carry no such attribute) |
| project | project key | currently registered project | out of range / nonexistent → 4xx |
| template | template id | `dev-lane` | determines the stage axis chain order |
| view | `time` \| `delivery` \| `token` \| `health` | required | absent → 4xx |
| mode | `full` \| `fast` | `full` | `fast`=cache-only aggregate (cache-first emits the snapshot, missing tickets are not computed on the spot, `cache.status='stale'`); `full`=full lazy computation (t260903-09 bump) |

**Error behavior**: invalid values, a missing required parameter, and a repeated parameter with the
same name are all `4xx {error, reason}` (a repeated parameter gets no "take the first one"
tolerance; it is blocked exactly like an invalid value).

**Response** (200):

```json
{
  "kpis": { "tickets": 0, "closed": 0, "avg_delivery_min": 0.0, "tokens_total": 0 },
  "charts": { "primary": ChartSpec, "secondaries": [ChartSpec, ChartSpec] },
  "generated_at": "ISO8601",
  "cache": { "status": "hit|miss|computed|stale", "computed_at": "ISO8601", "source_version": "v1" }
}
```

```
ChartSpec = { kind: 'bar'|'stackBar'|'hBar'|'donut', title, categories, series[{name,data}], drill: true }
```

- `cache.status`: `hit`=cache hit; `miss`→`computed`=generated lazily this time and then returned;
  `stale`=the cache snapshot in fast mode (tickets may be missing: tickets never computed and
  tickets whose engine version does not match do not enter the snapshot; existing records from an
  older version are approximately attributed to a window by their cache computation instant, and
  missing tickets are surfaced explicitly in reason; the client later replaces it with the full
  request running in the background. t260903-09 bump);
- **Single definition for KPI window attribution (t260903-09 clarification)**: tickets/closed/
  charts/tokens all share one anchor — closed tickets are attributed by their closing terminal-state
  instant and open tickets by their creation instant (gen2 was written this way from the start, but
  the implementation had split off a fourth population with tickets attributed by creation, which
  produced the paradox "closed count > ticket count"; that has been clarified);
- **Literal donut human-review sector contract (pinned by t260903-09)**: the backend donut category
  name "human review wait" is a frozen literal, and the frontend's coloring of the human sector
  keys off it (metrics-charts.isHumanSliceName); renaming it on the backend must change the
  frontend UT (tests/donut-render-dispatch.mjs) in the same ticket and must not silently drop the
  color;
- **Metric universe completion (t260903-09; acceptance F2/F3 revision)**: after directly-merged and
  clarified terminal-state tickets disappear from the ticket list, the metrics side folds them into
  the aggregate from the existing cache (the template filter is respected; for existing tickets an
  epic that is not in the cache = unknown, visible only under epic=all, and excluded from the none
  bucket — unknown ≠ no code), and reason explicitly counts "metric universe completion: N
  tickets…"; that notice is placed first in reason and is not truncated by the 20-item cap.
  **Anchor fallback**: existing cache records from an older version (with no created_ms/closed_ms)
  are approximately attributed to a window by rec.computed_at, and reason declares the approximate
  count; approximate anchors only enter the response and are **never written back into the cache**
  (to keep an approximation from being permanently reified into a real closing instant). For
  tickets in the list, older-version records that hit the full gate get their real anchors filled in
  from the in-row timeline and are **written back as an upgrade** (a one-time migration), after
  which fast mode benefits directly. Clarified tickets with no cache record cannot be completed on
  the metrics side (a root fix in the registry gets its own ticket). **The ticket list API's
  response set does not grow because of this** (the dispatch flow is not polluted by archived
  tickets);
- The health view queries Temporal directly and does not read the cache;
- CLI front door: `metrics '<json params>'` → the same JSON on stdout, same implementation and same
  cache.

**Byte-identical comparison surface (basis of the M3 baseline lock)**: for the same request across
the two front doors, the comparison surface = all remaining fields of the serialized JSON **after
removing `generated_at` and `cache.computed_at`** (keys in serialization order, full UTF-8 byte
comparison). The two timestamps mean "the instant this response was generated / the instant the
cache was computed", so the two front doors are allowed to read their own clocks; the M3 comparison
script removes them per this rule before comparing, and any difference in any other field is red.

### Block 3: Cache record schema (per-ticket, frozen)

```json
{
  "ticket_id": "string",
  "template": "string",
  "durations": { "by_stage": {}, "by_round": {}, "human_wait": 0.0 },
  "delivery": { "base": "commit hash", "add": 0, "del": 0, "commits": 0 },
  "tokens": { "by_stage": {}, "by_model": {}, "in": 0, "out": 0, "cacheRead": 0 },
  "open": false,
  "delivery_frozen": false,
  "source_version": "v1",
  "engine_version": "string",
  "updated_ts": "ISO8601",
  "computed_at": "ISO8601",
  "created_ms": 0,
  "closed_ms": 0
}
```

- Canonical field string (byte-for-byte identical to the schema line of UI plan §6, used for
  cross-document comparison):
  `{ ticket_id, template, durations: {by_stage,by_round,human_wait},
  delivery: {base,add,del,commits}, tokens: {by_stage,by_model,in,out,cacheRead}, open: bool, delivery_frozen: bool,
  source_version, engine_version, updated_ts, computed_at, created_ms, closed_ms }`
- **Window attribution anchors created_ms/closed_ms (t260903-09 bump)**: derived fields that enter
  the cache but not the response — the cache-hit path and the fast path use them to avoid per-ticket
  show calls to fill in anchors; the read side stays backward compatible (older-version records
  without these two keys → fall back to "the list row's timeline / timeline from show" to fill them
  in, and the hit path does not rewrite).
- **Invalidation rules (t260903-09 revision)**: a `source_version` mismatch (this document's
  version) → the record is voided and recomputed (key decision 2 of the epic); an `engine_version`
  mismatch (the template's STAGES chain changed) → **only the time dimension is voided** (durations
  are recomputed against the current chain), while the delivery/tokens dimensions are independent
  of the stage chain → **retained with reduced dimensionality** rather than buried with it
  (KI-017②③ clarification: voiding the whole record in the old implementation was the cache-side
  common cause of token/delivery evaporation). The cache as a whole may be discarded and rebuilt;
  its directory is `~/.sandbar/data/<project>/` and it does not enter git (sandbar key decision 3,
  the migration direction).
- **The single exception — delivery-dimension freeze (discardable ≠ recomputable)**: the delivery
  dimension's source of truth is the lane branch, and after the merge is booked the lane branch is
  cleaned up, so lazily recomputing an already-closed ticket has no source to compute from — while
  M3 reconciliation points exactly at already-closed tickets. Therefore **delivery data is frozen
  into the cache by a deterministic script after merge_check is all green and before the merge is
  booked** (the mount point belongs to M1a's bridge side, and the zero-touch-engine red line is
  unchanged); once frozen, `delivery_frozen=true`, and invalidation/recomputation **skips the
  delivery dimension** and refreshes only the other dimensions. Options compared: deriving backwards
  from main's merge commit history (commits merged across epics cannot be attributed per ticket) and
  counting only tickets whose lane is still alive (which cuts away M3's sampling surface) are both
  rejected. Historical tickets that closed before the mechanism shipped have no delivery data (same
  precedent as usage: statistics start when the feature ships), so **M3 sampling must draw from
  tickets closed after the freeze mechanism shipped**.
- **Main-repo archival definition (t260903-09 addition, KI-017①② clarification)**: the
  catch-up path for tickets that closed before the freeze mechanism shipped — when the lane has
  been torn down / base_ref·worktree are missing (directly-merged and clarified tickets) / the lane
  git fails, computeDelivery falls back to the main repo's `git log --grep <ticket id>` commit set
  (both merge and squash commit messages carry the ticket id; the commit-set definition
  inherently excludes progress absorbed by a mid-flight merge into main — a head-on clarification of
  the interval-diff pathology of 80k phantom delivery). On success `delivery_frozen=true`, and
  reason explicitly marks "main-repo archival definition" so it is never silently mixed with the
  live lane definition. Known boundary (W4 measured 20260903): when one commit references multiple
  ticket ids, the commit-set definition double-counts; a commit message of another ticket that
  **referentially mentions** this ticket's id (e.g. a lesson citing "the t260903-05 lesson") is
  likewise matched by grep and counted toward this ticket — both double-counting surfaces are
  registered in tests/delivery-recovery.mjs④, and a root fix needs per-commit attribution
  archiving (same batch as engine-side KI-017③).
- **Token-dimension project-level ledger (t260903-09 forward contract, KI-017③)**: the lane's
  `.dsh/sessions` is buried when the lane is torn down, so the usage out-of-repo archive (a frozen
  snapshot at merge time) lands in the project-level ledger
  `$SANDBAR_USAGE_LEDGER_DIR/<ticket id>/*.jsonl.zstd` (isomorphic to session.jsonl.zstd, persisted
  by the engine-side agent_activities.py; this ticket leaves only a detection seam); if both places
  are absent → tokens=null + a plain-language reason, never a silent 0.

### Block 4: Errors and degrade (three-state case table, frozen)

Expected behavior per case (value / status code / whether it is counted):

**Malformed**

| Input | Expected |
| --- | --- |
| `window=abc` | 4xx `{error, reason}` |
| `view` absent or invalid | 4xx |
| repeated parameter with the same name | 4xx (no "take the first one" tolerance) |
| `epic` overlong or containing illegal characters | 4xx |
| `project` nonexistent | 4xx |

**Missing**

| Input | Expected |
| --- | --- |
| timeline has no running entry | that stage's duration counts as 0 + a reason count (not silently dropped) |
| session file does not exist | soft degrade: 200 + empty data + a plain-language reason (SKIP); the UI shows "—" and raises no error |
| credential-free environment | 200 + SKIP notice (SKIP is correct behavior; the data fills in automatically once recovered) |
| lane branch has no diff | all zeros; legitimate data, not an error |
| cache directory not writable | compute directly this time and return + reason, no 5xx |

**Late / out of order**

| Input | Expected |
| --- | --- |
| timeline timestamps non-monotonic after a rework | sort by from before splitting windows |
| event timestamp outside this ticket's window | discard + a reason count |
| closed entry arrives late while the last window is open-ended | apply the last-window closing rule: right end = min(next window's from, closed_ts) |

### Block 5: Failure-mode trade-offs for the reused implementation

Declared reference implementation: `workbench/src/host/agent-usage.ts` (t260828-07, window
derivation + aggregation). The eight failure modes taken over one by one (**all carried over**):

| # | Failure mode | Trade-off | Notes |
| --- | --- | --- | --- |
| ① | chunk-mirror usage guarded against double counting | carried over | metrics consumes the same source data, so it must be the same |
| ② | events before the first window go only into total, not into a stage | carried over | same window derivation logic; the total ≥ ΣbyStage definition is unchanged |
| ③ | session directory/file missing → soft degrade | carried over | same as metrics: 200 + empty data + a plain-language reason (SKIP) |
| ④ | zstd unavailable / decompression fails → soft degrade | carried over | same soft degrade; the cap on decompressed output is carried over too |
| ⑤ | no usage events → soft degrade | carried over | empty set returns 200, not an error |
| ⑥ | sequential attribution fallback when usage has no model (request/context primary, request/header fallback) | carried over | the token-by-model breakdown depends on this attribution, and the implementation shares the same function |
| ⑦ | illegal ticket id / out-of-range field → 4xx block | carried over | every /metrics query parameter gets the same 4xx block |
| ⑧ | summing multiple roles' multiple session files | carried over | the per-ticket token record sums across all role sessions |

**New failure modes that agent-usage does not cover** (listed separately, without reusing the
numbering above):

- git command failure (branch does not exist / not a worktree environment) → that ticket's delivery
  is set to null + reason; soft degrade that does not block the whole response;
- a timeline entry missing its from timestamp → that stage counts as 0 + a reason count, not
  silently dropped.

### Block 6: Versioning and change discipline

- After v1 is frozen, any field addition or removal requires a new ticket to bump to v1.x / v2, and
  the two-front-door baseline is updated in step;
- The cache record's `source_version` follows this document's version;
- Consistency with *metrics Panel UI Plan* §6: this document has **three deltas** against §6 in
  total — ① the contract pointer line (pointing here); ② the epic enum gains `none`; ③ the schema
  line is kept in sync byte for byte (including `delivery.base` and `delivery_frozen`). No other
  differences.

### Closing the loop

This proposal freezes the definitions and degrade behavior field by field → it resolves the
Problem's "parallel implementations talking past each other, reconciliation with no basis" →
it satisfies Requirements 1–7 → it avoids the Nongoals (v2 / historical derivation / health
caching / visual styling / engine behavior are all explicitly fenced off).

### Supplementary section (t260904-04, KI-040~043 clarification; the schema freeze is not broken, this section declares semantic additions)

1. **Cache-hit self-healing (KI-040)**: a per-ticket cache hit no longer returns early
   unconditionally. Two kinds of stale records are let through to the full recomputation path (the
   existing reduced-dimensionality retention mechanism is unchanged):
   - Condition A (failed-dimension freeze + TTL throttle): `delivery===null` and the record's
     `updated_ts` is more than the TTL old (env `SANDBAR_METRICS_REPROBE_TTL_MIN`, default 60
     minutes; 0 = always probe, for tests only; a negative value is treated as 0). A missing or
     corrupt `updated_ts` is treated as expired and must be probed (the NaN comparison direction is
     settled: it leans toward "re-probe", leaving no dirty record in permanent silence). A re-probe
     write-back always refreshes `updated_ts`="the instant of the last attempt", so the throttle
     anchor is self-consistent — a genuinely incomputable ticket pays for at most one round of
     showTicket+git per TTL period. The dirty state `delivery===null && delivery_frozen===true` also
     belongs to condition A (the frozen flag is not consulted, and the recomputation gate likewise
     looks only at `delivery===null`); that state was previously unreachable and is registered to
     guard against schema-evolution leftovers.
   - Condition B (stale open): when `rec.open` and the ticket list row's `status` disagree, refresh.
     The comparison is zero-spawn, pure in-memory, and not subject to the TTL gate; **the refresh
     goes through the existing full recomputation path** (closed_ms/timeline come from ticket show —
     not an in-memory flag flip, which would degrade a closed ticket's window anchor to created_ms
     and pollute KPI window attribution). This converges the closed-count divergence (KI-040's
     measured 4 vs 5) between the time/delivery/token views (closed derived from rec.open) and the
     health view (which queries the list directly).
     **computed_at semantics refinement + archived-approximate-anchor baseline (acceptance F1 fix,
     20260904)**: when a recomputation has no real anchor (timeline unavailable, created_ms=null),
     computed_at keeps the baseline value (the instant the ticket was first computed, not overwritten
     by this probe's instant); for archived tickets recomputed within this request, the F3
     approximate window attribution uses the pre-recomputation existing computed_at as the baseline
     (response-memory only, not written back to the cache) — otherwise a healed ticket's approximate
     anchor drifts beyond the window's upper bound and is silently dropped by inWindow on the first
     tick (the population collapses by one tick; measured on real machines: sandbar 6→1, suyou
     50→2). With a real anchor, computed_at is always the instant of this computation; updated_ts is
     unaffected and always refreshed (the TTL throttle anchor).
     **Archived tickets' open has no external source of truth (acceptance F2 disposition,
     20260904)**: when show is unreachable (returns null), open keeps the existing flag and is not
     whitewashed; for an archived ticket with open=true, notices explicitly count "the closed count
     may be undercounted" (identical across the hit/recompute/fast ticks) — the missing source of
     truth for clarified terminal states is a registry root-fix debt (the KI-031 family, outside the
     write set), and this ticket closes it by making it explicit rather than silent; the health
     view's population = a direct query of the ticket list is the written contract definition, and
     the criterion "time and health closed agree" is only testable in a world where the ticket is
     still in the list.
2. **Explicit template-filter reason (KI-043②)**: tickets whose list row workflow is empty or
   mismatched and that are excluded by the template filter are counted into the response reason
   notices (at the same position as the universe-completion notice, not truncated by the 20-item
   cap), with the text `N tickets filtered out of the aggregate universe for template mismatch
   (workflow empty or not <template>)`.
3. **Multi-commit boundary of the archival definition (KI-040 related; the definition hover and
   reason already note it)**: the archival definition's reason opens with an explicit note that it
   "includes multiple commits (pre-resolution/booking commits are counted too, so the line count may
   exceed the true squash value)". The **narrowed definition (only squash merge commits) was
   discussed and not adopted** — git has no reliable mechanical discriminator for squash merges (no
   merge commit to recognize, and message heuristics misjudge widely); the root fix belongs to the
   engine-side out-of-repo snapshot ticket (KI-017③, filed separately). The UI definition ⓘ hover
   notes this in step.
4. **Panel parameters made constant (KI-042 host decree)**: the panel filter row's lane (template)
   and epic selectors are retired; the client passes through `template` as the constant `dev-lane`
   and `epic` as the constant `all` (the semantics of parseMetricsQuery requiring both parameters
   are unchanged; leftover localStorage values are normalized and ignored on read); the `project`
   dropdown is enabled (data source GET /wf/projects, the registry), with `''`=the backend default
   project. The request/response schema changes in no way.
5. **Epic whitelist boundary (C3 declaration)**: `listEpicCodes`'s whitelist is still parsed from
   the engine repo's notes/epics (it does not re-root with project). The panel's epic surface is
   retired (constant all does not go through validation); only when the CLI front door explicitly
   passes `epic=<code>&project=<key of a non-engine repo>` is it validated against the engine repo's
   whitelist — a known boundary whose harm is dormant, to be closed by another ticket if the epic
   domain ever becomes multi-project.
6. **Per-project repo re-rooting (KI-043①)**: the semantics of `deps.repo` tighten to "this
   project's registry primary directory" — after project validation passes, buildMetricsResponse
   re-roots locally for this request via `repoForProject(project)` (the defaultDeps default
   implementation = findProject→primaryDir; any legitimate registry key including the default
   project re-roots; an unknown key or a registry exception falls back to the passed-in repo), and
   git/main-repo fallback/session parsing then point at the project's primary directory. The admin
   CLI path is unchanged (it dispatches by the passed project). **Both front doors are fixed
   together**: node.ts and metrics-cli.mjs both consume defaultDeps, so there is no front-door
   fork. Querying the default project from inside a lane worktree also points at the registry
   primary directory (not the worktree's own git) — the same family of semantics as resolving the
   cache/data directory by project key.

### Supplementary section (t260904-09, settle out-of-repo snapshot clarification; the schema freeze is not broken, this section declares semantic additions)

1. **settle out-of-repo snapshot (KI-017 engine-side debt clarification)**: after the merge (squash
   closure) settles and before the lane is cleaned up, the engine freezes a single-ticket snapshot
   out of the repo to `<projects-root>/<key>/data/settle/<ticket number>.json` (the same root
   convention as the metrics cache; the test seam env `SANDBAR_SETTLE_SNAPSHOT_DIR` replaces **the
   whole project root**, in the same chain as
   `SANDBAR_METRICS_DIR ?? SANDBAR_PROJECTS_DIR ?? ~/.sandbar/projects`, with the same resolution
   semantics on the read and write sides). Snapshot contents: `tokens` (in/out/cacheRead, by_model;
   by_stage is always an empty object + `by_stage_available:false` — the engine side has no workflow
   timeline time-window source of truth and does not fabricate one)
   + `delivery` (the true squash numstat add/del/commits, base, squash_commit short hash,
   `zero_change`) + `schema_version:"v1"` + settled_at. Semantics:
   - **This item supersedes the out-of-repo format convention of block 3's "token-dimension
     project-level ledger (t260903-09 forward contract)"**: shipping the raw session files
     (`$SANDBAR_USAGE_LEDGER_DIR/<id>/*.jsonl.zstd`) out of the repo is no longer implemented, and an
     aggregated JSON snapshot takes its place. `resolveLedgerSessionFiles` is retained as a
     compatibility read slot (existing external injections can still be read), read-side priority
     sits below it, and no new references are added.
   - **Idempotent/immutable**: a repeated settle with an identical payload = skip; a differing one
     (reopened ticket etc.) = keep-old, no write-back — **known boundary: incremental delivery of a
     reopened ticket is invisible** (discoverable from the snapshot reason's squash_commit; it needs
     the old snapshot file deleted and settle run again).
   - **Failure soft degrade**: any snapshot failure turns into a note appended to the merge alert
     chain and never blocks the merge (observability debt must not stall delivery — the same
     catch-all→log→non-blocking semantics as ui_evidence). An illegal ticket id shape (failing the
     PROJECT_KEY_RE whitelist, including `../` path traversal shapes) → fail-closed, skip the
     snapshot + note, write nothing (W8 rework item clarified).
   - **Zero-change closure (zero_change)**: when the squash "produced no new commit" branch's HEAD
     message does not start with this ticket's prefix (truly nothing to close, HEAD = another
     ticket's closure) → delivery records zero and numstat is not taken (to keep another ticket's
     delivery from being misattributed to this one); the read-side reason explicitly says "closure
     with zero change (<hash> is main's tail commit, not this ticket's delivery)".
2. **Read-side priority (ticket item 5)**: the order for reading a single ticket's delivery/tokens
   = **settle snapshot > on-the-spot computation (live lane definition / session aggregation) >
   main-repo archival grep**. A snapshot hit → the numbers are the snapshot values,
   `delivery_frozen=true`, and reason says "settle snapshot (squash <hash>)". The cache record's
   `delivery` object gains **optional annotation keys** `squash_commit?: string` and
   `zero_change?: boolean` (written only under the snapshot definition; older readers ignore the
   extra JSON keys, so it is backward compatible).
3. **Narrowing of the archival definition (ticket item 6; this item supersedes the "narrowing
   discussed but not adopted" conclusion and the "includes multiple commits" reason text of
   t260904-04's supplementary item 3)**: for existing tickets with no snapshot, the archival
   definition recognizes only squash closure commits whose **message first line starts with the
   ticket number**; other accounts (referential mentions, pre-resolution/booking commits, etc.) are
   excluded. What was rejected back then was the **substring heuristic** (a referential mention of a
   ticket number that is not at the start is misjudged; git has no mechanical discriminator for
   squash merges); prefix anchoring = the message's first token, and the squash closure commit
   template (engine-side `%s squash 收口…`) guarantees that the first token is always the ticket
   number, so the misjudgment surface shrinks to "hand-forged messages". The empirical anchor is
   t260904-05: grep matched 5 commits while prefix matching matched 1 (the true commit 455320d totals
   5658; the grep total of 5783 includes 125 from other accounts). The double-counting surface (one
   commit with two ticket ids) is closed head-on by the narrowing — one commit is attributed only to
   its unique prefix ticket.
4. **Recomputation trigger (SOURCE_VERSION bump v1→v2)**: the definitional semantic change
   (snapshot priority + archival narrowing) travels with source_version (this document's version
   definition); after the bump, the entire per-ticket cache is voided and recomputed (= block 3's
   written rule "the cache as a whole may be discarded and rebuilt", not a red line). Known side
   effect: collectArchivedRows memory rows are filtered by source_version, so after the bump the old
   memory rows are absent (the aggregate universe shrinks temporarily; the recomputation entry
   points are the existing list/full gates; in-list tickets are unaffected). The structural surface
   that **existing non-null frozen records have no recomputation trigger** (t260904-04's self-healing
   covers only delivery===null) is opened up once by this bump; future definitional changes of the
   same kind must bump again, registered as a general discipline.
5. **Donut "share of tickets with or without code changes" four buckets (ticket item 7)**:
   `['has changes', 'closed·zero change', 'undelivered (in progress)', 'incomputable (missing
   data)']`, mapped bucket by bucket: has changes = add+del>0; closed·zero change = delivery non-null
   and all zeros; undelivered (in progress) = delivery=null and open; incomputable (missing data) =
   delivery=null and closed. The four buckets are mutually exclusive and Σ = ticket count; a
   zero-change closed ticket is no longer mixed with "incomputable". **Known boundary (inherited,
   no new silence invented)**: an archived ticket's open has no external source of truth
   (openUnverified, the KI-031 family), so the "undelivered (in progress)" bucket may contain
   archived tickets that are in fact closed.
6. **Legacy single-file registry mode (SANDBAR_PROJECTS_YAML)**: that mode only affects the host-side
   metrics cache persistence (enabled:false); resolution of the settle snapshot directory is
   unaffected by it — the engine writes the root chain directory as usual and the read side reads it
   as usual (a declaration of snapshot/cache independence).

## Related documents

- [metrics Panel UI Plan](./metrics-panel-ui-plan.md) — per-chart definitions of the four views and the panel skeleton; §6 is the illustrative entry point to this document
- [DeepSeek Harness and Temporal based multi-agent mechanism](./deepseek_harness_and_temporal_based_multi-agent_mechanism.md) — usage aggregation definitions and failure-mode precedents (the basis of blocks 1/5)

> Source epic: metrics
