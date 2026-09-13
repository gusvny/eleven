/**
 * sandbar-workbench · 全局 chat 消息项目 tag 装饰器（t260903-07 工单②）。
 *
 * 渲染机制（方案 v2 R1 换轨后的定稿，验收硬约束）：
 *   **零 childList 侵入 React 托管容器**——只给平台渲染的用户消息行**设置自有属性**
 *   `data-wb-projtag="<projectKey>"`，视觉全在注入 head 的自有 <style> 里
 *   （CSS ::before + attr() 出 chip 文本与着色）。插件卸载时 style 元素与全部
 *   自有属性摘除，出厂树恢复原样。
 *   平台锚=chat 行自声明的属性（非 css-module 哈希类，实查 dsh-client-ui-conversation
 *   产物 client.js：每条 flow 行 `div[data-chat-anchor-key][data-chat-flow-kind="<kind>"]`，
 *   用户消息行 kind="user"）——结构性特征写死为常量并注明出处。
 *
 * 先例借鉴模式取舍（对照 sidebar.tsx useHideFactoryNewSession /
 * metrics-anchor.ts / metrics-entry.tsx 三先例）：
 * - ✅ 锚定负向排除（OWN_SUBTREE_MARKER 教训）：正向只认平台 data-chat-* 属性；
 *   候选行 closest('[data-wb-projtag-scope]')（本装饰器自留作用域标记位）命中即跳过，
 *   杜绝误伤自有/同形节点。
 * - ✅ 锚丢失显式降级：扫描前验 document isConnected；失联置 stopped、断 Observer、
 *   warn 一次后停手——不进入反复重探风暴。
 * - ✅ 全终态回收五项：①断 MutationObserver；②退订索引变更通知（t260911-06 新增，
 *   onProjectTagIndexChange 的退订函数）；③兜底自取句柄 stop（定时器清理+nudge 停）；
 *   ④摘自铸物：head 里的 style 元素 remove + 自记账 Set 里全部已设属性 removeAttribute
 *   （只摘自己设过的，绝不动出厂节点）；⑤降级广播：console.warn 留痕（不新增横幅面）。
 * - ✅「移除自铸节点」语义（非「还原出厂值」）：本机制不动任何出厂属性，故无还原义务，
 *   卸载=移除自铸物——与 useHideFactoryNewSession 的「还原出厂 display」是两类，不混写。
 * - ✅ bounded 上溯 ≤10 层：本机制按属性直接 querySelectorAll，无上溯（不带，理由注明）。
 * - ✅ 幂等先查再设：属性同值跳过；style 文本同值跳过——React 重渲染反复触发也不抖。
 * - ✅ MutationObserver 兜防复活：盯 body 子树 childList（同 metrics-entry 先例），
 *   React 重建行节点后重设属性；attributes 不盯（自有属性无人动）。
 * - ✅ 索引数据落地即补扫（t260911-06，260911 夜「新行无 chip、旧行有」间歇红收口）：
 *   订阅索引变更通知（外部发布/nudge 成功且数据实际变化 → scan）+ scan 发现
 *   「带票号未归属」的新引用时按需 nudge 单次强取（有界：在途去重/最小间隔/
 *   按引用去重）——堵住「数据到了没人扫、新票映射要干等下个 10s 轮询」两缺口。
 * - ❌ body 级 overlay 贴 rect（metrics-entry 最终形态）：不带——tag 需逐消息行贴装且
 *   随流式增长移动，fixed overlay 逐帧跟 rect 成本与脆性远高于属性锚。
 *
 * 范围收窄（方案 v3 R7）：只装饰用户消息行（assistant/工具行 v1 不 tag）；
 * 扩展由后续票按锚稳定性结论决定。
 *
 * 归属判定（对方案 v3 R5 的一处实现期收窄，如实声明）：
 *   ①消息文本含工单 id 引用（/t\\d{6}-\\d{2}/）→ ticket→project 映射（索引单态）；
 *   ②方案的「会话 cwd → 项目」兜底**未实现**——平台 client 面的 sessions 快照
 *   （SessionListState，实查类型）不含 cwd，chat DOM 亦无 cwd 出处，插件内无可靠
 *   来源；强行猜测违反「不造隐形缺省」。缺失即不渲染 tag（验收声明的行为）。
 *   派活/工单上下文类消息本就含工单 id 引用，多项目区分主场景已覆盖。
 */

import { projectColor, projectTagCssRules, isProjectKeyLike } from '../shared/project-color.ts'
import { onProjectTagIndexChange, readProjectTagIndex, startProjectIndexFallback } from './project-tag-index.ts'

/** 自有属性名（tag 值=project key）。 */
export const PROJTAG_ATTR = 'data-wb-projtag'
/** 自有 style 元素选择器（head 内，React 树之外）。 */
const STYLE_SELECTOR = 'style[data-wb-projtag-style]'
/** 本装饰器作用域标记（负向排除用；本插件任何 DOM 都不设它，纯防御位）。 */
const OWN_SCOPE_ATTR = 'data-wb-projtag-scope'
/** 平台 chat flow 行锚（出处：dsh-client-ui-conversation lib/client.js，data-chat-* 为平台自声明属性）。 */
const USER_ROW_SELECTOR = '[data-chat-anchor-key][data-chat-flow-kind="user"]'
/** 工单 id 引用（t260903-07 口径；全局匹配，一行多工单取第一个命中）。 */
const TICKET_REF_RE = /t\d{6}-\d{2}/

/** 消息文本 → 项目 key（映射缺失/无引用 → null=不渲染 tag，声明行为）。 */
export function projectForText(text: string, projectByTicket: ReadonlyMap<string, string>): string | null {
  if (typeof text !== 'string' || text === '') return null
  const m = text.match(TICKET_REF_RE)
  if (!m) return null
  const key = projectByTicket.get(m[0])
  return isProjectKeyLike(key) ? key : null
}

/**
 * 对一个扫描根内全部用户消息行施加/回收 tag 属性（纯 DOM 逻辑，smoke 用自有桩直测）。
 * 幂等：同值跳过；映射消失的行回收属性。返回本次实际写动的行数（观测用）。
 */
export function applyProjectTags(root: ParentNode, projectByTicket: ReadonlyMap<string, string>): number {
  let touched = 0
  let rows: Element[]
  try {
    rows = Array.from(root.querySelectorAll(USER_ROW_SELECTOR))
  } catch {
    return 0
  }
  for (const row of rows) {
    const el = row as Element
    if (typeof el.setAttribute !== 'function' || typeof el.getAttribute !== 'function') continue
    // 负向排除（OWN_SUBTREE_MARKER 教训）：本装饰器作用域内的行不碰。
    if (el.closest(`[${OWN_SCOPE_ATTR}]`) !== null) continue
    const key = projectForText(el.textContent ?? '', projectByTicket)
    const cur = el.getAttribute(PROJTAG_ATTR)
    if (key === null) {
      if (cur !== null) { el.removeAttribute(PROJTAG_ATTR); touched++ }
      continue
    }
    if (cur !== key) { el.setAttribute(PROJTAG_ATTR, key); touched++ }
  }
  return touched
}

/**
 * 找第一个「带工单号引用却未归属」的用户行引用（t260911-06 新增，nudge 判据）。
 * 仅统计**当前未装饰**的行——已装饰行不参与；映射里查不到该引用才返回。
 * 纯 DOM 逻辑，UT 桩直测。返回 null=没有这种行（不 nudge）。
 */
export function firstUnmappedTicketRef(
  root: ParentNode,
  projectByTicket: ReadonlyMap<string, string>,
): string | null {
  let rows: Element[]
  try {
    rows = Array.from(root.querySelectorAll(USER_ROW_SELECTOR))
  } catch {
    return null
  }
  for (const row of rows) {
    const el = row as Element
    if (typeof el.getAttribute !== 'function') continue
    if (el.closest(`[${OWN_SCOPE_ATTR}]`) !== null) continue
    if (el.getAttribute(PROJTAG_ATTR) !== null) continue
    const m = (typeof el.textContent === 'string' ? el.textContent : '').match(TICKET_REF_RE)
    if (m && !projectByTicket.has(m[0])) return m[0]
  }
  return null
}

export interface ChatProjectTagOptions {
  fetchImpl: typeof fetch
  /** 注入面（生产=document；smoke 传自有桩）。 */
  doc?: Document
  /** 兜底自取选项透传（smoke 传小间隔/少次数）。 */
  fallback?: { initialDelayMs?: number; retryIntervalMs?: number; maxAttempts?: number }
}

export interface ChatProjectTagHandle {
  /** 手动触发一次扫描（测试/诊断用）。 */
  scan(): void
  /** 全终态回收（四项清单见文件头）。幂等。 */
  stop(): void
}

/**
 * useEffect 形态入口（F1 防呆）：返回的是**清理函数**本身，
 * 可直接 `useEffect(() => startChatProjectTagEffect(...), [])`——useEffect 只把
 * 返回函数登记为 cleanup，返回 handle 对象会被静默忽略（F1 死因：sidebar 直接
 * 返回 handle → 卸载零回收）。本入口从形状上消灭该陷阱；新接线一律走这里，
 * startChatProjectTag 保留给需要 scan 面的调用方（smoke/诊断）。
 */
export function startChatProjectTagEffect(opts: ChatProjectTagOptions): () => void {
  const h = startChatProjectTag(opts)
  return () => h.stop()
}

/**
 * 启动装饰器：head 挂自有 style + body 子树 childList Observer + 索引兜底自取。
 * 返回 handle，卸载方（sidebar useEffect cleanup）必须调用 stop()。
 */
export function startChatProjectTag(opts: ChatProjectTagOptions): ChatProjectTagHandle {
  const doc = opts.doc ?? (typeof document !== 'undefined' ? document : null)
  if (!doc || doc.documentElement === null) {
    console.warn('[workbench] chat 项目 tag 装饰器无 document 可挂，软退化不渲染')
    return { scan() {}, stop() {} }
  }

  // ── 自有 style（head 内；head 在 React 树之外，同 index.tsx CSS_TAG_ID 先例）──
  let style = doc.querySelector(STYLE_SELECTOR)
  if (style === null) {
    style = doc.createElement('style')
    style.setAttribute('data-wb-projtag-style', '')
    doc.head.appendChild(style)
  }
  let lastCss = ''
  const refreshCss = (): void => {
    const idx = readProjectTagIndex()
    const css = projectTagCssRules([...idx.projectDirs.keys()])
    if (css !== lastCss) {
      lastCss = css
      style!.textContent = css
    }
  }
  refreshCss()

  // ── 扫描（幂等；锚失联降级）──
  let stopped = false
  let warnedDisconnected = false
  // nudge 按引用去重：同一票号只强取一次（假票号/真未建票不无限重试；新引用才再取）。
  const nudgedRefs = new Set<string>()
  const scan = (): void => {
    if (stopped) return
    if (!doc.documentElement.isConnected) {
      if (!warnedDisconnected) {
        warnedDisconnected = true
        console.warn('[workbench] chat 项目 tag 装饰器：document 已失联，停手（软退化不渲染）')
      }
      observer.disconnect()
      return
    }
    refreshCss()
    const idx = readProjectTagIndex()
    applyProjectTags(doc, idx.projectByTicket)
    // t260911-06：索引已有数据但行里的票号归属不了 = 数据源落后于刚建成的新票
    //（此前只能干等侧栏下一个 10s 轮询周期，负载窗内即「新行无 chip、旧行有」
    // 的间歇红）。按需单次强取：取到 → publish → 变更通知 → 本装饰器重扫补装。
    if (idx.hasData) {
      const ref = firstUnmappedTicketRef(doc, idx.projectByTicket)
      if (ref !== null && !nudgedRefs.has(ref)) {
        nudgedRefs.add(ref)
        indexFallback.nudge()
      }
    }
  }

  // ── Observer 兜防复活：React 重建行节点后重设（body 子树 childList，同 metrics-entry 先例）──
  const observer = new MutationObserver(scan)
  observer.observe(doc.body ?? doc.documentElement, { childList: true, subtree: true })

  // ── 索引变更订阅（t260911-06 补缺）：外部发布（侧栏轮询/nudge 成功）数据实际
  //    变化即重扫——此前数据落地后无人重扫，行是否补装饰全看碰巧的无关 DOM 变动。──
  const unsubscribeIndexChange = onProjectTagIndexChange(() => { if (!stopped) scan() })

  // ── 索引兜底自取（侧栏未挂载/窄模式时 60s 低频；外部发布即自停）──
  const indexFallback = startProjectIndexFallback({
    fetchImpl: opts.fetchImpl,
    initialDelayMs: opts.fallback?.initialDelayMs ?? 0,
    retryIntervalMs: opts.fallback?.retryIntervalMs,
    maxAttempts: opts.fallback?.maxAttempts,
    // 兜底拉到数据后立即刷 CSS 并重扫（不留额外轮询定时器）。
    onData: () => { if (!stopped) scan() },
  })

  return {
    scan,
    stop() {
      if (stopped) return
      stopped = true
      observer.disconnect()
      unsubscribeIndexChange()
      indexFallback.stop()
      // 摘自铸物：style 元素 + 全部已设自有属性（只动自己的）。
      style.remove()
      for (const row of Array.from(doc.querySelectorAll(`[${PROJTAG_ATTR}]`))) {
        row.removeAttribute(PROJTAG_ATTR)
      }
    },
  }
}
