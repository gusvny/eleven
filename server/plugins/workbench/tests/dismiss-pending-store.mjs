#!/usr/bin/env node
/**
 * tests/dismiss-pending-store.mjs — the pending-dismissal store and the refusal
 * face classifier (t261031-06, L1).
 *
 * Run directly: node server/plugins/workbench/tests/dismiss-pending-store.mjs
 *
 * Covers:
 *   A. store lifecycle: begin = inflight with the typed reason; the engine's
 *      refusal lands verbatim; an accept forgets the row; a cancel forgets it.
 *   B. one entry per (project key, ticket id); a second attempt replaces the
 *      first; the newest entry owns the single prompt slot.
 *   C. subscribers: notified on every change, one throwing subscriber does not
 *      stop the others, snapshot reference stable while nothing changes.
 *   D. the scope anchor: the state survives a MODULE RE-EVALUATION (the same
 *      module imported again under a different URL specifier = a fresh module
 *      instance, exactly what a plugin re-register does to this bundle). This is
 *      the property the reproduced loss needs; a bare module-level Map fails it.
 *   E. the classifier names WHICH condition stopped the prompt from rendering
 *      (group gone / group collapsed / row gone) and leaves renderable refusals
 *      alone; the line quotes the engine's refusal verbatim.
 */
import assert from 'node:assert/strict'

const STORE_URL = new URL('../src/client/dismiss-pending-store.ts', import.meta.url)
const FACE_URL = new URL('../src/client/dismiss-notice-face.ts', import.meta.url)
const S = await import(STORE_URL.href)
const F = await import(FACE_URL.href)

const A = { projectKey: 'alpha', ticketId: 'tk-a', action: 'dismiss' }
const B = { projectKey: 'alpha', ticketId: 'tk-b', action: 'dismiss' }
const REFUSAL = 'the engine refused: dismissal reason is too short'

S.resetPendingDismissals()

// ------------------------------------------------------------------ A. lifecycle
S.beginPendingDismissal(A, 'duplicate of tk-0', 1000)
let entry = S.findPendingDismissal(A)
assert.equal(entry.phase, 'inflight', 'A1 begin = inflight')
assert.equal(entry.reason, 'duplicate of tk-0', 'A2 the typed reason is kept')
assert.equal(entry.notice, '', 'A3 no notice while in flight')
assert.equal(S.pendingDismissalForPrompt()?.ticketId, 'tk-a', 'A4 the in-flight row owns the slot')

S.notePendingDismissalRefusal(A, REFUSAL, 1000)
entry = S.findPendingDismissal(A)
assert.equal(entry.phase, 'refused', 'A5 a refusal flips the phase')
assert.equal(entry.notice, REFUSAL, 'A6 the refusal is stored verbatim')
assert.equal(entry.reason, 'duplicate of tk-0', 'A7 the refusal keeps the reason for a retry')

S.beginPendingDismissal(B, 'second row')
S.notePendingDismissalRefusal(B, REFUSAL, 2000)
S.forgetPendingDismissal(A)
assert.equal(S.findPendingDismissal(A), undefined, 'A8 an accept forgets the row')
assert.deepEqual(S.getPendingDismissals().map(e => e.ticketId), ['tk-b'], 'A9 only the live row remains')

// a refusal can land after the sending instance is gone: the store must be able
// to carry it alone (no prior begin on this instance)
S.notePendingDismissalRefusal(A, REFUSAL, 3000)
assert.equal(S.findPendingDismissal(A)?.notice, REFUSAL, 'A10 a late refusal is carried alone')
S.forgetPendingDismissal(A)
S.forgetPendingDismissal(B)
assert.deepEqual(S.getPendingDismissals(), [], 'A11 forget leaves an empty store')

// ------------------------------------------------- B. one entry per row, newest wins
S.beginPendingDismissal(A, 'first try')
S.beginPendingDismissal(A, 'second try')
assert.equal(S.getPendingDismissals().length, 1, 'B1 one entry per (project, ticket)')
assert.equal(S.findPendingDismissal(A).reason, 'second try', 'B2 the new attempt replaces the old')
// the same ticket id under ANOTHER project is a different row
S.beginPendingDismissal({ projectKey: '', ticketId: 'tk-a', action: 'dismiss' }, 'unowned row')
assert.equal(S.getPendingDismissals().length, 2, 'B3 the project key is part of the row identity')
assert.notEqual(S.pendingDismissalKey('alpha', 'tk-a'), S.pendingDismissalKey('', 'tk-a'),
  'B4 keys do not collide across a blank project key')
S.beginPendingDismissal(B, 'later row')
assert.equal(S.pendingDismissalForPrompt().ticketId, 'tk-b', 'B5 the newest entry owns the slot')

// ------------------------------------------------------------- C. subscriber rules
let calls = 0
let threw = 0
const unsubThrow = S.subscribePendingDismissals(() => { threw += 1; throw new Error('subscriber fault') })
const unsubCount = S.subscribePendingDismissals(() => { calls += 1 })
const snapshotBefore = S.getPendingDismissals()
assert.equal(S.getPendingDismissals(), snapshotBefore, 'C1 the snapshot reference is stable')
S.setPendingDismissalReason(B, 'edited reason')
assert.ok(calls >= 1 && threw >= 1, 'C2 every subscriber is called, a throwing one does not stop the rest')
assert.equal(S.findPendingDismissal(B).reason, 'edited reason', 'C3b the edit landed')
// C3: the snapshot is rebuilt once per change and then reused while nothing
// changes (two reads in a row return the same reference), and it is no longer
// the pre-edit reference (C4 pins the rebuild itself).
const afterEdit = S.getPendingDismissals()
assert.equal(S.getPendingDismissals(), afterEdit, 'C3 the snapshot is reused while nothing changes')
assert.notEqual(afterEdit, snapshotBefore, 'C3a the change rebuilt the snapshot reference')
const snapshotAfter = S.getPendingDismissals()
assert.notEqual(snapshotAfter, snapshotBefore, 'C4 a change rebuilds the snapshot reference')
const callsBefore = calls
S.setPendingDismissalReason(B, 'edited reason')
assert.equal(calls, callsBefore, 'C5 an identical reason is not a change (no notification)')
unsubThrow()
unsubCount()
const callsAfterUnsub = calls
S.forgetPendingDismissal(B)
assert.equal(calls, callsAfterUnsub, 'C6 an unsubscribed listener is not called')

// ---------------------------------------------- D. the scope anchor (re-evaluation)
S.resetPendingDismissals()
S.beginPendingDismissal(A, 'across a re-register')
S.notePendingDismissalRefusal(A, REFUSAL, 4000)
const S2 = await import(`${STORE_URL.href}?reloaded=1`)
assert.notEqual(S2.getPendingDismissals, S.getPendingDismissals, 'D0 the second import is a real second module instance')
assert.equal(S2.findPendingDismissal(A)?.notice, REFUSAL,
  'D1 the pending refusal survives a module re-evaluation (a bare module-level Map would be empty here)')
S2.forgetPendingDismissal(A)
assert.equal(S.findPendingDismissal(A), undefined,
  'D2 one store, not two: the second instance writes what the first reads')

// ------------------------------------------------------ E. the refusal face classifier
const face = (over = {}) => ({
  groups: [
    { projectKey: 'alpha', collapsed: false, ticketIds: ['tk-a', 'tk-b'], dismissedIds: ['tk-d'] },
    { projectKey: 'beta', collapsed: true, ticketIds: ['tk-c'], dismissedIds: [] },
  ],
  unownedOnFace: true,
  unownedIds: ['tk-u'],
  ...over,
})
const refused = (target, notice = REFUSAL) => ({
  ...target, reason: 'r', phase: 'refused', notice, at: 1,
})

S.resetPendingDismissals()
const inflightOnly = [ { ...A, reason: 'r', phase: 'inflight', notice: '', at: 1 } ]
assert.deepEqual(F.strandedRefusals(inflightOnly, face()), [], 'E1 an in-flight entry is not stranded')

const renderable = F.strandedRefusals([refused(A)], face())
assert.deepEqual(renderable, [], 'E2 a refused row still on the face renders in its prompt slot')

const groupGone = F.strandedRefusals([refused({ projectKey: 'gone', ticketId: 'tk-x', action: 'dismiss' })], face())
assert.equal(groupGone.length, 1, 'E3 a missing project block strands the refusal')
assert.equal(groupGone[0].condition, 'group-gone', 'E4 the condition is named group-gone')
assert.match(groupGone[0].detail, /"gone"/, 'E5 the detail names the project key that is not on the face')

const collapsed = F.strandedRefusals([refused({ projectKey: 'beta', ticketId: 'tk-c', action: 'dismiss' })], face())
assert.equal(collapsed[0].condition, 'group-collapsed', 'E6 a folded block is named group-collapsed')

const rowGone = F.strandedRefusals([refused({ projectKey: 'alpha', ticketId: 'tk-vanished', action: 'dismiss' })], face())
assert.equal(rowGone[0].condition, 'row-gone', 'E7 a vanished row is named row-gone')
assert.match(rowGone[0].detail, /row is no longer on the face/, 'E8 the row-gone text is literally true')

const dismissedRow = F.strandedRefusals([refused({ projectKey: 'alpha', ticketId: 'tk-d', action: 'restore' })], face())
assert.deepEqual(dismissedRow, [], 'E9 a row in the dismissed fold is still on the face')

const unowned = F.strandedRefusals([
  refused({ projectKey: '', ticketId: 'tk-u', action: 'dismiss' }),
  refused({ projectKey: '', ticketId: 'tk-zz', action: 'dismiss' }),
  refused({ projectKey: '', ticketId: 'tk-u', action: 'dismiss' }),
], face())
// The blank-key group has its own row test: the row that IS on the inspection
// face renders in its slot (no strand), and only the absent row is stranded -
// a repeated ticket id is the same row, never a second strand.
assert.deepEqual(unowned.map(s => s.condition), ['row-gone'], 'E10 the blank-key group has its own row test')
assert.deepEqual(unowned.map(s => s.entry.ticketId), ['tk-zz'],
  'E10b only the absent row is stranded (the served row keeps its prompt slot)')

const unownedGone = F.strandedRefusals([
  refused({ projectKey: '', ticketId: 'tk-u', action: 'dismiss' }),
], face({ unownedOnFace: false }))
assert.equal(unownedGone[0].condition, 'group-gone', 'E11 an absent inspection group is named')

const line = F.strandedRefusalLine(rowGone[0])
assert.match(line, /Dismiss of tk-vanished was refused/, 'E12 the line names the action and the ticket')
assert.match(line, /the row is no longer on the face/, 'E13 the line says what the condition means')
// E13b: the visible line names the condition by the SAME token the face carries in
// its data-dismiss-unrenderable-condition attribute, so a reader of the printed
// line and a reader of the DOM never name the thing differently.
assert.ok(line.includes('row-gone'), 'E13b the line names the condition token')
assert.ok(line.indexOf('row-gone') < line.indexOf('the row is no longer on the face'),
  'E13c the token comes before the plain-words clause')
assert.ok(line.includes(JSON.stringify(REFUSAL)), 'E14 the line carries the engine refusal verbatim (quoted)')
assert.ok(!/there is no/i.test(line), 'E15 the line never claims a thing is absent unless it is (no "there is no X" phrasing)')

const keys = F.strandedKeys(rowGone)
assert.equal(keys.size, 1, 'E16 strand keys are unique per row')
assert.ok(keys.has(S.pendingDismissalKey('alpha', 'tk-vanished')), 'E17 strand keys use the store row identity')

S.resetPendingDismissals()
console.log('PASS dismiss-pending-store: store lifecycle, one-row identity, subscribers, re-evaluation anchor, refusal face classifier')
