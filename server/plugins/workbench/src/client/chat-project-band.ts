/**
 * sandbar-workbench · 全局 chat 项目色带装饰器（票② R7，t260904-05）。
 *
 * 视觉：右栏 chat 滚动体顶部 border-top 3px 项目色横贯 + 右上角 sticky 零高
 * 角标显项目 key（「色+名」双通道，10px 等宽同色，pointer-events:none）。
 * 分工：色带管 **chat 归属**；chat-project-tag.ts（已上线）管**消息级工单
 * 引用**，两者互不动。
 *
 * 渲染机制（对齐 chat-project-tag.ts 纪律，零 childList 侵入 React 托管容器）：
 * 只给平台渲染的滚动体**设置自有属性** `data-wb-chat-projband="<projectKey>"`，
 * 视觉全在注入 head 的自有 <style> 里（CSS 属性选择器 + ::after attr() 出角标
 * 文本与着色）。插件卸载时 style 元素与全部自有属性摘除，出厂树恢复原样。
 * 平台锚=chat 滚动体自声明属性 `[data-conversation-scroll]`（出处：安装树
 * dsh-client-ui-conversation/lib/client.js 6 处实锤，ConversationRoot 滚动体；
 * 非 css-module 哈希类，勿用类名锚）。
 *
 * 归属判定**不在本模块**：装饰器只吃显式入参 setChatProjectBand(key|null)，
 * 推导在 sidebar.tsx（listState.current → 账册 project 查表）。不在册（工单
 * 会话/磁盘存量/blank hero）→ null=摘属性不渲染——声明行为，不造隐形缺省。
 *
 * ── 故障模式取舍清单（对照 chat-project-tag.ts 头注 9 项范式展开为 10 项，
 *    逐项「带/不带」+理由）──
 * 1. ✅ 锚丢失显式降级（分层）：document 失联（isConnected=false）=永久停手，
 *    断 Observer + warn 一次（同 tag）；**锚 0 命中=瞬态常态**（blank hero /
 *    会话卸载时滚动体不在场，开 chat 后回归）——本轮回调摘全部已设属性即停手，
 *    Observer 保持连接，锚再现时下一轮回调自然重设（C4 修订：不得断 Observer，
 *    否则 hero↔chat 切换后色带永久失明）。0 锚不 warn（常态不噪音）。
 * 2. ✅ 负向排除：**声明不需要**——本模块零自铸 DOM 入 React 树（仅 head 里
 *    一个 style），插件任何节点不可能命中平台自声明属性 [data-conversation-scroll]，
 *    误伤面不存在；此结论即声明（OWN_SUBTREE_MARKER 教训的对照面）。
 * 3. ✅ F1 防呆接线：startChatProjectBandEffect 返回清理函数本身，sidebar 以
 *    `useEffect(() => startChatProjectBandEffect(...), [])` 接线——直接返回
 *    handle 会被 useEffect 静默忽略→卸载零回收（t260903-07 F1 实案）。
 * 4. ✅ 注入防线（attr()-only 免疫）：key 只进属性值与 ::after 的 attr()
 *    content，**不拼进 CSS 选择器**——引号/反斜杠等字符无注入面（比 tag 的
 *    选择器引号双保险更强的免疫设计，差异声明）；生产闸门另设：set 前过
 *    isProjectKeyLike（畸形→按 null 摘除），账册是 localStorage 外部输入。
 * 5. ✅ 多锚语义：命中 N 个=全部设同属性（平台滚动体应唯一，N>1 属异常但齐设
 *    无害）；命中 0 个=见第 1 项。无「首个」偏好。
 * 6. ✅ 畸形 key 生产闸门：见第 4 项 isProjectKeyLike；smoke 另带 localStorage
 *    手改坏 project 用例（畸形输入用例纪律，桩复现不靠真外部源）。
 * 7. ✅ 幂等先查再设：属性同值跳过、style 文本同值跳过、key=null 且无属性时
 *    跳过——React 重渲染/Observer 回调反复触发不抖。
 * 8. ✅ MutationObserver 防重建：body 子树 childList（同 tag/metrics-entry
 *    先例），React 重建滚动体后重设属性；attributes 不盯（自有属性无人动）。
 * 9. ✅ 全终态回收：stop() 幂等四项=断 Observer + 摘 head style + 摘全部已设
 *    自有属性（只摘自己设过的）+ 降级路径 warn 留痕。**无** window/document
 *    级监听、**无**定时器/轮询——band 数据源是账册 store（sidebar 推导后显式
 *    调 set），不需要 tag 的 fetch 索引兜底自取（差异声明）。
 * 10. ❌ body 级 overlay 贴 rect：不带（同 tag 理由——属性锚成本与脆性远低于
 *     逐帧 rect 跟随）。
 */

import { projectColor, isProjectKeyLike } from '../shared/project-color.ts'

/** 自有属性名（值=project key）。 */
export const PROJBAND_ATTR = 'data-wb-chat-projband'
/** 自有 style 元素选择器（head 内，React 树之外）。 */
const STYLE_SELECTOR = 'style[data-wb-chat-projband-style]'
/** 平台 chat 滚动体锚（出处见文件头注；平台自声明属性，非 css-module 类名）。 */
const SCROLL_SELECTOR = '[data-conversation-scroll]'

/** hex → rgba() 字符串（16% 透明底等用途；避免 color-mix 兼容性赌注）。 */
export function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

/** 色带基础样式（注入 head 的自有 style；attr()-only，key 不进选择器）。 */
export const PROJBAND_BASE_CSS = `
[${PROJBAND_ATTR}] { border-top: 3px solid var(--wb-projband-color, transparent); position: relative; }
[${PROJBAND_ATTR}]::after {
  content: attr(${PROJBAND_ATTR});
  position: sticky; top: 0; float: right; margin-right: 8px; height: 0;
  display: block; font-size: 10px; line-height: 1.4; white-space: nowrap;
  font-family: var(--ds-font-family-code, monospace);
  color: var(--wb-projband-color, transparent);
  pointer-events: none; opacity: 0.9;
}
`

/**
 * 设/摘色带属性（纯 DOM 逻辑，smoke 用自有桩直测；幂等）。key=null/畸形=
 * 摘除（不在册不渲染，声明行为）。返回本次实际写动的节点数（观测用）。
 * N 个锚全部齐设（多锚语义见头注第 5 项）。
 */
export function applyProjectBand(root: ParentNode, key: string | null): number {
  let touched = 0
  let els: Element[]
  try {
    els = Array.from(root.querySelectorAll(SCROLL_SELECTOR))
  } catch {
    return 0
  }
  const valid = isProjectKeyLike(key) ? (key as string) : null
  for (const el of els) {
    if (typeof el.setAttribute !== 'function' || typeof el.getAttribute !== 'function') continue
    const cur = el.getAttribute(PROJBAND_ATTR)
    if (valid === null) {
      if (cur !== null) { el.removeAttribute(PROJBAND_ATTR); touched++ }
      continue
    }
    if (cur !== valid) {
      el.setAttribute(PROJBAND_ATTR, valid)
      // 逐项目着色走 CSS 变量，随属性同节点设置（不拼选择器，attr()-only）
      if (typeof (el as HTMLElement).style?.setProperty === 'function') {
        ;(el as HTMLElement).style.setProperty('--wb-projband-color', projectColor(valid))
      }
      touched++
    }
  }
  return touched
}

export interface ChatProjectBandOptions {
  /** 注入面（生产=document；smoke 传自有桩）。 */
  doc?: Document
}

export interface ChatProjectBandHandle {
  /** 显式设归属（sidebar 归属推导 effect 调用；null=摘除）。 */
  set(key: string | null): void
  /** 全终态回收（四项清单见头注第 9 项）。幂等。 */
  stop(): void
}

/**
 * useEffect 形态入口（F1 防呆，见头注第 3 项）：返回清理函数本身。
 */
export function startChatProjectBandEffect(opts: ChatProjectBandOptions = {}): () => void {
  const h = startChatProjectBand(opts)
  return () => h.stop()
}

/** 当前活跃 handle（模块级单例引用；sidebar 的归属推导 effect 走下面这个
 *  免实例透传入口，不必自己持有 handle——单插件单装饰器，多启后写后者）。 */
let active: ChatProjectBandHandle | null = null

/**
 * 模块级入口：设/摘色带归属（sidebar 由 listState.current → 账册 project 推导
 * 后调用；key=null=不在册，摘除不渲染——声明行为）。装饰器未启动时静默 no-op
 * （窄模式/未挂载无消费面，不造隐形报错面）。
 */
export function setChatProjectBand(key: string | null): void {
  active?.set(key)
}

/**
 * 启动装饰器：head 挂自有 style + body 子树 childList Observer。
 * 返回 handle：set(key|null) 供 sidebar 归属推导调用；stop() 卸载必调。
 */
export function startChatProjectBand(opts: ChatProjectBandOptions = {}): ChatProjectBandHandle {
  const doc = opts.doc ?? (typeof document !== 'undefined' ? document : null)
  if (!doc || doc.documentElement === null) {
    console.warn('[workbench] chat 项目色带装饰器无 document 可挂，软退化不渲染')
    return { set() {}, stop() {} }
  }

  // ── 自有 style（head 内）──
  let style = doc.querySelector(STYLE_SELECTOR)
  if (style === null) {
    style = doc.createElement('style')
    style.setAttribute('data-wb-chat-projband-style', '')
    doc.head.appendChild(style)
  }
  if (style.textContent !== PROJBAND_BASE_CSS) style.textContent = PROJBAND_BASE_CSS

  // 当前归属（sidebar 推导结果；Observer 回调按它重设，兜防 React 重建滚动体）。
  let current: string | null = null
  let stopped = false
  let warnedDisconnected = false

  const scan = (): void => {
    if (stopped) return
    if (!doc.documentElement.isConnected) {
      // document 级失联：永久停手（同 tag L153-161 口径），warn 一次。
      if (!warnedDisconnected) {
        warnedDisconnected = true
        console.warn('[workbench] chat 项目色带装饰器：document 已失联，停手（软退化不渲染）')
      }
      observer.disconnect()
      return
    }
    // 锚 0 命中=瞬态常态（blank hero / 会话卸载）：摘已设属性即停手，Observer
    // 保持连接（C4：不得断，否则 hero↔chat 切换后色带永久失明）；不 warn。
    applyProjectBand(doc, current)
  }

  const observer = new MutationObserver(scan)
  observer.observe(doc.body ?? doc.documentElement, { childList: true, subtree: true })

  const handle: ChatProjectBandHandle = {
    set(key: string | null) {
      current = isProjectKeyLike(key) ? (key as string) : null
      scan()
    },
    stop() {
      if (stopped) return
      stopped = true
      if (active === handle) active = null
      observer.disconnect()
      // 摘自铸物：style 元素 + 全部已设自有属性（只动自己的）。
      style.remove()
      try {
        for (const el of Array.from(doc.querySelectorAll(`[${PROJBAND_ATTR}]`))) {
          el.removeAttribute(PROJBAND_ATTR)
          if (typeof (el as HTMLElement).style?.removeProperty === 'function') {
            ;(el as HTMLElement).style.removeProperty('--wb-projband-color')
          }
        }
      } catch { /* 摘除面已随 document 失联，无可回收 */ }
    },
  }
  active = handle
  return handle
}
