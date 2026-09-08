/**
 * project-anchor.ts —— 工单台 host 项目锚解析器（KI-057 / t260907-11，S1 面）。
 *
 * 六处静态锚（diff 仓锚 / 审批意见锚 / epics 目录锚 / 证据目录锚 / 引擎 CLI 路径 /
 * repo 本尊）曾全部静态解析自 apply 闭包的 repo——外部项目工单的 worktree/立项单/
 * 审批意见/证据全被按引擎仓根判界（防穿越闸把跨项目泳道判成「越出仓库根」）。
 * 本模块把「请求层按项目键解析项目根」收口成单一纯函数（find 注入可单测），
 * 供 node.ts 各路由逐请求取锚。
 *
 * 取舍清单（create_plan gen1 R1-① 评审定稿体例，实现照单落）：
 * - key 缺省/空白：回落 fallback（config.repo→SUYOU_REPO→DEFAULT_REPO 全链不变），
 *   source='default'——兼容 viewProject 为空与老调用，sandbar 自身票行为不变。
 * - key 已注册：root=primaryDir(findProject(key))（suyou-projects.ts dirs[0]），
 *   source='project'。primaryDir 空串=注册条目残缺 → 显式 502（不回落：回落=
 *   数据串仓，比报错糟）。
 * - key 真未注册/形状非法：显式 400（同 tickets 路由白名单先例）——不静默回落，
 *   否则 diff 面闸会回「越出仓库根」，把根因（键解析失败）错引成穿越。
 * - 隔离条目 / 注册表装载失败：findProject throw → 显式 502 透传原文（不吞、
 *   不降级；隔离项目回落默认仓=读 sandbar 数据，违背隔离语义）。
 * - env 覆盖链红线（工单规格「旧 env 覆盖链保留」）：SUYOU_EPICS_DIR /
 *   SUYOU_EVIDENCE_DIR / SUYOU_EPIC_NEXT_DIR 三族**仅 source='default' 时生效**
 *   （anchorEpicsDir / anchorEvidenceBase / anchorEpicNextDir 内收口）——项目根
 *   路径不走 env（env 指向引擎仓，per-project 时会串味）；默认仓路径 env 行为
 *   与既有完全一致（测试桩不受影响）。
 * - 可观测性：解析结果经 resolvedMark() 挂进响应（source/key/root），回落原因由
 *   调用方落 host log——报错精确，不静默。
 */

import { join } from 'node:path'
import { findProject, primaryDir, type ProjectEntry } from '../../../../suyou-projects.ts'

export type ProjectAnchor =
  | { ok: true; root: string; source: 'project' | 'default'; key: string | null }
  | { ok: false; status: 400 | 502; error: string }

/** find 注入缝：单测传桩，生产用真注册表装载器（缺省参数）。 */
export function resolveProjectAnchor(
  key: unknown,
  fallbackRepo: string,
  find: (k: string) => ProjectEntry | undefined = findProject,
): ProjectAnchor {
  // 非 string（畸形 query 不会出现，但票面 t.project 可能是任意 JSON 值）→ 视同缺省。
  const k = typeof key === 'string' ? key.trim() : ''
  if (k === '') {
    return { ok: true, root: fallbackRepo, source: 'default', key: null }
  }
  let p: ProjectEntry | undefined
  try {
    p = find(k)
  } catch (err) {
    // 隔离条目/注册表装载失败都从这走：透传人话原文，显式 502。
    return { ok: false, status: 502, error: String(err instanceof Error ? err.message : err) }
  }
  if (p === undefined) {
    return { ok: false, status: 400, error: `未知项目 key：'${k}'（projects.yaml 注册表无此项）` }
  }
  const root = primaryDir(p)
  if (typeof root !== 'string' || root === '') {
    return { ok: false, status: 502, error: `项目 '${k}' 注册条目缺主目录（dirs 为空），拒绝回落默认仓（防数据串仓）` }
  }
  return { ok: true, root, source: 'project', key: k }
}

/** 响应可观测标记：六面路由 200 体统一挂 resolved={source,key,root}。 */
export function resolvedMark(a: Extract<ProjectAnchor, { ok: true }>): { source: string; key: string | null; root: string } {
  return { source: a.source, key: a.key, root: a.root }
}

/**
 * env 覆盖闸（红线收口单点）：仅默认仓锚透出 env 值；项目锚恒 null（env 属引擎仓
 * 域，per-project 时透出会把各项目目录串味）。三族 env 走这一个口，不散落。
 */
export function anchorEnv(a: Extract<ProjectAnchor, { ok: true }>, name: string): string | null {
  if (a.source !== 'default') return null
  const v = process.env[name]
  return typeof v === 'string' && v !== '' ? v : null
}

/** 立项单目录：默认仓锚=SUYOU_EPICS_DIR 优先（epics.ts resolveEpicsDir 同款先例）；项目锚=<项目根>/notes/epics。 */
export function anchorEpicsDir(a: Extract<ProjectAnchor, { ok: true }>): string {
  return anchorEnv(a, 'SUYOU_EPICS_DIR') ?? join(a.root, 'notes', 'epics')
}
/** 证据归档基目录：默认仓锚=SUYOU_EVIDENCE_DIR 优先（node.ts 既有先例）；项目锚=<项目根>/.suyou/evidence。 */
export function anchorEvidenceBase(a: Extract<ProjectAnchor, { ok: true }>): string {
  return anchorEnv(a, 'SUYOU_EVIDENCE_DIR') ?? join(a.root, '.suyou', 'evidence')
}

/** epic-next 作业根目录：默认仓锚=SUYOU_EPIC_NEXT_DIR 优先（epic-next.ts resolveEpicNextDir 同款）；项目锚=<项目根>/.suyou/epic-next。 */
export function anchorEpicNextDir(a: Extract<ProjectAnchor, { ok: true }>): string {
  return anchorEnv(a, 'SUYOU_EPIC_NEXT_DIR') ?? join(a.root, '.suyou', 'epic-next')
}
