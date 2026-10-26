# t261026-11 handover — the funnel, the matrices, and what integration still owes

## What landed (implement, this lane)

- **THE FUNNEL**: `server/plugins/workbench/src/shared/face-value.ts` — `FaceValue<T> =
  {kind:'value',v} | {kind:'absent',reason}`; `value(v)`, `absent(reason)` (reason REQUIRED;
  throws on empty/whitespace/non-string/placeholder-token reasons), `renderFace`, `reasonOf`,
  and the ONE placeholder literal `FACE_DASH`. Location note (review item 2): it lives in
  **workbench shared** so panel and workbench construct the dash through the SAME functions —
  one funnel, one module for the narrow check to exempt. The panel already imports workbench
  shared modules (`project-identity.ts` precedent); no copy exists.
- **Adoption (words unchanged)**: `metrics-tab-model.ts` — every dash is now
  `renderFace(absent(REASON))` / `renderFace(value(v))`; the `DASH` export re-exports
  `FACE_DASH`; `throughputSpecOf`/`tokensStackOf` answer as funnel values (the reason travels;
  the page keeps rendering its own copy words — verified byte-identical words, see pin below).
  `certification-view.ts` — `noCell` and the three empty-table rows read `FACE_DASH`.
  `requests.ts` — `RequestsRead.degrade?: string`; missing/unreadable/empty/malformed ledger
  answers name themselves (a file-level read failure is no longer miscounted as a malformed row).
- **Panel page**: funnel helpers + factored formatter bodies embedded per the transitive-closure
  law; `FACE_DASH`/`NO_VALUE_REASON` ride `METRICS_TABLES`; chart renderers unwrap the funnel
  value and render the SAME copy words as before.
- **Matrix harnesses** (`integration/t261026-11/degrade_*.mjs` — deliberately NOT `sc_`-prefixed
  so the developer stage can run them directly; the registry cmds point at these names):
  - `degrade_inspection_coverage.mjs` — GREEN ran=12 pass=12; **registered**.
  - `degrade_requests_list.mjs` — GREEN ran=11 pass=11; **registered**.
  - `degrade_metrics_charts.mjs` — GREEN ran=12 pass=12; **registered** (anchor added to
    `test_anchors.json`).
  - `degrade_metrics_kpi_tiles.mjs` — **RED, NOT registered** (filed below).
  - `degrade_certification_tab.mjs` — **ENV_FAIL by design, NOT registered** (filed below).
- `integration/lib_degrade_matrix.mjs` carried onto this lane from commit 48f02243 (byte-identical;
  the landing union must not half-carry it).
- Funnel unit truth table: `integration/t261026-11/face-value.test.mjs` (17 checks, includes the
  malformed-input cases: `absent('')`, whitespace, non-strings, `'—'` as reason all throw).

## PIECE 3 — the one narrow check — LANDED (implement gen2)

On the tree now: `integration/lint_face_dash.py` (battery rule L28, also a standalone entry),
`integration/face_dash_exemptions.json` (the only-shrink table), the registered scenario
`t261026-11-narrow-dash-check` (`node integration/t261026-11/narrow_dash_check.mjs`, ro/fast,
with its FAST_SET_CATCH declaration), and the anchor row in `test_anchors.json`.

Rule (exactly one): outside `server/plugins/workbench/src/shared/face-value.ts`, a bare
placeholder literal (`'—'` / `"—"`) in a host face module is an error, against the per-file:line
table that **must only shrink** — a stale exemption is itself an error (same discipline as the
known-red roster). NOT a shape scan beyond that one literal; comment lines never match, so
em-dash PROSE in copy strings is safe.

The seed table held 53 sites across 13 files; this ticket's own cleanup (routing
`metrics-tab-model.ts`'s `dash:` copy through `FACE_DASH`) already shrank it to 52 sites across
12 files — the discipline is live, not theoretical. Future sites = red; a future funnelling edit
removes its table row in the same change.

## Filed: faces NOT registered, with their matrix output

1. **metrics-kpi-tiles — RED (expected; t261026-05 owns the fix).**
   `node integration/t261026-11/degrade_metrics_kpi_tiles.mjs` →
   `SUMMARY ran=13 pass=10 fail=3`:
   - `real-renders-throughput_value` FAIL — the producer's own payload did not render THROUGHPUT
   - `real-renders-lead_time_value` FAIL — same for MEDIAN LEAD TIME
   - `real-renders-tokens_sub_calibers` FAIL — the real payload still headlines
     'FRESH TOKENS PER COVERED TICKET' (`metrics-tab-model.ts` `kpiTilesOf`)
   The harness file stays in the tree, runnable; register it the round t261026-05's caliber fix
   lands and it goes green (green-before-register).
2. **certification-tab — ENV_FAIL by design (no stubbed green).** The real payload must be the
   engine adapter's own receipt; capture on a machine with the project store, then re-run:
   `python3 server/plugins/executor-panel/src/host/certification-adapter.py <project-key> >
   integration/t261026-11/fixtures/cert-receipt.json`. Until then the harness exits 2 with a named
   message; never register while ENV_FAIL.
3. **inspection-coverage real payload — capture limitation.** `fixtures/coverage-real.json` rows
   follow the reader's documented row contract (not a live capture — this lane has no reachable
   project store). Re-capture before treating the real-shape verdict as producer-grade:
   `SANDBAR_PROJECTS_DIR=<root> SANDBAR_PROJECT_KEY=<key> python3
   integration/t261026-11/fixtures/regen_coverage_rows.py`.

## Borrowed-implementation checklist (review item 3)

From the t261009-49 precedent this ticket reused: it already handles — direct node `.mjs` import
of panel `.ts` (type stripping), ticket-dir write-set placement, offline/no-3099 discipline. It
does NOT handle — the `String(fn)` embed transitive closure (this ticket had to embed the funnel
helpers + alias `FACE_DASH`/`NO_VALUE_REASON` at page scope; the t261021-07 arbitrate lesson is
the guard), the L16 anchor manifest obligation (new registered scenario files need
`test_anchors.json` rows), and the registry pool classification (set `"ro","fast"` here).

## Regression pin (review item 4) — words unchanged, re-runnable

- `node integration/t261026-11/face-value.test.mjs` → 17 checks green
- `node server/plugins/executor-panel/tests/test_t261021_07_metrics_tab_model.test.mjs` → green
  (asserts the healthy-path spec/stack values AND that absent carries a named reason)
- `node server/plugins/executor-panel/tests/browser-page-contract.test.mjs` → green (page embeds
  intact); `api.test.mjs`, `requests*.test.mjs`, certification tab tests → green
- The three registered matrices re-run green offline in seconds.
- No visual difference: every renderer kept its own copy word (`noData`, `reasonNoDailyTokens`,
  the certification empty-row dash); only the PRODUCER of the dash changed — no screenshot
  evidence included for that reason (per the UI-ticket clause's no-visual-difference escape).

## docs

No docs/ page describes the degrade matrix or the funnel yet; the registry intent strings and this
handover carry the contract until a design doc lands (candidate: `docs/design/`, one page covering
the funnel union + the matrix + the narrow check).
