/**
 * 巡检报告读取（M6，t260821-m6-scan-expand）—— suyou-workbench 宿主半。
 *
 * 只读 `server/dsh/temporal-poc/out/scan/` 下**文件名序最新**的一份 `<YYYY-MM-DD>.json`
 * （DispatcherScanWorkflow 每轮巡检落盘，同日重跑覆盖当日文件）。
 *
 * 口径：
 *   - 文件名白名单 `YYYY-MM-DD.json`（防读到目录里任何非报告文件）；
 *   - 目录取不到 / 无报告 / 解析失败都走 `reason` 人话返回，不抛错——
 *     台面「巡检报告」区据此降级显示（report=null 不是错误态，是「还没跑过」）。
 */

import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'

/** 报告文件名白名单（与 write_scan_report 的落盘命名同款）。 */
export const SCAN_FILE_RE = /^\d{4}-\d{2}-\d{2}\.json$/

export interface ScanReportResult {
  /** 命中的报告文件名（无报告=null）。 */
  file: string | null
  /** 解析出的报告 JSON（无/坏=null）。 */
  report: any | null
  /** 人话降级原因（有报告时为空串）。 */
  reason: string
}

export async function readLatestScanReport(scanDir: string): Promise<ScanReportResult> {
  let names: string[]
  try {
    names = await readdir(scanDir)
  } catch {
    return { file: null, report: null, reason: '巡检报告目录不存在（dispatcher-scan 尚未跑过）' }
  }
  const files = names.filter(n => SCAN_FILE_RE.test(n)).sort()
  if (files.length === 0) {
    return { file: null, report: null, reason: '暂无巡检报告（等 schedule 下一轮，或手动 trigger）' }
  }
  const file = files[files.length - 1]
  try {
    const report = JSON.parse(await readFile(join(scanDir, file), 'utf8'))
    return { file, report, reason: '' }
  } catch (err) {
    return {
      file, report: null,
      reason: `报告解析失败：${String(err instanceof Error ? err.message : err)}`,
    }
  }
}
