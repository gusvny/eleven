// self-wake-loop UT（t260929-04 review C1/C2 钉死面）：喂「循环形状」的输入断言零唤醒/有界唤醒。
// 场景（每段都是完整闭环）：简报 → executor 消化 → 它自己的动作写账 → 断言不再醒。
import { wakeExecutor, freshWakeMemory } from '../src/host/exits.ts'
import { parseLedgerLine } from '../src/host/ledger-tail.ts'
import { ledgerLine, assert, done } from './lib.mjs'

let n = 0

function row(ticket, stage, state, seq = 1) {
  return parseLedgerLine(ledgerLine({ ticket, stage, stage_state: state, seq }))
}

function stubIo({ depth = 0, ours = undefined, accepted = true } = {}) {
  const prompts = []
  return {
    prompts,
    prompt: async (sid, text, mode) => { prompts.push({ sid, text, mode }); return { accepted, requestId: `watchdog-${prompts.length}` } },
    queueDepth: async () => depth,
    ourBriefPending: ours === undefined ? undefined : async () => ours,
  }
}

{
  // 核心闭环：简报点名 t1 → executor 签字产生 t1 的下一个迁移 → 零唤醒。
  const io = stubIo()
  const mem = freshWakeMemory()
  const r1 = await wakeExecutor(io, 'p1', 'executor-x', [row('t1', 'implement', 'running')], null, 'info', mem)
  assert(r1.woke === true && io.prompts.length === 1, 'brief-worthy row wakes once')
  // 它消化了（镜像认领 = false），随后自己的签字入账：
  const io2 = stubIo({ ours: false })
  const r2 = await wakeExecutor(io2, 'p1', 'executor-x', [row('t1', 'review', 'running')], null, 'info', mem)
  assert(r2.woke === false && r2.presumedSelf === 1 && io2.prompts.length === 0, 'LOOP SHAPED INPUT: executor own next transition = ZERO wakes (presumed-self exclusion)')
  assert((r2.reason ?? '').includes('疑似自'), 'suppression reason names the presumed-self rule (loud, not silent)')
  // 同一票第二个新迁移 = 多步真进展，恢复唤醒。
  const r3 = await wakeExecutor(io2, 'p1', 'executor-x', [row('t1', 'review', 'passed')], null, 'info', mem)
  assert(r3.woke === true && io2.prompts.length === 1, 'second new stage of same ticket wakes again (real progress not swallowed)')
  // 已进过简报的 stage_key 永不重醒（idem 排除）。
  const r4 = await wakeExecutor(io2, 'p1', 'executor-x', [row('t1', 'implement', 'running')], null, 'info', mem)
  assert(r4.woke === false && io2.prompts.length === 1, 'already-briefed stage_key never re-wakes (at-least-once replays)')
  n += 5
}
{
  // C1：简报没点名过的票（executor 顺手直修）——至多多醒一次，下一次迁移被压住：循环有界。
  const mem = freshWakeMemory()
  const io = stubIo()
  await wakeExecutor(io, 'p1', 'executor-x', [row('t1', 'implement', 'running')], null, 'info', mem) // 简报只点名 t1
  const io2 = stubIo({ ours: false })
  const r2 = await wakeExecutor(io2, 'p1', 'executor-x', [row('t9', 'direct-fix', 'running')], null, 'info', mem)
  assert(r2.woke === true && io2.prompts.length === 1, 'non-briefed ticket self-write wakes at most ONCE (C1 bounded)')
  const io3 = stubIo({ ours: false })
  const r3 = await wakeExecutor(io3, 'p1', 'executor-x', [row('t9', 'direct-fix', 'passed')], null, 'info', mem)
  assert(r3.woke === false && io3.prompts.length === 0 && r3.presumedSelf === 1, 'its NEXT transition suppressed: loop bounded to <=1 extra wake per new ticket (C1 case)')
  n += 2
}
{
  // 纯疑似自批（全部行都被排除）→ 不醒但显式点名，不是「无迁移行」的静默路径。
  const mem = freshWakeMemory()
  const io = stubIo()
  await wakeExecutor(io, 'p1', 'executor-x', [row('t1', 'a', 'running')], null, 'info', mem)
  const io2 = stubIo({ ours: false })
  const r = await wakeExecutor(io2, 'p1', 'executor-x', [row('t1', 'b', 'running'), row('t1', 'b', 'running', 2)], null, 'info', mem)
  assert(r.woke === false && io2.prompts.length === 0, 'all-presumed-self batch = no delivery at all')
  n += 1
}
{
  // C2：镜像可读且「我们的」简报还在 → 压住（哪怕别人也在队列里，认领面优先于深度）。
  const mem = freshWakeMemory()
  const io = stubIo()
  const r1 = await wakeExecutor(io, 'p1', 'executor-x', [row('t1', 'a', 'running')], null, 'info', mem)
  assert(mem.lastRequestId === 'watchdog-1', 'accepted brief records its requestId for rpcId claiming')
  const io2 = stubIo({ ours: true })
  const r2 = await wakeExecutor(io2, 'p1', 'executor-x', [row('t2', 'x', 'running')], null, 'info', mem)
  assert(r2.woke === false && (r2.reason ?? '').includes('我们的队列项'), 'un-digested window (rpcId claimed) = no second brief (message not lost, just deferred)')
  // 消化后（ours=false）同一行照发：别人的队列流量不拦我们（深度闸不再冒充认领面）。
  const io3 = stubIo({ ours: false, depth: 3 })
  const r3 = await wakeExecutor(io3, 'p1', 'executor-x', [row('t2', 'x', 'passed')], null, 'info', mem)
  assert(r3.woke === true && io3.prompts.length === 1, 'after digestion, wake resumes even with other-source queue traffic (C2)')
  n += 3
}
{
  // 认领面缺失（旧桩只有 queueDepth）→ 深度闸回落；镜像不可读 → 照发并点名（显式 no-signal）。
  const mem = freshWakeMemory()
  const ioDepth = stubIo({ depth: 2 })
  const r1 = await wakeExecutor(ioDepth, 'p1', 'executor-x', [row('t1', 'a', 'running')], null, 'info', mem)
  assert(r1.woke === false && (r1.reason ?? '').includes('队列深 2'), 'fallback: depth gate still enforced when claiming seam absent')
  const mem2 = freshWakeMemory()
  const ioUnreadable = stubIo({ depth: null, ours: undefined })
  const r2 = await wakeExecutor(ioUnreadable, 'p1', 'executor-x', [row('t1', 'a', 'running')], null, 'info', mem2)
  assert(r2.woke === true && (r2.reason ?? '').includes('队列态不可读'), 'unreadable mirror = send anyway with named no-signal (never fake digested)')
  const mem3 = freshWakeMemory()
  const ioUnreadableClaim = stubIo({ depth: null, ours: null })
  const r3 = await wakeExecutor(ioUnreadableClaim, 'p1', 'executor-x', [row('t1', 'a', 'running')], null, 'info', mem3)
  assert(r3.woke === true && (r3.reason ?? '').includes('队列态不可读'), 'claiming seam present but mirror unreadable (null) = same loud no-signal path')
  // 畸形行形状进过滤器不炸（外部输入纪律）。
  const weird = parseLedgerLine(ledgerLine({ ticket: 'tz', stage: 's', stage_state: undefined, __drop: ['stage_state'] }))
  const r4 = await wakeExecutor(stubIo({ depth: 0 }), 'p1', 'executor-x', [weird], null, 'info', freshWakeMemory())
  assert(r4.woke === true, 'row with missing stage_state still handled (no crash on odd shapes)')
  n += 4
}
done(n)
