/**
 * approve-note.ts —— KI-004（t260901-22）：人审 approve 签字的 note 拼接（纯函数层）。
 *
 * 工单台 approve 弹层的 note 由两段组成：
 *   ① 自动摘要 buildApproveSummary（审批意见统计，只读）；
 *   ② 审批人手输的自由备注（可空，KI-004 新增）。
 * 有备注时随 sign 进不可变事件历史；无备注时行为与现状逐字节一致。
 *
 * 纯函数、无 React/IO 依赖：smoke/approve-note.mjs 用 node ≥22.18 type-stripping
 * 直跑（模式同 epics-model.ts）；不允许把本逻辑内联回 index.tsx——畸形输入断言
 * 必须落在 smoke 文件里。
 */

/**
 * 拼接 sign 用 note。
 * - remark 空/纯空白 → 只返回 summary.trim()（空备注不污染历史口径）；
 * - 两者皆有 → summary.trim() + '\n\n' + remark.trim()（备注独立成段）；
 * - 两者皆空 → ''。
 * 外部输入只做 trim 与分段，不校验/改写内容（纯文本进历史）。
 */
export function buildApproveNote(summary: string, remark: string): string {
  const s = (summary ?? '').trim()
  const r = (remark ?? '').trim()
  if (s === '') return r
  if (r === '') return s
  return `${s}\n\n${r}`
}
