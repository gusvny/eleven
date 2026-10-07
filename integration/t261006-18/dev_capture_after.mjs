// t261006-18 developer-stage AFTER-capture (capture-only, zero assertions —
// NOT a scenario entry; the asserting journey is sc_t26100618_left_column_order.mjs,
// which the engine integration gate runs). Boots an isolated bench console
// (lib_fix17, free port, never 3099; full teardown on exit), stubs the wf API
// boundary with the same fixture data as the scenario, opens the shipped
// client bundle, and saves one screenshot of the left column with the CL-3
// faces rendered:
//   .sandbar/screenshots/after-left-column-order.png
// Run (cwd = repo root):
//   SANDBAR_CAPTURE_MAIN_UI_CHECK=<main>/server/ui-check node \
//     integration/t261006-18/dev_capture_after.mjs
import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, loadPlaywright, dismissNotice } from '../t260904-17/lib_fix17.mjs';
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

const PROJ = 'fixture-order'
const Q1 = 'tq1a', Q2 = 'tq2b', Q3 = 'tq3c', RUN = 'tr4d', HOLD = 'th5e', PAUSED = 'tp6f'
const T0 = 1789353600
function devRow(id, title, ts, extra = {}) {
  return { id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING', epic: 'concurrency-limit', ...extra }
}
const TICKETS = [devRow(Q1, 'first queued ticket', T0), devRow(Q2, 'second queued ticket', T0 + 1),
  devRow(Q3, 'third queued ticket', T0 + 2), devRow(RUN, 'at work ticket', T0 + 3),
  devRow(HOLD, 'held for you ticket', T0 + 4),
  // t261008-08 evidence face: a between-stages paused row (amber dot, no controls).
  devRow(PAUSED, 'paused between stages ticket', T0 + 5, { paused: true, paused_phase: 'at_gate' })]
let queueOrder = [Q1, Q2, Q3]
function face() {
  return { project: PROJ, limit: 2, unlimited: false,
    holders: [{ ticket: RUN, reason: 'running', since: T0, held_s: 12.5 },
      { ticket: HOLD, reason: 'human-hold', since: T0, held_s: 40.1 }],
    queue: queueOrder.map((t, i) => ({ ticket: t, position: i + 1, since: T0, waited_s: 3.3 })) }
}

const bench = await bootConsole(makeRegistryRoot('t26100618-cap-'), makeTicketStub())
await benchAuthUrl(bench)
teardownOnExit(bench.teardown)
const pw = await loadPlaywright()
if (!pw) { console.log('[ENV_FAIL] playwright-core unavailable'); process.exit(2) }
const browser = await pw.chromium.launch({ headless: true })
try {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0, 200)))
  page.on('console', m => { if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 200)) })
  page.on('response', async r => {
    if (r.url().includes('concurrency')) {
      let body = ''
      try { body = (await r.text()).slice(0, 200) } catch (e) { body = 'ERR ' + String(e).slice(0, 80) }
      console.log('[net]', r.status(), r.url(), body)
    }
  })
  await page.route('**/sandbar-workbench/api/wf/**', (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const rq = route.request()
    const method = typeof rq.method === 'function' ? rq.method() : rq.method
    console.log('[route]', method, path)
    if (/concurrency\/reorder$/.test(path) && method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}')
      queueOrder = Array.isArray(body.order) ? body.order.slice() : queueOrder
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, queue: queueOrder }) })
    }
    if (/concurrency$/.test(path) && method === 'GET')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(face()) })
    if (path === '/sandbar-workbench/api/wf/projects')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { projects: [{ key: PROJ, name: PROJ, primary: '/tmp/fx-order', dirs: ['/tmp/fx-order'] }], quarantined: [] } }) })
    if (path === '/sandbar-workbench/api/wf/tickets')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: TICKETS, workflows: [{ id: 'dev-lane', name: 'dev lane', lane: 'worktree', stages: [{ id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] }] }] } }) })
    if (path === '/sandbar-workbench/api/wf/inspection/tickets')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: [], count: 0 } }) })
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub' }) })
  })
  await bench.goto(page, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  try { await dismissNotice(page) } catch { /* notice may not render */ }
  await page.waitForTimeout(500)
  const srcProbe = await page.evaluate(async () => {
    const scripts = [...document.querySelectorAll('script[src]')].map(s => s.src)
    let hit = ''
    for (const u of scripts) {
      try { const t = await (await fetch(u)).text(); if (t.includes('data-order-kind')) hit = u } catch {}
    }
    const left = document.querySelector('.wb-sb-left')
    return { scripts: scripts.slice(0,5), hit, leftW: left ? left.getBoundingClientRect().width : null,
      inlineHit: document.documentElement.innerHTML.includes('data-order-kind') }
  })
  console.log('[srcprobe]', JSON.stringify(srcProbe))
  const probe = await page.evaluate(() => ({
    conc: document.querySelectorAll('[data-wb-conc-counts]').length,
    order: document.querySelectorAll('[data-order-kind]').length,
    pos: document.querySelectorAll('[data-order-pos]').length,
    dots: document.querySelectorAll('.wb-stage-dot').length,
    posInfo: (() => { const e = document.querySelector('[data-order-pos]'); if (!e) return null; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return { text: e.textContent, w: r.width, h: r.height, disp: cs.display, vis: cs.visibility, col: cs.color } })(),
    gripText: (() => { const e = document.querySelector('[data-order-grip]'); return e ? e.textContent : null })(),
  }))
  console.log('[probe]', JSON.stringify(probe))
  const outDir = join(process.cwd(), '.sandbar', 'screenshots')
  mkdirSync(outDir, { recursive: true })
  // t261008-08 evidence: light + dark captures of the left column carrying the
  // three faces (queued / at-work / paused). Theme flips via the client's own
  // data-theme attribute (same switch the panel's toggle uses).
  await page.screenshot({ path: join(outDir, 'after-left-column-order.png') })
  console.log('[capture] .sandbar/screenshots/after-left-column-order.png')
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark' })
  await page.waitForTimeout(400)
  await page.screenshot({ path: join(outDir, 'after-left-column-order-dark.png') })
  console.log('[capture] .sandbar/screenshots/after-left-column-order-dark.png')
} finally {
  await browser.close().catch(() => {})
  if (bench.teardown) await bench.teardown()
}
process.exit(0)
