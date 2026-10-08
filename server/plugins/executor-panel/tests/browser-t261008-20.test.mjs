/**
 * t261008-20-browser.test.mjs —— host order 261008 浏览器行为测试（真 HTTP harness + 真 Chromium）：
 *  - tab strip 无 Ledger；入口 'Recent actions (view source event)' 打开 source-event 对话框；
 *  - 对话框渲染 status 返回的**全部** 6 行 fixture（5 正常 + 1 畸形 at），点名计数与 20 行窗口；
 *  - 畸形 at 排最后（t261004-14 最新在前规则在对话框同样成立）；空 wakes / 缺 st.wakes →
 *    声明空态文案，不造行、不抛；
 *  - Concurrent limit 更名、无 running 票列表、无 'set by '；对话框轮询刷新后仍开着；
 *  - Esc 与 Close 都能关，焦点回到入口按钮；
 *  - KI-055：Overview（浅/深）与开着的对话框（浅/深）截图落 .sandbar/screenshots/。
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
const STATUS_OK = { ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 3 }, ledger: { path: '/x/ledger.jsonl', unreadable: false, counts: { lines: 9, duplicates: 1, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, alerts: [], wakes: WAKES } }
const STATUS_NO_WAKES = { ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 3 }, ledger: { path: '/x/ledger.jsonl', unreadable: false, counts: { lines: 9, duplicates: 1, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, alerts: [] } }

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

  // ① tab strip 无 Ledger；入口文案逐字；concurrent 面更名、无列表、无审计短语。
  assert(await page.locator('label[data-tab="ledger"]').count() === 0, 'no Ledger tab in the strip')
  const btn = page.locator('#ledgerDlgBtn')
  assert(await btn.textContent() === 'Recent actions (view source event)', 'entry reads the host wording verbatim')
  const bodyText = await page.evaluate(() => document.body.innerText)
  assert(bodyText.includes('Concurrent limit'), 'block title reads Concurrent limit')
  assert(!bodyText.includes('Running tickets'), 'old title gone from the rendered page')
  assert(!bodyText.includes('set by '), "no 'set by ' audit stamp anywhere")
  assert(await page.locator('#concList').count() === 0, 'no running-ticket list container renders')
  n += 6

  // ② 打开对话框：6 行全渲染（N>3），点名计数与 20 行窗口；畸形 at 排最后。
  await btn.click()
  assert((await page.locator('#ledgerDlg').getAttribute('data-open')) === 'true', 'the entry opens the dialog')
  await page.waitForFunction(() => document.getElementById('ledgerEvents').children.length === 6, { polling: 200 })
  const dlgText = await page.locator('#ledgerDlg').innerText()
  { const cnt = await page.textContent('#ledgerWakeCount'); assert(cnt === '· 6', 'the dialog states the count (ledgerWakeCount = · 6)'); assert(/wakes[\s\S]*·\s*6/i.test(dlgText), 'the count sits beside the Wakes heading'); }
  assert(dlgText.includes('The watchdog status keeps the last 20 wakes.'), 'the dialog names the 20-row window')
  const lastRow = await page.locator('#ledgerEvents .act').last().textContent()
  assert(lastRow.includes('t260915-06'), 'the malformed-at row sorts last (newest-first rule keeps it last)')
  const firstRow = await page.locator('#ledgerEvents .act').first().textContent()
  assert(firstRow.includes('t260910-01'), 'newest well-formed row sorts first')
  assert(dlgText.includes('/x/ledger.jsonl'), 'the dialog carries the ledger file reference')
  n += 6

  // ③ 焦点进了 Close；Esc 关、焦点回入口；再开、Close 关。
  assert(await page.evaluate(() => document.activeElement && document.activeElement.id === 'ledgerDlgClose'), 'focus moved to the Close control on open')
  await page.keyboard.press('Escape')
  assert((await page.locator('#ledgerDlg').getAttribute('data-open')) === 'false', 'Esc closes the dialog')
  assert(await page.evaluate(() => document.activeElement && document.activeElement.id === 'ledgerDlgBtn'), 'focus returns to the opener after Esc')
  await btn.click()
  await page.click('#ledgerDlgClose')
  assert((await page.locator('#ledgerDlg').getAttribute('data-open')) === 'false', 'the Close control closes the dialog')
  n += 3

  // ④ 轮询刷新不改对话框开合（innerHTML 换行，焦点不动）。
  await btn.click()
  await page.waitForFunction(() => document.getElementById('ledgerDlg').getAttribute('data-open') === 'true')
  await page.waitForTimeout(1600) // 覆盖至少一次轮询
  assert((await page.locator('#ledgerDlg').getAttribute('data-open')) === 'true', 'the dialog stays open across a poll refresh')
  assert((await page.locator('#ledgerEvents .act').count()) === 6, 'rows re-rendered in place (still 6)')
  await page.keyboard.press('Escape')
  n += 2

  // ⑤ KI-055 截图：Overview（浅/深）+ 开着的对话框（浅/深）。
  await page.screenshot({ path: join(shotsDir, 't261008-20-overview-light.png') })
  await btn.click()
  await page.waitForFunction(() => document.getElementById('ledgerDlg').getAttribute('data-open') === 'true')
  await page.screenshot({ path: join(shotsDir, 't261008-20-dialog-light.png') })
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=dark')
  await page.waitForFunction(() => document.getElementById('ledgerEvents') && document.getElementById('ledgerEvents').children.length > 0, { polling: 200 })
  await page.screenshot({ path: join(shotsDir, 't261008-20-overview-dark.png') })
  await btn.click()
  await page.waitForFunction(() => document.getElementById('ledgerDlg').getAttribute('data-open') === 'true')
  await page.screenshot({ path: join(shotsDir, 't261008-20-dialog-dark.png') })
  n += 1

  // ⑥ 空态 / 缺字段：声明空态文案，不造行、不抛。
  statusPayload = { ok: true, result: { ...STATUS_NO_WAKES.result, wakes: [] } }
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => document.getElementById('ledgerEvents') && document.getElementById('ledgerEvents').textContent.includes('No wakes yet'), { polling: 200 })
  assert(true, 'empty wakes renders the declared empty copy')
  await page.click('#ledgerDlgBtn')
  assert((await page.locator('#ledgerDlg').getAttribute('data-open')) === 'true', 'the dialog opens on an empty record too')
  await page.keyboard.press('Escape')
  statusPayload = STATUS_NO_WAKES // 无 wakes 字段
  await page.waitForTimeout(1600)
  const t2 = await page.locator('#ledgerDlg').innerText().catch(() => '')
  await btn.click()
  const dlg2 = await page.locator('#ledgerDlg').innerText()
  assert(dlg2.includes('No wakes yet') && (await page.locator('#ledgerEvents .act').count()) === 1, 'missing st.wakes renders the empty copy, no throw, no fabricated rows')
  n += 2

  // ⑦ 非对象行（null 混在 wakes 里）：行渲染诚实面（unknown / —），整面不被清空、不抛
  // （t261003-13 H4b/H4c 回归——旧 cap:3 时代该行被截掉，uncap 后曾使整个面崩掉）。
  statusPayload = { ok: true, result: { ...STATUS_NO_WAKES.result, wakes: [{ at: BASE_AT - DAY, ticket: 't260916-07', dedupe_key: 'k7', mode: 'queue', accepted: true }, null, { at: 'garbage', ticket: 't260917-08', dedupe_key: 'k8', mode: 'queue', accepted: true }] } }
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => document.getElementById('ledgerWakeCount') && document.getElementById('ledgerWakeCount').textContent === '· 3', { polling: 200 })
  let dlg3 = ''
  try { await btn.click(); dlg3 = await page.locator('#ledgerDlg').innerText() } catch (e) { dlg3 = 'CLICK-FAIL ' + e.message }
  assert(!dlg3.startsWith('CLICK-FAIL'), 'a null row among wakes does not crash the face')
  assert((await page.locator('#ledgerEvents .act').count()) === 3, 'all three rows render (null included, none wipes the face)')
  assert(/unknown/i.test(dlg3), 'the non-object row renders the explicit unknown sentence (H4b)')
  assert(dlg3.includes('—'), 'the unparseable-at row renders the dash, not a wrong clock (H4c)')
  assert((await page.locator('#ledgerWakeCount').textContent()) === '· 3', 'the count span survives the malformed rows')
  await page.keyboard.press('Escape')
  n += 4
  await ctx.close()
} finally {
  await browser.close()
  await H.close().catch(() => {})
  cleanup([wd, pan])
}
console.log('done ' + n)
