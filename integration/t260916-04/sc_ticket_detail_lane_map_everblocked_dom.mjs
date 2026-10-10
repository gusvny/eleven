// sc_ticket_detail_lane_map_everblocked_dom.mjs — t260916-04 泳道图受阻着色语义 DOM 对拍
// （历史已解除受阻不得显示为当前受阻红：完成色＋「曾受阻」角标＋悬停经过；保守兜底边界）。
//
// Intent (black-box, user perspective)：宿主打开工单详情泳道图，对「曾受阻」的段读到的是
// **当前语义**而非「最后一条流水」——
//   L1 复现子用例（t260916-02 实证形态）：implement 段同刻双记录 done＋blocked（受保护路径闸
//      拒绝落盘），其后兄弟段 design_integration_tests done（不构成推进证据）、工作流推进到
//      run_integration_tests——该段必须画完成色（data-vis=done，绝不是当前受阻红），节点挂
//      「曾受阻」角标（data-ever-blocked=true），悬停出经过：何时受阻（受阻条目 at）＋何因
//      （blocked reason）＋如何解除（已解除＋推进措辞）；
//   L2 真当前受阻子用例：受阻未解除（其后无任何证据）→ 实心红语义（data-vis=blocked）且**无**
//      角标；全图零误标角标（无受阻史的段绝不带 data-ever-blocked）；
//   L3 疑难子用例（保守兜底③「宁可吓人，不许漏报」）：
//      L3a 受阻后零后续证据 → 保持当前受阻、无角标；
//      L3b 并行兄弟陷阱：gather 里 implement 受阻后同组兄弟 design_integration_tests done
//          ——兄弟的 done **不是** implement 的解除证据 → implement 保持红且无角标
//          （兄弟段自身颜色走既有回退语义，非本票契约，不断言）；
//      L3c authorized 授权条目单独不构成解除（人放了话≠活干成了，t260912-03 通道留痕）
//          → 不亮完成色、不出角标；
//   L4 关闭票子用例（④）：closed 票的历史受阻段 → 完成色＋角标（hover 出「已解除」；
//      261001：hover 文案随 260925 英文令为 `Blocked N× before · … · Resolved (…)`，
//      判据按双语等价格匹配，四项语义（何时/何因/已解除/机制）一个不少）；
//   L5 重跑解除子用例（E1）：本段受阻后重跑 done → 完成色＋角标（解除措辞出「重跑」或「推进」，
//      E1/E2 双证时不锁机制词选择，只锁「已解除」必在场）；
//   L6 降级面：拓扑缺席回落线性步骤条时吃**同一推导**——t260916-02 实证形态在该面同样不得
//      停留 blocked 态（stale 红消除是一处推导两处消费，不是泳道图私有）。
//
// 高层步骤（high-level steps）：S0 build-contract（纯 node：twin bundle 同步＋ever-blocked
// 契约新鲜锚）→ S1 隔离测试台＋API 边界桩（page.route 拦 tickets/workflows 两路由，数据全
// 夹具）→ 逐子用例换桩（applyLeg：关抽屉→reload→进板→开抽屉）→ 断言 DOM 公开契约（wb-lm-node
// 的 data-vis / data-ever-blocked / title；步骤条 .wb-d2-step[data-s]）→ P 卫生子用例（全旅程零
// pageerror/console.error）。
//
// DOM 契约锚（方案 §改动清单 3 的公开 data-* 面，非内部实现）：节点 span 挂
// data-ever-blocked="true"＋角标元素 class wb-lm-ever＋title 给经过；步骤条沿用
// .wb-d2-step[data-s] 既有契约。
//
// 分工（防 intent 级重复）：t260915-05-detail-lane-map-dom 锁详情渲染面**通用**契约（并行
// 双道/红灯翻译/人门蓝卡/轮次带/关单可见/渲染器通用性/降级回落/检查明细）——本条不复断其
// 任何一面，只锁「受阻史的图面投影语义」这一新面；t260911-05 锁红卡四件 payload→pixel；
// t260901-09 锁现行步骤条并行双亮（本条 L6 只断降级面吃新推导，不断其双亮面）；developer
// UT（lane-blocked-history 纯推导矩阵）锁 L1 函数层——本条锁 JSX 运行时接线/落位/两消费面。
//
// 借用清单（岗位纪律·review_plan 意见 1 落实；借 t260915-05 场景骨架）：
//   ① 隔离台（lib_stage_console.ensureStageConsole＋3099 拒跑红线）——带；
//   ② ENV_FAIL exit-2 三态（台/playwright-core/chromium 缺席=exit 2 环境红，不假绿、
//      不以零退出装跑过）——带；
//   ③ API 边界 page.route 桩（tickets/workflows 两路由，glob ** 结尾，未知子路由 ok:false
//      绝不漏真台）——带；
//   ④ wb-lm-* data-* 清点契约（断言绑公开 data-*/title，不绑内部结构/私有名）——带
//      （扩采 data-ever-blocked 键）；
//   ⑤ 场景登记（run_scenarios.py SCENARIOS 三元组，sc_ 未登记=lint L5 红）——带
//      （条目 t260916-04-lane-map-everblocked-dom）。
//   不带：t260915-05 的红灯翻译/状态卡四件/蓝卡/检查明细区断言面——非本票语义，复制即
//   双维护（其正确性由该票自身场景守）。
//
// 用例设计依据（三依据穷尽）：①工单验收①②③④⑤逐条↔子用例映射见 Intent；②KI-019（open，
// 泳道图呈现失真族）：夹具 timeline 全按引擎真留痕形态编码（数组序=时序、同刻双记录、
// phase 并行相位），本推导与既有规则 2 同一顺序契约，不新增乱序暴露面；③对外契约=泳道图
// DOM data-* 契约＋方案 §语义口径（E1 同段 done／E2 后段非兄弟条目／E3 closed）。
//
// Execution contract (t260904-12 three-state)：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全 na → exit 1；
// env_fail>0 → exit 2。实现段落地前 L1/L4/L5/L6/S0 新鲜锚红属预期（TDD 信号），
// arbitrate/merge 期必须绿；**L2/L3a/L3b/L3c 保守子用例任何时刻都不得红**（红=把未解除的受阻
// 画成完成色，比 stale 红更危险——漏报）。隔离台/playwright/chromium 缺席=ENV_FAIL exit 2
// （KI-036 点名面）。Node >= 22.18。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;
const FID = 't26091604dom' // fixture ticket id (alnum only; never a real ticket)
// 每子用例截图落 .sandbar/screenshots/（t260916-04 UI 证据面：改动前后可对比；implement 段加，
// 截图失败不拦断言——证据尽力而为，断言面不受影响）。SANDBAR_SHOT_TAG=before|after
// 区分改动前后两摄（同名覆盖防混淆）。
const SHOT_TAG = process.env.SANDBAR_SHOT_TAG ? `${process.env.SANDBAR_SHOT_TAG}-` : ''
const SHOT_DIR = join(REPO, '.sandbar', 'screenshots')
async function shot(p, slug) {
  try {
    mkdirSync(SHOT_DIR, { recursive: true })
    await p.screenshot({ path: join(SHOT_DIR, `t260916-04-${SHOT_TAG}${slug}.png`), fullPage: false })
  } catch { /* 尽力而为 */ }
}

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

// ---------------------------------------------------------------- 拓扑夹具（契约形状，
// 与 t260915-05 同一引擎导出契约：nodes[id,label,role,kind,optional?]+edges+groups）

const TOPO_DEVLANE = {
  template: 'dev-lane', name: '开发泳道',
  nodes: [
    { id: 'create_plan', label: '做方案', role: 'developer', kind: 'agent' },
    { id: 'review_plan', label: '审方案', role: 'integration', kind: 'agent' },
    { id: 'implement', label: '实现', role: 'developer', kind: 'agent' },
    { id: 'design_integration_tests', label: '设计集成测试', role: 'integration', kind: 'agent' },
    { id: 'run_integration_tests', label: '跑集成测试', role: 'integration', kind: 'gate' },
    { id: 'merge_check', label: '合并检查', role: 'integration', kind: 'gate' },
    { id: 'merge', label: '合并', role: 'integration', kind: 'human' },
  ],
  edges: [
    ['create_plan', 'review_plan'],
    ['review_plan', 'implement'], ['review_plan', 'design_integration_tests'],
    ['implement', 'run_integration_tests'], ['design_integration_tests', 'run_integration_tests'],
    ['run_integration_tests', 'merge_check'],
    ['merge_check', 'merge'],
  ],
  groups: [
    { id: 'parallel_impl_design', members: ['implement', 'design_integration_tests'], phase: 'parallel_impl_design' },
  ],
}
const wfRow = (topo) => ({
  id: topo.template, name: topo.name, lane: 'worktree',
  stages: topo.nodes.map(n => ({ id: n.id, name: n.label, role: n.role, parts: ['agent'] })),
  topology: topo,
})
const WF_DEVLANE = wfRow(TOPO_DEVLANE)
// 拓扑缺席（L6 降级面）：同 workflow id、无 topology 键 → 详情页回落线性步骤条。
const WF_NO_TOPO = { id: 'dev-lane', name: '开发泳道', lane: 'worktree', stages: WF_DEVLANE.stages }

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const SRC_LS = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'lane-states.ts')
const SRC_LM = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'lane-map.tsx')

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
  if (!js.includes('wb-lanemap') || !js.includes('wb-lm-')) {
    record('S0 build-contract', 'fail', 'shipped bundle missing lane-map anchors — stale lib?')
    return false
  }
  // ever-blocked 契约新鲜锚（工单验收⑤「src 改后必须重建 lib」的本票特化面）：
  // src 已落 data-ever-blocked 而 bundle 没有 = 拿旧 bundle 对拍会假红/假绿，响亮点名重建。
  const srcFresh = [SRC_LS, SRC_LM].filter(existsSync)
    .map(f => readFileSync(f, 'utf8'))
    .some(t => t.includes('ever-blocked'))
  if (srcFresh && !js.includes('ever-blocked')) {
    record('S0 build-contract', 'fail',
      'src/client 已落 ever-blocked 契约而 lib bundle 无——改源后必须重建 lib（build-client.sh）')
    return false
  }
  record('S0 build-contract', 'pass',
    srcFresh ? 'twin bundles in sync, ever-blocked contract fresh in bundle'
             : 'twin bundles in sync（src 未落 ever-blocked——TDD 前段，行为子用例红属预期）')
  return true
}

// ---------------------------------------------------------------- S1 fixtures

const ROW = {
  id: FID, role: 'developer', status: 'dispatched', title: '受阻着色语义打桩工单',
  workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
  handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}

let currentDetail = null
let currentWorkflows = null

// t260916-02 实证时刻：同刻双记录（done＋blocked 同一 at 字符串）——数组序=时序契约的
// 实锚形态，hover「何时受阻」以它断言。
const AT_BLOCKED = '2026-09-15T23:57:07'
const AT_LATER = '2026-09-15T23:58:30'
const AT_BASE = '2026-09-15T23:50:00'
const REASON_PROTECTED = '受保护路径闸拒绝落盘：docs/design/metrics-api-contract-v1.md'

const tle = (stage, state, reason = '', gen, phase, at = AT_BASE) => ({
  at, stage, state, reason,
  ...(gen !== undefined ? { gen } : {}),
  ...(phase ? { phase } : {}),
})

function detailBase(over) {
  return {
    id: FID, title: ROW.title, workflow_id: 'dev-lane', epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'implement', stage_state: 'running', stage_name: '实现',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [], body: 'DOM 级渲染打桩（不进 Temporal）', write_set: [],
    timeline: [], gens: {}, gate_runs: [], human_context: {}, blocked_detail: null,
    blocked_reason: '', meta: {}, ...over,
  }
}

const resultsThrough = (ids, gen = 1) => Object.fromEntries(ids.map(id => [id, { status: 'ok', gen }]))

// L1 复现子用例：t260916-02 实证形态——done＋blocked 同刻相邻，兄弟 done 在后（不构成证据），
// 工作流推进到 run_integration_tests（真推进证据）。
const DETAIL_ADVANCED = detailBase({
  stage: 'run_integration_tests', stage_name: '跑集成测试', stage_state: 'running',
  results: resultsThrough(['create_plan', 'review_plan']),
  timeline: [
    tle('create_plan', 'done', '', 1),
    tle('review_plan', 'done', '', 1),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
    tle('implement', 'done', '', 1, 'parallel_impl_design', AT_BLOCKED),
    tle('implement', 'blocked', REASON_PROTECTED, 1, 'parallel_impl_design', AT_BLOCKED),
    tle('design_integration_tests', 'done', '', 1, 'parallel_impl_design', AT_LATER),
    tle('run_integration_tests', 'running', '', 1, '', AT_LATER),
  ],
  gens: { create_plan: 1, review_plan: 1, implement: 1, design_integration_tests: 1, run_integration_tests: 1 },
})

// L2 真当前受阻子用例：merge_check 受阻，其后无任何证据。
const DETAIL_REAL_BLOCKED = detailBase({
  stage: 'merge_check', stage_name: '合并检查', stage_state: 'blocked',
  blocked_reason: 'merge_check 红灯：泳道内 verify_lane code 绿灯: exit=1 red=1',
  results: resultsThrough(['create_plan', 'review_plan']),
  timeline: [
    tle('create_plan', 'done', '', 1),
    tle('review_plan', 'done', '', 1),
    tle('implement', 'done', '', 1, 'parallel_impl_design'),
    tle('design_integration_tests', 'done', '', 1, 'parallel_impl_design'),
    tle('run_integration_tests', 'done', '', 1),
    tle('merge_check', 'running', '', 1, '', AT_LATER),
    tle('merge_check', 'blocked', 'verify_red', 1, '', AT_LATER),
  ],
  gens: { create_plan: 1, review_plan: 1, implement: 1, design_integration_tests: 1, run_integration_tests: 1, merge_check: 1 },
})

// L3a 疑难子用例·零后续：implement 受阻后无任何条目（本段无 done、无后段推进）。
const DETAIL_NO_EVIDENCE = detailBase({
  stage: 'implement', stage_name: '实现', stage_state: 'blocked',
  blocked_reason: REASON_PROTECTED,
  results: resultsThrough(['create_plan', 'review_plan']),
  timeline: [
    tle('create_plan', 'done', '', 1),
    tle('review_plan', 'done', '', 1),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
    tle('implement', 'done', '', 1, 'parallel_impl_design', AT_BLOCKED),
    tle('implement', 'blocked', REASON_PROTECTED, 1, 'parallel_impl_design', AT_BLOCKED),
  ],
  gens: { create_plan: 1, review_plan: 1, implement: 1 },
})

// L3b 疑难子用例·并行兄弟陷阱：implement 受阻后**同组**兄弟 design_integration_tests done
// （mid-gather 实况：parallel_stages 在场）——兄弟 done 不是 implement 的解除证据。
const DETAIL_SIBLING_TRAP = detailBase({
  stage: 'implement', stage_name: '实现', stage_state: 'blocked',
  blocked_reason: REASON_PROTECTED,
  meta: { parallel_stages: ['implement', 'design_integration_tests'], parallel_phase: 'parallel_impl_design' },
  results: resultsThrough(['create_plan', 'review_plan']),
  timeline: [
    tle('create_plan', 'done', '', 1),
    tle('review_plan', 'done', '', 1),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
    tle('implement', 'done', '', 1, 'parallel_impl_design', AT_BLOCKED),
    tle('implement', 'blocked', REASON_PROTECTED, 1, 'parallel_impl_design', AT_BLOCKED),
    tle('design_integration_tests', 'running', '', 1, 'parallel_impl_design', AT_LATER),
    tle('design_integration_tests', 'done', '', 1, 'parallel_impl_design', AT_LATER),
  ],
  gens: { create_plan: 1, review_plan: 1, implement: 1, design_integration_tests: 1 },
})

// L3c 疑难子用例·授权非解除：authorized 条目（t260912-03 引擎留痕形态：当前段、无 gen/phase）
// 单独不构成解除——不亮完成色、不出角标（人放了话≠活干成了）。
const DETAIL_AUTHORIZED_ONLY = detailBase({
  stage: 'implement', stage_name: '实现', stage_state: 'blocked',
  blocked_reason: REASON_PROTECTED,
  results: resultsThrough(['create_plan', 'review_plan']),
  timeline: [
    tle('create_plan', 'done', '', 1),
    tle('review_plan', 'done', '', 1),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
    tle('implement', 'done', '', 1, 'parallel_impl_design', AT_BLOCKED),
    tle('implement', 'blocked', REASON_PROTECTED, 1, 'parallel_impl_design', AT_BLOCKED),
    { at: AT_LATER, stage: 'implement', state: 'authorized',
      reason: '人授权签发（kind=protected_path）：scope=写 docs/design/metrics-api-contract-v1.md 理由=宿主放行' },
  ],
  gens: { create_plan: 1, review_plan: 1, implement: 1 },
})

// L4 关闭票子用例：closed 票 + create_plan 受阻史（blocked 后本段重跑 done、全链收口）。
const DETAIL_CLOSED = detailBase({
  status: 'closed', stage: 'merge', stage_name: '合并', stage_state: 'done',
  results: { ...resultsThrough(['create_plan'], 2), ...resultsThrough(
    ['review_plan', 'implement', 'design_integration_tests', 'run_integration_tests', 'merge_check', 'merge']) },
  timeline: [
    tle('create_plan', 'running', '', 1),
    tle('create_plan', 'blocked', '验收口径缺三红场景', 1, '', AT_BLOCKED),
    tle('create_plan', 'running', '', 2),
    tle('create_plan', 'done', '', 2),
    tle('review_plan', 'done', '', 2),
    tle('implement', 'done', '', 1, 'parallel_impl_design'),
    tle('design_integration_tests', 'done', '', 1, 'parallel_impl_design'),
    tle('run_integration_tests', 'done', '', 1),
    tle('merge_check', 'done', '', 1),
    tle('merge', 'done', '', 1),
  ],
  gens: { create_plan: 2, review_plan: 2, implement: 1, design_integration_tests: 1, run_integration_tests: 1, merge_check: 1, merge: 1 },
})

// L5 重跑解除子用例（E1）：create_plan 受阻后本段重跑 done（g2），票仍在途（非 closed）。
const DETAIL_RERUN = detailBase({
  stage: 'implement', stage_name: '实现', stage_state: 'running',
  results: { create_plan: { status: 'ok', gen: 2 }, review_plan: { status: 'ok', gen: 1 } },
  timeline: [
    tle('create_plan', 'running', '', 1),
    tle('create_plan', 'blocked', '验收口径缺三红场景', 1, '', AT_BLOCKED),
    tle('create_plan', 'running', '', 2),
    tle('create_plan', 'done', '', 2),
    tle('review_plan', 'done', '', 2),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
  ],
  gens: { create_plan: 2, review_plan: 2, implement: 1 },
})

// L6 降级面（拓扑缺席）：与 L1 同一 t260916-02 实证形态，走线性步骤条。
const DETAIL_NO_TOPO = detailBase({
  ...DETAIL_ADVANCED,
})

// ---------------------------------------------------------------- S1 infra (precedent:
// sc_ticket_detail_lane_map_dom.mjs 骨架，借用清单见文件头)

function consoleHealthy() {
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) })
    .then(r => r.ok)
    .catch(() => false)
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

// 泳道图 DOM 清点（run in page context）：wb-lm-* 族全量回收＋data-ever-blocked 契约键
// （t260915-05 骨架的扩采版：多收一个键，其余逐字同族）。
const domMapInventory = `(() => {
  const els = [...document.querySelectorAll('[class*="wb-lanemap"], [class*="wb-lm-"]')];
  return els.map(el => ({
    // t261009-53 起图面=SVG 场景：SVG 元素的 className 是 SVGAnimatedString，取 baseVal
    cls: typeof el.className === 'string' ? el.className : String(el.className.baseVal || ''), text: (el.textContent || '').slice(0, 120),
    title: el.getAttribute('title') || '',
    dataKind: el.getAttribute('data-kind') || '', dataId: el.getAttribute('data-id') || '',
    dataVis: el.getAttribute('data-vis') || '', dataGen: el.getAttribute('data-gen') || '',
    dataGroup: el.getAttribute('data-group') || '',
    dataEverBlocked: el.getAttribute('data-ever-blocked') || '',
  }));
})()`
const domMapRoot = `document.querySelectorAll('.wb-lanemap').length`
const domSteps = `(() => [...document.querySelectorAll('.wb-d2-steps .wb-d2-step')]
  .map(el => ({ t: (el.textContent || '').trim(), s: el.getAttribute('data-s') || '' })))()`

async function snap(p) {
  try {
    const map = await p.evaluate(domMapInventory)
    const steps = await p.evaluate(domSteps).catch(() => [])
    return `mapEls=${map.length} steps=${steps.length} firstMap=${JSON.stringify(map[0] || null).slice(0, 140)}`
  } catch { return '(snapshot unavailable)' }
}

/** 节点查找：wb-lm-node 且 data-id 命中；缺席=undefined（断言侧点名）。 */
function nodeOf(inv, id) {
  return inv.find(x => x.dataId === id && String(x.cls).includes('wb-lm-node'))
}

/** 角标零误标：全图不存在 wb-lm-ever 元素、不存在 data-ever-blocked=true 的节点。 */
function noFalseBadge(inv) {
  if (inv.some(x => String(x.cls).includes('wb-lm-ever'))) return '出现了 wb-lm-ever 角标元素'
  if (inv.some(x => x.dataEverBlocked === 'true')) return '出现了 data-ever-blocked=true 节点'
  return null
}

/**
 * hover 经过断言：节点 title＋角标 title 拼接含 何时(at)＋何因(reason 片段)＋**已解除**＋机制词。
 *
 * 261001 口径同步：宿主 260925「控制台 UI 界面文案一律英文」令之后，这段 hover 文案由
 * `lane-map.everBlockedTitle()` 产出英文（`Blocked N× before · <at> · <reason> · Round N ·
 * Resolved (<机制>)`；机制词表=RESOLVED_HOW：`stage rerun completed` / `workflow advanced to
 * later stages` / `ticket closed`）。契约意图不变（**何时/何因/已解除/机制**四项都在场），
 * 故判据按**双语等价格**匹配：中文期望值映射到对应英文形态（英文面大小写不敏感），
 * `at` 与 `reasonFragment` 仍按**数据原文**比对（它们来自夹具数据，不随界面语言变）。
 */
const EVER_BILINGUAL = {
  '曾受阻': /曾受阻|Blocked\s+\d+×\s+before|was blocked/i,
  '已解除': /已解除|Resolved/i,
  '推进': /推进|advanced/i,
  '重跑': /重跑|rerun/i,
}
function _everHit(story, word) {
  const re = EVER_BILINGUAL[word]
  return re ? re.test(story) : story.includes(word)
}
function hoverHasStory(inv, id, { at, reasonFragment, mustWord, altWord }) {
  const node = nodeOf(inv, id)
  if (!node) return `未找到 ${id} 节点`
  const everTitles = inv.filter(x => String(x.cls).includes('wb-lm-ever')).map(x => x.title)
  const story = `${node.title} ${everTitles.join(' ')}`
  const miss = []
  if (!_everHit(story, '曾受阻')) miss.push('「曾受阻」字样')
  if (at && !story.includes(at)) miss.push(`受阻时刻 ${at}`)
  if (reasonFragment && !story.includes(reasonFragment)) miss.push(`受阻原因「${reasonFragment}」`)
  if (!_everHit(story, '已解除')) miss.push('「已解除」')
  if (mustWord && !_everHit(story, mustWord) && !(altWord && _everHit(story, altWord))) {
    miss.push(`解除机制词「${mustWord}」${altWord ? `（或「${altWord}」）` : ''}`)
  }
  return miss.length ? `hover 经过不全（title="${story.slice(0, 160)}"，缺 ${miss.join('、')}）` : null
}

/** 换子用例：改桩→reload（路由桩跨 reload 存活）→进板→开抽屉→等泳道图或步骤条渲染。 */
async function applyLeg(page, boardIcon, detail, workflows) {
  currentDetail = detail
  currentWorkflows = workflows
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
    (await page.locator('.wb-lanemap, .wb-d2-steps').count()) > 0, 10000)
  if (!ok) throw new Error('neither lane map nor stepper rendered after row click')
}

// ---------------------------------------------------------------- 断言子用例

async function scenarioAdvanced(page) {
  return await (async () => {
    const inv = await page.evaluate(domMapInventory)
    if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
    const node = nodeOf(inv, 'implement')
    if (!node) return 'implement 节点缺席'
    if (node.dataVis !== 'done') return `implement 段仍显示当前受阻语义（data-vis=${node.dataVis}，t260916-02 实证形态应画完成色）`
    if (node.dataEverBlocked !== 'true') return 'implement 节点缺 data-ever-blocked=true（「曾受阻」角标契约）'
    const storyErr = hoverHasStory(inv, 'implement', {
      at: AT_BLOCKED, reasonFragment: '受保护路径闸', mustWord: '推进',
    })
    if (storyErr) return storyErr
    // 无受阻史的段绝不带角标（误标=完成色语义被稀释）
    for (const id of ['review_plan', 'design_integration_tests', 'run_integration_tests']) {
      const n = nodeOf(inv, id)
      if (n && n.dataEverBlocked === 'true') return `${id} 无受阻史却被标 ever-blocked（角标误标）`
    }
    return null
  })()
}

async function scenarioRealBlocked(page) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
  const node = nodeOf(inv, 'merge_check')
  if (!node) return 'merge_check 节点缺席'
  if (node.dataVis !== 'blocked') return `真当前受阻未显受阻语义（data-vis=${node.dataVis}，应保持 blocked）`
  if (node.dataEverBlocked === 'true') return '未解除的受阻带了「曾受阻」角标（完成色语义误标，比 stale 红更危险）'
  const falseBadge = noFalseBadge(inv)
  if (falseBadge) return falseBadge
  return null
}

async function scenarioNoEvidence(page) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
  const node = nodeOf(inv, 'implement')
  if (!node) return 'implement 节点缺席'
  if (node.dataVis !== 'blocked') return `受阻后零后续证据应保持当前受阻（data-vis=${node.dataVis}，保守兜底③被击穿）`
  const falseBadge = noFalseBadge(inv)
  if (falseBadge) return falseBadge
  return null
}

async function scenarioSiblingTrap(page) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
  const node = nodeOf(inv, 'implement')
  if (!node) return 'implement 节点缺席'
  if (node.dataVis !== 'blocked') return `并行兄弟 done 被误当推进证据（implement data-vis=${node.dataVis}，应保持 blocked）`
  if (node.dataEverBlocked === 'true') return 'implement 未解除却带「曾受阻」角标（兄弟 done 被误记为解除）'
  // 注：兄弟段自身此刻显 todo 而非 done 是既有「活跃空集→单值指针回退」语义
  // （t260901-05 遗产，受阻钉住+兄弟 done 钉住→活跃空集），非本票契约，不断言其颜色。
  const falseBadge = noFalseBadge(inv)
  if (falseBadge) return falseBadge
  return null
}

async function scenarioAuthorizedOnly(page) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
  const node = nodeOf(inv, 'implement')
  if (!node) return 'implement 节点缺席'
  if (node.dataVis === 'done') return 'authorized 条目单独把受阻段画成完成色（人放了话≠活干成了，保守③被击穿）'
  const falseBadge = noFalseBadge(inv)
  if (falseBadge) return falseBadge
  return null
}

async function scenarioClosed(page) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
  const node = nodeOf(inv, 'create_plan')
  if (!node) return 'create_plan 节点缺席'
  if (node.dataVis !== 'done') return `closed 票历史受阻段未显完成色（data-vis=${node.dataVis}，工单④）`
  if (node.dataEverBlocked !== 'true') return 'closed 票历史受阻段缺「曾受阻」角标（工单④）'
  const storyErr = hoverHasStory(inv, 'create_plan', {
    at: AT_BLOCKED, reasonFragment: '验收口径', mustWord: '已解除',
  })
  if (storyErr) return storyErr
  return null
}

async function scenarioRerun(page) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染 @ ${await snap(page)}`
  const node = nodeOf(inv, 'create_plan')
  if (!node) return 'create_plan 节点缺席'
  if (node.dataVis !== 'done') return `本段重跑 done 未显完成色（data-vis=${node.dataVis}，E1）`
  if (node.dataEverBlocked !== 'true') return '本段重跑解除缺「曾受阻」角标（E1）'
  const storyErr = hoverHasStory(inv, 'create_plan', {
    at: AT_BLOCKED, reasonFragment: '验收口径', mustWord: '重跑', altWord: '推进',
  })
  if (storyErr) return storyErr
  return null
}

async function scenarioFallbackNoTopo(page) {
  const mapN = await page.evaluate(domMapRoot).catch(() => -1)
  if (mapN !== 0) return `拓扑缺席时泳道图仍渲染（应回落步骤条）：.wb-lanemap=${mapN}`
  const steps = await page.evaluate(domSteps).catch(() => [])
  if (!steps.length) return `回落步骤条未渲染 @ ${await snap(page)}`
  // 261001 口径同步：实施段名随 260925 英文令上屏为 "Implement"（旧形态中文「实现」仍在
  // 老快照/老拓扑里）——契约意图「步骤条带实施段、且该段不再是 blocked」不变，判据双语。
  const step = steps.find(x => /实现|Implement/i.test(String(x.t)))
  if (!step) return `步骤条缺实施段（中文「实现」或英文 "Implement"）（steps=${JSON.stringify(steps).slice(0, 160)}）`
  if (step.s === 'blocked') {
    return `降级步骤条仍显示 blocked（data-s=${step.s}）——stale 红是一处推导两处消费，泳道图治了步骤条不能留`
  }
  return null
}

// ---------------------------------------------------------------- S1 runner

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

    // API 边界桩：列表+详情+模板列表全夹具；未知 id/子路由 ok:false（绝不漏到真台）。
    currentDetail = DETAIL_ADVANCED
    currentWorkflows = [WF_DEVLANE]
    await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
      if (path === '/sandbar-workbench/api/wf/tickets') {
        return body({ ok: true, result: { tickets: [ROW] }, workflows: currentWorkflows })
      }
      const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && decodeURIComponent(m[1]) === FID) return body({ ok: true, result: currentDetail })
      return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
    })
    await page.route('**/sandbar-workbench/api/wf/workflows**', (route) => {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: currentWorkflows }) })
    })

    const boardIcon = page.locator('span.wb-view-icon[title="Tickets"]').first()
    if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `no board icon found on ${BASE} (console not provisioned for board view)`)
      return
    }
    await boardIcon.click()
    const rowOk = await waitFor(async () =>
      (await page.locator('.wb-card[data-ticket-id]', { hasText: FID }).count()) > 0, 10000)
    if (!rowOk) {
      record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
      return
    }

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
    const leg = async (name, slug, detail, workflows, fn) => {
      try {
        await applyLeg(page, boardIcon, detail, workflows)
        await shot(page, slug)
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
    }

    await leg('L1 复现子用例：同刻 done+blocked 已推进解除（完成色+角标+经过）', 'L1-advanced', DETAIL_ADVANCED, [WF_DEVLANE], scenarioAdvanced)
    await leg('L2 真当前受阻：未解除保持受阻语义且全图零角标', 'L2-real-blocked', DETAIL_REAL_BLOCKED, [WF_DEVLANE], scenarioRealBlocked)
    await leg('L3a 疑难子用例：受阻后零后续证据保持受阻（保守③）', 'L3a-no-evidence', DETAIL_NO_EVIDENCE, [WF_DEVLANE], scenarioNoEvidence)
    await leg('L3b 疑难子用例：并行兄弟 done 不构成推进证据', 'L3b-sibling-trap', DETAIL_SIBLING_TRAP, [WF_DEVLANE], scenarioSiblingTrap)
    await leg('L3c 疑难子用例：authorized 单独不构成解除', 'L3c-authorized', DETAIL_AUTHORIZED_ONLY, [WF_DEVLANE], scenarioAuthorizedOnly)
    await leg('L4 关闭票子用例：closed 票历史受阻段完成色+角标', 'L4-closed', DETAIL_CLOSED, [WF_DEVLANE], scenarioClosed)
    await leg('L5 重跑解除子用例：本段 done 解除（E1）角标+经过', 'L5-rerun', DETAIL_RERUN, [WF_DEVLANE], scenarioRerun)
    await leg('L6 降级面：拓扑缺席步骤条吃同一推导（stale 红消除）', 'L6-fallback', DETAIL_NO_TOPO, [WF_NO_TOPO], scenarioFallbackNoTopo)

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

  buildContract()

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

  try {
    await runBrowser(pw, browser)
  } finally {
    await browser.close().catch(() => {})
  }
  summarize()
}

await main()
