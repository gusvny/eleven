// lib_fix23.mjs —— t261008-23 四场景共享夹具（bootConsole + API 打桩 + 绑浅 DOM 探针）。
// 镜 t261008-08 的 bootConsole + page-boundary stub 模式；零 docker、红线零接触 3099。
// 输入三态纪律：夹具时间线/交接数据由本库构造，畸形形态由各场景显式置 malform 开关。
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs'

export const PROJ = 'fixture-comp'
export const TID = 't26100823-fix'
export const T0 = 1789353600000 // ms

// 时间线夹具：八段 dev-lane 全旅程，段间距（=段耗时真源）刻意不等比：
// create_plan 60s、review_plan 240s、implement 600s、design_integration_tests 120s
// （与 implement 同窗并行）、ui_evidence 30s、run_integration_tests 900s、
// arbitrate 480s、acceptance_walkthrough 90s（与 arbitrate 同窗并行）、merge_check 60s、merge 人等。
export function fixtureTimeline({ start = T0, longReason = true } = {}) {
  const LONG = 'handoff from implement: implemented the lane map v5 renderer with duration-proportional segment widths, folded the Changeset panel into Changes, moved the agent-log resolver onto the .sandbar directory with a .suyou compat fallback, and left the timeline rows in place because the host chose option b (collapse the reason, keep every entry) — this sentence is deliberately long so the collapse face has a real wall of prose to shorten'  // naming-compat
  // lane-durations contract (t260901-12): `at` is an ISO string (non-ISO is
  // skipped -> nominal weight) and windows OPEN on `state:'running'` marks
  // (the engine has no done mark). Durations then vary via the settle chain
  // (next stage's running mark closes the previous window; the trailing
  // merge:closed mark closes the tail). Fixture gap: numeric at + state 'done'
  // produced all-nominal weights and the widths collapsed to equal.
  const iso = (ms) => new Date(ms).toISOString()
  const rows = [
    { at: iso(start), stage: 'create_plan', state: 'running', reason: 'plan written' },
    { at: iso(start + 60e3), stage: 'review_plan', state: 'running', reason: 'review passed with conditions' },
    { at: iso(start + 300e3), stage: 'implement', state: 'running', reason: longReason ? LONG : 'implemented' },
    { at: iso(start + 360e3), stage: 'design_integration_tests', state: 'running', reason: longReason ? LONG : 'tests designed' },
    { at: iso(start + 900e3), stage: 'ui_evidence', state: 'running', reason: 'captures attached' },
    { at: iso(start + 930e3), stage: 'run_integration_tests', state: 'running', reason: 'suite green' },
    { at: iso(start + 1830e3), stage: 'arbitrate', state: 'running', reason: longReason ? LONG : 'arbitrated' },
    { at: iso(start + 2100e3), stage: 'acceptance_walkthrough', state: 'running', reason: longReason ? LONG : 'walked through' },
    { at: iso(start + 2310e3), stage: 'merge_check', state: 'running', reason: 'checks green' },
    { at: iso(start + 2370e3), stage: 'merge', state: 'running', reason: 'merged' },
    { at: iso(start + 2430e3), stage: 'merge', state: 'closed', reason: '' },
  ]
  return rows
}

export function fixtureTicketDetail(timeline) {
  return {
    id: TID,
    title: 'fixture ticket for detail-face scenarios',
    project: PROJ,
    status: 'RUNNING',
    // the detail face matches its workflow template by workflow_id (selWf in
    // index.tsx); `workflow` alone never matches (fixture gap, live probe:
    // drawer showed "no template" and the linear stepper instead of the map).
    workflow: 'dev-lane',
    workflow_id: 'dev-lane',
    stage: 'merge',
    stage_state: 'running',
    worktree: '',
    base_ref: 'abc123def456',
    write_set: ['server/plugins/workbench/src/client/lane-map.tsx'],
    meta: {
      parallel_stages: [
        ['implement', 'design_integration_tests'],
        ['arbitrate', 'acceptance_walkthrough'],
      ],
    },
    timeline,
  }
}

// 打桩路由：详情面消费的全部 API 面；未知路由诚实 ok:false（不静默假数据）。
export function routeDetail(page, detail, extra = {}) {
  return page.route('**/sandbar-workbench/api/wf/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const j = (body) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (method === 'GET' && path === '/sandbar-workbench/api/wf/projects') {
      return j({ ok: true, result: { projects: [{ key: PROJ, name: PROJ, primary: '/tmp/fx-comp', dirs: ['/tmp/fx-comp'] }], quarantined: [] } })
    }
    if (method === 'GET' && path === '/sandbar-workbench/api/wf/tickets') {
      // contract (node.ts list handler): workflows ride the ENVELOPE top level,
      // next to ok/result — not inside result (fixture gap, live probe).
      return j({ ok: true, result: { tickets: [detail] }, workflows: [fixtureWorkflow()] })
    }
    if (method === 'GET' && path === `/sandbar-workbench/api/wf/tickets/${TID}`) {
      return j({ ok: true, result: detail })
    }
    if (method === 'GET' && path === '/sandbar-workbench/api/wf/inspection/tickets') {
      return j({ ok: true, result: { tickets: [], count: 0 } })
    }
    if (extra.route && extra.route(path, method, j, route) === true) return
    // extra.passThrough: let named routes reach the real server (used when the
    // assertion must read the real host's answer, e.g. the changes empty state).
    if (extra.passThrough && extra.passThrough(path, method) === true) return route.fallback()
    return j({ ok: false, error: 'fixture stub: unknown route' })
  })
}

function fixtureWorkflow() {
  // topology is required for the v5 lane map to render at all — without it the
  // detail face falls back to the linear stepper (buildLaneMap returns null on
  // missing topology, fixture gap root-caused via live DOM probe).
  const topology = {
    template: 'dev-lane', name: 'dev lane',
    nodes: [
      { id: 'create_plan', label: 'create_plan', role: 'developer', kind: 'agent' },
      { id: 'review_plan', label: 'review_plan', role: 'developer', kind: 'agent' },
      { id: 'implement', label: 'implement', role: 'developer', kind: 'agent' },
      { id: 'design_integration_tests', label: 'design_integration_tests', role: 'developer', kind: 'agent' },
      { id: 'ui_evidence', label: 'ui_evidence', role: 'developer', kind: 'agent' },
      { id: 'run_integration_tests', label: 'run_integration_tests', role: 'developer', kind: 'agent' },
      { id: 'arbitrate', label: 'arbitrate', role: 'developer', kind: 'agent' },
      { id: 'acceptance_walkthrough', label: 'acceptance_walkthrough', role: 'developer', kind: 'agent' },
      { id: 'merge_check', label: 'merge_check', role: 'developer', kind: 'agent' },
      { id: 'merge', label: 'merge', role: 'human', kind: 'human' },
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
  return {
    id: 'dev-lane', name: 'dev lane', lane: 'worktree',
    stages: ['create_plan', 'review_plan', 'implement', 'design_integration_tests', 'ui_evidence',
      'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check', 'merge']
      .map((id) => ({ id, name: id, role: 'developer', parts: ['agent'] })),
    topology,
  }
}

// —— 通用浏览器脚手架 ——
export function mainRepoRoot(repo) {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: repo, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(repo, common, '..')
  } catch { /* not a worktree */ }
  return repo
}

export async function loadPlaywright(repo) {
  const candidates = ['playwright-core']
  const main = mainRepoRoot(repo)
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

export async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

export async function bootFixture(repo, label) {
  const projectsRoot = makeRegistryRoot(label + '-registry-')
  writeProjectEntry(projectsRoot, PROJ, PROJ, ['/tmp/fx-comp'])
  const stub = makeTicketStub()
  return { bench: await bootConsole(projectsRoot, stub), stub, teardownOnExit }
}

// 结果三态记录器（t260904-12：fail>0 或全 na=exit 1；env_fail>0=exit 2）。
export function recorder() {
  const results = []
  const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
  function record(name, status, detail = '') {
    if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
    results.push({ name, status, detail })
    console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
  }
  function rec(name, cond, detail = '') { record(name, cond ? 'pass' : 'fail', detail) }
  function summarize() {
    const p = results.filter(r => r.status === 'pass').length
    const e = results.filter(r => r.status === 'env_fail').length
    const n = results.filter(r => r.status === 'na').length
    const f = results.filter(r => r.status === 'fail').length
    const allNa = results.length > 0 && n === results.length
    console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
    process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
  }
  return { results, record, rec, summarize }
}

// The console home shows a one-time "Choose workspace / Continue" intro modal
// whose mask intercepts every pointer event — if it is not dismissed, the
// ticket-row click never lands and the detail drawer never opens (root-caused
// via live DOM probe: <div aria-hidden> _mask_… subtree intercepts pointer
// events). Dismiss it before interacting with the list face.
export async function dismissIntroModal(page) {
  try {
    const btn = page.getByRole('button', { name: 'Continue' }).first()
    if (await btn.isVisible({ timeout: 2000 })) { await btn.click({ timeout: 3000 }); await page.waitForTimeout(500) }
  } catch { /* intro modal absent — nothing to dismiss */ }
}

export async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}
