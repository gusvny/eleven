/**
 * browser-docs-index-state.test.mjs — t261103-19: the LIVE documents face renders the
 * derived index state (real Chromium against the plugin's real static page).
 *
 * The defect: the state was computed by the engine and carried by the host face but
 * rendered nowhere. This scenario drives the panel's Docs tab — the one live documents
 * face — with a stubbed workbench docs-tree and reads the DOM a reader actually sees:
 *
 *   1. current — "Index up to date — built <time>", quiet (ok) tone;
 *   2. stale   — the last build time AND why a rebuild is due, warn tone, and the list
 *                below is still the roots' listing (never the index, never hidden);
 *   3. absent  — "Index not built yet ...", warn tone, list from the declared roots;
 *   4. failed  — the named reason and the explicit "previous index is NOT shown as
 *                current", red tone, list from the roots;
 *   5. a refused documentation root is its own answer: no index banner, the refusal
 *                reason in place of the listing;
 *   6. a payload with no index face (the notes scope shape) and a malformed face render
 *                no banner at all — nothing is fabricated;
 *   7. read-only: the whole run makes no rebuild call (every docs request is a GET on
 *                tree/doc), so opening the view can never start a rebuild.
 *
 * The expected sentences come from `indexBanner` — the ONE wording the delivery defines
 * — so this scenario also proves the page does not carry a second wording.
 *
 * Fully isolated: kernel-picked port, temporary panel/watchdog dirs, no 3099, no 7233.
 */
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup, panelCookieFor } from './lib.mjs'
import { INDEX_COPY, indexBanner } from '../../knowledge/src/shared/docs-roots.ts'

const require = createRequire(import.meta.url)
function findPlaywrightCore() {
  let dir = import.meta.dirname
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found: expected server/ui-check/node_modules in this checkout or a sibling of the lane root')
}
const playwright = require(findPlaywrightCore())
async function launchBrowser() {
  try { return await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
  catch { return await playwright.chromium.launch({ headless: true }) }
}

const BUILT_AT = '2026-11-03T02:00:00.000Z'
const STALE_WHY = 'a document is newer than the build (page mtime 2026-11-03T03:00:00.000Z, built 2026-11-03T02:00:00.000Z)'
const FAILED_WHY = 'the documentation inspection could not read kb/design/a.md (EACCES)'

/** The host's sentence for one state — the same function the workbench face calls. */
function hostBanner(state, over = {}) {
  return indexBanner({
    state, project: 'idxdelta', builtAt: BUILT_AT, staleReason: '', reason: '', code: '',
    entries: [], roots: [], total: 0,
    review: { missing_frontmatter: [], deprecated: [], stale: [] }, ...over,
  })
}

function indexFace(state, over = {}) {
  return {
    state, built_at: BUILT_AT, stale_reason: over.staleReason || '', reason: over.reason || '',
    code: over.code || '', banner: hostBanner(state, over), total: 0,
  }
}

/** A served docs-tree payload (the shape /api/wf/docs/tree answers with). */
function servedTree(index) {
  const out = {
    empty: false, state: 'served', declared: false, declaration: '',
    roots: [{ id: '.:kb', repository: '.', path: 'kb', state: 'served', declared: false, groups: 1, docs: 2 }],
    groups: [{ dir: 'design', label: 'design', files: [
      { rel: 'design/a.md', title: 'A page' },
      { rel: 'design/b.md', title: 'B page' },
    ] }],
    skipped: [], looked_for: ['kb'], code: '',
  }
  if (index !== undefined) out.index = index
  return out
}

const wd = freshDir(), pan = freshDir()
const mod = await import('../harness.mjs')
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
const KEY = 'idxdelta'

const browser = await launchBrowser()
let n = 0
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const cookie = panelCookieFor(new URL(H.base).host)
  const ci = cookie.indexOf('=')
  await ctx.addCookies([{ name: cookie.slice(0, ci), value: cookie.slice(ci + 1), url: H.base }])
  const page = await ctx.newPage()
  page.setDefaultTimeout(20000)

  const requests = []
  page.on('request', (r) => requests.push({ url: r.url(), method: r.method() }))

  let tree = servedTree(indexFace('current'))
  let docsDocStatus = 'served'
  await page.route('**/sandbar-workbench/api/wf/docs/tree**', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: tree }) }))
  await page.route('**/sandbar-workbench/api/wf/docs/doc**', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { empty: docsDocStatus !== 'served', reason: docsDocStatus === 'served' ? undefined : 'refused', rel: 'design/a.md', title: 'A page', meta: {}, body: '# A page' } }) }))

  /** Load the panel, open the Docs tab, wait for the list and the banner (if any). */
  async function openDocs(expectedState) {
    await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
    await page.waitForSelector('label[for="t-docs"]', { timeout: 20000 })
    await page.click('label[for="t-docs"]')
    await page.waitForSelector('#docsTree [data-doc]', { timeout: 20000 })
    if (expectedState !== null) {
      await page.waitForFunction((s) => {
        const node = document.querySelector('#docsBanner [data-docs-index-state]')
        return !!node && node.getAttribute('data-docs-index-state') === s
      }, expectedState, { polling: 100 })
    }
  }
  async function readFace() {
    return await page.evaluate(() => {
      const node = document.querySelector('#docsBanner [data-docs-index-state]')
      const rows = [...document.querySelectorAll('#docsTree [data-doc]')]
      return {
        banners: document.querySelectorAll('#docsBanner [data-docs-index-state]').length,
        state: node ? node.getAttribute('data-docs-index-state') : null,
        text: node ? node.textContent.trim() : '',
        cls: node ? node.className : '',
        rows: rows.map((r) => r.getAttribute('data-doc')),
        tree: (document.getElementById('docsTree')?.innerText || '').trim(),
      }
    })
  }

  /* ---- 1. current ---------------------------------------------------------- */
  const currentText = hostBanner('current')
  await openDocs('current')
  {
    const f = await readFace()
    assert(f.banners === 1, 'current: exactly one banner renders on the docs face')
    assert(f.text === currentText, `current: the host sentence renders verbatim (${JSON.stringify(f.text)})`)
    assert(/Index up to date/i.test(f.text) && f.text.includes(BUILT_AT), 'current: names the build time')
    assert(/banner ok/.test(f.cls), `current: quiet (ok) tone, got class ${JSON.stringify(f.cls)}`)
    assert(f.rows.length === 2, `current: the list renders beside the banner (rows=${f.rows.length})`)
    n += 5
  }

  /* ---- 2. stale ------------------------------------------------------------ */
  const staleText = hostBanner('stale', { staleReason: STALE_WHY })
  tree = servedTree(indexFace('stale', { staleReason: STALE_WHY }))
  await openDocs('stale')
  {
    const f = await readFace()
    assert(f.text === staleText, 'stale: the host sentence renders verbatim')
    assert(/Index is stale/i.test(f.text) && f.text.includes(BUILT_AT), 'stale: names the time of the last build')
    assert(f.text.includes(STALE_WHY), 'stale: names why a rebuild is due')
    assert(!/up to date/i.test(f.text), 'stale: never reads as current')
    assert(!/banner ok/.test(f.cls) && !/banner red/.test(f.cls), `stale: warn tone (neither current-quiet nor failed-red), got ${JSON.stringify(f.cls)}`)
    assert(f.rows.length === 2 && /design\/a\.md/.test(f.rows.join(',')), 'stale: the list beside it is still the roots listing (not the index, not hidden)')
    n += 6
  }

  /* ---- 3. absent ----------------------------------------------------------- */
  tree = servedTree(indexFace('absent'))
  await openDocs('absent')
  {
    const f = await readFace()
    assert(f.text === INDEX_COPY.absent, 'absent: the host sentence renders verbatim')
    assert(/not built yet/i.test(f.text) && /declared roots/i.test(f.text), 'absent: says never built, and names the list source')
    assert(!/up to date/i.test(f.text), 'absent: never reads as current')
    assert(f.rows.length === 2, 'absent: the documents are still listed from the declared roots')
    n += 4
  }

  /* ---- 4. failed ----------------------------------------------------------- */
  const failedText = hostBanner('failed', { reason: FAILED_WHY, code: 'docs_index_rebuild_failed' })
  tree = servedTree(indexFace('failed', { reason: FAILED_WHY, code: 'docs_index_rebuild_failed' }))
  await openDocs('failed')
  {
    const f = await readFace()
    assert(f.text === failedText, 'failed: the host sentence renders verbatim')
    assert(f.text.includes(FAILED_WHY), 'failed: carries the named reason')
    assert(/previous index is NOT shown as current/i.test(f.text), 'failed: says explicitly that the previous index is not current')
    assert(/banner red/.test(f.cls), `failed: red tone, got ${JSON.stringify(f.cls)}`)
    assert(f.rows.length === 2, 'failed: the list beside it is the roots listing, not the failed index')
    n += 5
  }

  /* ---- 5. a refused root is its own answer (no index banner) --------------- */
  tree = {
    empty: true, state: 'refused', declared: true, declaration: '/tmp/idxdelta/project.yaml',
    reason: 'the declared documentation root is absent (declaration repository `.`, path kb)',
    roots: [], groups: [], skipped: [], looked_for: ['/tmp/idxdelta/kb'], code: 'docs_roots_root_absent',
    index: indexFace('failed', { reason: 'the declared documentation root is absent (declaration repository `.`, path kb)' }),
  }
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  await page.waitForSelector('label[for="t-docs"]', { timeout: 20000 })
  await page.click('label[for="t-docs"]')
  await page.waitForFunction(() => /documentation root is absent/i.test(document.getElementById('docsTree')?.innerText || ''), null, { polling: 100 })
  {
    const f = await readFace()
    assert(f.banners === 0, 'refused: no index banner is rendered (the refusal is the answer)')
    assert(/documentation root is absent/i.test(f.tree), 'refused: the named refusal renders in place of the listing')
    n += 2
  }

  /* ---- 6. no index face / malformed face: nothing is fabricated ------------ */
  tree = servedTree(undefined)
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  await page.waitForSelector('label[for="t-docs"]', { timeout: 20000 })
  await page.click('label[for="t-docs"]')
  await page.waitForSelector('#docsTree [data-doc]', { timeout: 20000 })
  await page.waitForTimeout(300)
  {
    const f = await readFace()
    assert(f.banners === 0, 'no index face: no banner renders (nothing fabricated)')
    assert(f.rows.length === 2, 'no index face: the listing still renders')
  }
  tree = servedTree({ state: 'stale', banner: '', built_at: BUILT_AT, stale_reason: STALE_WHY, reason: '', code: '', total: 0 })
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  await page.waitForSelector('label[for="t-docs"]', { timeout: 20000 })
  await page.click('label[for="t-docs"]')
  await page.waitForSelector('#docsTree [data-doc]', { timeout: 20000 })
  await page.waitForTimeout(300)
  {
    const f = await readFace()
    assert(f.banners === 0, 'malformed index face (empty banner): no banner renders, no sentence invented')
    assert(f.rows.length === 2, 'malformed index face: the listing still renders')
    n += 4
  }

  /* ---- 7. read-only: no rebuild call in the whole run ---------------------- */
  const docsReqs = requests.filter((r) => r.url.includes('/api/wf/docs/'))
  assert(docsReqs.length > 0, `read-only: the run did reach the docs endpoint (${docsReqs.length} request(s))`)
  assert(docsReqs.every((r) => /\/docs\/(tree|doc)\?/.test(r.url)), 'read-only: every docs request is a tree/doc read')
  assert(docsReqs.every((r) => r.method === 'GET'), 'read-only: every docs request is a GET (no write path is used)')
  assert(!requests.some((r) => /rebuild/i.test(r.url)), 'read-only: no rebuild route was called while rendering the four states')
  n += 4

  await ctx.close()
} finally {
  await browser.close()
  await H.close().catch(() => {})
  cleanup([wd, pan])
}
console.log('done ' + n)
done(n)
