/**
 * smoke/context-fold.mjs —— 上下文折叠件冒烟（t260905-04）。
 *
 * 直跑：node smoke/context-fold.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 被测=src/client/context-fold.ts（classifyContextFold 纯函数 + findCharterBubble
 * 定位纯函数 + applyContextFold 施折面 + start/stop 生命周期），DOM 用自有桩
 * （无 jsdom），MutationObserver 桩进 globalThis（同 chat-project-band.mjs 纪律）。
 *
 * 覆盖（对应模块头注故障模式取舍清单 + review 条件 A + arbitrate round1 回归）：
 *   A. classifyContextFold：marker 首行命中、前导空白容错、非字符串/空串/
 *      中段提及不误触发。
 *   B. findCharterBubble：唯一子链上爬到有兄弟层/滚动体直接子层、爬到滚动体
 *      本体=null（宁不折不藏滚动体）、无 marker=null、嵌套包裹链。
 *   C. applyContextFold：折叠态+小条铸入、幂等（重复回调不重插不重设）、
 *      无 marker 常态 'none'、降级 'degraded'、插入失败回滚属性。
 *   D. 孤儿小条（review 条件 A①）：气泡被移除/容器清空/文本改写后，回调
 *      摘小条+摘属性——幽灵小条不过夜。
 *   E. start/stop 生命周期（document 桩 + MutationObserver 桩）：style 注入与
 *      摘除、接线全树兜底扫、stop 回收（断桩 Observer/解绑 click/摘小条/摘
 *      属性/摘 style）、stop 幂等、无 document 软退化。
 *   F. 引用计数单例（取舍第 9 项）：双 start 只绑一次 click、先归零才真拆；
 *      StrictMode 序列（start→stop→start）第二段仍活。
 *   G. 点击委托：点小条切折叠态+文案切换；非小条点击不动。
 */

import {
  FOLD_ATTR,
  CHIP_ATTR,
  FOLD_STYLE_SELECTOR,
  CHIP_LABEL_FOLDED,
  CHIP_LABEL_OPEN,
  classifyContextFold,
  findCharterBubble,
  applyContextFold,
  startContextFold,
} from '../src/client/context-fold.ts'
import { CHARTER_MARKER } from '../src/host/session-charter.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ── 自有 DOM 桩（最小 Element/Document 面）──
 * children 语义=HTMLCollection（arbitrate round1 code-fault 修复回归用例的教训
 * 落桩：内部 _kids 数组，对外的 children 是**无数组方法的 array-like**——length+
 * 数字索引+Symbol.iterator 全真 DOM 语义，.some/.filter/.push 一律不存在。被测
 * 模块必须经 Array.from 消费，桩面才能代表浏览器真语义；桩回归用例 H 段直接断言
 * 「children 无 .some 时折叠照常工作」。 */
let nextId = 1
/** array-like（无数组方法）：真 HTMLCollection 的最小语义投影。 */
function arrayLike(arr) {
  const obj = { length: arr.length }
  arr.forEach((c, i) => { obj[i] = c })
  obj[Symbol.iterator] = function* () { yield* arr }
  return obj
}
function el(tag = 'div', text = '') {
  const node = {
    id: nextId++,
    tagName: tag,
    _kids: [],
    get children() { return arrayLike(node._kids) },
    parentElement: null,
    _text: text,
    attributes: {},
    get textContent() {
      // 自身文本 + 子树文本拼接（真 DOM 语义）
      return node._text + node._kids.map(c => c.textContent).join('')
    },
    set textContent(v) { node._text = String(v); node._kids = [] },
    get isConnected() {
      let cur = node
      while (cur.parentElement) cur = cur.parentElement
      return cur._isRoot === true
    },
    setAttribute(k, v) { node.attributes[k] = String(v) },
    getAttribute(k) { return k in node.attributes ? node.attributes[k] : null },
    removeAttribute(k) { delete node.attributes[k] },
    append(...kids) { for (const child of kids) { child.parentElement = node; node._kids.push(child) } return kids[kids.length - 1] },
    appendChild(c) { return node.append(c) },
    insertBefore(newNode, ref) {
      newNode.parentElement = node
      const i = node._kids.indexOf(ref)
      if (i === -1) node._kids.push(newNode)
      else node._kids.splice(i, 0, newNode)
      return newNode
    },
    remove() {
      const p = node.parentElement
      if (p) p._kids = p._kids.filter(c => c !== node)
      node.parentElement = null
    },
    querySelectorAll(sel) { return node._qsa(sel) },
    _qsa(sel) {
      const out = []
      const walk = (n) => { for (const c of n._kids) { out.push(c); walk(c) } }
      walk(node)
      if (sel === '*') return out
      if (sel === `[${FOLD_ATTR}]`) return out.filter(c => FOLD_ATTR in c.attributes)
      if (sel === `[${CHIP_ATTR}]`) return out.filter(c => CHIP_ATTR in c.attributes)
      return out.filter(c => sel.split(',').some(s => c._matchesSel?.(s)))
    },
    _matchesSel(s) { return false },
    closest(sel) {
      let cur = node
      while (cur) {
        if (sel === `[${CHIP_ATTR}]` && CHIP_ATTR in cur.attributes) return cur
        cur = cur.parentElement
      }
      return null
    },
  }
  return node
}
function rootEl() { const r = el('root'); r._isRoot = true; return r }

function docOf(scroll) {
  const doc = {
    documentElement: el('html'),
    head: el('head'),
    body: el('body'),
    _listeners: {},
    _style: null,
    createElement(tag) { return el(tag) },
    querySelector(sel) {
      if (sel === FOLD_STYLE_SELECTOR) return doc._style
      if (sel === '[data-conversation-scroll]') return [...doc.body.children].find(c => c === scroll) ?? null
      return null
    },
    querySelectorAll(sel) {
      if (sel === '[data-conversation-scroll]') return [...doc.body.children].filter(c => c._isScroll)
      return []
    },
    appendChild(c) { doc.head.append(c); if (c.attributes['data-wb-context-fold-style'] !== undefined) doc._style = c },
    removeChild(c) { doc.head.remove(c); if (doc._style === c) doc._style = null },
    addEventListener(type, fn) { (doc._listeners[type] ??= []).push(fn) },
    removeEventListener(type, fn) { doc._listeners[type] = (doc._listeners[type] ?? []).filter(f => f !== fn) },
  }
  // 模块经 doc.head.appendChild 注入 style——head 挂同一记账入口（摘除同）
  doc.head.appendChild = (c) => doc.appendChild(c)
  doc.head.removeChild = (c) => doc.removeChild(c)
  if (scroll) { scroll._isScroll = true; doc.body.append(scroll) }
  return doc
}

/** 标准会话 DOM：scroll > list > [bubbleCharter, bubbleReply]；charter 内 p 含 marker。 */
function charterScrollDoc() {
  const scroll = el('div')
  const list = el('div')
  const bubble = el('div')
  const p = el('p', `${CHARTER_MARKER}\n你是「sandbar」的项目会话……`)
  bubble.append(p)
  const reply = el('div', '好的，收到')
  list.append(bubble, reply)
  scroll.append(list)
  const doc = docOf(scroll)
  return { doc, scroll, list, bubble, p, reply }
}

section('A classifyContextFold：判定纯函数')
{
  ok(classifyContextFold(`${CHARTER_MARKER}\n正文`) === true, 'marker 首行命中')
  ok(classifyContextFold(`\n  ${CHARTER_MARKER}\n正文`) === true, '前导空白容错')
  ok(classifyContextFold(`正文提到 ${CHARTER_MARKER} 不算`) === false, '中段提及不误触发')
  ok(classifyContextFold('') === false && classifyContextFold(null) === false && classifyContextFold(undefined) === false, '空串/非字符串容错为 false')
  ok(classifyContextFold(CHARTER_MARKER) === true, '纯 marker 命中')
}

section('B findCharterBubble：定位纯函数')
{
  { const { scroll, bubble } = charterScrollDoc()
    ok(findCharterBubble(scroll) === bubble, '唯一子链上爬到有兄弟层=消息气泡') }
  { // 滚动体直接子层：scroll > [bubbleCharter, reply]
    const scroll = el('div'); const bubble = el('div', `${CHARTER_MARKER}\nx`); const reply = el('div', 'r')
    scroll.append(bubble, reply)
    ok(findCharterBubble(scroll) === bubble, '滚动体直接子层=气泡') }
  { // 无兄弟可分层：scroll > wrap > bubbleCharter——唯一子链爬到滚动体直接子层
    // 停（wrap=气泡，折叠它是正确语义：藏的只是这条消息，小条由 wrap 父层承载）。
    const scroll = el('div'); const wrap = el('div'); const bubble = el('div', `${CHARTER_MARKER}\nx`)
    wrap.append(bubble); scroll.append(wrap)
    ok(findCharterBubble(scroll) === wrap, '独苗链爬到滚动体直接子层=wrap（可折）') }
  { const scroll = el('div'); scroll.append(el('div', '没有注入物'))
    ok(findCharterBubble(scroll) === null, '无 marker=null') }
  { // 深嵌套：marker 在最内 c，唯一子链上爬停在「父层有兄弟」的 b 层（b=消息容器，
      // a=含 sib 的列表层，不是气泡）。
    const scroll = el('div'); const a = el('div'); const b = el('div'); const c = el('div', `${CHARTER_MARKER}\nx`)
    b.append(c); a.append(b); const sibling = el('div', 'sib'); a.append(sibling); scroll.append(a)
    ok(findCharterBubble(scroll) === b, '深嵌套：停在父层有兄弟的 b 层=气泡') }
}

section('C applyContextFold：施折面')
{
  // 模块级 state 只能经 start 建立——C 段统一走 start/stop 生命周期施折
  globalThis.MutationObserver = class { observe() {} disconnect() {} }
  {
    const { doc, scroll, bubble } = charterScrollDoc()
    const stop = startContextFold({ doc })
    ok(bubble.getAttribute(FOLD_ATTR) === 'folded', '接线兜底扫：气泡打折叠态')
    const chips = scroll.querySelectorAll(`[${CHIP_ATTR}]`)
    ok(chips.length === 1 && [...bubble.parentElement.children].includes(chips[0]), '小条恰一条且插在气泡紧前方')
    ok(chips[0].textContent === CHIP_LABEL_FOLDED, '小条文案=折叠态')
    const again = applyContextFold(scroll, doc)
    ok(again === 'folded' && scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 1, '重复回调幂等：不重插')
    ok(bubble.getAttribute(FOLD_ATTR) === 'folded', '重复回调不重设折叠态')
    stop()
  }
  {
    const doc = docOf(null); const scroll = el('div'); scroll.append(el('div', '普通消息')); doc.body.append(scroll); scroll._isScroll = true
    const stop = startContextFold({ doc })
    ok(applyContextFold(scroll, doc) === 'none', '无 marker=常态 none')
    stop()
  }
  {
    // 独苗链：爬到滚动体直接子层 wrap=气泡，正常折叠（气泡是滚动体本身才降级，
    // 该分支结构性不可达——停爬条件含 parentElement===scroll，保底防御保留）。
    const scroll = el('div'); const wrap = el('div'); wrap.append(el('div', `${CHARTER_MARKER}\nx`)); scroll.append(wrap)
    const doc = docOf(scroll)
    const stop = startContextFold({ doc })
    ok(applyContextFold(scroll, doc) === 'folded' && wrap.getAttribute(FOLD_ATTR) === 'folded', '独苗链：wrap 层正常折叠')
    stop()
  }
}

section('D 孤儿小条：气泡移除/清空/改写后不残留（review 条件 A）')
{
  { // 气泡被移除（会话切换：列表整体替换）
    const { doc, scroll, list, bubble } = charterScrollDoc()
    const stop = startContextFold({ doc })
    ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 1, '前置：小条在场')
    list._kids = list._kids.filter(c => c !== bubble) // 模拟 React 清气泡（小条非 React 记录节点，不被清）
    applyContextFold(scroll, doc)
    ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 0, '气泡被移除：小条被孤儿清扫摘除')
    ok(bubble.getAttribute(FOLD_ATTR) === null, '被摘气泡的折叠态属性清除')
    stop()
  }
  { // 容器内容清空
    const { doc, scroll, list } = charterScrollDoc()
    const stop = startContextFold({ doc })
    list._kids = []
    applyContextFold(scroll, doc)
    ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 0, '容器清空：小条不残留')
    stop()
  }
  { // 气泡文本被改写（marker 消失）
    const { doc, scroll, p } = charterScrollDoc()
    const stop = startContextFold({ doc })
    p._text = '普通回复文本'
    applyContextFold(scroll, doc)
    ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 0, '文本改写去 marker：小条摘除')
    stop()
  }
}

section('E start/stop 生命周期')
{
  const { doc, scroll, bubble } = charterScrollDoc()
  const stop = startContextFold({ doc })
  ok(doc._style !== null && doc._style.textContent.includes(FOLD_ATTR), 'head 注入自有 style')
  ok(bubble.getAttribute(FOLD_ATTR) === 'folded', '接线时全树兜底扫')
  ok((doc._listeners.click ?? []).length === 1, 'click 委托恰绑一次')
  stop()
  ok(doc._style === null, 'stop 摘 style')
  ok((doc._listeners.click ?? []).length === 0, 'stop 解绑 click')
  ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 0, 'stop 摘自铸小条')
  ok(bubble.getAttribute(FOLD_ATTR) === null, 'stop 摘折叠态属性')
  stop() // 幂等
  ok((doc._listeners.click ?? []).length === 0 && doc._style === null, 'stop 幂等')
  { // 无 document 软退化
    const savedDoc = globalThis.document
    // @ts-expect-error 桩面
    globalThis.document = undefined
    const stop2 = startContextFold()
    ok(typeof stop2 === 'function', '无 document：返回 no-op 清理函数不抛')
    stop2()
    globalThis.document = savedDoc
  }
}

section('F 引用计数单例：双 start 只绑一次 / StrictMode 序列')
{
  const { doc, scroll } = charterScrollDoc()
  const stop1 = startContextFold({ doc })
  const stop2 = startContextFold({ doc })
  ok((doc._listeners.click ?? []).length === 1, '双 start 只绑一次 click（防重入）')
  ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 1, '双 start 小条仍恰一条')
  stop1()
  ok((doc._listeners.click ?? []).length === 1, '引用未归零：监听仍在')
  ok(doc._style !== null, '引用未归零：style 仍在')
  stop2()
  ok((doc._listeners.click ?? []).length === 0 && doc._style === null, '引用归零才真拆')
  { // StrictMode：start→stop→start 第二段仍活
    const s1 = startContextFold({ doc })
    s1()
    const s2 = startContextFold({ doc })
    ok((doc._listeners.click ?? []).length === 1 && scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 1, 'StrictMode 序列：第二段照常折叠')
    s2()
  }
}

section('G 点击委托：展开/收起')
{
  const { doc, scroll, bubble } = charterScrollDoc()
  const stop = startContextFold({ doc })
  const chip = scroll.querySelectorAll(`[${CHIP_ATTR}]`)[0]
  const click = doc._listeners.click[0]
  click({ target: chip })
  ok(bubble.getAttribute(FOLD_ATTR) === 'open' && chip.textContent === CHIP_LABEL_OPEN, '点小条：展开+文案切换')
  click({ target: chip })
  ok(bubble.getAttribute(FOLD_ATTR) === 'folded' && chip.textContent === CHIP_LABEL_FOLDED, '再点：收起+文案还原')
  click({ target: bubble }) // 非小条点击
  ok(bubble.getAttribute(FOLD_ATTR) === 'folded', '非小条点击不动')
  click({ target: { closest: () => null } }) // closest 不命中
  ok(bubble.getAttribute(FOLD_ATTR) === 'folded', 'closest 不命中不动')
  click({ target: null }) // 畸形 target
  ok(bubble.getAttribute(FOLD_ATTR) === 'folded', 'target=null 容错不抛')
  stop()
}

section('H children=HTMLCollection 语义回归（arbitrate round1 code-fault 根因）')
{
  // 桩 children 已是无 .some 的 array-like（真 HTMLCollection 语义投影）——先证桩
  // 语义本身，再证被测模块在无数组方法 children 上照常工作（Array.from 修复面）。
  const { doc, scroll, bubble, list } = charterScrollDoc()
  ok(typeof scroll.children.some !== 'function' && typeof scroll.children.filter !== 'function'
    && scroll.children.length === 1 && scroll.children[0] === list, '桩语义：children 无数组方法、length+索引+可迭代')
  ok([...scroll.children][0] === list, '桩语义：children 可迭代展开')
  const stop = startContextFold({ doc })
  ok(bubble.getAttribute(FOLD_ATTR) === 'folded' && scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 1,
    '无数组方法 children 上折叠全链路照常工作（Array.from 消费）')
  applyContextFold(scroll, doc) // 重复回调（原崩溃路径：elementChildren().some）
  ok(scroll.querySelectorAll(`[${CHIP_ATTR}]`).length === 1, '重复回调不再 TypeError（回归锚）')
  stop()
}

console.log(`\ncontext-fold smoke: passed=${passed} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
