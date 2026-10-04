/**
 * list-contracts.test.mjs —— t261004-14：面板列表契约 UT。
 *  - 每个列表四件事齐全：source / order / cap（数字或 'all'）/ empty_copy；
 *  - 数字 cap 必须带 cap_reason（为什么藏行可接受）；
 *  - declaredCap：声明过的数字 cap 取值正确；'all' / 未知 id 显式报错（不静默 0）；
 *  - 畸形契约（缺字段 / cap 类型错 / 空 empty_copy）必须被守门函数认出——契约表本身
 *    也是消费对象，坏一行就要红，不许渲染期才炸。
 *  - 嵌入面：面板页携带 LIST_CONTRACTS 数据与 capOf/emptyCopyOf（单一声明源落到页面）。
 * 零 DOM、零网络、零 3099 触碰。
 */
import { assert, done } from './lib.mjs'
import { LIST_CONTRACTS, declaredCap } from '../src/host/list-contracts.ts'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'

let n = 0
const ids = Object.keys(LIST_CONTRACTS)
assert(ids.length >= 8, 'all panel lists are declared (got ' + ids.length + ')')

// 票面点名的列表必须都在
for (const must of ['overview_waits', 'overview_answered', 'overview_recent_actions',
  'grants_readout_sessions', 'alerts', 'ledger_last_wakes']) {
  assert(ids.includes(must), 'contract declared: ' + must)
}

// ---- 每条契约四件事齐全 + 数字 cap 带理由 ----
for (const id of ids) {
  const c = LIST_CONTRACTS[id]
  assert(c.id === id, id + ': id field matches its key')
  assert(typeof c.source === 'string' && c.source.trim() !== '', id + ': source declared')
  assert(typeof c.order === 'string' && c.order.trim() !== '', id + ': order declared')
  assert(c.cap === 'all' || (typeof c.cap === 'number' && Number.isInteger(c.cap) && c.cap > 0),
    id + ': cap is "all" or a positive integer (got ' + JSON.stringify(c.cap) + ')')
  assert(typeof c.empty_copy === 'string' && c.empty_copy.trim() !== '', id + ': empty copy declared')
  if (typeof c.cap === 'number') {
    assert(typeof c.cap_reason === 'string' && c.cap_reason.trim().length >= 20,
      id + ': numeric cap carries a stated reason')
  }
  // 可 JSON 化（嵌入页面用）
  assert(JSON.parse(JSON.stringify(c)).cap === c.cap, id + ': contract survives JSON round-trip')
}

// ---- 事故回归：ledger_last_wakes 的 3 行上限与最新在前必须写在契约里 ----
assert(declaredCap('ledger_last_wakes') === 3, 'last wakes cap declared as 3 (the incident cap)')
assert(/append-order|Newest first/i.test(LIST_CONTRACTS.ledger_last_wakes.order),
  'last wakes order states newest first over an append-ordered source')
assert(declaredCap('overview_recent_actions') === 50, 'recent actions cap declared as 50 (t261004-11 window, declared per t261004-14)')

// ---- declaredCap 守门：'all' 与未知 id 显式炸，不返回 0/undefined ----
for (const bad of ['alerts', 'no_such_list', '', 'overview_waits']) {
  let threw = false
  try { declaredCap(bad) } catch { threw = true }
  assert(threw, 'declaredCap throws for ' + JSON.stringify(bad) + ' (not a numeric cap)')
}

// ---- 契约守门函数：畸形契约必须认得出（消费侧纪律的形状测试） ----
function contractComplete(c) {
  return typeof c?.id === 'string' && typeof c?.source === 'string' && c.source.trim() !== ''
    && typeof c?.order === 'string' && c.order.trim() !== ''
    && (c?.cap === 'all' || (typeof c?.cap === 'number' && Number.isInteger(c.cap) && c.cap > 0))
    && typeof c?.empty_copy === 'string' && c.empty_copy.trim() !== ''
    && (typeof c.cap === 'number' ? typeof c.cap_reason === 'string' && c.cap_reason.trim() !== '' : true)
}
for (const [name, bad] of Object.entries({
  'missing source': { id: 'x', order: 'o', cap: 'all', empty_copy: 'e' },
  'cap 0': { id: 'x', source: 's', order: 'o', cap: 0, empty_copy: 'e', cap_reason: 'r' },
  'numeric cap without reason': { id: 'x', source: 's', order: 'o', cap: 5, empty_copy: 'e' },
  'empty empty_copy': { id: 'x', source: 's', order: 'o', cap: 'all', empty_copy: '  ' },
  'cap of wrong type': { id: 'x', source: 's', order: 'o', cap: '3', empty_copy: 'e' },
  'garbage row (string)': 'nope',
  'garbage row (null)': null,
})) {
  assert(!contractComplete(bad), 'malformed contract rejected: ' + name)
}
assert(contractComplete(LIST_CONTRACTS.ledger_last_wakes), 'the real incident contract passes the same shape gate')

// ---- 嵌入面：页面带契约数据与守门函数，上限不再内联在渲染路径 ----
assert(PANEL_PAGE_HTML.includes('var LIST_CONTRACTS ='), 'page embeds the contract table')
assert(PANEL_PAGE_HTML.includes('function capOf(') && PANEL_PAGE_HTML.includes('function emptyCopyOf('),
  'page embeds cap/empty-copy accessors')
assert(PANEL_PAGE_HTML.includes(JSON.stringify(LIST_CONTRACTS.ledger_last_wakes).slice(0, 40)),
  'embedded table is the same declaration the tests read')
assert(!/Math\.min\([^;\n]*?\d/.test(PANEL_PAGE_HTML.split('var LIST_CONTRACTS')[1] || ''), // 渲染段不再有截断常量
  'no cap-like integer constant in the page render path after the contract table')

n += ids.length + 30
done(n)
