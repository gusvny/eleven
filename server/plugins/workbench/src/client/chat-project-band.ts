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
 * 9. Full-terminal-state cleanup: stop() is idempotent = disconnect the
 *    Observer + remove the head style + remove every self-set attribute (only
 *    our own) + remove the band overlay element and the window-level
 *    scroll/resize listeners + warn on degraded paths.
 * 10. Body-level overlay pinned to the anchor rect: carried since UI-5
 *     (t261005-06 identity band) - the standing band of design 2.1 (14% band
 *     face + 3px bottom border + project key + handle + Sessions menu) needs
 *     an interactive element; a pure ::after cannot hold one. The overlay
 *     hangs off body (no child inserted into the React-managed subtree, so
 *     the zero-childList-intrusion discipline holds), position:fixed over the
 *     anchor rect, updated on capture scroll + resize (listeners fully
 *     cleaned up). Degradation: zero anchors = the overlay hides
 *     (display:none); it never disappears silently nor escapes the column.
 */

import { projectColor, isProjectKeyLike } from '../shared/project-color.ts'

/** 自有属性名（值=project key）。 */
export const PROJBAND_ATTR = 'data-wb-chat-projband'
/** Session-handle attribute (UI-5: the band's second text channel; value = short code or executor). */
export const PROJBAND_HANDLE_ATTR = 'data-wb-chat-projband-handle'
/** Identity-band overlay attribute (body-level element marker; value = project key). */
export const PROJBAND_BAND_ATTR = 'data-wb-chat-band'
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

/** Band base styles (self-owned style injected into head; attr()-only, the
 *  key never enters a selector). UI-5 upgrade: the three design-2.1 channels
 *  all hang off the one --wb-projband-color variable - the 3px top border
 *  (the old band face), the 5% column wash (background color-mix) and the
 *  corner tag color (::after), so one project switch moves all three in the
 *  same frame (integration scenario A4 contract: hits >= 3). */
export const PROJBAND_BASE_CSS = `
[${PROJBAND_ATTR}] { border-top: 3px solid var(--wb-projband-color, transparent); position: relative;
  background: color-mix(in srgb, var(--wb-projband-color, transparent) 5%, transparent); }
[${PROJBAND_ATTR}]::after {
  content: attr(${PROJBAND_HANDLE_ATTR}) " \\00b7 " attr(${PROJBAND_ATTR});
  position: sticky; top: 0; float: right; margin-right: 8px; height: 0;
  display: block; font-size: 10px; line-height: 1.4; white-space: nowrap;
  font-family: var(--ds-font-family-code, monospace);
  color: var(--wb-projband-color, transparent);
  pointer-events: none; opacity: 0.9;
}
[${PROJBAND_ATTR}]:not([${PROJBAND_HANDLE_ATTR}])::after { content: attr(${PROJBAND_ATTR}); }
`

/**
 * Identity-band overlay styles (design 2.1: a 32px band face at 14% project
 * color + a 3px solid bottom border + a 9px color chip + the project key +
 * the handle + a Sessions control; fixed over the anchor rect, zero anchors =
 * hidden).
 */
export const PROJBAND_BAND_CSS = `
[${PROJBAND_BAND_ATTR}] { position: fixed; z-index: 90; height: 32px;
  display: flex; align-items: center; gap: 6px; padding: 0 10px;
  background: color-mix(in srgb, var(--wb-projband-color, transparent) 14%, var(--dsw-alias-bg-primary, #fff));
  border-bottom: 3px solid var(--wb-projband-color, transparent);
  font-size: 12px; font-weight: 600; pointer-events: auto; }
[${PROJBAND_BAND_ATTR}][data-hidden] { display: none; }
[${PROJBAND_BAND_ATTR}] .wb-projband-chip { width: 9px; height: 9px; flex: none;
  background: var(--wb-projband-color, transparent); }
[${PROJBAND_BAND_ATTR}] .wb-projband-key { font-weight: 600; }
[${PROJBAND_BAND_ATTR}] .wb-projband-handle { font-family: var(--ds-font-family-code, monospace);
  font-size: 11px; font-weight: 400; opacity: 0.75; }
[${PROJBAND_BAND_ATTR}] .wb-projband-sessions { font: inherit; font-size: 11px;
  font-weight: 400; padding: 2px 8px; cursor: pointer; border-radius: 4px;
  border: 1px solid var(--wb-projband-color, transparent); background: none; }
[${PROJBAND_BAND_ATTR}] .wb-projband-menu { position: absolute; top: 34px; right: 0;
  min-width: 180px; max-height: 240px; overflow-y: auto; padding: 4px;
  border-radius: 6px; background: var(--dsw-alias-bg-primary, #fff);
  border: 1px solid var(--wb-projband-color, transparent);
  box-shadow: 0 8px 24px rgba(0,0,0,0.35); display: none; }
[${PROJBAND_BAND_ATTR}][data-menu-open] .wb-projband-menu { display: block; }
[${PROJBAND_BAND_ATTR}] .wb-projband-item { display: flex; align-items: center; gap: 6px;
  width: 100%; padding: 3px 6px; font: inherit; font-size: 11.5px; cursor: pointer;
  border: none; background: none; text-align: left; border-radius: 4px; }
[${PROJBAND_BAND_ATTR}] .wb-projband-item:hover { background: rgba(127,127,127,0.15); }
[${PROJBAND_BAND_ATTR}] .wb-projband-item .wb-projband-handle { flex: none; }
[${PROJBAND_BAND_ATTR}] .wb-projband-new { color: var(--wb-projband-color, inherit);
  border-top: 1px solid rgba(127,127,127,0.25); margin-top: 2px; }
`

/**
 * 设/摘色带属性（纯 DOM 逻辑，smoke 用自有桩直测；幂等）。key=null/畸形=
 * removal (not-in-ledger renders nothing, declared behavior; the handle
 * attribute goes with it). Returns the number of nodes actually written this
 * call (for observation). All N anchors are set together (header item 5).
 */
export function applyProjectBand(root: ParentNode, key: string | null, handle?: string): number {
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
      if (cur !== null || el.getAttribute(PROJBAND_HANDLE_ATTR) !== null) {
        el.removeAttribute(PROJBAND_ATTR)
        el.removeAttribute(PROJBAND_HANDLE_ATTR)
        touched++
      }
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
    // Handle channel (idempotent: same value skipped; undefined = only ensure the attribute is absent)
    const hCur = el.getAttribute(PROJBAND_HANDLE_ATTR)
    const hNext = typeof handle === 'string' && handle !== '' && !handle.includes('"') ? handle : null
    if (hNext === null) {
      if (hCur !== null) { el.removeAttribute(PROJBAND_HANDLE_ATTR); touched++ }
    } else if (hCur !== hNext) {
      el.setAttribute(PROJBAND_HANDLE_ATTR, hNext)
      touched++
    }
  }
  return touched
}

/** Data face of the band Sessions menu (supplied by the sidebar; plain data, rendered inside the decorator). */
export interface BandSessionItem {
  id: string
  /** Display handle (short code or executor). */
  handle: string
  /** Title (the title -> displayTitle -> id fallback is the caller's job). */
  title: string
  /** Raw display title for the tooltip (t261008-01, Measure 1): when `title`
   *  is the session handle standing in for a charter-injection raw title, the
   *  raw text stays reachable here (rendered as the row's `title` attribute).
   *  Absent = no tooltip beyond the handle. */
  rawTitle?: string
  active: boolean
}

export interface ChatProjectBandOptions {
  /** 注入面（生产=document；smoke 传自有桩）。 */
  doc?: Document
  /** Sessions menu data source (absent = the menu button is not rendered - declared degradation, no dead button). */
  getSessions?: () => BandSessionItem[]
  /** The menu's + New session action (absent = the item is not rendered). */
  onNewSession?: () => void
  /** The menu's open-session action (absent = entries are not rendered; only + New session stays). */
  onOpenSession?: (id: string) => void
}

export interface ChatProjectBandHandle {
  /** 显式设归属（sidebar 归属推导 effect 调用；null=摘除）。 */
  set(key: string | null): void
  /** UI-5 form: ownership and the current session handle go out together. */
  setInfo(info: { project: string | null; handle?: string }): void
  /** Full-terminal-state cleanup (header item 9 checklist). Idempotent. */
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

/** UI-5 entry: project ownership and the current session handle go out together (called by the sidebar after derivation). */
export function setChatProjectBandInfo(info: { project: string | null; handle?: string }): void {
  active?.setInfo(info)
}

/** Identity-band overlay element marker (stop cleanup / test assertions). */
export const BAND_STYLE_SELECTOR = 'style[data-wb-chat-band-style]'

/**
 * Start the decorator: a self-owned style in head (the container attribute
 * face + the identity-band overlay face) + a body-subtree childList Observer
 * + a body-level overlay element (the design-2.1 band; pinned to the anchor
 * rect, following capture scroll + resize, listeners and element fully
 * cleaned up). Returns a handle: set/setInfo for the sidebar ownership
 * derivation; stop() is mandatory on unload.
 */
export function startChatProjectBand(opts: ChatProjectBandOptions = {}): ChatProjectBandHandle {
  const doc = opts.doc ?? (typeof document !== 'undefined' ? document : null)
  if (!doc || doc.documentElement === null) {
    console.warn('[workbench] chat project-band decorator has no document to attach to; soft-degrade, nothing renders')
    return { set() {}, setInfo() {}, stop() {} }
  }

  // -- Own style in head (both CSS blocks in one style element; same-value writes are skipped) --
  let style = doc.querySelector(STYLE_SELECTOR)
  if (style === null) {
    style = doc.createElement('style')
    style.setAttribute('data-wb-chat-projband-style', '')
    doc.head.appendChild(style)
  }
  const fullCss = PROJBAND_BASE_CSS + '\n' + PROJBAND_BAND_CSS
  if (style.textContent !== fullCss) style.textContent = fullCss

  // 当前归属（sidebar 推导结果；Observer 回调按它重设，兜防 React 重建滚动体）。
  let current: string | null = null
  let currentHandle: string | undefined = undefined
  let stopped = false
  let warnedDisconnected = false

  // -- Identity-band overlay (a body-level element; no node inserted into the
  // React-managed subtree) --
  // Declared degradation: a missing doc.body (a malformed stub) or an
  // unavailable createElement -> no overlay is built and the container
  // attribute face keeps working (the design-2.1 band degrades to the existing
  // 3px top border + corner tag; no crash).
  let band: HTMLElement | null = null
  const canOverlay = typeof doc.createElement === 'function' && !!doc.body
      && typeof (doc.body as HTMLElement).appendChild === 'function'
  if (canOverlay) {
    try {
      band = doc.createElement('div') as HTMLElement
      band.setAttribute(PROJBAND_BAND_ATTR, '')
      // Sessions menu button (no getSessions source = the button is not rendered - declared degradation, no dead button)
      if (typeof opts.getSessions === 'function') {
        const btn = doc.createElement('button') as HTMLElement
        btn.className = 'wb-projband-sessions'
        btn.setAttribute('data-wb-band-sessions', '')
        btn.setAttribute('type', 'button')
        btn.textContent = 'Sessions'
        btn.addEventListener?.('click', (ev: Event) => {
          ev.stopPropagation()
          if (!band) return
          const open = band.getAttribute('data-menu-open') !== null
          if (open) { band.removeAttribute('data-menu-open'); return }
          renderMenu()
          band.setAttribute('data-menu-open', '')
        })
        band.appendChild(btn)
        const menu = doc.createElement('div') as HTMLElement
        menu.className = 'wb-projband-menu'
        menu.setAttribute('data-wb-band-menu', '')
        band.appendChild(menu)
      }
      ;(doc.body as HTMLElement).appendChild(band)
    } catch {
      band = null
    }
  }

  /** Redraw the menu content (called when opening; data from getSessions/onOpenSession/onNewSession). */
  const renderMenu = (): void => {
    if (!band) return
    const menu = band.querySelector('[data-wb-band-menu]') as HTMLElement | null
    if (!menu) return
    menu.textContent = ''
    const items = typeof opts.getSessions === 'function' ? opts.getSessions() : []
    for (const it of Array.isArray(items) ? items : []) {
      if (!it || typeof it.id !== 'string' || it.id === '') continue
      if (typeof opts.onOpenSession !== 'function') break
      const row = doc.createElement('button') as HTMLElement
      row.className = 'wb-projband-item'
      row.setAttribute('data-wb-band-item', it.id)
      row.setAttribute('type', 'button')
      const h = doc.createElement('span') as HTMLElement
      h.className = 'wb-projband-handle'
      h.textContent = it.handle
      const t = doc.createElement('span') as HTMLElement
      t.textContent = it.title
      // Raw title tooltip (t261008-01, Measure 1): the handle replaces the raw
      // charter-injection text as the visible label; the raw text stays one
      // hover away. Guarded against quoting surprises by setAttribute (no HTML
      // assembly). Absent rawTitle = attribute not set (declared absence).
      if (typeof it.rawTitle === 'string' && it.rawTitle !== '' && it.rawTitle !== it.title) {
        row.setAttribute('title', it.rawTitle)
      }
      row.appendChild(h)
      row.appendChild(t)
      if (it.active) row.setAttribute('data-active', '')
      row.addEventListener?.('click', (ev: Event) => {
        ev.stopPropagation()
        band?.removeAttribute('data-menu-open')
        opts.onOpenSession?.(it.id)
      })
      menu.appendChild(row)
    }
    if (typeof opts.onNewSession === 'function') {
      const nw = doc.createElement('button') as HTMLElement
      nw.className = 'wb-projband-item wb-projband-new'
      nw.setAttribute('data-wb-band-new', '')
      nw.setAttribute('type', 'button')
      nw.textContent = '+ New session'
      nw.addEventListener?.('click', (ev: Event) => {
        ev.stopPropagation()
        band?.removeAttribute('data-menu-open')
        opts.onNewSession?.()
      })
      menu.appendChild(nw)
    }
  }

  /** The open menu collapses on an ownership switch (a cross-project menu shows the wrong project's data; collapsing is the safe side). */
  const closeMenu = (): void => { band?.removeAttribute('data-menu-open') }

  /** Pin the overlay to the anchor rect (zero anchors = hidden; a stub without getBoundingClientRect = best-effort top placement). */
  const placeBand = (): void => {
    if (!band) return
    band.setAttribute(PROJBAND_BAND_ATTR, current ?? '')
    if (current === null) { band.setAttribute('data-hidden', ''); return }
    band.removeAttribute('data-hidden')
    const st = (band as HTMLElement).style
    if (typeof st?.setProperty !== 'function') return
    const color = projectColor(current)
    st.setProperty('--wb-projband-color', color)
    let anchor: Element | undefined
    try { anchor = Array.from(doc.querySelectorAll(SCROLL_SELECTOR))[0] } catch { anchor = undefined }
    const r = (anchor as HTMLElement | undefined)?.getBoundingClientRect?.()
    if (r && typeof r.top === 'number' && typeof r.left === 'number' && typeof r.width === 'number') {
      st.setProperty('top', `${Math.max(0, r.top)}px`)
      st.setProperty('left', `${r.left}px`)
      st.setProperty('width', `${r.width}px`)
    } else {
      // Stub/exception path: no positioning, no escaping the column (fixed defaults to top-left; tests assert presence and the hidden state only)
      st.setProperty('top', '0px')
      st.setProperty('left', '0px')
      st.removeProperty('width')
    }
  }

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
    applyProjectBand(doc, current, currentHandle)
    placeBand()
  }

  const observer = new MutationObserver(scan)
  observer.observe(doc.body ?? doc.documentElement, { childList: true, subtree: true })

  // Rect-follow listeners (capture scroll + resize; cleaned up on both the stop and the disconnected paths).
  const onFollow = (): void => { if (!stopped) placeBand() }
  const win = typeof window !== 'undefined' ? window : null
  try {
    doc.addEventListener?.('scroll', onFollow, true)
    win?.addEventListener?.('resize', onFollow)
  } catch { /* a stub without addEventListener: rect following degrades to scan-time updates */ }

  // One scan beat on startup: the overlay enters in the declared "no ownership = hidden" state (it does not wait for the first set).
  scan()

  const handle: ChatProjectBandHandle = {
    set(key: string | null) {
      current = isProjectKeyLike(key) ? (key as string) : null
      currentHandle = undefined
      closeMenu()
      scan()
    },
    setInfo(info) {
      const key = info?.project ?? null
      const changed = (isProjectKeyLike(key) ? (key as string) : null) !== current
      current = isProjectKeyLike(key) ? (key as string) : null
      currentHandle = typeof info?.handle === 'string' && info.handle !== '' ? info.handle : undefined
      if (changed) closeMenu()
      scan()
    },
    stop() {
      if (stopped) return
      stopped = true
      if (active === handle) active = null
      observer.disconnect()
      try {
        doc.removeEventListener?.('scroll', onFollow, true)
        win?.removeEventListener?.('resize', onFollow)
      } catch { /* if the listeners never attached there is nothing to remove */ }
      // Remove everything we created: the style element + the identity-band overlay + every self-set attribute (only our own).
      style.remove()
      try { band?.remove() } catch { /* the overlay is already gone */ }
      try {
        for (const el of Array.from(doc.querySelectorAll(`[${PROJBAND_ATTR}]`))) {
          el.removeAttribute(PROJBAND_ATTR)
          el.removeAttribute(PROJBAND_HANDLE_ATTR)
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
