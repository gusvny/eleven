/**
 * ticket-detail-column-model — pure model layer for the single-column ticket
 * detail (t261008-07, host order 261008 option 2).
 *
 * Visual baseline: notes/discussions/261004-concurrency-limit-mock.html v11,
 * function ticketView(). Design rule (261004 concurrency design notes, sec 7.3): the detail is
 * a decision surface, not an information surface — a section with no data
 * renders NOTHING (no empty scaffolding), and wording is stated, never implied.
 *
 * Zero react / platform deps; node imports it directly (type stripping, same
 * layering as queue-model.ts / ticket-list-model.ts). Every consumer face is
 * `unknown`-tolerant: malformed entries are skipped, never thrown — the column
 * renders only what the faces actually carry.
 *
 * Block order is the acceptance baseline (host order supersedes design §7.5's
 * spec-before-decision for the column layout; recorded on the ticket):
 * crumb → head → actions → decision card → spec → lane map → two columns
 * (timeline + stage notes | receipts + changes + requests) → collapsed heavy
 * sections.
 */

/** The mock's single-column section order. Asserted by the unit layer and
 *  re-asserted end to end by the scenario layer (sc_t26100807). */
export const SECTION_ORDER = [
  'crumb', 'head', 'actions', 'decision', 'spec', 'lane-map', 'columns', 'collapsed',
] as const

/** One key/value row of a mock-style kv2 box. */
export interface KvRow { k: string; v: string }

/** One timeline row (normalized; at kept verbatim — the renderer formats it). */
export interface TimelineRow { at: string; stage: string; state: string; reason: string }

/** One stage-note row: per-stage round/gen counts from the snapshot faces. */
export interface StageNoteRow { stage: string; note: string }

/** Decision card face (§7.3): null = no decision to make → render nothing. */
export interface DecisionCard { title: string; body: string }

/** Structural input — matches the detail snapshot face without importing it. */
interface DecisionDetail {
  status?: unknown
  stage_state?: unknown
  stage?: unknown
  stage_name?: unknown
  paused?: unknown
  kind?: unknown
  engine?: unknown
  exec_status?: unknown
}

function asStr(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/**
 * Decision card text per state (design §7.3 table, host order wording):
 * - awaiting-human → 'Waiting for you: sign the merge' + what is being signed
 *   + 'send it back instead if the diff is wrong';
 * - paused → 'Paused by you' + 'it stops after the current stage ends';
 * - queued → 'Queued, position N' (position may be unknown → plain 'Queued',
 *   never a fabricated number) + 'it starts when a slot frees';
 * - otherwise (running / awaiting / blocked) → 'At work: <stage>' +
 *   'nothing to decide yet'.
 * null: closed tickets, terminal done state, inspection tickets (the
 * inspection face is its own decision surface — no double frame) and any face
 * with neither a status nor a stage_state (malformed input renders nothing).
 */
export function decisionCard(detail: DecisionDetail, queuePosition: number | null): DecisionCard | null {
  if (detail === null || typeof detail !== 'object') return null
  if (detail.kind === 'inspection' || detail.engine === 'inspection') return null
  const status = asStr(detail.status)
  const ss = asStr(detail.stage_state)
  if (status === '' && ss === '') return null
  if (status === 'closed' || ss === 'done') return null
  const stage = asStr(detail.stage_name) || asStr(detail.stage) || 'the current stage'
  if (ss === 'awaiting-human') {
    return {
      title: 'Waiting for you: sign the merge',
      body: `Sign the ${stage} handoff and the ticket advances. Send it back instead if the diff is wrong.`,
    }
  }
  if (detail.paused === true) {
    return { title: 'Paused by you', body: 'It stops after the current stage ends.' }
  }
  if (status === 'queued' || ss === 'queued') {
    return {
      title: typeof queuePosition === 'number' && Number.isFinite(queuePosition) && queuePosition >= 1
        ? `Queued, position ${queuePosition}`
        : 'Queued',
      body: 'It starts when a slot frees.',
    }
  }
  return { title: `At work: ${stage}`, body: 'Nothing to decide yet.' }
}

/**
 * Receipts box (sec 7.3, 'last receipt'): the LAST gate round of the same gate_runs
 * face the checks detail consumes. Rows: `<label>: <green> of <total> green`,
 * plus the suite counts and the env red count ONLY when the face carries them.
 * Absent/empty/malformed face → null (render nothing).
 */
export function receiptRows(gateRuns: unknown): KvRow[] | null {
  if (!Array.isArray(gateRuns)) return null
  let last: Record<string, unknown> | null = null
  for (let i = gateRuns.length - 1; i >= 0; i--) {
    const r = gateRuns[i]
    if (r !== null && typeof r === 'object' && Array.isArray((r as Record<string, unknown>).checks)) {
      last = r as Record<string, unknown>
      break
    }
  }
  if (last === null) return null
  const rows: KvRow[] = []
  const label = asStr(last.label) || asStr(last.stage) || 'check'
  const checks = last.checks as unknown[]
  const total = checks.length
  const green = checks.filter(c => c !== null && typeof c === 'object' && (c as Record<string, unknown>).green === true).length
  rows.push({ k: label, v: total > 0 ? `${green} of ${total} green` : 'no checks recorded' })
  // Suite counts: additive face key (suite = {ran, passed, known?}); a run that
  // does not carry it (older snapshots / non-suite gates) renders no suite row.
  const suite = last.suite
  if (suite !== null && typeof suite === 'object' && !Array.isArray(suite)) {
    const s = suite as Record<string, unknown>
    const ran = typeof s.ran === 'number' ? s.ran : undefined
    const passed = typeof s.passed === 'number' ? s.passed : undefined
    if (ran !== undefined && passed !== undefined) {
      const known = typeof s.known === 'number' ? ` / ${s.known} known` : ''
      rows.push({ k: 'suite', v: `${ran} ran / ${passed} passed${known}` })
    }
  }
  const red = typeof last.red_count === 'number' && Number.isFinite(last.red_count) ? last.red_count : undefined
  if (red !== undefined && red > 0) rows.push({ k: 'env red', v: String(red) })
  return rows
}

/**
 * Stage notes (host order: per-stage gen and round counts from the snapshot's
 * faces). Round counts come from the snapshot `gens` face (stage → round
 * number, t260915-01); entries without it fall back to counting `running`
 * timeline entries per stage. Absent faces / no stages → null.
 */
export function stageNoteRows(detail: unknown): StageNoteRow[] | null {
  if (detail === null || typeof detail !== 'object') return null
  const d = detail as Record<string, unknown>
  const gens = (d.gens !== null && typeof d.gens === 'object' && !Array.isArray(d.gens))
    ? d.gens as Record<string, unknown>
    : null
  const runsByStage = new Map<string, number>()
  if (Array.isArray(d.timeline)) {
    for (const t of d.timeline) {
      if (t === null || typeof t !== 'object') continue
      const e = t as Record<string, unknown>
      if (e.state !== 'running') continue
      const stage = asStr(e.stage)
      if (!stage) continue
      runsByStage.set(stage, (runsByStage.get(stage) ?? 0) + 1)
    }
  }
  const stages = new Set<string>([...Object.keys(gens ?? {}), ...runsByStage.keys()])
  if (stages.size === 0) return null
  const out: StageNoteRow[] = []
  for (const stage of [...stages].sort()) {
    const gen = gens !== null && typeof gens[stage] === 'number' ? gens[stage] as number : null
    const runs = runsByStage.get(stage) ?? 0
    if (gen !== null && gen >= 1) out.push({ stage, note: `round ${gen}${runs > 1 ? ` · entered ${runs} times` : ''}` })
    else if (runs > 0) out.push({ stage, note: runs === 1 ? 'ran once' : `ran ${runs} times` })
  }
  return out.length > 0 ? out : null
}

/** +/− line count over one unified diff text (skips +++/--- header lines). */
function unifiedStats(text: unknown): { add: number; del: number } {
  if (typeof text !== 'string') return { add: 0, del: 0 }
  let add = 0
  let del = 0
  for (const l of text.split('\n')) {
    if (l.startsWith('+++') || l.startsWith('---')) continue
    if (l.startsWith('+')) add++
    else if (l.startsWith('-')) del++
  }
  return { add, del }
}

/**
 * Changes box (mock kv2): file count and the +/− line, the lane path and
 * branch, plus one compact row per file (path → status · +add −del; t261008-23
 * direction: the compact panel keeps file rows/status/size, the full diff body
 * and review actions live only in the collapsible fold at the end of the
 * column — the two do not overlap). Data: the same diff face the changes
 * section consumes (GET /tickets/:id/diff → {files:[{unified?...}]}
 * worktree?}) plus the snapshot's worktree/branch keys. No diff face or an
 * unreadable one → null (the §7.3 rule: no face, no scaffolding — the
 * collapsed changes section is the place that names read errors).
 */
export function changeRows(diff: unknown, detail: unknown): KvRow[] | null {
  if (diff === null || typeof diff !== 'object') return null
  const files = (diff as Record<string, unknown>).files
  if (!Array.isArray(files)) return null
  let add = 0
  let del = 0
  const perFile: KvRow[] = []
  for (const f of files) {
    if (f === null || typeof f !== 'object') continue
    const o = f as Record<string, unknown>
    const path = asStr(o.path)
    const st = unifiedStats(o.unified)
    add += st.add
    del += st.del
    if (path === '') continue
    const status = asStr(o.status)
    perFile.push({ k: path, v: `${status !== '' ? status + ' · ' : ''}+${st.add} −${st.del}` })
  }
  const rows: KvRow[] = [{ k: 'files', v: `${files.length} · +${add} −${del}` }]
  rows.push(...perFile.slice(0, CHANGE_FILE_ROWS_CAP))
  if (perFile.length > CHANGE_FILE_ROWS_CAP) {
    rows.push({ k: '…', v: `${perFile.length - CHANGE_FILE_ROWS_CAP} more files (full list in the changes fold)` })
  }
  const d = (detail !== null && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
  const lane = [asStr(d.worktree), asStr(d.branch)].filter(s => s !== '').join(' · ')
  if (lane !== '') rows.push({ k: 'lane', v: lane })
  return rows
}

/** Compact Changes panel: per-file rows cap (totals row always present; the
 *  full per-file diff stays in the collapsible fold). */
const CHANGE_FILE_ROWS_CAP = 8

/** Long timeline reason collapse (t261008-23 option b): every entry stays;
 *  a reason longer than the threshold renders as a short form with an
 *  expand-on-click control. Pure helper so the model half is unit-testable. */
export const TIMELINE_REASON_MAX = 120

export function collapseReason(reason: string): { short: string; full: string; collapsed: boolean } {
  const one = reason.replace(/\s+/g, ' ').trim()
  if (one.length <= TIMELINE_REASON_MAX) return { short: one, full: reason, collapsed: false }
  return { short: one.slice(0, TIMELINE_REASON_MAX) + '…', full: reason, collapsed: true }
}

/**
 * Requests on this ticket: the request-ledger head rows whose source_ticket
 * equals this ticket id (field landed with t261007-02; legacy rows without the
 * field never match). Malformed rows (non-object, missing/non-string id or
 * question) are skipped, never thrown. No rows → null (render nothing).
 */
export function requestsForTicket(rows: unknown, ticketId: string): Array<Record<string, unknown>> | null {
  if (!Array.isArray(rows) || typeof ticketId !== 'string' || ticketId === '') return null
  const out: Array<Record<string, unknown>> = []
  for (const r of rows) {
    if (r === null || typeof r !== 'object') continue
    const o = r as Record<string, unknown>
    if (o.source_ticket !== ticketId) continue
    if (asStr(o.id) === '' || asStr(o.question) === '') continue
    out.push(o)
  }
  return out.length > 0 ? out : null
}

/**
 * Timeline rows (same activity feed the live panel reads: the snapshot's
 * timeline face). Malformed entries skipped; empty face → null.
 */
export function timelineRows(timeline: unknown): TimelineRow[] | null {
  if (!Array.isArray(timeline)) return null
  const out: TimelineRow[] = []
  for (const t of timeline) {
    if (t === null || typeof t !== 'object') continue
    const e = t as Record<string, unknown>
    const stage = asStr(e.stage)
    const state = asStr(e.state)
    if (stage === '' && state === '') continue
    out.push({ at: asStr(e.at), stage, state, reason: asStr(e.reason) })
  }
  return out.length > 0 ? out : null
}
