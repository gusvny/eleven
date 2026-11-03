/**
 * t261021-12-epics-case-sort.test.mjs — the pure legs of the t261021-12 pair:
 * the Epics tab renders in normal case and its activity sort is live.
 *
 * Two defects (host 261021):
 * 1. renderEpics built each epic card as class="sect"; the page stylesheet gives
 *    .sect text-transform:uppercase, so the whole tab rendered in capitals.
 *    Fix: the card carries its own container class (.epicCard); .sect stays a
 *    one-line heading style.
 * 2. The activity sort read row.updated_ts, but handleEpicTickets stripped the
 *    field — every epic tied at -1 and registry order won. Fix: the boundary
 *    mapper (server/plugins/workbench/src/host/epic-tickets.ts) carries the
 *    ticket list's `updated_ts` through, converted ONCE from epoch seconds to
 *    milliseconds; a malformed value is ABSENT (never 0, never now).
 *
 * Legs in this file (zero integration entry, plain node — they belong to the
 * executor-panel --pure fast lane):
 * - source leg: static contract on panel-page.ts / node.ts (house style of
 *   t261019-12-epics-tab.test.mjs);
 * - fixture leg: epicTicketRow consumed directly (real code, not a mirror) over
 *   valid / absent / malformed inputs, including hostile ones.
 *
 * Split note (t261103-27): the third leg — computed styles, epic order and the
 * rel-time tripwire on a SERVED page — drives a real browser, so it moved to
 * browser-t261021-12-epics-case-sort.test.mjs. The executor classifies by name
 * and refuses a browser dependency under a non-browser name: a file that
 * launches a browser must say so in its name. This file therefore carries no
 * browser dependency at all, and its two legs stay in the fast lane.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { epicTicketRow } from '../../workbench/src/host/epic-tickets.ts'
import assert from 'node:assert/strict'

const REPO = join(fileURLToPath(import.meta.url), '..', '..', '..', '..', '..')
const PAGE_PATH = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')
const NODE_PATH = join(REPO, 'server/plugins/workbench/node.ts')
const PAGE = readFileSync(PAGE_PATH, 'utf8')
const NODE = readFileSync(NODE_PATH, 'utf8')

let fails = 0
const ok = (cond, name, detail = '') => {
  if (cond) { console.log('ok   ' + name); return }
  fails += 1; console.log('FAIL ' + name + (detail ? ' — ' + detail : ''))
}

// ---- source leg: the card is a container with its own class, never .sect ----
ok(/\.epicCard\{[^}]*border:1px solid var\(--line\)[^}]*\}/.test(PAGE), 'the card class exists in the stylesheet and carries the box style')
ok(!/\.epicCard\{[^}]*text-transform:uppercase/.test(PAGE), 'the card class carries no uppercase transform')
ok(PAGE.includes("'<div class=\"epicCard\""), 'renderEpics opens the epic card with .epicCard')
ok(!/html\+='<div class="sect"[^>]*display:block/.test(PAGE), 'no .sect element is used as a display:block container in renderEpics')

// ---- source leg: the boundary mapper is wired into handleEpicTickets ----
ok(NODE.includes("import { epicTicketRow } from './src/host/epic-tickets.ts'"), 'node.ts imports the boundary mapper (no mirrored copy)')
ok(/\.map\(\(t\) => epicTicketRow\(t\)\)/.test(NODE), 'handleEpicTickets maps rows through epicTicketRow')
ok(!/id:\s*String\(t\?\.id[\s\S]{0,200}stage_state:\s*String\(t\?\.stage_state[\s\S]{0,60}\}\)\)/.test(NODE), 'the old field-stripping inline mapper is gone')
ok(!/updated_ts[\s\S]{0,40}\?\?\s*0/.test(NODE.split('epicTicketRow').join('')), 'no updated_ts-zero fallback in node.ts outside the mapper')

// ---- fixture leg: the real mapper over valid / absent / malformed inputs ----
const valid = epicTicketRow({ id: 't1', title: 'A', status: 'open', stage: 'implement', stage_state: 'running', updated_ts: 1700000000 })
assert.equal(valid.updated_ts, 1700000000000, 'valid: seconds converted to milliseconds once')
assert.equal(valid.id, 't1', 'valid: identity fields pass through')

const noTime = epicTicketRow({ id: 't2' })
ok(!('updated_ts' in noTime), 'absent field stays absent (no 0 fallback)')
for (const [name, bad] of [
  ['zero', 0],
  ['negative', -5],
  ['string', '1700000000'],
  ['null', null],
  ['NaN', Number.NaN],
  ['Infinity', Number.Infinity],
  ['object', { valueOf: () => 1700000000 }],
]) {
  const r = epicTicketRow({ id: 'x', updated_ts: bad })
  ok(!('updated_ts' in r), `malformed (${name}) is absent, never 0, never now`)
}
ok(!('updated_ts' in epicTicketRow(null)) && epicTicketRow(null).id === '', 'a null source row degrades to the honest empty row, no throw')

// ---- the page keeps its sort comparators intact (existing contract, now live) ----
ok(/epicLastActivity\(epicCodeOf\(b\)\)-epicLastActivity\(epicCodeOf\(a\)\)/.test(PAGE), 'the merged list still sorts newest-activity-first (t261019-12 contract)')
ok(PAGE.includes("'no activity'"), 'a no-readable-tickets epic shows the honest no-activity face, not a fabricated time')

console.log(fails === 0 ? 'done 1' : 'done 0')
process.exit(fails === 0 ? 0 : 1)
