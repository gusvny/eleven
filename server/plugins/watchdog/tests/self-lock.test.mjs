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
done(n)
