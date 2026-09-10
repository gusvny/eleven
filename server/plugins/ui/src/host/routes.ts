/**
 * routes.ts —— 模型路由视图（M12，t260822-m12 模型路由UI+agent log）的宿主半纯函数。
 *
 * 数据源（只读，不改表）：
 *   ① server/model-routes.yaml —— 声明式路由表（真源，治理红线见文件头注释：
 *      改路由=改本表，走工单+人审；**运行时生效**：agent activity 每次 spawn 查表
 *      生成 --patch，下一个工单 agent 即用新模型，无生成步骤）。
 *
 * 本模块做四件事（全部纯函数/只读文件或显式保存，可被 smoke 直测）：
 *   A. parseRoutesYaml —— 严格最小 YAML 子集解析器
 *      （缩进 2 空格倍数、无行尾空白、无 tab、裸 token 值、' #' 行尾注释；
 *       不认识的行/键重复/缩进非法 → 带行号大声报错，不静默丢）。
 *   B. effectiveRoute —— 查表：(role, task_kind) → roles.<role>.tasks.<kind>
 *      → roles.<role> → default；缺 provider|model 告警并向上落；全落空 → null
 *      （与 engine/shared.py model_route_for 同口径；warnings 收集告警供 UI 展示）。
 *   C. applyRouteEdits —— M13 编辑：对真源文本做外科手术式补丁（只改被编辑的
 *      provider/model 值，表头注释/行尾注释/键序全保留；缺键按父键缩进插入，
 *      空值=删除该键 → 查表向上落兜底），schema 锁死可编辑槽位，防夹带。
 *   D. saveRoutesTable —— 读真源 → 校验 → 补丁 → 备份到 /tmp → 写回 model-routes.yaml。
 */

import { copyFile, readFile, writeFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/* ------------------------------------------------------------ 显示名常量（直接维护） */

/** 三角色编制：id → (显示名, 一句话)。与 server/roles/ 目录保持一致。 */
export const ROLES: Record<string, { display: string; desc: string }> = {
  integration: { display: '全局把关', desc: '设计×实现审查、待交付 workflow 验收审批、机械收口（合并/构建/记账）' },
  developer: { display: '开发', desc: 'app/管线/server 代码与修复，泳道作业' },
  'product-operation': { display: '产品运营', desc: '内容运营与上新节奏；内容生产全链在本角色内（加工/审校/验证/出数四分工）' },
}

/** 分工 kind → (显示名, 只读?)。stage→分工映射真源 = engine/shared.py STAGE_DISPATCH_KIND。 */
export const KINDS: Record<string, { display: string; readonly: boolean }> = {
  proofread: { display: '审校', readonly: true },
  qa: { display: '验证', readonly: true },
  analyst: { display: '出数', readonly: true },
}

/** provider → 家（M10 异模型交叉口径，model-routes.yaml 头注释「生成家/审校家」；
 *  纯 UI 展示用，不参与查表逻辑）。 */
export const PROVIDER_FAMILY: Record<string, string> = {
  'kimi-coding': '生成家',
  zai: '审校家',
  'deepseek-official': '主会话',
  scnet: '备用网关',
}

/* ------------------------------------------------------------ A. 严格最小 YAML 子集解析 */

/** 解析失败（带文件标签与行号，消息同 gen.py 口径）。 */
export class RoutesParseError extends Error { }

function asMap(v: unknown): Record<string, unknown> | null {
  return (typeof v === 'object' && v !== null && !Array.isArray(v)) ? v as Record<string, unknown> : null
}

/**
 * 解析 model-routes.yaml（严格最小子集，逐行镜像 gen.py parse_routes）：
 *  `key: value` 标量 / `key:` 开映射，2 空格缩进倍数，值裸 token（不带引号不带空格），
 *  整行注释 '#' 或行尾 ' #' 注释。不合法 → 抛 RoutesParseError（带行号，不静默丢）。
 */
export function parseRoutesYaml(text: string, fileLabel = 'model-routes.yaml'): Record<string, unknown> {
  const root: Record<string, unknown> = {}
  const stack: Array<{ indent: number; obj: Record<string, unknown> }> = [{ indent: -1, obj: root }]
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1
    let raw = lines[i]
    const hash = raw.indexOf(' #') // 值是裸 token，' #' 起即行尾注释（同 gen.py）
    if (hash >= 0) raw = raw.slice(0, hash)
    raw = raw.replace(/\s+$/, '')
    const stripped = raw.trim()
    if (stripped === '' || stripped.startsWith('#')) continue
    const indent = raw.length - raw.replace(/^ */, '').length
    if (indent % 2 !== 0 || raw !== raw.replace(/\s+$/, '') || raw.includes('\t')) {
      throw new RoutesParseError(
        `${fileLabel}:${lineNo} 缩进非法（须 2 空格倍数、无行尾空白、无 tab）: ${JSON.stringify(lines[i])}`)
    }
    const item = stripped
    const colon = item.indexOf(':')
    if (colon < 0) {
      throw new RoutesParseError(`${fileLabel}:${lineNo} 不认识的行（只认 key:/key: value）: ${JSON.stringify(lines[i])}`)
    }
    const key = item.slice(0, colon).trim()
    const val = item.slice(colon + 1).trim()
    if (key === '' || (val !== '' && /^['"]/.test(val))) {
      throw new RoutesParseError(`${fileLabel}:${lineNo} 键/值非法（值一律裸 token 不带引号）: ${JSON.stringify(lines[i])}`)
    }
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop()
    const parent = stack[stack.length - 1].obj
    if (Object.prototype.hasOwnProperty.call(parent, key)) {
      throw new RoutesParseError(`${fileLabel}:${lineNo} 键重复: ${key}`)
    }
    if (val !== '') {
      parent[key] = val
    } else {
      const child: Record<string, unknown> = {}
      parent[key] = child
      stack.push({ indent, obj: child })
    }
  }
  return root
}

/* ------------------------------------------------------------ B. 查表（同 gen.py route_for） */

export interface RouteEntry { provider: string; model: string; via: string }

/** (role, task_kind) → tasks.<kind> → roles.<role> → default；缺字段告警向上落；全落空 → null。
 *  warnings 收集查表告警（与 gen.py 大声告警同口径，UI 展示不静默）。 */
export function effectiveRoute(
  root: Record<string, unknown>, role: string, taskKind?: string, warnings: string[] = [],
): RouteEntry | null {
  const roles = asMap(root['roles']) ?? {}
  const entry = asMap(roles[role])
  const cands: Array<{ e: Record<string, unknown> | null; via: string }> = []
  if (entry !== null && taskKind !== undefined) {
    const tasks = asMap(entry['tasks']) ?? {}
    cands.push({ e: asMap(tasks[taskKind]), via: `roles.${role}.tasks.${taskKind}` })
  }
  cands.push({ e: entry, via: `roles.${role}` })
  cands.push({ e: asMap(root['default']), via: 'default' })
  for (const { e, via } of cands) {
    if (e === null) continue
    const provider = typeof e['provider'] === 'string' ? e['provider'] : ''
    const model = typeof e['model'] === 'string' ? e['model'] : ''
    if (provider !== '' && model !== '') return { provider, model, via }
    if (Object.keys(e).length > 0) {
      warnings.push(`路由表 ${via} 条目缺 provider/model——向上落兜底`)
    }
  }
  warnings.push(`路由表无 default 可用——${role} 不烘焙 agentOptions（继承 profile 默认）`)
  return null
}

/* ------------------------------------------------------------ C. 生成 preset 的实例扫描 */

/* ------------------------------------------------------------ 视图组装（读真源文件） */

export interface TaskRoute {
  kind: string
  display: string
  readonly: boolean
  /** roles.<role>.tasks.<kind> 原始条目（provider/model 缺省=null）。 */
  entry: { provider: string | null; model: string | null } | null
  /** 查表结果（含 via 链路；null=不设，继承 default/profile）。 */
  effective: RouteEntry | null
}

export interface RoleRoute {
  role: string
  display: string
  desc: string
  entry: { provider: string | null; model: string | null } | null
  effective: RouteEntry | null
  tasks: TaskRoute[]
}

export interface RoutesView {
  routes_file: string
  parsed_at: number
  /** default 条目（无 → null，告警已进 warnings）。 */
  default: RouteEntry | null
  roles: RoleRoute[]
  warnings: string[]
  /** 非空=视图组装失败（解析失败/读取故障等），UI 显示 error 不渲染空表。
   *  注意：表「缺失」不再是 error——那是未初始化态（uninitialized）。 */
  error?: string
  /** t260906-01 无表引导态（t260910-14 收窄为纯指引：init 动作已退役，
   *  新项目按 docs/model-routes-sample.yaml 人工填表）。 */
  uninitialized?: boolean
  /** t260910-14：声明 paths.model_routes 解析出的真源路径（未声明=null）。 */
  declared?: string | null
  /** t260910-14：解析四态（ok/decl_missing/file_missing/bad_content），与引擎
   *  resolve_routes_table 同名同判——禁静默，UI 须展示非 ok 态的 resolution_error。 */
  state?: 'ok' | 'decl_missing' | 'file_missing' | 'bad_content'
  /** 非 ok 态人话原因（生效来源/兜底说明）；生效时机=每次派活读表即生效；
   *  路由编辑端点在内存服务内，重启 3099 才见新逻辑（KI-052 同族）。 */
  resolution_error?: string
}

function entryOf(e: Record<string, unknown> | null): { provider: string | null; model: string | null } | null {
  if (e === null) return null
  return {
    provider: typeof e['provider'] === 'string' ? e['provider'] : null,
    model: typeof e['model'] === 'string' ? e['model'] : null,
  }
}

/** 仓内兜底表（宿主风险令 260910：读侧分层——声明指向文件优先，仓内表兜底；
 *  本票不删仓内表）。本文件在 server/plugins/ui/src/host/ 下，上三级即 server/。 */
export function repoRoutesFallbackPath(): string {
  return fileURLToPath(new URL('../../../../model-routes.yaml', import.meta.url))
}

export interface ResolvedRoutesFile {
  /** ok=声明指向文件在用；decl_missing=未声明（兜底=仓内表）；file_missing=声明文件
   *  缺失（读侧兜底）；bad_content=声明文件解析失败（读侧兜底）。与 python
   *  shared.resolve_routes_table 四态一一对应（一致性守卫见 integration 夹具矩阵）。 */
  state: 'ok' | 'decl_missing' | 'file_missing' | 'bad_content'
  /** 实际读/写目标：声明指向文件；未声明时=仓内兜底表。 */
  path: string
  /** 声明的绝对路径（未声明=null）。 */
  declared: string | null
  /** 非 ok 态的人话原因（ok 态空串）。禁静默：消费方须展示/留痕。 */
  error: string
}

/** 解析选项：projectsDir=注册表根注入点（测试夹具；缺省读 SANDBAR_PROJECTS_DIR）；
 *  projectKey=注册 key（缺省=未声明态）。 */
export interface RoutesResolveOpts {
  projectsDir?: string
  projectKey?: string
}

/** 读取注册表 per-key 条目的顶层 paths.model_routes 声明（最小行解析，镜像 python
 *  shared.project_paths 的 paths 节语义；SANDBAR_PROJECTS_DIR 覆盖同源）。 */
function readDeclaredRoutesPath(projectKey: string, projectsDir?: string): string | null {
  if (!PROJECT_KEY_TS_RE.test(projectKey)) return null
  const root = projectsDir ?? process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
  const entry = join(root, projectKey, 'project.yaml')
  let text: string
  try {
    text = readFileSync(entry, 'utf8')
  } catch {
    return null // 条目缺失/未注册=未声明（与 python project_paths 同判）
  }
  let inPaths = false
  for (const raw of text.split('\n')) {
    const line = raw.replace(/(#.*)?$/, '').trimEnd()
    if (line.trim() === '' || line.trim().startsWith('#')) continue
    if (line === 'paths:') { inPaths = true; continue }
    if (!/^\s/.test(raw)) inPaths = false // 退回顶层
    if (!inPaths) continue
    const m = line.trim().match(/^model_routes:\s*(.*)$/)
    if (m) {
      const v = m[1].trim().replace(/^["']|["']$/g, '')
      if (v === '') throw new Error(`paths.model_routes 声明值为空（strip 后判空，畸形）: ${entry}`)
      if (v.startsWith('{') || v.startsWith('[')) {
        throw new Error(`paths.model_routes 声明值非标量（fail-closed）: ${v.slice(0, 40)}`)
      }
      return v
    }
  }
  return null
}

const PROJECT_KEY_TS_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

/** 主目录反查 key（save/view 未显式传 key 时）：扫注册表根各条目 project.yaml 的
 *  dirs 列表，dirs[0]==primaryDir 的 key 即真源条目（与 python project_paths 的
 *  dirs[0] 主目录语义同源；找不到=null → 未声明态）。 */
function findKeyByPrimaryDir(projectsDir: string | undefined, primaryDir: string): string | null {
  const root = projectsDir ?? process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
  let entries: string[] = []
  try {
    entries = readFileSync(root, { withFileTypes: true }).map(e => e.name)
  } catch { return null }
  const want = resolve(primaryDir)
  for (const name of entries) {
    const f = join(root, name, 'project.yaml')
    let text: string
    try { text = readFileSync(f, 'utf8') } catch { continue }
    let inDirs = false
    let first: string | null = null
    for (const raw of text.split('\n')) {
      const line = raw.replace(/(#.*)?$/, '').trimEnd()
      if (line.trim() === '' || line.trim().startsWith('#')) continue
      if (line === 'dirs:') { inDirs = true; continue }
      if (!/^\s/.test(raw)) inDirs = false
      if (!inDirs) continue
      const m = line.trim().match(/^-\s*(.+)$/)
      if (m) { first = m[1].trim(); break }
    }
    if (first !== null && resolve(first) === want) return name
  }
  return null
}

/** 路由表文件解析——UI 读写与引擎查表的同一入口（t260910-14 读写同源）：
 *  声明 paths.model_routes 指向的文件优先（~/展开/绝对路径/相对项目主目录，
 *  `..` 逃逸 fail-closed 拒收），未声明回落仓内兜底表。三态分态可辨禁静默。 */
export function resolveRoutesFilePath(primaryDir: string, opts: RoutesResolveOpts = {}): ResolvedRoutesFile {
  const key = opts.projectKey ?? findKeyByPrimaryDir(opts.projectsDir, primaryDir)
  if (key === null) {
    return { state: 'decl_missing', path: repoRoutesFallbackPath(), declared: null,
             error: '注册表中未找到主目录对应的条目（读侧兜底=仓内表 ' + repoRoutesFallbackPath() + '）' }
  }
  const declaredRaw = readDeclaredRoutesPath(key, opts.projectsDir)
  if (declaredRaw === null || declaredRaw === '') {
    return { state: 'decl_missing', path: repoRoutesFallbackPath(), declared: null,
             error: '条目未声明 paths.model_routes（读侧兜底=仓内表 ' + repoRoutesFallbackPath() + '）' }
  }
  if (declaredRaw.includes('..') && (declaredRaw === '..' || declaredRaw.includes('/../') || declaredRaw.startsWith('../') || declaredRaw.endsWith('/..'))) {
    throw new Error(`paths.model_routes 禁止 .. 越界（机器级形态同样适用）: ${declaredRaw}`)
  }
  let declared: string
  if (declaredRaw === '~' || declaredRaw.startsWith('~/')) {
    declared = join(homedir(), declaredRaw.slice(1))
  } else if (declaredRaw.startsWith('/') || /^[a-zA-Z]:/.test(declaredRaw)) {
    declared = declaredRaw
  } else {
    declared = join(primaryDir, declaredRaw)
  }
  // 合法声明 → ok 态（存在性/内容缺陷由读面 buildRoutesView 在 readFile/parse 时
  // 分态点名——与 python project_paths（声明解析）+ resolve_routes_table（读侧分态）
  // 两层同构）。
  return { state: 'ok', path: declared, declared, error: '' }
}

/** 组装视图：读「声明指向的路由表」（真源，t260910-14 读写同源；未声明回落仓内
 *  兜底表——宿主风险令 260910 读侧分层），查表补齐 effective。 */
export async function buildRoutesView(primaryDir: string, opts: RoutesResolveOpts = {}): Promise<RoutesView> {
  const resolved = resolveRoutesFilePath(primaryDir, opts)
  const routesFile = resolved.path
  const view: RoutesView = {
    routes_file: routesFile,
    parsed_at: Math.floor(Date.now() / 1000),
    default: null,
    roles: [],
    warnings: [],
  }
  view.declared = resolved.declared
  view.state = resolved.state
  view.resolution_error = resolved.error
  let text: string
  try {
    text = await readFile(routesFile, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') {
      // 读侧分层兜底（宿主风险令 260910）：声明文件缺失 → 仓内兜底表若在则接管读
      // （写面仍指声明路径）；兜底也缺 = 未初始化引导态（纯指引，动作已随 init 退役）。
      if (resolved.declared !== null) {
        try {
          // 分层兜底接管**读内容**；routes_file 保持声明路径（真源/写面不漂移）
          text = await readFile(repoRoutesFallbackPath(), 'utf8')
          view.state = 'file_missing'
          view.resolution_error = resolved.error + '（读侧兜底=仓内表 ' + repoRoutesFallbackPath() + '）'
        } catch (err2: any) {
          if (err2?.code === 'ENOENT') {
            view.uninitialized = true
          } else {
            view.error = `路由表读取失败: ${String(err2?.message ?? err2)}`
          }
          return view
        }
      } else {
        // t260910-14：无表引导态保留为纯指引（init 动作已退役，新项目按 docs 样例人工填表）
        view.uninitialized = true
      }
    } else {
      view.error = `路由表读取失败: ${String(err?.message ?? err)}`
    }
    return view
  }
  let root: Record<string, unknown>
  try {
    root = parseRoutesYaml(text)
  } catch (err) {
    view.error = `路由表解析失败: ${err instanceof Error ? err.message : String(err)}`
    return view
  }
  const dft = asMap(root['default'])
  if (dft !== null && typeof dft['provider'] === 'string' && typeof dft['model'] === 'string') {
    view.default = { provider: dft['provider'], model: dft['model'], via: 'default' }
  }
  const roleEntries = asMap(root['roles']) ?? {}
  for (const [role, meta] of Object.entries(ROLES)) {
    const entry = asMap(roleEntries[role])
    const tasks = asMap(entry?.['tasks']) ?? {}
    const roleRoute: RoleRoute = {
      role,
      display: meta.display,
      desc: meta.desc,
      entry: entryOf(entry),
      effective: effectiveRoute(root, role, undefined, view.warnings),
      tasks: [],
    }
    for (const [kind, kmeta] of Object.entries(KINDS)) {
      if (!Object.prototype.hasOwnProperty.call(tasks, kind)) continue
      roleRoute.tasks.push({
        kind,
        display: kmeta.display,
        readonly: kmeta.readonly,
        entry: entryOf(asMap(tasks[kind])),
        effective: effectiveRoute(root, role, kind, view.warnings),
      })
    }
    view.roles.push(roleRoute)
  }
  return view
}

/* ------------------------------------------------------------ D. 可编辑 schema + 外科补丁（M13） */

/** provider/model 裸 token 格式（与表头「值一律裸 token」同口径）。 */
export const ROUTE_TOKEN_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/

/** 单个条目的可编辑字段：provider/model；缺省/空串 = 不设（查表向上落兜底）。 */
export interface RouteEntryEdit { provider?: string; model?: string }
/** 角色条目：可带 tasks（分工级，kind 必须在 KINDS 登记）。 */
export interface RouteRoleEdit extends RouteEntryEdit { tasks?: Record<string, RouteEntryEdit> }
/** M13 保存载荷：default + roles（只认 ROLES/KINDS 登记的槽位，其余键拒绝）。 */
export interface RouteTableEdits {
  default?: RouteEntryEdit
  roles?: Record<string, RouteRoleEdit>
}

/** 校验保存载荷：结构 + 键白名单 + 值格式；非法 → {ok:false,error}（不抛）。 */
export function validateRouteTable(table: unknown): { ok: true } | { ok: false; error: string } {
  const bad = (msg: string) => ({ ok: false as const, error: msg })
  if (typeof table !== 'object' || table === null || Array.isArray(table)) {
    return bad('保存载荷必须是对象 {default?, roles?}')
  }
  const t = table as Record<string, unknown>
  for (const top of Object.keys(t)) {
    if (top !== 'default' && top !== 'roles') return bad(`顶层键不认识: ${top}（只允许 default/roles）`)
  }

  const checkEntry = (v: unknown, where: string): { ok: boolean; error: string } => {
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return { ok: false, error: `${where} 必须是对象` }
    const e = v as Record<string, unknown>
    for (const k of Object.keys(e)) {
      if (k !== 'provider' && k !== 'model') return { ok: false, error: `${where} 键不认识: ${k}（只允许 provider/model）` }
      const val = e[k]
      if (typeof val !== 'string') return { ok: false, error: `${where}.${k} 必须是字符串（空串=不设）` }
      if (val !== '' && !ROUTE_TOKEN_RE.test(val)) {
        return { ok: false, error: `${where}.${k} 值不是合法裸 token（字母/数字开头，可含 - _ .）: ${JSON.stringify(val)}` }
      }
    }
    return { ok: true, error: '' }
  }

  if (t['default'] !== undefined) {
    const r = checkEntry(t['default'], 'default')
    if (!r.ok) return bad(r.error)
  }
  const roles = t['roles']
  if (roles !== undefined) {
    if (typeof roles !== 'object' || roles === null || Array.isArray(roles)) return bad('roles 必须是对象')
    for (const [rid, rv] of Object.entries(roles as Record<string, unknown>)) {
      if (!Object.prototype.hasOwnProperty.call(ROLES, rid)) {
        return bad(`roles.${rid} 不在三角色登记（ROLES 常量），不可编辑`)
      }
      if (typeof rv !== 'object' || rv === null || Array.isArray(rv)) return bad(`roles.${rid} 必须是对象`)
      const role = rv as Record<string, unknown>
      for (const k of Object.keys(role)) {
        if (k !== 'provider' && k !== 'model' && k !== 'tasks') {
          return bad(`roles.${rid} 键不认识: ${k}（只允许 provider/model/tasks）`)
        }
      }
      if (role['provider'] !== undefined) {
        const r = checkEntry({ provider: role['provider'] }, `roles.${rid}`)
        if (!r.ok) return bad(r.error)
      }
      if (role['model'] !== undefined) {
        const r = checkEntry({ model: role['model'] }, `roles.${rid}`)
        if (!r.ok) return bad(r.error)
      }
      const tasks = role['tasks']
      if (tasks !== undefined) {
        if (typeof tasks !== 'object' || tasks === null || Array.isArray(tasks)) return bad(`roles.${rid}.tasks 必须是对象`)
        for (const [kind, kv] of Object.entries(tasks as Record<string, unknown>)) {
          if (!Object.prototype.hasOwnProperty.call(KINDS, kind)) {
            return bad(`roles.${rid}.tasks.${kind} 不在分工登记（KINDS 白名单），不可编辑`)
          }
          const r = checkEntry(kv, `roles.${rid}.tasks.${kind}`)
          if (!r.ok) return bad(r.error)
        }
      }
    }
  }
  return { ok: true }
}

interface LineInfo {
  /** 1-based 行号（按 split('\n') 的物理行）。 */
  line: number
  indent: number
  /** 该键行是否有值（scalar）——无值=开映射。 */
  hasValue: boolean
  /** 已解析出的值（hasValue 时）。 */
  value: string
  /** 行尾注释（含前导 ' #'，原样保留）。 */
  comment: string
}

/** 逐行镜像 parseRoutesYaml 的栈语义，记录每个键路径的行信息（含行尾注释）。 */
function indexRoutesLines(lines: string[], fileLabel: string): Map<string, LineInfo> {
  const byPath = new Map<string, LineInfo>()
  const stack: Array<{ indent: number; key: string }> = [{ indent: -1, key: '' }]
  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1
    const raw = lines[i]
    const stripped = raw.split(' #', 1)[0].replace(/\s+$/, '')
    if (stripped.trim() === '' || stripped.trim().startsWith('#')) continue
    const indent = stripped.length - stripped.replace(/^ */, '').length
    if (indent % 2 !== 0 || raw !== raw.replace(/\s+$/, '') || raw.includes('\t')) {
      throw new RoutesParseError(
        `${fileLabel}:${lineNo} 缩进非法（须 2 空格倍数、无行尾空白、无 tab）: ${JSON.stringify(raw)}`)
    }
    const item = stripped.trim()
    const colon = item.indexOf(':')
    if (colon < 0) {
      throw new RoutesParseError(`${fileLabel}:${lineNo} 不认识的行（只认 key:/key: value）: ${JSON.stringify(raw)}`)
    }
    const key = item.slice(0, colon).trim()
    const val = item.slice(colon + 1).trim()
    if (key === '' || (val !== '' && /^['"]/.test(val))) {
      throw new RoutesParseError(`${fileLabel}:${lineNo} 键/值非法（值一律裸 token 不带引号）: ${JSON.stringify(raw)}`)
    }
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop()
    const path = [...stack.slice(1).map(s => s.key), key].join('/')
    const commentIdx = raw.indexOf(' #')
    byPath.set(path, {
      line: lineNo,
      indent,
      hasValue: val !== '',
      value: val,
      comment: commentIdx >= 0 ? raw.slice(commentIdx) : '',
    })
    if (val === '') stack.push({ indent, key })
  }
  return byPath
}

/** 找 parent 子树末行（1-based）：从 parent.line+1 起、缩进 > parent.indent 的最后一行；
 *  无子行 → parent.line。用于插入点定位。 */
function lastSubtreeLine(lines: string[], byPath: Map<string, LineInfo>, parentPath: string): number {
  const parent = byPath.get(parentPath)
  if (parent === undefined) return -1
  let last = parent.line
  for (let i = parent.line; i < lines.length; i++) {
    const stripped = lines[i].split(' #', 1)[0].replace(/\s+$/, '')
    if (stripped.trim() === '' || stripped.trim().startsWith('#')) continue
    const indent = stripped.length - stripped.replace(/^ */, '').length
    if (indent <= parent.indent) break
    last = i + 1
  }
  return last
}

export interface RouteEditsResult {
  /** 补丁后的完整文本（未变时与原文本相等）。 */
  text: string
  /** 实际发生变更的键路径（如 roles/developer/model）。 */
  changed: string[]
}

/** 把保存载荷打成 op 列表（只含「显式声明」的字段；'x' in entry 才进 op）。 */
function collectOps(edits: RouteTableEdits): Array<{ path: string; value: string }> {
  const ops: Array<{ path: string; value: string }> = []
  const pushEntry = (e: RouteEntryEdit | undefined, prefix: string): void => {
    if (e === undefined) return
    if ('provider' in e) ops.push({ path: `${prefix}/provider`, value: e.provider ?? '' })
    if ('model' in e) ops.push({ path: `${prefix}/model`, value: e.model ?? '' })
  }
  pushEntry(edits.default, 'default')
  if (edits.roles !== undefined) {
    for (const [rid, role] of Object.entries(edits.roles)) {
      pushEntry(role, `roles/${rid}`)
      if (role?.tasks !== undefined) {
        for (const [kind, entry] of Object.entries(role.tasks)) {
          pushEntry(entry, `roles/${rid}/tasks/${kind}`)
        }
      }
    }
  }
  return ops
}

/**
 * 对 model-routes.yaml 文本做外科手术式补丁（M13）：只改被编辑的 provider/model
 * 值——表头注释/行尾注释/键序/其余行全保留；目标键不存在且父键是映射 → 按父键缩进
 * 插入；空值 → 删除该键行（查表向上落兜底）。逐 op 重建行索引，行号不漂移。
 * 载荷必须先过 validateRouteTable（本函数对值再做一次格式兜底）。
 */
export function applyRouteEdits(
  text: string, edits: RouteTableEdits, fileLabel = 'model-routes.yaml',
): RouteEditsResult {
  const v = validateRouteTable(edits)
  if (!v.ok) throw new RoutesParseError(`${fileLabel} 保存载荷非法: ${v.error}`)
  const lines = text.split('\n')
  const changed: string[] = []
  for (const op of collectOps(edits)) {
    const byPath = indexRoutesLines(lines, fileLabel)
    const existing = byPath.get(op.path)
    if (existing !== undefined && existing.value === op.value) continue
    const lastSlash = op.path.lastIndexOf('/')
    const key = op.path.slice(lastSlash + 1)
    const parentPath = op.path.slice(0, lastSlash)
    if (op.value === '') {
      if (existing === undefined) continue // 本来就没有，无需删
      lines.splice(existing.line - 1, 1)
      changed.push(op.path)
      continue
    }
    if (!ROUTE_TOKEN_RE.test(op.value)) {
      throw new RoutesParseError(`${fileLabel} ${op.path} 值不是合法裸 token: ${JSON.stringify(op.value)}`)
    }
    if (existing !== undefined) {
      const indent = ' '.repeat(existing.indent)
      lines[existing.line - 1] = `${indent}${key}: ${op.value}${existing.comment}`
      changed.push(op.path)
      continue
    }
    // 插入：父键必须是映射（存在且非标量）
    const parent = byPath.get(parentPath)
    if (parent === undefined || parent.hasValue) {
      throw new RoutesParseError(`${fileLabel} 无法插入 ${op.path}：父键 ${parentPath} 不存在或是标量`)
    }
    const insertAt = lastSubtreeLine(lines, byPath, parentPath)
    const indent = ' '.repeat(parent.indent + 2)
    lines.splice(insertAt, 0, `${indent}${key}: ${op.value}`)
    changed.push(op.path)
  }
  return { text: lines.join('\n'), changed }
}

/* ------------------------------------------------------------ E. 保存（读真源→校验→补丁→备份→写回） */

/** 保存后生效话术：运行时查表，下一个工单 agent spawn 即生效，无生成步骤。 */
export const REGEN_HINT = '已生效（运行时查表：下一个工单 agent 启动即使用新路由，无需重跑任何生成步骤）'

export interface RoutesSaveResult {
  written: boolean
  routes_file: string
  /** 写前备份（/tmp/suyou-model-routes-<ts>.yaml.bak）；未写/失败 → null。 */
  backup: string | null
  changed: string[]
  regenerate: string
  error?: string
}

/** M13 保存：读真源 → validateRouteTable → applyRouteEdits → 备份 /tmp → 写回。
 *  表缺失/解析失败/载荷非法 → 返回 error（不抛，由 handler 转 200 {ok:false}）。 */
export async function saveRoutesTable(primaryDir: string, edits: RouteTableEdits, opts: RoutesResolveOpts = {}): Promise<RoutesSaveResult> {
  const routesFile = resolveRoutesFilePath(primaryDir, opts).path
  const base: RoutesSaveResult = {
    written: false, routes_file: routesFile, backup: null, changed: [], regenerate: REGEN_HINT,
  }
  let text: string
  try {
    text = await readFile(routesFile, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { ...base, error: `路由表不存在: ${routesFile}` }
    return { ...base, error: `路由表读取失败: ${String(err?.message ?? err)}` }
  }
  const v = validateRouteTable(edits)
  if (!v.ok) return { ...base, error: v.error }
  let applied: RouteEditsResult
  try {
    applied = applyRouteEdits(text, edits)
  } catch (err) {
    return { ...base, error: `路由表补丁失败: ${err instanceof Error ? err.message : String(err)}` }
  }
  if (applied.changed.length === 0) return base // 无变更不写
  const backup = join(tmpdir(), `suyou-model-routes-${Date.now()}.yaml.bak`)
  try {
    await copyFile(routesFile, backup)
  } catch (err) {
    return { ...base, error: `写前备份失败（未写表）: ${String(err instanceof Error ? err.message : err)}` }
  }
  try {
    await writeFile(routesFile, applied.text, 'utf8')
  } catch (err) {
    return { ...base, error: `写 model-routes.yaml 失败（备份已落 ${backup}）: ${String(err instanceof Error ? err.message : err)}` }
  }
  return { ...base, written: true, backup, changed: applied.changed }
}
