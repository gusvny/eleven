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

/** Overview left-column split (t261007-01: three buckets — waiting on top,
 *  answered and dismissed in collapsed groups below; newest first within each).
 *  t261007-02: the five-state model narrows the waiting bucket to open —
 *  resolved/superseded collapse away with answered (they are decisions or
 *  machine closures, never waiting), dismissed keeps its own bucket, and a
 *  row with a shape-off status stays waiting (an over-wait beats silencing a
 *  possibly-open item). The closed-state list is inlined in the body (this
 *  function is embedded into the page via String() and must be self-contained). */
export function splitWaiting<T extends { status?: string }>(rows: T[]): { waiting: T[]; answered: T[]; dismissed: T[] } {
  const waiting: T[] = []
  const answered: T[] = []
  const dismissed: T[] = []
  const closed = ['answered', 'resolved', 'dismissed', 'superseded']
  for (const r of rows || []) {
    if (!r) continue
    if (r.status === 'dismissed') dismissed.push(r)
    else if (closed.includes(String(r.status))) answered.push(r)
    else waiting.push(r)
  }
  return { waiting, answered, dismissed }
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

// ---------- t261003-13：Ledger 页诚实化（时间口径 + 唤醒行句，同纪律：零 DOM、经 String(fn) 嵌页） ----------

/**
 * 本地时间「YYYY-MM-DD HH:MM」（t261004-14：行时间必须带日期——旧 hhmmLocal 只出
 * HH:MM，跨天的列表行看不出是哪天；随票更名 localDateTime，旧名不留）。页面上所有
 * 时间一律**本地时区**，且三个 tab（Overview 最近动作 / Alerts / Ledger）都带
 * 「Times are local.」屏上标签——标签由 HTML 静态承载，函数只管格式。畸形输入
 * （NaN/garbage/null）显式降级为「—」。
 */
export function localDateTime(v: unknown): string {
  const t = typeof v === 'number' ? v : Date.parse(String(v))
  if (!Number.isFinite(t)) return '—'
  const d = new Date(t)
  const p = (n: number) => (n < 10 ? '0' + n : String(n))
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
    + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

/**
 * 列表行「最新在前」排序（t261004-14）：按 at 降序的统一实现——at 缺席/畸形排最后
 * （负无穷），at 相等保持原相对顺序（Array.sort 自 ES2019 起稳定）。不改动入参，
 * 返回副本；外部账本数据是消费侧输入，任何畸形行都不许让排序抛错。
 */
export function newestFirst<T>(rows: T[]): T[] {
  const key = (r: T): number => {
    const v = (r as Record<string, unknown> | null)?.at
    const t = typeof v === 'number' ? v : Date.parse(String(v))
    return Number.isFinite(t) ? t : Number.NEGATIVE_INFINITY
  }
  return rows.slice().sort((a, b) => key(b) - key(a))
}

/**
 * 本地时间 MM-DD HH:MM（t261004-13）。Alerts 列表与 Ledger 唤醒行跨天可辨——旧
 * hhmmLocal 只有 HH:MM，不同天的两条告警在屏上无法区分。同一本地时区口径，屏上
 * 仍由静态「Times are local.」标签承载。畸形输入与 hhmmLocal 同契约：显式降级「—」。
 */
export function dateTimeLocal(v: unknown): string {
  const t = typeof v === 'number' ? v : Date.parse(String(v))
  if (!Number.isFinite(t)) return '—'
  const d = new Date(t)
  const p = (n: number) => (n < 10 ? '0' + n : String(n))
  return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

/**
 * 唤醒行句（t261003-13 Finding 2）。行上真实存在的字段只有 mode 与 accepted：
 * 句子只由这两者构成；任一缺席/畸形都显式写成 unknown / 「未报告」——
 * **绝不留一个兜底词**（旧实现 `stage||stage_state||'sent'` 把字面量当数据打印）。
 */
export function wakeRowSentence(wake: unknown): string {
  if (typeof wake !== 'object' || wake === null || Array.isArray(wake)) {
    return 'Mode: unknown. The watchdog did not report whether the executor accepted the wake.'
  }
  const w = wake as Record<string, unknown>
  const mode = typeof w.mode === 'string' && w.mode.trim() !== '' ? w.mode : 'unknown'
  const accepted = typeof w.accepted === 'boolean'
    ? (w.accepted ? 'The executor accepted the wake.' : 'The executor did not accept the wake.')
    : 'The watchdog did not report whether the executor accepted the wake.'
  return 'Mode: ' + mode + '. ' + accepted
}

/**
 * 主题深链参数解析（t261003-09 缺陷 2，纯函数、经 String(fn) 嵌页）。
 * 只认 'light' / 'dark'（大小写与首尾空白宽容）；缺席、畸形、非字符串一律 null——
 * 页面对 null 不设 data-theme，交给 prefers-color-scheme 显式降级（面板永不自造
 * 硬编码缺省调色板）。 */
export function themeParamOf(v: unknown): 'light' | 'dark' | null {
  const s = typeof v === 'string' ? v.trim().toLowerCase() : ''
  if (s === 'light') return 'light'
  if (s === 'dark') return 'dark'
  return null
}
