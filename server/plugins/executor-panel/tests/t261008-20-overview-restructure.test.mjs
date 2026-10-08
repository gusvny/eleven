/**
 * t261008-20-overview-restructure.test.mjs —— host order 261008（Overview 重排）静态面 UT：
 *  - Ledger 页签退场（tab strip 无 ledger、无隐藏 paneLedger）；
 *  - Overview 右列新入口 'Recent actions (view source event)' 打开 source-event 对话框，
 *    对话框携带原 Ledger 全部三件（health grid / ledger file / wakes）；
 *  - 唤醒面不再截前三行：契约 cap='all'，渲染路径无截断，对话框文案点名 watchdog
 *    20 行窗口（不静默截前缀）；
 *  - Running tickets → Concurrent limit，running 票列表容器与 'set by ' 审计短语退场
 *    （负形回归：旧标记不得无声回归）；
 *  - 畸形/缺失输入面：空 wakes / 缺 st.wakes → 空态文案（不造行），st 缺失分支显式清空。
 * 零 DOM、零网络、零 3099 触碰；浏览器级行为断言在 browser-redesign.test.mjs。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { LIST_CONTRACTS } from '../src/host/list-contracts.ts'

let n = 0
const H = PANEL_PAGE_HTML

// ---- 1. Ledger tab gone from the strip, no hidden face ----
const tabs = [...H.matchAll(/data-tab="([a-z_-]+)"/g)].map(m => m[1])
assert(!tabs.includes('ledger'), 'tab strip carries no Ledger entry')
assert(!H.includes('id="paneLedger"'), 'no hidden paneLedger left (no hidden Ledger tab)')
assert(!/['"]t-ledger['"]/.test(H), 'no stale t-ledger wiring left')

// ---- 2. The entry + dialog beside Recent actions (host wording) ----
{
  const col = H.slice(H.indexOf('Recent actions</div>'), H.indexOf('</section>', H.indexOf('Recent actions</div>')))
  assert(col.includes('Recent actions (view source event)'), 'the entry reads exactly "Recent actions (view source event)"')
  assert(col.includes('id="ledgerDlgBtn"') && /button[^>]*id="ledgerDlgBtn"/.test(col), 'the entry is a real button (keyboard reachable)')
}
assert(H.includes('id="ledgerDlg"') && H.includes('data-open="false"'), 'the dialog face exists with a data-open state')
for (const id of ['ledgerGrid', 'ledgerFile', 'ledgerEvents']) {
  assert(H.includes('id="' + id + '"'), 'dialog carries the former Ledger face element: ' + id)
}
assert(H.includes('id="ledgerDlgClose"'), 'the dialog has a close control')
assert(H.includes("'Escape'"), 'Esc closes the dialog')
assert(H.includes('ledgerDlgClose\').focus()') || H.includes("el('ledgerDlgClose').focus()"), 'focus moves into the dialog on open')

// ---- 3. More than three wakes: cap 'all', no truncation, ceiling named ----
assert(LIST_CONTRACTS.ledger_last_wakes.cap === 'all', 'wakes contract cap is "all" (not 3)')
assert(!H.includes("capOf('ledger_last_wakes')"), 'no render-path cap reference for the wakes list')
assert(!/Math\.min\(wakes\.length\s*,/.test(H), 'no Math.min truncation over the wakes list')
assert(H.includes('The watchdog status keeps the last 20 wakes.'), 'the dialog copy names the 20-row window (no silent prefix)')
assert(H.includes("el('ledgerWakeCount').textContent = '· ' + wakes.length"), 'the dialog states the wakes count')
assert(H.includes("emptyCopyOf('ledger_last_wakes')"), 'the empty list shows the declared empty copy (no fabricated rows)')

// ---- 4. Concurrent limit rename, list + audit stamp removed ----
{
  const b0 = H.indexOf('id="concBlock"')
  const b1 = H.indexOf('class="cols"', b0)
  const block = H.slice(b0, b1)
  assert(block.includes('Concurrent limit'), 'the block title reads "Concurrent limit"')
  assert(!block.includes('Running tickets'), 'the old title is gone from the rendered block')
  assert(!block.includes('id="concList"'), 'no running-ticket list container in the block')
  assert(!/id="dot|class="dot/.test(block), 'no holder-row dot markup in the block')
  assert(!block.includes('concAudit'), 'no audit-stamp span in the block')
  assert(!block.includes('set by '), "no 'set by ' text in the block")
  assert(!H.includes("'set by '"), "no 'set by ' producer anywhere in the page script")
  assert(block.includes('id="concCounts"'), 'the counts line element stays')
  assert(block.includes('id="concMinus"') && block.includes('id="concPlus"') && block.includes('id="concLimit"') && block.includes('id="concSave"'),
    'the limit knob, value and Save stay')
  assert(H.includes("c.at_work + ' at work · ' + c.waiting + ' waiting'"), 'holders/queue stated in words in the counts line')
}

// ---- 5. Malformed / missing input face (static anchors; behavior in browser tests) ----
assert(/st\.wakes\|\|\[\]/.test(H), 'missing st.wakes degrades to an empty list (no throw, no fabricated rows)')
{
  const fn = H.slice(H.indexOf('function renderAlertsLedger()'), H.indexOf('function renderLimitRow()'))
  assert(fn.includes("el('ledgerWakeCount').textContent=''"), 'the no-status branch clears the wakes count line')
  // t261003-13 rework (re-exposed by the uncap): a non-object wake row (null among
  // the rows) must render the honest face — dash time, unknown sentence — never
  // abort the loop (the unchecked dereference blanked the whole ledger face).
  assert(/var bad = !w2 \|\| typeof w2 !== 'object' \|\| Array\.isArray\(w2\)/.test(fn),
    'the wakes loop guards non-object rows (a null row cannot abort the face)')
  assert(fn.includes("var when = bad ? '—' : localDateTime(w2.at)"),
    'a malformed row renders the dash time (no unchecked field dereference)')
  assert(fn.includes('wakeRowSentence(w2)'), 'the row sentence still goes through the null-safe shared helper')
}

n += 30
done(n)
