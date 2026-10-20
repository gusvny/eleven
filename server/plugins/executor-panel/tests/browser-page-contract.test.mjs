/**
 * browser-page-contract.test.mjs —— t261004-03：场景 sc_executor_panel_page_redesign
 * 五个假红断言的处置锁定（真 Chromium + 桩缝，零 docker，不触 3099/7233）。
 *
 * 背景：该场景首挂时 playwright 浏览器缺席（ENV_FAIL 假红），浏览器装好后真跑暴露
 * 5 FAIL。诊断结论：面板页无缺陷，五个全是场景侧锚/桩形漂移——
 *   桩形  行形状对齐 requests.ts RequestView（status/at）；status={ok,result} 信封、
 *         路径 /sandbar-watchdog/api/status；actions=/api/actions（页面真拉的面）。
 *   L1    负形收窄 #paneOv（Settings 夜间策略 <select> 是合法控件）。
 *   L2    两栏锚 .cols > div；断点锚 @container max-width:7xx（t261003-09 缺陷 1 定稿）。
 *   L4b   兜底锚=兜底控件本体（折叠行体 display:none 不进 innerText）。
 *   L5    锚 #doneHead2 textContent + data-open（.sect uppercase 使 innerText 随版本漂）。
 *   X1    两条 404 同源（桩形）；宿主 node.ts 是否漏注册 /api/actions 属 t261003-10，
 *         本测试不经宿主路由面，不在此重复修。
 * 本文件把这套修正锚钉进 UT 面，防再次漂移。含畸形输入用例（缺 status/kind 的桩行）。
 */
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { assert, done } from './lib.mjs'
import { PANEL_HTML } from '../src/host/panel-page.ts'

let n = 0
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

const PROJ = 'contractalpha'
const NOW = Date.now()
/** 桩行：形状=requests.ts RequestView（页面分栏消费的真读出视图）。 */
function stubRows() {
  return [
    { type: 'request', id: 'rq-1', at: NOW - 120_000, project: PROJ, kind: 'question', question: 'Which ticket does the executor verify first?', detail: 'Pick the first one.', raised_by: 'bench:plan', default_action: 'verify t1', expires_at: null, status: 'waiting' },
    { type: 'request', id: 'rq-2', at: NOW - 60_000, project: PROJ, kind: 'decision', question: 'How should the executor proceed?', detail: 'two viable paths', raised_by: 'bench', default_action: 'Open a new ticket', options: ['Open a new ticket', 'Extend the current ticket'], expires_at: null, status: 'waiting' },
    { type: 'request', id: 'rq-0', at: NOW - 3_600_000, project: PROJ, kind: 'question', question: 'Old question?', detail: 'done', raised_by: 'bench', default_action: 'x', expires_at: null, status: 'answered', answer: 'Open a new ticket' },
  ]
}

/** 起桩 + 起页：返回 { page, errors, close() }。rows=null → /api/requests 返畸形行。 */
async function openPage(rowsOverride) {
  const rows = rowsOverride !== undefined ? rowsOverride : stubRows()
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json(rows === null ? { rows: [] } : { rows })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: 'Permissions: 4 of 6' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [{ at: NOW, action: 'Sign', ticket: 't1', result: 'ok', permission: 'merge' }], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/bridge/status')) return json({ ok: true, mounted: true, counters: { mirrored: 2 }, last_events: [{ at: NOW, kind: 'mirrored', detail: '' }], at: NOW })
    if (u.pathname.endsWith('/api/status')) return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } } })
    // t261019-43: the overview also pulls the concurrency face on load (twice:
    // render + limit row). Without this stub the X1 zero-console-error check saw
    // two 404s from stub drift, not from the page (probe: on a plain load these
    // are the only two 404 paths).
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, declared: true, limit: 2, running: 0, waiting: 0 })
    res.writeHead(404); res.end('{}')
  })
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(PANEL_HTML) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const browser = await launchBrowser()
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', (e) => errors.push('pageerror: ' + e))
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()) })
  await page.route('**/api/**', (route) =>
    route.continue({ url: 'http://127.0.0.1:' + stub.address().port + new URL(route.request().url()).pathname }))
  await page.goto('http://127.0.0.1:' + local.address().port + '/?project=' + PROJ)
  // 等待徽标=期望等待数（等待桩行数；「· 0」会先到——分栏真源是请求账拉取完成）。
  const want = String(rows.filter(r => r && r.status !== 'answered').length)
  await page.waitForFunction((w) => { const b = document.getElementById('reqBadge'); return b && b.textContent === w }, want, { polling: 200, timeout: 8000 })
  return {
    page, errors,
    async close() {
      await browser.close()
      await new Promise(r => local.close(r))
      await new Promise(r => stub.close(r))
    },
  }
}

// ---- ① 正形桩：五个修正锚 + 零报错 ----
{
  const { page, errors, close } = await openPage()
  try {
    // L1：Overview 面无选择器三件套/无 select/无轮询行（负形收窄到 #paneOv）。
    const ovNeg = await page.evaluate(() => {
      const pane = document.getElementById('paneOv')
      const els = [...pane.querySelectorAll('input[type=text],input:not([type]),select,button')]
      return { joined: els.map(e => (e.placeholder || e.value || e.textContent || '').trim()).join('|'), selects: pane.querySelectorAll('select').length }
    })
    n++
    assert(!/load/i.test(ovNeg.joined) && ovNeg.selects === 0, 'L1 overview pane has no picker controls and no select')
    n++
    assert(!/polling/i.test(await page.evaluate(() => document.body.innerText)), 'L1 no polling status line anywhere')
    // Settings 夜间策略下拉仍在（它合法，只是不属于 Overview 负形）。
    n++
    assert(await page.$$eval('#paneSet select', s => s.length) === 1, 'settings night-policy select remains (legal, out of L1 scope)')

    // L2：两栏（.cols > div）+ 容器查询断点（按容器宽折叠，t261003-09 缺陷 1 定稿）。
    const twoCol = await page.evaluate(() => {
      const css = [...document.styleSheets].flatMap(s => { try { return [...s.cssRules].map(r => r.cssText) } catch { return [] } }).join('\n')
      return { cols: document.querySelectorAll('.cols > div').length, mq: /@(container|media)[^{]*max-width:\s*7\d\dpx/.test(css) }
    })
    n += 2
    assert(twoCol.cols >= 2, 'L2 two overview columns via .cols > div')
    assert(twoCol.mq, 'L2 breakpoint is a container/media query at ~760px')

    // L4b：兜底控件在场（无选项行的输入框 + 有选项行的 reveal 按钮；均在折叠行体内）。
    n++
    assert(await page.$$eval('#paneOv textarea[data-answerbox][placeholder="Type an answer"]', e => e.length) === 1, 'L4b free-text fallback input present in collapsed row')
    n++
    assert(await page.$$eval('#paneOv button[data-reveal]', b => b.length) === 1, 'L4b reveal button present on the options row')

    // L5：answered 行进 Answered 区（桩形 status:'answered' 驱动），默认收起。
    const doneHead = (await page.textContent('#doneHead2')) || ''
    n += 2
    assert(/answered\s*·\s*1/i.test(doneHead), 'L5 answered row splits into the Answered section by status; head=' + JSON.stringify(doneHead))
    assert((await page.getAttribute('#doneWrap', 'data-open')) === 'false', 'L5 Answered section starts collapsed')
    n++
    assert((await page.textContent('#reqBadge')) === '2', 'badge counts waiting only (2), answered excluded')

    // X1：修正桩形后零 pageerror / 零 console error（两条 404 均为旧桩形假象）。
    n++
    assert(errors.length === 0, 'X1 zero page/console errors with contract-shaped stubs; got: ' + errors.join(' | ').slice(0, 200))
  } finally { await close() }
}

// ---- ② 畸形输入：桩行缺 status/kind/project —— 页面不炸、不当 answered 呈现 ----
{
  const { page, errors, close } = await openPage([
    { type: 'request', id: 'bad-1', at: NOW - 5_000, question: 'Row with no status or kind?' },
    { type: 'request', id: 'ok-1', at: NOW - 4_000, project: PROJ, kind: 'question', question: 'Well-formed row?', detail: '', raised_by: '', default_action: '', expires_at: null, status: 'waiting' },
  ])
  try {
    const badge = await page.textContent('#reqBadge')
    n += 3
    assert(badge === '2', 'malformed row still surfaces as waiting (never dropped, never answered) — badge=' + badge)
    assert(/answered\s*·\s*0/i.test((await page.textContent('#doneHead2')) || ''), 'malformed row is not presented as answered')
    assert(errors.filter(e => e.startsWith('pageerror')).length === 0, 'no pageerror on malformed fixture rows')
  } finally { await close() }
}

done(n)
