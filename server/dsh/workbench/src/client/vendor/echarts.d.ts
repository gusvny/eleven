/**
 * echarts 最小类型声明（metrics M2a，t260902-01）。
 *
 * 背景：本目录 `echarts.esm.min.js` 是从 npmmirror 官方 echarts@5.6.0 tgz
 * 解包出的 `dist/echarts.esm.min.js`（Apache-2.0，LICENSE 同目录）。为避免引入
 * node_modules 依赖（构建零网络目标），不装 @types/echarts，由本文件声明
 * metrics-charts.ts adapter 实际用到的最小 API 面。类型按需补充，不追求全量。
 */
export interface ChartOption {
  [key: string]: unknown
}
export interface ChartInitOpts {
  renderer?: 'canvas' | 'svg'
  width?: number | string
  height?: number | string
}
export interface EChartsInstance {
  setOption(option: ChartOption): void
  resize(): void
  on(event: string, handler: (params: unknown) => void): void
  off(event: string, handler?: (params: unknown) => void): void
  dispose(): void
  getWidth(): number
}
export function init(dom: HTMLElement, theme?: string | Record<string, unknown> | null, opts?: ChartInitOpts): EChartsInstance
export function dispose(instance: EChartsInstance): void
export const version: string
declare const echarts: {
  init: typeof init
  dispose: typeof dispose
  version: string
}
export default echarts
