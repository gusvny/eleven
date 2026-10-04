/**
 * api.ts —— 面板自有 API 核（t260929-03）：与 HTTP 解耦的处理函数面。
 *
 * node.ts 只做薄壳：解析 method/path/body → 调本文件的 createApi().handle → 回 JSON。
 * 这样 UT 直接打 API 层（review 意见 #2：POST 端点的非 JSON 体/缺字段/坏 key/
 * 二次应答都在 API 级有显式拒绝用例），不必起真服务；形状与真路由同源。
 *
 * 只读刚性：除 requests append/answer 与 settings save 三个 POST 外一律 GET-only（405）。
 */

import { readdirSync } from 'node:fs'
import { join } from 'node:path'
import {
  appendRequest, answerRequest, readRequests, parseJsonBody, requestUrgency,
  fsLedgerIo, type LedgerIo,
} from './requests.ts'
import { loadWatchdogConfig } from './settings.ts'
import { instanceProjectsRoot } from '../../../watchdog/src/host/config.ts'
import { readSettings, saveWatchdogDecl, revokeAll, sleepToggle } from './settings.ts'
import { deriveGrants, extractTemplateFacts, grantsUnavailable, type GrantsResult } from './grants.ts'
import { clearGrants, grantAllOps, grantsReadoutState, isOpGranted, provenanceKeys, readDeclaration, saveGrantsDecl, GRANT_OPS, toGrantOp } from './executor-grants.ts'
import { readRecentActions, fsActionsIo, type ActionsIo } from './recent-actions.ts'
import { listOpenTicketEpics } from './open-tickets.ts'
import { PROJECT_KEY_RE, malformedProjectMessage } from './project-key.ts'

export interface ApiResponse { status: number; json: Record<string, unknown> }

function bad(status: number, error: string): ApiResponse {
  return { status, json: { ok: false, error } }
}

/**
 * 面板自有 API 路由表（单一真源，t261003-10）：node.ts 的注册循环与 handle 的
 * 准入守卫共用这一份常量——handle 对不在表内的 path 一律 404（表⊇可处理），
 * 注册循环对表内每条都挂路由（表⊆可达），两侧永不漂移；tests/route-parity.test.mjs
 * 机械锁两侧。t260930-09 起 /api/actions、/api/projects 只在 handle 里、从未注册
 * （生产 404）正是缺这张表的直接后果。
 * /api/projects 处置决定（票面要求记录）：**接通**——tests/projects.test.mjs 在用、
 * 深链检视语义仍在（页面选择器虽已于 t261003-06 移除，端点仍是程序化选项目的
 * 数据面）；删它会回归面。
 */
export const PANEL_API_ROUTES: ReadonlyArray<{ path: string; methods: string[] }> = [
  { path: '/sandbar-executor-panel/api/requests', methods: ['GET', 'POST'] },
  { path: '/sandbar-executor-panel/api/requests/answer', methods: ['POST'] },
  { path: '/sandbar-executor-panel/api/settings', methods: ['GET', 'POST'] },
  { path: '/sandbar-executor-panel/api/grants', methods: ['GET', 'POST'] },
  { path: '/sandbar-executor-panel/api/actions', methods: ['GET'] },
  { path: '/sandbar-executor-panel/api/projects', methods: ['GET'] },
]

export interface ApiDeps {
  /** 模板事实读面（缺省同源 fetch workbench 只读端点；测试注入桩）。 */
  fetchTemplateFacts?: () => Promise<GrantsResult>
  now?: () => number
  ledgerIo?: LedgerIo
  /** grants 读取的声明开关面（缺省走 loadWatchdogConfig；测试可注入）。 */
  declaredEnabled?: (key: string) => { declared: boolean; enabled: boolean }
  /** 最近动作账本 io（缺省 fs；测试注入内存桩）。 */
  actionsIo?: ActionsIo
  /** workbench 端点基址（config 显式指定；缺省 env → 请求来源同源，见 resolveWorkbenchBase）。 */
  workbenchBase?: string
}

/**
 * grants 上游基址解析（t260929-22 GAP B：给上游一个真生产者，失败在构造上不可能）：
 *   ① deps.workbenchBase（profile config 显式指定）→ ② env SANDBAR_WORKBENCH_BASE
 *   → ③ 请求来源推同源基址（面板与 workbench 同挂一台 console web 服务，普通生产
 *   形态恒可解析）→ 都没有才降级（点名缺什么）。
 *
 * Host 可信边界（review 条件①落款）：来源只取 `http://<Host 头原样>` 拼接——不注
 * 凭据、不跟随路径、不做出站重写；伪造 Host 的最坏结果是 fetch 打到一个不存在的
 * 上游 → 落进下方既有的显式降级（点名原因），这正是可接受的失败模式。
 */
function resolveWorkbenchBase(depsBase: string | undefined, env: NodeJS.ProcessEnv, origin: string): string {
  if (depsBase) return depsBase
  if (env.SANDBAR_WORKBENCH_BASE) return env.SANDBAR_WORKBENCH_BASE
  if (origin) return origin
  return ''
}

export function createApi(env: NodeJS.ProcessEnv = process.env, deps: ApiDeps = {}) {
  const ledgerIo = deps.ledgerIo ?? fsLedgerIo
  const now = deps.now ?? Date.now

  async function grantsResult(key: string, origin: string): Promise<GrantsResult> {
    const de = deps.declaredEnabled
      ? deps.declaredEnabled(key)
      : declFace(key)
    const factsFace = deps.fetchTemplateFacts ?? (() => defaultTemplateFacts(origin))
    const factsRes = await factsFace()
    if (!factsRes.ok) return factsRes
    return deriveGrants(factsRes.facts, de.declared, de.enabled)
  }

  function declFace(key: string): { declared: boolean; enabled: boolean } {
    const r = loadWatchdogConfig(key, env)
    return { declared: r.declared, enabled: r.enabled }
  }

  async function defaultTemplateFacts(origin: string): Promise<GrantsResult> {
    const base = resolveWorkbenchBase(deps.workbenchBase, env, origin)
    if (base === '') return grantsUnavailable('workbench endpoint base not resolvable (no config workbenchBase, no SANDBAR_WORKBENCH_BASE, request origin absent) — template facts unavailable, shown explicitly')
    try {
      const res = await fetch(base + '/sandbar-workbench/api/wf/workflows', { signal: AbortSignal.timeout(5000) })
      if (!res.ok) return grantsUnavailable(`workbench workflows endpoint HTTP ${res.status}`)
      return extractTemplateFacts(await res.json())
    } catch (e) {
      return grantsUnavailable(`workbench unreachable: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function handle(method: string, path: string, query: URLSearchParams, bodyRaw: string, origin = ''): Promise<ApiResponse> {
    // ---- 路由表准入守卫（t261003-10）：表外一律 404，表内每条都必须在下方有处理分支
    // （route-parity UT 双向锁死）——这是「未知面板路由」的唯一出口。
    if (!(PANEL_API_ROUTES as ReadonlyArray<{ path: string }>).some((r) => r.path === path)) {
      return bad(404, `未知面板路由：${path}`)
    }
    // ---- requests ----
    if (path === '/sandbar-executor-panel/api/requests') {
      if (method === 'GET') {
        const key = query.get('project')
        if (key !== null && !PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
        const keys = key !== null && key !== '' ? [key] : allPanelProjects(env)
        const groups: Array<Record<string, unknown>> = []
        const rows: Array<Record<string, unknown>> = []
        let malformed = 0
        for (const k of keys) {
          const read = readRequests(ledgerIo, env, k)
          malformed += read.malformed_rows
          const withUrgency = read.rows.map(r => ({ ...r, urgency: requestUrgency(r, now()) }))
          rows.push(...withUrgency)
          groups.push({
            project: k, file: read.file, malformed_rows: read.malformed_rows,
            rows: withUrgency,
          })
        }
        rows.sort((a, b) => (b.at as number) - (a.at as number))
        return { status: 200, json: { ok: true, groups, rows, malformed_rows: malformed, note: 'own ledger — never auto-deleted, never auto-answered' } }
      }
      if (method === 'POST') {
        const parsed = parseJsonBody(bodyRaw) // 非 JSON 体显式拒绝（review #2）
        if (!parsed.ok) return bad(400, parsed.error)
        const b = parsed.body
        const key = b.project
        const res = appendRequest(ledgerIo, env, String(key ?? ''), b as never, now())
        if (!res.ok) return bad(res.error.startsWith('project 形状') ? 400 : 422, res.error)
        return { status: 200, json: { ok: true, row: res.row } }
      }
      return bad(405, '仅 GET/POST（append=生产者投递面）')
    }
    if (path === '/sandbar-executor-panel/api/requests/answer') {
      if (method !== 'POST') return bad(405, '应答面仅 POST（写操作，显式留痕）')
      const parsed = parseJsonBody(bodyRaw)
      if (!parsed.ok) return bad(400, parsed.error)
      const b = parsed.body
      const res = answerRequest(ledgerIo, env, String(b.project ?? ''), b.id, b.answer, String(b.by ?? 'host'), now())
      if (!res.ok) {
        const status = res.error.startsWith('project 形状') || res.error.startsWith('id 必须') || res.error.startsWith('answer 必须')
          ? 400
          : res.error.startsWith('无此请求') ? 404 : 409
        return bad(status, res.error)
      }
      return { status: 200, json: { ok: true, answered: res.answerRow } }
    }
    // ---- settings ----
    if (path === '/sandbar-executor-panel/api/settings') {
      const key = query.get('project') ?? ''
      if (method === 'GET') {
        if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
        return { status: 200, json: readSettings(key, env, now()) }
      }
      if (method === 'POST') {
        if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
        const parsed = parseJsonBody(bodyRaw)
        if (!parsed.ok) return bad(400, parsed.error)
        const op = typeof parsed.body.op === 'string' ? parsed.body.op : 'save'
        if (op === 'save') {
          // 票面契约：保存被拒收=HTTP 200 + saved:false + 人类可读原因（拒收是
          // 「编辑面正常工作」，不是传输层错误；盘上文件未动才是硬保证）。
          const cfgInput = parsed.body.config !== undefined ? parsed.body.config : parsed.body.declaration
          const res = saveWatchdogDecl(key, cfgInput, env)
          if (!res.saved) return { status: 200, json: { ok: false, saved: false, error: res.reason, reason: res.reason } }
          return { status: 200, json: { ok: true, saved: true, resolved: res.resolved } }
        }
        if (op === 'revoke') {
          const res = revokeAll(key, env)
          if (!res.saved) return { status: 200, json: { ok: false, saved: false, error: res.reason, reason: res.reason } }
          // t260930-14：收回变真——同步清空执行器授权声明（全 op 未授予=引擎侧零授予）。
          // t261003-06：改走 clearGrants（仅授权面收回，保留会话点名）；守望者的
          // enabled:false 语义由上面 revokeAll 承担，两个面各管各的（review C2）。
          const g = clearGrants(key, String(parsed.body.by ?? 'host'), env, now(), String(parsed.body.caller_surface ?? ''))
          if (!g.saved) return { status: 200, json: { ok: false, saved: false, error: g.reason, reason: g.reason } }
          return { status: 200, json: { ok: true, saved: true, note: 'all grants revoked (watchdog enabled:false + executor grants declaration cleared)' } }
        }
        if (op === 'sleep') {
          const res = sleepToggle(key, parsed.body.policy as never, Number(parsed.body.until), env, now())
          if (!res.ok) return { status: 422, json: { ok: false, error: res.error } }
          return { status: 200, json: { ok: true, saved: true, override: res.override } }
        }
        return bad(422, `未知 settings 操作：${op}（∈ save|revoke|sleep）`)
      }
      return bad(405, '仅 GET/POST')
    }
    // ---- grants（t260930-14：声明成为真源——GET 带声明+溯源；POST=编辑器写面）----
    if (path === '/sandbar-executor-panel/api/grants') {
      const key = query.get('project') ?? ''
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      if (method === 'POST') {
        const parsed = parseJsonBody(bodyRaw)
        if (!parsed.ok) return bad(400, parsed.error)
        const b = parsed.body as Record<string, unknown>
        // t261003-06 总开关（Overview 电源开关 = Grants 总开关，同一份状态）：
        //   op:'master' + enabled:false → 仅授权面收回（clearGrants：清 grants、留会话点名、
        //   绝不碰 watchdog.json——「收回授权只影响授权，守望者照常运行」）；
        //   op:'master' + enabled:true  → 全部六操作授予（grantAllOps）。
        // 旧 settings 的 op=revoke（enabled:false，禁守望者）是另一个面，语义不混用。
        if (b.op === 'master') {
          const by = String(b.by ?? 'host')
          const surface = String(b.caller_surface ?? '')
          const res = b.enabled === false
            ? clearGrants(key, by, env, now(), surface)
            : grantAllOps(key, by, env, now(), surface)
          if (!res.saved) return { status: 200, json: { ok: false, saved: false, error: res.reason, reason: res.reason } }
          return { status: 200, json: { ok: true, saved: true, file: res.file, declaration: res.resolved,
            note: b.enabled === false ? 'all permissions revoked (session naming kept, watchdog untouched)' : 'all six permissions granted' } }
        }
        // 保存被拒收=HTTP 200 + saved:false + 人话原因（拒收是「编辑面正常工作」，与 settings save 同口径）。
        const res = saveGrantsDecl(key, b, String(b.by ?? ''), env, now(), String(b.caller_surface ?? ''))
        if (!res.saved) return { status: 200, json: { ok: false, saved: false, error: res.reason, reason: res.reason } }
        return { status: 200, json: { ok: true, saved: true, file: res.file, declaration: res.resolved } }
      }
      if (method !== 'GET') return bad(405, '仅 GET/POST（POST=声明编辑器写面）')
      const res = await grantsResult(key, origin)
      // 声明面 + 逐 op 溯源（哪个声明哪条键定的——KI-148/149 同纪律）。
      const decl = readDeclaration(key, env)
      // t261001-21（读出面诚实）：派生行 ≠ 已授予。此前 rows 是「派生能力矩阵」
      // （这个动词在该模板上是什么意思），却顶着 grants 之名被渲染成「这些授权存在」
      // ——零声明项目也显示 18 行，执行器第一轮就被它误导。现在：
      //   ① 每行带 granted（真声明定的：grants.<op>=true 或活跃夜间档；缺席/坏声明=全 false）；
      //   ② granted_count + readout_note 一眼可读「到底授了什么」；
      //   ③ 顶层 declaration_summary 给声明状态与已授予 op 清单（消费方不用拆表）。
      let grantsFace: Record<string, unknown> = res as never
      // t261003-06 缺陷二修复：读出面的分子分母 = **去重的权限个数**（GRANT_OPS 6 个），
      // 不再是派生行数（op × 模板：六操作 × 三模板会被报成 18）。
      const grantedOps = GRANT_OPS.filter((op) => isOpGranted(decl, op, now()))
      const grantedCount = grantedOps.length
      const total = GRANT_OPS.length
      const readout = grantsReadoutState(decl.declaration, decl.declared, decl.kind, now())
      if (res.ok) {
        const rows = res.rows.map((r) => ({ ...r, granted: isOpGranted(decl, r.op, now()) }))
        grantsFace = {
          ...res,
          rows,
          granted_count: grantedCount,
          granted_total: total,
          readout_note: grantedCount === 0
            ? 'NOTHING is granted: rows below are the derived capability matrix (what each verb means per template), NOT existing grants — a row here is not a grant'
            : `Permissions: ${grantedCount} of ${total} granted (distinct permissions, not capability rows)`,
        }
      }
      const auditNote = 'refusals and grant changes are audited to ' + key + '/executor-grants-audit.jsonl'
      // degraded 顶层显式位（消费方可不拆 grants 判定「模板事实不可得」）。
      return {
        status: 200,
        json: {
          ok: true, grants: grantsFace, degraded: res.ok === false, reason: res.ok ? undefined : res.reason,
          granted_ops: grantedOps,
          granted_total: total,
          // t261003-06 缺陷三：读出面三态显式在顶层（没点名 / 点名了但零授予 / 已授予），
          // 消费方不用从会话列表与授予清单自行推断。
          session_readout: { state: readout.state, sessions: readout.sessions, sentence: readout.sentence },
          declaration: decl.ok ? decl.declaration : null,
          declaration_state: { declared: decl.declared, kind: decl.kind ?? (decl.ok ? 'ok' : 'absent'), error: decl.error, file: decl.file },
          provenance: { file: decl.file, keys: provenanceKeys(decl, now()) },
          // t261004-19：epic 授权读面（「Open tickets in these epics」节的数据源）——
          // 全部 epic + 当前是否在名单；解析不出=ok:false + 原因（显式降级卡）。
          open_ticket_epics: listOpenTicketEpics(key, env),
          open_ticket_cap: decl.ok ? (decl.declaration?.open_ticket_cap ?? 3) : 3,
          audit_note: auditNote,
        },
      }
    }
    // ---- recent actions（t261003-06 引入；t261004-11 换源=项目自己的执行器动作账） ----
    if (path === '/sandbar-executor-panel/api/actions') {
      if (method !== 'GET') return bad(405, '只读面：仅 GET')
      const key = query.get('project') ?? ''
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      const read = readRecentActions(deps.actionsIo ?? fsActionsIo, env, key)
      // 不可得=200 + ok:false + 原因（页面渲染显式降级卡）；绝不渲染成空列表冒充「没动作」。
      if (!read.ok) return { status: 200, json: { ok: false, source: read.source, reason: read.reason } }
      return {
        status: 200,
        json: {
          ok: true, source: read.source, actions: read.actions,
          malformed_rows: read.malformed_rows, unknown_op_rows: read.unknown_op_rows,
          deduped_rows: read.deduped_rows, older_rows: read.older_rows,
          gaps_recent: read.gaps_recent, gaps_file: read.gapsFile,
          note: read.older_rows > 0
            ? 'Showing the latest ' + read.actions.length + ' action(s). Older rows are in ' + read.source + '.'
            : undefined,
        },
      }
    }
    // ---- projects (t260930-09 scope 8) ----
    if (path === '/sandbar-executor-panel/api/projects') {
      if (method !== 'GET') return bad(405, '只读面：仅 GET')
      // 面板已知的全量项目（注册表根下的目录），逐个标注声明状态——项目在「什么都没
      // 声明」之前就能被选中检视（旧口径只列已声明项目，fresh machine 连第一只项目
      // 都进不了下拉框）。?project=<key> 深链不受影响。
      const projects = allPanelProjects(env).map((k) => {
        const r = loadWatchdogConfig(k, env)
        return { project: k, declared: r.declared, enabled: r.enabled, config_error: r.config_error }
      })
      return { status: 200, json: { ok: true, projects, note: 'declared=false = nothing enrolled yet — still selectable for inspection' } }
    }
    return bad(404, `未知面板路由：${path}`)
  }

  return { handle }
}

/** panel 自有项目集（有 requests.jsonl 或 watchdog 声明的项目；「按项目分组」的主列数据源）。 */
export function allPanelProjects(env: NodeJS.ProcessEnv): string[] {
  // t261003-04：兜底走实例 projects 根（非缺省实例 = <DSH_HOME>/sandbar/projects）。
  const root = env.SANDBAR_PANEL_DIR || instanceProjectsRoot(env)
  try {
    return readdirSync(root, { withFileTypes: true })
      .filter(d => d.isDirectory() && PROJECT_KEY_RE.test(d.name))
      .map(d => d.name).sort()
  } catch {
    return []
  }
}
