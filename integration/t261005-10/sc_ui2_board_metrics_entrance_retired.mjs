#!/usr/bin/env node
/**
 * sc_ui2_board_metrics_entrance_retired — t261005-10 L3 scenario (epic
 * console-ui item UI-2, grey-box, offline seconds, zero docker / Temporal /
 * browser, never touches 3099).
 *
 * User-perceivable contract under test (ticket scope): the status board is
 * DELETED as a middle-column view and the stale Metrics-from-sidebar entrance
 * (all three levels of it: shell-row injection, footer slot, .wb-sb-foot
 * button, plus the wb-metrics-toggle CustomEvent bus) is REMOVED — no second
 * entrance may survive next to the panel tabs. Absence faces are pinned as a
 * source-presence guard (anchor: source-text) because "gone" is only provable
 * from the tree; the positive journeys live in the sibling scenarios.
 *
 * Legs:
 *   R1 board view gone: no 'board' view in the host client source (view union,
 *      icon cluster, board title) — a user can no longer open a ticket board
 *      in the middle column.
 *   R2 metrics entrance gone: no metrics-entry module wiring and no
 *      wb-metrics-toggle dispatcher/listener anywhere under server/plugins/
 *      (full same-mechanism family sweep, not just the named file).
 *   R3 built-bundle parity (KI-052/KI-168 family): if a client bundle is
 *      present it must not still carry the retired markers — a stale build is
 *      named, never silently green.
 *
 * Intent split: the panel-side strip/limit-row face belongs to
 * sc_ui2_panel_tab_order_contract; the browser journey (no board icon in the
 * host UI at runtime) belongs to sc_ui2_epics_docs_metrics_tabs_journey; this
 * entry is the whole-tree absence guard. Pre-implement red is the expected
 * TDD signal; arbitrate/merge must be green.
 */
import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs'
import { join } from 'node:path'

const REPO = new URL('../..', import.meta.url).pathname.replace(/\/$/, '')
const CLIENT = join(REPO, 'server/plugins/workbench/src/client')
const PLUGINS = join(REPO, 'server/plugins')

let results = []
function check(name, state, detail = '') {
  // state: 'pass' | 'fail' | 'env_fail' (booleans coerce: true=pass, false=fail)
  if (typeof state === 'boolean') state = state ? 'pass' : 'fail'
  results.push([name, state])
  console.log(`${state.toUpperCase()} :: ${name}${detail ? ' :: ' + String(detail).slice(0, 300) : ''}`)
  if (state === 'fail') process.exitCode = 1
  if (state === 'env_fail') process.exitCode = 2
}
function summarize() {
  const pass = results.filter(r => r[1] === 'pass').length
  const fail = results.filter(r => r[1] === 'fail').length
  const ef = results.filter(r => r[1] === 'env_fail').length
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${ef} na=0`)
}

if (!existsSync(CLIENT)) {
  check('R0 workbench client source present', 'env_fail', `${CLIENT} missing`)
  summarize()
  process.exit(2)
}

function walk(dir, out = []) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e)
    const st = statSync(p)
    if (st.isDirectory()) walk(p, out)
    else if (/\.(tsx?|jsx?|mjs|css)$/.test(e)) out.push(p)
  }
  return out
}

// ------------------------------------------------------------- R1 board view
const clientFiles = walk(CLIENT)
let boardHits = []
for (const f of clientFiles) {
  const src = readFileSync(f, 'utf8')
  const lines = src.split('\n')
  lines.forEach((line, i) => {
    // view-union literal, view-switch literals, board title — the view faces a
    // user can switch to; the word "board" inside an unrelated identifier is
    // classified by reading the hit line shape.
    if (/'board'|"board"|Ticket Board|ticket-board/.test(line)) boardHits.push(`${f.replace(CLIENT + '/', '')}:${i + 1}: ${line.trim().slice(0, 140)}`)
  })
}
check('R1 status-board view retired from host client', boardHits.length === 0,
  boardHits.length ? `${boardHits.length} board-view hit(s) still in host client:\n  ${boardHits.slice(0, 8).join('\n  ')}` : '')

// ------------------------------------------------- R2 metrics entrance family
const pluginFiles = walk(PLUGINS)
let toggleHits = []
for (const f of pluginFiles) {
  const src = readFileSync(f, 'utf8')
  const lines = src.split('\n')
  lines.forEach((line, i) => {
    if (/wb-metrics-toggle/.test(line)) toggleHits.push(`${f.replace(PLUGINS + '/', '')}:${i + 1}: ${line.trim().slice(0, 140)}`)
  })
}
check('R2 wb-metrics-toggle bus fully retired (family sweep)', toggleHits.length === 0,
  toggleHits.length ? `${toggleHits.length} dispatch/listen site(s) remain:\n  ${toggleHits.slice(0, 8).join('\n  ')}` : '')

const ENTRY = join(CLIENT, 'metrics-entry.tsx')
check('R2b sidebar metrics entrance module removed', !existsSync(ENTRY),
  existsSync(ENTRY) ? `${ENTRY.replace(REPO + '/', '')} still present — the three-level sidebar entrance must go` : '')

// The echarts host renderer may stay (host-side vendor bundle, plan risk note),
// but it must not be reachable from the sidebar: no import of metrics.tsx from
// sidebar/sidebar-shell surfaces.
let sidebarImportsMetrics = []
for (const f of clientFiles) {
  const base = f.replace(CLIENT + '/', '')
  if (!/^sidebar|^index\.|^app-shell/.test(base)) continue
  const src = readFileSync(f, 'utf8')
  if (/from\s+'[^']*metrics/.test(src)) sidebarImportsMetrics.push(base)
}
check('R2c sidebar no longer imports the metrics renderer', sidebarImportsMetrics.length === 0,
  sidebarImportsMetrics.length ? `sidebar-side importers: ${sidebarImportsMetrics.join(', ')}` : '')

// ------------------------------------------------------- R3 bundle freshness
const BUNDLE = join(REPO, 'server/plugins/workbench/lib/client.js')
if (!existsSync(BUNDLE)) {
  check('R3 client bundle present (conditional freshness guard)', 'pass', 'no bundle on disk — nothing stale to detect')
} else {
  const bundle = readFileSync(BUNDLE, 'utf8')
  const staleToggle = bundle.includes('wb-metrics-toggle')
  // board view marker: the view-union literal survives minification as a string
  const staleBoard = /['"]board['"]/.test(bundle)
  check('R3 served bundle free of retired markers', !(staleToggle || staleBoard),
    `stale markers in bundle: ${[staleToggle && 'wb-metrics-toggle', staleBoard && "'board'"].filter(Boolean).join(', ')} — rebuild pending (KI-052 family)`)
}

summarize()
