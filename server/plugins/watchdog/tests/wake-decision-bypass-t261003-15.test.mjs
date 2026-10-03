// t261003-15 UT：决策态唤醒旁路（blocked / refused / awaiting-human 无条件醒）+ 逐拍
// 唤醒裁决可观测（last_wake_verdict）。漂移锁：从引擎源码抽 state 字面量逐词分类，
// 引擎词表一变本测试即红——决策集合不许与账本词表悄悄漂移。
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DECISION_STAGE_STATES, isDecisionRow, wakeExecutor, freshWakeMemory } from '../src/host/exits.ts'
import { Watchdog } from '../src/host/core.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock, assert, done } from './lib.mjs'

let n = 0
const repo = join(dirname(fileURLToPath(import.meta.url)), '../../../..')

// ledgerLine 生成 JSON 串；parse 回引擎同款行形状（ledger-tail.parseLedgerLine）。
import { parseLedgerLine } from '../src/host/ledger-tail.ts'
function lrow(ticket, stage, state, seq = 1) {
  const over = { ticket, stage, seq, idem: `${ticket}|${stage}|${state}|${seq}` }
  if (state !== undefined) over.stage_state = state
  else over.__drop = ['stage_state']
  return parseLedgerLine(ledgerLine(over))
}

function stubIo({ ours = undefined, depth = 0, accepted = true } = {}) {
  const prompts = []
  return {
    prompts,
    prompt: async (sid, text, mode) => { prompts.push({ sid, text, mode }); return { accepted, requestId: `wd-${prompts.length}` } },
    queueDepth: async () => depth,
    ourBriefPending: ours === undefined ? undefined : async () => ours,
  }
}

// —— 纯判定面：isDecisionRow ——
assert([...DECISION_STAGE_STATES].sort().join(',') === 'awaiting-human,blocked,refused', 'decision set is exactly {blocked, refused, awaiting-human}')
for (const s of ['blocked', 'refused', 'awaiting-human']) assert(isDecisionRow(lrow('t1', 'implement', s)) === true, `decision row recognized: ${s}`)
assert(isDecisionRow(lrow('t1', 'implement', 'running')) === false, 'routine state is not a decision row')
assert(isDecisionRow(lrow('t1', 'implement', 'done')) === false, 'done is not a decision row')
assert(isDecisionRow(lrow('t1', 'implement', undefined)) === false, 'malformed input: row without stage_state is NOT a decision row (fails closed, no bypass)')
assert(isDecisionRow(lrow('t1', 'implement', 'BLOCKED ')) === false, 'malformed input: padded/cased state does not bypass (exact vocabulary match only)')
n += 8

// —— 场景 (a)：简报已点名过的票进入决策态 → 必须醒（旁路 ① idem 与 ② 疑似自）——
{
  const mem = freshWakeMemory()
  const io1 = stubIo()
  await wakeExecutor(io1, 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', mem) // 简报点名 t1
  for (const s of ['blocked', 'refused', 'awaiting-human']) {
    const io2 = stubIo({ ours: false })
    const m2 = freshWakeMemory()
    await wakeExecutor(io2, 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', m2) // 先点名
    const r = await wakeExecutor(io2, 'p1', 'exec', [lrow('t1', 'arbitrate', s)], null, 'info', m2)
    assert(r.woke === true && io2.prompts.length === 2, `(a) briefed ticket entering ${s} WAKES (idem + presumed-self bypassed)`)
    assert(io2.prompts[1].text.includes('t1'), `(a) ${s} brief names the ticket`)
  }
  // 同票同批：先 idem 命中的 (implement|running) 重放 + 决策行同窗——决策行把整批带醒。
  const io3 = stubIo({ ours: false })
  const m3 = freshWakeMemory()
  await wakeExecutor(io3, 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', m3)
  const r3 = await wakeExecutor(io3, 'p1', 'exec', [lrow('t1', 'implement', 'running', 2), lrow('t1', 'implement', 'blocked')], null, 'info', m3)
  assert(r3.woke === true, '(a) decision row in a mixed window carries the whole batch through')
  n += 5
}

// —— 场景 (b)：简报后的第一个普通迁移仍被压（t260929-04 不回归）——
{
  const mem = freshWakeMemory()
  const io1 = stubIo()
  await wakeExecutor(io1, 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', mem)
  const io2 = stubIo({ ours: false })
  const r = await wakeExecutor(io2, 'p1', 'exec', [lrow('t1', 'review', 'running')], null, 'info', mem)
  assert(r.woke === false && io2.prompts.length === 0 && r.presumedSelf === 1, '(b) routine first transition after a brief stays suppressed')
  // 有界性不破：决策行醒过之后，下一拍普通迁移照样受 ② 约束（循环仍有界）。
  const io3 = stubIo({ ours: false })
  const m3 = freshWakeMemory()
  await wakeExecutor(io3, 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', m3)
  await wakeExecutor(io3, 'p1', 'exec', [lrow('t1', 'implement', 'blocked')], null, 'info', m3) // 决策醒
  const r2 = await wakeExecutor(io3, 'p1', 'exec', [lrow('t1', 'arbitrate', 'running')], null, 'info', m3)
  assert(r2.woke === false && r2.presumedSelf >= 1, 'after a decision wake the next routine transition is suppressed again (loop still bounded)')
  n += 2
}

// —— 规则③不旁路：上一份简报未消化时，决策态也只显式点名不重发 ——
{
  const mem = freshWakeMemory()
  await wakeExecutor(stubIo(), 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', mem)
  const io2 = stubIo({ ours: true }) // 我们的简报还在队列里 = 未消化
  const r = await wakeExecutor(io2, 'p1', 'exec', [lrow('t1', 'implement', 'blocked')], null, 'info', mem)
  assert(r.woke === false && io2.prompts.length === 0, 'rule 3 still applies to decision rows: unconsumed brief blocks the re-send')
  assert((r.reason ?? '').includes('未消化'), 'suppression reason names the unconsumed brief (verdict answers why not woken)')
  n += 2
}

// —— 红线拍旁路（stall / self_lock 拍 level='redline'）——
{
  const mem = freshWakeMemory()
  await wakeExecutor(stubIo(), 'p1', 'exec', [lrow('t1', 'implement', 'running')], null, 'info', mem)
  const io2 = stubIo({ ours: false })
  const r = await wakeExecutor(io2, 'p1', 'exec', [lrow('t1', 'review', 'running')], null, 'redline', mem)
  assert(r.woke === true && io2.prompts.length === 1, 'redline cycle (stall/self_lock) bypasses the self-feed filters')
  n += 1
}

// —— 零发现周期行不回归（t261003-04）+ considered 计数 ——
{
  const io = { async prompt() { return { accepted: true, requestId: 'r1' } }, async queueDepth() { return 0 } }
  const zero = lrow('t1', 'scan', 'done')
  zero.reason = 'Scan report: 0 tickets, 0 pending (stuck-suspect 0 / needs-supply 0 / signable 0)'
  const r0 = await wakeExecutor(io, 'p', 's', [zero], null, 'info', freshWakeMemory())
  assert(r0.woke === false && r0.considered === 0, 'zero-finding row filtered before the sieve; considered=0 matches the no-wake verdict')
  const blocked = lrow('t2', 'implement', 'blocked')
  const r1 = await wakeExecutor(io, 'p', 's', [zero, blocked], null, 'info', freshWakeMemory())
  assert(r1.woke === true && r1.considered === 1, 'decision row wakes in a window that also carried a zero-finding row (considered counts sieve survivors)')
  n += 2
}

// —— 漂移锁：引擎词表逐词分类，未知词即红 ——
{
  const engineSrc = readFileSync(join(repo, 'server/engine/base.py'), 'utf8') + '\n' + readFileSync(join(repo, 'server/engine/dev_lane.py'), 'utf8')
  const literals = new Set()
  for (const m of engineSrc.matchAll(/_mark\((?:.*?,\s*)?"([a-z_-]+)"/g)) literals.add(m[1])
  for (const m of engineSrc.matchAll(/_mark\((?:.*?,\s*)?'([a-z_-]+)'/g)) literals.add(m[1])
  for (const m of engineSrc.matchAll(/_ledger_note\(\s*["']([a-z_-]+)["']\s*,\s*["']([a-z_-]+)["']/g)) literals.add(m[2])
  assert(literals.size >= 8, `drift lock: extracted ${literals.size} engine state literals (regex still finds them)`)
  // 显式分类表：decision（必须与 DECISION_STAGE_STATES 一致）+ routine（本测试文档化决定）。
  const DECISION = new Set(['blocked', 'refused', 'awaiting-human'])
  const ROUTINE = new Set(['running', 'awaiting', 'done', 'rework', 'closed', 'ready', 'paused', 'resumed', 'paused-waiting'])
  const unknown = [...literals].filter(s => !DECISION.has(s) && !ROUTINE.has(s))
  assert(unknown.length === 0, `drift lock: every engine state literal is classified (unknown: ${unknown.join(',') || 'none'})`)
  for (const d of DECISION) assert(DECISION_STAGE_STATES.has(d), `drift lock: decision state ${d} present in the watchdog set`)
  for (const d of DECISION_STAGE_STATES) assert(DECISION.has(d), `drift lock: watchdog decision state ${d} is a deliberate engine-classified entry`)
  // ticket.py 枚举里的每个 stage_state 也必须被分类（文档词表不漂）。
  const ticketSrc = readFileSync(join(repo, 'server/tools/ticket.py'), 'utf8')
  const enumM = ticketSrc.match(/'stage_state':\s*\{'type':\s*'string',\s*'enum':\s*\[([^\]]+)\]/)
  assert(enumM !== null, 'drift lock: ticket.py stage_state enum found')
  const enumVals = [...enumM[1].matchAll(/'([a-z_-]+)'/g)].map(m => m[1])
  const unclassified = enumVals.filter(s => !DECISION.has(s) && !ROUTINE.has(s))
  assert(unclassified.length === 0, `drift lock: ticket.py enum fully classified (unclassified: ${unclassified.join(',') || 'none'})`)
  n += 6
}

// —— core 状态面：last_wake_verdict 每条拍路径都显式在场 ——
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } } }
function makeDeps({ clock, ledgerLines = [], boardRows = [], wakeIo = null }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.map(l => l + '\n').join('') } }
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => ({ ...CFG, config: { enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['self_lock', 'stall'], keep_days: 14 } } }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: boardRows }),
    wakeIo,
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now() }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return { w, files }
}

{
  // 启动拍（重放消费完存量行）→ 无新行拍 verdict；随后普通迁移拍压制拍；
  // 再决策态拍：简报后的 blocked 行 → 立刻再醒（端到端穿过 tick 链）。
  const clock = fakeClock()
  const io = stubIo()
  const { w, files } = makeDeps({ clock, ledgerLines: [ledgerLine({ seq: 1, ticket: 't1', stage: 'implement', stage_state: 'running' })], boardRows: [{ id: 't1', stage_state: 'running' }], wakeIo: io })
  await w.start()
  let st = w.status()
  assert(st.last_wake_verdict !== null && st.last_wake_verdict.woke === false && st.last_wake_verdict.reason.length > 0, 'status face: startup replay tick records an explicit no-wake verdict')
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 2, ticket: 't1', stage: 'review', stage_state: 'running', idem: 's|t1|2' }) + '\n'
  await w.tickOnce()
  st = w.status()
  assert(st.last_wake_verdict.woke === true, 'status face: first new transition after startup wakes (baseline)')
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 3, ticket: 't1', stage: 'review', stage_state: 'done', idem: 's|t1|3' }) + '\n'
  await w.tickOnce()
  st = w.status()
  assert(st.last_wake_verdict.woke === false && (st.last_wake_verdict.reason ?? '').includes('疑似自'), 'status face: suppressed cycle names the presumed-self rule')
  assert(st.last_wake_verdict.considered >= 1 && st.last_wake_verdict.at > 0 && st.last_wake_verdict.presumed_self >= 1, 'status face: verdict carries considered + at + presumed_self')
  files['/ledg/sandbar.jsonl'].content += ledgerLine({ seq: 4, ticket: 't1', stage: 'implement', stage_state: 'blocked', idem: 's|t1|4' }) + '\n'
  await w.tickOnce()
  st = w.status()
  assert(st.last_wake_verdict.woke === true, 'status face: briefed ticket entering blocked wakes end-to-end through tick')
  assert(io.prompts.length === 2 && io.prompts[1].text.includes('blocked'), 'end-to-end brief names the blocked transition')
  w.dispose(); n += 4
}
{
  // 无投递面：verdict 点名 wakeIo 缺失，绝不留空。
  const clock2 = fakeClock()
  const { w: w2 } = makeDeps({ clock: clock2, ledgerLines: [ledgerLine({ seq: 1, ticket: 't1' })], boardRows: [{ id: 't1' }], wakeIo: null })
  await w2.start()
  const st = w2.status()
  assert(st.last_wake_verdict !== null && st.last_wake_verdict.woke === false && (st.last_wake_verdict.reason ?? '').includes('投递面'), 'status face: no-wakeIo cycle records an explicit verdict (never empty while running)')
  w2.dispose(); n += 1
}

console.log(`ok   wake-decision-bypass-t261003-15 blocks=${n}`)
done(n)
