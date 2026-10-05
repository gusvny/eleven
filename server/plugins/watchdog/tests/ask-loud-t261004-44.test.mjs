/**
 * ask-loud-t261004-44.test.mjs —— 守望者双红线（t261004-44，KI-196/KI-197）：
 *   ① 纯核 judgeAskMirror：时限内 watch / 超时 raise（点名会话与 ask 面）/ 行到 forget /
 *     归属缺席不判；raisedAt 缺席=首见起算（年龄下界，绝不因缺时间戳永不响）；
 *   ② 纯核 collectDeliverRefusals：拒收行收集、无归属行计数（具名跳过）、非本类行忽略；
 *   ③ 真核集成（Watchdog + 注入 io）：超时挂起问 → ask_unmirrored 红线（会话+面点名）；
 *     行落进账 → 清（clear stays clear）；deliver_refused 行 → 红线且拒收文案活进告警；
 *     畸形账行 → 不炸、running 保持、跳过具名（review C4 的账行侧）。
 */
import { assert, done } from './lib.mjs'
import { judgeAskMirror, collectDeliverRefusals } from '../src/host/ask-loud.ts'
import { Watchdog } from '../src/host/core.ts'
import { memCoreIo, memTailIo, ledgerLine, fakeClock } from './lib.mjs'

let n = 0
const NOW = 1_700_000_000_000

// ── ① 纯核 judgeAskMirror ──
{
  const base = { ledgerRows: [], deadlineMs: 120_000, nowMs: NOW }
  let j = judgeAskMirror({ ...base, pending: { raisedBy: 's1', kind: 'question' } })
  assert(j.action === 'watch' && j.sinceMs === NOW, 'first sighting = watch from now (no fake age)')

  j = judgeAskMirror({ ...base, pending: { raisedBy: 's1', kind: 'question' }, firstSeenMs: NOW - 121_000 })
  assert(j.action === 'raise' && j.sessionId === 's1' && /ask_user_question/.test(j.detail) && j.detail.includes('s1'),
    'past deadline = raise naming the session and the ask face')

  j = judgeAskMirror({ ...base, pending: { raisedBy: 's1', kind: 'question', raisedAt: NOW - 500_000 }, firstSeenMs: NOW - 1_000 })
  assert(j.action === 'raise', 'row raisedAt older than firstSeen pulls the age down (early evidence wins the min)')

  j = judgeAskMirror({ ...base, pending: { raisedBy: 's2', kind: 'question' }, ledgerRows: [JSON.parse(ledgerLine({ kind: 'question', raised_by: 's2' }))] })
  assert(j.action === 'forget', 'mirrored question row clears the watch (clear stays clear)')

  j = judgeAskMirror({ ...base, pending: { kind: 'question' } })
  assert(j.action === 'none', 'unattributed pending ask = not judged (never fakes red or clear)')

  n++
}

// ── ② 纯核 collectDeliverRefusals ──
{
  const { refusals, malformed } = collectDeliverRefusals([
    { kind: 'deliver_refused', session: 's9', error: 'deliver: workflow class X is not registered (registered: Y)', at: NOW },
    { kind: 'question', raised_by: 's1' },
    { kind: 'deliver_refused', error: 'no session on this row' },
    'garbage-string',
    null,
  ])
  assert(refusals.length === 1 && refusals[0].sessionId === 's9'
    && refusals[0].detail.includes('not registered'),
    'the deliver_refused row is collected with its refusal text in the detail')
  assert(refusals[0].detail.includes('deliver') && refusals[0].detail.includes('s9'),
    'the refusal detail names the session and the deliver face')
  assert(malformed === 1, 'a deliver_refused row without attribution is counted (named skip), other kinds ignored')
  n++
}

// ── ③ 真核集成 ──
const BASE_CFG = {
  declared: true, enabled: true, config_error: null,
  provenance: { file: 'mem', keys: {} },
  config: {
    enabled: true, executor_session: 'executor-x', stall_minutes: 15, reconcile_seconds: 5,
    ask_mirror_deadline_s: 120,
    alerts: { enabled: true, sound: false, desktop: false,
      night: { start: '23:00', end: '07:30', policy: 'redline-only' },
      redline: ['ask_unmirrored', 'deliver_refused'], keep_days: 14 },
  },
}
function boot({ clock, pending = [], ledgerLines = [] }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  return new Watchdog('sandbar', {
    configLoader: () => JSON.parse(JSON.stringify(BASE_CFG)),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: true }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
}
const hasAlert = (st, needle) => (st.alerts ?? []).some((a) => needle.every((s) => JSON.stringify(a).includes(s)))

{
  // 超时挂起问 → 红线，点名会话 + ask 面
  const clock = fakeClock()
  const w = boot({ clock, pending: [{ raisedBy: 'session-a', kind: 'question', target: 'req-1', sessionRunning: true }] })
  await w.start()
  clock.advance(121_000)
  await w.tickOnce()
  const st = w.status()
  assert(hasAlert(st, ['session-a', 'ask_user_question']) && (st.alerts ?? []).some((a) => a.level === 'redline'),
    'watchdog: unmirrored pending ask past deadline = redline naming session + ask face')
  w.dispose()
  n++
}
{
  // 行已落账 → 清（clear stays clear）
  const clock = fakeClock()
  const w = boot({ clock, pending: [{ raisedBy: 'session-b', kind: 'question', target: 'req-2', sessionRunning: true }],
    ledgerLines: [ledgerLine({ kind: 'question', raised_by: 'session-b', session: 'session-b' })] })
  await w.start()
  clock.advance(200_000)
  await w.tickOnce()
  const st = w.status()
  assert(!hasAlert(st, ['session-b']), 'watchdog: mirrored-in-time ask stays clear (no alert noise)')
  w.dispose()
  n++
}
{
  // deliver_refused 行 → 红线，拒收文案活进告警
  const clock = fakeClock()
  const refusal = ledgerLine({ kind: 'deliver_refused', session: 'session-c', ticket: 't',
    error: 'deliver: workflow class ExecutorDeliveryWorkflow is not registered on the running worker (registered: A, B)' })
  const w = boot({ clock, ledgerLines: [refusal] })
  await w.start()
  await w.tickOnce()
  const st = w.status()
  assert(hasAlert(st, ['session-c', 'deliver', 'ExecutorDeliveryWorkflow']),
    'watchdog: deliver_refused ledger row = redline carrying the refusal text (session + face + detail)')
  w.dispose()
  n++
}
{
  // 畸形账行（review C4）：不炸、running 保持、跳过具名
  const clock = fakeClock()
  const w = boot({ clock, ledgerLines: ['{{{not json at all'] })
  await w.start()
  await w.tickOnce()
  const st = w.status()
  assert(st.phase === 'running', 'watchdog: malformed ledger row does not crash the watchdog')
  assert((st.ledger?.malformed_rows ?? 0) > 0 || (st.last_error ?? '') !== '',
    'watchdog: malformed row skip is named (malformed counter or lastError), never silent')
  w.dispose()
  n++
}

done(n)
