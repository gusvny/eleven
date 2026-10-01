// liveness UT：进展驱动判活（三源）/ 休眠不误报 / missing / no_signal / 心跳读写与显式降级。
import { judgeExecutor, touchHeartbeat, readHeartbeat } from '../src/host/liveness.ts'
import { assert, done } from './lib.mjs'

let n = 0
const NOW = 1_700_000_000_000
const M = 60_000
// 推进三源任一 = advancing。
{
  const base = { sessionKnown: true, sessionProgress: false, lastWakeAt: null }
  const r1 = judgeExecutor({ ...base, ledgerAdvanced: true }, NOW, 15, null)
  assert(r1.state === 'advancing' && r1.last_progress_at === NOW, 'ledger advance = progress')
  const r2 = judgeExecutor({ ...base, ledgerAdvanced: false, sessionProgress: true }, NOW, 15, NOW - 20 * M)
  assert(r2.state === 'advancing', 'session file progress = progress')
  const r3 = judgeExecutor({ ...base, ledgerAdvanced: false, lastWakeAt: NOW - M }, NOW, 15, NOW - 20 * M)
  assert(r3.state === 'advancing', 'recent wake = progress')
  n += 3
}
// 有信号无推进 + 墙钟超阈 = stalled；未达阈 = 静默但不判死（偏宽兜底语义）。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null }
  const r = judgeExecutor(sig, NOW, 15, NOW - 16 * M)
  assert(r.state === 'stalled' && r.stall_minutes === 15, 'signal but no progress past threshold = stalled')
  const r2 = judgeExecutor(sig, NOW, 15, NOW - 10 * M)
  assert(r2.state === 'advancing' && r2.evidence.includes('未达阈值'), 'silent but under threshold = not stalled (wide upper bound)')
  const r3 = judgeExecutor(sig, NOW, 15, NOW - 16 * M - 8 * 3600_000)
  assert(r3.state === 'stalled', 'host-sleep long jump with signal still judged by progress rule (no false kill on bare clock alone)')
  n += 3
}
// 宽限拍不得重置静默计时（t261001-19 缺陷 A 回归钉）：调用方按返回的 last_progress_at
// 回灌基准点时，静默分钟数必须单调增长直至 stalled（每拍清零 = stall 永不可达）。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null }
  const base = NOW - 60_000
  let r = judgeExecutor(sig, NOW, 15, base)
  let last = r.last_progress_at
  r = judgeExecutor(sig, NOW + 5 * M, 15, last)
  last = r.last_progress_at
  assert(r.state === 'advancing' && r.evidence.includes('静默 6'), 'grace tick silence grows (6 min) across ticks')
  assert(last === base, 'grace tick does NOT move last_progress_at (no clock reset)')
  r = judgeExecutor(sig, NOW + 16 * M, 15, last)
  assert(r.state === 'stalled', 'feedback loop reaches stalled once silence passes threshold')
  n += 3
}
// 无信号 vs missing 分开报。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: null, lastWakeAt: null }
  const r = judgeExecutor(sig, NOW, 15, null)
  assert(r.state === 'no_signal' && r.evidence.includes('数据可能过期'), 'no signal at all = no_signal (data may be stale), not stalled')
  const r2 = judgeExecutor({ ...sig, sessionKnown: false }, NOW, 15, null)
  assert(r2.state === 'missing', 'undeclared session = explicit missing')
  n += 2
}
// 心跳写读：新鲜/过期/坏内容/缺文件。
{
  const calls = []
  const io = {
    write: async (p, d) => { calls.push([p, d]) },
    read: async () => JSON.stringify({ last_beat: NOW - 30_000 }),
    mtimeMs: async () => null,
  }
  await touchHeartbeat(io, '/hb.json', NOW)
  assert(calls.length === 1 && JSON.parse(calls[0][1]).last_beat === NOW, 'heartbeat touch writes last_beat')
  const fresh = await readHeartbeat(io, '/hb.json', NOW, 3 * M)
  assert(fresh.alive === true && fresh.age_seconds === 30, 'fresh heartbeat alive')
  const ioOld = { ...io, read: async () => JSON.stringify({ last_beat: NOW - 10 * M }) }
  const stale = await readHeartbeat(ioOld, '/hb.json', NOW, 3 * M)
  assert(stale.alive === false && stale.reason === null, 'stale heartbeat explicitly not alive')
  const ioBad = { ...io, read: async () => 'not-json', mtimeMs: async () => NOW - 1000 }
  const bad = await readHeartbeat(ioBad, '/hb.json', NOW, 3 * M)
  assert(bad.alive === true && bad.reason !== null, 'corrupt heartbeat falls to mtime with explicit reason')
  const ioNone = { ...io, read: async () => { throw new Error('ENOENT') }, mtimeMs: async () => null }
  const none = await readHeartbeat(ioNone, '/hb.json', NOW, 3 * M)
  assert(none.alive === false && none.reason !== null, 'no heartbeat file = explicit dead, never all-fine')
  n += 5
}
done(n)
