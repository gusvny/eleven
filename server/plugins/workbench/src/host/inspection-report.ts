/**
 * inspection-report —— 巡检落账报告只读端点（t260926-05）宿主半计算核。
 *
 * GET /sandbar-workbench/api/wf/tickets/<id>/inspection-report?path=<report_path>
 * 数据源=引擎落账件 out/inspection/inspection-<实例>-<期>.json（face 原样 JSON，
 * inspection_flow.write_inspection_report_impl 落盘）。票面只有 report_path 指针；
 * 本端点把指针变成「可读出路」：读文件 → reportDigest 缩进式可读摘要（与
 * 浏览器渲染契约同源：src/client/inspection-report-model.ts 单点，不各写一套）。
 *
 * 借 /file 通道（ticket-time-file.ts）fail-closed 风格的取舍（票方案 rev2 故障清单c）：
 *   - 沿用：路径问题一律 200 + 人话 reason（不是服务器错，绝不 5xx/不抛）；
 *     非 GET 由路由通道 405；只读刚性（node:fs 只有 readFile/realpath 原语）。
 *   - 舍弃：git 版本梯子（settle/base/current、在飞拒绝）——报告是活性 out/ 产物，
 *     时刻版语义不适用；二进制判别降为 NUL/U+FFFD 兜底（输入白名单已是 .json 文本）。
 *   - 新增（/file 模型没有的故障模式）：绝对/相对路径归一 + 仓库根包含检查 +
 *     **realpath 符号链接逃逸拒绝**（先 realpath 再比对，链接出去的 out/ 也拦）；
 *     扩展名白名单 .json；256 KB 封顶——**超限不 JSON.parse**（截断文本可能断在
 *     JSON 半截），改走 reason + 8KB 原文摘录（客户端 <pre> 原样转义渲染）；
 *     解析失败 → reason + 原文（≤上限时）；digest 行数封顶（巨报告不刷爆 DOM）。
 * 资源终态：纯 readFile/realpath，无定时器/监听/长驻句柄；任何路径（正常/
 * fail-closed/fs 异常）都自然终止，无遗留资源。
 */

import { readFile, realpath } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { reportDigest } from '../client/inspection-report-model.ts'

/** 报告文件字节封顶：超限只回摘录不解析（截断 JSON 解析=半截对象冒充报告）。 */
export const INSPECTION_REPORT_MAX_BYTES = 256 * 1024
/** 超限/解析失败时随回执带的原文摘录字节封顶。 */
const RAW_EXCERPT_BYTES = 8 * 1024
/** digest 行数封顶（reportDigest 同参，双保险）。 */
const DIGEST_MAX_LINES = 2000

export interface InspectionReportResult {
  ok: boolean
  /** ok=true：解析出的报告 JSON 原样（客户端兜底/自行消化用）。 */
  report?: unknown
  /** ok=true：摘要行（缩进 depth + 安全文本）。 */
  digest?: { depth: number; text: string }[]
  /** fail 时的人话原因（fail-closed：永不缺）。 */
  reason?: string
  /** 超限/解析失败时的原文摘录（≤8KB，客户端转义 <pre> 渲染，绝不 parse）。 */
  raw?: string
}

/** 只读报告读取器：任何失败路径都回 {ok:false, reason}，绝不抛。 */
export async function readInspectionReportFile(repoRoot: string, rawPath: unknown): Promise<InspectionReportResult> {
  if (typeof rawPath !== 'string' || rawPath.trim() === '') {
    return { ok: false, reason: 'path 必传（报告 report_path）' }
  }
  if (!rawPath.endsWith('.json')) {
    return { ok: false, reason: `只读 .json 报告文件（收到: ${rawPath.slice(0, 200)}）` }
  }
  // 绝对路径（引擎 report_path=绝对串）与仓内相对路径都归一到 repoRoot 下判定。
  // realpath 先行：符号链接逃逸（repo 内链接指向 repo 外真身）在这里被拦——
  // 比对的是真身不是字面路径。文件不存在 → ENOENT 人话。
  let rootReal: string
  try {
    rootReal = await realpath(repoRoot)
  } catch {
    return { ok: false, reason: `仓库根不可达: ${repoRoot}` }
  }
  const p = resolve(repoRoot, rawPath)
  let real: string
  try {
    real = await realpath(p)
  } catch (err: unknown) {
    const code = (err as { code?: string })?.code
    return { ok: false, reason: code === 'ENOENT' ? '报告文件不存在（期未落账或路径已失效）' : `报告路径不可达: ${String(err instanceof Error ? err.message : err)}` }
  }
  if (real !== rootReal && !real.startsWith(rootReal + sep)) {
    return { ok: false, reason: '报告路径不在仓库根内（含符号链接逃逸形态），拒绝读取' }
  }
  let buf: Buffer
  try {
    buf = await readFile(real)
  } catch (err: unknown) {
    return { ok: false, reason: `报告读取失败: ${String(err instanceof Error ? err.message : err)}` }
  }
  if (buf.length > INSPECTION_REPORT_MAX_BYTES) {
    return {
      ok: false,
      reason: `报告文件 ${buf.length} 字节，超过 ${INSPECTION_REPORT_MAX_BYTES} 上限——不解析（截断 JSON 不当报告），只回原文摘录`,
      raw: buf.toString('utf8', 0, RAW_EXCERPT_BYTES),
    }
  }
  const text = buf.toString('utf8')
  if (text.includes('\u0000') || text.includes('\uFFFD')) {
    return { ok: false, reason: '报告文件含 NUL/坏字节（非纯 UTF-8 文本），拒绝解析' }
  }
  let json: unknown
  try {
    json = JSON.parse(text)
  } catch (err: unknown) {
    return { ok: false, reason: `报告 JSON 解析失败: ${String(err instanceof Error ? err.message : err)}`, raw: text }
  }
  return { ok: true, report: json, digest: reportDigest(json, DIGEST_MAX_LINES) }
}
