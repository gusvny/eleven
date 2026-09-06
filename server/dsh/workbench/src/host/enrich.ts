/**
 * enrich.ts —— 列表 enrichment 的行级派生纯函数（t260905-07）。
 *
 * 口径（review 附条件3 钉死，fixture 与实现以此为准，防各执一词）：
 *   - title 非空票**跳过裁剪**（不白裁——展示选择函数 title 本就优先）；
 *   - show 失败（row/showResult 缺）/body 非字符串/裁不出首句 → undefined
 *     （字段缺省=行卡回退裸编号，降级自然，不造空串脏字段）；
 *   - 裁剪口径=firstSentenceOf（./src/client/ticket-list-model.ts 单一事实，列表
 *     enrichment 与详情头部两条通道一个口径）。
 */

import { firstSentenceOf } from '../client/ticket-list-model.ts'

/**
 * 无标题票的首句派生字段值。row=列表行（含 title），showResult=ticket show 应答
 * （result.body 为正文）。返回 undefined=不下发（字段缺省）。
 */
export function deriveTitleOrFirst(row: unknown, showResult: unknown): string | undefined {
  if (row === null || typeof row !== 'object') return undefined
  const title = (row as Record<string, unknown>).title
  if (typeof title === 'string' && title.trim() !== '') return undefined
  if (showResult === null || typeof showResult !== 'object') return undefined
  const body = (showResult as Record<string, unknown>).body
  if (typeof body !== 'string') return undefined
  return firstSentenceOf(body) ?? undefined
}
