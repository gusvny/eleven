// executor-session core UT（t260930-09）：「未声明 = 按需创建；已声明 = 收养」在
// Watchdog 状态机里的接线——无活不建 / 有活一拍恰建一只并回写 / 重启复用（不建第二只）/
// 声明 id 从宿主消失才重建 / 人的声明绝不替换（对本票改动前的代码此杆为红）/ off 开关。
// 全内存桩（零真实宿主、零 3099/7233），与 core.test.mjs 同款依赖注入。
import { Watchdog } from '../src/host/core.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock, assert, done } from './lib.mjs'

let n = 0
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
const mkCfg = (over = {}) => ({ ...CFG, config: { enabled: true, executor_session: '', stall_minutes: 15, reconcile_seconds: 5, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'], keep_days: 14 }, ...over } })

function makeWd({ clock, executorSession = '', boardRows = [], ledgerLines = [], sessionEnsure = null, enabled = true } = {}) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  const events = []
  const w = new Watchdog('sandbar', {
    configLoader: () => ({ ...CFG, enabled, config: mkCfg({ executor_session: executorSession }).config }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: boardRows }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: null }),
    sessionEnsure,
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return { w, events, core }
}

function stubEnsure({ fail = false } = {}) {
  const calls = []
  return {
    calls,
    fn: async ({ declaredSessionId, hasWork }) => {
      calls.push({ declaredSessionId, hasWork })
      if (fail) return { action: 'refused', sessionId: null, declaredWritten: false, reason: 'host create failed (stub)', event: { at: 1, action: 'refused', session_id: null, by: 'watchdog', preset: 'sandbar-executor', project: 'sandbar', cwd: null, reason: 'x' } }
      return { action: declaredSessionId === '' ? 'create' : 'adopt', sessionId: declaredSessionId === '' ? 'auto-1' : declaredSessionId, declaredWritten: declaredSessionId === '', reason: 'stub', event: { at: 1, action: declaredSessionId === '' ? 'create' : 'adopt', session_id: declaredSessionId === '' ? 'auto-1' : declaredSessionId, by: 'watchdog', preset: 'sandbar-executor', project: 'sandbar', cwd: '/c', reason: 'stub' } }
    },
  }
}

// ① 有活 + 未声明：恰一次代建，回写进内存面（后续拍用同一 id），状态面显式。
{
  const clock = fakeClock()
  const se = stubEnsure()
  const { w } = makeWd({ clock, ledgerLines: [ledgerLine({ seq: 1 })], sessionEnsure: se.fn })
  await w.start()
  assert(se.calls.length === 1, 'work + undeclared = exactly one ensure call')
  assert(se.calls[0].hasWork === true && se.calls[0].declaredSessionId === '', 'ensure saw work and empty declaration')
  await w.tickOnce()
  assert(se.calls.length === 1, 'second tick does NOT create again (idempotent after adopt/write-back)')
  const st = w.status()
  assert(st.executor_session && st.executor_session.session_id === 'auto-1' && st.executor_session.last_action === 'create', 'status names the created session')
  assert(st.liveness.executor && st.liveness.executor.state !== 'missing', 'liveness no longer "missing" once the session exists')
  w.dispose(); n += 4
}
// ② 无活：零代建（冻结遗留项目口径）。
{
  const clock = fakeClock()
  const se = stubEnsure()
  const { w } = makeWd({ clock, ledgerLines: [], boardRows: [], sessionEnsure: se.fn })
  await w.start()
  assert(se.calls.length === 0, 'no work = nothing created at all')
  w.dispose(); n += 1
}
// ③ 有活无账本但有在飞票（board 有行）→ 也算有活。
{
  const clock = fakeClock()
  const se = stubEnsure()
  const { w } = makeWd({ clock, boardRows: [{ id: 't1', stage_state: 'running' }], sessionEnsure: se.fn })
  await w.start()
  assert(se.calls.length === 1 && se.calls[0].hasWork === true, 'in-flight board tickets count as work')
  w.dispose(); n += 1
}
// ④ 已声明（人的声明）：收养，绝不创建、绝不覆盖——本票改动前的代码此杆为红
//   （旧语义是「缺声明=零行为」，没有收养/代建面可言；新语义下必须恰一次 adopt）。
{
  const clock = fakeClock()
  const se = stubEnsure()
  const { w } = makeWd({ clock, executorSession: 'human-declared', ledgerLines: [ledgerLine({ seq: 1 })], sessionEnsure: se.fn })
  await w.start()
  await w.tickOnce()
  assert(se.calls.length === 1, 'declared id = exactly one adopt check per process')
  assert(se.calls[0].declaredSessionId === 'human-declared', 'adopt sees the human-declared id')
  const last = se.calls[se.calls.length - 1]
  assert(last.declaredSessionId === 'human-declared', 'the human declaration is passed through untouched')
  w.dispose(); n += 2
}
// ⑤ 重启（新实例、同账）：声明的 id 仍在宿主清单 → 不建第二只（ensure 恰一次 adopt）。
//   ensure 桩的声明入参非空即代表「声明仍在」，走收养分支——等价于 ④ 的重启面。
{
  const clock = fakeClock()
  const se = stubEnsure()
  const { w } = makeWd({ clock, executorSession: 'recorded-1', ledgerLines: [ledgerLine({ seq: 1 })], sessionEnsure: se.fn })
  await w.start()
  assert(se.calls.length === 1, 'restart with recorded id reuses it (one adopt, no second session)')
  w.dispose(); n += 1
}
// ⑥ 声明 id 从宿主消失 + 有活 → ensure 收到 recreate 语义（声明 id + hasWork，由
//   session-create 决策核判 recreate）；此处钉 core 把两个事实都交出去。
{
  const clock = fakeClock()
  const se = { calls: [], fn: async (a) => { se.calls.push(a); return { action: 'recreate', sessionId: 're-1', declaredWritten: true, reason: 'stub', event: null } } }
  const { w } = makeWd({ clock, executorSession: 'ghost-1', ledgerLines: [ledgerLine({ seq: 1 })], sessionEnsure: se.fn })
  await w.start()
  assert(se.calls.length === 1 && se.calls[0].declaredSessionId === 'ghost-1' && se.calls[0].hasWork === true, 'core hands declaration + work facts to the decision core')
  const st = w.status()
  assert(st.executor_session.last_action === 'recreate', 'status shows the recreate action')
  w.dispose(); n += 2
}
// ⑦ off 开关（enabled=false）：不代建、不唤醒、节拍全停。
{
  const clock = fakeClock()
  const se = stubEnsure()
  const { w } = makeWd({ clock, ledgerLines: [ledgerLine({ seq: 1 })], sessionEnsure: se.fn, enabled: false })
  await w.start()
  assert(se.calls.length === 0 && w.phase === 'stopped', 'project switched off = no create, no wake, no beat')
  w.dispose(); n += 1
}
// ⑧ 代建失败：显式 refused 进状态面，且节流（5 分钟内不重复敲宿主）。
{
  const clock = fakeClock()
  const se = stubEnsure({ fail: true })
  const { w } = makeWd({ clock, ledgerLines: [ledgerLine({ seq: 1 })], sessionEnsure: se.fn })
  await w.start()
  assert(se.calls.length === 1, 'failed ensure attempted once')
  const st1 = w.status()
  assert(st1.executor_session.last_action === 'refused' && st1.executor_session.session_id === null, 'refusal is explicit in status, never silent')
  await w.tickOnce()
  assert(se.calls.length === 1, 'retry throttled within the backoff window (no host hammering)')
  clock.advance(5 * 60_000 + 1)
  await w.tickOnce()
  assert(se.calls.length === 2, 'retry after the backoff window')
  w.dispose(); n += 3
}
done(n)
