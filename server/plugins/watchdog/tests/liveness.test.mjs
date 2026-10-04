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
// t261004-12：stall 路径要求 running=false 位（新加法信号），语义与旧路径逐字同。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null, sessionRunning: false }
  const r = judgeExecutor(sig, NOW, 15, NOW - 16 * M)
  assert(r.state === 'stalled' && r.stall_minutes === 15, 'signal but no progress past threshold = stalled')
  assert(r.evidence.includes('running=false'), 'stalled evidence names the running bit as the check source')
  assert(r.session_running === false, 'liveness exposes session_running on the status face')
  const r2 = judgeExecutor(sig, NOW, 15, NOW - 10 * M)
  assert(r2.state === 'advancing' && r2.evidence.includes('under the threshold'), 'silent but under threshold = not stalled (wide upper bound)')
  const r3 = judgeExecutor(sig, NOW, 15, NOW - 16 * M - 8 * 3600_000)
  assert(r3.state === 'stalled', 'host-sleep long jump with signal still judged by progress rule (no false kill on bare clock alone)')
  n += 5
}
// 宽限拍不得重置静默计时（t261001-19 缺陷 A 回归钉）：调用方按返回的 last_progress_at
// 回灌基准点时，静默分钟数必须单调增长直至 stalled（每拍清零 = stall 永不可达）。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null, sessionRunning: false }
  const base = NOW - 60_000
  let r = judgeExecutor(sig, NOW, 15, base)
  let last = r.last_progress_at
  r = judgeExecutor(sig, NOW + 5 * M, 15, last)
  last = r.last_progress_at
  assert(r.state === 'advancing' && r.evidence.includes('silence 6'), 'grace tick silence grows (6 min) across ticks')
  assert(last === base, 'grace tick does NOT move last_progress_at (no clock reset)')
  r = judgeExecutor(sig, NOW + 16 * M, 15, last)
  assert(r.state === 'stalled', 'feedback loop reaches stalled once silence passes threshold')
  n += 3
}
// 无信号 vs missing 分开报。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: null, lastWakeAt: null, sessionRunning: false }
  const r = judgeExecutor(sig, NOW, 15, null)
  assert(r.state === 'no_signal' && r.evidence.includes('Data may be stale'), 'no signal at all = no_signal (data may be stale), not stalled')
  const r2 = judgeExecutor({ ...sig, sessionKnown: false }, NOW, 15, null)
  assert(r2.state === 'missing', 'undeclared session = explicit missing')
  n += 2
}
// —— t261004-12：running 位进判定 ——
// running=true 且无推进：不是停摆。静默未超长回合阈值照常 advancing（措辞点名来源）。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null, sessionRunning: true }
  const r = judgeExecutor(sig, NOW, 15, NOW - 16 * M, 45)
  assert(r.state === 'advancing', 'running=true silence under long-turn threshold is NOT stalled (old code redlined here)')
  assert(r.evidence.includes('running=true') && r.evidence.includes('Not stalled'), 'evidence names running bit as the check source')
  assert(r.session_running === true, 'liveness exposes session_running=true')
  n += 3
}
// running=true 静默超长回合阈值 = 独立态 long_turn（不是 stalled，自有措辞）。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null, sessionRunning: true }
  const r = judgeExecutor(sig, NOW, 15, NOW - 45 * M, 45)
  assert(r.state === 'long_turn', 'silence past long_turn threshold = distinct long_turn state')
  assert(r.evidence.includes('Long-turn threshold: 45'), 'long_turn evidence names its own threshold')
  const rUnder = judgeExecutor(sig, NOW, 15, NOW - 45 * M + 1, 45)
  assert(rUnder.state === 'advancing', 'one ms under the threshold stays advancing (boundary)')
  // 缺省阈值 = stall_minutes × 3（调用方不显式传时）。
  const rDefault = judgeExecutor(sig, NOW, 15, NOW - 45 * M)
  assert(rDefault.state === 'long_turn', 'default long-turn threshold is stall_minutes * 3')
  n += 4
}
// long_turn 拍不得重置静默计时（review 条件 1，t261001-19 同形雷）：回灌 last_progress_at
// 再走一拍（越过阈值），必须到 long_turn —— 时钟若被宽限拍清零就永远到不了。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null, sessionRunning: true }
  const base = NOW - 40 * M
  let r = judgeExecutor(sig, NOW, 15, base, 45)
  assert(r.state === 'advancing' && r.last_progress_at === base, 'pre-threshold tick keeps baseline untouched')
  r = judgeExecutor(sig, NOW + 10 * M, 15, r.last_progress_at, 45) // 静默 50min > 45min
  assert(r.state === 'long_turn', 'one beat PAST long_turn threshold still reaches long_turn (clock was not reset)')
  assert(r.last_progress_at === base, 'long_turn beat does NOT move last_progress_at either')
  n += 3
}
// running 位读不到（null）：显式 unknown = no_signal，绝不 stalled，也绝不冒充正常。
{
  const sig = { sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: null, sessionRunning: null }
  const r = judgeExecutor(sig, NOW, 15, NOW - 60 * M, 45)
  assert(r.state === 'no_signal', 'unreadable running bit = explicit unknown, never stalled even past stall_minutes')
  assert(r.evidence.includes('running bit is not readable'), 'evidence names the unreadable bit specifically')
  assert(r.session_running === null, 'status face shows session_running=null (unknown stays unknown)')
  // 与「会话文件不可读」是两条 no_signal 来源，措辞必须分得开（review 条件 2）。
  const r2 = judgeExecutor({ ...sig, sessionRunning: false, sessionProgress: null }, NOW, 15, NOW - 60 * M, 45)
  assert(r2.state === 'no_signal' && r2.evidence.includes('session progress signal'), 'session-file unreadable path keeps its own wording')
  assert(r2.evidence !== r.evidence, 'the two no_signal sources have distinct evidence')
  // 畸形输入：sessionRunning 非布尔（undefined 等）一律按 unknown 走，不抛、不冒充。
  const r3 = judgeExecutor({ ...sig, sessionRunning: undefined }, NOW, 15, NOW - 60 * M, 45)
  assert(r3.state === 'no_signal', 'malformed (undefined) running bit treated as unknown, no throw')
  n += 6
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
