/**
 * integration/t260901-22/t01_sign_note_passthrough.mjs
 * —— KI-004「approve 签字自由备注」服务端全链路黑盒（t260901-22）。
 *
 * 用户故事：审批人在工单台 approve 弹层填了自由备注，点「确认通过并推进」，
 * 这条备注必须随 sign 信号**逐字节**进 Temporal 工单事件历史——不能丢、不能截、
 * 不能被服务端二次加工。（2026-09-01 一天十几次 CLI 代签就是因为弹层没有输入口。）
 *
 * 黑盒手法：真实 host（node.ts apply + mock webServer）+ 临时 repo 里塞一个
 * 桩 `.venv/bin/python` 顶替 temporal-poc client.py——它把收到的 sign 信号 payload
 * 原文落盘。测试从 HTTP POST /sandbar-workbench/api/wf/tickets/<id>/sign 打入，
 * 断言桩落盘的信号 input.note 与请求体逐字节一致（模式同 smoke/epics.mjs C 组）。
 *
 * 直跑：node integration/t260901-22/t01_sign_note_passthrough.mjs（node ≥22.18）。
 * 末行 SUMMARY pass=<n> skip=<m> fail=<k>；fail>0 才 exit 1。
 */

import { execFile } from 'node:child_process'
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)
const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '..', '..')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fail++; console.error(`  ✗ ${label}`) }
}
function section(s) { console.log(`\n== ${s} ==`) }

const tmp = await mkdtemp(path.join(tmpdir(), 't22-t01-'))

try {
  /* ---- 客户端纯函数：用它 compose 备注（同时证明 src/client/approve-note.ts 已交付）---- */
  section('前置：src/client/approve-note.ts 可 import 且语义正确')
  let buildApproveNote
  try {
    ({ buildApproveNote } = await import('./../src/client/approve-note.ts'))
    ok(typeof buildApproveNote === 'function', 'buildApproveNote 已导出')
  } catch (err) {
    ok(false, `src/client/approve-note.ts 不可 import（implement 未交付？）：${String(err)}`)
  }

  /* ---- 桩 repo：.venv/bin/python 顶替 client.py，把 sign payload 落盘 ---- */
  section('环境：真实 host + 桩 poc CLI')
  const stubRepo = path.join(tmp, 'stub-repo')
  const record = path.join(tmp, 'sign-record.jsonl')
  const venvBin = path.join(stubRepo, 'server', 'dsh', 'temporal-poc', '.venv', 'bin')
  await mkdir(venvBin, { recursive: true })
  await writeFile(path.join(venvBin, 'python'), `#!/bin/sh
# 桩 temporal-poc client.py：argv = client.py <op> <json>。JSON 是最后一个参数，原文落盘后回固定应答。
last=
for a in "$@"; do last=$a; done
printf '%s\\n' "$last" >> '${record}'
printf '%s\\n' '{"ok": true, "result": {"stub": "poc-cli", "note_echoed": true}}'
`, 'utf8')
  await chmod(path.join(venvBin, 'python'), 0o755)

  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  const { apply } = await import('./../node.ts')
  apply(ctx, { repo: stubRepo })
  const ticketPrefix = routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/wf/tickets')
  ok(ticketPrefix !== undefined, 'host 路由已挂（/sandbar-workbench/api/wf/tickets prefix）')

  const mockRes = () => ({
    status: 0, body: null,
    writeHead(s) { this.status = s },
    end(b) { this.body = b ? JSON.parse(b) : null },
  })
  const mockReq = (url, method, body) => ({
    url, method,
    async *[Symbol.asyncIterator]() { if (body !== undefined) yield Buffer.from(body) },
  })
  const call = async (url, method, payload) => {
    const res = mockRes()
    const body = payload === undefined ? undefined : JSON.stringify(payload)
    await ticketPrefix.handler(mockReq(url, method, body), res)
    return res
  }
  /** 读桩落盘的最后一条 sign payload。 */
  const lastSignal = async () => {
    try {
      const lines = (await readFile(record, 'utf8')).trim().split('\n').filter(Boolean)
      return lines.length === 0 ? undefined : JSON.parse(lines[lines.length - 1])
    } catch { return undefined }
  }
  const signalCount = async () => {
    try { return (await readFile(record, 'utf8')).trim().split('\n').filter(Boolean).length }
    catch { return 0 }
  }
  const URL = '/sandbar-workbench/api/wf/tickets/t260901-22/sign'

  /* ---- A. approve + 自由备注：逐字节进 sign 信号 ---- */
  section('A approve：备注随 sign 进历史（用户主路径）')
  if (typeof buildApproveNote === 'function') {
    const summary = '审批意见第3轮：conclude=pass，块 approve 2/reject 0/带注释 1（落盘 server/dsh/reviews/t260901-22.json，reviewer integration）'
    const remark = '第一段：内容方向认可。\n第二段：但「这段有问题」里的引号与 CJK 标点要保留，\\n 不转义。'
    const note = buildApproveNote(summary, remark)
    const r = await call(URL, 'POST', { decision: 'approve', note, who: 'integration-tester' })
    ok(r.status === 200 && r.body?.ok === true, 'POST sign approve → 200 ok')
    const sig = await lastSignal()
    ok(sig?.op === 'sign' && sig?.ticket_id === 't260901-22', '信号路由到 ticket workflow（op=sign，id 正确）')
    ok(sig?.input?.decision === 'approve', 'input.decision=approve')
    ok(sig?.input?.note === note, 'input.note 与请求体逐字节一致（多行/CJK/引号不丢不转义）')
    ok(sig?.input?.note.includes('\n\n') && sig?.input?.note.split('\n\n').length === 2,
      '摘要与备注之间恰好一个空行分段（备注独立成段）')
    ok(sig?.input?.who === 'integration-tester', 'input.who 透传')
  } else {
    ok(false, 'A 组跳过前置失败：buildApproveNote 不可用')
  }

  /* ---- B. 空备注回落：sign 照发，note='' ---- */
  section('B 空备注：可空口径（留空=现状行为）')
  {
    const before = await signalCount()
    const r = await call(URL, 'POST', { decision: 'approve', who: 'op-local' })
    ok(r.status === 200 && r.body?.ok === true, 'note 缺省 → 200（签字不阻塞）')
    const sig = await lastSignal()
    ok(sig?.input?.note === '', 'note 缺省 → input.note=""（回落，不报错）')
    ok((await signalCount()) === before + 1, '恰好发出 1 条 sign 信号')
  }

  /* ---- C. 边界：超长不截、纯空白不加工 ---- */
  section('C 边界：超长备注 / 纯空白备注')
  {
    const longRemark = '长'.repeat(5000)
    const note = typeof buildApproveNote === 'function'
      ? buildApproveNote('审批意见第1轮：conclude=pass', longRemark) : longRemark
    const r = await call(URL, 'POST', { decision: 'approve', note })
    ok(r.status === 200 && r.body?.ok === true, '5000 字备注 → 200')
    const sig = await lastSignal()
    ok(sig?.input?.note === note && sig?.input?.note.length === note.length,
      '5000 字备注逐字节透传、零截断')
  }
  {
    const r = await call(URL, 'POST', { decision: 'approve', note: '   ' })
    ok(r.status === 200, '纯空白备注 → 200')
    const sig = await lastSignal()
    ok(sig?.input?.note === '   ', '服务端不 trim 备注（trim 是客户端纯函数职责，服务端零加工）')
  }

  /* ---- D. 打回路径零改动回归 ---- */
  section('D 回归：reject 路径未被本单破坏')
  {
    const r = await call(URL, 'POST', { decision: 'reject', note: '返工：第2节例子不成立', who: 'integration-tester' })
    ok(r.status === 200 && r.body?.ok === true, 'POST sign reject → 200')
    const sig = await lastSignal()
    ok(sig?.input?.decision === 'reject' && sig?.input?.note === '返工：第2节例子不成立',
      'reject + 自由 note 逐字节透传')
  }

  /* ---- E. 异常输入 fail-closed（畸形/超限时不得产生 sign 信号）---- */
  section('E 异常输入：fail-closed 且不产生信号')
  {
    const before = await signalCount()
    let r = await call(URL, 'POST', undefined) // 空 body → {}
    ok(r.status === 200 && (await lastSignal())?.input?.decision === 'approve',
      '空 body → 按缺省 approve+空 note 放行（引擎既有口径，不 4xx）')
    r = await call(URL, 'GET')
    ok(r.status === 405, 'GET sign → 405')
    r = await mockRes() && await (async () => {
      const res = mockRes()
      await ticketPrefix.handler(mockReq(URL, 'POST', '{not-json'), res)
      return res
    })()
    ok(r.status === 400 && String(r.body?.error).includes('JSON'), '非法 JSON body → 400 人话')
    ok((await signalCount()) === before + 1, '畸形输入零 sign 信号泄漏（只放行过空 body 那 1 条）')
  }
  {
    const big = 'x'.repeat(70 * 1024)
    const res = mockRes()
    await ticketPrefix.handler(mockReq(URL, 'POST', big), res)
    ok(res.status === 400 && String(res.body?.error).includes('64KB'),
      'body 超 64KB → 400 明确报「body 超过 64KB」（历史 note 有实际上限，报错必须精确）')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\nSUMMARY pass=${pass} skip=0 fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
