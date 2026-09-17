/**
 * session-discovery.ts —— dsh 会话文件「双名发现」单点 helper（t260916-23，epic dsh-upgrade T1）。
 *
 * dsh 0.1.5 把会话落盘文件换名：session.jsonl.zstd → session.v3.jsonl.zstd（zstd 压缩；
 * 格式 v3）。workbench 读侧（usage/live/logs）原先按旧字面名定位会话，升级后引擎会
 * 「找不到会话」、回退踩同一坑。本模块是 workbench 侧唯一旧名字面锚点：
 *   - SESSION_FILE_NAMES：两代文件名（[0]=旧代=当前生产，[1]=新代 0.1.5+；平局旧名优先按此序）；
 *   - existingSessionFilesIn：目录内两代名字层发现（isFile 守卫，只 stat 不读内容）；
 *   - pickNewestSessionFile：同一会话目录两代并存取 mtime 最新一份（平局旧名优先）。
 * 与引擎 py 侧对称物行为逐条一致：server/engine/agent_activities.py 的
 * SESSION_FILE_NAMES / _iter_session_files / _pick_newest_session（改一侧必须对拍另一侧）。
 * 只做名字层发现与路径返回，不读 zstd 内容、不引压缩依赖——内容解析仍走既有
 * decompressSession 通路；dsh 自身的落盘与解析不在本票范围（零行为变更：只有旧名
 * 文件时发现集与改前一致）。
 */

import { basename, join } from 'node:path'
import { stat } from 'node:fs/promises'

/** 两代会话文件名（[0]=旧代、[1]=新代；同 mtime 平局时旧名优先即按此序）。 */
export const SESSION_FILE_NAMES = ['session.jsonl.zstd', 'session.v3.jsonl.zstd'] as const

export type SessionFileName = (typeof SESSION_FILE_NAMES)[number]

/** 代序（旧名=0、新名=1、未知名字=排在最后——平局比较用，语义同 py 侧）。 */
function genOf(fp: string): number {
  const idx = SESSION_FILE_NAMES.indexOf(basename(fp) as SessionFileName)
  return idx >= 0 ? idx : SESSION_FILE_NAMES.length
}

/** 目录内两代会话文件的名字层发现：isFile 守卫（同名目录不算）、stat 失败的候选跳过。 */
export async function existingSessionFilesIn(dir: string): Promise<string[]> {
  const found: string[] = []
  for (const name of SESSION_FILE_NAMES) {
    const fp = join(dir, name)
    try {
      if ((await stat(fp)).isFile()) found.push(fp)
    } catch { /* 无此代文件，跳过（名字层发现的常态） */ }
  }
  return found
}

/** 同一会话目录两代并存取 mtime 最新一份；平局取旧名（与「只有旧名」现状对齐）；
 *  stat 不可读的候选跳过；全不可读返回 null（调用方走既有零会话降级）。 */
export async function pickNewestSessionFile(paths: readonly string[]): Promise<string | null> {
  let bestPath: string | null = null
  let bestMtime = -Infinity
  let bestGen = Number.MAX_SAFE_INTEGER
  for (const fp of paths) {
    let mtime: number
    try {
      mtime = (await stat(fp)).mtimeMs
    } catch { continue /* stat 失败的候选跳过（与 py 侧一致） */ }
    const gen = genOf(fp)
    if (mtime > bestMtime || (mtime === bestMtime && gen < bestGen)) {
      bestPath = fp
      bestMtime = mtime
      bestGen = gen
    }
  }
  return bestPath
}
