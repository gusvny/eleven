// sc_ticket_detail_lane_map_dom.mjs — t260915-05 详情观测面重设计的 DOM 级对拍基线
// （真泳道图＋人话状态卡蓝子用例＋检查明细区＋红灯翻译层＋渲染器通用性，验收①②③）。
//
// Intent (black-box, user perspective)：宿主打开工单详情抽屉时，按 mock ①②③④
// （260904-ticket-detail-ui-mock.html 宿主过稿）可感知到的新观测面：
//   L1 真泳道图：拓扑在场时以泳道图替换线性步骤条——并行双道虚线框
//      （implement∥design_integration_tests、arbitrate∥acceptance_walkthrough）、
//      人门虚线圈（merge kind=human）、节点标签全部来自拓扑（零业务词硬编码）；
//   L2 红灯翻译层：blocked 票面状态卡人话主文案来自词条表（同一组件两种 reason_code
//      出不同人话、绝不冒出裸引擎码当主文案）、文件点名/下一步来自 blocked_detail
//      结构化字段、原始日志 <details> 折叠可展开（UI 不翻译它没拿到的信息——files 空
//      则不凭空捏造文件 chip）；
//   L3 人门蓝卡：awaiting-human 时状态卡变蓝列出「签什么」（human_context.merge.
//      context_text＋stage_acceptance 数据源可读）；
//   L4 轮次带：同段多轮逐轮格（gens/timeline 的 gen 维度），hover 出该轮证据/打回
//      原因，返工史以 ×N 徽章呈现、图面保持单向流（节点数不因返工重复）；
//   L5 关单可见（KI-027）：closed 票详情同组件全图＋轮次带仍在（拓扑=模板导出通道，
//      不依赖活快照）；
//   L6 渲染器通用性（mock ④ callout G）：另一模板拓扑（fixture-two-step 线性两段）
//      同组件渲染，标签来自拓扑、DOM 零 dev-lane 业务词；
//   L7 降级锚：拓扑缺席回落现行线性步骤条（零回归锚）；畸形 topology/gens/timeline
//      不炸、零 pageerror；
//   L8 检查明细区（mock ① 成分）：gate_runs 逐轮逐条 ✓/✗＋item＋detail，红行点名
//      文件与状态卡文件清单联动，<details> 折叠可展开。
//
// 分工（防 intent 级重复）：t260911-05 sc_ki048_status_card_dom 已锁 merge-dirty 族
// 红卡四件 payload→pixel 与畸形 blocked_detail 不捏造文件——本条 L2 用 verify_red /
// main_dirty 两族只锁「翻译层词条表驱动」这一新面，不复断其四件形状；t260901-09
// lane-parallel-dom 锁现行步骤条并行双亮（本条 L7 反向守其降级回落不回归）；
// t260915-01 journey 锁数据面引擎半（本条全部数据为 API 桩夹具）；developer L1
// （lane-map-model 纯函数矩阵/status-card 词条表 UT）不同层——L1 锁不住 JSX 运行时
// 错/落位/降级渲染。
//
// Two layers (same split as sc_lane_parallel_dom.mjs)：
//   S0 build-contract (pure node, runs everywhere): shipped twin bundles in sync +
//      泳道图/词条表锚点在 bundle + buildLaneMap 纯模型冒烟（fixture 拓扑→组/节点齐全）。
//   S1 browser DOM：隔离测试台（SANDBAR_TEST_CONSOLE，缺 3099 红线零接触）＋
//      playwright-core＋chromium，任一缺席=ENV_FAIL exit 2。数据在 API 边界用
//      page.route() 桩：真浏览器/真 console/真 bundle/真 React 渲染链，只拦
//      /sandbar-workbench/api/wf/tickets** 与 /api/wf/workflows**（夹具快照/拓扑，
//      契约形状={template,name,nodes[{id,label,role,kind,optional?}],edges,groups}）。
//
// Execution contract (t260904-12 three-state)：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全 na → exit 1；
// env_fail>0 → exit 2。Node >= 22.18。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;
const FID = 't26091505dom' // fixture ticket id (alnum only; never a real ticket)

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

// ---------------------------------------------------------------- 拓扑夹具（契约形状）

// dev-lane 真并行拓扑（按引擎导出契约编码：节点+边+kind+并行组+人门标记；
// mock ③④ 的图面语义真源，不是线性近似链）。
const TOPO_DEVLANE = {
  template: 'dev-lane', name: '开发泳道',
  nodes: [
    { id: 'create_plan', label: '做方案', role: 'developer', kind: 'agent' },
    { id: 'review_plan', label: '审方案', role: 'integration', kind: 'agent' },
    { id: 'implement', label: '实现', role: 'developer', kind: 'agent' },
    { id: 'design_integration_tests', label: '设计集成测试', role: 'integration', kind: 'agent' },
    { id: 'ui_evidence', label: 'UI截图证据', role: 'developer', kind: 'agent', optional: '仅 UI 票' },
    { id: 'run_integration_tests', label: '跑集成测试', role: 'integration', kind: 'gate' },
    { id: 'arbitrate', label: '仲裁', role: 'integration', kind: 'agent' },
    { id: 'acceptance_walkthrough', label: '验收走查', role: 'integration', kind: 'agent' },
    { id: 'merge_check', label: '合并检查', role: 'integration', kind: 'gate' },
    { id: 'merge', label: '合并', role: 'integration', kind: 'human' },
  ],
  edges: [
    ['create_plan', 'review_plan'],
    ['review_plan', 'implement'], ['review_plan', 'design_integration_tests'],
    ['implement', 'ui_evidence'], ['design_integration_tests', 'ui_evidence'],
    ['ui_evidence', 'run_integration_tests'],
    ['run_integration_tests', 'arbitrate'], ['run_integration_tests', 'acceptance_walkthrough'],
    ['arbitrate', 'merge_check'], ['acceptance_walkthrough', 'merge_check'],
    ['merge_check', 'merge'],
  ],
  groups: [
    { id: 'parallel_impl_design', members: ['implement', 'design_integration_tests'], phase: 'parallel_impl_design' },
    { id: 'arb_acc_parallel', members: ['arbitrate', 'acceptance_walkthrough'], phase: 'arb_acc_parallel' },
  ],
}
// 另一 workflow 类拓扑（渲染器通用性对拍：线性两段、零并行组、零 dev-lane 业务词）。
const TOPO_FX = {
  template: 'fixture-two-step', name: '夹具两步',
  nodes: [
    { id: 'fx_step_one', label: '夹具段一', role: 'developer', kind: 'agent' },
    { id: 'fx_step_two', label: '夹具段二', role: 'developer', kind: 'agent' },
  ],
  edges: [['fx_step_one', 'fx_step_two']],
  groups: [],
}
const wfRow = (topo) => ({
  id: topo.template, name: topo.name, lane: 'worktree',
  stages: topo.nodes.map(n => ({ id: n.id, name: n.label, role: n.role, parts: ['agent'] })),
  ...(topo ? { topology: topo } : {}),
})
const WF_DEVLANE = wfRow(TOPO_DEVLANE)
const WF_FX = wfRow(TOPO_FX)
const WF_NO_TOPO = { id: 'dev-lane', name: '开发泳道', lane: 'worktree', stages: WF_DEVLANE.stages }

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const LANE_MAP_MODEL = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'lane-map-model.ts')

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
  const anchors = ['wb-lanemap', 'wb-lm-', 'wb-checks', '签什么', 'translateReason',
    'wb-status-card', 'wb-d2-step']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 build-contract', 'fail', `shipped bundle missing lane-map/lexicon anchors: ${missing.join(', ')}`)
    return false
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync, lane-map/lexicon anchors present')
  return true
}

async function modelSmoke() {
  if (!existsSync(LANE_MAP_MODEL)) {
    record('S0 lane-map-model', 'fail', 'lane-map-model.ts missing（渲染器纯模型模块未落地）')
    return false
  }
  try {
    const mod = await import(pathToFileURL(LANE_MAP_MODEL).href + '?t=' + Date.now())
    const build = mod.buildLaneMap
    if (typeof build !== 'function') {
      record('S0 lane-map-model', 'fail', 'lane-map-model.ts does not export buildLaneMap')
      return false
    }
    const detail = {
      stage: 'implement', stage_state: 'running',
      meta: { parallel_stages: ['implement', 'design_integration_tests'], parallel_phase: 'parallel_impl_design' },
      gens: { create_plan: 3, review_plan: 1, implement: 1 },
      timeline: [
        { at: 't', stage: 'create_plan', state: 'running', reason: '', gen: 1 },
        { at: 't', stage: 'create_plan', state: 'blocked', reason: '越界探针', gen: 1 },
        { at: 't', stage: 'create_plan', state: 'running', reason: '', gen: 2 },
        { at: 't', stage: 'review_plan', state: 'done', reason: '', gen: 1 },
        { at: 't', stage: 'implement', state: 'running', reason: '', gen: 1 },
      ],
    }
    const out = build(TOPO_DEVLANE, detail)
    const s = JSON.stringify(out ?? {})
    const need = ['create_plan', 'merge', 'parallel_impl_design', 'arb_acc_parallel']
    const miss = need.filter(a => !s.includes(a))
    if (miss.length) {
      record('S0 lane-map-model', 'fail', `model output missing contract anchors ${miss.join(',')}: ${s.slice(0, 200)}`)
      return false
    }
    record('S0 lane-map-model', 'pass', 'buildLaneMap consumes topology+detail, groups/nodes present')
    return true
  } catch (e) {
    record('S0 lane-map-model', 'fail', `lane-map-model.ts not importable: ${String(e).slice(0, 140)}`)
    return false
  }
}

// ---------------------------------------------------------------- S1 fixtures

const ROW = {
  id: FID, role: 'developer', status: 'dispatched', title: '泳道图 DOM 打桩工单',
  workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
  handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}

// API 桩状态（模块级：路由桩闭包与 applyLeg/leg 共读共写）。
let currentDetail = null
let currentWorkflows = null

const T = '2026-09-01T00:00:00'
const tle = (stage, state, reason = '', gen, phase) => ({
  at: T, stage, state, reason,
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

const FORK_META = { parallel_stages: ['implement', 'design_integration_tests'], parallel_phase: 'parallel_impl_design' }

// L1 分叉期：泳道图双道亮
const DETAIL_FORK = detailBase({
  meta: FORK_META,
  results: { create_plan: { status: 'ok', gen: 1 }, review_plan: { status: 'ok', gen: 1 } },
  timeline: [tle('create_plan', 'done', '', 1), tle('review_plan', 'done', '', 1),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
    tle('design_integration_tests', 'running', '', 1, 'parallel_impl_design')],
  gens: { create_plan: 1, review_plan: 1, implement: 1, design_integration_tests: 1 },
})

// L2a 翻译层：verify_red 族（结构化 files 空=UI 不得捏造文件 chip）
const DETAIL_RED_VERIFY = detailBase({
  stage: 'merge_check', stage_name: '合并检查', stage_state: 'blocked',
  blocked_reason: 'merge_check 红灯：泳道内 verify_lane code 绿灯: exit=1 red=1',
  blocked_detail: {
    check_id: 'verify_lane_code', item: '泳道内 verify_lane code 绿灯', red: true,
    reason_code: 'verify_red', files: [],
    next_action: '按 detail 里的红灯项修复后发 retry_qc 重验',
    evidence: '改动文件不在本票写集: server/zz_t26091505_probe.py',
  },
  results: { create_plan: { status: 'ok', gen: 1 }, review_plan: { status: 'ok', gen: 1 } },
  timeline: [tle('create_plan', 'done', '', 1), tle('review_plan', 'done', '', 1),
    tle('merge_check', 'running', '', 1), tle('merge_check', 'blocked', 'verify_red', 1)],
  gens: { create_plan: 1, review_plan: 1, merge_check: 1 },
})

// L2b 翻译层：main_dirty 族（files 结构化点名→文件 chip）＋同表不同词条=不同人话
const DETAIL_RED_DIRTY = detailBase({
  stage: 'merge_check', stage_name: '合并检查', stage_state: 'blocked',
  blocked_reason: 'merge 未收口（dirty/main_dirty）：main 工作区有无主未提交编辑',
  blocked_detail: {
    check_id: 'merge_check', item: 'main 工作区干净', red: true,
    reason_code: 'main_dirty', files: ['docs/契约v1.md'],
    next_action: '在 main 提交或暂存这些改动，或票面说明后发 retry_qc 重验',
    evidence: 'main 侧未提交编辑: docs/契约v1.md',
  },
  results: { create_plan: { status: 'ok', gen: 1 }, review_plan: { status: 'ok', gen: 1 } },
  timeline: [tle('create_plan', 'done', '', 1), tle('review_plan', 'done', '', 1),
    tle('merge_check', 'running', '', 1), tle('merge_check', 'blocked', 'main_dirty', 1)],
  gens: { create_plan: 1, review_plan: 1, merge_check: 1 },
})

// L3 人门蓝卡：「签什么」三源（human_context.merge.context_text＋stage_acceptance＋绿 gate_runs）
const DETAIL_HUMAN = detailBase({
  stage: 'merge', stage_name: '合并', stage_state: 'awaiting-human',
  human_context: { merge: { context_text: '签字要点：merge_check 已全绿；改动清单 2 文件；落账后泳道拆除' } },
  stage_acceptance: ['泳道分支有 commit', '泳道内 verify_lane code 绿灯'],
  gate_runs: [{ stage: 'merge_check', label: 'merge_check（程序化检查）', green: true, red_count: 0,
    exit_code: 0, checks: [{ item: '泳道分支有 commit', green: true, detail: '2 commits', id: 'lane_commits' }] }],
  results: { create_plan: { status: 'ok', gen: 1 }, review_plan: { status: 'ok', gen: 1 },
    merge_check: { status: 'ok', gen: 1 } },
  timeline: [tle('create_plan', 'done', '', 1), tle('review_plan', 'done', '', 1),
    tle('merge_check', 'done', '', 1), tle('merge', 'awaiting-human', '等人签字：sign(gate=merge)', 1)],
  gens: { create_plan: 1, review_plan: 1, merge_check: 1, merge: 1 },
})

// L4 轮次带：create_plan 三轮（第 1 轮越界被打回）＋分叉期活跃
const DETAIL_ROUNDS = detailBase({
  meta: FORK_META,
  results: { create_plan: { status: 'ok', gen: 3 }, review_plan: { status: 'ok', gen: 2 } },
  timeline: [
    tle('create_plan', 'running', '', 1), tle('create_plan', 'blocked', '改动文件不在本票写集（越界）', 1),
    tle('create_plan', 'running', '', 2), tle('create_plan', 'blocked', '验收口径缺三红场景', 2),
    tle('create_plan', 'done', '', 3), tle('review_plan', 'done', '', 2),
    tle('implement', 'running', '', 1, 'parallel_impl_design'),
    tle('design_integration_tests', 'running', '', 1, 'parallel_impl_design'),
  ],
  gens: { create_plan: 3, review_plan: 2, implement: 1, design_integration_tests: 1 },
})

// L5 关单可见（KI-027）：closed 终态＋返工史＋全拓扑
const DETAIL_CLOSED = detailBase({
  status: 'closed', stage: 'merge', stage_name: '合并', stage_state: 'done',
  results: { create_plan: { status: 'ok', gen: 2 }, review_plan: { status: 'ok', gen: 2 },
    arbitrate: { status: 'ok', gen: 1 }, acceptance_walkthrough: { status: 'ok', gen: 1 },
    merge_check: { status: 'ok', gen: 1 }, merge: { status: 'ok', gen: 1 } },
  timeline: [
    tle('create_plan', 'running', '', 1), tle('create_plan', 'blocked', '越界', 1),
    tle('create_plan', 'done', '', 2), tle('review_plan', 'done', '', 2),
    tle('implement', 'done', '', 1, 'parallel_impl_design'),
    tle('design_integration_tests', 'done', '', 1, 'parallel_impl_design'),
    tle('run_integration_tests', 'done', '', 1),
    tle('arbitrate', 'done', '', 1, 'arb_acc_parallel'),
    tle('acceptance_walkthrough', 'done', '', 1, 'arb_acc_parallel'),
    tle('merge_check', 'done', '', 1), tle('merge', 'done', '', 1),
  ],
  gens: { create_plan: 2, review_plan: 2, implement: 1, design_integration_tests: 1,
    run_integration_tests: 1, arbitrate: 1, acceptance_walkthrough: 1, merge_check: 1, merge: 1 },
  gate_runs: [{ stage: 'merge_check', label: 'merge_check（程序化检查）', green: true, red_count: 0,
    exit_code: 0, checks: [{ item: '泳道分支有 commit', green: true, detail: '3 commits', id: 'lane_commits' }] }],
  signatures: [{ who: '宿主', gate: 'merge', decision: 'approve', note: 'ok', ts: T }],
})

// L6 通用性：另一模板（fixture-two-step 线性）同组件
const DETAIL_FX = detailBase({
  workflow_id: 'fixture-two-step', stage: 'fx_step_two', stage_name: '夹具段二',
  stage_state: 'running',
  timeline: [tle('fx_step_one', 'done', '', 1), tle('fx_step_two', 'running', '', 1)],
  gens: { fx_step_one: 1, fx_step_two: 1 },
})

// L7 降级：无拓扑→现行步骤条；畸形 topology/gens/timeline→不炸
const DETAIL_NO_TOPO = detailBase({
  results: { create_plan: { status: 'ok', gen: 1 } },
  timeline: [tle('create_plan', 'done', '', 1), tle('review_plan', 'running', '', 1)],
  gens: { create_plan: 1, review_plan: 1 },
})
const DETAIL_MALFORMED = detailBase({
  topology: { nodes: 'garbage', edges: 7, groups: null },
  gens: 'abc',
  timeline: [{ at: T }, { at: T, stage: 123, state: 'running' }, tle('implement', 'running', '', 1)],
  meta: { parallel_stages: 'not-a-list' },
})

// L8 检查明细区：gate_runs 两轮（红含探针点名＋绿）＋红卡文件联动
const GATE_RUNS_PAIR = [
  { stage: 'merge_check', label: 'merge_check（程序化检查）', green: false, red_count: 1, exit_code: 0,
    checks: [{ item: '泳道内 verify_lane code 绿灯', green: false,
      detail: 'exit=1 red=1；改动文件不在本票写集: server/zz_t26091505_probe.py',
      id: 'verify_lane_code', reason_code: 'verify_red',
      next_action: '按 detail 里的红灯项修复后发 retry_qc 重验' }] },
  { stage: 'merge_check', label: 'merge_check（程序化检查）', green: true, red_count: 0, exit_code: 0,
    checks: [{ item: '泳道分支有 commit', green: true, detail: '3 commits', id: 'lane_commits' },
      { item: '泳道内 verify_lane code 绿灯', green: true, detail: 'exit=0 red=0', id: 'verify_lane_code' }] },
]
const DETAIL_CHECKS = detailBase({
  ...DETAIL_RED_DIRTY,
  gate_runs: GATE_RUNS_PAIR,
  blocked_detail: {
    check_id: 'verify_lane_code', item: '泳道内 verify_lane code 绿灯', red: true,
    reason_code: 'verify_red', files: ['server/zz_t26091505_probe.py'],
    next_action: '按 detail 里的红灯项修复后发 retry_qc 重验',
    evidence: '改动文件不在本票写集: server/zz_t26091505_probe.py',
  },
})

// ---------------------------------------------------------------- S1 infra (precedent: sc_lane_parallel_dom.mjs)

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

// 泳道图 DOM 清点（run in page context）：泳道图族类全量回收（根 wb-lanemap＋道内
// wb-lm-*；data-* 契约=id/kind/vis/gen/group）。
const domMapInventory = `(() => {
  const els = [...document.querySelectorAll('[class*="wb-lanemap"], [class*="wb-lm-"]')];
  return els.map(el => ({
    cls: el.className, text: (el.textContent || '').slice(0, 120),
    title: el.getAttribute('title') || '',
    dataKind: el.getAttribute('data-kind') || '', dataId: el.getAttribute('data-id') || '',
    dataVis: el.getAttribute('data-vis') || '', dataGen: el.getAttribute('data-gen') || '',
    dataGroup: el.getAttribute('data-group') || '',
  }));
})()`
const domMapRoot = `document.querySelectorAll('.wb-lanemap').length`
const domArcCount = `document.querySelectorAll('[class*="wb-lm-arc"]').length`
const domDrawerText = `(() => {
  const d = document.querySelector('.wb-drawer');
  return d ? d.textContent : document.body.textContent;
})()`
const domStepCount = `document.querySelectorAll('.wb-d2-steps .wb-d2-step').length`

async function snap(p) {
  try {
    const map = await p.evaluate(domMapInventory)
    const steps = await p.evaluate(domStepCount)
    return `mapEls=${map.length} steps=${steps} firstMap=${JSON.stringify(map[0] || null).slice(0, 140)}`
  } catch { return '(snapshot unavailable)' }
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

/** 泳道图在场的子用例断言跑法：先确认 wb-lanemap- 元素在场（缺席=fail 带诊断）。 */
async function withMap(page, name, fn) {
  const inv = await page.evaluate(domMapInventory)
  if (!inv.length) return `泳道图未渲染（wb-lanemap-* 元素=0，拓扑缺席或组件未接线）@ ${await snap(page)}`
  return await fn(inv)
}

// ---------------------------------------------------------------- S1 scenarios

async function scenarioLaneMapFork(page) {
  return withMap(page, 'L1', async (inv) => {
    const text = inv.map(x => `${x.text} ${x.title}`).join(' | ')
    for (const label of ['实现', '设计集成测试', '仲裁', '验收走查', '做方案', '合并']) {
      if (!text.includes(label)) return `泳道图缺拓扑标签「${label}」（标签须全部来自拓扑）：${text.slice(0, 260)}`
    }
    // 并行双道虚线框 ×2（.wb-lm-parallel[data-group]，各自含双分支成员）
    const groupish = inv.filter(x => /wb-lm-parallel|group/i.test(x.cls) || x.dataGroup)
    const g1 = groupish.filter(x => x.text.includes('实现') && x.text.includes('设计集成测试'))
    const g2 = groupish.filter(x => x.text.includes('仲裁') && x.text.includes('验收走查'))
    if (!g1.length || !g2.length) {
      return `并行双道虚线框缺席（组语义元素：${JSON.stringify(groupish).slice(0, 220)}）`
    }
    // 人门虚线圈（merge kind=human：data-kind 契约＋👤 视觉词同族）
    const humanish = inv.filter(x => x.dataKind === 'human')
    if (!humanish.length) return `人门虚线圈缺席（merge 无 data-kind=human 标记）`
    if (!humanish.some(x => `${x.text} ${x.title}`.includes('合并'))) {
      return `人门标记未落在合并节点：${JSON.stringify(humanish).slice(0, 200)}`
    }
    // 单向流守卫（组件头注点名的对抗断言）：返工弧类恒零
    const arcs = await page.evaluate(domArcCount)
    if (arcs !== 0) return `泳道图渲染了返工弧（wb-lm-arc ×${arcs}，图面须单向流）`
    return null
  })
}

async function cardOf(page) {
  return page.evaluate(`(() => {
    const c = document.querySelector('.wb-status-card');
    if (!c) return null;
    return { text: c.textContent, cls: c.className, sev: c.getAttribute('data-sev'),
      head: (c.querySelector('.sc-head') || {}).textContent || '',
      fallback: !!c.querySelector('.sc-fallback'),
      files: [...c.querySelectorAll('.sc-file')].map(x => x.textContent),
      signwhat: !!c.querySelector('.sc-signwhat') };
  })()`)
}

async function scenarioRedCardTranslate(page) {
  const card = await cardOf(page)
  if (!card) return `红卡未渲染（.wb-status-card 缺席）@ ${await snap(page)}`
  // 主文案（.sc-head）必须是人话词条，不冒裸引擎码（callout C：翻译层走词条表）
  if (!card.head || !card.head.trim()) return '红卡主文案（.sc-head）为空'
  if (card.head.includes('verify_red')) {
    return `主文案冒出裸引擎码 verify_red（翻译层未走词条表）：${card.head.slice(0, 160)}`
  }
  if (card.fallback) return '词条表命中面失效（出现「词条表缺此原因码」降级锚——verify_red 应有词条）'
  // 原始日志折叠可展开（evidence 原文在 details.sc-raw 里；折叠内出现原文=合法）
  const det = page.locator('.wb-status-card details.sc-raw').first()
  if (!(await det.count())) return '红卡缺原始日志 <details> 折叠'
  await det.locator('summary').first().click({ timeout: 3000 }).catch(() => {})
  if (!(await waitFor(async () => (await det.textContent().catch(() => '')).includes('zz_t26091505_probe.py'), 8000))) {
    // 页内探针：回取抽屉同一 detail 端点，分层定位 evidence 丢在桩/渲染哪层
    const probe = await page.evaluate(`(async () => {
      const r = await fetch('/sandbar-workbench/api/wf/tickets/${FID}');
      const j = await r.json();
      const d = j.result || j;
      const bd = d && d.blocked_detail;
      const pre = document.querySelector('.wb-status-card details.sc-raw pre');
      return { bdKeys: bd ? Object.keys(bd) : null,
        ev: bd ? bd.evidence : '(no bd)',
        preHead: pre ? pre.textContent.slice(0, 90) : '(no pre)' };
    })()`)
    return `折叠展开后不见 evidence 原文——页内探针：bdKeys=${JSON.stringify(probe.bdKeys)} ` +
      `evidence=${JSON.stringify(String(probe.ev).slice(0, 60))} 折叠首行=${JSON.stringify(probe.preHead)}`
  }
  return null
}

async function scenarioRedCardDirtyFiles(page) {
  const card = await cardOf(page)
  if (!card) return '红卡未渲染'
  // 结构化 files 点名到卡面 chips（.sc-file 只吃 blocked_detail.files——结构化面）
  if (!card.files.some(f => (f || '').includes('docs/契约v1.md'))) {
    return `结构化 files 未点名到卡面 chips（files=['docs/契约v1.md']，实得=${JSON.stringify(card.files)}）`
  }
  if ((card.head || '').includes('main_dirty')) {
    return `主文案冒出裸引擎码 main_dirty：${card.head.slice(0, 160)}`
  }
  if (card.fallback) return '词条表命中面失效（main_dirty 应有词条）'
  return null
}

async function scenarioBlueCard(page) {
  const card = await cardOf(page)
  if (!card) return '状态卡未渲染（awaiting-human 子用例）'
  if (!/blue|awaiting/i.test(card.cls) && !/Waiting on your approval|人门/.test(card.text)) {
    return `蓝卡语义缺席（cls=${card.cls.slice(0, 80)}）`
  }
  if (!card.text.includes('签')) return `蓝卡未列「签什么」：${card.text.slice(0, 160)}`
  if (!card.text.includes('签字要点')) return `蓝卡缺 human_context.merge.context_text 内容（签什么数据源）`
  if (!card.text.includes('泳道分支有 commit')) return `蓝卡缺 stage_acceptance 内容（签前看什么数据源）`
  return null
}

async function scenarioRounds(page) {
  return withMap(page, 'L4', async (inv) => {
    const text = inv.map(x => `${x.text} ${x.title}`).join(' | ')
    // ×N 徽章（返工史归徽章；badge=title「该段共 N 轮」）
    const badges = inv.filter(x => x.cls.includes('wb-lm-badge'))
    if (!badges.length && !/×\s*\d/.test(text)) return `×N 徽章缺席（create_plan 返工 2 次的票）`
    // 逐轮格（wb-lm-round[data-gen]）hover title 出该轮证据/打回原因
    const rounds = inv.filter(x => x.cls.includes('wb-lm-round') && x.dataGen)
    if (rounds.length < 3) return `逐轮格不足 3 格（create_plan 三轮，实得 ${rounds.length}）：${JSON.stringify(rounds).slice(0, 200)}`
    if (!rounds.some(x => `${x.title}`.includes('越界'))) {
      return `逐轮格 hover title 缺第 1 轮打回原因「越界」：${JSON.stringify(rounds).slice(0, 260)}`
    }
    // 单向流：节点不因返工重复（create_plan 语义位恰 1）＋返工弧恒零
    const cp = inv.filter(x => x.dataId === 'create_plan')
    if (cp.length !== 1) return `create_plan 节点重复渲染（${cp.length} 个，应恰 1）`
    const arcs = await page.evaluate(domArcCount)
    if (arcs !== 0) return `泳道图渲染了返工弧（wb-lm-arc ×${arcs}）`
    return null
  })
}

async function scenarioClosedVisible(page) {
  return withMap(page, 'L5', async (inv) => {
    const text = inv.map(x => `${x.text} ${x.title}`).join(' | ')
    for (const label of ['做方案', '合并检查', '合并']) {
      if (!text.includes(label)) return `关单票泳道图缺节点「${label}」（KI-027：关单后全图可见）`
    }
    if (!/×\s*\d/.test(text) && !inv.some(x => x.cls.includes('wb-lm-badge'))) {
      return '关单票轮次带/返工徽章缺席（KI-027：轮次带关单可见）'
    }
    // 关单=无可视运行态（全图终态）
    const running = inv.filter(x => x.dataVis === 'running')
    if (running.length) return `关单票仍有 running 态节点（${running.length} 个）`
    return null
  })
}

async function scenarioGenerality(page) {
  return withMap(page, 'L6', async (inv) => {
    const text = inv.map(x => `${x.text} ${x.title}`).join(' | ')
    for (const label of ['夹具段一', '夹具段二']) {
      if (!text.includes(label)) return `另一模板拓扑未按拓扑标签渲染（缺「${label}」）`
    }
    for (const biz of ['做方案', '审方案', '合并检查']) {
      if (text.includes(biz)) return `渲染器泄漏 dev-lane 业务词「${biz}」（零业务词契约）`
    }
    return null
  })
}

async function scenarioFallback(page) {
  const mapN = await page.evaluate(domMapRoot).catch(() => -1)
  const stepN = await page.evaluate(domStepCount).catch(() => -1)
  if (mapN !== 0) return `拓扑缺席时泳道图仍渲染（应回落现行步骤条）：.wb-lanemap=${mapN}`
  if (stepN <= 0) return `回落步骤条未渲染（零回归锚破面）：steps=${stepN}`
  return null
}

async function scenarioChecksArea(page) {
  const area = await page.evaluate(`(() => {
    const a = document.querySelector('.wb-checks');
    return a ? { text: a.textContent, runs: a.querySelectorAll('.wb-ck-run').length,
      marksR: a.querySelectorAll('.wb-ck-mark.r').length, marksG: a.querySelectorAll('.wb-ck-mark.g').length,
      rows: a.querySelectorAll('details.wb-ck-row').length } : null;
  })()`)
  if (!area) return `检查明细区未渲染（.wb-checks 缺席；gate_runs 两轮夹具）@ ${await snap(page)}`
  if (area.runs < 2) return `检查明细区轮记录不足（应 2 轮，实得 ${area.runs}）`
  if (!area.marksR || !area.marksG) return `✓/✗ 记号不齐（✗=${area.marksR} ✓=${area.marksG}，红绿轮各一）`
  const txt = await page.evaluate(domDrawerText)
  // 逐轮逐条 item 名（第 1 轮红项＋第 2 轮绿项）
  if (!txt.includes('泳道内 verify_lane code 绿灯')) return `检查明细区缺 item 名（verify_lane 项）`
  if (!txt.includes('泳道分支有 commit')) return `检查明细区缺绿轮 item 名`
  // 红行点名文件与状态卡联动：同一文件名在检查明细区与卡面同时可见
  if (!txt.includes('server/zz_t26091505_probe.py')) {
    return `检查明细区/卡面未点名越界文件（红行与状态卡文件清单联动）`
  }
  // gate_runs <details> 折叠可展开：点【红行】（data-green=false）展开见该轮 detail 原文
  const det = page.locator('.wb-checks details.wb-ck-row[data-green="false"]').first()
  if (!(await det.count())) return '检查明细红行非 <details> 折叠（原始输出不可查）'
  await det.locator('summary').first().click({ timeout: 3000 }).catch(() => {})
  if (!(await waitFor(async () => (await det.textContent().catch(() => '')).includes('exit=1'), 4000))) {
    return `红行折叠展开后不见该轮 detail 原文（${(await det.textContent().catch(() => '')).slice(0, 120)}）`
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
    // glob 必须 ** 结尾（playwright 单 * 不跨 /，见 sc_lane_parallel_dom.mjs 实证注释）。
    currentDetail = DETAIL_FORK
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

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
    const leg = async (name, detail, workflows, fn) => {
      try {
        await applyLeg(page, boardIcon, detail, workflows)
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
    }

    await leg('L1 泳道图并行双道+人门圈', DETAIL_FORK, [WF_DEVLANE], scenarioLaneMapFork)
    await leg('L2a 红灯翻译（verify_red 族，不裸码）', DETAIL_RED_VERIFY, [WF_DEVLANE], scenarioRedCardTranslate)
    await leg('L2b 红灯翻译（main_dirty 族，结构化文件点名）', DETAIL_RED_DIRTY, [WF_DEVLANE], scenarioRedCardDirtyFiles)
    await leg('L3 人门蓝卡「签什么」', DETAIL_HUMAN, [WF_DEVLANE], scenarioBlueCard)
    await leg('L4 轮次带逐轮格+×N 徽章', DETAIL_ROUNDS, [WF_DEVLANE], scenarioRounds)
    await leg('L5 关单全图可见（KI-027）', DETAIL_CLOSED, [WF_DEVLANE], scenarioClosedVisible)
    await leg('L6 渲染器通用性（另一模板拓扑）', DETAIL_FX, [WF_FX], scenarioGenerality)
    await leg('L7a 拓扑缺席回落步骤条（零回归锚）', DETAIL_NO_TOPO, [WF_NO_TOPO], scenarioFallback)
    await leg('L7b 畸形拓扑/轮次数据不炸', DETAIL_MALFORMED, [WF_DEVLANE], async () => {
      const mapN = await page.evaluate(domMapInventory).then(x => x.length).catch(() => -1)
      if (mapN < 0) return '页面在畸形数据下不可评估（疑似崩溃）'
      return null // 不炸＋零 pageerror 由 P 卫生子用例统一判
    })
    await leg('L8 检查明细区（gate_runs 逐轮逐条+联动）', DETAIL_CHECKS, [WF_DEVLANE], scenarioChecksArea)

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

  const s0ok = buildContract()
  if (s0ok) await modelSmoke()

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

// 中途异常按三态 triage（导航/连接类=env_fail，其余=fail，绝不静默——同范本口径）。
main().catch(e => {
  const s = String(e?.message ?? e);
  const nav = /Timeout\s*\d+ms\s+exceeded|networkidle|ERR_CONNECTION|ECONNREFUSED|socket hang up|Target closed|net::/i.test(s);
  record('mid-run-abort', nav ? 'env_fail' : 'fail', s.slice(0, 200));
  summarize();
})
