/**
 * 对账（t260928-28，纯函数核）——「对账是第一公民，不是兜底」。
 *
 * 真源=看板（visibility list，绝不依赖某票 worker 在线）；账本=派生投影。
 *  - 不一致：以看板为准 + 把不一致本身落成 alertable event（reconcile_mismatch）。
 *  - 对账失败（board 读不到）：显式 degraded + 原因 + since，绝不渲染成 all-fine。
 *  - 缺行覆盖（t261004-13 重写）：口径=**账本零行覆盖该票**才算缺（账本有行但与看板
 *    态分叉归 reconcile_mismatch，不在此重复计）。只对**在飞票**告警，去重键带缺口
 *    集合指纹（`project:N:hash8`）——集合不变不重响；终态缺口只进状态面。
 *    见 makeMissingRowsSpec / ledgerCoverage。
 *  - 两侧必须同 scope：账本是**本项目**文件，看板行也必须裁到本项目
 *    （filterBoardRowsToProject；KI-180：全机看板比项目账本 = 永不收敛的假警）。
 */

import type { LedgerRow } from './ledger-tail.ts'

/** 看板一行（engine client.py ticket-list 的 tickets[] 行的必要子集；ticket 为兼容别名）。
 *  status（t261004-13）：引擎票状态机 dispatched→settled→verified→closed/rework，
 *  用于把终态票从缺行告警里摘出去（终态票的账本缺口不可行动，不进告警面）。 */
export interface BoardRow {
  id?: string
  ticket?: string
  stage?: string
  stage_state?: string
  /** ticket.py list 行自带的状态机值；无标签的历史票缺席此字段。 */
  status?: string
  /** ticket.py list 行自带的项目 key（引擎 SA 投影；无标签的历史票缺席此字段）。 */
  project?: string
}

function boardId(b: BoardRow): string {
  return String(b.id ?? b.ticket ?? '')
}
function boardState(b: BoardRow): string {
  return String(b.stage_state ?? b.stage ?? '')
}
function ledgerState(l: { stage?: string; stage_state?: string }): string {
  return String(l.stage_state ?? l.stage ?? '')
}

export interface Mismatch {
  ticket: string
  board_state: string
  ledger_state: string
}

export type ReconcileState = 'ok' | 'mismatch' | 'degraded' | 'never_run'

export interface ReconcileResult {
  state: ReconcileState
  reason: string | null
  since: number | null
  mismatches: Mismatch[]
}

/** 推演态 vs 看板真源比对（纯函数）。账本缺票不在此报——那归 missing-rows 面
 *  （账本可能整段缺，逐票 mismatch 会把一件事拆成 N 条响声，违反「一声就够」）。 */
export function compareStates(
  ledgerStates: Map<string, { stage?: string; stage_state?: string }>,
  board: BoardRow[],
): Mismatch[] {
  const boardMap = new Map(board.map(b => [boardId(b), b]))
  const mism: Mismatch[] = []
  for (const [ticket, led] of ledgerStates) {
    const b = boardMap.get(ticket)
    if (!b) {
      mism.push({ ticket, board_state: '<absent>', ledger_state: ledgerState(led) || '<unknown>' })
      continue
    }
    const bs = boardState(b)
    const ls = ledgerState(led)
    if (bs !== '' && ls !== '' && bs !== ls) {
      mism.push({ ticket, board_state: bs, ledger_state: ls })
    }
  }
  return mism
}

/** board 读不到时的 degraded 结果（watchdog 活着但看板真源不可达——显式，不是 ok）。 */
export function degradedResult(reason: string, nowMs: number): ReconcileResult {
  return { state: 'degraded', reason, since: nowMs, mismatches: [] }
}

/** 终态票状态值（t261004-13）：closed/verified 之后票不可行动，账本缺口不再是告警。
 *  settled 保守按在飞算（还欠 verify）；rework 显然在飞。status 缺席（无标签历史票）
 *  保守按在飞算——宁多看一眼，不假报平安（与 filterBoardRowsToProject 同纪律）。 */
export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(['closed', 'verified'])

function isTerminalBoardRow(b: BoardRow): boolean {
  return b.status !== undefined && b.status !== null && TERMINAL_STATUSES.has(String(b.status))
}

/** FNV-1a 32 位，取 8 位十六进制（t261004-13）：给去重 key 一个确定性的集合指纹。
 *  零依赖纯函数；同一集合（排序后）恒得同一指纹，不同集合几乎必得不同指纹。 */
export function fnv1a8(input: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/** 缺行 alert 的 spec 构造（t261004-13 重写）：**去重键带集合，不带裸计数**——
 *  target = `project:N:hash8`（N=在飞缺口数，hash=排序后票 id 集合的 FNV 指纹）。
 *  同一集合（无论收到顺序）= 同一 key = 冷却；真来了新缺口票 = 新 key = 重响；
 *  纯计数增长但集合不变 = 不再重响（旧实现 `project:N` 每 +1 票就刷一声，KI-180 同族）。
 *  文案用英文（宿主令 260925：控制台 UI 文案一律英文）。 */
export function makeMissingRowsSpec(project: string, missingTickets: string[], level: 'warn' | 'redline' = 'warn'): {
  rule: string; target: string; level: 'warn' | 'redline'; title: string; detail: string
} {
  const ids = [...missingTickets].sort()
  const target = `${project}:${ids.length}:${fnv1a8(ids.join(','))}`
  return {
    rule: 'ledger_missing_rows',
    target,
    level,
    title: `Ledger has no rows for ${ids.length} in-flight tickets (project ${project})`,
    detail: `Uncovered in-flight tickets: ${ids.slice(0, 10).join(', ')}${ids.length > 10 ? `, +${ids.length - 10} more` : ''}. `
      + 'A ticket counts as uncovered only when the event ledger holds no row for it at all. '
      + 'Uncovered closed or verified tickets are reported on the status face, not here.',
  }
}

/**
 * 缺行覆盖面（t261004-13 重写，纯函数）：**覆盖 = 账本里有该票的任意一行**。
 *  旧口径要求账本行精确等于看板当前状态，历史票/终态票最后一次账本行不等于看板态
 *  就永远算缺——实测 150 行看板 145 行「缺」，永不收敛（KI-180 同族）。
 *  口径收窄说明（对应票面 "at or after the board state"）：账本落后/分叉于看板态的
 *  情形已归 reconcile_mismatch（compareStates 以看板为真源逐票报），此处不再重复
 *  计数——watchdog 看不到 stage 全序，无法定义 "at or after"，引入第二真源违反
 *  visibility-list 纪律。结果按可行动性分两桶：在飞缺口（进告警面）与终态缺口
 *  （只进状态面）。ticket id 空白的行不计数（没有可报的对象）。
 */
export function ledgerCoverage(board: BoardRow[], ledgerRows: LedgerRow[]): {
  in_flight_missing: string[]
  terminal_missing: string[]
} {
  const covered = new Set(ledgerRows.map(r => String(r.ticket)))
  const inFlight: string[] = []
  const terminal: string[] = []
  for (const b of board) {
    const id = boardId(b)
    if (id === '' || covered.has(id)) continue
    ;(isTerminalBoardRow(b) ? terminal : inFlight).push(id)
  }
  return { in_flight_missing: inFlight, terminal_missing: terminal }
}

/**
 * 项目过滤（KI-180 防御纵深，纯函数）：对账与缺行计数都拿**本项目账本**比看板，
 * 所以喂进来的看板行必须先裁到本项目——否则别家票永不可能被本项目账本覆盖，
 * `ledger_missing_rows` 的 N 会恒等于全机票数（结构假警，永不收敛）。
 * 规则：行带 project 字段时只留等于本项目的；字段缺席（无 SA 标签的历史票）
 * 保守保留——引擎侧 project 过滤同样匹配不到它们，误删真源行比多算一行缺行更危险。
 */
export function filterBoardRowsToProject(rows: BoardRow[], project: string): BoardRow[] {
  return rows.filter(b => {
    const p = b.project
    return p === undefined || p === null || String(p) === project
  })
}
