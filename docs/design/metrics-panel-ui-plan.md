---
title: metrics Panel UI Plan
category: design
tags:
  - metrics
  - workbench
status: active
updated: 2026-09-28
---

# metrics Panel UI Plan

> This document is the UI implementation plan for the metrics epic (notes/epics/metrics.md):
> the panel skeleton, per-chart definitions of the four views, the engineering structure and the
> API contract, and the phase-to-ticket mapping. Mockups are in `metrics-mockops/` in the same
> directory (5 images, illustrative data, layout authoritative). Editing this document counts as
> changing the contract and must go through a ticket under the metrics epic.

## 1. Settled premises (the foundation, conclusions of five review rounds)

- Four views: time distribution / delivery volume / token consumption / system health; the entry
  sits next to settings in the bottom bar;
- Chart library **ECharts**, isolated behind an adapter (the only file importing echarts is
  metrics-charts.ts);
- Three storage layers: read-only sources of truth (Temporal timeline / git / ~/.dsh session files)
  → discardable aggregate cache (the runtime data directory, records carrying versioned
  invalidation via source_version/engine_version/updated_ts, not entering git) → the aggregation
  service (host /metrics + node CLI, two front doors, byte-identical, locked by a baseline);
- Multiple templates: the aggregation key = (template, stage); no mixing across templates;
- Donut discipline: share-type charts use a donut, trend/ranking-type charts use columns or bars;
- Temporal's native Prometheus/Grafana belongs to sandbar M2 and is out of scope here.

## 2. Entry and navigation

- Bottom bar rework: a "📊 metrics" button on the left + the ⚙ settings icon on the right (the
  original sandbar inline input area folds into the ⚙ popover, which also hosts health-tab
  parameters such as "silent in-progress threshold (minutes)"); the bottom bar's height is
  unchanged;
- Clicking "metrics" = a full-bleed overlay panel (like the epics full-page view, not a right-side
  drawer — charts need width); Esc/✕ closes it;
- Panel state (tab/filters/time window/project) is stored in localStorage and restored on reopen.

## 3. Panel skeleton (shared by the four views)

> **t260904-04 revision (KI-042 host decree)**: the filter row converges to the two dropdowns
> `[time window▾][project▾]` — "epic▾" and "template▾" are retired (template is always the backend
> default `dev-lane` and epic is always `all`, normalized to constants by loadPanelState and passed
> through, with leftover localStorage values discarded on read, so a stale stored value cannot lock
> the panel to a non-dev-lane template and leave it empty); the project dropdown is enabled (data
> source GET /wf/projects, the registry, `project: default` = the backend default + each project's
> key). The skeleton below follows the revised version.

```
┌────────────────────────────────────────────┐
│ metrics [time window▾][project▾] defsⓘ ✕   │
│ KPI bar: tickets│closed│avg delivery│total tokens │  ← always present on any tab
│ [time] [delivery] [Token] [system health]  │
│ ┌────────────────────────────────────────┐ │
│ │      primary chart (one per tab)       │ │
│ └────────────────────────────────────────┘ │
│ ┌─secondary 1──┐ ┌─secondary 2──┐          │
└────────────────────────────────────────────┘
```

- The "definitionsⓘ" hover declares: duration v1 = handoff approximation / v2 = 08 precise
  terminal states, token excludes cacheRead (hover-visible), the cache time, and source_version;
- **Global drill-down rule (the first red line)**: any column/sector is clickable → a side panel
  lists the constituent tickets (ticket id/title/value) → clicking a ticket jumps to the existing
  detail drawer.

## 4. Per-chart definitions of the four views

### Tab time
- Primary chart: **stage duration distribution**, switchable between column and donut. Column: X =
  stage (the selected template's chain order), Y = elapsed time, with an averaging switch
  (mean/P50/P90); donut "where did the time go": single-ticket average shares as a donut, **human
  review wait as its own orange block**, with the center in large type "N minutes · of which
  human wait X%". Drill-down = the list of tickets that were slow in that stage;
- Secondary 1: single-ticket elapsed-time ranking (horizontal bars, Top N, click jumps to detail);
- Secondary 2: human review wait vs machine time (a 100% stacked bar per ticket, orange = human
  wait).

### Tab delivery
- Primary chart: weekly grouped columns, series = additions/deletions two series (not netted);
  metric switcher (LOC/commits/ticket count, three modes sharing one chart);
- Secondary 1: share by epic donut; secondary 2: columns by role;
- The footnote under the chart pins the definitions down: LOC = diff vs base, listed separately;
  commits = lane branch count (including commits persisted by the worker on the ticket's behalf);
  the tooltip lists them ticket by ticket.

### Tab Token (following the t260828-07 definitions: cacheRead folded into the hover)
- Top switcher: **ticket view / whole-machine sessions**;
- Primary chart: daily stacked columns (X = day, series = model, value = in+out combined),
  drill-down = that day's per-ticket list;
- Secondary 1: per-stage average consumption columns; secondary 2: single-ticket Top N table;
- Empty state: a yellow bar "SKIP is correct behavior" in credential-free environments (the data
  fills in automatically once recovered).

### Tab system health
- KPI cards: in progress / awaiting human review / blocked / closed today;
- Primary chart: ticket flow stacked by day (created/closed/in-progress final state/human-review
  final state);
- Secondary 1: blocked leaderboard (currently blocked tickets + reason + how long they have been
  stuck);
- Secondary 2: **silent in-progress list** — tickets that are running but have had no activity
  heartbeat for N minutes (threshold default 15, adjustable in the ⚙ popover), alerted by a pulsing
  red dot.

## 5. Multi-template definitions

> **t260904-04 revision**: the "template▾" selector is retired and the template is always `dev-lane`
> (the backend default) — the primary chart's stage axis is the dev-lane STAGES chain order; the
> aggregate storage key = (template, stage) is unchanged, and the no-mixing-across-templates
> contract is not broken. The multi-template switching UI awaits a host reopening (it must come with
> a contract bump).

- The template determines the primary chart's stage axis (that template's STAGES chain order); the
  aggregate storage key = (template, stage);
- Per-ticket dimension charts (elapsed-time ranking / human wait vs machine) are independent of the
  template;
- Stages are not force-mapped across templates; the "stage category" normalized view (the six
  classes plan/review/implement/test/gate/human) is an M3+ option and does not enter v1.

## 6. Engineering structure and API contract (M0 freeze)

New code lives in three new files + one CLI:

- `server/plugins/workbench/src/client/metrics.tsx` — panel/views/filters/KPI bar (the wb- CSS
  prefix convention);
- `server/plugins/workbench/src/client/metrics-charts.ts` — the ECharts adapter: exposes the four
  factories `stackBar()/groupBar()/hBar()/donut()` (taking categories+series+onDrill); the view layer
  never sees echarts types;
- `server/plugins/workbench/src/host/metrics.ts` — the single aggregation implementation (three
  source reads + discardable cache + invalidation);
- `metrics-cli.mjs` (under workbench, mounted on the server/tools bridge = the dsh tool "metrics") —
  argv→parameters→stdout JSON, the same implementation and the same cache as HTTP.

**API contract (v1; the field-level frozen source of truth is
[metrics-api-contract-v1](./metrics-api-contract-v1.md), this section is illustrative)**:

```
GET /metrics?window=7d|30d|all&epic=<code|all|none>&project=<key>&template=<id>&view=time|delivery|token|health&mode=full|fast
→ {
    kpis: { tickets, closed, avg_delivery_min, tokens_total },
    charts: { primary: ChartSpec, secondaries: [ChartSpec, ChartSpec] },
    generated_at, cache: { status, computed_at, source_version }
  }
CLI: metrics '{"window":"7d","view":"time",...}'  → the same JSON
```

ChartSpec = { kind: 'bar'|'stackBar'|'hBar'|'donut', title, categories, series[{name,data}], drill: true }.
Cache record schema (per-ticket): `{ ticket_id, template, durations: {by_stage,by_round,human_wait},
  delivery: {base,add,del,commits}, tokens: {by_stage,by_model,in,out,cacheRead}, open: bool, delivery_frozen: bool,
  source_version, engine_version, updated_ts, computed_at, created_ms, closed_ms }`.
(t260903-09 bump: the mode parameter, cache.status gaining stale, and the cache anchors
created_ms/closed_ms — for semantics see blocks 2/3 of [metrics-api-contract-v1](./metrics-api-contract-v1.md).)

## 7. Phase→ticket mapping

| Ticket | Content | Prerequisite |
| --- | --- | --- |
| M0 | definitions document (docs/design/metrics-api-contract-v1.md) + API contract freeze | can start now (pure docs) |
| M1a | host /metrics + discardable cache + CLI front door (on the tools bridge) | M0; wait for t260901-08 to be booked (parallel-slot discipline, write sets must not collide) |
| M1b | lane graph node elapsed time (the minimal drill-down consumer) | can start now (09 has landed, write sets do not collide) |
| M2a | panel skeleton + KPI bar + Tab time | M1a |
| M2b | Tab delivery + Tab Token (including the whole-machine switch) | M2a |
| M2c | Tab system health (including silent in-progress) | M2a |
| M3 | reconciliation acceptance (manual check of 3 tickets) + two-front-door consistency baseline + derivation baseline | all |

Write-set discipline: the M1a/M2 series = workbench src/client + lib artifacts +
host/metrics.ts (+node.ts routing) + integration/ (baseline); **zero engine touch** is written into
every ticket as a red line; M1b = workbench src/client + lib + integration/.

## 8. Whole-panel acceptance red lines

Numbers can be drilled down to a single ticket; definitions are hover-visible; tab switching <500ms
(cache hit); echarts does not escape the adapter; every view has an empty state; the panel is purely
read-only (zero write operations); the CLI produces numbers independently with no console
environment; byte-identical across the two front doors (integration baseline lock).

> Source epic: metrics
