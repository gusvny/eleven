// exits UT：worth-waking 过滤 / 队列未消化不重发 / 队列态不可读照发并点名 / 空 session / 投递失败 / mode 映射。
import { worthWaking, wakeMode, buildBrief, wakeExecutor, alertRecord } from '../src/host/exits.ts'
import { parseLedgerLine } from '../src/host/ledger-tail.ts'
import { ledgerLine, assert, done } from './lib.mjs'

let n = 0
const transitionRow = parseLedgerLine(ledgerLine({ ticket: 't1', stage: 'implement', stage_state: 'running' }))
const engineRow = parseLedgerLine(ledgerLine({ ticket: 't1', kind: 'engine-maintenance', stage: undefined, stage_state: undefined, __drop: ['stage', 'stage_state'] }))

{
  assert(worthWaking(transitionRow) === true, 'stage-transition row worth waking')
  assert(worthWaking(engineRow) === false, 'non-transition row NOT worth waking (no per-row wake polling)')
  assert(wakeMode('info') === 'queue' && wakeMode('warn') === 'queue', 'info/warn wake = queued (never lose the message)')
  assert(wakeMode('redline') === 'steer', 'redline urgency = steer')
  const brief = buildBrief('sandbar', [transitionRow], 'req-7')
  assert(brief.includes('t1') && brief.includes('req-7'), 'brief names the transition and self-lock target')
  n += 5
}
{
  // 队列里已有未消化简报 → 不重发。
  const io = {
    prompt: async () => ({ accepted: true }),
    queueDepth: async () => 2,
  }
  const r = await wakeExecutor(io, 'p1', 'executor-x', [transitionRow], null)
  assert(r.woke === false && r.reason.includes('未消化'), 'un-digested brief = no re-send (digestion check)')
  // 队列态不可读（null）→ 照发但点名。
  const io2 = { prompt: async () => ({ accepted: true }), queueDepth: async () => null }
  const r2 = await wakeExecutor(io2, 'p1', 'executor-x', [transitionRow], null)
  assert(r2.woke === true && r2.accepted === true && r2.reason.includes('队列态不可读'), 'unreadable queue state = send anyway with explicit note (never silently assume digested)')
  // 无值得醒的行 → 不醒（连 prompt 都不碰）。
  let touched = false
  const io3 = { prompt: async () => { touched = true; return { accepted: true } }, queueDepth: async () => 0 }
  const r3 = await wakeExecutor(io3, 'p1', 'executor-x', [engineRow], null)
  assert(r3.woke === false && touched === false, 'no wakeable rows = no delivery at all')
  // 空 session id = 显式不作为（不代建会话）。
  const r4 = await wakeExecutor(io3, 'p1', '', [transitionRow], null)
  assert(r4.woke === false && r4.reason.includes('未声明 executor_session'), 'missing executor session = explicit no-op, never auto-create')
  // 投递拒绝/异常 = accepted:false 显式。
  const io5 = { prompt: async () => ({ accepted: false, error: 'steer-unavailable' }), queueDepth: async () => 0 }
  const r5 = await wakeExecutor(io5, 'p1', 'executor-x', [transitionRow], null)
  assert(r5.accepted === false && r5.reason.includes('steer-unavailable'), 'delivery rejection surfaces the reason')
  const io6 = { prompt: async () => { throw new Error('boom') }, queueDepth: async () => 0 }
  const r6 = await wakeExecutor(io6, 'p1', 'executor-x', [transitionRow], null)
  assert(r6.accepted === false && r6.reason.includes('boom'), 'delivery exception surfaces (no silent swallow)')
  n += 6
}
{
  // alert 落账行形状：只有追加态，没有任何「已答/自动处置」位。
  const rec = alertRecord({ rule: 'stall', target: 's1', level: 'redline', title: 'T', detail: 'D' }, 'stall:s1', 123, false)
  assert(rec.at === 123 && rec.key === 'stall:s1' && rec.level === 'redline' && rec.night_muted === false, 'alert record shape complete')
  assert(!('answered' in rec) && !('auto_action' in rec), 'no answered/auto-action field (unanswered alert never becomes a decision)')
  n += 2
}
done(n)
