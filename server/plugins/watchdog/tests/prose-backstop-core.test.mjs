// prose-backstop core orchestration UT (t261004-08, all in-memory): row filing / alerting /
// journal idempotency / fail-loud unknowns / the N1 co-fire alert set ({prose_ask_filed×1,
// self_lock×1}) / restart journal replay.
import { Watchdog } from '../src/host/core.ts'
import { proseKey } from '../src/host/prose-backstop.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock, assert, done } from './lib.mjs'

let n = 0
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
const mkCfg = (over = {}) => ({ ...CFG, config: {
  enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5,
  waiting_minutes: 1, prose_backstop: { enabled: true, idle_minutes: 10 },
  alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['self_lock'], keep_days: 14 },
  ...over,
} })

function makeDeps({ clock, pending: pendingArg = () => [], recent, waitingRows: waitingRowsArg = () => [], journalLines = [], appendFail = null, readWaitingFail = null, cfg = {} }) {
  const core = memCoreIo()
  const pending = typeof pendingArg === 'function' ? pendingArg : () => pendingArg
  const appends = []
  const journalAppends = []
  const proseIo = {
    async readWaiting() {
      if (readWaitingFail !== null) return { ok: false, reason: readWaitingFail }
      const waitingRows = typeof waitingRowsArg === 'function' ? waitingRowsArg : () => waitingRowsArg
      return { ok: true, rows: waitingRows() }
    },
    async append(args) {
      if (appendFail !== null) return { ok: false, reason: appendFail }
      const id = `req-filed-${appends.length + 1}`
      appends.push({ ...args, id })
      return { ok: true, requestId: id }
    },
    async readJournal() { return [...journalLines, ...journalAppends] },
    async appendJournal(line) { journalAppends.push(line) },
  }
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(cfg),
    io: { tail: memTailIo({}), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending: pending() }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now() - 15 * 60_000 }),
    waitingRunningLookup: () => false,
    recentText: recent(),
    proseBackstopIo: proseIo,
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return { w, appends, journalAppends }
}
const MARKER_TEXT = '做了 A 和 B。仍等你一句话的：worker 重启 / 要不要开批量清红票'

// ① 补落：空闲 15min + 标记命中 + 无覆盖 → 恰好一行（引句点名会话、归属该会话）+ 恰好一响。
{
  const clock = fakeClock()
  const { w, appends } = makeDeps({ clock, recent: () => async () => ({ ok: true, text: MARKER_TEXT }) })
  await w.start()
  const st = w.status()
  assert(st.prose_backstop.state === 'filed' && st.prose_backstop.last_request_id === 'req-filed-1', 'backstop files once with a request id')
  assert(appends.length === 1 && appends[0].sessionId === 'executor-sb', 'row attributed to the executor session')
  assert(appends[0].sentence.includes('仍等你一句话'), 'detail quotes the sentence it came from')
  const alerts = st.alerts.filter(a => a.rule === 'prose_ask_filed')
  assert(alerts.length === 1 && alerts[0].target === 'req-filed-1', 'exactly one prose_ask_filed alert naming the row')
  assert(st.prose_backstop.reason.includes('quote:'), 'status reason quotes the source sentence')
  w.dispose(); n += 5
}
// ② 幂等：第二拍同句不落第二行、不响第二次（journal + 覆盖双层）。
{
  const clock = fakeClock()
  const filedRows = []
  const { w, appends } = makeDeps({
    clock,
    recent: () => async () => ({ ok: true, text: MARKER_TEXT }),
    waitingRows: () => filedRows,
  })
  await w.start()
  filedRows.push({ id: 'req-filed-1', raisedBy: 'executor-sb' })
  await w.tickOnce()
  await w.tickOnce()
  assert(appends.length === 1, 'same sentence does not file a second row on later cycles')
  assert(w.status().alerts.filter(a => a.rule === 'prose_ask_filed').length === 1, 'no duplicate prose_ask_filed alert')
  assert(w.status().prose_backstop.state === 'covered', 'second cycle reads covered, not silence')
  w.dispose(); n += 3
}
// ③ fail loud：宿主面不可读 → unknown + 一条 prose_backstop_unknown，第二拍不重响。
{
  const clock = fakeClock()
  const { w, appends } = makeDeps({ clock, recent: () => async () => ({ ok: false, reason: '宿主历史面不可达（测试桩）' }) })
  await w.start()
  const st = w.status()
  assert(st.prose_backstop.state === 'unknown' && appends.length === 0, 'unreadable transcript → unknown, nothing filed')
  assert(st.alerts.filter(a => a.rule === 'prose_backstop_unknown').length === 1, 'unknown raises exactly one alert, never "nothing to report"')
  await w.tickOnce()
  assert(w.status().alerts.filter(a => a.rule === 'prose_backstop_unknown').length === 1, 'second cycle produces no duplicate unknown alert')
  w.dispose(); n += 3
}
// ④ 账读失败 / 落行失败 → unknown + alert，绝不盲落。
{
  const clock = fakeClock()
  const a = makeDeps({ clock, recent: () => async () => ({ ok: true, text: MARKER_TEXT }), readWaitingFail: '账被独占（测试桩）' })
  await a.w.start()
  assert(a.w.status().prose_backstop.state === 'unknown' && a.appends.length === 0, 'ledger read failure → unknown, nothing filed')
  a.w.dispose()
  const b = makeDeps({ clock, recent: () => async () => ({ ok: true, text: MARKER_TEXT }), appendFail: '盘满（测试桩）' })
  await b.w.start()
  assert(b.w.status().prose_backstop.state === 'unknown' && b.w.status().alerts.some(x => x.rule === 'prose_backstop_unknown'), 'append failure → unknown + alert')
  b.w.dispose()
  n += 2
}
// ⑤ N1 共响 alert 集：补落引发的等待全程 = {prose_ask_filed×1, self_lock×1}，别无其它。
{
  const clock = fakeClock()
  let pendingRows = []
  const filedRows = []
  const { w, appends } = makeDeps({ clock, pending: () => pendingRows, waitingRows: () => filedRows, recent: () => async () => ({ ok: true, text: MARKER_TEXT }) })
  await w.start()
  assert(appends.length === 1, 'filing happened')
  // 补落行进入请求账（watchdog 下一拍经 pendingProvider/readWaiting 读到它），时钟拨过升级阈值。
  filedRows.push({ id: 'req-filed-1', raisedBy: 'executor-sb' })
  pendingRows = [{ raisedBy: 'executor-sb', kind: 'question', target: 'req-filed-1', sessionRunning: false, raisedAt: clock.now() }]
  clock.advance(2 * 60_000)
  await w.tickOnce()
  const st = w.status()
  const byRule = {}
  for (const a of st.alerts) byRule[a.rule] = (byRule[a.rule] ?? 0) + 1
  assert(byRule['prose_ask_filed'] === 1 && byRule['self_lock'] === 1, `co-fire: prose_ask_filed×1 and self_lock×1 regardless of unrelated rules like stall (got ${JSON.stringify(byRule)})`)
  assert(byRule['prose_ask_filed'] === 1 && byRule['self_lock'] === 1 && (byRule['prose_backstop_unknown'] ?? 0) === 0, 'no duplicates and no unknown noise in the backstop-originated wait')
  assert(st.self_lock.state === 'waiting_on_itself' && st.self_lock.target === 'req-filed-1', 'escalated self_lock names the ask (per-ask dedupe target)')
  assert(st.waiting_on_host.state === 'waiting' && st.waiting_on_host.asks.length === 1, 'waiting_on_host face reads waiting with the ask projected')
  w.dispose(); n += 3
}
// ⑥ 重启 journal 重放 + 验收用例：已答复行 + 同句再现 = 恰好一行**新**问。
{
  const clock = fakeClock()
  const oldKey = proseKey('executor-sb', '仍等你一句话的：worker 重启')
  const journalLines = [JSON.stringify({ key: oldKey, request_id: 'req-old', at: 1 })]
  // 第一棒：行 req-old 已被答复（waitingRows 空）→ 同句再现场景补落新行。
  const first = makeDeps({ clock, recent: () => async () => ({ ok: true, text: MARKER_TEXT }), journalLines })
  await first.w.start()
  assert(first.appends.length === 1 && first.appends[0].id === 'req-filed-1', 'answered prior filing + same sentence → one NEW row')
  // 第二棒（重启）：journal 里已有两问的记录，同句且无未答复行 → 再答再现才落；仍只一行。
  const second = makeDeps({ clock, recent: () => async () => ({ ok: true, text: MARKER_TEXT }), journalLines: [...journalLines, JSON.stringify({ key: oldKey, request_id: 'req-filed-1', at: 2 })] })
  await second.w.start()
  assert(second.w.status().prose_backstop.state === 'filed', 'restarted watchdog keeps filing per ask instance (journal replay does not mute forever)')
  second.w.dispose(); first.w.dispose(); n += 2
}
// ⑦ 未过阈的等：不响铃，状态面可见（self_lock=waiting + waiting_on_host=waiting）。
{
  const clock = fakeClock()
  const { w } = makeDeps({
    clock, recent: () => async () => ({ ok: true, text: MARKER_TEXT }),
    pending: () => [{ raisedBy: 'executor-sb', kind: 'question', target: 'req-x', sessionRunning: false, raisedAt: clock.now() }],
  })
  await w.start()
  const st = w.status()
  assert(st.self_lock.state === 'waiting' && st.alerts.filter(a => a.rule === 'self_lock').length === 0, 'below-threshold wait is status-only, no alert')
  assert(st.waiting_on_host.state === 'waiting', 'waiting_on_host face still shows the wait')
  w.dispose(); n += 2
}
done(n)
