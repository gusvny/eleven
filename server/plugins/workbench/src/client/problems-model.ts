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
 *
 * t261028-48 (family sweep): the row verdict and the row NAME are not decided
 * here any more — they come from the one accessor in lane-map-model
 * (`receiptRowView`). Before this, this reader judged rows with `green === true`
 * and named them from `item`, so on a red SCRIPT gate ({check, level, count})
 * it listed every row as "red" (the green ones included) and could not name
 * any of them.
 */

import { receiptRowView, readGateRunVerdict } from './lane-map-model.ts'

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

/**
 * Receipt rows of a red gate → problem rows (t261028-48).
 *
 * The row verdict and the row name both come from the ONE shape-tolerant
 * accessor (`receiptRowView`), so a green SCRIPT row ({check, level: 'green',
 * count}) is never listed as a problem, and a red one is named from whichever
 * identity field the engine wrote (item / check / id) and carries its own
 * detail, note or count as the dim half.
 *
 * The prefix names the stage whose receipt this is (`stage` id, else the
 * human label): a red script gate must say "cs-machine-qc red: …", not a
 * borrowed "merge_check red: …".
 *
 * A scalar entry is skipped: this face judges receipt rows, and a bare word
 * carries no verdict field. Nothing is lost — when no row survives,
 * `gateProblemRows` still names the gate in the no-detail fallback row.
 */
function rowsFromChecks(checks: unknown[], prefix: string): ProblemRow[] {
  const out: ProblemRow[] = []
  for (let i = 0; i < checks.length; i++) {
    const raw = checks[i]
    if (raw === null || typeof raw !== 'object') continue
    const view = receiptRowView(raw)
    if (view === null || view.green) continue
    const dim = view.detail || view.note
      || (view.count !== undefined ? `count ${view.count}` : '')
    out.push({
      key: `check-${i}-${view.item}`,
      text: `${prefix} red: ${view.item}`,
      dim: dim || undefined,
    })
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
 * Last gate run → problem rows (the main data source of the Problems area; it
 * accepts every receipt shape):
 * - Red. The verdict comes from the shared reader `readGateRunVerdict`, so a
 *   gate that writes `level` is read too. When the engine wrote no verdict,
 *   the row evidence decides. A checks array gives one row per red item; a
 *   gate without one gives the field rows (counts / red_count / error).
 *   If both are empty, one row still names the red gate with no detail. The
 *   area is never silently blank.
 * - Not red, malformed or absent: an empty array. The caller falls back to
 *   the timeline reason or a plain stuck line.
 */
export function gateProblemRows(detail: unknown): ProblemRow[] {
  const g = lastGateRun(detail)
  if (!g) return []
  const label = gateStageLabel(g)
  const prefix = asString(g.stage) || label
  const checks = Array.isArray(g.checks) ? g.checks : null
  const rowProblems = checks !== null ? rowsFromChecks(checks, prefix) : null
  const written = readGateRunVerdict(g).green
  // No written verdict: the row evidence decides. A light gate carries no
  // rows, so its red evidence stays the counts/error fields below.
  const red = written !== undefined ? written === false : (rowProblems !== null && rowProblems.length > 0)
  if (!red) return []
  const rows = rowProblems !== null ? rowProblems : rowsFromLightGate(g)
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
