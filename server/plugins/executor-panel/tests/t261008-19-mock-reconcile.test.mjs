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
 *  - 负断言（本票不是重画许可）：页签条顺序不变、paneInsp 四锚原样在场、既有
 *    KPI 卡标签（tickets (7d) 等）原样在场、端点集合不新增。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { countDocsTree, docEntryRow } from '../src/host/page-logic.ts'

const html = PANEL_PAGE_HTML
let n = 0

// ---- T1 Metrics: the mock's Charts box with byte-identical named entries ----
const paneMetrics = html.slice(html.indexOf('id="paneMetrics"'), html.indexOf('id="paneGrants"'))
assert(paneMetrics.includes('>Charts<'), 'Metrics pane has a Charts heading')
for (const label of ['lanes per day', 'stage duration', 'gate reds']) {
  assert(paneMetrics.includes(label), `Metrics Charts box names '${label}' as semantic text`)
}
assert(paneMetrics.includes('(chart from the project metrics API)'),
  "Metrics Charts box carries the mock's lanes-per-day value copy verbatim")
assert(!/<canvas|<svg|echarts/i.test(paneMetrics),
  'no chart engine in the Metrics pane (degradation is declared copy, not silence)')

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
// page-contract test's ORDER; t261008-20 retired the Ledger tab). This ticket's guard
// is only that THIS ticket changed nothing about the strip.
const ORDER = ['overview', 'epics', 'alerts', 'inspection', 'metrics', 'docs', 'grants', 'settings']
const tabs = [...html.matchAll(/data-tab="([a-z_-]+)"/g)].map(m => m[1])
assert(JSON.stringify(tabs) === JSON.stringify(ORDER), 'the tab strip order is unchanged')
const paneInsp = html.slice(html.indexOf('id="paneInsp"'), html.indexOf('id="paneSet"'))
for (const anchor of ['id="inspRunBtn"', 'id="inspDlg"', 'id="inspPeriodBtns"', 'id="inspBody"', 'id="inspRecords"',
  'Run a full-codebase review', 'Reviews you started']) {
  assert(paneInsp.includes(anchor), `Inspection pane keeps its mock anchor (${anchor})`)
}
for (const kpi of ['tickets (7d)', 'closed (7d)', 'avg delivery (min)', 'tokens total']) {
  assert(html.includes(kpi), `the existing Metrics KPI card label stays (${kpi})`)
}
const endpoints = [...html.matchAll(/fetch\('([^']+)'/g)].map(m => m[1].split('?')[0])
assert(new Set(endpoints).size === new Set(endpoints.map(e => e)).size,
  'no duplicate endpoint paths introduced')
assert(!endpoints.some(e => !/\/sandbar-workbench\/api\/|\/sandbar-executor-panel\/api\/|\/sandbar-watchdog\/api\//.test(e)),
  'every fetch stays on the existing API prefixes (no invented endpoint)')

done(n + 1)
