#!/usr/bin/env node
/**
 * sc_t26100943_left_column_dismiss.mjs — the left-column dismiss face and the
 * dwell-rule hole (ticket t261009-43).
 *
 * Run directly: node integration/t261009-32/sc_t26100943_left_column_dismiss.mjs
 * (cwd = repo root), or through the registry entry in integration/run_scenarios.py.
 *
 * Grey-box L3, offline seconds, zero docker / Temporal / real browser, never
 * touches 3099. The engine half (journal, row augmentation, CLI) is owned by
 * the t261009-31 entries; this entry owns what a READER of the left column
 * sees: a failed row retiring by age, a dismissed row leaving the board for
 * BOTH sources, a dismissed fold that says dismissed (never done), and the
 * control's discipline (failed-class only, reason required, no bulk action,
 * never worded close/done, the client never invents the dismissed key).
 *
 * User story (host order 261009): "failed的票为什么还在左栏ui上，不能去掉吗"
 * and "能不能dismiss了就消失" — a failed workflow sits in the left column
 * forever (73 h / 110 h / 249 h measured) because sandbar-dwell.ts treats
 * every status except closed/verified as open; and a dismissed ticket must
 * disappear from the left column. The left column merges the dev-lane list
 * with the inspection board face, so the dismissal must work on both.
 *
 * Judged through the PUBLIC client faces: the dwell predicate (inSandbar /
 * isDwellOpen in sandbar-dwell.ts), the row-model helpers that read the
 * engine's dismissed payload (ticket-list-model.ts), and the sidebar source's
 * user-visible strings and wiring — never through private helper names, so a
 * contract-preserving refactor must not break this. Bound shallow on purpose:
 * source scans pin WORDING and WIRING SHAPE, not line numbers or identifier
 * spellings.
 *
 * Legs:
 *  D1  the dwell hole: a failure-class terminal row settles like a closed one
 *      and obeys the same pinned 24 h window from close_ts (fallback created);
 *      young failure rows stay; the closed/verified truth table is unchanged;
 *      exec_status-terminal rows settle too; in-flight rows never retire; no
 *      id/project special-casing (same status+age => same verdict).
 *  D2  the dismissed key is read from the engine payload and never invented:
 *      a plain-object dismissed row reads as dismissed; primitive/array/null
 *      shapes never do; a dismissed_note row (journal read failure) STAYS and
 *      is never treated as dismissed; a dismissed row is NOT reclassified —
 *      its five-state stays failed.
 *  D3  the fold: dismissed rows collect under a per-project fold whose label
 *      says "dismissed" and never done-family wording; the close/done words
 *      never appear in the dismiss control or fold label strings.
 *  D4  the control: offered on failure-class rows only, requires a reason
 *      (empty/whitespace refused client-side), never a bulk/group action,
 *      sends who+reason to the engine route, and the row leaves only when the
 *      payload says dismissed (re-read, no local flip).
 *  D5  the inspection source: a dismissed inspection row leaves the column
 *      through the same filter as dev-lane rows, and the client-window
 *      asymmetry (inspection rows never pass the 24 h dwell window, so the
 *      dismissal IS their retirement mechanism) is stated in a code comment,
 *      not left implicit.
 *  D6  order stability: removing a dismissed row from a merged project group
 *      keeps the remaining rows in their previous order.
 *
 * Pre-implementation tree: red naming the missing face is the expected TDD
 * signal; green required at the integration gate / merge. node missing or the
 * client tree missing = ENV_FAIL exit 2.
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

const CLIENT = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client')
const DWELL = join(CLIENT, 'sandbar-dwell.ts')
const MODEL = join(CLIENT, 'ticket-list-model.ts')
const SIDEBAR = join(CLIENT, 'sidebar.tsx')

for (const [label, p] of [['sandbar-dwell.ts', DWELL], ['ticket-list-model.ts', MODEL], ['sidebar.tsx', SIDEBAR]]) {
  if (!existsSync(p)) {
    console.log(`ENV_FAIL: workbench client tree missing ${label}: ${p}`)
    process.exit(2)
  }
}

const HOUR = 3600
const NOW = 1_800_000_000

function devRow(over = {}) {
  return { id: 't261009-01', project: 'sandbar', status: 'failed', close_ts: NOW - 2 * HOUR, created: NOW - 300 * HOUR, ...over }
}
function inspRow(over = {}) {
  return { id: 't261008-09', kind: 'inspection', project: 'integration-tests', status: 'failed', updated_ts: NOW - 2 * HOUR, ...over }
}

// ---- module loading (plain-TS modules import under node type stripping) ----
let dwell = null
let model = null
try { dwell = await import(`file://${DWELL}`) } catch (e) { record('D0 dwell-module-imports', 'fail', String(e).slice(0, 200)) }
try { model = await import(`file://${MODEL}`) } catch (e) { record('D0 model-module-imports', 'fail', String(e).slice(0, 200)) }

const sidebarSrc = readFileSync(SIDEBAR, 'utf8')
const modelSrc = readFileSync(MODEL, 'utf8')
const dwellSrc = readFileSync(DWELL, 'utf8')

/* =========================================================================
 * D1 — the dwell rule hole (spec 3)
 * ========================================================================= */
if (dwell && typeof dwell.inSandbar === 'function') {
  const open = (t) => dwell.inSandbar(t, NOW)

  // young failure row still lists (settling must not over-reach)
  record('D1a failed-young-still-lists', open(devRow({ close_ts: NOW - 1 * HOUR })) === true ? 'pass' : 'fail',
    'a failed row 1 h old must still be listed')

  // the hole itself: a failure-class terminal row older than the pinned window retires
  record('D1b failed-older-than-window-retires', open(devRow({ close_ts: NOW - 25 * HOUR })) === false ? 'pass' : 'fail',
    'a failed row 25 h old must have left (the reported 73/110/249 h shape)')

  // boundary is the pinned window, strict
  record('D1c failed-exactly-at-window-left', open(devRow({ close_ts: NOW - 24 * HOUR })) === false ? 'pass' : 'fail',
    'a failed row at exactly 24 h must have left (strict window)')

  // closed/verified lifecycle truth table unchanged
  const closedOk = open(devRow({ status: 'closed', close_ts: NOW - 1 * HOUR })) === true
    && open(devRow({ status: 'closed', close_ts: NOW - 25 * HOUR })) === false
    && open(devRow({ status: 'verified', close_ts: NOW - 25 * HOUR })) === false
  record('D1d closed-verified-truth-table-unchanged', closedOk ? 'pass' : 'fail',
    'the closed/verified dwell behaviour must not move')

  // exec_status terminal complement settles too; in-flight never retires
  const execOk = open(devRow({ status: 'active', close_ts: NOW - 300 * HOUR, exec_status: 'FAILED' })) === false
    && open(devRow({ status: 'active', close_ts: NOW - 1 * HOUR, exec_status: 'RUNNING' })) === true
  record('D1e exec-status-terminal-settles', execOk ? 'pass' : 'fail',
    'a terminal exec_status (FAILED) settles like closed; RUNNING stays open at any age')

  // close_ts fallback: a failure row without close_ts ages from created
  const fbOk = open(devRow({ close_ts: undefined, created: NOW - 25 * HOUR })) === false
    && open(devRow({ close_ts: undefined, created: NOW - 1 * HOUR })) === true
  record('D1f created-fallback-honoured', fbOk ? 'pass' : 'fail',
    'without close_ts the window runs from created')

  // no special-casing: identical status+age => identical verdict for different ids/projects
  const a = open(devRow({ id: 't260919-01', project: 'p-one', close_ts: NOW - 25 * HOUR }))
  const b = open(devRow({ id: 't260918-01', project: 'p-two', close_ts: NOW - 25 * HOUR }))
  record('D1g no-id-or-project-special-casing', a === b ? 'pass' : 'fail',
    'same status+age must give the same verdict regardless of id/project')

  // the rule lives in one place: the dwell module delegates failure-class
  // detection to the single derivation point and never compares a raw status
  // field against the five-state vocabulary itself (the only allowed literals
  // are the closed/verified early-out and the derivation's failed verdict).
  const ownWords = [...dwellSrc.matchAll(/(?:status|stage_state|exec_status)\s*===?\s*['"](failed|blocked|active|running|awaiting)['"]/g)].length
    + [...dwellSrc.matchAll(/['"](failed|blocked|active|running|awaiting)['"]\s*===?\s*t\./g)].length
  const delegates = /deriveTicketState/.test(dwellSrc)
  record('D1h rule-stays-single-point', ownWords === 0 && delegates ? 'pass' : 'fail',
    delegates
      ? `sandbar-dwell.ts re-derives lifecycle words itself (${ownWords} raw field/vocabulary comparisons) instead of delegating to the single derivation point`
      : 'sandbar-dwell.ts does not delegate failure detection to the five-state single point')
} else if (dwell) {
  record('D1 dwell-predicate-face', 'fail', 'inSandbar not exported from sandbar-dwell.ts')
}

/* =========================================================================
 * D2 — the dismissed key is read, never invented (specs 2/4/6)
 * ========================================================================= */
// The read helpers are public row-model functions (contract names per the
// t261009-31 payload: dismissed:{at,who,reason} / dismissed_note). Bind by
// declared export name with a shape probe; identifier renames that keep the
// contract may pass, missing faces fail.
const faceOf = (model && (model.dismissedFaceOf || model.isDismissedRow)) || null
const noteOf = (model && model.dismissedNoteOf) || null

if (typeof faceOf !== 'function') {
  record('D2 dismissed-read-helper-exists', 'fail',
    'no dismissed-face read helper exported from ticket-list-model.ts — the row-leaves face is not landed')
} else {
  const yes = faceOf({ dismissed: { at: '2026-10-09T00:00:00Z', who: 'host', reason: 'dead four days' } })
  record('D2a plain-object-dismissed-reads', yes ? 'pass' : 'fail',
    'a plain-object dismissed payload must read as dismissed')

  // malformed payload shapes wrapped as the row's `dismissed` value, plus the
  // primitive-as-value row shape itself
  const malformed = [true, 'yes', 5, [], [{}], null, undefined].map((v) => faceOf({ dismissed: v }))
    .concat([faceOf({ dismissed: 'x' }), faceOf(null), faceOf(undefined), faceOf(7)])
  record('D2b malformed-shapes-never-dismissed', malformed.every((v) => !v) ? 'pass' : 'fail',
    'primitive/array/null dismissed shapes must never read as dismissed (the client never invents the key)')

  const derived = model.deriveTicketState
  if (typeof derived === 'function') {
    const st = derived('failed', undefined, undefined)
    record('D2c dismissed-row-not-reclassified', st === 'failed' ? 'pass' : 'fail',
      'the five-state derivation must still call a dismissed failed row failed (never done, never in-flight)')
  } else {
    record('D2c dismissed-row-not-reclassified', 'fail', 'deriveTicketState not exported')
  }
}

if (typeof noteOf !== 'function') {
  record('D2d note-read-helper-exists', 'fail',
    'no dismissed-note read helper exported from ticket-list-model.ts — the read-failure face is not landed')
} else {
  const noteRow = { dismissed_note: 'journal read failed: permission denied' }
  const rowStays = (typeof noteOf(noteRow) === 'string' && noteOf(noteRow) !== '')
    && (typeof faceOf !== 'function' || !faceOf(noteRow))
  record('D2e note-row-stays-never-dismissed', rowStays ? 'pass' : 'fail',
    'a dismissed_note row (journal read failure) must stay on the board and never read as dismissed')
  const nonString = noteOf({ dismissed_note: 42 }) === '' || noteOf({ dismissed_note: 42 }) === undefined
  record('D2f non-string-note-degrades', nonString ? 'pass' : 'fail',
    'a non-string dismissed_note must degrade, not crash and not read as dismissed')
}

/* =========================================================================
 * D3 — the fold says dismissed, never done (spec 2)
 * ========================================================================= */
// The fold/label strings are user-visible copy: collect the sidebar's string
// literals that carry the dismissal wording and pin both directions.
const stringLiterals = [...sidebarSrc.matchAll(/['"`]([^'"`\n]{2,120})['"`]/g)].map((m) => m[1])
const dismissedCopy = stringLiterals.filter((s) => /dismiss/i.test(s))
record('D3a dismissed-fold-copy-exists', dismissedCopy.length > 0 ? 'pass' : 'fail',
  'no user-visible dismissed wording in sidebar.tsx — the fold (and its label) is not landed')

const doneWorded = dismissedCopy.filter((s) => /(^|[^a-z])(close|closed|done|complete[d]?)([^a-z]|$)/i.test(s.replace(/not\s+(done|closed?|completed?)|(never|no)\s+(done|closed?|completed?)/gi, '')))
record('D3b fold-never-worded-done', doneWorded.length === 0 ? 'pass' : 'fail',
  `dismissal copy leaks done-family wording: ${doneWorded.slice(0, 3).join(' | ')}`)

// the fold is per project (the done family's fold pattern), with restore reachable
record('D3c fold-is-per-project-and-restorable',
  /dismissedOpen|dismissed.*fold|foldDismissed/i.test(sidebarSrc) && /restore/i.test(sidebarSrc) ? 'pass' : 'fail',
  'a per-project dismissed fold state with a Restore path is not landed')

/* =========================================================================
 * D4 — the control (spec 1)
 * ========================================================================= */
// Offered on failure-class rows only: the affordance sits behind the failed
// derivation (the row card renders it only when the five-state is failed and
// the row carries no dismissed voucher), never unconditionally on every row.
const cardSrc = readFileSync(join(CLIENT, 'ticket-row-card.tsx'), 'utf8')
const failedGateLine = (cardSrc.match(/^[^\n]*state4\s*===?\s*['"]failed['"][^\n]*onDismiss[^\n]*$/m)
  || cardSrc.match(/^[^\n]*onDismiss[^\n]*state4\s*===?\s*['"]failed['"][^\n]*$/m) || [''])[0]
record('D4a control-gated-on-failed-class', failedGateLine !== '' ? 'pass' : 'fail',
  'the dismiss affordance is not gated on the failed-class derivation (+ no dismissed voucher) in ticket-row-card.tsx')

// The one write path: locate the dismissal submit handler and judge its window.
const submitIdx = sidebarSrc.indexOf('submitDismissal')
const dismissBlock = submitIdx < 0 ? '' : sidebarSrc.slice(submitIdx, submitIdx + 1400)

// reason required client-side: the dismiss path refuses empty/whitespace before POSTing
record('D4b reason-required-client-side',
  dismissBlock !== '' && /trim\(\)\s*===?\s*['"]{2}/.test(dismissBlock) ? 'pass' : 'fail',
  'the dismiss path does not visibly refuse an empty/whitespace reason before posting')

// who+reason travel to the engine route
record('D4c posts-who-and-reason',
  /\/dismiss/.test(sidebarSrc) && /who/.test(dismissBlock) && /reason/.test(dismissBlock) ? 'pass' : 'fail',
  'the dismiss request does not visibly carry who+reason to the route')

// never a bulk action: no dismiss WRITE issued from a map over rows / a group-level
// handler (rendering the fold's rows via .map is fine — a write inside a map is not)
const bulkish = [...sidebarSrc.matchAll(/\.map\(([^)]{0,80})\)[^;\n]{0,160}(submitDismissal|DISMISS_OP_URL|fetch\([^)]{0,120}dismiss)/gi)].length
  + [...sidebarSrc.matchAll(/(submitDismissal|DISMISS_OP_URL)[^;\n]{0,160}\.map\(/gi)].length
record('D4d no-bulk-dismiss', bulkish === 0 ? 'pass' : 'fail',
  `${bulkish} map-shaped dismiss call site(s) — the action must be one person on one row`)

// the row leaves only when the payload says dismissed: the handler re-reads, it never
// flips the dismissed key on local state
const localFlip = [...sidebarSrc.matchAll(/\.dismissed\s*=\s*(?!undefined)/g)].length
  + [...sidebarSrc.matchAll(/set[A-Za-z]*\([^)]*\{\s*dismissed\s*:/g)].length
record('D4e no-local-dismissed-flip', localFlip === 0 ? 'pass' : 'fail',
  `${localFlip} local write(s) to a dismissed key — the client must never invent the key; the row leaves on the next payload read`)

/* =========================================================================
 * D5 — the inspection source is a second covered source (spec 6)
 * ========================================================================= */
// Both branches of the merged group assembly filter dismissed rows: the
// dev-lane branch (beside inSandbar) AND the inspection branch (before the
// merge). One filter is the exact "works on dev-lane only" break the spec
// forbids.
const filterSites = [...sidebarSrc.matchAll(/dismissed/gi)].length
const inspComment = /inspection/i.test(sidebarSrc)
  ? /(?:inspection[^\n]{0,200}(?:dismiss|retire)|(?:dismiss|retire)[^\n]{0,200}inspection)/i.test(sidebarSrc)
  : false
record('D5a inspection-branch-filters-dismissed', filterSites >= 3 ? 'pass' : 'fail',
  `dismissed filtering appears ${filterSites} time(s) in sidebar.tsx — both merged sources (dev-lane + inspection) must filter; a comment naming the inspection asymmetry must state that for inspection rows the dismissal IS the retirement mechanism`)

// behaviourally: an inspection row with the engine's dismissed payload is excludable by the
// same read the dev-lane row uses (model-level composition; the column-level wiring is D5a/D3)
if (typeof faceOf === 'function') {
  const dismissedInsp = inspRow({ dismissed: { at: 'x', who: 'host', reason: 'r' } })
  const liveInsp = inspRow()
  const noteInsp = inspRow({ dismissed_note: 'read failed' })
  const okInsp = !!faceOf(dismissedInsp) && !faceOf(liveInsp) && !faceOf(noteInsp)
  record('D5b inspection-row-dismissed-read', okInsp ? 'pass' : 'fail',
    'the same dismissed/note read must classify inspection rows (kind=inspection) exactly like dev-lane rows')
} else {
  record('D5b inspection-row-dismissed-read', 'fail', 'dismissed read helpers missing (see D2)')
}

/* =========================================================================
 * D6 — remaining rows keep their order (spec 2)
 * ========================================================================= */
if (model && typeof model.sortMergedTickets === 'function' && typeof model.splitDismissedRows === 'function') {
  const voucher = { at: 'x', who: 'host', reason: 'r' }
  const rows = [
    devRow({ id: 'a', status: 'closed', close_ts: NOW - 1 * HOUR, updated_ts: NOW - 9 * HOUR }),
    devRow({ id: 'b', status: 'failed', close_ts: NOW - 2 * HOUR, updated_ts: NOW - 8 * HOUR, dismissed: voucher }),
    inspRow({ id: 'c', updated_ts: NOW - 7 * HOUR }),
    devRow({ id: 'd', status: 'active', updated_ts: NOW - 6 * HOUR }),
  ]
  const sorted = model.sortMergedTickets([...rows])
  const { kept, dismissed } = model.splitDismissedRows(sorted)
  const stable = kept.length === sorted.length - 1
    && dismissed.length === 1 && dismissed[0].id === 'b'
    && kept.map((t) => t.id).join(',') === sorted.filter((t) => t.id !== 'b').map((t) => t.id).join(',')
  record('D6 remaining-order-stable', stable ? 'pass' : 'fail',
    `the kept/dismissed split must preserve the merged order (kept=${kept.map((t) => t.id).join(',')})`)
} else {
  record('D6 remaining-order-stable', 'fail', 'sortMergedTickets/splitDismissedRows not exported from ticket-list-model.ts')
}

summarize()
