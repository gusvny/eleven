---
title: metrics token face and population — delta rulings 261025
category: design
tags:
  - metrics
  - tokens
  - contract
status: active
updated: 2026-10-25
---

# metrics token face and population — delta rulings 261025

> This is a delta to [metrics-api-contract-v2.md](metrics-api-contract-v2.md), written the way v2
> was written to v1: the frozen document is not rewritten in place. Every field below is additive;
> no existing field changes name, position or meaning.

## Why this delta exists

The host read the Metrics tab on 261025 and challenged two numbers. Both challenges were correct,
and both were about the same thing: a face that shows a ratio rather than what it measured.

1. **"41 tickets in 31 days?"** The store held 422 archived tickets, 293 of them created inside the
   last 31 days. The face counted 43 — in 7 days, in 30 days, and in `window=all` alike. A count that
   does not move with the window is not a window count. The cut was made earlier: 339 of the 384
   ticket-list rows project with an empty `workflow` and no `created` (the legacy era), and the KPI
   population drops rows whose workflow is not the selected template.
2. **"28.1M tokens?"** Measured directly from the session stores, the sandbar work inside the same
   31 days moved about 170M fresh tokens (input+output) and about 23B including cache reads. The
   face's 28.1M was fresh tokens over the 13 tickets that still had a session file. Three losses
   stacked: cache reads never enter the total, a closed ticket's session file dies with its lane,
   and sessions that belong to no ticket are not counted at all.

So this delta is not about a display format. It is about the rule that a face may never present a
partial population as a whole.

## Rule 1 — a population on the face must equal the population in the store, or name the difference

Every population a metrics face shows (tickets opened, tickets closed, tickets with usage) must
either equal what the store holds for that window, or carry its shortfall on the same face: how many
tickets are excluded and why, in the same units a reader can check.

A row that cannot be keyed to a chain (the legacy era has no workflow chain to key to) is still a
ticket. It counts in ticket totals. It is excluded from the chain-based blocks, and the exclusion is
counted and named. Dropping it from the population silently is the defect this rule retires.

## Rule 2 — a ratio states its numerator, its denominator and its coverage

A per-ticket average is only meaningful when the tickets in the numerator are the tickets in the
denominator. Where coverage is partial, the face says "over N of M closed tickets" next to the value.
A ratio computed over a partial numerator and a full denominator is forbidden, not merely imprecise.

This is what retires the old "tokens per closed ticket": 13 tickets' usage divided by 41 closed
tickets produced a number with no interpretation.

## Rule 3 — three token tiles, each naming what it measures

| Tile | Value | Coverage line |
|---|---|---|
| Fresh tokens per covered ticket | (input+output) ÷ closed tickets **that carry a usage face** | over N of M closed |
| Actual traffic per covered ticket | (input+output+cacheRead) ÷ the same set | over N of M closed |
| Cache share per covered ticket | cacheRead ÷ (input+output+cacheRead) over the same set | over N of M closed |

The third tile is named per ticket so it cannot be confused with the existing `cache_hit` KPI, which
is a share of the token domain and not of a ticket.

The REWORK RATE tile is removed. A rate that reads 100 percent on every window carries no
information. The underlying field may stay in the response for readers who want it; the face stops
showing it.

## Rule 4 — the additive fields the tiles need

Three inputs, additive, each null-and-named when absent (never zero-filled, v2's own rule):

| Field | Type | Source of truth | Degrade |
|---|---|---|---|
| `tokens_cache_read` | number \| null | sum of `cacheReadTokens` over the same covered set the token KPIs already use | null when no ticket in the population carries a usage face |
| `tickets_with_usage` | number | count of population tickets that carry a usage face | 0 only when the population is genuinely empty |
| `closed_with_usage` | number | count of closed population tickets that carry a usage face | 0 only when no closed ticket carries one |

The panel never derives these from `cache_hit`: a share cannot be inverted back into an amount
without inventing the amount.

## Out of scope

How usage is collected (the lane session file is the only source today; keeping it past close is
another ticket), and the population filter's own repair. This delta fixes what the faces are allowed
to claim.
