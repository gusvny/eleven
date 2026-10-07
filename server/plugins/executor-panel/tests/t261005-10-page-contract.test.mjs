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

const here = dirname(fileURLToPath(import.meta.url))
const html = PANEL_PAGE_HTML
let n = 0

// ---- T1 tab strip: fixed order, no board, no duplicates ----
const ORDER = ['overview', 'epics', 'ledger', 'alerts', 'inspection', 'metrics', 'docs', 'grants', 'settings']
const tabs = [...html.matchAll(/data-tab="([a-z_-]+)"/g)].map(m => m[1])
assert(JSON.stringify(tabs) === JSON.stringify(ORDER), `tab strip is the 9 fixed-order tabs (got [${tabs.join(',')}])`)
assert(!tabs.includes('board'), 'no status-board tab in the strip')
assert(new Set(tabs).size === tabs.length, 'no duplicate tabs')

// radio inputs back every label (click targets exist for each tab)
for (const t of ORDER) assert(html.includes(`id="t-${t}"`), `radio input for ${t}`)
for (const t of ORDER) assert(html.includes(`id="pane`), 'panes present')

// ---- panes for the four moved-in faces ----
for (const id of ['paneEpics', 'paneInspection', 'paneMetrics', 'paneDocs']) {
  assert(html.includes(`id="${id}"`), `${id} pane present`)
}
// lazy loaders wired in the page script
for (const fn of ['loadEpics', 'loadInspection', 'loadMetrics', 'loadDocs', 'loadConcurrency']) {
  assert(html.includes(`function ${fn}`), `page defines ${fn}`)
}

// ---- ONE limit row (single knob; CL-2 boundary stated, no second knob markup) ----
assert(html.includes('id="limitRow"'), 'Overview carries the limit row element')
assert((html.match(/id="limitRow"/g) ?? []).length === 1, 'exactly ONE limit row element')
assert(!/id="limit(Up|Down|Minus|Plus|Input)"/.test(html), 'no second limit knob on the page')
assert(html.includes('CL-2'), 'the absent write face is named (CL-2)')

// ---- list contracts declared for the new faces ----
for (const id of ['epics_list', 'epic_tickets', 'docs_tree', 'metrics_kpis', 'inspection_items']) {
  assert(LIST_CONTRACTS[id] && typeof LIST_CONTRACTS[id].empty_copy === 'string' && LIST_CONTRACTS[id].empty_copy.length > 0,
    `list contract ${id} declared with empty copy`)
}
// the page renders empty states through the contract (no inline copies for the new lists)
assert(html.includes("emptyCopyOf('epics_list')") && html.includes("emptyCopyOf('epic_tickets')")
  && html.includes("emptyCopyOf('docs_tree')") && html.includes("emptyCopyOf('metrics_kpis')")
  && html.includes("emptyCopyOf('inspection_items')"), 'page references the declared empty copies by name')

// ---- postMessage contract pairing with the host (executor-view.tsx) ----
const hostSrc = readFileSync(join(here, '../../workbench/src/client/executor-view.tsx'), 'utf8')
for (const type of ['sandbar-executor-panel:open-ticket', 'sandbar-executor-panel:show-tab', 'sandbar-executor-panel:show-epic']) {
  assert(html.includes(`'${type}'`), `panel page speaks '${type}'`)
  assert(hostSrc.includes(`'${type}'`), `host executor-view speaks '${type}'`)
}
// show-tab/show-epic honored only from the parent window
assert(/window\.parent === window\) return;/.test(html), 'panel ignores parent-bound message types when standalone')

done(`T261005_10_PAGE_CONTRACT ran=${++n}`)
