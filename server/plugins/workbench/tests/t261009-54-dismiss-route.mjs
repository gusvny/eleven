#!/usr/bin/env node
// t261009-54 UT —— /wf/tickets/<id>/dismiss|restore 路由接缝（API 面，假引擎）。
//
// 直跑：node server/plugins/workbench/tests/t261009-54-dismiss-route.mjs
// （exit 0 = 过）。零网络 / 零真仓 / 零真 Temporal / 不碰 console。
//
// 背景（工单正文）：左列摘除按钮点了没反应——client 早已 POST
// /wf/tickets/<id>/dismiss|restore（sidebar.tsx DISMISS_URL/RESTORE_URL），
// 而 node.ts OPS 白名单没有这两个 op ⇒ 恒 404「未知操作」。引擎半边
// （ticket.py op=dismiss|restore，t261009-31）早已存在。本票把路由接上：
// OPS 加二 op + 分发分支 who→by、reason 原样，callTool('ticket', args)
// 审计面透传，引擎回执（含拒收）逐字回给面板。
//
// 借 t260910-04 假仓 harness 形态。借 pause/resume 分支形态的故障模式取舍
// （review 意见①）：畸形 payload / 幂等态（重复 dismiss、未摘先 restore）
// **不在路由层处理**——全是引擎具名拒收，原样透传；pause/resume 走 Temporal
// signal 而 dismiss/restore 刻意不走（摘除只记 journal、不发信号、不动状态机，
// ticket_dismiss.py 契约），本 UT 用「假引擎（client.py 通道）零调用」钉死这点。
//
// 覆盖：
//   A. dismiss POST 真到引擎 op：假 admin 收到 op:'dismiss'、by=请求 who（请求
//      身份，非路由常量）、reason 原样、project 锚随行；回执 200 逐字透传。
//   B. restore 同形映射（op:'restore'）。
//   C. 引擎拒收逐字透传：ok:false（空 reason / agent 角色名）→ 200 + 原文
//      ok:false——绝不 404、绝不空体、绝不改写成成功（修掉 x.json() 解析错模式）。
//   D. 畸形输入不默认：缺 who → by 为空串原样到引擎（审计锚=请求身份，路由不
//      代填）；缺 reason → reason 空串原样到引擎（空 reason 的拒收是引擎的）。
//   E. 未知 op 仍回具名 404「未知操作 <op>（可用：…）」。
//   F. 通道锁：dismiss/restore 不发 Temporal signal（假引擎 client.py 通道零调用）。
//   G. 端到端面：ticket-list 行的 dismissed 键以引擎 payload 为真源逐字透传
//      （摘除后行面 dismissed:true，撤回后 false）——前端/路由从不本地翻转。

import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { apply } from './../node.ts'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const TICKETS_PREFIX = '/sandbar-workbench/api/wf/tickets'

/** 假仓 harness（t260910-04 形态）：registry + 假 admin.py（记录 ticket 通道实参）
 *  + 假引擎 venv python（client.py 通道；本票它应保持零调用）。 */
function makeRepo(tmp, { adminMode, engineStdout } = {}) {
  const repo = join(tmp, 'repo')
  const reg = join(tmp, 'registry')
  mkdirSync(join(reg, 'alpha'), { recursive: true })
  writeFileSync(join(reg, 'alpha', 'project.yaml'),
    'schema: v1\nproject:\n  - key: alpha\n    name: 甲\n    dirs:\n      - /tmp/alpha\n', 'utf8')
  writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
  process.env.SANDBAR_PROJECTS_DIR = reg

  const record = join(tmp, 'admin-calls.json')
  const mode = adminMode ?? 'ok'
  mkdirSync(join(repo, 'server'), { recursive: true })
  // 假 admin.py：runAdminCli 以 config.python=process.execPath 直接执行本文件。
  // 记录每次 ticket 通道实参（工具审计锚用例的取证面），按 mode 回结构化回执。
  writeFileSync(join(repo, 'server', 'admin.py'), `
const fs = require('node:fs');
const args = process.argv.slice(2); // ['call', tool, argsJSON]
const tool = args[1] ?? '';
const calls = JSON.parse(fs.readFileSync(${JSON.stringify(record)}, 'utf8'));
calls.push({ tool, args: JSON.parse(args[2] ?? '{}') });
fs.writeFileSync(${JSON.stringify(record)}, JSON.stringify(calls));
if (tool === 'workflow') {
  console.log(JSON.stringify({ ok: true, result: { workflows: [{ id: 'wf1' }] } }));
  process.exit(0);
}
if (tool === 'ticket') {
  const mode = ${JSON.stringify(mode)};
  if (mode === 'ok') {
    console.log(JSON.stringify({ ok: true, run_id: 'run-test-1', result: { dismissed: true, journal: 'appended' } }));
  } else if (mode === 'refuse-reason') {
    console.log(JSON.stringify({ ok: false, error: 'dismiss 需要 reason（处置理由必填非空，绝不默认）' }));
  } else if (mode === 'refuse-agent-role') {
    console.log(JSON.stringify({ ok: false, error: 'who is an agent role name (developer) — only a human can sign a dismissal' }));
  } else if (mode === 'refuse-who') {
    console.log(JSON.stringify({ ok: false, error: 'dismiss 需要 who/by（人工签名必填——无签名的人工处置绝不收）' }));
  }
  process.exit(0);
}
console.log(JSON.stringify({ ok: false, error: 'FAKE-ADMIN: 未供通道 ' + tool }));
process.exit(1);
`, 'utf8')
  writeFileSync(record, '[]', 'utf8')

  // 假引擎：<repo>/server/engine/.venv/bin/python（runPocCli 硬编码路径）。本票
  // dismiss/restore 不走此通道（不发 signal）——用例 F 靠「调用即污染列表回执」暴露。
  const engineBin = join(repo, 'server', 'engine', '.venv', 'bin', 'python')
  mkdirSync(dirname(engineBin), { recursive: true })
  writeFileSync(engineBin, `#!/usr/bin/env node
process.stdout.write(${JSON.stringify(String(engineStdout ?? JSON.stringify({ ok: true, result: { count: 0, tickets: [] } })))})
`, 'utf8')
  chmodSync(engineBin, 0o755)
  return { repo, record }
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
  const route = routes.find(r => r.path === TICKETS_PREFIX && r.kind === 'prefix')
  return route
}

const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b ?? ''; try { this.body = JSON.parse(b) } catch { this.body = null } },
})
const post = async (handler, path, body) => {
  const res = mockRes()
  const payload = Buffer.from(JSON.stringify(body ?? {}))
  const req = {
    url: path, method: 'POST',
    async *[Symbol.asyncIterator]() { yield payload },
  }
  await handler.handler(req, res)
  return res
}
const recorded = (record) => JSON.parse(readFileSync(record, 'utf8')).filter(c => c.tool === 'ticket')

/** 标准引擎行（键序对齐 client.py _row_from_meta；dismissed=t261009-31 行面）。 */
function engineRow(over = {}) {
  return {
    id: 't261009-50', project: 'alpha', epic: '', role: 'developer',
    status: 'failed', title: 'dead dismiss button', workflow: 'DevLaneWorkflow',
    proposal_id: '', stage: 'implement', stage_state: 'running',
    paused: false, paused_phase: '', dismissed: false,
    handoff_count: 1, pending_count: 0,
    worktree: '', workspace: null, created: 1000, updated: '10-10 12:00',
    updated_ts: 1760000000, engine: 'v2', exec_status: 'FAILED', close_ts: 0,
    ...over,
  }
}

try {
  /* ---------------- A/B 映射 + 透传 ---------------- */
  section('A dismiss POST 到引擎 op：who→by（请求身份）、reason 原样、回执逐字透传')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
    const { repo, record } = makeRepo(tmp, { adminMode: 'ok' })
    const h = makeHarness(repo)
    const r = await post(h, `${TICKETS_PREFIX}/t261009-50/dismiss?project=alpha`,
      { who: '宿主', reason: 'dupe of t261009-51' })
    ok(r.status === 200 && r.body?.ok === true, '200 ok 回执')
    ok(r.body.result?.dismissed === true && r.body.result?.journal === 'appended', '引擎 result 逐字透传')
    ok(r.body.run_id === 'run-test-1', 'admin run_id 审计锚随行透传')
    const calls = recorded(record)
    ok(calls.length === 1, 'ticket 通道恰被调一次')
    const a = calls[0].args
    ok(a.op === 'dismiss' && a.id === 't261009-50', 'op=dismiss + 票 id 到引擎')
    ok(a.by === '宿主', 'who→by 映射：记录人=请求身份（非路由常量）')
    ok(a.reason === 'dupe of t261009-51', 'reason 原样到引擎（不裁剪不默认）')
    ok(a.caller_project === 'alpha', '项目锚随行（跨项目闸 caller_project 身份声明）')
    rmSync(tmp, { recursive: true, force: true })
  }

  section('B restore 同形映射')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
    const { repo, record } = makeRepo(tmp, { adminMode: 'ok' })
    const h = makeHarness(repo)
    const r = await post(h, `${TICKETS_PREFIX}/t261009-50/restore?project=alpha`,
      { who: '宿主', reason: 'still needs rework' })
    ok(r.status === 200 && r.body?.ok === true, 'restore 200 ok')
    const a = recorded(record)[0].args
    ok(a.op === 'restore' && a.by === '宿主' && a.reason === 'still needs rework', 'restore 映射同形')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- C 拒收逐字透传 ---------------- */
  section('C 引擎拒收逐字透传：200+ok:false（绝不 404/空体/改写成成功）')
  {
    for (const mode of ['refuse-reason', 'refuse-agent-role']) {
      const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
      const { repo } = makeRepo(tmp, { adminMode: mode })
      const h = makeHarness(repo)
      const r = await post(h, `${TICKETS_PREFIX}/t261009-50/dismiss?project=alpha`,
        { who: mode === 'refuse-agent-role' ? 'developer' : '宿主', reason: mode === 'refuse-reason' ? '' : 'x' })
      ok(r.status === 200, `${mode}: 状态 200（路由不再 404）`)
      ok(r.body !== null && typeof r.body === 'object', `${mode}: JSON 体可解析（x.json() 不再炸）`)
      ok(r.body?.ok === false && typeof r.body?.error === 'string' && r.body.error.length > 0,
        `${mode}: 引擎拒收原文 ok:false 透传，不改写成成功、不吞成空体`)
      rmSync(tmp, { recursive: true, force: true })
    }
  }

  /* ---------------- D 畸形输入不默认 ---------------- */
  section('D 畸形输入不默认：缺 who/缺 reason 原样到引擎（拒收是引擎的）')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
    const { repo, record } = makeRepo(tmp, { adminMode: 'refuse-who' })
    const h = makeHarness(repo)
    const r = await post(h, `${TICKETS_PREFIX}/t261009-50/dismiss?project=alpha`, { reason: 'x' })
    ok(r.status === 200 && r.body?.ok === false
      && String(r.body?.error).includes('who/by'), '缺 who：引擎 who/by 拒收原文透传')
    const a = recorded(record)[0].args
    ok(a.by === '', '缺 who：路由不代填（by 为空串原样——审计锚=请求身份）')
    rmSync(tmp, { recursive: true, force: true })
  }
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
    const { repo, record } = makeRepo(tmp, { adminMode: 'refuse-reason' })
    const h = makeHarness(repo)
    const r = await post(h, `${TICKETS_PREFIX}/t261009-50/dismiss?project=alpha`, { who: '宿主' })
    ok(r.status === 200 && r.body?.ok === false
      && String(r.body?.error).includes('reason'), '缺 reason：引擎 reason 拒收原文透传')
    const a = recorded(record)[0].args
    ok(a.reason === '', '缺 reason：路由不默认（reason 空串原样）')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- E 未知 op 具名 404 ---------------- */
  section('E 未知 op 仍回具名 404')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
    const { repo, record } = makeRepo(tmp, { adminMode: 'ok' })
    const h = makeHarness(repo)
    const r = await post(h, `${TICKETS_PREFIX}/t261009-50/bogus?project=alpha`, { who: '宿主' })
    ok(r.status === 404, '未知 op 404')
    ok(String(r.body?.error ?? '').includes('未知操作 bogus'), '具名 404 face（含可用 op 表）')
    ok(recorded(record).length === 0, '未知 op 不触引擎')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- F 通道锁 ---------------- */
  section('F dismiss/restore 不发 Temporal signal（client.py 通道零调用）')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
    // 假引擎被调即回污染行表——A 用例若误走此通道，200 回执形状立刻不同且本组用例可辨。
    const { repo } = makeRepo(tmp, {
      adminMode: 'ok',
      engineStdout: JSON.stringify({ ok: false, error: 'FAKE-ENGINE: dismiss 不应走 client.py 通道' }),
    })
    const h = makeHarness(repo)
    const r = await post(h, `${TICKETS_PREFIX}/t261009-50/dismiss?project=alpha`,
      { who: '宿主', reason: 'x' })
    ok(r.status === 200 && r.body?.result?.dismissed === true,
      '回执来自 admin ticket 通道（client.py 通道未被触碰）')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* ---------------- G 端到端行面 ---------------- */
  section('G ticket-list 行面 dismissed 以引擎为真源（摘除/撤回）')
  {
    for (const dismissed of [true, false]) {
      const tmp = mkdtempSync(join(tmpdir(), 'wb-t91054-'))
      const rows = [engineRow({ id: 't261009-50', dismissed })]
      const { repo } = makeRepo(tmp, {
        engineStdout: JSON.stringify({ ok: true, result: { count: rows.length, tickets: rows } }),
      })
      const routes = []
      const ws = { register: (r) => { routes.push(r); return () => {} } }
      apply({ effect: (fn) => { fn() }, logger: { info() {}, warn() {} },
        get: (k) => (k === 'webServer' ? ws : undefined), on: () => () => {} },
        { repo, python: process.execPath })
      const list = routes.find(r => r.path === TICKETS_PREFIX && r.kind === 'exact')
      const res = mockRes()
      await list.handler({ url: `${TICKETS_PREFIX}?project=alpha`, method: 'GET',
        async *[Symbol.asyncIterator]() {} }, res)
      ok(res.status === 200 && res.body?.result?.tickets?.[0]?.dismissed === dismissed,
        `行面 dismissed=${dismissed} 逐字透传（引擎真源，不本地翻转）`)
      rmSync(tmp, { recursive: true, force: true })
    }
  }

  console.log(`\n${pass} passed, ${fail} failed`)
  process.exit(fail === 0 ? 0 : 1)
} catch (err) {
  console.error(err)
  process.exit(1)
}
