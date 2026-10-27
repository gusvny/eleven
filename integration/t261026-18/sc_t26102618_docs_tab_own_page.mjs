// sc_t26102618_docs_tab_own_page.mjs — t261026-18 the Docs tab journey after the
// four host-reported defects are fixed (grey-box L3, real browser + page-boundary
// API stubs, zero docker, never touches 3099/7233; seam = t261003-06/lib_panel_seam).
//
// Incident (host 261026 user words): "docs 那个 tab，里头 docs/ 和 notes 两个 button
// 没用了吧，上面已经有 open 按钮了。另外，点击单个 doc 应该有一个新页来显示这个 doc
// 的内容，而不是在当前的 list 下面。另外"总目录"还是中文。还有，notes 目录下面的
// epics 也没用了吧，都已经放到 documents 里去了。"
//
// Intent (user-perceivable):
//   S1 ONE scope selector: the redundant docs//notes/ bar (#docsScopeBar) is gone
//      from the served page source AND the live DOM; the entry rows (#docsEntries)
//      remain the only scope chooser.
//   S2 The entry rows still switch scope: activating the notes entry loads the
//      notes tree (the stub records which scope was requested); scope state and
//      the load path are unchanged.
//   S3 The root-level file group label is English: the tree renders root files
//      under an ASCII label and the fixed Chinese label '总目录' appears nowhere
//      on the page. File titles and directory names (data) are NOT asserted —
//      data stays whatever the library says.
//   S4 A document opens on its own page: clicking a doc in the tree replaces the
//      list view with the article view (tree not on screen), the article renders
//      through the markdown renderer, and a clear back control returns the list.
//   S5 The notes/epics group is hidden in the view: the notes tree stub DOES
//      return an epics group (files stay on disk — never deleted) but the pane
//      does not render it; under the docs scope the epics group STAYS visible
//      (the Epics tab opens docs/epics/<code>.md through it).
//   S6 Epic link path intact on the new view: the Epics tab document link still
//      opens the article, on the page view (list replaced), and back returns to
//      the docs list. Intent split: t261021-13-epic-doc-link-opens-reader owns
//      "the epic link opens the reader at all" (E1-E7); THIS entry owns only how
//      that landing coexists with the new list/article view split.
//   S7 A malformed doc payload (body not a string) states a readable error on
//      the article view — never raw JSON on the page.
//   X1 Zero pageerror across every leg.
//
// playwright-core missing = ENV_FAIL exit 2 (KI-036 family); failing faces while
// the fix is not yet implemented = FAIL named (TDD-phase red expected; green
// required at arbitrate/merge). Light theme only; assertions locate by DOM
// anchor, never by colour (KI-055 theme-matrix discipline).
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const ROOT_REL = 'README.md'
const NOTE_REL = 'notes/scratch.md'
const EPIC_REL = 'epics/EPIC-01.md'
const CODE = 'EPIC-01'

const ARTICLE = [
  '# Fixture article', '',
  'Use **bold** prose.', '',
  '- one', '- two', '',
  'closing line',
].join('\n')

// Stub state per leg.
let docMode = 'ok' // ok | malformed
let requestedScopes = []

function groupsFor(scope) {
  // Root-level files carry dir '' (the group whose fixed label this ticket
  // turns English). The notes scope deliberately includes an epics group —
  // the files exist on disk; the VIEW must hide them (S5).
  const groups = []
  if (scope === 'docs') {
    groups.push({ label: 'epics', dir: 'epics', files: [{ rel: EPIC_REL, title: 'Epic ' + CODE }] })
  }
  if (scope === 'notes') {
    groups.push({ label: 'epics', dir: 'epics', files: [{ rel: 'epics/EPIC-01.md', title: 'Epic ' + CODE }] })
    groups.push({ label: 'notes', dir: 'notes', files: [{ rel: NOTE_REL, title: 'Scratch note' }] })
  }
  groups.push({ label: '', dir: '', files: [{ rel: ROOT_REL, title: 'Root readme' }] })
  return groups
}

function stubServer() {
  const s = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [{ type: 'request', id: 'req-seed', at: Date.now() - 60_000, project: PROJ, kind: 'question', question: 'Seed row so the Overview tab renders healthily.', detail: 'seed', raised_by: 'bench', default_action: 'Proceed', options: null, expires_at: null, status: 'waiting' }] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 0, total: 0, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/status')) return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 1, duplicates: 0, bad: 0 } }, liveness: { executor: { alive: true } }, wakes: [], alerts: [] } })
    if (u.pathname.endsWith('/api/bridge/status')) return json({ ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [] })
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: PROJ, limit: 3, unlimited: false, at_work: 0, waiting: 0, holders: [], queue: [], audit: { ok: false } })
    if (u.pathname.endsWith('/tickets')) return json({ ok: true, result: { tickets: [] } })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [{ code: CODE, retired: false, summary: 'doc link fixture epic', started: '2026-10-01' }] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) {
      const scope = u.searchParams.get('scope') || 'docs'
      requestedScopes.push(scope)
      return json({ ok: true, result: { groups: groupsFor(scope) } })
    }
    if (u.pathname.endsWith('/api/wf/docs/doc')) {
      const rel = u.searchParams.get('scope_path') || u.searchParams.get('path') || ''
      const body = docMode === 'malformed' ? 42 : ARTICLE
      return json({ ok: true, result: { path: rel, body } })
    }
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })
    res.writeHead(404); res.end('{}')
  })
  return s
}

async function loadPlaywright() {
  for (const p of [
    join(process.env.HOME || '', '.sandbar', 'pw', 'playwright-core', 'index.mjs'),
    join(fileURLToPath(new URL('../../', import.meta.url)), 'server/ui-check/node_modules/playwright-core/index.mjs'),
    join(fileURLToPath(new URL('../../', import.meta.url)), 'server/plugins/workbench/node_modules/playwright-core/index.mjs'),
  ]) {
    if (p && existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
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

  // S1 source face, judged before the browser leg: the redundant bar must not
  // exist as a live shape in the served page source (the removal comment naming
  // #docsScopeBar is not a selector).
  const src = pageMod.PANEL_PAGE_HTML
  const liveBar = /id="docsScopeBar"|getElementById\(\s*['"]docsScopeBar/.test(src)
  C.case('S1-no-scope-bar-in-source', !liveBar,
    liveBar ? 'live docsScopeBar shape still in the page source' : 'no live docsScopeBar shape in the page source')

  const stub = stubServer()
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const port = stub.address().port
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(pageMod.PANEL_PAGE_HTML) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const lport = local.address().port

  const errors = []
  let browser = null
  try {
    browser = await pw.chromium.launch({ headless: true })
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } })
    const page = await ctx.newPage()
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    // Keep the query string on the redirect: the scope switch face (S2) is judged
    // from the tree request's scope param, and the doc route names its article.
    await page.route('**/api/**', (route) => {
      const u = new URL(route.request().url())
      route.continue({ url: `http://127.0.0.1:${port}` + u.pathname + u.search })
    })
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForSelector('.row[data-row]', { timeout: 30000 })
    await page.click('label[for="t-docs"]')
    await page.waitForSelector('#docsTree [data-doc], #docsTree .group, #docsTree *', { timeout: 30000 })

    // S1 live face: the bar is gone from the DOM, the entry rows are still there.
    const s1 = await page.evaluate(() => ({
      bar: !!document.querySelector('#docsScopeBar'),
      entries: !!document.querySelector('#docsEntries'),
      entryCount: document.querySelectorAll('#docsEntries [data-docopen]').length,
    }))
    C.case('S1-scope-bar-gone-from-dom', !s1.bar && s1.entries && s1.entryCount >= 1,
      `bar=${s1.bar} entries=${s1.entries} entryRows=${s1.entryCount}`)

    // S3 root label is English: root files render under an ASCII label; the
    // fixed Chinese label appears nowhere. Data (titles/dirs) not asserted.
    const s3 = await page.evaluate(() => {
      const tree = document.querySelector('#docsTree')
      const text = tree ? (tree.textContent || '') : ''
      const cjk = (s) => /[\u4e00-\u9fff]/.test(s || '')
      const labels = [...document.querySelectorAll('#docsTree [data-docdir], #docsTree [data-dir], #docsTree .group, #docsTree .dirlabel')]
        .map((n) => (n.getAttribute('data-docdir') || n.getAttribute('data-dir') || n.textContent || '').trim())
      const rootReadme = text.includes('Root readme')
      return { anyCjkInTree: cjk(text), labels, rootReadme, pageCjk: cjk(document.body.textContent) }
    })
    C.case('S3-root-label-english', s3.rootReadme && !s3.anyCjkInTree,
      `rootFileShown=${s3.rootReadme} cjkInTree=${s3.anyCjkInTree} labels=${JSON.stringify(s3.labels)}`)
    C.case('S3b-no-zongmulu-anywhere', !/总目录/.test(await page.evaluate(() => document.body.textContent)),
      "the fixed label '总目录' appears nowhere on the page")

    // S4 own page: open a doc from the tree — the list is replaced by the
    // article, and a back control returns the list.
    await page.evaluate((rel) => {
      const n = document.querySelector(`#docsTree [data-doc="${rel}"]`) ||
        [...document.querySelectorAll('#docsTree *')].find((x) => (x.textContent || '').includes('Root readme'))
      if (n) n.click()
    }, ROOT_REL)
    await page.waitForTimeout(600)
    const s4a = await page.evaluate((rel) => {
      const tree = document.querySelector('#docsTree')
      const reader = document.querySelector('#docsReader')
      const body = document.body.textContent || ''
      return {
        treeVisible: !!tree && tree.offsetParent !== null && (tree.textContent || '').includes('Root readme'),
        articleShown: body.includes('Fixture article') && body.includes(rel),
        rendered: body.includes('closing line'),
        backCandidates: ['[data-docback]', '.backbtn', '[data-doc-back]']
          .map((s) => ({ s, n: document.querySelectorAll(s).length })),
      }
    }, ROOT_REL)
    const backSel = (s4a.backCandidates.find((b) => b.n >= 1) || {}).s || null
    C.case('S4-article-replaces-list', s4a.articleShown && s4a.rendered && !s4a.treeVisible,
      `article=${s4a.articleShown} rendered=${s4a.rendered} listStillVisible=${s4a.treeVisible}`)
    C.case('S4b-back-control-present', !!backSel, backSel ? `back control found at ${backSel}` : 'no back control in the article view')

    if (backSel) {
      await page.evaluate((s) => { const n = document.querySelector(s); if (n) n.click() }, backSel)
      await page.waitForTimeout(400)
      const s4c = await page.evaluate(() => {
        const tree = document.querySelector('#docsTree')
        return { listBack: !!tree && tree.offsetParent !== null && (tree.textContent || '').includes('Root readme') }
      })
      C.case('S4c-back-returns-list', s4c.listBack, `listBack=${s4c.listBack}`)
    }

    // S7 malformed payload face on the article view (external input).
    docMode = 'malformed'
    await page.evaluate((rel) => {
      const n = document.querySelector(`#docsTree [data-doc="${rel}"]`) ||
        [...document.querySelectorAll('#docsTree *')].find((x) => (x.textContent || '').includes('Root readme'))
      if (n) n.click()
    }, ROOT_REL)
    await page.waitForTimeout(600)
    const s7 = await page.evaluate(() => {
      const body = document.body.textContent || ''
      return { readableError: /could not be (read|loaded)|unable to (read|load)/i.test(body), rawJson: /"ok"\s*:/.test(body), banner: document.querySelectorAll('.banner.red').length }
    })
    C.case('S7-malformed-payload-readable-error', s7.readableError && !s7.rawJson,
      `copy=${s7.readableError} rawJson=${s7.rawJson} banner=${s7.banner}`)
    docMode = 'ok'

    // S2/S5: entry rows choose scope; the notes tree hides the epics group.
    requestedScopes = []
    await page.evaluate(() => {
      const b = document.querySelector('#docsEntries [data-docopen="notes"]') ||
        [...document.querySelectorAll('#docsEntries *')].find((x) => (x.textContent || '').includes('notes'))
      if (b) b.click()
    })
    await page.waitForTimeout(600)
    const s5 = await page.evaluate(() => {
      const tree = document.querySelector('#docsTree')
      const text = tree ? (tree.textContent || '') : ''
      return { noteShown: text.includes('Scratch note'), epicShown: text.includes('Epic EPIC-01') }
    })
    C.case('S2-entry-row-loads-notes-scope', requestedScopes.includes('notes') && s5.noteShown,
      `scopesRequested=${JSON.stringify(requestedScopes)} noteShown=${s5.noteShown}`)
    C.case('S5-notes-epics-group-hidden', !s5.epicShown,
      `epicsGroupRendered=${s5.epicShown} (stub still returned it — files stay on disk, the view hides it)`)

    // S5b docs scope keeps epics visible; S6 epic link lands on the page view.
    requestedScopes = []
    await page.evaluate(() => {
      const b = document.querySelector('#docsEntries [data-docopen="docs"]') ||
        [...document.querySelectorAll('#docsEntries *')].find((x) => (x.textContent || '').includes('docs'))
      if (b) b.click()
    })
    await page.waitForTimeout(600)
    const s5b = await page.evaluate(() => {
      const text = (document.querySelector('#docsTree') || {}).textContent || ''
      return { epicShown: text.includes('Epic EPIC-01') }
    })
    C.case('S5b-docs-scope-keeps-epics', s5b.epicShown,
      `epicsGroupRendered=${s5b.epicShown} (Epics tab opens docs/epics/<code>.md through it)`)

    await page.click('label[for="t-epics"]')
    await page.waitForSelector('[data-epic-head]', { timeout: 30000 })
    await page.click(`[data-epic-head="${CODE}"]`, { force: true })
    await page.waitForTimeout(200)
    await page.evaluate((code) => {
      const ctl = [...document.querySelectorAll('*')].find((n) => (n.textContent || '').includes(`Open docs/epics/${code}.md`))
      if (ctl) ctl.click()
    }, CODE)
    await page.waitForTimeout(600)
    const s6 = await page.evaluate((rel) => {
      const body = document.body.textContent || ''
      const tree = document.querySelector('#docsTree')
      return { articleShown: body.includes(rel), listHidden: !tree || tree.offsetParent === null }
    }, EPIC_REL)
    C.case('S6-epic-link-lands-on-page-view', s6.articleShown && s6.listHidden,
      `article=${s6.articleShown} listHidden=${s6.listHidden} (view split owned here; reader-opening itself owned by t261021-13)`)

    C.case('X1-zero-pageerror', errors.length === 0, errors.length ? 'page errors: ' + errors.slice(0, 3).join(' | ') : 'no pageerror/console error in any leg')
  } finally {
    if (browser) await browser.close().catch(() => {})
    await new Promise(r => local.close(r))
    await new Promise(r => stub.close(r))
  }
  C.exit()
}

main().catch((e) => { console.error('FATAL', e); process.exit(1) })
