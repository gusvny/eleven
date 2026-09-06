/**
 * suyou-workbench · 上下文折叠件（t260905-04）——通用「渲染面」装饰器。
 *
 * 职责：把带引擎打标（首行 CHARTER_MARKER，同源常量在 ../host/session-charter.ts）
 * 的上下文注入消息在 chat 会话区收成一条可展开小条（「📋 已注入项目背景 · 点击
 * 展开」），点开见全文（占位符已实值化）。未来任何上下文注入（项目简介、文档
 * 引用）带同一标记即走本折叠件——机制在引擎（打标），面在渲染（本模块）。
 *
 * 平台消息气泡锚（方案步 1 取证结论）：隔离台 DOM 探针在本实现环境不可用
 * （stage_docker ensure 容器只读挂载 ENV_FAIL，见工单 evidence），故锚算法取
 * 「内容推导式」而非「结构属性式」——不依赖平台气泡类名/属性（非 css-module
 * 哈希类不赌、也无处可实查）：在 [data-conversation-scroll] 内找 textContent
 * 以 marker 开头的最深元素（markerHost），再沿「唯一元素子链」上爬到父层有
 * 兄弟（=同级还有其他消息）或父层即滚动体的那一层为气泡。降级口径：爬到滚动体
 * 本体（=会话仅此一条消息、无兄弟可分层）则**跳过折叠**——宁可整段照旧，绝不
 * 把整个滚动体藏掉；marker 消失后由孤儿清扫恢复原状。平台气泡结构一旦可实查，
 * 可在 findCharterBubble 里补结构锚短路（属性锚成本与脆性 tradeoff 同 band 第 10 项）。
 *
 * ── 故障模式取舍清单（对照 chat-project-band.ts 头注 10 项范式逐项，t260905-04
 *    review C1 打回定稿；「照搬」字样禁用，逐项「带/不带+理由」）──
 * 1. ✅ 锚丢失显式降级：滚动体 0 命中=hero/卸载瞬态，Observer 不断、不 warn
 *    （同 band）；差异声明：滚动体在场但扫不到 marker=常态（会话无注入物），
 *    同样不 warn 不断 Observer。
 * 2. ⚠️ 负向排除**收窄声明**（非 band 原样）：本模块需在滚动体内自铸一个小条
 *    元素（insertBefore 到气泡父容器，带 CHIP_ATTR 自有属性锚）——这是对 band
 *    「零自铸 DOM」的真实扩面。气泡内部子树零触碰（内容隐藏纯靠气泡自身 attr
 *    +CSS）。**孤儿小条专项（review 条件 A）**：React commit 只清自己 fiber 记
 *    录的节点，外部插入的兄弟不随气泡被清理——会话切换/内容清空后旧小条可残留
 *    为幽灵。对策：小条与气泡的配对记入注册表，每轮回调校验「气泡仍连接 且
 *    classifyContextFold(气泡文本) 仍真」，失效即摘小条+摘气泡属性——幽灵小条
 *    不过夜（无注入物会话开头绝不出现「已注入项目背景」）。
 * 3. ✅ F1 防呆接线：startContextFoldEffect 返回清理函数本身，sidebar 以
 *    useEffect(() => startContextFoldEffect(), []) 接线（t260903-07 F1 实案不复犯）。
 * 4. ✅ 注入防线（attr-only 加码）：marker/文案只进属性值与 textContent，**不进
 *    CSS 选择器**——本模块 CSS 全静态字面量，零插值。
 * 5. ✅ 多锚语义收紧：单会话注入物恰一条（t3 ×1 守卫），命中 N>1=console.warn
 *    一次（疑似误打标信号，与 band「齐设无害」不同，差异声明）；仍全部处理。
 * 6. ✅ 畸形输入生产闸门：classifyContextFold 对非字符串/空串容错为 false；
 *    只认 trimStart 后以 marker 开头（中段提及 marker 的普通消息不误触发）。
 * 7. ✅ 幂等先查再设：属性值/小条存在性/style 文本同值跳过——React 重渲染与
 *    Observer 回调反复触发不抖。
 * 8. ✅ MutationObserver 防重建：滚动体祖先链 childList+subtree；**characterData
 *    不盯**——marker 到场必经 childList 变更，盯 characterData 会让 agent 流式
 *    逐 token 输出每帧触发全文扫描（性能不值，方案 review C1-② 定稿）。回调内
 *    只对新增节点子树扫描（增量），接线时对既有 DOM 跑一次全树兜底（覆盖先于
 *    接线已渲染的历史会话）。removedNodes 不盯——孤儿由第 2 项配对校验兜住。
 * 9. ✅ 全终态回收五项（band 第 9 项是四项，本模块多一项，非照抄）：断 Observer
 *    + 摘 head style + 摘全部自设属性与自铸小条（只摘自己设过/铸过的）+ **解绑
 *    document click 委托（band 明文无监听面，本模块新增件）** + 降级路径 warn
 *    留痕。点击委托防重入=引用计数单例：重复 start 不叠绑（监听器只绑一次），
 *    引用归零才真拆——React StrictMode 双挂（挂→清→挂）与多消费方两安全。
 * 10. ❌ body 级 overlay 贴 rect：不带（同 band 同 tag 理由——属性锚成本与脆性
 *     远低于逐帧 rect 跟随；本模块无逐帧跟随诉求）。
 *
 * 折叠态语义（方案 D2 裁定）：折叠=气泡 display:none（文本仍在 DOM，textContent
 * 可读——journey t2/t3 特征串 ×1 计数零改动兼容）；展开=去折叠态。marker 行展开
 * 态随全文可见（C2 定死「接受+声明」，改 DOM 摘行=childList 入气泡、与 React
 * 重渲染打架，不做）。
 */

import { CHARTER_MARKER } from '../host/session-charter.ts'

/** 折叠态自有属性（气泡上；值='folded'|'open'）。 */
export const FOLD_ATTR = 'data-wb-context-fold'
/** 小条自有属性锚。 */
export const CHIP_ATTR = 'data-wb-context-fold-chip'
/** 自有 style 元素选择器（head 内，React 树之外）。 */
export const FOLD_STYLE_SELECTOR = 'style[data-wb-context-fold-style]'
/** 平台 chat 滚动体锚（同 chat-project-band；平台自声明属性）。 */
const SCROLL_SELECTOR = '[data-conversation-scroll]'

/** 小条文案（折叠态/展开态）。 */
export const CHIP_LABEL_FOLDED = '📋 已注入项目背景 · 点击展开'
export const CHIP_LABEL_OPEN = '📋 已注入项目背景 · 点击收起'

/** 折叠件基础样式（全静态字面量，零插值——取舍第 4 项）。 */
export const FOLD_BASE_CSS = `
[data-wb-context-fold="folded"] { display: none !important; }
[${CHIP_ATTR}] { cursor: pointer; opacity: 0.85; font-size: 12px; }
`

/**
 * 折叠判定（纯函数，smoke 直测）：文本 trimStart 后以 CHARTER_MARKER 开头=是。
 * 非字符串/空串/中段提及 marker → false（取舍第 6 项）。
 */
export function classifyContextFold(text: unknown): boolean {
  return typeof text === 'string' && text.trimStart().startsWith(CHARTER_MARKER)
}

/* ── DOM 面（桩可测：只依赖 querySelectorAll/parentElement/children/textContent/
      insertBefore/remove/setAttribute/getAttribute/removeAttribute/isConnected）── */

type El = {
  textContent?: string
  isConnected?: boolean
  parentElement?: El | null
  children?: El[]
  setAttribute(k: string, v: string): void
  getAttribute(k: string): string | null
  removeAttribute(k: string): void
  remove(): void
  insertBefore(node: El, ref: El | null): void
  querySelectorAll(sel: string): El[]
}

/**
 * 元素子节点集合数组化。真 DOM 的 el.children 是 HTMLCollection（live 集合，
 * 无 .some/.map 等数组方法）——必须 Array.from 落成真数组再集合操作；
 * 直接 `as El[]` 断言会在浏览器运行期炸（arbitrate round1 code-fault 根因，
 * KI 候选「桩集合语义分裂」的修复点）。Array.from 对桩数组/HTMLCollection/
 * NodeList 三形态一律成立，遍历期瞬时快照也消除了 live 集合遍历中 DOM 被改
 * 的失稳面。
 */
function elementChildren(el: El): El[] {
  return Array.from((el.children ?? []) as ArrayLike<El>)
}

/**
 * 在滚动体内定位注入物气泡（纯函数面，可测）：
 * ① 收集全部以 marker 开头的元素，取最深者为 markerHost（无→null）；
 * ② 沿唯一元素子链上爬：父层只有这一个元素子且父层≠滚动体 → 上移；
 *    停在「父层有兄弟（=同级还有其他消息）或父层=滚动体」的那层=气泡。
 * ③ 气泡=滚动体本身（无兄弟可分层）→ null（降级：宁不折，不藏整个滚动体）。
 */
export function findCharterBubble(scroll: El): El | null {
  const all = scroll.querySelectorAll('*') ?? []
  let host: El | null = null
  let hostDepth = -1
  const depthOf = (el: El): number => {
    let d = 0
    let cur: El | null | undefined = el
    while (cur && cur !== (scroll as El)) { cur = cur.parentElement; d++ }
    return d
  }
  for (const el of all) {
    if (classifyContextFold(el.textContent) && !elementChildren(el).some(c => classifyContextFold(c.textContent))) {
      const d = depthOf(el)
      if (d > hostDepth) { host = el; hostDepth = d }
    }
  }
  if (!host) return null
  let bubble = host
  while (bubble.parentElement && bubble.parentElement !== scroll && elementChildren(bubble.parentElement).length === 1) {
    bubble = bubble.parentElement
  }
  if (bubble === scroll || bubble.parentElement === scroll) {
    // 父层=滚动体：气泡即滚动体直接子层，正常；气泡=滚动体本身：降级跳过。
    return bubble === scroll ? null : bubble
  }
  return bubble
}

/* ── 生命周期（引用计数单例 + 全终态回收，取舍第 3/9 项）── */

interface FoldState {
  observer: MutationObserver | null
  doc: Document | null
  /** 小条→锚定气泡 配对注册表（孤儿清扫依据，取舍第 2 项）。 */
  pairs: Map<El, El>
  warnedMulti: boolean
}
let state: FoldState | null = null
let refCount = 0

/** 摘一个配对（小条+气泡属性）。 */
function unpair(st: FoldState, chip: El, bubble: El): void {
  try { chip.remove() } catch { /* 已不在树 */ }
  try { bubble.removeAttribute(FOLD_ATTR) } catch { /* 已不在树 */ }
  st.pairs.delete(chip)
}

/**
 * 对单个滚动体施折叠（幂等）：孤儿清扫 → 定位气泡 → 打折叠态+铸小条。
 * 返回处理结果：'none'=无 marker（常态）| 'folded'=新折/保持 | 'degraded'=爬到滚动体跳过。
 */
export function applyContextFold(scroll: El, doc: Document): 'none' | 'folded' | 'degraded' {
  const st = state
  if (!st) return 'none'
  // ① 孤儿清扫（先于一切）：配对里失效的（小条脱树/气泡脱树/气泡不再以
  //    marker 开头）一律摘——会话切换、消息清空、内容改写后不残留幽灵小条。
  for (const [chip, bubble] of [...st.pairs]) {
    if (chip.isConnected === false || bubble.isConnected === false || !classifyContextFold(bubble.textContent)) {
      unpair(st, chip, bubble)
    }
  }
  // ② 定位气泡
  const bubble = findCharterBubble(scroll)
  if (!bubble) {
    // 滚动体在场但扫不到 marker=常态（取舍第 1 项差异声明），不 warn。
    // 但若本滚动体曾有已折叠气泡而 marker 消失（如内容改写），上面的孤儿清扫
    // 已摘属性——此处只需确认无残留折叠态（罕见：气泡在、非配对小条铸的 attr）。
    return 'none'
  }
  // ③ 幂等：已是本模块折叠态（配对在册）则保持
  const existing = [...st.pairs.entries()].find(([, b]) => b === bubble)
  if (existing) return 'folded'
  // ④ 多锚 warn（取舍第 5 项，每次 start 生命周期只 warn 一次）
  const marked = (scroll.querySelectorAll(`[${FOLD_ATTR}]`) ?? []).length
  if (marked > 0 && !st.warnedMulti) {
    st.warnedMulti = true
    console.warn('[workbench] context-fold：单滚动体命中多条注入物（预期恰一条，疑似误打标）：', marked)
  }
  // ⑤ 打折叠态 + 铸小条（insertBefore 到气泡父容器，气泡内部零触碰）
  bubble.setAttribute(FOLD_ATTR, 'folded')
  const chip = doc.createElement('button') as unknown as El
  chip.setAttribute(CHIP_ATTR, '')
  ;(chip as unknown as { textContent: string }).textContent = CHIP_LABEL_FOLDED
  try {
    bubble.parentElement?.insertBefore(chip, bubble)
  } catch (err) {
    // 铸条失败=回滚属性，宁整段照旧不留半态
    bubble.removeAttribute(FOLD_ATTR)
    console.warn('[workbench] context-fold：小条插入失败，本条不折叠：', err instanceof Error ? err.message : err)
    return 'degraded'
  }
  st.pairs.set(chip, bubble)
  return 'folded'
}

/** 扫全部滚动体（增量回调与全树兜底共用入口）。 */
function scanAll(doc: Document): void {
  const scrolls = doc.querySelectorAll(SCROLL_SELECTOR) ?? []
  if (scrolls.length === 0) return
  for (const scroll of scrolls) applyContextFold(scroll as unknown as El, doc)
}

/** 小条点击（document 级委托，取舍第 9 项；展开/收起同点切换）。 */
function onChipClick(ev: Event): void {
  const st = state
  if (!st) return
  const target = ev.target as El | null
  if (!target || typeof (target as unknown as { closest?: unknown }).closest !== 'function') return
  const chip = (target as unknown as { closest(sel: string): El | null }).closest(`[${CHIP_ATTR}]`)
  if (!chip) return
  const bubble = st.pairs.get(chip as El)
  if (!bubble) return
  const folded = bubble.getAttribute(FOLD_ATTR) === 'folded'
  bubble.setAttribute(FOLD_ATTR, folded ? 'open' : 'folded')
  ;(chip as unknown as { textContent: string }).textContent = folded ? CHIP_LABEL_OPEN : CHIP_LABEL_FOLDED
}

/**
 * 启动折叠件（引用计数单例）：head 注入 style + Observer（document 子树
 * childList）+ document click 委托；接线时先全树兜底扫一次。二次调用不叠绑
 * （监听器只绑一次），返回值=清理函数（引用归零才真拆，取舍第 9 项）。
 */
export function startContextFold(opts: { doc?: Document } = {}): () => void {
  const doc = opts.doc ?? (typeof document !== 'undefined' ? document : null)
  if (!doc) {
    console.warn('[workbench] context-fold：无 document 可挂，软退化不折叠')
    return () => {}
  }
  refCount++
  if (!state) {
    const st: FoldState = { observer: null, doc, pairs: new Map(), warnedMulti: false }
    state = st
    // style 幂等注入（取舍第 7 项）
    if (!doc.querySelector(FOLD_STYLE_SELECTOR)) {
      const style = doc.createElement('style')
      style.setAttribute('data-wb-context-fold-style', '')
      ;(style as unknown as { textContent: string }).textContent = FOLD_BASE_CSS
      doc.head.appendChild(style)
    }
    // 全树兜底扫（覆盖接线前已渲染的历史会话，取舍第 8 项）
    scanAll(doc)
    // Observer：document 子树 childList；回调增量守门——只对「新增了元素节点」
    // 或「新增文本节点自带 marker」的批次扫（agent 流式逐 token 换文本节点不含
    // marker，在此被挡，取舍第 8 项性能口径落地）。
    const observer = new MutationObserver(muts => {
      let interesting = false
      for (const m of muts) {
        for (const n of m.addedNodes) {
          if (n.nodeType === 1 || (typeof n.textContent === 'string' && n.textContent.includes(CHARTER_MARKER))) {
            interesting = true
            break
          }
        }
        if (interesting) break
      }
      if (!interesting) return
      scanAll(st.doc as Document)
    })
    observer.observe(doc.documentElement ?? doc, { childList: true, subtree: true })
    st.observer = observer
    doc.addEventListener('click', onChipClick)
  }
  let stopped = false
  return () => {
    if (stopped) return
    stopped = true
    refCount--
    if (refCount > 0 || !state) return
    const st = state
    try { st.observer?.disconnect() } catch { /* 幂等 */ }
    try { st.doc?.removeEventListener('click', onChipClick) } catch { /* 幂等 */ }
    for (const [chip, bubble] of [...st.pairs]) unpair(st, chip, bubble)
    try {
      const style = st.doc?.querySelector(FOLD_STYLE_SELECTOR)
      if (style) st.doc?.head.removeChild(style)
    } catch { /* 幂等 */ }
    state = null
  }
}

/** 降级路径 warn 留痕（stop 收口时统一，取舍第 9 项第五项）。 */
export function stopContextFoldWithWarn(stop: () => void): void {
  try { stop() } catch (err) {
    console.warn('[workbench] context-fold：stop 异常（回收不完整风险）：', err instanceof Error ? err.message : err)
  }
}

/** sidebar 接线入口（F1：返回清理函数本身，取舍第 3 项）。 */
export function startContextFoldEffect(): () => void {
  return startContextFold()
}
