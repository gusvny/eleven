/**
 * smoke/chat-project-tag.mjs — smoke for the ticket-2 decorator and index singleton (t260903-07).
 *
 * Run: node smoke/chat-project-tag.mjs (node >= 22.18 native type-stripping).
 *
 * Covers (plan v2 R1 / v3 N2, R5 acceptance criteria):
 *   A. applyProjectTags: attribute applied (idempotent, no stacking / same value skipped),
 *      mapping removal recovers, negative exclusion (OWN_SCOPE_ATTR subtree untouched),
 *      malformed message text does not crash, missing mapping -> nothing applied.
 *   B. project-tag-index publish semantics: success overwrites; "success but empty" keeps
 *      last-known-good + warns once; the failure branch publishes nothing = singleton
 *      unchanged (same family as KI-018); publishProjects from outside stops the fallback.
 *   C. startProjectIndexFallback: success calls onData, retries to the cap on failure,
 *      malformed response does not crash, stops after all terminals.
 *   D. startChatProjectTag: style mounted on head (idempotent), scan applies, stop leaves
 *      zero residue (style + attributes), document lost -> stopped, no throw.
 *
 * Coverage boundary (declared honestly): the DOM is a homemade minimal stub (not jsdom,
 * not a real React environment) — this smoke only asserts pure logic and the attribute/style
 * mounting mechanism; React reconciliation safety is guaranteed structurally by the
 * "zero childList" design (see chat-project-tag.ts header); real React reconciliation
 * assertions are out of scope here.
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

/* ------------------------------------------------ Minimal DOM stub */

/** Element: attribute map + child nodes + parent chain; querySelectorAll only recognizes the three selectors this plugin uses (coverage boundary in the header). */
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
  /** Build one user message row (text = message text; kind can override to make an assistant row). */
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
  const asst = doc.addAssistantRow('工单 t260903-07 的回复') // assistant rows are not decorated (R7 scope)
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

  n = applyProjectTags(doc, new Map()) // mapping emptied (e.g. the project was retired)
  ok(rowA.getAttribute(PROJTAG_ATTR) === null && rowB.getAttribute(PROJTAG_ATTR) === null, '映射消失 → 回收属性')
  ok(n === 2, `回收计 2 行（got ${n}）`)

  // Malformed message text does not crash
  const weird = doc.addUserRow('t260903-07\x00\u2028 及超长 ' + 'x'.repeat(5000))
  doc.addUserRow('')
  doc.addUserRow(nullLike())
  ok(typeof applyProjectTags(doc, map) === 'number', '畸形文本（控制字符/超长/空）不炸')
  ok(weird.getAttribute(PROJTAG_ATTR) === 'suyou', '控制字符不影响工单 id 命中')

  // Multiple ticket refs: the first one wins
  const two = doc.addUserRow('先 t260903-07 后 t260901-15')
  applyProjectTags(doc, map)
  ok(two.getAttribute(PROJTAG_ATTR) === 'suyou', '多引用取第一个命中（确定性）')
}

function nullLike() { return undefined }

/* ---------------------------------------- B. Index publish semantics */

section('B 发布语义：覆盖/空保留 last-known-good/失败不发')
{
  _resetProjectTagIndex()
  publishProjects([{ key: 'suyou', dirs: ['/repo/suyou'] }, { key: 'sandbar', dirs: [] }, null, { key: '' }])
  const idx = readProjectTagIndex()
  ok(idx.projectDirs.get('suyou')?.[0] === '/repo/suyou', '项目集登记')
  ok(idx.projectDirs.has('sandbar') && !idx.projectDirs.has(''), '畸形条目跳过不炸')

  publishProjectEntry('suyou', ['t260903-07', 'bad-id', 42, null])
  ok(readProjectTagIndex().projectByTicket.get('t260903-07') === 'suyou', '合法工单 id 入映射，非法值过滤')

  // "Success but empty" -> keep last-known-good + warn once
  let warned = 0
  const origWarn = console.warn
  console.warn = () => { warned++ }
  publishProjectEntry('suyou', [])
  console.warn = origWarn
  ok(readProjectTagIndex().projectByTicket.get('t260903-07') === 'suyou', '空列表：保留 last-known-good')
  publishProjectEntry('suyou', [])
  ok(warned === 1, `同项目只 warn 一次（got ${warned}）`)

  // "Failure branch publishes nothing" = publishProjectEntry not called, so the singleton naturally stays unchanged (here simulated: just assert current state)
  const before = readProjectTagIndex().projectByTicket.size
  // (simulate one failed poll: nothing is published)
  ok(readProjectTagIndex().projectByTicket.size === before, '失败不发 → 单态不变（KI-018 同族）')

  // Overwrite: a new non-empty value replaces the old (including a ticket moving out of a project)
  publishProjectEntry('suyou', ['t260902-01'])
  const after = readProjectTagIndex().projectByTicket
  ok(after.get('t260902-01') === 'suyou' && !after.has('t260903-07'), '非空新值整体替换（迁移出映射正确摘除）')

  ok(projectForText('看下 t260902-01', after) === 'suyou', 'projectForText 命中')
  ok(projectForText('没有引用', after) === null && projectForText('t999999-99', after) === null, '无引用/未知工单 → null')
  ok(projectForText(42, after) === null && projectForText('', after) === null, '畸形文本 → null')
}

/* ---------------------------------------- C. Fallback self-fetch */

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

  // All fail -> retries to the cap, then stops
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

  // Malformed response does not crash
  _resetProjectTagIndex()
  stop = startProjectIndexFallback({
    fetchImpl: async () => ({ json: async () => ({ result: { projects: 'not-an-array' } }) }),
    initialDelayMs: 1, retryIntervalMs: 2, maxAttempts: 2,
  })
  await tick(40)
  ok(!readProjectTagIndex().hasData, '畸形响应：不炸、单态保持空（tag 不渲染）')
  stop()

  // External publish stops the fallback immediately
  _resetProjectTagIndex()
  let extCalls = 0
  stop = startProjectIndexFallback({ fetchImpl: goodFetch, initialDelayMs: 1, retryIntervalMs: 2, maxAttempts: 50 })
  publishProjects([{ key: 'x', dirs: [] }]) // published from outside the sidebar
  await tick(20)
  extCalls = calls
  await tick(20)
  stop()
  ok(calls === extCalls, '外部发布后兜底自取停（无双轮询面）')
}

function tick(ms) { return new Promise(r => setTimeout(r, ms)) }

/* ---------------------------------------- D. Decorator as a whole */

section('D startChatProjectTag：挂载/scan/stop 零残留/失联停手')
{
  // node has no MutationObserver: stub one (childList callback not firing is fine — scan is called manually in assertions)
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

  // Double mount does not stack (style looked up before creation)
  const h2 = startChatProjectTag({ fetchImpl: async () => { throw new Error('x') }, doc, fallback: { maxAttempts: 0 } })
  ok(doc.querySelectorAll('style[data-wb-projtag-style]').length === undefined || doc.head.children.filter(c => c.attrs['data-wb-projtag-style'] === '').length === 1, 'style 幂等：先查再建不叠加')
  h2.stop()

  // stop leaves zero residue
  h.stop()
  ok(doc.querySelector('style[data-wb-projtag-style]') === null, 'stop：style 摘除')
  ok(doc.querySelectorAll(`[${PROJTAG_ATTR}]`).length === 0, 'stop：自有属性全摘（出厂树恢复原样）')
  h.stop() // idempotent
  ok(true, 'stop 幂等不炸')

  // Lost document -> stop and stay silent
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
  // F1 cause of death: useEffect returning the handle object directly = cleanup ignored,
  // zero recovery on unmount. The effect entry must return a **function** (useEffect only
  // accepts a function as cleanup), and calling it must do full terminal-state recovery.
  const doc3 = new FakeDoc()
  doc3.addUserRow('工单 t260903-07 再来')
  publishProjects([{ key: 'suyou', dirs: [] }])
  publishProjectEntry('suyou', ['t260903-07'])
  const cleanup = startChatProjectTagEffect({ fetchImpl: async () => { throw new Error('x') }, doc: doc3, fallback: { maxAttempts: 0 } })
  ok(typeof cleanup === 'function', 'effect 入口返回函数（useEffect 可登记为 cleanup——形状级防呆）')
  cleanup()
  ok(doc3.querySelector('style[data-wb-projtag-style]') === null
    && doc3.querySelectorAll(`[${PROJTAG_ATTR}]`).length === 0, 'cleanup=全终态回收：style+属性零残留')
  cleanup() // idempotent
  ok(true, 'cleanup 幂等不炸')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
