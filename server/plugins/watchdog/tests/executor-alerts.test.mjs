// t261001-13 UT：executor 缺席/代建被拒必须响（报警面收口）。
// 真机 261001 实证：executor 从未起来（preset 未安装，18/18 refused），alerts.jsonl
// 零相关行——拒绝是静默的。本文件钉：missing 且有活 → executor_missing；
// 代建面 refused-* → executor_session_refused（原因点名）；无活不响；冷却不重响；
// 出厂 redline 名单含 executor_missing（夜里也发声的例外名单）。
import { Watchdog, SESSION_ENSURE_RETRY_MS } from '../src/host/core.ts'
import { FACTORY_DEFAULTS } from '../src/host/config.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock, assert } from './lib.mjs'

const BASE_ALERTS = { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['stall'], keep_days: 14 }
const mkCfg = (over = {}) => ({ declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} }, config: { enabled: true, executor_session: '', stall_minutes: 15, reconcile_seconds: 5, alerts: { ...BASE_ALERTS, ...over.alerts }, ...(over.config ?? {}) } })

function makeDeps({ clock, cfgOver = {}, ledgerLines = [], boardRows = [], sessionEnsure = null, tailIo = null }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(cfgOver),
    io: { tail: tailIo ?? memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: boardRows }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: null, mtimeMs: null }),
    sessionEnsure,
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return { w, files, core }
}

// ① 出厂 redline 名单含 executor_missing（夜间 redline-only 策略下夜里也响）。
{
  assert(FACTORY_DEFAULTS.alerts.redline.includes('executor_missing'), 'executor_missing in factory redline list')
}

// ② 未声明会话 + 未注入代建面 + 项目有活（账本有行）→ executor_missing 落账；冷却内不重响。
{
  const clock = fakeClock()
  const lines = [ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' })]
  const { w, files } = makeDeps({ clock, ledgerLines: lines, boardRows: [{ id: 't1', stage_state: 'running' }] })
  await w.start()
  let alerts = w.status().alerts.filter(a => a.rule === 'executor_missing')
  assert(alerts.length === 1, 'missing executor with work raises executor_missing exactly once on startup')
  assert(alerts[0].level === 'redline', 'executor_missing is redline level')
  assert(typeof alerts[0].detail === 'string' && alerts[0].detail.length > 0, 'detail carries evidence (not empty)')
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 2, ticket: 't1', stage_state: 'done' }) + '\n'
  await w.tickOnce()
  alerts = w.status().alerts.filter(a => a.rule === 'executor_missing')
  assert(alerts.length === 1, 'cooldown dedupes: second tick does not re-record executor_missing')
  w.dispose()
}

// ③ 项目无活（无账本、无票）→ 不响（冻结遗留项目不该被报警轰炸）。
{
  const clock = fakeClock()
  const { w } = makeDeps({ clock })
  await w.start()
  assert(w.status().alerts.filter(a => a.rule === 'executor_missing').length === 0, 'no work → no executor_missing alert')
  w.dispose()
}

// ④ 代建面点名拒绝（preset 未装，refused-preset）→ executor_session_refused 落账，
//    detail 点名 preset 路径（拒绝原因必须可见，而非只有面板才能翻到的状态键）。
{
  const clock = fakeClock()
  const lines = [ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' })]
  const { w } = makeDeps({
    clock, ledgerLines: lines, boardRows: [{ id: 't1', stage_state: 'running' }],
    sessionEnsure: async () => ({
      action: 'refused-preset', sessionId: null, declaredWritten: false,
      reason: 'executor preset 未安装：sandbar-executor（缺 /home/x/.dsh/.agent-presets/sandbar-executor/preset.yml）',
      event: null,
    }),
  })
  await w.start()
  const alerts = w.status().alerts.filter(a => a.rule === 'executor_session_refused')
  assert(alerts.length === 1, 'refused-preset raises executor_session_refused exactly once')
  assert(alerts[0].detail.includes('preset 未安装'), 'refusal detail names the root cause')
  assert(alerts[0].level === 'redline', 'refusal is redline (loop silently dead otherwise)')
  // 状态面 executor_session 同步在场（面板口径不变，additive）。
  const st = w.status()
  assert(st.executor_session !== null && st.executor_session.last_action === 'refused-preset', 'status surface still reports last_action')
  w.dispose()
}

// ⑤ 会话已声明并收养（sessionKnown=true）→ 不报 missing（有会话不算缺席）。
{
  const clock = fakeClock()
  const lines = [ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' })]
  const { w } = makeDeps({
    clock, ledgerLines: lines, boardRows: [{ id: 't1', stage_state: 'running' }],
    cfgOver: { config: { executor_session: 'executor-sb' } },
    sessionEnsure: async ({ declaredSessionId }) => ({ action: 'adopt', sessionId: declaredSessionId, declaredWritten: false, reason: 'adopt', event: null }),
  })
  await w.start()
  const st = w.status()
  assert(st.alerts.filter(a => a.rule === 'executor_missing').length === 0, 'declared+adopted session → no missing alert')
  w.dispose()
}

// ⑥ 失败重试节流不吞掉响铃：拒绝后重试冷却期内仍只有一条 refused 账（去重规则独立于
//    SESSION_ENSURE_RETRY_MS——报警按 alert 冷却走，不按代建重试走）。
{
  const clock = fakeClock()
  const lines = [ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' })]
  let ensureCalls = 0
  const { w, files } = makeDeps({
    clock, ledgerLines: lines, boardRows: [{ id: 't1', stage_state: 'running' }],
    sessionEnsure: async () => { ensureCalls += 1; return { action: 'refused-preset', sessionId: null, declaredWritten: false, reason: 'preset 缺失', event: null } },
  })
  await w.start()
  assert(ensureCalls === 1, 'ensure attempted once on startup')
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 2, ticket: 't1', stage_state: 'done' }) + '\n'
  clock.advance(60_000) // < SESSION_ENSURE_RETRY_MS：代建不再试
  await w.tickOnce()
  assert(ensureCalls === 1, 'ensure retry throttled within retry window')
  assert(w.status().alerts.filter(a => a.rule === 'executor_session_refused').length === 1, 'alert stays at one within alert cooldown (no spam)')
  // 越过代建重试窗：再试一次失败；alert 冷却（默认 12h）未过 → 仍不重响。
  clock.advance(SESSION_ENSURE_RETRY_MS + 60_000)
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 3, ticket: 't1', stage_state: 'review' }) + '\n'
  await w.tickOnce()
  assert(ensureCalls === 2, 'ensure retried after retry window')
  assert(w.status().alerts.filter(a => a.rule === 'executor_session_refused').length === 1, 'still one alert record within 12h cooldown (throttled, not silent: dedupe state persists)')
  w.dispose()
}
