// sc_external_template_lane_map_render.mjs — t260927-05 外置模板票的泳道图渲染契约（灰盒 L3，隔离台 + API 桩，browser-free）。
//
// Intent（用户可感知行为，工单 scope④ + 验收②控制台半边）：
//   L1 外置模板票泳道图照画：工单详情 workflow_id 指向目录面查不到的外置模板
//      （桩让 GET /api/wf/workflows 只回 dev-lane = 目录 miss 形态），但详情快照
//      自带该票的 topology（服务端导出面产出）→ 泳道图必须照常渲染（.wb-lanemap
//      在位、外置段 id 的节点可见）——客户端从**票携带的拓扑**渲染，不因目录
//      lookup miss 而 undefined 崩链（scope④：catalog lookup miss 时回落票面拓扑）。
//   L2 目录命中形态零回归：同一张详情当目录面**含**该外置模板行（topology 同源）
//      时，泳道图同样渲染且节点一致——两条来源路径（detail.topology 优先 / 目录
//      回落）画同一张图，任何一条被实现改断即红。
//   L3 无拓扑 + 目录 miss = 诚实降级：老外置票（快照无 topology、目录也 miss）
//      泳道图缺席但**不伪造**（绝不猜拓扑红线）、页面零 pageerror/console.error
//      ——降级是显式可判定的缺席，不是空白崩溃。
//
// 分层纪律（防 intent 级重复）：
//   - t260915-05 sc_ticket_detail_lane_map_dom 锁 dev-lane 拓扑渲染/降级/红灯层；
//     本场景只锁**外置模板（目录 miss 族）**的泳道渲染契约，dev-lane 面不复断。
//   - t260925-18 锁界面语言层（英文界面×中文数据）；本场景不碰标签语言断言。
//   - sc_external_template_catalog_topology.py（同票）锁目录/拓扑**数据面**；
//     本场景锁 payload→像素渲染面。developer L1（client 纯函数单测）不同层。
//
// 两层 → 真浏览器渲染级（precedent=t260925-18）：需要隔离测试台（lib_stage_console）、
// playwright-core 可解析、chromium 可启动，任一缺席=ENV_FAIL exit 2（KI-036 家族）。
// 数据在 API 边界 page.route() 桩：真浏览器/真 console/真 bundle/真 React 渲染链，
// 只拦 /sandbar-workbench/api/wf/tickets** 与 /api/wf/workflows**（夹具快照）。
// 红线：永不接触生产 console(3099)、不起替换服务。
//
// 执行契约（t260904-12 三态）：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全部子用例 na → exit 1；
// env_fail>0 → exit 2。实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。

import { ensureStageConsole } from '../lib_stage_console.mjs'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()

// 三态契约：共享测试台供给失败（seed/起台/跨项目拒收等）= 环境红 ENV_FAIL exit 2，
// 绝不落成 exit 1 产品红假信号（t260927-05 仲裁修正：seed 阶段 seedws 跨项目拒收
// 曾以裸 ValueError 崩出 exit 1，被误读为产品红）。
let BASE
try {
  BASE = (await ensureStageConsole()).base
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable — ${String(e).slice(0, 300)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
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

const EXT_ID = 'content-studio'
const FID = 't26092705a' // 外置模板票（纯字母数字，永不与真票相撞）
const FID_OLD = 't26092705b' // 无拓扑老外置票（降级对照）

// ---------------------------------------------------------------- fixtures

// 外置模板拓扑（形状=template_topology 契约：nodes/edges/groups，零业务词）
const TOPO_EXT = {
  template: EXT_ID, name: 'Content Studio',
  nodes: [
    { id: 'cs-draft', label: 'Draft', role: 'developer', kind: 'agent' },
    { id: 'cs-review', label: 'Review', role: 'integration', kind: 'agent' },
    { id: 'cs-publish', label: 'Publish', role: 'developer', kind: 'agent' },
  ],
  edges: [['cs-draft', 'cs-review'], ['cs-review', 'cs-publish']],
  groups: [],
}

const EXT_STAGES = TOPO_EXT.nodes.map(n => ({ id: n.id, name: n.label, role: n.role, parts: ['agent'] }))
const WF_EXT = { id: EXT_ID, name: 'Content Studio', lane: 'worktree', stages: EXT_STAGES, topology: TOPO_EXT }

// 目录 miss 形态：目录面只有 dev-lane（外置模板未并入时的现状形状）。
// 形状对齐真实契约（index.tsx 消费口）：列表聚合口回顶层 `workflows` 键 +
// `result.tickets`——桩必须同形，否则红因是桩形状错而非产品红（gen0 首跑
// 「fixture row not rendered」的真因即此，gen1 修正）。
// 目录桩变量（模块级：scenario() 内 S3 改写后 reload 切换命中形态）
let catalog
const WF_CATALOG_MISS = [{
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [{ id: 'create_plan', name: '做方案', role: 'developer', parts: ['agent'] }],
  topology: null,
}]
catalog = WF_CATALOG_MISS

function detailBase(id, over = {}) {
  return {
    id, title: `Fixture ${id} — external template lane map`, workflow_id: EXT_ID, epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'cs-draft', stage_state: 'running', stage_name: 'Draft',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [], body: '外置模板夹具票正文（中文数据不译对照）',
    write_set: [], timeline: [], spec: '', spec_len: 0,
    ...over,
  }
}

const DETAIL_WITH_TOPO = detailBase(FID, { topology: TOPO_EXT })
const DETAIL_NO_TOPO = detailBase(FID_OLD) // 老快照：无 topology 键
const DETAIL_BY_ID = { [FID]: DETAIL_WITH_TOPO, [FID_OLD]: DETAIL_NO_TOPO }

const ROWS = [
  { id: FID, role: 'developer', status: 'dispatched', title: DETAIL_WITH_TOPO.title, workflow: EXT_ID, stage: 'cs-draft', stage_state: 'running', handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0 },
  { id: FID_OLD, role: 'developer', status: 'dispatched', title: DETAIL_NO_TOPO.title, workflow: EXT_ID, stage: 'cs-draft', stage_state: 'running', handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0 },
]

// ---------------------------------------------------------------- helpers

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
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

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* poll */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

async function openDetail(page, fid) {
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
  // 定位契约：卡片 id 列显示短序号（#01），完整 id 只在 data-ticket-id 属性上
  // （t260901-12 短序号纪律）——按属性定位，不按全文 hasText。
  const rowEl = page.locator(`.wb-card[data-ticket-id="${fid}"]`).first()
  if (!(await waitFor(async () => (await rowEl.count()) > 0, 8000))) {
    throw new Error(`fixture row ${fid} not rendered`)
  }
  await rowEl.click({ timeout: 5000 }).catch(async () => {
    // 桩面轮询重渲染会让 actionability 等待偶尔饿死——派发 click 事件兜底
    //（本契约锁渲染链，不锁指针命中几何）。
    await rowEl.dispatchEvent('click')
  })
  const ok = await waitFor(async () => await page.evaluate(
    () => !!document.querySelector('.wb-d2-spec, .wb-d2-steps, .wb-d2-body, .wb-drawer')), 8000)
  if (!ok) throw new Error(`detail drawer did not render ${fid}`)
}

async function laneMapProbe(page) {
  return page.evaluate(() => {
    const el = document.querySelector('.wb-lanemap')
    return {
      present: !!el,
      text: el ? (el.textContent || '') : '',
      ids: el ? [...el.querySelectorAll('[data-stage-id], [data-node-id]')].map(e => e.getAttribute('data-stage-id') || e.getAttribute('data-node-id')) : [],
    }
  })
}

async function scenario(page, cases) {
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

  // S1：目录 miss + 详情带拓扑 → 泳道图照画（scope④ 主契约）
  await openDetail(page, FID)
  let probe = await laneMapProbe(page)
  if (!probe.present) {
    // 就绪等待：lane map 可能迟于抽屉渲染
    await waitFor(async () => (await laneMapProbe(page)).present, 6000)
    probe = await laneMapProbe(page)
  }
  record('L1 lane map renders from ticket topology on catalog miss', probe.present ? 'pass' : 'fail',
    probe.present ? '' : 'no .wb-lanemap in detail drawer (catalog-miss fallback missing)')
  if (probe.present) {
    const hit = ['cs-draft', 'cs-review', 'cs-publish'].filter(id => probe.text.includes(id) || probe.ids.includes(id))
    record('L1 external stage nodes visible', hit.length === 3 ? 'pass' : 'fail',
      `found=${hit.length}/3 text=${probe.text.slice(0, 120)}`)
  }

  // S2：无拓扑 + 目录 miss → 诚实降级（无泳道图、不伪造、零崩溃）
  await openDetail(page, FID_OLD)
  const probe2 = await laneMapProbe(page)
  record('L3 no topology + catalog miss = honest degradation (no fake lane map)', probe2.present ? 'fail' : 'pass',
    probe2.present ? `unexpected .wb-lanemap with no topology source: ${probe2.text.slice(0, 120)}` : '')

  const realErrors = errors.filter(e => !/favicon|404|net::ERR_FAILED/i.test(e))
  record('L3 journey zero pageerror/console.error', realErrors.length === 0 ? 'pass' : 'fail',
    realErrors.slice(0, 3).join(' | '))

  // S3：目录命中形态（目录面含外置模板行）→ 同一张图（目录回落路径零回归）。
  // 客户端从列表聚合口的顶层 `workflows` 键取目录——改目录=改桩回执后 reload。
  catalog = [...WF_CATALOG_MISS, WF_EXT]
  await page.reload({ waitUntil: 'networkidle' })
  await openDetail(page, FID_OLD) // 该详情自身无 topology → 必须从目录行回落取到
  const probe3 = await laneMapProbe(page)
  if (!probe3.present) {
    await waitFor(async () => (await laneMapProbe(page)).present, 6000)
  }
  const probe3b = await laneMapProbe(page)
  record('L2 catalog-hit fallback renders same external topology', probe3b.present && probe3b.text.includes('cs-') ? 'pass' : 'fail',
    probe3b.present ? `text=${probe3b.text.slice(0, 120)}` : 'no .wb-lanemap when only catalog carries the topology')
}

// ---------------------------------------------------------------- main

const pw = await loadPlaywright().catch(() => null)
if (!pw) {
  record('S0 playwright', 'env_fail', 'playwright-core 不可解析（KI-036 家族：ui-check 依赖缺席，恢复后自动生效）')
  summarize()
}
const browser = await launchBrowser(pw)
if (!browser) {
  record('S0 chromium', 'env_fail', '无可启动的 chromium/chrome（headless）')
  summarize()
}

try {
  const page = await browser.newPage()
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
    const url = new URL(route.request().url())
    const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
    const m = url.pathname.match(/tickets\/([^/]+)$/)
    if (m && DETAIL_BY_ID[m[1]]) return body({ ok: true, result: DETAIL_BY_ID[m[1]] })
    if (url.searchParams.has('id') && DETAIL_BY_ID[url.searchParams.get('id')]) {
      return body({ ok: true, result: DETAIL_BY_ID[url.searchParams.get('id')] })
    }
    // 列表聚合口契约：result.tickets 行集 + 顶层 workflows 目录
    return body({ ok: true, result: { tickets: ROWS }, workflows: catalog })
  })

  await scenario(page, null)
  await browser.close()
} catch (e) {
  const msg = String(e)
  if (/playwright|chromium|Executable|browser/i.test(msg)) {
    record('browser availability', 'env_fail', msg.slice(0, 200))
  } else {
    record('scenario driver', 'fail', msg.slice(0, 300))
  }
}
summarize()
