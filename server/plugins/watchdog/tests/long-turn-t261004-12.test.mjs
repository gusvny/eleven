// t261004-12 UT：running 位进 stall 判定的接线与状态面（公开面断言，非内部结构）。
// 钉三件事：① running=true 长静默不再误报 stall 红线（超长回合阈值 = executor_long_turn
// warn，独立规则独立措辞）；② running=false 超 stall_minutes 照旧 stall 红线（不弱化）；
// ③ running 位读不到 = 显式 unknown，绝不据它打红线。状态面经 w.status().liveness.executor
// 暴露 running 位与所选 case（review 条件 3：从公开面断言，扛内部结构重构）。
import { Watchdog } from '../src/host/core.ts'
import { memTailIo, memCoreIo, fakeClock, assert, done } from './lib.mjs'

const NOW = 1_700_000_000_000
const M = 60_000
let n = 0

function makeDeps({ stat, clock }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => ({
      declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} },
      config: {
        enabled: true, executor_session: 'ex', stall_minutes: 15, long_turn_minutes: 45, reconcile_seconds: 5,
        alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'normal' }, redline: ['stall', 'executor_missing'], keep_days: 14 },
      },
    }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: stat,
    sessionEnsure: async ({ declaredSessionId }) => ({ action: 'adopt', sessionId: declaredSessionId, declaredWritten: false, reason: 'adopt', event: null }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return w
}

// 起点基准：第一拍会话有消息落盘（advanced=true）→ 真进展，基准点定在本拍。
async function seeded(stat, clock) {
  const w = makeDeps({ stat, clock })
  await w.start()
  return w
}

// ① running=true：静默超 stall_minutes(15) 但未超 long_turn(45) → 不再是 stall（旧代码在此打假红线）。
{
  const clock = fakeClock(NOW)
  let running = true, advanced = true
  const w = await seeded(async () => ({ advanced, mtimeMs: clock.now(), running }), clock)
  const face1 = w.status().liveness.executor
  assert(face1.state === 'advancing' && face1.last_progress_at === clock.now(), 'seed beat sets progress baseline (public face)')
  assert(face1.session_running === true, 'status face exposes session_running=true (requirement 4)')
  advanced = false // 长回合开始：不再落消息
  clock.advance(20 * M) // > stall_minutes 15，< long_turn 45
  await w.tickOnce()
  const face2 = w.status().liveness.executor
  assert(face2.state === 'advancing', 'running=true silence 20min is NOT stalled (old code redlined here)')
  assert(face2.evidence.includes('running=true') && face2.evidence.includes('非停摆'), 'evidence names the check (running bit)')
  assert(face2.session_running === true, 'status face still shows the running bit')
  assert(w.status().alerts.filter(a => a.rule === 'stall').length === 0, 'no false stall redline was recorded')
  w.dispose()
  n += 5
}

// ② running=true 静默超 long_turn(45) → 独立 case：state=long_turn + executor_long_turn(warn)，
//    且 clock 不被宽限拍清零（先在阈值内走两拍，再越过阈值一拍，必须到达 long_turn）。
{
  const clock = fakeClock(NOW)
  let running = true, advanced = true
  const w = await seeded(async () => ({ advanced, mtimeMs: clock.now(), running }), clock)
  advanced = false
  clock.advance(30 * M)
  await w.tickOnce()
  assert(w.status().liveness.executor.state === 'advancing', 'pre-threshold long-turn beat stays advancing')
  clock.advance(20 * M) // 累计 50min > 45min
  await w.tickOnce()
  const face = w.status().liveness.executor
  assert(face.state === 'long_turn', 'past long_turn threshold the state is the distinct long_turn case')
  assert(face.evidence.includes('长回合阈值 45'), 'long_turn wording names its own threshold')
  const lt = w.status().alerts.filter(a => a.rule === 'executor_long_turn')
  assert(lt.length === 1, 'executor_long_turn raised exactly once (dedupe path)')
  assert(lt[0].level === 'warn', 'executor_long_turn is warn, NOT a redline (not in the redline list)')
  assert(w.status().alerts.filter(a => a.rule === 'stall').length === 0, 'long turn never raises the stall rule')
  w.dispose()
  n += 5
}

// ③ running=false：静默超 stall_minutes(15) → stall 红线照旧（有用行为不弱化）。
{
  const clock = fakeClock(NOW)
  let running = true, advanced = true
  const w = await seeded(async () => ({ advanced, mtimeMs: clock.now(), running }), clock)
  advanced = false
  running = false // 会话空转/死透：running 位为 false
  clock.advance(16 * M)
  await w.tickOnce()
  const face = w.status().liveness.executor
  assert(face.state === 'stalled', 'running=false silence past stall_minutes = stalled exactly as today')
  assert(face.evidence.includes('running=false'), 'stall evidence names the running=false check')
  const stall = w.status().alerts.filter(a => a.rule === 'stall')
  assert(stall.length === 1 && stall[0].level === 'redline', 'stall redline still fires (no weakening)')
  w.dispose()
  n += 3
}

// ④ running 位读不到（null）：即使静默 60min 也不打 stall 红线；显式 unknown 上状态面。
{
  const clock = fakeClock(NOW)
  let running = true, advanced = true
  const w = await seeded(async () => ({ advanced, mtimeMs: clock.now(), running }), clock)
  advanced = false
  running = null
  clock.advance(60 * M)
  await w.tickOnce()
  const face = w.status().liveness.executor
  assert(face.state === 'no_signal', 'unreadable running bit = explicit unknown, never stalled')
  assert(face.session_running === null, 'status face shows session_running=null (unknown stays unknown)')
  assert(w.status().alerts.filter(a => a.rule === 'stall').length === 0, 'no stall redline from an unreadable bit')
  w.dispose()
  n += 3
}

// ⑤ 不变量回归：missing（未声明会话）与 self_lock 的输入面未动——executor_missing 仍在
//    （有活+无会话），判活状态面照旧缺省与会话无关的路径。
{
  const clock = fakeClock(NOW)
  const core = memCoreIo()
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const w = new Watchdog('sandbar', {
    configLoader: () => ({
      declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} },
      config: {
        enabled: true, executor_session: '', stall_minutes: 15, long_turn_minutes: 45, reconcile_seconds: 5,
        alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'normal' }, redline: ['stall', 'executor_missing'], keep_days: 14 },
      },
    }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [{ id: 't1', stage_state: 'running' }] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: null, mtimeMs: null, running: null }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  await w.start()
  assert(w.status().alerts.filter(a => a.rule === 'executor_missing').length === 1, 'executor_missing unchanged (undeclared session + work)')
  w.dispose()
  n += 1
}

done(n)
