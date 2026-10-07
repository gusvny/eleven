/**
 * smoke/chat-project-band.mjs — smoke for the right-rail chat project color band decorator (ticket 2 R7, t260904-05).
 *
 * Run: node smoke/chat-project-band.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Under test: src/client/chat-project-band.ts (applyProjectBand pure DOM side + start/stop
 * lifecycle). The DOM is a homemade stub (no jsdom) and does not depend on real platform
 * packages — the same stub discipline as smoke/chat-project-tag.mjs.
 *
 * Covers (matching the failure-mode tradeoff list in the module header):
 *   A. applyProjectBand: sets attribute/CSS variable, idempotent (same value skipped),
 *      null/malformed key removes the band, multiple anchors all set, zero anchors harmless,
 *      non-element nodes skipped.
 *   B. hexToRgba: normal expansion + malformed hex does not throw (NaN propagation is the
 *      caller's contract, no crash).
 *   C. start/stop lifecycle (document stub): style injected and removed, set -> attribute
 *      written, stop clears attributes, stop idempotent, set after stop harmless.
 *   D. MutationObserver rebuild guard: after the scroll-body node is rebuilt, the callback
 *      re-applies attributes (a real MutationObserver cannot be stubbed — verified via the
 *      scan re-entry surface: rebuild = new node without attributes, then scan fills them;
 *      observer connectivity is guarded by code review + integration, the stub only checks
 *      the re-apply logic).
 */

import {
  PROJBAND_ATTR,
  PROJBAND_BASE_CSS,
  PROJBAND_BAND_CSS,
  PROJBAND_HANDLE_ATTR,
  applyProjectBand,
  hexToRgba,
  startChatProjectBand,
  startChatProjectBandEffect,
} from '../src/client/chat-project-band.ts'
import { projectColor } from '../src/shared/project-color.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** Homemade DOM stub: minimal Element/Document surface (setattr/getattr/attribute bookkeeping + style.setProperty). */
function el(tag = 'div', attrs = {}) {
  const node = {
    tagName: tag,
    isConnected: true,
    attributes: { ...attrs },
    style: {
      _props: {},
      setProperty(k, v) { this._props[k] = v },
      removeProperty(k) { delete this._props[k] },
    },
    setAttribute(k, v) { node.attributes[k] = String(v) },
    getAttribute(k) { return k in node.attributes ? node.attributes[k] : null },
    removeAttribute(k) { delete node.attributes[k] },
    remove() { node.removed = true },
  }
  return node
}
function docOf(...children) {
  const body = { children }
  const doc = {
    documentElement: el('html'),
    head: { appendChild() {}, removeChild() {} },
    body,
    querySelector(sel) { return sel === 'style[data-wb-chat-projband-style]' ? doc._style ?? null : null },
    createElement() { return el('style') },
    querySelectorAll(sel) {
      if (sel === `[${PROJBAND_ATTR}]`) return body.children.filter(c => PROJBAND_ATTR in c.attributes)
      if (sel === '[data-conversation-scroll]') return body.children
      return []
    },
  }
  return doc
}

section('A applyProjectBand：设/摘/幂等/畸形/多锚')
{
  const a = el('div', { 'data-conversation-scroll': '' })
  const root = docOf(a)
  ok(applyProjectBand(root, 'suyou') === 1, '设属性：1 节点写动')
  ok(a.getAttribute(PROJBAND_ATTR) === 'suyou', '属性值=project key')
  ok(a.style._props['--wb-projband-color'] === projectColor('suyou'), 'CSS 变量=projectColor（suyou 恒同色；t261005-05 起 12 色声明板，锚函数不锚具体值）')
  ok(applyProjectBand(root, 'suyou') === 0, '幂等：同值跳过零写动')
  ok(applyProjectBand(root, null) === 1 && a.getAttribute(PROJBAND_ATTR) === null, 'null=摘除（不在册不渲染）')
  ok(applyProjectBand(root, null) === 0, '幂等：无属性时摘除零写动')
  // Malformed key (the ledger is external input via localStorage): treated as null -> band removed, no attribute set
  const b = el('div', { 'data-conversation-scroll': '' })
  const root2 = docOf(b)
  for (const bad of ['', 42, null, undefined, { x: 1 }, 'k'.repeat(65), 'bad\nkey']) {
    applyProjectBand(root2, bad)
    ok(b.getAttribute(PROJBAND_ATTR) === null, `畸形 key 不设属性（${JSON.stringify(String(bad)).slice(0, 12)}）`)
  }
  // Multiple anchors all set + zero anchors harmless
  const c1 = el('div', { 'data-conversation-scroll': '' })
  const c2 = el('div', { 'data-conversation-scroll': '' })
  const root3 = docOf(c1, c2)
  ok(applyProjectBand(root3, 'sandbar') === 2 && c1.getAttribute(PROJBAND_ATTR) === 'sandbar' && c2.getAttribute(PROJBAND_ATTR) === 'sandbar', 'N 个锚全部齐设')
  ok(applyProjectBand(docOf(), 'suyou') === 0, '0 锚（blank hero 瞬态）无害返回 0')
  // Non-element dirty nodes skipped (malformed-input discipline: reproduced with a stub, no real external source)
  const dirty = { getAttribute: 'not-a-fn' }
  const root4 = docOf(dirty, el('div', { 'data-conversation-scroll': '' }))
  ok(applyProjectBand(root4, 'suyou') === 1, '脏节点（方法缺失）跳过不崩，健康节点照常')
  // UI-5: handle channel — set / update / idempotent / removed with the key / quote-safe
  const d1 = el('div', { 'data-conversation-scroll': '' })
  const root5 = docOf(d1)
  applyProjectBand(root5, 'sandbar', '09ca')
  ok(d1.getAttribute(PROJBAND_HANDLE_ATTR) === '09ca', '句柄属性=短码')
  ok(applyProjectBand(root5, 'sandbar', '09ca') === 0, '句柄幂等：同值零写动')
  applyProjectBand(root5, 'sandbar', 'e')
  ok(d1.getAttribute(PROJBAND_HANDLE_ATTR) === 'e', '句柄更新（如 executor 固定名）')
  applyProjectBand(root5, 'sandbar', 'bad"quote')
  ok(d1.getAttribute(PROJBAND_HANDLE_ATTR) === null, '句柄含引号=拒设（attr() 注入面免疫）')
  applyProjectBand(root5, null, '09ca')
  ok(d1.getAttribute(PROJBAND_ATTR) === null && d1.getAttribute(PROJBAND_HANDLE_ATTR) === null, 'null key=属性与句柄同摘')
}

section('B hexToRgba')
{
  ok(hexToRgba('#e76a6a', 0.16) === 'rgba(231,106,106,0.16)', 'hex→rgba 16% 展开')
  ok(hexToRgba('#000000', 1) === 'rgba(0,0,0,1)', '黑全不透明')
  let threw = false
  try { hexToRgba('zz', 0.5) } catch { threw = true }
  ok(!threw, '畸形 hex 不抛（NaN 传播，调用方只吃 projectColor 产物）')
}

section('C start/stop 生命周期（document 桩）')
{
  const sc = el('div', { 'data-conversation-scroll': '' })
  const doc = docOf(sc)
  let styleNode = null
  // head.appendChild captures the injected style; observe/disconnect stubbed (a real Observer needs a DOM)
  doc.head.appendChild = (n) => { styleNode = n }
  doc.body.observe = () => {}
  const saved = globalThis.MutationObserver
  globalThis.MutationObserver = class { constructor() {} observe() {} disconnect() {} }
  try {
    const h = startChatProjectBand({ doc })
    ok(styleNode !== null && styleNode.getAttribute('data-wb-chat-projband-style') === '', 'head 注入自有 style')
    ok(styleNode.textContent === (PROJBAND_BASE_CSS + '\n' + PROJBAND_BAND_CSS) && styleNode.textContent.includes('border-top: 3px solid'), 'style 内容=基础规则+身份带规则（border-top 3px 项目色 + sticky 角标 + overlay 带面）')
    h.set('suyou')
    ok(sc.getAttribute(PROJBAND_ATTR) === 'suyou', 'set(key)→属性落锚')
    h.set('chat-20260831-120000-abcd')
    ok(sc.getAttribute(PROJBAND_ATTR) === 'chat-20260831-120000-abcd', '换绑 key 属性更新')
    h.set(null)
    ok(sc.getAttribute(PROJBAND_ATTR) === null, 'set(null)=摘除')
    h.set('suyou')
    h.stop()
    ok(sc.getAttribute(PROJBAND_ATTR) === null, 'stop：已设属性摘除')
    ok(styleNode.textContent === undefined || styleNode.textContent === null || styleNode.removed === true, 'stop：style 摘除面被调')
    h.stop()
    h.set('sandbar')
    ok(sc.getAttribute(PROJBAND_ATTR) === null, 'stop 幂等 + stop 后 set 无害')
    // Effect shape: returns the cleanup function itself (F1 guard)
    const doc2 = docOf(el('div', { 'data-conversation-scroll': '' }))
    doc2.head.appendChild = () => {}
    doc2.body.observe = () => {}
    const cleanup = startChatProjectBandEffect({ doc: doc2 })
    ok(typeof cleanup === 'function', 'startChatProjectBandEffect 返回清理函数本身（F1）')
    cleanup()
  } finally {
    globalThis.MutationObserver = saved
  }
}

section('D 防重建重设逻辑（scan 重入面）')
{
  // Rebuild = new node without attributes; scan (same path as set) fills them — observer
  // connectivity is declared in the module header + guarded by integration; the stub only
  // checks the re-apply logic is idempotent and converges.
  const n1 = el('div', { 'data-conversation-scroll': '' })
  const root = docOf(n1)
  applyProjectBand(root, 'suyou')
  const n2 = el('div', { 'data-conversation-scroll': '' })
  root.body.children = [n2]
  ok(applyProjectBand(root, 'suyou') === 1 && n2.getAttribute(PROJBAND_ATTR) === 'suyou', '重建节点经 scan 重设属性')
  ok(n1.getAttribute(PROJBAND_ATTR) === 'suyou' && !root.body.children.includes(n1), '旧节点引用随重建离场（不残留判定）')
}

section('E 身份带 overlay（UI-5：§2.1 带面 + Sessions 菜单 + 全终态回收）')
{
  const sc = el('div', { 'data-conversation-scroll': '' })
  const doc = docOf(sc)
  doc.head.appendChild = () => {}
  const created = []
  // Richer element stub: appendChild/querySelector/querySelectorAll/addEventListener/remove
  function rich(tag) {
    const node = el(tag)
    node.children = []
    node._bySel = {}
    node.appendChild = (c) => { node.children.push(c); return c }
    node.querySelector = (sel) => node.children.find(c => sel === '[data-wb-band-menu]' && c.attributes['data-wb-band-menu'] !== undefined)
      ?? node.children.find(c => sel === '[data-wb-band-sessions]' && c.attributes['data-wb-band-sessions'] !== undefined) ?? null
    node._listeners = {}
    node.addEventListener = (k, fn) => { (node._listeners[k] ??= []).push(fn) }
    node.getBoundingClientRect = () => ({ top: 40, left: 900, width: 420 })
    node.style.setProperty('top', ''); node.style.setProperty('left', ''); node.style.setProperty('width', '')
    created.push(node)
    return node
  }
  doc.createElement = (tag) => rich(String(tag))
  doc.body.appendChild = (c) => {
    doc.body.children.push(c)
    doc.body._band = c
    // 桩的 remove=真离场（父容器 children 剔除），stop 摘除面才有断言意义
    c.remove = () => { doc.body.children = doc.body.children.filter(x => x !== c); c.removed = true }
    return c
  }
  doc.body._band = null
  const items = [
    { id: 'session-09ca0247-1', handle: '09ca', title: '09ca', rawTitle: '<!-- workbench:kind:charter -->\n<!-- session_charter.md -->\n正文', active: true },
    { id: 'session-beef0000-2', handle: 'executor', title: 'executor', active: false },
  ]
  let opened = 0
  const saved = globalThis.MutationObserver
  globalThis.MutationObserver = class { constructor() {} observe() {} disconnect() {} }
  try {
    const h = startChatProjectBand({
      doc,
      getSessions: () => items,
      onOpenSession: () => {},
      onNewSession: () => { opened++ },
    })
    const band = doc.body._band
    ok(band !== null, '带面 overlay 挂 body')
    ok(band.getAttribute('data-hidden') !== null, '锚归属未设=隐藏（不越界）')
    ok(band.children.some(c => c.className === 'wb-projband-sessions'), 'Sessions 钮在场（有 getSessions 数据源）')
    h.setInfo({ project: 'sandbar', handle: '09ca' })
    ok(band.getAttribute('data-hidden') === null, '设归属=可见')
    ok(band.style._props['--wb-projband-color'] === projectColor('sandbar'), '带面 CSS 变量=projectColor(sandbar)')
    ok(PROJBAND_BAND_CSS.includes('14%') && PROJBAND_BASE_CSS.match(/--wb-projband-color/g).length >= 3, '三通道（带面/带底/柱洗）全挂 --wb-projband-color 一个变量（§2.1 验收）')
    ok(band.getAttribute('data-wb-chat-band') === 'sandbar', '带面属性=project key')
    ok(sc.getAttribute(PROJBAND_HANDLE_ATTR) === '09ca', '句柄属性同帧落锚')
    // menu render: Sessions click -> menu children filled, + New session present
    const sessBtn = band.children.find(c => c.className === 'wb-projband-sessions')
    sessBtn._listeners.click[0]({ stopPropagation() {} })
    ok(band.getAttribute('data-menu-open') !== null, '点 Sessions=菜单开')
    const menu = band.querySelector('[data-wb-band-menu]')
    ok(menu.children.length === items.length + 1, '菜单=会话条目 + New session（执行器条目在场）')
    ok(menu.children.some(c => c.className.includes('wb-projband-new')), '+ New session 项在场（§2.6 入口 2）')
    // t261008-01 Measure 1: charter raw title -> handle label, raw text in the row tooltip.
    const rawRow = menu.children.find(c => c.getAttribute?.('data-wb-band-item') === items[0].id)
    ok(rawRow !== undefined, '会话条目按 id 可寻址')
    const rawTexts = (rawRow?.children ?? []).map(c => c.textContent).join('|')
    ok(rawTexts.split('|').includes('09ca') && !rawTexts.includes('workbench:kind:charter'), 'charter 原文标题 → 行文本=handle（非注释文本）')
    ok(rawRow?.getAttribute?.('title') === items[0].rawTitle, 'raw 标题在行 tooltip（title 属性）可达')
    const execRow = menu.children.find(c => c.getAttribute?.('data-wb-band-item') === items[1].id)
    ok(execRow?.getAttribute?.('title') === undefined || execRow?.getAttribute?.('title') === null, '无 rawTitle/同值 → 不设 tooltip（声明缺席）')
    const newBtn = menu.children.find(c => c.className.includes('wb-projband-new'))
    newBtn._listeners.click[0]({ stopPropagation() {} })
    ok(opened === 1 && band.getAttribute('data-menu-open') === null, '点 + New session=动作下发 + 菜单收起')
    h.setInfo({ project: 'suyou', handle: 'e' })
    ok(band.getAttribute('data-menu-open') === null, '换项目=菜单收起（不错项目数据）')
    h.set(null)
    ok(band.getAttribute('data-hidden') !== null, '摘归属=带面隐藏')
    h.stop()
    ok(band.removed === true, 'stop：overlay 摘除')
    ok(doc.body.children.filter(c => c.attributes['data-wb-chat-band'] !== undefined).length === 0, 'stop：body 无带面残留')
    ok(sc.getAttribute(PROJBAND_HANDLE_ATTR) === null, 'stop：句柄属性摘除')
    h.stop()
  } finally {
    globalThis.MutationObserver = saved
  }
  // No getSessions -> no Sessions button (declared degradation, no dead button)
  const doc2 = docOf(el('div', { 'data-conversation-scroll': '' }))
  doc2.head.appendChild = () => {}
  doc2.createElement = (tag) => rich(String(tag))
  doc2.body.appendChild = (c) => {
    doc2.body.children.push(c)
    doc2.body._band = c
    c.remove = () => { doc2.body.children = doc2.body.children.filter(x => x !== c); c.removed = true }
    return c
  }
  doc2.body._band = null
  const saved2 = globalThis.MutationObserver
  globalThis.MutationObserver = class { constructor() {} observe() {} disconnect() {} }
  try {
    const h2 = startChatProjectBand({ doc: doc2 })
    ok(doc2.body._band !== null && !doc2.body._band.children.some(c => c.className === 'wb-projband-sessions'), '无数据源=Sessions 钮不渲染（声明降级）')
    h2.stop()
  } finally {
    globalThis.MutationObserver = saved2
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
