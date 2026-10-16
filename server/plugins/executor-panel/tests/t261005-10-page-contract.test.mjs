/**
 * t261005-10-page-contract.test.mjs —— UI-2 页面契约 UT（对 PANEL_PAGE_HTML 静态面）：
 * 九页签 data-tab 定序（mock v11 顺序，无 board、无重复）、四个新 tab 的 pane/装载
 * 元素在场、Overview 恰一条 limit 行（单旋钮：不出现第二个 limit 控件）、列表契约
 * 新增五条、页内寻路/开票 postMessage 类型成对（面板侧字面量 ↔ executor-view 常量）。
 */
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { LIST_CONTRACTS } from '../src/host/list-contracts.ts'
import { countDocsTree } from '../src/host/page-logic.ts'

const here = dirname(fileURLToPath(import.meta.url))
const html = PANEL_PAGE_HTML
let n = 0

// ---- T1 tab strip: fixed order, no board, no duplicates ----
// t261008-20 (host order): the Ledger tab left the strip; t261009-37 (host order
// 261009-(1)): the Alerts tab left too — both faces live in the Overview blocks.
// t261009-44: the Certification tab joins the strip (after Inspection).
const ORDER = ['overview', 'epics', 'inspection', 'certification', 'metrics', 'docs', 'grants', 'settings']
const tabs = [...html.matchAll(/data-tab="([a-z_-]+)"/g)].map(m => m[1])
assert(JSON.stringify(tabs) === JSON.stringify(ORDER), `tab strip is the 8 fixed-order tabs (got [${tabs.join(',')}])`)
assert(!tabs.includes('board'), 'no status-board tab in the strip')
assert(!tabs.includes('ledger'), 'no Ledger tab in the strip (t261008-20)')
assert(!tabs.includes('alerts'), 'no Alerts tab in the strip (t261009-37)')
assert(new Set(tabs).size === tabs.length, 'no duplicate tabs')

// t261009-37: the source-event dialog is retired; the former Ledger face is the
// inline Events block on the Overview (visible without any entry click).
assert(!html.includes('id="ledgerDlgBtn"') && !html.includes('Recent actions (view source event)'),
  'the lone source-event entry is gone (t261009-37)')
assert(!html.includes('id="ledgerDlg"') && !html.includes('id="ledgerDlgClose"'),
  'the dialog overlay and its close control are gone (t261009-37)')
assert(html.includes('id="ledgerHealth"') && html.includes('id="ledgerFile"') && html.includes('id="ledgerEvents"') && html.includes('id="wakeCount"'),
  'the Events block carries the whole former Ledger face (health line, file, wakes, count)')
assert(!html.includes('id="paneLedger"') && !html.includes('data-tab="ledger"') && !html.includes('id="paneAlert"'),
  'no hidden Ledger/Alerts pane or tab anchor left (negative regression)')

// radio inputs back every label (click targets exist for each tab)
for (const t of ORDER) assert(html.includes(`id="t-${t}"`), `radio input for ${t}`)
for (const t of ORDER) assert(html.includes(`id="pane`), 'panes present')

// ---- panes for the moved-in faces ----
// t261006-15 reconcile: the Inspection slot's pane is the inspection epic's CONTENT
// face (paneInsp), not the t261005-10 placeholder (paneInspection retired with its
// scan-report dwell table — the placeholder's own comment assigned the report
// content to the inspection epic).
for (const id of ['paneEpics', 'paneInsp', 'paneMetrics', 'paneDocs']) {
  assert(html.includes(`id="${id}"`), `${id} pane present`)
}
assert(!html.includes('paneInspection') && !html.includes('loadInspection'),
  'the placeholder inspection face is fully retired (one slot, one content face)')
// lazy loaders wired in the page script (inspection loads via its own lazy gate)
for (const fn of ['loadEpics', 'loadMetrics', 'loadDocs', 'loadConcurrency', 'inspEnsureLoaded']) {
  assert(html.includes(`function ${fn}`), `page defines ${fn}`)
}

// ---- ONE limit row (single knob; CL-2 boundary stated, no second knob markup) ----
assert(html.includes('id="limitRow"'), 'Overview carries the limit row element')
assert((html.match(/id="limitRow"/g) ?? []).length === 1, 'exactly ONE limit row element')
assert(!/id="limit(Up|Down|Minus|Plus|Input)"/.test(html), 'no second limit knob on the page')
assert(html.includes('CL-2'), 'the absent write face is named (CL-2)')

// ---- list contracts declared for the new faces ----
// t261006-15 reconcile: inspection_items (the placeholder's dwell list) is retired
// with the placeholder face; the Inspection tab's lists are inspection_periods /
// inspection_trigger_records (declared by t261006-15).
for (const id of ['epics_list', 'epic_tickets', 'docs_tree', 'metrics_kpis', 'inspection_periods', 'inspection_trigger_records']) {
  assert(LIST_CONTRACTS[id] && typeof LIST_CONTRACTS[id].empty_copy === 'string' && LIST_CONTRACTS[id].empty_copy.length > 0,
    `list contract ${id} declared with empty copy`)
}
// the page renders empty states through the contract (no inline copies for the new lists)
assert(html.includes("emptyCopyOf('epics_list')") && html.includes("emptyCopyOf('epic_tickets')")
  && html.includes("emptyCopyOf('docs_tree')") && html.includes("emptyCopyOf('metrics_kpis')"),
  'page references the declared empty copies by name')

// ---- postMessage contract pairing with the host (executor-view.tsx) ----
const hostSrc = readFileSync(join(here, '../../workbench/src/client/executor-view.tsx'), 'utf8')
for (const type of ['sandbar-executor-panel:open-ticket', 'sandbar-executor-panel:show-tab', 'sandbar-executor-panel:show-epic']) {
  assert(html.includes(`'${type}'`), `panel page speaks '${type}'`)
  assert(hostSrc.includes(`'${type}'`), `host executor-view speaks '${type}'`)
}
// show-tab/show-epic honored only from the parent window
assert(/window\.parent === window\) return;/.test(html), 'panel ignores parent-bound message types when standalone')

done(`T261005_10_PAGE_CONTRACT ran=${++n}`)

// ---- 261016: the Docs tab must read the workbench ENVELOPE correctly ----
// Host report: the tab said "The library is empty for this scope." while the
// endpoint returned a full tree. The loader stored {ok,result,resolved} and then
// read d.groups / d.empty off the top level, so the tree always rendered empty.
// Read path = the loader unwraps j.result; count path = countDocsTree takes the
// UNWRAPPED tree and answers null (never a fabricated 0) for anything else.
{
  const envelope = { ok: true, result: { empty: false, scope: 'docs', groups: [
    { dir: '', label: '总目录', files: [{ rel: 'README.md', title: 'docs index' }] },
    { dir: 'design', label: 'design', files: [{ rel: 'design/a.md', title: 'a' }, { rel: 'design/b.md', title: 'b' }] },
  ] }, resolved: { source: 'project', key: 'sandbar', root: '/x' } }
  assert(countDocsTree(envelope.result) === 3, 'countDocsTree counts the UNWRAPPED tree (3 files)')
  assert(countDocsTree(envelope) === null, 'countDocsTree refuses the envelope (null, never a fabricated count)')
  assert(countDocsTree({ empty: true, reason: 'x', scope: 'docs', groups: [] }) === 0, 'an empty-but-present tree counts 0')
  assert(/state\.docs=\(j && j\.ok===true && j\.result/.test(html), 'the Docs loader unwraps j.result (envelope shape pinned)')
}
