/**
 * chat-project-tag-refresh.mjs —— t260911-06：chat 项目 tag 索引通知/按需强取 UT 层。
 *
 * 背景（260911 夜 chat-project-tag 间歇红「新行无 chip、旧行有」仲裁归因）：
 *   ①外部发布（侧栏 10s 轮询）不通知装饰器 → 数据落地后无人重扫，行是否补装饰
 *     全看「碰巧有无别的 DOM 变动」；②新建工单的映射要等下一个轮询周期才进索引，
 *     负载窗内场景重试窗口耗尽即红。本 UT 锁两个缺口的产品面修复：
 *   R1 publish* 仅在数据实际变化时通知订阅者（同值重发零通知）；
 *   R2 装饰器订阅通知 → 外部发布后无 DOM 变动也即刻补装（Gap1 回归锁）；
 *   R3 scan 发现「带票号未归属」的新引用 → nudge 单次强取 → 发布 → 通知 → 补装；
 *   R4 nudge 有界：在途去重、最小间隔、按引用去重（假票号不无限重试）；
 *   R5 stop 全终态回收：退订通知、停兜底、摘自铸物，publish 后零动作；
 *   R6 firstUnmappedTicketRef 纯函数判定面（未装饰才参与/作用域排除/assistant 排除）。
 *
 * 桩口径：同族 smoke/chat-project-tag.mjs 的自制最小 DOM 桩（非 jsdom；覆盖声明见彼
 * 文件头）。Run: node tests/chat-project-tag-refresh.mjs（exit 0 = 过）。
 */
import {
  applyProjectTags, firstUnmappedTicketRef, startChatProjectTag, PROJTAG_ATTR,
} from '../src/client/chat-project-tag.ts'
import {
  _resetProjectTagIndex, onProjectTagIndexChange, publishProjectEntry, publishProjects,
  readProjectTagIndex, startProjectIndexFallback,
} from '../src/client/project-tag-index.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function tick(ms) { return new Promise(r => setTimeout(r, ms)) }

/* ---- 最小 DOM 桩（同族 smoke；querySelectorAll 只认本插件三个选择器）---- */
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
  addUserRow(text, { kind = 'user', scope = false } = {}) {
    const row = new FakeEl('div', { 'data-chat-anchor-key': `k${this.rows.length}`, 'data-chat-flow-kind': kind }, this.body)
    if (scope) row.setAttribute('data-wb-projtag-scope', '')
    if (text !== undefined) row.textNodes.push(text)
    this.body.children.push(row)
    this.rows.push(row)
    return row
  }
}
class FakeMO { observe() {} disconnect() {} }
globalThis.MutationObserver = FakeMO

/* ---- R1 发布通知：仅数据实际变化才通知 ---- */
section('R1 publish* 变更通知：同值零通知、变化恰一次、退订生效')
{
  _resetProjectTagIndex()
  let fired = 0
  const off = onProjectTagIndexChange(() => { fired++ })

  publishProjects([{ key: 'seedq', dirs: ['/r/seedq'] }])
  ok(fired === 1, `新项目集 → 通知 1 次（got ${fired}）`)
  publishProjects([{ key: 'seedq', dirs: ['/r/seedq'] }])
  ok(fired === 1, '同值项目集重发（10s 轮询常态）→ 零通知')
  publishProjects([{ key: 'seedq', dirs: ['/r/seedq'] }, { key: 'seedws', dirs: [] }])
  ok(fired === 2, `项目集变化 → 通知（got ${fired}）`)

  publishProjectEntry('seedq', ['t260903-07'])
  ok(fired === 3, `新工单映射 → 通知（got ${fired}）`)
  publishProjectEntry('seedq', ['t260903-07'])
  ok(fired === 3, '同值工单映射重发 → 零通知（delete-then-add 不再误报变化）')
  publishProjectEntry('seedq', [])
  ok(fired === 3 && readProjectTagIndex().projectByTicket.get('t260903-07') === 'seedq',
    '空列表（last-known-good 保留）→ 零通知且映射不丢')
  publishProjectEntry('seedq', ['t260902-01'])
  ok(fired === 4, `工单迁移（整体替换）→ 通知（got ${fired}）`)

  off()
  publishProjects([{ key: 'other', dirs: [] }])
  ok(fired === 4, '退订后不再通知')
  off() // 幂等
  ok(true, '退订幂等不炸')
}

/* ---- R2 Gap1 回归锁：外部发布后无 DOM 变动也即刻补装 ---- */
section('R2 装饰器订阅：外部发布 → 无 DOM 变动 → 行即刻补装（Gap1 回归锁）')
{
  _resetProjectTagIndex()
  const doc = new FakeDoc()
  const row = doc.addUserRow('【派活指令】工单 t260903-07 干活')
  const h = startChatProjectTag({
    fetchImpl: async () => { throw new Error('R2 不应触发 fetch（索引自取已停）') },
    doc,
    fallback: { maxAttempts: 0, nudgeMinIntervalMs: 60_000 },
  })
  h.scan()
  ok(row.getAttribute(PROJTAG_ATTR) === null, '索引空窗插入的行：无映射 → 无 tag（声明行为）')

  // 侧栏路径外部发布（期间零 DOM 变动——旧实现此处永远裸奔）
  publishProjects([{ key: 'seedq', dirs: [] }])
  publishProjectEntry('seedq', ['t260903-07'])
  ok(row.getAttribute(PROJTAG_ATTR) === 'seedq', '外部发布数据落地 → 订阅触发重扫 → 行即刻补装')

  h.stop()
  ok(row.getAttribute(PROJTAG_ATTR) === null, 'stop：自铸属性摘除（出厂树恢复）')
}

/* ---- R3 nudge 子用例：新票映射滞后 → 单次强取 → 补装 ---- */
section('R3 nudge：带票号未归属 → 强取一轮 → 发布通知 → 补装')
{
  _resetProjectTagIndex()
  const doc = new FakeDoc()
  let projectsCalls = 0
  let ticketsCalls = 0
  const h = startChatProjectTag({
    fetchImpl: async (url) => {
      if (String(url).includes('/wf/projects')) {
        projectsCalls++
        return { json: async () => ({ result: { projects: [{ key: 'seedq', dirs: ['/r'] }] } }) }
      }
      ticketsCalls++
      // 第 1 轮：索引已建但**没有**这张新票（数据源落后）；nudge 第 2 轮：票已在
      return { json: async () => ({ result: { tickets: ticketsCalls >= 2 ? [{ id: 't260903-07' }] : [] } }) }
    },
    doc,
    fallback: { initialDelayMs: 0, nudgeMinIntervalMs: 60_000 },
  })
  // 等首轮兜底自取（projects + tickets 各一次）落地：索引 hasData 但缺新票
  await tick(30)
  ok(readProjectTagIndex().hasData === true, '首轮自取：索引有数据（项目登记在案）')
  ok(readProjectTagIndex().projectByTicket.has('t260903-07') === false, '首轮工单列表尚无新票（数据源滞后现场）')

  const row = doc.addUserRow('工单 t260903-07 开工')
  h.scan()
  ok(row.getAttribute(PROJTAG_ATTR) === null, '映射缺失 → scan 不装饰（声明行为不造假 key）')
  await tick(30)
  ok(ticketsCalls >= 2, `nudge 强取发生（tickets 拉取 ${ticketsCalls} 次）`)
  ok(row.getAttribute(PROJTAG_ATTR) === 'seedq', '强取拉到新票 → 发布通知 → 行补装（Gap2 收口）')

  const callsAtSettled = projectsCalls + ticketsCalls
  h.scan(); h.scan(); h.scan()
  await tick(20)
  ok(projectsCalls + ticketsCalls === callsAtSettled, '同引用不重复强取（按引用去重）')
  h.stop()
}

/* ---- R4 nudge 有界 ---- */
section('R4 nudge 有界：在途去重 / 最小间隔 / 间隔期满放行 / stop 后不取')
{
  _resetProjectTagIndex()
  let calls = 0
  const fb = startProjectIndexFallback({
    fetchImpl: async () => {
      calls++
      await tick(15) // 慢响应：在途窗口可观测
      return { json: async () => ({ result: { projects: [{ key: 'k', dirs: [] }] } }) }
    },
    initialDelayMs: 0,
    retryIntervalMs: 60_000,
    maxAttempts: 1,
    nudgeMinIntervalMs: 60_000,
  })
  await tick(80) // 首轮自取完成（一轮=projects+tickets 两次取数，calls=2；有数据后定时轮询自停）
  const base = calls
  fb.nudge(); fb.nudge(); fb.nudge()
  await tick(80)
  ok(calls === base + 2, `在途去重：并发三次 nudge 只发一轮（一轮=2 次取数，got +${calls - base}）`)
  fb.nudge()
  await tick(80)
  ok(calls === base + 2, '最小间隔（60s）内的 nudge 被拒')
  fb.stop()
  const afterStop = calls
  await tick(30)
  fb.nudge()
  await tick(30)
  ok(calls === afterStop, 'stop 后 nudge 不取（全终态回收）')

  // 间隔期满放行分支：1ms 间隔句柄
  _resetProjectTagIndex()
  let calls2 = 0
  const fb2 = startProjectIndexFallback({
    fetchImpl: async () => {
      calls2++
      await tick(2)
      return { json: async () => ({ result: { projects: [{ key: 'k', dirs: [] }] } }) }
    },
    initialDelayMs: 0,
    retryIntervalMs: 60_000,
    maxAttempts: 1,
    nudgeMinIntervalMs: 1,
  })
  await tick(20) // 首轮（2 次取数）
  fb2.nudge()
  await tick(20)
  ok(calls2 === 4, '间隔期满首个 nudge 放行（+2 次取数）')
  fb2.nudge()
  await tick(20)
  ok(calls2 === 6, '间隔（1ms）期满后再次放行')
  fb2.stop()
}

/* ---- R6 firstUnmappedTicketRef 纯函数 ---- */
section('R6 firstUnmappedTicketRef：未装饰才参与/排除面/畸形输入')
{
  _resetProjectTagIndex()
  const doc = new FakeDoc()
  const map = new Map([['t260903-07', 'seedq']])
  doc.addUserRow('工单 t260903-07 已归属')
  ok(firstUnmappedTicketRef(doc, map) === null, '已装饰行不参与')
  doc.addUserRow('工单 t260901-15 未归属')
  ok(firstUnmappedTicketRef(doc, map) === 't260901-15', '未归属票号 → 返回该引用')
  doc.addUserRow('作用域内 t260902-01', { scope: true })
  ok(firstUnmappedTicketRef(doc, map) === 't260901-15', '自有作用域行排除（负向排除面）')
  doc.addUserRow('assistant t260903-01', { kind: 'assistant' })
  ok(firstUnmappedTicketRef(doc, map) === 't260901-15', 'assistant 行排除（R7 范围）')
  doc.addUserRow('无任何引用')
  doc.addUserRow('')
  doc.addUserRow(undefined)
  ok(firstUnmappedTicketRef(doc, map) === 't260901-15', '畸形/空文本行不炸不误报')
  doc.rows.find(r => r.textContent.includes('t260901-15')).setAttribute(PROJTAG_ATTR, 'x')
  ok(firstUnmappedTicketRef(doc, map) === null, '全装饰后 → null（不 nudge）')
  ok(applyProjectTags(doc, map) >= 0, 'applyProjectTags 行为面不回归（冒烟触达）')
}

/* ---- R5 stop 全回收（通知面 + 兜底面）---- */
section('R5 stop 全终态回收：退订通知 / 停 nudge / 摘自铸物')
{
  _resetProjectTagIndex()
  const doc = new FakeDoc()
  doc.addUserRow('工单 t260903-07 开工')
  publishProjects([{ key: 'seedq', dirs: [] }])
  publishProjectEntry('seedq', ['t260903-07'])
  let fetchCalls = 0
  const h = startChatProjectTag({
    fetchImpl: async () => { fetchCalls++; return { json: async () => ({ result: { projects: [{ key: 'seedq', dirs: [] }] } }) } },
    doc,
    fallback: { initialDelayMs: 0, nudgeMinIntervalMs: 1 },
  })
  h.scan()
  h.stop()
  ok(doc.querySelector('style[data-wb-projtag-style]') === null, 'style 摘除')
  ok(doc.querySelectorAll(`[${PROJTAG_ATTR}]`).length === 0, '自铸属性全摘')

  // stop 后：发布变化（订阅已退）+ nudge（兜底已停）都不得再有动作
  const attrAfterStop = doc.rows[0].getAttribute(PROJTAG_ATTR)
  publishProjectEntry('seedq', ['t260902-01'])
  ok(doc.rows[0].getAttribute(PROJTAG_ATTR) === attrAfterStop, 'stop 后发布变化不再补装（退订生效）')
  const callsBefore = fetchCalls
  h.scan()
  await tick(20)
  ok(fetchCalls === callsBefore, 'stop 后 scan/nudge 不触发 fetch（兜底已停）')
  h.stop()
  ok(true, 'stop 幂等不炸')
}

console.log(`\nSUMMARY pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
