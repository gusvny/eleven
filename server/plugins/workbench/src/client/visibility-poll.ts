import { useEffect, useRef } from 'react'
import { pageVisible } from './visibility-state.ts'

// pageVisible 于 t260915-10 gen7 拆至 ./visibility-state.ts（零依赖，供非 React
// 模块复用——本文件顶上 import react 会拖垮 node 裸跑 UT 的 import 链）；此处
// re-export 保持既有 import 面（含潜在外部 smoke）兼容。
export { pageVisible } from './visibility-state.ts'

/**
 * visibility-poll.ts —— 不可见页签暂停轮询（t260901-15，多页签共存③）。
 *
 * 背景：用户常开多个控制台页签，后台页签照常全速轮询（台面 5s/health 5s/
 * 巡检 30s/agent-live 8s/侧栏 10s/立项 8~10s），放大查询通道压力（KI-003）。
 * 本模块把「定时轮询」统一收口成可见性门：页签不可见即停表、零请求；
 * 重新可见立即补刷一次并恢复节拍。
 *
 * 两条 API：
 *   - startVisibleInterval(fn, ms) → 停表函数：命令式（用在已有 effect 内部，
 *     替换裸 setInterval，初始 load() 语义不动）；
 *   - useVisiblePoll(fn, ms)：useVisiblePoll 的 hook 封装（fn 走 ref 取最新，
 *     避免每次渲染重建定时器）。
 *
 * 故障口径：document 不可用（node/smoke 裸跑）→ 视为可见直接轮询（与旧行为
 * 一致，不静默改语义——那里没有「隐藏页签」概念）；fn 异常向上抛给宿主 effect
 * 的既有兜底（各 effect 内部已有 try/catch 或静默约定）。
 */

/**
 * 启动一个可见性门控的周期任务。返回停表函数（幂等，必调——终态回收纪律）。
 * 立即可见时建表；隐藏时清表；回可见时先补跑一次再建表。
 */
export function startVisibleInterval(fn: () => void, ms: number): () => void {
  if (typeof document === 'undefined') {
    const t = setInterval(fn, ms)
    return () => { clearInterval(t) }
  }
  let timer: ReturnType<typeof setInterval> | null = null
  const start = () => {
    if (timer === null && pageVisible()) timer = setInterval(() => { if (pageVisible()) fn() }, ms)
  }
  const stop = () => {
    if (timer !== null) { clearInterval(timer); timer = null }
  }
  const onVis = () => {
    if (pageVisible()) { fn(); start() } else { stop() }
  }
  start()
  document.addEventListener('visibilitychange', onVis)
  return () => {
    stop()
    document.removeEventListener('visibilitychange', onVis)
  }
}

/** React 封装：fn 走 ref 取最新值，组件渲染不重建定时器；卸载即停表。 */
export function useVisiblePoll(fn: () => void, ms: number): void {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => startVisibleInterval(() => ref.current(), ms), [ms])
}

