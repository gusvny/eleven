// t261006-05 UT：未应答审批的具名判活（KI-207 条目 1 / KI-208 观测面）。
// 钉四件事（公开面断言，非内部结构）：
// ① approval-face 纯核：asked 无 decided = awaiting（id/at 进证据）；decided 在后 =
//    clear；窗口无审批事件 = none；records 无 type 形状 = unknown（绝不冒充「没有」）；
//    畸形深嵌套不坠拍。
// ② judgeExecutor：具名待答优先于一切推进/长回合分支（KI-207 教训：running=true +
//    等人不得折叠成 long_turn；他票的账本推进也不得掩盖）。
// ③ core 接线：approvalProvider 报待答 → 状态面 awaiting_approval + executor_
//    awaiting_approval 红线告警，证据点名审批 id；provider 不可读 → 旧行为，零审批告警。
import { Watchdog } from '../src/host/core.ts'
import { judgeApprovalWindow } from '../src/host/approval-face.ts'
import { judgeExecutor } from '../src/host/liveness.ts'
import { memTailIo, memCoreIo, fakeClock, assert, done } from './lib.mjs'

const NOW = 1_700_000_000_000
const M = 60_000
let n = 0

// ---------- ① approval-face 纯核 ----------
{
  const asked = { type: 'approval/asked', data: { id: 'ea1dc845-1', at: NOW } }
  const decided = { type: 'approval/decided', data: { id: 'ea1dc845-1' } }
  const w1 = judgeApprovalWindow([asked])
  assert(w1.state === 'awaiting' && w1.approval_id === 'ea1dc845-1' && w1.asked_at === NOW,
    'asked without decided = awaiting, id and asked-at extracted')
  assert(w1.evidence.includes('ea1dc845-1') && w1.evidence.includes('no approval/decided'),
    'evidence names the approval id (host-facing line)')
  const w2 = judgeApprovalWindow([asked, decided])
  assert(w2.state === 'clear', 'decided after asked = clear (not awaiting)')
  const w3 = judgeApprovalWindow([{ type: 'tool/call', data: {} }])
  assert(w3.state === 'none', 'window without approval events = none')
  const w4 = judgeApprovalWindow([{ data: 'no type field' }])
  assert(w4.state === 'unknown', 'records without a type shape = unknown (never fakes none)')
  const w5 = judgeApprovalWindow([])
  assert(w5.state === 'none', 'empty window = none')
  const deep = { type: 'approval/asked', data: { a: { b: { c: { d: { e: { f: { id: 'deep-id' } } } } } } } }
  const w6 = judgeApprovalWindow([deep])
  assert(w6.state === 'awaiting', 'malformed deep nesting does not crash the tick')
  const w7 = judgeApprovalWindow([asked, { type: 'approval/asked', data: { id: 'second-ask' } }])
  assert(w7.state === 'awaiting' && w7.approval_id === 'second-ask', 'two asked in a row = awaiting (latest named)')
  n += 8
}

// ---------- ② judgeExecutor：待答优先 ----------
{
  const sig = {
    sessionKnown: true, ledgerAdvanced: true, sessionProgress: true,
    lastWakeAt: NOW, sessionRunning: true,
    unansweredApproval: { approval_id: 'ea1dc845-1', asked_at: NOW, evidence: 'Unanswered approval prompt id=ea1dc845-1' },
  }
  const j = judgeExecutor(sig, NOW + 200 * M, 15, NOW, 45)
  assert(j.state === 'awaiting_approval', 'named unanswered approval wins over progressing/running signals')
  assert(j.evidence.includes('ea1dc845-1'), 'liveness evidence carries the approval id')
  const j2 = judgeExecutor({ sessionKnown: true, ledgerAdvanced: false, sessionProgress: false, lastWakeAt: NOW, sessionRunning: true }, NOW + 90 * M, 15, NOW, 45)
  assert(j2.state === 'long_turn', 'without the signal the old long_turn path is unchanged')
  n += 2
}

// ---------- ③ core 接线（注入桩，零真宿主） ----------
function makeW(approvalProvider) {
  const clock = fakeClock(NOW)
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const core = memCoreIo()
  let advanced = true
  const w = new Watchdog('sandbar', {
    configLoader: () => ({
      declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} },
      config: {
        enabled: true, executor_session: 'ex', stall_minutes: 15, long_turn_minutes: 45, reconcile_seconds: 5,
        alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'normal' }, redline: ['stall', 'executor_missing', 'executor_awaiting_approval'], keep_days: 14 },
      },
    }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced, mtimeMs: clock.now(), running: true }),
    sessionEnsure: async ({ declaredSessionId }) => ({ action: 'adopt', sessionId: declaredSessionId, declaredWritten: false, reason: 'adopt', event: null }),
    approvalProvider,
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return { w, clock, setAdvanced: v => { advanced = v } }
}

{
  const { w } = makeW(async () => ({ available: true, awaiting: true, approval_id: 'ea1dc845-1', asked_at: NOW, evidence: 'Unanswered approval prompt in the recent history window id=ea1dc845-1' }))
  await w.start()
  await w.tickOnce()
  const face = w.status().liveness.executor
  assert(face.state === 'awaiting_approval', 'status face names awaiting_approval (not long_turn)')
  assert(face.evidence.includes('ea1dc845-1'), 'host-facing line names the approval id')
  const hit = w.status().alerts.filter(a => a.rule === 'executor_awaiting_approval')
  assert(hit.length === 1 && hit[0].level === 'redline', 'redline alert raised through the normal raise path (review condition 2)')
  assert((hit[0].detail || '').includes('ea1dc845-1'), 'alert detail names the approval id and evidence')
  w.dispose()
  n += 3
}
{
  const { w } = makeW(async () => ({ available: false, awaiting: false, approval_id: null, asked_at: null, evidence: '', reason: 'history window unreadable' }))
  await w.start()
  await w.tickOnce()
  const face = w.status().liveness.executor
  assert(face.state === 'advancing', 'unreadable approval window feeds no signal — old advancing verdict stands (never fakes waiting)')
  assert(w.status().alerts.filter(a => a.rule === 'executor_awaiting_approval').length === 0, 'no approval alert is faked from an unreadable window')
  w.dispose()
  n += 2
}

// ---------- ④ create-shape 回归（review 条件 1：判据是行为，形状锁只作 conscious-diff 次要位） ----------
// 一拍式代建（watchdog 建 executor 会话的路径）： lawful delivery 走引擎侧投递面
// （不在会话进程内做仓外写入）→ 回合正常完成、零审批面介入；反向：真需要审批的
// 动作在本票下不再悬死——它以 awaiting_approval + 红线告警具名可见（上面 ③ 已钉）。
import { runOneShotUnit } from '../src/host/one-shot.ts'
{
  const files = {}
  const io = {
    async readText(p) { if (!(p in files)) { const e = new Error('ENOENT'); e.code = 'ENOENT'; throw e } return files[p] },
    async writeText(p, d) { files[p] = d },
    async append(p, line) { files[p] = (files[p] || '') + line },
  }
  let createInput = null
  const sessions = {
    async create(input) { createInput = input; return { ok: true, sessionId: 'oneshot-exec' } },
    // The turn performs its lawful delivery THROUGH the engine-side face — from the
    // session's own process this is a submit (no out-of-workspace write), so no
    // approval prompt exists on this path and the turn completes.
    async runTurn() { return { ok: true, summary: 'delivered via engine-side face; no approval record' } },
  }
  const out = await runOneShotUnit({
    project: 'p', dataDir: '/d', cwd: '/proj', unit: { kind: 'ticket', id: 't261006-05' }, limit: 2,
    io, sessions, nowMs: 1_700_000_000_000,
  })
  assert(out.action === 'done' && out.outcome === 'ok', 'lawful delivery turn completes with no approval record (grey-box behavior criterion)')
  assert(createInput !== null && JSON.stringify(Object.keys(createInput).sort()) === '["agentPreset","cwd"]',
    'create input stays {cwd, agentPreset} (conscious-diff lock, secondary)')
  n += 2
}

console.log(`approval-liveness-t261006-05: ${n} checks passed`)
await done()
