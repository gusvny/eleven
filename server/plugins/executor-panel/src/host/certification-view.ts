/**
 * certification-view.ts — the Certification tab's pure render core
 * (t261009-44 Slice 2). Closure-free like buildPeriodViewCore: every table and
 * copy table it needs is an argument, so the unit test and the page run ONE
 * implementation (the page embeds this function's source via String()).
 *
 * Layout law (the approved mock v15,
 * notes/discussions/261009-executor-certification-tab-mock.html):
 *   - ONE bar, ONE boundary: segments sized by cert/wait counts; the delivered
 *     total is a running number beside a fixed cap, never in the segment scale.
 *   - counts appear once: inside the segments and on the Promote button. The
 *     face carries no tally row and this core draws none.
 *   - `Promote N` is disabled only at zero — a freeze never holds the
 *     certified part hostage.
 *   - no glyph carries meaning; every label is an engine word or a mock word.
 *   - the promote dialog is explicitly ABSENT and named: this slice renders no
 *     promotion write path (the act stays a record-signed engine operation);
 *     the button renders, and activating it surfaces the named absence.
 *   - English copy; data (ids, titles, epics, revisions) untranslated.
 */

/** The face row vocabulary, fixed here once (the mock's column words). */
export const CERT_COPIES = {
  waiting: 'waiting',
  certified: 'certified',
  delivered: 'delivered',
  certifiedAt: 'certified',
  asOf: 'as of',
  idle: 'idle',
  running: 'running',
  promote: 'Promote',
  lineWord: 'line',
  red: 'red',
  blockers: 'blockers',
  green: 'green',
  // t261016-09 (D4): the delivered split is stated on the row, and a disabled
  // Promote button always names its reason next to itself.
  deliveredMark: 'delivered',
  promoteBlockWhy: 'Nothing can be promoted:',
  // The named absence: the one sentence that says the dialog is not faked.
  promoteAbsent: 'Promotion is not wired from the panel yet — the record-signed promote stays an engine operation. This tab shows what one signature would promote; it does not fake the dialog.',
  runAbsent: 'Rounds chain on the engine side; this panel starts none (the scheduler is another ticket).',
  degrade: 'The certification face is not derivable',
} as const

/** The helpers ride INSIDE each exported function's source: the page embeds
 *  these functions via String(), so each must be closure-free on its own
 *  (the t261009-37 lesson — module-private closures never reach the page).
 *  The one allowed module-level name is the copy table: the page aliases it
 *  (`var CERT_COPIES = CERT_RUNTIME.COPIES`) before the embed. */

/** t261012-03: the Rounds table + round dialog's copy table (the mock's own
 *  column and state words, fixed once). */
export const ROUND_COPIES = {
  rounds: 'Rounds',
  started: 'Started',
  trigger: 'Trigger',
  result: 'Result',
  verdict: 'Verdict',
  measured: 'Measured',
  running: 'running',
  green: 'green',
  red: 'red',
  noProof: 'no proof',
  couldNotRun: 'could not run',
  unreadableOutcome: 'unreadable outcome',
  noCell: '—',
  older: 'older rounds not shown',
  sectionError: 'The rounds faces are not readable',
  noSection: 'The receipt carries no round-faces section',
  resultSoFar: 'result so far',
  lastJudged: 'last judged',
  failures: 'Failures',
  scenario: 'Scenario',
  status: 'Status',
  duration: 'Duration',
  more: 'more',
  wrote: 'Wrote',
  nothingYet: 'nothing yet — the round is still running; the dialog states that instead of listing what it might write.',
  wroteAbsent: 'no ledger record cites this run',
  retainedLog: 'Retained log',
  logAbsent: 'retained log not written',
  countsUnreadable: 'counts unreadable',
  dialogRefused: 'The round record is not readable',
  triggerUnreadable: 'trigger unreadable',
  faceAbsent: 'no terminal face is retained for this run',
  // t261019-23 (F5): a running face never claims 'running' without its own
  // last-write moment, and a running face the engine face no longer backs
  // reads stale — never a terminal word (nothing is invented).
  lastWrite: 'last write',
  stale: 'stale',
  noWriteSince: 'no write since',
  writeUnreadable: 'write time unreadable',
} as const

/** '379 pass · 12 fail · 40 env' — the face's own counts. A counts_note (the
 *  face saying its counts are NOT a trustworthy roll-up, t261012-01) renders
 *  verbatim INSTEAD of the numbers: a round with unreadable counts never reads
 *  as a completed zero line (KI-01M4P0FK2W87WXW2S6N8BXECYZ). A face without a
 *  counts object names the absence — never invented zeros. */
export function countsCell(counts: unknown, note: unknown): string {
  if (typeof note === 'string' && note) return note
  if (typeof counts !== 'object' || counts === null || Array.isArray(counts)) {
    return ROUND_COPIES.countsUnreadable
  }
  const c = counts as Record<string, unknown>
  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  return `${num(c.pass)} pass · ${num(c.fail)} fail · ${num(c.env_fail)} env`
}

/** The state pill: derived from the face's OWN fields only, in a fixed order
 *  — running wins first, then the failed state (a could-not-run round never
 *  falls through to an outcome word), then the outcome verdict. No glyph
 *  carries meaning; every word is a face word. */
export function roundPill(face: unknown): { k: string; text: string } {
  const f = (typeof face === 'object' && face !== null && !Array.isArray(face))
    ? face as Record<string, unknown> : {}
  if (f.state === 'running') return { k: 'run', text: ROUND_COPIES.running }
  if (f.state === 'failed') return { k: 'none', text: ROUND_COPIES.couldNotRun }
  const o = (typeof f.outcome === 'object' && f.outcome !== null && !Array.isArray(f.outcome))
    ? f.outcome as Record<string, unknown> : null
  const v = o ? String(o.verdict ?? '') : ''
  if (v === 'green') return { k: 'green', text: ROUND_COPIES.green }
  if (v === 'red') return { k: 'red', text: ROUND_COPIES.red }
  if (v === 'no_proof') return { k: 'none', text: ROUND_COPIES.noProof }
  return { k: 'none', text: ROUND_COPIES.unreadableOutcome }
}

/** The terminal reason (why a round is red / no proof / could not run) — an
 *  outcome field, absent while running. */
export function roundReason(face: unknown): string {
  const f = (typeof face === 'object' && face !== null && !Array.isArray(face))
    ? face as Record<string, unknown> : {}
  const o = (typeof f.outcome === 'object' && f.outcome !== null && !Array.isArray(f.outcome))
    ? f.outcome as Record<string, unknown> : null
  return o && typeof o.reason === 'string' ? o.reason : ''
}

/** The trigger word, pinned by certification-model.triggerWord ('scheduled'
 *  → auto, anything else → manual); inlined here because every consumer is
 *  embedded via String() — no module imports survive the embed. */
export function roundTriggerWord(source: unknown): string {
  return source === 'scheduled' ? 'auto' : 'manual'
}

/** 'auto' / 'manual' from the run headers the tab already carries (raw.runs);
 *  an unknown run id renders the em-dash, never a guessed trigger word. */
export function roundTrigger(runs: unknown, runId: unknown): string {
  const id = typeof runId === 'string' ? runId : ''
  if (!Array.isArray(runs)) return ROUND_COPIES.noCell
  for (const r of runs) {
    const h = (typeof r === 'object' && r !== null) ? r as Record<string, unknown> : {}
    if (h.id === id) {
      const s = h.source
      return typeof s === 'string' && s ? roundTriggerWord(s) : ROUND_COPIES.noCell
    }
  }
  return ROUND_COPIES.noCell
}

/** The round face's revision set -> 'line repo:sha8' — the measured cell's
 *  only legal shape. t261019-23 (F6, rework): the face writer's shape is ONE
 *  `{repo, revision}` entry; a repo-keyed `{<repo>: <rev>}` map is accepted
 *  too (older fixtures). The sha is cut to 8 AND labelled with its repo and
 *  the 'line' word, so a short hash never reads as a serial number; an
 *  entry without a repo name renders the plain sha fallback; no readable
 *  revision renders 'line ?' — never a made-up label. */
export function roundMeasured(revision: unknown): string {
  const cut = (rev: unknown): string => {
    const s = (typeof rev === 'string' || typeof rev === 'number') ? String(rev) : ''
    return s.slice(0, 8) // LIST-CAP-OK: revision-label width, not a list cap
  }
  if (typeof revision !== 'object' || revision === null || Array.isArray(revision)) {
    return ROUND_COPIES.noCell
  }
  const rec = revision as Record<string, unknown>
  if ('revision' in rec) {
    const repo = typeof rec.repo === 'string' && rec.repo ? rec.repo : ''
    const sha = cut(rec.revision)
    if (!sha) return 'line ?'
    return 'line ' + (repo ? repo + ':' + sha : sha)
  }
  const parts = Object.entries(rec)
    .map(([repo, rev]) => `line ${repo}:${cut(rev)}`) // LIST-CAP-OK: revision-label width, not a list cap
  return parts.length ? parts.join(' · ') : ROUND_COPIES.noCell
}

/**
 * The Rounds table's body + notes (t261012-03): rows from the runner's
 * published faces ONLY. `rf` is the receipt's round_faces section (validated
 * softly by the reader); `runs` is the tab's raw.runs (headers, for the
 * trigger column); `engineRunning` is the engine face's own roundState==='running'
 * answer — the second read source the running pill is reconciled against.
 * Per-row named states — an absent or unreadable face names itself in the
 * row, never counts in its place. The live face (current.json) leads; a
 * terminal face for the same run does not duplicate the row. Terminal rounds
 * sort newest-first by their own started_at (t261019-23 F4); a face without
 * a readable started_at sorts last.
 * t261019-23 (F5): a running face's pill carries its OWN last-write moment
 * (the face's updated_at); when the engine face says no round is running,
 * that same pill reads stale — a round that died mid-flight never reads
 * plainly 'running' again.
 */
export function buildRoundsRows(rf: unknown, runs: unknown, engineRunning?: boolean): string {
  const esc = (s: unknown): string => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')
  if (typeof rf !== 'object' || rf === null || Array.isArray(rf)) {
    return ''
  }
  const section = rf as Record<string, unknown>
  // t261019-23 (F6, rework): the Measured cell is the run header's OWN repos
  // entry shaped by the same rule as the model's measuredToken — 'line
  // <repo>:<sha8>', plain-sha fallback without a repo name, 'line ?' without
  // a readable revision. The face's revision object stays the fallback for a
  // run no header names (closure-free: the model module does not survive the
  // String() embed).
  const headerMeasured = (id: string): string => {
    if (Array.isArray(runs)) {
      for (const r of runs) {
        const h = (typeof r === 'object' && r !== null && !Array.isArray(r)) ? r as Record<string, unknown> : null
        if (!h || h.id !== id || !Array.isArray(h.repos) || !(h.repos as unknown[]).length) continue
        const first = (h.repos as unknown[])[0] as Record<string, unknown>
        const rev = (typeof first.revision === 'string' || typeof first.revision === 'number') ? String(first.revision) : ''
        if (!rev) return 'line ?'
        const sha = rev.slice(0, 8) // LIST-CAP-OK: revision-label width, not a list cap
        const repo = typeof first.repo === 'string' && first.repo ? first.repo : ''
        return 'line ' + (repo ? repo + ':' + sha : sha)
      }
    }
    return ''
  }
  const row = (runId: unknown, face: unknown, named: string): string => {
    const id = str(runId)
    const f = (typeof face === 'object' && face !== null && !Array.isArray(face))
      ? face as Record<string, unknown> : null
    let pill = f ? roundPill(f) : { k: 'none', text: named }
    if (f && f.state === 'running') {
      const stamp = str(f.updated_at) || ROUND_COPIES.writeUnreadable
      pill = engineRunning === false
        ? { k: 'none', text: `${ROUND_COPIES.stale} · ${ROUND_COPIES.noWriteSince} ${stamp}` }
        : { k: 'run', text: `${ROUND_COPIES.running} · ${ROUND_COPIES.lastWrite} ${stamp}` }
    }
    const result = f ? countsCell(f.counts, f.counts_note) : named
    const fromHeader = headerMeasured(id)
    const measured = fromHeader || (f ? roundMeasured(f.revision) : ROUND_COPIES.noCell)
    const started = f ? str(f.started_at) : ROUND_COPIES.noCell
    return `<tr data-run="${esc(id)}">`
      + `<td><span class="link mono" data-round-link="${esc(id)}" title="open the record of this round">${esc(id)}</span></td>`
      + `<td class="mono">${esc(started)}</td>`
      + `<td>${esc(roundTrigger(runs, id))}</td>`
      + `<td class="mono">${esc(result)}</td>`
      + `<td><span class="pill" data-k="${esc(pill.k)}">${esc(pill.text)}</span>`
      + (f && roundReason(f) ? ` <span class="k">${esc(roundReason(f))}</span>` : '')
      + '</td>'
      + `<td class="mono k">${esc(measured)}</td></tr>`
  }
  const rows: string[] = []
  const seen: Record<string, boolean> = {}
  const live = section.live
  if (typeof live === 'object' && live !== null) {
    const l = live as Record<string, unknown>
    if (l.ok === true) {
      const f = (typeof l.face === 'object' && l.face !== null && !Array.isArray(l.face))
        ? l.face as Record<string, unknown> : {}
      const id = str(f.run_id)
      seen[id] = true
      rows.push(row(id, f, ''))
    } else {
      rows.push(`<tr><td colspan="6" class="k">${esc(str(l.reason))}</td></tr>`)
    }
  }
  const entries = Array.isArray(section.rounds) ? section.rounds as Record<string, unknown>[] : []
  const startedOf = (e: Record<string, unknown>): string => {
    const f = (typeof e.face === 'object' && e.face !== null && !Array.isArray(e.face))
      ? e.face as Record<string, unknown> : {}
    return str(f.started_at)
  }
  entries.sort((a, b) => {
    const sa = startedOf(a)
    const sb = startedOf(b)
    return sa < sb ? 1 : sa > sb ? -1 : 0
  })
  for (const e of entries) {
    const id = str(e.run_id)
    if (seen[id]) continue
    seen[id] = true
    if (typeof e.face === 'object' && e.face !== null) {
      rows.push(row(id, e.face, ''))
    } else if (typeof e.absent === 'string') {
      rows.push(row(id, null, e.absent))
    } else {
      rows.push(row(id, null, str(e.reason) || 'face unreadable (reason absent)'))
    }
  }
  const body = rows.join('') || '<tr><td colspan="6" class="k">—</td></tr>'
  const older = typeof section.older === 'number' && section.older > 0
    ? `<div class="who" id="certRoundsOlder">${section.older} ${ROUND_COPIES.older}</div>` : ''
  return body + older
}

/**
 * The Rounds card's degrade banner: the section's own named error (an
 * unreadable rounds path) — the table above keeps its last readable state
 * (the page holds the last good section; degrade scope is THIS table only).
 */
export function roundsSectionNote(rf: unknown): string {
  if (typeof rf !== 'object' || rf === null || Array.isArray(rf)) {
    return `<div class="banner red" id="certRoundsDegrade">${ROUND_COPIES.noSection}</div>`
  }
  const err = (rf as Record<string, unknown>).error
  if (typeof err === 'string' && err) {
    return `<div class="banner red" id="certRoundsDegrade"><b>${ROUND_COPIES.sectionError}:</b> ${err
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>`
  }
  return ''
}

/**
 * The whole tab body from the route answer. `data` is the /api/certification
 * JSON (validated softly: a degraded answer renders its named reason).
 */
export function buildCertificationCore(data: Record<string, unknown>): string {
  const esc = (s: unknown): string => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')
  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  if (!data || data.ok !== true) {
    const reason = str(data && data.reason) || 'the reason above names what could not be read'
    // t261012-03 fault 2: a refusal receipt still carries the round-faces
    // section — the Rounds table survives the line declaration's refusal.
    const rfRefused = (typeof data.round_faces === 'object' && data.round_faces !== null && !Array.isArray(data.round_faces))
      ? data.round_faces : null
    const roundsCard = rfRefused
      ? `<div class="card"><h3>${ROUND_COPIES.rounds}</h3><div class="pad">`
        + roundsSectionNote(rfRefused)
        + `<table><thead><tr><th>Round</th><th>${ROUND_COPIES.started}</th><th>${ROUND_COPIES.trigger}</th><th>${ROUND_COPIES.result}</th><th>${ROUND_COPIES.verdict}</th><th>${ROUND_COPIES.measured}</th></tr></thead><tbody id="certRoundRows">${buildRoundsRows(rfRefused, [])}</tbody></table></div></div>`
      : ''
    return `<div class="banner red" id="certDegrade"><b>${CERT_COPIES.degrade}:</b> <span>${esc(reason)}</span></div>` + roundsCard
  }
  const face = (typeof data.face === 'object' && data.face !== null && !Array.isArray(data.face))
    ? data.face as Record<string, unknown> : {}
  const raw = (typeof data.raw === 'object' && data.raw !== null && !Array.isArray(data.raw))
    ? data.raw as Record<string, unknown> : {}
  const lines = Array.isArray(data.lines) ? data.lines as Record<string, unknown>[] : []
  const boundary = (typeof face.boundary === 'object' && face.boundary !== null && !Array.isArray(face.boundary))
    ? face.boundary as Record<string, unknown> : null
  const rounds = Array.isArray(face.rounds) ? face.rounds as Record<string, unknown>[] : []
  const asOf = boundary && str(boundary.at) ? str(boundary.at) : (rounds[0] ? str(rounds[0].startedAt) : '')
  const certified = Array.isArray(face.certified) ? face.certified as Record<string, unknown>[] : []
  const waiting = Array.isArray(face.waiting) ? face.waiting as Record<string, unknown>[] : []
  const promotable = num(face.promotable)
  const frozen = face.frozen === true
  const frozenFace = (typeof face.frozenFace === 'object' && face.frozenFace !== null && !Array.isArray(face.frozenFace))
    ? face.frozenFace as Record<string, unknown> : null
  const blockers = frozenFace && Array.isArray(frozenFace.blockers) ? frozenFace.blockers as unknown[] : []

  const options = lines.map((l) => {
    const id = str(l.line_id)
    return `<option value="${esc(id)}"${id === str(data.line) ? ' selected' : ''}>${esc(id)}</option>`
  }).join('')

  const cell = (ticket: unknown, title: unknown): string => {
    const t = str(ticket)
    return `<td><span class="link mono" title="open the ticket">${esc(t)}</span> <span class="ttl">${esc(str(title))}</span></td>`
  }
  const waitRows = waiting.map((w) =>
    `<tr>${cell(w.ticket, w.title)}<td class="mono k">${esc(str(w.epic))}</td><td class="mono k">${esc(str(w.landedAt))}</td></tr>`
  ).join('') || '<tr><td colspan="3" class="k">—</td></tr>'
  const certRows = certified.map((c) =>
    `<tr>${cell(c.ticket, c.title)}<td class="mono k">${esc(str(c.epic))}</td><td><span class="link mono" title="open the round's record">${esc(str(c.certifiedBy))}</span></td>`
      + `<td class="mono k">${esc(str(c.landedAt))}</td>`
      + `<td>${c.delivered === true ? `<span class="pill" data-k="none">${CERT_COPIES.deliveredMark}</span>` : ''}</td></tr>`
  ).join('') || '<tr><td colspan="5" class="k">—</td></tr>'
  // t261012-03: the Rounds table reads the runner's published faces (the
  // receipt's round_faces section), not a headers-derived projection. The
  // headers still feed the trigger column (raw.runs) — nothing else.
  const rf = (typeof data.round_faces === 'object' && data.round_faces !== null && !Array.isArray(data.round_faces))
    ? data.round_faces : null
  const runs = raw && Array.isArray(raw.runs) ? raw.runs : []

  return ''
    + `<div class="pick"><span class="lbl">Line</span><select id="certLine">${options}</select></div>`
    + `<div class="card" id="certStateCard"><div class="hd">`
    + `<span class="dot ${frozen ? 'r' : 'g'}" id="certDot"></span>`
    + `<span class="state" id="certBig">${esc(str(face.state))}</span>`
    + `<span class="chip" id="certWhen" title="the last round and its verdict — the state above is as of this round">${CERT_COPIES.asOf} ${esc(asOf)}</span>`
    + '</div><div class="pad">'
    // t261019-23 (F1/F7): the count-proportional bar is gone — certified only
    // grows, so it always filled and carried no information. The strip is
    // three labelled figures; promotable appears exactly ONCE, on the Promote
    // button below (the certified-not-delivered set and promotable are the
    // same set — it is never drawn twice).
    + '<div class="lbt" id="certBar">'
    + `<span id="certFigCertified" title="certified by the boundary round"><span class="k">${CERT_COPIES.certified}</span> <b class="mono">${certified.length}</b></span>`
    + `<span id="certDelivered" title="delivered: already in main — coverage outlives promotion"><span class="k">${CERT_COPIES.delivered}</span> <b class="mono">${num(face.deliveredTotal)}</b></span>`
    + `<span id="certFigWaiting" title="waiting for the next certification round"><span class="k">${CERT_COPIES.waiting}</span> <b class="mono">${waiting.length}</b></span>`
    + (boundary ? `<span id="certBnd" title="the certification point: covered by the green round of this moment">${CERT_COPIES.certifiedAt} ${esc(str(boundary.at))}</span>` : '')
    + '</div>'
    // t261019-23 (F2): the 'auto rounds' switch is gone — it had no handler
    // and could not be clicked, so a control-shaped element carried a lie.
    // The round-state word stays as plain text.
    + `<div class="flow"><span class="mono" id="certRoundState" title="one round at a time; a new round starts when the previous one ends">${esc(str(face.roundState) === 'running' ? CERT_COPIES.running : CERT_COPIES.idle)}</span>`
    + '</div>'
    + '</div></div>'
    + (frozen
      ? `<div class="banner red" id="certBanner"><b>FROZEN</b> <span id="certBannerTxt">${esc(str(frozenFace && frozenFace.banner))}</span>`
        + (frozenFace && str(frozenFace.cause) ? ` <span class="mono k" id="certCause" title="the red certification that opened this freeze episode">cause ${esc(str(frozenFace.cause))}</span>` : '')
        + (blockers.length ? ` <span class="mono k" id="certBannerNames">${esc(blockers.map((b) => str(b)).filter(Boolean).join(' · '))}</span>` : '')
        + (frozenFace && Array.isArray(frozenFace.fixChain) && frozenFace.fixChain.length
          ? `<div class="mono k" id="certFixChain" title="the landings made while the freeze was open — the exempt fixes and what each repairs; this chain is the next red's candidate culprits">fix chain: ${esc((frozenFace.fixChain as { landing?: unknown; ticket?: unknown; repaired?: unknown }[]).map((f) => `${str(f.ticket)} (${str(f.landing)}${f.repaired ? ' repairs ' + str(f.repaired) : ''})`).join(' → '))}</div>`
          : '')
        + '</div>'
      : '')
    + `<div class="card"><h3>${CERT_COPIES.waiting} <span class="k" id="certWaitCount">${waiting.length}</span></h3>`
    + `<div class="pad"><table><thead><tr><th>Ticket</th><th>Epic</th><th title="the landing record's own moment">Landed</th></tr></thead><tbody id="certWaitRows">${waitRows}</tbody></table></div></div>`
    + `<div class="card"><h3>${CERT_COPIES.certified} <span class="k" id="certCount">${certified.length}</span></h3>`
    + `<div class="pad"><table><thead><tr><th>Ticket</th><th>Epic</th><th title="the certification that covers it: certified_by">Certified by</th><th title="the row's own landing moment">Landed</th><th></th></tr></thead><tbody id="certRows">${certRows}</tbody></table>`
    + `<div style="display:flex;align-items:center;gap:8px;margin-top:8px"><span class="grow"></span>`
    + (promotable === 0 && str(face.promoteBlock)
      ? `<span class="k" id="certPromoBlock" title="why the promo control is disabled">${CERT_COPIES.promoteBlockWhy} ${esc(str(face.promoteBlock))}</span>`
      : '')
    // t261019-23 rework (F7): the word 'Promote' appears EXACTLY once on the
    // face — the control itself. The internal ids/copy around it carry no
    // second occurrence (the promotable set IS the certified-not-delivered
    // set; it is never drawn twice).
    + `<button class="btn p" id="certPromo" data-promotable="${promotable}"${promotable === 0 ? ' disabled' : ''} title="disabled only when nothing is certified — a freeze never holds the certified part hostage">${CERT_COPIES.promote} ${promotable}</button>`
    + '</div>'
    + `<div class="who" id="certPromoNote" data-wired="false" hidden></div>`
    + '</div></div>'
    + `<div class="card"><h3>${ROUND_COPIES.rounds}</h3><div class="pad">`
    + roundsSectionNote(rf)
    + `<table><thead><tr><th>Round</th><th>${ROUND_COPIES.started}</th><th>${ROUND_COPIES.trigger}</th><th>${ROUND_COPIES.result}</th><th>${ROUND_COPIES.verdict}</th><th title="the revision set the round measured: the line head — what would be delivered if the certified part were promoted">${ROUND_COPIES.measured}</th></tr></thead><tbody id="certRoundRows">${rf ? buildRoundsRows(rf, runs, str(face.roundState) === 'running') : ''}</tbody></table>`
    + `<div class="who" id="certRunNote">${CERT_COPIES.runAbsent}</div></div></div>`
}

/**
 * The round dialog's body (t261012-03, the approved mock §2): ONE fetch per
 * open, rendered from the `round` mode's receipt. `d` is the
 * /api/certification/round JSON (validated softly — a refusal renders its
 * named reason). Blocks, in mock order: top (run id, state pill, line),
 * kv facts, Failures, the ONE Wrote line, the retained log path.
 */
export function buildRoundDialogCore(d: Record<string, unknown>): string {
  const esc = (s: unknown): string => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')
  if (!d || d.ok !== true) {
    const reason = str(d && d.reason) || 'the reason above names what could not be read'
    return `<div class="banner red" id="roundDegrade"><b>${ROUND_COPIES.dialogRefused}:</b> <span>${esc(reason)}</span></div>`
  }
  const face = (typeof d.face === 'object' && d.face !== null && !Array.isArray(d.face))
    ? d.face as Record<string, unknown> : null
  const faceNote = str(d.face_reason)
  let pill = face ? roundPill(face) : { k: 'none', text: faceNote || ROUND_COPIES.faceAbsent }
  // t261019-23 (F5): a running face claims its own last-write moment here
  // too — the dialog's receipt carries no second read source, so no stale
  // word is coined; the moment names the claim's age by itself.
  if (face && face.state === 'running') {
    pill = { k: 'run', text: `${ROUND_COPIES.running} · ${ROUND_COPIES.lastWrite} ${str(face.updated_at) || ROUND_COPIES.writeUnreadable}` }
  }
  const reason = face ? roundReason(face) : ''
  const counts = face ? countsCell(face.counts, face.counts_note) : ROUND_COPIES.countsUnreadable
  const running = face !== null && face.state === 'running'
  const failures = (typeof d.failures === 'object' && d.failures !== null && !Array.isArray(d.failures))
    ? d.failures as Record<string, unknown> : null
  const failuresAbsent = str(d.failures_absent)
  const failureRows = failures && Array.isArray(failures.rows)
    ? (failures.rows as Record<string, unknown>[])
      .map((f) => `<tr><td class="mono">${esc(str(f.name))}</td>`
        + `<td><span class="pill" data-k="${f.verdict === 'fail' ? 'red' : 'none'}">${esc(str(f.verdict))}</span></td>`
        + `<td class="mono k">${esc(str(f.duration))}</td></tr>`)
      .join('')
    : ''
  const more = failures && typeof failures.more === 'number' && failures.more > 0
    ? `<tr><td colspan="3" class="k">… ${failures.more} ${ROUND_COPIES.more}</td></tr>` : ''
  const failuresBody = failuresAbsent
    ? `<div class="k" id="roundFailuresAbsent">${esc(failuresAbsent)}</div>`
    : `<table><thead><tr><th>${ROUND_COPIES.scenario}</th><th>${ROUND_COPIES.status}</th><th>${ROUND_COPIES.duration}</th></tr></thead><tbody id="roundFailureRows">`
      + (failureRows || more || '<tr><td colspan="3" class="k">—</td></tr>') + more + '</tbody></table>'
  // The ONE Wrote line: running names the absence of a write; a terminal
  // failed round with no ledger row names its could-not-run reason; a
  // terminal round with no citing record names that absence. Several facts
  // render as ONE line with N clauses — nothing silently dropped.
  let wroteLine: string
  if (running) wroteLine = ROUND_COPIES.nothingYet
  else if (Array.isArray(d.wrote) && (d.wrote as unknown[]).length) {
    wroteLine = (d.wrote as unknown[]).map((c) => esc(str(c))).join(' · ')
  } else if (face && (face.state === 'failed' || reason)) {
    wroteLine = esc(reason || faceNote) || esc(ROUND_COPIES.wroteAbsent)
  } else {
    wroteLine = ROUND_COPIES.wroteAbsent
  }
  const wroteNote = str(d.wrote_note)
  const wrote = `<div class="k" id="roundWrote">${wroteLine}</div>`
    + (wroteNote ? `<div class="k" id="roundWroteNote">${esc(wroteNote)}</div>` : '')
  const logPath = str(d.log_path)
  const logAbsent = str(d.log_absent)
  const trigger = d.trigger == null
    ? (str(d.trigger_note) || ROUND_COPIES.triggerUnreadable)
    : roundTriggerWord(d.trigger)
  const last = failures && typeof failures.last === 'object' && failures.last !== null
    ? failures.last as Record<string, unknown> : null
  return ''
    + `<div class="top"><span class="mono" id="roundRunId"><b>${esc(str(d.run))}</b></span>`
    + `<span class="pill" data-k="${esc(pill.k)}" id="roundPill">${esc(pill.text)}</span>`
    + (face && str(face.line) ? `<span class="pill">line ${esc(str(face.line))}</span>` : '')
    + (reason ? `<span class="k" id="roundReason">${esc(reason)}</span>` : '')
    + '<span class="x" data-round-close="1">✕</span></div>'
    + '<div class="pad"><div class="kv">'
    + `<b>${ROUND_COPIES.measured}</b><span class="mono" id="roundMeasured">${face ? esc(roundMeasured(face.revision)) : ROUND_COPIES.noCell}</span>`
    + `<b>${ROUND_COPIES.started} · ${ROUND_COPIES.trigger}</b><span class="mono">${face ? esc(str(face.started_at)) : ROUND_COPIES.noCell} · ${esc(trigger)}</span>`
    + `<b>${running ? ROUND_COPIES.resultSoFar : ROUND_COPIES.verdict}</b><span class="mono" id="roundResult">${esc(counts)}</span>`
    + `<b>${ROUND_COPIES.lastJudged}</b><span class="mono" id="roundLastJudged">${last
      ? `${esc(str(last.name))} <span class="k">${esc(str(last.verdict))}${last.duration ? ' · ' + esc(str(last.duration)) : ''}</span>`
      : ROUND_COPIES.noCell}</span>`
    + '</div></div>'
    + `<div class="pad" style="border-top:1px solid var(--line)"><div style="font-weight:600;margin-bottom:4px">${ROUND_COPIES.failures}</div>${failuresBody}</div>`
    + `<div class="pad" style="border-top:1px solid var(--line)"><div style="font-weight:600;margin-bottom:4px">${ROUND_COPIES.wrote}</div>${wrote}</div>`
    + `<div class="pad" style="border-top:1px solid var(--line);display:flex;gap:8px;align-items:center">`
    + `<span>${ROUND_COPIES.retainedLog}</span>`
    + (logAbsent
      ? `<span class="k" id="roundLogAbsent">${esc(logAbsent)}</span>`
      : `<span class="mono k" id="roundLogPath">${esc(logPath)}</span>`)
    + '</div>'
}
