/**
 * workspace.ts —— 工单「工作区」展示的纯函数（M14，t260822-m14-detail-refactor）。
 *
 * 数据模型（M4/M5 ticket.py，见 docs/design/工单工作流台设计.md §3）：
 *   - workspace: {type: 'worktree'|'dir', path} | null   —— M4 新字段：
 *     type=worktree → 代码泳道（.worktrees/<短slug>）；type=dir → 非 git 工单的
 *     隔离目录（/tmp/suyou-ws/<工单id>，cleanup 类模板约定）；null=未登记。
 *   - worktree: string                                   —— 旧字段：泳道路径（''=无泳道）。
 *
 * 本文件统一「工作区」的显示语义（列表「工作区」列 + 详情抽屉基本信息 + 行悬停
 * title），纯函数无 DOM 依赖，浏览器半与冒烟（smoke/workspace.mjs）共用同一代码。
 * 优先级：workspace(worktree) > workspace(dir) > 旧 worktree 字段 > 主树（无独立空间）。
 */

export interface WorkspaceInfo {
  /** 工作区类型：worktree=代码泳道 / dir=非 git 隔离目录 / main=主树直改（无独立空间）。 */
  type: 'worktree' | 'dir' | 'main'
  /** 显示标签：worktree=短 slug（路径末段）；dir=目录路径；main=「主树」。 */
  label: string
  /** 完整路径（main 为空串；展示 title 用）。 */
  path: string
}

export interface WorkspaceInput {
  workspace?: { type?: string; path?: string } | null
  worktree?: string
}

/** 路径末段（短 slug 展示：.worktrees/t260822-x → t260822-x）。 */
function shortSlug(path: string): string {
  const segs = path.split('/').filter(Boolean)
  return segs[segs.length - 1] ?? path
}

/**
 * 由工单行/详情的工作空间字段计算展示信息。
 * 旧工单（workspace=null）回退读 worktree 字段；两者皆无 → 主树（数据道/审读/回归
 * 等直接改主树的工单，设计 v0.3 模板 lane: main）。
 */
export function workspaceInfoOf(t: WorkspaceInput | null | undefined): WorkspaceInfo {
  const ws = t?.workspace
  if (ws && ws.type === 'worktree' && typeof ws.path === 'string' && ws.path !== '') {
    return { type: 'worktree', label: shortSlug(ws.path), path: ws.path }
  }
  if (ws && ws.type === 'dir' && typeof ws.path === 'string' && ws.path !== '') {
    return { type: 'dir', label: ws.path, path: ws.path }
  }
  const wt = t?.worktree
  if (typeof wt === 'string' && wt !== '') {
    return { type: 'worktree', label: shortSlug(wt), path: wt }
  }
  return { type: 'main', label: '主树', path: '' }
}

/** 行内/元信息的紧凑文本（title 与 aria 用；含类型前缀，如「泳道 t260822-x」「目录 /tmp/…」「主树」）。 */
export function workspaceTextOf(t: WorkspaceInput | null | undefined): string {
  const info = workspaceInfoOf(t)
  if (info.type === 'main') return info.label
  if (info.type === 'worktree') return `泳道 ${info.label}`
  return `目录 ${info.label}`
}
