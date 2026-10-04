#!/usr/bin/env node
/**
 * shots.mjs —— t261004-16 UI 证据通道：隔离 harness（端口 0，零 3099/7233）+
 * 真 Chromium，产出票面要求的 4 张截图（light/dark × 1600/1100，Overview 页签、
 * 一条 markdown 请求展开）与量测数字 JSON（.sandbar/screenshots/）。
 *
 * 量测口径（票面 6d/6e，数字不是形容词）：
 *   content box 宽 + 两侧留白 @1600；Overview 两栏宽；detail 限高与字号；
 *   展开真实请求时 DOM 里的 markdown 元素计数。
 *
 * 用法：node shots.mjs   （cwd=仓库根或本插件目录均可；playwright-core 寻址同
 * tests/browser-redesign.test.mjs 的约定：server/ui-check/node_modules）
 */
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const pluginDir = dirname(fileURLToPath(import.meta.url))
const repo = resolve(pluginDir, '../../..')
const outDir = join(repo, '.sandbar/screenshots')
mkdirSync(outDir, { recursive: true })

function findPlaywrightCore() {
  let dir = pluginDir
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found: expected server/ui-check/node_modules in this checkout or a sibling of the lane root')
}
const playwright = createRequire(import.meta.url)(findPlaywrightCore())

const mod = await import(join(pluginDir, 'harness.mjs'))
const KEY = 'rodalpha'
const wd = mkdtempSync('/tmp/ep-shots-wd-')
const pan = mkdtempSync('/tmp/ep-shots-pan-')
// 全终态回收：成功/失败/超时（进程退出即兜底 rmSync）都清干净隔离目录。
let cleaned = false
function reclaim() {
  if (cleaned) return
  cleaned = true
  for (const d of [wd, pan]) { try { rmSync(d, { recursive: true, force: true }) } catch (e) {} }
}
process.on('exit', reclaim)
process.on('SIGINT', () => { process.exit(130) })
process.on('SIGTERM', () => { process.exit(143) })
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
const browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }).catch(() => playwright.chromium.launch({ headless: true }))

const MD_DETAIL = [
  '## Merge readiness',
  '',
  'The gate is **green** and the lockfile is current.',
  '',
  'Two things before you sign:',
  '',
  '- run `python3 integration/lint_tests.py`',
  '- confirm the baseline diff is empty',
  '',
  '1. review the handoff',
  '2. approve the merge',
  '',
  '> Reference: docs/design/ticket-workflow-console-design.md',
  '',
  '```sh',
  'python3 integration/lint_tests.py --help',
  '```',
].join('\n')

try {
  mkdirSync(join(wd, KEY), { recursive: true })
  writeFileSync(join(wd, KEY, 'watchdog.json'), JSON.stringify({ enabled: true, stall_minutes: 15 }) + '\n', 'utf8')
  const post = (path, body) => fetch(H.base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json())
  await post('/sandbar-executor-panel/api/requests', {
    project: KEY, kind: 'sign', question: 'Merge ticket t261004-16: does the panel change look right?',
    detail: MD_DETAIL, default_action: 'hold', raised_by: 'session-shot01',
    options: ['**Approve** the merge', 'Reject with `notes`'],
  })
  await post('/sandbar-executor-panel/api/requests', {
    project: KEY, kind: 'question', question: 'Do you have more instructions?',
    detail: 'The executor waits for your answer.', default_action: 'hold',
  })

  const numbers = {}
  for (const [theme, width, height] of [['light', 1600, 900], ['light', 1100, 800], ['dark', 1600, 900], ['dark', 1100, 800]]) {
    const page = await browser.newPage({ viewport: { width, height } })
    page.setDefaultTimeout(15000)
    await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY + '&theme=' + theme)
    await page.waitForFunction(() => document.getElementById('reqBadge') && document.getElementById('reqBadge').textContent === '2', { polling: 200 })
    // 展开两条：markdown 请求（选项面）+ 普通请求（应答框面）。
    const mdRow = page.locator('[data-row]', { hasText: 'Merge ticket t261004-16' }).first()
    await mdRow.locator('.head').click()
    await page.waitForSelector('[data-row] .opts button[data-answer]', { timeout: 5000 })
    const qRow = page.locator('[data-row]', { hasText: 'Do you have more instructions' }).first()
    await qRow.locator('.head').click()
    await page.waitForSelector('[data-row] .answer input', { timeout: 5000 })

    const m = await page.evaluate(() => {
      const cs = (el) => getComputedStyle(el)
      const wrap = document.querySelector('.wrap')
      const wr = wrap.getBoundingClientRect()
      const cols = document.querySelectorAll('.cols > div')
      const detail = document.querySelector('[data-row] .detail')
      const dcs = detail ? cs(detail) : null
      const mdTags = ['h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'strong', 'em', 'a']
      let mdCount = 0
      document.querySelectorAll('.qfull, .detail, .given').forEach((box) => {
        mdTags.forEach((t) => { mdCount += box.querySelectorAll(t).length })
      })
      return {
        viewportWidth: window.innerWidth,
        horizontalScrollbar: document.documentElement.scrollWidth > window.innerWidth,
        contentBoxWidth: Math.round(wr.width),
        leftGutter: Math.round(wr.left),
        rightGutter: Math.round(window.innerWidth - wr.right),
        columnWidths: [...cols].map((c) => Math.round(c.getBoundingClientRect().width)),
        detailCapHeightPx: dcs ? parseInt(dcs.maxHeight, 10) : null,
        detailFontSizePx: dcs ? parseFloat(dcs.fontSize) : null,
        markdownElementCount: mdCount,
      }
    })
    const tag = `${theme}-${width}`
    numbers[tag] = m
    const shot = join(outDir, `executor-${tag}.png`)
    await page.screenshot({ path: shot, fullPage: false })
    console.log('shot', shot, JSON.stringify(m))
    await page.close()
  }
  writeFileSync(join(outDir, 'executor-numbers.json'), JSON.stringify(numbers, null, 2) + '\n', 'utf8')
  console.log('numbers ->', join(outDir, 'executor-numbers.json'))
  await browser.close()
  await H.close()
} catch (e) {
  console.error('SHOTS FAILED:', e && e.message)
  await browser.close().catch(() => {})
  await H.close().catch(() => {})
  process.exit(1)
}
