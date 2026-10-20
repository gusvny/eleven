/**
 * certification-model.ts — the Certification tab's decision layer (t261009-41).
 *
 * Slice 1 of the ticket split: the complete face derivation the approved mock
 * (notes/discussions/261009-executor-certification-tab-mock.html, v15) draws, as a
 * pure module — no React, no fs, no fetch. The tab itself (executor panel) is
 * Slice 2 (integration/t261009-41/slice2-ticket-draft.md); it renders this face.
 *
 * Binding rule (review R2, plan v2 §2): this module only shapes presentation.
 * Every count it shows is arithmetic over engine-derived facts that arrive as
 * inputs — `freeze_state`, `ticket_wait_state` and `ticket_outcome` outputs from
 * server/engine/develop_certify.py / develop_promote.py, plus the certification,
 * run-header and promotion rows. The module computes no certification outcome of
 * its own; the golden-fixture contract test keeps the two sides from drifting.
 *
 * Faces the mock rules, and where they live here:
 * - one bar, one boundary: segments sized by cert/wait counts; the delivered
 *   total is a running number and a fixed cap, never in the segment scale.
 * - counts appear once: the face carries counts inside segments and the promote
 *   batch size; it carries no tally row.
 * - promote stays enabled while frozen: the gate is `promotable === 0` only.
 * - no invented scheduler: `roundState` is an input; when records carry no
 *   round-chaining state it defaults to 'idle' and nothing else is invented.
 * - no glyph carries meaning; every label is an engine word or a mock word.
 *
 * Malformed input degrades to an explicit empty face with a reason string —
 * never a throw, never a guessed count.
 */

/** Engine word list a produced label may draw from; anything else is a defect. */
const FACE_WORDS = [
  'GREEN', 'FROZEN', 'certified', 'waiting', 'delivered', 'as of',
  'auto rounds', 'idle', 'running', 'run now', 'Promote', 'line',
  'green', 'red', 'blockers', 'auto', 'manual', 'pass', 'fail', 'env',
] as const

export interface LineInput {
  line_id?: unknown
  scope?: unknown
  owner?: unknown
}

export interface FreezeInput {
  frozen?: unknown
  culprit?: unknown
}

/** One `ticket_wait_state` output, keyed with its ticket. */
export interface WaitStateInput {
  ticket?: unknown
  state?: unknown
  waiting_since?: unknown
  covered_by?: unknown
}

/** One `ticket_outcome` output, keyed with its ticket. */
export interface OutcomeInput {
  ticket?: unknown
  delivered_in?: unknown
  ending?: unknown
}

export interface CertRowInput {
  id?: unknown
  run?: unknown
  at?: unknown
}

export interface RunRowInput {
  id?: unknown
  cases?: unknown
  verdict?: unknown
  source?: unknown
  started_at?: unknown
  repos?: unknown
}

export interface TicketMeta {
  title?: unknown
  epic?: unknown
}

export interface CertificationInput {
  line?: LineInput | null
  freeze?: FreezeInput | null
  /** t261009-67: the engine's open_freeze_summary output — the signer's
   *  freeze face (cause cert + the chain of fix landings). Absent on older
   *  adapter receipts; present-but-malformed degrades the face by name. */
  freezeSummary?: unknown
  waitStates?: unknown
  outcomes?: unknown
  certs?: unknown
  runs?: unknown
  ticketMeta?: unknown
  /** Records' own round state ('idle' | 'running'); absent = 'idle'. Rule 9. */
  roundState?: unknown
}

/** One fix landing of the chain, as the signer face shows it (goal 166):
 *  the fix landing, its ticket, and the landing its current repairs
 *  relation names (null when the repair target is unresolved — the gap
 *  stays visible, never guessed closed). */
export interface FixChainRow {
  landing: string
  ticket: string
  repaired: string | null
}

export interface TicketRow {
  ticket: string
  title: string
  epic: string
}

export interface CertifiedRow extends TicketRow {
  certifiedBy: string
  /** t261016-09 (D4): the delivered split is STATED on the row — a delivered
   *  ticket stays on the certified list (coverage outlives promotion) with
   *  this marker, instead of silently emptying the table. */
  delivered: boolean
  /** t261019-23 (F3/F4): the row's own landing moment, dated ('' when the
   *  wait record carried no readable waiting_since — the row then sorts
   *  last and names the absence by showing nothing, never a guessed time). */
  landedAt: string
}

export interface WaitingRow extends TicketRow {
  landedAt: string
  redImplicated: boolean
}

export interface RoundFace {
  runId: string
  startedAt: string
  trigger: 'auto' | 'manual'
  result: { pass: number; fail: number; env: number }
  /** green, or red with its blocker count in words. */
  verdict: 'green' | 'red'
  blockers: number
  /** 'line <sha>' — the revision the round measured as the line head. */
  measured: string
}

export interface CertificationFace {
  ok: boolean
  /** Why the face is empty/degraded; '' when ok. */
  reason: string
  lineId: string
  state: 'GREEN' | 'FROZEN'
  frozen: boolean
  /** One freeze line + the blockers verbatim; null when not frozen.
   *  t261009-67: carries the cause certification and the chain of fixes
   *  (goal 167: the signer sees what froze the line and which fix is
   *  reopening it). */
  frozenFace: {
    banner: string
    blockers: string[]
    cause: string
    fixChain: FixChainRow[]
  } | null
  deliveredTotal: number
  certified: CertifiedRow[]
  waiting: WaitingRow[]
  /** What one signature would still promote: the UNDELIVERED certified part
   *  (a freeze never holds the certified part hostage — design goal 8). */
  promotable: number
  /** t261016-09 (D4): the refusal face — non-empty exactly when promotable
   *  is 0, naming WHY nothing can be promoted. Never a mute "Promote 0". */
  promoteBlock: string
  /** The moment of the boundary: the round that certified the covered set. */
  boundary: { at: string; runId: string } | null
  rounds: RoundFace[]
  roundState: 'idle' | 'running'
}

/** Empty face with a reason: the explicit degradation, never a guessed count. */
function emptyFace(reason: string): CertificationFace {
  return {
    ok: false, reason, lineId: '', state: 'GREEN', frozen: false,
    frozenFace: null, deliveredTotal: 0, certified: [], waiting: [],
    promotable: 0, promoteBlock: 'nothing is certified yet',
    boundary: null, rounds: [], roundState: 'idle',
  }
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : NaN
}

function list(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter(isObj) : []
}

function optStr(v: unknown): boolean {
  return v === null || v === undefined || typeof v === 'string'
}

/** The engine's freeze_state output shape, validated: a freeze record that
 *  does not match it is NEVER silently read as "not frozen" — the fail-closed
 *  ledger rule. Missing freeze (null/undefined) is a legitimate no-freeze. */
function freezeFace(v: unknown): { frozen: boolean; culprit: string } | null {
  if (v === null || v === undefined) return { frozen: false, culprit: '' }
  if (!isObj(v)) return null
  if (typeof v.frozen !== 'boolean') return null
  if (!optStr(v.episode) || !optStr(v.cause) || !optStr(v.culprit)) return null
  if (v.closed_at !== null && v.closed_at !== undefined
    && typeof v.closed_at !== 'number') return null
  return { frozen: v.frozen, culprit: str(v.culprit).trim() }
}

/** The engine's open_freeze_summary output, validated (t261009-67). Absent
 *  (null/undefined) = an older adapter receipt: an empty signer face rides
 *  along. Present but malformed degrades the whole face by name — a frozen
 *  line whose signer face cannot be read is never rendered as if it could. */
function freezeSummaryFace(v: unknown): {
  cause: string
  fixChain: FixChainRow[]
} | null {
  if (v === null || v === undefined) return { cause: '', fixChain: [] }
  if (!isObj(v)) return null
  if (!optStr(v.cause) || !optStr(v.freeze)) return null
  if (v.fix_landings !== undefined && !Array.isArray(v.fix_landings)) {
    return null
  }
  if (Array.isArray(v.fix_landings)
    && v.fix_landings.some((x) => !isObj(x))) {
    return null
  }
  const fixChain: FixChainRow[] = list(v.fix_landings).map((r) => {
    const repairs = list(r.repairs)
    let repaired: string | null = null
    for (const rep of repairs) {
      const cand = rep.repaired
      if (typeof cand === 'string' && cand.trim()) repaired = cand.trim()
    }
    return {
      landing: str(r.landing).trim(),
      ticket: str(r.ticket).trim(),
      repaired,
    }
  })
  return { cause: str(v.cause).trim(), fixChain }
}

/** 'YYYY-MM-DD HH:MM', 24h local — every moment the face shows carries its
 *  date (t261019-23 F3: a clock-only '10:45' reads as today even when the
 *  landing is a week old). */
export function formatStamp(ms: unknown): string {
  const n = num(ms)
  if (Number.isNaN(n) || n < 0) return ''
  const d = new Date(n)
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` + p(d.getHours()) + ':' + p(d.getMinutes())
}

/** Legacy clock-only shape (HH:MM), kept for callers that render a moment
 *  whose date is on-screen already. No face field uses it since t261019-23. */
export function formatClock(ms: unknown): string {
  const n = num(ms)
  if (Number.isNaN(n) || n < 0) return ''
  const d = new Date(n)
  const p = (x: number) => String(x).padStart(2, '0')
  return p(d.getHours()) + ':' + p(d.getMinutes())
}

/** The engine's mechanical roll-up (develop_certify.run_verdict), shaped. */
export function verdictFace(cases: unknown): { verdict: 'green' | 'red'; blockers: number; result: { pass: number; fail: number; env: number } } {
  const c = isObj(cases) ? cases : {}
  const ran = num(c.ran) || 0
  const passed = num(c.passed) || 0
  const failed = num(c.failed) || 0
  const env = num(c.env_failed) || 0
  const green = ran > 0 && failed === 0 && env === 0
  return { verdict: green ? 'green' : 'red', blockers: failed + env, result: { pass: passed, fail: failed, env } }
}

/** t261016-09 (D4): the engine's OWN green caliber — the run ledger row's
 *  `verdict` field, exactly what develop_promote._is_green_reader reads
 *  (obj.verdict == "green"; absent/unknown/unreadable -> not green, never
 *  guessed). The panel used to recompute the absolute roll-up here and so
 *  painted red the very rounds the engine certifies. This is the one green
 *  answer for coverage and boundary decisions; `verdictFace` stays display-
 *  side only (the counts line). */
export function ledgerGreen(run: unknown): boolean {
  return isObj(run) && run.verdict === 'green'
}

/** 'line <repo>:<sha8>' — the measured column's only legal shape. The repo
 *  word comes off the run record's own repos entry so the short sha reads as
 *  a revision of a named repo, not a serial number (t261019-23 F6). Never
 *  'main@… +N'; an absent sha stays 'line ?'. */
export function measuredToken(repos: unknown): string {
  const arr = Array.isArray(repos) ? repos.filter(isObj) : []
  const first = arr[0] ?? {}
  const rev = str(first.revision)
  const repo = str(first.repo)
  const sha = rev ? rev.slice(0, 8) : '?'
  return repo ? `line ${repo}:${sha}` : 'line ' + sha
}

/** Newest-first sort KEY over a wait record's own moment: the waiting_since
 *  number itself, or -Infinity when it is missing/non-numeric (the row then
 *  sorts LAST and still renders — named by its empty landedAt — never
 *  dropped) (t261019-23 F4, review C1). */
export function waitingMoment(v: unknown): number {
  const n = num(isObj(v) ? v.waiting_since : NaN)
  return Number.isNaN(n) ? -Infinity : n
}

/** Trigger word from the run record's own `source`. Records carry 'scheduled'
 *  (chained/scheduled by itself) or a person/agent-driven source. */
export function triggerWord(source: unknown): 'auto' | 'manual' {
  return source === 'scheduled' ? 'auto' : 'manual'
}

function metaFor(ticketMeta: unknown, ticket: string): TicketMeta {
  const m = isObj(ticketMeta) ? ticketMeta : {}
  const t = isObj(m[ticket]) ? m[ticket] : {}
  return { title: t.title, epic: t.epic }
}

/**
 * Derive the whole tab face. Malformed input degrades by name, never throws.
 */
export function deriveCertificationFace(input: CertificationInput): CertificationFace {
  if (!isObj(input)) return emptyFace('input not an object')
  const lineId = str((isObj(input.line) ? input.line : {}).line_id).trim()
  if (!lineId) return emptyFace('line_id missing')

  const freeze = freezeFace(input.freeze)
  if (freeze === null) return emptyFace('freeze record unreadable')
  const summary = freezeSummaryFace(input.freezeSummary)
  if (summary === null) return emptyFace('freeze summary unreadable')
  const frozen = freeze.frozen
  const culprit = freeze.culprit
  const frozenFace = frozen
    ? {
        banner: 'Frozen by a red round — new landings stop; the certified part can still be promoted.',
        blockers: culprit ? [culprit] : [],
        cause: summary.cause,
        fixChain: summary.fixChain,
      }
    : null

  const outcomes = list(input.outcomes)
  const waits = list(input.waitStates)
  const certs = list(input.certs)
  const runs = list(input.runs)

  // Delivered: a running total — promoted and not withdrawn. Engine-derived
  // per-ticket facts, summed; never shown inside the bar's scale.
  const delivered = new Set(outcomes
    .filter((o) => typeof o.delivered_in === 'string' && o.ending !== 'withdrawn')
    .map((o) => str(o.ticket)))
  const deliveredTotal = delivered.size

  // Certified / waiting: the engine's own wait-state words decide the side.
  // t261016-09 (D4): a delivered ticket STAYS on the certified list with its
  // own marker — coverage outlives promotion, and silently subtracting it
  // emptied the table by construction once everything was promoted (the
  // host-measured "certified table is always empty"). What one signature
  // would still promote is the UNDELIVERED part; the split is stated, never
  // hidden.
  // t261019-23 (F4, review C1): BOTH lists sort newest-first by the row's own
  // waiting_since (the engine puts it on every wait-state row, certified
  // included); a row without a readable moment sorts last and still renders.
  const orderedWaits = waits.slice().sort((a, b) => waitingMoment(b) - waitingMoment(a))
  const certified: CertifiedRow[] = []
  const waiting: WaitingRow[] = []
  for (const w of orderedWaits) {
    const ticket = str(w.ticket).trim()
    if (!ticket) continue
    const state = str(w.state)
    const meta = metaFor(input.ticketMeta, ticket)
    const row: TicketRow = {
      ticket,
      title: str(meta.title),
      epic: str(meta.epic),
    }
    if (state === 'certified') {
      certified.push({ ...row, certifiedBy: str(w.covered_by), delivered: delivered.has(ticket), landedAt: formatStamp(w.waiting_since) })
    } else if (state === 'waiting' || state === 'red_implicated') {
      waiting.push({
        ...row,
        landedAt: formatStamp(w.waiting_since),
        redImplicated: state === 'red_implicated',
      })
    }
    // 'reverted' and every other engine word: not on this tab's two lists.
  }
  const promotableCount = certified.filter((c) => !c.delivered).length
  // The refusal face: promotable === 0 always names its reason (t261016-09).
  const promoteBlock = promotableCount > 0
    ? ''
    : (certified.length
      ? `all ${certified.length} certified ticket(s) are already delivered`
      : 'nothing is certified yet')

  // The boundary: the latest green certification that covers the certified set.
  const coveredIds = new Set(certified.map((c) => c.certifiedBy))
  const covering = certs
    .filter((c) => coveredIds.has(str(c.id)))
    .filter((c) => {
      const run = runs.find((r) => str(r.id) === str(c.run))
      // t261016-09 (D4): the engine's own caliber (ledgerGreen) decides — an
      // absent run record or an absent/unknown verdict is never green.
      return !!run && ledgerGreen(run)
    })
    .sort((a, b) => (num(a.at) || 0) - (num(b.at) || 0))
  const boundaryCert = covering[covering.length - 1] ?? null
  const boundary = boundaryCert
    ? { at: formatStamp(boundaryCert.at), runId: str(boundaryCert.run) }
    : null

  const rounds: RoundFace[] = runs.map((r) => {
    // Display verdict: the row's OWN verdict word decides when it is a known
    // word (the engine's caliber); only an absent/unknown word falls back to
    // the absolute roll-up shape, and that fallback can still never read a
    // ledger row green against its own word (ledgerGreen guards coverage).
    const own = str((isObj(r) ? r : {}).verdict)
    const v = verdictFace(isObj(r) ? r.cases : undefined)
    const verdict: 'green' | 'red' = own === 'green' ? 'green'
      : own === 'red' || own === 'no_proof' ? 'red'
      : v.verdict
    return {
      runId: str(r.id),
      startedAt: formatStamp(r.started_at),
      trigger: triggerWord(r.source),
      result: v.result,
      verdict,
      blockers: v.blockers,
      measured: measuredToken(r.repos),
    }
  })

  const rs = input.roundState === 'running' ? 'running' : 'idle'

  return {
    ok: true,
    reason: '',
    lineId,
    state: frozen ? 'FROZEN' : 'GREEN',
    frozen,
    frozenFace,
    deliveredTotal,
    certified,
    waiting,
    promotable: promotableCount,
    promoteBlock,
    boundary,
    rounds,
    roundState: rs,
  }
}

/** The promote gate: disabled only when there is nothing to promote. Freeze
 *  never holds the certified part hostage (develop-buffer design goal 8). */
export function promoteDisabled(face: CertificationFace): boolean {
  return face.promotable === 0
}

/** Vocabulary guard for tests: every fixed word the face may produce. */
export function faceVocabulary(): readonly string[] {
  return FACE_WORDS
}
