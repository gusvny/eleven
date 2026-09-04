/**
 * smoke/chat-project-band.mjs —— 右栏 chat 项目色带装饰器冒烟（票② R7，t260904-05）。
 *
 * 直跑：node smoke/chat-project-band.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 被测=src/client/chat-project-band.ts（applyProjectBand 纯 DOM 面 + start/stop
 * 生命周期），DOM 用自有桩（无 jsdom），不依赖真平台包——机制对齐
 * smoke/chat-project-tag.mjs 的桩纪律。
 *
 * 覆盖（对应模块头注故障模式取舍清单）：
 *   A. applyProjectBand：设属性/CSS 变量、幂等（同值跳过）、null/畸形 key 摘除、
 *      多锚齐设、0 锚无害、非元素节点跳过。
 *   B. hexToRgba：正常展开 + 畸形 hex 不抛（NaN 传播属调用方契约，不 crash）。
 *   C. start/stop 生命周期（document 桩）：style 注入与摘除、set→属性落、
 *      stop 后属性清零、stop 幂等、set 在 stop 后无害。
 *   D. MutationObserver 防重建：重建滚动体节点后回调重设属性（真
 *      MutationObserver 不可桩——以 scan 重入面验证：重建=新节点无属性，
 *      再 scan 补齐；Observer 连接性由代码审查+集成面看守，桩面只验重设逻辑）。
 */

import {
  PROJBAND_ATTR,
  PROJBAND_BASE_CSS,
  applyProjectBand,
  hexToRgba,
  startChatProjectBand,
  startChatProjectBandEffect,
} from '../src/client/chat-project-band.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 自有 DOM 桩：最小 Element/Document 面（setattr/getattr/attr 记账 + style.setProperty）。 */
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
  ok(a.style._props['--wb-projband-color'] === '#83e76a', 'CSS 变量=projectColor（suyou 恒同色）')
  ok(applyProjectBand(root, 'suyou') === 0, '幂等：同值跳过零写动')
  ok(applyProjectBand(root, null) === 1 && a.getAttribute(PROJBAND_ATTR) === null, 'null=摘除（不在册不渲染）')
  ok(applyProjectBand(root, null) === 0, '幂等：无属性时摘除零写动')
  // 畸形 key（账册是 localStorage 外部输入）：按 null 摘除，不设属性
  const b = el('div', { 'data-conversation-scroll': '' })
  const root2 = docOf(b)
  for (const bad of ['', 42, null, undefined, { x: 1 }, 'k'.repeat(65), 'bad\nkey']) {
    applyProjectBand(root2, bad)
    ok(b.getAttribute(PROJBAND_ATTR) === null, `畸形 key 不设属性（${JSON.stringify(String(bad)).slice(0, 12)}）`)
  }
  // 多锚齐设 + 0 锚无害
  const c1 = el('div', { 'data-conversation-scroll': '' })
  const c2 = el('div', { 'data-conversation-scroll': '' })
  const root3 = docOf(c1, c2)
  ok(applyProjectBand(root3, 'sandbar') === 2 && c1.getAttribute(PROJBAND_ATTR) === 'sandbar' && c2.getAttribute(PROJBAND_ATTR) === 'sandbar', 'N 个锚全部齐设')
  ok(applyProjectBand(docOf(), 'suyou') === 0, '0 锚（blank hero 瞬态）无害返回 0')
  // 非元素脏节点跳过（畸形输入纪律：桩复现，不靠真外部源）
  const dirty = { getAttribute: 'not-a-fn' }
  const root4 = docOf(dirty, el('div', { 'data-conversation-scroll': '' }))
  ok(applyProjectBand(root4, 'suyou') === 1, '脏节点（方法缺失）跳过不崩，健康节点照常')
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
  // head.appendChild 捕获注入的 style；observe/disconnect 桩掉（真 Observer 需 DOM）
  doc.head.appendChild = (n) => { styleNode = n }
  doc.body.observe = () => {}
  const saved = globalThis.MutationObserver
  globalThis.MutationObserver = class { constructor() {} observe() {} disconnect() {} }
  try {
    const h = startChatProjectBand({ doc })
    ok(styleNode !== null && styleNode.getAttribute('data-wb-chat-projband-style') === '', 'head 注入自有 style')
    ok(styleNode.textContent === PROJBAND_BASE_CSS && styleNode.textContent.includes('border-top: 3px solid'), 'style 内容=基础规则（border-top 3px 项目色 + sticky 角标）')
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
    // effect 形态：返回清理函数本身（F1 防呆）
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
  // 重建=新节点无属性；scan（经 set 同路径）补齐——Observer 连接性由
  // 模块头注声明 + 集成看守，桩面只验重设逻辑幂等收敛。
  const n1 = el('div', { 'data-conversation-scroll': '' })
  const root = docOf(n1)
  applyProjectBand(root, 'suyou')
  const n2 = el('div', { 'data-conversation-scroll': '' })
  root.body.children = [n2]
  ok(applyProjectBand(root, 'suyou') === 1 && n2.getAttribute(PROJBAND_ATTR) === 'suyou', '重建节点经 scan 重设属性')
  ok(n1.getAttribute(PROJBAND_ATTR) === 'suyou' && !root.body.children.includes(n1), '旧节点引用随重建离场（不残留判定）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
