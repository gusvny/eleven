/**
 * ticket-error.ts —— ticket show 失败的 HTTP 分级裁定（KI-025，t260903-06）。
 *
 * kind 的产线：client.py（五出口穷举分级）→ ticket.py QueryError(kind) →
 * tools_registry.call 异常口并入回执 → node.ts 以本模块裁定 HTTP 形态：
 *   not_found → 404（唯一「不存在」语义，只能由 NotFoundFailure 触发）
 *   terminal  → 410（终态票永久不可得，刷新无效）
 *   transient → 503 + retryable（瞬时故障，UI 保留快照静默重试）
 *   缺失/未知 → 500（绝不 404——kind 断链时宁可报「读取失败」不可谎报不存在）
 *
 * 纯函数无 IO，供 tests/ 单测直跑；node.ts 的 sendTicketShowError 消费它。
 */

export interface TicketShowHttpVerdict {
  status: number
  retryable: boolean
}

export function ticketShowHttpVerdict(kind: unknown): TicketShowHttpVerdict {
  if (kind === 'not_found') return { status: 404, retryable: false }
  if (kind === 'terminal') return { status: 410, retryable: false }
  if (kind === 'transient') return { status: 503, retryable: true }
  return { status: 500, retryable: false }
}
