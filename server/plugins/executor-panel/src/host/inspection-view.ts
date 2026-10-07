/**
 * inspection-view — pure render model for the Inspection tab's content
 * (t261006-15, plan D5 / step 1).
 *
 * Zero DOM, zero io, zero react — unit-tested directly in node, embedded verbatim into
 * the static page via String(fn) (page-logic.ts layering). Input = workbench
 * inspection-archive.ts PeriodEntry[] (UNTRUSTED external input: the report JSON is an
 * engine ledger file; missing or drifted fields degrade — no throw, no fabrication).
 *
 * Copy discipline (261004 host rulings, verbatim):
 *  - "Findings count" and "named items" are two numbers, written apart: the card shows
 *    counts, the block description says `N named of M counted` — the two numbers are
 *    not equal by design, not a dropped row.
 *  - "Not reviewed" must never read as "no problem": an absent coverage list says so
 *    explicitly; a non-empty not_reviewed list is carried verbatim.
 *  - The past-period read-only banner and every empty-state copy are verbatim
 *    (EMPTY_COPIES is the single point; the page references, never rewrites).
 *  - The rolling-window control (7/30 days) is a STRICTLY informational debt note
 *    (its data source is t261006-12's reviewed ledger): the wording claims nothing
 *    about coverage data existing anywhere today.
 */

/** Instance display names (known instances mapped; unknown falls back to its own id —
 *  never invented, never hidden). */
export const INSTANCE_LABELS: Record<string, string> = {
  'integration-tests': 'Integration tests',
  'simplify': 'Simplify',
  'docs-sync': 'Documents',
}

/** Core form takes the tables as a parameter so the page can embed this function
 *  verbatim via String(fn) together with the JSON-serialised tables (EMBEDDED
 *  pattern) — one implementation for the unit test and the page. */
export function instanceLabelCore(instance: string, labels: Record<string, string>): string {
  return labels[instance] ?? instance
}

export function instanceLabel(instance: string): string {
  return instanceLabelCore(instance, INSTANCE_LABELS)
}

/** Empty-state / banner copy contract (§7 verbatim; the page only references it). */
export const EMPTY_COPIES = {
  read_only: 'This period is closed. Shown read-only from its report.',
  no_report: 'No report for this period.',
  no_reports: 'No report for these periods.',
  not_available: 'The report is not available for this period.',
  no_reviews: 'No reviews started yet.',
  no_findings: 'No findings this period.',
  range_note: 'Range windows (7 / 30 days) are not part of this tab yet; they will read the reviewed-file ledger when ticket t261006-12 lands.',
} as const

/** One face card (fields unified regardless of the instance's rhythm — §7 "one card
 *  per inspection instance"). */
export interface FaceCard {
  instance: string
  label: string
  /** Human reason when the report slot failed (fail-closed; the card shows the reason,
   *  not a blank). */
  report_error: string
  /** Severity counts (the doc face uses the same field family; absent = the report did
   *  not give them — never 0). */
  counts: { high: number; med: number; low: number; total: number } | null
  counts_copy: string
  named: string[]
  named_copy: string
  findings_copy: string
  coverage_copy: string
  /** Item-level coverage lists (either absent = null -> coverage_copy says so). */
  reviewed: string[] | null
  not_reviewed: string[] | null
}

export interface PeriodView {
  /** The selected period is closed (not the newest reported one) -> banner
   *  EMPTY_COPIES.read_only. */
  read_only: boolean
  banner: string
  cards: FaceCard[]
  range_note: string
}

function toStrArray(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null
  const out: string[] = []
  for (const x of v) {
    if (typeof x === 'string' && x.trim() !== '') out.push(x)
    else if (typeof x === 'object' && x !== null) {
      const t = (x as Record<string, unknown>).text
      if (typeof t === 'string' && t.trim() !== '') out.push(t)
    }
  }
  return out
}

/** Drift-tolerant count extraction: findings{high,med,low} counts only when all three
 *  are finite numbers (one missing = the whole group is absent). */
function extractCounts(report: unknown): FaceCard['counts'] {
  if (typeof report !== 'object' || report === null) return null
  const f = (report as Record<string, unknown>).findings
  if (typeof f !== 'object' || f === null) return null
  const doc = f as Record<string, unknown>
  const n = (k: string) => (typeof doc[k] === 'number' && Number.isFinite(doc[k]) ? doc[k] : null)
  const high = n('high'); const med = n('med'); const low = n('low')
  if (high === null || med === null || low === null) return null
  const total = high + med + low
  return { high, med, low, total }
}

function extractNamed(report: unknown): string[] {
  if (typeof report !== 'object' || report === null) return []
  const doc = report as Record<string, unknown>
  const f = typeof doc.findings === 'object' && doc.findings !== null ? doc.findings as Record<string, unknown> : doc
  // Named items may live in either home: findings.named (beside the counts) or the
  // document top level.
  return toStrArray(f.named) ?? toStrArray(f.named_items) ?? toStrArray(f.items)
    ?? toStrArray(doc.named) ?? toStrArray(doc.named_items) ?? []
}

function extractCoverage(report: unknown): {
  reviewed: string[] | null; not_reviewed: string[] | null; copy: string
} {
  if (typeof report !== 'object' || report === null) {
    return { reviewed: null, not_reviewed: null, copy: 'The report does not state coverage for this period.' }
  }
  const doc = report as Record<string, unknown>
  const cov = typeof doc.coverage === 'object' && doc.coverage !== null
    ? doc.coverage as Record<string, unknown>
    : (typeof doc.scope === 'object' && doc.scope !== null ? doc.scope as Record<string, unknown> : null)
  if (!cov) return { reviewed: null, not_reviewed: null, copy: 'The report does not state coverage for this period.' }
  const reviewed = toStrArray(cov.reviewed) ?? toStrArray(cov.reviewed_files)
  const notReviewed = toStrArray(cov.not_reviewed) ?? toStrArray(cov.skipped)
  const rCount = typeof cov.reviewed_count === 'number' && Number.isFinite(cov.reviewed_count) ? cov.reviewed_count : null
  const tCount = typeof cov.total_count === 'number' && Number.isFinite(cov.total_count) ? cov.total_count : null
  let copy: string
  if (reviewed !== null || notReviewed !== null || (rCount !== null && tCount !== null)) {
    const head = rCount !== null && tCount !== null ? `Code: ${rCount} of ${tCount} reviewed` : 'Coverage stated in the report'
    copy = reviewed !== null ? `${head} · ${reviewed.length} listed below` : `${head}.`
  } else {
    copy = 'The report does not state coverage for this period.'
  }
  return { reviewed, not_reviewed: notReviewed, copy }
}

/**
 * One period's view: a null periodEntry means the archive has no such period (explicit
 * not-available, never a blank). latestReported = the newest reported period in the
 * archive (the read side computes it from items and passes it in — the ordering single
 * point stays in the archive module).
 */
export interface InspTables {
  EMPTY_COPIES: typeof EMPTY_COPIES
  INSTANCE_LABELS: Record<string, string>
}

/** Table-parameterised core (page embeds this + the JSON tables; the wrapper below
 *  is the module-level convenience used by the unit tests). */
export function buildPeriodViewCore(
  periodEntry: { period: string; reports: Record<string, { ok: boolean; reason?: string; report?: unknown }> } | null,
  latestReported: string | null,
  instances: string[],
  T: InspTables,
): PeriodView {
  const C = T.EMPTY_COPIES
  function toStrArray(v: unknown): string[] | null {
    if (!Array.isArray(v)) return null
    const out: string[] = []
    for (const x of v) {
      if (typeof x === 'string' && x.trim() !== '') out.push(x)
      else if (typeof x === 'object' && x !== null) {
        const t = (x as Record<string, unknown>).text
        if (typeof t === 'string' && t.trim() !== '') out.push(t)
      }
    }
    return out
  }
  /** Drift-tolerant count extraction: findings{high,med,low} counts only when all three
   *  are finite numbers (one missing = the whole group is absent). */
  function extractCounts(report: unknown): FaceCard['counts'] {
    if (typeof report !== 'object' || report === null) return null
    const f = (report as Record<string, unknown>).findings
    if (typeof f !== 'object' || f === null) return null
    const doc = f as Record<string, unknown>
    const n = (k: string) => (typeof doc[k] === 'number' && Number.isFinite(doc[k]) ? doc[k] : null)
    const high = n('high'); const med = n('med'); const low = n('low')
    if (high === null || med === null || low === null) return null
    const total = high + med + low
    return { high, med, low, total }
  }
  function extractNamed(report: unknown): string[] {
    if (typeof report !== 'object' || report === null) return []
    const doc = report as Record<string, unknown>
    const f = typeof doc.findings === 'object' && doc.findings !== null ? doc.findings as Record<string, unknown> : doc
    // Named items may live in either home: findings.named (beside the counts) or the
    // document top level.
    return toStrArray(f.named) ?? toStrArray(f.named_items) ?? toStrArray(f.items)
      ?? toStrArray(doc.named) ?? toStrArray(doc.named_items) ?? []
  }
  function extractCoverage(report: unknown): {
    reviewed: string[] | null; not_reviewed: string[] | null; copy: string
  } {
    if (typeof report !== 'object' || report === null) {
      return { reviewed: null, not_reviewed: null, copy: 'The report does not state coverage for this period.' }
    }
    const doc = report as Record<string, unknown>
    const cov = typeof doc.coverage === 'object' && doc.coverage !== null
      ? doc.coverage as Record<string, unknown>
      : (typeof doc.scope === 'object' && doc.scope !== null ? doc.scope as Record<string, unknown> : null)
    if (!cov) return { reviewed: null, not_reviewed: null, copy: 'The report does not state coverage for this period.' }
    const reviewed = toStrArray(cov.reviewed) ?? toStrArray(cov.reviewed_files)
    const notReviewed = toStrArray(cov.not_reviewed) ?? toStrArray(cov.skipped)
    const rCount = typeof cov.reviewed_count === 'number' && Number.isFinite(cov.reviewed_count) ? cov.reviewed_count : null
    const tCount = typeof cov.total_count === 'number' && Number.isFinite(cov.total_count) ? cov.total_count : null
    let copy: string
    if (reviewed !== null || notReviewed !== null || (rCount !== null && tCount !== null)) {
      const head = rCount !== null && tCount !== null ? `Code: ${rCount} of ${tCount} reviewed` : 'Coverage stated in the report'
      copy = reviewed !== null ? `${head} · ${reviewed.length} listed below` : `${head}.`
    } else {
      copy = 'The report does not state coverage for this period.'
    }
    return { reviewed, not_reviewed: notReviewed, copy }
  }
  const rangeNote = C.range_note
  if (periodEntry === null) {
    return { read_only: true, banner: C.not_available, cards: [], range_note: rangeNote }
  }
  const readOnly = latestReported !== null && periodEntry.period !== latestReported
  const cards: FaceCard[] = instances.map((inst) => {
    const label = T.INSTANCE_LABELS[inst] ?? inst
    const slot = periodEntry.reports[inst]
    if (!slot || slot.ok !== true) {
      return {
        instance: inst, label,
        report_error: slot && slot.reason ? slot.reason : C.no_report,
        counts: null,
        counts_copy: 'No counts without a report.',
        named: [], named_copy: 'No named items without a report.',
        findings_copy: C.no_findings,
        coverage_copy: 'No coverage without a report.',
        reviewed: null, not_reviewed: null,
      }
    }
    const counts = extractCounts(slot.report)
    const named = extractNamed(slot.report)
    const cov = extractCoverage(slot.report)
    return {
      instance: inst, label, report_error: '',
      counts,
      counts_copy: counts ? `${counts.total} counted (high ${counts.high} · med ${counts.med} · low ${counts.low})` : 'The report gives no severity counts.',
      named,
      named_copy: counts ? `${named.length} named of ${counts.total} counted` : `${named.length} named items`,
      findings_copy: named.length === 0 && (counts?.total ?? 0) === 0 ? C.no_findings : '',
      coverage_copy: cov.copy,
      reviewed: cov.reviewed,
      not_reviewed: cov.not_reviewed,
    }
  })
  return { read_only: readOnly, banner: readOnly ? C.read_only : '', cards, range_note: rangeNote }
}

export function buildPeriodView(
  periodEntry: { period: string; reports: Record<string, { ok: boolean; reason?: string; report?: unknown }> } | null,
  latestReported: string | null,
  instances: string[],
): PeriodView {
  return buildPeriodViewCore(periodEntry, latestReported, instances, { EMPTY_COPIES, INSTANCE_LABELS })
}
