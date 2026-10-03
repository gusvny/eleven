# Handoff — t261003-06 executor panel redesign (implement stage)

Visual baseline: `notes/discussions/261003-executor-panel-redesign-mock.html`.
Design truth: `notes/discussions/261003-executor-panel-redesign.md`.
Screenshots: `.sandbar/screenshots/panel-before.png` / `panel-after.png` (harness-isolated capture, `.sandbar/capture-panel.mjs`).

This document walks the design note §7 acceptance list item by item, and states where each
behaviour is locked (unit test / browser test / code seam).

## §7-1 Layout (design note §2)

| Acceptance item | Where it lives | Evidence |
|---|---|---|
| Five tabs: Overview / Grants / Alerts / Ledger / Settings | `panel-page.ts` tab radios + panes | `tests/page.test.mjs` (tab labels); `tests/browser-redesign.test.mjs` (real clicks) |
| Requests tab removed (merged into Overview) | no Requests pane; left Overview column | `page.test.mjs` negative lock `>Requests<` absent |
| Project picker (dropdown, free-key box, Load) does not exist | removed from markup | `page.test.mjs` + `page-projects.test.mjs` + `browser-redesign.test.mjs` (DOM count === 0) |
| Polling status line removed | `pollNote` gone; polling continues silently at 5s | same negative locks |
| Two columns (left = needs your answer, right = recent actions) | `.cols` grid | `page.test.mjs` (CSS lock); browser test renders both sections |
| Stack below ~760px | `@media (max-width:760px){ .cols{grid-template-columns:1fr} }` | CSS string lock in `page.test.mjs` |
| Project arrives via `?project=` deep link only | boot reads `location.search`; explicit red banner when absent | `page-projects.test.mjs` |
| Waiting-count badge on Overview | `#reqBadge`, updated per poll | browser test asserts badge === '2' then '1' |

## §7-2 Interaction (design note §3)

| Acceptance item | Where it lives | Evidence |
|---|---|---|
| Request row collapsed to one line, expands in place | `data-open` toggle on `.row` | `page.test.mjs`; browser test clicks a head and sees body |
| Expanded: detail (height-capped ~170px, scrollable), answer controls, trace line (raised by / request id / default action) | `.detail` CSS + `traceLine()` | CSS lock; browser test asserts the full trace sentence |
| Options render as buttons; only option-less requests show a free-text box; fallback named "Type an answer" | `hasOptions()` (pure, embedded via `String(fn)`) branches in `rowBody()` | `requests-options.test.mjs` (data face) + browser test asserts button-vs-input per row |
| Answered items move to collapsed "Answered", reopenable | `#doneWrap data-open`, split by `splitWaiting()` | browser test: badge falls 2→1, section collapsed, reopen shows "You answered: Approve" |
| Grants tab: master switch, named executor session input, six per-permission switches, greyed host-only entry, Give all / Give none, Save | `paneGrants` markup + `PERMS` table (declaration keys `sign, send-back, rerun, open-ticket, pause-resume, cleanup`) | `page.test.mjs` structural locks; browser test drives Save |
| Overview switch ≡ Grants master switch (one state); off = revoke all permissions, executor can only read and ask; watchdog keeps running | both post `POST /api/grants {op:'master', enabled}` → `clearGrants()` / `grantAllOps()`; `clearGrants` never touches `watchdog.json`, keeps `executor_sessions` | `grants-session-roundtrip.test.mjs` ③④ (grants cleared, sessions kept, `watchdog.json` still `enabled:true`) + browser test ⑤ through the real button |
| Recent actions row: time + action + ticket + result, action shows which permission | `recent-actions.ts` fixed kind→(action, permission) table; permission in the pill title | `recent-actions.test.mjs`; API `GET /api/actions` |
| Recent-actions source is read-only over the existing event ledger; explicit degraded card when unavailable — never an empty list pretending "no actions" | `recent-actions.ts` `readRecentActions`; page renders "No action list. <reason>" | `recent-actions.test.mjs` absent/unreadable/bad-key cases; API degraded face test |

## §7-3 STE copy (design note §4)

- All five tabs rewritten to the STE rules: short sentences, one idea per sentence, active
  voice, fixed terms, no contractions, no idioms, colon-introduced labels
  (`Request id:`, `Default action:`), full-sentence status lines.
- Sample conversions applied: "Needs you" → "Needs your answer"; "Other…" → "Type an
  answer"; "One-click revoke" → "Disable watchdog" (distinct from the executor power
  switch — one term per concept, review C2); option "None" → "No permission" is a
  request-payload value, copy around it states "No permission".
- Locked by string assertions in `page.test.mjs` (no contractions regex, fixed-term
  presence) and by the seeded integration scenario `sc_executor_panel_page_redesign.mjs`
  S1a/S1b (runs at the merge gate, not in this lane).

## §7-4 The three defect regressions (design note §5)

1. **Session naming survives saves** — root cause: `saveGrantsDecl` never copied
   `executor_sessions` from the request body, so every Grants-face save silently dropped
   it (the settings `op=revoke` face never touched the grants file at all — review C1).
   Fix: body value is carried and validated; absent value inherits the on-disk naming.
   Regression: `tests/grants-session-roundtrip.test.mjs` (save → file has naming → a
   later save without the field keeps it) and browser test ④ (UI save → re-save).
2. **Readout counts distinct permissions, not rows** — root cause: `granted_count` counted
   derived op×template capability rows (6 ops × 3 templates = 18). Fix: numerator and
   denominator are the six `GRANT_OPS`; readout says "Permissions: N of 6".
   Regression: `tests/grants-readout-states.test.mjs` (12 capability rows, `granted_count === 6`,
   note contains "6 of 6") and `grants-session-roundtrip` ④ (all six granted).
3. **Three-state readout** — `session_readout.state` ∈ `no-declaration / no-session /
   named-zero-grants / granted` with a plain sentence, top-level in `GET /api/grants`.
   Regression: `grants-readout-states.test.mjs` (all states incl. malformed declaration)
   and roundtrip ③ (power off → `named-zero-grants`).

## Contract notes for the merge gate

- `POST /api/grants` gained `op:'master'` (`enabled:true|false`) — the grants-only power
  face. The legacy settings `op=revoke` (watchdog `enabled:false`) is unchanged in
  semantics; its grants-clearing half now goes through `clearGrants` so it no longer
  erases session naming (its watchdog-disabling behaviour is untouched, per review C2).
- `GET /api/grants` payload additions: `granted_total`, `session_readout {state, sessions,
  sentence}`; `granted_count` is now distinct ops. `grants.readout_note` reworded.
- New read endpoint `GET /api/actions?project=` (200 with `actions[]`/`unmapped_rows`/
  `malformed_rows`, or 200 `ok:false` + `reason` when the ledger is absent/unreadable).
- Requests schema: optional `options: string[]` (≤8 items, trimmed, deduped, ≤80 chars
  each; malformed = 400/422 at append). Producer face unchanged otherwise.
- `harness.mjs` unchanged in signature; the seeded scenarios' optional `eventsPath`
  injection is not required (the recent-actions scenario drives via `watchdogDir`, which
  matches `eventLedgerFile`).
- The `run_scenarios.py` additions and `integration/t261003-06/` scenario files were
  seeded by the workflow before this stage; this stage aligned the implementation to
  their contract seams (verified by reading, not running — integration entries are
  forbidden in the developer lane).

## Known limits / follow-ups

- The action-kind→permission mapping table (`ACTION_BY_KIND`) covers the six grant-op
  families plus observed aliases (`merge`, `retry`, `open`, `cancel`, `send_back`).
  Ledger kinds outside the table are counted (`unmapped_rows`) and surfaced, never
  invented. If production uses further kinds, extend the table in a follow-up ticket.
- `pickDegraded()` banner wording (shared with the pre-redesign page) still contains the
  parenthetical "(this is NOT \"all fine\")" — kept to avoid touching the embedded pure
  function contract mid-ticket; candidates for the next STE sweep.
- `integration/lint_tests.py` reports a pre-existing L7 banned-term finding in
  `notes/debts/known-issues.md` and baseline files outside this ticket's write set —
  not introduced here, not touched.
