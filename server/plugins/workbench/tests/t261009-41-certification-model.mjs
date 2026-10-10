/**
 * t261009-41 — Certification tab model UT (Slice 1).
 *
 * Covers, against the approved mock's rules:
 *  - the golden fixture (integration/t261009-41/test_model_fixture_contract.py
 *    regenerates it from the REAL engine projections): frozen face, counts add
 *    up, boundary, rounds table faces, promote gate through freeze;
 *  - presentation shaping: verdict roll-up, 'line <sha>' measured token,
 *    trigger words, HH:MM clock;
 *  - promote disabled only at zero, never because of freeze (design goal 8);
 *  - malformed inputs degrade to an explicit empty face, never a throw;
 *  - vocabulary: no emoji, no invented token ('main@… +N' impossible).
 *
 * Import mechanics (plan v2 R3): relative specifier with the explicit `.ts`
 * extension; node v26 strips types natively, no flag.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  deriveCertificationFace, promoteDisabled, verdictFace, measuredToken,
  triggerWord, formatClock, faceVocabulary,
} from '../src/client/certification-model.ts'

let n = 0

// ---- the golden fixture: engine projections -> face ----
const fixture = JSON.parse(
  readFileSync(new URL('./fixtures/t261009-41-certification-fixture.json', import.meta.url), 'utf8'))
const face = deriveCertificationFace(fixture.input)

{
  assert(face.ok && face.reason === '', `fixture face ok (${++n})`)
  assert(face.lineId === 'develop-buffer', `line id (${++n})`)
  assert(face.state === 'FROZEN' && face.frozen, `frozen state (${++n})`)
  // the one freeze line, and the culprit named
  assert(face.frozenFace && /Frozen by a red round/.test(face.frozenFace.banner)
    && /the certified part can still be promoted/.test(face.frozenFace.banner),
    `freeze banner one line (${++n})`)
  assert.deepEqual(face.frozenFace.blockers, ['t260922-12-gate-ledger-debt-not-blocked'],
    `blockers named (${++n})`)
  // counts add up: delivered + certified + waiting == landed total
  assert(face.deliveredTotal === 2, `delivered total (${++n})`)
  assert(face.certified.length === 2, `certified count (${++n})`)
  assert(face.waiting.length === 3, `waiting count (${++n})`)
  assert(face.deliveredTotal + face.certified.length + face.waiting.length === 7,
    `counts add up to landed total (${++n})`)
  assert(face.promotable === 2, `promotable = certified (${++n})`)
  // promote lives through the freeze
  assert(promoteDisabled(face) === false, `promote enabled while frozen (${++n})`)
  // ticket rows carry title and epic (the host asked for both)
  assert(face.certified[0].title === 'Promote the certified part'
    && face.certified[0].epic === 'develop-buffer', `certified row face (${++n})`)
  assert(face.waiting[0].epic === 'engine-hardening' && face.waiting[0].landedAt !== '',
    `waiting row face (${++n})`)
  // certified rows name the certification that covers them, and a promoted
  // ticket leaves the promotable side (coverage outlives promotion)
  assert(face.certified.every((r) => r.certifiedBy === 'cert-A'
    && r.ticket.startsWith('t261009-2')),
    `certified rows name their certification, delivered subtracted (${++n})`)
  // boundary: the covering green round, not the red one
  assert(face.boundary && face.boundary.runId === 'run-green',
    `boundary is the certifying round (${++n})`)
  assert(/^\d\d:\d\d$/.test(face.boundary.at), `boundary clock shape (${++n})`)
  // rounds table
  assert(face.rounds.length === 2, `rounds count (${++n})`)
  const red = face.rounds.find((r) => r.runId === 'run-red')
  assert(red.verdict === 'red' && red.blockers === 2, `red verdict with blockers (${++n})`)
  assert(red.trigger === 'auto' && red.measured === 'line 396b221a',
    `red round trigger + measured (${++n})`)
  assert(red.result.pass === 496 && red.result.fail === 2 && red.result.env === 0,
    `result parts labelled and summing (${++n})`)
  assert(face.roundState === 'idle', `round state from records (${++n})`)
}

// ---- presentation shaping helpers ----
{
  assert(verdictFace({ ran: 1, passed: 1, failed: 0, env_failed: 0 }).verdict === 'green',
    `ran>0 green (${++n})`)
  assert(verdictFace({ ran: 0, passed: 0, failed: 0, env_failed: 0 }).verdict === 'red',
    `ran==0 never a proof (${++n})`)
  const env = verdictFace({ ran: 10, passed: 5, failed: 3, env_failed: 2 })
  assert(env.blockers === 5 && env.result.env === 2, `env failures count as blockers (${++n})`)
  assert(verdictFace('garbage').verdict === 'red', `malformed cases -> red, no throw (${++n})`)
  assert(measuredToken([{ repo: 'sandbar', revision: '396b221aX' }]) === 'line 396b221a',
    `measured truncates to 8 (${++n})`)
  assert(measuredToken([]) === 'line ?', `measured empty -> explicit ? (${++n})`)
  assert(triggerWord('scheduled') === 'auto' && triggerWord('lane') === 'manual',
    `trigger words (${++n})`)
  assert(formatClock(0).match(/^\d\d:\d\d$/), `clock at epoch (${++n})`)
  assert(formatClock('x') === '' && formatClock(-1) === '', `malformed clock -> empty (${++n})`)
}

// ---- promote gate: zero is the only disable; freeze never disables ----
{
  const green = deriveCertificationFace({
    line: { line_id: 'l' },
    waitStates: [{ ticket: 't1', state: 'certified', covered_by: 'c1', waiting_since: 5 }],
    certs: [{ id: 'c1', run: 'r1', at: 5 }],
    runs: [{ id: 'r1', source: 'scheduled', started_at: 1, cases: { ran: 2, passed: 2, failed: 0, env_failed: 0 } }],
    outcomes: [],
  })
  assert(green.state === 'GREEN' && green.frozenFace === null, `unfrozen face (${++n})`)
  assert(promoteDisabled(green) === false, `green promote enabled (${++n})`)
  const frozenEmpty = deriveCertificationFace({
    line: { line_id: 'l' }, freeze: { frozen: true, culprit: 'x', episode: 'frz-1', cause: 'cert-B', closed_at: null },
    waitStates: [{ ticket: 't1', state: 'waiting', waiting_since: 5 }],
  })
  assert(promoteDisabled(frozenEmpty) === true, `zero promotable is the only disable (${++n})`)
  const frozenFull = deriveCertificationFace({
    line: { line_id: 'l' }, freeze: { frozen: true, culprit: 'x', episode: 'frz-1', cause: 'cert-B', closed_at: null },
    waitStates: [{ ticket: 't1', state: 'certified', covered_by: 'c1' }],
    certs: [{ id: 'c1', run: 'r1', at: 5 }],
    runs: [{ id: 'r1', source: 'scheduled', started_at: 1, cases: { ran: 2, passed: 2, failed: 0, env_failed: 0 } }] })
  assert(frozenFull.frozen === true && promoteDisabled(frozenFull) === false,
    `freeze does not hold certified part hostage (${++n})`)
  // boundary prefers the older covering green round when a red follows
  assert(frozenFull.boundary.runId === 'r1', `boundary skips red (${++n})`)
}

// ---- rule 9: no invented scheduler ----
{
  const f = deriveCertificationFace({ line: { line_id: 'l' }, roundState: 'running' })
  assert(f.roundState === 'running', `records' round state passes through (${++n})`)
  const d = deriveCertificationFace({ line: { line_id: 'l' } })
  assert(d.roundState === 'idle' && d.ok, `absent round state degrades to idle, nothing invented (${++n})`)
  assert(!JSON.stringify(d).match(/next round/i), `no scheduler token anywhere (${++n})`)
}

// ---- malformed inputs: explicit degradation, never a throw ----
{
  const cases = [null, 42, 'x', {}, { line: null }, { line: { line_id: '  ' } },
    { line: { line_id: 'l' }, waitStates: 'garbage', certs: 7, runs: [null, 3] }]
  for (const bad of cases) {
    const f = deriveCertificationFace(bad)
    assert(typeof f.ok === 'boolean' && typeof f.deliveredTotal === 'number',
      `degraded face shape (${++n})`)
  }
  assert(deriveCertificationFace(null).ok === false
    && deriveCertificationFace(null).reason !== '', `null input names the reason (${++n})`)
  assert(deriveCertificationFace({}).reason.includes('line_id'), `missing line named (${++n})`)
  const junk = deriveCertificationFace({ line: { line_id: 'l' }, waitStates: [{ ticket: 5 }, { state: 'certified' }] })
  assert(junk.ok && junk.certified.length === 0 && junk.waiting.length === 0,
    `junk rows dropped, face stands (${++n})`)
}

// ---- rule 8: vocabulary — no emoji, no invented token ----
{
  const vocab = faceVocabulary()
  assert(!vocab.some((w) => /[\u{1F300}-\u{1FAFF}\u{2190}-\u{21FF}\u{FE0F}]/u.test(w)),
    `no glyph carries meaning (${++n})`)
  const blob = JSON.stringify(face)
  assert(!blob.includes('main@') && !blob.includes('+3') && !blob.includes('record'),
    `no 'main@sha +N', no 'record' word (${++n})`)
}

console.log(`t261009-41-certification-model: ${n} assertions ok`)
