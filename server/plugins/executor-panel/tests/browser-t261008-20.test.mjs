/**
 * t261008-20-browser.test.mjs —— host order 261008 浏览器行为测试（真 HTTP harness + 真 Chromium）；
 * t261009-37 更新（host order 261009）：source-event 对话框退场，Ledger 面改居 Overview
 * 右列 Events 区块（内联，无需任何点击）：
 *  - tab strip 无 Ledger、无入口链接；Events 区块直接可见并渲染 status 返回的**全部**
 *    6 行 fixture（5 正常 + 1 畸形 at），头行点名计数，文案点名 20 行窗口；
 *  - 畸形 at 排最后（t261004-14 最新在前规则同样成立）；空 wakes / 缺 st.wakes →
 *    声明空态文案，不造行、不抛；
 *  - Concurrent limit 更名、无 running 票列表、无 'set by '；轮询刷新后行数不变；
 *  - 旧对话框 D5（焦点/Esc/Close）随其模式整体退役（host order 261009-(2)）——不是
 *    弱化断言，是断言对象消失；
 *  - KI-055：Overview（浅/深）截图落 .sandbar/screenshots/。
 * status 端点经 page.route 打桩（fixture 在本文件内固定——不依赖真 watchdog，无外部源）。
 * 全隔离（harness 端口 0，零 3099/7233）。
 */
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup, panelCookieFor } from './lib.mjs'

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

const wd = freshDir(), pan = freshDir()
const mod = await import('../harness.mjs')
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })

const CRED = (() => { const c = panelCookieFor(new URL(H.base).host); const i = c.indexOf('='); return { header: c, cookies: [{ name: c.slice(i ? 0 : 0), value: c.slice(i + 1), url: H.base }] } })()

// 固定 fixture（票面要求 N>3 且含畸形输入面）：5 行正常 + 1 行 at 为字符串（排最后）。
const DAY = 86_400_000
const BASE_AT = 1_700_000_000_000
const WAKES = [
  { at: BASE_AT - 1 * DAY, ticket: 't260910-01', dedupe_key: 'k1', mode: 'queue', accepted: true },
  { at: BASE_AT - 2 * DAY, ticket: 't260911-02', dedupe_key: 'k2', mode: 'queue', accepted: false },
  { at: BASE_AT - 3 * DAY, ticket: 't260912-03', dedupe_key: 'k3', mode: 'direct', accepted: true },
  { at: BASE_AT - 4 * DAY, ticket: 't260913-04', dedupe_key: 'k4', mode: null, accepted: null },
  { at: BASE_AT - 5 * DAY, ticket: 't260914-05', dedupe_key: 'k5', mode: 'queue', accepted: true },
  { at: 'not-a-number', ticket: 't260915-06', dedupe_key: 'k6', mode: 'queue', accepted: true },
]
const STATUS_OK = { ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 3 }, ledger: { path: '/x/ledger.jsonl', unreadable: false, rows_seen: 12480, dupes_skipped: 3, malformed_rows: 0, gaps_seen: 0 }, liveness: { executor: { alive: true } }, alerts: [], wakes: WAKES } }
const STATUS_NO_WAKES = { ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 3 }, ledger: { path: '/x/ledger.jsonl', unreadable: false, rows_seen: 12480, dupes_skipped: 3, malformed_rows: 0, gaps_seen: 0 }, liveness: { executor: { alive: true } }, alerts: [] } }

const browser = await launchBrowser()
const KEY = 'rodbeta'
mkdirSync(join(wd, KEY), { recursive: true })
writeFileSync(join(wd, KEY, 'watchdog.json'), JSON.stringify({ enabled: true, stall_minutes: 15 }) + '\n', 'utf8')

const shotsDir = join(import.meta.dirname, '../../../../.sandbar/screenshots')
mkdirSync(shotsDir, { recursive: true })

try {
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
  await ctx.addCookies([{ name: CRED.header.slice(0, CRED.header.indexOf('=')), value: CRED.header.slice(CRED.header.indexOf('=') + 1), url: H.base }])
  const page = await ctx.newPage()
  page.setDefaultTimeout(15000)
  let statusPayload = STATUS_OK
  await page.route('**/sandbar-watchdog/api/status*', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(statusPayload) }))
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  await page.waitForFunction(() => document.getElementById('ledgerEvents') && document.getElementById('ledgerEvents').children.length > 0, { polling: 200 })

  // ① tab strip 无 Ledger；对话框入口与对话框整体退场；concurrent 面更名、无列表、无审计短语。
  assert(await page.locator('label[data-tab="ledger"]').count() === 0, 'no Ledger tab in the strip')
  assert(await page.locator('#ledgerDlgBtn').count() === 0, 'the lone source-event entry link is gone (t261009-37)')
  assert(await page.locator('#ledgerDlg').count() === 0, 'the source-event dialog is gone (t261009-37)')
  const bodyText = await page.evaluate(() => document.body.innerText)
  // t261009-37: the block title now sits in a .sect header (CSS uppercases it), so
  // the rendered-text check is case-insensitive on purpose.
  assert(/concurrent limit/i.test(bodyText), 'block title reads Concurrent limit')
  assert(!bodyText.includes('Running tickets'), 'old title gone from the rendered page')
  assert(!bodyText.includes('set by '), "no 'set by ' audit stamp anywhere")
  assert(await page.locator('#concList').count() === 0, 'no running-ticket list container renders')
  n += 6

  // ② Events 区块内联可见（无任何点击）：6 行全渲染（N>3），头行计数 + 20 行窗口；畸形 at 排最后。
  assert(await page.locator('#ledgerEvents').isVisible(), 'the events block is visible on the Overview without any entry click')
  await page.waitForFunction(() => document.getElementById('ledgerEvents').children.length === 6, { polling: 200 })
  { const cnt = await page.textContent('#wakeCount'); assert(cnt === '6', 'the Events header states the count (wakeCount = 6)'); }
  const evText = await page.locator('#ledgerEvents').innerText()
  assert((await page.evaluate(() => document.getElementById('ledgerEvents').closest('.bbd').innerText)).includes('The watchdog status keeps the last 20 wakes.'), 'the block names the 20-row window')
  const lastRow = await page.locator('#ledgerEvents .act').last().textContent()
  assert(lastRow.includes('t260915-06'), 'the malformed-at row sorts last (newest-first rule keeps it last)')
  const firstRow = await page.locator('#ledgerEvents .act').first().textContent()
  assert(firstRow.includes('t260910-01'), 'newest well-formed row sorts first')
  { const f = await page.textContent('#ledgerFile'); assert(f === '/x/ledger.jsonl', 'the Events header carries the ledger path'); assert(await page.getAttribute('#ledgerFile', 'title') === '/x/ledger.jsonl', 'the full path travels on the title (hover face)'); }
  { const h = await page.textContent('#ledgerHealth'); assert(/12480 rows/.test(h) && /bad rows/.test(h) && /gaps/.test(h), 'the health facts render on one line: ' + h.trim()); }
  n += 6

  // ③ （D5 已退役，见文件头注释——对话框模式整体被 host order 261009-(2) 替换。）

  // ④ 轮询刷新不改内联区块（innerHTML 换行，行数不变）。
  await page.waitForTimeout(1600) // 覆盖至少一次轮询
  assert((await page.locator('#ledgerEvents .act').count()) === 6, 'rows re-rendered in place (still 6)')
  n += 1

  // ⑤ KI-055 截图：Overview（浅/深）。
  await page.screenshot({ path: join(shotsDir, 't261009-37-overview-light.png') })
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=dark')
  await page.waitForFunction(() => document.getElementById('ledgerEvents') && document.getElementById('ledgerEvents').children.length > 0, { polling: 200 })
  await page.screenshot({ path: join(shotsDir, 't261009-37-overview-dark.png') })
  n += 1

  // ⑥ 空态 / 缺字段：声明空态文案，不造行、不抛。
  statusPayload = { ok: true, result: { ...STATUS_NO_WAKES.result, wakes: [] } }
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => document.getElementById('ledgerEvents') && document.getElementById('ledgerEvents').textContent.includes('No wakes yet'), { polling: 200 })
  assert(await page.locator('#ledgerEvents').isVisible(), 'the empty face is inline (visible without a click)')
  assert((await page.textContent('#wakeCount')) === '0', 'the empty face states the zero count')
  statusPayload = STATUS_NO_WAKES // 无 wakes 字段
  await page.waitForTimeout(1600)
  assert((await page.textContent('#wakeCount')) === '0', 'missing st.wakes renders the empty copy, no throw, no fabricated rows')
  n += 2

  // ⑦ 非对象行（null 混在 wakes 里）：行渲染诚实面（unknown / —），整面不被清空、不抛
  // （t261003-13 H4b/H4c 回归——旧 cap:3 时代该行被截掉，uncap 后曾使整个面崩掉）。
  statusPayload = { ok: true, result: { ...STATUS_NO_WAKES.result, wakes: [{ at: BASE_AT - DAY, ticket: 't260916-07', dedupe_key: 'k7', mode: 'queue', accepted: true }, null, { at: 'garbage', ticket: 't260917-08', dedupe_key: 'k8', mode: 'queue', accepted: true }] } }
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => document.getElementById('wakeCount') && document.getElementById('wakeCount').textContent === '3', { polling: 200 })
  const ev3 = await page.locator('#ledgerEvents').innerText()
  assert((await page.locator('#ledgerEvents .act').count()) === 3, 'all three rows render (null included, none wipes the face)')
  assert(/unknown/i.test(ev3), 'the non-object row renders the explicit unknown sentence (H4b)')
  assert(ev3.includes('—'), 'the unparseable-at row renders the dash, not a wrong clock (H4c)')
  assert((await page.textContent('#wakeCount')) === '3', 'the count span survives the malformed rows')
  n += 4
  await ctx.close()
} finally {
  await browser.close()
  await H.close().catch(() => {})
  cleanup([wd, pan])
}
console.log('done ' + n)
