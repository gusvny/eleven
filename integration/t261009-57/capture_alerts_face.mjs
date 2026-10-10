#!/usr/bin/env node
/**
 * capture_alerts_face.mjs —— t261009-57 UI 证据：Overview Alerts 区块实拍。
 * 复用 browser-t261008-20 的既有模式：隔离 harness（端口 0、临时目录、KI-193 cookie）
 * + page.route 打桩 /sandbar-watchdog/api/status（fixture 在本文件内固定——不依赖真
 * watchdog，无外部源）。只读打开面板页并截图，不提交任何表单、不碰 3099/7233。
 * 用法：node capture_alerts_face.mjs --out <png 绝对路径>
 */
import { createRequire } from 'node:module'
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

function arg(name) {
  const i = process.argv.indexOf('--' + name)
  return i > 0 ? process.argv[i + 1] : null
}
const out = arg('out')
if (!out) { console.error('usage: node capture_alerts_face.mjs --out <png>'); process.exit(2) }

const require = createRequire(import.meta.url)
function findPlaywrightCore() {
  let dir = import.meta.dirname
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found (expected server/ui-check/node_modules)')
}
const playwright = require(findPlaywrightCore())
async function launchBrowser() {
  try { return await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
  catch { return await playwright.chromium.launch({ headless: true }) }
}

const { freshDir, cleanup, panelCookieFor } = await import('../../server/plugins/executor-panel/tests/lib.mjs')
const wd = freshDir(), pan = freshDir()
const mod = await import('../../server/plugins/executor-panel/harness.mjs')
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })

// 固定 fixture：两个持久条件各响多拍（xN 面）+ 一条跨窗口边的旧条件 + 一条独立 warn。
// 账本全量行原样进 payload（raw rows），alerts_display_max=8 只数并排后的行。
const NOW = Date.now()
const MIN = 60_000
const row = (key, rule, target, level, title, at) => ({ key, rule, target, level, title, at, night_muted: false })
const ledgerRows = [
  ...Array.from({ length: 14 }, (_, i) => row('ledger_unreadable:ledger', 'ledger_unreadable', 'ledger', 'redline',
    '账本不可读：watermark 落后且 archive 缺口未合（ledger watermark behind and the archive gap is not closed, the reconcile retry keeps failing)', NOW - (14 - i) * 10 * MIN)),
  ...Array.from({ length: 6 }, (_, i) => row('executor_awaiting_self:session-09ca', 'executor_awaiting_approval', 'session-09ca', 'warn',
    'executor 在等自己（awaiting its own wake)', NOW - (6 - i) * 10 * MIN)),
  row('stall:executor-sb', 'stall', 'executor-sb', 'redline', '无动作超过阈值（no motion past the stall threshold)', NOW - 25 * 3600_000),
  row('engine_down:engine', 'engine_down', 'engine', 'redline', '引擎心跳不可达（engine heartbeat unreachable)', NOW - 3 * MIN),
]
const STATUS = { ok: true, result: {
  declared: true, enabled: true,
  heartbeat: { alive: true, age_seconds: 3 },
  ledger: { path: '/x/ledger.jsonl', unreadable: false, rows_seen: 12480, dupes_skipped: 3, malformed_rows: 0, gaps_seen: 0 },
  liveness: { executor: { alive: true } },
  alerts: ledgerRows, alerts_display_max: 8,
  notify: { beep: false, unseen_redline: 0 },
} }

const browser = await launchBrowser()
try {
  const CRED = (() => { const c = panelCookieFor(new URL(H.base).host); const i = c.indexOf('='); return { header: c, cookies: [{ name: c.slice(0, i), value: c.slice(i + 1), url: H.base }] } })()
  const ctx = await browser.newContext({ viewport: { width: 1300, height: 1400 } })
  await ctx.addCookies(CRED.cookies)
  const page = await ctx.newPage()
  page.setDefaultTimeout(15000)
  await page.route('**/sandbar-watchdog/api/status*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(STATUS) }))
  await page.goto(H.base + '/sandbar-executor-panel?project=rodalpha&theme=light')
  // --legacy: the pre-ticket page has no coalescing, so the x14 marker never
  // appears — wait only for rows to render (the raw-rows ellipsis face IS the point).
  const needX = !process.argv.includes('--legacy')
  await page.waitForFunction((needX) => {
    const el = document.getElementById('alertList')
    if (!el || el.children.length === 0 || el.querySelector('.empty')) return false
    return !needX || el.textContent.includes('x14')
  }, needX, { polling: 200 }).catch(async (e) => { console.error('HEAD:', await page.evaluate(() => document.getElementById('alertHead').textContent), '| rows:', await page.evaluate(() => Array.from(document.querySelectorAll('#alertList .row')).map(r => r.querySelector('.txt.altxt').textContent))); throw e })
  // clip-shot: the poll loop rewrites the block every beat, so an element screenshot
  // (which waits for box stability) can starve — a clipped page shot does not.
  const box = await page.locator('.blk', { has: page.locator('#alertList') }).first().boundingBox()
  await page.screenshot({ path: out, clip: box })
  console.log('captured', out)
  await ctx.close()
} finally {
  await browser.close().catch(() => {})
  try { await H.close() } catch {}
  cleanup([wd, pan])
}
