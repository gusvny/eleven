// sc_inspection_detail_lane_map_dom.mjs — t260916-05 巡检票详情泳道图 DOM 对拍基线
// （引擎登记巡检模板拓扑 + 阶段声明真源 + 一致性锁；本条守用户可感知的渲染面，验收①的 DOM 半+降级现状维持）。
//
// Intent (black-box, user perspective)：宿主打开一张巡检票详情抽屉——
//   L1 在飞票：引擎拓扑在场即泳道图自动在——节点集==阶段声明全集
//      {setup,suite,inspect,report,close}、节点标签全部来自拓扑（零硬编码业务词）、
//      人门虚线圈恰落 close（data-kind=human）、条件段注记恰 setup+suite
//      （wb-lm-opt=「仅套件档」，条件段泄漏=图面撒谎）、在飞状态如实投影
//      （已进入段 data-vis=running、未进入段 todo——巡检 timeline 无逐段 done，
//      多节点同显 running 是引擎现状的诚实投影，非图面失真）；
//   L2 待签票：close data-vis=awaiting-human（人门到站 ✋，签什么在巡检面不在图）；
//   L3 关闭票（KI-027 同族「关单可见」）：全节点 data-vis=done 且图仍在；
//   L4 降级锚：详情无 topology 键（老实例重放常态）→零泳道图且零 dev-lane
//      步骤条回落——维持 t260915-08 以来巡检详情的现状降级，绝不拿 dev-lane
//      步骤条冒充巡检图，巡检面时间线照常；
//   P 卫生腿：全旅程零 pageerror / console.error。
//
// 分工（防 intent 级重复）：t260915-05-detail-lane-map-dom 守 dev-lane 泳道图本体
// +渲染器通用性+畸形拓扑不炸（本条不重复其面，渲染器零改动是被测前提）；
// t260915-08-board-ui 守板面巡检行/详情下钻/签字通道；t260915-19 守左栏分拣；
// 引擎数据半（拓扑真进 ticket-query 回执、旧实例省键）由 t260916-05-topology-receipt
// 守；双真源同步锁的闸内活性由 t260916-05-dual-source-lock 守；一致性锁 UT
// （阶段声明↔导出面逐字段）归 developer L1 不同层。本条数据全桩：list/detail/
// workflows 三路由 page.route 拦截（契约形状={template,name,nodes[id,label,role,
// kind,parts,optional?],edges,groups}——契约漂移=红点名），浏览器/bundle/React 全真。
//
// Two layers（同 t260915-05 家族切法）：
//   S0 build-contract（纯 node）：双 bundle 同步 + 渲染器锚在 bundle +
//      buildLaneMap 巡检夹具冒烟（拓扑契约→模型出 5 节点/人门/条件段注记）；
//   S1 browser DOM：隔离测试台（SANDBAR_TEST_CONSOLE，3099 红线零接触）＋
//      playwright-core＋chromium，任一缺席=ENV_FAIL exit 2。
//
// Execution contract (t260904-12 three-state)：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全 na → exit 1；
// env_fail>0 → exit 2。Node >= 22.18。
// 实现段落地前红属预期（TDD 信号：L1~L3 红=图未接线；S0 与 L4 应即绿），
// arbitrate/merge 期必须绿。

import { ensureStageConsole } from '../lib_stage_console.mjs'
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve, dirname } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

// 仓库根解析：爬根找 CLAUDE.md（KI-075 族——禁宿主绝对路径、禁裸 process.cwd；
// t260915-08-inspection-face.mjs 同款范式）。
const REPO = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 8; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根（爬根 8 层无 CLAUDE.md）')
})()

const FID = 't26091605dom' // fixture ticket id（alnum only；绝不真票）

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

// ---------------------------------------------------------------- 拓扑契约夹具
// 引擎 template_topology.py topology-v1 导出形状（不是线性近似链）：巡检模板
// =5 节点线性 + close 人门 + setup/suite 条件段（套件档开关的展示面）。
// 段 id/name=引擎 InspectionPeriodicWorkflow.STAGES 声明（一致性锁归 developer UT）。
const OPT_SUITE = '仅套件档'
const TOPO_INSP = {
  template: 'inspection-lite', name: '巡检',
  nodes: [
    { id: 'setup', label: '泳道准备', role: '', kind: 'gate', parts: ['script'], optional: OPT_SUITE },
    { id: 'inspect', label: '巡检审查', role: '', kind: 'gate', parts: ['script'] },
    { id: 'suite', label: '巡检泳道套件', role: '', kind: 'gate', parts: ['script'], optional: OPT_SUITE },
    { id: 'report', label: '落账', role: '', kind: 'gate', parts: ['script'] },
    { id: 'close', label: '人审收口', role: '', kind: 'human', parts: ['human', 'script'] },
  ],
  edges: [['setup', 'suite'], ['suite', 'inspect'], ['inspect', 'report'], ['report', 'close']],
  groups: [],
}
const INSPECTION_IDS = ['setup', 'suite', 'inspect', 'report', 'close']
const INSPECTION_LABELS = ['泳道准备', '巡检审查', '巡检泳道套件', '落账', '人审收口']

// ---------------------------------------------------------------- S1 fixtures
// 巡检详情契约形状（t260915-08 insDetail 同源）+ 本票 additive 键 topology。
const ROW = {
  id: FID, kind: 'inspection', engine: 'inspection', project: '', epic: '',
  title: '巡检 DOM 桩 · 期 20260916', template: 'inspection-lite',
  instance_id: 'fixture', period: '20260916', stage: 'inspect', stage_state: 'running',
  status: 'running', decision: '', findings: { high: 0, med: 1, low: 1, total: 2 },
  heartbeat: true, report_path: 'out/inspection/fixture-20260916.json',
  awaiting_gate: false, human_gate: null, blocked_reason: '', gate_error: '',
  created: 1789526400, updated: '09-16 08:00', updated_ts: 1789526400,
  paused: false, paused_phase: '', handoff_count: 0, pending_count: 0,
  worktree: '', workspace: null, role: null, proposal_id: '', workflow: '',
  close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
}

const T = '2026-09-16T08:00:00'
const tle = (stage, state, reason = '') => ({ at: T, stage, state, reason })

function insDetail(over) {
  return {
    id: FID, kind: 'inspection', engine: 'inspection', template: 'inspection-lite',
    title: ROW.title, stage: 'inspect', stage_state: 'running', status: 'running',
    decision: '', gate_id: 'inspection-close', instance_id: 'fixture', period: '20260916',
    report_path: ROW.report_path, red_line: '巡检只出报告与开票建议，绝不直接改码。',
    heartbeat: true, summary: { high: 0, med: 1, low: 1 },
    findings: [
      { id: 'f1', scan: 'test', severity: 'med', subject: '中危样例', evidence: 'ev-med', suggestion: '人审后定' },
      { id: 'f2', scan: 'test', severity: 'low', subject: '低危样例', evidence: 'ev-low', suggestion: '留意' },
    ],
    suggested_fix_tickets: [], blocked_reason: '', human_gate: null, gate_error: '',
    worktree: '', workspace: null, results: {},
    timeline: [tle('setup', 'running', '泳道准备'), tle('inspect', 'running', '巡检审查')],
    topology: TOPO_INSP,
    ...over,
  }
}

// L1 在飞票：setup+inspect 已进入（running）、suite/report/close 未进入（todo）
const DETAIL_INFLIGHT = insDetail()
// L2 待签：close 人门到站
const DETAIL_AWAITING = insDetail({
  stage: 'close', stage_state: 'awaiting-human',
  timeline: [tle('setup', 'running'), tle('inspect', 'running'), tle('report', 'running'),
    tle('close', 'awaiting-human', '人审发现清单：sign(gate=inspection-close)')],
})
// L3 关闭票：全段 done、图仍在（KI-027 关单可见同族）
const DETAIL_CLOSED = insDetail({
  status: 'closed', stage: 'close', stage_state: 'done',
  timeline: [tle('setup', 'running'), tle('inspect', 'running'), tle('report', 'running'),
    tle('close', 'awaiting-human'), tle('close', 'done', '巡检票收口')],
})
// L4 降级锚：无 topology 键（老实例重放常态）→零图零回落
const DETAIL_NO_TOPO = (() => { const d = insDetail(); delete d.topology; return d })()

// API 桩状态（路由桩闭包与 applyLeg 共读共写）。
let currentDetail = null

// ---------------------------------------------------------------- S0 build-contract
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const LANE_MAP_MODEL = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'lane-map-model.ts')

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
  const anchors = ['wb-lanemap', 'wb-lm-']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 build-contract', 'fail', `shipped bundle missing lane-map anchors: ${missing.join(', ')}`)
    return
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync, lane-map anchors present')
}

async function modelSmoke() {
  if (!existsSync(LANE_MAP_MODEL)) {
    record('S0 lane-map-model', 'fail', 'lane-map-model.ts missing（渲染器纯模型模块未落地）')
    return
  }
  try {
    const mod = await import(pathToFileURL(LANE_MAP_MODEL).href + '?t=' + Date.now())
    const build = mod.buildLaneMap
    if (typeof build !== 'function') {
      record('S0 lane-map-model', 'fail', 'lane-map-model.ts does not export buildLaneMap')
      return
    }
    const out = build(TOPO_INSP, insDetail())
    const s = JSON.stringify(out ?? {})
    const need = [...INSPECTION_IDS, OPT_SUITE, 'human']
    const miss = need.filter(a => !s.includes(a))
    if (miss.length) {
      record('S0 lane-map-model', 'fail', `巡检拓扑模型缺契约锚 ${miss.join(',')}: ${s.slice(0, 200)}`)
      return
    }
    record('S0 lane-map-model', 'pass', 'buildLaneMap consumes inspection topology: 5 nodes/human/optional notes')
  } catch (e) {
    record('S0 lane-map-model', 'fail', `lane-map-model.ts not importable: ${String(e).slice(0, 140)}`)
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

// 泳道图 DOM 清点（page context）：作用域限定详情抽屉（左栏行卡迷你站道不串扰）；
// 泳道图族类全量回收＋data-* 契约（id/kind/vis）。
const domInventory = `(() => {
  const root = document.querySelector('.wb-drawer') || document
  const els = [...root.querySelectorAll('[class*="wb-lanemap"], [class*="wb-lm-"]')]
  return els.map(el => ({
    cls: String(el.className || ''), text: (el.textContent || '').slice(0, 140),
    title: el.getAttribute('title') || '',
    dataKind: el.getAttribute('data-kind') || '', dataId: el.getAttribute('data-id') || '',
    dataVis: el.getAttribute('data-vis') || '',
  }))
})()`
const domMapRootCount = `(() => {
  const root = document.querySelector('.wb-drawer') || document
  return root.querySelectorAll('.wb-lanemap').length
})()`
const domOptCount = `(() => {
  const root = document.querySelector('.wb-drawer') || document
  return root.querySelectorAll('.wb-lm-opt').length
})()`
const domStepCount = `document.querySelectorAll('.wb-d2-steps .wb-d2-step').length`

function snapOf(inv) {
  const nodes = inv.filter(x => x.dataId)
  return `mapEls=${inv.length} nodes=${JSON.stringify(nodes.map(n => `${n.dataId}:${n.dataVis || '?'}`))}`
}

/** 换腿：改桩→reload（路由桩跨 reload 存活）→进板→开抽屉→等巡检详情面渲染。 */
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

/** 泳道图在场的腿跑法：图缺席=fail 带诊断快照（不给静默通过）。 */
async function withMap(page, fn) {
  const inv = await page.evaluate(domInventory)
  if (!inv.filter(x => x.dataId).length) {
    return `泳道图未渲染（抽屉内 wb-lanemap-* 元素=0，拓扑未接线或组合闸未放行）@ ${JSON.stringify(await page.evaluate(domMapRootCount))}`
  }
  return await fn(inv)
}

// ---------------------------------------------------------------- S1 scenarios

async function scenarioInflight(page) {
  return withMap(page, async (inv) => {
    const nodes = inv.filter(x => x.dataId)
    const ids = [...new Set(nodes.map(x => x.dataId))].sort()
    const want = [...INSPECTION_IDS].sort()
    if (ids.join(',') !== want.join(',')) {
      return `节点集≠阶段声明全集：得 [${ids.join(',')}] 期望 [${want.join(',')}]`
    }
    const text = nodes.map(x => `${x.text} ${x.title}`).join(' | ')
    for (const lbl of INSPECTION_LABELS) {
      if (!text.includes(lbl)) return `节点标签缺拓扑词「${lbl}」（标签须全部来自拓扑）：${text.slice(0, 240)}`
    }
    const human = nodes.filter(n => n.dataKind === 'human')
    if (human.length !== 1 || human[0].dataId !== 'close') {
      return `人门虚线圈应恰落 close（data-kind=human）：${JSON.stringify(human).slice(0, 160)}`
    }
    for (const id of ['setup', 'suite']) {
      if (!nodes.some(n => n.dataId === id && n.text.includes(OPT_SUITE))) {
        return `条件段注记缺席：${id} 应带「${OPT_SUITE}」（套件档开关的展示面）`
      }
    }
    for (const id of ['inspect', 'report', 'close']) {
      if (nodes.some(n => n.dataId === id && n.text.includes(OPT_SUITE))) {
        return `条件段注记泄漏：${id} 不应带「${OPT_SUITE}」（图面撒谎形态）`
      }
    }
    const optN = await page.evaluate(domOptCount)
    if (optN !== 2) return `wb-lm-opt 注记数=${optN}（期望恰 2：setup/suite）`
    const vis = Object.fromEntries(nodes.map(n => [n.dataId, n.dataVis]))
    for (const id of ['setup', 'inspect']) {
      if (vis[id] !== 'running') return `已进入段 ${id} 应显 running，实得 ${vis[id]}（在飞如实投影）`
    }
    for (const id of ['suite', 'report', 'close']) {
      if (vis[id] !== 'todo') return `未进入段 ${id} 应显 todo，实得 ${vis[id]}`
    }
    return null
  })
}

async function scenarioAwaiting(page) {
  return withMap(page, async (inv) => {
    const close = inv.filter(x => x.dataId === 'close')
    if (!close.some(n => n.dataVis === 'awaiting-human')) {
      return `close 应显 awaiting-human（人门到站 ✋）：${JSON.stringify(close.map(n => n.dataVis))}`
    }
    return null
  })
}

async function scenarioClosed(page) {
  return withMap(page, async (inv) => {
    const nodes = inv.filter(x => x.dataId)
    const notDone = nodes.filter(n => n.dataVis !== 'done')
    if (notDone.length) {
      return `关闭票应全段 done：${JSON.stringify(notDone.map(n => `${n.dataId}:${n.dataVis}`))}`
    }
    return null
  })
}

async function scenarioNoTopo(page) {
  const mapN = await page.evaluate(domMapRootCount)
  const stepN = await page.evaluate(domStepCount)
  if (mapN !== 0) return `无拓扑详情渲染了泳道图（wb-lanemap ×${mapN}）——无中生有形态`
  if (stepN !== 0) return `无拓扑详情回落了 dev-lane 步骤条（wb-d2-step ×${stepN}）——现状降级被破坏`
  return null // 巡检面时间线在场已由 applyLeg 的等待面保证
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

    // API 边界桩：列表+详情+模板列表全夹具；未知 id/子路由 ok:false（绝不漏到真台）。
    // glob 必须 ** 结尾（playwright 单 * 不跨 /，家族实证注释）。
    currentDetail = DETAIL_INFLIGHT
    await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
      if (path === '/sandbar-workbench/api/wf/tickets') {
        return body({ ok: true, result: { tickets: [ROW] }, workflows: [] })
      }
      const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && decodeURIComponent(m[1]) === FID) return body({ ok: true, result: currentDetail })
      return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
    })
    await page.route('**/sandbar-workbench/api/wf/workflows**', (route) => {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: [] }) })
    })

    const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
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
      const inv = await page.evaluate(domInventory).catch(() => [])
      record(name, 'fail', `${String(e).slice(0, 140)} @ ${snapOf(inv)}`)
    }
    // 像素证据（t260916-05 review gen1 意见 3：capture.mjs VIEWS 无巡检详情视图且
    // server/ui-check 不在本票写集——像素证据由本场景产出）。
    // 落盘口径=引擎官方（宿主 260916 出路①裁定）：<泳道>/.sandbar/screenshots/ 第一层
    // （ui_evidence_dir + merge_check 证据闸 agent_activities.py glob('*.png') 只吃
    // 第一层）——禁挂子目录（rework gen1：子目录=证据对闸隐身）。
    // L1=改后形态（泳道图在场），L4=改前形态留证（无 topology 键=改前全部巡检票的样子）。
    // 失败软处理（截图写不出不拖断言三态，DOM 断言才是本场景判定面）。
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

    await leg('L1 在飞票：图在场+节点集=声明全集+人门圈+条件段+如实投影', DETAIL_INFLIGHT, scenarioInflight, 'after-inflight-map.png')
    await leg('L2 待签票：close 人门到站 awaiting-human', DETAIL_AWAITING, scenarioAwaiting, 'after-awaiting-gate.png')
    await leg('L3 关闭票：全段 done 且图仍在（关单可见）', DETAIL_CLOSED, scenarioClosed, 'after-closed-map.png')
    await leg('L4 降级锚：无 topology 键=零图零回落（现状维持）', DETAIL_NO_TOPO, scenarioNoTopo, 'before-old-ticket-no-map.png')

    const hygieneDetail = `pageerrors=${pageErrors.length} consoleErrors=${consoleErrors.length}` +
      (pageErrors.length ? ` first=${pageErrors[0]}` : '') + (consoleErrors.length ? ` firstConsole=${consoleErrors[0]}` : '')
    if (pageErrors.length === 0 && consoleErrors.length === 0) {
      record('P 全旅程零 pageerror/console.error', 'pass')
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
