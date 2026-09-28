/**
 * 对账（t260928-28，纯函数核）——「对账是第一公民，不是兜底」。
 *
 * 真源=看板（visibility list，绝不依赖某票 worker 在线）；账本=派生投影。
 *  - 不一致：以看板为准 + 把不一致本身落成 alertable event（reconcile_mismatch）。
 *  - 对账失败（board 读不到）：显式 degraded + 原因 + since，绝不渲染成 all-fine。
 *  - 缺行计数：以看板票面在账本应有序 vs 账本实有 idem 的差额 N 落
 *    `ledger_missing_rows:<project>` 专属 alert（N 变化即新事实重响——dedupe key
 *    的 target 带上 N，N 不变自然冷却，见 makeMissingRowsSpec）。
 */

import type { LedgerRow } from './ledger-tail.ts'

/** 看板一行（engine client.py ticket-list 的 tickets[] 行的必要子集；ticket 为兼容别名）。 */
export interface BoardRow {
  id?: string
  ticket?: string
  stage?: string
  stage_state?: string
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

/** 缺行 alert 的 spec 构造：target 带 N，N 变化 = 新 key = 重响；N 不变 = 冷却。 */
export function makeMissingRowsSpec(project: string, missing: number, level: 'warn' | 'redline' = 'warn'): {
  rule: string; target: string; level: 'warn' | 'redline'; title: string; detail: string
} {
  return {
    rule: 'ledger_missing_rows',
    target: `${project}:${missing}`,
    level,
    title: `账本缺 ${missing} 行（project ${project}）`,
    detail: 'ledger 是派生投影；对账以看板为真源补齐状态，并把「曾缺 N 条」本身记为 alertable event。',
  }
}

/**
 * 缺行计数（纯函数）：看板各票应有序（此处用看板行数下界近似——精确「应有序」需要票内
 * timeline，那要走查询/依赖 worker，违反 visibility-list 纪律；故口径=**看板有票而账本
 * 零覆盖**或**账本 idem 总数低于看板在飞票数**的保守计数，宁少报不多报）。
 */
export function countMissingRows(board: BoardRow[], ledgerRows: LedgerRow[]): number {
  if (board.length === 0) return 0
  // 覆盖 = 账本里有一行把该票带到看板当前状态（票有行但落后于看板 = 仍算缺行）。
  const covered = new Set(ledgerRows.map(r => `${r.ticket}|${ledgerState(r)}`))
  return board.filter(b => !covered.has(`${boardId(b)}|${boardState(b)}`)).length
}
