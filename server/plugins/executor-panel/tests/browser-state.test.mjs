/**
 * browser-state.test.mjs —— t261003-14 UI 态跨轮询保持（真 HTTP harness + 真 Chromium）：
 *  - 展开的行跨任意次轮询保持展开；宿主收起后保持收起；
 *  - 长详情滚动位置跨轮询保持；
 *  - 自由文本草稿跨轮询保持（含收起再展开后仍在）；
 *  - 选项行点「Type an answer」后：草稿在、输入框在（revealed 态跨轮询保持）；
 *  - 发送成功才清草稿与 reveal；被拒的草稿原样保留；
 *  - 畸形输入（空 options / 缺 detail / null 字段）渲染与展开不抛错。
 * 轮询周期用 window.__panelTick 注入（不等真实 5s 墙钟，review #1）。全隔离（端口 0，零 3099/7233）。
 */
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup } from './lib.mjs'

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
const browser = await launchBrowser()
const KEY = 'rodalpha'
const LONG_DETAIL = Array.from({ length: 40 }, (_, i) => 'Line ' + (i + 1) + ' of the detail block for the scroll check.').join('\n')
try {
  const post = (path, body) => fetch(H.base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json())
  // 无选项（自由文本）+ 有选项（按钮/展开框）+ 畸形（空 options、缺 detail、null 字段）。
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'question', question: 'Do you have more instructions before the executor opens this ticket?', detail: LONG_DETAIL })
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'sign', question: 'Merge ticket t261003-14 into main?', detail: 'Check passed. Conflicts: none.', default_action: 'hold', options: ['Approve', 'Reject'] })
  // 畸形（options:null——API 拒绝空数组并要求不传、缺 detail、null 字段）。
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'question', question: 'Malformed shape probe', options: null, detail: null, default_action: null, raised_by: null })
  const idOf = (text) => page.$$eval('[data-row]', (rows, t) => rows.find((r) => r.textContent.includes(t))?.dataset.row, text)

  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  page.setDefaultTimeout(15000)
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '3', { polling: 200 })
  const tick = () => page.evaluate(() => window.__panelTick())
  const rowBy = (text) => page.locator('[data-row]', { hasText: text }).first()

  // ① 展开 → 两次注入轮询 → 仍展开；收起 → 再轮询 → 仍收起（主症状回归）。
  const qRow = rowBy('Do you have more instructions')
  await qRow.locator('.head').click()
  assert((await qRow.getAttribute('data-open')) === 'true', 'click expands the row')
  await tick(); await tick()
  assert((await qRow.getAttribute('data-open')) === 'true', 'row stays expanded across two poll cycles')
  await qRow.locator('.head').click()
  await tick()
  assert((await qRow.getAttribute('data-open')) === 'false', 'a host-collapsed row stays collapsed across a poll cycle')
  await qRow.locator('.head').click()
  n += 3

  // ② 长详情滚动位置跨轮询保持。
  const qId = await idOf('Do you have more instructions')
  await page.$eval('[data-row="' + qId + '"] .detail', (d) => { d.scrollTop = 300 })
  const before = await page.$eval('[data-row="' + qId + '"] .detail', (d) => d.scrollTop)
  await tick()
  const after = await page.$eval('[data-row="' + qId + '"] .detail', (d) => d.scrollTop)
  assert(before === 300 && after === 300, 'detail scroll position survives a poll cycle')
  n += 1

  // ③ 自由文本草稿跨轮询保持；收起再展开后仍在；焦点光标回到输入框。
  const input = qRow.locator('input[data-answerbox]')
  await input.click()
  await input.type('half typed answer')
  await tick()
  assert((await input.inputValue()) === 'half typed answer', 'a half-typed draft survives a poll cycle')
  assert(await page.evaluate(() => document.activeElement && document.activeElement.tagName === 'INPUT'), 'focus returns to the answer input after a poll cycle')
  await qRow.locator('.head').click()
  await tick()
  await qRow.locator('.head').click()
  assert((await input.inputValue()) === 'half typed answer', 'the draft survives a collapse and re-expand')
  n += 3

  // ④ 选项行：点「Type an answer」→ 输入框；草稿跨轮询保持（review #2 全路径）。
  const mRow = rowBy('Merge ticket t261003-14')
  await mRow.locator('.head').click()
  await mRow.locator('button[data-reveal]').click()
  const rInput = mRow.locator('.answer input')
  await rInput.type('typed in revealed box')
  await tick()
  assert((await mRow.locator('.answer input').count()) === 1, 'a revealed answer box stays a box across a poll cycle')
  assert((await rInput.inputValue()) === 'typed in revealed box', 'the revealed-box draft survives a poll cycle')
  n += 2

  // ⑤ 发送成功才清草稿与 reveal（review #3）：被拒草稿保留。
  await page.route('**/sandbar-executor-panel/api/requests/answer', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'the request already expired' }) }))
  await rInput.press('Enter')
  await tick()
  assert((await mRow.locator('.answer input').inputValue()) === 'typed in revealed box', 'a rejected answer keeps its draft in the box')
  await page.unroute('**/sandbar-executor-panel/api/requests/answer')
  // 真发送（假路由已撤）：草稿清空，行进 Answered 且仍可展开回看。
  await rInput.press('Enter')
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '2', { polling: 200 })
  assert((await rowBy('Merge ticket t261003-14').locator('.answer input').count()) === 0, 'a successful send clears the answer box')
  await page.locator('#doneHeadBtn').click()
  assert((await page.textContent('#doneList')).includes('You answered: typed in revealed box'), 'the sent answer shows in the Answered section')
  n += 3

  // ⑥ 已答行：展开态随 id 继承进 Answered 区（等待时就展开过），跨轮询保持；收起后同样保持。
  const doneRow = rowBy('Merge ticket t261003-14')
  assert((await doneRow.getAttribute('data-open')) === 'true', 'an answered row keeps the expand state it had while waiting')
  await tick(); await tick()
  assert((await doneRow.getAttribute('data-open')) === 'true', 'an expanded answered row stays expanded across poll cycles')
  await doneRow.locator('.head').click()
  await tick()
  assert((await doneRow.getAttribute('data-open')) === 'false', 'a collapsed answered row stays collapsed across poll cycles')
  n += 3

  // ⑦ 畸形输入：空 options / null 字段行渲染、展开、给输入框，不抛错（消费外部输入钩子）。
  const pageErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e && e.message)))
  const badRow = rowBy('Malformed shape probe')
  await badRow.locator('.head').click()
  await tick()
  assert((await badRow.getAttribute('data-open')) === 'true', 'a malformed-shape row expands without throwing')
  assert((await badRow.locator('input[data-answerbox]').count()) === 1, 'a malformed row with empty options falls back to the text box')
  assert(pageErrors.length === 0, 'no page errors across all poll cycles and rows: ' + pageErrors.join(' | '))
  n += 3

  await page.close()
} finally {
  await browser.close()
  await H.close()
  cleanup([wd, pan])
}
done(n)
