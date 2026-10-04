/**
 * browser-redesign.test.mjs —— t261003-06 改版行为浏览器测试杆（真 HTTP harness + 真 Chromium）：
 *  - 页面顶部无项目选择器/Load/轮询行；五个页签真实可切；
 *  - 选项请求渲染成按钮（不让人打字），点按钮=应答，行进 Answered 折叠区；
 *  - 无选项请求给输入框；条目收起一行、点开展开（detail/控件/trace 可见）；
 *  - Overview 徽标 = 等待数；Grants 页签开关/会话输入/Save 往返保留会话点名（缺陷一 UI 面）；
 *  - Overview 电源开关=Grants 总开关同一状态：关掉后 grants 清空、点名保留、watchdog.json 仍 enabled:true（C3）。
 * 全隔离（harness 端口 0，零 3099/7233）。
 */
import { createRequire } from 'node:module'
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
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
const grantsFile = join(wd, KEY, 'executor-grants.json')
const watchdogFile = join(wd, KEY, 'watchdog.json')
try {
  // 种子：守望者声明 enabled:true；一条带选项的请求 + 一条无选项的请求（走真 append API）。
  mkdirSync(join(wd, KEY), { recursive: true })
  writeFileSync(watchdogFile, JSON.stringify({ enabled: true, stall_minutes: 15 }) + '\n', 'utf8')
  const post = (path, body) => fetch(H.base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json())
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'sign', question: 'Merge ticket t261002-14 into main?', detail: 'Check passed. Conflicts: none.', default_action: 'hold', raised_by: 'session-09ca0247', options: ['Approve', 'Reject'] })
  await post('/sandbar-executor-panel/api/requests', { project: KEY, kind: 'question', question: 'Do you have more instructions?', detail: 'The executor waits for your answer.' })

  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  page.setDefaultTimeout(15000)
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)

  // ① 选择器不存在、无项目横幅不显示、项目 chip 在场。
  assert(await page.locator('#project').count() === 0, 'no project dropdown in the served page')
  assert(await page.locator('#freeProject').count() === 0, 'no free-key box in the served page')
  assert(await page.locator('#go').count() === 0, 'no Load button in the served page')
  assert(await page.locator('#pollNote').count() === 0, 'no polling status line in the served page')
  assert(await page.textContent('#projChip') === KEY, 'project chip shows the deep-linked project')
  assert(!(await page.locator('#noProject').isVisible()), 'no-project banner hidden when a project is present')

  // ② 等待区：两条请求折叠成一行；徽标=2；选项行展开后是按钮不是输入框。
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '2', { polling: 200 })
  n += 4
  assert((await page.textContent('#waitHead')).includes('· 2'), 'waiting heading counts 2')
  const mergeRow = page.locator('[data-row]', { hasText: 'Merge ticket t261002-14' }).first()
  await mergeRow.locator('.head').click()
  await page.waitForSelector('[data-row] .opts button[data-answer]', { timeout: 5000 })
  assert(await mergeRow.locator('.answer textarea').count() === 0, 'option request shows buttons, not a text box')
  assert(await mergeRow.locator('.trace').textContent().then((t) => t.includes('Request id:') && t.includes('Raised by session session-09ca0247') && t.includes('Default action: hold')), 'trace line carries raised-by / id / default action')
  // 无选项行：展开后是输入框。
  const qRow = page.locator('[data-row]', { hasText: 'Do you have more instructions' }).first()
  await qRow.locator('.head').click()
  await page.waitForSelector('[data-row] .answer textarea', { timeout: 5000 })
  assert(await qRow.locator('.opts').count() === 0, 'free-text request shows an answer box, not buttons')
  n += 3

  // ③ 点选项按钮=应答：行进 Answered 折叠区，徽标回落。
  await mergeRow.locator('button[data-answer="Approve"]').click()
  await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '1', { polling: 200 })
  assert((await page.textContent('#doneHead2')).includes('Answered · 1'), 'answered row moved to the Answered section')
  const doneWrap = page.locator('#doneWrap')
  assert((await doneWrap.getAttribute('data-open')) === 'false', 'Answered section starts collapsed')
  await page.locator('#doneHeadBtn').click()
  assert((await doneWrap.getAttribute('data-open')) === 'true', 'Answered section can be reopened')
  assert((await page.textContent('#doneList')).includes('You answered: Approve'), 'the answer text is kept and shown')
  n += 3

  // ④ Grants 页签：会话输入 + Save 往返保留点名（缺陷一 UI 面）。
  await page.locator('label[for="t-grants"]').click()
  await page.waitForSelector('#grantsSave')
  await page.fill('#grantSession', 'session-09ca0247')
  await page.locator('.sw.grant[data-op="sign"]').click()
  await page.locator('.sw.grant[data-op="rerun"]').click()
  await page.click('#grantsSave')
  await page.waitForFunction(() => { const t = document.getElementById('grantsSaveOut'); return t && t.textContent.includes('Saved') }, { polling: 200 })
  let decl = JSON.parse(readFileSync(grantsFile, 'utf8'))
  assert(decl.executor_sessions?.[0] === 'session-09ca0247', 'UI save writes the session naming')
  assert(decl.grants.sign === true && decl.grants.rerun === true, 'UI save writes the ticked permissions')
  // 再保存一次（不带会话输入变化）→ 点名仍在（缺陷一回归）。
  await page.locator('.sw.grant[data-op="cleanup"]').click()
  await page.click('#grantsSave')
  await page.waitForFunction(() => { const t = document.getElementById('grantsSaveOut'); return t && t.textContent.includes('Saved') }, { polling: 200 })
  decl = JSON.parse(readFileSync(grantsFile, 'utf8'))
  assert(decl.executor_sessions?.[0] === 'session-09ca0247', 'a later UI save keeps the session naming')
  await page.waitForFunction(() => document.getElementById('grantsReadout') && document.getElementById('grantsReadout').textContent.includes('3 of 6'), { polling: 200 })
  assert((await page.textContent('#grantsReadout')).includes('3 of 6 permissions are granted'), 'readout sentence names 3 of 6')
  assert((await page.textContent('#grantChip')).includes('3 of 6'), 'Overview permission chip mirrors the grants state')
  n += 3

  // ⑤ 电源开关（Overview）= 总开关同一状态：关掉 → grants 清空、点名保留、watchdog 仍 enabled:true。
  await page.locator('label[for="t-overview"]').click()
  await page.waitForSelector('#powerBtn')
  await page.click('#powerBtn')
  await page.waitForFunction(() => document.getElementById('powerBtn') && document.getElementById('powerBtn').textContent.includes('Enable executor'), { polling: 200 })
  decl = JSON.parse(readFileSync(grantsFile, 'utf8'))
  assert(Object.keys(decl.grants ?? {}).length === 0, 'power off cleared every permission switch')
  assert(decl.executor_sessions?.[0] === 'session-09ca0247', 'power off kept the session naming')
  const wdDecl = JSON.parse(readFileSync(watchdogFile, 'utf8'))
  assert(wdDecl.enabled === true, 'power off left the watchdog enabled (watchdog keeps running)')
  n += 3

  await page.close()
} finally {
  await browser.close()
  await H.close()
  cleanup([wd, pan])
}
done(n)
