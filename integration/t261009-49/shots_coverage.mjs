/**
 * shots_coverage.mjs — before/after screenshot capture for the t261009-49 UI
 * evidence (the panel Inspection tab's new coverage face). NOT an integration
 * scenario: a capture harness in the browser-page-contract.test.mjs pattern —
 * serves the panel page statically, routes the inspection API faces to contract-
 * shaped stubs (including a blocked shell + a failed-only period, the KI shape),
 * clicks the Inspection tab open, screenshots #paneInsp. Zero docker, never
 * touches 3099/7233.
 *
 * Usage: node integration/t261009-49/shots_coverage.mjs --tag before|after --out <dir>
 */
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

const arg = (name, def) => {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 ? process.argv[i + 1] : def
}
const tag = arg('tag', 'after')
const outDir = arg('out', '.sandbar/screenshots')
if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true })

const require = createRequire(import.meta.url)
let dir = import.meta.dirname
for (let i = 0; i < 8 && dir; i++) {
  if (existsSync(join(dir, 'server/ui-check/node_modules/playwright-core/package.json'))) break
  dir = resolve(dir, '..')
}
const playwright = require(join(dir, 'server/ui-check/node_modules/playwright-core'))

const { PANEL_HTML } = await import('../../server/plugins/executor-panel/src/host/panel-page.ts')

const NOW = '2026-10-09T07:30:00Z'
const PROJ = 'sandbar'
const report = (extra) => JSON.stringify(Object.assign({ findings: { high: 1, med: 0, low: 0 }, named: [], coverage: {} }, extra))
const periods = [
  { period: '20261009', reports: { 'integration-tests': { ok: true, report: report({}) }, simplify: { ok: true, report: report({}) } } },
  { period: '20261008', reports: { 'integration-tests': { ok: false, reason: 'report file unreadable or not JSON: Unexpected token' }, simplify: { ok: true, report: JSON.parse(report({ ticket_id: 't261008-17', blocked_reason: 'inspect parse refused', findings: [] })) } } },
  { period: '20260919', reports: { 'integration-tests': { ok: false, reason: 'no report file in the archive' } } },
  { period: '20260918', reports: { 'integration-tests': { ok: false, reason: 'no report file in the archive' } } },
]
const items = [
  { kind: 'period', period: '20261009', any_report: true },
  { kind: 'period', period: '20261008', any_report: true },
  { kind: 'no-report-run', label: '20260919–20260918 · 2 without a report', count: 2, periods: periods.slice(2) },
]
const json = (b) => (req, res) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }

const stub = createServer((req, res) => {
  const u = new URL(req.url, 'http://x')
  const send = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
  if (u.pathname.endsWith('/api/requests')) return send({ rows: [{ at: NOW, status: 'waiting', kind: 'sign', text: 'stub' }] })
  if (u.pathname.endsWith('/api/settings')) return send({ ok: true, config: { enabled: true }, provenance: {} })
  if (u.pathname.endsWith('/api/grants')) return send({ ok: true, granted_count: 0, total: 0, executor_sessions: [], session_state: 'none', note: 'Permissions: 0 of 0' })
  if (u.pathname.endsWith('/api/actions')) return send({ ok: true, source: 'stub', actions: [], malformed_rows: 0, unmapped_rows: 0 })
  if (u.pathname.endsWith('/api/bridge/status')) return send({ ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [], at: NOW })
  if (u.pathname.endsWith('/watchdog/api/status')) return send({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } } })
  if (u.pathname.endsWith('/api/concurrency')) return send({ ok: true, limit: 2, source: 'stub' })
  if (u.pathname.endsWith('/inspection-archive')) return send({ ok: true, result: { ok: true, dir: '/x', instances: ['integration-tests', 'simplify'], periods, items, unreadable_files: 0, hidden_files: 0, reason: '' } })
  if (u.pathname.endsWith('/trigger-records')) return send({ ok: true, rows: [] })
  if (u.pathname.endsWith('/disposition-records')) return send({ ok: true, rows: [
    { at: NOW, by: 'host', kind: 'rerun', instance: 'integration-tests', period: '20260918', reason: 'rerun after failure', spawn: { ok: false, error: 'workflow FAILED' } },
    { at: NOW, by: 'host', kind: 'rerun', instance: 'integration-tests', period: '20260919', reason: 'rerun after failure', spawn: { ok: false, error: 'workflow FAILED' } },
  ] })
  send({ ok: true })
})
await new Promise((r) => stub.listen(0, '127.0.0.1', r))
const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); const html = PANEL_HTML
      .split('INSP.archive = (j && j.result && j.result.ok === true) ? j.result : null;').join('console.log("THEN1 fired"); INSP.archive = (j && j.result && j.result.ok === true) ? j.result : null; console.log("THEN1 archive=" + !!INSP.archive);')
.split('.catch(function(){ INSP.archive=null;').join('.catch(function(e){ console.log("CATCH " + (e && e.stack || e)); INSP.archive=null;')
      .split('function inspRenderPeriods(){').join('function inspRenderPeriods(){ console.log("RENDER-PERIODS archive=" + !!INSP.archive);')
    res.end(html)
})
await new Promise((r) => local.listen(0, '127.0.0.1', r))

let browser
try {
  browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }).catch(() => playwright.chromium.launch({ headless: true }))
  const page = await browser.newPage({ viewport: { width: 1280, height: 1400 } })
  await page.route('**/api/**', (route) =>
    route.continue({ url: 'http://127.0.0.1:' + stub.address().port + new URL(route.request().url()).pathname }))
  await page.addInitScript(() => {
const of_ = window.fetch
    window.fetch = function (...a) {
      const p = of_.apply(this, a)
      if (String(a[0]).includes('inspection-archive')) {
        console.log('INPAGE archive fetch issued')
        p.then((r) => r.clone().json()).then((j) => {
          console.log('INPAGE archive json ok=' + (j && j.result && j.result.ok))
        }).catch((e) => console.log('INPAGE archive json ERR ' + e))
      }
      return p
    }
    window.addEventListener('unhandledrejection', (e) => console.log('UNHANDLED', String((e.reason && e.reason.stack) || e.reason).slice(0, 300)))
    window.addEventListener('error', (e) => console.log('SCRIPTERR', String(e.message).slice(0, 200)))
  })
  await page.goto('http://127.0.0.1:' + local.address().port + '/?project=' + PROJ)
    await page.click('label[for=t-inspection]')
  await new Promise((r) => setTimeout(r, 2500))
  const vis = await page.evaluate(() => {
    const p = document.getElementById('paneInsp')
    return { paneDisplay: p && getComputedStyle(p).display, body: document.getElementById('inspBody')?.innerHTML.slice(0, 200), btns: document.getElementById('inspPeriodBtns')?.children.length, note: document.getElementById('inspPeriodNote')?.textContent.slice(0,120), noteDisp: document.getElementById('inspPeriodNote')?.style.display, banner: document.getElementById('inspBanner')?.innerHTML.slice(0,80), checked: document.getElementById('t-inspection')?.checked }
  })
  console.log('DEBUG', JSON.stringify(vis))
  await page.waitForSelector('#inspBody .inspCard', { timeout: 8000 })
  await new Promise((r) => setTimeout(r, 600))
  const file = join(outDir, 't261009-49-inspection-coverage-' + tag + '.png')
  const pane = await page.$('#paneInsp')
  await (pane || page).screenshot({ path: file })
  console.log('saved ' + file)
} finally {
  await browser?.close()
  await new Promise((r) => stub.close(r))
  await new Promise((r) => local.close(r))
}
