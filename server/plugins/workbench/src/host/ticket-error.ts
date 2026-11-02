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
 * t261102-12 named read states (see NAMED_READ_KINDS): a located cause that refreshing
 * cannot fix as jitter is 409 without `retryable`. The panel names it and stops
 * re-polling; no caller may treat it as a slow read.
 *
 * 纯函数无 IO，供 tests/ 单测直跑；node.ts 的 sendTicketShowError 消费它。
 */

export interface TicketShowHttpVerdict {
  status: number
  retryable: boolean
}

/** t261102-12: the named read states. `no_poller` = the queue this ticket polls has no
 *  live poller; `workflow_task_failed` = the server reports the workflow task in a failed
 *  state, which is deterministic (retrying the read cannot help). Neither is a timeout. */
export const NAMED_READ_KINDS = ['no_poller', 'workflow_task_failed'] as const

/** True when `kind` is one of the named read states (never a transient retry). */
export function isNamedReadKind(kind: unknown): boolean {
  return typeof kind === 'string' && (NAMED_READ_KINDS as readonly string[]).includes(kind)
}

export function ticketShowHttpVerdict(kind: unknown): TicketShowHttpVerdict {
  if (kind === 'not_found') return { status: 404, retryable: false }
  if (kind === 'terminal') return { status: 410, retryable: false }
  if (isNamedReadKind(kind)) return { status: 409, retryable: false }
  if (kind === 'transient') return { status: 503, retryable: true }
  return { status: 500, retryable: false }
}

/** ticket show 失败响应的装配产物：HTTP 状态 + JSON body（形状固定，face 可缺席）。 */
export interface TicketShowErrorReply {
  status: number
  body: {
    ok: false
    error: string
    kind: string
    retryable?: true
    face?: Record<string, unknown>
    read_face?: Record<string, unknown>
  }
}

/**
 * ticket show 失败响应的统一装配（t260919-02 在 KI-025 分级上只加 face 键）：
 *  - HTTP 级裁定仍走 ticketShowHttpVerdict 单点（terminal 恒 410、刷新无效口径
 *    零退化——face 只加载荷不改级别，绝不把终态伪装成可重试）；
 *  - face 仅「plain dict」且 kind=terminal 才附带：直读桥失败/超时/畸形（null/
 *    非对象/数组）→ 回执**无 face 键**，UI 按纯错误提示降级（不渲染失败面板）；
 *    非终态 kind 一律不附带（失败面是终态专属语义，不随错误扩散）。
 *  - t261102-12 `readFace` rides in its OWN key `read_face` (never the terminal `face`
 *    slot): the named read states carry the engine's read face (the queue this ticket
 *    polls and its live poller count, or the workflow-task failure cause) so the panel
 *    names the state. Same honesty rule: only a plain object rides, only for the named
 *    read kinds — an unreachable or malformed face leaves the key out and the panel
 *    says the cause is unavailable.
 */
export function ticketShowErrorReply(
  s: { error?: unknown; kind?: unknown } | null,
  id: string,
  face?: unknown,
  readFace?: unknown,
): TicketShowErrorReply {
  const kind = typeof s?.kind === 'string' ? s.kind : ''
  const msg = String(s?.error ?? (id ? `工单读取失败：${id}` : '工单读取失败'))
  const v = ticketShowHttpVerdict(kind)
  const faceOk = kind === 'terminal'
    && face !== null && typeof face === 'object' && !Array.isArray(face)
  const readFaceOk = isNamedReadKind(kind)
    && readFace !== null && typeof readFace === 'object' && !Array.isArray(readFace)
  return {
    status: v.status,
    body: {
      ok: false,
      error: msg,
      kind: kind || 'internal',
      ...(v.retryable ? { retryable: true } : {}),
      ...(faceOk ? { face: face as Record<string, unknown> } : {}),
      ...(readFaceOk ? { read_face: readFace as Record<string, unknown> } : {}),
    },
  }
}
