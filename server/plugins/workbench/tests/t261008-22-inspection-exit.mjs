/**
 * t261008-22 — voided inspection rows leave the blocked tier, and the exit block's
 * pure model refuses reason-less attempts by name (workbench client half).
 *
 * Legs:
 *  - deriveTicketState truth table: a voided row NEVER maps to 'blocked' (the state
 *    drives the left-column position — asserted on the returned state, not a class
 *    name); failed still wins; no voided key = zero behavior change.
 *  - ticketMergeTierOf: voided blocked row is no longer tier 0 (waiting/blocked/failed).
 *  - closeHealthBadgeOf: voided row carries the "Voided · findings were rejected"
 *    badge copy (void must not read as success; findings not erased).
 *  - inspectionExitVisible: inspection-only; blocked or voided; malformed input degrades.
 *  - buildExitPayload: reason-less rerun/void refused BY NAME; void carries ticket_id;
 *    missing instance/period named; ok payload carries project/instance/period/reason.
 * Zero react render, zero fetch, never touches 3099.
 */
import assert from 'node:assert/strict'
import {
  deriveTicketState, ticketMergeTierOf, closeHealthBadgeOf,
} from '../src/client/ticket-list-model.ts'
import {
  inspectionExitVisible, buildExitPayload,
} from '../src/client/inspection-exit-model.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- deriveTicketState: voided rows leave the blocked tier ----
ok(deriveTicketState('blocked', 'blocked', undefined) === 'blocked', 'blocked row stays blocked (no voided key = zero behavior change)')
ok(deriveTicketState('blocked', 'blocked', undefined, { who: 'host' }) === 'done', 'voided blocked row -> done (not blocked)')
ok(deriveTicketState('blocked', 'blocked', 'COMPLETED', { who: 'host' }) === 'done', 'voided completed row -> done')
ok(deriveTicketState('failed', 'failed', undefined, { who: 'host' }) === 'failed', 'failed still wins over voided (defensive order)')
ok(deriveTicketState('blocked', 'blocked', undefined, null) === 'blocked', 'voided=null degrades to no-void shape')
ok(deriveTicketState('blocked', 'blocked', undefined, 0) === 'blocked', 'voided=0 falsy degrades to no-void shape')
ok(deriveTicketState('blocked', 'blocked', undefined, 'yes') === 'done', 'voided truthy scalar -> done (defensive)')

// ---- merge tier: no longer the top tier ----
// The complaint shape: a blocked-completed inspection row as the console lists it
// (blocked status/stage_state face; exec_status absent on the row the left column
// consumed — the word 'blocked' is what ranked it tier 0 for six days).
const blockedRow = { status: 'blocked', stage_state: 'blocked',
  kind: 'inspection', blocked_reason: 'two findings blocks', voided: { who: 'host', reason: 'r' } }
const plainBlocked = { status: 'blocked', stage_state: 'blocked',
  kind: 'inspection', blocked_reason: 'two findings blocks' }
ok(ticketMergeTierOf('blocked', 'blocked', undefined, plainBlocked) === 0, 'plain blocked inspection row is tier 0 (the six-day complaint shape)')
ok(ticketMergeTierOf('blocked', 'blocked', undefined, blockedRow) > 0, 'voided row is NOT tier 0 — stops being the most prominent row')

// ---- badge copy: void is not a success, findings not erased ----
ok(closeHealthBadgeOf(blockedRow) === 'Voided · findings were rejected', 'voided badge names the disposition and keeps the rejection statement')
ok(closeHealthBadgeOf(plainBlocked) === '', 'plain blocked (no exec face) keeps the existing badge shape (no new copy)')

// ---- exit block visibility ----
ok(inspectionExitVisible({ kind: 'inspection', status: 'blocked' }) === true, 'blocked inspection row shows the exit block')
ok(inspectionExitVisible({ kind: 'inspection', status: 'blocked', voided: { who: 'h' } }) === true, 'voided row keeps the block (renders the disposition)')
ok(inspectionExitVisible({ kind: 'inspection', status: 'running' }) === false, 'running inspection row: no exit block')
ok(inspectionExitVisible({ kind: 'dev', status: 'blocked' }) === false, 'non-inspection row: no exit block')
ok(inspectionExitVisible(null) === false, 'null detail degrades to hidden')
ok(inspectionExitVisible(undefined) === false, 'undefined detail degrades to hidden')
ok(inspectionExitVisible({ status: 'blocked' }) === false, 'row without kind degrades to hidden (untrusted input)')

// ---- exit payload: reason-less refused by name, shapes named ----
const detail = { id: 't261002-12', instance_id: 'integration-tests', period: '20261002' }
const rr = buildExitPayload('rerun', detail, 'sandbar', '')
ok(rr.ok === false && rr.error.includes('reason is required'), `reason-less rerun refused by name: ${rr.ok === false ? rr.error : ''}`)
const rv = buildExitPayload('void', detail, 'sandbar', '   ')
ok(rv.ok === false && rv.error.includes('reason is required'), 'whitespace-only void refused by name')
ok(buildExitPayload('rerun', { period: '20261002' }, 'sandbar', 'r').ok === false, 'missing instance refused')
ok(buildExitPayload('rerun', { instance_id: 'i' }, 'sandbar', 'r').ok === false, 'missing period refused')
const pv = buildExitPayload('void', detail, 'sandbar', 'two findings blocks; parser refused')
ok(pv.ok === true && pv.payload.ticket_id === 't261002-12', 'void payload carries ticket_id')
ok(pv.payload.instance === 'integration-tests' && pv.payload.period === '20261002' && pv.payload.reason === 'two findings blocks; parser refused', 'void payload fields verbatim')
const pr = buildExitPayload('rerun', detail, undefined, 'r')
ok(pr.ok === true && pr.payload.project === '', 'missing projectKey degrades to empty project (server names it if it matters)')

console.log(`t261008-22-inspection-exit: ${n} assertions passed`)
