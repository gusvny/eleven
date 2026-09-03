/**
 * smoke/workspace.mjs —— suyou-workbench M14「工作区」展示纯函数冒烟。
 *
 * 直跑：node smoke/workspace.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖 workspaceInfoOf / workspaceTextOf（src/shared/workspace.ts）：
 *   A. workspace{type:worktree} → 泳道短 slug（路径末段）；path 透传 title 用。
 *   B. workspace{type:dir} → 非 git 工单隔离目录路径（/tmp/suyou-ws/<id>）。
 *   C. workspace 缺/空 → 回退旧 worktree 字段（legacy code-lane 工单）。
 *   D. 两者皆无 → 主树（数据道/审读/回归直改主树的工单，模板 lane: main）。
 *   E. 边界：workspace 缺 type/path、空串、null、undefined → 按优先级兜底不抛错。
 *   F. workspaceTextOf 紧凑文本（行悬停 title 用）：泳道/目录/主树 前缀。
 */

import { workspaceInfoOf, workspaceTextOf } from '../src/shared/workspace.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('A workspace.type=worktree → 泳道短 slug')
{
  const r = workspaceInfoOf({ workspace: { type: 'worktree', path: '.worktrees/t260822-m14-detail-refactor' } })
  ok(r.type === 'worktree' && r.label === 't260822-m14-detail-refactor'
    && r.path === '.worktrees/t260822-m14-detail-refactor', '短 slug=路径末段，path 完整保留')
  const r2 = workspaceInfoOf({ workspace: { type: 'worktree', path: '.worktrees/t260820-bodycolor' } })
  ok(r2.label === 't260820-bodycolor', '常规泳道短 slug')
}

section('B workspace.type=dir → 非 git 隔离目录')
{
  const r = workspaceInfoOf({ workspace: { type: 'dir', path: '/tmp/suyou-ws/t260821-m45-demo-dir' } })
  ok(r.type === 'dir' && r.label === '/tmp/suyou-ws/t260821-m45-demo-dir', 'dir 显示完整隔离目录路径')
}

section('C workspace 缺/空 → 回退旧 worktree 字段（legacy code-lane）')
{
  const r = workspaceInfoOf({ workspace: null, worktree: '.worktrees/t260820-instr-audio' })
  ok(r.type === 'worktree' && r.label === 't260820-instr-audio', 'workspace=null + worktree → 泳道 slug')
  const r2 = workspaceInfoOf({ worktree: '.worktrees/wf-m1' })
  ok(r2.type === 'worktree' && r2.label === 'wf-m1', 'workspace 缺失 + worktree → 泳道 slug')
  const r3 = workspaceInfoOf({ workspace: { type: 'worktree', path: '' }, worktree: '.worktrees/wf-m2' })
  ok(r3.label === 'wf-m2', 'workspace.path 空串 → 回退 worktree（不显示空标签）')
}

section('D 两者皆无 → 主树（lane: main 数据道）')
{
  const r = workspaceInfoOf({ workspace: null, worktree: '' })
  ok(r.type === 'main' && r.label === '主树' && r.path === '', '空 worktree+空 workspace → 主树')
  const r2 = workspaceInfoOf({})
  ok(r2.type === 'main' && r2.label === '主树', '空对象 → 主树')
  const r3 = workspaceInfoOf(undefined)
  ok(r3.type === 'main' && r3.label === '主树', 'undefined → 主树（不抛错）')
  const r4 = workspaceInfoOf(null)
  ok(r4.type === 'main' && r4.label === '主树', 'null → 主树（不抛错）')
}

section('E 边界：type 非 worktree/dir 的 workspace 不误判')
{
  const r = workspaceInfoOf({ workspace: { type: 'registry', path: '/x' }, worktree: '.worktrees/wt' })
  ok(r.type === 'worktree' && r.label === 'wt', '非法 type → 跳过 workspace 走 worktree 回退')
  const r2 = workspaceInfoOf({ workspace: { path: '/x' } })
  ok(r2.type === 'main', '缺 type → 主树兜底')
}

section('F workspaceTextOf 紧凑文本（行悬停 title）')
{
  ok(workspaceTextOf({ workspace: { type: 'worktree', path: '.worktrees/t260822-m14-detail-refactor' } })
    === '泳道 t260822-m14-detail-refactor', 'worktree → 「泳道 <slug>」')
  ok(workspaceTextOf({ workspace: { type: 'dir', path: '/tmp/suyou-ws/t-x' } }) === '目录 /tmp/suyou-ws/t-x', 'dir → 「目录 <path>」')
  ok(workspaceTextOf({ worktree: '' }) === '主树', '无工作空间 → 「主树」')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
