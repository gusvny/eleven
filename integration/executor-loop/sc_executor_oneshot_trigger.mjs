#!/usr/bin/env node
/**
 * sc_executor_oneshot_trigger.mjs -- the approved-request one-shot ignition
 * contract, grey-box L3 (ticket t261006-06; registered as
 * t261006-06-oneshot-trigger-privilege).
 *
 * The host's approved-request shape holds end to end: the executor files a
 * request, the human approval is the only gate, ONE privileged one-shot
 * session does that one thing, then ends. Offline seconds, zero docker /
 * Temporal / browser / network, never touches 3099.
 *
 * Legs (map to the ticket's required outcomes a-d plus review additions):
 *   S0  the privilege DECLARATION is the only preset source and validates
 *       fail-closed by name (wrong v, empty/non-string preset, empty/
 *       non-absolute roots, non-positive ttl, undeclared key);
 *   S1  (outcome b) an UNAPPROVED request spawns nothing -- the refusal
 *       names the missing approval;
 *   S2  (outcome a) an approved request passes the gate exactly once, the
 *       audit row records who (server-derived host) / what scope / when /
 *       which preset, and the settle row lands through the REAL engine port
 *       executor_oneshot.py (subprocess against a temp projects root) with
 *       the locked v1 schema;
 *   S3  (outcome e, review R2) the approval is CONSUMED -- a second spawn of
 *       the same settled approval is refused by name, checked against the
 *       append-only journal/audit, never the mutable lock;
 *   S4  (outcome c) scope is bounded -- a grant past max_ttl is refused by
 *       name, self-approval is refused by name, a trigger body smuggling
 *       preset/scope keys is refused by name;
 *   S5  (outcome d) a duplicate object is refused object-held naming the
 *       holder session; a second DISTINCT object under a cap of 1 is
 *       refused at-cap;
 *   S6  (review N1) a torn truncated last line of the request ledger fails
 *       the gate closed with a named parse count -- nothing spawns.
 *
 * Binding depth: the watchdog module's PUBLIC exports only (the pure decision
 * core + the spawn orchestration face); the host session seam is stubbed at
 * the declared boundary (headless lanes have no sessionController -- the stub
 * records create and delivery, every privileged decision around it is real).
 * A missing module or export is a named FAIL (pre-implement red expected,
 * TDD signal; arbitrate/merge must be green). node missing = exit path is
 * this script never running (ENV_FAIL at the runner).
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync, spawnSync } from 'node:child_process'

const REPO = path.resolve(new URL('../..', import.meta.url).pathname)
const WD = REPO + '/server/plugins/watchdog'
const ENGINE = REPO + '/server/engine/executor_oneshot.py'

let passed = 0, failed = 0, envFailed = 0, na = 0

function ok(cond, label, detail = '') {
  if (cond) { passed++; console.log('  ok  ' + label) }
  else { failed++; console.log('  FAIL ' + label + ' :: ' + String(detail).slice(0, 300)) }
  return Boolean(cond)
}
function info(label) { console.log('  ..  ' + label) }

const NOW = 1_759_700_000_000
const DECL = { v: 1, preset: 'sandbar-executor-privileged', allowed_roots: ['/srv/deploys'], max_ttl_ms: 600_000 }
const REQ_ID = 'req-0007'
const RAISER = 'agent:sandbar-executor'
const ACTION = 'rotate the deploy key'

// ------------------------------------------------ module under test (public exports)
let m = null
let vehicle = null
try {
  m = await import(WD + '/src/host/one-shot-privilege.ts')
  vehicle = await import(WD + '/src/host/one-shot.ts')
  info('module loads: one-shot-privilege.ts + one-shot.ts (vehicle admission)')
} catch (e) {
  console.log('FAIL :: module missing/unloadable -- contract cannot be pinned :: ' + String(e).slice(0, 200))
  console.log('SUMMARY pass=' + passed + ' fail=' + (failed + 1) + ' env_fail=' + envFailed + ' na=' + na)
  process.exit(1)
}
const need = (name) => {
  const fn = m[name]
  if (typeof fn === 'function') return fn
  failed++
  console.log('  FAIL export ' + name + ' missing (contract seam not implemented)')
  return null
}

function runOrSkip(label, fn) {
  info(label)
  try { fn() } catch (e) {
    failed++
    console.log('  FAIL ' + label + ' threw :: ' + String((e && e.message) || e).slice(0, 300))
  }
}

// fixtures -------------------------------------------------------------------

function ledgerLine(reqId = REQ_ID, raiser = RAISER) {
  return JSON.stringify({ type: 'request', id: reqId, at: NOW - 1000, project: 'alpha',
    kind: 'approval', question: 'may I rotate the deploy key?', detail: '',
    default_action: '', expires_at: null, raised_by: raiser }) + '\n'
}
function answerLine(reqId = REQ_ID, by = 'host', at = NOW, answer = 'approved') {
  return JSON.stringify({ type: 'answer', answer_for: reqId, at, by, answer }) + '\n'
}
function runLine(sessionId, reqId = REQ_ID) {
  return JSON.stringify({ session_id: sessionId, project: 'alpha',
    object_key: 'request:' + reqId, started_at: NOW, ended_at: NOW + 10,
    outcome: 'ok', summary: 'delivered' }) + '\n'
}

// S0 declaration validation (fail-closed, named) ------------------------------

runOrSkip('S0 declaration validates fail-closed by name', () => {
  const validate = need('validatePrivilegeDeclaration')
  if (!validate) return
  ok(validate(DECL).ok === true, 'S0 valid declaration accepted', validate(DECL))
  const bads = [
    [{ ...DECL, v: 2 }, 'wrong schema version'],
    [{ ...DECL, preset: '' }, 'empty preset'],
    [{ ...DECL, preset: 42 }, 'non-string preset'],
    [{ ...DECL, allowed_roots: [] }, 'empty roots'],
    [{ ...DECL, allowed_roots: ['relative/path'] }, 'non-absolute root'],
    [{ ...DECL, max_ttl_ms: 0 }, 'non-positive ttl'],
    [{ ...DECL, extra: 1 }, 'undeclared key'],
  ]
  for (const [bad, why] of bads) {
    const r = validate(bad)
    ok(r && r.ok === false && String(r.error || '').length > 0,
      'S0 malformed declaration refused by name: ' + why, r)
  }
})

// S1 unapproved spawns nothing (outcome b) ------------------------------------

runOrSkip('S1 unapproved request refused, names the missing approval (outcome b)', () => {
  const gate = need('checkApprovalGate')
  if (!gate) return
  const r = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine(),
    runsRaw: null, auditRaw: null, decl: DECL, nowMs: NOW })
  ok(r && r.ok === false && /unanswered/i.test(r.error), 'S1 no answer => refused, approval named', r)
  const absent = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: null,
    runsRaw: null, auditRaw: null, decl: DECL, nowMs: NOW })
  ok(absent && absent.ok === false && /absent/i.test(absent.error), 'S1 absent ledger => refused', absent)
})

// S2 approved exactly once; audit records who/scope/when/preset; REAL settle (outcome a)

runOrSkip('S2 approved request: gate once, audit row, real engine settle (outcome a)', () => {
  const gate = need('checkApprovalGate')
  const auditRow = need('buildPrivilegeAuditRow')
  if (!gate || !auditRow) return
  const granted = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine() + answerLine(),
    runsRaw: '', auditRaw: '', decl: DECL, nowMs: NOW + 20 })
  ok(granted && granted.ok === true, 'S2 approved request admits', granted)
  ok(granted && granted.approved_by === 'host' && granted.preset === DECL.preset
    && JSON.stringify(granted.scope_roots) === JSON.stringify(DECL.allowed_roots),
    'S2 gate records who (server-derived host) / preset / scope', granted)
  const row = JSON.parse(auditRow({ at: granted.approved_at, project: 'alpha', request_id: REQ_ID,
    action: ACTION, approved_by: granted.approved_by, approved_at: granted.approved_at,
    scope_roots: granted.scope_roots, preset: granted.preset, session_id: null,
    decision: 'granted', reason: 'admitted' }))
  ok(row.decision === 'granted' && row.approved_by === 'host' && row.at === granted.approved_at
    && row.preset === DECL.preset, 'S2 audit row carries who / what scope / when / which preset', row)

  // REAL engine settle port against a temp projects root.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'oneshot-s2-'))
  try {
    const key = 'alpha'
    fs.mkdirSync(path.join(tmp, key, 'ledger'), { recursive: true })
    fs.writeFileSync(path.join(tmp, key, 'executor_sessions.json'),
      JSON.stringify({ sessions: [{ id: 's-oneshot-real', kind: 'one_shot' }] }))
    const body = JSON.stringify({ op: 'settle', project: key, session: 's-oneshot-real',
      ticket: 'request:' + REQ_ID, result: 'rotated the deploy key; scoped to /srv/deploys' })
    const env = { ...process.env, SANDBAR_PROJECTS_DIR: tmp, HOME: tmp }
    const rr = spawnSync('python3', [ENGINE, body], { env, encoding: 'utf8', timeout: 30000, input: '' })
    if (rr.error || rr.status !== 0) {
      ok(false, 'S2 settle subprocess failed',
        JSON.stringify({ error: String(rr.error || ''), status: rr.status, stderr: String(rr.stderr || '').slice(0, 200), stdout: String(rr.stdout || '').slice(0, 200) }))
      return
    }
    const out = rr.stdout
    const receipt = JSON.parse(out.trim().split('\n').pop())
    ok(receipt.ok === true, 'S2 real engine settle port accepted the unit result', out)
    const rows = fs.readFileSync(path.join(tmp, key, 'ledger', 'executor-settle.jsonl'), 'utf8')
      .split('\n').filter((l) => l.trim() !== '').map((l) => JSON.parse(l))
    ok(rows.length === 1 && rows[0].session === 's-oneshot-real' && rows[0].surface === 'engine-oneshot'
      && rows[0].v === 1 && rows[0].ticket === 'request:' + REQ_ID,
      'S2 settle row present with the locked v1 schema', rows)
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})

// S3 the approval is CONSUMED (outcome e, review R2) ---------------------------

runOrSkip('S3 settled approval consumed; replay refused by name (outcome e)', () => {
  const gate = need('checkApprovalGate')
  if (!gate) return
  const journal = runLine('s-oneshot-real')
  const r = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine() + answerLine(),
    runsRaw: journal, auditRaw: '', decl: DECL, nowMs: NOW + 20 })
  ok(r && r.ok === false && /already consumed/i.test(r.error) && r.error.includes('s-oneshot-real'),
    'S3 replay refused by name, consuming run named', r)
  // Append-only audit as the consumed source (never the mutable lock).
  const audit = JSON.stringify({ at: NOW, project: 'alpha', request_id: REQ_ID, action: ACTION,
    approved_by: 'host', scope_roots: DECL.allowed_roots, preset: DECL.preset,
    session_id: 's-9', decision: 'granted', reason: 'admitted' }) + '\n'
  const r2 = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine() + answerLine(),
    runsRaw: '', auditRaw: audit, decl: DECL, nowMs: NOW + 20 })
  ok(r2 && r2.ok === false && r2.error.includes('s-9'), 'S3 granted audit row also consumes', r2)
})

// S4 scope is bounded (outcome c) ----------------------------------------------

runOrSkip('S4 scope bounded: ttl, self-approval, smuggled keys (outcome c)', () => {
  const gate = need('checkApprovalGate')
  const smuggled = need('smuggledPrivilegeKeys')
  if (!gate || !smuggled) return
  const late = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine() + answerLine(REQ_ID, 'host', NOW - 10_000_000),
    runsRaw: '', auditRaw: '', decl: DECL, nowMs: NOW + 20 })
  ok(late && late.ok === false && /expired|ttl/i.test(late.error), 'S4 grant past max_ttl refused by name', late)
  const self = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine() + answerLine(REQ_ID, RAISER),
    runsRaw: '', auditRaw: '', decl: DECL, nowMs: NOW + 20 })
  ok(self && self.ok === false && /self-approval|raiser/i.test(self.error), 'S4 self-approval refused by name', self)
  const body = { project: 'alpha', request_id: REQ_ID, action: ACTION, preset: 'evil', scope: ['/etc'] }
  const keys = smuggled(body)
  ok(Array.isArray(keys) && keys.includes('preset') && keys.includes('scope'),
    'S4 trigger body smuggling preset/scope keys refused by name', keys)
  ok(smuggled({ project: 'alpha', request_id: REQ_ID, action: ACTION }).length === 0,
    'S4 clean body carries no smuggled keys')
})

// S5 lock and cap (outcome d) ---------------------------------------------------

runOrSkip('S5 duplicate object names the holder; distinct object at-cap (outcome d)', () => {
  const gate = need('checkApprovalGate')
  const admit = vehicle ? vehicle.admitUnit : null
  if (!gate) return
  const lockTable = { v: 1, locks: [{ object_key: 'request:' + REQ_ID, session_id: 's-holder',
    acquired_at: NOW - 5, heartbeat_at: NOW - 1 }] }
  // The gate admits (approval fresh, not consumed); the vehicle's admission
  // (public export of one-shot.ts, same module family) then refuses.
  const g = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: ledgerLine() + answerLine(),
    runsRaw: '', auditRaw: '', decl: DECL, nowMs: NOW + 20 })
  ok(g && g.ok === true, 'S5 fresh approval passes the gate', g)
  if (typeof admit === 'function') {
    const held = admit({ objectKey: 'request:' + REQ_ID, table: lockTable, limit: 3, nowMs: NOW })
    ok(held.action === 'object-held' && held.reason.includes('s-holder'),
      'S5 duplicate object refused object-held, holder session named', held)
    const capped = admit({ objectKey: 'request:req-other', table: lockTable, limit: 1, nowMs: NOW })
    ok(capped.action === 'at-cap' && /cap/i.test(capped.reason),
      'S5 second DISTINCT object under a cap of 1 refused at-cap', capped)
  } else {
    failed++
    console.log('  FAIL admitUnit export missing from the one-shot vehicle module')
  }
})

// S6 torn ledger line fails closed (review N1) ----------------------------------

runOrSkip('S6 torn ledger line fails the gate closed with a named count', () => {
  const gate = need('checkApprovalGate')
  const parse = need('parseRequestLedger')
  if (!gate || !parse) return
  const torn = ledgerLine() + answerLine() + '{"type":"ans'
  const parsed = parse(torn)
  ok(parsed.malformed_rows === 1, 'S6 torn last line counted, never dropped', parsed)
  const r = gate({ requestId: REQ_ID, action: ACTION, ledgerRaw: torn,
    runsRaw: '', auditRaw: '', decl: DECL, nowMs: NOW + 20 })
  ok(r && r.ok === false && /malformed/i.test(r.error), 'S6 gate fails closed, count named', r)
})

console.log('SUMMARY pass=' + passed + ' fail=' + failed + ' env_fail=' + envFailed + ' na=' + na)
process.exit(failed > 0 ? 1 : 0)
