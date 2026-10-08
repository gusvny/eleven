#!/usr/bin/env node
/**
 * t261008-22 scenario 3 — the discoverable disposition entry on a blocked
 * inspection card (grey-box L3, offline seconds, zero docker / Temporal /
 * real browser, never touches 3099).
 *
 * User-visible promise under test (host order 261008): on the executor
 * panel's Inspection face, a blocked period card NAMES both human exits —
 * "Re-run this period" and "Void with a reason" — both require a reason; an
 * attempt without one is refused by name, never accepted silently; the
 * engine's own refusal strings are surfaced verbatim; a voided card says
 * "Voided by <who>: <reason>" AND keeps stating the findings were rejected
 * (void must never read as a success, findings must never be hidden).
 *
 * Legs:
 *  P1  the blocked card's render model carries both action labels verbatim
 *      plus a reason-mandatory copy (the labels are the ticket's contract
 *      wording, not invented words).
 *  P2  a refusal/error payload fed through the render model is surfaced to
 *      the reader verbatim (the engine's in-flight refusal substring
 *      "在飞" reaches the model's error face — never swallowed).
 *  P3  a voided card renders "Voided by <who>: <reason>" and STILL contains
 *      the rejected-findings face (voiding hides nothing).
 *  P4  single-path tripwire (shallow source check): the disposition route
 *      face drives the engine's own entries — the rerun route carries the
 *      trigger path with a reopen reason and the void route carries the
 *      engine void entry; `ticket-cancel` appears nowhere in the disposition
 *      write face (it is a documented no-op on terminal tickets — plan v2 C1).
 *
 * Intent split: the engine void surface's own contract belongs to
 * sc_t26100822_void_named_surface; the composition/ordering belongs to
 * sc_t26100822_void_then_rerun_period; the left-column ranking face belongs
 * to sc_t26100822_voided_row_ranking; this entry owns only what a reader
 * sees on the panel's Inspection disposition face.
 *
 * Pre-implement = FAIL naming the missing face (TDD-phase red expected);
 * must be green at arbitrate/merge. node missing = ENV_FAIL exit 2.
 */
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
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

const EXIT = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'inspection-exit.tsx')
const VIEW = join(REPO, 'server', 'plugins', 'executor-panel', 'src', 'host', 'inspection-view.ts')
const API = join(REPO, 'server', 'plugins', 'executor-panel', 'src', 'host', 'api.ts')

// Blocked fixture: the t261002-12 shape, two findings fenced blocks — the
// parser's named refusal is the blocked_reason; the findings list is empty
// (zero findings produced) and the face must still say the findings were
// rejected.
const BLOCKED_CARD = {
  instance_id: 'integration-tests',
  period: '20261002',
  ticket_id: 't261002-12',
  blocked_reason: 'findings 围栏块必须恰一块，实际 2 块',
  findings: [],
  status: 'blocked',
}
const VOIDED = { who: 'host', reason: 'superseded by hand rerun; output rejected', at: '2026-10-08T00:00:00Z' }
const REFUSAL = '同期已有在飞巡检 t261002-12（RUNNING）——重跑会双跑同一期，在飞期不接受重开；等它收口，或先记名 cancel 后再重跑'

function deepText(v, out = []) {
  if (v == null) return out
  if (typeof v === 'string' || typeof v === 'number') { out.push(String(v)); return out }
  if (Array.isArray(v)) { for (const x of v) deepText(x, out); return out }
  if (typeof v === 'object') {
    for (const [k, val] of Object.entries(v)) { out.push(k); deepText(val, out) }
  }
  return out
}

function modelTexts(fn, card, extra) {
  // Call every exported function with the card (plus optional extra payloads)
  // and collect every string reachable in the returned structure. Shallow
  // binding by design: we pin what the model SAYS, not the function names.
  const texts = []
  const tries = [[card], [card, extra || {}], [{ card, ...extra || {} }]]
  for (const args of tries) {
    try {
      const r = fn(...args)
      if (r && typeof r.then === 'function') continue
      texts.push(deepText(r).join('\u0001'))
    } catch { /* not this export's shape */ }
  }
  return texts
}

// The reader face: the workbench ticket-detail exit block (pure helpers import
// cleanly; the JSX component itself is pinned at its copy face below).
let exitSrc = existsSync(EXIT) ? readFileSync(EXIT, 'utf8') : ''
let ex = null
try {
  ex = existsSync(EXIT) ? await import(`file://${EXIT}`) : null
} catch { /* JSX-bearing module may not strip-import; the copy face still bites */ }

if (!exitSrc) {
  record('P1 blocked-card-names-both-actions', 'fail', `missing ${EXIT} — the human-exit block (t261008-22) is not landed`)
} else {
  // ---- P1 both action labels + reason-mandatory copy (the ticket's wording) ----
  const hitRerun = exitSrc.includes('Re-run this period')
  const hitVoid = exitSrc.includes('Void with a reason')
  const hitReason = /Both need a reason|reason is required/i.test(exitSrc)
  // logic faces: the JSX-bearing module cannot strip-import under bare node, so
  // the visible-gate/reasonless-refusal LOGIC is pinned at the write face (the
  // server repeats the same named refusals — engine-side zero-side-effect proofs
  // live in the void-named-surface scenario) and at the module's own L1; here we
  // pin that the WRITE face refuses a reason-less attempt by name pre-spawn.
  let disp = ''
  const dispPath = join(REPO, 'server', 'plugins', 'executor-panel', 'src', 'host', 'inspection-disposition.ts')
  if (existsSync(dispPath)) disp = readFileSync(dispPath, 'utf8')
  const reasonless = /reason/i.test(disp) && /refus|required|never accepts/i.test(disp)
  record('P1 blocked-card-names-both-actions',
    hitRerun && hitVoid && hitReason && reasonless ? 'pass' : 'fail',
    `rerun=${hitRerun} void=${hitVoid} reason_copy=${hitReason} writeface_reason_refusal=${reasonless}`)

  // ---- P2 engine refusal reaches the reader verbatim (panel error surface) ----
  if (!existsSync(VIEW)) {
    record('P2 refusal-reaches-reader-verbatim', 'fail', `missing ${VIEW}`)
  } else {
    let vm = null
    try { vm = await import(`file://${VIEW}`) } catch (e) {
      record('P2 refusal-reaches-reader-verbatim', 'fail', `import failed: ${e.message}`)
    }
    if (vm) {
      const fns = Object.entries(vm).filter(([, v]) => typeof v === 'function')
      const refusalInput = { ok: false, error: REFUSAL }
      const texts = fns.flatMap(([n, f]) =>
        modelTexts(f, BLOCKED_CARD, refusalInput).concat(modelTexts(f, BLOCKED_CARD, REFUSAL)))
      record('P2 refusal-reaches-reader-verbatim',
        texts.some(t => t.includes('在飞') && t.includes('重跑')) ? 'pass' : 'fail',
        `faces_with_refusal=${texts.filter(t => t.includes('在飞')).length}`)
    }
  }

  // ---- P3 voided card: "Voided by" + rejection stays, findings not erased ----
  const hasVoidedBy = exitSrc.includes('Voided by')
  const keepsRejection = /rejected|not erased|stays on record/i.test(exitSrc)
  record('P3 voided-card-names-who-reason-keeps-rejection',
    hasVoidedBy && keepsRejection ? 'pass' : 'fail',
    `voided_by=${hasVoidedBy} rejection_kept=${keepsRejection}`)
}

// ---- P4 single-path tripwire on the write face (shallow, source-level) ----
if (!existsSync(API)) {
  record('P4 disposition-write-face-single-path', 'fail', `missing ${API} — the disposition routes (plan v2 Step 3) are not landed`)
} else {
  let dispositionSrc = ''
  const dispCandidates = [
    join(REPO, 'server', 'plugins', 'executor-panel', 'src', 'host', 'inspection-disposition.ts'),
  ]
  for (const c of dispCandidates) if (existsSync(c)) dispositionSrc += readFileSync(c, 'utf8')
  const apiSrc = readFileSync(API, 'utf8')
  // strip comments so a doc comment NAMING ticket-cancel (explaining why it is
  // NOT used) is not mistaken for code invoking it
  const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ').replace(/^\s*\*.*$/gm, ' ')
  const both = strip(dispositionSrc) + strip(apiSrc)
  const hasRerunRoute = both.includes('inspection/period/rerun')
  const hasVoidRoute = both.includes('inspection/period/void')
  const noCancel = !both.includes('ticket-cancel')
  const drivesTrigger = /inspection_trigger|trigger\b/.test(dispositionSrc) && dispositionSrc.includes('reopen-reason')
  record('P4 disposition-write-face-single-path',
    hasRerunRoute && hasVoidRoute && noCancel && drivesTrigger ? 'pass' : 'fail',
    `rerun_route=${hasRerunRoute} void_route=${hasVoidRoute} ticket_cancel_absent=${noCancel} drives_trigger_reopen=${drivesTrigger}`)
}

summarize()
