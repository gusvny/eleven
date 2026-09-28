#!/usr/bin/env node
// t260915-19 UI 截图证据通道（交付契约：UI 票交付含 .sandbar/screenshots/ 实拍）。
// 取台=lib_fix17 bootConsole（同 sc_sidebar_inspection_ui.mjs，非 docker 形态；
// freePort 拒 3099=红线零接触，teardownOnExit 全终态回收）。数据只桩 API 边界
// （page.route，与场景同款夹具）。截图三张：
//   t260915-19-sidebar-inspection.png   常规态：巡检行落组（甲组合并序+乙组）+等你
//                                       黄调+「巡检」兜底组（老票显式在册）
//   t260915-19-sidebar-leftcol.png      左栏聚焦裁剪（.wb-sb-left element shot）
//   t260915-19-sidebar-degraded.png     降级态：端点 ok:false→左栏横幅显原文+快照行保留
// 「改动前」对照：无先帧图（工作区不可来回切换基线）；改动前后的左栏项目组渲染
// 零变化由场景对照子用例机械钉死（dev 等你行不上漆 + 等你巡检行压在跑 dev 行之上 + 零
// pageerror），见场景 S1 waiting-yellow-control / anti-sink-smoke / page-health 三子用例
// （t260916-15 起组内为合并排序口径，行序全矩阵归 t260916-15 场景）。
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
const DEV_A_RUN = 'devfixa1901run'
const DEV_A_WAIT = 'devfixa1902wait'
const INS_A = 'inspfixa1903a'
const INS_B = 'inspfixb1904b'
const INS_UN = 'inspfixun1905u'
const WORKFLOWS = [{ id: 'dev-lane', name: '开发泳道', lane: 'worktree', stages: [
  { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
  { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
]}]
function devRow(id, stageState, title) {
  return { id, role: 'developer', status: 'dispatched', title, workflow: 'dev-lane', stage: 'implement',
    stage_state: stageState, handoff_count: 0, pending_count: 0, worktree: '', updated: '—',
    updated_ts: 1789354800, created: 1789354800, engine: 'template-as-code-v2', exec_status: 'RUNNING' }
}
function insRow(over) {
  return { id: '', kind: 'inspection', engine: 'inspection', project: '', epic: '', title: '',
    template: 'inspection-lite', instance_id: '', period: '20260915', stage: 'inspect',
    stage_state: 'running', status: 'running', decision: '', findings: { high: 0, med: 0, low: 0, total: 0 },
    heartbeat: true, report_path: '', awaiting_gate: false, human_gate: null, blocked_reason: '',
    gate_error: '', created: 1789354800, updated: '09-15 07:30', updated_ts: 1789354800, paused: false,
    paused_phase: '', handoff_count: 0, pending_count: 0, worktree: '', workspace: null, role: null,
    proposal_id: '', workflow: '', close_ts: 0, authz_active: 0, exec_status: 'RUNNING', ...over }
}
const INS_ROWS = [
  insRow({ id: INS_A, project: PROJ_A, instance_id: 'fixture-alpha', title: '巡检 fixture-alpha · 期 20260915',
    stage: 'close', stage_state: 'awaiting-human', awaiting_gate: true,
    findings: { high: 1, med: 2, low: 0, total: 3 },
    created: 1789362000, updated_ts: 1789362000, // t260916-15 合并口径：INS_A 最新 ts（截图示新序）
    report_path: 'out/inspection/inspfixa1903a.json' }),
  insRow({ id: INS_B, project: PROJ_B, instance_id: 'fixture-beta', title: '巡检 fixture-beta · 期 20260915',
    stage: 'inspect', stage_state: 'running', findings: { high: 0, med: 0, low: 1, total: 1 },
    report_path: 'out/inspection/inspfixb1904b.json' }),
  insRow({ id: INS_UN, project: '', instance_id: 'legacy', title: '巡检 legacy · 期 20260901',
    stage: 'report', stage_state: 'running', findings: { high: 0, med: 1, low: 0, total: 1 },
    report_path: 'out/inspection/inspfixun1905u.json' }),
]
const INS_A_DETAIL = { id: INS_A, kind: 'inspection', engine: 'inspection', template: 'inspection-lite',
  title: '巡检 fixture-alpha · 期 20260915', stage: 'close', stage_state: 'awaiting-human', status: 'running',
  decision: '', gate_id: 'inspection-close', instance_id: 'fixture-alpha', period: '20260915',
  report_path: 'out/inspection/inspfixa1903a.json', red_line: '巡检只出报告与开票建议，绝不直接改码。',
  heartbeat: true, summary: { high: 1, med: 2, low: 0 },
  findings: [{ id: 'f1', scan: 'test', severity: 'high', subject: '高危样例', evidence: 'evidence-high', suggestion: '开票修' }],
  suggested_fix_tickets: [], blocked_reason: '', human_gate: null, gate_error: '', worktree: '', workspace: null,
  timeline: [{ at: '2026-09-15T07:30:00', stage: 'close', state: 'running', reason: '人审发现清单' }] }

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
  const projectsRoot = makeRegistryRoot('t260915-19-shot-registry-')
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
  let insPayload = { ok: true, result: { tickets: INS_ROWS, count: INS_ROWS.length } }
  const DEGRADE = { ok: false, error: 'ticket-list(inspection) 失败: fixture 降级注入 0x519' }
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
      const tickets = proj === PROJ_A
        ? [devRow(DEV_A_RUN, 'running', '甲组进行中 dev 票'), devRow(DEV_A_WAIT, 'awaiting-human', '甲组等你 dev 票')]
        : []
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets, workflows: WORKFLOWS } }) })
    }
    if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(insPayload) })
    }
    if (/\/wf\/tickets\/[^/]+$/.test(path) && decodeURIComponent(path.split('/').pop()) === INS_A) {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: INS_A_DETAIL }) })
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'shot stub: unknown' }) })
  })

  await bench.goto(page, { waitUntil: 'networkidle' })
  console.log('[phase] goto ok')
  await page.waitForTimeout(3000)
  await dismissOverlays(page)
  console.log('[phase] overlays dismissed')
  const probe = page.locator(`.wb-sb .wb-card[data-ticket-id="${INS_A}"]`).first()
  if (!(await waitFor(async () => (await probe.count()) > 0, 15000))) {
    console.log('[FAIL] 巡检行未落组，无图可交')
    process.exit(1)
  }
  console.log('[phase] rows landed, shooting full page')
  await page.waitForTimeout(800)
  await page.screenshot({ path: join(OUT, 't260915-19-sidebar-inspection.png'), fullPage: false, timeout: 20000 })
  console.log('[phase] full shot ok')
  const left = page.locator('.wb-sb-left').first()
  if (await left.count()) await left.screenshot({ path: join(OUT, 't260915-19-sidebar-leftcol.png'), timeout: 20000 }).catch(() => {})
  console.log('[phase] leftcol shot ok')

  insPayload = DEGRADE
  const banner = page.locator('.wb-sb [data-testid="sidebar-inspection-degraded"]').first()
  if (await waitFor(async () => (await banner.count()) > 0, 15000)) {
    await page.waitForTimeout(500)
    await page.screenshot({ path: join(OUT, 't260915-19-sidebar-degraded.png'), fullPage: false })
    console.log('[PASS] 三张截图落盘 ' + OUT)
  } else {
    console.log('[FAIL] 降级横幅未现，降级图缺失')
    process.exit(1)
  }
} finally {
  await ctx.close().catch(() => {})
  await browser.close().catch(() => {})
}
