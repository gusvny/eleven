// one-shot-privilege UT (t261006-06): declaration validation (each key, incl.
// empty allowed_roots / relative roots / '..' roots), request-ledger parse
// (torn last line counted, never dropped), the approval gate (absent /
// unanswered / self-approval / expired request / aged-out grant / CONSUMED
// approval), audit-before-run fail-closed, duplicate-object refusal naming
// the holder, smuggled-privilege-key shape. All stubs: zero real host, zero
// ~/.sandbar, zero ports 3099/7233.
import {
  validatePrivilegeDeclaration, loadPrivilegeDeclaration, parseRequestLedger,
  checkApprovalGate, composeUnitBriefing, spawnApprovedUnit,
  privilegeDeclPath, privilegeAuditPath, buildPrivilegeAuditRow,
  smuggledPrivilegeKeys,
} from '../src/host/one-shot-privilege.ts'
import { assert, done } from './lib.mjs'

let n = 0
const T0 = 1_700_000_000_000

const DECL = { v: 1, preset: 'sandbar-executor-oneshot', allowed_roots: ['/tmp/proj'], max_ttl_ms: 3_600_000 }

// ---------- declaration ----------

{
  const v = validatePrivilegeDeclaration(DECL)
  assert(v.ok && v.decl.preset === 'sandbar-executor-oneshot', 'valid declaration accepted')
  n += 1
  const bads = [
    [null, 'not an object'],
    [{ ...DECL, v: 2 }, 'wrong version'],
    [{ ...DECL, preset: '' }, 'empty preset'],
    [{ ...DECL, allowed_roots: 'x' }, 'roots not array'],
    [{ ...DECL, allowed_roots: ['rel/path'] }, 'relative root'],
    [{ ...DECL, allowed_roots: ['/a/../b'] }, 'dotdot root'],
    [{ ...DECL, allowed_roots: [] }, 'empty roots (valid shape, refused at gate)'],
    [{ ...DECL, max_ttl_ms: 0 }, 'zero ttl'],
    [{ ...DECL, max_ttl_ms: 1.5 }, 'fractional ttl'],
  ]
  for (const [block, why] of bads) {
    const ok = validatePrivilegeDeclaration(block).ok
    assert(!ok, 'declaration refused: ' + why)
    n += 1
  }
  {
    const u = validatePrivilegeDeclaration({ ...DECL, extra: 1 })
    assert(!u.ok && u.error.includes('unknown keys'), 'unknown declaration key refused (fail-closed)')
    n += 1
  }
  {
    const sm = smuggledPrivilegeKeys({ project: 'p', request_id: 'r', action: 'a', preset: 'evil', scope: ['/etc'] })
    assert(JSON.stringify(sm) === JSON.stringify(['preset', 'scope']), 'smuggled privilege keys named exactly')
    assert(smuggledPrivilegeKeys({ project: 'p', request_id: 'r', action: 'a' }).length === 0, 'clean body carries no smuggled keys')
    n += 2
  }
  assert(!loadPrivilegeDeclaration(null).ok, 'absent declaration refused by name')
  assert(!loadPrivilegeDeclaration('not json').ok, 'malformed declaration JSON refused')
  n += 2
  assert(privilegeDeclPath('/cfg', 'p').endsWith('/cfg/p/one-shot-privilege.json'), 'decl path shape')
  assert(privilegeAuditPath('/data', 'p').endsWith('/data/p.one-shot-privilege-audit.jsonl'), 'audit path shape')
  n += 2
}

// ---------- ledger parse (torn last line) ----------

{
  const raw = [
    JSON.stringify({ type: 'request', id: 'req-1', at: T0, project: 'p', kind: 'approval', question: 'q', detail: 'd', default_action: '', expires_at: null, raised_by: 'session-exec' }),
    JSON.stringify({ type: 'answer', answer_for: 'req-1', at: T0 + 10, by: 'host' }),
    '',
  ].join('\n')
  const p = parseRequestLedger(raw)
  assert(p.requests.length === 1 && p.answers.length === 1 && p.malformed_rows === 0, 'clean ledger parses')
  n += 1
  // Torn last line: a truncated append must be COUNTED, never dropped.
  const torn = raw + '{"type":"ans'
  const t = parseRequestLedger(torn)
  assert(t.malformed_rows === 1, 'torn last line counted')
  n += 1
  const junk = parseRequestLedger('garbage\n' + raw)
  assert(junk.malformed_rows === 1 && junk.requests.length === 1, 'junk line counted, good rows kept')
  n += 1
}

// ---------- gate ----------

function ledger(requestId = 'req-1', raisedBy = 'session-exec', expiresAt = null, answerBy = 'host', answered = true) {
  const req = { type: 'request', id: requestId, at: T0, project: 'p', kind: 'approval', question: 'q', detail: 'd', default_action: '', expires_at: expiresAt, raised_by: raisedBy }
  const ans = answered ? JSON.stringify({ type: 'answer', answer_for: requestId, at: T0 + 10, by: answerBy }) : ''
  return JSON.stringify(req) + '\n' + (ans ? ans + '\n' : '')
}

{
  const base = { requestId: 'req-1', action: 'rotate the deploy key', ledgerRaw: ledger(), runsRaw: null, auditRaw: null, decl: DECL, nowMs: T0 + 20 }
  const ok = checkApprovalGate(base)
  assert(ok.ok && ok.approved_by === 'host' && ok.scope_roots.length === 1, 'approved request admits')
  n += 1

  const refusals = [
    [{ ...base, action: '' }, 'empty action'],
    [{ ...base, ledgerRaw: null }, 'absent ledger'],
    [{ ...base, ledgerRaw: ledger('req-2') }, 'request not found'],
    [{ ...base, ledgerRaw: ledger('req-1', 'session-exec', null, 'host', false) }, 'unanswered'],
    [{ ...base, ledgerRaw: ledger('req-1', 'session-exec', null, 'session-exec') }, 'self-approval'],
    [{ ...base, ledgerRaw: ledger('req-1', 'session-exec', T0 + 15) }, 'expired request'],
    [{ ...base, nowMs: T0 + 10 + DECL.max_ttl_ms + 1 }, 'aged-out grant'],
    [{ ...base, decl: { ...DECL, allowed_roots: [] } }, 'no roots granted'],
    [{ ...base, ledgerRaw: 'garbage\n' + ledger() }, 'malformed ledger fails closed'],
  ]
  for (const [input, why] of refusals) {
    const r = checkApprovalGate(input)
    assert(!r.ok, 'gate refuses: ' + why)
    assert(typeof r.error === 'string' && r.error.length > 10, 'refusal carries a named reason: ' + why)
    n += 2
  }

  // Consumed: run journal row (append-only, not the lock) refuses by name.
  const runs = JSON.stringify({ session_id: 's-oneshot-1', project: 'p', object_key: 'request:req-1', started_at: T0 + 50, ended_at: T0 + 60, outcome: 'ok', summary: 'done' }) + '\n'
  const c1 = checkApprovalGate({ ...base, runsRaw: runs })
  assert(!c1.ok && c1.error.includes('s-oneshot-1') && c1.error.includes('already consumed'), 'consumed via run journal, names the run')
  n += 1
  const auditRow = buildPrivilegeAuditRow({ at: T0 + 50, project: 'p', request_id: 'req-1', action: 'a', approved_by: 'host', scope_roots: ['/x'], preset: 'p1', session_id: 's-9', decision: 'granted', reason: 'admitted' })
  const c2 = checkApprovalGate({ ...base, auditRaw: auditRow })
  assert(!c2.ok && c2.error.includes('s-9'), 'consumed via audit granted row')
  n += 1
  // A refused audit row does NOT consume.
  const refusedRow = buildPrivilegeAuditRow({ at: T0 + 50, project: 'p', request_id: 'req-1', action: 'a', approved_by: '', scope_roots: [], preset: '', session_id: null, decision: 'refused', reason: 'expired' })
  const c3 = checkApprovalGate({ ...base, auditRaw: refusedRow })
  assert(c3.ok, 'refused audit rows do not consume the approval')
  n += 1
  // A different request's run does not consume this one.
  const other = runs.replace('request:req-1', 'request:req-2')
  const c4 = checkApprovalGate({ ...base, runsRaw: other })
  assert(c4.ok, 'another request\'s run does not consume')
  n += 1
}

// ---------- briefing ----------

{
  const b = composeUnitBriefing({ objectKey: 'request:req-1', action: 'rotate key', scopeRoots: ['/tmp/proj'], preset: 'oneshot', approvedBy: 'host', approvedAt: T0 })
  assert(b.includes('request:req-1') && b.includes('rotate key') && b.includes('/tmp/proj') && b.includes('Refuse by name'), 'briefing names object, action, scope, boundary')
  n += 1
}

// ---------- spawn face ----------

function memDeps(over = {}) {
  const files = {
    '/cfg/p/one-shot-privilege.json': JSON.stringify(DECL),
    '/root/p/requests.jsonl': ledger(),
    '/data/p.one-shot-runs.jsonl': '',
    '/data/p.one-shot-privilege-audit.jsonl': '',
  }
  const auditRows = []
  let createCalls = 0
  return {
    files, auditRows,
    deps: {
      read: async (p) => (p in files ? files[p] : null),
      auditAppend: async (row) => { auditRows.push(row) },
      runUnit: async () => { createCalls += 1; return { action: 'done', sessionId: 's-new', objectKey: 'request:req-1', outcome: 'ok', summary: 'delivered' } },
      project: 'p', requestId: 'req-1', action: 'rotate key',
      declFile: '/cfg/p/one-shot-privilege.json',
      ledgerFile: '/root/p/requests.jsonl',
      runsFile: '/data/p.one-shot-runs.jsonl',
      auditFile: '/data/p.one-shot-privilege-audit.jsonl',
      nowMs: T0 + 20,
      ...over,
    },
    calls: () => createCalls,
  }
}

{
  // Approved: exactly one unit, granted audit row BEFORE the run.
  const m = memDeps()
  let sawAuditBeforeRun = false
  m.deps.auditAppend = async (row) => {
    if (row.decision === 'granted') sawAuditBeforeRun = m.calls() === 0
    m.auditRows.push(row)
  }
  const r = await spawnApprovedUnit(m.deps)
  assert(r.ok && r.spawn.action === 'done' && r.spawn.sessionId === 's-new', 'approved spawn runs exactly one unit')
  assert(m.calls() === 1, 'exactly one session create')
  assert(sawAuditBeforeRun, 'granted audit row lands before the run')
  assert(m.auditRows.some((x) => x.decision === 'settled' && x.session_id === 's-new'), 'settled audit row carries the session')
  n += 3

  // Unapproved: nothing spawns.
  const u = memDeps({ ledgerRawUnused: true })
  u.files['/root/p/requests.jsonl'] = ledger('req-1', 'session-exec', null, 'host', false)
  const r2 = await spawnApprovedUnit(u.deps)
  assert(!r2.ok && u.calls() === 0 && r2.error.includes('unanswered'), 'unapproved request spawns nothing')
  assert(u.auditRows.length === 1 && u.auditRows[0].decision === 'refused', 'refusal lands an audit row')
  n += 2

  // Consumed: second spawn of the same approval refuses by name.
  const c = memDeps()
  await spawnApprovedUnit(c.deps)
  const c2mem = memDeps()
  c2mem.files['/data/p.one-shot-runs.jsonl'] = JSON.stringify({ session_id: 's-1', project: 'p', object_key: 'request:req-1', started_at: T0, ended_at: T0, outcome: 'ok', summary: '' }) + '\n'
  const r3 = await spawnApprovedUnit(c2mem.deps)
  assert(!r3.ok && r3.error.includes('already consumed') && r3.error.includes('s-1'), 'replay refused by name, naming the consuming run')
  n += 1

  // Duplicate object while in flight: vehicle refuses by name, audit names the holder.
  const d = memDeps({ runUnitOverride: true })
  d.files['/data/p.one-shot-locks.json'] = JSON.stringify({ v: 1, locks: [{ object_key: 'request:req-1', session_id: 's-holder', acquired_at: T0, heartbeat_at: T0 + 1 }] })
  d.deps.runUnit = async () => ({ action: 'object-held', reason: 'object request:req-1 is locked by session s-holder since ' + T0 + ' -- one session per object' })
  const r4 = await spawnApprovedUnit(d.deps)
  assert(!r4.ok && r4.error.includes('s-holder'), 'duplicate object refused, holder named')
  const refusedRow = d.auditRows.find((x) => x.decision === 'refused')
  assert(refusedRow && refusedRow.reason.includes('s-holder'), 'audit reason carries the holder session')
  n += 2

  // Audit append failure: fail closed, nothing spawns.
  const f = memDeps()
  f.deps.auditAppend = async (row) => { if (row.decision === 'granted') throw new Error('disk full') }
  const r5 = await spawnApprovedUnit(f.deps)
  assert(!r5.ok && f.calls() === 0 && r5.error.includes('audit append failed'), 'audit append failure refuses the spawn fail-closed')
  n += 1

  // Malformed declaration: named refusal, no spawn.
  const b = memDeps()
  b.files['/cfg/p/one-shot-privilege.json'] = '{"v":2}'
  const r6 = await spawnApprovedUnit(b.deps)
  assert(!r6.ok && b.calls() === 0 && r6.error.includes('declaration rejected'), 'malformed declaration refused by name')
  n += 1

  // Scope limit rides the briefing (the unit is told its boundary).
  const br = memDeps()
  let briefingText = ''
  br.deps.runUnit = async (input) => { briefingText = input.briefing; return { action: 'done', sessionId: 's-2', objectKey: 'request:req-1', outcome: 'ok', summary: '' } }
  await spawnApprovedUnit(br.deps)
  assert(briefingText.includes('/tmp/proj') && briefingText.includes('Refuse by name'), 'briefing carries the declared scope and the boundary')
  n += 1
}

done(n)
