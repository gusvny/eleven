#!/usr/bin/env node
/**
 * sc_ui2_panel_tab_order_contract — t261005-10 L3 component-contract scenario
 * (epic console-ui item UI-2, grey-box, offline seconds, zero docker / Temporal /
 * browser, never touches 3099).
 *
 * User-perceivable contract under test (ticket scope): the middle column carries
 * ONE consolidated tab strip inside the executor panel, in the fixed order the
 * design note fixes: Overview / Epics / Alerts / Inspection / Metrics /
 * Docs / Grants / Settings (Ledger left the strip with t261008-20, host order
 * 261008 — its face lives in the Overview dialog now). The status board is NOT a
 * tab and must not re-enter the strip. The Overview carries exactly ONE
 * concurrency-limit row: value +
 * declaration path as the engine face reports them; when no limit is declared the
 * row says so explicitly and names the absent write face (CL-2 boundary) — it
 * never shows a guessed number and never renders a second knob.
 *
 * Legs:
 *   T1 the panel page face serves exactly 8 tabs in the fixed order, no board
 *      tab, no Ledger tab (t261008-20), no duplicates.
 *   T2 the asserted face is the production page constant (harness parity —
 *      what we assert is what a user gets).
 *   T3 undeclared limit: the concurrency face reports no number and an explicit
 *      not-declared state — a fabricated default number is the defect.
 *   T4 declared limit: with a fixture concurrency-limit.json placed under the
 *      injected root (three plausible layouts tried, any hit counts), the face
 *      flips to declared and carries the value together with the declaration
 *      path (value without provenance = defect).
 *
 * Intent split: the Epics/Docs/Metrics tab content journeys belong to
 * sc_ui2_epics_docs_metrics_tabs_journey (browser pool); the host-side board /
 * metrics-entrance retirement guard belongs to
 * sc_ui2_board_metrics_entrance_retired; this entry pins only the strip order
 * and the single-limit-row face. Pre-implement red is the expected TDD signal;
 * arbitrate/merge must be green. Harness seam missing = FAIL named (product
 * red); broken process environment = ENV_FAIL exit 2.
 */
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const REPO = new URL('../..', import.meta.url).pathname.replace(/\/$/, '')

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

const ORDER = ['overview', 'epics', 'alerts', 'inspection', 'metrics', 'docs', 'grants', 'settings']

// ------------------------------------------------------------- production face
const HARNESS = REPO + '/server/plugins/executor-panel/harness.mjs'
let harness = null
try {
  harness = await import('file://' + HARNESS)
  check('T0 harness seam loads', 'pass')
} catch (e) {
  check('T0 harness seam loads', 'fail',
    `${HARNESS} missing or unimportable — TDD-phase red expected: ${String(e).slice(0, 160)}`)
}

if (harness) {
  // T2 + T1: the page face. PANEL_PAGE_HTML is the exact constant the production
  // route serves (harness.mjs re-exports it next to createApi).
  const html = harness.PANEL_PAGE_HTML
  if (typeof html !== 'string' || html.length < 200) {
    check('T2 production page constant readable', 'fail', 'PANEL_PAGE_HTML export missing/empty')
  } else {
    check('T2 production page constant readable', 'pass', `length ${html.length}`)
    const tabs = [...html.matchAll(/data-tab="([a-z_-]+)"/g)].map(m => m[1])
    const uniq = [...new Set(tabs)]
    if (tabs.length === 0) {
      check('T1 tab strip present', 'fail', 'no data-tab markers on the panel page face (pre-implement red expected)')
    } else if (JSON.stringify(tabs) !== JSON.stringify(ORDER)) {
      check('T1 tab strip present', 'fail',
        `tab order/shape drifted: got [${tabs.join(',')}] want [${ORDER.join(',')}] (duplicates: ${tabs.length !== uniq.length})`)
    } else {
      check('T1 tab strip present', 'pass', `8 tabs, fixed order, no duplicates: ${tabs.join(',')}`)
    }
    check('T1b no status-board tab', tabs.includes('board') ? 'fail' : 'pass',
      tabs.includes('board') ? 'board tab re-entered the consolidated strip' : '')
    // one limit row, facts only (epic rule: the UI carries facts, not doctrine)
    const limitMentions = (html.match(/concurrency/gi) || []).length
    check('T5 overview carries a bounded limit face (sanity: facts present, doctrine-free)',
      limitMentions > 0 && limitMentions <= 40 ? 'pass' : 'fail',
      `concurrency mentions on page: ${limitMentions}`)
  }

  // T3/T4: the concurrency read face over the real route surface.
  const iso = mkdtempSync(join(tmpdir(), 't261005-10-'))
  let cleaned = false
  const clean = () => { if (!cleaned) { cleaned = true; rmSync(iso, { recursive: true, force: true }) } }
  process.on('exit', clean)
  process.on('SIGINT', () => { clean(); process.exit(130) })

  const saved = { ...process.env }
  let h = null
  try {
    h = await harness.startPluginHarness({ panelDir: iso })
  } catch (e) {
    check('T3 concurrency face reachable', 'fail', `harness start failed: ${String(e).slice(0, 160)}`)
  }
  if (h) {
    const base = h.base
    async function getJSON(path) {
      const r = await fetch(base + path, { signal: AbortSignal.timeout(8000) })
      const text = await r.text()
      try { return { status: r.status, json: JSON.parse(text) } } catch { return { status: r.status, text } }
    }
    let undeclared = null
    try { undeclared = await getJSON('/sandbar-executor-panel/api/concurrency?project=it10a') } catch (e) {
      check('T3 concurrency face reachable', 'env_fail', `fetch failed: ${String(e).slice(0, 120)}`)
    }
    if (undeclared) {
      if (undeclared.status === 404) {
        check('T3 concurrency face reachable', 'fail',
          'GET /sandbar-executor-panel/api/concurrency?project=… is 404 — overview limit-row read face not landed (TDD-phase red expected)')
      } else {
        check('T3 concurrency face reachable', 'pass', `status ${undeclared.status}`)
        const j = undeclared.json
        const declared = j && (j.declared === true || j.declared === 'true')
        if (declared) {
          check('T3 undeclared fixture reports not-declared', 'fail',
            'fresh isolated panel dir reported a DECLARED limit — the face is reading something outside its injected root (provenance defect)')
        } else {
          const leaked = j && j.limit !== undefined && j.limit !== null
          check('T3 undeclared fixture reports not-declared', !leaked,
            leaked ? `undeclared face leaks a limit value ${JSON.stringify(j.limit)} (guessed-number defect)` : `shape: ${JSON.stringify(j).slice(0, 160)}`)
        }
      }
    }

    // T4 declared: place a fixture declaration under the injected root; three
    // plausible layouts — any flip to declared with value+path counts.
    // engine schema (CL-1 truth: server/engine/concurrency.py) is fail-closed —
    // a declaration without version:1 must NOT count as declared.
    const decl = JSON.stringify({ version: 1, limit: 3 })
    const layouts = [
      join(iso, 'concurrency-limit.json'),
      join(iso, 'it10a', 'concurrency-limit.json'),
      join(iso, 'projects', 'it10a', 'concurrency-limit.json'),
    ]
    for (const p of layouts) { mkdirSync(join(p, '..'), { recursive: true }); writeFileSync(p, decl) }
    try { process.env.SANDBAR_PROJECTS_ROOT = iso } catch { /* env frozen; layouts still probed */ }
    let declared = null
    try { declared = await getJSON('/sandbar-executor-panel/api/concurrency?project=it10a') } catch { declared = null }
    if (declared && declared.status !== 404) {
      const j = declared.json || {}
      const isDeclared = j.declared === true || (j.limit !== undefined && j.limit !== null)
      const hasProvenance = (typeof j.source === 'string' && j.source.length > 0)
        || (typeof j.path === 'string' && j.path.length > 0)
        || (typeof j.declaration_path === 'string' && j.declaration_path.length > 0)
      if (!isDeclared) {
        check('T4 declared fixture shows value + declaration path', 'fail',
          `no fixture layout flipped the face to declared (tried ${layouts.length} layouts under ${iso}); either the read root differs from every injected layout or the face is hard-wired undeclared`)
      } else if (!hasProvenance) {
        check('T4 declared fixture shows value + declaration path', 'fail',
          `face declares a limit (${JSON.stringify(j).slice(0, 160)}) but carries no declaration path — value without provenance`)
      } else {
        check('T4 declared fixture shows value + declaration path', 'pass', JSON.stringify(j).slice(0, 160))
      }
      // T4b malformed declaration (truncated JSON) must fail closed: declared:false,
      // never a guessed number from a broken file.
      writeFileSync(join(iso, 'it10a', 'concurrency-limit.json'), '{"version":1,"limit":')
      let malformed = null
      try { malformed = await getJSON('/sandbar-executor-panel/api/concurrency?project=it10a') } catch { malformed = null }
      const mj = (malformed && malformed.json) || {}
      check('T4b malformed declaration fails closed',
        mj.declared === false && (mj.limit === null || mj.limit === undefined) ? 'pass' : 'fail',
        `shape: ${JSON.stringify(mj).slice(0, 160)}`)
    } else if (declared && declared.status === 404) {
      check('T4 declared fixture shows value + declaration path', 'fail', 'read face still 404 (same missing face as T3)')
    }
    try { for (const k of Object.keys(saved)) if (process.env[k] !== saved[k]) process.env[k] = saved[k] } catch { /* best effort */ }
    try { if (h.close) h.close() } catch { /* already closed */ }
    clean()
  }
}

summarize()
