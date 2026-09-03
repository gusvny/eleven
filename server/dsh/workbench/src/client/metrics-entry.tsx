/**
 * metrics-entry.tsx —— 度量面板入口（t260902-05①）。
 *
 * 用户反馈：「入口要在最底下与 dsh settings 同一排」。三级入口策略（t260902-05
 * 验收打回后修订：footer.action 槽实拍落点=侧栏包 footer（中列底），与 shell
 * 底部 Settings 行不同排，方案前提被实拍证伪）：
 *   1. 首选「注入+语义锚」（useHideFactoryNewSession 先例）：把钮直接注入 shell
 *      底部 Settings 齿轮所在行（aria/text 锚定 + MutationObserver 防复活 +
 *      卸载还原/全终态回收）——mountMetricsIntoSettingsRow()。
 *   2. shell 行找不到（结构变化）→ 回退 `sidebar.footer.action` 槽（apply() 注册，
 *      MetricsFooterButton；收到 METRICS_SHELL_EVENT active=true 时自隐，不重复）。
 *   3. 槽也注册失败 → 侧栏 .wb-sb-foot 兜底钮（footerSlotOk() 判定）。
 * 每级退化和成功都有 console 留痕/事件广播，不静默。
 *
 * 与面板的联动用 document CustomEvent 总线（入口钮与 WorkbenchSidebar 分属
 * 两棵 React 子树，无共同 state 属主）：
 *   - 钮 → 侧栏：dispatch wb-metrics-toggle（侧栏监听后开/关面板）；
 *   - 侧栏 → 钮：dispatch wb-metrics-state {open}（钮回显高亮）；
 *   - shell 注入 → 槽钮：dispatch wb-metrics-shell {active}（槽钮自隐/复显）。
 */
import { useEffect, useRef, useState } from 'react'
import { findSettingsRow } from './metrics-anchor.ts'

const SHELL_BTN_ID = 'wb-metrics-shell-btn'

export const METRICS_TOGGLE_EVENT = 'wb-metrics-toggle'
export const METRICS_STATE_EVENT = 'wb-metrics-state'
export const METRICS_SHELL_EVENT = 'wb-metrics-shell'

/** 槽注册结果标志（apply() 注册回调内置位；true=footer 槽可用，false=软退化）。 */
let footerSlotRegistered = false
export function markFooterSlot(ok: boolean): void { footerSlotRegistered = ok }
export function footerSlotOk(): boolean { return footerSlotRegistered }

/**
 * shell 覆盖层激活态（模块级最新值 + 惰性常驻监听，第 5 轮探针发现的一次性事件
 * 竞态的根治：槽钮 mount 时机夹在「广播已发/监听未挂」之间时既错过事件、初始
 * 检查时覆盖层钮又尚未挂载——常驻监听保证模块内任何时刻读到的是最新态）。
 * t260902-05 gen6 集成打回修正：常驻监听**不能放模块顶层**——顶层裸 document
 * 随 tsdown 进 bundle 后，node 侧 import（t260901-13 S0 bundle-exports 金丝雀）
 * 即 ReferenceError。改为惰性挂一次（幂等守卫 + typeof document 防呆），首次
 * 消费（槽钮 mount / 订阅 / 覆盖层 mount）时激活。
 */
let shellActive = false
let shellWatchAttached = false
function ensureShellActiveWatch(): void {
  if (shellWatchAttached || typeof document === 'undefined') return
  shellWatchAttached = true
  document.addEventListener(METRICS_SHELL_EVENT, (e) => {
    shellActive = Boolean((e as CustomEvent<{ active?: boolean }>).detail?.active)
  })
}

/** 读当前 shell 覆盖层激活态。 */
export function shellActiveNow(): boolean {
  ensureShellActiveWatch()
  return shellActive
}
/** 订阅激活态变化；返回退订函数。 */
export function subscribeShellActive(fn: (active: boolean) => void): () => void {
  ensureShellActiveWatch()
  const h = (e: Event) => fn(Boolean((e as CustomEvent<{ active?: boolean }>).detail?.active))
  document.addEventListener(METRICS_SHELL_EVENT, h)
  return () => { document.removeEventListener(METRICS_SHELL_EVENT, h) }
}

/** 出厂 footer.action 槽里的「📊 度量」钮（shell 覆盖层激活时自隐，防重复入口）。 */
export function MetricsFooterButton(_props: Record<string, never>) {
  const [open, setOpen] = useState(false)
  // 初始态三重：模块最新态（常驻监听维护）∨ 现存 DOM；一次性事件竞态（第 2/5 轮
  // 实拍与探针两次证实）不再影响可见性。
  const [hidden, setHidden] = useState(() =>
    shellActive
    || (typeof document !== 'undefined' && document.getElementById(SHELL_BTN_ID) !== null))
  const ref = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    ensureShellActiveWatch()
    const h = (e: Event) => setOpen(Boolean((e as CustomEvent<{ open?: boolean }>).detail?.open))
    const hs = (e: Event) => setHidden(Boolean((e as CustomEvent<{ active?: boolean }>).detail?.active))
    document.addEventListener(METRICS_STATE_EVENT, h)
    document.addEventListener(METRICS_SHELL_EVENT, hs)
    // 挂完监听立即从模块真值重同步（根治挂载序竞态：本钮 effect 晚于 active:true
    // 广播时，靠这次重同步收敛，不再依赖「恰好赶上事件」）
    setHidden(shellActive || document.getElementById(SHELL_BTN_ID) !== null)
    return () => {
      document.removeEventListener(METRICS_STATE_EVENT, h)
      document.removeEventListener(METRICS_SHELL_EVENT, hs)
    }
  }, [])
  if (hidden) return null
  return (
    <button
      ref={ref}
      className="wb-sb-foot-btn"
      data-on={open}
      title="度量面板（stage 时长 / 交付 / Token / 系统健康）"
      onClick={() => { document.dispatchEvent(new CustomEvent(METRICS_TOGGLE_EVENT)) }}
    >📊 度量</button>
  )
}

/**
 * 把「📊 度量」钮做成 body 级 fixed 覆盖层贴位 shell Settings 齿轮右侧（同排视觉）。
 * 返回 cleanup 全终态回收（详见函数内注释）。幂等可重复调。
 */
export function mountMetricsIntoSettingsRow(root: HTMLElement): () => void {
  const found = findSettingsRow(root)
  if (!found) {
    console.warn('[workbench] 未找到 shell Settings 行（度量入口软退化：回退 sidebar.footer.action 槽）')
    return () => { /* 无注入即无回收 */ }
  }
  const { settings } = found
  /**
   * body 级 fixed 覆盖层（第 5 轮打回定性修正）：上一版把钮 `settings.after(btn)`
   * 插进 React 托管的行容器——外部 DOM 变更与 React 协调互踩，页面随机崩/挂
   * （chat 必挂、hero 高概率挂），即「网络静默破坏源」。改法：钮挂 document.body
   * （React 树之外），fixed 定位贴到 Settings 齿轮右侧同排视觉，只读 rect、只动
   * 自己的节点——对 React 零侵入。防复活：MutationObserver 盯 body 子树，齿轮
   * 被移动/摘除时重贴位或降级广播（槽钮复显）。cleanup 全终态：断 Observer、
   * 摘 resize/scroll 监听、摘回显监听、摘钮、广播降级。
   */
  let stopped = false
  const reposition = () => {
    if (stopped) return
    if (!settings.isConnected) {
      stopped = true
      if (btn) btn.style.display = 'none'
      document.dispatchEvent(new CustomEvent(METRICS_SHELL_EVENT, { detail: { active: false } }))
      console.warn('[workbench] shell Settings 钮离开 DOM，度量入口覆盖层停用（回退 footer.action 槽）')
      return
    }
    const r = settings.getBoundingClientRect()
    if (btn) {
      btn.style.display = 'block'
      btn.style.left = `${Math.round(r.right + 6)}px`
      btn.style.top = `${Math.round(r.top + r.height / 2)}px`
      btn.style.transform = 'translateY(-50%)'
    }
  }
  let btn = document.getElementById(SHELL_BTN_ID) as ShellBtn | null
  if (!btn) {
    btn = document.createElement('button')
    btn.id = SHELL_BTN_ID
    btn.type = 'button'
    btn.title = '度量面板（stage 时长 / 交付 / Token / 系统健康）'
    btn.textContent = '📊'
    btn.style.cssText = 'position:fixed;z-index:1200;display:none;border:none;background:none;'
      + 'cursor:pointer;font:inherit;font-size:14px;padding:2px 6px;border-radius:6px;opacity:.75'
    btn.addEventListener('click', () => { document.dispatchEvent(new CustomEvent(METRICS_TOGGLE_EVENT)) })
    const reflect = (e: Event) => {
      const open = Boolean((e as CustomEvent<{ open?: boolean }>).detail?.open)
      if (btn) { btn.style.opacity = open ? '1' : '.75'; btn.style.color = open ? '#7ee787' : 'inherit' }
    }
    ;(btn as ShellBtn)._wbReflect = reflect
    document.addEventListener(METRICS_STATE_EVENT, reflect)
    document.body.appendChild(btn)
  }
  reposition()
  document.dispatchEvent(new CustomEvent(METRICS_SHELL_EVENT, { detail: { active: true } }))
  console.info('[workbench] 度量入口已贴位 shell Settings 行（body 级覆盖层，零 React 树侵入）')
  const mo = new MutationObserver(reposition)
  mo.observe(document.body, { childList: true, subtree: true })
  window.addEventListener('resize', reposition)
  window.addEventListener('scroll', reposition, true)
  return () => {
    stopped = true
    mo.disconnect()
    window.removeEventListener('resize', reposition)
    window.removeEventListener('scroll', reposition, true)
    if (btn) {
      document.removeEventListener(METRICS_STATE_EVENT, (btn as ShellBtn)._wbReflect!)
      btn.remove()
    }
    document.dispatchEvent(new CustomEvent(METRICS_SHELL_EVENT, { detail: { active: false } }))
  }
}

// 注入钮挂的回显监听器引用（挂在元素上，cleanup 时精确摘除）
type ShellBtn = HTMLButtonElement & { _wbReflect?: (e: Event) => void }
