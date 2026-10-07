#!/usr/bin/env node
/**
 * sc_t26100615_inspection_tab_journey_layout.mjs — t261006-15, grey-box L3,
 * "browser-free" pool (real Chromium + page-boundary API stubs, zero docker,
 * never touches 3099/7233).
 *
 * User-perceivable faces under test (design §7–§8 + mock v8 + dispatch spec
 * P1/P2/P4/P6/P7), rendered Inspection tab in the executor panel:
 *   J1 the tab exists and is reachable (slot owned by t261005-10 — this entry
 *      requires the tab to be REACHABLE, not that this ticket draws the slot);
 *   J2 period row renders newest-first; clicking a PAST reported period shows
 *      the read-only banner VERBATIM ("This period is closed. Shown read-only
 *      from its report.");
 *   J3 a no-report run shows explicit copy ("No report for these periods."
 *      + the span label + per-period causes), never a silent blank;
 *   J4 face cards: the counted metrics and the NAMED findings are two
 *      separate faces (heading "Named findings" + Findings/Named items kv
 *      blocks) and the seeded named items are served;
 *   J5 coverage shows NOT-REVIEWED entries explicitly ("not a clean result"
 *      face) and the body never reads "no problem"/"all clear";
 *   J6 the trigger strip says the host-only rule ("Only you can start a full
 *      review") and trigger records sit below the period row;
 *   L1 layout RULE via Range (not pixels): text left edges share one line
 *      within 1px across the inspection pane's text faces; right-aligned
 *      faces align on one right line; metric cells equal width;
 *   L2 the page uses the full window width — at a 1600px viewport the side
 *      margins are ≤5% each (host measured 44% whitespace on the old face).
 *
 * Harness: PANEL_HTML from panel-page.ts served over a stub http server that
 * answers the tab's API faces in the SERVED contract shapes: workbench
 * envelope {ok, result:{periods:[{period,reports,any_report}], items:[period |
 * no-report-run]}} — items carry the server-computed merge/missing semantics;
 * trigger records {ok, rows:[{at,by,scope,reason,spawn}]}. Project selected
 * via the declared ?project= deep link (setProject → inspLoad). Stub shapes
 * mirror the real routes (gen2 arbitrate fix, KI-051 stub-drift family: the
 * page consumes j.result / items / rows, not a scenario-invented shape).
 * Assertions anchor to user-visible text/ranges, not implementation internals.
 * playwright-core/chromium missing = ENV_FAIL exit 2 (KI-036 family).
 */
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
let passed = 0, failed = 0, envfail = 0
const C = {
  case(name, ok, reason = '') {
    ok ? passed++ : failed++
    console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
  },
  envFail(name, reason) { envfail++; console.log(`[ENV_FAIL] ${name} — ${reason}`) },
  exit() {
    console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail} na=0`)
    process.exit(envfail ? 2 : failed ? 1 : 0)
  },
}

const require = createRequire(import.meta.url)
function findPlaywrightCore() {
  let dir = REPO
  for (let i = 0; i < 4 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  return null
}

const READONLY = 'This period is closed. Shown read-only from its report.'
const HOST_ONLY = 'Only you can start a full review'
const PROJ = 'sandbar'
const INST = 'integration-tests'

// ---- seeded archive in the SERVED contract shape ({ok, result}) ----
function reportOf(period) {
  return {
    instance: INST, period,
    findings: { high: 2, med: 1, low: 0, total: 3,
      named: [
        'high dead-code: server/plugins/watchdog/src/host/config.ts',
        'med dup-impl: server/plugins/workbench/src/host/scan-report.ts',
      ] },
    coverage: {
      reviewed: ['server/plugins/executor-panel/src/host/api.ts'],
      not_reviewed: ['server/dsh/temporal-poc/base/workflow.ts'],
      total_source_files: 1298, slice: true,
    },
  }
}
const slotOk = (p) => ({ ok: true, file: `/archive/inspection-${INST}-${p}.json`, report: reportOf(p) })
const slotBad = (p) => ({ ok: false, file: `/archive/inspection-${INST}-${p}.json`, reason: `report file unreadable or not JSON: Unexpected token o in JSON at position 1 (${p})` })
function archivePayload() {
  const periods = [
    { period: '20261004', reports: { [INST]: slotOk('20261004') }, any_report: true },
    { period: '20261003', reports: { [INST]: slotBad('20261003') }, any_report: false },
    { period: '20261002', reports: { [INST]: slotBad('20261002') }, any_report: false },
    { period: '20261001', reports: { [INST]: slotOk('20261001') }, any_report: true },
    { period: '20260928', reports: { [INST]: slotBad('20260928') }, any_report: false },
  ]
  const items = [
    { kind: 'period', period: '20261004', any_report: true },
    { kind: 'no-report-run', label: '20261003–20261002 · 2 without a report', count: 2,
      periods: [periods[1], periods[2]] },
    { kind: 'period', period: '20261001', any_report: true },
    { kind: 'no-report-run', label: '20260928 · (no report)', count: 1, periods: [periods[4]] },
  ]
  return { ok: true, result: { ok: true, dir: '/archive/out/inspection', instances: [INST],
    periods, items, unreadable_files: 0, hidden_files: 0, reason: '' } }
}
const RECORDS = {
  ok: true, source: '/projects/sandbar/inspection/trigger-records.jsonl',
  rows: [
    { at: 1791297582762, by: 'host', project: PROJ, instance: INST, scope: 'server/plugins', reason: 'deep dive before release', spawn: { ok: true, ticket_id: 't261006-20' } },
    { at: 1791100000000, by: 'host', project: PROJ, instance: INST, scope: 'docs/ + notes/', reason: 'doc face check', spawn: { ok: true, ticket_id: 't261006-18' } },
  ],
}

async function main() {
  let PANEL_HTML = null
  try { ({ PANEL_HTML } = await import(pathToFileURL(join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')))) } catch { /* below */ }
  if (!PANEL_HTML) { C.case('panel-page-importable', false, 'panel-page.ts PANEL_HTML missing'); return C.exit() }

  const pwDir = findPlaywrightCore()
  if (!pwDir) { C.envFail('playwright-core', 'server/ui-check/node_modules/playwright-core missing (KI-036 family)'); return C.exit() }
  const playwright = require(pwDir)
  let browser
  try {
    try { browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
    catch { browser = await playwright.chromium.launch({ headless: true }) }
  } catch (e) { C.envFail('chromium', String(e).slice(0, 160)); return C.exit() }

  const stub = createServer((req, res) => {
    const p = new URL(req.url, 'http://x').pathname
    const send = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (p.includes('inspection-archive')) return send(archivePayload())
    if (p.includes('trigger-records')) return send(RECORDS)
    if (p.includes('/api/requests')) return send({ rows: [] })
    if (p.includes('/api/settings')) return send({ ok: true, config: { enabled: true }, provenance: {} })
    if (p.includes('/api/actions')) return send({ rows: [] })
    if (p.includes('/api/grants')) return send({ ok: true, grants: {}, provenance: {} })
    if (p.includes('/api/status')) return send({ ok: false, reason: 'offline stub' })
    send({ ok: true })
  })
  await new Promise((r) => stub.listen(0, '127.0.0.1', r))
  const base = 'http://127.0.0.1:' + stub.address().port

  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const pageErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 160)))
  await page.route('**/*', (route) => {
    const u = new URL(route.request().url())
    if (u.pathname === '/' || u.pathname === '/index.html') {
      route.fulfill({ contentType: 'text/html', body: PANEL_HTML })
    } else {
      route.continue()
    }
  })
  try {
    await page.goto(base + '/?project=' + PROJ, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(400)

    // ---- J1: the Inspection tab is reachable ----
    const tab = page.locator('label[for="t-inspection"]').first()
    const tabVisible = await tab.isVisible().catch(() => false)
    C.case('J1-inspection-tab-reachable', tabVisible, tabVisible ? '' : 'no Inspection tab face in rendered panel')
    if (!tabVisible) return C.exit()
    await tab.click()
    await page.waitForTimeout(300)
    const pane = page.locator('#paneInsp')

    // ---- J2: period row newest-first; past reported period read-only banner ----
    const order = await page.evaluate(() =>
      [...document.querySelectorAll('#inspPeriodBtns button')].map((b) => b.textContent.trim()))
    const ids = order.map((t) => (t.match(/2026\d{4}/) || [])[0]).filter(Boolean)
    C.case('J2-period-row-newest-first',
      ids.length >= 3 && ids.indexOf('20261004') === 0 && ids.indexOf('20261001') < ids.indexOf('20260928'),
      'order=' + order.join(' | '))
    await page.locator('#inspPeriodBtns button', { hasText: '20261001' }).first().click()
    await page.waitForTimeout(200)
    const banner = await page.locator('#inspBanner').innerText().catch(() => '')
    C.case('J2-readonly-banner-verbatim', banner.includes(READONLY), 'banner=«' + banner.slice(0, 120) + '»')

    // ---- J3: merged no-report run explicit, per-period causes kept ----
    await page.locator('#inspPeriodBtns button', { hasText: 'without a report' }).first().click()
    await page.waitForTimeout(200)
    const runBody = await page.locator('#inspBody').innerText()
    C.case('J3-merged-no-report-explicit',
      runBody.includes('No report for these periods') && runBody.includes('20261003') && runBody.includes('20261002'),
      'body=' + runBody.slice(0, 200))
    C.case('J3-per-period-causes-kept', !runBody.includes('20260928') && runBody.includes('unreadable or not JSON'),
      'per-period cause lines present without the far period')

    // ---- J4/J5: newest reported period ----
    await page.locator('#inspPeriodBtns button', { hasText: '20261004' }).first().click()
    await page.waitForTimeout(200)
    const body = await pane.innerText()
    C.case('J4-named-findings-face-present',
      body.includes('Named findings') && body.includes('Findings') && body.includes('Named items'),
      '')
    C.case('J4-named-items-served', body.includes('dead-code') && body.includes('watchdog'), '')
    C.case('J5-not-reviewed-explicit',
      body.includes('temporal-poc/base/workflow.ts') && body.includes('not a clean result')
      && !/\bno problem\b/i.test(body) && !/\ball clear\b/i.test(body),
      '')

    // ---- J6: host-only copy + records below the period row ----
    C.case('J6-host-only-copy', body.includes(HOST_ONLY), '')
    const recText = await page.locator('#inspRecords').innerText().catch(() => '')
    C.case('J6-trigger-records-listed',
      recText.includes('server/plugins') && recText.includes('doc face check'),
      'records=' + recText.slice(0, 160))
    const recBox = await page.locator('#inspRecords').boundingBox().catch(() => null)
    const perBox = await page.locator('#inspPeriodBtns').boundingBox().catch(() => null)
    C.case('J6-records-below-period-row',
      !!(recBox && perBox) && recBox.y > perBox.y,
      recBox && perBox ? `records.y=${recBox.y.toFixed(0)} period.y=${perBox.y.toFixed(0)}` : 'faces not found')

    // ---- L1 layout rule via Range, scoped to the inspection pane ----
    // The rule names TWO lines: text faces share the left gutter; RIGHT-
    // ALIGNED faces (meta, numeric last column, the toolbar button) share one
    // right line. The measurement sets are therefore disjoint by construction
    // — a right-aligned meta's left edge is NOT a left-line member (that mix
    // is what produced the gen1 false 1266px spread).
    const geom = await page.evaluate(() => {
      const sel = document.querySelector('#paneInsp') || document.body
      const all = [...sel.querySelectorAll('*')]
      const isRightAligned = (e) => {
        const cls = String(e.className ?? '')
        return /\binspMeta\b|\bnum\b/.test(cls) || (e.tagName === 'BUTTON' && e.id === 'inspRunBtn')
      }
      // The rule pins a table's FIRST column to the gutter — columns 2..n are
      // their own grid and are not left-line members (including them made the
      // records table's scope/reason columns false outliers; gen3 fix).
      const isFirstCol = (e) => {
        if (!/^TD$|^TH$/.test(e.tagName)) return true
        return e.parentElement && e.parentElement.firstElementChild === e
      }
      const textEls = all.filter((e) => {
        if (isRightAligned(e)) return false
        if (!isFirstCol(e)) return false
        if (!e.childNodes.length) return false
        const hasText = [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 3)
        if (!hasText) return false
        const cls = String(e.className ?? '')
        return /desc|title|metric|kv|cell|card|gutter|label|key|pad|inspNote/i.test(cls) || /^TD$|^TH$/.test(e.tagName)
      })
      // Range over an element's CONTENTS already starts at the rendered text
      // origin (padding excluded) — adding computed paddingLeft double-counted
      // the inset and produced the phantom 2px spread (gen4 measurement fix).
      const rects = textEls.slice(0, 80).map((e) => {
        const r = document.createRange()
        r.selectNodeContents(e)
        const b = r.getBoundingClientRect()
        return { left: b.left, right: b.right, w: b.width }
      }).filter((x) => x.right > x.left && x.w > 30)
      // Right-line faces: mock v8 precedent — a BUTTON aligns by its BOX edge,
      // a text meta by its TEXT edge (Range end). Mixing box-for-text was the
      // second artifact (button 1479 vs meta box 1477).
      const rights = all.filter(isRightAligned).slice(0, 40).map((e) => {
        if (e.id === 'inspRunBtn') return e.getBoundingClientRect().right
        const r = document.createRange()
        r.selectNodeContents(e)
        return r.getBoundingClientRect().right
      }).filter((x) => x > 0)
      return { lefts: rects.map((x) => Math.round(x.left * 10) / 10), rights: rights.map((x) => Math.round(x * 10) / 10) }
    })
    const spread = (arr) => arr.length ? Math.max(...arr) - Math.min(...arr) : 0
    const leftSpread = spread(geom.lefts)
    C.case('L1-text-left-edges-one-line', leftSpread <= 1 || geom.lefts.length < 4,
      `n=${geom.lefts.length} spread=${leftSpread.toFixed(1)}px sample=${geom.lefts.slice(0, 6).join(',')}`)
    const rightSpread = spread(geom.rights)
    C.case('L1-right-edges-one-line', rightSpread <= 1 || geom.rights.length < 2,
      `n=${geom.rights.length} spread=${rightSpread.toFixed(1)}px`)

    // metrics equal-width grid: cells sharing the grid have equal widths
    const gridWidths = await page.evaluate(() => {
      const cells = [...document.querySelectorAll('#paneInsp .kv')].filter((e) => e.getBoundingClientRect().width > 10)
      return cells.slice(0, 8).map((e) => Math.round(e.getBoundingClientRect().width))
    })
    const gw = [...new Set(gridWidths)]
    C.case('L1-metrics-equal-width-grid', gridWidths.length < 2 || gw.length === 1,
      `widths=${gridWidths.join(',')}`)

    // ---- L2 full-window width: side margins ≤5% at 1600px ----
    const margins = await page.evaluate(() => {
      const wrap = document.querySelector('.wrap, main, body > div')
      const b = (wrap || document.body).getBoundingClientRect()
      return { left: b.left, right: window.innerWidth - b.right, vw: window.innerWidth }
    })
    C.case('L2-full-window-width',
      margins.left <= margins.vw * 0.05 && margins.right <= margins.vw * 0.05,
      `left=${margins.left.toFixed(0)}px right=${margins.right.toFixed(0)}px vw=${margins.vw}`)

    C.case('J0-zero-pageerror', pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '))
  } finally {
    await browser.close().catch(() => {})
    stub.close()
  }
  C.exit()
}

main().catch((e) => { console.log(`[FAIL] scenario-run — ${String(e?.stack ?? e).slice(0, 300)}`); process.exit(1) })
