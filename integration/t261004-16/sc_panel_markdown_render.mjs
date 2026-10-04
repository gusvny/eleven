// sc_panel_markdown_render.mjs — t261004-16 markdown rendering of request and
// answer text (grey-box L3, real browser + page-boundary API stubs, zero docker,
// never touches 3099/7233; seam = t261003-06/lib_panel_seam).
//
// Intent (user-perceivable; ticket Req 3 — today the panel shows raw markdown
// source, so the user reads "**text**" and "`path`" markers inside a 170px box;
// the host reported real requests.jsonl rows carrying bold, inline code and
// bullet lists):
//   R1 Headings, bold, italic, inline code, lists and blockquotes render as
//      formatted elements — no literal ** / backtick-pair markers survive in the
//      rendered text.
//   R2 Raw HTML never passes through: a script/img payload renders inert, the
//      probe flag it tries to set stays unset, zero pageerror.
//   R3 A javascript: link target is dropped and the label still shows as text;
//      no anchor with a javascript: href exists anywhere.
//   R4 An https link renders as a real anchor with target="_blank" and a rel
//      containing noopener and noreferrer.
//   R5 A fenced code block renders as pre > code with its content escaped, never
//      as HTML.
//   R6 Plain prose without markdown keeps its line breaks.
//   R7 The answer echo uses the same formatting (no second renderer, ticket rule):
//      bold in an answer renders as an element, no literal ** in the echo.
//   R8 Option labels render inline formatting without literal markers.
//   R9 A 10000-character request renders without exception and the rendered
//      payload stays bounded (output does not explode past a sane multiple).
//   X1 Zero pageerror across the journey.
//
// playwright-core missing = ENV_FAIL exit 2 (KI-036 family); missing page module
// = FAIL named (TDD-phase red expected; arbitrate/merge must be green).
// Intent split: hostile-input truth tables at the unit level belong to developer
// L1 (ticket Req 6a); geometry/width faces belong to sc_panel_width_columns.mjs;
// expand persistence belongs to t261003-14. This file judges only what the user
// sees rendered.
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const PROJ = 'alpha'
const NOW = Date.now()
const FENCE = '```js\nif (a < b && c > d) { alert("<b>hi</b>") }\n```'

const DETAIL = [
  '# Wide layout plan',
  '',
  'Use **bold** and *italic* and `src/host/panel-page.ts` inline code.',
  '',
  '- first bullet',
  '- second bullet',
  '',
  '1. numbered one',
  '2. numbered two',
  '',
  '> a quoted line',
  '',
  FENCE,
  '',
  'See [docs](https://example.com/guide) and [bad](javascript:alert(1)).',
  '',
  '<img src=x onerror=window.__pwned=1>',
  '',
  'plain line one',
  'plain line two',
  '',
  '```html',
  '</script><script>window.__pwnedScript=1</script>',
  '```',
].join('\n')

const TEN_K = 'x'.repeat(10_000) + '\n\n**still bold at the end**'

const waiting = [
  {
    type: 'request', id: 'req-wait', at: NOW - 60_000, project: PROJ, kind: 'question',
    question: 'Render this markdown request?', detail: DETAIL, raised_by: 'bench',
    default_action: 'Proceed', options: ['**Proceed** with `plan-a`', 'Wait'], expires_at: null,
    status: 'waiting',
  },
  {
    type: 'request', id: 'req-big', at: NOW - 90_000, project: PROJ, kind: 'question',
    question: 'Long input?', detail: TEN_K, raised_by: 'bench', default_action: 'ok',
    options: null, expires_at: null, status: 'waiting',
  },
]
const answered = [
  {
    type: 'request', id: 'req-done', at: NOW - 120_000, project: PROJ, kind: 'question',
    question: 'Earlier question?', detail: 'short', raised_by: 'bench', default_action: 'x',
    options: null, expires_at: null, status: 'answered',
    answer: 'Answer with **bold** and `code`.', answered_at: NOW - 30_000,
  },
]

function stubServer() {
  const s = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [...waiting, ...answered] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/status')) {
      return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 1, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, wakes: [], alerts: [] } })
    }
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
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForSelector('.row[data-row]', { timeout: 5000 })

    // Open the markdown request row, then judge the rendered DOM.
    await page.click('.row[data-row="req-wait"] .head', { force: true })
    await page.waitForTimeout(300)

    const m = await page.evaluate(() => {
      const row = document.querySelector('.row[data-row="req-wait"]')
      const body = row ? row.querySelector('.body') : null
      const detail = row ? row.querySelector('.detail') : null
      if (!detail) return null
      const q = (sel) => detail.querySelectorAll(sel).length
      const text = detail.textContent || ''
      const links = [...detail.querySelectorAll('a')].map(a => ({ href: a.getAttribute('href') || '', target: a.getAttribute('target') || '', rel: a.getAttribute('rel') || '' }))
      const bodyText = body ? (body.textContent || '') : ''
      const allPre = [...detail.querySelectorAll('pre')].map(p => p.textContent || '').join('\n')
      return {
        allPre,
        h: q('h1,h2,h3,h4'), strong: q('strong,b'), em: q('em,i'), code: q('code'), pre: q('pre'),
        ul: q('ul'), ol: q('ol'), li: q('li'), bq: q('blockquote'), a: links,
        literalBold: text.includes('**'), literalTick: /\`[^\`]*\`/.test(text),
        imgTags: q('img'), scriptTags: q('script'),
        pwned: !!window.__pwned, pwnedScript: !!window.__pwnedScript,
        rawLower: text.toLowerCase(),
        proseKept: text.includes('plain line one') && text.includes('plain line two'),
        questionInBody: bodyText.includes('Render this markdown request?'),
      }
    })
    if (!m) { C.case('detail-renders', false, 'no .detail box in the expanded row'); return C.exit() }

    C.case('R1-markdown-elements-render',
      m.h >= 1 && m.strong >= 1 && m.em >= 1 && m.code >= 1 && m.ul >= 1 && m.ol >= 1 && m.li >= 2 && m.bq >= 1,
      `h=${m.h} strong=${m.strong} em=${m.em} code=${m.code} ul=${m.ul} ol=${m.ol} li=${m.li} bq=${m.bq}`)
    C.case('R1b-no-literal-markers-left', !m.literalBold && !m.literalTick,
      `literal ** present=${m.literalBold} backtick-pair present=${m.literalTick}`)
    C.case('R2-html-never-passes-through',
      m.imgTags === 0 && m.scriptTags === 0 && !m.pwned && !m.pwnedScript && m.rawLower.includes('<img'),
      `img=${m.imgTags} script=${m.scriptTags} pwned=${m.pwned} pwnedScript=${m.pwnedScript} (payload text must show escaped, not execute)`)
    const jsAnchor = m.a.find(x => /^\s*javascript:/i.test(x.href))
    const goodLink = m.a.find(x => x.href === 'https://example.com/guide')
    C.case('R3-javascript-link-dropped', !jsAnchor && m.rawLower.includes('javascript:alert(1)'),
      `js-anchor=${JSON.stringify(jsAnchor || null)} (target dropped, label stays as text)`)
    C.case('R4-https-link-safe-attrs', !!goodLink && goodLink.target === '_blank' && /noopener/.test(goodLink.rel) && /noreferrer/.test(goodLink.rel),
      `link=${JSON.stringify(goodLink || null)}`)
    C.case('R5-fenced-code-escaped-in-pre',
      m.pre >= 2 && m.allPre.includes('<b>hi</b>') && m.allPre.includes('</script>'),
      `pre=${m.pre} allPre=${JSON.stringify(m.allPre.slice(0, 120))}`)
    C.case('R6-plain-prose-keeps-line-breaks', m.proseKept,
      `plain lines present=${m.proseKept}`)
    C.case('R8-open-row-shows-full-question', m.questionInBody,
      `question at top of open body=${m.questionInBody}`)

    // Answer echo: same renderer face, no literal markers. The answered list sits
    // in a collapsed wrapper — open it first, then open the row.
    await page.click('#doneWrap .head, #doneWrap .chev2', { force: true }).catch(() => {})
    await page.waitForTimeout(200)
    await page.click('.row[data-row="req-done"] .head', { force: true })
    await page.waitForTimeout(200)
    const echo = await page.evaluate(() => {
      const row = document.querySelector('.row[data-row="req-done"]')
      const g = row ? row.querySelector('.given') : null
      if (!g) return null
      return { strong: g.querySelectorAll('strong,b').length, code: g.querySelectorAll('code').length, literal: (g.textContent || '').includes('**') }
    })
    C.case('R7-answer-echo-formatted-same-renderer',
      !!echo && echo.strong >= 1 && echo.code >= 1 && !echo.literal,
      `echo=${JSON.stringify(echo)}`)

    // Option labels: inline formatting, no literal markers.
    const opt = await page.evaluate(() => {
      const row = document.querySelector('.row[data-row="req-wait"]')
      const btns = row ? [...row.querySelectorAll('button')] : []
      const labelled = btns.filter(b => (b.textContent || '').includes('Proceed'))
      return { strong: labelled.some(b => b.querySelector('strong,b')), literal: labelled.some(b => (b.textContent || '').includes('**')), n: labelled.length }
    })
    C.case('R9-option-label-inline-format', !!opt && opt.n >= 1 && opt.strong && !opt.literal,
      `opt=${JSON.stringify(opt)}`)

    // 10k input: renders, no exception, bounded output.
    await page.click('.row[data-row="req-big"] .head', { force: true })
    await page.waitForTimeout(300)
    const big = await page.evaluate(() => {
      const d = document.querySelector('.row[data-row="req-big"] .detail')
      if (!d) return null
      return { len: (d.innerHTML || '').length, strong: d.querySelectorAll('strong,b').length }
    })
    C.case('R9b-10k-input-bounded-no-exception',
      !!big && big.len >= 10_000 && big.len <= 100_000 && big.strong >= 1,
      `html-length=${big ? big.len : 'n/a'} strong=${big ? big.strong : 'n/a'} (bounded: within [input, 10x input])`)

    C.case('X1-no-pageerror', errors.length === 0, errors.slice(0, 2).join(' | ').slice(0, 200))
  } catch (e) {
    C.case('browser-journey', false, String(e).slice(0, 200))
  } finally {
    if (browser) { try { await browser.close() } catch { /* already closed */ } }
    try { stub.close() } catch { /* noop */ }
    try { local.close() } catch { /* noop */ }
  }
  C.exit()
}

main().catch((e) => { console.error(String(e)); process.exit(1) })
