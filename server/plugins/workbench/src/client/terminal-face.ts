/**
 * terminal-face.ts —— 终态失败票详情面板视图模型（t260919-02）纯函数层。
 *
 * 数据链：引擎 ticket-query 终态回执 face 键（client.py _terminal_failure_face，正源=
 * Temporal 终态执行历史回放异常链）→ workbench host 直读桥（node.ts，410 body 附带）
 * → openDetail 捕获 → 本函数把不可信外部输入（face 可能缺失/畸形/半残）裁成可渲染
 * 视图。零 react 依赖，node 裸 import 黑盒单测（tests/t260919-02-terminal-face.mjs）。
 *
 * 诚实纪律（KI-025 家族红线，t260919-02 验收③）：
 *  - 畸形输入全降级（不抛、不编造）：face 缺失/非对象/缺键 → 对应字段显式
 *    「不可得/未知」，绝不猜值补位；
 *  - reason_available=false → reasonNote 显式「原因不可得 + 为何」，执行状态原文
 *    保留（绝不把「查不到原因」渲染成「没有失败」或反之）；
 *  - 本视图零操作语义：消费方（TerminalFailurePanel）不得给终态票任何推进入口。
 */

/** 终态失败面板视图（全部字段可直接渲染，缺数据=显式不可得文案而非空串裸奔）。 */
export interface TerminalFaceView {
  /** Temporal 执行状态原文（FAILED/CANCELED/…；畸形 → '未知'）。 */
  execStatus: string
  /** 失败原因摘要（''=不可得；面板渲染 reasonNote 兜底）。 */
  reason: string
  /** 原因是否可得（false → 面板必须显式呈现 reasonNote 的「原因不可得」说明）。 */
  reasonAvailable: boolean
  /** 原因来源说明 / 原因不可得说明（恒非空：要么说来源要么说为何不可得）。 */
  reasonNote: string
  /** 回执错误原文（诚实口径的锚：终态「刷新无效」文案随面板可见，不只闪提示条）。 */
  receiptError: string
  /** 无快照及为何无（恒非空）。 */
  snapshotNote: string
  /** 最后已知阶段（''=不可得）。 */
  lastStage: string
  /** 最后已知阶段说明（'' 时面板显它，恒非空由引擎面保证、畸形降级兜底）。 */
  lastStageNote: string
  /** 票身份。 */
  ticketId: string
  project: string
  epic: string
  instanceId: string
  period: string
  /** 起跑/终态时刻（引擎本地时区展示串；''=不可得）。 */
  startTimeTxt: string
  closeTimeTxt: string
}

/** 恒定兜底文案（与引擎 face 面语义一致；face 缺失时 UI 侧唯一免责声明源）。 */
export const TERMINAL_FACE_FALLBACKS = {
  execStatus: 'Unknown',
  reasonNote: 'Reason unavailable: failure-face data missing or malformed — not invented',
  snapshotNote: 'No snapshot: a closed workflow no longer runs and no worker answers the snapshot query (deterministic for terminal state, not transient; refreshing will not help)',
  lastStageNote: 'Last known stage unavailable: omitted rather than guessed',
} as const

/** str 消费：非字符串 → ''（畸形降级，不抛）。 */
function strOf(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** epoch 秒消费：正有限数 → 数值，其余 → null（0/负/畸形=不可得）。 */
function tsOf(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null
}

/**
 * 引擎终态回执 face（unknown，可能 null/非对象/半残）+ 回执错误原文 → 可渲染视图。
 * 纯函数：不抛、不编造；缺什么显式写什么。
 */
export function terminalFaceView(face: unknown, receiptError?: unknown): TerminalFaceView {
  const errTxt = strOf(receiptError)
  if (face === null || typeof face !== 'object' || Array.isArray(face)) {
    return {
      execStatus: TERMINAL_FACE_FALLBACKS.execStatus,
      reason: '',
      reasonAvailable: false,
      reasonNote: TERMINAL_FACE_FALLBACKS.reasonNote,
      receiptError: errTxt,
      snapshotNote: TERMINAL_FACE_FALLBACKS.snapshotNote,
      lastStage: '',
      lastStageNote: TERMINAL_FACE_FALLBACKS.lastStageNote,
      ticketId: '',
      project: '',
      epic: '',
      instanceId: '',
      period: '',
      startTimeTxt: '',
      closeTimeTxt: '',
    }
  }
  const f = face as Record<string, unknown>
  const reason = strOf(f.reason)
  const reasonAvailable = f.reason_available === true && reason !== ''
  const lastStage = strOf(f.last_stage)
  return {
    execStatus: strOf(f.exec_status) || TERMINAL_FACE_FALLBACKS.execStatus,
    reason,
    reasonAvailable,
    reasonNote: reasonAvailable
      ? (strOf(f.reason_source) || 'source: Temporal workflow execution failure info')
      : (strOf(f.reason_source) || strOf(f.reason_unavailable_note) || TERMINAL_FACE_FALLBACKS.reasonNote),
    receiptError: errTxt,
    snapshotNote: strOf(f.snapshot_note) || TERMINAL_FACE_FALLBACKS.snapshotNote,
    lastStage,
    lastStageNote: strOf(f.last_stage_note) || TERMINAL_FACE_FALLBACKS.lastStageNote,
    ticketId: strOf(f.ticket_id),
    project: strOf(f.project),
    epic: strOf(f.epic),
    instanceId: strOf(f.instance_id),
    period: strOf(f.period),
    startTimeTxt: strOf(f.start_time_txt),
    closeTimeTxt: strOf(f.close_time_txt),
  }
}
