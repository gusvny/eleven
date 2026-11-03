/**
 * t261008-19-mock-reconcile.test.mjs —— Inspection / Metrics / Docs 页签内容对齐
 * 261004 mock 的页面契约 UT（静态 HTML + 嵌入纯函数，零 DOM、零网络）：
 *  - Metrics：mock 的 Charts 盒与三个命名条目按字节原样在场（语义文本锚，KI-051）；
 *    无 chart 引擎（无 canvas/echarts —— 降级是显式声明，不是沉默）。
 *  - Docs：docsEntries 容器在场；docEntryRow 产出 mock 的两条入口行文本
 *    （docs/ the library / notes/ the ledger / Open）；页数未知显示 '— pages'，
 *    绝不出现 mock 的示意数字 25/60。
 *  - countDocsTree：畸形输入（null/非对象/groups 缺席/非数组/files 非数组）不 throw、
 *    不造数。
 *  - negative assertions (this ticket is not a licence to redraw the panel): the
 *    tab strip order is unchanged, the four Inspection anchors are byte-intact,
 *    the KPI row is exactly the shipped six tiles, the two tiles retired by the
 *    t261025-13 ruling stay retired, and every fetch stays on a declared API
 *    prefix (or the panel's own vendored-chart asset route) — no invented
 *    endpoint. (t261103-29: this replaces the pre-t261025-13 wording, which named
 *    tiles and a prefix set that no longer exist.)
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { countDocsTree, docEntryRow } from '../src/host/page-logic.ts'
import { kpiTilesOf } from '../src/host/metrics-tab-model.ts'

const html = PANEL_PAGE_HTML
let n = 0

// ---- T1 Metrics: the mock's Charts box with byte-identical named entries ----
const paneMetrics = html.slice(html.indexOf('id="paneMetrics"'), html.indexOf('id="paneGrants"'))
// RESURRECTION NOTE (t261021-07): this hunk was re-pointed to the approved-mock
// Metrics tab (host 261021). main@434b285 still carries the pre-rebuild snapshot
// of this file, so every pre-verification main-sync re-materialises the retired
// pins — if this hunk reverts, re-apply the t261021-07 re-point; the landing of
// THIS ticket is what cures main.
// T1 Metrics: the approved seven-section face — six KPI tile titles (the titles
// ride the embedded model core, so they are asserted on the WHOLE page), the
// five section headings (markup case; CSS uppercases at render), and the
// retirement of the placeholder copy.
// t261025-13 (host ruling 261025): the REWORK RATE tile and the single
// tokens-per-closed-ticket tile are retired; three honest token tiles replace
// them (docs/design/metrics-token-face-delta.md rule 3, "The REWORK RATE tile is
// removed"). The six titles below are the shipped face — the same set the
// integration anchor list pins (integration/t261021-07/...mock_anchors.mjs:116).
// A tile that comes back must come back with its ruling, not by re-adding an
// expectation here; this list is the live face, not a historical one.
for (const title of ['THROUGHPUT', 'MEDIAN LEAD TIME', 'TOKENS',
  'FRESH TOKENS PER COVERED TICKET', 'CACHE SHARE', 'HUMAN WAIT']) {
  assert(html.includes(title), `Metrics model carries the KPI tile title (${title})`)
}
// The row itself is pinned exactly (order and count), so a seventh tile cannot
// slip in behind the six presence checks; the model is the same function the
// page embeds, so this reads the shipped face, not a copy of it.
const kpiRow = kpiTilesOf({ kpis: {} }).map((t) => t.title)
assert(JSON.stringify(kpiRow) === JSON.stringify(
  ['THROUGHPUT', 'MEDIAN LEAD TIME', 'TOKENS', 'FRESH TOKENS PER COVERED TICKET',
    'CACHE SHARE', 'HUMAN WAIT']),
'the KPI row is exactly the shipped six tiles, in order (actual: ' + kpiRow.join(' / ') + ')')
for (const heading of ['Where the time goes', 'Certification', 'Epics',
  'Throughput', 'Where the tokens go']) {
  assert(paneMetrics.includes(heading), `Metrics pane carries the section heading (${heading})`)
}
assert(!/no chart data drawn/i.test(paneMetrics),
  'the retired placeholder copy stays retired')

// ---- T2 Docs: the two mock entry rows ----
const paneDocs = html.slice(html.indexOf('id="paneDocs"'), html.indexOf('id="paneGrants"'))
assert(paneDocs.includes('id="docsEntries"'), 'Docs pane has the entries container')
assert(paneDocs.includes('id="docsTree"') && paneDocs.includes('id="docsReader"'),
  'the existing tree + reader stay (not removed by this ticket)')
const rowDocs = docEntryRow('docs', 'the library', 7)
const rowNotes = docEntryRow('notes', 'the ledger', null)
for (const [row, name] of [[rowDocs, 'docs'], [rowNotes, 'notes']]) {
  assert(row.includes(name + '/') && row.includes('Open'), `${name} entry row shows its scope and an Open action`)
}
assert(rowDocs.includes('the library') && rowNotes.includes('the ledger'), 'entry rows carry the mock labels')
assert(rowDocs.includes('7 pages'), 'a known count renders as N pages')
assert(rowNotes.includes('— pages') && !/\d+ pages/.test(rowNotes), 'an unknown count renders as — pages (never fabricated)')
assert(!paneDocs.includes('25 pages') && !paneDocs.includes('60 pages'),
  "the mock's illustrative counts (25/60) never appear in the page")

// ---- T3 countDocsTree: malformed inputs degrade to null, no throw ----
const fixed = { groups: [{ files: [{ rel: 'a.md' }, { rel: 'b.md' }] }, { files: [{ rel: 'c.md' }] }] }
assert(countDocsTree(fixed) === 3, 'counts every file across groups')
assert(countDocsTree({ groups: [{ files: [] }] }) === 0, 'an empty tree counts 0 (a real number, not null)')
assert(countDocsTree(null) === null, 'null input -> null')
assert(countDocsTree('x') === null, 'non-object input -> null')
assert(countDocsTree({}) === null, 'missing groups -> null')
assert(countDocsTree({ groups: 'nope' }) === null, 'non-array groups -> null')
assert(countDocsTree({ groups: [null, { files: 'nope' }, { files: [{ rel: 'a.md' }] }] }) === 1,
  'junk group entries are skipped, real files still counted')

// ---- T4 negative assertions: this ticket is not a licence to redraw the panel ----
// Tab strip follows the currently declared strip (source of truth = the t261005-10
// page-contract test's ORDER; t261008-20 retired the Ledger tab; t261009-37 retired
// the Alerts tab — host order 261009-(1), face moved into the Overview). This
// ticket's guard is only that THIS ticket changed nothing about the strip.
// t261009-44: the Certification tab joins the strip (after Inspection, before Metrics);
// this guard keeps its original job — the ORDER here is the current declared strip.
const ORDER = ['overview', 'epics', 'inspection', 'certification', 'metrics', 'docs', 'grants', 'settings']
const tabs = [...html.matchAll(/data-tab="([a-z_-]+)"/g)].map(m => m[1])
assert(JSON.stringify(tabs) === JSON.stringify(ORDER), 'the tab strip order is unchanged')
const paneInsp = html.slice(html.indexOf('id="paneInsp"'), html.indexOf('id="paneSet"'))
for (const anchor of ['id="inspRunBtn"', 'id="inspDlg"', 'id="inspPeriodBtns"', 'id="inspBody"', 'id="inspRecords"',
  'Run a full-codebase review', 'Reviews you started']) {
  assert(paneInsp.includes(anchor), `Inspection pane keeps its mock anchor (${anchor})`)
}
// The negative face of the KPI row: the two tiles retired by the t261025-13
// ruling must not come back without a new ruling. The pre-repair version of this
// hunk asserted 'REWORK RATE' as PRESENT, which is why the retirement shipped
// with a red pin behind it (docs/design/metrics-token-face-delta.md rule 3).
for (const retired of ['REWORK RATE', 'TOKENS PER CLOSED TICKET']) {
  assert(!html.includes(retired), `the retired KPI tile title stays retired (${retired})`)
}
const endpoints = [...html.matchAll(/fetch\('([^']+)'/g)].map(m => m[1].split('?')[0])
assert(new Set(endpoints).size === new Set(endpoints.map(e => e)).size,
  'no duplicate endpoint paths introduced')
// t261021-07: the panel's vendored echarts build is served from its own static
// route (panel-page.ts:2182 probes it with HEAD before the lazy module import,
// harness.mjs:43 serves it as a prefix route). It is an asset, not an API, so
// the allowed set is the three API prefixes plus that one asset route — any
// other target still reds, which is what this guard is for.
const ALLOWED = /\/sandbar-workbench\/api\/|\/sandbar-executor-panel\/api\/|\/sandbar-watchdog\/api\/|\/sandbar-executor-panel\/vendor\//
assert(!endpoints.some(e => !ALLOWED.test(e)),
  'every fetch stays on the existing API prefixes or the panel asset route (no invented endpoint)')

done(n + 1)
