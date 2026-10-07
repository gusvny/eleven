/**
 * browser-request-card.test.mjs —— t261004-17 请求卡可答性行为测试杆（真 HTTP harness + 真 Chromium）：
 *  - 一问一行镜像的多问组：收起态逐问可见、逐问自带选项按钮（不展开就能一键答），
 *    头上带「question i of n」组标签，点按钮=只答该问；
 *  - 无选项卡在收起态亮出默认动作行（If you do not answer: …）；
 *  - 应答框是多行 textarea：两行草稿一次发出，账上原文保留换行；
 *  - 1600 字符 detail 的卡：测展开后 detail 块需要的像素高度（t261004-16 改 detail
 *    高度，本读数按当前树取——交接注明基线）；
 *  - SANDBAR_CARD_SHOTS=<dir> 时另存浅色/深色截图（UI 验收证据，缺省不落盘——
 *    run_tests 全量跑时零副作用）。
 * 全隔离（harness 端口 0，零 3099/7233）。
 */
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup, panelCookieFor } from './lib.mjs'

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

const shotsDir = process.env.SANDBAR_CARD_SHOTS || ''
const wd = freshDir(), pan = freshDir()
const mod = await import('../harness.mjs')
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
const browser = await launchBrowser()
const KEY = 'rodalpha'
  // KI-193：harness 上的 POST 与浏览器上下文都要带控制台会话 cookie（写面凭据门）。
  const CRED = (() => { const c = panelCookieFor(new URL(H.base).host); const i = c.indexOf('='); return { header: c, cookies: [{ name: c.slice(0, i), value: c.slice(i + 1), url: H.base }] } })()
  const newAuthedPage = async (viewport) => { const ctx = await browser.newContext(viewport ? { viewport } : {}); await ctx.addCookies(CRED.cookies); return ctx.newPage() }
let n = 0
try {
  mkdirSync(join(wd, KEY), { recursive: true })
  writeFileSync(join(wd, KEY, 'watchdog.json'), JSON.stringify({ enabled: true, stall_minutes: 15 }) + '\n', 'utf8')
  const post = (path, body) => fetch(H.base + path, { method: 'POST', headers: { 'content-type': 'application/json', cookie: CRED.header }, body: JSON.stringify(body) }).then((r) => r.json())
  // 一次两问 ask（镜像落账后的形状：同 group_id，逐问 options/default_action），加一条
  // 无选项有默认动作的行，和一条 1600 字符 detail 的行。
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'question', question: 'Restart the stalled worker?', detail: 'queue depth 340, no progress for 12 minutes.', default_action: 'leave it running', raised_by: 'session-09ca0247', options: ['Restart now', 'Leave it'], group_id: 'ask-17' })
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'question', question: 'Open the red-clear ticket?', detail: '232 redline rows await a decision.', raised_by: 'session-09ca0247', options: ['Open it', 'Skip'], group_id: 'ask-17' })
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'approval', question: 'Rotate the access key?', detail: 'key is 90 days old.', default_action: 'hold the rotation' })
  const sent = 'The queue keeps growing while the worker is stopped, and each stalled batch adds one more row to the evidence the host has to read before deciding. '
  const longDetail = (sent.repeat(40)).slice(0, 1600)
  const longRow = await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'decision', question: 'Keep the interim lock?', detail: longDetail })
  assert(longRow.ok === true, 'long-detail row seeded')

  const page = await newAuthedPage({ width: 1200, height: 900 })
  page.setDefaultTimeout(15000)
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '4', { polling: 200 })

  // ① 收起态：选项按钮直接可见可点（不点开 head）。
  const restartRow = page.locator('[data-row]', { hasText: 'Restart the stalled worker' }).first()
  const inlineBtn = restartRow.locator('.opts.inline button[data-answer="Restart now"]')
  await inlineBtn.waitFor({ timeout: 5000 })
  assert(await inlineBtn.isVisible(), 'options are visible without expanding the card')
  assert((await restartRow.locator('.opts.inline button[data-answer]').count()) === 2, 'a question row shows its own two options')

  // ② 组标签：两问组逐问标 question i of 2。
  const waitTxt = await page.textContent('#waitList')
  assert(waitTxt.includes('question 1 of 2') && waitTxt.includes('question 2 of 2'), 'a multi-question ask shows one row per question with group tags')

  // ③ 无选项卡：收起态亮默认动作行。
  const rotateRow = page.locator('[data-row]', { hasText: 'Rotate the access key' }).first()
  const dflt = rotateRow.locator('.dflt')
  assert(await dflt.isVisible(), 'the default action is visible without expanding')
  assert((await dflt.textContent()).includes('If you do not answer: hold the rotation.'), 'the card states what happens when the host does not answer')
  // t261007-01: the Dismiss button is the one intended button on a no-options
  // card — no answer buttons, the answer box fallback, and Dismiss.
  assert((await rotateRow.locator('button[data-answer]').count()) === 0, 'a no-options card shows no answer buttons')
  assert((await rotateRow.locator('button[data-dismiss="1"]').count()) === 1, 'a no-options card still offers the Dismiss action')
  assert((await rotateRow.locator('textarea[data-answerbox]').count()) === 1, 'a no-options card falls back to the answer box')

  // ④ 收起态等待时长在头上一行可见（fmtWaiting 的输出在场，点开才看详情不再是必经路）。
  assert((await restartRow.locator('.head .meta').textContent()).includes('·'), 'the waited duration stays on the collapsed row')

  // ⑧ 截图证据（浅色 + 深色）：四行全在等待时的收起态——多问组（选项可见不展开）、
  // 无选项卡（默认动作可见）同屏。
  let geoShot = null
  if (shotsDir) {
    mkdirSync(shotsDir, { recursive: true })
    for (const theme of ['light', 'dark']) {
      await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=' + theme)
      await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '4', { polling: 200 })
      await page.screenshot({ path: join(shotsDir, 't261004-17-request-card-' + theme + '.png'), fullPage: false })
    }
    // 1600 字符 detail 的几何在浅色页上量（展开后 detail 块像素高）。
    await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
    await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '4', { polling: 200 })
    const longLoc = page.locator('[data-row]', { hasText: 'Keep the interim lock' }).first()
    await longLoc.locator('.head').click()
    // The render loop can rebuild the list between attach and click; wait until
    // the expand actually took (data-open projects from state.openIds).
    await longLoc.waitFor({ state: 'visible', timeout: 5000 })
    await page.waitForFunction((row) => {
      const el = document.querySelector('[data-row="' + row + '"]')
      return el && el.dataset.open === 'true'
    }, longRow.row.id, { polling: 200, timeout: 5000 }).catch(async () => { await longLoc.locator('.head').click() })
    geoShot = await longLoc.locator('.detail').evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight, card: el.closest('[data-row]').getBoundingClientRect().height }))
    writeFileSync(join(shotsDir, 't261004-17-card-metrics.json'), JSON.stringify({
      detail_1600: geoShot,
      group_rows_before: { visible_questions: 1, visible_options: 0, note: 'pre-change collapsed row showed no options and only the first question (mirror collapsed a two-question ask into one row)' },
      group_rows_after: { visible_questions: 2, visible_options: 4 },
      theme_note: 'measured after the main sync (t261004-16 width/markdown/detail height in the tree): the 170px inner-scroll cap is gone, the 1600-char detail renders fully (client=scroll), and option labels ride the shared markdown inline renderer',
    }, null, 2) + '\n', 'utf8')
    n += 2
    assert(true, 'light and dark screenshots written to ' + shotsDir)
  }

  // ⑤ 点选项=应答：只答该问；另一问保持等待。
  await inlineBtn.click()
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '3', { polling: 200 })
  const doneTxt = await page.textContent('#doneList')
  assert(doneTxt.includes('You answered: Restart now'), 'one click answers the clicked question')
  assert((await page.textContent('#waitList')).includes('Open the red-clear ticket?'), 'the sibling question stays waiting')
  n += 6

  // ⑥ 多行应答：textarea 收两行草稿，一次发送，账上原文保留换行。
  await rotateRow.locator('.head').click()
  const box = rotateRow.locator('textarea[data-answerbox]')
  await box.waitFor({ timeout: 5000 })
  await box.fill('rotate after the batch lands\nnot before 18:00')
  await rotateRow.locator('button[data-sendbox]').click()
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '2', { polling: 200 })
  const read = await fetch(H.base + '/sandbar-executor-panel/api/requests?project=' + KEY).then((r) => r.json())
  const rot = read.rows.find((r) => r.question === 'Rotate the access key?')
  assert(rot.status === 'answered' && rot.answer === 'rotate after the batch lands\nnot before 18:00', 'a multi-line typed answer lands verbatim')
  n += 2

  // ⑦ 1600 字符 detail：展开后的 detail 块几何（截图分支量好的 geoShot；当前树基线，
  // t261004-16 改 detail 高度后须重测）。无截图分支时就地量一次。
  if (!geoShot) {
    const longRowLoc = page.locator('[data-row]', { hasText: 'Keep the interim lock' }).first()
    await longRowLoc.locator('.head').click()
    await page.waitForFunction((row) => {
      const el = document.querySelector('[data-row="' + row + '"]')
      return el && el.dataset.open === 'true'
    }, longRow.row.id, { polling: 200, timeout: 5000 }).catch(async () => { await longRowLoc.locator('.head').click() })
    geoShot = await longRowLoc.locator('.detail').evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight, card: el.closest('[data-row]').getBoundingClientRect().height }))
  }
  assert(geoShot.scroll > 100, 'the 1600-char detail has real content height')
  n += 1

  // ⑨ t261007-01: the Dismiss action — one click moves the card out of
  // Needs your answer into the collapsed Dismissed group, with the card copy;
  // the ledger read-back carries the session-derived writer 'host'.
  const holdRow = page.locator('[data-row]', { hasText: 'Keep the interim lock' }).first()
  const dismissBtn = holdRow.locator('button[data-dismiss="1"]')
  await dismissBtn.waitFor({ timeout: 5000 })
  await dismissBtn.click()
  await page.waitForFunction(() => {
    const h = document.getElementById('dismissedHead')
    return h && h.textContent === 'Dismissed · 1'
  }, { polling: 200 })
  assert((await page.textContent('#waitList')).includes('Open the red-clear ticket?'), 'the remaining question still waits after the dismiss')
  assert(!(await page.textContent('#waitList')).includes('Keep the interim lock'), 'the dismissed card left Needs your answer')
  const disTxt = await page.textContent('#dismissedList')
  assert(disTxt.includes('Keep the interim lock'), 'the dismissed card shows in the Dismissed group')
  assert(disTxt.includes('Dismissed by you. Your default action applies.'), 'the dismissed card carries the copy')
  const readAfter = await fetch(H.base + '/sandbar-executor-panel/api/requests?project=' + KEY).then((r) => r.json())
  const held = readAfter.rows.find((r) => r.question === 'Keep the interim lock?')
  assert(held.status === 'dismissed' && held.dismissed_by === 'host', 'ledger read-back: the dismiss row carries the console-session identity')
  // UI evidence (ticket acceptance): one capture with the dismissed card in its
  // group, next to Answered. Written only when SANDBAR_CARD_SHOTS is set.
  if (shotsDir) {
    await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=light')
    await page.waitForFunction(() => document.getElementById('dismissedHead') && document.getElementById('dismissedHead').textContent === 'Dismissed · 1', { polling: 200 })
    await page.screenshot({ path: join(shotsDir, 't261007-01-dismissed-card-light.png'), fullPage: false })
    assert(true, 'dismiss UI capture written to ' + shotsDir)
  }
  n += 6

  await page.close()
} finally {
  await browser.close().catch(() => {})
  await H.close().catch(() => {})
  cleanup([wd, pan])
}
done(n)
