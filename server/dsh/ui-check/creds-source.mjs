/**
 * creds-source.mjs —— 凭据拷贝源解析（sandbar M1-2，契约《sandbar 项目接入契约 v1》①b）。
 *
 * 读侧唯一真源逻辑的 JS 同构（Python 侧真源 = temporal-poc/agent_activities.py
 * `_resolve_credentials_source`，两侧口径不得漂移）：
 * 1. projectKey 非空且过 key 白名单（suyou-projects.ts PROJECT_KEY_RE 同款，防路径
 *    穿越），且 `<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/credentials.yaml`
 *    是文件 → 用它（per-key 首选）；
 * 2. 否则 legacy 回落：$DSH_HOME/.credentials.yaml → $HOME/.dsh/.credentials.yaml
 *    （=M1-2 前行为，弃用窗口；调用方负责打迁移提示日志）；
 * 3. 两处皆无 → null（不拷贝）。
 *
 * 与照搬实现的取舍（t260901-21 方案故障模式清单）：
 * - env 空串一律视为未设置（不拼相对路径）；SANDBAR_PROJECTS_DIR 相对路径也视为
 *   未设置（Python 侧同口径；TS suyou-projects.ts 的 `??` 不剔空串是有意不带的差异）。
 * - 存在性判定用 isFile：命中同名目录不算，继续回落（capture-lane 旧 existsSync 的
 *   目录误判面不带）。
 * 只做路径解析与存在性判定，不读不解析文件内容（内容由 dsh credentials seam 解析）。
 */

import { statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** 项目 key 白名单：小写字母/数字/中划线（suyou-projects.ts PROJECT_KEY_RE 同款）。 */
export const PROJECT_KEY_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

function isFile(p) {
  try { return statSync(p).isFile() } catch { return false }
}

/** per-key 项目目录根（每次调用现读 env；空串/相对路径视为未设置）。 */
export function perkeyProjectsRoot() {
  const root = process.env.SANDBAR_PROJECTS_DIR || ''
  if (!root || !(root.startsWith('/'))) return join(homedir(), '.sandbar', 'projects')
  return root
}

/**
 * 解析凭据拷贝源；返回绝对路径或 null。projectKey 空/非法 = 跳过 per-key 首查、
 * 仍走 legacy 回落（=M1-2 前行为）。
 */
export function resolveCredentialsSource(projectKey = '') {
  const key = String(projectKey || '').trim()
  if (key && PROJECT_KEY_RE.test(key)) {
    const perkey = join(perkeyProjectsRoot(), key, 'credentials.yaml')
    if (isFile(perkey)) return perkey
  }
  for (const home of [process.env.DSH_HOME || '', join(homedir(), '.dsh')]) {
    if (!home) continue
    const cand = join(home, '.credentials.yaml')
    if (isFile(cand)) return cand
  }
  return null
}

/** projectKey 合法且 src 即 per-key 路径（迁移提示日志的判定，测试亦直用）。 */
export function perkeyIsHit(projectKey, src) {
  const key = String(projectKey || '').trim()
  return Boolean(key) && PROJECT_KEY_RE.test(key) &&
    src === join(perkeyProjectsRoot(), key, 'credentials.yaml')
}
