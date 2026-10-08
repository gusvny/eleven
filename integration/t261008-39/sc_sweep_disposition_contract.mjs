#!/usr/bin/env node
/**
 * sc_sweep_disposition_contract.mjs — t261008-39 scenario (grey-box L2, offline
 * seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Intent (user-perceivable contract): the executor's sweep vocabulary is CLOSED and
 * evidence-backed — from any measured disk-truth shape exactly ONE disposition comes
 * out (retry_qc / rework(to_stage=implement) / file a request), a shape that fits
 * nothing (or readings that failed to measure) fail-closes to file-a-request, and
 * malformed readings never throw. The brief text and the classifying helper must
 * agree on the vocabulary — a helper that says one thing and a brief that asks for
 * another is the fabricated-checklist defect the ticket forbids.
 *
 * Steps:
 *  A table-driven replay over ALL 32 well-formed fact combinations through the
 *  PUBLIC classification export: exactly one outcome each, drawn from the closed
 *  vocabulary, mutually exclusive by construction (one call, one answer).
 *  B the known corner shapes: all-clean+ancestor => retry_qc; each unresolved
 *    marker (unmerged>0 / dirty / conflict markers / not-ancestor) => rework with a
 *    NAMED requirement (different facts name different requirements).
 *  C malformed readings (missing field, NaN, negative count, wrong type, null) =>
 *    file_request, never a throw, never a guess (external-input three-state hook).
 *  D vocabulary agreement: the brief produced by the real buildBrief names the same
 *    disposition outcomes the helper returns (no drift between ask and classify).
 *
 * Intent split (anti-duplication): the developer L1 battery owns the helper's
 * internal truth table; this entry pins the PUBLIC face — exportability, fail-closed
 * default on malformed input, and brief/helper vocabulary agreement. Pre-implement
 * red = FAIL naming the missing export; arbitrate/merge must be green.
 * Run directly: node integration/t261008-39/sc_sweep_disposition_contract.mjs (cwd=repo root).
 */
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const WD = join(REPO, 'server/plugins/watchdog')

let fails = 0
const fail = (m) => { console.error('FAIL ' + m); fails += 1 }
const ok = (m) => console.log('ok ' + m)

const VOCAB = ['retry_qc', 'rework', 'file_request', 'request']

let classify = null
let buildBrief = null
try {
  // The public classification seam: the plan names board-sweep.ts as its home.
  const mod = await import(pathToFileURL(join(WD, 'src/host/board-sweep.ts')).href)
  classify = mod.classifyDisposition ?? mod.classify ?? mod.default?.classifyDisposition ?? null
} catch (e) {
  fail('classification export missing (board-sweep.ts / classifyDisposition): ' + e.message)
}
try {
  ;({ buildBrief } = await import(pathToFileURL(join(WD, 'src/host/exits.ts')).href))
} catch (e) {
  fail('buildBrief export missing: ' + e.message)
}

function outcomeOf(r) {
  // The helper may return a string or a structured disposition; accept both shapes
  // but demand the closed vocabulary either way (grey-box: bind to the contract).
  if (r == null) return null
  if (typeof r === 'string') return r
  return r.disposition ?? r.action ?? r.outcome ?? null
}

function main() {
  if (typeof classify !== 'function') { console.error('FAIL count=' + fails); process.exit(1) }

  // A: exhaustive 32-combination table (booleans x unmergedCount in {0, 2})
  let seen = new Set()
  for (const readingsOk of [true, false]) {
    for (const mergeHeadPresent of [true, false]) {
      for (const unmergedCount of [0, 2]) {
        for (const worktreeDirty of [true, false]) {
          for (const conflictMarkers of [true, false]) {
            for (const mainIsAncestor of [true, false]) {
              const facts = { readingsOk, mergeHeadPresent, unmergedCount, worktreeDirty, conflictMarkers, mainIsAncestor }
              let r
              try { r = classify(facts) } catch (e) { fail('A helper threw on well-formed facts ' + JSON.stringify(facts) + ': ' + e.message); continue }
              const o = outcomeOf(r)
              if (o == null) { fail('A no outcome for facts ' + JSON.stringify(facts) + ' — the vocabulary fell through'); continue }
              if (!VOCAB.some((v) => String(o).includes(v))) fail('A outcome "' + o + '" outside the closed vocabulary for facts ' + JSON.stringify(facts))
              // B corner shapes
              const allClean = readingsOk && !mergeHeadPresent && unmergedCount === 0 && !worktreeDirty && !conflictMarkers && mainIsAncestor
              if (allClean && !String(o).includes('retry_qc')) fail('B stale-block shape (all clean, main ancestor) did not classify retry_qc: got ' + o)
              const unresolved = readingsOk && (unmergedCount > 0 || worktreeDirty || conflictMarkers || !mainIsAncestor)
              if (unresolved && !allClean && !String(o).includes('rework')) fail('B unresolved shape did not classify rework: ' + JSON.stringify(facts) + ' got ' + o)
              if (!readingsOk && !String(o).includes('request') && !String(o).includes('file')) fail('B unreadable readings must fail closed to file-a-request, got ' + o)
              seen.add(String(o))
            }
          }
        }
      }
    }
  }
  if (seen.size >= 3) ok('A table replayed over 32 combinations, vocabulary outcomes seen: ' + [...seen].join(', '))
  else if (fails === 0) fail('A fewer than three distinct outcomes over the full table — the vocabulary is not exercised')

  // B2: distinct unresolved facts must name distinct requirements (a named
  // requirement is what separates a rework from a bare demotion).
  const reqTexts = new Set()
  for (const facts of [
    { readingsOk: true, mergeHeadPresent: true, unmergedCount: 3, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: true, unmergedCount: 0, worktreeDirty: true, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: true, unmergedCount: 0, worktreeDirty: false, conflictMarkers: true, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: true, unmergedCount: 0, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: false },
  ]) {
    const r = classify(facts)
    const text = typeof r === 'string' ? r : JSON.stringify(r)
    reqTexts.add(text)
    if (typeof r === 'object' && r && !/requirement|rework|because|reason|unmerged|dirty|conflict|ancestor/i.test(text)) {
      fail('B2 rework result carries no named requirement: ' + text)
    }
  }
  if (reqTexts.size >= 3) ok('B2 four distinct unresolved fact-sets yield distinct/named results (' + reqTexts.size + ' distinct)')
  else fail('B2 distinct unresolved fact-sets collapse to the same unnamed result (' + reqTexts.size + ') — requirements not named per fact')

  // C: malformed readings fail closed, never throw
  for (const bad of [
    {},
    { readingsOk: true }, // fields missing
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: Number.NaN, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: -1, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: 'many', worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: 0, worktreeDirty: null, conflictMarkers: false, mainIsAncestor: true },
    null,
  ]) {
    let r = null
    try { r = classify(bad) } catch (e) { fail('C malformed input threw (must fail closed): ' + JSON.stringify(bad) + ' -> ' + e.message); continue }
    const o = outcomeOf(r)
    if (o == null || !(String(o).includes('request') || String(o).includes('file'))) {
      fail('C malformed input ' + JSON.stringify(bad) + ' classified to "' + o + '" — must fail closed to file-a-request')
    } else ok('C malformed input fail-closed: ' + JSON.stringify(bad))
  }

  // D: brief/helper vocabulary agreement
  if (typeof buildBrief === 'function') {
    const brief = buildBrief('sandbar', [], null)
    for (const token of ['retry_qc', 'rework']) {
      if (brief.includes(token)) ok('D brief names vocabulary token ' + token)
      else fail('D brief does not name vocabulary token "' + token + '" — ask and classify can drift apart')
    }
    if (/blocked|refused/i.test(brief) && /awaiting-human/i.test(brief)) ok('D brief names the decision states')
    else fail('D brief does not name the decision states for the sweep')
  }

  if (fails > 0) { console.error('FAIL count=' + fails); process.exit(1) }
  console.log('PASS sc_sweep_disposition_contract')
}

main()
