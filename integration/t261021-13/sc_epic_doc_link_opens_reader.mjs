// sc_epic_doc_link_opens_reader.mjs — t261021-13 the epic document link opens the
// console's own markdown reader (grey-box L3, real browser + page-boundary API
// stubs, zero docker, never touches 3099/7233; seam = t261003-06/lib_panel_seam).
//
// Incident (host 261021 user words): "clicking an epic's document link in the
// Epics tab opens a JSON blob in a new tab. The console already has a markdown
// reader; the link must use it."
//
// Intent (user-perceivable):
//   E1 The epic's document control is not a navigation anchor: no href aiming at
//      an api/ route, no target=_blank; clicking it does not navigate and does
//      not open a second page/tab.
//   E2 Clicking it lands the user on the Docs tab with the docs/ scope active,
//      the reader showing the title path epics/<code>.md and the document
//      rendered through the panel's existing markdown renderer: headings, bullet
//      list, table and fenced code as elements, no literal ** markers, and the
//      raw JSON envelope nowhere on screen.
//   E3 A vanished / unreadable document states a readable error (the reader's
//      "could not be read" red banner) — never an empty box, never raw JSON.
//   E4 A malformed payload (body not a string) lands in the same readable-error
//      banner (external-input malformed face).
//   E5 A project whose doc tree answers empty must still render the epic
//      document in the reader (the empty-tree branch must not wipe the reader).
//   E6 Sweep the whole surface: no anchor anywhere on the page points at an
//      api/ route (the epic link was the only one; the check keeps it that way),
//      and the served page source carries no href aimed at /api/.
//   X1 Zero pageerror across every leg.
//
// playwright-core missing = ENV_FAIL exit 2 (KI-036 family); missing page module
// = FAIL named (TDD-phase red expected pre-implement; green required at
// arbitrate/merge). Light theme only: colour-independent assertions (banner
// located by class, not colour), so the KI-055 theme matrix is not re-entered
// here (the banner copy and DOM anchor are theme-stable).
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const PROJ = 'alpha'
const CODE = 'EPIC-01'
const REL = 'epics/' + CODE + '.md'

const MD = [
  '# ' + REL + ' rendering check',
  '',
  'Use **bold** prose and `inline code`.',
  '',
  '- first bullet',
  '- second bullet',
  '',
  '| col a | col b |',
  '| --- | --- |',
  '| one | two |',
  '',
  '```js',
  'if (a < b) { keep() }',
  '```',
  '',
  'plain closing line',
].join('\n')

// Mutable stub state per leg; the doc route and the tree route read it.
let docMode = 'ok' // ok | missing | malformed
let treeEmpty = false

function stubServer() {
  const s = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [{ type: 'request', id: 'req-seed', at: Date.now() - 60_000, project: PROJ, kind: 'question', question: 'Seed row so the Overview tab renders healthily.', detail: 'seed', raised_by: 'bench', default_action: 'Proceed', options: null, expires_at: null, status: 'waiting' }] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 0, total: 0, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/status')) return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 1, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, wakes: [], alerts: [] } })
    if (u.pathname.endsWith('/api/bridge/status')) return json({ ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [] })
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: PROJ, limit: 3, unlimited: false, at_work: 0, waiting: 0, holders: [], queue: [], audit: { ok: false } })
    if (u.pathname.endsWith('/tickets')) return json({ ok: true, result: { tickets: [] } })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [{ code: CODE, retired: false, summary: 'doc link fixture epic', started: '2026-10-01' }] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) {
      if (treeEmpty) return json({ ok: true, result: { empty: true, reason: 'fixture: empty library' } })
      return json({ ok: true, result: { groups: [{ label: 'docs/epics', dir: 'epics', files: [{ rel: REL, title: 'Epic ' + CODE }] }] } })
    }
    if (u.pathname.endsWith('/api/wf/docs/doc')) {
      // A small real delay keeps the in-flight window observable for E7's
      // double-click race (the second click must win cleanly, not clobber).
      const body = docMode === 'missing' ? { ok: false, error: 'document not found: ' + REL }
        : docMode === 'malformed' ? { ok: true, result: { path: REL, body: 42 } }
        : { ok: true, result: { path: REL, body: MD } }
      setTimeout(() => json(body), 120)
      return undefined
    }
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })
    res.writeHead(404); res.end('{}')
  })
  return s
}

async function loadPlaywright() {
  for (const p of [
    join(REPO, 'server/ui-check/node_modules/playwright-core/index.mjs'),
    join(REPO, 'server/plugins/workbench/node_modules/playwright-core/index.mjs'),
  ]) {
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
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
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }

  // E6 source face, judged before the browser leg: the served page source must
  // carry no href aimed at an api/ route (static, anchor-free).
  const src = pageMod.PANEL_PAGE_HTML
  const srcApiHrefs = (src.match(/href="[^"]*\/api\/[^"]*"/g) || [])
  C.case('E6-source-no-api-href', srcApiHrefs.length === 0,
    srcApiHrefs.length ? 'api-aimed hrefs in page source: ' + JSON.stringify(srcApiHrefs) : 'no href targets an api/ route in the page source')

  const stub = stubServer()
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const port = stub.address().port
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(pageMod.PANEL_PAGE_HTML) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const lport = local.address().port

  const errors = []
  let popupSeen = false
  let browser = null
  try {
    browser = await pw.chromium.launch({ headless: true })
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } })
    // ctx.newPage() itself fires the context 'page' event — count only pages
    // other than the journey page, or every run would read as "a tab opened".
    const page = await ctx.newPage()
    ctx.on('page', (p) => { if (p !== page) popupSeen = true })
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForSelector('.row[data-row]', { timeout: 5000 })
    // The Epics tab is lazy (TAB_LOADER); select it like the user does.
    await page.click('label[for="t-epics"]')
    await page.waitForSelector('[data-epic-head]', { timeout: 5000 })

    const urlBefore = page.url()

    // Open the epic, then click its document control. The control is located by
    // its user-facing label (grey-box: contract, not implementation attribute).
    await page.click(`[data-epic-head="${CODE}"]`, { force: true })
    await page.waitForTimeout(200)
    const ctl = page.locator(`text=/Open docs\\\/epics\\\/${CODE}\\.md/`).first()
    if (await ctl.count() === 0) {
      C.case('E1-epic-doc-control-present', false, `no control labelled "Open docs/epics/${CODE}.md" in the open epic detail`)
      return C.exit()
    }

    // E1: the control must not be a navigation anchor.
    const ctlFace = await ctl.evaluate((n) => ({ tag: n.tagName, href: n.getAttribute('href'), target: n.getAttribute('target') }))
    C.case('E1-not-a-navigation-anchor',
      !(typeof ctlFace.href === 'string' && /\/api\//.test(ctlFace.href)) && !(typeof ctlFace.target === 'string' && /_blank/i.test(ctlFace.target)),
      `tag=${ctlFace.tag} href=${JSON.stringify(ctlFace.href)} target=${JSON.stringify(ctlFace.target)}`)

    // E2: click lands the reader on the SAME page, Docs tab visible, scope docs,
    // title path + rendered markdown, no JSON envelope on screen.
    await ctl.click()
    await page.waitForTimeout(500)
    const e2 = await page.evaluate((rel) => {
      const radios = [...document.querySelectorAll('input[type=radio]')]
      const docsRadio = radios.find((r) => r.value === 't-docs' || r.id === 't-docs')
      const labels = [...document.querySelectorAll('label')].filter((l) => /docs/i.test(l.textContent || ''))
      const docsTabActive = (docsRadio && docsRadio.checked) ||
        [...document.querySelectorAll('.tab,.pane,[id^=t-]')].some((n) => (n.id || '').includes('docs') && n.offsetParent !== null) ||
        labels.some((l) => l.offsetParent !== null)
      const reader = document.querySelector('#docsReader')
      const bannerRed = document.querySelectorAll('.banner.red').length
      const text = reader ? (reader.textContent || '') : ''
      return {
        docsTabActive,
        readerPresent: !!reader,
        readerVisible: !!reader && reader.offsetParent !== null,
        titleShown: text.includes(rel),
        h1: reader ? reader.querySelectorAll('h1,h2,h3').length : 0,
        li: reader ? reader.querySelectorAll('li').length : 0,
        table: reader ? reader.querySelectorAll('table').length : 0,
        preCode: reader ? reader.querySelectorAll('pre code, pre').length : 0,
        literalBold: text.includes('**'),
        rawJsonOnScreen: /"ok"\s*:/.test(text) || /"result"\s*:/.test(text),
        bannerRed,
      }
    }, REL)
    C.case('E2-same-page-no-new-tab', page.url() === urlBefore && !popupSeen,
      `urlUnchanged=${page.url() === urlBefore} newTabOpened=${popupSeen}`)
    C.case('E2b-docs-tab-active', e2.docsTabActive, `docsTabActive=${e2.docsTabActive}`)
    C.case('E2c-reader-renders-markdown',
      e2.readerVisible && e2.titleShown && e2.h1 >= 1 && e2.li >= 2 && e2.table >= 1 && e2.preCode >= 1 && !e2.literalBold && !e2.rawJsonOnScreen,
      `visible=${e2.readerVisible} title=${e2.titleShown} h=${e2.h1} li=${e2.li} table=${e2.table} pre=${e2.preCode} literal**=${e2.literalBold} rawJson=${e2.rawJsonOnScreen}`)

    // E3: vanished document — the reader states a readable error, never an
    // empty box, never raw JSON.
    // JS dispatch from here on: after the first click the epics pane is hidden
    // (the docs tab is up) and Playwright refuses real clicks on hidden
    // elements. The dispatched click exercises the same handler contract.
    docMode = 'missing'
    await ctl.evaluate((n) => n.click()); await page.waitForTimeout(500)
    const e3 = await page.evaluate(() => {
      const reader = document.querySelector('#docsReader')
      const text = reader ? (reader.textContent || '') : ''
      return {
        banner: reader ? reader.querySelectorAll('.banner.red').length : 0,
        saysUnreadable: /could not be (read|loaded)/i.test(text),
        notEmptyBox: !!reader && (reader.textContent || '').trim().length > 0,
        rawJson: /"ok"\s*:/.test(text),
      }
    })
    C.case('E3-missing-doc-readable-error',
      e3.banner >= 1 && e3.saysUnreadable && e3.notEmptyBox && !e3.rawJson,
      `banner=${e3.banner} copy=${e3.saysUnreadable} nonEmpty=${e3.notEmptyBox} rawJson=${e3.rawJson}`)

    // E4: malformed payload (body not a string) — same readable-error banner.
    docMode = 'malformed'
    await ctl.evaluate((n) => n.click()); await page.waitForTimeout(500)
    const e4 = await page.evaluate(() => {
      const reader = document.querySelector('#docsReader')
      const text = reader ? (reader.textContent || '') : ''
      return { banner: reader ? reader.querySelectorAll('.banner.red').length : 0, saysUnreadable: /could not be (read|loaded)/i.test(text) }
    })
    C.case('E4-malformed-payload-readable-error', e4.banner >= 1 && e4.saysUnreadable,
      `banner=${e4.banner} copy=${e4.saysUnreadable}`)

    // E5: empty doc-tree project — the epic doc must still render in the reader.
    docMode = 'ok'
    treeEmpty = true
    await ctl.evaluate((n) => n.click()); await page.waitForTimeout(600)
    const e5 = await page.evaluate((rel) => {
      const reader = document.querySelector('#docsReader')
      const text = reader ? (reader.textContent || '') : ''
      return { titleShown: text.includes(rel), rendered: reader ? reader.querySelectorAll('h1,h2,h3').length : 0 }
    }, REL)
    C.case('E5-empty-tree-still-renders-reader', e5.titleShown && e5.rendered >= 1,
      `title=${e5.titleShown} headings=${e5.rendered} (empty-tree branch must not wipe the reader)`)

    // E7 double-click race: two rapid activations while the doc fetch is in
    // flight must leave the reader on the epic document — never a stuck
    // "Loading" face, never a wipe (gen0 review comment 1(iv)).
    docMode = 'ok'
    treeEmpty = false
    await ctl.evaluate((n) => n.click())
    await page.waitForTimeout(40)
    await ctl.evaluate((n) => n.click())
    await page.waitForTimeout(900)
    const e7 = await page.evaluate((rel) => {
      const reader = document.querySelector('#docsReader')
      const text = reader ? (reader.textContent || '') : ''
      return {
        titleShown: text.includes(rel),
        rendered: reader ? reader.querySelectorAll('h1,h2,h3').length : 0,
        stuckLoading: /Loading /.test(text),
        empty: !reader || text.trim().length === 0,
      }
    }, REL)
    C.case('E7-double-click-race-lands-epic-doc',
      e7.titleShown && e7.rendered >= 1 && !e7.stuckLoading && !e7.empty,
      `title=${e7.titleShown} headings=${e7.rendered} stuckLoading=${e7.stuckLoading} empty=${e7.empty}`)

    // E6 DOM face: no anchor anywhere on the page aims at an api/ route.
    const e6 = await page.evaluate(() =>
      [...document.querySelectorAll('a')].map((a) => a.getAttribute('href') || '').filter((h) => /\/api\//.test(h)))
    C.case('E6-dom-no-api-anchors', e6.length === 0, `api-aimed anchors: ${JSON.stringify(e6)}`)

    C.case('X1-zero-pageerror', errors.length === 0, errors.slice(0, 3).join(' | '))
  } catch (e) {
    C.case('journey-completes', false, String(e).slice(0, 300))
  } finally {
    if (browser) await browser.close().catch(() => {})
    stub.close(); local.close()
  }
  C.exit()
}

main()
