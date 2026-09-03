/**
 * build-info.ts —— host 陈旧看守的指纹侧（t260902-03，一日三咬根治）。
 *
 * 病根：console（dsh webServer）进程启动时加载 host 半代码（node.ts + src/host/*.ts）；
 * 工单合并落账后磁盘代码已更新，进程仍跑旧码（t260901-01 透传 / t260901-26 squash
 * 回放 / metrics 路由一日三咬，均因 3099 未重启）。浏览器端无从感知 → 度量报错、
 * squash 票 diff 消失。本模块提供「启动指纹 vs 磁盘指纹」比对的数据侧：
 * node.ts apply 时固化 bootHash（仅首次解析，Promise 单例，后续 apply 重放不覆盖
 * ——R3 不变量），/suyou-workbench/api/build-info 现算磁盘指纹返回 stale。
 *
 * 指纹算法：FNV-1a 64 位（纯 TS、BigInt 实现）。不用 node:crypto 的理由——本插件
 * 不设 node_modules、node-shims.d.ts 是最小手声明（node-shims.d.ts 不在本工单写集，
 * 不能为它加声明），自实现散列零新增类型面。陈旧判定只需「内容变→指纹大概率变」，
 * 不需要密码学强度；每个文件路径/长度都参与混合，工程误报窗口可忽略。
 *
 * 故障口径（不抛错、降级到人话）：
 *   - 单个文件读不到 → 记入 missing 继续聚合（陈旧判定只看可读文件的 hash）；
 *   - 全部读不到 → 返回 {error} 人话。端点侧取 stale:false（无法判定=不误报）；
 *     客户端见 error 不显横幅（有意降级：指纹全缺=部署形态异常，不属于陈旧提醒范畴）。
 *   - 用内容 hash 而非 mtime：checkout/合并工具触碰时间戳不误报（review 拍板口径）。
 *
 * 清单纪律（手写 HOST_SOURCE_FILES）：新增 host 文件必然伴随 node.ts 或既有 host
 * 文件的 import 变更，hash 仍会动，漏列新文件可接受——不为此加动态扫描机制。
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

/** host 半来源清单：node.ts 入口 + src/host/ 全部现存模块（相对 repo 根）。 */
export const HOST_SOURCE_FILES: readonly string[] = [
  'server/dsh/workbench/node.ts',
  'server/dsh/workbench/src/host/agent-live.ts',
  'server/dsh/workbench/src/host/agent-logs.ts',
  'server/dsh/workbench/src/host/agent-usage.ts',
  'server/dsh/workbench/src/host/build-info.ts',
  'server/dsh/workbench/src/host/changes.ts',
  'server/dsh/workbench/src/host/epic-next.ts',
  'server/dsh/workbench/src/host/epics.ts',
  'server/dsh/workbench/src/host/metrics.ts',
  'server/dsh/workbench/src/host/scan-report.ts',
]

const FNV_OFFSET = 0xcbf29ce484222325n
const FNV_PRIME = 0x100000001b3n
const U64 = 0xffffffffffffffffn

/** FNV-1a 64 位（纯 TS）。字符串逐 UTF-16 码元参与混合，0x 前缀 16 位 hex。 */
export function fnv1a64(text: string): string {
  let h = FNV_OFFSET
  for (let i = 0; i < text.length; i++) {
    h ^= BigInt(text.charCodeAt(i))
    h = (h * FNV_PRIME) & U64
  }
  return h.toString(16).padStart(16, '0')
}

export interface HostFingerprint {
  /** 聚合 hash（fnv1a64 迭代混合，见 computeHostFingerprint）；全缺失时 undefined 且带 error。 */
  hash?: string
  /** 成功参与聚合的文件数。 */
  files: number
  /** 读不到、被跳过的文件（相对 repo 根路径）。 */
  missing: string[]
  /** 人话错误（仅全缺失时存在）。 */
  error?: string
}

/**
 * 计算 host 半指纹。rootDir 可注入（fixture 测试用，不真改仓库文件）。
 * 不抛错——任何 IO 失败都落进 missing/error。
 */
export async function computeHostFingerprint(rootDir: string): Promise<HostFingerprint> {
  const missing: string[] = []
  let files = 0
  let agg = FNV_OFFSET
  const mix = (v: number): void => {
    agg ^= BigInt(v & 0xffff)
    agg = (agg * FNV_PRIME) & U64
  }
  for (const rel of HOST_SOURCE_FILES) {
    try {
      const text = await readFile(join(rootDir, rel), 'utf8')
      // 路径长度 + 内容混合：防「跨文件内容拼接碰撞」（A=「ab」+B=「c」 vs A=「a」+B=「bc」）。
      mix(rel.length)
      for (let i = 0; i < text.length; i++) mix(text.charCodeAt(i))
      mix(text.length)
      files += 1
    } catch {
      missing.push(rel)
    }
  }
  if (files === 0) {
    return {
      files: 0,
      missing,
      error: `host 指纹计算失败：${HOST_SOURCE_FILES.length} 个来源文件全部读不到（部署形态异常）`,
    }
  }
  return { hash: agg.toString(16).padStart(16, '0'), files, missing }
}
