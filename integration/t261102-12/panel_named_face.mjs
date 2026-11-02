#!/usr/bin/env node
/**
 * t261102-12 console-half leg (called by sc_t26110212_named_read_state.py).
 *
 * Input: a JSON file holding the engine receipts the python leg just produced — the REAL
 * receipts of client.py, not fixtures written by hand:
 *   closed_no_poller / retained / workflow_task_failed / no_poller /
 *   transient_with_live_poller / retained_unavailable.
 *
 * What it proves (the seam the measured bug lived in: the engine named one thing and the
 * console rendered another):
 *   G-A a closed ticket's answer is a plain success — no named failure state, no re-poll;
 *   G-B a retained answer renders as `retained` and is NEVER re-read as a live ticket;
 *   G-C a deterministic workflow-task failure renders by name (cause included) and the
 *       console schedules NO further detail read;
 *   G-D a no_poller renders by name with the queue the execution reports and is re-read
 *       on the SLOW beat only;
 *   G-E a real transient read keeps the normal beat (the fix did not freeze recoverable
 *       faults);
 *   G-F a ticket with neither a live read nor a retained record renders
 *       `retained_unavailable` and is not re-read.
 *
 * Usage: node panel_named_face.mjs <receipts.json> <repo-root>
 * Exit: 0 = every leg green, 1 = red, 2 = environment failure (unreadable input).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const [feedPath, repoArg] = process.argv.slice(2)
if (!feedPath || !repoArg) {
  console.error('ENV_FAIL usage: node panel_named_face.mjs <receipts.json> <repo-root>')
  process.exit(2)
}

let receipts
try {
  receipts = JSON.parse(readFileSync(feedPath, 'utf8'))
} catch (err) {
  console.error(`ENV_FAIL receipts unreadable: ${String(err?.message ?? err)}`)
  process.exit(2)
}

const plugin = join(repoArg, 'server/plugins/workbench')
let readStateView, detailRepollDelayMs
let ticketShowHttpVerdict
try {
  // Two separate imports (no ASI hazard: a statement starting with "(" after a call
  // expression is parsed as a CALL of that expression).
  const stateModel = await import(
    pathToFileURL(join(plugin, 'src/client/read-state.ts')).href)
  readStateView = stateModel.readStateView
  detailRepollDelayMs = stateModel.detailRepollDelayMs
  const verdictModel = await import(
    pathToFileURL(join(plugin, 'src/host/ticket-error.ts')).href)
  ticketShowHttpVerdict = verdictModel.ticketShowHttpVerdict
} catch (err) {
  console.error(`ENV_FAIL panel model unimportable: ${String(err?.message ?? err)}`)
  process.exit(2)
}

let passed = 0
const fails = []
function ok(cond, label, detail = '') {
  if (cond) { passed++; console.log(`PASS ${label}`) }
  else { fails.push(label); console.log(`FAIL ${label}${detail ? `: ${detail}` : ''}`) }
}

const NORMAL_MS = 5000
const SLOW_MS = 30000

function viewOf(receipt) {
  if (receipt === null || typeof receipt !== 'object') return null
  const face = receipt.face ?? receipt.read_face
  return readStateView(receipt.kind, face, receipt.error, receipt.ticket_id)
}

// ---- G-A: a closed ticket is a plain success -------------------------------------
{
  const r = receipts.closed_no_poller
  ok(r?.ok === true, 'G-A1 the closed read is a success (no named failure)',
    JSON.stringify(r ?? null).slice(0, 160))
  ok(r?.result?.exec_status === 'COMPLETED', 'G-A2 the outcome rides on the answer')
}

// ---- G-B: the retained record -----------------------------------------------------
{
  const r = receipts.retained
  const v = viewOf(r)
  ok(v?.state === 'retained', 'G-B1 a closed ticket with a retained record renders retained',
    v?.state ?? 'none')
  ok(detailRepollDelayMs(v, NORMAL_MS, SLOW_MS) === null,
    'G-B2 the retained answer is never re-read as a live ticket')
  ok(/retained record/.test(v?.cause ?? ''), 'G-B3 the cause names the record', v?.cause)
  ok(ticketShowHttpVerdict(r?.kind).status === (r?.kind === 'not_found' ? 404 : 409)
    || r?.kind === 'transient',
    'G-B4 the HTTP verdict stays a named level (404/409/503, never a silent 200)',
    String(r?.kind))
}

// ---- G-C: the deterministic refusal ----------------------------------------------
{
  const r = receipts.workflow_task_failed
  const v = viewOf(r)
  ok(r?.kind === 'workflow_task_failed', 'G-C1 the engine names the deterministic kind',
    String(r?.kind))
  ok(ticketShowHttpVerdict(r?.kind).status === 409
    && ticketShowHttpVerdict(r?.kind).retryable === false,
    'G-C2 the host answers 409 without a retry flag')
  ok(v?.state === 'workflow_task_failed', 'G-C3 the panel renders the state by name',
    v?.state ?? 'none')
  ok(/RestrictedWorkflowAccessError/.test(v?.cause ?? ''),
    'G-C4 the cause from the execution history is rendered', v?.cause)
  ok(/not re-polled/i.test(v?.pollNote ?? ''),
    'G-C5 the panel says no further read is scheduled', v?.pollNote)
  ok(detailRepollDelayMs(v, NORMAL_MS, SLOW_MS) === null,
    'G-C6 the console schedules NO further detail read (the measured forever-timeout)')
  ok(!/transient query error/i.test(v?.pollNote ?? ''),
    'G-C7 the deterministic state is never called transient')
}

// ---- G-D: no poller --------------------------------------------------------------
{
  const r = receipts.no_poller
  const v = viewOf(r)
  ok(r?.kind === 'no_poller', 'G-D1 the engine names the missing poller', String(r?.kind))
  ok(v?.state === 'no_poller', 'G-D2 the panel renders no_poller by name', v?.state ?? 'none')
  ok(v?.facts.some(f => f.label === 'Queue' && f.value === 'sandbar-ticket-t-d'),
    'G-D3 the rendered queue is the one the execution reports',
    JSON.stringify(v?.facts ?? []).slice(0, 200))
  ok(detailRepollDelayMs(v, NORMAL_MS, SLOW_MS) === SLOW_MS,
    'G-D4 it is re-read on the slow beat only (a worker may appear)')
}

// ---- G-E: a genuine transient fault keeps the normal beat ------------------------
{
  const r = receipts.transient_with_live_poller
  const v = viewOf(r)
  ok(r?.kind !== 'no_poller', 'G-E1 a live poller is never reported as no_poller',
    String(r?.kind))
  ok(detailRepollDelayMs(v, NORMAL_MS, SLOW_MS) === NORMAL_MS,
    'G-E2 a real transient fault keeps the normal beat (nothing was frozen)',
    String(detailRepollDelayMs(v, NORMAL_MS, SLOW_MS)))
}

// ---- G-F: retained unavailable ---------------------------------------------------
{
  const r = receipts.retained_unavailable
  const v = viewOf(r)
  ok(v?.state === 'retained_unavailable', 'G-F1 it renders retained_unavailable by name',
    v?.state ?? 'none')
  ok(detailRepollDelayMs(v, NORMAL_MS, SLOW_MS) === null,
    'G-F2 it is not left as an endless transient retry')
  ok(/no retained state/.test(v?.causeNote ?? ''),
    'G-F3 the absence names itself', v?.causeNote)
}

// ---- one summary line for the python leg ----------------------------------------
console.log(`PANEL pass=${passed} fail=${fails.length}`)
process.exit(fails.length > 0 ? 1 : 0)
