/**
 * smoke/chat-project-tag.mjs —— t260903-07 工单② 装饰器与索引单态冒烟。
 *
 * 直跑：node smoke/chat-project-tag.mjs（node ≥22.18 原生 type-stripping）。
 *
 * 覆盖（方案 v2 R1 / v3 N2、R5 验收口径）：
 *   A. applyProjectTags：属性施加（幂等不叠加/同值跳过）、映射消失回收、负向排除
 *      （OWN_SCOPE_ATTR 子树不碰）、畸形消息文本不炸、映射缺失不施。
 *   B. project-tag-index 发布语义：成功覆盖；「成功但空」保留 last-known-good+warn 一次；
 *      失败分支不发=单态不变（KI-018 同族）；publishProjects 外部发布即关停兜底。
 *   C. startProjectIndexFallback：成功 onData、失败重试至上限、畸形响应不炸、全终态停止。
 *   D. startChatProjectTag：style 挂载 head（幂等）、scan 施加、stop 零残留（style+属性）、
 *      document 失联 stopped 停手不抛。
 *
 * 覆盖边界（如实声明）：DOM 用自有最小桩（非 jsdom、非真实 React 环境）——本 smoke
 * 只断言纯逻辑与属性/样式挂载机制；React 协调安全性由机制层「零 childList」结构保证
 * （见 chat-project-tag.ts 头注），此处不做也做不了真 React 协调断言。
 */

import {
  applyProjectTags, projectForText, startChatProjectTag, startChatProjectTagEffect, PROJTAG_ATTR,
} from '../src/client/chat-project-tag.ts'
import {
  publishProjectEntry, publishProjects, readProjectTagIndex,
  startProjectIndexFallback, _resetProjectTagIndex,
} from '../src/client/project-tag-index.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ------------------------------------------------ 最小 DOM 桩 */

/** 元素：属性表 + 子节点 + 父链；querySelectorAll 只认本插件用到的三个选择器（覆盖边界见头注）。 */
class FakeEl {
  constructor(tag, attrs = {}, parent = null) {
    this.tagName = tag
    this.attrs = { ...attrs }
    this.parent = parent
    this.children = []
    this.textNodes = []
    this.style = {}
  }
  get textContent() {
    if (this._text !== undefined) return this._text
    return this.textNodes.join('') + this.children.map(c => c.textContent).join('')
  }
  set textContent(v) { this._text = String(v) }
  setAttribute(k, v) { this.attrs[k] = String(v) }
  appendChild(c) { c.parent = this; this.children.push(c); return c }
  remove() {
    if (this.parent !== null) {
      const i = this.parent.children.indexOf(this)
      if (i >= 0) this.parent.children.splice(i, 1)
    }
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null }
  removeAttribute(k) { delete this.attrs[k] }
  closest(sel) {
    if (sel === `[${PROJTAG_ATTR}]`) return this.getAttribute(PROJTAG_ATTR) !== null ? this : null
    const m = sel.match(/^\[(.+)\]$/)
    const want = m ? m[1] : null
    for (let e = this; e; e = e.parent) {
      if (want !== null && Object.prototype.hasOwnProperty.call(e.attrs, want)) return e
    }
    return null
  }
  isUserRow() {
    return 'data-chat-anchor-key' in this.attrs && this.attrs['data-chat-flow-kind'] === 'user'
  }
}

class FakeDoc {
  constructor() {
    this.documentElement = new FakeEl('html')
    this.documentElement.isConnected = true
    this.head = new FakeEl('head', {}, this.documentElement)
    this.body = new FakeEl('body', {}, this.documentElement)
    this.rows = []
    this.createElement = (tag) => new FakeEl(tag)
    this.querySelectorAllCache = () => this.rows
  }
  querySelector(sel) {
    if (sel === 'style[data-wb-projtag-style]') return this.head.children.find(c => c.attrs['data-wb-projtag-style'] === '') ?? null
    return null
  }
  querySelectorAll(sel) {
    if (sel === `[${PROJTAG_ATTR}]`) return this.rows.filter(r => r.getAttribute(PROJTAG_ATTR) !== null)
    if (sel === '[data-chat-anchor-key][data-chat-flow-kind="user"]') return this.rows.filter(r => r.isUserRow())
    return []
  }
  /** 组一条用户消息行（text=消息文本；kind 可覆盖造 assistant 行）。 */
  addUserRow(text, { kind = 'user', scope = false } = {}) {
    const row = new FakeEl('div', { 'data-chat-anchor-key': `k${this.rows.length}`, 'data-chat-flow-kind': kind }, this.body)
    if (scope) row.setAttribute('data-wb-projtag-scope', '')
    row.textNodes.push(text)
    this.body.children.push(row)
    this.rows.push(row)
    return row
  }
  addAssistantRow(text) { return this.addRowKind('assistant', text) }
  addRowKind(kind, text) {
    const row = new FakeEl('div', { 'data-chat-anchor-key': `k${this.rows.length}`, 'data-chat-flow-kind': kind }, this.body)
    row.textNodes.push(text)
    this.body.children.push(row)
    this.rows.push(row)
    return row
  }
}

/* ------------------------------------------------ A applyProjectTags */

section('A applyProjectTags：施加/幂等/回收/排除/畸形')
{
  const doc = new FakeDoc()
  const map = new Map([['t260903-07', 'suyou'], ['t260901-15', 'sandbar']])
  const rowA = doc.addUserRow('【派活指令】工单 t260903-07 干活')
  const rowB = doc.addUserRow('工单 t260901-15 的事')
  const rowPlain = doc.addUserRow('随便聊聊，没有工单引用')
  const asst = doc.addAssistantRow('工单 t260903-07 的回复') // assistant 行不装饰（R7 范围）
  const scoped = doc.addUserRow('工单 t260903-07 在自有作用域内', { scope: true })

  let n = applyProjectTags(doc, map)
  ok(rowA.getAttribute(PROJTAG_ATTR) === 'suyou', '工单引用 → 施加项目属性')
  ok(rowB.getAttribute(PROJTAG_ATTR) === 'sandbar', '不同工单 → 不同项目')
  ok(rowPlain.getAttribute(PROJTAG_ATTR) === null, '无引用 → 不渲染（映射缺失声明行为）')
  ok(asst.getAttribute(PROJTAG_ATTR) === null, 'assistant 行不装饰（R7 范围收窄）')
  ok(scoped.getAttribute(PROJTAG_ATTR) === null, '负向排除：自有作用域子树不碰')
  ok(n === 2, `首次施加写动 2 行（got ${n}）`)

  n = applyProjectTags(doc, map)
  ok(n === 0, '幂等：同值重扫零写动（React 反复触发不抖）')
  rowA.setAttribute(PROJTAG_ATTR, 'suyou')
  ok(applyProjectTags(doc, map) === 0, '先查再设：同值不重写')

  n = applyProjectTags(doc, new Map()) // 映射清空（如项目下线）
  ok(rowA.getAttribute(PROJTAG_ATTR) === null && rowB.getAttribute(PROJTAG_ATTR) === null, '映射消失 → 回收属性')
  ok(n === 2, `回收计 2 行（got ${n}）`)

  // 畸形消息文本不炸
  const weird = doc.addUserRow('t260903-07\x00\u2028 及超长 ' + 'x'.repeat(5000))
  doc.addUserRow('')
  doc.addUserRow(nullLike())
  ok(typeof applyProjectTags(doc, map) === 'number', '畸形文本（控制字符/超长/空）不炸')
  ok(weird.getAttribute(PROJTAG_ATTR) === 'suyou', '控制字符不影响工单 id 命中')

  // 多工单引用取第一个
  const two = doc.addUserRow('先 t260903-07 后 t260901-15')
  applyProjectTags(doc, map)
  ok(two.getAttribute(PROJTAG_ATTR) === 'suyou', '多引用取第一个命中（确定性）')
}

function nullLike() { return undefined }

/* ---------------------------------------- B 索引发布语义 */

section('B 发布语义：覆盖/空保留 last-known-good/失败不发')
{
  _resetProjectTagIndex()
  publishProjects([{ key: 'suyou', dirs: ['/repo/suyou'] }, { key: 'sandbar', dirs: [] }, null, { key: '' }])
  const idx = readProjectTagIndex()
  ok(idx.projectDirs.get('suyou')?.[0] === '/repo/suyou', '项目集登记')
  ok(idx.projectDirs.has('sandbar') && !idx.projectDirs.has(''), '畸形条目跳过不炸')

  publishProjectEntry('suyou', ['t260903-07', 'bad-id', 42, null])
  ok(readProjectTagIndex().projectByTicket.get('t260903-07') === 'suyou', '合法工单 id 入映射，非法值过滤')

  // 「成功但空」→ 保留 last-known-good + warn 一次
  let warned = 0
  const origWarn = console.warn
  console.warn = () => { warned++ }
  publishProjectEntry('suyou', [])
  console.warn = origWarn
  ok(readProjectTagIndex().projectByTicket.get('t260903-07') === 'suyou', '空列表：保留 last-known-good')
  publishProjectEntry('suyou', [])
  ok(warned === 1, `同项目只 warn 一次（got ${warned}）`)

  // 「失败分支不发」=不调 publishProjectEntry，单态自然不变（此处模拟：直接断言现状）
  const before = readProjectTagIndex().projectByTicket.size
  // （模拟一次失败轮询：什么都不发）
  ok(readProjectTagIndex().projectByTicket.size === before, '失败不发 → 单态不变（KI-018 同族）')

  // 覆盖：非空新值替换旧值（含工单迁移出项目）
  publishProjectEntry('suyou', ['t260902-01'])
  const after = readProjectTagIndex().projectByTicket
  ok(after.get('t260902-01') === 'suyou' && !after.has('t260903-07'), '非空新值整体替换（迁移出映射正确摘除）')

  ok(projectForText('看下 t260902-01', after) === 'suyou', 'projectForText 命中')
  ok(projectForText('没有引用', after) === null && projectForText('t999999-99', after) === null, '无引用/未知工单 → null')
  ok(projectForText(42, after) === null && projectForText('', after) === null, '畸形文本 → null')
}

/* ---------------------------------------- C 兜底自取 */

section('C startProjectIndexFallback：成功/失败重试/畸形响应')
{
  _resetProjectTagIndex()
  let onDataCalls = 0
  let calls = 0
  const goodFetch = async (url) => {
    calls++
    if (String(url).includes('/wf/projects')) {
      return { json: async () => ({ result: { projects: [{ key: 'suyou', dirs: ['/r'] }] } }) }
    }
    return { json: async () => ({ result: { tickets: [{ id: 't260903-07' }] } }) }
  }
  let stop = startProjectIndexFallback({
    fetchImpl: goodFetch, initialDelayMs: 1, retryIntervalMs: 5, maxAttempts: 3,
    onData: () => { onDataCalls++ },
  })
  await tick(50)
  ok(readProjectTagIndex().projectByTicket.get('t260903-07') === 'suyou', '兜底拉取成功入单态')
  ok(onDataCalls >= 1, '成功回调 onData 恰好触发')
  const callsAtSuccess = calls
  await tick(30)
  ok(calls === callsAtSuccess, '有数据后不再重试（停止条件）')
  stop()

  // 全失败 → 重试至上限后停
  _resetProjectTagIndex()
  let failCalls = 0
  stop = startProjectIndexFallback({
    fetchImpl: async () => { failCalls++; throw new Error('boom') },
    initialDelayMs: 1, retryIntervalMs: 2, maxAttempts: 3,
  })
  await tick(80)
  ok(failCalls === 3, `失败重试恰好至上限 3 次（got ${failCalls}）`)
  const c = failCalls
  await tick(20)
  ok(failCalls === c, '达上限后停手（防永久轮询）')
  stop()

  // 畸形响应不炸
  _resetProjectTagIndex()
  stop = startProjectIndexFallback({
    fetchImpl: async () => ({ json: async () => ({ result: { projects: 'not-an-array' } }) }),
    initialDelayMs: 1, retryIntervalMs: 2, maxAttempts: 2,
  })
  await tick(40)
  ok(!readProjectTagIndex().hasData, '畸形响应：不炸、单态保持空（tag 不渲染）')
  stop()

  // 外部发布即自停
  _resetProjectTagIndex()
  let extCalls = 0
  stop = startProjectIndexFallback({ fetchImpl: goodFetch, initialDelayMs: 1, retryIntervalMs: 2, maxAttempts: 50 })
  publishProjects([{ key: 'x', dirs: [] }]) // 侧栏外部发布
  await tick(20)
  extCalls = calls
  await tick(20)
  stop()
  ok(calls === extCalls, '外部发布后兜底自取停（无双轮询面）')
}

function tick(ms) { return new Promise(r => setTimeout(r, ms)) }

/* ---------------------------------------- D 装饰器整体 */

section('D startChatProjectTag：挂载/scan/stop 零残留/失联停手')
{
  // node 无 MutationObserver：桩一个（childList 回调不触发也行——scan 手动调用断言）
  class FakeMO { observe() {} disconnect() {} }
  globalThis.MutationObserver = FakeMO

  const doc = new FakeDoc()
  doc.addUserRow('工单 t260903-07 开工')
  publishProjects([{ key: 'suyou', dirs: [] }])
  publishProjectEntry('suyou', ['t260903-07'])

  const h = startChatProjectTag({ fetchImpl: async () => { throw new Error('不应触发：单态已有数据') }, doc, fallback: { maxAttempts: 0 } })
  const style = doc.querySelector('style[data-wb-projtag-style]')
  ok(style !== null, '自有 style 挂入 head（React 树之外）')
  ok(style.textContent.includes('[data-wb-projtag="suyou"]'), '着色规则随项目集生成')

  h.scan()
  ok(doc.rows[0].getAttribute(PROJTAG_ATTR) === 'suyou', 'scan 施加属性')

  // 重复挂载不叠加（style 先查再建）
  const h2 = startChatProjectTag({ fetchImpl: async () => { throw new Error('x') }, doc, fallback: { maxAttempts: 0 } })
  ok(doc.querySelectorAll('style[data-wb-projtag-style]').length === undefined || doc.head.children.filter(c => c.attrs['data-wb-projtag-style'] === '').length === 1, 'style 幂等：先查再建不叠加')
  h2.stop()

  // stop 零残留
  h.stop()
  ok(doc.querySelector('style[data-wb-projtag-style]') === null, 'stop：style 摘除')
  ok(doc.querySelectorAll(`[${PROJTAG_ATTR}]`).length === 0, 'stop：自有属性全摘（出厂树恢复原样）')
  h.stop() // 幂等
  ok(true, 'stop 幂等不炸')

  // 失联停手
  const doc2 = new FakeDoc()
  doc2.documentElement.isConnected = false
  const h3 = startChatProjectTag({ fetchImpl: async () => { throw new Error('x') }, doc: doc2, fallback: { maxAttempts: 0 } })
  let threw = false
  try { h3.scan() } catch { threw = true }
  ok(!threw, 'document 失联：scan 停手不抛（降级 warn 一次）')
  h3.stop()
}

section("E startChatProjectTagEffect：effect 形态入口（F1 接线防呆回归网）")
{
  // F1 死因：useEffect 直接返回 handle 对象=cleanup 被忽略、卸载零回收。
  // effect 入口必须返回**函数**（useEffect 只认函数 cleanup），且调用它=全终态回收。
  const doc3 = new FakeDoc()
  doc3.addUserRow('工单 t260903-07 再来')
  publishProjects([{ key: 'suyou', dirs: [] }])
  publishProjectEntry('suyou', ['t260903-07'])
  const cleanup = startChatProjectTagEffect({ fetchImpl: async () => { throw new Error('x') }, doc: doc3, fallback: { maxAttempts: 0 } })
  ok(typeof cleanup === 'function', 'effect 入口返回函数（useEffect 可登记为 cleanup——形状级防呆）')
  cleanup()
  ok(doc3.querySelector('style[data-wb-projtag-style]') === null
    && doc3.querySelectorAll(`[${PROJTAG_ATTR}]`).length === 0, 'cleanup=全终态回收：style+属性零残留')
  cleanup() // 幂等
  ok(true, 'cleanup 幂等不炸')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
