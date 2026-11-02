#!/usr/bin/env node
/**
 * t261102-12: the named read states — model truth table, host verdict, panel wiring.
 *
 * The defect (measured 261101): seven inspection period tickets sat in the left column
 * with the row title "query timed out, refresh to retry" forever. Their workflows were
 * RUNNING in Temporal with a FAILED workflow task, so every snapshot query was refused
 * deterministically; the panel treated the refusal as a transient fault and re-polled it
 * every beat. Two lies had to go: a read that cannot succeed is not a timeout, and a
 * finished ticket is not a slow ticket.
 *
 * Covered here:
 *   A MODEL - readStateView names every receipt kind (no_poller / workflow_task_failed /
 *     terminal / not_found / transient / unknown) with its own state, whether a cause is
 *     available, and the polling rule; malformed input (null / array / scalar / missing
 *     keys) never throws and never invents a cause.
 *   B NO RE-POLL - a deterministic or finished state returns null from
 *     detailRepollDelayMs (the detail is NOT re-read); no_poller returns the slow beat
 *     (a worker may appear); a transient fault keeps the normal beat.
 *   C HOST VERDICT - `no_poller` and `workflow_task_failed` are 409 without `retryable`
 *     (never 503-with-retry, never 500-by-default); 404/410/503 keep their meanings; the
 *     engine's read face rides in its own `read_face` key, only for those kinds, and only
 *     as a plain object (the terminal `face` contract is untouched).
 *   D WIRING (source anchors) - the host attaches the face through the bounded bridge; the
 *     panel builds the view in openDetail, stops the detail re-poll, renders the panel, and
 *     the left column's row card shows the state by name.
 *
 * Offline, no browser, no Temporal, no console (never touches 3099/7233).
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  readStateView, isPermanentReadState, detailRepollDelayMs,
} from '../src/client/read-state.ts'
import {
  ticketShowHttpVerdict, ticketShowErrorReply, isNamedReadKind, NAMED_READ_KINDS,
} from '../src/host/ticket-error.ts'
import { readStateLabel } from '../src/client/ui-labels.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
})()

let passed = 0
let failed = 0
function ok(cond, label, detail = '') {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}${detail ? ` :: ${detail}` : ''}`) }
}

/* ---------------------------------------------------------------- A model */

// The real receipt shape the engine produces for the measured ticket (client.py
// _augment_read_failure_receipt + _classify_snapshot_failure): workflow_task_failed.
const WTF_FACE = {
  ticket: 't261101-25',
  queue: 'sandbar',
  queue_source: 'describe',
  deterministic: true,
  retryable: false,
  face_state: 'workflow_task_failed',
  durable: {
    status: 'RUNNING',
    queue: 'sandbar',
    queue_source: 'describe',
    face_state: 'workflow_task_failed',
    unavailable: 'unavailable(workflow_task_failed @ queue=sandbar ticket=t261101-25)',
    deterministic: true,
    retryable: false,
    retained: {
      source: 'execution history (WorkflowTaskFailed event)',
      available: true,
      failure_type: 'RestrictedWorkflowAccessError',
      failure_message: 'Cannot access os.path.join from inside a workflow.',
      event_id: 36,
      reason: 'last WorkflowTaskFailed event in the execution history',
    },
  },
}

{
  const v = readStateView('workflow_task_failed', WTF_FACE, 'deterministic refusal',
    't261101-25')
  ok(v.state === 'workflow_task_failed', 'A1 kind workflow_task_failed keeps its own name', v.state)
  ok(v.headline !== '' && !/timeout/i.test(v.headline), 'A2 the headline never says timeout', v.headline)
  ok(v.causeAvailable && /RestrictedWorkflowAccessError/.test(v.cause),
    'A3 the located cause rides verbatim', v.cause)
  ok(/WorkflowTaskFailed/.test(v.causeNote), 'A4 the cause names its source', v.causeNote)
  ok(v.retry === 'never', 'A5 a deterministic state is never retried', v.retry)
  ok(/not re-polled/i.test(v.pollNote), 'A6 the polling rule is stated in words', v.pollNote)
  ok(v.receiptError === 'deterministic refusal', 'A7 the engine receipt text rides')
  ok(v.facts.some(f => f.label === 'Queue' && f.value === 'sandbar'),
    'A8 the queue the ticket really polls is a rendered fact')
  ok(v.facts.some(f => f.value === 'RestrictedWorkflowAccessError'),
    'A9 the failure type is a rendered fact')
}

{
  const v = readStateView('no_poller', {
    ticket: 't-1', queue: 'sandbar-ticket-t-1', queue_source: 'describe',
    live_pollers: 0, face_state: 'no_poller',
  }, 'no_poller: ...', 't-1')
  ok(v.state === 'no_poller', 'A10 no_poller keeps its own name', v.state)
  ok(v.causeAvailable && /0|no live poller/i.test(v.cause) === true
    || /No live poller/.test(v.cause), 'A11 the cause names the missing poller', v.cause)
  ok(v.retry === 'slow', 'A12 no_poller is re-read on the slow beat, not the transient one', v.retry)
  ok(v.facts.some(f => f.label === 'Live pollers' && f.value === '0'),
    'A13 the poller count is rendered as the engine reported it')
}

{
  // A finished ticket whose workflow answered from the retained record.
  const v = readStateView('not_found', {
    face_state: 'retained',
    retained: {
      face_state: 'retained', project: 'sandbar', terminal_status: 'COMPLETED',
      closed_at: '2026-11-01T00:15:21+00:00', written_by: 'engine:client.ticket-close-out',
      source: '/tmp/projects/sandbar/data/tickets/t-2/closed.json',
      title: 'Inspection docs-sync · period 20261030', archived_at: '2026-11-01T00:15:21+00:00',
    },
  }, 'ticket not found', 't-2')
  ok(v.state === 'retained', 'A14 a gone workflow with a retained record reads as retained', v.state)
  ok(v.retry === 'never', 'A15 the retained answer is not re-polled', v.retry)
  ok(v.facts.some(f => f.value === 'COMPLETED'), 'A16 the outcome is readable from the record')
  ok(v.causeAvailable && /retained record/.test(v.cause), 'A17 the cause names the record', v.cause)
}

{
  const v = readStateView('not_found', {
    face_state: 'retained_unavailable',
    retained: { face_state: 'retained_unavailable', reason: 'no retained state for ticket t-3' },
  }, 'ticket not found', 't-3')
  ok(v.state === 'retained_unavailable', 'A18 no retained record is NAMED', v.state)
  ok(v.causeAvailable === false && /no retained state/.test(v.causeNote),
    'A19 the missing record names why', v.causeNote)
  ok(v.retry === 'never', 'A20 it is not spun as a transient retry', v.retry)
}

{
  // Malformed input: never throws, never invents a cause, still names a state.
  for (const [kind, face] of [[undefined, undefined], ['', null], ['no_poller', []],
    ['workflow_task_failed', 'nonsense'], [42, { durable: 'x' }]]) {
    const v = readStateView(kind, face, undefined, undefined)
    ok(typeof v.state === 'string' && v.state !== '', `A21 malformed (${String(kind)}) still named`, v.state)
    ok(v.causeNote !== '', `A22 malformed (${String(kind)}) says why the cause is absent`)
    ok(v.retry === 'never' || v.retry === 'slow' || v.retry === 'normal',
      `A23 malformed (${String(kind)}) carries a legal retry rule`, v.retry)
  }
}

{
  const v = readStateView('workflow_task_failed', {
    durable: { retained: { available: false, reason: 'history unreadable (RuntimeError: x)' } },
  }, 'x', 't-4')
  ok(v.causeAvailable === false && /retained_unavailable/.test(v.causeNote),
    'A24 an unreadable cause is named retained_unavailable', v.causeNote)
}

/* ---------------------------------------------------------------- B no re-poll */

{
  const wtf = readStateView('workflow_task_failed', WTF_FACE, '', 't-1')
  const np = readStateView('no_poller', { queue: 'q', live_pollers: 0 }, '', 't-2')
  const tr = readStateView('transient', null, '', 't-3')
  ok(detailRepollDelayMs(wtf, 5000, 30000) === null,
    'B1 a deterministic state is NOT re-read')
  ok(isPermanentReadState(wtf) === true, 'B2 isPermanentReadState agrees for it')
  ok(detailRepollDelayMs(np, 5000, 30000) === 30000,
    'B3 a no_poller state is re-read on the slow beat only')
  ok(detailRepollDelayMs(tr, 5000, 30000) === 5000,
    'B4 a transient fault keeps the normal beat')
  ok(detailRepollDelayMs(null, 5000, 30000) === 5000,
    'B5 no named state = the normal beat')
  const ret = readStateView('not_found', { face_state: 'retained' }, '', 't-4')
  ok(detailRepollDelayMs(ret, 5000, 30000) === null,
    'B6 a finished ticket read from its record is not re-polled')
}

/* ---------------------------------------------------------------- C host verdict */

{
  ok(ticketShowHttpVerdict('no_poller').status === 409, 'C1 no_poller is 409')
  ok(ticketShowHttpVerdict('no_poller').retryable === false, 'C2 no_poller is not retryable')
  ok(ticketShowHttpVerdict('workflow_task_failed').status === 409,
    'C3 workflow_task_failed is 409')
  ok(ticketShowHttpVerdict('workflow_task_failed').retryable === false,
    'C4 workflow_task_failed is not retryable')
  // The pre-existing meanings must not drift.
  ok(ticketShowHttpVerdict('not_found').status === 404, 'C5 not_found stays 404')
  ok(ticketShowHttpVerdict('terminal').status === 410, 'C6 terminal stays 410')
  ok(ticketShowHttpVerdict('transient').status === 503
    && ticketShowHttpVerdict('transient').retryable === true, 'C7 transient stays 503 retryable')
  ok(ticketShowHttpVerdict('internal').status === 500, 'C8 internal stays 500')
  ok(ticketShowHttpVerdict('something_new').status === 500, 'C9 unknown kind stays 500 (never 404)')
  ok(isNamedReadKind('no_poller') && isNamedReadKind('workflow_task_failed'),
    'C10 the named set is the two located causes')
  ok(!isNamedReadKind('terminal') && !isNamedReadKind('not_found'),
    'C11 terminal / not_found keep their own paths')
  ok(NAMED_READ_KINDS.length === 2, 'C12 the named set stays exactly two')
}

{
  const r = ticketShowErrorReply({ error: 'e', kind: 'workflow_task_failed' }, 't-1',
    undefined, WTF_FACE)
  ok(r.status === 409 && r.body.read_face !== undefined,
    'C13 the read face rides in its own key')
  ok(r.body.face === undefined, 'C14 the terminal face slot stays untouched')
  ok(r.body.retryable === undefined, 'C15 no retryable flag on a named state')
  const bad = ticketShowErrorReply({ error: 'e', kind: 'no_poller' }, 't-1', undefined, [1, 2])
  ok(bad.body.read_face === undefined, 'C16 a malformed face never rides')
  const notNamed = ticketShowErrorReply({ error: 'e', kind: 'transient' }, 't-1', undefined,
    WTF_FACE)
  ok(notNamed.body.read_face === undefined, 'C17 only the named kinds carry a read face')
  const term = ticketShowErrorReply({ error: 'e', kind: 'terminal' }, 't-1', { exec_status: 'FAILED' },
    WTF_FACE)
  ok(term.status === 410 && term.body.face !== undefined && term.body.read_face === undefined,
    'C18 terminal keeps face-only (t260919-02 contract held)')
}

/* ---------------------------------------------------------------- C' label table */

{
  ok(readStateLabel('workflow_task_failed') === 'Workflow task failed', 'C19 chip label mapped')
  ok(readStateLabel('no_poller') === 'No worker polling', 'C20 no_poller chip label mapped')
  ok(readStateLabel('a_new_state') === 'a_new_state', 'C21 an unknown state renders raw')
  ok(readStateLabel('') === '', 'C22 an empty state renders nothing')
}

/* ---------------------------------------------------------------- D wiring anchors */

{
  const indexSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  const nodeSrc = readFileSync(join(repo, 'server/plugins/workbench/node.ts'), 'utf8')
  const rowSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
  ok(indexSrc.includes("./read-state.ts"), 'D1 the panel consumes the model')
  ok(indexSrc.includes('readStateView('), 'D2 openDetail builds the named view')
  ok(indexSrc.includes('isPermanentReadState') && indexSrc.includes('detailRepollDelayMs'),
    'D3 the panel holds the no-re-poll rule')
  ok(indexSrc.includes('detailRepollDelayMs(readView, 5_000, 30_000)'),
    'D4 the poll loop applies the rule per state')
  ok(indexSrc.includes('data-testid="read-state-panel"'),
    'D5 the drawer renders the named-state panel')
  ok(indexSrc.includes('setReadStateFace(null)'),
    'D6 the state never outlives its ticket (cleared on open and on close)')
  ok(!indexSrc.includes('Detail load failed (transient query error), retrying: ${String(err instanceof Error ? err.message : err)}')
    || indexSrc.includes("kind === 'not_found'"),
    'D7 the named kinds are handled before the transient branch')
  ok(nodeSrc.includes('isNamedReadKind((r as any)?.kind)'),
    'D8 the host routes the named kinds through the read-face bridge')
  ok(nodeSrc.includes('fetchReadFace(parts[0])'), 'D9 the bridge reads the engine receipt once more')
  ok(nodeSrc.includes('sendTicketShowError(res, r, parts[0], undefined, readFace)'),
    'D10 the face rides in the fourth slot (the terminal slot stays untouched)')
  ok(rowSrc.includes('data-read-state={state}'),
    'D11 the left-column row card shows the named read state')
  ok(rowSrc.includes('read_state_note'), 'D12 the row card tooltip carries the engine note')
}

console.log(`SUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
