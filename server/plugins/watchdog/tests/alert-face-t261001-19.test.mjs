// t261001-19 UT：watchdog 报警面两缺陷的行为断言（全内存桩，零真实 fs/引擎触碰）。
//
// 缺陷 A（stall 不可达）：core 曾按 `state==='advancing'` 刷新 lastProgressAt，而
//   「无推进但未达阈值」的宽限拍也是 advancing ⇒ 静默计时每拍清零 ⇒ stall 永不可能响。
//   钉：宽限拍不动 last_progress_at、证据里静默分钟数增长、超阈后 stalled + stall 落账。
// 缺陷 B（去重键缺 home/preset 隔离域）：key 曾只有 rule+target ⇒ 临时 home 的场景
//   实例响一次就把真宿主同规则静音 12h（真机 261001 实证：18 次 refused 零报警）。
//   钉：共享同一 alerts 账时，不同 DSH_HOME 的实例各自独立响；落账行带 scope。
import { Watchdog } from '../src/host/core.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock, assert, done } from './lib.mjs'

let n = 0
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
const mkCfg = (executorSession) => ({
  ...CFG,
  config: {
    enabled: true, executor_session: executorSession, stall_minutes: 15, reconcile_seconds: 5,
    alerts: {
      enabled: true, sound: true, desktop: true,
      night: { start: '23:00', end: '07:30', policy: 'redline-only' },
      redline: ['stall', 'executor_session_refused', 'executor_missing'], keep_days: 14,
    },
  },
})

function makeDeps({ clock, dshHome, executorSession = 'executor-sb', ledgerLines = [], sessionAdvanced = false, sessionEnsure = null, coreIo = memCoreIo() }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(executorSession),
    io: { tail: memTailIo(files), heartbeat: coreIo.heartbeat, appendAlerts: coreIo.appendAlerts, listAlerts: coreIo.listAlerts },
    boardReader: async () => ({ ok: true, rows: [{ id: 't1', stage_state: 'running' }] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: sessionAdvanced, mtimeMs: clock.now(), running: false }),
    sessionEnsure,
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: dshHome },
  })
  return { w, coreIo }
}

// ── 缺陷 A：宽限拍清零静默计时 ⇒ stall 永不可达 ──────────────────────────────
{
  const clock = fakeClock()
  // 有信号（会话可读）但 sessionAdvanced=false、账本不再进新行 = 「静默推进」场景。
  const { w } = makeDeps({ clock, dshHome: '/realhome', ledgerLines: [ledgerLine({ seq: 1, ticket: 't1' })], sessionAdvanced: false })
  await w.start()
  const p0 = w.status().liveness.executor.last_progress_at
  clock.advance(2 * 60_000)
  await w.tickOnce()
  const l1 = w.status().liveness.executor
  assert(l1.state === 'advancing', 'grace tick stays advancing (under threshold)')
  assert(l1.last_progress_at === p0, 'grace tick does NOT reset the silence clock (last_progress_at unchanged)')
  assert(l1.evidence.includes('silence 2'), 'evidence silence minutes grow across ticks (no more 永远静默 1)')
  clock.advance(13 * 60_000 + 1000)
  await w.tickOnce()
  const l2 = w.status().liveness.executor
  assert(l2.state === 'stalled', 'stall branch is reachable: 15+ min silence with signal = stalled')
  assert(w.status().alerts.some(a => a.rule === 'stall' && a.level === 'redline'), 'stall redline alert actually raised')
  w.dispose(); n += 5
}

// ── 缺陷 B：临时 home 的场景实例不得静音真宿主 ───────────────────────────────
{
  const clock = fakeClock()
  const shared = memCoreIo() // 生产形状：两个实例读写同一个 alerts.jsonl（同 dataDir）。
  const refused = async () => ({
    action: 'refused-preset', sessionId: null, declaredWritten: false,
    reason: 'executor preset 未安装：sandbar-executor（缺 <home>/.agent-presets/sandbar-executor/preset.yml）',
    event: null,
  })
  // ① 临时 home 场景实例：响一次（去重键 = rule:target@/tmp/scene-…）。
  const scene = makeDeps({ clock, dshHome: '/tmp/scene-capture-lane', executorSession: '', ledgerLines: [ledgerLine({ seq: 1, ticket: 't1' })], sessionEnsure: refused, coreIo: shared })
  await scene.w.start()
  const sceneAlerts = scene.w.status().alerts.filter(a => a.rule === 'executor_session_refused')
  assert(sceneAlerts.length === 1, 'temp-home scenario instance records its refusal once')
  assert(sceneAlerts[0].scope === '/tmp/scene-capture-lane', 'recorded alert carries its instance scope (audit face)')
  // ② 真宿主实例（不同 DSH_HOME，共享同一账）：不得被场景实例静音。
  const real = makeDeps({ clock, dshHome: '/Users/user/.dsh', executorSession: '', ledgerLines: [ledgerLine({ seq: 1, ticket: 't1' })], sessionEnsure: refused, coreIo: shared })
  await real.w.start()
  // status().alerts 含共享账重放回来的历史行（含场景实例的）——按本实例 scope 计数。
  const realAlerts = real.w.status().alerts.filter(a => a.rule === 'executor_session_refused' && a.scope === '/Users/user/.dsh')
  assert(realAlerts.length === 1, 'real host records its OWN refusal alert (not muted by temp-home instance)')
  // ③ 同实例冷却内不重响（节流语义不丢）。
  scene.coreIo.appended.length = 0
  clock.advance(60_000)
  await scene.w.tickOnce()
  const sceneScopeAlerts = () => scene.w.status().alerts.filter(a => a.rule === 'executor_session_refused' && a.scope === '/tmp/scene-capture-lane')
  assert(sceneScopeAlerts().length === 1, 'same instance within cooldown stays deduped (no spam)')
  scene.w.dispose(); real.w.dispose(); n += 5
}
done(n)
