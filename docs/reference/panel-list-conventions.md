---
title: "Panel list conventions"
category: reference
tags:
  - executor-panel
  - list-contract
  - frontend
status: active
updated: 2026-10-04
---

# Panel list conventions

> t261004-14. The executor panel once rendered three rows of a wake list because the render
> loop took the first three entries of an append-ordered array, and its timestamp carried no
> date. The code looked innocent because no contract said what each list must show. This
> document is that contract. The machine face is `server/plugins/executor-panel/src/host/list-contracts.ts`
> (`LIST_CONTRACTS`); the mechanical check is `server/plugins/executor-panel/check_list_caps.mjs`.

## The rule

Every list the panel renders declares four things in one place:

1. **Source** — where the rows come from (endpoint, payload field, or fixed table).
2. **Order** — the sort the render applies, and what "newest first" means for that source:
   descending by `at`; a missing or malformed `at` sorts last; equal `at` keeps the source's
   relative order (stable sort).
3. **Cap** — an explicit number, or the explicit string "all rows".
4. **Empty copy** — the text the panel shows when the list has no rows.

A numeric cap must carry a `cap_reason`: why that number, and why hiding rows is acceptable.
A cap must not appear as a constant inside render code. If a literal truncation in a render
path is not a list cap (a storage field length, a date-string cut), the line carries a
`LIST-CAP-OK: <reason>` comment so the check can tell them apart.

## The panel's lists today

Declared in `LIST_CONTRACTS`; this table mirrors it (the module is the truth):

| List | Source | Order | Cap | Empty copy |
|---|---|---|---|---|
| Overview — Needs your answer | `/api/requests`, status `waiting` | newest first by `at` | all rows | "Nothing waits on you." |
| Overview — Answered | `/api/requests`, status `answered` | newest first by `at` | all rows | Section stays hidden when empty |
| Overview — Recent actions | executor audit log tail (`recent-actions.ts`, permission-bearing rows) | newest first by `at`, sorted server-side | 50 (tail window over recent gated actions; rows beyond the window surface as an older_rows note, not a silent cut; full log stays in the file) | Degraded card names the reason |
| Grants — declared sessions | `/api/grants` session readout | payload order (not chronological) | all rows | Copy points at Settings |
| Grants — capability matrix | `/api/grants` `grants.rows` | payload order | all rows | Block not rendered when rows are missing |
| Grants — permission switches | fixed `PERMS` table | fixed order | all rows | Not applicable (fixed shape) |
| Alerts — Recent | watchdog status `alerts` | newest first by `at`, sorted in the page | all rows | "No alerts exist. The watchdog writes an alert only when a rule fires." |
| Ledger — Last wakes | watchdog status `wakes` | newest first by `at`, sorted in the page | 3 (compact "last" view beside counters; the record is the ledger file) | "No wakes yet. The watchdog adds a row here when it wakes an executor." |
| Settings — knobs and panes | fixed `KNOBS`/`PANES` tables | fixed order | all rows | Not applicable (fixed shape) |

Timestamps on every list row carry the date (`YYYY-MM-DD HH:MM`, local time) — a bare
`HH:MM` cannot tell two days apart.

## Mechanical check

`check_list_caps.mjs` scans **all** `.ts` files under `server/plugins/executor-panel/src/host/`
(closed by directory, so a new render file is covered without edits) for cap-like constants:
`Math.min(x, <integer>)`, `.slice(0, <integer>)`, and loop bounds written as integer literals.
Any such integer literal fails the check — even when the value equals a declared cap, because
a declared cap must be referenced by name (`declaredCap(...)`, `LIST_CONTRACTS`, or a named
constant), never by numeric coincidence. Lines with a `LIST-CAP-OK: <reason>` comment are
exempt.

Run it from the repository root:

```
node server/plugins/executor-panel/check_list_caps.mjs
```

Exit 0 = pass. Exit 1 lists each `file:line`. The unit wrapper
`server/plugins/executor-panel/tests/list-cap-check.test.mjs` runs the check against the real
tree and against fixtures with undeclared caps, so the panel test run
(`node server/plugins/executor-panel/run_tests.mjs`) covers it too.
