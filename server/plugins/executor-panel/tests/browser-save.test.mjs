/**
 * browser-save.test.mjs —— t261001-10 浏览器驱动测试杆（补此前盲区）：
 * 起 harness 真 HTTP + playwright-core 真 Chromium 装载**服务出的真页面**，断言：
 *  (a) 全文档无重复 id（此前 `/\./g` 被模板字符串吃掉反斜杠 → 等长路径 id 撞车）；
 *  (b) 在 executor_session 输入并点 Save，值落到声明文件正确的键且只此一键；
 *  (c) 故意被拒的保存：引擎理由显示在页上、settings 刷新后仍在、文件逐字节不动。
 *
 * playwright-core 复用 server/ui-check/node_modules（票面指定；不新增依赖）。
 * 浏览器获取同 capture.mjs 口径：系统 Chrome 优先，探测不到退自带 chromium，
 * 都不可用=显式报错非零退出（不静默跳过）。
 */
import { createRequire } from 'node:module'
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { assert, done, freshDir, cleanup } from './lib.mjs'

let n = 0
const require = createRequire(import.meta.url)

// playwright-core 解析（票面指定复用 server/ui-check/node_modules，不新增依赖）：
// 先从本文件向上找（主检出内直接命中）；泳道 worktree 不含 untracked node_modules
// → 逐级到根的兄弟检出（../..../server/ui-check）兜底；都没有=显式报错不静默跳过。
function findPlaywrightCore() {
  let dir = import.meta.dirname
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found: expected server/ui-check/node_modules/playwright-core in this checkout or a sibling of the lane root')
}
const playwright = require(findPlaywrightCore())

async function launchBrowser() {
  try {
    return await playwright.chromium.launch({ channel: 'chrome', headless: true })
  } catch (e) {
    return await playwright.chromium.launch({ headless: true })
  }
}

const wd = freshDir(), pan = freshDir()
const mod = await import('../harness.mjs')
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
const browser = await launchBrowser()
const declFile = join(wd, 'rodalpha', 'watchdog.json')
let savedBytes = ''
try {
  const page = await browser.newPage()
  page.setDefaultTimeout(15000)
  await page.goto(H.base + '/sandbar-executor-panel?project=rodalpha')
  await page.waitForSelector('#saveBtn', { state: 'attached' })
  await page.evaluate(() => document.getElementById('t-settings').click()) // 切到 Settings tab（pane 才可见）
  await page.waitForSelector('#saveBtn')

  // (a) 无重复 id：读端 getElementById 读第一个 → 重复 id = 读错字段的根因。
  const dupes = await page.evaluate(() => {
    const ids = Array.from(document.querySelectorAll('[id]')).map((e) => e.id)
    const seen = new Set(), d = new Set()
    for (const i of ids) { if (seen.has(i)) d.add(i); seen.add(i) }
    return Array.from(d)
  })
  assert(dupes.length === 0, 'no duplicate ids in the served document (found: ' + JSON.stringify(dupes) + ')')
  const knobIds = await page.evaluate(() =>
    Array.from(document.querySelectorAll('#setKnobs [id^="kb_"]')).map((e) => e.id).sort())
  assert(new Set(knobIds).size === knobIds.length, 'every knob has its own id (' + knobIds.length + ' knobs)')
  assert(knobIds.includes('kb_executor_session') && knobIds.includes('kb_alerts_keep_days')
    && knobIds.includes('kb_alerts_night_end'), 'dotted paths map to distinct ids (old collision trio present, distinct)')

  // (b) 真点 Save：值落到 executor_session 键且不出现在任何其他键。
  const VALUE = 'rod-session-value'
  await page.fill('#kb_executor_session', VALUE)
  await page.click('#saveBtn')
  await page.waitForSelector('#saveResult .good')
  n += 4
  const decl = JSON.parse(readFileSync(declFile, 'utf8'))
  assert(decl.executor_session === VALUE, 'typed value lands under executor_session in the written declaration file')
  const hits = JSON.stringify(decl).split(VALUE).length - 1
  assert(hits === 1, 'typed value appears exactly once in the file (not smeared onto other keys), hits=' + hits)
  assert(decl.alerts.keep_days !== VALUE && typeof decl.alerts.keep_days === 'number', 'alerts.keep_days stays numeric')

  // (c) 拒收的保存：理由显示、刷新后仍在、文件逐字节不动。
  savedBytes = readFileSync(declFile, 'utf8')
  await page.fill('#kb_alerts_keep_days', '-1')
  await page.click('#saveBtn')
  await page.waitForSelector('#saveResult .bad')
  const reason = await page.textContent('#saveResult')
  assert(reason.includes('REJECTED') && reason.includes('keep_days'), 'engine rejection reason shown on the page: ' + reason.trim().slice(0, 120))
  // loadSettings 的重渲染会重建 #saveResult —— 理由必须在刷新落定后**仍在**。
  // （t261003-06 改版：#saveBtn 移出 #setKnobs 到独立 .bar 行——刷新落定判据改为旋钮已重建。）
  await page.waitForFunction(() => {
    const t = document.getElementById('saveResult')
    return t && t.textContent.includes('REJECTED') && document.querySelector('#setKnobs .knob')
  }, { polling: 200 })
  await page.waitForTimeout(800) // 等 settings+grants 两个 GET 的重渲染都落定
  const after = await page.textContent('#saveResult')
  assert(after.includes('REJECTED') && after.includes('keep_days'), 'rejection reason survives the settings refresh')
  assert(readFileSync(declFile, 'utf8') === savedBytes, 'rejected save left the declaration file byte-identical')
  n += 4
  await page.close()
} finally {
  await browser.close()
  await H.close()
  cleanup([wd, pan])
}
done(n)
