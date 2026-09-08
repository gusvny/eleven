/**
 * metrics-model.ts —— metrics M2a（t260902-01）面板纯逻辑层（node 可裸 import 直测）。
 *
 * 职责：本文件收全部「消费外部输入后可独立验证」的纯函数，畸形输入一律容错
 * 不抛（写集纪律：消费外部输入的实现在单测里必带畸形用例，见
 * integration/t260902-01/t01_metrics_model.mjs）。UI 层（metrics.tsx）只做渲染
 * 与交互时序，不含数据推导。
 *
 * 口径出处（create_plan gen2 决策 4/9，两论审查通过）：
 * - 饼形态 = 机器 stage 各一扇区（模板链序）+ 链内 exit==='human' 的 stage
 *   时长合并为一个橙色扇区；全环合计 = Σby_stage，人审时长不重复计数
 *   （后端 human_wait ⊂ by_stage，见 host/metrics.ts L343/349）。模板数据缺失
 *   /stages 坏 → 软降级为 secondaries[0]「人审 vs 机器」二分环（同一橙色）。
 * - 口径偏差显式声明：UI 规划 §4 写「单票平均占比」，本实现 = 全窗口合计占比
 *   （与后端 donut/KPI 同口径，M3 对账可核）。判「必须单票平均」属契约 bump 范围，
 *   本单不越权（口径ⓘ 悬停按实际口径书写）。
 */
/* ------------------------------------------------------------ storage 存取小助手 */

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

/**
 * localStorage 读取（无 window/调用抛错环境 → null，不崩）。node 单测不注入时
 * 走此分支，等价于「无持久层」语义（读默认、写 no-op）。
 */
export function loadStorage(): StorageLike | null {
  try {
    const w = globalThis as { localStorage?: StorageLike }
    return w.localStorage ?? null
  } catch { return null }
}

export function saveStorage(storage: unknown, key: string, value: string): void {
  try { (storage as StorageLike | null)?.setItem?.(key, value) } catch { /* 满配额/禁写：丢弃不崩 */ }
}

/** 面板状态（tab/筛选/形态），存 localStorage sandbar-workbench-metrics-panel-v1。 */
export interface PanelState {
  view: string
  window: string
  epic: string
  project: string
  template: string
  shape: 'bar' | 'donut'
}

export const PANEL_STORAGE_KEY = 'sandbar-workbench-metrics-panel-v1'
// t260902-05⑤：时间窗扩 1d/3d（后端 WINDOWS 同步，授权=工单正文）
export const PANEL_WINDOWS = ['1d', '3d', '7d', '30d', 'all'] as const
export const PANEL_VIEWS = ['time', 'delivery', 'token', 'health'] as const

const DEFAULT_STATE: PanelState = { view: 'time', window: '7d', epic: 'all', project: '', template: 'dev-lane', shape: 'bar' }

const WINDOW_SET = new Set<string>(PANEL_WINDOWS)
const VIEW_SET = new Set<string>(PANEL_VIEWS)

/** 字符串过滤：超长一律截断（41 与后端 epic 形状上限一致，防 localStorage 毒化面）。 */
function cleanStr(v: unknown, max = 41): string {
  return typeof v === 'string' ? v.slice(0, max) : ''
}

/**
 * 面板状态读（容错不抛）：非对象/字段类型错/非法枚举一律回默认；局部坏字段
 * 只丢弃坏字段，其余保留。
 */
export function loadPanelState(storage: unknown = loadStorage()): PanelState {
  const raw = (storage as any)?.getItem?.(PANEL_STORAGE_KEY)
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > 4096) return { ...DEFAULT_STATE }
  let parsed: unknown
  try { parsed = JSON.parse(raw) } catch { return { ...DEFAULT_STATE } }
  if (typeof parsed !== 'object' || parsed === null) return { ...DEFAULT_STATE }
  const s = parsed as Record<string, unknown>
  const out = { ...DEFAULT_STATE }
  if (typeof s.view === 'string' && VIEW_SET.has(s.view)) out.view = s.view
  if (typeof s.window === 'string' && WINDOW_SET.has(s.window)) out.window = s.window
  // t260904-04（KI-042 宿主令）：泳道（模板）与立项选择器退役，两参数恒归常量
  // 透传后端（parseMetricsQuery 必收 epic/template，schema 不动）。持久化残留
  // （旧版存过非 dev-lane 模板/非 all 立项）一律弃用——防旧 localStorage 锁死
  // 非 dev-lane 模板导致空面板；保存 effect 会把归一值写回覆盖残留。
  out.template = 'dev-lane'
  out.epic = 'all'
  if (typeof s.project === 'string') out.project = cleanStr(s.project)
  if (s.shape === 'bar' || s.shape === 'donut') out.shape = s.shape
  return out
}

export function savePanelState(state: PanelState, storage: unknown = loadStorage()): void {
  saveStorage(storage, PANEL_STORAGE_KEY, JSON.stringify(state))
}

/* ------------------------------------------------------------ ChartSpec（契约形状） */

export interface ChartSeries {
  name: string
  data: number[]
}

export interface ChartSpec {
  kind: string
  title: string
  categories: string[]
  series: ChartSeries[]
  drill: boolean
}

const KNOWN_KINDS = new Set(['bar', 'stackBar', 'hBar', 'donut'])

/** 单个 spec 合法性（畸形容错：非对象/类型错/维度不齐/非法 kind 一律判坏丢弃）。 */
export function isChartSpec(v: unknown): v is ChartSpec {
  if (typeof v !== 'object' || v === null) return false
  const c = v as Record<string, unknown>
  if (typeof c.kind !== 'string' || !KNOWN_KINDS.has(c.kind)) return false
  if (typeof c.title !== 'string') return false
  if (!Array.isArray(c.categories)) return false
  if (!Array.isArray(c.series)) return false
  const n = c.categories.length
  for (const s of c.series as unknown[]) {
    if (typeof s !== 'object' || s === null) return false
    const sv = s as Record<string, unknown>
    if (typeof sv.name !== 'string' || !Array.isArray(sv.data)) return false
    if ((sv.data as unknown[]).length !== n) return false
    if ((sv.data as unknown[]).some(d => typeof d !== 'number' || !Number.isFinite(d))) return false
  }
  return true
}

export interface MetricsKpis {
  tickets: number
  closed: number
  avg_delivery_min: number
  tokens_total: number
}

export interface MetricsResponse {
  kpis: MetricsKpis
  primary: ChartSpec | null
  secondaries: ChartSpec[]
  generatedAt: string
  cache: Record<string, unknown>
  error: string | null
  /** 后端人话降级原因（health 直查/软降级口径说明；无则空串）——t260902-05③。 */
  reason: string
}

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)

/**
 * /metrics 响应解析（畸形容错不抛）：4xx/{error}、非对象、kpis 坏、charts 坏都有
 * 明确定义——error 承载人话（空态渲染），坏 spec 丢弃而非崩。这是面板 fetch 后
 * 的唯一入口，UI 层不见原始 JSON。
 */
export function sanitizeMetricsResponse(body: unknown): MetricsResponse {
  const bad = (msg: string): MetricsResponse => ({
    kpis: { tickets: 0, closed: 0, avg_delivery_min: 0, tokens_total: 0 },
    primary: null, secondaries: [], generatedAt: '', cache: {}, error: msg, reason: '',
  })
  if (typeof body !== 'object' || body === null) return bad('响应不是 JSON 对象')
  const b = body as Record<string, unknown>
  if (typeof b.error === 'string' && b.error.length > 0) return bad(b.error.slice(0, 300))
  const kp = (typeof b.kpis === 'object' && b.kpis !== null ? b.kpis : {}) as Record<string, unknown>
  const kpis: MetricsKpis = {
    tickets: num(kp.tickets), closed: num(kp.closed),
    avg_delivery_min: num(kp.avg_delivery_min), tokens_total: num(kp.tokens_total),
  }
  const charts = (typeof b.charts === 'object' && b.charts !== null ? b.charts : {}) as Record<string, unknown>
  const primary = isChartSpec(charts.primary) ? charts.primary : null
  const secondaries = Array.isArray(charts.secondaries)
    ? (charts.secondaries as unknown[]).filter(isChartSpec)
    : []
  return {
    kpis, primary, secondaries,
    generatedAt: typeof b.generated_at === 'string' ? b.generated_at : '',
    cache: (typeof b.cache === 'object' && b.cache !== null ? b.cache : {}) as Record<string, unknown>,
    error: null,
    reason: typeof b.reason === 'string' ? b.reason.slice(0, 600) : '',
  }
}

/**
 * 图表数据是否「全零/不可绘」（t260902-05⑥）：donut/bar 全零时 echarts 画布上
 * 不可见（用户看到「无 chart」的白块），UI 层改显空态文案。全零判断畸形容错：
 * data 非数/缺项按 0 计，series 空也判不可绘。
 */
export function specIsBlank(spec: ChartSpec | null | undefined): boolean {
  if (!spec || spec.categories.length === 0 || spec.series.length === 0) return true
  return spec.series.every(s => s.data.every(v => !Number.isFinite(v) || v === 0))
}

/** DonutInput 全零（主图饼形态空态，同 specIsBlank 口径）。 */
export function donutIsBlank(input: DonutInput | null | undefined): boolean {
  if (!input || input.slices.length === 0) return true
  return input.slices.every(s => !Number.isFinite(s.value) || s.value === 0)
}

/* ------------------------------------------------------------ 饼形态组合（决策 4） */

export interface DonutSlice {
  name: string
  value: number
  /** true = 人审等待合并扇区（固定橙色主题，adapter 消费）。 */
  human: boolean
}

export interface DonutInput {
  slices: DonutSlice[]
  /** 中心大字：合计分钟。 */
  totalMin: number
  /** 中心小字：人等占比 0..1。 */
  humanRatio: number
  /** true = 模板数据缺失走了降级二分环（UI 显式标注）。 */
  degraded: boolean
}

/** 模板 stage 判定：exit==='human' 的 id 集合（WfStage.exit，index.tsx L709-717）。 */
export function humanStageIds(stages: unknown): Set<string> {
  const out = new Set<string>()
  if (!Array.isArray(stages)) return out
  for (const s of stages) {
    if (typeof s === 'object' && s !== null && (s as Record<string, unknown>).exit === 'human'
      && typeof (s as Record<string, unknown>).id === 'string') {
      out.add((s as Record<string, unknown>).id as string)
    }
  }
  return out
}

/**
 * 饼形态组合（方案 a，gen2 决策 4）：
 * 环形 = Σby_stage 全环——primary（bar，stage 时长合计）的 categories/data 为
 * 机器扇区逐 stage 展开，链内 exit==='human' 的 stage 合并为一个 human 扇区。
 * 人审时长已在链内（human_wait ⊂ by_stage），只合并不追加 → 全环合计=Σby_stage
 * 无重复计数。模板缺 stages/数据坏 → 降级 secondaries[0] 二分环（同一橙色，
 * degraded=true 显性标注）。
 *
 * 畸形容错：primary 坏、series 空、categories/data 维度不齐 → 各路径都有定义
 * （空 slices / 降级 / error 丢弃），绝不抛。
 */
export function buildTimeDonut(primary: ChartSpec | null, fallback: ChartSpec | null, stages: unknown): DonutInput {
  const humans = humanStageIds(stages)
  const hasStages = Array.isArray(stages) && stages.length > 0
  if (primary && hasStages && primary.series.length > 0 && primary.categories.length > 0) {
    const data = primary.series[0].data
    const machine: DonutSlice[] = []
    let humanTotal = 0
    let total = 0
    for (let i = 0; i < primary.categories.length; i++) {
      const v = typeof data[i] === 'number' && Number.isFinite(data[i]) ? data[i] : 0
      total += v
      if (humans.has(primary.categories[i])) humanTotal += v
      else machine.push({ name: primary.categories[i], value: v, human: false })
    }
    const slices: DonutSlice[] = [...machine]
    if (humanTotal > 0) slices.push({ name: '人审等待', value: humanTotal, human: true })
    else if (humans.size > 0) slices.push({ name: '人审等待', value: 0, human: true })
    return {
      slices,
      totalMin: round2(total),
      humanRatio: total > 0 ? humanTotal / total : 0,
      degraded: false,
    }
  }
  // 降级：secondaries[0]「人审等待 vs 机器」二分环（值域已满足机器=合计-人审）。
  if (fallback && fallback.kind === 'donut' && fallback.series.length > 0) {
    const data = fallback.series[0].data
    const slices: DonutSlice[] = fallback.categories.map((name, i) => ({
      name,
      value: typeof data[i] === 'number' && Number.isFinite(data[i]) ? data[i] : 0,
      human: name.includes('人审') || name.includes('human'),
    }))
    const total = slices.reduce((s, x) => s + x.value, 0)
    const human = slices.filter(x => x.human).reduce((s, x) => s + x.value, 0)
    return { slices, totalMin: round2(total), humanRatio: total > 0 ? human / total : 0, degraded: true }
  }
  return { slices: [], totalMin: 0, humanRatio: 0, degraded: hasStages }
}

/* ------------------------------------------------------------ KPI 卡 */

export interface KpiCard {
  label: string
  value: string
  title: string
}

const fmtInt = (n: number): string => {
  const v = Math.trunc(n)
  return Number.isFinite(v) ? v.toLocaleString('zh-CN') : '0'
}

/** 数字格式化：NaN/负/超大/0 边界全部有定义（单测覆盖）。 */
export function formatMinutes(min: number): string {
  if (!Number.isFinite(min) || min <= 0) return '0'
  if (min >= 10000) return `${Math.round(min).toLocaleString('zh-CN')}`
  if (min < 10) return String(round2(min))
  if (min < 100) return String(Math.round(min * 10) / 10)
  return String(Math.round(min))
}

export function formatTokens(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0'
  if (n >= 1_000_000) return `${round2(n / 1_000_000)}M`
  if (n >= 10_000) return `${round2(n / 1000)}k`
  return fmtInt(n)
}

/** KPI 四卡（契约冻结四字段，常量序）。 */
export function kpiCards(k: MetricsKpis): KpiCard[] {
  return [
    { label: '工单数', value: fmtInt(k.tickets), title: '时间窗内纳票总数（closed 票按闭单时刻、未结票按创建时刻归窗）' },
    { label: '关闭数', value: fmtInt(k.closed), title: '时间窗内已收口票数' },
    { label: '均交付时长', value: `${formatMinutes(k.avg_delivery_min)} 分钟`, title: '窗口内 closed 票交付时长均值（v1 = handoff 近似口径，v2 = 08 终态精确）' },
    { label: 'Token 总量', value: formatTokens(k.tokens_total), title: 'in + out 合计，不含 cacheRead（cacheRead 数见 Token tab，M2b）' },
  ]
}

/* ------------------------------------------------------------ 工具 */

export function round2(n: number): number {
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0
}

/** fetch 查询串（后端契约：window/epic/project/template/view 五参数，缺省后端给默认）。 */
export function metricsQueryString(state: PanelState): string {
  const q = new URLSearchParams()
  q.set('window', state.window)
  q.set('epic', state.epic)
  if (state.project) q.set('project', state.project)
  q.set('template', state.template)
  q.set('view', state.view)
  return q.toString()
}
