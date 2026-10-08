// sc_executor_panel_height_chain.mjs — t261008-05 中列几何链：全高执行器面板 + 中列前驱块
// 共存（灰盒 L3，真浏览器 + 隔离台 + API 桩，红线零接触 3099；t261008-18 起前驱块不再
// 是机器状态头——该行已退役，几何契约本身不变）。
//
// Intent（用户可感知行为；真源=工单 t261008-05 宿主实测与验收口径）：
//   点左栏项目名打开执行器面板后，用户必须**同时**看到：
//   - 其上的 overlay 前驱块（宿主 .wb-root，flex:none 的兄弟块；曾经是机器状态头）；
//   - 其下占满中列剩余高度的执行器面板（.wb-executor-view + 内部 iframe）。
//   t261005-10 回归（宿主 261008 实测）：宿主仍带遗留 min-height:100%/height:100%，
//   吃满整列 → 面板视图高度 0 → iframe 落回 150px 替换元素默认值并外溢——用户看到
//   头 + 分隔线 + 一片白。本场景锁修复后的几何链，并保证它不能再静默回退：
//   **面板视图高度为 0 而容器更高 ⇒ 本场景红**。
//
// Intent 分工（防重复）：
//   - t260929-22-executor-entry-console 锁「怎么到达面板」（入口语义）；本场景只锁
//     「到达后的中列几何」，入口/遮罩收口逻辑复用其夹具面（共享 helpers 合法）。
//   - t260929-03 族锁面板**页面内部**（桩顶替，不复断页内）。
//   - developer L1（源码级 CSS 契约单测）不同层：本场景锁真浏览器 computed layout
//     ——CSS 字符串锁看不见的声明重排/特异性变化/浏览器默认值（150px）都在这层现形。
//
// 执行契约（t260904-12 三态）：隔离台/playwright/chromium 缺席=ENV_FAIL exit 2
// （KI-036 家族）；几何链塌缩=FAIL 点名（修复未落地时 TDD 红属预期=anti-proof）。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { existsSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base

const PROJ = 'heightproj'
const PROJ_NAME = 'Height Project'
const PANEL_STUB_MARKER = 'EXECUTOR_PANEL_STUB_OK'
const VIEWPORT = { width: 1440, height: 900 }   // 验收口径锁定视口
const MIN_PANEL_H = 600                          // 验收口径：.wb-executor-view 高度 > 600

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
  id: 't26100805a', role: 'developer', status: 'dispatched',
  title: 'Fixture ticket for height-chain scenario', workflow: 'dev-lane',
  stage: 'implement', stage_state: 'running', handoff_count: 0, pending_count: 0,
  worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}

// ---------------------------------------------------------------- helpers（夹具面与 t260929-22 同源，共享合法）

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

async function stubConsole(page) {
  // 桩面与 t260929-22 同源（低位兜底放行真台，只桩本票契约面；兜底不发明响应形状）。
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
  await page.route('**/sandbar-executor-panel/**', (route) => {
    const url = new URL(route.request().url())
    const proj = url.searchParams.get('project') ?? ''
    const html = `<!doctype html><html><body data-panel-project="${proj}"><div id="panel-stub">${PANEL_STUB_MARKER}:${proj}</div></body></html>`
    return route.fulfill({ contentType: 'text/html', body: html })
  })
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

/** 中列几何链实测（computed layout，非源码）。锚 data-* 只为定位；断言全部落在
 *  用户可感知的盒子尺寸上，不锚内部实现命名。 */
async function measureChain(page) {
  return page.evaluate(() => {
    const q = (sel) => document.querySelector(sel)
    const col = q('.wb-right-content')
    const view = q('[data-wb-executor-view]') || q('.wb-executor-view')
    const frame = q('[data-wb-executor-frame]') || q('.wb-executor-frame')
    const rect = (el) => el ? el.getBoundingClientRect() : null
    const colR = rect(col), viewR = rect(view), frameR = rect(frame)
    // 宿主 = 中列里面板视图的直接前驱块（overlay 所在；t261008-18 前曾是机器状态头），按兄弟关系定位。
    let hostR = null
    if (view && view.parentElement) {
      const sibs = [...view.parentElement.children].filter(c => c !== view)
      const prev = sibs[sibs.length - 1]
      if (prev) hostR = prev.getBoundingClientRect()
    }
    const fr = (r) => r ? { top: Math.round(r.top), h: Math.round(r.height), bottom: Math.round(r.bottom) } : null
    return { col: fr(colR), view: fr(viewR), frame: fr(frameR), host: fr(hostR) }
  })
}

function chainProblems(m) {
  if (!m.col || !m.view || !m.frame) return `layout chain incomplete: ${JSON.stringify(m)}`
  const probs = []
  // G1 核心判据：面板视图必须拿到实质高度（0 高 = 本票缺陷复现）。
  if (m.view.h <= MIN_PANEL_H) probs.push(`executor view height ${m.view.h}px <= ${MIN_PANEL_H} (panel squeezed — the ticket defect)`)
  // G2 面板视图不吃满整列：前驱块（overlay 等）与 view 同列共存。
  if (m.host && m.host.h >= m.col.h) probs.push(`overlay host takes the whole column (${m.host.h}px of ${m.col.h}px)`)
  // G3 iframe 填满视图（150px 替换元素默认值 = 缺陷面）。
  if (m.frame.h < m.view.h * 0.9) probs.push(`iframe ${m.frame.h}px does not fill its view ${m.view.h}px (replaced-element default leak)`)
  // G4 无外溢：面板不出中列底缘。
  if (m.frame.bottom > m.col.bottom + 2) probs.push(`iframe bottom ${m.frame.bottom} overflows column bottom ${m.col.bottom}`)
  return probs
}

// ---- G 面板几何链

async function scenarioHeightChain(page) {
  const err = await openExecutorPanel(page)
  if (err) return err
  const ok = await waitFor(async () => {
    const probs = chainProblems(await measureChain(page))
    return probs.length === 0
  }, 8000)
  const m = await measureChain(page)
  const probs = chainProblems(m)
  if (probs.length) return probs.join('; ') + ` @ chain=${JSON.stringify(m)}`
  // 验收证据：中列截图（头 + 全高面板同框），落票目录。
  const outDir = join(REPO, 'integration', 't261008-05', 'out')
  mkdirSync(outDir, { recursive: true })
  const col = page.locator('.wb-right-content').first()
  await col.screenshot({ path: join(outDir, 'middle-column-height-chain.png') })
  return null
}

// ---- R 渲染链卫生（只 pageerror；console.error 契约归 t260929-22 E5，不重复）

async function scenarioNoPageErrors(pageErrors) {
  if (pageErrors.length) return `pageerror(s): ${JSON.stringify(pageErrors.slice(0, 3))}`
  return null
}

// ---------------------------------------------------------------- main

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
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))

  await stubConsole(page)
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 })
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

  await run1('G1 machine-status head and full-height executor panel share the middle column @1440x900', scenarioHeightChain)
  await run1('R1 zero pageerror across the journey', scenarioNoPageErrors, pageErrors)

  await ctx.browser.close()
  summarize()
}

run().catch(async (e) => {
  console.error('FATAL', e)
  process.exit(2)
})
