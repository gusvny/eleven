/**
 * grants.ts —— 授予清单轻量过滤式派生（设计稿 260927 决定 10/15，t260929-03）。
 *
 * 不是「推导出一套新东西」：**固定操作清单 × 三项过滤事实**——
 *   事实一（模板）：有没有人门、有哪几个 → 决定「签」这项有无意义；
 *   事实二（声明）：有无泳道/工作树；事实三：哪些目录允许直修；
 *   能力过滤（决定 15）：巡检没有暂停面 → 不显示 pause-resume 行。
 * 明确不做：①「门×模板×项目」三维矩阵；②把策略塞进推导；③手维护清单（必漂移）。
 * 判定点在引擎——本面编辑/显示项目授权声明（t260930-14 起：声明本体
 * executor-grants.json 由本面板持久化，见 executor-grants.ts），授权语义
 * （判定放行/拒收）仍只在引擎写路径（server/engine/executor_grants.py）。
 *
 * 模板事实源：workbench 只读端点 /sandbar-workbench/api/wf/workflows（同源 fetch）。
 * 端点形状漂移/不可达 → 显式降级对象（点名原因），**绝不渲染成「无授权」空表**。
 */

/** 引擎固定操作面（不随项目变——设计稿决定 10 原文词表）。 */
export const FIXED_OPS = ['sign', 'reject', 'rerun', 'open-ticket', 'pause-resume', 'cleanup'] as const
export type FixedOp = (typeof FIXED_OPS)[number]

export interface TemplateFact {
  name: string
  kind: string
  /** 模板拓扑里存在 exit=human 的门（决定 10：输入已现成——拓扑导出面自带 kind）。 */
  has_human_gate: boolean
}

export interface GrantRow {
  op: FixedOp
  template: string
  template_kind: string
  reason: string
}

export type GrantsResult =
  | { ok: true; rows: GrantRow[]; filtered: number; filtered_note: string; source: 'workbench-workflows' }
  | { ok: false; reason: string; source: 'workbench-workflows' }

/**
 * 从 workbench workflows 回执提取模板事实（容形状：数组可在 result / workflows /
 * 顶层；单项认 name/id + kind + 任意 human 门标记）。认不出的形状=显式降级，不猜。
 */
export function extractTemplateFacts(payload: unknown): { ok: true; facts: TemplateFact[] } | { ok: false; reason: string } {
  let list: unknown
  if (Array.isArray(payload)) list = payload
  else if (typeof payload === 'object' && payload !== null) {
    const doc = payload as Record<string, unknown>
    if (Array.isArray(doc.workflows)) list = doc.workflows
    else if (typeof doc.result === 'object' && doc.result !== null && Array.isArray((doc.result as Record<string, unknown>).workflows)) {
      list = (doc.result as Record<string, unknown>).workflows
    }
  }
  if (!Array.isArray(list)) return { ok: false, reason: 'workflows 回执形状认不出（无数组）——形状漂移须显式降级，不猜' }
  const facts: TemplateFact[] = []
  for (const item of list) {
    if (typeof item !== 'object' || item === null) return { ok: false, reason: 'workflows 回执含非对象项——形状漂移，显式降级' }
    const w = item as Record<string, unknown>
    const name = typeof w.name === 'string' ? w.name : typeof w.id === 'string' ? w.id : null
    if (!name) return { ok: false, reason: 'workflows 回执项缺 name/id——形状漂移，显式降级' }
    // kind 缺省时按 id/name 识别巡检族（决定 15 的「巡检族」判据是模板身份，不是新发明）；
    // 其余模板 kind=unknown（不猜更细的分类）。
    const kind = typeof w.kind === 'string' && w.kind !== ''
      ? w.kind
      : (/inspect|巡检/i.test(name) ? 'inspection' : 'unknown')
    // 人门标记（宽容面全收，真源形状在后两行——仲裁 gen1 点名）：
    //   真形状一：stages[].exit === 'human'（引擎 exit=human 门）
    //   真形状二：topology.nodes[].kind === 'human'（template_topology.py：exit=human
    //   → node kind human；workbench briefs 的 topology 是对象不是字符串）
    const topologyObj = typeof w.topology === 'object' && w.topology !== null
      ? w.topology as Record<string, unknown> : null
    const nodeArr = Array.isArray(w.nodes) ? w.nodes
      : topologyObj && Array.isArray(topologyObj.nodes) ? topologyObj.nodes : null
    const isHumanNode = (n: unknown) => {
      if (typeof n !== 'object' || n === null) return false
      const node = n as Record<string, unknown>
      return node.exit === 'human' || node.kind === 'human'
    }
    const hasHumanGate =
      w.has_human_gate === true ||
      w.human_gate === true ||
      (typeof w.topology === 'string' && /exit['":\s=]*human/.test(w.topology)) ||
      (nodeArr !== null && nodeArr.some(isHumanNode)) ||
      (Array.isArray(w.stages) && w.stages.some((g: unknown) =>
        typeof g === 'object' && g !== null && (g as Record<string, unknown>).exit === 'human'))
    facts.push({ name, kind, has_human_gate: hasHumanGate === true })
  }
  return { ok: true, facts }
}

/**
 * 授予清单派生核（纯函数）。**只返回显示行**：被模板事实/能力过滤掉的项不进
 * rows（payload 里不留它们的字样——过滤事实以 filtered 计数 + filtered_note
 * 点名「有 N 项被过滤、依据决定 10/15」，不给「无授权」空表冒充的机会）。
 * enabled:false = 一键收回后——rows 空 + note 点名「全收回（声明 enabled:false）」。
 */
export function deriveGrants(facts: TemplateFact[], declared: boolean, enabled: boolean): GrantsResult {
  if (!declared) return { ok: false, reason: '项目未声明守望者——授权面未接入（显式，不是空表）', source: 'workbench-workflows' }
  if (!enabled) {
    return {
      ok: true, rows: [], filtered: facts.length * FIXED_OPS.length,
      filtered_note: 'all revoked (declaration enabled:false) — derived list, nothing hand-maintained to drift',
      source: 'workbench-workflows',
    }
  }
  const rows: GrantRow[] = []
  let filtered = 0
  for (const f of facts) {
    const inspection = f.kind === 'inspection'
    for (const op of FIXED_OPS) {
      if (op === 'sign' && !f.has_human_gate) { filtered++; continue } // 决定 10 事实一：无人门不显「签」
      if (op === 'pause-resume' && inspection) { filtered++; continue } // 决定 15：巡检无该控制面
      rows.push({ op, template: f.name, template_kind: f.kind, reason: 'derived: fixed op × template facts' })
    }
  }
  return {
    ok: true, rows, filtered,
    filtered_note: filtered > 0 ? `${filtered} op(s) hidden by template/capability filters (design decision 10/15)` : '',
    source: 'workbench-workflows',
  }
}

/** 模板事实不可达时的显式降级对象（页面渲染成「模板事实不可得（原因）」卡）。 */
export function grantsUnavailable(reason: string): GrantsResult {
  return { ok: false, reason, source: 'workbench-workflows' }
}
