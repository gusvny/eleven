/**
 * metrics-charts.ts —— metrics M2a（t260902-01）ECharts adapter。
 *
 * 红线（UI 规划 §1）：全仓**唯一 import echarts 的文件**是本文件（vendor 单文件
 * echarts@5.6.0，Apache-2.0，见 vendor/echarts.d.ts）。视图层（metrics.tsx）只见
 * 本文件的工厂函数与纯数据类型，不见 echarts 类型。
 *
 * 工厂四件（UI 规划 §6 冻结形状）：bar / groupBar / stackBar / hBar / donut
 * （groupBar 为 M2b Tab 交付预留，本单实现但与时间视图无耦合）。
 *
 * 资源回收（全终态纪律）：每个工厂返回的 ChartHandle 挂 mount 元素，持有
 * echarts 实例 + ResizeObserver；release() 可重复调用（幂等），observe/resize
 * 抛错路径也走 release。容器组件 unmount 时必调 release，Esc/✕ 关闭面板同路径。
 */
import * as echarts from './vendor/echarts.esm.min.js'
import type { ChartSpec, DonutInput } from './metrics-model.ts'

/** 人审等待主题色（固定橙，UI 规划 §4「人审等待独立一块橙色」）。 */
export const HUMAN_COLOR = '#ff9b1f'
const PALETTE = ['#0969da', '#8250df', '#1a7f37', '#cf222e', '#bf8700', '#57606a']

export interface ChartHandle {
  /** 幂等释放：dispose 实例 + 断开 ResizeObserver，重复调用安全。 */
  release(): void
}

export interface ChartFactoryOptions {
  /** 挂载点（空 div，adapter 全权接管其内容）。 */
  mount: HTMLElement
  spec: ChartSpec
  /** 点击柱/条（params.name = category；票 id 类图用于下钻跳详情）。 */
  onPick?: (name: string) => void
}

/* ------------------------------------------------------------ 内部：实例生命周期 */

interface Live {
  inst: ReturnType<typeof echarts.init> | null
  ro: ResizeObserver | null
  released: boolean
  /** 幂等释放（makeLive 内赋值）。 */
  release(): void
}

function makeLive(mount: HTMLElement): Live {
  const live: Live = { inst: null, ro: null, released: false, release: () => { /* 占位，下方覆写 */ } }
  live.inst = echarts.init(mount, null, { renderer: 'canvas' })
  const onResize = () => {
    if (!live.released && live.inst) {
      try { live.inst.resize() } catch { /* 实例已半毁：忽略，release 兜底 */ }
    }
  }
  if (typeof ResizeObserver !== 'undefined') {
    live.ro = new ResizeObserver(onResize)
    try { live.ro.observe(mount) } catch { /* observe 抛错：无观察能力降级为不自适应 */ }
  }
  live.release = () => {
    if (live.released) return
    live.released = true
    if (live.ro) { try { live.ro.disconnect() } catch { /* noop */ } }
    live.ro = null
    const inst = live.inst
    live.inst = null
    if (inst) { try { echarts.dispose(inst) } catch { /* dispose 幂等容忍 */ } }
  }
  return live
}

function baseOption(spec: ChartSpec) {
  return {
    animation: false,
    grid: { left: 56, right: 24, top: 36, bottom: 56 },
    xAxis: {
      type: 'category', data: spec.categories,
      axisLabel: { interval: 0, rotate: spec.categories.some(c => c.length > 6) ? 30 : 0, fontSize: 11 },
    },
    yAxis: { type: 'value' },
    tooltip: { trigger: 'axis' },
    legend: spec.series.length > 1 ? { bottom: 0, textStyle: { fontSize: 11 } } : undefined,
  }
}

function wirePick(live: Live, inst: ReturnType<typeof echarts.init>, onPick?: (name: string) => void) {
  if (!onPick) return
  const handler = (params: unknown) => {
    if (live.released) return
    const name = (params as { name?: unknown })?.name
    if (typeof name === 'string' && name.length > 0 && name.length <= 64) onPick(name)
  }
  inst.on('click', handler)
}

/* ------------------------------------------------------------ 工厂 */

/** 普通柱图（序列并列，Tab 时间柱形态主图）。 */
export function bar(opts: ChartFactoryOptions): ChartHandle {
  const live = makeLive(opts.mount)
  const inst = live.inst!
  inst.setOption({
    ...baseOption(opts.spec),
    series: opts.spec.series.map(s => ({
      name: s.name, type: 'bar', data: s.data, barMaxWidth: 42,
      itemStyle: { color: PALETTE[0] },
    })),
  })
  wirePick(live, inst, opts.onPick)
  return { release: () => live.release() }
}

/** 分组柱（M2b Tab 交付 add/del 双序列预留，本单已实现）。 */
export function groupBar(opts: ChartFactoryOptions): ChartHandle {
  const live = makeLive(opts.mount)
  const inst = live.inst!
  inst.setOption({
    ...baseOption(opts.spec),
    series: opts.spec.series.map((s, i) => ({
      name: s.name, type: 'bar', data: s.data, barMaxWidth: 42,
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  })
  wirePick(live, inst, opts.onPick)
  return { release: () => live.release() }
}

/** 堆叠柱（副2 Top 票 stage 构成，票 id 下钻）。 */
export function stackBar(opts: ChartFactoryOptions): ChartHandle {
  const live = makeLive(opts.mount)
  const inst = live.inst!
  const colors = new Map<string, string>()
  inst.setOption({
    ...baseOption(opts.spec),
    series: opts.spec.series.map((s, i) => {
      const color = s.name.includes('人审') || s.name.includes('human') ? HUMAN_COLOR : PALETTE[(i + 1) % PALETTE.length]
      colors.set(s.name, color)
      return { name: s.name, type: 'bar', stack: 'total', data: s.data, barMaxWidth: 28, itemStyle: { color } }
    }),
  })
  wirePick(live, inst, opts.onPick)
  return { release: () => live.release() }
}

/** 横向条（hBar，票排行类；本单时间视图暂无此 kind 消费方，工厂与冻结形状一致预留）。 */
export function hBar(opts: ChartFactoryOptions): ChartHandle {
  const live = makeLive(opts.mount)
  const inst = live.inst!
  inst.setOption({
    animation: false,
    grid: { left: 120, right: 32, top: 16, bottom: 32 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: opts.spec.categories, axisLabel: { fontSize: 11 } },
    tooltip: { trigger: 'axis' },
    series: opts.spec.series.map((s, i) => ({
      name: s.name, type: 'bar', data: s.data, barMaxWidth: 20,
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  })
  wirePick(live, inst, opts.onPick)
  return { release: () => live.release() }
}

export interface DonutFactoryOptions {
  mount: HTMLElement
  donut: DonutInput
}

/**
 * 环形图（饼形态主图 + 副1 donut）。人审扇区恒 HUMAN_COLOR 橙；中心大字
 * 「N 分钟 · 其中人等 X%」由 metrics.tsx 用 DonutInput 数据以绝对定位 DOM 渲染
 * （adapter 不管 DOM 叠加，专注画布）。
 */
export function donut(opts: DonutFactoryOptions): ChartHandle {
  const live = makeLive(opts.mount)
  const inst = live.inst!
  inst.setOption({
    animation: false,
    tooltip: { trigger: 'item', formatter: '{b}: {c} 分钟（{d}%）' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['52%', '76%'], center: ['50%', '44%'],
      avoidLabelOverlap: true,
      label: { show: true, formatter: '{b}', fontSize: 11 },
      data: opts.donut.slices.map(s => ({
        name: s.name, value: s.value,
        itemStyle: { color: s.human ? HUMAN_COLOR : undefined },
      })),
    }],
  })
  return { release: () => live.release() }
}

/** 按 kind 分派（未知 kind 容错返回 no-op handle，不抛——畸形数据防御）。 */
export function renderSpec(opts: ChartFactoryOptions): ChartHandle {
  switch (opts.spec.kind) {
    case 'bar': return bar(opts)
    case 'groupBar': return groupBar(opts)
    case 'stackBar': return stackBar(opts)
    case 'hBar': return hBar(opts)
    default: return { release: () => { /* no-op */ } }
  }
}
