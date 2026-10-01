/**
 * problems-model.ts —— 问题区（D2Problems）行模型的纯函数单写者（t261001-11）。
 *
 * 根因：D2Problems 曾假设 gate_runs 末条必带 `checks` 数组（dev-lane 的
 * merge_check 形态），而轻道 run_integration_tests 的闸记录根本无该键
 * （键族=stage/label/green/red_count/exit_code/counts/error/narrowed/
 * excluded_pools/known_red_skipped）→ `g.checks.filter` 抛 TypeError →
 * 槽条目整体崩 → 侧栏退回 dsh 默认 UI。本文件把「gate 记录→人话原因行」
 * 收成形态容忍的纯函数：checks 形态走逐项行，轻道形态走自带字段
 * （counts/red_count/error），任何畸形输入不抛、至少给出 stage 标签 +
 * 为什么红。两形态都由引擎各自落账（不在引擎侧统一形态），读者必须双吃。
 */

/** 一条原因行：text 主体，dim 为灰色补充（与旧 D2Problems 行同构）。 */
export interface ProblemRow {
  key: string
  text: string
  dim?: string
}

const asString = (v: unknown): string => (typeof v === 'string' ? v : '')
const asFinite = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null

/** gate_runs 末条（容忍 detail/gate_runs 畸形：非对象/非数组 → undefined）。 */
export function lastGateRun(detail: unknown): Record<string, unknown> | undefined {
  if (detail === null || typeof detail !== 'object') return undefined
  const runs = (detail as Record<string, unknown>).gate_runs
  if (!Array.isArray(runs) || runs.length === 0) return undefined
  const g = runs[runs.length - 1]
  return g !== null && typeof g === 'object' ? (g as Record<string, unknown>) : undefined
}

/** gate 的展示标签：label 优先、stage 兜底，畸形 → 'gate'。 */
export function gateStageLabel(g: Record<string, unknown> | undefined): string {
  if (!g) return 'gate'
  return asString(g.label) || asString(g.stage) || 'gate'
}

/** merge_check 形态：checks 数组里的红项 → 行（项内畸形逐条跳过不抛）。 */
function rowsFromChecks(checks: unknown): ProblemRow[] {
  if (!Array.isArray(checks)) return []
  const out: ProblemRow[] = []
  for (let i = 0; i < checks.length; i++) {
    const c = checks[i]
    if (c === null || typeof c !== 'object') continue
    const co = c as Record<string, unknown>
    if (co.green === true) continue
    const item = asString(co.item) || asString(co.id) || `check #${i}`
    out.push({ key: `check-${i}-${item}`, text: `merge_check red: ${item}`, dim: asString(co.detail) || undefined })
  }
  return out
}

/** 轻道闸形态（无 checks 键）：自带字段 → 人话原因行。 */
function rowsFromLightGate(g: Record<string, unknown>): ProblemRow[] {
  const out: ProblemRow[] = []
  // error：闸/命令的报错原文（引擎落的是 str(ir.error or '')，空串不占行）
  const err = asString(g.error)
  if (err) out.push({ key: 'error', text: `gate error: ${err}` })
  // counts：{ran/passed/failed/env_fail} 数值族 → 一行人话对账；畸形键值逐对跳过
  const counts = g.counts
  if (counts !== null && typeof counts === 'object' && !Array.isArray(counts)) {
    const parts: string[] = []
    for (const [k, v] of Object.entries(counts as Record<string, unknown>)) {
      const n = asFinite(v)
      if (n !== null) parts.push(`${k}=${n}`)
    }
    if (parts.length > 0) out.push({ key: 'counts', text: `gate counts: ${parts.join(' / ')}` })
  }
  const red = asFinite(g.red_count)
  if (red !== null && red > 0) out.push({ key: 'red_count', text: `${red} red item(s) this round` })
  const exit = asFinite(g.exit_code)
  if (exit !== null && exit !== 0) out.push({ key: 'exit_code', text: `exit_code=${exit}` })
  return out
}

/**
 * gate_runs 末条 → 原因行（问题区主数据源，形态容忍）：
 * - red（green === false）：checks 形态走逐项行；否则走轻道自带字段；
 *   两面都空也要点名「该闸红但无明细」（绝不静默空白）。
 * - 非 red / 畸形 / 缺席：空数组（调用方回落 timeline reason / 兜底行）。
 */
export function gateProblemRows(detail: unknown): ProblemRow[] {
  const g = lastGateRun(detail)
  if (!g || g.green !== false) return []
  const label = gateStageLabel(g)
  const rows = Array.isArray(g.checks) ? rowsFromChecks(g.checks) : rowsFromLightGate(g)
  if (rows.length === 0) rows.push({ key: 'no-detail', text: `${label}: red (no per-item detail recorded)` })
  return rows
}

/* ── 槽错误边界（slot error boundary）纯面 ────────────────────────── */

/**
 * 槽条目渲染崩溃 → 边界 fallback 文案（t261001-11 第二缺陷：一个坏记录
 * 曾能打掉整个侧栏——现在边界兜住，点名故障、其余 UI 存活）。
 * 畸形 error（非 Error/空 message）也有可读文案，绝不渲染空白。
 */
export function slotFaultMessage(error: unknown): string {
  const msg = error instanceof Error ? error.message : typeof error === 'string' ? error : ''
  return `Workbench panel crashed while rendering: ${msg || 'unknown fault'} — the rest of the console stays usable.`
}
