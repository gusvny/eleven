// waiting-face UT (t261004-08): three-valued predicate (unknown never fakes normal) /
// running-bit discipline / attribution filter / unattributed rows named / asks projection.
import { detectWaitingFace } from '../src/host/waiting-face.ts'
import { assert, done } from './lib.mjs'

let n = 0
const NOW = 1_700_000_000_000
const EX = 'executor-sandbar'
const OWN = { raisedBy: EX, kind: 'question', target: 'req-1', sessionRunning: false, raisedAt: NOW - 60_000 }

// unknown 三入口：账不可读 / 会话 id 空 / 快照缺席——绝不读成 normal。
{
  const u1 = detectWaitingFace({ pending: null, sessionId: EX, running: false, nowMs: NOW })
  assert(u1.state === 'unknown' && u1.reason.length > 0, 'ledger unreadable → unknown with reason')
  const u2 = detectWaitingFace({ pending: [OWN], sessionId: '', running: false, nowMs: NOW })
  assert(u2.state === 'unknown' && u2.reason.includes('not declared'), 'no session id → unknown, never normal')
  const u3 = detectWaitingFace({ pending: [OWN], sessionId: EX, running: null, nowMs: NOW })
  assert(u3.state === 'unknown' && u3.reason.includes('snapshot'), 'snapshot missing → unknown (C3: null is NOT idle)')
  assert(u3.asks.length === 0, 'unknown carries no asks (nothing was read)')
  n += 4
}

// waiting：空闲 + 归属本会话的未答复行。
{
  const w = detectWaitingFace({ pending: [OWN, { raisedBy: 'other', kind: 'approval', target: 'req-2', sessionRunning: true }], sessionId: EX, running: false, nowMs: NOW })
  assert(w.state === 'waiting' && w.asks.length === 1 && w.asks[0].requestId === 'req-1', 'waiting with only own-session asks projected')
  assert(w.sinceMs === NOW - 60_000, 'sinceMs = earliest own ask raisedAt')
  n += 2
}

// clear 两形态：没有归属行 / 会话在跑（在跑时挂起行仍点名在 reason，不静默）。
{
  const c1 = detectWaitingFace({ pending: [{ raisedBy: 'other', kind: 'approval', target: 'r', sessionRunning: true }], sessionId: EX, running: false, nowMs: NOW })
  assert(c1.state === 'clear' && c1.asks.length === 0, 'no own ask → clear')
  const c2 = detectWaitingFace({ pending: [OWN], sessionId: EX, running: true, nowMs: NOW })
  assert(c2.state === 'clear' && c2.asks.length === 1 && c2.reason.includes('running=true'), 'running=true → clear but pending asks still named')
  n += 2
}

// 未归属行：不参与匹配，reason 显式点名计数。
{
  const u = detectWaitingFace({
    pending: [{ raisedBy: '', kind: 'approval', target: 'req-9', sessionRunning: false }],
    sessionId: EX, running: false, nowMs: NOW,
  })
  assert(u.state === 'clear' && u.reason.includes('1 request(s) lack attribution'), 'unattributed rows named in reason, never matched')
  n += 1
}

// raisedAt 畸形（缺席/NaN）→ asks 里 null 显式，sinceMs 落在剩余可读行的最小值。
{
  const w = detectWaitingFace({
    pending: [
      { raisedBy: EX, kind: 'question', target: 'a', sessionRunning: false },
      { raisedBy: EX, kind: 'question', target: 'b', sessionRunning: false, raisedAt: Number.NaN },
      { raisedBy: EX, kind: 'question', target: 'c', sessionRunning: false, raisedAt: NOW - 120_000 },
    ],
    sessionId: EX, running: false, nowMs: NOW,
  })
  assert(w.state === 'waiting' && w.asks.length === 3, 'malformed raisedAt rows still projected')
  assert(w.asks[0].raisedAt === null && w.asks[1].raisedAt === null, 'missing/NaN raisedAt → explicit null')
  assert(w.sinceMs === NOW - 120_000, 'sinceMs = min of readable raisedAt only')
  n += 3
}
done(n)
