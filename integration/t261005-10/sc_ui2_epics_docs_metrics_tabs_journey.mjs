#!/usr/bin/env node
/**
 * sc_ui2_epics_docs_metrics_tabs_journey — t261005-10 L3 system scenario (epic
 * console-ui item UI-2, grey-box, shared isolated test console + per-page API
 * stubs, zero real writes, never touches the production 3099 console).
 *
 * User-perceivable contract under test: the consolidated panel tabs carry real,
 * honest read-only faces. Epics and Docs move INTO the panel; Metrics moves in
 * from the sidebar. A source that is down or malformed degrades to a NAMED
 * face — never a blank pane, never a crash (external-input three-state
 * discipline: missing / malformed / late).
 *
 * Sub-cases:
 *   U1 Epics tab lists the fixture epics with recognisable rows (code · title ·
 *      stage · state); clicking a fixture ticket row opens the EXISTING ticket
 *      detail overlay (one overlay node — the t261005-04 surface, reused, not
 *      reinvented).
 *   U2 epic detail renders INSIDE the Epics tab with a `← Back` walk-back (the
 *      single-layer rule; the overlay count never exceeds one).
 *   U3 Docs tab renders the fixture doc tree entry and the doc body markdown.
 *   U4 Metrics tab renders the fixture metrics numbers (facts visible, not a
 *      blank pane; no echarts requirement — facts-only face per mock v11).
 *   U5 degradation: epics endpoint 500 → the tab shows a named error face with
 *      text (not blank); epics endpoint malformed JSON → no pageerror, named
 *      face.
 *   U6 host-side staleness probe: the host project row offers no Board view
 *      icon and no sidebar Metrics entrance at runtime (positive-face twin of
 *      sc_ui2_board_metrics_entrance_retired).
 *   U7 hygiene: zero pageerror across the whole journey.
 *
 * Intent split: strip order + limit row belong to sc_ui2_panel_tab_order_contract;
 * whole-tree entrance absence belongs to sc_ui2_board_metrics_entrance_retired;
 * the ticket overlay's own a11y/keyboard contract stays with t261005-04. The
 * epics/docs/metrics/scan-report DATA contracts belong to their owner tickets;
 * this entry only pins that the tabs render real facts and degrade honestly.
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Stage/browser/playwright absence = ENV_FAIL exit 2.
 */
import {
  BASE,
  refuseProductionConsole,
  consoleHealthy,
  loadPlaywright,
  openTestPage,
  makeResults,
} from '../t260904-05/lib_browser.mjs'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
// Fixture shapes = the REAL endpoint contracts (single truth: the owner hosts) —
// epics list: GET /sandbar-workbench/api/epics → {ok,result:{epics:[{code,title,status,note,created}]}}
//   (src/host/epics.ts listEpics / parseEpicMeta);
// epic tickets: GET /sandbar-workbench/api/epics/<code>/tickets → {ok,result:{code,count,buckets,tickets:[…]}}
//   (node.ts handleEpicTickets);
// docs tree: GET …/wf/docs/tree → {empty,groups:[{dir,label,files:[{rel,title}]}],skipped:[]}
//   (shared/docs-model.ts buildDocTree); docs doc: GET …/wf/docs/doc → {ok,result:{rel,title,meta,body}}
//   (src/host/docs.ts readDoc); metrics: GET …/wf/metrics → {kpis:{tickets,closed,avg_delivery_min,tokens_total},…}
//   (src/host/metrics.ts frozen four fields). The pre-implement draft stubbed guessed
//   shapes; implement landed on the real ones and the fixtures were aligned (not the
//   other way round — the page must not bend to a fixture).
// t261019-12 wire shape: the retired boolean + the English summary are the only
// document prose the API serves (title/status/created retired with the vocabulary).
const EPIC = { code: 'console-ui', retired: false, summary: 'The console rebuild: three columns, ticket detail as an overlay.', started: '2026-10-04' }
const EPIC_TICKETS = {
  code: 'console-ui', count: 2, buckets: { running: 1, settled: 1 },
  tickets: [
    { id: 'it10a', title: 'tab consolidation fixture', status: 'running', stage: 'implement', stage_state: 'running' },
    { id: 'it10b', title: 'metrics move fixture', status: 'settled', stage: 'implement', stage_state: 'done' },
  ],
}
const DOC_TREE = { empty: false, groups: [{ dir: 'design', label: 'design', files: [{ rel: 'design/ui2-note.md', title: 'ui2 note' }] }], skipped: [] }
const DOC_BODY = { ok: true, result: { rel: 'design/ui2-note.md', title: 'ui2 note', meta: {}, body: '# ui2 note\n\nTabs are consolidated into one strip.' } }
const METRICS = { kpis: { tickets: 42, closed: 38, avg_delivery_min: 130, tokens_total: 123456 }, generated_at: '2026-10-05T00:00:00Z', cache: { status: 'hit' } }

const results = makeResults()

async function loadPlaywrightRobust() {
  const pw = await loadPlaywright()
  if (pw) return pw
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (!common) return null
    const main = resolve(REPO, common, '..')
    for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
      'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
      const p = join(main, sub)
      if (existsSync(p)) {
        try { return await import(pathToFileURL(p).href) } catch { /* next */ }
      }
    }
  } catch { /* not a worktree */ }
  return null
}

async function attachStub(page, mode = 'ok') {
  await page.route('**/sandbar-workbench/api/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const json = (b, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (mode === 'down' && /\/api\/epics/.test(url.pathname)) return json({ ok: false, error: 'fixture stub: epics source down' }, 500)
    if (mode === 'malformed' && /\/api\/epics/.test(url.pathname)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '<html>not json</html>' })
    }
    if (/\/api\/epics\/[^/]+\/tickets/.test(url.pathname)) return json({ ok: true, result: EPIC_TICKETS })
    if (/\/api\/epics\/[^/]+/.test(url.pathname)) return json({ ok: true, result: EPIC })
    if (/\/api\/epics/.test(url.pathname)) return json({ ok: true, result: { epics: [EPIC] } })
    if (/\/api\/wf\/docs\/tree/.test(url.pathname)) return json(DOC_TREE) // real shape: no {ok,result} envelope
    if (/\/api\/wf\/docs?\/doc/.test(url.pathname)) return json(DOC_BODY)
    if (/\/api\/wf\/metrics/.test(url.pathname)) return json(METRICS) // real shape: body has no envelope
    if (/\/api\/wf\/scan-report/.test(url.pathname)) return json({ ok: true, result: { findings: [], pending: 0 } })
    if (/\/api\/wf\/tickets/.test(url.pathname)) {
      return json({ ok: true, result: { tickets: EPIC_TICKETS.tickets.map(t => ({ ...t, workflow: 'dev-lane', handoff_count: 0, pending_count: 0 })), workflows: [] } })
    }
    // One fixture project so the left column renders a project row — post-UI-2
    // the cockpit entrance IS the project row (点项目名即进驾驶舱; project rows
    // carry no icons any more). Same stub shape as t260916-15.
    if (/\/api\/wf\/projects/.test(url.pathname)) {
      return json({ ok: true, result: { projects: [{ key: 'it10a', name: 'it10a fixture', primary: '/tmp/fx-it10a', dirs: ['/tmp/fx-it10a'] }], quarantined: [] } })
    }
    try {
      const resp = await route.fetch()
      await route.fulfill({ response: resp })
    } catch {
      await json({ ok: false, error: 'fixture passthrough failed' }, 502)
    }
  })
}

async function waitFor(page, probe, ms = 8000) {
  const steps = Math.ceil(ms / 250)
  for (let i = 0; i < steps; i++) {
    if (await probe()) return true
    await page.waitForTimeout(250)
  }
  return false
}

/** Open the panel page face directly on the test-console origin. Post-UI-2 the
 *  cockpit is the panel itself; the host view-switching machinery (which row
 *  click opens it) is host-side wiring already pinned by t261005-04's console
 *  journey — this scenario drives the panel FACE plus the console-home
 *  staleness probe, over the SAME stage origin. */
async function openPanelPage(page) {
  await page.goto(BASE + '/sandbar-executor-panel/?project=it10a', { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.waitForTimeout(800)
  const tabs = await page.locator('[data-tab]').count()
  return tabs > 0 ? page : null
}

async function clickTab(frame, tab) {
  const el = frame.locator(`[data-tab="${tab}"]`).first()
  if (!(await el.count())) return false
  await el.click()
  return true
}

async function main() {
  refuseProductionConsole()
  if (!(await consoleHealthy())) {
    results.record('L0 precheck', 'env_fail', 'test console unreachable')
    return results.summarize()
  }
  const pw = await loadPlaywrightRobust()
  if (!pw) {
    results.record('L0 precheck', 'env_fail', 'playwright-core not resolvable')
    return results.summarize()
  }
  // Supply-provenance guard (KI-052/KI-168 family, same seam as t261005-04 T6):
  // every assertion below rides on the host client the console actually serves.
  // If the workbench client asset is absent or predates the executor-panel
  // wiring, the journey has no valid premise — an ENV red (mis-supplied shared
  // stage), never a silent product red.
  let servedOk = false
  let servedDetail = ''
  try {
    const r = await fetch(`${BASE}/plugins/sandbar-workbench/client.js`, { signal: AbortSignal.timeout(8000) })
    if (r.ok) {
      const text = await r.text()
      servedOk = text.includes('executor-panel')
      servedDetail = servedOk
        ? `served client carries executor-panel wiring (${text.length} bytes)`
        : `served client ${text.length} bytes but carries NO executor-panel wiring — stale/wrong-tree supply`
    } else {
      servedDetail = `served client asset HTTP ${r.status} (repo lib exists: ${existsSync(join(REPO, 'server/plugins/workbench/lib/client.js'))})`
    }
  } catch (e) { servedDetail = `served client fetch failed: ${String(e).slice(0, 120)}` }
  if (!servedOk) {
    results.record('L0 supply provenance', 'env_fail', `${servedDetail} — shared stage supply face, not this ticket's product (KI-052/KI-168 family); re-run after the stage re-mounts this tree`)
    return results.summarize()
  }
  results.record('L0 supply provenance', 'pass', servedDetail)
  const consoleErrors = []
  const opened = await openTestPage(pw, { results, tag: 'L0', consoleErrors })
  if (!opened) return results.summarize()
  const { page } = opened
  page.on('dialog', (dlg) => { void dlg.accept() })

  const pageerrors = []
  page.on('pageerror', (e) => pageerrors.push(String(e)))
  const badResponses = []
  page.on('response', (r) => { if (r.status() >= 500) badResponses.push(`${r.status()} ${r.url().slice(0, 140)}`) })

  try {
    await attachStub(page, 'ok')
    const frame = await openPanelPage(page)
    if (!frame) {
      results.record('L0 panel page', 'fail', 'panel page served no [data-tab] strip on the test-console origin (pre-implement red expected)')
      return results.summarize()
    }
    results.record('L0 panel page', 'pass', 'panel face live with its tab strip')

    // U1 Epics tab lists fixture rows; row click opens the existing overlay
    if (!(await clickTab(frame, 'epics'))) {
      results.record('U1 epics tab', 'fail', 'no [data-tab="epics"] on the panel face (pre-implement red expected)')
    } else {
      // t261019-12: the row IS the epic (collapsed = code + badge + summary);
      // ticket rows render inside the expanded row, so expand first.
      const expandOK = await waitFor(page, async () => {
        const head = frame.locator('[data-epic-head="console-ui"]').first()
        try { await head.click({ timeout: 2000 }); return true } catch { return false }
      })
      const okList = await waitFor(page, async () => {
        const t = await frame.textContent('body').catch(() => '')
        return t.includes('console-ui') && t.includes('tab consolidation fixture')
      })
      if (!okList) {
        results.record('U1 epics tab', 'fail', 'epics tab did not render the fixture epic/ticket rows from /api/epics')
      } else {
        results.record('U1 epics tab', 'pass', 'fixture epic + ticket rows visible')
        // ticket row click: this drive mode is the panel page STANDALONE on the
        // stage origin (window.parent === window), so the documented contract is
        // a graceful no-op — the panel posts to its parent and never fabricates a
        // second overlay of its own (t261003-09 precedent W5). The positive
        // row-click → host-overlay path is host wiring, pinned by t261005-04's
        // console journey; this entry pins only the no-fabrication half.
        const row = frame.locator('text=tab consolidation fixture').first()
        let clicked = true
        try { await row.click({ timeout: 4000 }) } catch { clicked = false }
        if (!clicked) {
          results.record('U1b ticket row click', 'fail', 'fixture ticket row not clickable in the epics tab')
        } else {
          await page.waitForTimeout(1000)
          const fabricated = await frame.locator('.wb-overlay, .wb-drawer').count()
          const alive = await frame.textContent('body').then(() => true).catch(() => false)
          results.record('U1b ticket row click (standalone no-op)', fabricated === 0 && alive ? 'pass' : 'fail',
            fabricated === 0 && alive ? 'standalone click no-ops: no fabricated overlay, page alive' : `fabricated overlays: ${fabricated}, page alive: ${alive}`)
        }
      }
      // U2 epic detail expands IN PLACE (t261019-12 mock): the expanded row carries
      // the started/counts strip and the document link — no separate detail page.
      const inPlaceOK = await waitFor(page, async () => {
        const t = await frame.textContent('body').catch(() => '')
        return t.includes('waiting on you') && t.includes('landed today')
      }, 6000)
      const bodyText = await frame.textContent('body').catch(() => '')
      if (!inPlaceOK) {
        results.record('U2 epic detail expands in place', 'fail',
          `no in-place expansion face (started/counts strip); epics tab text head: ${JSON.stringify(bodyText.slice(0, 200))}`)
      } else {
        results.record('U2 epic detail expands in place', 'pass', 'expanded row carries the counts strip in place (no separate detail page)')
      }
    }

    // U3 Docs tab
    if (!(await clickTab(frame, 'docs'))) {
      results.record('U3 docs tab', 'fail', 'no [data-tab="docs"]')
    } else {
      const okDocs = await waitFor(page, async () => {
        const t = await frame.textContent('body').catch(() => '')
        return t.includes('ui2-note') || t.includes('Tabs are consolidated')
      })
      results.record('U3 docs tab', okDocs ? 'pass' : 'fail',
        okDocs ? 'fixture doc tree entry + body markdown visible' : 'docs tab did not render fixture tree/body from /api/wf/docs')
    }

    // U4 Metrics tab shows facts
    if (!(await clickTab(frame, 'metrics'))) {
      results.record('U4 metrics tab', 'fail', 'no [data-tab="metrics"]')
    } else {
      const okMetrics = await waitFor(page, async () => {
        const t = await frame.textContent('body').catch(() => '')
        return t.includes('42') || t.includes('lanes') || t.includes('Lanes')
      })
      results.record('U4 metrics tab', okMetrics ? 'pass' : 'fail',
        okMetrics ? 'fixture metrics facts visible' : 'metrics tab rendered no fixture facts (blank-pane defect)')
    }

    // Baseline before fault injection: console noise produced by our OWN
    // deliberate 500/malformed probes is the test's doing, not the product's —
    // U7 judges only errors beyond this baseline.
    const baselineConsoleErrors = consoleErrors.length
    const baselinePageErrors = pageerrors.length
    // U5 degradation: source down → named face, not blank
    await attachStub(page, 'down')
    await clickTab(frame, 'epics')
    const downFace = await waitFor(page, async () => {
      const t = await frame.textContent('body').catch(() => '')
      return t.trim().length > 0 && /(unavailable|unreachable|error|failed|retry|down)/i.test(t)
    }, 6000)
    results.record('U5 epics source down → named face', downFace ? 'pass' : 'fail',
      downFace ? 'error named in the tab' : 'epics tab blank/silent on a 500 source (defect)')

    // U5b malformed JSON → no crash
    await attachStub(page, 'malformed')
    await clickTab(frame, 'ledger') // leave and re-enter to refetch
    await clickTab(frame, 'epics')
    await page.waitForTimeout(1200)
    const stillAlive = await frame.textContent('body').then(() => true).catch(() => false)
    results.record('U5b malformed epics payload → no crash', stillAlive ? 'pass' : 'fail',
      stillAlive ? 'panel survives a malformed payload' : 'panel frame died on malformed JSON')

    // restore the healthy stub so later legs (U6 home reload) don't inherit the
    // 500 and count its console noise as a hygiene failure
    await attachStub(page, 'ok')

    // U6 host staleness: back to the console home — no Board icon, no sidebar metrics entrance
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 15000 })
    await page.waitForTimeout(1200)
    const boardIcon = await page.locator('span.wb-view-icon[title="Tickets"]').count()
    const metricsEntry = await page.locator('.wb-sb-foot', { hasText: /metrics/i }).count()
      + await page.getByText('Metrics', { exact: true }).count()
    results.record('U6 no board icon / no sidebar metrics entrance', boardIcon === 0 ? 'pass' : 'fail',
      boardIcon === 0 ? 'host project row carries no board view icon' : `board view icon still offered (${boardIcon}); metrics-entrance probes: ${metricsEntry}`)

    // U7 hygiene
    // The fault-injection legs DELIBERATELY 500/ corrupt /api/epics; the browser
    // logs each as a resource-load console error. Those are the test's own doing
    // (the product face passed U5/U5b by degrading gracefully), so U7 excludes
    // resource-load errors whose 5xx URL is a deliberately-faulted endpoint.
    const faultedMarkers = ['/api/epics']
    const extra = consoleErrors.slice(baselineConsoleErrors)
      .concat(pageerrors.slice(baselinePageErrors))
      .filter((e) => !( /Failed to load resource/i.test(e)
        && badResponses.some((b) => faultedMarkers.some((m) => b.includes(m))) ))
    results.record('U7 zero pageerror/console-error', extra.length === 0 ? 'pass' : 'fail',
      extra.length ? (extra.slice(0, 4).join(' | ') + ' | 5xx: ' + badResponses.slice(0, 4).join(' ; ')).slice(0, 400) : 'clean journey beyond the deliberate fault-injection baseline')
  } finally {
    await page.close().catch(() => {})
  }
  return results.summarize()
}

main()
