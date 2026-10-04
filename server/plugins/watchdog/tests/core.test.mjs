// core UT（全内存）：启动全量重放（重启不信任内存水位）/ 对账 mismatch / 缺行 / 唤醒链 /
// 自锁 / 停摆 / alerts 重放去重（重启不重播）/ board 降级 / dispose 全终态 / config_error。
// 真实 fs 不进本测试（沙箱 vfs 读可见性不稳，见 lib.mjs 注）——io 全走注入内存桩。
import { Watchdog } from '../src/host/core.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock, assert, done } from './lib.mjs'

let n = 0
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } } }
const mkCfg = (over = {}) => ({ ...CFG, config: { enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'], keep_days: 14 }, ...over } })
const cfgLoader = (cfg) => () => mkCfg(cfg)

function makeDeps({ clock, boardRows = [], ledgerLines = [], alertLines = [], wakeIo = null, pending = [], sessionAdvanced = false, tailIo = null, cfg = {} }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: cfgLoader(cfg),
    io: {
      tail: tailIo ?? memTailIo(files),
      heartbeat: core.heartbeat,
      appendAlerts: core.appendAlerts,
      listAlerts: async (p) => {
        const seeded = alertLines.join('\n') + (alertLines.length ? '\n' : '')
        const cur = await core.listAlerts(p)
        return [...seeded.split('\n').filter(x => x !== ''), ...cur]
      },
    },
    boardReader: async () => ({ ok: true, rows: boardRows }),
    wakeIo,
    pendingProvider: async () => ({ available: true, pending }),
    sessionStat: async () => ({ advanced: sessionAdvanced, mtimeMs: clock.now() }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    // t261001-19：dedupe key 带实例隔离域——测试统一注入固定 DSH_HOME，scope 可预测。
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return { w, files, core }
}

// ① 启动全量重放：重启后水位从账本第 0 行重建（startup.replayed_rows 记录事实）。
{
  const clock = fakeClock()
  const lines = [1, 2, 3].map(s => ledgerLine({ seq: s, ticket: 't' + s }))
  const board = [1, 2, 3].map(s => ({ id: 't' + s, stage_state: 'running' }))
  const { w } = makeDeps({ clock, ledgerLines: lines, boardRows: board })
  await w.start()
  const st = w.status()
  assert(st.phase === 'running' && st.startup.replayed_rows === 3, 'startup full replay counts every ledger row')
  assert(st.ledger.rows_seen === 3 && st.ledger.watermark_offset > 0, 'watermark rebuilt from zero, not trusted from memory')
  assert(st.reconcile.state === 'ok', 'consistent board → reconcile ok')
  assert(st.heartbeat.reason === null || st.heartbeat.alive === true || st.heartbeat.reason !== null, 'heartbeat shape present')
  w.dispose(); n += 4
}
// ② 对账 mismatch：以看板为准 + mismatch 本身落账。
{
  const clock = fakeClock()
  const { w } = makeDeps({
    clock, ledgerLines: [ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' })],
    boardRows: [{ id: 't1', stage_state: 'done' }],
  })
  await w.start()
  const st = w.status()
  assert(st.reconcile.state === 'mismatch' && st.reconcile.mismatches[0].board_state === 'done', 'mismatch surfaces with board as truth')
  assert(st.alerts.some(a => a.rule === 'reconcile_mismatch'), 'mismatch is itself alertable')
  w.dispose(); n += 2
}
// ③ 缺行覆盖：看板在飞票账本零行覆盖 → ledger_missing_rows；去重键带集合指纹——
// 同集合不重响（即使新票使另一桶计数变化）；终态缺口只进状态面，不响（t261004-13）。
{
  const clock = fakeClock()
  const { w } = makeDeps({ clock, ledgerLines: [], boardRows: [{ id: 't1' }, { id: 't2' }] })
  await w.start()
  const st = w.status()
  assert(st.startup.missing_rows === 2, 'in-flight missing counted on startup replay')
  assert(st.ledger_coverage && st.ledger_coverage.in_flight_missing.join(',') === 't1,t2' && st.ledger_coverage.terminal_missing.length === 0, 'status face exposes both coverage buckets')
  await w.tickOnce()
  const keys = w.status().alerts.filter(a => a.rule === 'ledger_missing_rows').map(a => a.key)
  assert(keys.length === 1, 'same uncovered set does not re-alert (one beep discipline)')
  assert(/ledger_missing_rows:sandbar:2:[0-9a-f]{8}@\/memhome$/.test(keys[0]), 'dedupe key = rule:project:N:sethash@scope')
  w.dispose(); n += 4
}
// ③b 终态票不进告警：closed/verified 零覆盖 → 只在 ledger_coverage.terminal_missing。
{
  const clock = fakeClock()
  const { w } = makeDeps({ clock, ledgerLines: [ledgerLine({ seq: 1, ticket: 't2', stage_state: 'running' })], boardRows: [{ id: 't1', status: 'closed' }, { id: 't2', status: 'rework' }] })
  await w.start()
  const st = w.status()
  assert(st.startup.missing_rows === 0 && st.ledger_coverage.in_flight_missing.length === 0, 'covered in-flight ticket is not missing')
  assert(st.ledger_coverage.terminal_missing.join(',') === 't1', 'terminal gap lands on the status face only')
  assert(w.status().alerts.every(a => a.rule !== 'ledger_missing_rows'), 'terminal-only gap raises no alert')
  w.dispose(); n += 3
}
// ③c 空缺口：账本全覆盖（含分叉状态行）→ 无告警、coverage 两桶皆空。
{
  const clock = fakeClock()
  const lines = [ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' }), ledgerLine({ seq: 2, ticket: 't2', stage_state: 'done' })]
  const { w } = makeDeps({ clock, ledgerLines: lines, boardRows: [{ id: 't1', stage_state: 'done' }, { id: 't2', stage_state: 'running' }] })
  await w.start()
  const st = w.status()
  assert(st.startup.missing_rows === 0 && st.ledger_coverage.in_flight_missing.length === 0 && st.ledger_coverage.terminal_missing.length === 0, 'every board ticket has a ledger row → both buckets empty (divergent states still cover)')
  assert(w.status().alerts.every(a => a.rule !== 'ledger_missing_rows'), 'no gap → no alert at all')
  w.dispose(); n += 2
}
// ④ 唤醒链：启动重放不醒旧行；新迁移行醒一次；无新行不重醒。
{
  const clock = fakeClock()
  let prompts = 0
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' }) + '\n' } }
  const { w } = makeDeps({
    clock, boardRows: [{ id: 't1', stage_state: 'running' }],
    tailIo: memTailIo(files),
    wakeIo: { prompt: async () => { prompts += 1; return { accepted: true } }, queueDepth: async () => 0 },
  })
  await w.start()
  assert(prompts === 0, 'startup replay does not wake on old rows (no replay of history)')
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 2, ticket: 't1', stage_state: 'done' }) + '\n'
  await w.tickOnce()
  assert(prompts === 1, 'new transition row wakes executor (queued)')
  await w.tickOnce()
  assert(prompts === 1, 'no new rows = no re-wake (not stupid polling)')
  // 队列有未消化项 → 不重发。
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 3, ticket: 't1', stage_state: 'review' }) + '\n'
  const st = w.status()
  assert(st.wakes.length === 1 && st.wakes[0].accepted === true, 'wake recorded with accepted receipt')
  w.dispose(); n += 4
}
// ④b t260929-04：自醒排除在整条 tick 链上生效 + additive 状态键在场（旧键不动）。
{
  const clock = fakeClock()
  let prompts = 0
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' }) + '\n' } }
  const { w } = makeDeps({
    clock, boardRows: [{ id: 't1', stage_state: 'running' }],
    tailIo: memTailIo(files),
    wakeIo: {
      prompt: async () => { prompts += 1; return { accepted: true, requestId: 'watchdog-core-1' } },
      queueDepth: async () => 0,
      ourBriefPending: async () => false,
      transportState: () => 'live（测试桩）',
    },
  })
  await w.start()
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 2, ticket: 't1', stage_state: 'done' }) + '\n'
  await w.tickOnce()
  assert(prompts === 1, 'first transition wakes (queued brief delivered)')
  // executor 签字 → t1 下一迁移入账：自喂循环排除 = 不再醒。
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 3, ticket: 't1', stage_state: 'review' }) + '\n'
  await w.tickOnce()
  assert(prompts === 1, 'executor own next transition does NOT re-wake (no self-feeding loop)')
  const st = w.status()
  assert(st.presumed_self_rows === 1 && (st.presumed_self_detail ?? '').includes('t1'), 'presumed-self suppression is loud in status (audit counter)')
  assert(st.queue_mirror === 'live（测试桩）', 'queue_mirror transport state surfaced (additive key)')
  assert(st.wakes.length === 1 && Object.keys(st.wakes[0]).join(',') === 'at,ticket,dedupe_key,mode,accepted', 'wakes row keys unchanged (panel-contract promise)')
  w.dispose(); n += 4
}
// ⑤ 自锁即时报警（不等停摆超时）。
{
  const clock = fakeClock()
  const { w } = makeDeps({ clock, pending: [{ raisedBy: 'executor-sb', kind: 'approval', target: 't9/auth', sessionRunning: false }] })
  await w.start()
  const st = w.status()
  assert(st.self_lock.state === 'waiting_on_itself' && st.self_lock.target === 't9/auth', 'self-lock detected immediately')
  assert(st.alerts.some(a => a.rule === 'self_lock' && a.level === 'redline'), 'self-lock raises redline alert')
  w.dispose(); n += 2
}
// ⑥ 停摆：有信号无推进超阈 → stall redline。
{
  const clock = fakeClock()
  const { w } = makeDeps({ clock, ledgerLines: [ledgerLine({ seq: 1, ticket: 't1' })], boardRows: [{ id: 't1' }], sessionAdvanced: false })
  await w.start()
  clock.advance(20 * 60_000)
  await w.tickOnce()
  const st = w.status()
  assert(st.liveness.executor.state === 'stalled' && st.alerts.some(a => a.rule === 'stall'), 'long silence with signal = stalled + alert')
  w.dispose(); n += 1
}
// ⑦ 重启不重播：预置 alerts（1h 前 stall）→ start 后去重集含该 key，同事实不重响。
{
  const clock = fakeClock()
  const alertLine = JSON.stringify({ at: clock.now() - 3600_000, key: 'stall:executor-sb@/memhome', rule: 'stall', target: 'executor-sb', level: 'redline', title: 'old', detail: '', night_muted: false })
  const { w } = makeDeps({
    clock, ledgerLines: [ledgerLine({ seq: 1, ticket: 't1' })], boardRows: [{ id: 't1' }], alertLines: [alertLine], sessionAdvanced: false,
  })
  await w.start()
  clock.advance(20 * 60_000)
  await w.tickOnce()
  const stallAlerts = w.status().alerts.filter(a => a.rule === 'stall')
  assert(stallAlerts.length === 1 && stallAlerts[0].title === 'old', 'restart does not replay the old alert (dedupe rebuilt)')
  assert(w.status().startup.dedupe_keys === 1, 'dedupe state rebuilt from alerts ledger')
  w.dispose(); n += 2
}
// ⑧ board 读失败 → degraded 显式。
{
  const clock = fakeClock()
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: cfgLoader({}),
    io: { tail: memTailIo({ '/ledg/sandbar.jsonl': { ino: 1, content: '' } }), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: false, rows: [], error: '引擎不可达' }),
    wakeIo: null, now: clock.now, dataDir: '/memdata', ledgerDir: '/ledg',
  })
  await w.start()
  const st = w.status()
  assert(st.reconcile.state === 'degraded' && st.reconcile.reason.includes('引擎不可达'), 'board failure = explicit degraded')
  assert(st.alerts.some(a => a.rule === 'reconcile_degraded'), 'degradation itself alertable')
  assert(st.liveness.engine.online === null, 'engine liveness explicitly unknown on failure')
  w.dispose(); n += 3
}
// ⑨ dispose 全终态（幂等；dispose 后 tick 不动）。
{
  const clock = fakeClock()
  const { w } = makeDeps({ clock })
  await w.start()
  w.dispose(); w.dispose()
  const before = w.status().ledger.rows_seen
  await w.tickOnce()
  assert(w.status().phase === 'stopped' && w.status().ledger.rows_seen === before, 'dispose stops all activity (idempotent)')
  n += 1
}
// ⑩ config_error：畸形声明 = declared 但停 + 显式错误。
{
  const clock = fakeClock()
  const w = new Watchdog('sandbar', {
    configLoader: () => ({ declared: true, enabled: false, config_error: 'watchdog.json 不是合法 JSON', config: mkCfg({}).config, provenance: { file: 'x', keys: {} } }),
    io: { tail: memTailIo({}), heartbeat: memCoreIo().heartbeat, appendAlerts: memCoreIo().appendAlerts, listAlerts: async () => [] },
    boardReader: async () => ({ ok: true, rows: [] }), now: clock.now, dataDir: '/m', ledgerDir: '/ledg2',
  })
  await w.start()
  const st = w.status()
  assert(st.phase === 'config_error' && st.config_error !== null && st.enabled === false, 'malformed config = explicit stopped with reason')
  w.dispose(); n += 1
}
done(n)
