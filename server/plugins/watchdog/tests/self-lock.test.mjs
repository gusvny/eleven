// self-lock UT：waiting_on_itself / none / unknown 显式（provider 不可用不冒充 none）。
import { detectSelfLock } from '../src/host/self-lock.ts'
import { assert, done } from './lib.mjs'

let n = 0
const NOW = 1_700_000_000_000
const EX = 'executor-sandbar'
{
  const pending = [
    { raisedBy: 'ticket-t1-worker', kind: 'approval', target: 't1/merge-gate', sessionRunning: false },
    { raisedBy: EX, kind: 'approval', target: 't2/authorization', sessionRunning: false },
  ]
  const v = detectSelfLock(pending, EX, NOW)
  assert(v.state === 'waiting_on_itself' && v.target === 't2/authorization' && v.since === NOW, 'own pending approval = waiting on itself (immediate, no stall wait)')
  assert(detectSelfLock([], EX, NOW).state === 'none', 'no pending = none')
  assert(detectSelfLock([{ raisedBy: 'other-session', kind: 'approval', target: 'x', sessionRunning: true }], EX, NOW).state === 'none', 'others pending = not self-lock')
  const u = detectSelfLock(null, EX, NOW)
  assert(u.state === 'unknown' && u.reason.length > 0, 'provider unavailable = explicit unknown, never fake none')
  const u2 = detectSelfLock(null, EX, NOW, 'S1-probe 未过')
  assert(u2.reason.includes('S1-probe'), 'unknown carries the concrete reason')
  n += 5
}

// 未归属行（t260929-08）：空归属不参与匹配，显式点名计数，绝不冒充「没有自锁」。
{
  const mixed = [
    { raisedBy: '', kind: 'approval', target: 'req-1', sessionRunning: false },
    { raisedBy: 'other-session', kind: 'sign', target: 'req-2', sessionRunning: true },
  ]
  const v = detectSelfLock(mixed, EX, NOW)
  assert(v.state === 'none' && v.reason.includes('1 条') && v.reason.includes('raised_by'), 'unattributed waiting rows named explicitly in reason, state stays none')
  assert(detectSelfLock([{ raisedBy: '', kind: 'approval', target: 'req-1', sessionRunning: false }], EX, NOW).state !== 'waiting_on_itself', 'empty attribution can never match the executor session')
  const allAttr = detectSelfLock([{ raisedBy: 'other', kind: 'approval', target: 'x', sessionRunning: true }], EX, NOW)
  assert(allAttr.state === 'none' && allAttr.reason === '', 'fully attributed no-match = plain none with empty reason (no noise)')
  const matchAmongUnattr = detectSelfLock([
    { raisedBy: '', kind: 'approval', target: 'req-1', sessionRunning: false },
    { raisedBy: EX, kind: 'question', target: 'req-3', sessionRunning: false },
  ], EX, NOW)
  assert(matchAmongUnattr.state === 'waiting_on_itself' && matchAmongUnattr.target === 'req-3', 'attributed own request still fires even among unattributed rows')
  n += 4
}
done(n)
