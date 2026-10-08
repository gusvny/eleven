#!/usr/bin/env node
/**
 * sc_t26100819_panel_tab_mock_anchors.mjs — t261008-19, grey-box L3,
 * "browser-free" pool (real Chromium + page-boundary API stubs, zero docker,
 * never touches 3099/7233). Harness model: t261006-15 journey scenario
 * (PANEL_HTML served over a stub http server; assertions anchor to
 * user-visible semantic text, never class names or node indexes — KI-051).
 *
 * User story (ticket t261008-19, host order 261008): the executor panel's
 * Inspection / Metrics / Docs tabs stay, but their CONTENT must match the
 * 261004 mocks. The mocks are layout-authoritative; their NUMBERS are
 * illustrative and must never be fabricated onto the real faces (reject rule).
 *
 * Faces under test (mock truth quoted in the ticket):
 *   M1 the Metrics tab keeps its real KPI facts (stub-fed values visible) and
 *      never renders the mock's illustrative numbers (38 / 2h10m / 64 / 7);
 *   M2 a Charts face exists carrying the mock's three named entries as
 *      semantic text anchors: "lanes per day", "stage duration", "gate reds";
 *   M3 the Charts entries are honest about their data state (label text from
 *      the mock; value side states the real data availability — no invented
 *      chart figures);
 *   D1 the Docs tab shows the mock's two entry rows: "docs/" + "the library",
 *      "notes/" + "the ledger", each with an "Open" action;
 *   D2 the entry-row page counts are REAL: docs/ shows the count derived from
 *      the served tree (or an explicit "—" until loaded), never the mock's
 *      illustrative 25/60;
 *   D3 clicking Open brings up that scope's tree in the SAME page through the
 *      existing docs/tree endpoint — no invented endpoint, no navigation;
 *   N1 NEGATIVE: the tab strip is unchanged — exactly the 9 declared tabs in
 *      the declared order, none deleted or renamed (the ticket is not a
 *      licence to redraw the panel);
 *   N2 NEGATIVE: the Inspection tab's own face is untouched — its anchors
 *      (host-only full-review strip, Period row, reviews records) still
 *      render as before (its mock already matches; this ticket must not
 *      replay as an Inspection redesign);
 *   E0 zero pageerror across the whole journey.
 * Every leg runs under light AND dark (KI-055 theme-matrix discipline), each
 * theme with a screenshot into integration/t261008-19/out/ as the ticket's
 * named capture evidence.
 *
 * Three states (t260904-12): any fail>0 = exit 1; env_fail>0 = exit 2; the
 * scenario is RED before the implement stage lands the faces (expected TDD
 * signal) and must be green at arbitrate/merge.
 *
 * Intent split: tab strip order + concurrency-limit row = t261005-10-ui2-
 * panel-tab-order-contract; board/entrance retirement = t261005-10-ui2-board-
 * metrics-entrance-retired; the UI-2 journey's degrade faces (named 500 error
 * face, malformed JSON) = t261005-10-ui2-epics-docs-metrics-tabs-journey;
 * inspection archive/trigger/record semantics = t261006-15 entries. This
 * entry uniquely owns: mock-anchored CONTENT of the three tabs (Charts box,
 * Docs entry rows) plus the ticket's negative assertions and theme-matrix
 * captures.
 * KI alignment: KI-051 (semantic-text anchors, stub shapes in the served
 * contract), KI-052 family n/a (panel page is served from source, no built
 * bundle), KI-055 (light+dark), KI-036 (playwright/chromium missing =
 * ENV_FAIL exit 2).
 */
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { existsSync, mkdirSync } from 'node:fs'
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

const PROJ = 'sandbar'
// Wait for an anchor to appear in a pane's text instead of a fixed sleep:
// under concurrent gate load a fetch may take longer than any constant
// budget (gate leg 261008-10:31 measured exactly that race), so the
// discipline is anchor-wait, never sleep-then-read (KI-051 spirit).
async function waitText(page, sel, substr, ms = 8000) {
  try {
    await page.waitForFunction(
      ([s, t]) => { const e = document.querySelector(s); return !!e && (e.textContent || '').includes(t) },
      [sel, substr], { timeout: ms })
    return true
  } catch { return false }
}
const OUT_DIR = join(REPO, 'integration', 't261008-19', 'out')
// t261008-20 (post-merge recalibration, not this ticket): the Ledger tab was
// retired into Overview; the declared strip is now the 8 fixed-order tabs —
// same source of truth as the t261005-10 page-contract test's ORDER.
const TAB_ORDER = ['Overview', 'Epics', 'Alerts', 'Inspection', 'Metrics', 'Docs', 'Grants', 'Settings']
const CHART_ENTRIES = ['lanes per day', 'stage duration', 'gate reds']
const MOCK_ILLUSTRATIVE = ['38', '2h10m', '25 pages', '60 pages']

// ---- stub data in the SERVED contract shapes (KI-051: the page consumes
// j.kpis / j.groups[].files[].rel — the real routes' shapes, not invented ones) ----
const METRICS = {
  kpis: { tickets: 3, closed: 2, avg_delivery_min: 42, tokens_total: 1234 },
  generated_at: '2026-10-08T00:00:00Z',
  cache: { status: 'live' },
}
const DOCS_TREE = {
  docs: {
    groups: [{ label: 'design', dir: 'design', files: [
      { rel: 'design/alpha.md', title: 'Alpha design' },
      { rel: 'design/beta.md', title: 'Beta design' },
    ] }],
    skipped: [],
  },
  notes: {
    groups: [{ label: 'discussions', dir: 'discussions', files: [
      { rel: 'discussions/gamma.md', title: 'Gamma note' },
    ] }],
    skipped: [],
  },
}
const DOCS_COUNTS = { docs: 2, notes: 1 } // derived from the stub above — the only honest counts

function archivePayload() {
  return { ok: true, result: { ok: true, dir: '/archive/out/inspection', instances: ['integration-tests'],
    periods: [], items: [], unreadable_files: 0, hidden_files: 0, reason: 'no archive seeded (out of scope here)' } }
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

  const endpointsHit = new Set()
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const p = u.pathname
    endpointsHit.add(p.split('?')[0])
    const send = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (p.includes('/api/wf/metrics')) return send(METRICS)
    if (p.includes('/api/wf/docs/tree')) {
      const scope = u.searchParams.get('scope') === 'notes' ? 'notes' : 'docs'
      return send(DOCS_TREE[scope])
    }
    if (p.includes('/api/wf/docs/doc')) return send({ ok: true, doc: { rel: 'design/alpha.md', body: '# Alpha' } })
    if (p.includes('inspection-archive')) return send(archivePayload())
    if (p.includes('trigger-records')) return send({ ok: true, source: '/stub', rows: [] })
    if (p.includes('/api/requests')) return send({ rows: [] })
    if (p.includes('/api/settings')) return send({ ok: true, config: { enabled: true }, provenance: {} })
    if (p.includes('/api/actions')) return send({ rows: [] })
    if (p.includes('/api/grants')) return send({ ok: true, grants: {}, provenance: {} })
    if (p.includes('/api/status')) return send({ ok: false, reason: 'offline stub' })
    send({ ok: true })
  })
  await new Promise((r) => stub.listen(0, '127.0.0.1', r))
  const base = 'http://127.0.0.1:' + stub.address().port
  const closeAll = async () => { await new Promise((r) => stub.close(r)); try { await browser.close() } catch {} }
  process.on('exit', () => { try { stub.close() } catch {} })

  try { mkdirSync(OUT_DIR, { recursive: true }) } catch {}

  for (const theme of ['light', 'dark']) {
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
      await page.goto(base + '/?project=' + PROJ + '&theme=' + theme, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(400)
      const T = (n) => theme[0].toUpperCase() + theme.slice(1) + ':' + n

      // ---- N1 NEGATIVE: the tab strip is unchanged (9 tabs, declared order) ----
      const tabs = await page.evaluate(() =>
        [...document.querySelectorAll('.seg label[data-tab]')].map((l) => l.textContent.trim().replace(/\s*\d+$/, '')))
      C.case(T('N1-tab-strip-unchanged'),
        tabs.length === TAB_ORDER.length && TAB_ORDER.every((t, i) => tabs[i] === t),
        'tabs=' + tabs.join('|'))

      // ---- Metrics tab ----
      await page.locator('label[for="t-metrics"]').first().click()
      await waitText(page, '#paneMetrics', 'charts')
      const mText = await page.locator('#paneMetrics').innerText().catch(() => '')
      C.case(T('M1-kpi-facts-real'),
        mText.includes('tickets (7d)') && mText.includes('42') && mText.includes('1234'),
        'metrics=' + mText.slice(0, 140).replace(/\n/g, ' '))
      C.case(T('M1-no-mock-numbers'),
        !MOCK_ILLUSTRATIVE.some((n) => mText.includes(n)),
        MOCK_ILLUSTRATIVE.join(',') + ' must never render (mock numbers are illustrative)')
      // M2/M3: the Charts face with the mock's three named entries as semantic
      // text anchors; honest data state, no invented figures. Matching is
      // case-insensitive: the section heading carries text-transform:uppercase
      // (presentation), so innerText reads "CHARTS" while the served content
      // is "Charts" — case is not part of the contract.
      const mLower = mText.toLowerCase()
      C.case(T('M2-charts-face-present'), mLower.includes('charts'), 'no Charts face in the Metrics tab')
      const chartsText = mLower.includes('charts') ? mLower.slice(mLower.indexOf('charts')) : ''
      for (const entry of CHART_ENTRIES) {
        C.case(T('M2-entry-' + entry.replace(/\s+/g, '-')), chartsText.includes(entry),
          'missing semantic anchor «' + entry + '»')
      }
      C.case(T('M3-charts-honest'),
        chartsText.length > 0 && !MOCK_ILLUSTRATIVE.some((n) => chartsText.includes(n)) && !/\b\d{3,}\b\s*(tickets|lanes)/.test(chartsText),
        'charts=' + chartsText.slice(0, 140).replace(/\n/g, ' '))
      await page.screenshot({ path: join(OUT_DIR, 'metrics-tab-' + theme + '.png'), fullPage: true }).catch(() => {})

      // ---- Docs tab ----
      await page.locator('label[for="t-docs"]').first().click()
      await waitText(page, '#paneDocs', 'the library')
      const dText = await page.locator('#paneDocs').innerText().catch(() => '')
      for (const anchor of ['docs/', 'the library', 'notes/', 'the ledger', 'Open']) {
        C.case(T('D1-entry-' + anchor.replace(/[^a-z]+/gi, '-') || 'docs'), dText.includes(anchor),
          'missing semantic anchor «' + anchor + '»')
      }
      // D2: counts are real — the docs/ row shows the served count (2) or an
      // explicit not-loaded mark, never the mock's illustrative 25/60.
      const honestCount = dText.includes('2 page') || /—\s*page/i.test(dText)
      C.case(T('D2-counts-real'), honestCount && !dText.includes('25 pages') && !dText.includes('60 pages'),
        'docs=' + dText.slice(0, 160).replace(/\n/g, ' '))

      // D3: Open brings up that scope's tree in the same page via the
      // existing endpoint — no navigation away.
      await page.locator('#paneDocs button, #paneDocs [role="button"], #paneDocs .go')
        .filter({ hasText: 'Open' }).first().click().catch(() => {})
      await waitText(page, '#docsTree', 'design/alpha.md')
      const stillThere = await page.locator('#paneDocs').isVisible().catch(() => false)
      const treeText = await page.locator('#docsTree').innerText().catch(() => '')
      C.case(T('D3-open-shows-tree'), stillThere && treeText.includes('design/alpha.md'),
        'tree=' + treeText.slice(0, 120).replace(/\n/g, ' '))
      await page.screenshot({ path: join(OUT_DIR, 'docs-tab-' + theme + '.png'), fullPage: true }).catch(() => {})

      // ---- N2 NEGATIVE: Inspection face untouched (anchors still render) ----
      await page.locator('label[for="t-inspection"]').first().click()
      await waitText(page, '#paneInsp', 'reviews you started')
      const iText = (await page.locator('#paneInsp').innerText().catch(() => '')).toLowerCase()
      C.case(T('N2-inspection-face-untouched'),
        iText.includes('only you can start a full review') && iText.includes('period') && iText.includes('reviews you started'),
        'inspection=' + iText.slice(0, 120).replace(/\n/g, ' '))
      await page.screenshot({ path: join(OUT_DIR, 'inspection-tab-' + theme + '.png'), fullPage: true }).catch(() => {})

      C.case(T('E0-zero-pageerror'), pageErrors.length === 0, pageErrors.join(' | '))
    } catch (e) {
      C.case(theme + ':journey-completed', false, String(e).slice(0, 200))
    } finally {
      await page.close().catch(() => {})
    }
  }

  // D3 endpoint discipline: only the declared pre-existing API faces were hit
  // (no invented endpoint, no changed contract).
  const invented = [...endpointsHit].filter((p) =>
    !/\/api\/(wf\/metrics|wf\/docs\/tree|wf\/docs\/doc|requests|settings|actions|grants|status|concurrency|bridge\/status)/.test(p)
    && !p.includes('inspection-archive') && !p.includes('trigger-records') && !p.includes('/api/wf/inspection'))
  C.case('E1-no-invented-endpoint', invented.length === 0, 'unexpected=' + invented.join(','))

  await closeAll()
  C.exit()
}

main().catch((e) => { console.log('[ENV_FAIL] harness: ' + String(e).slice(0, 200)); console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2) })
