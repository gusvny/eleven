/**
 * visibility-state.ts —— 页面可见性纯读（t260915-10 gen7 从 visibility-poll.ts 拆出）。
 *
 * 拆分原因：visibility-poll.ts 顶上 import react（hook 封装需要），而 react 由宿主
 * dsh 核心供给、不在插件 node_modules——非 React 模块（project-tag-index.ts 等
 * node 裸跑 UT 覆盖面）一旦 import 它即 ERR_MODULE_NOT_FOUND。本模块零依赖，供
 * 「只读可见性、不起定时器」的取数路径共用同一门判定，语义单源不复制。
 *
 * 契约不变（沿 visibility-poll.ts 原实现）：document 不可用（node/smoke 裸跑）→
 * 视为可见——那里没有「隐藏页签」概念，不静默改语义。
 */

export function pageVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState === 'visible'
}
