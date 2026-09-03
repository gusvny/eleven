/**
 * stale-check.ts —— host 陈旧响应分类纯函数（t260902-03）。不 import react / 无 DOM，
 * smoke 裸 node 直跑（review 非阻塞意见 1：响应分类逻辑必须可单测）。
 *
 * 降级口径（有意降级，注释写明不静默绕过）：
 *   - 非 2xx、JSON 解析失败、响应缺 stale 字段、stale 非布尔、带 error 字段
 *     → 全部 {stale:false}，不显横幅、调用方不抛错。理由=看守自身不得成为新报错源；
 *     其中带 error 的响应=指纹全缺（部署形态异常），不属于陈旧提醒范畴。
 *   - 仅 stale 严格 === true 才置位。
 */

export interface BuildInfoVerdict {
  stale: boolean
  /** 端点带人话 error（指纹全缺=部署形态异常），与「陈旧」区分，供调试观测。 */
  error?: string
}

/** 分类 build-info 响应（status + 原始文本）。不抛错——任何畸形输入都落 {stale:false}。 */
export function classifyBuildInfoResponse(status: number, bodyText: string): BuildInfoVerdict {
  if (status < 200 || status >= 300) return { stale: false }
  let parsed: unknown
  try {
    parsed = JSON.parse(bodyText)
  } catch {
    return { stale: false }
  }
  if (typeof parsed !== 'object' || parsed === null) return { stale: false }
  const result = (parsed as Record<string, unknown>).result
  if (typeof result !== 'object' || result === null) return { stale: false }
  const r = result as Record<string, unknown>
  if (typeof r.error === 'string') return { stale: false, error: r.error }
  return { stale: r.stale === true }
}
