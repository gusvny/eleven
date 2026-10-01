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
  /** 投递一轮输入；返回 accepted 回执。requestId = 本次投递自铸的幂等标识
   *  （宿主队列项以 rpcId 回显它；镜像面据此认领「我们的」未消化项）。 */
  prompt(sessionId: string, text: string, mode: 'queue' | 'steer'): Promise<{ accepted: boolean; error?: string; requestId?: string }>
  /** 队列镜像：该会话当前待消化项数（读不到 = null，显式 no-signal）。 */
  queueDepth(sessionId: string): Promise<number | null>
  /** 我们上一份简报是否仍未消化（按 requestId→rpcId 精确认领；review C2：
   *  队列里有人类/其它来源输入时不能用总深度冒充「我们的没消化」）。
   *  null = 镜像不可读（显式）。缺省未实现 = 回落 queueDepth 语义。 */
  ourBriefPending?(sessionId: string, requestId: string): Promise<boolean | null>
  /** 我们未消化简报的队列项 id（updateQueue 主动消化/运维用；null = 不可见或不可读）。 */
  ourPendingItemId?(sessionId: string, requestId: string): Promise<string | null>
  /** 镜像/通路状态串（status 面 additive 键 queue_mirror；缺省 null）。 */
  transportState?(): string | null
  /** 全终态：镜像消费循环等后台面的收口钩子（node.ts dispose 链调用）。 */
  dispose?(): void | Promise<void>
}

/**
 * 自醒排除的记忆（t260929-04 新失败模式）：executor 自己的动作也写同一本账，
 * 不排除就是自喂循环。行内无 actor 字段（engine/base.py 的账本行形状已核实），
 * 引擎侧改 schema 越界——排除规则落在消费侧、确定性、可测：
 *  ① idem 排除：进过简报的 stage_key 永不重醒（尾部去重之外的第二道闸）；
 *  ② 疑似自排除：简报点名过的票 T，它的**第一个**新 stage_key 迁移视为对那份
 *     简报的自身响应，不醒（计数 presumed_self_rows，响亮不静默）；同一票的
 *     **第二个**新 stage_key 再醒——多步真进展不被吞掉；
 *  ③ 简报没点名过的票（executor 顺手直修别票）照醒一次——此后它进了简报名单，
 *     下一次迁移被 ② 压住：循环有界（每张新票至多多醒一次），绝不无限自喂。
 */
export interface WakeMemory {
  /** ticket -> 已进过简报的 stage_key 集。 */
  briefed: Map<string, Set<string>>
  /** ticket -> 上份简报之后观察到的新 stage_key 集（首见即疑似自产行）。 */
  fresh: Map<string, Set<string>>
  /** 上一份被接受简报的 requestId（镜像认领用）。 */
  lastRequestId: string | null
  /** 疑似自产行累计（status 面 presumed_self_rows）。 */
  presumedSelfRows: number
  /** 最近一次疑似自排除的人类可读说明（status 面证据）。 */
  presumedSelfDetail: string | null
}

export function freshWakeMemory(): WakeMemory {
  return { briefed: new Map(), fresh: new Map(), lastRequestId: null, presumedSelfRows: 0, presumedSelfDetail: null }
}

function stageKeyOf(row: LedgerRow): string {
  return `${row.stage ?? ''}|${row.stage_state ?? ''}`
}

/** 值醒行 × 自醒排除（纯函数；mem.fresh 原地累积，其余只读）。 */
export function splitLoopRows(rows: LedgerRow[], mem: WakeMemory): { wakeable: LedgerRow[]; presumed: LedgerRow[] } {
  const wakeable: LedgerRow[] = []
  const presumed: LedgerRow[] = []
  for (const row of rows) {
    const key = stageKeyOf(row)
    const fresh = mem.fresh.get(row.ticket) ?? new Set<string>()
    if (mem.briefed.get(row.ticket)?.has(key)) continue // ① idem：简报讲过的迁移不讲第二遍
    if (fresh.has(key)) continue // 同一观察窗内的重复行（重投/同批重复）不重复计数
    if (mem.briefed.has(row.ticket) && fresh.size === 0) {
      // ② 首个新迁移 = 对上份简报的自身响应（疑似自），压下但响亮计数。
      fresh.add(key)
      mem.fresh.set(row.ticket, fresh)
      mem.presumedSelfRows += 1
      mem.presumedSelfDetail = `${row.ticket} ${key}（简报点名后的首个迁移——疑似它自己的动作）`
      presumed.push(row)
      continue
    }
    fresh.add(key)
    mem.fresh.set(row.ticket, fresh)
    wakeable.push(row)
  }
  return { wakeable, presumed }
}

export interface WakeOutcome {
  woke: boolean
  reason: string
  accepted: boolean | null
  mode: 'queue' | 'steer' | null
  /** 自醒排除的观测（additive；旧消费面不读不破）。 */
  presumedSelf?: number
  presumedSelfDetail?: string | null
  /** 本次被接受简报的 requestId（core 记进 WakeMemory.lastRequestId）。 */
  requestId?: string | null
}

/**
 * 唤醒决策 + 执行（io 注入）。纪律逐条落在这一个函数里，测试逐条钉：
 *  - 无值得醒的行 → 不醒（不每行醒）；
 *  - 自醒排除（splitLoopRows：idem + 疑似自 + 有界例外，见 WakeMemory 注）；
 *  - 已消化判定（review C2 口径）：能按 requestId 认领时只认「我们的简报还在不在」
 *    （别人的队列输入不拦我们）；认领面缺失回落队列深度；镜像不可读（null）→
 *    照发但 reason 点名「队列态不可读」，绝不静默假设已消化；
 *  - 会话 id 空 → 显式不可执行（不代建 executor 会话，身份是后续票）。
 */
export async function wakeExecutor(
  io: WakeIo,
  project: string,
  sessionId: string,
  rows: LedgerRow[],
  selfLockTarget: string | null,
  level: 'info' | 'warn' | 'redline' = 'info',
  mem: WakeMemory = freshWakeMemory(),
): Promise<WakeOutcome> {
  const { wakeable, presumed } = splitLoopRows(rows.filter(worthWaking), mem)
  const presumedMeta = { presumedSelf: mem.presumedSelfRows, presumedSelfDetail: mem.presumedSelfDetail }
  if (wakeable.length === 0) {
    if (presumed.length > 0) {
      return { woke: false, reason: `全是疑似自产行，不醒（自喂循环排除：${mem.presumedSelfDetail}）`, accepted: null, mode: null, ...presumedMeta }
    }
    return { woke: false, reason: '无状态迁移类行（不值得唤醒——不做每行唤醒的傻轮询）', accepted: null, mode: null }
  }
  if (sessionId === '') {
    return { woke: false, reason: '该项目未声明 executor_session——不代建（身份/槽位是后续票），显式不作为', accepted: null, mode: null, ...presumedMeta }
  }
  // 已消化判定：先按 requestId 精确认领；没有认领面再退回队列深度。
  let noSignal = false
  if (typeof io.ourBriefPending === 'function' && mem.lastRequestId !== null) {
    const ours = await io.ourBriefPending(sessionId, mem.lastRequestId)
    if (ours === true) {
      return { woke: false, reason: `上一份简报仍未消化（我们的队列项 ${mem.lastRequestId} 还在）——不重发`, accepted: null, mode: null, ...presumedMeta }
    }
    if (ours === null) noSignal = true // 镜像不可读：照发，但点名
  } else {
    const depth = await io.queueDepth(sessionId)
    if (depth !== null && depth > 0) {
      return { woke: false, reason: `上一份简报仍未消化（队列深 ${depth}）——不重发`, accepted: null, mode: null, ...presumedMeta }
    }
    if (depth === null) noSignal = true
  }
  const mode = wakeMode(level)
  const brief = buildBrief(project, wakeable, selfLockTarget)
  try {
    const r = await io.prompt(sessionId, brief, mode)
    if (r.accepted) {
      // 简报投出 = 这些 stage_key 都进了简报：fresh 并入 briefed，开始新一轮观察窗。
      for (const row of wakeable) {
        const set = mem.briefed.get(row.ticket) ?? new Set<string>()
        set.add(stageKeyOf(row))
        mem.briefed.set(row.ticket, set)
        mem.fresh.delete(row.ticket)
      }
      if (r.requestId) mem.lastRequestId = r.requestId
      return { woke: true, reason: noSignal ? '已投递（队列态不可读，照发——不静默假设已消化）' : '已投递', accepted: true, mode, requestId: r.requestId ?? null, ...presumedMeta }
    }
    return { woke: false, reason: `投递被拒：${r.error ?? 'unknown'}`, accepted: false, mode, ...presumedMeta }
  } catch (e) {
    return { woke: false, reason: `投递通路失败：${e instanceof Error ? e.message : String(e)}`, accepted: false, mode, ...presumedMeta }
  }
}

/** alert 落账行形状（alerts.jsonl 一行一条；去重状态由它重放重建）。 */
export function alertRecord(spec: AlertSpec, key: string, at: number, nightMuted: boolean): Record<string, unknown> {
  return {
    at, key, rule: spec.rule, target: spec.target, level: spec.level,
    title: spec.title, detail: spec.detail ?? '', night_muted: nightMuted,
    // 实例隔离域（t261001-19）：scope 随账落盘（缺省不落，保持历史行形状）——
    // 审计面能答「这条报警是哪个 DSH_HOME 实例响的」。
    ...(spec.scope !== undefined && spec.scope !== '' ? { scope: spec.scope } : {}),
    // 未答复 ≠ 已答：记录只有追加，没有任何「已答/自动处置」状态位——提醒不变成决定。
  }
}
