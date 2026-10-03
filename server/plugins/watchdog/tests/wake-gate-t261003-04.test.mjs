// t261003-04 缺陷 B：零发现的周期巡检行不得唤醒执行器；真迁移照醒；行留在审计账。
// 真机 261002 实测：dispatcher-scan 行占项目账 17.4%（374/2147），全部 '0 tickets,
// 0 pending' 且全部投递了 wake（15 秒一簇的空醒）。
import { worthWaking, isZeroFindingPeriodicRow, wakeExecutor, freshWakeMemory } from '../src/host/exits.ts'
import { assert, done } from './lib.mjs'

let n = 0
const row = (over = {}) => ({
  idem: 'x|1', project: 'sandbar', ticket: 't1', seq: 1, raw: {}, ...over,
})

// —— 纯判定面：零发现行识别 ——
// dispatcher scan 真形（workflows.py 逐字：'Scan report: N tickets, M pending (...)'）。
assert(isZeroFindingPeriodicRow(row({ stage: 'scan', stage_state: 'done', reason: 'Scan report: 0 tickets, 0 pending (stuck-suspect 0 / needs-supply 0 / signable 0)' })), 'scan 0/0 done row is zero-finding')
assert(isZeroFindingPeriodicRow(row({ stage: 'scan', stage_state: 'running', reason: 'Dispatcher scan started' })) === false, 'scan running row (no counts) is NOT zero-finding (fails open = may wake, conservative)')
assert(isZeroFindingPeriodicRow(row({ stage: 'scan', stage_state: 'done', reason: 'Scan report: 3 tickets, 1 pending (stuck-suspect 0 / needs-supply 0 / signable 0)' })) === false, 'scan with tickets/pending is NOT zero-finding (real content must wake)')
assert(isZeroFindingPeriodicRow(row({ stage: 'scan', stage_state: 'done', reason: 'Scan report: 0 tickets, 2 pending (...)' })) === false, 'scan with pending decisions is NOT zero-finding')
assert(isZeroFindingPeriodicRow(row({ stage: 'scan', stage_state: 'done' })) === false, 'malformed input: scan row with no reason fails open (NOT suppressed)')
assert(isZeroFindingPeriodicRow(row({ stage: 'scan', stage_state: 'done', reason: 'Scan report: ?? tickets, ?? pending' })) === false, 'malformed input: unparseable counts fail open (NOT suppressed)')
// inspection spawn dedup 回执（inspection_flow.py：'... deduped=true/false ...'）。
assert(isZeroFindingPeriodicRow(row({ stage: 'spawn', stage_state: 'done', reason: 'Period ticket spawned (instance a, ticket=t9, deduped=true, slot_taken_at=unknown, fixture=false)' })), 'spawn deduped=true receipt is zero-finding (no new ticket)')
assert(isZeroFindingPeriodicRow(row({ stage: 'spawn', stage_state: 'done', reason: 'Period ticket spawned (instance a, ticket=t9, deduped=false, slot_taken_at=unknown, fixture=false)' })) === false, 'spawn deduped=false (real new ticket) is NOT zero-finding')
assert(isZeroFindingPeriodicRow(row({ stage: 'spawn', stage_state: 'running', reason: 'Spawning period ticket (instance a)' })) === false, 'spawn running row is NOT zero-finding')
// 其它 stage 一律不压（真迁移不受影响）。
assert(isZeroFindingPeriodicRow(row({ stage: 'implement', stage_state: 'running', reason: 'Scan report: 0 tickets, 0 pending' })) === false, 'non-periodic stage is never suppressed even with zero-scan reason')
n += 10

// —— worthWaking 组合面 ——
assert(worthWaking(row({ stage: 'implement', stage_state: 'running' })) === true, 'real stage transition still wakes')
assert(worthWaking(row({ stage: 'implement' })) === true, 'stage-only row still wakes')
assert(worthWaking(row({ kind: 'engine-maintenance' })) === false, 'pure-kind row still does not wake')
assert(worthWaking(row({ stage: 'scan', stage_state: 'done', reason: 'Scan report: 0 tickets, 0 pending (...)' })) === false, 'DEFECT B: zero-finding scan row no longer wakes (row stays in audit ledger)')
assert(worthWaking(row({ stage: 'scan', stage_state: 'done', reason: 'Scan report: 5 tickets, 0 pending' })) === true, 'scan with findings still wakes')
assert(worthWaking(row({ stage: 'spawn', stage_state: 'done', reason: '... deduped=true ...' })) === false, 'DEFECT B: dedup receipt no longer wakes')
n += 6

// —— 出口行为面：零发现行不产生投递；真迁移行照投 ——
{
  let prompts = 0
  const io = { async prompt() { prompts += 1; return { accepted: true, requestId: 'r1' } }, async queueDepth() { return 0 } }
  const zero = [row({ ticket: 't1', stage: 'scan', stage_state: 'done', reason: 'Scan report: 0 tickets, 0 pending (stuck-suspect 0 / needs-supply 0 / signable 0)' })]
  const out0 = await wakeExecutor(io, 'sandbar', 'sess-1', zero, null, 'info', freshWakeMemory())
  assert(out0.woke === false && prompts === 0, 'exit face: all-zero-finding window does not prompt the executor')
  const real = [row({ ticket: 't2', stage: 'review', stage_state: 'running', reason: 'started' })]
  const mem = freshWakeMemory()
  const out1 = await wakeExecutor(io, 'sandbar', 'sess-1', real, null, 'info', mem)
  assert(out1.woke === true && prompts === 1, 'exit face: real transition in the same window prompts exactly once')
  const mixed = [...zero, ...real]
  const out2 = await wakeExecutor(io, 'sandbar', 'sess-1', mixed, null, 'info', freshWakeMemory())
  assert(out2.woke === true && prompts === 2, 'exit face: mixed window wakes on the real rows only')
  n += 3
}

done(n)
