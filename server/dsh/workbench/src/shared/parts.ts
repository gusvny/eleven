/**
 * suyou-workbench · 阶段链「执行主体」徽标纯函数（observability 立项 t260828-01）。
 *
 * 数据源：模版 STAGES 的 parts 静态声明（agent🤖/script⚙️/human👤，可组合），
 * 经 server/dsh/workflows/*.yaml → workflow.py _brief → /api/wf/workflows 透传到前端。
 * 动态真源仍是 Temporal history，这里只渲染静态声明，不做动态判定。
 *
 * 软降级口径：无 parts 字段/空数组的旧数据 → 「—」，不报错；枚举外的未知值
 * 不炸、不硬删——徽标位显「❓」，悬停行里点名（与 yaml 侧「大声报错」分工：
 * 数据入口 workflow.py validate 已拦非法值，前端这层只做兜底呈现）。
 *
 * 纯函数无 IO，smoke/stage-parts.mjs 直跑（node ≥22.18 原生 type-stripping）。
 */

/** 执行主体枚举（与 temporal-poc/shared.py PART_KINDS、server/tools/workflow.py 同口径）。 */
export type PartKind = 'agent' | 'script' | 'human'

export const PART_ICON: Record<PartKind, string> = {
  agent: '🤖',
  script: '⚙️',
  human: '👤',
}

/** 悬停说明里的人读标签。 */
export const PART_LABEL: Record<PartKind, string> = {
  agent: 'agent 执行',
  script: '脚本/程序化',
  human: '人工',
}

/** 徽标串：parts 直接拼接（如 ['agent','script'] → '🤖⚙️'）；空/undefined → '—'。 */
export function partsIcons(parts?: string[]): string {
  if (!parts || parts.length === 0) return '—'
  return parts.map(p => PART_ICON[p as PartKind] ?? '❓').join('')
}

/** 悬停一行说明：「执行主体：🤖 agent 执行 + ⚙️ 脚本/程序化」；空/undefined → 旧数据口径说明。 */
export function partsTitle(parts?: string[]): string {
  if (!parts || parts.length === 0) return '执行主体：—（旧数据无 parts 静态声明，以实际运行为准）'
  const seg = parts.map(p => {
    const icon = PART_ICON[p as PartKind]
    const label = PART_LABEL[p as PartKind]
    return icon ? `${icon} ${label}` : `❓ 未知执行主体 ${p}`
  })
  return `执行主体：${seg.join(' + ')}（静态声明；动态真源=Temporal history）`
}
