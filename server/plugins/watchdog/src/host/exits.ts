/**
 * 两个出口（t260928-28，纯函数核 + 注入投递面）——请求与提醒的边界永不混装。
 *
 * 出口 (a) wake：经宿主会话服务向该项目的 executor 会话投递 `mode:'queue'` 一轮简报
 *   （dsh SessionPromptRequest；steer 仅红线急停）。三条去重纪律：
 *     ① 行级 idem 去重（tailer 已做）；
 *     ② worth-waking 过滤——只对「状态迁移类」行醒，**绝不每行都醒**（宿主明拒的傻轮询）；
 *     ③ 已消化判定——上一份简报的队列项还在 = 它还没消化，不重发（队列镜像可读，
 *        accepted:true 回执 + 队列项消失 = 「不丢消息」的证明面）。
 * 出口 (b) call the human：alert 落 watchdog/<key>.alerts.jsonl（append-only，含
 *   level/dedupe key/时刻/指向）；页面通知+声音由面板消费状态面字段发声（一声就够）。
 * **未答复的 alert 永不自动变成决定**——本模块没有任何「默认动作执行」路径。
 */

import type { LedgerRow } from './ledger-tail.ts'
import type { AlertSpec } from './alert-rules.ts'

/** 值得唤醒的行：状态迁移类（带 stage/stage_state 的行）。纯 kind 行（如 engine 维护）不醒。 */
export function worthWaking(row: LedgerRow): boolean {
  return Boolean(row.stage || row.stage_state)
}

/** steer 仅红线急停；本票的 wake 恒为 queue（红线急停面留给后续票接真源时启用）。 */
export function wakeMode(level: 'info' | 'warn' | 'redline'): 'queue' | 'steer' {
  return level === 'redline' ? 'steer' : 'queue'
}

/** 简报构造（人说人话：增量 + 请求指针，说清「为什么叫你」）。 */
export function buildBrief(project: string, rows: LedgerRow[], selfLockTarget: string | null): string {
  const lines = [`【watchdog 唤醒 · ${project}】事件账有新内容，请读简报推进：`]
  for (const r of rows.slice(0, 20)) {
    lines.push(`- ${r.ticket} ${r.stage ?? ''}→${r.stage_state ?? ''}${r.reason ? `（${r.reason}）` : ''}`)
  }
  if (rows.length > 20) lines.push(`…另有 ${rows.length - 20} 行，读账本增量`)
  if (selfLockTarget) lines.push(`注意：你有一个自己发起、尚未被答复的挂起项（${selfLockTarget}）——它在等你，先处理或落成请求。`)
  return lines.join('\n')
}

/** 投递面（node.ts 用宿主会话服务实现；测试注入桩）。 */
export interface WakeIo {
  /** 投递一轮输入；返回 accepted 回执。 */
  prompt(sessionId: string, text: string, mode: 'queue' | 'steer'): Promise<{ accepted: boolean; error?: string }>
  /** 队列镜像：该会话当前待消化项数（读不到 = null，显式 no-signal）。 */
  queueDepth(sessionId: string): Promise<number | null>
}

export interface WakeOutcome {
  woke: boolean
  reason: string
  accepted: boolean | null
  mode: 'queue' | 'steer' | null
}

/**
 * 唤醒决策 + 执行（io 注入）。纪律逐条落在这一个函数里，测试逐条钉：
 *  - 无值得醒的行 → 不醒（不每行醒）；
 *  - 队列里已有未消化简报（depth>0）→ 不重发（已消化判定；depth 读不到=null → 照发但
 *    outcome.reason 点名「队列态不可读」，不静默假设已消化）；
 *  - 会话 id 空 → 显式不可执行（不代建 executor 会话，身份是后续票）。
 */
export async function wakeExecutor(
  io: WakeIo,
  project: string,
  sessionId: string,
  rows: LedgerRow[],
  selfLockTarget: string | null,
  level: 'info' | 'warn' | 'redline' = 'info',
): Promise<WakeOutcome> {
  const wakeable = rows.filter(worthWaking)
  if (wakeable.length === 0) {
    return { woke: false, reason: '无状态迁移类行（不值得唤醒——不做每行唤醒的傻轮询）', accepted: null, mode: null }
  }
  if (sessionId === '') {
    return { woke: false, reason: '该项目未声明 executor_session——不代建（身份/槽位是后续票），显式不作为', accepted: null, mode: null }
  }
  const depth = await io.queueDepth(sessionId)
  if (depth !== null && depth > 0) {
    return { woke: false, reason: `上一份简报仍未消化（队列深 ${depth}）——不重发`, accepted: null, mode: null }
  }
  const mode = wakeMode(level)
  const brief = buildBrief(project, wakeable, selfLockTarget)
  try {
    const r = await io.prompt(sessionId, brief, mode)
    if (r.accepted) return { woke: true, reason: depth === null ? '已投递（队列态不可读，照发——不静默假设已消化）' : '已投递', accepted: true, mode }
    return { woke: false, reason: `投递被拒：${r.error ?? 'unknown'}`, accepted: false, mode }
  } catch (e) {
    return { woke: false, reason: `投递通路失败：${e instanceof Error ? e.message : String(e)}`, accepted: false, mode }
  }
}

/** alert 落账行形状（alerts.jsonl 一行一条；去重状态由它重放重建）。 */
export function alertRecord(spec: AlertSpec, key: string, at: number, nightMuted: boolean): Record<string, unknown> {
  return {
    at, key, rule: spec.rule, target: spec.target, level: spec.level,
    title: spec.title, detail: spec.detail ?? '', night_muted: nightMuted,
    // 未答复 ≠ 已答：记录只有追加，没有任何「已答/自动处置」状态位——提醒不变成决定。
  }
}
