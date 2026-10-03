/**
 * page-logic.ts —— 面板页面的**纯逻辑面**（t260929-03）：beep 决策、降级态挑选、
 * 健康度比例口径、请求等待标注。全部纯函数、零 DOM、零 io——node 单测直接表驱动，
 * 并经 `String(fn)` 原样嵌进静态页（panel-page.ts），页面与单测永远同一份实现。
 *
 * beep 纪律（宿主 260927「一声就够，别烦我」）：仅当 notify.beep=true 且出现**新 key
 * 的未读 alert** 时响一声；重复轮询零重复；夜间已静音的行（除非红线）绝不响——
 * notify 位已含 sound+夜间口径，这里再挡一道（防御纵深）。
 * 契约偏差（review 意见 #1，如实声明）：已读清除走页面本地 seen-set（localStorage），
 * 未加 watchdog 侧 per-key 清除端点——同 key 在第二台设备会再响一声、守望者侧
 * unseen 状态不被消费。原因：清除端点要改已合并的守望者插件（本票 out-of-scope）。
 * 后果与后续票处置写进交接报告。
 */

/** 单条 alert 的最小形状（页面只消费契约承诺的键）。 */
export interface AlertLike {
  key: string
  rule: string
  level: string
  night_muted: boolean
}

/**
 * beep 决策（纯函数；seen 由调用方持有——localStorage 或测试里的 Set）。
 * 返回**本轮全部该响的 key**（每个新未见 key 恰一声——「一声就够」按 key 计，
 * 不按轮计；一次轮询进两个新 key = 两声，之后永不重复）。
 */
export function beepDecision(
  notify: { beep: boolean } | null | undefined,
  alerts: AlertLike[] | null | undefined,
  key: string,
  seen: Set<string>,
): { play: boolean; keys: string[] } {
  if (!notify || notify.beep !== true) return { play: false, keys: [] }
  if (!Array.isArray(alerts)) return { play: false, keys: [] }
  const keys: string[] = []
  for (const a of alerts) {
    if (!a || typeof a.key !== 'string' || seen.has(a.key)) continue
    // 夜间已静音的行只在红线例外名单内可响（alerts.redline 在 notify 位已与过一次，
    // 这里按行再挡：night_muted 且非 redline 级 → 沉默）。
    if (a.night_muted === true && a.level !== 'redline') continue
    keys.push(a.key)
  }
  return { play: keys.length > 0, keys }
}

export type DegradedKind = 'route-down' | 'not-declared' | 'stale' | 'config-error' | null

/**
 * 三种不可达的显式降级挑选（panel-contract.md：绝不渲染成空态或正常态）。
 * 返回 null = 一切可达且新鲜（唯一渲染正常卡的情形）。
 */
export function pickDegraded(input: {
  reachable: boolean
  declared?: boolean
  alive?: boolean
  config_error?: string | null
}): { kind: DegradedKind; label: string } {
  if (!input.reachable) {
    return { kind: 'route-down', label: 'Watchdog unreachable — route missing or console half down (this is NOT "all fine")' }
  }
  if (input.declared === false) {
    return { kind: 'not-declared', label: 'Not enrolled — no watchdog.json for this project: zero behavior by design (not an empty state)' }
  }
  if (input.alive === false) {
    return { kind: 'stale', label: 'Watchdog data possibly stale — watchdog process dead or never started' }
  }
  if (input.config_error) {
    return { kind: 'config-error', label: 'Declaration REJECTED by loader: ' + input.config_error }
  }
  return { kind: null, label: '' }
}

/** 健康度比例口径（mock：绝对数误导，按比例显示）。 */
export function fmtProportion(bad: number, total: number): string {
  if (!Number.isFinite(bad) || !Number.isFinite(total) || total <= 0) return '— (no rows)'
  const pct = Math.round((bad / total) * 1000) / 10
  return `${bad}/${total} rows (${pct}%)`
}

/** 等待时长（请求卡「已等多久」）。 */
export function fmtWaiting(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const s = Math.floor(ms / 1000)
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  if (m < 60) return m + 'm ' + (s % 60) + 's'
  const h = Math.floor(m / 60)
  return h + 'h ' + (m % 60) + 'm'
}

/** 心跳年龄的可读口径（含「数据可能过期」阈值提示）。 */
export function fmtAge(ageSeconds: number | null | undefined): string {
  if (typeof ageSeconds !== 'number' || !Number.isFinite(ageSeconds) || ageSeconds < 0) return '—'
  return fmtWaiting(ageSeconds * 1000) + ' ago'
}

/** 请求分组（master 列按项目分组；组内新的在前，尾巴永不丢——分页由调用方切片）。 */
export function groupByProject<T extends { project: string }>(rows: T[]): Array<{ project: string; rows: T[] }> {
  const order: string[] = []
  const map = new Map<string, T[]>()
  for (const r of rows) {
    if (!map.has(r.project)) { map.set(r.project, []); order.push(r.project) }
    map.get(r.project)!.push(r)
  }
  return order.map(project => ({ project, rows: map.get(project)! }))
}

// ---------- t261003-06：改版页面纯逻辑面（与上面同纪律：零 DOM、经 String(fn) 嵌页） ----------

/** 等待/已答切分（Overview 左栏：waiting 在上、answered 收进折叠区；组内新的在前）。 */
export function splitWaiting<T extends { status?: string }>(rows: T[]): { waiting: T[]; answered: T[] } {
  const waiting: T[] = []
  const answered: T[] = []
  for (const r of rows || []) {
    if (r && r.status === 'answered') answered.push(r)
    else if (r) waiting.push(r)
  }
  return { waiting, answered }
}

/** 选项判据（有选项=按钮，没选项=自由文本框；畸形选项项当没有——渲染面拿到的恒可信）。 */
export function hasOptions(row: { options?: unknown }): boolean {
  return Array.isArray(row?.options)
    && row.options.length > 0
    && (row.options as unknown[]).every((o) => typeof o === 'string' && o.trim() !== '')
}

/** 权限读出句（「Permissions: N of 6」口径——去重权限数，不是派生行数）。 */
export function chipLabel(count: number, total: number): string {
  const c = Number.isFinite(count) && count > 0 ? count : 0
  const t = Number.isFinite(total) && total > 0 ? total : 0
  return 'Permissions: ' + c + ' of ' + t
}

/** 总开关派生（同一份状态：任一权限开=总开关开；全关=总开关关）。 */
export function masterOn(count: number): boolean {
  return Number.isFinite(count) && count > 0
}
