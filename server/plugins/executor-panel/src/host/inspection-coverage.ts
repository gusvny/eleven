/**
 * inspection-coverage — pure render model for the period-x-face coverage answer
 * (t261009-49, KI-01M4GGFXPAHDGSQ9767VMB5NGM).
 *
 * Zero DOM, zero io, zero react — unit-tested in
 * integration/t261009-49/inspection-coverage.test.mjs, embedded verbatim into the
 * static page via String(fn) (page-logic.ts layering). Input = the served archive
 * payload (UNTRUSTED engine ledger files), the disposition/trigger record rows
 * (UNTRUSTED) and an optional declared-face table (UNTRUSTED): missing or drifted
 * fields degrade to named copy — no throw, no fabrication.
 *
 * Discipline (ticket spec):
 *  - This is a SECOND fact, never merged with the dead-man verdict ('was the
 *    period's ticket created?'). A blocked/failed attempt IS a run for dead-man and
 *    here it IS a 'produced nothing' row — the two answers stay worded apart.
 *  - 'Ran but produced nothing' and 'there was nothing to report' never share a
 *    word: blocked / failed / not_run each carry their own copy.
 *  - The blocked-shell shape (readable ledger + non-empty blocked_reason + zero
 *    served findings, t261002-12) is `blocked`, NEVER `produced`.
 *  - An unreadable ledger is `unreadable` — never fine, never missing.
 *  - Attempt terminal states are NOT re-derived here (the five-state single point
 *    owns them): an attempt record without a state carries the literal copy
 *    'state unknown on this surface'.
 *  - The declared face id comes from the FACES table (declared scan_face per
 *    instance). A missing entry is the named marker 'decl-unreadable' — no face id
 *    is invented.
 *  - When the attempt records are unavailable, a missing slot still renders, but as
 *    the named degraded reading `not_run` with attempts_unavailable=true — the row
 *    says plainly that the surface could not check attempts, so 'no attempt' is this
 *    surface's limit, not a verified fact.
 */

/** Copy contract (single point — the page and the tests reference, never rewrite). */
export const COVERAGE_COPIES = {
  produced: 'This face produced a result this period.',
  blocked: 'Ran but produced nothing: the ledger is a blocked shell (the inspect stage refused the report).',
  failed: 'Attempted and produced nothing this period.',
  not_run: 'No attempt recorded for this period.',
  unreadable: 'The ledger file exists but is unreadable — named here, never read as fine and never read as missing.',
  attempts_unavailable:
    'Attempt records (the inspection ticket board, /sandbar-workbench/api/wf/inspection/tickets) are unavailable on this surface; "no attempt" below is this surface\'s limit, not a verified fact.',
  last_ok_prefix: 'Last successful period for this face: ',
  last_ok_suffix: '.',
  last_never: 'This face never produced a result in the shown window.',
  unknown_state: 'state unknown on this surface',
  decl_unreadable: 'decl-unreadable',
  block_title: 'Produced nothing (named lines, not a count)',
  attempts_more_prefix: 'and ',
  attempts_more_suffix: ' more attempt(s) not shown',
} as const

export interface CoverageAttempt {
  ticket_id: string
  state: string
  blocked_reason: string
}

export interface CoverageRow {
  instance: string
  period: string
  face: string
  result: 'produced' | 'blocked' | 'failed' | 'not_run' | 'unreadable'
  attempts_unavailable: boolean
  last_ok_period: string
  attempts: CoverageAttempt[]
  copy: string
}

export interface CoverageView {
  rows: CoverageRow[]
  attempts_available: boolean
  block: { visible: boolean; title: string; lines: string[] }
}

export interface CoveragePeriodEntry {
  period: string
  reports: Record<string, { ok: boolean; reason?: string; report?: unknown }>
}

export interface CoverageTables {
  COPIES: typeof COVERAGE_COPIES
  /** instance -> declared face id (scan_face); a missing entry reads decl-unreadable. */
  FACES: Record<string, string>
  ATTEMPT_CAP: number
}

function s(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

/** Build the attempts map from disposition/trigger record rows (UNTRUSTED). Rows
 *  without both instance and period are not attributable to a coverage cell and are
 *  dropped; a row without a ticket_id still counts as an attempt with the named
 *  unknown-state copy. Returns null when there are no rows at all (records
 *  unavailable) — the caller's attempts_unavailable flag comes from that null. */
export function recordsToAttempts(rows: unknown): Record<string, unknown> | null {
    // Local copy of the string-coercion helper: this function is embedded into the
  // page via String(fn), so everything it calls must live inside its own source.
  function s(v: unknown): string {
    return typeof v === 'string' ? v.trim() : ''
  }
  if (!Array.isArray(rows) || rows.length === 0) return null
  const out: Record<string, unknown> = {}
  let kept = 0
  for (const r of rows) {
    if (r === null || typeof r !== 'object') continue
    const d = r as Record<string, unknown>
    const inst = s(d.instance ?? d.instance_id)
    const period = s(d.period)
    if (!inst || !period) continue
    kept += 1
    const key = `${inst}/${period}`
    const arr = Array.isArray(out[key]) ? (out[key] as CoverageAttempt[]) : []
    const spawn = (d.spawn !== null && typeof d.spawn === 'object') ? d.spawn as Record<string, unknown> : {}
    const ticket = s(spawn.ticket_id) || s(d.ticket_id)
    // Inline copies (no closure over COVERAGE_COPIES): this function is embedded into
    // the page via String(fn), so every literal it uses must live inside its own source.
    arr.push({
      ticket_id: ticket,
      state: s(spawn.error) ? 'spawn failed' : 'state unknown on this surface',
      blocked_reason: s(d.reason) || s(spawn.error),
    })
    out[key] = arr
  }
  return kept > 0 ? out : null
}

/** t261026-10 (defect C): build the attempts map from the inspection TICKET BOARD rows
 *  (GET /sandbar-workbench/api/wf/inspection/tickets — the route already exists; this
 *  is not a new fetch face). One ticket row = one attempt record: ticket_id = the row
 *  id, state = the engine's status/stage words verbatim (never re-derived here — the
 *  five-state single point owns terminal states), blocked_reason = the row's named
 *  reason. UNTRUSTED input: the same guards as recordsToAttempts — rows without both
 *  instance and period are not attributable to a coverage cell and are dropped; a row
 *  without an id still counts as an attempt with the named unknown-state copy.
 *
 *  Project scope (review C1, named choice): the board route serves inspection rows
 *  across projects. A row whose `project` field is a non-empty string that differs
 *  from `project` is DROPPED — a same-named instance id from another project must not
 *  light up this project's cells. Rows with an empty/absent project (the pre-t260915-20
 *  historical shape) are KEPT: the rendered instances come from THIS project's
 *  declaration (the archive's declared-instance filter), so a kept legacy row can only
 *  ever land on a declared cell of the project being viewed.
 *  Returns null when nothing attributable survives (records unavailable). */
export function ticketRowsToAttempts(rows: unknown, project: string): Record<string, unknown> | null {
  // Local string helper: embedded into the page via String(fn) — no outer closure.
  function s(v: unknown): string {
    return typeof v === 'string' ? v.trim() : ''
  }
  if (!Array.isArray(rows) || rows.length === 0) return null
  const want = s(project)
  const out: Record<string, unknown> = {}
  let kept = 0
  for (const r of rows) {
    if (r === null || typeof r !== 'object') continue
    const d = r as Record<string, unknown>
    const rowProject = s(d.project)
    if (rowProject !== '' && want !== '' && rowProject !== want) continue
    const inst = s(d.instance ?? d.instance_id)
    const period = s(d.period)
    if (!inst || !period) continue
    kept += 1
    const key = `${inst}/${period}`
    const arr = Array.isArray(out[key]) ? (out[key] as CoverageAttempt[]) : []
    arr.push({
      ticket_id: s(d.id ?? d.ticket_id),
      state: s(d.stage_state) || s(d.status),
      blocked_reason: s(d.blocked_reason),
    })
    out[key] = arr
  }
  return kept > 0 ? out : null
}

/** The period-x-face coverage view (closure-free; tables passed in — embedded via
 *  String(fn) with the JSON-serialised tables). Periods are consumed in ascending
 *  numeric order; `last_ok_period` is the newest strictly-earlier period whose face
 *  produced a result, or the explicit word 'never'. */
export function buildCoverageCore(
  periods: CoveragePeriodEntry[],
  instances: string[],
  attempts: Record<string, unknown> | null,
  T: CoverageTables,
): CoverageView {
  const C = T.COPIES
  // Local copies of the module-private helpers: this function is embedded into the
  // page via String(fn), so everything it calls must live inside its own source.
  function s(v: unknown): string {
    return typeof v === 'string' ? v.trim() : ''
  }
  function attemptsFor(attempts: Record<string, unknown> | null, key: string): CoverageAttempt[] {
    if (!attempts) return []
    const raw = attempts[key]
    // A key carries a LIST of attempt rows, or (t261026-10, integration-scenario
    // tolerance) a single attempt record object — both read; anything else is none.
    const list = Array.isArray(raw) ? raw : (raw !== null && typeof raw === 'object' ? [raw] : [])
    const out: CoverageAttempt[] = []
    for (const e of list) {
      if (e !== null && typeof e === 'object') {
        const d = e as Record<string, unknown>
        out.push({ ticket_id: s(d.ticket_id), state: s(d.state), blocked_reason: s(d.blocked_reason) })
      }
    }
    return out
  }

  // Untrusted payload guards: a non-array/absent period list reads as an empty
  // window (never a throw); a non-object reports map reads as no slots.
  const asc = (Array.isArray(periods) ? periods : [])
    .filter((p) => p !== null && typeof p === 'object')
    .sort((a, b) => Number(a.period) - Number(b.period))
  const rows: CoverageRow[] = []
  const lines: string[] = []
  for (const inst of (Array.isArray(instances) ? instances : []).filter((i) => typeof i === 'string')) {
    const face = s(T.FACES[inst]) || C.decl_unreadable
    let lastOk: string | null = null
    for (const p of asc) {
      const reports = (p.reports !== null && typeof p.reports === 'object') ? p.reports : {}
      const slot = reports[inst]
      const attemptRows = attemptsFor(attempts, `${inst}/${p.period}`)
      let result: CoverageRow['result']
      let evidence: CoverageAttempt[] = []
      if (slot && slot.ok === true) {
        const rep = (slot.report !== null && typeof slot.report === 'object') ? slot.report as Record<string, unknown> : {}
        const blockedReason = s(rep.blocked_reason)
        if (blockedReason) {
          result = 'blocked'
          evidence = [{ ticket_id: s(rep.ticket_id), state: 'blocked', blocked_reason: blockedReason }]
        } else {
          result = 'produced'
          lastOk = p.period
        }
      } else if (slot && s(slot.reason)) {
        result = 'unreadable'
      } else if (attemptRows.length > 0) {
        result = 'failed'
        evidence = attemptRows
      } else {
        result = 'not_run'
      }
      const unavailable = !(slot && slot.ok === true) && attempts === null
      const lastCopy = lastOk === null ? C.last_never : C.last_ok_prefix + lastOk + C.last_ok_suffix
      let copy: string
      if (result === 'produced') copy = C.produced
      else if (result === 'blocked') copy = `${C.blocked} ${lastCopy}`
      else if (result === 'failed') copy = `${C.failed} ${lastCopy}`
      else if (result === 'unreadable') copy = `${C.unreadable} ${lastCopy}`
      else copy = unavailable ? `${C.not_run} ${C.attempts_unavailable}` : `${C.not_run} ${lastCopy}`
      rows.push({
        instance: inst, period: p.period, face, result,
        attempts_unavailable: unavailable,
        last_ok_period: lastOk === null ? 'never' : lastOk,
        attempts: evidence, copy,
      })
      if (result !== 'produced') {
        let line = `${p.period} · ${inst} (face ${face}): ${result} — ${lastOk === null ? 'last success never' : `last success ${lastOk}`}`
        const shown = evidence.slice(0, T.ATTEMPT_CAP)
        if (shown.length) {
          line += ' | attempts: ' + shown.map((a) =>
            `${a.ticket_id || '(ticket unknown)'} (${a.state || C.unknown_state}${a.blocked_reason ? `: ${a.blocked_reason}` : ''})`
          ).join(', ')
          if (evidence.length > shown.length) {
            line += `, ${C.attempts_more_prefix}${evidence.length - shown.length}${C.attempts_more_suffix}`
          }
        } else if (result === 'not_run') {
          line += ' | no attempt recorded'
        }
        lines.push(line)
      }
    }
  }
  return { rows, attempts_available: attempts !== null, block: { visible: lines.length > 0, title: C.block_title, lines } }
}

/** Module-level convenience (tables = the real copies, no declared faces — the page
 *  passes its own FACES table through the core). */
export function buildCoverage(
  periods: CoveragePeriodEntry[],
  instances: string[],
  attempts: Record<string, unknown> | null,
): CoverageView {
  return buildCoverageCore(periods, instances, attempts, { COPIES: COVERAGE_COPIES, FACES: {}, ATTEMPT_CAP: 5 })
}
