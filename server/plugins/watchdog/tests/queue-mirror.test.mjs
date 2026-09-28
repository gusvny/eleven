// queue-mirror UT（t260929-04）：baseline 全量 / queue 增量替换 / 坏帧点名 / 流失败与
// 提前结束 = 显式 unreadable / ourBriefPending 按 rpcId 认领 / dispose 全终态。
import { QueueMirror } from '../src/host/queue-mirror.ts'
import { assert, done } from './lib.mjs'

let n = 0

/** 手动供帧的可迭代（测试推进节拍用）。 */
function manualStream() {
  const queued = []
  let doneFlag = false
  let failWith = null
  return {
    push(f) { queued.push(f) },
    end() { doneFlag = true },
    fail(e) { failWith = e; doneFlag = true },
    [Symbol.asyncIterator]() {
      return {
        next: async () => {
          for (;;) {
            if (queued.length > 0) return { value: queued.shift(), done: false }
            if (failWith) throw failWith
            if (doneFlag) return { value: undefined, done: true }
            await new Promise(r => setTimeout(r, 1))
          }
        },
      }
    },
  }
}

{
  // baseline 种全量 → queue 帧逐会话替换。
  const s = manualStream()
  const m = new QueueMirror({ frames: () => s })
  m.start()
  s.push({ type: 'baseline', value: { queues: { 'sess-a': [{ id: 'i1', placement: 'queued', rpcId: 'watchdog-1' }, { id: 'i2', placement: 'context' }], 'sess-b': [] } } })
  await new Promise(r => setTimeout(r, 10))
  assert(m.depthOf('sess-a') === 1, 'baseline seeds: only queued/steering counted (context excluded)')
  assert(m.depthOf('sess-b') === 0, 'baseline seeds empty queue as 0')
  assert(m.depthOf('sess-unknown') === 0, 'unknown session in live mirror = 0 (authoritative), not null')
  s.push({ type: 'queue', sessionId: 'sess-a', items: [] })
  await new Promise(r => setTimeout(r, 10))
  assert(m.depthOf('sess-a') === 0, 'queue frame replaces per-session depth (digestion observed)')
  assert(m.stateInfo === 'live', 'mirror live after baseline')
  s.end()
  await m.dispose()
  n += 6
}
{
  // ourBriefPending：按 rpcId 精确认领我们的项；别人的项不算。
  const s = manualStream()
  const m = new QueueMirror({ frames: () => s })
  m.start()
  s.push({ type: 'queue', sessionId: 'x', items: [{ id: 'i1', placement: 'queued', rpcId: 'watchdog-abc' }, { id: 'i2', placement: 'queued', rpcId: 'human-1' }] })
  await new Promise(r => setTimeout(r, 10))
  assert(m.ourBriefPending('x', 'watchdog-abc') === true, 'our brief (rpcId echo) still pending = true')
  assert(m.ourBriefPending('x', 'human-1') === true, 'any known requestId can be claimed (caller passes only ours)')
  assert(m.ourBriefPending('x', 'watchdog-gone') === false, 'our item digested = false (even with other traffic pending)')
  assert(m.ourBriefPending('y', 'watchdog-abc') === false, 'other session = false, not cross-contaminated')
  assert(m.itemIdOfRpc('x', 'watchdog-abc') === 'i1', 'itemIdOfRpc locates our pending item (updateQueue handle)')
  assert(m.itemIdOfRpc('x', 'watchdog-gone') === null, 'itemIdOfRpc = null when not pending (explicit)')
  s.end()
  await m.dispose()
  n += 4
}
{
  // 坏帧点名计数；jobs/projection 帧不消费也不算坏。
  const s = manualStream()
  const m = new QueueMirror({ frames: () => s })
  m.start()
  s.push({ type: 'jobs', sessionId: 'x', jobs: [] })
  s.push({ type: 'projection', sessionId: 'x', key: 'k', value: 1, seq: 1 })
  s.push(null)
  s.push({ type: 'mystery-frame' })
  s.push({ type: 'queue', sessionId: 42, items: [] }) // sessionId 形状坏
  await new Promise(r => setTimeout(r, 10))
  assert(m.describe().includes('坏帧 3'), `malformed frames counted loudly (got: ${m.describe()})`)
  assert(m.stateInfo === 'idle', 'no baseline yet = not live (never fake authority)')
  assert(m.depthOf('x') === null, 'not-live mirror = explicit null (no-signal), never 0')
  s.end()
  await m.dispose()
  n += 3
}
{
  // 流抛错 / 提前结束 = 终态 unreadable + 原因；终态后 depthOf 恒 null。
  const s = manualStream()
  const terminals = []
  const m = new QueueMirror({ frames: () => s, onTerminal: (st, reason) => terminals.push({ st, reason }) })
  m.start()
  s.push({ type: 'queue', sessionId: 'x', items: [{ id: 'i1' }] })
  await new Promise(r => setTimeout(r, 10))
  assert(m.depthOf('x') === 1, 'live before failure')
  s.fail(new Error('stream exploded'))
  await new Promise(r => setTimeout(r, 10))
  assert(m.stateInfo === 'unreadable' && m.describe().includes('stream exploded'), 'stream error = explicit unreadable with reason')
  assert(m.depthOf('x') === null, 'unreadable mirror never pretends authority')

  const s2 = manualStream()
  const m2 = new QueueMirror({ frames: () => s2 })
  m2.start()
  s2.push({ type: 'queue', sessionId: 'x', items: [] })
  await new Promise(r => setTimeout(r, 10))
  s2.end()
  await new Promise(r => setTimeout(r, 10))
  assert(m2.stateInfo === 'unreadable' && m2.describe().includes('结束'), 'premature stream end = explicit unreadable')
  await m.dispose(); await m2.dispose()
  n += 5
}
{
  // 工厂不可达 / 抛错 = 显式 unreadable；dispose 幂等且终态收口。
  const m = new QueueMirror({ frames: () => null })
  m.start()
  assert(m.stateInfo === 'unreadable' && m.describe().includes('不可达'), 'unavailable controller = explicit unreadable')
  const m2 = new QueueMirror({ frames: () => { throw new Error('factory boom') } })
  m2.start()
  assert(m2.describe().includes('factory boom'), 'factory throw = named reason')
  await m.dispose(); await m2.dispose()
  await m.dispose() // 幂等
  assert(m.stateInfo === 'unreadable', 'dispose idempotent, terminal')
  n += 3
}
done(n)
