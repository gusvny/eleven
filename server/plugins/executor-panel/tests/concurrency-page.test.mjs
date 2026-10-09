/**
 * concurrency-page.test.mjs —— t261006-17 (CL-2) 页面形状 UT（纯 node，无浏览器）；
 * t261008-20 更新：区块更名 Concurrent limit，running list 容器与审计短语位退场。
 *  - Overview 的 Concurrent limit 区块形状：区块头（chip）、唯一旋钮行
 *    （Limit [−] N [+] · 计数 · [Save]）；
 *  - 宿主裁定锁面：**无队列列出、无解释文案、无 running 票列表**（左列已有 running 面）；
 *  - #project= 深链回退在案（切项目 = 换上限与数字）；
 *  - EMBEDDED 单实现锁：limitStep / concChipState 源码与 CONC_LIMITS 表嵌入页面，
 *    与 UT 所测函数同源（漂移在此红）。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { limitStep, concChipState, CONC_LIMITS } from '../src/host/concurrency.ts'

let n = 0
const H = PANEL_PAGE_HTML

// ---- 区块形状 ----
for (const id of ['concBlock', 'concChip', 'concBox', 'concMinus', 'concLimit',
  'concPlus', 'concCounts', 'concSave', 'concMsg']) {
  assert(H.includes('id="' + id + '"'), 'Overview block element present: ' + id)
  n++
}
// t261008-20 negative face: the removed containers/stamp cannot come back unnoticed.
assert(!H.includes('id="concList"'), 'no running-ticket list container (removed by t261008-20)')
assert(!H.includes('id="concAudit"'), 'no audit-stamp span (removed by t261008-20)')
assert(!H.includes("'set by '"), "no 'set by ' audit phrase producer anywhere")
{
  // Check the old title on the rendered block itself (page comments may narrate the rename).
  // t261009-37: the block now lives inside the right-column stack; slice to the next block.
  const b0 = H.indexOf('id="concBlock"')
  const b1 = H.indexOf('id="alertBanner"', b0)
  assert(b0 > 0 && b1 > b0, 'the block slice is locatable')
  const block = H.slice(Math.max(0, b0 - 200), b1 > b0 ? b1 : b0 + 400)
  assert(!block.includes('Running tickets'), 'old block title gone from the rendered block')
  assert(block.includes('Concurrent limit'), 'block header: Concurrent limit (t261008-20)')
}
assert(H.includes('>Limit<'), 'the one knob row is labeled Limit')
assert(H.includes("id=\"concSave\""), 'one Save control in the block')
assert(H.includes('concChipLabel') && H.includes("'room to start one'") && H.includes("'at the limit'") && H.includes("'over the limit'"),
  'the three chip states are named on the page (design §2.1)')
assert(H.includes('conc-amber'), 'the over-the-limit amber marking lands in a class name (attribute-readable)')
n += 6

// ---- host-ruling lock face: no queue listing, no explanation copy (checked on the
// block markup slice; the page's other tabs may legitimately use these words) ----
{
  const b0 = H.indexOf('id="concBlock"')
  const b1 = H.indexOf('id="alertBanner"', b0)
  assert(b0 >= 0 && b1 > b0, 'the block slice is locatable')
  const block = H.slice(b0, b1)
  assert(!/fifo|first in|queue (is|orders|reorders|semantics)|reorder/i.test(block),
    'no queue-semantics explanation copy in the block (host ruling)')
  assert(!block.includes('queue'), 'no queue list container in the block (queue listing belongs to CL-3)')
  n += 2
}
n += 2

// ---- 切项目深链（#project= 回退）----
assert(H.includes('#project='), 'the hash deep-link fallback is wired (switching project switches the face)')
assert(H.includes('loadConcurrency()'), 'project switch reloads the concurrency face')
n += 2

// ---- EMBEDDED 单实现锁：页面与 UT 跑同一份函数源码 ----
assert(H.includes(String(limitStep).slice(0, 60)), 'limitStep source embedded into the page (single implementation)')
assert(H.includes(String(concChipState).slice(0, 60)), 'concChipState source embedded into the page')
assert(H.includes('"min":' + CONC_LIMITS.min) && H.includes('"max":' + CONC_LIMITS.max)
  && H.includes('"' + CONC_LIMITS.unlimited + '"'), 'the CONC_LIMITS table is embedded as JSON next to the functions')
n += 3

// ---- 嵌入函数在页面作用域内自洽（CONC_LIMITS 在 EMBEDDED 之前声明） ----
{
  // var 声明提升到脚本顶；首次渲染（setProject）在全部赋值之后，函数体运行时表已在作用域。
  // 这里只锁「表与函数同页」；运行时自洽由 loadPageModule 的页面加载冒烟（plugin-load/browser 场景）覆盖。
  assert(H.includes('var CONC_LIMITS') && H.includes(String(limitStep).slice(0, 40)),
    'the CONC_LIMITS table ships in the same served document as the embedded functions')
  // 嵌入函数体引用的名字必须都在页面作用域（CONC_LIMITS）。
  assert(String(limitStep).includes('CONC_LIMITS'), 'limitStep reads the embedded table (no hidden literals)')
  n += 2
}

// 同一实现的真值抽样（此处只是再锚一次；全表在 concurrency-face.test.mjs）。
assert(limitStep(10, 1) === 'unlimited' && concChipState(1, false, 2) === 'over',
  'the imported implementation is the one under test')
n++

done(n)
