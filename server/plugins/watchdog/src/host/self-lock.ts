/**
 * 自锁检测（t260928-28，纯函数核；t261004-08 escalation-threshold rework）。
 *
 * 「它在等自己」：executor 会话正等一个**它自己发的**审批/请求（或它自己立的 gate）
 * —— t261004-08 (this ticket): `waiting_on_itself` fires once the ask has been
 * pending past the waiting_minutes threshold (pointing at the request); inside the
 * threshold the new verdict `waiting` is status-face only, no alert.
 *
 * 证据源纪律（不静默降级）：宿主侧待办交互面（approval/user-questions per session）
 * 由注入的 provider 提供；**provider 不可用 = 显式 `unknown` + reason**，绝不冒充
 * 「没有自锁」。
 *
 * t261004-08 review C1 ruling: escalation adds no parallel rule — self_lock stays one
 * rule, one key, at most one alert per ask (dedupe key = request id, 12h cooldown;
 * different asks alert independently).
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
  /**
   * t261004-08 raised-at (ledger row `at`; absent = treated as just-raised — the
   * escalation threshold never fires early off a missing timestamp; late beats wrong).
   */
  raisedAt?: number
}

/**
 * t261004-08 verdict semantics:
 *  - `waiting`: an own unanswered ask exists, pending time still inside the
 *    escalation threshold — status face only, no alert;
 *  - `waiting_on_itself`: past the threshold — redline alert (which still raises the
 *    wake level to redline as before);
 *  - missing timestamp counts as just-raised (never escalates early).
 */
export type SelfLockState = 'none' | 'waiting' | 'waiting_on_itself' | 'unknown'

export interface SelfLockVerdict {
  state: SelfLockState
  reason: string
  target: string | null
  since: number | null
}

/** Escalation threshold options (default 0 = immediate escalation, for legacy callers/tests). */
export interface SelfLockOpts {
  /** Milliseconds; the ask must be pending longer than this to escalate to waiting_on_itself. */
  waitingThresholdMs?: number
}

/** Pure verdict: an own pending ask → `waiting` inside the threshold, `waiting_on_itself` past it. */
export function detectSelfLock(
  pending: PendingInteraction[] | null,
  executorSessionId: string,
  nowMs: number,
  unavailableReason?: string,
  opts: SelfLockOpts = {},
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
    const raisedAt = typeof hit.raisedAt === 'number' && Number.isFinite(hit.raisedAt) ? hit.raisedAt : nowMs
    const thresholdMs = typeof opts.waitingThresholdMs === 'number' && opts.waitingThresholdMs > 0 ? opts.waitingThresholdMs : 0
    const ageMs = nowMs - raisedAt
    const baseReason = `executor session ${executorSessionId} is waiting on its own ${hit.kind} (${hit.target})`
    if (ageMs < thresholdMs) {
      const remainMin = Math.ceil((thresholdMs - ageMs) / 60_000)
      return {
        state: 'waiting',
        reason: `${baseReason} — pending ${Math.floor(ageMs / 60_000)} min, escalation threshold not passed yet (about ${remainMin} min left; status face only, no alert)`,
        target: hit.target,
        since: raisedAt,
      }
    }
    const waited = ageMs >= 60_000 ? `pending about ${Math.floor(ageMs / 60_000)} min` : 'just raised'
    return {
      state: 'waiting_on_itself',
      reason: `${baseReason} — it is waiting on itself, ${waited} (threshold of ${Math.round(thresholdMs / 60_000)} min passed)`,
      target: hit.target,
      since: raisedAt,
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
