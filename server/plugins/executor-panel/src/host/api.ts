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
import { readSettings, saveWatchdogDecl, revokeAll, sleepToggle } from './settings.ts'
import { deriveGrants, extractTemplateFacts, grantsUnavailable, type GrantsResult } from './grants.ts'
import { PROJECT_KEY_RE, malformedProjectMessage } from './project-key.ts'

export interface ApiResponse { status: number; json: Record<string, unknown> }

function bad(status: number, error: string): ApiResponse {
  return { status, json: { ok: false, error } }
}

export interface ApiDeps {
  /** 模板事实读面（缺省同源 fetch workbench 只读端点；测试注入桩）。 */
  fetchTemplateFacts?: () => Promise<GrantsResult>
  now?: () => number
  ledgerIo?: LedgerIo
  /** grants 读取的声明开关面（缺省走 loadWatchdogConfig；测试可注入）。 */
  declaredEnabled?: (key: string) => { declared: boolean; enabled: boolean }
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
          return { status: 200, json: { ok: true, saved: true, note: 'all grants revoked (derived list renders as all-revoked)' } }
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
    // ---- grants ----
    if (path === '/sandbar-executor-panel/api/grants') {
      if (method !== 'GET') return bad(405, '只读面：仅 GET')
      const key = query.get('project') ?? ''
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      const res = await grantsResult(key, origin)
      // degraded 顶层显式位（消费方可不拆 grants 判定「模板事实不可得」）。
      return { status: 200, json: { ok: true, grants: res, degraded: res.ok === false, reason: res.ok ? undefined : res.reason } }
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
  const root = env.SANDBAR_PANEL_DIR || join(env.HOME || '', '.sandbar', 'projects')
  try {
    return readdirSync(root, { withFileTypes: true })
      .filter(d => d.isDirectory() && PROJECT_KEY_RE.test(d.name))
      .map(d => d.name).sort()
  } catch {
    return []
  }
}
