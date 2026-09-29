/**
 * 真形锁（t260929-07，本票要点）：reader 必须「机器读」真入口 client.py ticket-list
 * 的 ACTUAL stdout——不是我们假设的形状。自证桩（实现形状喂实现）正是本缺陷根因
 * （KI-148/150 家族），桩测试不作为本锁证据。
 *
 * 语义：真入口不可达（Temporal 离线/venv 缺失）= ENV_FAIL，测试非零退出——绝不静默
 * 放行（跳过 = 假绿）。
 */
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { assert, done } from './lib.mjs'
import { parseTicketListDoc } from '../node.ts'

const execFileP = promisify(execFile)
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')
const engineDir = join(repo, 'server', 'engine')
const py = existsSync(join(engineDir, '.venv', 'bin', 'python')) ? join(engineDir, '.venv', 'bin', 'python') : 'python3'

let raw
try {
  const { stdout } = await execFileP(py, ['client.py', 'ticket-list', JSON.stringify({})], {
    cwd: engineDir, timeout: 30_000, maxBuffer: 32 * 1024 * 1024,
  })
  raw = stdout
} catch (e) {
  console.error('ENV_FAIL: real client.py ticket-list unreachable on this machine — '
    + 'the real-shape lock must never pass silently without the live receipt. '
    + (e instanceof Error ? e.message.slice(0, 300) : String(e)))
  process.exit(2)
}

let n = 0
const t = (cond, name) => { assert(cond, name); n++ }

// 形状契约 belt（t260929-07 实证）：真入口打的是信封 {ok:true,result:{...}}，且
// result 内层没有 ok 键——旧代码 `res.ok !== true` 正是踩在这条上。锁住它：
// 未来引擎侧改变这条契约时，本断言翻转 = 有意识变更，不是漂移。
const doc = JSON.parse(raw)
t(doc.ok === true, 'real entry envelope ok:true')
t(doc.result != null && typeof doc.result === 'object' && !('ok' in doc.result), 'envelope result has NO ok key (the exact contract the old code violated)')
t(Array.isArray(doc.result.tickets), 'envelope result exposes tickets array')

// 真实 stdout 原样过 reader 的解析实现（同一份发布代码路径，不是测试侧重抄）。
const parsed = parseTicketListDoc(raw)
t(parsed.ok === true, 'reader parses the LIVE entry stdout (real-shape lock, t260929-07)')
t(parsed.ok && parsed.tickets.length > 0, `reader yields rows>0 from live engine (got ${parsed.ok ? parsed.tickets.length : 0})`)
t(parsed.ok && parsed.tickets.every((row) => typeof row.id === 'string' && row.id.length > 0), 'every live row has an id')

console.log(`board-reader-real-shape: ${n} checks, live rows=${parsed.ok ? parsed.tickets.length : 'n/a'}`)
await done()
