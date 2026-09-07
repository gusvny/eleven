/**
 * routes-edit.ts —— sandbar-providers「路由表」分区的纯函数（M13，t260822-m13-model-routes-edit）。
 *
 * 浏览器半（src/client/index.tsx 的 RoutesTableSection）与冒烟（smoke/routes-save.mjs）
 * 共用的视图→草稿→保存载荷变换。无 DOM/无 node 依赖，可被 node 冒烟直测：
 *
 *   draftFromView  —— /suyou-admin/api/routes 视图（sandbar-admin-ui RoutesView 子集）
 *                     → 编辑草稿（provider/model 一律字符串，''=不设）
 *   draftToPayload —— 草稿 → POST /suyou-admin/api/routes/save 的 {table} 载荷
 *                     （显式带 ''=清空该键 → 宿主删键，查表向上落兜底）
 *
 * 载荷 schema 与宿主侧（sandbar-admin-ui routes.ts RouteTableEdits）逐字对齐：
 * default/roles.<三角色>[/tasks.<三分工>] 的 provider|model，其余键宿主拒绝。
 */

/** /suyou-admin/api/routes 视图（RoutesView 子集，见 sandbar-admin-ui routes.ts）。 */
export interface RouteEff { provider: string; model: string; via: string }
export interface RouteEntryDisp { provider: string | null; model: string | null }
export interface RouteRoleView {
  role: string
  display: string
  desc: string
  entry: RouteEntryDisp | null
  effective: RouteEff | null
  tasks: Array<{ kind: string; display: string; entry: RouteEntryDisp | null; effective: RouteEff | null }>
}
export interface RoutesViewResp {
  routes_file: string
  parsed_at: number
  default: RouteEff | null
  roles: RouteRoleView[]
  warnings: string[]
  error?: string
}

/** 编辑草稿：provider/model 一律字符串，''=不设（保存时删键，查表向上落兜底）。 */
export interface RouteDraft {
  default: { provider: string; model: string }
  roles: Record<string, {
    provider: string
    model: string
    tasks: Record<string, { provider: string; model: string }>
  }>
}

/** 保存载荷（sandbar-admin-ui routes.ts RouteTableEdits 口径）：显式带 '' 表示「清空该键」。 */
export interface RouteTablePayload {
  default?: { provider?: string; model?: string }
  roles?: Record<string, {
    provider?: string
    model?: string
    tasks?: Record<string, { provider?: string; model?: string }>
  }>
}

/** 视图 → 编辑草稿（null 条目 → 空串，UI 显示为「继承 default」）。 */
export function draftFromView(view: RoutesViewResp): RouteDraft {
  const dft = view.default ?? { provider: '', model: '' }
  const roles: RouteDraft['roles'] = {}
  for (const role of view.roles) {
    const e = role.entry ?? { provider: '', model: '' }
    const tasks: RouteDraft['roles'][string]['tasks'] = {}
    for (const t of role.tasks) {
      const te = t.entry ?? { provider: '', model: '' }
      tasks[t.kind] = { provider: te.provider ?? '', model: te.model ?? '' }
    }
    roles[role.role] = { provider: e.provider ?? '', model: e.model ?? '', tasks }
  }
  return { default: { provider: dft.provider ?? '', model: dft.model ?? '' }, roles }
}

/** 草稿 → 保存载荷：所有字段显式携带（含 ''=清空键），宿主 diff 后只改有变化的行。 */
export function draftToPayload(d: RouteDraft): RouteTablePayload {
  const payload: RouteTablePayload = { default: { provider: d.default.provider, model: d.default.model }, roles: {} }
  for (const [rid, r] of Object.entries(d.roles)) {
    const role: NonNullable<RouteTablePayload['roles']>[string] = { provider: r.provider, model: r.model }
    const tasks: Record<string, { provider?: string; model?: string }> = {}
    for (const [kind, t] of Object.entries(r.tasks)) tasks[kind] = { provider: t.provider, model: t.model }
    role.tasks = tasks
    payload.roles![rid] = role
  }
  return payload
}

/** provider/model 展示（''=未设）。 */
export function fmtEntry(provider: string, model: string): string {
  return provider !== '' && model !== '' ? `${provider}/${model}` : '—'
}
