/**
 * concurrency-face.test.mjs —— t261006-17 (CL-2) 读面 UT：
 *  - 回执解析真值表（ok:true 外壳 / 具名拒收逐字 / 非 JSON / 形状坏 / 非零退出带可解析回执）；
 *  - spawn 全终态（成功 / 超时 kill / 非零退出+空回执 / spawn 抛错）——全部落定，无悬挂；
 *  - 旋钮一步与 chip 三态纯函数真值表（与页面同一实现，EMBEDDED 漂移在 page 测试锁）。
 * 全部用桩 execFileFn，零真引擎、零真盘。
 */
import { assert, done } from './lib.mjs'
import { join } from 'node:path'
import {
  readConcurrency, parseConcurrencyRead, limitStep, concChipState,
  concurrencyReadArgv, engineTicketPath,
} from '../src/host/concurrency.ts'

let n = 0

const GOOD_FACE = {
  project: 'alpha', limit: 2, unlimited: false, decl: '/tmp/p/alpha/concurrency-limit.json',
  holders: [
    { ticket: 't-1', since: 100, reason: 'running', held_s: 60 },
    { ticket: 't-2', since: 200, reason: 'human-hold', held_s: 30 },
  ],
  queue: [
    { ticket: 't-3', position: 1, since: 300, waited_s: 120 },
    { ticket: 't-4', position: 2, since: 400, waited_s: 60 },
  ],
}

// ---- argv 形状（读面入口钉死 ticket.py op=concurrency） ----
{
  const [ticketPath, payload] = concurrencyReadArgv('alpha')
  assert(ticketPath === engineTicketPath() && ticketPath.endsWith(join('server', 'tools', 'ticket.py')),
    'read face addresses server/tools/ticket.py')
  const parsed = JSON.parse(payload)
  assert(parsed.op === 'concurrency' && parsed.project === 'alpha',
    'read payload is {op:concurrency, project:key}')
  n += 2
}
// ---- 解析真值表 ----
{
  const r = parseConcurrencyRead(JSON.stringify({ ok: true, result: GOOD_FACE }))
  assert(r.ok === true && r.limit === 2 && r.unlimited === false, 'happy face parses')
  assert(r.ok === true && r.holders.length === 2 && r.queue.length === 2, 'holders and queue carried')
  assert(r.ok === true && r.queue[1].position === 2 && r.queue[1].waited_s === 60,
    'engine-owned positions and waited seconds carried verbatim')
  assert(r.ok === true && r.holders[1].reason === 'human-hold', 'human-hold reason carried (amber-dot source)')
  n += 4

  const REFUSAL = { ok: false, error: 'ValueError: Concurrency slot ledger unreadable/malformed: /tmp/p/alpha/concurrency-state.json (JSONDecodeError: x) - fail-closed refusal, never treated as an empty ledger' }
  const r2 = parseConcurrencyRead(JSON.stringify(REFUSAL))
  assert(r2.ok === false && r2.reason.includes('/tmp/p/alpha/concurrency-state.json'),
    'refusal text carried VERBATIM incl. the absolute path')
  assert(r2.ok === false && !('holders' in r2) && !('queue' in r2),
    'a refusal never carries holders/queue (an empty array would read as "nobody working")')
  n += 2

  const r3 = parseConcurrencyRead('{ this is not json')
  assert(r3.ok === false && r3.reason.includes('non-JSON'), 'non-JSON receipt = named refusal')
  const r4 = parseConcurrencyRead(JSON.stringify({ ok: true }))
  assert(r4.ok === false && r4.reason.includes('no result object'), 'missing result = named refusal')
  const r5 = parseConcurrencyRead(JSON.stringify({ ok: true, result: { ...GOOD_FACE, holders: 'nope' } }))
  assert(r5.ok === false && r5.reason.includes('holders must be an array'), 'bad holders shape = named refusal')
  const r6 = parseConcurrencyRead(JSON.stringify({ ok: true, result: { ...GOOD_FACE, limit: '3' } }))
  assert(r6.ok === false && r6.reason.includes('limit'), 'string limit = named refusal (never a silent unlimited)')
  const r7 = parseConcurrencyRead('')
  assert(r7.ok === false && r7.reason.length > 0, 'empty stdout = named refusal')
  n += 5
}

// ---- spawn 全终态 ----
function stubExec(stdout, err, capture) {
  return (cmd, args, opts, cb) => {
    if (capture) capture.push({ cmd, args, timeout: opts.timeout })
    setTimeout(() => cb(err || null, stdout), 1)
  }
}
async function readWith(stdout, err) {
  return await readConcurrency('alpha', { SANDBAR_PROJECTS_DIR: '/tmp/x' }, { execFileFn: stubExec(stdout, err) })
}
{
  const r = await readWith(JSON.stringify({ ok: true, result: GOOD_FACE }), null)
  assert(r.ok === true, 'spawn success parses the receipt')
  n++
  const r2 = await readWith('', Object.assign(new Error('boom'), { killed: true }))
  assert(r2.ok === false && r2.reason.includes('timed out and was killed'), 'timeout kill = named, no dangling')
  const r3 = await readWith('', new Error('spawn ENOENT'))
  assert(r3.ok === false && r3.reason.includes('failed:'), 'non-zero exit + empty stdout = named failure')
  // 非零退出但 stdout 带完整回执 → 照解析（引擎先打印再退出）。
  const r4 = await readWith(JSON.stringify({ ok: false, error: 'ValueError: absent declaration' }), Object.assign(new Error('exit 1')))
  assert(r4.ok === false && r4.reason.includes('absent declaration'),
    'non-zero exit with a parseable receipt still carries the engine refusal text')
  n += 3
  // spawn 抛错（同步 throw 路径）也落定。
  const thrower = () => { throw new Error('cannot spawn') }
  const r5 = await readConcurrency('alpha', {}, { execFileFn: thrower })
  assert(r5.ok === false && r5.reason.includes('could not spawn'), 'synchronous spawn throw = named')
  n++
}

// ---- 旋钮一步真值表（页面上限=同一份实现） ----
{
  assert(limitStep(10, 1) === 'unlimited', '10 + -> Unlimited')
  assert(limitStep('unlimited', -1) === 10, 'Unlimited - -> 10')
  assert(limitStep(1, -1) === 1, '1 - clamps at 1')
  assert(limitStep('unlimited', 1) === 'unlimited', 'Unlimited + stays Unlimited')
  assert(limitStep(3, 1) === 4 && limitStep(3, -1) === 2, 'mid-range steps')
  n += 5
  assert(concChipState(5, false, 2) === 'room', '2 of 5 = room to start one')
  assert(concChipState(2, false, 2) === 'at', '2 of 2 = at the limit')
  assert(concChipState(1, false, 2) === 'over', '2 over 1 = over the limit')
  assert(concChipState(null, true, 9) === 'room', 'unlimited is always room')
  assert(concChipState(null, false, 1) === 'room', 'null limit with unlimited flag false still room (defensive)')
  n += 5
}

done(n)
