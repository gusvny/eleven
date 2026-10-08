#!/usr/bin/env node
/**
 * t261008-22 scenario 4 — a voided inspection row stops being ranked as
 * blocked (grey-box L3, offline seconds, zero docker / Temporal / browser,
 * never touches 3099).
 *
 * User-visible promise under test (host order 261008, acceptance 5): the
 * host's complaint is a six-day-old blocked row sitting at the top of the
 * left column; after the human exit the row must stop being ranked as
 * 'blocked' FOREVER — the plan's stated choice is re-classification (the row
 * stays visible, saying it was voided, in the closed family), not removal.
 * The assertion is on the derived STATE that drives rendered position, never
 * on a class name.
 *
 * Legs:
 *  R1  a row carrying the voided key is re-classified: the module's public
 *      derivation maps it to the done/closed family — never 'blocked' — even
 *      though its status/stage words still say blocked (the snapshot words
 *      are history; the voided key is the disposition).
 *  R2  regression: a NON-voided row with the same status/stage/exec words
 *      still maps to 'blocked' exactly as today (the exit must not soften
 *      the ranking for live blocked rows).
 *  R3  merged ordering: in a list [voided blocked row, live blocked row,
 *      running dev row] the voided row is NOT in the top blocked tier —
 *      assert relative order through sortMergedTickets, the production
 *      ordering face.
 *
 * Intent split: the engine row carrying the voided key belongs to the engine
 * scenarios (sc_t26100822_void_named_surface / _void_then_rerun_period); the
 * panel card's own copy belongs to sc_t26100822_disposition_entry_face; this
 * entry owns only the left-column ranking contract.
 *
 * Pre-implement = FAIL naming the missing face (TDD-phase red expected);
 * must be green at arbitrate/merge. node missing = ENV_FAIL exit 2.
 */
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

if (typeof process === 'undefined' || !process.versions?.node) {
  console.log('ENV_FAIL: node runtime missing')
  process.exit(2)
}

const MOD = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'ticket-list-model.ts')
if (!existsSync(MOD)) {
  console.log(`ENV_FAIL: workbench ticket-list model missing: ${MOD}`)
  process.exit(2)
}
let m = null
try {
  m = await import(`file://${MOD}`)
} catch (e) {
  console.log(`ENV_FAIL: model module unimportable: ${e.message}`)
  process.exit(2)
}
assert.equal(typeof m.deriveTicketState, 'function', 'deriveTicketState export')
assert.equal(typeof m.sortMergedTickets, 'function', 'sortMergedTickets export')

// The fixture rows mirror the documented row shape (status/stage snapshot
// words + exec status); the voided key is the plan-declared disposition mark.
const VOIDED_ROW = {
  id: 't261002-12',
  title: 'Inspection integration-tests · period 20261002',
  status: 'blocked',
  stage_state: 'blocked',
  exec_status: 'RUNNING',
  blocked_reason: 'findings fenced blocks must be exactly one; got 2',
  updated_ts: '2026-10-02T10:00:00Z',
  voided: { who: 'host', reason: 'superseded by hand rerun; output rejected', at: '2026-10-08T00:00:00Z' },
}
const LIVE_BLOCKED_ROW = { ...VOIDED_ROW, id: 't-live', blocked_reason: 'findings fenced blocks must be exactly one; got 2', updated_ts: '2026-10-09T10:00:00Z' }
delete LIVE_BLOCKED_ROW.voided
const RUNNING_ROW = {
  id: 't-dev-run', title: 'dev running', status: 'running', stage_state: 'running',
  exec_status: 'RUNNING', updated_ts: '2026-10-09T11:00:00Z',
}

// ---- R1 the voided row's derived state is never 'blocked' ----
// The plan's contract: the derivation consumes the voided key EARLY, so a
// voided row re-classifies out of the blocked family even when its snapshot
// words (status/stage_state 'blocked', live/absent exec) would derive
// 'blocked'. The discriminator is the row's UN-voided twin: the entry point
// must be genuinely voided-aware (twin derives blocked, voided differs), not
// an accidental malformed-input default answering 'active' for any object.
const TWIN_ROW = { ...VOIDED_ROW }
delete TWIN_ROW.voided
let sawNonBlocked = false
let probeDetail = 'no voided-aware derivation found'
try {
  const candidates = []
  if (m.deriveTicketState.length >= 4 || m.deriveTicketState.length === 1) {
    candidates.push(['deriveTicketState(row)', (r) => m.deriveTicketState(r)])
    candidates.push(['deriveTicketState(words,voided)', (r) => m.deriveTicketState('blocked', 'blocked', 'RUNNING', r.voided)])
  }
  for (const [name, fn] of Object.entries(m)) {
    if (typeof fn !== 'function' || name === 'deriveTicketState') continue
    if (/state|tier|row/i.test(name)) {
      candidates.push([name, (r) => fn(r)])
      candidates.push([`${name}+words`, (r) => fn('blocked', 'blocked', 'RUNNING', r)])  // row-shaped consumers (tier family)
    }
  }
  const outcomes = []
  for (const [name, fn] of candidates) {
    try {
      const a = fn(VOIDED_ROW)
      const b = fn(TWIN_ROW)
      const key = (x) => (x != null && typeof x === 'object' && typeof x.state === 'string') ? x.state : x
      const ka = key(a)
      const kb = key(b)
      outcomes.push(`${name}: voided=${JSON.stringify(ka)} twin=${JSON.stringify(kb)}`)
      // genuinely voided-aware: the twin (same words, no disposition) derives
      // 'blocked' AND the voided row derives something else
      if (kb === 'blocked' && ka !== 'blocked') sawNonBlocked = true
    } catch { /* not this shape */ }
  }
  probeDetail = `probes: ${outcomes.join('; ') || 'none'}`
} catch (e) {
  probeDetail = `probe error: ${e.message}`
}
record('R1 voided-row-derives-non-blocked', sawNonBlocked ? 'pass' : 'fail', probeDetail)

// ---- R2 regression: non-voided mapping unchanged (current documented truth) ----
try {
  // t260921-03 terminal reconciliation: exec COMPLETED wins over snapshot words.
  assert.equal(m.deriveTicketState('blocked', 'blocked', 'COMPLETED'), 'done')
  // A genuinely live blocked row stays blocked.
  assert.equal(m.deriveTicketState('blocked', 'blocked', 'RUNNING'), 'blocked')
  assert.equal(m.deriveTicketState('running', 'running', 'RUNNING'), 'active')
  record('R2 non-voided-mapping-unchanged', 'pass', 'blocked+COMPLETED stays done, blocked+RUNNING stays blocked, running stays active')
} catch (e) {
  record('R2 non-voided-mapping-unchanged', 'fail', e.message)
}

// ---- R3 merged ordering: the voided row leaves the blocked tier ----
try {
  const ordered = m.sortMergedTickets([VOIDED_ROW, LIVE_BLOCKED_ROW, RUNNING_ROW])
  const ids = ordered.map(r => r.id)
  const voidedPos = ids.indexOf(VOIDED_ROW.id)
  const liveBlockedPos = ids.indexOf(LIVE_BLOCKED_ROW.id)
  const tierOf = m.ticketMergeTierOf
  // row-aware tier calls: the voided row (carrying its key as the row face)
  // must land OUT of the blocked tier while the live blocked twin stays in it
  const voidedTier = typeof tierOf === 'function'
    ? tierOf('blocked', 'blocked', 'RUNNING', VOIDED_ROW) : null
  const liveTier = typeof tierOf === 'function'
    ? tierOf('blocked', 'blocked', 'RUNNING', LIVE_BLOCKED_ROW) : null
  const ok = voidedPos > liveBlockedPos && voidedTier !== liveTier
  record('R3 voided-row-out-of-blocked-tier', ok ? 'pass' : 'fail',
    `order=${ids.join(',')} voided_tier=${JSON.stringify(voidedTier)} live_blocked_tier=${JSON.stringify(liveTier)}`)
} catch (e) {
  record('R3 voided-row-out-of-blocked-tier', 'fail', e.message)
}

summarize()
