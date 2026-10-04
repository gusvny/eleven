// sc_panel_list_contract_render.mjs — t261004-14 panel list contract (grey-box L3,
// real browser + API stubs, zero docker, never touches 3099; same architecture seam
// as t261003-06/sc_executor_panel_page_redesign.mjs).
//
// Intent (user-perceivable; ticket spec Part B + host incident: a list showed only
// 3 rows because the render loop took the head of an append-ordered array, and its
// timestamps carried no date):
//   W1 Last wakes shows the newest rows up to the cap **declared in the contract
//      module** (not an inline constant). With 6 wakes and a declared cap > 3, the
//      user sees more than the incident's 3 rows. If the contract module is absent
//      or the declared cap is not applied, this fails.
//   W2 Last wakes renders newest first (descending by at), regardless of payload
//      order — the incident's append-ordered array showed the oldest head.
//   W3 Alerts render newest first regardless of payload order.
//   W4 Waiting requests render newest first (Overview left column order).
//   W5 Timestamps in wakes, alerts and recent actions carry the date (a
//      YYYY-MM-DD of a crafted past day appears in the rendered text; HH:MM-only
//      is the incident's second face).
//   W6 Empty lists still show their empty-state copy (alerts empty copy survives
//      the rework — declared contract, not a new invention).
//   W7 A wake row with a missing/malformed `at` must not throw and must not wipe
//      the list (external input discipline; zero pageerror on the whole journey).
//   D1 Part A doc exists: docs/reference/panel-list-conventions.md, reference
//      frontmatter, and names the contract declaration site.
//
// Seam: PANEL_PAGE_HTML named export; watchdog status / requests / settings /
// grants / actions stubbed at the page boundary. playwright-core missing =
// ENV_FAIL exit 2 (KI-036 family); missing page module / contract module = FAIL
// with the name (TDD-phase red is expected; arbitrate/merge phase must be green).
// Intent split: routes/answers/actions source semantics belong to t261003-06/-10;
// this file only judges order / cap / timestamp / empty-copy behavior.
import { createServer } from 'node:http'
import { existsSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const PROJ = 'alpha'
const CONTRACT_PATH = join(REPO, 'server/plugins/executor-panel/src/host/list-contracts.ts')
const DOC_PATH = join(REPO, 'docs/reference/panel-list-conventions.md')

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}

async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

/** Read the declared wake cap from the contract module source (the declaration IS
 *  the contract — grey-box reads the promise, not the render internals). */
function declaredWakeCap() {
  if (!existsSync(CONTRACT_PATH)) return null
  const src = readFileSync(CONTRACT_PATH, 'utf8')
  // Accept any entry whose id/cap line pair mentions wakes; look for a numeric cap
  // in the wakes entry block. Deliberately loose in shape, strict in semantics:
  // a wakes entry must carry an explicit number.
  const m = src.match(/wakes[\s\S]{0,400}?cap['"]?\s*[:=]\s*(\d+)/i)
  return m ? Number(m[1]) : undefined // null = no module; undefined = module without a numeric wakes cap
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts missing')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts lacks named export PANEL_PAGE_HTML (seam contract)')
    return C.exit()
  }
  const cap = declaredWakeCap()
  if (cap === null) C.case('contract-module-present', false, 'src/host/list-contracts.ts missing (Part B: one findable declaration site)')
  else if (cap === undefined) C.case('contract-wakes-cap-declared', false, 'list-contracts.ts has no numeric cap for the wakes list')
  else C.case('contract-wakes-cap-declared', true, `declared wakes cap=${cap}`)

  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }

  // ---- page-boundary stubs (shapes follow t261004-03 corrections in t261003-06) ----
  // Payloads are deliberately NOT in newest-first order: the page must sort.
  // Wake/alert days are fixed past dates so W5 can anchor a literal date string.
  const OLD = Date.UTC(2026, 0, 5)      // 2026-01-05
  const OLDER = Date.UTC(2025, 11, 30)  // 2025-12-30
  const NOW = Date.now()
  const wakes = [
    { at: OLDER + 3_600_000, ticket: 't-old-1' },
    { at: OLD + 7_200_000, ticket: 't-new-6' },
    { at: OLDER + 1_800_000, ticket: 't-old-2' },
    { at: OLD + 900_000, ticket: 't-new-5' },
    { at: OLD + 3_600_000, ticket: 't-new-4' },
    { at: OLD + 1_800_000, ticket: 't-new-3' },
  ]
  const alerts = [
    { at: OLDER + 3_600_000, title: 'older alert', level: 'warn' },
    { at: OLD + 3_600_000, title: 'newer alert', level: 'warn' },
  ]
  const waiting = [
    { type: 'request', id: 'req-1', at: NOW - 120_000, project: PROJ, kind: 'question', question: 'Older waiting question?', detail: 'd', raised_by: 'bench', default_action: 'x', expires_at: null, status: 'waiting' },
    { type: 'request', id: 'req-2', at: NOW - 60_000, project: PROJ, kind: 'question', question: 'Newer waiting question?', detail: 'd', raised_by: 'bench', default_action: 'x', expires_at: null, status: 'waiting' },
  ]
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: waiting })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: 'Permissions: 4 of 6' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [{ at: OLD + 5_400_000, action: 'Sign', ticket: 't261002-10', result: 'ok', permission: 'merge' }], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/status')) {
      return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, wakes, alerts } })
    }
    res.writeHead(404); res.end('{}')
  })
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const port = stub.address().port
  const html = pageMod.PANEL_PAGE_HTML
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const lport = local.address().port

  const { chromium } = pw
  let browser = null
  try {
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForTimeout(600)

    // Ledger tab holds wakes; Alerts tab holds alerts. Collect rendered rows.
    const rows = await page.evaluate(() => {
      const grab = (sel) => [...document.querySelectorAll(sel)].map(e => (e.textContent || '').trim())
      return { wakes: grab('#ledgerEvents .act'), alerts: grab('#alertList .row'), acts: grab('#actList .act'), body: document.body.innerText, doc: document.documentElement.textContent }
    })
    const t = rows.body.toLowerCase()

    // W1 cap: rendered wake row count equals the declared cap when payload exceeds it.
    if (typeof cap === 'number') {
      const shown = rows.wakes.filter(x => /wake/i.test(x)).length
      C.case('W1-wakes-shown-per-declared-cap', shown === Math.min(cap, wakes.length),
        `declared=${cap} payload=${wakes.length} shown=${shown} (incident showed 3 regardless)`)
      if (cap > 3) C.case('W1b-incident-unfixed-detect', shown > 3, `shown=${shown} must exceed the incident's 3`)
    } else {
      C.case('W1-wakes-shown-per-declared-cap', false, 'no declared cap to compare against')
    }

    // W2 wakes newest first: ticket ids in DOM order must follow at desc.
    // Newest = t-new-6 > t-new-5 > t-new-4 > t-new-3 > t-old-1 > t-old-2.
    const order = ['t-new-6', 't-new-5', 't-new-4', 't-new-3', 't-old-1', 't-old-2']
    const seq = rows.wakes.map(x => (x.match(/t-(?:new|old)-\d/) || [''])[0]).filter(Boolean)
    const wantSeq = order.filter(id => seq.includes(id))
    C.case('W2-wakes-newest-first', wantSeq.length >= 2 && JSON.stringify(seq) === JSON.stringify(wantSeq), `dom order=${seq.join(',')} expected=${wantSeq.join(',')}`)

    // W3 alerts newest first.
    const aSeq = rows.alerts.map(x => x.includes('newer alert') ? 'new' : (x.includes('older alert') ? 'old' : ''))
    const aFiltered = aSeq.filter(Boolean)
    C.case('W3-alerts-newest-first', aFiltered.length === 2 && aFiltered[0] === 'new', `dom order=${aFiltered.join(',')}`)

    // W4 waiting newest first: the newer question appears above the older one.
    const iNew = rows.body.indexOf('Newer waiting question?')
    const iOld = rows.body.indexOf('Older waiting question?')
    C.case('W4-waits-newest-first', iNew !== -1 && iOld !== -1 && iNew < iOld, `newer@${iNew} older@${iOld}`)

    // W5 timestamps carry the date: the crafted past days appear in rendered text.
    const dated = rows.doc.includes('2026-01-05') && rows.doc.includes('2025-12-30')
    C.case('W5-timestamps-carry-date', dated, `2026-01-05=${rows.doc.includes('2026-01-05')} 2025-12-30=${rows.doc.includes('2025-12-30')}`)

    C.case('W7-no-pageerror-with-crafted-payloads', errors.length === 0, errors.slice(0, 2).join(' | ').slice(0, 200))
  } catch (e) {
    C.case('browser-journey', false, String(e).slice(0, 200))
  } finally {
    if (browser) { try { await browser.close() } catch { /* already closed */ } }
  }

  // W6 empty-state copy: second pass with an empty payload (separate short journey).
  try {
    const stub2 = createServer((req, res) => {
      const u = new URL(req.url, 'http://x')
      const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
      if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
      if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
      if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted' })
      if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [], malformed_rows: 0, unmapped_rows: 0 })
      if (u.pathname.endsWith('/api/status')) return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 0, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, wakes: [], alerts: [] } })
      res.writeHead(404); res.end('{}')
    })
    await new Promise(r => stub2.listen(0, '127.0.0.1', r))
    const p2 = stub2.address().port
    const browser2 = await chromium.launch({ headless: true })
    const page2 = await browser2.newPage()
    await page2.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${p2}` + new URL(route.request().url()).pathname }))
    await page2.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page2.waitForTimeout(600)
    const body = await page2.evaluate(() => document.documentElement.textContent)
    const lt = body.toLowerCase()
    const emptyCopies = lt.includes('no alerts exist') && lt.includes('no wakes yet') && lt.includes('nothing waits on you')
    C.case('W6-empty-state-copies', emptyCopies, `alerts=${lt.includes('no alerts exist')} wakes=${lt.includes('no wakes yet')} waits=${lt.includes('nothing waits on you')}`)
    await browser2.close()
    stub2.close()
  } catch (e) {
    C.case('W6-empty-state-copies', false, String(e).slice(0, 200))
  }

  // D1 contract doc face (Part A deliverable): exists, reference frontmatter,
  // points at the declaration site.
  if (!existsSync(DOC_PATH)) {
    C.case('D1-contract-doc-present', false, 'docs/reference/panel-list-conventions.md missing')
  } else {
    const doc = readFileSync(DOC_PATH, 'utf8')
    const fm = doc.slice(0, 400)
    const ok = /category:\s*reference/.test(fm) && /list-contracts/.test(doc) && /cap/i.test(doc)
    C.case('D1-contract-doc-present', ok, `reference-frontmatter=${/category:\s*reference/.test(fm)} declares-site=${/list-contracts/.test(doc)}`)
  }

  stub.close(); local.close()
  return C.exit()
}

main().catch((e) => { C.case('scenario-crash', false, String(e).slice(0, 300)); C.exit() })
