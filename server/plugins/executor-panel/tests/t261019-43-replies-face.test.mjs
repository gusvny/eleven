/**
 * t261019-43-replies-face.test.mjs — the reply face (replies leave the 11px trace).
 *
 * t261019-20 / host report 261019: the API returns rows[].replies, but the panel
 * rendered them only inside traceLine() (11px faint trace at the bottom of the
 * expanded body), attributed to a bare session id — so a collapsed row showed
 * nothing and the host read 'no reply' and re-asked (37 fact replies "never happened").
 *
 * Covers:
 * - replyBadge: '1 reply' / 'N replies', zero/non-array tolerance (never a throw);
 * - replyFace: named per-reply fields (by / intent / source_class / via / anchor /
 *   text); malformed inputs (non-array, non-object entries, missing text, missing
 *   by, string at, hostile markup) are literal placeholders, counted, never silent;
 * - static page contract: both cores embedded via String(fn), the .replies CSS
 *   present, rowHead/rowBody call sites wired, traceLine no longer renders replies.
 * Importing PANEL_HTML compiles the whole page (TS strip), so a broken template
 * fails this file first. Zero DOM, zero network, zero integration entry.
 */
import assert from 'node:assert/strict'
import { PANEL_HTML } from '../src/host/panel-page.ts'
import { replyBadge, replyFace } from '../src/host/page-logic.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- replyBadge: the collapsed-head signal ----
ok(replyBadge([]) === '', 'zero replies = empty badge (no stray meta)')
ok(replyBadge([{ text: 'x' }]) === '1 reply', 'one reply = "1 reply" (singular)')
ok(replyBadge([{ text: 'x' }, { text: 'y' }]) === '2 replies', 'two replies = "2 replies"')
ok(replyBadge(undefined) === '', 'undefined replies = empty badge (legacy rows)')
ok(replyBadge('nope') === '', 'non-array replies = empty badge, never a throw')

// ---- replyFace: the expanded per-reply named lines ----
const good = [{ type: 'reply', id: 'r1', reply_for: 'req-1', at: 1, text: 'the fact',
  by: 'session-133c76bf', intent: 'fact', source_class: 'project-session',
  via: 'bob', anchor: 'some anchor' }]
let f = replyFace(good)
ok(f.malformed === 0 && f.lines.length === 1, 'a well-formed reply parses clean')
ok(f.lines[0].by === 'session-133c76bf' && f.lines[0].text === 'the fact', 'by and text carried verbatim')
ok(f.lines[0].intent === 'fact' && f.lines[0].source_class === 'project-session', 'intent and source_class reach the face (the two fields the trace never showed)')
ok(f.lines[0].via === 'bob' && f.lines[0].anchor === 'some anchor', 'via and anchor carried (the delegated trio)')

// zero / malformed inputs — never a throw, never a silent drop
f = replyFace([])
ok(f.lines.length === 0 && f.malformed === 0, 'no replies = empty face')
f = replyFace(undefined)
ok(f.lines.length === 0 && f.malformed === 0, 'undefined replies = empty face (never a throw)')
f = replyFace('nope')
ok(f.lines.length === 0 && f.malformed === 0, 'non-array replies = empty face (never a throw)')
f = replyFace([null, 42])
ok(f.lines.length === 0 && f.malformed === 2, 'non-object entries are counted malformed, never silently dropped')
f = replyFace([{ by: 's1' }])
ok(f.malformed === 1 && f.lines[0].text === '(reply text missing)', 'a text-less reply is a counted placeholder line (KI: attribution without content)')
f = replyFace([{ text: 'hi' }])
ok(f.malformed === 0 && f.lines[0].by === '(unknown by)', 'a by-less reply still shows its text, by named (unknown by) — not lost')
// hostile markup stays literal data — escaping happens at the page (esc/renderMarkdown)
f = replyFace([{ text: '<script>alert(1)</script>', by: '<b>x</b>' }])
ok(f.lines[0].text.includes('<script>') && f.lines[0].by.includes('<b>'), 'hostile markup returns as raw data (page escapes; the core never injects)')

// ---- static page contract: one implementation, wired call sites ----
ok(PANEL_HTML.includes(String(replyBadge)) && PANEL_HTML.includes(String(replyFace)),
  'both cores embedded via String(fn) (the page and this test run one implementation)')
ok(PANEL_HTML.includes('.replies{margin-top:10px'), 'the .replies CSS block is present (readable face, not the 11px trace)')
ok(!PANEL_HTML.includes('.replies{color:var(--faint);font-size:11px'), 'the reply face does not reuse the 11px faint trace style')
ok(PANEL_HTML.includes("var rbadge = replyBadge(r.replies)"), 'rowHead carries the collapsed badge')
ok(PANEL_HTML.includes('function replyBlock(r)'), 'rowBody has the reply block builder')
ok((PANEL_HTML.match(/\+ replyBlock\(r\) \+ '<div class="trace">'/g) || []).length === 3,
  'all three rowBody branches (dismissed/answered/open) render the reply block above the trace')
ok(!/Reply by ' \+ rp\.by/.test(PANEL_HTML), 'traceLine no longer renders replies (one reply rendering home)')

console.log(`t261019-43-replies-face.test: ${n} checks passed`)
