/**
 * t261103-19 — the live documents face renders the derived index state.
 *
 * The defect this ticket closes: the state was COMPUTED and carried by the host and
 * engine faces but rendered nowhere, so a reader could never see "index stale, last
 * built <time>", "index not built yet" or "rebuild failed: <reason>". This battery pins
 * the three things that make the live panel face honest:
 *
 *   A. the four states map to four distinguishable presentations (current quiet; absent
 *      and stale warn; failed red), and the sentence shown is the HOST's own sentence —
 *      taken from `indexBanner`, the one implementation the delivery already defines, so
 *      there is one wording and not two;
 *   B. a malformed or missing index face renders nothing (no fabricated state, no empty
 *      banner), and an unknown state is shown as itself, never mapped onto one of the
 *      four;
 *   C. the page is READ-ONLY and has exactly one banner surface: the docs render path
 *      writes the banner from the payload's index face, a refused root keeps the banner
 *      slot empty, and no docs code path calls a rebuild.
 *
 * Zero DOM, zero network, zero port: the presentation model is imported directly and the
 * page wiring is asserted on the served source (the same source the browser runs).
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { INDEX_COPY, indexBanner } from '../../knowledge/src/shared/docs-roots.ts'
import { docsIndexBannerHtml, docsIndexStateView } from '../src/host/docs-index-view.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const PAGE_SRC = readFileSync(join(HERE, '..', 'src', 'host', 'panel-page.ts'), 'utf8')
const MODEL_SRC = readFileSync(join(HERE, '..', 'src', 'host', 'docs-index-view.ts'), 'utf8')

/** The page's own escaper shape, mimicked: text, never markup. */
const esc = (text) => String(text == null ? '' : text)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

let pass = 0
let fail = 0
function ok(cond, label, detail = '') {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** One IndexRead-shaped object, as the host face builds it. */
function read(state, over = {}) {
  return {
    state, project: 't261103-19', builtAt: '2026-11-03T02:00:00.000Z',
    staleReason: '', reason: '', code: '', entries: [], roots: [], total: 0,
    review: { missing_frontmatter: [], deprecated: [], stale: [] }, ...over,
  }
}

const STALE_WHY = 'a document is newer than the build (page mtime 2026-11-03T03:00:00.000Z, built 2026-11-03T02:00:00.000Z)'
const FAILED_WHY = 'the documentation inspection could not read kb/design/a.md (EACCES)'

/** The face as the workbench host hands it to the page (result.index). */
function faceOf(state, over = {}) {
  const r = read(state, over)
  return {
    state: r.state, built_at: r.builtAt, stale_reason: r.staleReason, reason: r.reason,
    code: r.code, banner: indexBanner(r), total: 0,
  }
}

/** A served docs-tree payload carrying that index face. */
function payloadOf(state, over = {}) {
  return {
    empty: false, state: 'served', declared: false, declaration: '',
    roots: [{ id: '.:kb', repository: '.', path: 'kb', state: 'served', declared: false, groups: 1, docs: 1 }],
    groups: [{ dir: 'design', label: 'design', files: [{ rel: 'design/a.md', title: 'A' }] }],
    skipped: [], looked_for: ['kb'], code: '',
    index: faceOf(state, over),
  }
}

/* ------------------------------------------------------------------ A */
section('A. the four states render, each in its own presentation, with the host sentence')

for (const state of ['current', 'absent', 'stale', 'failed']) {
  const view = docsIndexStateView(payloadOf(state, state === 'stale' ? { staleReason: STALE_WHY } : (state === 'failed' ? { reason: FAILED_WHY } : {})))
  ok(view !== null, `state ${state}: a face is rendered`)
  if (!view) continue
  ok(view.state === state, `state ${state}: the host state string is carried verbatim`, String(view.state))
  // The ONE wording: the sentence is the host's `indexBanner` output, byte for byte.
  ok(view.banner === faceOf(state, state === 'stale' ? { staleReason: STALE_WHY } : (state === 'failed' ? { reason: FAILED_WHY } : {})).banner,
    `state ${state}: the sentence is the host banner verbatim (one wording, not two)`)
  ok(view.notCurrent === (state !== 'current'), `state ${state}: notCurrent = ${state !== 'current'}`)
}

ok(docsIndexStateView(payloadOf('current')).tone === 'ok', 'current is the quiet tone')
ok(docsIndexStateView(payloadOf('absent')).tone === 'warn', 'absent is the warn tone')
ok(docsIndexStateView(payloadOf('stale', { staleReason: STALE_WHY })).tone === 'warn', 'stale is the warn tone')
ok(docsIndexStateView(payloadOf('failed', { reason: FAILED_WHY })).tone === 'red', 'failed is the red tone')

// The exact copy the delivery defines, asserted once here so a silent rewrite of the
// sentence by either side goes red.
{
  const absent = docsIndexStateView(payloadOf('absent')).banner
  ok(absent === INDEX_COPY.absent, 'absent sentence = INDEX_COPY.absent')
  ok(/declared roots/i.test(absent), 'absent sentence names the list source (the declared roots)')

  const stale = docsIndexStateView(payloadOf('stale', { staleReason: STALE_WHY })).banner
  ok(stale.startsWith(INDEX_COPY.stalePrefix), 'stale sentence opens with INDEX_COPY.stalePrefix')
  ok(stale.includes('2026-11-03T02:00:00.000Z'), 'stale sentence names the time of the last build')
  ok(stale.includes(STALE_WHY), 'stale sentence names why a rebuild is due')
  ok(/not from that index/i.test(stale), 'stale sentence says the list is not that index')
  ok(!/up to date/i.test(stale), 'stale never reads as current')

  const failed = docsIndexStateView(payloadOf('failed', { reason: FAILED_WHY })).banner
  ok(failed.startsWith(INDEX_COPY.failedPrefix), 'failed sentence opens with INDEX_COPY.failedPrefix')
  ok(failed.includes(FAILED_WHY), 'failed sentence carries the named reason')
  ok(/previous index is NOT shown as current/i.test(failed), 'failed sentence says the previous index is NOT current')
  ok(!/up to date/i.test(failed), 'failed never reads as current')

  const current = docsIndexStateView(payloadOf('current')).banner
  ok(current.startsWith(INDEX_COPY.currentPrefix), 'current sentence opens with INDEX_COPY.currentPrefix')
  ok(current.includes('2026-11-03T02:00:00.000Z'), 'current sentence names the build time')
}

/* ------------------------------------------------------------------ B */
section('B. malformed input invents nothing')

ok(docsIndexStateView(undefined) === null, 'undefined payload renders nothing')
ok(docsIndexStateView(null) === null, 'null payload renders nothing')
ok(docsIndexStateView({}) === null, 'payload without an index face renders nothing (the notes scope shape)')
ok(docsIndexStateView({ index: null }) === null, 'null index face renders nothing')
ok(docsIndexStateView({ index: { state: 'stale', banner: '' } }) === null, 'empty banner renders nothing (no fabricated sentence)')
ok(docsIndexStateView({ index: { banner: 'text' } }) === null, 'missing state renders nothing')
ok(docsIndexStateView({ index: { state: 'stale', banner: 42 } }) === null, 'non-string banner renders nothing')
{
  const unknown = docsIndexStateView({ index: { state: 'half-built', banner: 'Index is half-built.' } })
  ok(unknown !== null && unknown.state === 'half-built' && unknown.tone === 'warn' && unknown.notCurrent === true,
    'an unknown state is shown as itself with the warn tone, never mapped onto one of the four')
}

/* ------------------------------------------------------------------ B2 */
section('B2. the banner markup: one tone per state, the sentence escaped verbatim')

for (const [state, cls] of [['current', 'banner ok'], ['absent', 'banner'], ['stale', 'banner'], ['failed', 'banner red']]) {
  const payload = payloadOf(state, state === 'stale' ? { staleReason: STALE_WHY } : (state === 'failed' ? { reason: FAILED_WHY } : {}))
  const html = docsIndexBannerHtml(payload, esc)
  const view = docsIndexStateView(payload)
  ok(html.startsWith(`<div class="${cls}" data-docs-index-state="${state}">`),
    `${state}: the banner carries the ${JSON.stringify(cls)} tone and its own state`)
  ok(html.includes(esc(view.banner)), `${state}: the sentence is rendered escaped and verbatim`)
  ok((html.match(/<div /g) || []).length === 1, `${state}: exactly one banner element per payload`)
}
ok(docsIndexBannerHtml({}, esc) === '', 'no index face: no markup at all')
ok(docsIndexBannerHtml({ index: { state: 'failed', banner: '' } }, esc) === '', 'malformed face: no markup at all')
{
  const hostile = { index: { state: 'failed', banner: '<img src=x onerror=alert(1)>' } }
  const html = docsIndexBannerHtml(hostile, esc)
  ok(!/<img/.test(html) && html.includes('&lt;img'), 'the banner sentence is escaped (host data is not markup)')
}

/* ------------------------------------------------------------------ C */
section('C. the live page: one banner surface, read-only')

ok(/String\(docsIndexStateView\), String\(docsIndexBannerHtml\)/.test(PAGE_SRC),
  'the page embeds both the state view and the banner builder (UT and page run one implementation)')
ok(/import \{ docsIndexStateView, docsIndexBannerHtml \} from '\.\/docs-index-view\.ts'/.test(PAGE_SRC),
  'the page imports the presentation model (appended after the template: the line-keyed face-dash sites stay put)')
ok(/e\.innerHTML=\(d\.state==='refused'\) \? '' : docsIndexBannerHtml\(d, esc\);/.test(PAGE_SRC),
  'the docs render writes the banner from the payload, and a refused root keeps the slot empty')
ok(!/docsIndexBannerHtml\(d, esc\)[\s\S]{0,120}fetch\(/.test(PAGE_SRC),
  'the banner render is not followed by a fetch (a render can never start a rebuild)')
ok(!/function docsIndexBannerHtml/.test(PAGE_SRC.slice(PAGE_SRC.indexOf("'use strict'"), PAGE_SRC.indexOf('</html>`'))),
  'no second banner builder lives inside the served page (one implementation only)')

// Read-only: the docs face talks to exactly two endpoints (list + one page). No rebuild
// route exists in the page, so opening the view can never start one.
const docsUrls = [...PAGE_SRC.matchAll(/var url='([^']*\/api\/wf\/docs\/[^']*)'/g)].map((m) => m[1])
ok(docsUrls.length === 2, `the docs face uses two endpoints (got ${docsUrls.length}: ${docsUrls.join(' | ')})`)
ok(docsUrls.every((u) => /\/docs\/(tree|doc)\?/.test(u)), 'both are read endpoints (tree, doc)')
ok(!/api\/wf\/docs\/[a-z]*rebuild/i.test(PAGE_SRC + MODEL_SRC), 'no docs rebuild route is named anywhere in the renderer')
ok(!/fetch\(|XMLHttpRequest|\.post\(|method:/.test(MODEL_SRC),
  'the presentation model never calls the network (no rebuild, no write)')

console.log(`\n${fail === 0 ? 'PASS' : 'FAIL'} t261103-19 docs index face: ${pass} ok, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
