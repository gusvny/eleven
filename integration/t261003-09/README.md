# t261003-09 — executor panel follow-ups（展开不推栏 / 主题跟随 / 顶部行退场恰一入口）

Three scenarios, registered in `run_scenarios.py` (delivery of the
design_integration_tests stage; they RUN at the integration gate per the
260921 rule). Shared stub seam `lib_panel_stub.mjs` re-exports the
t261003-06 `lib_panel_seam.mjs` protocol (same harness seam, no new contract).

- `sc_executor_panel_unfold_layout.mjs` (pool `browser-free`) — Defect 1:
  unfolding a request must not move the other column or anything below it,
  at a narrow container (~700px, stacked — the real console middle-column
  shape) and a wide one (~1000px, side-by-side); the detail keeps its
  height cap + inner scroll (t261003-06 face not regressed).
- `sc_executor_panel_theme_follow.mjs` (pool `browser-free`) — Defect 2:
  `?theme=light|dark` flips the rendered palette (relative-luminance check);
  absent or malformed param → no theme marker (no hardcoded default — the
  ticket's red line) and system `prefers-color-scheme` fallback is not the
  old hardcoded dark face.
- `sc_executor_panel_open_session.mjs` (pool `browser-free`) — Defect 3,
  panel side: exactly one open-session button in Overview; enabled only when
  a session is declared; click posts the same-origin open-session message to
  the parent (console stand-in) and surfaces the parent's result; standalone
  open → disabled with one STE sentence; malformed parent reply does not
  crash the panel; zero pageerror.

## Companion edit (previous family, same write-set)

`t260929-22/sc_executor_entry_console.mjs` E2 rewritten from the positive
switcher face ("Executor / Chat flips both ways") to the retirement negative
face required by this ticket: no seg anchors, no Executor tablist, panel
still mounted. Registry intent text updated accordingly. E1/E3/E4/E5 kept.

## Anti-proof

All three scenarios are red against the pre-fix tree by construction: the
current `panel-page.ts` has a hardcoded dark palette and no `?theme=`
handling (V1/V3 red), `@media (max-width:760px)` stacking pushes Recent
actions on unfold (U1 red), and there is no open-session button (W1 red).
They must be green by the arbitrate/merge gate (260921 rule).

Triage note: this design stage did not execute the browser legs (the fix is
not implemented yet — TDD red is the expected face). Static gates:
`python3 integration/lint_tests.py` run before settlement.
