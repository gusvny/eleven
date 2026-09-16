#!/usr/bin/env node
// t260916-15 UI 截图证据通道（交付契约：UI 票交付含 .sandbar/screenshots/ 实拍）。
// 取台=lib_fix17 bootConsole（同 t260915-19/capture_sidebar_ui.mjs，非 docker 形态；
// freePort 拒 3099=红线零接触，teardownOnExit 全终态回收）。数据只桩 API 边界
// （page.route，夹具=本票场景同款序敏感数据集）。截图两张：
//   t260916-15-sidebar-merged.png   全页：甲组 dev+巡检混排（等你→在跑→已完成）
//                                   +「巡检」兜底组（含排序）+ 行1 徽标
//   t260916-15-sidebar-leftcol.png  左栏聚焦裁剪（.wb-sb-left element shot）
// 改动前后对照：本助手对**改动前后 bundle 各跑一遍**（旧 bundle=改动前工作区
// 原生构建产物，改动落盘重建后再跑一遍），产物由交付层复制为 *-before.png /
// *-after.png。序敏感夹具（巡检等你行 ts 最新+收口 dev 行 ts 最新）保证前后帧
// 行序肉眼可辨：改前=拼接序（巡检恒尾、收口行夹中）；改后=合并排序（等你区在
// 顶、收口行沉底、巡检行带徽标混排）。
import { writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub } from '../t260904-17/lib_fix17.mjs'

const REPO = process.cwd()
const OUT = join(REPO, '.sandbar', 'screenshots')
mkdirSync(OUT, { recursive: true })

const PROJ_A = 'fixture-alpha'
const PROJ_B = 'fixture-beta'
const DEV_A_RUN = 'devfixa1501run'    // 甲组 dev 在跑（ts 最老）
const DEV_A_WAIT = 'devfixa1502wait'  // 甲组 dev 等你（ts 中）
const DEV_A_DONE = 'devfixa1503done'  // 甲组 dev 已收口（updated_ts 全场最新——收口层仍须沉底）
const INS_A = 'inspfixa1504a'         // 甲组巡检·等你（ts=等你层最新 → 排序后组首=反沉底主角）
const INS_ARUN = 'inspfixa1505r'      // 甲组巡检·在跑（ts 更老 → 在跑层内排 dev 之后）
const INS_B = 'inspfixb1506b'         // 乙组巡检·在跑（乙组零 dev 票空态语义）
const INS_UN_WAIT = 'inspfixun07w'    // 兜底组·等你（输入序在后 → 排序后应升至兜底组首）
const INS_UN_RUN = 'inspfixun08r'     // 兜底组·在跑

const T0 = 1789354800
const WORKFLOWS = [{ id: 'dev-lane', name: '开发泳道', lane: 'worktree', stages: [
  { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
  { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
]}]
function devRow(id, stageState, title, over = {}) {
  return { id, role: 'developer', status: 'dispatched', title, workflow: 'dev-lane', stage: 'implement',
    stage_state: stageState, handoff_count: 0, pending_count: 0, worktree: '', updated: '—',
    updated_ts: T0, created: T0, engine: 'template-as-code-v2', exec_status: 'RUNNING', ...over }
}
function insRow(over) {
  return { id: '', kind: 'inspection', engine: 'inspection', project: '', epic: '', title: '',
    template: 'inspection-lite', instance_id: '', period: '20260916', stage: 'scan',
    stage_state: 'running', status: 'running', decision: '', findings: { high: 0, med: 0, low: 0, total: 0 },
    heartbeat: true, report_path: '', awaiting_gate: false, human_gate: null, blocked_reason: '',
    gate_error: '', created: T0, updated: '09-16 07:30', updated_ts: T0, paused: false,
    paused_phase: '', handoff_count: 0, pending_count: 0, worktree: '', workspace: null, role: null,
    proposal_id: '', workflow: '', close_ts: 0, authz: 0, authz_active: 0, exec_status: 'RUNNING', ...over }
}

// 收口行要在左栏驻留窗（默认 24h）内：close_ts=现挂钟前 1 小时。
const CLOSE_TS = Math.floor(Date.now() / 1000) - 3600

const DEV_ROWS = [
  devRow(DEV_A_RUN, 'running', '甲组进行中 dev 票', { updated_ts: T0 }),
  devRow(DEV_A_WAIT, 'awaiting-human', '甲组等你 dev 票', { updated_ts: T0 + 7200 }),
  devRow(DEV_A_DONE, 'awaiting', '甲组已收口 dev 票', {
    status: 'closed', close_ts: CLOSE_TS, updated_ts: T0 + 999_999, exec_status: 'COMPLETED' }),
]

const INS_ROWS = [
  insRow({ id: INS_A, project: PROJ_A, instance_id: 'fixture-alpha', title: '巡检 fixture-alpha · 期 20260916',
    stage: 'close', stage_state: 'awaiting-human', awaiting_gate: true, updated_ts: T0 + 14400,
    findings: { high: 1, med: 2, low: 0, total: 3 }, report_path: `out/inspection/${INS_A}.json` }),
  insRow({ id: INS_ARUN, project: PROJ_A, instance_id: 'fixture-alpha', title: '巡检 fixture-alpha · 期 20260915',
    stage: 'scan', stage_state: 'running', updated_ts: T0 - 3600,
    findings: { high: 0, med: 1, low: 1, total: 2 }, report_path: `out/inspection/${INS_ARUN}.json` }),
  insRow({ id: INS_B, project: PROJ_B, instance_id: 'fixture-beta', title: '巡检 fixture-beta · 期 20260916',
    stage: 'suite', stage_state: 'running', findings: { high: 0, med: 0, low: 1, total: 1 },
    report_path: `out/inspection/${INS_B}.json` }),
  // 兜底组两条：输入序「在跑在前、等你在后」，排序后等你行应升至兜底组首。
  insRow({ id: INS_UN_RUN, project: '', instance_id: 'legacy', title: '巡检 legacy · 期 20260901',
    stage: 'report', stage_state: 'running', updated_ts: T0 + 100,
    findings: { high: 0, med: 1, low: 0, total: 1 }, report_path: `out/inspection/${INS_UN_RUN}.json` }),
  insRow({ id: INS_UN_WAIT, project: '', instance_id: 'legacy2', title: '巡检 legacy2 · 期 20260902',
    stage: 'close', stage_state: 'awaiting-human', awaiting_gate: true, updated_ts: T0 + 50,
    findings: { high: 2, med: 0, low: 0, total: 2 }, report_path: `out/inspection/${INS_UN_WAIT}.json` }),
]

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    try { return await import(pathToFileURL(join(main, sub)).href) } catch { /* next */ }
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
    try { if (await cond()) return true } catch { /* poll */ }
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

let bench = null
try {
  const projectsRoot = makeRegistryRoot('t260916-15-shot-registry-')
  writeProjectEntry(projectsRoot, PROJ_A, '夹具甲', ['/tmp/fx-alpha'])
  writeProjectEntry(projectsRoot, PROJ_B, '夹具乙', ['/tmp/fx-beta'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] console 不可得：${String(e).slice(0, 160)}`)
  process.exit(2)
}
const pw = await loadPlaywright()
if (!pw) { console.log('[ENV_FAIL] playwright-core 不可解析'); process.exit(2) }
const browser = await launchBrowser(pw)
if (!browser) { console.log('[ENV_FAIL] chromium/chrome 无法启动'); process.exit(2) }

const ctx = await browser.newContext()
try {
  const page = await ctx.newPage()
  await page.route('**/sandbar-workbench/api/wf/**', (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/+$/, '')
    if (path === '/sandbar-workbench/api/wf/projects') {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: {
        projects: [
          { key: PROJ_A, name: '夹具甲', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
          { key: PROJ_B, name: '夹具乙', primary: '/tmp/fx-beta', dirs: ['/tmp/fx-beta'] },
        ], quarantined: [] } }) })
    }
    if (path === '/sandbar-workbench/api/wf/tickets' && !path.startsWith('/sandbar-workbench/api/wf/tickets/')) {
      const proj = new URL(route.request().url()).searchParams.get('project') || ''
      const tickets = proj === PROJ_A ? DEV_ROWS : []
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets, workflows: WORKFLOWS } }) })
    }
    if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: INS_ROWS, count: INS_ROWS.length } }) })
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'shot stub: unknown' }) })
  })

  await page.goto(`${bench.base}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(3000)
  await dismissOverlays(page)
  const probe = page.locator(`.wb-sb .wb-card[data-ticket-id="${INS_A}"]`).first()
  if (!(await waitFor(async () => (await probe.count()) > 0, 15000))) {
    console.log('[FAIL] 巡检行未落组，无图可交')
    process.exit(1)
  }
  // 等一拍渲染稳定（相对时间/黄调/徽标全落），再拍。
  await page.waitForTimeout(800)
  await page.screenshot({ path: join(OUT, 't260916-15-sidebar-merged.png'), fullPage: false, timeout: 20000 })
  const left = page.locator('.wb-sb-left').first()
  if (await left.count()) await left.screenshot({ path: join(OUT, 't260916-15-sidebar-leftcol.png'), timeout: 20000 }).catch(() => {})
  console.log('[PASS] 两张截图落盘 ' + OUT)
} finally {
  await ctx.close().catch(() => {})
  await browser.close().catch(() => {})
}
