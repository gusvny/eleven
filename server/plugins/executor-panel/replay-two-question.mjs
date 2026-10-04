/**
 * replay-two-question.mjs —— t261004-17 证据回放（lane handoff 用；非 UT，不进 run_tests）。
 * 真桥 + 真账模块 + 内存 io（零真实 ~/.sandbar）：回放一次真实形状的两问两选 ask，
 * 打印它写下的账行、面板读回的 JSON、以及两问各答一行后的映射结果（含同标签串问反例）。
 * 用法：node server/plugins/executor-panel/replay-two-question.mjs
 */
import { mirrorToLedger, mapLedgerAnswer, waitForLedgerAnswer } from './src/host/question-bridge.ts'
import { readRequests, answerRequest } from './src/host/requests.ts'
import { memLedgerIo, fakeClock, freshDir, cleanup } from './tests/lib.mjs'

const env = { HOME: freshDir('replay-') }
const io = memLedgerIo()
const clock = fakeClock()
const ask = {
  id: 'ask-20261004-01',
  questions: [
    { id: 'restart', question: 'Restart the stalled worker?', detail: 'queue depth 340, no progress for 12 minutes.',
      options: [{ label: 'Restart now' }, { label: 'Leave it' }], default_action: 'leave it running' },
    { id: 'redclear', question: 'Open the red-clear ticket?', detail: '232 redline rows await a decision.',
      options: [{ label: 'Open it' }, { label: 'Skip' }], expires_at: clock.now() + 3600_000 },
  ],
  agent: { id: 'session-09ca0247', cwd: '/repo' },
}

const mirrored = mirrorToLedger(io, env, 'sandbar', ask, clock.now())
console.log('== 1. mirror result ==')
console.log(JSON.stringify(mirrored, null, 2))
const read = readRequests(io, env, 'sandbar')
console.log('== 2. ledger rows the mirror wrote (per question) ==')
for (const r of read.rows) console.log(JSON.stringify(r))
console.log('== 3. the JSON the panel reads back (GET /api/requests rows view) ==')
const panelView = read.rows.map(r => ({ ...r, urgency: { waiting_ms: 0, expired: false, answered: false } }))
console.log(JSON.stringify({ ok: true, rows: panelView, malformed_rows: read.malformed_rows }, null, 2))

// 宿主只答第二问 → 第一问不动。
const ids = mirrored.rows.map(r => r.id)
for (const id of ids) answerRequest(io, env, 'sandbar', id, '', 'host', clock.now()).ok // noop guard (must fail: empty answer)
answerRequest(io, env, 'sandbar', ids[1], 'Open it', 'host', clock.now())
console.log('== 4. answer question 2 only -> mapping ==')
console.log('unanswered group wait settles? (must be pending):')
const w = waitForLedgerAnswer({ io, env, project: 'sandbar', requestIds: ids, signal: null, pollMs: 1, deadlineMs: 60_000, now: clock.now })
const raced = await Promise.race([w.then(() => 'settled'), new Promise((r) => setTimeout(() => r('pending'), 30))])
console.log(raced)
answerRequest(io, env, 'sandbar', ids[0], 'Leave it', 'host', clock.now())
const out = await w
console.log(JSON.stringify(mapLedgerAnswer(ask, out.answers), null, 2))

// 同标签串问反例：两问都带 Proceed，只答第二问的 Proceed。
const collideAsk = { questions: [
  { id: 'a', question: 'Deploy now?', options: [{ label: 'Proceed' }, { label: 'Hold' }] },
  { id: 'b', question: 'Run the migration?', options: [{ label: 'Proceed' }, { label: 'Hold' }] },
] }
console.log('== 5. same label in both questions, only question 2 answered ==')
console.log(JSON.stringify(mapLedgerAnswer(collideAsk, ['', 'Proceed']), null, 2))

cleanup([env.HOME])
