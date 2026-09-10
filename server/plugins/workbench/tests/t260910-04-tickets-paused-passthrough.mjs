#!/usr/bin/env node
// t260910-04 UT —— /wf/tickets 列表 paused/paused_phase 透传 + 换源/错误契约锁（API 面，假引擎）。
//
// 直跑：node server/plugins/workbench/tests/t260910-04-tickets-paused-passthrough.mjs
// （exit 0 = 过）。零网络/零真仓/真 Temporal/console。
//
// 背景：t260908-01 引擎侧暂停语义落地后，host 列表行仍缺 paused/paused_phase——
// 原通路 callTool('ticket',{op:'list'}) 经 server/tools/ticket.py 投影把两键丢了。
// t260910-04 修复：handleTickets 直走引擎 client.py ticket-list（runPocCli），
// 并把「引擎 ok:false 被吃成 200 空列表」的旧沉默改为显式 502（R3）。
//
// 本 UT 锁 host 层形状与错误契约（假引擎）；「与引擎 snapshot 一致」的真链断言
// 在 integration/t260910-04/sc_console_paused_list.mjs（两层各管一段，UT 不冒充场景）。
//
// 覆盖：
//   A. paused=true/paused_phase=at_gate|pending|'' 原样透传；close_ts 防御性归一；
//      其余键逐键透传不清洗（含引擎超集键 exec_status）。
//   B. 畸形输入：行缺 paused 键→字段缺省不 throw；paused 非布尔原样透传不清洗；
//      tickets 缺失→空列表 200。
//   C. 错误契约（R3 修法后）：引擎回执 ok:false→502 原文 error（client.py main
//      全路径 exit 0，execFile 不 reject，检查必须落在回执结构上）；workflow-list
//      ok:false→502；stdout 非 JSON→502（JSON.parse 抛→catch）。
//   D. 通道锁：列表不再走 admin.py 的 ticket 通道（假 admin 收到 ticket list 调用即红）。
//   E. 回归：project 缺参 400 / 未知 key 400（findProject 白名单仍把门）。
//   F. maxBuffer 处置冒烟：行数组撑过 execFile 默认 1MB → 仍 200 全量（16MB 生效）。

import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply } from './../node.ts'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------- 假仓 harness（project-routes.mjs 形态） ---------------- */

const savedEnv = {
  SANDBAR_PROJECTS_DIR: process.env.SANDBAR_PROJECTS_DIR,
  SANDBAR_PROJECTS_YAML: process.env.SANDBAR_PROJECTS_YAML,
}
delete process.env.SANDBAR_PROJECTS_YAML

/** 造一个假仓：registry（key=alpha）+ 假 admin.py（node 脚本）+ 假引擎 venv python。 */
function makeRepo(tmp, { engineStdout, adminMode } = {}) {
  const repo = join(tmp, 'repo')
  // 注册表（findProject 白名单数据源）：per-key 目录形态 + .migrated 免迁移链
  const reg = join(tmp, 'registry')
  mkdirSync(join(reg, 'alpha'), { recursive: true })
  writeFileSync(join(reg, 'alpha', 'project.yaml'),
    'schema: v1\nproject:\n  - key: alpha\n    name: 甲\n    dirs:\n      - /tmp/alpha\n', 'utf8')
  writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
  process.env.SANDBAR_PROJECTS_DIR = reg

  // 假 admin.py：runAdminCli 以 config.python=process.execPath 直接执行本文件。
  // workflow list 回正常回执；ticket 通道一旦被调（不该再走）即回 ok:false 并打标记。
  mkdirSync(join(repo, 'server'), { recursive: true })
  const adminScript = `
const args = process.argv.slice(2); // ['call', tool, argsJSON]
const tool = args[1] ?? '';
${adminMode ?? ''}
if (tool === 'workflow') {
  console.log(JSON.stringify({ ok: true, result: { workflows: [{ id: 'wf1' }] } }));
  process.exit(0);
}
// ticket 通道（本票后列表不该走；其他 op 也一并不供）：
console.log(JSON.stringify({ ok: false, error: 'FAKE-ADMIN: ticket 通道不应被列表调用' }));
process.exit(1);
`
  writeFileSync(join(repo, 'server', 'admin.py'), adminScript, 'utf8')

  // 假引擎：<repo>/server/engine/.venv/bin/python（runPocCli 硬编码路径），node shebang。
  const engineBin = join(repo, 'server', 'engine', '.venv', 'bin', 'python')
  mkdirSync(dirname(engineBin), { recursive: true })
  const stdout = typeof engineStdout === 'function' ? '__FN__' : (engineStdout ?? '')
  writeFileSync(engineBin, `#!/usr/bin/env node
${typeof engineStdout === 'function' ? `const emit = ${engineStdout.toString()}; emit(process.argv)` : `process.stdout.write(${JSON.stringify(String(stdout))})`}
`, 'utf8')
  chmodSync(engineBin, 0o755)
  return repo
}

function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo, python: process.execPath })
  const find = (p) => routes.find(r => r.path === p)
  return { tickets: find('/sandbar-workbench/api/wf/tickets') }
}

const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b ?? ''; try { this.body = JSON.parse(b) } catch { this.body = null } },
})
const call = async (handler, url, method = 'GET') => {
  const res = mockRes()
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* [] } }
  await handler.handler(req, res)
  return res
}

/** 标准引擎行（键序对齐 client.py _row_from_meta）。 */
function engineRow(over = {}) {
  return {
    id: 't260910-02', project: 'alpha', epic: '', role: 'developer',
    status: 'running', title: '暂停补全', workflow: 'DevLaneWorkflow',
    proposal_id: '', stage: 'implement', stage_state: 'running',
    paused: true, paused_phase: 'at_gate',
    handoff_count: 2, pending_count: 0,
    worktree: '', workspace: null, created: 1000, updated: '09-10 12:00',
    updated_ts: 1725900000, engine: 'v2', exec_status: 'RUNNING', close_ts: 0,
    ...over,
  }
}

try {
  /* ---------------- A 透传面 ---------------- */
  section('A paused/paused_phase 原样透传 + 行形状归一')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const rows = [
      engineRow({ id: 'a1', paused: true, paused_phase: 'at_gate' }),
      engineRow({ id: 'a2', paused: true, paused_phase: 'pending' }),
      engineRow({ id: 'a3', paused: false, paused_phase: '' }),
      engineRow({ id: 'a4', paused: false, paused_phase: '', status: 'closed', stage_state: 'done', exec_status: 'COMPLETED' }),
    ]
    const repo = makeRepo(tmp, {
      engineStdout: JSON.stringify({ ok: true, result: { count: rows.length, tickets: rows } }),
    })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 200 && r.body?.ok === true, '200 ok 回执')
    const got = r.body.result.tickets
    ok(got.length === 4, '行数透传')
    ok(got[0].paused === true && got[0].paused_phase === 'at_gate', 'at_gate 二态透传')
    ok(got[1].paused === true && got[1].paused_phase === 'pending', 'pending 二态透传')
    ok(got[2].paused === false && got[2].paused_phase === '', '未暂停二态透传')
    ok(got[3].close_ts === 0 && got[3].exec_status === 'COMPLETED' && got[3].updated_ts === 1725900000,
      'close_ts 归一 + 引擎超集键（exec_status/updated_ts）逐键透传')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- B 畸形输入 ---------------- */
  section('B 畸形输入：缺键/非布尔/缺 tickets 不 throw')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const rows = [
      { id: 'b1', project: 'alpha', stage_state: 'done' },            // 缺 paused/paused_phase/close_ts
      engineRow({ id: 'b2', paused: 'yes', paused_phase: 42 }),       // 非布尔/非串——原样透传不清洗
    ]
    const repo = makeRepo(tmp, {
      engineStdout: JSON.stringify({ ok: true, result: { count: rows.length, tickets: rows } }),
    })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 200, '畸形行不拖垮整体（200）')
    const got = r.body.result.tickets
    ok(got[0].paused === undefined && got[0].paused_phase === undefined && got[0].close_ts === 0,
      '缺 paused 键字段缺省、close_ts 防御归一，不 throw')
    ok(got[1].paused === 'yes' && got[1].paused_phase === 42, '非布尔/非串原样透传不清洗（清洗=前端纯函数层职责）')
    rmSync(tmp, { recursive: true, force: true })
  }
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const repo = makeRepo(tmp, { engineStdout: JSON.stringify({ ok: true, result: {} }) })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 200 && r.body.result.count === 0 && r.body.result.tickets.length === 0,
      'result 缺 tickets → 200 空列表（合法空态）')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- C 错误契约（R3） ---------------- */
  section('C 引擎 ok:false → 502 原文；workflow ok:false → 502；stdout 非 JSON → 502')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const repo = makeRepo(tmp, {
      engineStdout: JSON.stringify({ ok: false, error: 'Temporal 不可达: connection refused' }),
    })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 502, '引擎 ok:false 显式 502（不再吃成 200 空列表）')
    ok(String(r.body?.error).includes('Temporal 不可达: connection refused'), '错误原文透传')
    rmSync(tmp, { recursive: true, force: true })
  }
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    // 引擎好、workflow list 坏（admin.py 被参设为 workflow 也回 ok:false）
    const repo = makeRepo(tmp, {
      engineStdout: JSON.stringify({ ok: true, result: { count: 0, tickets: [] } }),
      adminMode: `if (tool === 'workflow') { console.log(JSON.stringify({ ok: false, error: 'workflow-list 炸了' })); process.exit(0) }`,
    })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 502 && String(r.body?.error).includes('workflow-list 炸了'), 'workflow list ok:false 同族 502')
    rmSync(tmp, { recursive: true, force: true })
  }
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const repo = makeRepo(tmp, { engineStdout: 'Traceback (most recent call last): ...' })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 502, 'stdout 非 JSON（引擎栈溢出文本）→ 502（JSON.parse 拒→catch）')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- D 通道锁 ---------------- */
  section('D 列表不再走 admin.py 的 ticket 通道')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const repo = makeRepo(tmp, {
      engineStdout: JSON.stringify({ ok: true, result: { count: 1, tickets: [engineRow()] } }),
      // 假 admin 对 ticket op 回炸错：若列表仍走旧通路，Promise.all 会炸或回 502
      adminMode: `if (tool === 'ticket') { console.log('TICKET-CHANNEL-USED'); process.exit(3) }`,
    })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 200 && r.body.result.tickets[0].paused === true,
      '列表直走引擎 ticket-list（ticket 通道被调用会破坏本断言）')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- E 白名单回归 ---------------- */
  section('E project 缺参/未知 key → 400 回归')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const repo = makeRepo(tmp, { engineStdout: JSON.stringify({ ok: true, result: { count: 0, tickets: [] } }) })
    const h = makeHarness(repo)
    const r1 = await call(h.tickets, '/sandbar-workbench/api/wf/tickets')
    ok(r1.status === 400, '缺 project → 400')
    const r2 = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=nope')
    ok(r2.status === 400 && String(r2.body?.error).includes('nope'), '未知 key → 400（findProject 白名单）')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- F maxBuffer 冒烟 ---------------- */
  section('F 行数组 >1MB 仍 200 全量（maxBuffer 16MB 处置生效）')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91004-'))
    const rows = Array.from({ length: 4000 }, (_, i) =>
      engineRow({ id: `bulk-${i}`, title: 'x'.repeat(300) }))
    const payload = JSON.stringify({ ok: true, result: { count: rows.length, tickets: rows } })
    ok(payload.length > 1024 * 1024, `造的回执确实超过 execFile 默认 1MB（实际 ${(payload.length / 1048576).toFixed(2)}MB）`)
    const repo = makeRepo(tmp, { engineStdout: payload })
    const h = makeHarness(repo)
    const r = await call(h.tickets, '/sandbar-workbench/api/wf/tickets?project=alpha')
    ok(r.status === 200 && r.body.result.tickets.length === 4000, '批量响应不被 maxBuffer 剪断（502 会暴露）')
    rmSync(tmp, { recursive: true, force: true })
  }
} finally {
  if (savedEnv.SANDBAR_PROJECTS_DIR === undefined) delete process.env.SANDBAR_PROJECTS_DIR
  else process.env.SANDBAR_PROJECTS_DIR = savedEnv.SANDBAR_PROJECTS_DIR
  if (savedEnv.SANDBAR_PROJECTS_YAML === undefined) delete process.env.SANDBAR_PROJECTS_YAML
  else process.env.SANDBAR_PROJECTS_YAML = savedEnv.SANDBAR_PROJECTS_YAML
}

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
