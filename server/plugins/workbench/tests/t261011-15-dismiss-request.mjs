#!/usr/bin/env node
// t261011-15 UT —— dismiss/restore 请求面：项目锚走 ?project= URL 通道 + 请求 URL 构造。
//
// 直跑：node server/plugins/workbench/tests/t261011-15-dismiss-request.mjs
// （exit 0 = 过）。零网络 / 零真仓 / 零真 Temporal / 不碰 console。
//
// 背景（工单正文第二道缝）：submitDismissal 收 projectKey 却从不发送——URL 不带
// ?project=，body 只有 {who, reason}。路由（node.ts:1339-1345）从不读 body.project；
// 调用方身份只经 anchorOf(url)（?project=）→ caller_project 进引擎（t260928-24
// 同缝类）。本票把锚接上：URL 构造单点抽到模型层纯函数 dismissRequestUrl
// （ticket-list-model.ts，node 可裸 import），sidebar 只委托。
//
// 借 t261009-54 假仓 harness 形态（假 admin.py 记录 ticket 通道实参）。**故障模式
// 取舍清单原样承接**（t261009-54 头注，review gen1 意见③：不重新推导）：畸形
// payload / 幂等态（重复 dismiss、未摘先 restore）**不在客户端与路由层处理**——
// 全是引擎具名拒收，原样透传；who/reason 双方都不默认（空 reason 的拒收是引擎的，
// 面板先问）；dismiss/restore 不发 Temporal signal（假引擎通道零调用）。
// 拒收透传与通道锁已由 t261009-54 钉死，本 UT 不重复，只补项目锚两支。
//
// 覆盖：
//   A. URL 构造（纯函数面）：带 key → ?project=<enc>；空 key（无主巡检组）→ 无
//      query（路由纪律「视图无 key 时不猜」，node.ts:1258-1260）；id/key 特殊字符
//      编码；非字符串 key（畸形输入）不 throw、按缺省落无 query。
//   B. 引擎缝（假引擎实参面）：用构造出的 URL POST dismiss → 引擎 args 带
//      caller_project:'alpha'、by/reason 原样（镜像 t261009-54 覆盖 A 的
//      「项目锚随行」，但锚来自本票的客户端构造）。
//   C. 空 key 支路在缝上：无 query 的请求引擎 args **不带** caller_project
//      （未声明身份原样到引擎，绝不猜默认 key）、回执仍 200 ok。
//
// Independent (node >=22 type-stripping, cwd=repo root; exit 0 = pass).
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { dismissRequestUrl } from '../src/client/ticket-list-model.ts'
import { apply } from './../node.ts'

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

const TICKETS_PREFIX = '/sandbar-workbench/api/wf/tickets'

/* ---------------- A. URL 构造（纯函数面） ---------------- */
ok(dismissRequestUrl('alpha', 't261011-15', 'dismiss') === `${TICKETS_PREFIX}/t261011-15/dismiss?project=alpha`,
  'with a project key: ?project= rides the URL')
ok(dismissRequestUrl('', 't261011-15', 'restore') === `${TICKETS_PREFIX}/t261011-15/restore`,
  'blank key (unowned inspection group): NO query — no guessing (route discipline)')
ok(dismissRequestUrl('a b/c', 't 3', 'dismiss') === `${TICKETS_PREFIX}/t%203/dismiss?project=a%20b%2Fc`,
  'id and key are URL-encoded (no raw spaces/slashes in the path or query)')
for (const bad of [undefined, null, 0, 7, true, {}, []]) {
  // Declared behaviour: a non-string key is treated as absent — the base URL,
  // no query, never a throw and never a guessed key.
  ok(dismissRequestUrl(bad, 't1', 'dismiss') === `${TICKETS_PREFIX}/t1/dismiss`,
    `malformed project key (${String(bad)}) = no query, no throw`)
}

/* ---------------- 假仓 harness（t261009-54 形态，只留本票需要的面） ---------------- */
function makeRepo(tmp) {
  const repo = join(tmp, 'repo')
  const reg = join(tmp, 'registry')
  mkdirSync(join(reg, 'alpha'), { recursive: true })
  writeFileSync(join(reg, 'alpha', 'project.yaml'),
    'schema: v1\nproject:\n  - key: alpha\n    name: 甲\n    dirs:\n      - /tmp/alpha\n', 'utf8')
  writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
  process.env.SANDBAR_PROJECTS_DIR = reg
  const record = join(tmp, 'admin-calls.json')
  mkdirSync(join(repo, 'server'), { recursive: true })
  writeFileSync(join(repo, 'server', 'admin.py'), `
const fs = require('node:fs');
const args = process.argv.slice(2);
const tool = args[1] ?? '';
const calls = JSON.parse(fs.readFileSync(${JSON.stringify(record)}, 'utf8'));
calls.push({ tool, args: JSON.parse(args[2] ?? '{}') });
fs.writeFileSync(${JSON.stringify(record)}, JSON.stringify(calls));
if (tool === 'ticket') console.log(JSON.stringify({ ok: true, run_id: 'run-t1115', result: { dismissed: true } }));
else console.log(JSON.stringify({ ok: true, result: { workflows: [] } }));
process.exit(0);
`, 'utf8')
  writeFileSync(record, '[]', 'utf8')
  const engineBin = join(repo, 'server', 'engine', '.venv', 'bin', 'python')
  mkdirSync(dirname(engineBin), { recursive: true })
  writeFileSync(engineBin, `#!/usr/bin/env node
process.stdout.write(JSON.stringify({ ok: true, result: { count: 0, tickets: [] } }))
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
  return routes.find(r => r.path === TICKETS_PREFIX && r.kind === 'prefix')
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

/* ---------------- B. 引擎缝：构造 URL 的锚随行 ---------------- */
{
  const tmp = mkdtempSync(join(tmpdir(), 'wb-t11115-'))
  const { repo, record } = makeRepo(tmp)
  const h = makeHarness(repo)
  const url = dismissRequestUrl('alpha', 't261011-15', 'dismiss')
  const r = await post(h, url, { who: 'op-abc123', reason: 'dead failed ticket' })
  ok(r.status === 200 && r.body?.ok === true, 'B: dismiss via the built URL -> 200 ok')
  const a = recorded(record)[0]?.args ?? {}
  ok(a.op === 'dismiss' && a.id === 't261011-15', 'B: op + id reach the engine')
  ok(a.by === 'op-abc123' && a.reason === 'dead failed ticket', 'B: who->by and reason verbatim (contract untouched)')
  ok(a.caller_project === 'alpha', 'B: ?project= from the built URL -> caller_project at the engine (the seam this ticket closes)')
  rmSync(tmp, { recursive: true, force: true })
}

/* ---------------- C. 引擎缝：空 key 支路不猜 ---------------- */
{
  const tmp = mkdtempSync(join(tmpdir(), 'wb-t11115-'))
  const { repo, record } = makeRepo(tmp)
  const h = makeHarness(repo)
  const url = dismissRequestUrl('', 't261011-15', 'restore')
  ok(!url.includes('?'), 'C: blank-key URL carries no query (pre-condition)')
  const r = await post(h, url, { who: 'op-abc123', reason: 'put back' })
  ok(r.status === 200 && r.body?.ok === true, 'C: restore via the blank-key URL -> 200 ok')
  const a = recorded(record)[0]?.args ?? {}
  ok(a.op === 'restore' && a.by === 'op-abc123', 'C: op/by verbatim')
  ok(!('caller_project' in a), 'C: no caller_project injected — undeclared identity stays undeclared, never guessed')
  rmSync(tmp, { recursive: true, force: true })
}

console.log(`t261011-15-dismiss-request: ${n} assertions, all pass`)
