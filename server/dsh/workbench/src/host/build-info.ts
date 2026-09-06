/**
 * build-info.ts —— 插件陈旧看守的指纹侧（t260902-03 立，t260905-07 KI-052 根治扩展）。
 *
 * 病根：console（dsh webServer）进程启动时加载 host 半代码（node.ts + src/host/*.ts）；
 * 工单合并落账后磁盘代码已更新，进程仍跑旧码（t260901-01 透传 / t260901-26 squash
 * 回放 / metrics 路由一日三咬，均因 3099 未重启）。浏览器端无从感知 → 度量报错、
 * squash 票 diff 消失。本模块提供「启动指纹 vs 磁盘指纹」比对的数据侧：
 * node.ts apply 时固化 bootHash（仅首次解析，Promise 单例，后续 apply 重放不覆盖
 * ——R3 不变量），/suyou-workbench/api/build-info 现算磁盘指纹返回 stale。
 * KI-052 补刀：看守自身也会内存旧（405 现场=进程启动早于看守代码落盘）——根治面
 * 在客户端握手（src/client/stale-check.ts classifyHandshake 三元组判定矩阵），
 * 本模块为其供同一份清单、同一个指纹函数（同构性由「同一函数」保证，不靠两份
 * 清单人肉同步——gen0 打回①钉死口径）。
 *
 * 指纹算法：FNV-1a 64 位（纯 TS、BigInt 实现）。不用 node:crypto 的理由——本插件
 * 不设 node_modules、node-shims.d.ts 是最小手声明，自实现散列零新增类型面。陈旧
 * 判定只需「内容变→指纹大概率变」，不需要密码学强度；每个文件路径/长度都参与混合，
 * 工程误报窗口可忽略。
 *
 * 故障口径（不抛错、降级到人话）：
 *   - 单个文件读不到 → 记入 missing 继续聚合（陈旧判定只看可读文件的 hash）；
 *   - 全部读不到 → 返回 {error} 人话。端点侧取 stale:false（无法判定=不误报）；
 *     客户端见 error 不显横幅（有意降级：指纹全缺=部署形态异常，不属于陈旧提醒范畴）。
 *   - 用内容 hash 而非 mtime：checkout/合并工具触碰时间戳不误报（review 拍板口径）。
 *
 * 清单纪律（t260905-07 改版：动态扫描取代手写清单）：旧 HOST_SOURCE_FILES 手写清单
 * 已实证漏收 project-admin.ts / session-charter.ts / ticket-error.ts（原「漏列新文件
 * 可接受」取舍即本票根治对象，不再沿用）。扫描面钉死：node.ts 入口 + src/host/*.ts
 * + src/client/*.ts(x)（vendor/ 与 *.d.ts 排除），按 rootDir 首次调用时枚举排序固化。
 * 运行期限制（有意取舍）：boot 后清单固定，新增文件须重启 console 才进看守面——
 * 与「重启生效」语义自洽，不算新盲区。
 */

import { readFile } from 'node:fs/promises'
import { readdirSync } from 'node:fs'
import { join } from 'node:path'

/** 插件来源扫描面（相对 repo 根）。client 半纯函数层纳入指纹=client 源码变更同样
 *  可见（信噪比取舍登记：纯 client 变更真实消除链=启动构建+刷新页面，横幅文案
 *  两支分别对应「重启」「刷新」，见 banner-text.ts——防止后续被当 bug 再立案）。 */
const WB_SCAN_DIRS: readonly { dir: string; exts: readonly string[] }[] = [
  { dir: 'server/dsh/workbench/src/host', exts: ['.ts'] },
  { dir: 'server/dsh/workbench/src/client', exts: ['.ts', '.tsx'] },
]

/** 按 repo 根收集来源清单（相对路径，排序固化；node.ts 入口固定首位）。
 *  扫描失败（目录不存在）静默跳过该目录——不抛；全目录皆缺时上游按「全缺失」
 *  口径落 error。 */
export function collectSourceFiles(rootDir: string): string[] {
  const out: string[] = ['server/dsh/workbench/node.ts']
  for (const { dir, exts } of WB_SCAN_DIRS) {
    let names: string[] = []
    try {
      names = readdirSync(join(rootDir, dir))
    } catch {
      continue
    }
    for (const name of [...names].sort()) {
      if (name.endsWith('.d.ts')) continue // 声明面（node-shims.d.ts）不是运行码
      if (name === 'vendor') continue // 三方供给目录，非本插件维护面
      if (exts.some((e) => name.endsWith(e))) out.push(`${dir}/${name}`)
    }
  }
  return out
}

/** 兼容别名（tests/ 既有 import 与 fixture 布点用）：动态清单的当前快照。
 *  仅测试语境消费，生产路径一律走 collectSourceFiles（root 注入）。 */
export function HOST_SOURCE_FILES(rootDir: string): readonly string[] {
  return collectSourceFiles(rootDir)
}

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
  /** 聚合 hash（fnv1a64 迭代混合）；全缺失时 undefined 且带 error。 */
  hash?: string
  /** 成功参与聚合的文件数。 */
  files: number
  /** 读不到、被跳过的文件（相对 repo 根路径）。 */
  missing: string[]
  /** 人话错误（仅全缺失时存在）。 */
  error?: string
}

/** 扫描清单 memo（按 rootDir）：目录枚举一次固化，指纹计算只重复读文件。
 *  boot 单例 / build-info 应答 / 未来注入侧三处同消费，天然同构。 */
/** 扫描清单不 memo（有意取舍）：readdirSync 两个目录成本可忽略，而 memo 会把
 *  「合并落账后新增的来源文件」挡在 disk 指纹之外——运行期漏列盲区（本票根治
 *  对象的变体）。每次现扫目录；boot 侧由 node.ts 单例固化（语义不同：boot 只在
 *  启动取一次）。boot 单例 / build-info 应答 / 未来注入侧三处同消费本函数，天然同构。 */

/**
 * 计算插件来源指纹。rootDir 可注入（fixture 测试用，不真改仓库文件）；
 * files 可显式传清单（测试钉最小面，绕过扫描）。
 * 不抛错——任何 IO 失败都落进 missing/error。
 */
export async function computeHostFingerprint(rootDir: string, files?: readonly string[]): Promise<HostFingerprint> {
  // 清单不 memo（有意取舍）：readdirSync 两个目录成本可忽略，而 memo 会把「合并
  // 落账后新增的来源文件」挡在 disk 指纹之外——运行期漏列盲区（本票根治对象的
  // 变体）。每次现扫目录；boot 侧由 node.ts 单例固化（语义不同：boot 只在启动取）。
  const list = files ?? collectSourceFiles(rootDir)
  const missing: string[] = []
  let count = 0
  let agg = FNV_OFFSET
  const mix = (v: number): void => {
    agg ^= BigInt(v & 0xffff)
    agg = (agg * FNV_PRIME) & U64
  }
  for (const rel of list) {
    try {
      const text = await readFile(join(rootDir, rel), 'utf8')
      // 路径长度 + 内容混合：防「跨文件内容拼接碰撞」（A=「ab」+B=「c」 vs A=「a」+B=「bc」）。
      mix(rel.length)
      for (let i = 0; i < text.length; i++) mix(text.charCodeAt(i))
      mix(text.length)
      count += 1
    } catch {
      missing.push(rel)
    }
  }
  if (count === 0) {
    return {
      files: 0,
      missing,
      error: `插件指纹计算失败：${list.length} 个来源文件全部读不到（部署形态异常）`,
    }
  }
  return { hash: agg.toString(16).padStart(16, '0'), files: count, missing }
}
