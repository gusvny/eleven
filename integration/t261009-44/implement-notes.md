# t261009-44 — implement notes (Slice 2: the Certification tab)

Status: implemented, unit-tested, UI evidence captured. See
`.sandbar/stage_implement_gen0.json` for the full report.

## What landed

- `server/plugins/executor-panel/src/host/certification-adapter.py` — the
  read-only engine-side adapter: imports the engine's own modules
  (develop_line / develop_certify / develop_promote / shared) and calls the
  REAL projection rules (`freeze_state`, `ticket_wait_state`,
  `ticket_outcome`, `run_verdict`); emits one strict JSON receipt. Zero
  engine files modified; write set respected.
- `server/plugins/executor-panel/src/host/certification-reader.ts` — the
  spawn seam (enginePython venv fallback chain, full-termination recovery,
  strict receipt parse, line choice).
- `server/plugins/executor-panel/src/host/api.ts` —
  `GET /sandbar-executor-panel/api/certification` in `PANEL_API_ROUTES`
  (GET-only, no write path), reader behind the `certificationRead` dep.
- `server/plugins/executor-panel/src/host/certification-view.ts` +
  `panel-page.ts` — the tab, drawn to mock v15's layout law; the promote
  dialog is explicitly absent and named (`CERT_COPIES.promoteAbsent`).
- Tests: `certification-reader.test.mjs` (31), `certification-route.test.mjs`
  (14), `t261009-44-certification-tab.test.mjs` (45, carries review C2a/C3),
  `t261009-44-shot.mjs` (UI evidence channel).
- Guard updates (legit strip change): `t261008-19-mock-reconcile` and
  `t261005-10-page-contract` tab-order constants now carry
  `certification` between `inspection` and `metrics`.

## Review conditions

- C1 take/leave list: in the reader header comment (carried vs not-carried).
- C2a dead-button guard: the tab test cross-checks every page-fetched
  `/sandbar-executor-panel/api/*` path against `PANEL_API_ROUTES`.
- C2b reader strictness: malformed delivery/runs rows degrade by name at the
  engine readers' own strictness (`read_rows` bad-line counting); a cited run
  absent from the headers is a named refusal (never a default green).
- C3 anchors: rendered-markup assertions sit on structure, not copy strings.
