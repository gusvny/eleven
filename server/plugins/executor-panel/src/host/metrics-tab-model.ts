/**
 * metrics-tab-model.ts — the Metrics tab v2 pure view-model layer (t261021-07).
 *
 * Closure-free pure functions only: the page embeds them via String(fn) (the
 * established panel pattern), so the unit test and the page always run ONE
 * implementation. Every module-level constant must ride along as a JSON embed
 * (the t261009-37 lesson) — nothing here may close over an import.
 *
 * Data sources (one fetch each, all GET, all same-origin):
 *  - metrics v2 (t261021-06 contract, docs/design/metrics-api-contract-v2.md):
 *    /sandbar-workbench/api/wf/metrics?...&view=time&mode=full — kpis,
 *    workflows[], stages[], epics[], project_sessions.
 *  - the same endpoint view=health — charts.primary is the daily
 *    opened/closed ChartSpec → the Throughput chart (t261026-05: the server
 *    ships this shape; the blocked chart it used to carry as primary moved
 *    to secondaries[0]).
 *  - the same endpoint view=token — charts.primary is the payload's OWN
 *    spec, rendered verbatim (today the per-stage token bar; the card shows
 *    the API's title so it says what it draws).
 *  - /sandbar-executor-panel/api/certification — round_faces.rounds → the
 *    certification strip and the green/red counts.
 *
 * FIELD-COUPLED(t261021-06) marks every read of a v2 field name. All of them
 * live inside `metricsV2Of` so a contract rename stays a one-function fix.
 *
 * Degrade law: a missing or malformed value renders the honest dash ('—') or
 * a named empty state — never zero, never a fabricated number, never an
 * explanatory sentence (the mock's behaviour prose is banned; labels, values,
 * axis titles and legends only).
 */

/** The tab's fixed copy (labels and the named-empty-state words). */
export const METRICS_TAB_COPIES = {
  dash: '—',
  allProjects: 'all projects',
  windowWord: 'window',
  projectWord: 'project',
  addWorkflow: '+ workflow',
  workflowChipRemove: '×',
  addEpic: '+ epic',
  sortActivity: 'Last activity',
  sortTickets: 'Tickets',
  sortElapsed: 'Elapsed',
  sortTokens: 'Tokens',
  ticketsWord: 'tickets',
  stageRunsWord: 'stage runs',
  elapsedWord: 'elapsed',
  tokensWord: 'tokens',
  openedWord: 'opened',
  closedWord: 'closed',
  roundWord: 'rounds',
  greenWord: 'green verdicts',
  redWord: 'red',
  flakyWord: 'flaky, quarantined',
  timeToGreen: 'time to green after a red',
  // Named empty states (a reason word each, never a behaviour sentence).
  noData: 'no data',
  reasonUnreachable: 'the metrics API could not be reached',
  reasonNoDailyTokens: 'the metrics response carries no per-day token face',
  reasonNoRoleTokens: 'the metrics response carries no per-role token face',
  reasonNoFlakyFace: 'the certification receipt carries no flaky face',
  reasonNoCert: 'the certification face could not be read',
} as const

/** The honest dash — exported because the page embed reads it from the JSON table. */
export const DASH = '—'

/** A finite number or null. Booleans, strings and NaN are malformed here. */
export function mnum(v: unknown): number | null {
  return (typeof v === 'number' && Number.isFinite(v)) ? v : null
}

/** A non-empty string or null. */
export function mstr(v: unknown): string | null {
  const s = (typeof v === 'string') ? v.trim() : ''
  return s.length > 0 ? s : null
}

/** Value or the honest dash. */
export function mdash(v: unknown): string {
  const n = mnum(v)
  if (n !== null) return String(n)
  return mstr(v) ?? DASH
}

/** Integer with thousands separators; malformed → dash. */
export function fmtInt(v: unknown): string {
  const n = mnum(v)
  if (n === null) return DASH
  return n.toLocaleString('en-US')
}

/** 0..1 share → whole percent, one decimal dropped; malformed → dash. */
export function fmtPct01(v: unknown): string {
  const n = mnum(v)
  if (n === null || n < 0) return DASH
  return Math.round(n * 100) + '%'
}

/** Token count → the mock's M scale ('412.6M', '2.1M'); malformed → dash. */
export function fmtTokensM(v: unknown): string {
  const n = mnum(v)
  if (n === null || n < 0) return DASH
  return (n / 1e6).toFixed(1) + 'M'
}

/** Milliseconds → '3h 40m' / '26m' / '2d 3h'; malformed → dash. */
export function fmtMs(v: unknown): string {
  const n = mnum(v)
  if (n === null || n < 0) return DASH
  const min = Math.round(n / 60000)
  const d = Math.floor(min / 1440)
  const h = Math.floor((min % 1440) / 60)
  const m = min % 60
  if (d > 0) return d + 'd ' + h + 'h'
  if (h > 0) return h + 'h ' + m + 'm'
  return m + 'm'
}

/** Epoch ms → the mock's relative words ('18m ago', '1h 05m ago', '1d 2h ago');
 *  malformed or future → dash. nowMs is injected (pure, testable). */
export function fmtAgo(v: unknown, nowMs: number): string {
  const n = mnum(v)
  if (n === null || n <= 0 || !(nowMs > n)) return DASH
  const min = Math.floor((nowMs - n) / 60000)
  if (min < 1) return 'just now'
  const d = Math.floor(min / 1440)
  const h = Math.floor((min % 1440) / 60)
  const m = min % 60
  if (d > 0) return d + 'd ' + h + 'h ago'
  if (h > 0) return h + 'h ' + String(m).padStart(2, '0') + 'm ago'
  return m + 'm ago'
}

/** The share-bar width percent of one value against a max (0..100 int);
 *  a non-positive or malformed max yields 0 (never NaN in CSS). */
export function shareBarPct(v: unknown, maxV: unknown): number {
  const n = mnum(v)
  const max = mnum(maxV)
  if (n === null || max === null || max <= 0 || n <= 0) return 0
  return Math.max(1, Math.min(100, Math.round((n / max) * 100))) // LIST-CAP-OK: percent clamp to the 0..100 scale, not a list cap
}

/**
 * The ONE place that reads the metrics v2 payload's field names.
 * FIELD-COUPLED(t261021-06): every contract rename is fixed here and nowhere
 * else. Returns the normalized view model, or { ok:false, reason } when the
 * envelope itself is not a readable metrics answer.
 */
export function metricsV2Of(j: unknown): Record<string, unknown> {
  const o = (j && typeof j === 'object' && !Array.isArray(j)) ? j as Record<string, unknown> : null
  if (!o || typeof o.kpis !== 'object' || o.kpis === null) {
    return { ok: false, reason: mstr((o as Record<string, unknown> | null)?.error) ?? 'no metrics payload' }
  }
  const k = o.kpis as Record<string, unknown>
  // FIELD-COUPLED(t261021-06): extended kpis names verbatim from the contract.
  const kpis = {
    tickets: mnum(k.tickets),
    closed: mnum(k.closed),
    rework_rate: mnum(k.rework_rate),
    throughput_per_day: mnum(k.throughput_per_day),
    median_lead_time: mnum(k.median_lead_time),
    p90_lead_time: mnum(k.p90_lead_time),
    human_wait_share: mnum(k.human_wait_share),
    tokens_total: mnum(k.tokens_total),
    tokens_in_tickets: mnum(k.tokens_in_tickets),
    tokens_outside_tickets: mnum(k.tokens_outside_tickets),
    tokens_per_closed_ticket: mnum(k.tokens_per_closed_ticket),
    // t261025-13 token-coverage inputs (workbench additive KPIs)
    tokens_cache_read: mnum(k.tokens_cache_read),
    tickets_with_usage: mnum(k.tickets_with_usage),
    closed_with_usage: mnum(k.closed_with_usage),
  }
  // FIELD-COUPLED(t261021-06): workflows[] block (each entry re-guarded —
  // a null/junk row inside the array is malformed, never a crash).
  const workflows = Array.isArray(o.workflows)
    ? (o.workflows as unknown[]).map(function (raw) {
        const w = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {}
        return {
          name: mstr(w.workflow),
          elapsed_ms: mnum(w.elapsed_ms),
          rounds_per_ticket: mnum(w.rounds_per_ticket),
          tickets: mnum(w.tickets),
          stage_runs: mnum(w.stage_runs),
        }
      }).filter(function (w) { return w.name !== null })
    : []
  // FIELD-COUPLED(t261021-06): stages[] block (per (workflow, stage), never mixed).
  const stages = Array.isArray(o.stages)
    ? (o.stages as unknown[]).map(function (raw) {
        const s = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {}
        return {
          workflow: mstr(s.workflow),
          stage: mstr(s.stage),
          runs: mnum(s.runs),
          elapsed_ms: mnum(s.elapsed_ms),
          avg_rounds: mnum(s.avg_rounds_per_ticket),
          tickets_reached: mnum(s.tickets_reached),
        }
      }).filter(function (s) { return s.workflow !== null && s.stage !== null })
    : []
  // FIELD-COUPLED(t261021-06): epics[] block.
  const epics = Array.isArray(o.epics)
    ? (o.epics as unknown[]).map(function (raw) {
        const e = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {}
        return {
          name: mstr(e.epic),
          tickets: mnum(e.tickets),
          elapsed_ms: mnum(e.elapsed_ms),
          tokens: mnum(e.tokens),
          last_activity_ms: mnum(e.last_activity_ms),
        }
      }).filter(function (e) { return e.name !== null })
    : []
  // FIELD-COUPLED(t261021-06): project_sessions block (null = named degrade).
  let sessions: Record<string, unknown> | null = null
  if (o.project_sessions && typeof o.project_sessions === 'object') {
    const ps = o.project_sessions as Record<string, unknown>
    const total = (ps.total && typeof ps.total === 'object') ? ps.total as Record<string, unknown> : null
    const buckets: Array<Record<string, unknown>> = []
    if (ps.buckets && typeof ps.buckets === 'object') {
      for (const slug of Object.keys(ps.buckets as Record<string, unknown>)) {
        const b = (ps.buckets as Record<string, unknown>)[slug]
        if (!b || typeof b !== 'object') continue
        const bb = b as Record<string, unknown>
        buckets.push({
          name: slug,
          tokens: ((mnum(bb.in) ?? 0) + (mnum(bb.out) ?? 0)),
          cache_read: mnum(bb.cache_read),
        })
      }
    }
    sessions = {
      total_tokens: total ? ((mnum(total.in) ?? 0) + (mnum(total.out) ?? 0)) : null,
      buckets,
      searched: mstr(ps.searched),
      reason: mstr(ps.reason),
    }
  }
  // The null-path carry (t261026-02, review item 1): when project_sessions is null
  // the reason + searched root travel in the payload's structured
  // project_sessions_degrade block (not only inside the joined notices string) and
  // are mapped into the view model so the row functions can name them.
  let sessionsDegrade: Record<string, unknown> | null = null
  if (sessions === null && o.project_sessions_degrade && typeof o.project_sessions_degrade === 'object') {
    const dg = o.project_sessions_degrade as Record<string, unknown>
    sessionsDegrade = { reason: mstr(dg.reason), searched: mstr(dg.searched) }
  }
  // FIELD-COUPLED(t261026-02): the role_aggregate block's field names verbatim —
  // one read here, like every other v2 block. Roles are guarded entry by entry
  // (a null/junk role row is malformed, never a crash).
  let roleAggregate: Record<string, unknown> | null = null
  if (o.role_aggregate && typeof o.role_aggregate === 'object') {
    const ra = o.role_aggregate as Record<string, unknown>
    const roles: Record<string, unknown> = {}
    if (ra.roles && typeof ra.roles === 'object') {
      for (const role of Object.keys(ra.roles as Record<string, unknown>)) {
        const e = (ra.roles as Record<string, unknown>)[role]
        if (!e || typeof e !== 'object') continue
        const ee = e as Record<string, unknown>
        roles[role] = {
          tickets: mnum(ee.tickets),
          files: mnum(ee.files),
          tokens: ((mnum(ee.in) ?? 0) + (mnum(ee.out) ?? 0)),
          cache_read: mnum(ee.cache_read),
          reason: mstr(ee.reason),
        }
      }
    }
    roleAggregate = { roles, searched: mstr(ra.searched), reason: mstr(ra.reason) }
  }
  const cache = (o.cache && typeof o.cache === 'object') ? o.cache as Record<string, unknown> : {}
  return {
    ok: true,
    reason: '',
    kpis,
    workflows,
    stages,
    epics,
    sessions,
    sessions_degrade: sessionsDegrade,
    role_aggregate: roleAggregate,
    cache_status: mstr(cache.status),
    generated_at: mstr(o.generated_at),
  }
}

/** The six KPI tiles (mock order, mock words). Every value may be the dash. */
export function kpiTilesOf(vm: Record<string, unknown>): Array<Record<string, string>> {
  const k = (vm.kpis ?? {}) as Record<string, unknown>
  const inTok = mnum(k.tokens_in_tickets)
  const outTok = mnum(k.tokens_outside_tickets)
  // t261025-13 item 2: a missing outside-tokens source (project_sessions null)
  // NAMES the degrade on the sub-line — a bare dash is the control-shaped lie the
  // host ruling bans. The split keeps rendering whenever both values exist.
  const tokenSub = (inTok !== null && outTok !== null)
    ? fmtTokensM(inTok) + ' in tickets · ' + fmtTokensM(outTok) + ' outside'
    : (inTok !== null
      ? fmtTokensM(inTok) + ' in tickets · outside unavailable (no project sessions)'
      : DASH)
  const closed = mnum(k.closed)
  const opened = mnum(k.tickets)
  const throughSub = (closed !== null && opened !== null)
    ? fmtInt(closed) + ' closed of ' + fmtInt(opened) + ' opened'
    : DASH
  // t261025-13 token-coverage ruling: three honest token tiles, each carrying an
  // over-N-of-M coverage line; the rework-rate tile is removed (the number is
  // stage-run semantics, not a tile face). All inputs null-degrade — a missing
  // source renders the dash or the named line, never a fabricated number.
  const cacheRead = mnum(k.tokens_cache_read)
  const covered = mnum(k.tickets_with_usage)
  const covSub = (covered !== null && opened !== null)
    ? fmtInt(covered) + ' of ' + fmtInt(opened) + ' tickets with usage'
    : DASH
  const fresh = mnum(k.tokens_in_tickets)
  const actualTraffic = (mnum(k.tokens_total) !== null && cacheRead !== null)
    ? (k.tokens_total as number) + cacheRead
    : null
  const tokensValue = fmtTokensM(actualTraffic)
  const tokensSub = (tokenSub !== DASH && covSub !== DASH) ? tokenSub + ' · ' + covSub
    : (tokenSub !== DASH ? tokenSub : covSub)
  const freshPerCovered = (fresh !== null && covered !== null && covered > 0)
    ? fresh / covered
    : null
  const cacheShare = (actualTraffic !== null && cacheRead !== null && actualTraffic > 0)
    ? cacheRead / actualTraffic
    : null
  return [
    { title: 'THROUGHPUT', value: (mnum(k.throughput_per_day) !== null ? (mnum(k.throughput_per_day) as number).toFixed(1) + '/day' : DASH), sub: throughSub },
    // t261025-13 item 3: the P90 sub renders the computed value when the payload
    // carries one; a null P90 degrades to a NAMED face, never a hardcoded 'P90 —'.
    { title: 'MEDIAN LEAD TIME', value: fmtMs(k.median_lead_time),
      sub: (mnum(k.p90_lead_time) !== null ? 'P90 ' + fmtMs(k.p90_lead_time) : 'P90 unavailable (empty window)') },
    { title: 'TOKENS', value: tokensValue, sub: tokensSub },
    { title: 'FRESH TOKENS PER COVERED TICKET', value: fmtTokensM(freshPerCovered), sub: covSub },
    { title: 'CACHE SHARE', value: fmtPct01(cacheShare), sub: covSub },
    { title: 'HUMAN WAIT', value: fmtPct01(k.human_wait_share), sub: 'of lead time, at gates' },
  ]
}

/**
 * The Where-the-time-goes rows. selected = the chip list (empty = all
 * workflows). Each row: name, elapsed, avg rounds ('×1.9' mock face), sub
 * 'N tickets · N stage runs', bar percent against the largest selected
 * elapsed. Unknown names in the selection are dropped silently (a chip for a
 * workflow the window no longer contains has no row to show).
 */
export function workflowRowsOf(vm: Record<string, unknown>, selected: string[]): Array<Record<string, unknown>> {
  const all = (vm.workflows ?? []) as Array<Record<string, unknown>>
  const sel = Array.isArray(selected) ? selected : []
  const rows = sel.length === 0 ? all : all.filter(function (w) { return sel.indexOf(String(w.name)) >= 0 })
  let max = 0
  for (const r of rows) { const e = mnum(r.elapsed_ms); if (e !== null && e > max) max = e }
  return rows.map(function (r) {
    const rounds = mnum(r.rounds_per_ticket)
    return {
      name: r.name,
      elapsed: fmtMs(r.elapsed_ms),
      // t261025-13 NOT-A-BUG wording: the number is stage executions per ticket —
      // name it so it is not read as rework loops.
      rounds: (rounds !== null ? '×' + rounds.toFixed(1) + ' stage runs' : DASH),
      sub: fmtInt(r.tickets) + ' ' + 'tickets' + ' · ' + fmtInt(r.stage_runs) + ' ' + 'stage runs',
      bar: shareBarPct(r.elapsed_ms, max),
    }
  })
}

/** One workflow's stage rows for the in-card drill (same card, never a page).
 *  Ordered as the payload's chain order (the stages[] contract keeps it). */
export function stageRowsOf(vm: Record<string, unknown>, workflow: string): Array<Record<string, unknown>> {
  const all = (vm.stages ?? []) as Array<Record<string, unknown>>
  const rows = all.filter(function (s) { return s.workflow === workflow })
  let max = 0
  for (const r of rows) { const e = mnum(r.elapsed_ms); if (e !== null && e > max) max = e }
  return rows.map(function (r) {
    const avg = mnum(r.avg_rounds)
    return {
      stage: r.stage,
      elapsed: fmtMs(r.elapsed_ms),
      rounds: (avg !== null ? '×' + avg.toFixed(1) : DASH),
      sub: fmtInt(r.tickets_reached) + ' ' + 'tickets' + ' · ' + fmtInt(r.runs) + ' ' + 'stage runs',
      bar: shareBarPct(r.elapsed_ms, max),
    }
  })
}

/** The five epic cards. sortKey: 'activity' (default) | 'tickets' | 'elapsed'
 *  | 'tokens'. picked = type-to-match multi-select names that join the top
 *  five even when the sort leaves them out. Null sort values sink; nulls
 *  inside a card stay the dash. */
export function epicCardsOf(vm: Record<string, unknown>, sortKey: string, picked: string[], nowMs: number): Array<Record<string, unknown>> {
  const all = ((vm.epics ?? []) as Array<Record<string, unknown>>).slice()
  const key = ['activity', 'tickets', 'elapsed', 'tokens'].indexOf(sortKey) >= 0 ? sortKey : 'activity'
  const field = key === 'activity' ? 'last_activity_ms' : (key === 'tickets' ? 'tickets' : (key === 'elapsed' ? 'elapsed_ms' : 'tokens'))
  all.sort(function (a, b) {
    const av = mnum(a[field])
    const bv = mnum(b[field])
    if (av === null && bv === null) return 0
    if (av === null) return 1
    if (bv === null) return -1
    return bv - av
  })
  const pick = Array.isArray(picked) ? picked : []
  const top = all.slice(0, 5) // LIST-CAP-OK: the approved mock's five-card epic row; declared in list-contracts.ts metrics_kpis.order ('top five plus the picked names')
  for (const name of pick) {
    if (top.some(function (c) { return c.name === name })) continue
    const found = all.find(function (c) { return c.name === name })
    if (found) top.push(found)
  }
  let max = 0
  for (const c of top) { const t = mnum(c.tokens); if (t !== null && t > max) max = t }
  return top.map(function (c) {
    return {
      name: c.name,
      tickets: fmtInt(c.tickets),
      elapsed: fmtMs(c.elapsed_ms),
      tokens: fmtTokensM(c.tokens),
      activity: fmtAgo(c.last_activity_ms, nowMs),
      bar: shareBarPct(c.tokens, max),
      picked: pick.indexOf(String(c.name)) >= 0,
    }
  })
}

/** The Project sessions rows (the mock's two buckets named; any other slug
 *  verbatim). sessions null or empty → the named empty state with the reason and
 *  the searched root (t261026-02: no bare dash for an unexplained absence), never
 *  zeros. */
export function sessionRowsOf(vm: Record<string, unknown>): Array<Record<string, string>> {
  const s = vm.sessions as Record<string, unknown> | null
  if (!s || ((s.buckets ?? []) as Array<Record<string, unknown>>).length === 0) {
    const dg = (vm.sessions_degrade ?? null) as Record<string, unknown> | null
    let sub = (s ? mstr(s.reason) : null) ?? (dg ? mstr(dg.reason) : null) ?? 'no project-level sessions'
    const searched = s ? mstr(s.searched) : (dg ? mstr(dg.searched) : null)
    if (searched) sub = sub + ' (searched ' + searched + ')'
    return [{ name: 'project sessions', value: DASH, sub }]
  }
  const buckets = (s.buckets ?? []) as Array<Record<string, unknown>>
  return buckets.map(function (b) {
    const name = String(b.name) === 'executor' ? 'executor session' : (String(b.name) === 'global' ? 'global session' : String(b.name))
    const cache = mnum(b.cache_read)
    const total = mnum(b.tokens) ?? 0
    const cachePct = (cache !== null && total > 0) ? ' · cache ' + Math.round((cache / (total + cache)) * 100) + '%' : ''
    return { name, value: fmtTokensM(b.tokens), sub: cachePct ? cachePct.slice(3) : DASH }
  })
}

/**
 * The certification summary from /api/certification's round_faces.
 * green/red count the rounds' outcome verdicts (the round-face vocabulary:
 * green | red | no_proof). flaky reads the optional per-face flaky marker —
 * the receipt carries none today, so the count stays the named dash rather
 * than a re-spelled no_proof (FIELD-COUPLED, one read here).
 */
export function certSummaryOf(j: unknown): Record<string, unknown> {
  const o = (j && typeof j === 'object') ? j as Record<string, unknown> : null
  const rf = o && typeof o.round_faces === 'object' ? o.round_faces as Record<string, unknown> : null
  const rounds = rf && Array.isArray(rf.rounds) ? rf.rounds as Array<Record<string, unknown>> : null
  if (!rounds) return { ok: false, reason: 'no rounds face', green: null, red: null, flaky: null, strip: [] as string[], ttg: DASH }
  let green = 0
  let red = 0
  const strip: string[] = []
  const stamps: Array<{ v: string; ms: number | null }> = []
  for (const r of rounds) {
    const face = (r && typeof r.face === 'object' && r.face !== null) ? r.face as Record<string, unknown> : null
    const outcome = (face && typeof face.outcome === 'object' && face.outcome !== null) ? face.outcome as Record<string, unknown> : null
    const v = outcome ? mstr(outcome.verdict) : null
    if (v === 'green') { green += 1; strip.push('green') }
    else if (v === 'red') { red += 1; strip.push('red') }
    else strip.push('other')
    const ts = face ? mnum(face.ts) : null
    stamps.push({ v: v ?? 'other', ms: ts })
  }
  // Time to green after a red: the first red → next green gap, median over
  // the gaps; needs per-round timestamps, else the honest dash.
  const gaps: number[] = []
  let pendingRed: number | null = null
  for (const s of stamps) {
    if (s.v === 'red' && pendingRed === null && s.ms !== null) { pendingRed = s.ms; continue }
    if (s.v === 'green' && pendingRed !== null && s.ms !== null && s.ms >= pendingRed) { gaps.push(s.ms - pendingRed); pendingRed = null }
  }
  gaps.sort(function (a, b) { return a - b })
  const ttg = gaps.length > 0 ? fmtMs(gaps[Math.floor((gaps.length - 1) / 2)]) : DASH
  let flaky: number | null = null
  for (const r of rounds) {
    const face = (r && typeof r.face === 'object' && r.face !== null) ? r.face as Record<string, unknown> : null
    const f = face ? mnum(face.flaky_count) : null
    if (f !== null) flaky = (flaky ?? 0) + f
  }
  return { ok: true, reason: '', green, red, flaky, strip: strip.slice(0, 60), ttg } // LIST-CAP-OK: display cap for the fixed-face per-round strip (payload rounds stay complete), not a data cap
}

/**
 * The Throughput chart spec from the health view's charts.primary (the daily
 * created/closed ChartSpec). FIELD-COUPLED: the series-name mapping lives
 * here (a name containing 'clos' is closed, the first other series is
 * opened). Not derivable → null (the chart's named empty state).
 */
export function throughputSpecOf(j: unknown): Record<string, unknown> | null {
  const o = (j && typeof j === 'object') ? j as Record<string, unknown> : null
  const charts = o && typeof o.charts === 'object' ? o.charts as Record<string, unknown> : null
  const p = charts && typeof charts.primary === 'object' ? charts.primary as Record<string, unknown> : null
  const cats = p && Array.isArray(p.categories) ? p.categories : null
  const series = p && Array.isArray(p.series) ? p.series as Array<Record<string, unknown>> : null
  if (!cats || !series) return null
  let opened: unknown[] | null = null
  let closed: unknown[] | null = null
  for (const s of series) {
    const name = mstr(s.name) ?? ''
    if (name.toLowerCase().indexOf('clos') >= 0) { closed = Array.isArray(s.data) ? s.data : null; continue }
    if (opened === null) opened = Array.isArray(s.data) ? s.data : null
  }
  if (!opened && !closed) return null
  return { days: cats.map(function (d) { return mstr(d) ?? DASH }), opened: opened ?? [], closed: closed ?? [] }
}

/**
 * The tokens stack from the token view's charts.primary — the payload's OWN
 * spec, rendered verbatim (t261026-05: the doc winner is the server; today
 * that is the per-stage token bar, not the daily-by-model series an older
 * docstring claimed). The spec's title travels with the shape so the card
 * can say what it draws; not derivable → null.
 */
export function tokensStackOf(j: unknown): Record<string, unknown> | null {
  const o = (j && typeof j === 'object') ? j as Record<string, unknown> : null
  const charts = o && typeof o.charts === 'object' ? o.charts as Record<string, unknown> : null
  const p = charts && typeof charts.primary === 'object' ? charts.primary as Record<string, unknown> : null
  const cats = p && Array.isArray(p.categories) ? p.categories : null
  const series = p && Array.isArray(p.series) ? p.series as Array<Record<string, unknown>> : null
  if (!cats || !series || series.length === 0) return null
  return {
    title: mstr(p.title),
    categories: cats.map(function (d) { return mstr(d) ?? DASH }),
    series: series.map(function (s) {
      return { name: mstr(s.name) ?? DASH, data: Array.isArray(s.data) ? s.data : [] }
    }),
  }
}

/**
 * The Tokens-by-role rows (t261026-02): each role face comes from the payload's
 * role_aggregate block — fresh tokens (in+out), cache share and ticket coverage.
 * A role with no session files in the window says 'no sessions in window' (a role
 * nobody ran under is never invented); a role with files but an unreadable face
 * carries its per-file reason; when the whole block is missing or empty the
 * block-level reason (which names the searched root) is the sub-line, so the
 * reader can tell 'nothing ran' from 'we looked in the wrong place'. Roles the
 * payload carries beyond the fixed three are appended verbatim.
 */
export function roleRowsOf(vm: Record<string, unknown>): Array<Record<string, string>> {
  const rows: Array<Record<string, string>> = []
  const ra = (vm.role_aggregate ?? null) as Record<string, unknown> | null
  const roles = (ra && typeof ra.roles === 'object' ? ra.roles : null) as Record<string, unknown> | null
  const names = ['developer', 'integration', 'executor']
  if (roles) for (const k of Object.keys(roles)) if (names.indexOf(k) < 0) names.push(k)
  for (const role of names) {
    const e = roles ? roles[role] as Record<string, unknown> | undefined : undefined
    if (!e) {
      // Block absent entirely (an older payload): 'no per-role face' is the honest
      // word — we cannot claim anything about sessions we never saw. Block present
      // but the role missing: genuinely no sessions for it in the window — unless
      // the block is entirely empty, then the block reason (naming the searched
      // root) is the honest sub-line.
      if (!roles) { rows.push({ name: role, value: DASH, sub: 'no per-role face' }); continue }
      const blockReason = mstr(ra.reason)
      const anyRole = Object.keys(roles).length > 0
      rows.push({ name: role, value: DASH, sub: (!anyRole && blockReason) ? blockReason : 'no sessions in window' })
      continue
    }
    const files = mnum(e.files) ?? 0
    const tokens = mnum(e.tokens)
    const reason = mstr(e.reason)
    if (files === 0 || tokens === null || tokens <= 0) {
      rows.push({ name: role, value: DASH, sub: reason ?? 'no sessions in window' })
      continue
    }
    const cache = mnum(e.cache_read)
    const cachePct = (cache !== null && cache > 0) ? ' · cache ' + Math.round((cache / (tokens + cache)) * 100) + '%' : ''
    rows.push({ name: role, value: fmtTokensM(tokens), sub: fmtInt(e.tickets) + ' tickets' + cachePct })
  }
  for (const r of sessionRowsOf(vm)) rows.push(r)
  return rows
}
