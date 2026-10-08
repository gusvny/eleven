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
import { isReriseRow, sweepInstruction } from './board-sweep.ts'

/** 值得唤醒的行：状态迁移类（带 stage/stage_state 的行）。纯 kind 行（如 engine 维护）不醒。
 *
 * t261003-04 缺陷 B：零发现的周期巡检行（dispatcher scan / inspection dedup 回执）
 * 也带 stage/stage_state，旧判定让它们把执行器白白叫醒——真机 261002 实测 17.4% 的
 * 项目账行是 dispatcher-scan、全部 '0 tickets, 0 pending'、全部投递了 wake（15 秒一簇
 * 的空醒）。行**留在审计账里**（本函数只影响 wake 门，不碰账本），只是不再值醒；
 * 真迁移（任何真实 stage/stage_state 推进）照醒。 */
export function worthWaking(row: LedgerRow): boolean {
  if (!Boolean(row.stage || row.stage_state)) return false
  return !isZeroFindingPeriodicRow(row)
}

/** 零发现周期行识别（纯函数，只压「确认零发现」的行——判不出零发现就照旧醒，保守
 *  不静默吞掉真信号）：
 *  - dispatcher scan 收尾行（workflows.py DispatcherScanWorkflow `_ledger_note('scan',
 *    'done', 'Scan report: N tickets, M pending (...)')`）：tickets 与 pending **都为 0**
 *    才算零发现；有票/有待决 = 有真内容，照醒；
 *  - inspection spawn dedup 回执（inspection_flow.py `spawn/done`，reason 带
 *    `deduped=true`）：本期没起新票（去重复用旧票），对执行器零增量——不值醒；
 *    `deduped=false`（真起了票）照醒——新票自己的迁移随后也会醒，不靠这行。 */
export function isZeroFindingPeriodicRow(row: LedgerRow): boolean {
  const reason = row.reason ?? ''
  if (row.stage === 'scan') {
    const m = /(\d+) tickets, (\d+) pending/.exec(reason)
    return m !== null && m[1] === '0' && m[2] === '0'
  }
  if (row.stage === 'spawn') {
    return /\bdeduped=true\b/.test(reason)
  }
  return false
}

/** steer 仅红线急停；本票的 wake 恒为 queue（红线急停面留给后续票接真源时启用）。 */
export function wakeMode(level: 'info' | 'warn' | 'redline'): 'queue' | 'steer' {
  return level === 'redline' ? 'steer' : 'queue'
}

/** Brief builder (human-readable: the delta + the request pointer, saying why the
 *  executor was woken).
 *  t261008-39 (host order 261008): the brief UNCONDITIONALLY carries the standing
 *  board-sweep instruction (with or without new transitions) — the executor sweeps
 *  the whole board on wake and returns a bounded disposition per decision-state
 *  ticket; reriseRows (long-stuck re-raise synthetic rows) get their own named
 *  section. reriseRows affect the text only; the dedupe bookkeeping is owned by
 *  splitLoopRows' per-row force. */
export function buildBrief(project: string, rows: LedgerRow[], selfLockTarget: string | null, reriseRows: LedgerRow[] = [], reriseThresholdMinutes: number | null = null): string {
  const lines: string[] = []
  lines.push(sweepInstruction(reriseThresholdMinutes ?? 30))
  lines.push(`[watchdog wake · ${project}] The event ledger has new content — read the brief and move the work forward:`)
  for (const r of rows.slice(0, 20)) {
    lines.push(`- ${r.ticket} ${r.stage ?? ''}→${r.stage_state ?? ''}${r.reason ? ` (${r.reason})` : ''}`)
  }
  if (rows.length > 20) lines.push(`…and ${rows.length - 20} more rows — read the ledger delta`)
  for (const r of reriseRows.slice(0, 20)) {
    const real = typeof r.raw?.real_ticket === 'string' ? r.raw.real_ticket : r.ticket
    lines.push(`- [re-raise] ${real}: ${r.reason}`)
  }
  if (reriseRows.length > 20) lines.push(`…and ${reriseRows.length - 20} more re-raises`)
  if (selfLockTarget) lines.push(`Note: you have a self-initiated, unanswered pending item (${selfLockTarget}) — it waits on you; handle it or file it as a request.`)
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
  /**
   * t261005-02 self-heal: cancel one live turn, retaining pending inbox work (host
   * SessionCancelRequest). accepted=true = cancellation admitted; accepted=null = the
   * face is absent/unbounded-timeout (explicitly unsupported — the self-heal step
   * holds, never retries); accepted=false = the host named a refusal (error carried).
   * Failure-mode checklist carried over from the wake path: host absent → explicit
   * unsupported (no silent degrade); bounded wait → Promise.race timeout (the host
   * cancel is synchronous, no AbortSignal parameter — no signal is claimed);
   * error → named receipt; no retry loop (one attempt per park is enforced by the
   * decision core, not here). Cancel-specific: accepted:false = named refusal; an
   * already-finished turn is a host-side no-op refusal and surfaces as accepted=false.
   */
  cancelTurn?(sessionId: string): Promise<{ accepted: boolean | null; error?: string }>
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

/**
 * 决策态集合（t261003-15）：进入这些 stage_state 的迁移**无条件醒**——旁路 idem 规则
 * （①）与疑似自规则（②）。取词来源（单一真源，禁止另抄第二份清单）：
 *  - `blocked` / `awaiting-human`：server/tools/ticket.py 的 stage_state 枚举
 *    （L18/L166：running | awaiting | awaiting-human | blocked）——「等机器重跑」与
 *    「等人决策」的进度态；
 *  - `refused`：引擎闸回执 landing='refused'（client.py 门面拒收语义）——防御性纳入，
 *    引擎哪天把拒收落成账行原词也零漏醒。
 * 漂移锁：tests/wake-decision-bypass-t261003-15.test.mjs 从引擎源码抽取 _mark /
 * _ledger_note 的 state 字面量 + ticket.py 枚举，逐词断言分类，未知词即红——引擎
 * 词表一变本集合必须被自觉更新，不能悄悄漂。
 * **规则③（上一份简报未消化）对本集合照常生效**：决策态旁路的是 ①②，不旁路 ③——
 * 对着未消化的队列无条件重发会把自喂循环的门重新打开（t260929-04 的教训）；被 ③
 * 压下时 verdict reason 点名未消化简报，状态面仍可答「为什么不醒」。
 * stall / self_lock 不是账本态而是红线 alert 规则（core.ts），它们的拍以
 * level='redline' 进 wakeExecutor——红线拍同样整体旁路 ①②（见 wakeExecutor）。
 */
export const DECISION_STAGE_STATES: ReadonlySet<string> = new Set(['blocked', 'refused', 'awaiting-human'])

/** 决策态行判定（纯函数；无 stage_state 的行不是决策态——判不出就不旁路，保守）。 */
export function isDecisionRow(row: LedgerRow): boolean {
  return row.stage_state !== undefined && DECISION_STAGE_STATES.has(row.stage_state)
}

function stageKeyOf(row: LedgerRow): string {
  return `${row.stage ?? ''}|${row.stage_state ?? ''}`
}

/** 值醒行 × 自醒排除（纯函数；mem.fresh 原地累积，其余只读）。
 *  bypass=true（红线拍 / 决策态行）跳过 ① idem 与 ② 疑似自，但保留同窗去重与
 *  fresh 记账——决策行醒后照样进 briefed，下一拍普通迁移仍受 ② 约束，循环有界不变。 */
export function splitLoopRows(rows: LedgerRow[], mem: WakeMemory, bypass = false): { wakeable: LedgerRow[]; presumed: LedgerRow[] } {
  const wakeable: LedgerRow[] = []
  const presumed: LedgerRow[] = []
  for (const row of rows) {
    const key = stageKeyOf(row)
    // t261008-39: a re-raise synthetic row forces its own row through (the explicit
    // raw.rerise marker only, see isReriseRow) — the batch-level bypass is NOT
    // widened by its presence: normal already-briefed rows in the same batch keep
    // their guards ①② suppression.
    const force = bypass || isDecisionRow(row) || isReriseRow(row)
    const fresh = mem.fresh.get(row.ticket) ?? new Set<string>()
    if (!force && mem.briefed.get(row.ticket)?.has(key)) continue // ① idem：简报讲过的迁移不讲第二遍
    if (!force && fresh.has(key)) continue // 同一观察窗内的重复行（重投/同批重复）不重复计数
    if (!force && mem.briefed.has(row.ticket) && fresh.size === 0) {
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
  /** t261003-15 additive：worthWaking 后进入自醒筛的行数（verdict「考虑了几行」；
   *  零发现周期行在此计数之前就被 worthWaking 滤掉，不计入）。 */
  considered?: number
}

/**
 * 唤醒决策 + 执行（io 注入）。纪律逐条落在这一个函数里，测试逐条钉：
 *  - 无值得醒的行 → 不醒（不每行醒）；
 *  - 自醒排除（splitLoopRows：idem + 疑似自 + 有界例外，见 WakeMemory 注）；
 *  - 决策态旁路（t261003-15）：blocked/refused/awaiting-human 行与红线拍（level=
 *    'redline'，即 stall / self_lock 拍）跳过 idem 与疑似自——需要人/执行器决策的态
 *    绝不被自喂排除吞掉；规则③（未消化简报）仍生效，理由见 DECISION_STAGE_STATES 注；
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
  reriseRows: LedgerRow[] = [],
  reriseThresholdMinutes: number | null = null,
): Promise<WakeOutcome> {
  const worthies = rows.filter(worthWaking)
  // t261003-15：决策态行（或红线拍）旁路 ①②；规则③不旁路（见 DECISION_STAGE_STATES 注）。
  // t261008-39 (review R2): re-raise synthetic rows do NOT take part in the
  // batch-level bypass computation (they carry their own per-row force) — otherwise
  // one synthetic row in the batch would dismantle guards ①② for all normal rows.
  const bypass = level === 'redline' || worthies.some(r => isDecisionRow(r) && !isReriseRow(r))
  const { wakeable, presumed } = splitLoopRows(worthies, mem, bypass)
  const considered = worthies.length
  const presumedMeta = { presumedSelf: mem.presumedSelfRows, presumedSelfDetail: mem.presumedSelfDetail, considered }
  if (wakeable.length === 0) {
    if (presumed.length > 0) {
      return { woke: false, reason: `全是疑似自产行，不醒（自喂循环排除：${mem.presumedSelfDetail}）`, accepted: null, mode: null, ...presumedMeta }
    }
    return { woke: false, reason: '无状态迁移类行（不值得唤醒——不做每行唤醒的傻轮询）', accepted: null, mode: null, considered }
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
  // t261008-39: re-raise synthetic rows travel the same delivery channel (no second
  // channel) but pass splitLoopRows via their per-row force (never swallowed by ①②);
  // after an accepted prompt only NORMAL rows are recorded into briefed — the
  // synthetic keys are unique per episode by construction, and recording them would
  // grow mem.briefed without bound.
  const normalWakeable = wakeable.filter(r => !isReriseRow(r))
  const reriseWakeable = wakeable.filter(isReriseRow)
  const brief = buildBrief(project, normalWakeable, selfLockTarget, reriseWakeable, reriseThresholdMinutes)
  try {
    const r = await io.prompt(sessionId, brief, mode)
    if (r.accepted) {
      // 简报投出 = 这些 stage_key 都进了简报：fresh 并入 briefed，开始新一轮观察窗。
      for (const row of normalWakeable) {
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

/**
 * Synthetic wake-source rows (t261004-29): an answered request and a cleared alert are
 * wake-worthy events. They are shaped as ledger rows so they flow through the existing
 * `wakeExecutor` path unchanged — worthWaking gate, self-feed guard ①②③, queue-mode
 * delivery — never rebuilt beside it. They are NOT written to any ledger; they exist
 * only as wake inputs (the event ledger stays engine-owned, single writer).
 *
 * - `requestAnswerRow`: `ticket` embeds the request id and `answerRequest` already
 *   rejects a second answer of the same request, so one answered request wakes at most
 *   once through this path (guard ① would suppress an exact repeat anyway).
 * - `alertClearedRow`: `ticket` embeds the alert dedupe key AND the fire-episode id
 *   (the alert's last raise timestamp). A re-fired alert starts a new episode id, so
 *   its later clear is a fresh ticket and wakes again — one wake per (alert key × fire
 *   episode), not one per memory lifetime.
 */
export function requestAnswerRow(project: string, requestId: string, by = 'host', detail = ''): LedgerRow {
  const clean = String(requestId || '')
  return {
    idem: `request-answer:${clean}`,
    project,
    ticket: `request-${clean}`,
    seq: 0,
    stage: 'request',
    stage_state: 'answered',
    reason: `request ${clean} answered by ${by}${detail ? `: ${detail}` : ''}`,
    raw: {},
  }
}

export function alertClearedRow(project: string, alertKey: string, episodeAtMs: number, detail = ''): LedgerRow {
  const episode = Number.isFinite(episodeAtMs) ? episodeAtMs : 0
  return {
    idem: `alert-clear:${alertKey}:${episode}`,
    project,
    ticket: `alert-${alertKey}-${episode}`,
    seq: 0,
    stage: 'alert',
    stage_state: 'cleared',
    reason: `alert ${alertKey} cleared (last raised at ${new Date(episode).toISOString()})${detail ? `: ${detail}` : ''}`,
    raw: {},
  }
}

/** Wake receipt (t261004-29): every push-path wake attempt answers "was a wake
 *  attempted, did it wake, and why" — `attempted:false` always carries the reason. */
export interface WakeReceipt {
  at: number
  source: 'request-answer' | 'alert-clear'
  request_id: string | null
  attempted: boolean
  woke: boolean
  reason: string
  mode: 'queue' | 'steer' | null
  accepted: boolean | null
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
