/**
 * smoke/scan-report.mjs —— sandbar-workbench M6「巡检报告」区的宿主半冒烟。
 *
 * 直跑：node smoke/scan-report.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. readLatestScanReport（src/host/scan-report.ts，临时目录）：
 *      目录不存在→reason；空目录→暂无报告；多日期取文件名序最新；非报告文件不入
 *      候选（白名单 YYYY-MM-DD.json）；最新文件坏 JSON→解析失败 reason。
 *   B. /sandbar-workbench/api/wf/scan-report 路由（node.ts apply + mock webServer/req/res）：
 *      有报告→200+report 逐字段；无报告→200+reason 降级（不抛错）。
 */

import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readLatestScanReport } from '../src/host/scan-report.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const SAMPLE = {
  generated_at: '2026-08-22T01:00:00+0800',
  total_tickets: 50,
  by_status: { closed: 46, settled: 1, rework: 1, dispatched: 2 },
  pending_decision_count: 1,
  stuck_threshold_hours: 48,
  red_line: '巡检只出建议不出决定；签字只能人（sign who=用户/总管）。',
  summary: { 疑似卡死: 0, 待补: 0, 可签: 1 },
  items: [{
    ticket_id: 't-smoke-scan', title: '样例工单', status: 'rework', stage: 'final-review',
    stage_state: 'awaiting-human', dwell_hours: 3.5, acceptance_done: 0, acceptance_total: 1,
    pending_count: 2, gate_label: 'qc_run all', gate_green: true,
    suggestion: '可签', reasons: ['人门 final-review 挂起待人签字'],
  }],
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-scan-'))
try {
  /* ------------------------------------------------------------ A. readLatestScanReport */
  section('A readLatestScanReport')
  const scanDir = join(tmp, 'out', 'scan')

  let r = await readLatestScanReport(scanDir)
  ok(r.report === null && r.file === null && r.reason.includes('不存在'), '目录不存在 → reason 降级')

  await mkdir(scanDir, { recursive: true })
  r = await readLatestScanReport(scanDir)
  ok(r.report === null && r.reason.includes('暂无'), '空目录 → 暂无巡检报告')

  await writeFile(join(scanDir, '2026-08-20.json'), JSON.stringify({ generated_at: 'old', items: [] }), 'utf8')
  await writeFile(join(scanDir, '2026-08-22.json'), JSON.stringify(SAMPLE), 'utf8')
  await writeFile(join(scanDir, 'notes.txt'), '不是报告', 'utf8')
  await writeFile(join(scanDir, '2026-08-99.json'), JSON.stringify({ generated_at: 'bad-date' }), 'utf8') // 格式合法但日期假——仍按文件名取
  r = await readLatestScanReport(scanDir)
  ok(r.file === '2026-08-99.json', '取文件名序最新（白名单只卡格式不卡日历真伪）')
  r = await (async () => { // 去掉假日期文件后再取
    const { unlink } = await import('node:fs/promises')
    await unlink(join(scanDir, '2026-08-99.json'))
    return readLatestScanReport(scanDir)
  })()
  ok(r.file === '2026-08-22.json' && r.report.total_tickets === 50, 'notes.txt 等非报告文件不入候选')
  ok(r.report.items[0].suggestion === '可签' && r.report.red_line.includes('只出建议'),
    '报告逐字段解析（建议/红线）')

  await writeFile(join(scanDir, '2026-08-23.json'), '{bad json', 'utf8')
  r = await readLatestScanReport(scanDir)
  ok(r.file === '2026-08-23.json' && r.report === null && r.reason.includes('解析失败'),
    '最新文件坏 JSON → 解析失败 reason（不抛错）')

  /* ------------------------------------------------------------ B. 路由 */
  section('B /sandbar-workbench/api/wf/scan-report 路由（mock webServer）')
  {
    // 清掉坏文件，留 2026-08-22 作为最新
    const { unlink } = await import('node:fs/promises')
    await unlink(join(scanDir, '2026-08-23.json'))
    // 构造 node.ts 期望的 repo 布局：<repo>/server/engine/out/scan
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server', 'engine', 'out'), { recursive: true })
    // 用符号链接把临时 scan 目录挂进 repo 布局（免复制）
    const { symlink } = await import('node:fs/promises')
    await symlink(scanDir, join(repo, 'server', 'engine', 'out', 'scan'))

    const routes = []
    const ws = { register: (x) => { routes.push(x); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const route = routes.find(x => x.kind === 'exact' && x.path === '/sandbar-workbench/api/wf/scan-report')
    ok(route !== undefined, 'scan-report exact 路由已挂')

    const res = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    await route.handler({ url: '/sandbar-workbench/api/wf/scan-report', method: 'GET' }, res)
    ok(res.status === 200 && res.body.ok === true, 'GET 200')
    ok(res.body.result.file === '2026-08-22.json', '命中最新报告文件')
    ok(res.body.result.report.items[0].ticket_id === 't-smoke-scan', '报告内容透传')

    // 无报告场景：另一个 repo 布局（目录不存在）→ 200 + reason 降级
    const res2 = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    const routes2 = []
    const ws2 = { register: (x) => { routes2.push(x); return () => {} } }
    const ctx2 = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws2 : undefined),
      on: () => () => {},
    }
    apply(ctx2, { repo: join(tmp, 'repo-empty') })
    const route2 = routes2.find(x => x.kind === 'exact' && x.path === '/sandbar-workbench/api/wf/scan-report')
    await route2.handler({ url: '/sandbar-workbench/api/wf/scan-report', method: 'GET' }, res2)
    ok(res2.status === 200 && res2.body.ok === true && res2.body.result.report === null
      && res2.body.result.reason !== '', '无报告 → 200 + reason 降级（不抛错）')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
