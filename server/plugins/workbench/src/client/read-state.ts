/**
 * read-state.ts — the NAMED read states of a ticket detail read (t261102-12).
 *
 * Why this module exists (measured 261101): the left column listed seven inspection
 * period tickets whose rows said "query timed out, refresh to retry" forever. Their
 * workflow tasks were in a FAILED state, so the server refuses every snapshot query
 * ("Unable to query workflow due to Workflow Task in failed state") — a DETERMINISTIC
 * refusal. The detail panel called that a transient fault and re-polled it every beat,
 * so the operator saw a timeout that could never clear, while a refresh could never
 * help either.
 *
 * Contract: every read failure that has a located cause becomes a NAMED state with its
 * own words, and the panel stops treating it as jitter. This module is the one pure
 * place that turns the engine's receipt (kind + face) into a renderable view. It is
 * intentionally shallow-bound: it reads only the engine's public receipt keys, so a
 * refactor inside the engine never breaks it.
 *
 * Honesty rules (same family as terminal-face.ts):
 *  - malformed / missing input never throws and never invents a cause: the state is
 *    still named and the missing part says why it is unavailable;
 *  - the receipt's own error text always rides (the operator reads the engine's words);
 *  - a state may not be retried as jitter once it is deterministic: `retry` says so and
 *    the caller obeys it (never the other way round).
 *
 * No React, no DOM, no IO: node can import it directly for behaviour tests.
 */

/** The named read states this module renders. */
export type ReadStateName =
  | 'no_poller'
  | 'workflow_task_failed'
  | 'terminal'
  | 'retained'
  | 'retained_unavailable'
  | 'not_found'
  | 'transient'
  | 'internal'

/** How the caller may re-read the state.
 *  never = a finished or deterministic state (no auto re-poll, no "refresh will help");
 *  slow  = a named state that a platform actor can heal (a worker appearing), so it is
 *          re-read on the slow beat, never on the transient beat;
 *  normal = an ordinary transient fault (the existing poll behaviour). */
export type ReadStateRetry = 'never' | 'slow' | 'normal'

export interface ReadStateFact {
  label: string
  value: string
}

export interface ReadStateView {
  /** The named state (always one of the names above — never empty). */
  state: ReadStateName
  /** One short headline naming the state (never empty, always English). */
  headline: string
  /** Whether the cause is known (false → causeNote says why it is not). */
  causeAvailable: boolean
  /** The located cause as one line ('' when unavailable). */
  cause: string
  /** Always non-empty: the source of the cause, or why no cause could be read. */
  causeNote: string
  /** Rendered key/value facts ('' values are omitted, never faked). */
  facts: ReadStateFact[]
  /** What automatic re-reading does next. */
  retry: ReadStateRetry
  /** One line stating the polling rule in the operator's words (never empty). */
  pollNote: string
  /** The engine's own error text (verbatim; '' only when the caller had none). */
  receiptError: string
  ticketId: string
}

/** Headlines per state (the ONLY place these words live). */
const HEADLINES: Record<ReadStateName, string> = {
  no_poller: 'No worker polls this ticket',
  workflow_task_failed: 'Workflow task failed — this ticket cannot be read',
  terminal: 'Ticket ended (terminal state)',
  retained: 'Read from retained state (workflow not running)',
  retained_unavailable: 'No retained state and the workflow is not readable',
  not_found: 'No such workflow',
  transient: 'Read failed (transient)',
  internal: 'Read failed (unexpected answer)',
}

/** What auto re-reading does, per state, in the operator's words. */
const POLL_NOTES: Record<ReadStateName, string> = {
  no_poller: 'Named state, slow re-read only: a worker must appear on this queue first.',
  workflow_task_failed:
    'Deterministic state, not re-polled: retrying the read cannot help until the workflow task stops failing.',
  terminal: 'Terminal state, not re-polled: a closed workflow no longer answers.',
  retained: 'Read from the retained record, not re-polled as a live workflow read.',
  retained_unavailable:
    'Not re-polled: neither a live read nor a retained record is available for this ticket.',
  not_found: 'Not re-polled: no workflow with this id exists on this namespace.',
  transient: 'Transient fault: auto re-read on the next beat.',
  internal: 'Not re-polled as transient: the answer was malformed — a defect, not jitter.',
}

const NAMED = new Set<string>(Object.keys(HEADLINES))

/** str consume: non-string → '' (malformed degrade, never throws). */
function strOf(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** plain-object consume: anything else → null (arrays and null are not faces). */
function objOf(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null
}

/** Finite number consume: anything else → null (0 is a real count, keep it). */
function numOf(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** The engine's read face nests its durable facts here (client.py). */
function durableOf(face: Record<string, unknown> | null): Record<string, unknown> {
  const d = objOf(face?.durable)
  return d ?? {}
}

/** The retained record inside a read face. The engine puts it under
 *  `face.durable.retained` on the detail receipt and under `face.retained` on the
 *  ticket-list row face — read both, prefer the durable one (the detail receipt). */
function retainedOf(face: Record<string, unknown> | null,
                    durable: Record<string, unknown> = {}): Record<string, unknown> {
  return objOf(durable.retained) ?? objOf(face?.retained) ?? {}
}

/**
 * Turn one failed detail read into its named view.
 *
 * @param kind  the receipt kind (`no_poller` / `workflow_task_failed` / `not_found` /
 *              `terminal` / `transient` / missing) — the engine's classification.
 * @param face  the engine read face (the `read_face` key of the HTTP body, or `face`).
 * @param errorText the receipt's own error string (verbatim, may be '').
 * @param ticketId the id the read was for ('' when unknown).
 */
export function readStateView(
  kind: unknown,
  face: unknown,
  errorText: unknown,
  ticketId: unknown,
): ReadStateView {
  const receiptError = strOf(errorText)
  const id = strOf(ticketId)
  const f = objOf(face)
  const dur = durableOf(f)
  const ret = retainedOf(f, dur)
  const receipt = strOf(kind)
  // The face may name its own state (engine: face_state) — the face is the finer signal
  // (a transient receipt can carry the retained outcome; a not_found receipt carries
  // retained / retained_unavailable).
  const faceState = strOf(f?.face_state)
  let state: ReadStateName = 'internal'
  if (receipt === 'workflow_task_failed') state = 'workflow_task_failed'
  else if (receipt === 'no_poller') state = 'no_poller'
  else if (receipt === 'terminal') state = 'terminal'
  else if (receipt === 'not_found') {
    // A gone workflow is answered from its retained record when one exists. Without one
    // the state is still named: 'retained_unavailable' when the receipt says the record
    // was looked for and is absent, otherwise the plain "no such workflow".
    state = faceState === 'retained' ? 'retained'
      : faceState === 'retained_unavailable' ? 'retained_unavailable'
        : 'not_found'
  } else if (receipt === 'transient') {
    state = faceState === 'retained' ? 'retained'
      : faceState === 'retained_unavailable' ? 'retained_unavailable'
        : 'transient'
  } else if (NAMED.has(receipt)) state = receipt as ReadStateName
  else if (faceState !== '' && NAMED.has(faceState)) state = faceState as ReadStateName

  const facts: ReadStateFact[] = []
  const push = (label: string, value: unknown) => {
    const v = strOf(value)
    if (v !== '') facts.push({ label, value: v })
  }
  const queue = strOf(dur.queue) || strOf(f?.queue)
  const queueSource = strOf(dur.queue_source) || strOf(f?.queue_source)
  push('Queue', queue)
  push('Queue source', queueSource)
  const live = numOf(f?.live_pollers) ?? numOf(dur.live_pollers)
  if (live !== null) push('Live pollers', String(live))
  push('Workflow status', dur.status)
  push('Last known stage', dur.last_stage_available === true ? strOf(dur.last_stage) : '')
  const retainedSource = strOf(ret.source)
  push('Retained source', retainedSource)
  if (strOf(ret.failure_type) !== '') push('Workflow task failure', strOf(ret.failure_type))
  if (strOf(ret.failure_message) !== '') push('Cause message', strOf(ret.failure_message))
  push('Terminal status', strOf(ret.terminal_status) || strOf(f?.terminal_status))
  push('Closed at', strOf(ret.closed_at) || strOf(f?.closed_at))
  push('Closed by', strOf(ret.written_by) || strOf(f?.written_by))
  push('Ticket title (from the retained record)', strOf(ret.title))
  push('Archived at', strOf(ret.archived_at))

  let cause = ''
  let causeNote = ''
  if (state === 'workflow_task_failed') {
    const msg = strOf(ret.failure_message)
    const type = strOf(ret.failure_type)
    if (msg !== '' || type !== '') {
      cause = [type, msg].filter(x => x !== '').join(': ')
      causeNote = 'Cause: the last WorkflowTaskFailed event in the execution history'
    } else {
      causeNote = strOf(ret.reason) !== ''
        ? `Cause unavailable (retained_unavailable): ${strOf(ret.reason)}`
        : ('Cause unavailable (retained_unavailable): the execution history carries no '
          + 'WorkflowTaskFailed cause')
    }
  } else if (state === 'no_poller') {
    const where = queue === '' ? 'the ticket queue' : `queue ${queue}`
    cause = `No live poller on ${where}, so the snapshot read has no one to answer it`
    causeNote = queueSource === 'describe'
      ? 'Cause: the queue the execution itself reports'
      : 'Cause: the queue derived from the ticket id (the execution reported none)'
  } else if (state === 'retained') {
    cause = retainedSource !== ''
      ? `The workflow is not readable; the outcome comes from the retained record (${retainedSource})`
      : 'The workflow is not readable; the outcome comes from the retained record'
    causeNote = 'Cause: the on-disk record the engine wrote when the ticket closed'
  } else if (state === 'retained_unavailable') {
    const why = strOf(ret.reason)
    causeNote = f === null
      ? 'No retained record readable: the read receipt carried no read face at all'
      : (why !== ''
        ? `No retained record readable: ${why}`
        : 'No retained record readable and the workflow does not answer')
  } else if (state === 'terminal') {
    cause = strOf(f?.exec_status) !== '' ? `Execution status ${strOf(f?.exec_status)}` : ''
    causeNote = cause !== ''
      ? 'Cause: the workflow reached a terminal state'
      : 'Cause unavailable: the terminal receipt carried no execution status'
  } else if (state === 'transient') {
    causeNote = 'Cause not located: the read failed without a located reason (a service hiccup)'
  } else if (state === 'not_found') {
    causeNote = 'Cause: the server reports no workflow with this id'
  } else {
    causeNote = 'Cause not located: the receipt carried no classification this panel knows'
  }

  const retry: ReadStateRetry =
    state === 'no_poller' ? 'slow'
      : state === 'transient' ? 'normal'
        : state === 'internal' ? 'never'
          : 'never'

  return {
    state,
    headline: HEADLINES[state],
    causeAvailable: cause !== '',
    cause,
    causeNote,
    facts,
    retry,
    pollNote: POLL_NOTES[state],
    receiptError,
    ticketId: id,
  }
}

/** True when the caller must NOT auto re-read this state (deterministic / finished). */
export function isPermanentReadState(view: ReadStateView | null | undefined): boolean {
  return view !== null && view !== undefined && view.retry === 'never'
}

/** The next delay for a detail re-read, or null = do not re-read automatically.
 *  Deterministic states return null so a finished ticket is never spun as transient. */
export function detailRepollDelayMs(view: ReadStateView | null | undefined,
                                     normalMs: number, slowMs: number): number | null {
  if (view === null || view === undefined) return normalMs
  if (view.retry === 'never') return null
  if (view.retry === 'slow') return slowMs
  return normalMs
}
