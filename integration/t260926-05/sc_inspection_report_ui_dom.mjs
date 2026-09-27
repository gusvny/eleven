// sc_inspection_report_ui_dom.mjs — t260926-05 巡检票详情「报告面全量可读」DOM 对拍
// （宿主单 260926：详情页报告曾整页 [object Object]、findings 九字段只渲染四——本条守修复后的用户可感知面）。
//
// Intent (black-box, user perspective)：宿主打开一张带 findings 的巡检票详情抽屉——
//   L1 findings 全字段可读：每条 finding 以自身英文标签渲染
//      (Severity / Scan / Confidence / Verified / Subject / Why / Suggestion)，
//      evidence 逐条以 path:line + 引文呈现——数据不译；
//   L2 畸形 finding 不炸页：finding 形状未知（字符串/对象套对象字段/数组）时页面
//      不崩、可读回落文案在场、抽屉全文零 '[object Object]'；
//   L3 套件证据段：ran/passed/failed 计数、阶段墙钟、suite_timeout、
//      late-receipt 告警各自带英文标签可读（inspection-suite 段）；
//   L4 report_path 亲和物：路径以可读文本在场，「打开报告摘要」动作渲染出
//      可读摘要内容（桩端点供数），零 '[object Object]'、零裸对象倾倒；
//   L4b 摘要端点失败→显式降级文案（绝不静默空白）；
//   P 卫生子用例：全旅程零 pageerror / console.error。
//
// 分工（防 intent 级重复）：t260916-05-inspection-detail-lane-map-dom 守泳道图/
// 拓扑/降级锚；t260916-05-topology-receipt 守查询回执数据半（其 T3 守查询边界
// 畸形，本条守渲染侧畸形——不重复）；t260915-08 守板面巡检行/签字通道；
// t260915-08-inspection-face（developer L1）守 face 静态形状。
// 本条独占「报告面渲染完整性 + 安全文本契约」面。
//
// 数据全桩：list/detail/workflows + 本票新增 inspection-report 摘要端点均
// page.route 拦截；浏览器/bundle/React 全真，引擎不需要。
//
// Two layers（t260916-05 家族切法）：
//   S0 build-contract（纯 node）：双 bundle 同步 + 渲染锚在 bundle +
//      inspection-report-model.ts 纯模型冒烟（畸形 suite/finding 不炸、零 [object Object]）；
//   S1 browser DOM：隔离测试台（SANDBAR_TEST_CONSOLE，3099 红线零接触）＋
//      playwright-core＋chromium，任一缺席=ENV_FAIL exit 2。
//
// Execution contract (t260904-12 three-state)：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全 na → exit 1；
// env_fail>0 → exit 2。Node >= 22.18。
// 实现段落地前红属预期（TDD 信号：L1~L4 红=渲染面未接线；S0 的 bundle 双同步
// 应即绿、模型冒烟红=模型未落地），arbitrate/merge 期必须绿。

import { ensureStageConsole } from '../lib_stage_console.mjs'
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve, dirname } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

// 仓库根解析：爬根找 CLAUDE.md（KI-075 族——禁宿主绝对路径、禁裸 process.cwd）。
const REPO = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 8; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根（爬根 8 层无 CLAUDE.md）')
})()

const FID = 't26092605ui' // fixture ticket id（alnum only；绝不真票）

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
  results.push({ name, status, detail })
  const tag = status === 'pass' ? 'ok' : status.toUpperCase()
  console.log(`${tag} ${name}${detail ? ' — ' + detail : ''}`)
}
function summarize() {
  const n = (s) => results.filter(r => r.status === s).length
  const p = n('pass'), f = n('fail'), e = n('env_fail'), na = n('na')
  for (const r of results) {
    if (r.status !== 'pass') console.log(`  ${r.status}: ${r.name} — ${r.detail}`)
  }
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${na}`)
  process.exit(f > 0 || (p + f + e === 0) ? 1 : e > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- 契约夹具
// findings 九字段（引擎 finding 形状契约）：id/scan/severity/confidence/verified/
// subject/why/suggestion/evidence[{path,line,quote}]。数据中文=数据不译规则的证据面。
const FINDING_FULL = {
  id: 'f1', scan: 'deadman', severity: 'high', confidence: 0.92, verified: true,
  subject: '套件档墙钟超预算',
  why: 'supply_used_sec 743 > run_budget_sec 600，晚收据通道已触发。',
  suggestion: '复核 supply_timeout_sec 配置并补跑该期套件。',
  evidence: [
    { path: 'server/engine/inspection_deadman.py', line: 371, quote: 'supply_used_sec = now - supply_start' },
    { path: 'notes/debts/known-issues.md', line: 12, quote: '在本仓追加' },
  ],
}
// 畸形形态三支：字符串体、对象套对象字段、数组体——渲染侧必须可读回落不炸。
const FINDING_MALFORMED = [
  'raw-string-finding',
  { severity: { level: 'med' }, evidence: [{ path: { deep: true } }], subject: ['nested', 'array'] },
  ['array', 'finding'],
]
const FINDING_OK_PLAIN = {
  id: 'f3', scan: 'test', severity: 'low', subject: '低危样例', evidence: 'ev-low', suggestion: '留意',
}

const SUITE_FULL = {
  ok: false, ran: 88, passed: 85, failed: 3, env_fail: 0,
  wall_seconds: 641, supply_used_sec: 743, runner_used_sec: 120,
  run_budget_sec: 600, supply_timeout_sec: 900, suite_timeout_sec: 1800, suite_timeout: false,
  late: true, late_error: 'receipt arrived 95s after budget window',
  worktree: '/repo/.lane/inspection-x', base_ref: 'main',
  report_path: 'out/inspection/inspection-fixture-20260926.json',
  blockers: [], cases: [{ name: 'tests/a.py::t1', exit: 0 }, { name: 'tests/b.py::t2', exit: 1 }],
}

const REPORT_JSON = {
  instance_id: 'fixture', period: '20260926', red_line: '巡检只出报告与开票建议，绝不直接改码。',
  summary: { high: 1, med: 0, low: 1 }, findings: [FINDING_FULL],
  suite: SUITE_FULL,
  nested_unknown: { a: { b: { c: ['x', 2, null] } } },
}

const ROW = {
  id: FID, kind: 'inspection', engine: 'inspection', project: '', epic: '',
  title: '巡检报告面 DOM 桩 · 期 20260926', template: 'inspection-lite',
  instance_id: 'fixture', period: '20260926', stage: 'report', stage_state: 'running',
  status: 'running', decision: '', findings: { high: 1, med: 0, low: 1, total: 2 },
  heartbeat: true, report_path: 'out/inspection/inspection-fixture-20260926.json',
  awaiting_gate: false, human_gate: null, blocked_reason: '', gate_error: '',
  created: 1789526400, updated: '09-26 08:00', updated_ts: 1789526400,
  paused: false, paused_phase: '', handoff_count: 0, pending_count: 0,
  worktree: '', workspace: null, role: null, proposal_id: '', workflow: '',
  close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
}

const tle = (stage, state, reason = '') => ({ at: '2026-09-26T08:00:00', stage, state, reason })

function insDetail(over) {
  return {
    id: FID, kind: 'inspection', engine: 'inspection', template: 'inspection-lite',
    title: ROW.title, stage: 'report', stage_state: 'running', status: 'running',
    decision: '', gate_id: 'inspection-close', instance_id: 'fixture', period: '20260926',
    report_path: ROW.report_path, red_line: '巡检只出报告与开票建议，绝不直接改码。',
    heartbeat: true, summary: { high: 1, med: 0, low: 1 },
    findings: [FINDING_FULL, FINDING_OK_PLAIN],
    suggested_fix_tickets: [], blocked_reason: '', human_gate: null, gate_error: '',
    worktree: '', workspace: null, results: {},
    suite: SUITE_FULL,
    budget_note: 'supply 743s/600s budget — over by 143s',
    heartbeat_note: 'deadman heartbeat alive at 08:00',
    scan_meta: { scans: ['deadman', 'test'], generated_at: '2026-09-26T08:00:00' },
    timeline: [tle('setup', 'running'), tle('suite', 'running'), tle('inspect', 'running'), tle('report', 'running')],
    ...over,
  }
}

const DETAIL_FULL = insDetail()
// L2：findings 混入畸形形态（同一详情面，页面不得崩、不得 [object Object]）
const DETAIL_MALFORMED = insDetail({ findings: [FINDING_FULL, ...FINDING_MALFORMED, FINDING_OK_PLAIN] })

// API 桩状态（路由桩闭包与 applyLeg 共读共写）。
let currentDetail = null
let currentReport = REPORT_JSON
let reportStubMode = 'ok' // ok | broken（摘要端点失败回落路径）

// ---------------------------------------------------------------- S0 build-contract
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const MODEL_TS = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'inspection-report-model.ts')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return
  }
  const anchors = ['inspection-suite', 'inspection-report', 'inspection-face-rows', 'inspection-findings-list']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 build-contract', 'fail', `shipped bundle missing report-face anchors: ${missing.join(', ')}`)
    return
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync, report-face anchors present')
}

async function modelSmoke() {
  if (!existsSync(MODEL_TS)) {
    record('S0 report-model', 'fail', 'inspection-report-model.ts missing（纯模型模块未落地）')
    return
  }
  try {
    const mod = await import(pathToFileURL(MODEL_TS).href + '?t=' + Date.now())
    const names = ['suiteSectionView', 'findingView', 'reportDigest', 'asText']
    const missing = names.filter(n => typeof mod[n] !== 'function')
    if (missing.length) {
      record('S0 report-model', 'fail', `inspection-report-model.ts missing exports: ${missing.join(', ')}`)
      return
    }
    // 畸形面冒烟：任何畸形形状输出零 [object Object] 且不抛。
    const probes = [
      () => mod.suiteSectionView(null), () => mod.suiteSectionView('garbage'),
      () => mod.suiteSectionView({ ran: 'x', cases: [{ name: { deep: 1 } }] }),
      () => mod.findingView('raw-string'), () => mod.findingView(['a', { b: { c: 1 } }]),
      () => mod.findingView({ severity: { level: 'med' }, evidence: [{ path: { deep: true } }] }),
      () => mod.reportDigest('scalar'), () => mod.reportDigest([{ n: [{ m: { deep: 1 } }] }]),
    ]
    for (const p of probes) {
      const out = JSON.stringify(p() ?? '')
      if (out.includes('[object Object]')) {
        record('S0 report-model', 'fail', 'model output contains [object Object] for malformed shape')
        return
      }
    }
    record('S0 report-model', 'pass', 'model consumes malformed shapes: no throw, no [object Object]')
  } catch (e) {
    record('S0 report-model', 'fail', `inspection-report-model.ts not importable: ${String(e).slice(0, 140)}`)
  }
}

// ---------------------------------------------------------------- S1 infra（家族同款）
function consoleHealthy(base) {
  return fetch(`${base}/`, { signal: AbortSignal.timeout(5000) }).then(r => r.ok).catch(() => false)
}

function mainRepoRoot() {
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

// 抽屉全文回收（本场景判定面：可读性 + 零 [object Object]）。
// 只收**渲染的可见文本**：剔除 style/script 节点——验收走查实证（t260926-05 gen0）：
// 详情面内联 CSS 注释里合法引用了「[object Object]」字样（260926 修复注释），
// textContent 全量回收把样式表注释误判为数据渲染（false positive，非实现缺陷）。
// 数据面零 [object Object] 的契约不变，只是判定面与「用户可感知文本」对齐。
const domDrawerText = `(() => {
  const root = document.querySelector('.wb-drawer') || document
  const clone = root.cloneNode(true)
  clone.querySelectorAll('style,script').forEach((el) => el.remove())
  return (clone.textContent || '')
})()`

function snapOf(text) {
  return `drawerLen=${text.length} hasObjObj=${text.includes('[object Object]')}`
}

/** 换子用例：改桩→reload→进板→开抽屉→等巡检详情面渲染。 */
async function applyLeg(page, boardIcon, detail) {
  currentDetail = detail
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await dismissOverlays(page)
  await boardIcon.click().catch(() => {})
  const row = page.locator('.wb-card[data-ticket-id]', { hasText: FID }).first()
  if (!(await waitFor(async () => (await row.count()) > 0, 10000))) {
    throw new Error('fixture row not rendered after leg switch (list stub not consumed?)')
  }
  await row.click()
  const ok = await waitFor(async () =>
    (await page.locator('[data-testid="inspection-timeline"]').count()) > 0, 10000)
  if (!ok) throw new Error('巡检详情面未渲染（inspection-timeline 缺席——组合闸或详情链断了）')
}

async function openDetails(page, testid) {
  const sec = page.locator(`[data-testid="${testid}"]`).first()
  if (!(await sec.count())) return `section [data-testid=${testid}] missing from drawer`
  await sec.evaluate(el => { el.open = true }).catch(() => {})
  return null
}

// ---------------------------------------------------------------- S1 scenarios

// L1：findings 全字段 + evidence path:line + 引文（数据不译——中文 subject 照原样在场）。
async function scenarioFindings(page) {
  const err = await openDetails(page, 'inspection-findings-list')
  if (err) return err
  const text = await page.evaluate(domDrawerText)
  const need = ['Severity', 'Scan', 'Confidence', 'Verified', 'Subject', 'Why', 'Suggestion',
    'deadman', 'high', '0.92', '套件档墙钟超预算', '复核 supply_timeout_sec 配置并补跑该期套件',
    'server/engine/inspection_deadman.py:371', 'supply_used_sec = now - supply_start',
    'notes/debts/known-issues.md:12']
  const miss = need.filter(a => !text.includes(a))
  if (miss.length) return `findings 面缺契约锚: ${miss.join(' | ')}`
  return null
}

// L2：畸形 finding 不炸页、可读回落、零 [object Object]。
async function scenarioMalformed(page) {
  const err = await openDetails(page, 'inspection-findings-list')
  if (err) return err
  const text = await page.evaluate(domDrawerText)
  if (text.includes('[object Object]')) return '抽屉出现 [object Object]（畸形 finding 走了裸渲染）'
  for (const anchor of ['raw-string-finding', 'array', 'finding']) {
    if (!text.includes(anchor)) return `畸形 finding 输入文本「${anchor}」未以任何可读形态出现在抽屉（回落缺失）`
  }
  return null
}

// L3：套件证据段——计数/墙钟/超时/晚收据告警各自带英文标签。
async function scenarioSuite(page) {
  const err = await openDetails(page, 'inspection-suite')
  if (err) return err
  const text = await page.evaluate(domDrawerText)
  const need = ['Suite evidence', 'Ran', 'Passed', 'Failed', 'supply_used_sec', 'runner_used_sec',
    'run_budget_sec', 'suite_timeout', '743', '120', '600', '88', '85', '3',
    'Late receipt', 'receipt arrived 95s after budget window', 'tests/a.py::t1']
  const miss = need.filter(a => !text.includes(a))
  if (miss.length) return `套件证据段缺契约锚: ${miss.join(' | ')}`
  return null
}

// L4：report_path 亲和物——路径可读在场，摘要动作出可读内容，零 [object Object]。
async function scenarioReportAffordance(page) {
  const err = await openDetails(page, 'inspection-report')
  if (err) return err
  let text = await page.evaluate(domDrawerText)
  if (!text.includes('out/inspection/inspection-fixture-20260926.json')) {
    return 'report_path 未以可读文本呈现在抽屉'
  }
  const toggle = page.locator('[data-testid="inspection-report"] button, [data-testid="inspection-report"] summary', { hasText: /digest|Open/i }).first()
  if (!(await toggle.count())) return 'report_path 无「打开摘要」亲和物（button/summary 缺席）'
  await toggle.click().catch(() => {})
  const ok = await waitFor(async () => {
    const t = await page.evaluate(domDrawerText)
    return t.includes('巡检只出报告与开票建议') && t.includes('nested_unknown')
  }, 8000)
  if (!ok) return '摘要动作后报告体内容未渲染（巡检红线/nested 键缺席——摘要链未接）'
  text = await page.evaluate(domDrawerText)
  if (text.includes('[object Object]')) return '摘要渲染出现 [object Object]'
  return null
}

// L4b：摘要端点失败→显式降级文案（绝不静默空白）。
async function scenarioReportBroken(page) {
  reportStubMode = 'broken'
  const err = await openDetails(page, 'inspection-report')
  if (err) { reportStubMode = 'ok'; return err }
  const toggle = page.locator('[data-testid="inspection-report"] button, [data-testid="inspection-report"] summary', { hasText: /digest|Open/i }).first()
  await toggle.click().catch(() => {})
  const ok = await waitFor(async () => {
    const t = await page.evaluate(domDrawerText)
    return /could not|failed|unavailable|reason/i.test(t)
  }, 8000)
  reportStubMode = 'ok'
  if (!ok) return '摘要端点失败无显式降级文案（静默空白=非契约）'
  return null
}

// ---------------------------------------------------------------- S1 runner

async function runBrowser(BASE, pw, browser) {
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

    // API 边界桩：list/detail/workflows + 本票摘要端点全夹具；未知路由 ok:false。
    // glob 必须 ** 结尾（playwright 单 * 不跨 /，家族实证注释）。
    currentDetail = DETAIL_FULL
    await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
      if (path === '/sandbar-workbench/api/wf/tickets') {
        return body({ ok: true, result: { tickets: [ROW] }, workflows: [] })
      }
      const rm = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)\/inspection-report$/.exec(path)
      if (rm && decodeURIComponent(rm[1]) === FID) {
        if (reportStubMode === 'broken') return body({ ok: false, error: 'fixture stub: report read failed' })
        return body({ ok: true, result: { ok: true, report: currentReport } })
      }
      const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && decodeURIComponent(m[1]) === FID) return body({ ok: true, result: currentDetail })
      return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
    })
    await page.route('**/sandbar-workbench/api/wf/workflows**', (route) => {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: [] }) })
    })

    const boardIcon = page.locator('span.wb-view-icon[title="Tickets"]').first()
    if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `no project group 📋 found on ${BASE} (console not provisioned for board view)`)
      return
    }
    await boardIcon.click()
    const rowOk = await waitFor(async () =>
      (await page.locator('.wb-card[data-ticket-id]', { hasText: FID }).count()) > 0, 10000)
    if (!rowOk) {
      record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
      return
    }

    const failWith = async (name, e) => {
      const text = await page.evaluate(domDrawerText).catch(() => '')
      // 三态归因（t260904-12；t260916-05 家族口径）：导航/连接类中途异常=台面死亡，
      // 属环境面 env_fail——绝不冒充产品红（gen1 闸红实证：stage console 在闸群
      // 负载下中途死，五个子用例 reload 全 ERR_CONNECTION_REFUSED 被旧写法记成 fail）。
      const s = String(e)
      const nav = /Timeout\s*\d+ms\s+exceeded|networkidle|ERR_CONNECTION|ECONNREFUSED|ERR_INCOMPLETE|socket hang up|Target closed|net::/i.test(s)
      record(name, nav ? 'env_fail' : 'fail', `${s.slice(0, 140)} @ ${snapOf(text)}`)
    }
    // 像素证据落盘口径=引擎官方（<泳道>/.sandbar/screenshots/ 第一层，merge_check 证据闸
    // 只吃第一层）；失败软处理——DOM 断言才是判定面。
    const SCREENS_DIR = join(REPO, '.sandbar', 'screenshots')
    const shot = async (name) => {
      try {
        mkdirSync(SCREENS_DIR, { recursive: true })
        await page.screenshot({ path: join(SCREENS_DIR, name), fullPage: false })
        return name
      } catch { return `(screenshot ${name} failed)` }
    }
    const leg = async (name, detail, fn, shotName) => {
      try {
        await applyLeg(page, boardIcon, detail)
        const err = await fn(page)
        const s = shotName ? await shot(shotName) : ''
        if (err) record(name, 'fail', `${err}${s ? ` [shot=${s}]` : ''}`)
        else record(name, 'pass', s ? `[shot=${s}]` : '')
      } catch (e) { await failWith(name, e) }
    }

    await leg('L1 findings 全字段+evidence path:line+引文（数据不译）', DETAIL_FULL, scenarioFindings, 't26092605-findings-full.png')
    await leg('L2 畸形 finding 不炸页+可读回落+零 [object Object]', DETAIL_MALFORMED, scenarioMalformed, 't26092605-findings-malformed.png')
    await leg('L3 套件证据段：计数/墙钟/超时/晚收据带标签', DETAIL_FULL, scenarioSuite, 't26092605-suite-evidence.png')
    await leg('L4 report_path 亲和物+摘要可读+零 [object Object]', DETAIL_FULL, scenarioReportAffordance, 't26092605-report-digest.png')
    await leg('L4b 摘要端点失败→显式降级文案', DETAIL_FULL, scenarioReportBroken, 't26092605-report-broken.png')

    // P 分诊（gen6 实证）：台面抖动窗的资源加载失败（502/ERR_*/net::）是环境噪音
    // （console 重复 down/ensure 期间页面拉资源失败，281s 重拉窗实证），非产品错误——
    // 记 env_fail；pageerror 与真实 console.error 才是产品面 fail。契约不变：产品
    // 错误零容忍，只是环境噪音不冒充产品红（与 failWith 同一三态口径）。
    const envConsole = (t) => /Failed to load resource|ERR_|net::|502|503|ECONN|socket hang up/i.test(t)
    const productConsole = consoleErrors.filter(t => !envConsole(t))
    const hygieneDetail = `pageerrors=${pageErrors.length} consoleErrors=${consoleErrors.length}` +
      (pageErrors.length ? ` first=${pageErrors[0]}` : '') + (consoleErrors.length ? ` firstConsole=${consoleErrors[0]}` : '')
    if (pageErrors.length === 0 && consoleErrors.length === 0) {
      record('P 全旅程零 pageerror/console.error', 'pass')
    } else if (pageErrors.length === 0 && productConsole.length === 0) {
      record('P 全旅程零 pageerror/console.error', 'env_fail', `env-only console noise (stage console churn): ${hygieneDetail}`)
    } else {
      record('P 全旅程零 pageerror/console.error', 'fail', hygieneDetail)
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

  // S0 先跑（纯 node，无台面依赖）——环境红不得捂住 S0 的证据。
  buildContract()
  await modelSmoke()

  // 台面供给（懒供给：S0 证据先落，boot 失败按三态 exit 2，绝不假绿）。
  let BASE = ''
  try {
    BASE = (await ensureStageConsole()).base
  } catch (e) {
    record('S1 supply', 'env_fail', `stage console ensure failed: ${String(e).slice(0, 160)}`)
    return summarize()
  }
  if (BASE.includes(':3099')) {
    console.error('refusing to run: test console points at the production console (3099)')
    process.exit(1)
  }
  if (!(await consoleHealthy(BASE))) {
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
    await runBrowser(BASE, pw, browser)
  } finally {
    if (!exiting) await browser.close().catch(() => {})
  }
  summarize()
}

// 中途异常按三态 triage（导航/连接类=env_fail，其余=fail，绝不静默——家族口径）。
main().catch(e => {
  const s = String(e?.message ?? e)
  const nav = /Timeout\s*\d+ms\s+exceeded|networkidle|ERR_CONNECTION|ECONNREFUSED|socket hang up|Target closed|net::/i.test(s)
  record('mid-run-abort', nav ? 'env_fail' : 'fail', s.slice(0, 200))
  summarize()
})
