// sc_executor_entry_console.mjs — t260929-22 console 左栏执行器入口（灰盒 L3，真浏览器+隔离台+API 桩）。
//
// Intent（用户可感知行为；真源=notes/discussions/260927-project-executor-design.md §界面与命名 + 工单 scope①）：
//   E1 入口=项目名行本身：左栏一个项目一组，点**项目名行**（组头，不是组内某个图标）
//      → 中列打开该项目的执行器面板（面板带该项目的 project 标识）。
//   E2 （t261003-09 改写为退场负脸）顶部 Executor / Chat 切换器行整体退役——
//      两段锚与 tablist 形状不得再现；行移除后唯一面板视图保持挂载。
//   E3 设计负形：没有单独的「Tick 行」、没有单独「打开对话」按钮——入口就是项目名行
//      （E1 已证），左栏项目组内不得再出现第二个执行器入口形状。
//   E4 视图图标簇零残留（t261012-05 改写为退役负脸）：组内 .wb-view-icon 计数==0
//      且组头仍渲染——t261008-36 退役面不得回潮（板面唯一家=执行器面板内，归其 F5）。
//   E5 全旅程零 pageerror / console.error（渲染链卫生）。
//
// 分层与 intent 分工（防重复）：
//   - t260929-03-executor-panel-page 锁面板**页面内部**（五 tab/降级态/beep）——本场景
//     只锁 console 侧「怎么到达面板」，面板内容用桩页顶替（page.route），不复断页内。
//   - grants 上游与 400 文案归同票 sc_grants_upstream_400_text.mjs（节点半）。
//   - developer L1（sidebar 单测）不同层：本场景锁 payload→像素真渲染链。
//
// 执行契约（t260904-12 三态）：隔离台/playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 家族）；
// 入口未落地=FAIL 点名（TDD 期红属预期，anti-proof：pre-fix 树上 E1/E2/E3 红）。
// 红线：永不接触生产 console(3099)；台由 lib_stage_console 供给（每树一台）。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base

const PROJ = 'entryproj'          // 夹具项目 key（进面板 URL 断言）
const PROJ_NAME = 'Entry Project' // 夹具项目显示名（点它=入口）
const PANEL_STUB_MARKER = 'EXECUTOR_PANEL_STUB_OK'

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
  id: 't26092922a', role: 'developer', status: 'dispatched',
  title: 'Fixture ticket for entry regression', workflow: 'dev-lane',
  stage: 'implement', stage_state: 'running', handoff_count: 0, pending_count: 0,
  worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}

// ---------------------------------------------------------------- helpers

/** 关遮罩弹层（role=dialog 有钮点钮，无钮 Escape；t260925-18 同款纪律）。 */
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
  // 低位兜底（先注册=低优先）：一切放行到真实台——只桩本票契约面（projects/tickets/
  // watchdog status/面板页）。之前「未知 API 回 ok:true 空壳」会让 DocsSection 等
  // 消费方拿到错形数据直接崩槽（定点复跑实锤）——兜底绝不发明响应形状。
  await page.route('**/*', (route) => route.fallback())
  // 高位夹具桩（后注册=高优先）。
  await page.route('**/sandbar-workbench/api/wf/projects', (route) =>
    json(route, { ok: true, result: { projects: [{ key: PROJ, name: PROJ_NAME, dirs: [] }], quarantined: [] } }))
  await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/+$/, '')
    if (path === '/sandbar-workbench/api/wf/tickets') return json(route, { ok: true, result: { tickets: [FIXTURE_TICKET] } })
    return json(route, { ok: true, result: {} })
  })
  await page.route('**/sandbar-watchdog/api/status**', (route) => json(route, { ok: true, projects: [] }))
  // 面板 settings 桩=确定性 declared:false（夹具项目不声明守望者——声明是宿主动作，
  // out-of-scope 守卫）：Chat 分支必走「点名原因」提示，绝不触真实会话创建机器
  // （夹具项目无工作区，放行到真台会以 console.error 收场——闸红实锤）。
  await page.route('**/sandbar-executor-panel/api/settings**', (route) =>
    json(route, { ok: true, declared: false, enabled: false, executor_session: '', file: null }))
  // 面板页桩：只顶替面板页面本体（console 怎么到达它才是本场景对象），页内归 t260929-03。
  await page.route('**/sandbar-executor-panel/**', (route) => {
    const url = new URL(route.request().url())
    const proj = url.searchParams.get('project') ?? ''
    const html = `<!doctype html><html><body data-panel-project="${proj}"><div id="panel-stub">${PANEL_STUB_MARKER}:${proj}</div></body></html>`
    return route.fulfill({ contentType: 'text/html', body: html })
  })
}

/** 左栏夹具项目组头（项目名行）。锚 class 只为定位（rendering-side hook，
 *  t260925-18 同纪律：定位可以锚 class，断言不锚实现细节）。 */
async function projectRow(page) {
  const head = page.locator('.wb-group-head', { hasText: PROJ_NAME }).first()
  if (!(await waitFor(async () => (await head.count()) > 0, 12000))) return null
  return head
}

async function panelVisible(page, proj) {
  return waitFor(async () => {
    const txt = await page.evaluate(() => {
      const f = [...document.querySelectorAll('iframe')].find(f => /sandbar-executor-panel/.test(f.src || ''))
      return { iframeSrc: f?.src ?? '', body: document.body.textContent || '' }
    })
    if (proj) {
      if (txt.iframeSrc && /project=/.test(txt.iframeSrc) && decodeURIComponent(txt.iframeSrc).includes(proj)) return true
      return txt.body.includes(`${PANEL_STUB_MARKER}:${proj}`)
    }
    return !!(txt.iframeSrc || txt.body.includes(PANEL_STUB_MARKER))
  }, 8000)
}

// ---- E1 入口=项目名行

async function scenarioEntryOpensPanel(page) {
  const head = await projectRow(page)
  if (!head) return `project group row for "${PROJ_NAME}" not rendered in left column (projects stub not consumed?)`
  // 点入口段本体（data-wb-executor-entry=developer 声明的测试锚，覆盖名字+计数+空档）。
  // gen2 起行 onClick 收进入口段（行体其余是死区）——按锚点击=按用户点项目名的语义。
  const entry = page.locator('[data-wb-executor-entry]').first()
  if (!(await entry.count())) return 'executor entry anchor not rendered on the project row'
  await entry.click({ force: true, timeout: 8000 })
  if (!(await panelVisible(page, PROJ))) {
    return `clicking the project-name row did not open the executor panel for ${PROJ} @ ${await snap(page)}`
  }
  return null
}

// ---- E2 Executor / Chat 切换器（t261003-09 改写：切换器行退场——原「双向翻」正脸
// 已随 t261003-09 缺陷③退役：该行整体移除，恰一个入口=Overview 里的打开会话按钮。
// 本条改锁退场负脸：两段锚、tablist 形状都不得再出现，面板保持挂载不动）。

async function scenarioSwitcherFlips(page) {
  const neg = await page.evaluate(() => ({
    segs: document.querySelectorAll('[data-wb-executor-seg],[data-wb-chat-seg]').length,
    tablists: [...document.querySelectorAll('[role="tablist"]')].filter(t => /executor/i.test(t.getAttribute('aria-label') || '')).length,
    frames: [...document.querySelectorAll('iframe')].filter(f => /sandbar-executor-panel/.test(f.src || '')).length,
  }))
  if (neg.segs !== 0) return `switcher segments still present after t261003-09 removal (${neg.segs} seg anchors)`
  if (neg.tablists !== 0) return 'a tablist labelled Executor still present in the executor view (tab row must not be reintroduced)'
  if (neg.frames === 0) return 'executor panel iframe not mounted (row removal must not drop the single panel view)'
  return null
}

// ---- E3 设计负形：无第二入口

async function scenarioNoSeparateEntry(page) {
  const m = await page.evaluate((projName) => {
    const heads = [...document.querySelectorAll('.wb-group-head')]
    const head = heads.find(h => (h.textContent || '').includes(projName))
    const group = head?.parentElement
    return {
      hasGroup: !!group,
      groupText: (group?.textContent || ''),
      // 组内可点击行数（组头 + 工单行……第二入口若存在会以行/按钮形状出现）
      clickables: group ? group.querySelectorAll('button, [role="button"], .wb-card, .wb-group-head').length : -1,
    }
  }, PROJ_NAME)
  if (!m.hasGroup) return `project group for ${PROJ_NAME} disappeared (view state lost?)`
  if (/open\s+(the\s+)?(executor|panel|conversation)/i.test(m.groupText)) {
    return 'design ban: a separate "open conversation/panel" affordance appeared inside the project group'
  }
  if (/(^|\W)tick(\W|$)/i.test(m.groupText)) {
    return 'design ban: a separate Tick row appeared inside the project group'
  }
  return null
}

// ---- E4 视图图标簇零残留（t261012-05 改写：t261008-36/gen4 宿主令退役了五视图
// 图标簇——"one face, one home; no second door"，组头只剩 caret+身份点+执行器入口；
// 板面唯一家=执行器面板内部，图标缺席面归 t261008-36 F5 钉死。本子用例与其同向：
// 断夹具项目组内 .wb-view-icon 计数==0 且组头本体仍渲染——退役面不得回潮，
// 也不能因改写而放松组头渲染链的可见性。）

async function scenarioBoardIconStillWorks(page) {
  const head = await projectRow(page)
  if (!head) return 'project row not rendered (cannot run retirement leg)'
  const icons = await head.locator('.wb-view-icon').count()
  if (icons !== 0) {
    return `${icons} .wb-view-icon element(s) inside the project row — the view-icon cluster was retired by t261008-36 and must not reappear`
  }
  return null
}

// ---- E5 渲染链卫生

// t261012-05: URL-aware hygiene exemption (precedent: baselines/sc_ticket_session_restore.mjs
// S9 ghost-row exemption). The shared stage registry does not hold every
// host-registry project, so the engine-channel endpoints answer 4xx/502 for
// them (/wf/concurrency, host-shell /sessions) and the browser logs the failed
// resource load. That is stage provisioning, not this ticket's entry face; the
// dropped entries are counted and reported by the caller as a named env leg.
const STAGE_CHANNEL = /\/(api\/wf\/concurrency|sessions)(\?|$)/
function scenarioHygiene(pageErrors, consoleErrors) {
  if (pageErrors.length) return `pageerror(s): ${JSON.stringify(pageErrors.slice(0, 3))}`
  const real = consoleErrors.filter((t) => !(STAGE_CHANNEL.test(t) && /Failed to load resource/.test(t)))
  if (real.length) return `console.error(s): ${JSON.stringify(real.slice(0, 3))}`
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

  const bctx = await ctx.browser.newContext()
  const pageErrors = []
  const consoleErrors = []
  const page = await bctx.newPage()
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200) + ' @' + (m.location()?.url || '').split('/').pop() + ':' + (m.location()?.lineNumber ?? '?')) })

  await stubConsole(page)
  // domcontentloaded（networkidle 在轮询型 console 上不可收敛——闸红归因：导航超时）；
  // 遮罩收口（Internal Testing Notice aria-modal 使 #root inert——不关它所有点击全被拦）。
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await dismissOverlays(page)
  await page.waitForTimeout(3000)
  await dismissOverlays(page)

  const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
  const run1 = async (name, fn) => {
    try {
      const err = await fn(page)
      if (err) record(name, 'fail', err)
      else record(name, 'pass')
    } catch (e) { await failWith(name, e) }
  }

  await run1('E1 project-name row opens the executor panel', scenarioEntryOpensPanel)
  await run1('E2 Executor/Chat switcher flips both ways', scenarioSwitcherFlips)
  await run1('E3 no separate Tick row / open-conversation button', scenarioNoSeparateEntry)
  await run1('E4 view-icon cluster stays retired (zero in project group)', scenarioBoardIconStillWorks)
  await run1('E5 zero pageerror / console.error', () => scenarioHygiene(pageErrors, consoleErrors))
  {
    const dropped = consoleErrors.filter((t) => STAGE_CHANNEL.test(t) && /Failed to load resource/.test(t))
    if (dropped.length) record('E5a stage-channel face', 'env_fail',
      `${dropped.length} x failed resource load on engine-channel endpoints (exempted by name: /api/wf/concurrency, /sessions) — stage registry does not hold every host project`)
  }

  await bctx.close().catch(() => {})
  await ctx.browser.close().catch(() => {})
  summarize()
}

await run()
