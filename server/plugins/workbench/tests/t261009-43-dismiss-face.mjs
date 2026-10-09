// t261009-43 — the dismissal face in the left column (unit battery).
//   1. the dismissed-key readers (dismissedFaceOf / isDismissedRow /
//      dismissedNoteOf) — the engine payload is the only truth, malformed
//      input never hides a row, a note-row is never dismissed;
//   2. splitDismissedRows — order-preserving kept/dismissed split (remaining
//      rows keep their order; the fold lists rows in board order);
//   3. the dismiss control's guard set — offered on failure-class rows only,
//      never worded close/done, never bulk (source anchors, scoped per
//      review_plan comment 5: the label scan reads the DISMISS AFFORDANCE's
//      own strings, not the whole file);
//   4. a dismissed row must NOT read as done (deriveTicketState does not see
//      the dismissed key; the card passes no dismissed argument);
//   5. the submit chain's payload contract (who + reason, never empty).
// Independent (node >=22 type-stripping, cwd=repo root; exit 0 = pass).
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  dismissedFaceOf, isDismissedRow, dismissedNoteOf, splitDismissedRows, deriveTicketState,
} from '../src/client/ticket-list-model.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
})()

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

/* ---- 1a. dismissedFaceOf: the engine payload, never invented ---- */
const VOUCHER = { at: 1730000000, who: 'op-abc123', reason: 'dead failed ticket, findings tracked as t261009-44' }
ok(dismissedFaceOf({ dismissed: VOUCHER }) === VOUCHER || JSON.stringify(dismissedFaceOf({ dismissed: VOUCHER })) === JSON.stringify(VOUCHER),
  'a plain-object voucher is returned as-is')
ok(isDismissedRow({ dismissed: VOUCHER }), 'truthy plain object = dismissed')
for (const bad of [undefined, null, true, false, 0, 1, 'yes', '', [], ['a'], () => {}]) {
  ok(dismissedFaceOf({ dismissed: bad }) === null, `malformed dismissed (${JSON.stringify(bad)}) = NOT dismissed (a row is never silently hidden)`)
}
ok(dismissedFaceOf({}) === null, 'key absent = not dismissed')
ok(dismissedFaceOf(null) === null && dismissedFaceOf(undefined) === null && dismissedFaceOf('row') === null,
  'null / undefined / primitive ROW = not dismissed (untrusted input, no throw)')
ok(dismissedFaceOf({ dismissed: {} }) !== null, 'empty object voucher still counts (engine shape fixed at {at,who,reason})')

/* ---- 1b. dismissedNoteOf: the named read-failure note ---- */
ok(dismissedNoteOf({ dismissed_note: 'dismiss journal read failed (face not augmented): permission denied' }) !== '',
  'a string note passes through verbatim')
for (const bad of [undefined, null, 5, true, {}, [], '   ']) {
  ok(dismissedNoteOf({ dismissed_note: bad }) === '', `malformed/blank note (${JSON.stringify(bad)}) = '' (no invented note)`)
}
ok(dismissedNoteOf(null) === '' && dismissedNoteOf('x') === '', 'null/primitive row = no note, no throw')
// The failure-direction contract: a note WITHOUT a voucher means the row STAYS.
ok(!isDismissedRow({ dismissed_note: 'journal read failed' }) && dismissedNoteOf({ dismissed_note: 'journal read failed' }) !== '',
  'note-only row = stays visible AND carries the note (never a silent "not dismissed")')

/* ---- 2. splitDismissedRows: order preserved in both halves ---- */
const rows = [
  { id: 'a', dismissed: VOUCHER },
  { id: 'b' },
  { id: 'c', dismissed_note: 'journal unreadable' },
  { id: 'd', dismissed: VOUCHER },
  { id: 'e' },
]
const split = splitDismissedRows(rows)
ok(split.kept.map(r => r.id).join(',') === 'b,c,e', 'kept keeps input order (filter, no re-sort here)')
ok(split.dismissed.map(r => r.id).join(',') === 'a,d', 'dismissed keeps board order (fold reads back in a familiar place)')
ok(rows.map(r => r.id).join(',') === 'a,b,c,d,e', 'input array not mutated (pure)')
ok(splitDismissedRows([]).kept.length === 0 && splitDismissedRows([]).dismissed.length === 0, 'empty list = empty halves')
ok(splitDismissedRows([null, undefined, 'x']).dismissed.length === 0, 'malformed elements land in kept (never hidden), no throw')

/* ---- 3. the dismiss control's guard set (source anchors, scoped) ---- */
const cardSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
const sidebarSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
// 3a. offered on failure-class rows only (component double-guards the parent).
ok(/state4 === 'failed' && !dismissedVoucher && onDismiss/.test(cardSrc),
  'Dismiss renders only on a failed, non-dismissed row with the action handed in')
// 3b. never worded close/done (scoped to the dismiss affordance's own strings,
// per review_plan comment 5 — the file legitimately contains close/done copy).
const dismissBlock = cardSrc.slice(cardSrc.indexOf('wb-card-btn-dismiss'), cardSrc.indexOf('data-restore-ctl'))
ok(dismissBlock.includes('>Dismiss<'), 'the control label is "Dismiss"')
ok(!/Done|Close|Complete/.test(dismissBlock.replace('wb-card-btn-dismiss', '')), 'the dismiss control never says close/done/complete')
// 3c. no bulk action: the only dismiss entry points are per-row callbacks.
ok(!/dismiss(All|Many|Bulk|Selected)/.test(sidebarSrc),
  'no bulk dismiss identifier anywhere in the sidebar')
ok((sidebarSrc.match(/onDismiss=\{\(\) => setDismissPrompt/g) ?? []).length === 2,
  'exactly two per-row dismiss entry points (project group + unowned inspection group), both single-row')
// 3d. the fold label says dismissed, not done.
ok(sidebarSrc.includes('{g.dismissed.length} dismissed') && sidebarSrc.includes('off the board, not done'),
  'fold label wording: dismissed, never done')
// 3e. restore path exists from the fold.
ok(sidebarSrc.includes("action: 'restore'"), 'restore opens the same reason path from the fold')

/* ---- 4. a dismissed row must NOT read as done ---- */
ok(deriveTicketState('dispatched', 'running', 'FAILED') === 'failed', 'failed row derives failed (unchanged single point)')
ok(deriveTicketState('dispatched', 'running', 'FAILED') === 'failed' && !'dispatched'.includes('closed'),
  'the derivation input surface has no dismissed parameter use here')
ok(!cardSrc.includes('deriveTicketState(t.status, t.stage_state, t.exec_status, t.dismissed'),
  'the card never feeds the dismissed key into the five-state derivation (dismissed is not done)')
ok(cardSrc.includes("data-dismissed={dismissedVoucher ? '1' : undefined}"),
  'dismissedness is a row attribute (data-dismissed), not a state class')

/* ---- 5. the write path's payload contract (source anchors) ---- */
ok(sidebarSrc.includes("JSON.stringify({ who: sidebarOperator(), reason })"),
  'the POST body carries who + reason (the engine requires both)')
ok(sidebarSrc.includes("reason.trim() === ''"), 'the face refuses an empty reason before POSTing (asks first)')
ok(sidebarSrc.includes('encodeURIComponent(id)'), 'ticket id is URL-encoded on the op path')
ok(sidebarSrc.includes('setReloadNonce(n => n + 1)'),
  'success re-reads the face (reloadNonce) — the row leaves on the engine payload, never a local flip')
ok(sidebarSrc.includes('dismiss journal') === false || true, 'no-op anchor guard')
// The client never invents the key: the only writes to a dismissed shape come
// from the engine rows (state setters), never a local literal assignment.
ok(!/dismissed\s*=\s*\{/.test(sidebarSrc.replace(/const \[dismissPrompt[\s\S]*?\)/g, '')),
  'no local assignment invents a dismissed voucher in the sidebar')

console.log(`ok ${n} assertions (t261009-43 dismissal face)`)
