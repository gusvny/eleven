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
  autoRounds: 'auto rounds',
  idle: 'idle',
  running: 'running',
  promote: 'Promote',
  lineWord: 'line',
  red: 'red',
  blockers: 'blockers',
  green: 'green',
  // The named absence: the one sentence that says the dialog is not faked.
  promoteAbsent: 'Promotion is not wired from the panel yet — the record-signed promote stays an engine operation. This tab shows what one signature would promote; it does not fake the dialog.',
  runAbsent: 'Rounds chain on the engine side; this panel starts none (the scheduler is another ticket).',
  degrade: 'The certification face is not derivable',
} as const

/** The helpers ride INSIDE each exported function's source: the page embeds
 *  these functions via String(), so each must be closure-free on its own
 *  (the t261009-37 lesson — module-private closures never reach the page). */
/** '478 pass · 4 fail · 16 env' — the rounds table's labelled summing result. */
export function resultCell(result: unknown): string {
  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  const r = (typeof result === 'object' && result !== null && !Array.isArray(result)) ? result as Record<string, unknown> : {}
  return `${num(r.pass)} pass · ${num(r.fail)} fail · ${num(r.env)} env`
}

/** 'red · 2 blockers' or 'green' — the mechanical verdict, never a glyph alone. */
export function verdictCell(verdict: unknown, blockers: unknown): string {
  const n = (typeof blockers === 'number' && Number.isFinite(blockers)) ? blockers : 0
  return verdict === 'red' ? `${CERT_COPIES.red} · ${n} ${CERT_COPIES.blockers}` : CERT_COPIES.green
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
    return `<div class="banner red" id="certDegrade"><b>${CERT_COPIES.degrade}:</b> <span>${esc(reason)}</span></div>`
  }
  const face = (typeof data.face === 'object' && data.face !== null && !Array.isArray(data.face))
    ? data.face as Record<string, unknown> : {}
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
    `<tr>${cell(c.ticket, c.title)}<td class="mono k">${esc(str(c.epic))}</td><td><span class="link mono" title="open the round's record">${esc(str(c.certifiedBy))}</span></td></tr>`
  ).join('') || '<tr><td colspan="3" class="k">—</td></tr>'
  const roundRows = rounds.map((r) =>
    `<tr><td><span class="link mono" title="open the record of this round">${esc(str(r.runId))}</span></td>`
    + `<td class="mono">${esc(str(r.startedAt))}</td>`
    + `<td title="${str(r.trigger) === 'auto' ? 'started by itself: chained onto the round before it' : 'started by a person'}">${esc(str(r.trigger))}</td>`
    + `<td class="mono">${esc(resultCell(r.result))}</td>`
    + `<td class="st ${str(r.verdict) === 'red' ? 'r' : 'g'}">${esc(verdictCell(r.verdict, r.blockers))}</td>`
    + `<td class="mono k">${esc(str(r.measured))}</td></tr>`
  ).join('') || '<tr><td colspan="6" class="k">—</td></tr>'

  return ''
    + `<div class="pick"><span class="lbl">Line</span><select id="certLine">${options}</select></div>`
    + `<div class="card" id="certStateCard"><div class="hd">`
    + `<span class="dot ${frozen ? 'r' : 'g'}" id="certDot"></span>`
    + `<span class="state" id="certBig">${esc(str(face.state))}</span>`
    + `<span class="chip" id="certWhen" title="the last round and its verdict — the state above is as of this round">${CERT_COPIES.asOf} ${esc(asOf)}</span>`
    + '</div><div class="pad">'
    + '<div class="linebar" id="certBar">'
    + '<div class="s cap" title="' + CERT_COPIES.delivered + '"></div>'
    + '<div class="s cert" style="flex:' + certified.length + '"><span>' + CERT_COPIES.certified + '</span><span class="n">' + certified.length + '</span></div>'
    + '<div class="s wait" style="flex:' + waiting.length + '"><span>' + CERT_COPIES.waiting + '</span><span class="n">' + waiting.length + '</span></div>'
    + '</div>'
    + `<div class="lbt"><span class="mono" id="certDelivered" title="delivered: already in main — the total, so it is a number here and a fixed bar above">${CERT_COPIES.delivered} ${num(face.deliveredTotal)}</span>`
    + (boundary ? `<span id="certBnd" title="the certification point: covered by the green round of this moment">${CERT_COPIES.certifiedAt} ${esc(str(boundary.at))}</span>` : '')
    + '</div>'
    + `<div class="flow"><span class="sw"><span class="track${frozen ? '' : ''}"><span class="knob"></span></span>${CERT_COPIES.autoRounds}</span>`
    + `<span class="mono" id="certRoundState" title="one round at a time; a new round starts when the previous one ends">${esc(str(face.roundState) === 'running' ? CERT_COPIES.running : CERT_COPIES.idle)}</span>`
    + '</div>'
    + '</div></div>'
    + (frozen
      ? `<div class="banner red" id="certBanner"><b>FROZEN</b> <span id="certBannerTxt">${esc(str(frozenFace && frozenFace.banner))}</span>`
        + (blockers.length ? ` <span class="mono k" id="certBannerNames">${esc(blockers.map((b) => str(b)).filter(Boolean).join(' · '))}</span>` : '')
        + '</div>'
      : '')
    + `<div class="card"><h3>${CERT_COPIES.waiting} <span class="k" id="certWaitCount">${waiting.length}</span></h3>`
    + `<div class="pad"><table><thead><tr><th>Ticket</th><th>Epic</th><th title="the landing record's own moment">Landed</th></tr></thead><tbody id="certWaitRows">${waitRows}</tbody></table></div></div>`
    + `<div class="card"><h3>${CERT_COPIES.certified} <span class="k" id="certCount">${certified.length}</span></h3>`
    + `<div class="pad"><table><thead><tr><th>Ticket</th><th>Epic</th><th title="the certification that covers it: certified_by">Certified by</th></tr></thead><tbody id="certRows">${certRows}</tbody></table>`
    + `<div style="display:flex;align-items:center;gap:8px;margin-top:8px"><span class="grow"></span>`
    + `<button class="btn p" id="certPromote" data-promotable="${promotable}"${promotable === 0 ? ' disabled' : ''} title="disabled only when nothing is certified — a freeze never holds the certified part hostage">${CERT_COPIES.promote} ${promotable}</button>`
    + '</div>'
    + `<div class="who" id="certPromoteNote" data-wired="false" hidden></div>`
    + '</div></div>'
    + `<div class="card"><h3>Rounds</h3><div class="pad"><table><thead><tr><th>Round</th><th>Started</th><th>Trigger</th><th>Result</th><th>Verdict</th><th title="the revision set the round measured: the line head — what would be delivered if the certified part were promoted">Measured</th></tr></thead><tbody id="certRoundRows">${roundRows}</tbody></table>`
    + `<div class="who" id="certRunNote">${CERT_COPIES.runAbsent}</div></div></div>`
}
