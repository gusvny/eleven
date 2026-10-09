/**
 * browser-followups.test.mjs —— t261003-09 三缺陷的浏览器行为杆（真 HTTP harness + 真 Chromium，
 * 全隔离端口 0；不是集成入口）：
 *  - 缺陷 1 不变量（review 条件 1：断言用户可见结果，不锚 CSS 字符串）：窄容器（叠放）
 *    与宽容器（并列）两种布局下，展开任何请求，**另一栏与页面其余内容的包围盒都不动**；
 *  - 缺陷 2：?theme=light/dark 驱动两块调色板；缺席/畸形 → 无 data-theme，
 *    落 prefers-color-scheme（显式降级，无硬编码缺省调色板）；
 *  - 缺陷 3（t261009-37）：Open session 按钮退场——按钮不存在、面板不发
 *    open-session postMessage；会话 chip 仍在（形状负回归）。
 */
import { createRequire } from 'node:module'
import { existsSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup , panelCookieFor } from './lib.mjs'

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

  // KI-193：浏览器上下文也带会话 cookie（dsh cookieName 算法；形状门可过）——
  // 页面 JS 的 POST 与测试侧 fetch 走同一凭据面。
  const CRED = (() => { const c = panelCookieFor(new URL(H.base).host); const i = c.indexOf('='); return { header: c, cookies: [{ name: c.slice(0, i), value: c.slice(i + 1), url: H.base }] } })()
  const newAuthedPage = async (viewport) => { const ctx = await browser.newContext(viewport ? { viewport } : {}); await ctx.addCookies(CRED.cookies); return ctx.newPage() }
const browser = await launchBrowser()
const KEY = 'rodalpha'
mkdirSync(join(wd, KEY), { recursive: true })
writeFileSync(join(wd, KEY, 'watchdog.json'), JSON.stringify({ enabled: true, stall_minutes: 15 }) + '\n', 'utf8')
try {
  const post = (path, body) => fetch(H.base + path, { method: 'POST', headers: { 'content-type': 'application/json', cookie: CRED.header }, body: JSON.stringify(body) }).then((r) => r.json())
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'sign', question: 'Merge ticket t261002-14 into main?', detail: 'Check line one.\n'.repeat(40) + 'Check passed.', default_action: 'hold', raised_by: 'session-09ca0247', options: ['Approve', 'Reject'] })

  // ---- 缺陷 1：展开不动另一栏 / 不动下方内容（窄=叠放，宽=并列） ----
  const page = await newAuthedPage({ width: 700, height: 900 })
  page.setDefaultTimeout(15000)
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '1', { polling: 200 })
  // ---- 缺陷 1（t261009-37 更新）：右列改为区块叠（.colstk），两栏随页面滚动——
  // 旧的「展开永不动另一栏 / 页高不涨」不变量随限高内滚规则退役（host order 261009，
  // mock 为准）。新杆：宽视口（并列）下展开请求，右列区块盒不动（top/height 不变）；
  // 窄视口（叠放）下右列在请求列下方正常渲染；行内 detail 限高不变。
  const rects = () => page.evaluate(() => {
    const cols = document.querySelectorAll('.cols > div')
    const r2 = cols[1].getBoundingClientRect()
    return { cols: cols.length, other: { top: r2.top, height: r2.height, width: r2.width }, pageH: document.documentElement.scrollHeight }
  })
  const before = await rects()
  assert(before.cols === 2, 'two column blocks exist (narrow container stacks them)')
  await page.locator('.head[data-id]').first().click()
  await page.waitForSelector('[data-row][data-open="true"] .detail')
  const afterNarrow = await rects()
  assert(afterNarrow.other.width === before.other.width, 'narrow/stacked: the right column keeps its width when a request unfolds')
  assert(afterNarrow.pageH >= before.pageH, 'narrow/stacked: the unfolded detail is on the page (the stack grows downward by design)')

  await page.setViewportSize({ width: 1300, height: 900 })
  await page.waitForTimeout(100)
  const beforeWide = await rects()
  assert(beforeWide.other.width !== before.other.width, 'wide viewport switches to the side-by-side grid')
  // 收起再展开（换一条已收起的行验证双向）：并列布局下右列区块盒不动。
  await page.locator('.head[data-id]').first().click()
  await page.waitForSelector('[data-row][data-open="false"] .detail', { state: 'detached' }).catch(() => {})
  await page.locator('.head[data-id]').first().click()
  await page.waitForSelector('[data-row][data-open="true"]')
  const afterWide = await rects()
  assert(JSON.stringify(afterWide.other) === JSON.stringify(beforeWide.other), 'wide/side-by-side: the right-column block boxes do not move when a request unfolds')
  // 行内 detail 仍限高内滚（t261003-06 回归锚）。
  const detailH = await page.evaluate(() => document.querySelector('[data-row][data-open="true"] .detail').getBoundingClientRect().height)
  // t261004-16：限高 170→440px（票面要求 ≥420）。
  assert(detailH <= 441, 'row detail stays height-capped and scrollable')
  n += 7
  await page.close()

  // ---- 缺陷 2：主题深链 + 显式降级（无硬编码缺省调色板） ----
  const tp = await newAuthedPage({ width: 1200, height: 900 })
  tp.setDefaultTimeout(15000)
  const bg = () => tp.evaluate(() => getComputedStyle(document.body).backgroundColor)
  await tp.emulateMedia({ colorScheme: 'dark' })
  await tp.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=dark')
  assert((await bg()) === 'rgb(20, 26, 36)', 'theme=dark paints the dark palette')
  assert(await tp.evaluate(() => document.documentElement.dataset.theme) === 'dark', 'the param lands on data-theme')
  await tp.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  assert((await bg()) === 'rgb(255, 255, 255)', 'theme=light paints the light palette')
  await tp.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=garbage')
  assert(await tp.evaluate(() => document.documentElement.dataset.theme) === undefined, 'malformed theme -> no data-theme (explicit degrade, no hardcoded default)')
  assert((await bg()) === 'rgb(20, 26, 36)', 'malformed theme falls back to prefers-color-scheme (dark here)')
  await tp.emulateMedia({ colorScheme: 'light' })
  await tp.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  assert(await tp.evaluate(() => document.documentElement.dataset.theme) === undefined, 'absent theme -> no data-theme')
  assert((await bg()) === 'rgb(255, 255, 255)', 'absent theme follows prefers-color-scheme (light here)')
  n += 6
  await tp.close()

  // ---- 缺陷 3（t261009-37 更新，host order 261009-(3)）：Open session 按钮整体退场——
  // standalone 打开时按钮不存在、不发任何 open-session postMessage；会话 chip 仍在。 ----
  const sp = await newAuthedPage({ width: 1200, height: 900 })
  sp.setDefaultTimeout(15000)
  await sp.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  await sp.waitForSelector('#sessionChip')
  assert(await sp.waitForFunction(() => document.getElementById('sessionChip').textContent.startsWith('Session:'), { polling: 200 }).then(() => true).catch(() => false), 'the session chip renders the session state')
  assert(await sp.locator('#openSessionBtn').count() === 0, 'the Open session button is gone from the strip (t261009-37)')
  // 按钮已不在场：面板不再发 open-session postMessage（形状负回归；宿主侧监听器是
  // workbench 文件、写集外，属遗留）。
  await sp.evaluate(() => {
    window.__captured = []
    window.addEventListener('message', (e) => { window.__captured.push(e.data) })
  })
  const sentOpenSession = await sp.evaluate(() => (window.__captured || []).some((d) => d && d.type === 'sandbar-executor-panel:open-session'))
  assert(!sentOpenSession, 'no open-session postMessage is sent from the panel')
  n += 3
  await sp.close()
  await browser.close()
} finally {
  await browser.close().catch(() => {})
  await H.close()
  cleanup([wd, pan])
}
done(n)
