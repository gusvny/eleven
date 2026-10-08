// sc_middle_head_strip_retired.mjs — t261008-18 中列机器状态条退役（灰盒 L3，真浏览器 +
// 隔离台 + 页边界 API 桩，红线零接触 3099）。
//
// Intent（用户可感知行为；真源=工单 t261008-18 宿主令 + mock 261003/261004）：
//   宿主令 261008：中列顶部的机器状态条（● Temporal UI ↗ | N workers | Inspection N，
//   t261005-10 UI-2 引入）整行退役。用户此后在中列看到的头=**只有**执行器面板自己的头
//   「Executor + 项目 chip」（mock 真源，panel 页内已实现）；上面不再有任何机器级状态行、
//   不再有 Temporal 控制台链接 / workers 按钮 / Inspection 按钮 / 离线告警行。
//   本场景锁四件事，全部同一趟跑完：
//   A1 状态条整行消失（语义锚：顶栏文档里不再有文本含「Temporal UI」的链接、不再有
//      匹配 workers / Inspection 的按钮、不再有 offline 告警行——锚用户可读文案，
//      不锚 class 名；reject 红线：CSS 藏起来不算删，这里测的是 DOM 在不在）。
//   A2 头=标题+项目 chip：面板头可见文本以 Executor 开头且含项目 key（mock 真源）。
//   A3 孤儿机械面必须死：轮询清理不是「没人看就留着」——页面边界计数器记录 ≥6s 观察窗
//      （大于旧 5s 轮询周期，残留循环必现形）内 wf/temporal-health、wf/workers、
//      wf/scan-report 三条 API 的请求次数，任何一次 >0 = 孤儿 fetch 循环 = FAIL。
//   A4 布局链同趟存活：删一行不得动 t261008-05 修好的几何链——面板视图 computed
//      height > 600 且 iframe 填满视图（本场景只做「同趟共存」轻断言；几何契约本体
//      归 t261008-05-executor-panel-height-chain，intent 分工：那边锁链，这边锁
//      「删行同趟链不断」）。
//   A5 KI-055 双主题矩阵：light + dark 各截中列证据图落票目录；dark 子用例断言页面底色
//      亮度 < 0.5（截图在 = 证据在，暗底不暗 = 假 dark = FAIL）。
//   R1 全程零 pageerror。
//
// 执行契约（t260904-12 三态）：隔离台/playwright/chromium 缺席=ENV_FAIL exit 2
// （KI-036 家族）；实现未落地时 A1/A3 红=TDD 预期 anti-proof。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { existsSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base

const PROJ = 'stripproj'
const PROJ_NAME = 'Strip Project'
const PANEL_STUB_MARKER = 'EXECUTOR_PANEL_STUB_OK'
const VIEWPORT = { width: 1440, height: 900 }
const MIN_PANEL_H = 600          // 同趟共存判据（契约本体归 t261008-05）
const POLL_WINDOW_MS = 6500      // > 旧 5s health/workers 轮询周期

// ---------------------------------------------------------------- results

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- fixtures

const FIXTURE_TICKET = {
  id: 't26100818a', role: 'developer', status: 'dispatched',
  title: 'Fixture ticket for strip-retirement scenario', workflow: 'dev-lane',
  stage: 'implement', stage_state: 'running', handoff_count: 0, pending_count: 0,
  worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}

// ---------------------------------------------------------------- helpers（夹具面与 t261008-05 同源，共享合法）

async function dismissOverlays(page) {
  for (let i = 0; i < 5; i++) {
    const dialog = page.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(600)
  }
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

async function snap(page) {
  try {
    const txt = await page.evaluate(() => (document.body.textContent || '').slice(0, 200))
    return JSON.stringify(txt)
  } catch { return '(snapshot unavailable)' }
}

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}

async function loadPlaywright() {
  const candidates = ['playwright-core']
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) candidates.push(pathToFileURL(p).href)
  }
  for (const c of candidates) {
    try { return await import(c) } catch { /* next */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

const json = (route, b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })

// 状态条退役的负向计数器：三条只喂状态条的 API，页边界计数 + 低位兜底放行。
const pollCounts = { health: 0, workers: 0, scan: 0 }
function trackPolls(page) {
  const tracks = [
    ['**/sandbar-workbench/api/wf/temporal-health*', 'health'],
    ['**/sandbar-workbench/api/wf/workers*', 'workers'],
    ['**/sandbar-workbench/api/wf/scan-report*', 'scan'],
  ]
  for (const [glob, key] of tracks) {
    void page.route(glob, (route) => { pollCounts[key] += 1; return route.fallback() })
  }
}

async function stubConsole(page) {
  await page.route('**/*', (route) => route.fallback())
  await page.route('**/sandbar-workbench/api/wf/projects', (route) =>
    json(route, { ok: true, result: { projects: [{ key: PROJ, name: PROJ_NAME, dirs: [] }], quarantined: [] } }))
  await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/+$/, '')
    if (path === '/sandbar-workbench/api/wf/tickets') return json(route, { ok: true, result: { tickets: [FIXTURE_TICKET] } })
    return json(route, { ok: true, result: {} })
  })
  await page.route('**/sandbar-watchdog/api/status**', (route) => json(route, { ok: true, projects: [] }))
  await page.route('**/sandbar-executor-panel/api/settings**', (route) =>
    json(route, { ok: true, declared: false, enabled: false, executor_session: '', file: null }))
  // 面板页文档放行给隔离台真件（A2 要看 mock 真源的头），面板自有 API 也走真台。
}

async function openExecutorPanel(page) {
  const head = page.locator('.wb-group-head', { hasText: PROJ_NAME }).first()
  if (!(await waitFor(async () => (await head.count()) > 0, 12000))) return 'project group row not rendered'
  const entry = page.locator('[data-wb-executor-entry]').first()
  if (!(await entry.count())) return 'executor entry anchor not rendered on the project row'
  await entry.click({ force: true, timeout: 8000 })
  const ok = await waitFor(async () => {
    const txt = await page.evaluate(() => {
      const f = [...document.querySelectorAll('iframe')].find(f => /sandbar-executor-panel/.test(f.src || ''))
      return { src: f?.src ?? '', body: document.body.textContent || '' }
    })
    return (txt.src && decodeURIComponent(txt.src).includes(PROJ)) || txt.body.includes(`${PANEL_STUB_MARKER}:${PROJ}`)
  }, 8000)
  return ok ? null : `panel iframe with project=${PROJ} never mounted @ ${await snap(page)}`
}

// ---- A1 状态条整行消失（语义锚，锚文案不锚 class；只看顶层文档，面板 iframe 内的
//      Inspection 标签页内容是另一张票的面，不在本断言面内）

async function scenarioStripGone(page) {
  return page.evaluate(() => {
    const probs = []
    const topLinks = [...document.querySelectorAll('a')]
    if (topLinks.some(a => /Temporal/i.test(a.textContent || ''))) probs.push('a link mentioning Temporal still renders in the top-level document')
    const topButtons = [...document.querySelectorAll('button')]
    if (topButtons.some(b => /workers/i.test(b.textContent || ''))) probs.push('a workers button still renders in the top-level document')
    if (topButtons.some(b => /Inspection/i.test(b.textContent || ''))) probs.push('an Inspection button still renders in the top-level document')
    if (/offline/i.test(document.body.textContent || '')) probs.push('an offline warning row still renders')
    return probs
  }).then(probs => probs.length ? probs.join('; ') : null)
}

// ---- A2 头=标题+项目 chip（mock 真源：Executor + 项目 key，面板页内）

async function scenarioHeadIsTitleAndChip(page) {
  const frameEl = await page.waitForSelector('iframe[data-wb-executor-frame]', { timeout: 8000 }).catch(() => null)
  if (!frameEl) return 'executor panel iframe not found'
  const frame = await frameEl.contentFrame()
  if (!frame) return 'panel iframe not accessible (same-origin expected on the bench console)'
  const ok = await waitFor(async () => {
    try {
      const head = await frame.locator('.top').first().innerText()
      return /^Executor/.test(head.trim()) && head.includes(PROJ)
    } catch { return false }
  }, 8000)
  if (!ok) {
    const txt = await frame.locator('.top').first().innerText().catch(() => '(no .top head)')
    return `panel head is not "Executor + ${PROJ}" — got ${JSON.stringify(txt.slice(0, 120))}`
  }
  return null
}

// ---- A3 孤儿轮询必须死：≥6s 观察窗内三条 API 计数全 0（计数，不是声称）

async function scenarioNoOrphanPolling() {
  await page0.waitForTimeout(POLL_WINDOW_MS)
  const fired = Object.entries(pollCounts).filter(([, n]) => n > 0)
  return fired.length
    ? `orphan strip polling still fires: ${fired.map(([k, n]) => `${k}=${n}`).join(', ')} in a ${POLL_WINDOW_MS}ms window`
    : null
}

// ---- A4 布局链同趟存活（轻断言；几何契约本体归 t261008-05）

async function measureChain(page) {
  return page.evaluate(() => {
    const q = (sel) => document.querySelector(sel)
    const view = q('[data-wb-executor-view]') || q('.wb-executor-view')
    const frame = q('[data-wb-executor-frame]') || q('.wb-executor-frame')
    const rect = (el) => el ? el.getBoundingClientRect() : null
    const viewR = rect(view), frameR = rect(frame)
    const fr = (r) => r ? { h: Math.round(r.height), bottom: Math.round(r.bottom) } : null
    return { view: fr(viewR), frame: fr(frameR) }
  })
}

async function scenarioLayoutChainIntact(page) {
  // 面板已在 P0 打开；这里只做同趟几何共存断言，不再点入口（重复点击可能切换视图）。
  if (!(await waitFor(async () => {
    const m = await measureChain(page)
    return m.view && m.frame && m.view.h > MIN_PANEL_H && m.frame.h >= m.view.h * 0.9
  }, 8000))) {
    const m = await measureChain(page)
    const probs = []
    if (!m.view || m.view.h <= MIN_PANEL_H) probs.push(`executor view height ${m.view?.h ?? 'none'}px <= ${MIN_PANEL_H}`)
    if (!m.frame || m.frame.h < m.view.h * 0.9) probs.push(`iframe ${m.frame?.h ?? 'none'}px does not fill its view ${m.view?.h ?? '?'}px`)
    return probs.join('; ') + ` @ chain=${JSON.stringify(m)}`
  }
  return null
}

// ---- A5 KI-055 双主题矩阵：light+dark 截图 + dark 底色亮度断言

function luminance(rgb) {
  if (!rgb) return null
  const hx = rgb.match(/^#([0-9a-f]{6})$/i)
  if (hx) {
    const n = parseInt(hx[1], 16)
    rgb = `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`
  }
  if (!rgb.startsWith('rgb')) return null
  const m = rgb.match(/(\d+),\s*(\d+),\s*(\d+)/)
  if (!m) return null
  return [1, 2, 3].map(i => {
    const c = Number(m[i]) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }).reduce((acc, c, i) => acc + c * [0.2126, 0.7152, 0.0722][i], 0)
}

async function captureTheme(page, theme) {
  const outDir = join(REPO, 'integration', 't261008-18', 'out')
  mkdirSync(outDir, { recursive: true })
  const col = page.locator('.wb-right-content').first()
  await col.screenshot({ path: join(outDir, `middle-column-${theme}.png`) })
  const bg = await page.evaluate(() => {
    // 亮度判据读声明令牌面（--dsw-alias-bg-base，theme.ts dark 分档翻的正是它），
    // 读不到再回落 body 实底——both 是「台面真的暗了」的用户可感知面。
    const v = getComputedStyle(document.documentElement).getPropertyValue('--dsw-alias-bg-base').trim()
    return v || getComputedStyle(document.body).backgroundColor
  })
  if (theme === 'dark') {
    const lum = luminance(bg)
    if (lum === null) return `dark sub-case: background token unreadable (${bg})`
    if (lum >= 0.5) return `dark sub-case: background ${bg} luminance ${lum.toFixed(2)} >= 0.5 (not actually dark)`
  }
  return null
}

// ---- R 渲染卫生

async function scenarioNoPageErrors(pageErrors) {
  if (pageErrors.length) return `pageerror(s): ${JSON.stringify(pageErrors.slice(0, 3))}`
  return null
}

// ---------------------------------------------------------------- main

let page0 = null // A3 观察窗用的活动页

async function run() {
  const ctx = { browser: null, pw: null }
  try { ctx.pw = await loadPlaywright() } catch { /* treated as missing below */ }
  if (!ctx.pw) {
    record('S0 playwright', 'env_fail', 'playwright-core 不可解析（KI-036 家族：ui-check 依赖缺席，恢复后自动生效）')
    summarize()
  }
  ctx.browser = await launchBrowser(ctx.pw)
  if (!ctx.browser) {
    record('S0 chromium', 'env_fail', '无可启动的 chromium/chrome（headless）')
    summarize()
  }

  const bctx = await ctx.browser.newContext({ viewport: VIEWPORT })
  const pageErrors = []
  const page = await bctx.newPage()
  page0 = page
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))

  trackPolls(page)
  await stubConsole(page)
  await page.goto(`${BASE}/?theme=light`, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await dismissOverlays(page)
  await page.waitForTimeout(3000)
  await dismissOverlays(page)

  const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
  const run1 = async (name, fn, arg) => {
    try {
      const err = await fn(arg ?? page)
      if (err) record(name, 'fail', err)
      else record(name, 'pass')
    } catch (e) { await failWith(name, e) }
  }

  const openErr = await openExecutorPanel(page)
  if (openErr) {
    record('P0 panel open', 'fail', openErr)
    await ctx.browser.close()
    summarize()
  }
  record('P0 panel open', 'pass')

  await run1('A1 machine status strip is gone from the middle-column head', scenarioStripGone)
  await run1('A2 head keeps only the executor title and the project chip', scenarioHeadIsTitleAndChip)
  await run1('A3 zero orphan strip-API polling in a >=6s window', scenarioNoOrphanPolling)
  await run1('A4 executor panel still fills the middle column (layout chain intact)', scenarioLayoutChainIntact)
  await run1('A5 light capture of the middle column (KI-055 matrix)', (p) => captureTheme(p, 'light'))
  // dark 子用例：台面 dark = 平台外壳按 system 外观翻 --dsw-alias 令牌并置位
  // body[data-ds-dark-theme]（theme.ts 契约「无自有主题态」；外壳 boot 脚本会按
  // system 偏好回写该属性，故 emulateMedia + toggleAttribute 同施，t261008-07 先例）。
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.evaluate(() => document.body.toggleAttribute('data-ds-dark-theme', true))
  await page.waitForTimeout(800)
  await dismissOverlays(page)
  if (await openExecutorPanel(page)) {
    record('A5 dark capture of the middle column (KI-055 matrix)', 'fail', `dark leg: panel did not reopen @ ${await snap(page)}`)
  } else {
    await run1('A5 dark capture of the middle column (KI-055 matrix)', (p) => captureTheme(p, 'dark'))
  }
  await run1('R1 zero pageerror across the journey', scenarioNoPageErrors, pageErrors)

  await ctx.browser.close()
  summarize()
}

run().catch(async (e) => {
  console.error('FATAL', e)
  process.exit(2)
})
