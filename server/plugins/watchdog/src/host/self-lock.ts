/**
 * 自锁检测（t260928-28，纯函数核）。
 *
 * 「它在等自己」：executor 会话正等一个**它自己发的**审批/请求（或它自己立的 gate）
 * ——不等 stall 超时，立刻报 `waiting_on_itself`（指向对应请求），设计稿验收动作第三条。
 *
 * 证据源纪律（不静默降级）：宿主侧待办交互面（approval/user-questions per session）
 * 由注入的 provider 提供；**provider 不可用 = 显式 `unknown` + reason**，绝不冒充
 * 「没有自锁」（S1-probe 未落地前的默认 provider 就返回 unknown，探针结果决定后续票
 * 是否接真源）。
 */

export interface PendingInteraction {
  /** 挂起项的发起方（哪个会话/身份立的这个审批或请求）。 */
  raisedBy: string
  /** 挂起项的类型（approval / user-question / plan-confirm …）。 */
  kind: string
  /** 挂起项的指向（票号/请求 id/gate 名，供 alert 指路）。 */
  target: string
  /** 目标会话是否仍在跑（running=false + 有 pending = 它没事干光等，自锁信号更强）。 */
  sessionRunning: boolean
}

export type SelfLockState = 'none' | 'waiting_on_itself' | 'unknown'

export interface SelfLockVerdict {
  state: SelfLockState
  reason: string
  target: string | null
  since: number | null
}

/** 纯判定：executor 会话的 pending 里存在「自己立的」→ waiting_on_itself。 */
export function detectSelfLock(
  pending: PendingInteraction[] | null,
  executorSessionId: string,
  nowMs: number,
  unavailableReason?: string,
): SelfLockVerdict {
  if (pending === null) {
    return {
      state: 'unknown',
      reason: unavailableReason ?? '宿主侧待办交互面不可读（provider 未接入）——显式 unknown，不冒充「没有自锁」',
      target: null,
      since: nowMs,
    }
  }
  const hit = pending.find(p => p.raisedBy === executorSessionId)
  if (hit) {
    return {
      state: 'waiting_on_itself',
      reason: `executor 会话 ${executorSessionId} 正在等一个它自己发起的 ${hit.kind}（${hit.target}）——它在等自己，不等停摆超时`,
      target: hit.target,
      since: nowMs,
    }
  }
  // 未归属行（t260929-08）：raisedBy 空 = 账里读到了但不知道谁发起——自锁判定不认空归属
  // （绝不冒充匹配，也绝不冒充「没有自锁」），显式点名计数，人看了知道去补归属。
  const unattributed = pending.filter(p => typeof p.raisedBy !== 'string' || p.raisedBy === '').length
  if (unattributed > 0) {
    return {
      state: 'none',
      reason: `pending 里 ${unattributed} 条挂起请求缺发起方归属（raised_by 空）——自锁只认非空归属，这几条不参与匹配（显式点名，不是「确认没有自锁」）`,
      target: null,
      since: nowMs,
    }
  }
  return { state: 'none', reason: '', target: null, since: nowMs }
}
