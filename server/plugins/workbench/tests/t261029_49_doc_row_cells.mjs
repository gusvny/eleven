/**
 * t261029-49 — the five cells of a docs list row: an epic row fills its own fields and
 * never leaves a blank.
 *
 * INTENT: docs/index.json now has an `epics` category whose 16 pages use their own
 * frontmatter schema (code / retired / summary) with no status, no updated and no tags.
 * Drawing those rows with the five-field projection left the status and updated cells
 * permanently empty, and an empty cell reads as "the data is missing" — that is the
 * second half of this ticket. This case pins the projection in
 * ../knowledge/src/shared/doc-row.ts: an epic row fills the three cells the five-field
 * rows fill with its own code / retired / summary, a field its schema does not have is
 * an explicit 'n/a', and no row ever renders an empty string.
 *
 * HIGH-LEVEL STEPS:
 *   A. epic row projection truth table: code -> title-cell badge, retired -> status cell,
 *      summary -> updated cell, tags cell explicit n/a; both retired shapes (boolean and
 *      the string an older index carried) and a missing summary have defined values.
 *   B. five-field rows unchanged: title/status/updated/tags pass through; a missing field
 *      becomes an explicit n/a (not a blank cell).
 *   C. malformed entries: null / {} / non-object / non-array tags / non-string fields /
 *      an unrecognised retired value — no throw, no fabrication, every cell non-empty.
 *   D. the rendering leg: the five <td> cells the list actually draws are produced from
 *      the projection and asserted non-empty; the epic row shows code / active|retired /
 *      summary and exactly one explicit n/a cell (tags).
 *   E. wiring: the client list really goes through this projection (source anchor) and
 *      the shipped bundle was rebuilt (it carries the projection; cjs and js identical).
 *
 * No temporary resources (source files and build artefacts are read, nothing is written).
 */
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { docRow, NOT_APPLICABLE, EPIC_CATEGORY } from '../../knowledge/src/shared/doc-row.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..', '..', '..', '..')
const KNOWLEDGE = join(REPO, 'server', 'plugins', 'knowledge')

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function eq(actual, expected, label) {
  ok(actual === expected, `${label} (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`)
}

/** Field-for-field the shape build_epics() in docs/scripts/build_index.py writes (t261029-45). */
const EPIC = {
  path: 'epics/agent-backend.md',
  file: 'agent-backend.md',
  title: 'agent-backend',
  category: 'epics',
  tags: [],
  code: 'agent-backend',
  retired: false,
  summary: 'Pluggable agent backends: a ticket can run on a different executor than its neighbour.',
  has_frontmatter: true,
}
const FIVE = {
  path: 'design/design-doc-writing-guide.md',
  file: 'design-doc-writing-guide.md',
  title: 'Design Document Writing Guide',
  category: 'design',
  tags: ['design doc', 'guideline'],
  status: 'active',
  updated: '2026-09-28',
  has_frontmatter: true,
}

section('A. epic row: its own schema fills the five-field cells')
const epic = docRow(EPIC)
ok(epic.isEpic === true, 'an epics-category entry is projected as an epic row')
eq(epic.title.text, 'agent-backend', 'title cell carries the entry title (never blank)')
eq(epic.code, 'agent-backend', 'the epic code is carried for the title cell badge')
eq(epic.status.text, 'active', 'retired=false renders as the status cell value "active"')
eq(epic.status.na, false, 'the status cell is data, not a placeholder')
eq(epic.status.field, 'retired', 'the status cell names the epic field it came from')
eq(epic.updated.text, EPIC.summary, 'the updated cell carries the epic summary')
eq(epic.updated.field, 'summary', 'the updated cell names the epic field it came from')
eq(epic.tagsCell.text, NOT_APPLICABLE, 'the epic schema has no tags -> explicit n/a')
ok(epic.tagsCell.na === true && epic.tags.length === 0, 'tags cell is an explicit placeholder, tags list empty')

const retired = docRow({ ...EPIC, retired: true })
eq(retired.status.text, 'retired', 'retired=true renders as the status cell value "retired"')
const retiredString = docRow({ ...EPIC, retired: 'true' })
eq(retiredString.status.text, 'retired', 'a string "true" (pre-rebuild index shape) also renders "retired"')
const noSummary = docRow({ ...EPIC, summary: '' })
eq(noSummary.updated.text, NOT_APPLICABLE, 'a missing summary is explicit n/a, never blank')
ok(noSummary.updated.na === true, 'the n/a marker is set, so the UI can style it as a placeholder')
const noCode = docRow({ ...EPIC, code: '' })
eq(noCode.code, 'agent-backend', 'a missing code falls back to the file stem (index path is authoritative)')

section('B. five-field rows: unchanged, and a missing field is n/a not blank')
const five = docRow(FIVE)
ok(five.isEpic === false, 'a design-category entry is not an epic row')
eq(five.title.text, FIVE.title, 'title passthrough')
eq(five.status.text, 'active', 'status passthrough')
eq(five.updated.text, '2026-09-28', 'updated passthrough')
eq(five.status.field, 'status', 'status cell names its field')
eq(five.tags.join('|'), 'design doc|guideline', 'tag chips passthrough')
eq(five.code, '', 'no code badge for a five-field row')
eq(five.tagsCell.na, false, 'a row with tags has no n/a tags cell')
const noStatus = docRow({ ...FIVE, status: undefined })
eq(noStatus.status.text, NOT_APPLICABLE, 'a five-field row without status shows n/a (was: blank cell)')
const noTags = docRow({ ...FIVE, tags: [] })
eq(noTags.tagsCell.text, NOT_APPLICABLE, 'a five-field row without tags shows n/a')

section('C. malformed entries: no throw, and no cell is ever blank')
const MALFORMED = [
  ['null', null],
  ['undefined', undefined],
  ['empty object', {}],
  ['a string', 'epics/x.md'],
  ['an array', [EPIC]],
  ['tags not an array', { ...FIVE, tags: 'design doc' }],
  ['tags with junk items', { ...FIVE, tags: [1, null, 'ok', ''] }],
  ['numeric fields', { path: 7, title: 9, status: 1, updated: {}, category: 'design' }],
  ['unrecognised retired', { ...EPIC, retired: 'maybe' }],
  ['epic without path', { category: EPIC_CATEGORY }],
]
for (const [label, entry] of MALFORMED) {
  let row = null, threw = ''
  try { row = docRow(entry) } catch (e) { threw = String(e && e.message || e) }
  ok(threw === '', `no throw on ${label}${threw ? ` (threw: ${threw})` : ''}`)
  if (row === null) continue
  const cells = [row.title, row.status, row.updated, row.tagsCell]
  ok(cells.every(c => typeof c.text === 'string' && c.text.trim() !== ''),
    `every cell has renderable text on ${label} (${cells.map(c => JSON.stringify(c.text)).join(' / ')})`)
}
const whacky = docRow({ ...EPIC, retired: 'maybe' })
eq(whacky.status.text, NOT_APPLICABLE, 'an unrecognised retired value is explicit n/a, never a guess')

section('D. rendering leg: the five cells the list actually draws')
/** Same order as the <tr> in src/client/index.tsx (title / category / tags / status /
 *  updated), text only, with data-field on the n/a cells — the decidable form of "the row
 *  renders no blank cell". */
function renderRow(entry) {
  const row = docRow(entry)
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const cellHtml = (c) => `<span class="${c.na ? 'kb-na' : 'kb-cell'}" data-field="${c.field}">${esc(c.text)}</span>`
  const tags = row.tags.length > 0
    ? row.tags.map(t => `<span class="kb-tag">${esc(t)}</span>`).join('')
    : cellHtml(row.tagsCell)
  const code = row.isEpic && row.code !== '' ? `<span class="kb-code" data-field="code">${esc(row.code)}</span>` : ''
  return `<tr data-doc-category="${row.category}">`
    + `<td>${cellHtml(row.title)}${code}<span class="kb-path">${esc(row.path)}</span></td>`
    + `<td><span class="kb-cat" data-cat="${row.category}">${esc(row.category)}</span></td>`
    + `<td>${tags}</td>`
    + `<td>${cellHtml(row.status)}</td>`
    + `<td>${cellHtml(row.updated)}</td>`
    + '</tr>'
}
const epicHtml = renderRow(EPIC)
const tds = [...epicHtml.matchAll(/<td>([\s\S]*?)<\/td>/g)].map(m => m[1])
eq(tds.length, 5, 'an epic row renders five cells')
ok(tds.every(td => td.replace(/<[^>]*>/g, '').trim() !== ''), 'no epic cell renders blank text')
ok(epicHtml.includes('agent-backend'), 'the epic code is on the row')
ok(epicHtml.includes('>active<'), 'the retired flag is rendered in the status cell')
ok(epicHtml.includes(EPIC.summary.slice(0, 40)), 'the summary is rendered in the updated cell')
ok((epicHtml.match(/class="kb-na"/g) || []).length === 1, 'exactly one explicit n/a cell on an epic row (tags)')
const fiveHtml = renderRow(FIVE)
ok(!fiveHtml.includes('kb-na'), 'a complete five-field row shows no n/a cell at all')
ok(fiveHtml.includes('2026-09-28') && fiveHtml.includes('>active<'), 'a five-field row keeps its own values')

section('E. wiring: the list uses this projection, and the shipped bundle is rebuilt')
const clientSrc = readFileSync(join(KNOWLEDGE, 'src', 'client', 'index.tsx'), 'utf8')
ok(/import \{ docRow \} from '\.\.\/shared\/doc-row'/.test(clientSrc),
  'the docs list imports the one row projection')
ok(/const row: DocRow = docRow\(d\)/.test(clientSrc), 'the row map runs every entry through docRow')
ok(!/d\.tags\.map\(/.test(clientSrc), 'the row map no longer maps tags straight off the entry (crashed on epics)')
const bundleJs = readFileSync(join(KNOWLEDGE, 'lib', 'client.js'), 'utf8')
const bundleCjs = readFileSync(join(KNOWLEDGE, 'lib', 'client.cjs'), 'utf8')
ok(bundleJs.includes('epics') && bundleJs.includes('n/a'), 'the shipped bundle carries the epic row projection')
ok(bundleJs === bundleCjs, 'lib/client.js and lib/client.cjs are byte identical (the build copied its artefact)')

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
