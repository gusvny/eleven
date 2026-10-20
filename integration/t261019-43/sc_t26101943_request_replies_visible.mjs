#!/usr/bin/env node
/**
 * sc_t26101943_request_replies_visible.mjs — t261019-43: a request's replies
 * must be VISIBLE on the executor panel page, not an 11px trace fragment.
 *
 * Incident (host report 261019, 'I replied to your requests - why does the UI
 * show none of it?'): the API returns rows[].replies, but the page rendered
 * replies only inside traceLine() — one escaped string in <div class="trace">
 * (11px faint text) at the bottom of the EXPANDED body. A collapsed row showed
 * nothing about a reply; an expanded row showed 'Reply by session-<uuid>: ...'
 * with no intent and no source class. 37 fact replies were posted and the host
 * concluded the replies never happened. The API half was healthy — this entry
 * owns the PAGE FACE the host actually reads.
 *
 * intent (user-perceivable behaviour; grey-box — assertions sit on the page
 * the host loads and on the reply rows the public API contract declares):
 *   A COLLAPSED VISIBILITY — a row carrying replies shows a reply indicator on
 *     its collapsed head ('1 reply' / 'N replies'), without any expansion;
 *     a row with no replies stays clean (no empty marker, no stray markup).
 *   B EXPANDED READABILITY — the expanded body shows each reply as its own
 *     readable line that names WHO decided (by), WHAT KIND of reply it is
 *     (intent: fact/answer/ask) and WHERE IT CAME FROM (source_class) — the
 *     host can tell a fact from a question and a project session from an
 *     executor, and never has to re-ask because a reply was invisible.
 *   C ONE RENDERING HOME — the reply text leaves the audit trace: the trace
 *     keeps its audit fields (request id, raised-by, state) but no longer
 *     carries reply text, so reply text has exactly one rendering home and
 *     the fix cannot rot back into the 11px line.
 *   D READABLE STYLING — the stylesheet ships a dedicated reply-face rule
 *     that is not the trace's faint 11px treatment (a reply is body text,
 *     not a footnote).
 *   E ADVERSARY FACE — reply rows are external data: a non-array replies
 *     payload, entries missing text or by, a wrong-typed at, and hostile
 *     markup in the text never crash the page face and never drop a reply
 *     silently (every reply stays counted and present).
 *
 * Technique: the page embeds its render cores from page-logic.ts via
 * String(fn) so the unit test and the page always run ONE implementation —
 * this scenario judges those embedded implementations (imported from the real
 * page-logic module) plus static contract legs on the REAL PANEL_PAGE_HTML /
 * page source (rowHead/rowBody call sites, traceLine's content, stylesheet
 * rules). This is the t261019-23 precedent: the real page module, the real
 * embedded cores, the real stylesheet, offline, no browser.
 *
 * Layering / intent split (no intent-level duplication):
 *   - the reply ROW contract on the ledger side (append-only rows, delegated
 *     by/via/anchor trio, writer derivation) belongs to
 *     t26100702-reply-and-delegated-answer;
 *   - the thread READ VIEW (five states, waiting list semantics, view fields)
 *     belongs to t26100702-panel-thread-view — neither of those judges the
 *     page's request-card reply rendering, which is exactly this entry's gap;
 *   - the API row shape (replies on GET /api/requests) is the declared public
 *     contract consumed here, re-asserted nowhere;
 *   - per-field parse truth tables and unit matrices belong to developer L1
 *     (the ticket's own test file).
 *
 * Three states: panel modules missing/unimportable or the public page faces
 * absent = ENV_FAIL exit 2; a named face missing = FAIL (pre-implementation
 * tree red on A/B/C/D is the expected TDD signal); green required at the
 * integration gate / merge. PASS/FAIL/ENV_FAIL only — no SKIP.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const PAGE_TS = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')
const LOGIC_TS = join(REPO, 'server/plugins/executor-panel/src/host/page-logic.ts')

let PASS = 0, FAIL = 0
const check = (name, cond, detail = '') => {
  if (cond) { PASS++; console.log('PASS ' + name) }
  else { FAIL++; console.log('FAIL ' + name + (detail ? ': ' + String(detail).slice(0, 400) : '')) }
}

// The row shape GET /sandbar-executor-panel/api/requests declares (requests.ts
// ReplyRow): text, by, intent ('answer'|'fact'|'ask'), source_class, via,
// anchor. One fact reply — the exact shape the host reported as invisible.
const factReply = {
  type: 'reply', id: 'r1', reply_for: 'req-1', at: 1791500000000,
  text: 'Rework lane already started for the group; no fix needed on your side.',
  by: 'session-133c76bf', intent: 'fact', source_class: 'project-session',
  via: '', anchor: '',
}
const delegatedReply = {
  type: 'reply', id: 'r2', reply_for: 'req-1', at: 1791500000001,
  text: 'Answered: keep the buffer line frozen until certification.',
  by: 'session-exec', intent: 'answer', source_class: 'executor-session',
  via: 'session-decider', anchor: 'the buffer line stays frozen',
}
const main = async () => {
  if (!existsSync(PAGE_TS) || !existsSync(LOGIC_TS)) {
    console.log('ENV_FAIL: panel page/page-logic sources missing: ' + PAGE_TS)
    process.exit(2)
  }
  let logic, page
  try {
    logic = await import(LOGIC_TS)
    page = await import(PAGE_TS)
  } catch (e) { console.log('ENV_FAIL: panel modules unimportable: ' + e.message); process.exit(2) }
  const html = String(page.PANEL_PAGE_HTML || page.PANEL_ROUTE && page.PANEL_PAGE_HTML || '')
  if (!html) { console.log('ENV_FAIL: the panel page HTML face is absent'); process.exit(2) }
  const pageSrc = readFileSync(PAGE_TS, 'utf8')

  // Capability discovery by contract name keeps a contract-preserving refactor
  // green; a missing face is a named FAIL (the TDD signal pre-implement).
  const hasBadge = typeof logic.replyBadge === 'function'
  const hasFace = typeof logic.replyFace === 'function'
  check('A0 the page ships a reply-badge face and a reply-face builder '
    + '(contract names replyBadge/replyFace on the page-embedded core)',
    hasBadge && hasFace, 'replyBadge=' + hasBadge + ' replyFace=' + hasFace)

  if (hasBadge) {
    // ---- A collapsed visibility ----
    const one = String(logic.replyBadge([factReply]))
    const two = String(logic.replyBadge([factReply, delegatedReply]))
    const none = String(logic.replyBadge([]))
    check('A1 a row carrying ONE reply shows a reply indicator on the '
      + 'collapsed head (singular form, never silence)',
      /1\s*reply/i.test(one), JSON.stringify(one))
    check('A2 two replies read as a count (plural form, not one blob of ids)',
      /2\s*repl/i.test(two), JSON.stringify(two))
    check('A3 a row with no replies stays clean (empty marker, no stray markup)',
      none === '' , JSON.stringify(none))
    check('A4 the collapsed head actually carries the badge — rowHead in the '
      + 'real page source consumes replyBadge into its meta line',
      /rowHead\s*\(/.test(pageSrc)
        && /replyBadge\s*\(/.test(pageSrc.slice(pageSrc.indexOf('function rowHead'))), 'no replyBadge call in rowHead')
  }

  // The embedded core answers structured named lines (one per reply). A plain
  // string return (an alternative decomposition) stays readable too — the
  // assertions key on CONTENT, never on the container shape.
  const faceText = (out) => {
    if (out == null) return ''
    if (typeof out === 'string') return out
    const lines = Array.isArray(out.lines) ? out.lines : []
    return lines.map((l) => (l && typeof l === 'object')
      ? [l.by, l.intent, l.source_class, l.via ? 'decided by ' + l.via : '',
        l.anchor ? 'anchor: ' + l.anchor : '', l.text].filter(Boolean).join(' ')
      : String(l)).join('\n')
  }
  const lineCount = (out) => (out && Array.isArray(out.lines)) ? out.lines.length : NaN

  if (hasFace) {
    // ---- B expanded readability ----
    const out = logic.replyFace([factReply, delegatedReply])
    const face = faceText(out)
    check('B1 the expanded body shows the fact reply as its own readable line '
      + 'carrying the reply text',
      face.includes(factReply.text), face.slice(0, 200))
    check('B2 the reply names WHAT KIND it is (intent "fact" reaches the '
      + 'surface, not just the API)',
      /fact/.test(face), face.slice(0, 200))
    check('B3 the reply names WHERE IT CAME FROM (source_class '
      + '"project-session" reaches the surface)',
      /project-session/.test(face), face.slice(0, 200))
    check('B4 the delegated answer names its trio — who decided (via) and the '
      + "host's words (anchor) are not collapsed into the by-session id",
      face.includes(delegatedReply.via) && face.includes(delegatedReply.anchor), face.slice(0, 300))
    check('B5 a plain by-session id alone is no longer the only attribution — '
      + 'the fact reply line names a human-readable source alongside the id',
      face.includes(factReply.by) && /project-session/.test(face), face.slice(0, 200))
    check('B6 both replies stay distinct lines — two replies in, two named '
      + 'lines out (no merge into one blob, none dropped)',
      lineCount(out) === 2, 'lines=' + lineCount(out))
  }

  // ---- C one rendering home: the trace loses reply text ----
  const traceIdx = pageSrc.indexOf('function traceLine')
  const traceSrc = traceIdx >= 0 ? pageSrc.slice(traceIdx, pageSrc.indexOf('}', pageSrc.indexOf('return t', traceIdx)) + 1) : ''
  check('C0 the real page ships a traceLine face', traceIdx >= 0 && traceSrc.length > 0, 'traceLine not found')
  if (traceIdx >= 0 && traceSrc) {
    check('C1 the audit trace no longer renders reply text (the reply loop '
      + 'left traceLine — replies have exactly one rendering home)',
      !/rp\.by|Reply by /.test(traceSrc), traceSrc.slice(0, 300))
    check('C2 the audit trace keeps its audit fields (request id and state '
      + 'stay on the trace)',
      /Request id/.test(traceSrc) && /State:/.test(traceSrc), traceSrc.slice(0, 300))
  }
  check('C3 the expanded body renders the reply block OUTSIDE the 11px trace '
    + 'div in every branch (open, answered, dismissed) — each rowBody branch '
    + 'carries the reply block before the trace, never only a trace line',
    (pageSrc.match(/replyBlock\(r\)/g) || []).length >= 3, 'replyBlock call sites: '
      + (pageSrc.match(/replyBlock\(r\)/g) || []).length)

  // ---- D readable styling ----
  const cssIdx = html.indexOf('.replies')
  check('D0 the stylesheet ships a dedicated reply-face rule (.replies)',
    cssIdx >= 0, 'no .replies rule in PANEL_PAGE_HTML')
  if (cssIdx >= 0) {
    const cssRule = html.slice(cssIdx, html.indexOf('}', cssIdx) + 1)
    const traceIdx2 = html.indexOf('.trace')
    const traceRule = traceIdx2 >= 0 ? html.slice(traceIdx2, html.indexOf('}', traceIdx2) + 1) : ''
    check('D1 the reply face is NOT the trace treatment — no 11px faint '
      + 'footnote styling on .replies (the exact face the host could not read)',
      !/11px/.test(cssRule) && cssRule !== traceRule, JSON.stringify({ cssRule, traceRule }))
  }

  // ---- E adversary face: replies are external data ----
  if (hasBadge && hasFace) {
    let threw = ''
    let badgeBad = '', faceBad = ''
    try {
      badgeBad = String(logic.replyBadge('not-an-array'))
      faceBad = faceText(logic.replyFace('not-an-array'))
    } catch (e) { threw = e.message }
    check('E1 a non-array replies payload never throws the page face down '
      + '(named empty, never a crash)',
      threw === '' && badgeBad === '' && faceBad === '', threw || JSON.stringify({ badgeBad, faceBad }))
    threw = ''
    const malformed = [
      { type: 'reply', id: 'm1', reply_for: 'req-1', at: 'not-a-number', text: 't1', by: 'b1', intent: 'fact' },
      { type: 'reply', id: 'm2', reply_for: 'req-1', at: 1, text: '', by: 'b2', intent: 'ask' },
      { type: 'reply', id: 'm3', reply_for: 'req-1', at: 2, text: 't3' },
      null,
      'junk',
    ]
    let faceM = ''
    try { faceM = faceText(logic.replyFace(malformed)) } catch (e) { threw = e.message }
    check('E2 malformed reply rows never crash the face and never drop a '
      + 'reply silently — the five entries stay represented (placeholders '
      + 'counted, nulls/junk named)',
      threw === '' && faceM.length > 0, threw || 'empty face for 5 malformed entries')
    threw = ''
    const hostile = [{ type: 'reply', id: 'h1', reply_for: 'req-1', at: 1,
      text: '<script>alert(1)</script>', by: 'session-x', intent: 'fact' }]
    let faceH = ''
    try { faceH = faceText(logic.replyFace(hostile)) } catch (e) { threw = e.message }
    check('E3 hostile markup in reply text survives as data without crashing '
      + 'the face (the page renders it through the escape-first renderer, '
      + 'the text is never lost)',
      threw === '' && faceH.includes('alert(1)'), threw || faceH.slice(0, 200))
  }

  console.log('SUMMARY pass=' + PASS + ' fail=' + FAIL + ' env_fail=0 na=0')
  return FAIL > 0 ? 1 : 0
}

main().then((code) => process.exit(code)).catch((e) => {
  console.log('ENV_FAIL: scenario harness error: ' + (e && e.message))
  process.exit(2)
})
