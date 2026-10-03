// lib_panel_state.mjs —— t261003-14 集成场景共享夹具（非 sc_ 前缀，不进 SCENARIOS，
// lint L5 不登记；共享 helpers 允许复用——步骤级复用不视为重复用例设计）。
//
// 缝：server/plugins/executor-panel/harness.mjs（插件真 API 面 + 真 panel 页，端口 0
// 全隔离，零 3099/7233）+ integration/lib_pw_deps.mjs（playwright-core 位置无关解析，
// KI-036 家族）。浏览器/依赖缺席一律 ENV_FAIL exit 2（t260904-12 三态，无 SKIP）。
//
// 契约锚定口径（灰盒铁律）：断言只落在用户可感知面——data-open 可见状态、输入框值、
// .detail 滚动位置、Answered 区文案、徽标数、pageerror 零发生；不锚内部 Set 字段名、
// 不锚渲染字符串形状。POLL_MS=5000 是页面公开口径（页脚自述「refresh every 5 seconds」），
// 等一个真实轮询周期（5.7s）即等一个用户真实会遇到的刷新边界。

import { join } from 'node:path'
import { mkdirSync, writeFileSync } from 'node:fs'
import { loadPlaywright, pwMissingDetail } from '../lib_pw_deps.mjs'

const REPO = process.cwd()
const POLL_MS = 5000
const POLL_WAIT_MS = POLL_MS + 700 // 一个真实轮询周期 + 页面 fetch 余量

export const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])

export function record(results, name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`)
}

export function summarize(results) {
  const p = results.filter((r) => r.status === 'pass').length
  const f = results.filter((r) => r.status === 'fail').length
  const e = results.filter((r) => r.status === 'env_fail').length
  const n = results.filter((r) => r.status === 'na').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

export function envFail(results, why) {
  record(results, 'browser dependency', 'env_fail', why)
  summarize(results)
}

async function launchBrowser(pw) {
  try { return await pw.chromium.launch({ channel: 'chrome', headless: true }) }
  catch { return await pw.chromium.launch({ headless: true }) }
}

/**
 * 起一台隔离面板台并开好页面。seed: [{kind, question, detail, options?}, …] 逐条走
 * 真 POST /api/requests 投递面。返回 { page, browser, H, post, waitPoll, close }。
 * 任何环境缺口（playwright/chromium）→ 抛 EnvMissing，由调用方转 ENV_FAIL。
 */
export async function openPanel({ KEY, seed = [], viewport = { width: 1280, height: 900 } }) {
  const pw = await loadPlaywright()
  if (!pw) { const e = new Error(pwMissingDetail()); e.envMissing = true; throw e }
  const { freshDir } = await import('../../server/plugins/executor-panel/tests/lib.mjs')
  const { startHarness } = await import('../../server/plugins/executor-panel/harness.mjs')
  const pan = freshDir('t26100314-panel-')
  const wd = freshDir('t26100314-wd-')
  const H = await startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
  const post = async (path, body) => {
    const r = await fetch(H.base + path, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    })
    return { status: r.status, json: await r.json() }
  }
  for (const s of seed) {
    const r = await post('/sandbar-executor-panel/api/requests', { project: KEY, raised_by: 'integration-fixture', ...s })
    if (r.status !== 200) throw new Error('fixture seed rejected: ' + JSON.stringify(r.json))
  }
  let browser
  try { browser = await launchBrowser(pw) } catch (e) {
    const close0 = H.close?.() // 台先收口，零残留
    await close0
    const err = new Error('chromium launch failed: ' + (e?.message || String(e))); err.envMissing = true; throw err
  }
  const pageErrors = []
  const page = await browser.newPage({ viewport })
  page.setDefaultTimeout(15000)
  page.on('pageerror', (e) => pageErrors.push(String(e)))
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.waitForFunction(() => {
    const b = document.getElementById('reqBadge')
    return b && b.textContent !== '' && document.querySelector('.row, .act')
  }, { polling: 200 })
  const waitPoll = () => page.waitForTimeout(POLL_WAIT_MS)
  const close = async () => {
    try { await browser.close() } catch { /* 终态回收尽力而为 */ }
    await H.close()
    const { cleanup } = await import('../../server/plugins/executor-panel/tests/lib.mjs')
    cleanup([pan, wd])
  }
  return { page, browser, H, post, waitPoll, close, pageErrors, KEY }
}

// 等待区/已答区的行定位（用户可见锚：data-row=id + 区块容器 id）。
export const waitRow = (id) => `.row.wait[data-row="${id}"] .head`
export const waitRowEl = (id) => `.row.wait[data-row="${id}"]`
export const doneRowEl = (id) => `.row.done[data-row="${id}"]`
export const doneHead = (id) => `.row.done[data-row="${id}"] .head`

// 长文本 fixture：.detail max-height:170px overflow:auto，约 40 行必可滚。
export const LONG_DETAIL = Array.from({ length: 40 }, (_, i) => `line ${String(i).padStart(2, '0')} — the host is reading a long detail across the refresh boundary.`).join('\n')
