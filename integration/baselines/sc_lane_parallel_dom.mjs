// lane-parallel-dom —— t260901-09「并行段泳道图 DOM 级双边同亮断言」.
//
// Intent (black-box, user perspective): t260901-05 shipped the lane diagram's
// parallel-fork rendering (single pointer -> active-step array, src/client/
// lane-states.ts) plus DATA-level baselines (lane-parallel-states.mjs). What no
// baseline covered yet is the RENDERING level: that in a real browser DOM both
// parallel branches are lit simultaneously. This baseline opens the shipped
// bundle in a real browser and asserts the DOM contract:
//   - parallel phase: exactly 2 .wb-d2-step[data-s="running"] in one render
//     frame, one per branch, both icon ▶, each carrying the parallel (∥) peer
//     marker whose hover title cross-references the other branch;
//   - status line reports "并行分叉中" with both branch names (text/image split
//     regression gate);
//   - single-running regression: exactly 1 lit step, no ∥, no parallel text;
//   - fallback (no timeline): single-pointer semantics, 1 lit step;
//   - malformed timeline (missing fields / template-external ids): no crash,
//     no extra lit steps, zero pageerror.
//
// Two layers (same split as session-tab-interactions.mjs):
//   S0 build-contract (pure node, runs everywhere): shipped twin bundles in
//      sync + parallel render anchors present + deriveStageStates smoke-run
//      against a parallel fixture (data source on disk and wired).
//   S1 browser DOM assertions (real rendering level): needs the ISOLATED test
//      console (SANDBAR_TEST_CONSOLE, default 127.0.0.1:3199), playwright-core
//      resolvable, and a launchable chromium. Any missing -> ENV_FAIL (exit 2)
//      with the reason on stdout). Data is stubbed at the API boundary with
//      page.route(): the browser, console, shipped bundle and React render
//      path are all real; only GET /sandbar-workbench/api/wf/tickets[/<id>] is
//      intercepted (fixture snapshots, same shape lane-parallel-states.mjs F4
//      consumes). Never touches production console (3099) nor real tickets.
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 或全腿 na -> exit 1;
// env_fail>0 -> exit 2. Node >= 22.18.

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;
const FID = 't26090109dom' // fixture ticket id (alnum only; never a real ticket)

const results = [] // { name, status: 'pass'|'fail'|'env_fail'|'na', detail }
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na']);
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length;
  const e = results.filter(r => r.status === 'env_fail').length;
  const n = results.filter(r => r.status === 'na').length;
  const f = results.filter(r => r.status === 'fail').length;
  const allNa = results.length > 0 && n === results.length;
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
}

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const LANE_STATES = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'lane-states.ts')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return false
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return false
  }
  const anchors = ['wb-d2-step', 'data-s=', 'wb-d2-par', '并行分叉中', 'deriveStageStates']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 build-contract', 'fail', `shipped bundle missing parallel-render anchors: ${missing.join(', ')}`)
    return false
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync, all parallel anchors present')
  return true
}

async function dataSourceSmoke() {
  if (!existsSync(LANE_STATES)) {
    record('S0 data-source', 'fail', 'lane-states.ts missing')
    return false
  }
  try {
    const mod = await import(pathToFileURL(LANE_STATES).href + '?t=' + Date.now())
    if (typeof mod.deriveStageStates !== 'function') {
      record('S0 data-source', 'fail', 'lane-states.ts does not export deriveStageStates')
      return false
    }
    const d = {
      status: 'dispatched', stage: 'design_integration_tests', stage_state: 'running',
      results: { create_plan: { status: 'ok', gen: 0 }, review_plan: { status: 'ok', gen: 0 } },
      timeline: [
        { at: 't', stage: 'create_plan', state: 'running', reason: '' },
        { at: 't', stage: 'review_plan', state: 'running', reason: '' },
        { at: 't', stage: 'implement', state: 'running', reason: '' },
        { at: 't', stage: 'design_integration_tests', state: 'running', reason: '' },
      ],
    }
    const out = mod.deriveStageStates(d, ['create_plan', 'review_plan', 'implement', 'design_integration_tests'])
    const states = out.states ?? out
    const active = out.active ?? Object.keys(states).filter(k => states[k] === 'running')
    if (states.implement !== 'running' || states.design_integration_tests !== 'running'
      || active.length !== 2 || states.create_plan !== 'done') {
      record('S0 data-source', 'fail', `parallel fixture not double-lit: ${JSON.stringify(states)}`)
      return false
    }
    record('S0 data-source', 'pass', 'deriveStageStates double-lights the parallel fixture')
    return true
  } catch (e) {
    record('S0 data-source', 'fail', `lane-states.ts not importable: ${String(e).slice(0, 120)}`)
    return false
  }
}

// ---------------------------------------------------------------- S1 fixtures

const WF = {
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
    { id: 'review_plan', name: '审方案', role: 'integration', parts: ['agent'] },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
    { id: 'design_integration_tests', name: '设计集成测试', role: 'integration', parts: ['agent'] },
    { id: 'run_integration_tests', name: '跑集成测试', role: 'integration', parts: ['script'] },
    { id: 'arbitrate', name: '仲裁', role: 'integration', parts: ['agent', 'script'] },
    { id: 'acceptance_walkthrough', name: '验收走查', role: 'integration', parts: ['agent', 'script'] },
    { id: 'merge_check', name: '合并检查', role: 'integration', parts: ['script'] },
    { id: 'merge', name: '合并', role: 'integration', parts: ['human'] },
    { id: 'suggest_next', name: '建议下一单', role: 'integration', parts: ['script'] },
  ],
}
const ROW = {
  id: FID, role: 'developer', status: 'dispatched', title: '并行渲染 DOM 打桩工单',
  workflow: 'dev-lane', stage: 'design_integration_tests', stage_state: 'running',
  handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}

const T = '2026-09-01T00:00:00'
const tle = (stage, state, reason = '') => ({ at: T, stage, state, reason })

/** Detail fixture. Mirrors lane-parallel-states.mjs F4 semantics: completed
 *  steps carry results (gen 0) + a running timeline entry; parallel branches
 *  carry a running entry with no done signal. */
function detailBase(over) {
  return {
    id: FID, title: ROW.title, workflow_id: 'dev-lane', epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'design_integration_tests', stage_state: 'running', stage_name: '设计集成测试',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [], body: 'DOM 级渲染打桩（不进 Temporal）', write_set: [],
    timeline: [], ...over,
  }
}

// P1 parallel fork: both branches lit.
const DETAIL_PARALLEL = detailBase({
  results: { create_plan: { status: 'ok', gen: 0 }, review_plan: { status: 'ok', gen: 0 } },
  timeline: [tle('create_plan', 'running'), tle('review_plan', 'running'),
    tle('implement', 'running'), tle('design_integration_tests', 'running')],
})
// P2 single running branch (implement already done): regression control.
const DETAIL_SINGLE = detailBase({
  results: { create_plan: { status: 'ok', gen: 0 }, review_plan: { status: 'ok', gen: 0 },
    implement: { status: 'ok', gen: 0 } },
  timeline: [tle('create_plan', 'running'), tle('review_plan', 'running'),
    tle('implement', 'running'), tle('design_integration_tests', 'running')],
})
// P3 fallback: no timeline at all -> single-pointer semantics.
const DETAIL_FALLBACK = detailBase({
  stage: 'implement', stage_name: '实现', timeline: null,
  results: { create_plan: { status: 'ok', gen: 0 } },
})
// P4 malformed timeline: missing fields + non-string fields + template-external
// phase id (parallel_impl_design) must be dropped, not crash, not light up.
const DETAIL_MALFORMED = detailBase({
  results: { create_plan: { status: 'ok', gen: 0 }, review_plan: { status: 'ok', gen: 0 } },
  timeline: [
    { at: T },                                   // missing stage/state
    { at: T, stage: 123, state: 'running' },     // non-string fields
    tle('parallel_impl_design', 'running'),      // phase id, not a template stage
    tle('create_plan', 'running'), tle('review_plan', 'running'),
    tle('implement', 'running'), tle('design_integration_tests', 'running'),
  ],
})

// ---------------------------------------------------------------- S1 infra (precedent: session-tab-interactions.mjs)

function consoleHealthy() {
  // Same semantics as the precedent: GET / with a 5s timeout, r.ok decides.
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) })
    .then(r => r.ok)
    .catch(() => false)
}

function mainRepoRoot() {
  // node_modules never travels with git worktrees; resolve the main checkout
  // via the gitfile so playwright-core can be found there.
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree — cwd is the main checkout */ }
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
    try { return await import(c) } catch { /* next candidate */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

// First-run dialogs intercept pointer events on fresh contexts (full rationale
// in session-top-entry.mjs dismissOverlays — same fault mode applies here).
async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await p.keyboard.press('Escape').catch(() => {})
    await p.waitForTimeout(600)
  }
}

// ---------------------------------------------------------------- S1 scenarios

/** DOM snapshot helpers (run in page context). */
const domLitSteps = `(() => {
  const steps = [...document.querySelectorAll('.wb-d2-steps .wb-d2-step')];
  return steps.map(el => ({
    id: (el.getAttribute('title') || '').split(' · ')[0],
    s: el.getAttribute('data-s'),
    ico: (el.querySelector('.ico')?.textContent || '').trim(),
    par: el.querySelector('.wb-d2-par') !== null,
    parTitle: el.querySelector('.wb-d2-par')?.getAttribute('title') || '',
  }));
})()`
const domStatusText = `(() => {
  const el = document.querySelector('.wb-d2-status');
  return el ? el.textContent : null;
})()`
const domStepCount = `document.querySelectorAll('.wb-d2-steps .wb-d2-step').length`

function litOf(list, id) { return list.find(x => x.id === id && x.s === 'running') }

async function openFixtureDetail(page, snap) {
  // Close any open drawer first: the detail drawer is a full-screen overlay
  // (above the board), so a real user — and this probe — must close it before
  // clicking another row (t260901-15 acceptance revision; the overlay already
  // existed when this baseline was authored, but S1 had never actually run
  // against a live console until t260901-15).
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
  // Click the fixture row again so openDetail refetches through the route stub.
  const row = page.locator('tr.wb-row', { hasText: FID }).first()
  if (!(await waitFor(async () => (await row.count()) > 0, 8000))) {
    throw new Error('fixture row not rendered (list stub not consumed?)')
  }
  await row.click()
  const ok = await waitFor(async () => (await page.locator('.wb-d2-steps').count()) > 0, 8000)
  if (!ok) throw new Error('stepper not rendered after row click')
  // Snapshots MUST be evaluated one expression at a time: evaluate() stringifies
  // an array argument via Array#toString into a comma expression and returns
  // only the LAST value (verified against playwright-core 1.62) — the historical
  // `page.evaluate([a, b])` made every S1 scenario fail with "steps.filter is not
  // a function" the first time S1 actually ran (t260901-15 acceptance).
  const first = await page.evaluate(snap[0])
  return snap.length > 1 ? [first, await page.evaluate(snap[1])] : [first]
}

async function scenarioDoubleLit(page) {
  const [steps, status] = await openFixtureDetail(page, [domLitSteps, domStatusText])
  const lit = steps.filter(x => x.s === 'running')
  if (lit.length !== 2) return `expected 2 lit steps, got ${lit.length}: ${JSON.stringify(steps)}`
  if (!litOf(steps, 'implement') || !litOf(steps, 'design_integration_tests')) {
    return `lit steps are not implement+design: ${JSON.stringify(lit.map(x => x.id))}`
  }
  if (!lit.every(x => x.par)) return `parallel peer marker (∥) missing on a lit step: ${JSON.stringify(lit)}`
  // t260901-09 方案契约：running 步图标均为 ▶，∥ hover 文案互指对方（name 口径）。
  if (!lit.every(x => x.ico === '▶')) return `running step icon not ▶: ${JSON.stringify(lit.map(x => x.ico))}`
  const impl = lit.find(x => x.id === 'implement'), dsgn = lit.find(x => x.id === 'design_integration_tests')
  if (!impl.parTitle.includes('设计集成测试') || !dsgn.parTitle.includes('实现')) {
    return `∥ hover titles do not cross-reference peers: implement="${impl.parTitle}" design="${dsgn.parTitle}"`
  }
  if (!status || !status.includes('并行分叉中')) return `status line missing 并行分叉中: ${JSON.stringify(status)}`
  if (!status.includes('实现') || !status.includes('设计集成测试')) {
    return `status line missing both branch names: ${JSON.stringify(status)}`
  }
  return null
}

async function scenarioSingleLit(page) {
  const [steps, status] = await openFixtureDetail(page, [domLitSteps, domStatusText])
  const lit = steps.filter(x => x.s === 'running')
  if (steps.length !== 10) return `stepper should render all 10 template stages, got ${steps.length}`
  if (lit.length !== 1 || !litOf(steps, 'design_integration_tests')) {
    return `expected exactly 1 lit step (design), got: ${JSON.stringify(steps)}`
  }
  if (steps.some(x => x.par)) return '∥ marker present in single-running state'
  if (status && status.includes('并行分叉中')) return `status line wrongly reports parallel: ${JSON.stringify(status)}`
  return null
}

async function scenarioFallback(page) {
  const [steps] = await openFixtureDetail(page, [domLitSteps])
  const lit = steps.filter(x => x.s === 'running')
  if (steps.length !== 10) return `stepper should render all 10 template stages, got ${steps.length}`
  if (lit.length !== 1 || !litOf(steps, 'implement')) {
    return `fallback expected exactly 1 lit step (implement), got: ${JSON.stringify(steps)}`
  }
  return null
}

async function scenarioMalformed(page) {
  const [steps] = await openFixtureDetail(page, [domLitSteps])
  if (steps.length !== 10) {
    return `malformed timeline leaked extra steps (expect 10): ${JSON.stringify(steps.map(x => x.id))}`
  }
  const lit = steps.filter(x => x.s === 'running')
  if (lit.length !== 2 || !litOf(steps, 'implement') || !litOf(steps, 'design_integration_tests')) {
    return `malformed timeline broke double-lit: ${JSON.stringify(steps)}`
  }
  return null
}

/** Failure-scene snapshot (precedent snap()/failWith): what is on the page now. */
async function snap(p) {
  try {
    const steps = await p.evaluate(domLitSteps)
    const dialogs = await p.locator('[role="dialog"]').count()
    const status = await p.evaluate(domStatusText)
    return `steps=${JSON.stringify(steps).slice(0, 200)} dialogs=${dialogs} status=${JSON.stringify(status)?.slice(0, 80)}`
  } catch { return '(snapshot unavailable)' }
}

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const consoleErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await dismissOverlays(page)

    // API-boundary stub: list/detail carry fixtures; sub-routes and unknown ids
    // answer ok:false so nothing reaches Temporal for the fixture id.
    // 注意 glob 尾必须是 **：playwright 单 * 编译为 [^/]*（不跨 /，实测
    // globToRegexPattern），tickets* 拦不到 tickets/<id> 详情——整份 fixture 会
    // 漏到真控制台，P1-P4 在隔离台必红。
    let currentDetail = DETAIL_PARALLEL
    let listMalformed = false
    await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
      if (path === '/sandbar-workbench/api/wf/tickets') {
        if (listMalformed) return route.fulfill({ contentType: 'application/json', body: '{' })
        return body({ ok: true, result: { tickets: [ROW] }, workflows: [WF] })
      }
      const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && decodeURIComponent(m[1]) === FID) return body({ ok: true, result: currentDetail })
      return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
    })

    // Open the ticket board via the first project group's 📋 (workbench needs a
    // projectKey before it renders the ticket list).
    const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
    if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `no project group 📋 found on ${BASE} (console not provisioned for board view)`)
      return
    }
    await boardIcon.click()
    const rowOk = await waitFor(async () =>
      (await page.locator('tr.wb-row', { hasText: FID }).count()) > 0, 10000)
    if (!rowOk) {
      record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
      return
    }

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
    const run = async (name, fn) => {
      try {
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
    }

    await run('P1 parallel double-lit', scenarioDoubleLit)
    currentDetail = DETAIL_SINGLE
    await run('P2 single-running regression', scenarioSingleLit)
    currentDetail = DETAIL_FALLBACK
    await run('P3 no-timeline fallback', scenarioFallback)
    currentDetail = DETAIL_MALFORMED
    await run('P4 malformed timeline tolerated', scenarioMalformed)

    // P5: malformed list payload — must surface as a board error, never crash.
    // t260903-06 验收更新：轮询优雅降级合同（工单需求③）取代旧口径「单次失败
    // 立即红条」。新旅程四拍：①首轮失败静默——滞后角标在位、.wb-err 不得出现；
    // ②连败第 2 拍仍在静默窗；③连续 3 次失败错误态如期浮现（错误可感知、不崩）；
    // ④恢复健康数据后红条/角标清零（不粘滞，30s 慢轮询节拍内自愈）。
    currentDetail = DETAIL_PARALLEL
    listMalformed = true
    try {
      await page.reload({ waitUntil: 'networkidle' })
      await page.waitForTimeout(2500)
      await dismissOverlays(page)
      await boardIcon.click().catch(() => {})
      // ① 静默窗（failStreak=1）：角标在位、无红条
      const badgeShown = await waitFor(async () =>
        (await page.locator('.wb-sub', { hasText: '数据可能滞后' }).count()) > 0, 10000)
      const earlyErr = (await page.locator('.wb-err').count()) > 0
      // ② 连败第 2 拍（+4s < 第 3 拍 ~10s）：仍在静默窗
      await page.waitForTimeout(4000)
      const stillSilent = (await page.locator('.wb-err').count()) === 0
      // ③ 阈值（第 3 次连败）：红条浮现
      const errShown = await waitFor(async () =>
        (await page.locator('.wb-err').count()) > 0, 25000)
      if (!badgeShown || earlyErr || !stillSilent || !errShown) {
        record('P5 malformed list payload', 'fail',
          `degrade journey broken: badge=${badgeShown} earlyErr=${earlyErr} ` +
          `stillSilent=${stillSilent} thresholdErr=${errShown} @ ${await snap(page)}`)
      } else {
        // ④ 恢复：健康列表回归，红条与角标清零
        listMalformed = false
        const errGone = await waitFor(async () =>
          (await page.locator('.wb-err').count()) === 0, 60000)
        const badgeGone = await waitFor(async () =>
          (await page.locator('.wb-sub', { hasText: '数据可能滞后' }).count()) === 0, 10000)
        if (errGone && badgeGone) record('P5 malformed list payload', 'pass')
        else record('P5 malformed list payload', 'fail',
          `recovery stuck: errGone=${errGone} badgeGone=${badgeGone} @ ${await snap(page)}`)
      }
    } catch (e) { await failWith('P5 malformed list payload', e) }
    listMalformed = false

    const hygieneDetail = `pageerrors=${pageErrors.length} consoleErrors=${consoleErrors.length}` +
      (pageErrors.length ? ` first=${pageErrors[0]}` : '') + (consoleErrors.length ? ` firstConsole=${consoleErrors[0]}` : '')
    if (pageErrors.length === 0 && consoleErrors.length === 0) {
      record('P6 zero pageerror/console.error', 'pass')
    } else {
      record('P6 zero pageerror/console.error', 'fail', hygieneDetail)
    }
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

async function main() {
  const [maj, min] = process.versions.node.split('.').map(Number)
  if (maj < 22 || (maj === 22 && min < 18)) {
    record('node', 'env_fail', `node ${process.versions.node} < 22.18`)
    return summarize()
  }

  const s0ok = buildContract()
  if (s0ok) await dataSourceSmoke()

  if (BASE.includes(':3099')) {
    console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)')
    process.exit(1)
  }

  const healthy = await consoleHealthy()
  if (!healthy) {
    record('S1 precheck', 'env_fail', `test console unreachable at ${BASE} (docker compose -f server/docker-compose.test.yml up -d)`)
    return summarize()
  }
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 precheck', 'env_fail', 'playwright-core not resolvable (browser scenarios not run: env)')
    return summarize()
  }
  const browser = await launchBrowser(pw)
  if (!browser) {
    record('S1 precheck', 'env_fail', 'no browser could be launched')
    return summarize()
  }

  // Terminal-state matrix: normal completion, scenario failure, SIGINT/SIGTERM.
  let exiting = false
  const shutdown = async (code) => {
    if (exiting) return
    exiting = true
    await browser.close().catch(() => {})
    process.exit(code)
  }
  process.on('SIGINT', () => { void shutdown(130) })
  process.on('SIGTERM', () => { void shutdown(143) })
  try {
    await runBrowser(pw, browser)
  } finally {
    if (!exiting) await browser.close().catch(() => {})
  }
  summarize()
}

main().catch(e => { console.error(String(e)); summarize() })
