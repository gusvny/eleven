/**
 * usage-model.ts —— 用量降级/可疑态的 UI 提示合成纯函数（t260917-05「可辨」）。
 *
 * 背景：agent-usage 端点的降级信息原来只进 hover title（UsageSummaryLine 的
 * 「tokens —」），「会话格式不认识（疑似 dsh 版本不匹配）」这种统计不可信态在
 * 页面上与普通「还没跑过」不可区分 = 零值观感。本模块把「要不要警示、警示什么」
 * 收成可单测的纯函数；渲染位（UsageSummaryLine / AgentLogsTab）只消费其结论。
 * 日志面同族警示走 agent-logs 的 sessionNote 注记（AgentLogsTab meta 行渲染）。
 */

/** agent-usage 端点结果的形状切片（client 侧宽松镜像，缺字段=未置位，畸形不抛）。 */
export interface UsageSuspectFace {
  exists?: boolean
  suspect?: boolean
  suspectFiles?: string[]
  suspectDetail?: string
  reason?: string
}

/**
 * 用量区可见警示文案（非 hover-only）；null=维持既有呈现（tokens — / 正常行）。
 * - exists:true 且 suspect → S1 混合态：totals 来自好文件，坏文件也必须可见；
 * - exists:false 且 suspect → S1 全灭：统计值不可信；
 * - exists:false 且 suspectFiles 非空 → S3：发现集空但目录有未入统计的会话样文件；
 * - 其余（普通没跑过/历史单）→ null，不虚报。
 */
export function usageSuspectHint(usage: UsageSuspectFace | undefined | null): string | null {
  if (!usage || typeof usage !== 'object') return null
  if (usage.exists === true) {
    return usage.suspect === true
      ? '⚠ 部分会话记录格式不认识（疑似 dsh 版本不匹配），该部分未计入'
      : null
  }
  if (usage.suspect === true) {
    return '⚠ 会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信'
  }
  if (Array.isArray(usage.suspectFiles) && usage.suspectFiles.length > 0) {
    return '⚠ 发现未入统计的会话文件（名字/布局与本版本解析面对不上，疑似 dsh 版本不匹配）'
  }
  return null
}

/** 悬停明细：S1 逐文件人话（suspectDetail）优先，其次端点 reason。 */
export function usageSuspectTitle(usage: UsageSuspectFace | undefined | null): string | undefined {
  if (!usage || typeof usage !== 'object') return undefined
  return usage.suspectDetail ?? usage.reason
}
