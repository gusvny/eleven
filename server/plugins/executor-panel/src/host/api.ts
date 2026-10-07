/**
 * api.ts —— 面板自有 API 核（t260929-03）：与 HTTP 解耦的处理函数面。
 *
 * node.ts 只做薄壳：解析 method/path/body → 调本文件的 createApi().handle → 回 JSON。
 * 这样 UT 直接打 API 层（review 意见 #2：POST 端点的非 JSON 体/缺字段/坏 key/
 * 二次应答都在 API 级有显式拒绝用例），不必起真服务；形状与真路由同源。
 *
 * 只读刚性：除 requests append/answer 与 settings save 三个 POST 外一律 GET-only（405）。
 *
 * Write credential gate (t261004-18, KI-193): the console root unauthenticated-request gate lives
 * inside the dsh package (@deepseek-ai/dsh-client-connection browserAuth) and does
 * NOT cover this plugin's webServer routes — the strongest guard available in this
 * repo: every write method (POST/PUT/DELETE) must carry the dsh browser session
 * cookie (name computable from Host, value shape v1.<b64>.<b64>); without it the
 * request is refused unauthorized and nothing is written. Honest boundary: the cookie HMAC
 * secret is process-private to dsh, so this repo cannot verify signatures — the gate
 * stops credential-less requests, not a local process that forges headers.
 * Writer identity (requirement 2): the recorded writer is the fixed 'host' (the only
 * identity the credential proves); a body `by` is no longer trusted — if present and
 * != 'host', the row/audit carry by_claimed + writer_mismatch:true (visible, not
 * silent). Authority-declaration writes (grants save/master, the grants-clearing half
 * of settings revoke) all go through the engine entry client.py
 * executor-grants-write (single truth for META_OP judgment + audit).
 */

import { readdirSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import {
  appendRequest, answerRequest, dismissRequest, readRequests, parseJsonBody, requestUrgency, setThreadState,
  fsLedgerIo, type LedgerIo,
} from './requests.ts'
import { loadWatchdogConfig } from './settings.ts'

/** Legacy prefix of malformedProjectMessage (existing copy; kept as a constant so new lines stay English-only). */
const LEGACY_PROJECT_BAD = 'project ' + String.fromCharCode(24418,29366)
import { instanceProjectsRoot } from '../../../watchdog/src/host/config.ts'
import { readSettings, saveWatchdogDecl, revokeAll, sleepToggle } from './settings.ts'
import { deriveGrants, extractTemplateFacts, grantsUnavailable, type GrantsResult } from './grants.ts'
import { grantsReadoutState, isOpGranted, provenanceKeys, readDeclaration, GRANT_OPS, toGrantOp,
  spawnEngineGrantsWrite, type EngineGrantsWriteFace, type EngineGrantsWritePayload } from './executor-grants.ts'
import { readRecentActions, fsActionsIo, type ActionsIo } from './recent-actions.ts'
import {
  appendTriggerRecord, readTriggerRecords, validateTriggerInput,
  makeDefaultSpawnTrigger, fsTriggerIo,
  type TriggerIo, type SpawnTriggerFace,
} from './inspection-triggers.ts'
import { readConcurrency, spawnConcurrencyLimitWrite, CONCURRENCY_LIMIT_MIN, CONCURRENCY_LIMIT_MAX,
  CONCURRENCY_UNLIMITED, readLastLimitAudit, concurrencyDeclarationPath,
  type ConcurrencyRead, type ConcurrencyWriteFace } from './concurrency.ts'
import { readOneShotFace, fsOneShotIo, type OneShotIo } from './one-shot-view.ts'
import type { BridgeStatusSnapshot } from './question-bridge.ts'
import { listOpenTicketEpics } from './open-tickets.ts'
import { PROJECT_KEY_RE, malformedProjectMessage } from './project-key.ts'
import { WAKE_PUSH_DETAIL_CAP } from './list-contracts.ts'

export interface ApiResponse { status: number; json: Record<string, unknown> }

function bad(status: number, error: string): ApiResponse {
  return { status, json: { ok: false, error } }
}

// ---- KI-193 write credential gate ----

/** Raw credential material carried by the request (node.ts passes req.headers verbatim). */
export interface AuthInput { cookie?: string; host?: string }

export type AuthFace = (input: AuthInput) => { ok: boolean; why: string }

/**
 * dsh browser session cookie name (source of truth: dsh 0.1.5 dsh-client-connection
 * cookieName(authority) = 'dsh-auth-' + base64url(sha256(Host)) — the name is
 * computable; the HMAC secret for the value is process-private and unverifiable in
 * this repo. Three checks here: present / name matches the authority / value shape.
 * Any failure = unauthorized and nothing is written.
 */
export function defaultAuthFace({ cookie, host }: AuthInput): { ok: boolean; why: string } {
  if (!host) return { ok: false, why: 'request has no Host header — cannot bind the console session cookie' }
  const name = 'dsh-auth-' + createHash('sha256').update(host).digest('base64url')
  const segment = String(cookie ?? '')
    .split(';')
    .map((s) => s.trim())
    .find((s) => s.startsWith(name + '='))
  if (!segment) {
    return { ok: false, why: `no console session credential (${name}) — file requests via server/engine/executor_requests` }
  }
  const value = segment.slice(name.length + 1)
  if (!/^v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)) {
    return { ok: false, why: 'console session credential has an unexpected shape — file requests via server/engine/executor_requests' }
  }
  return { ok: true, why: '' }
}

/** Audit source face for authority writes (KI-193 requirement 4): panel origin + visible writer mismatch. */
function auditSource(byClaimed: unknown): Record<string, unknown> {
  const mismatch = byClaimed !== undefined && byClaimed !== null && byClaimed !== 'host'
  return {
    surface: 'panel-api', transport: 'http', guarded: true, by: 'host',
    ...(mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : {}),
  }
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
  // t261007-01: the dismiss write (host-only, same credential gate as answer).
  { path: '/sandbar-executor-panel/api/requests/dismiss', methods: ['POST'] },
  // t261007-02: the host state-change face behind the thread states (dismissed
  // here; resolved belongs to the doer via the engine entry request_thread.py).
  { path: '/sandbar-executor-panel/api/requests/state', methods: ['POST'] },
  { path: '/sandbar-executor-panel/api/settings', methods: ['GET', 'POST'] },
  { path: '/sandbar-executor-panel/api/grants', methods: ['GET', 'POST'] },
  { path: '/sandbar-executor-panel/api/actions', methods: ['GET'] },
  { path: '/sandbar-executor-panel/api/one-shot', methods: ['GET'] },
  { path: '/sandbar-executor-panel/api/one-shot/spawn', methods: ['POST'] },
  { path: '/sandbar-executor-panel/api/projects', methods: ['GET'] },
  // t261006-15: on-demand inspection. The trigger POST is a WRITE (attributed,
  // project's own account) and sits behind the KI-193 gate like every other write
  // method (the gate is method-based above, not per-branch). The records GET is a
  // read face over the same ledger (already-attributed facts only).
  { path: '/sandbar-executor-panel/api/inspection/trigger-records', methods: ['GET'] },
  { path: '/sandbar-executor-panel/api/inspection/trigger', methods: ['POST'] },
  // t261004-44 (KI-196 way out (2)): the question-bridge state face -- mounted flag /
  // per-kind counters / recent event ring. GET-only (read face); the read source is
  // deps.bridgeStatus (node.ts injects the createBridgeStatus sink).
  { path: '/sandbar-executor-panel/api/bridge/status', methods: ['GET'] },
  // t261006-17 (CL-2): concurrency read face + limit write face. GET reads the engine
  // ledger (ticket.py op=concurrency) and never recomputes it; POST saves the
  // declaration through the engine entry (client.py concurrency-limit-write, CL-2b).
  { path: '/sandbar-executor-panel/api/concurrency', methods: ['GET', 'POST'] },
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
  /** One-shot read-face io (default fs; tests inject an in-memory stub). */
  oneShotIo?: OneShotIo
  /** workbench 端点基址（config 显式指定；缺省 env → 请求来源同源，见 resolveWorkbenchBase）。 */
  workbenchBase?: string
  /** t261004-29 wake-caller seam: after a successful answer, push a wake to the
   *  watchdog wake endpoint (default = same-origin fetch, see defaultWakeCaller;
   *  tests inject a stub). */
  wakeCaller?: (args: { project: string; requestId: string; detail: string }) => Promise<WakeCallResult>
  /** t261006-06 spawn-caller seam: forward an approved one-shot spawn to the
   *  watchdog route (default = same-origin fetch, see defaultSpawnCaller;
   *  tests inject a stub). */
  spawnCaller?: (args: { project: string; requestId: string; action: string }) => Promise<SpawnCallResult>
  /** Write credential verdict face (default defaultAuthFace; test stub injection, KI-193). */
  authFace?: AuthFace
  /** Authority-declaration write face (default spawnEngineGrantsWrite via the engine CLI; test stub, KI-193). */
  engineGrantsWrite?: EngineGrantsWriteFace
  /** Bridge status read source (t261004-44; node.ts injects createBridgeStatus().snapshot.
   *  Not injected = an explicit not-wired shape (mounted:false + a naming note), never a
   *  fake healthy snapshot. */
  bridgeStatus?: () => BridgeStatusSnapshot
  /** t261006-15 trigger-record ledger io (default fs; tests inject an in-memory stub). */
  triggerIo?: TriggerIo
  /** t261006-15 trigger spawn face (default: spawn inspection_trigger.py via
   *  makeDefaultSpawnTrigger, full lifecycle reaping; tests inject a stub — never a real
   *  workflow start from a unit test). */
  spawnTrigger?: SpawnTriggerFace
  /** Concurrency read face (default readConcurrency via the engine CLI; test stub injection, t261006-17). */
  engineConcurrencyRead?: (key: string, env: NodeJS.ProcessEnv) => Promise<ConcurrencyRead>
  /** Concurrency limit write face (default spawnConcurrencyLimitWrite via the engine CLI; test stub, t261006-17). */
  engineConcurrencyWrite?: ConcurrencyWriteFace
}

/** Wake-call result (ok:false always carries a human-readable reason — the receipt
 *  is never silently absent). */
export type WakeCallResult =
  | { ok: true; receipt: { attempted: boolean; woke: boolean; reason: string; mode?: string | null; accepted?: boolean | null; at?: number } }
  | { ok: false; reason: string }

/** t261006-06 spawn-call result: the watchdog spawn receipt is validated to
 *  shape here, like the wake receipt -- never trusted blindly, never echoed
 *  verbatim. */
export type SpawnCallResult =
  | { ok: true; receipt: { action: string; sessionId?: string; objectKey?: string; outcome?: string; summary?: string } }
  | { ok: false; reason: string }

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

  /**
   * Authority-declaration write (KI-193 requirement 3): grants save / master / the
   * grants-clearing half of settings revoke all go through deps.engineGrantsWrite
   * (default: spawn the engine CLI `client.py executor-grants-write`) — single
   * truth for META_OP judgment + audit, whatever surface asked. The writer is the
   * fixed 'host'; a caller-reported by lands only in the source mismatch fields.
   * Engine unreachable / malformed receipt = saved:false named explicitly (never a
   * fallback to direct file write).
   */
  async function engineGrantsWrite(key: string, doc: Record<string, unknown>, byClaimed: unknown) {
    const payload: EngineGrantsWritePayload = {
      key, by: 'host',
      grants: (doc.grants ?? {}) as Record<string, unknown>,
      ...(doc.night_tier !== undefined ? { night_tier: doc.night_tier } : {}),
      ...(doc.executor_sessions !== undefined ? { executor_sessions: doc.executor_sessions } : {}),
      // t261004-41: the open-ticket keys ride along — an explicit [] must survive as a
      // clear-all, an absent key stays absent (the engine then inherits the on-disk value).
      ...(doc.open_ticket_epics !== undefined ? { open_ticket_epics: doc.open_ticket_epics } : {}),
      ...(doc.open_ticket_cap !== undefined ? { open_ticket_cap: doc.open_ticket_cap } : {}),
      source: auditSource(byClaimed),
    }
    return (deps.engineGrantsWrite ?? spawnEngineGrantsWrite)(payload)
  }

  /** Read the current declaration (source for executor_sessions / night_tier inheritance). */
  function prevDecl(key: string) {
    return readDeclaration(key, env)
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

  /**
   * t261004-29 default wake caller: POST to the watchdog /sandbar-watchdog/api/wake
   * route (panel and watchdog mount on the same console web server; base resolution
   * follows the same resolveWorkbenchBase trusted-origin discipline — the Host header
   * verbatim, no credentials, no path following, no outbound rewrite). The receipt
   * shape is never trusted blindly — non-200 / non-JSON / non-receipt bodies are all
   * normalized into ok:false with the reason named. An unresolvable base is an
   * explicit no-op (no guessing, no send).
   */
  async function defaultWakeCaller(args: { project: string; requestId: string; detail: string }, origin: string): Promise<WakeCallResult> {
    const base = resolveWorkbenchBase(undefined, env, origin)
    if (base === '') return { ok: false, reason: 'watchdog wake endpoint base not resolvable (no SANDBAR_WORKBENCH_BASE, request origin absent) — wake not attempted' }
    try {
      const res = await fetch(base + '/sandbar-watchdog/api/wake', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ project: args.project, request_id: args.requestId, detail: args.detail, by: 'host-panel' }),
        signal: AbortSignal.timeout(5000),
      })
      if (!res.ok) return { ok: false, reason: `watchdog wake endpoint HTTP ${res.status}` }
      const doc = await res.json().catch(() => null) as { ok?: boolean; wake?: unknown } | null
      const w = doc?.wake as { attempted?: unknown; woke?: unknown; reason?: unknown } | undefined
      if (doc?.ok === true && w && typeof w.attempted === 'boolean' && typeof w.woke === 'boolean' && typeof w.reason === 'string') {
        return { ok: true, receipt: { attempted: w.attempted, woke: w.woke, reason: w.reason, mode: typeof w.mode === 'string' ? w.mode : null, accepted: typeof w.accepted === 'boolean' ? w.accepted : null } }
      }
      return { ok: false, reason: 'watchdog wake response is not a receipt shape — normalized to explicit failure, never trusted blindly' }
    } catch (e) {
      return { ok: false, reason: `watchdog wake call failed: ${e instanceof Error ? e.message : String(e)}` }
    }
  }

  /**
   * t261006-06 default spawn caller: POST to the watchdog
   * /sandbar-watchdog/api/one-shot/run route (same same-origin discipline as
   * the wake caller: the Host header verbatim, no credentials, no path
   * following, no outbound rewrite). The receipt is validated to shape;
   * non-200 / non-JSON / non-receipt bodies normalize into ok:false with the
   * reason named. An unresolvable base is an explicit no-op.
   */
  async function defaultSpawnCaller(args: { project: string; requestId: string; action: string }, origin: string): Promise<SpawnCallResult> {
    const base = resolveWorkbenchBase(deps.workbenchBase, env, origin)
    if (base === '') return { ok: false, reason: 'watchdog spawn endpoint base not resolvable (no SANDBAR_WORKBENCH_BASE, request origin absent) — spawn not attempted' }
    try {
      const res = await fetch(base + '/sandbar-watchdog/api/one-shot/run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ project: args.project, request_id: args.requestId, action: args.action }),
        signal: AbortSignal.timeout(10_000),
      })
      const doc = await res.json().catch(() => null) as { ok?: boolean; spawn?: unknown; error?: unknown } | null
      if (doc?.ok !== true || typeof doc.spawn !== 'object' || doc.spawn === null) {
        const why = typeof doc?.error === 'string' ? doc.error : `watchdog spawn endpoint HTTP ${res.status}`
        return { ok: false, reason: why }
      }
      const sp = doc.spawn as { action?: unknown; sessionId?: unknown; objectKey?: unknown; outcome?: unknown; summary?: unknown }
      if (sp.action !== 'done' || typeof sp.sessionId !== 'string') {
        return { ok: false, reason: 'watchdog spawn response is not a done-receipt — normalized to explicit failure, never trusted blindly' }
      }
      return { ok: true, receipt: {
        action: String(sp.action),
        sessionId: sp.sessionId,
        ...(typeof sp.objectKey === 'string' ? { objectKey: sp.objectKey } : {}),
        ...(typeof sp.outcome === 'string' ? { outcome: sp.outcome } : {}),
        ...(typeof sp.summary === 'string' ? { summary: sp.summary } : {}),
      } }
    } catch (e) {
      return { ok: false, reason: `watchdog spawn call failed: ${e instanceof Error ? e.message : String(e)}` }
    }
  }

  async function handle(method: string, path: string, query: URLSearchParams, bodyRaw: string, origin = '', auth: AuthInput = {}): Promise<ApiResponse> {
    // ---- 路由表准入守卫（t261003-10）：表外一律 404，表内每条都必须在下方有处理分支
    // （route-parity UT 双向锁死）——这是「未知面板路由」的唯一出口。
    if (!(PANEL_API_ROUTES as ReadonlyArray<{ path: string }>).some((r) => r.path === path)) {
      return bad(404, `未知面板路由：${path}`)
    }
    // ---- 写面凭据门（KI-193）：一切写方法先过门再碰任何解析/写盘——401 时
    // 账本与声明逐字节不动。GET 不设门（读面开放，页面要能加载）。
    if (method === 'POST' || method === 'PUT' || method === 'DELETE') {
      const verdict = (deps.authFace ?? defaultAuthFace)(auth)
      if (!verdict.ok) {
        return bad(401, `panel write refused (401): ${verdict.why} — file requests via server/engine/executor_requests (engine entry); the panel does not mint credentials (KI-193)`)
      }
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
      // KI-193：写者不由调用方自报——凭据能证明的唯一身份就是 'host'（固定值）。
      // body.by 只作兼容保留：带了且 ≠'host' → 应答行带 by_claimed + writer_mismatch，
      // 台账里「host 的决定」不再能被任意命名（错配可见，不静默）。
      const byClaimed = typeof b.by === 'string' ? b.by : undefined
      const mismatch = byClaimed !== undefined && byClaimed !== 'host'
      const res = answerRequest(ledgerIo, env, String(b.project ?? ''), b.id, b.answer, 'host', now(),
        mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : undefined)
      if (!res.ok) {
        // t261007-02: the answer refusals moved to English copy (writing standard);
        // match the same three classes. LEGACY_PROJECT_BAD is the existing
        // malformedProjectMessage prefix constant (legacy copy, not reworded here).
        const status = res.error.startsWith(LEGACY_PROJECT_BAD) || res.error.startsWith('id must')
          || res.error.startsWith('answer must')
          ? 400
          : res.error.startsWith('no such request') ? 404 : 409
        return bad(status, res.error)
      }
      // t261004-29: the wake is pushed only after the answer has landed (the answer
      // is never lost to a wake failure). The receipt is merged additively into the
      // response (attempted/woke/reason) — "was a wake attempted and why" travels
      // back with the answer. The receipt shape is validated HERE, for injected
      // callers too: a non-receipt-shaped result is normalized into an explicit
      // failure, never trusted blindly and never echoed verbatim.
      const caller = deps.wakeCaller ?? ((a: { project: string; requestId: string; detail: string }) => defaultWakeCaller(a, origin))
      let wake: Record<string, unknown>
      try {
        const r = await caller({ project: String(b.project ?? ''), requestId: String(b.id ?? ''), detail: typeof b.answer === 'string' ? b.answer.slice(0, WAKE_PUSH_DETAIL_CAP) : '' })
        const rc = r.ok ? r.receipt : null
        if (rc !== null && typeof rc.attempted === 'boolean' && typeof rc.woke === 'boolean' && typeof rc.reason === 'string' && rc.reason.length > 0) {
          wake = { attempted: rc.attempted, woke: rc.woke, reason: rc.reason }
        } else {
          wake = { attempted: false, woke: false, reason: r.ok
            ? 'wake caller returned a non-receipt-shaped result — normalized to explicit failure, never trusted blindly'
            : r.reason }
        }
      } catch (e) {
        wake = { attempted: false, woke: false, reason: `wake caller threw: ${e instanceof Error ? e.message : String(e)}` }
      }
      return { status: 200, json: { ok: true, answered: res.answerRow, wake,
        ...(mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : {}) } }
    }
    // t261007-01: the dismiss write rides the SAME credential gate as the answer
    // write (the gate at dispatch above covers it — no second door), and the
    // writer is the fixed 'host' exactly like the answer path. No wake is pushed:
    // a dismiss carries no decision, so the executor has nothing new to wake for
    // (the default action it already runs is unchanged).
    if (path === '/sandbar-executor-panel/api/requests/dismiss') {
      if (method !== 'POST') return bad(405, 'dismiss face is POST-only (write operation, explicit trace)')
      const parsed = parseJsonBody(bodyRaw)
      if (!parsed.ok) return bad(400, parsed.error)
      const b = parsed.body
      // KI-193, same as answer: the writer is never caller-asserted. A body `by`
      // that differs from 'host' is kept only as by_claimed + writer_mismatch.
      const byClaimed = typeof b.by === 'string' ? b.by : undefined
      const mismatch = byClaimed !== undefined && byClaimed !== 'host'
      const projectKey = String(b.project ?? '')
      if (!PROJECT_KEY_RE.test(projectKey)) return bad(400, malformedProjectMessage(b.project))
      const res = dismissRequest(ledgerIo, env, projectKey, b.id, 'host', now(),
        mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : undefined)
      if (!res.ok) {
        // Stable error-message prefixes, same design as the answer path
        // (fault-mode item 7): shape refusals = 400, unknown id = 404, the
        // rest = 409. The project-key shape is checked here so no CJK copy of
        // the shared malformed-key message is duplicated in the prefix test.
        const status = res.error.startsWith('id must')
          ? 400
          : res.error.startsWith('no such request') ? 404 : 409
        return bad(status, res.error)
      }
      return { status: 200, json: { ok: true, dismissed: res.dismissRow,
        ...(mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : {}) } }
    }
    // ---- t261007-02: host state change (dismissed only; see setThreadState) ----
    if (path === '/sandbar-executor-panel/api/requests/state') {
      if (method !== 'POST') return bad(405, 'state face is POST-only (a write, recorded on the trail)')
      const parsed = parseJsonBody(bodyRaw)
      if (!parsed.ok) return bad(400, parsed.error)
      const b = parsed.body
      const res = setThreadState(ledgerIo, env, String(b.project ?? ''), b.id, b.state, 'host', now())
      if (!res.ok) {
        // the refusal carries its own status hint (no message-text matching)
        return bad(res.status ?? 409, res.error)
      }
      return { status: 200, json: { ok: true, state: res.stateRow } }
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
          // t261003-06：仅授权面收回（保留会话点名）；守望者的 enabled:false 语义由上面
          // revokeAll 承担。t261004-18（KI-193 review #1）：清权半边同走引擎入口
          // （META_OP 判定+审计），不再直写声明文件。
          const prev = prevDecl(key)
          const g = await engineGrantsWrite(key, {
            grants: {},
            ...(prev.ok && prev.declaration?.executor_sessions ? { executor_sessions: prev.declaration.executor_sessions } : {}),
            ...(prev.ok && prev.declaration?.night_tier ? { night_tier: { ...prev.declaration.night_tier, enabled: false } } : {}),
          }, parsed.body.by)
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
        //   op:'master' + enabled:false → 仅授权面收回（清 grants、留会话点名、
        //   绝不碰 watchdog.json——「收回授权只影响授权，守望者照常运行」）；
        //   op:'master' + enabled:true  → 全部六操作授予。
        // t261004-18（KI-193）：三个写面（save/master/clear）一律走引擎入口
        // executor-grants-write（META_OP 判定+审计单一真源），不再直写声明文件；
        // 写者固定 'host'，body.by 只作错配记录。
        const prev = prevDecl(key)
        // t261004-41: the open-ticket keys inherit from the on-disk declaration on every
        // write face (save / master on/off) — a partial edit or a master toggle must
        // never silently wipe the epic list or reset the cap (same rule as executor_sessions).
        const prevEpics = prev.ok && Array.isArray(prev.declaration?.open_ticket_epics)
          ? prev.declaration.open_ticket_epics : []
        const prevCap = prev.ok && typeof prev.declaration?.open_ticket_cap === 'number'
          ? prev.declaration.open_ticket_cap : undefined
        let doc: Record<string, unknown>
        if (b.op === 'master') {
          doc = b.enabled === false
            ? {
                grants: {},
                ...(prev.ok && prev.declaration?.executor_sessions ? { executor_sessions: prev.declaration.executor_sessions } : {}),
                ...(prev.ok && prev.declaration?.night_tier ? { night_tier: { ...prev.declaration.night_tier, enabled: false } } : {}),
                open_ticket_epics: prevEpics,
                ...(prevCap !== undefined ? { open_ticket_cap: prevCap } : {}),
              }
            : {
                grants: Object.fromEntries(GRANT_OPS.map((op) => [op, true])),
                ...(prev.ok && prev.declaration?.executor_sessions ? { executor_sessions: prev.declaration.executor_sessions } : {}),
                open_ticket_epics: prevEpics,
                ...(prevCap !== undefined ? { open_ticket_cap: prevCap } : {}),
              }
        } else {
          // 部分编辑不丢字段：body 没给 executor_sessions = 从盘上现声明继承
          //（与旧 saveGrantsDecl 同语义，t261003-06 缺陷一）。
          // t261004-41: open_ticket_epics / open_ticket_cap follow the same rule —
          // given → move it (an explicit [] is a real clear-all), absent → inherit.
          doc = {
            grants: (b.grants ?? {}) as Record<string, unknown>,
            ...(b.night_tier !== undefined ? { night_tier: b.night_tier } : {}),
            ...(b.executor_sessions !== undefined
              ? { executor_sessions: b.executor_sessions }
              : prev.ok && prev.declaration?.executor_sessions ? { executor_sessions: prev.declaration.executor_sessions } : {}),
            ...(b.open_ticket_epics !== undefined
              ? { open_ticket_epics: b.open_ticket_epics }
              : { open_ticket_epics: prevEpics }),
            ...(b.open_ticket_cap !== undefined
              ? { open_ticket_cap: b.open_ticket_cap }
              : prevCap !== undefined ? { open_ticket_cap: prevCap } : {}),
          }
        }
        const res = await engineGrantsWrite(key, doc, b.by)
        if (!res.saved) return { status: 200, json: { ok: false, saved: false, error: res.reason, reason: res.reason } }
        const mismatch = b.by !== undefined && b.by !== null && b.by !== 'host'
        return { status: 200, json: { ok: true, saved: true, file: res.file, declaration: res.resolved,
          ...(b.op === 'master' ? { note: b.enabled === false ? 'all permissions revoked (session naming kept, watchdog untouched)' : 'all six permissions granted' } : {}),
          ...(mismatch ? { by_claimed: b.by, writer_mismatch: true } : {}) } }
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
      // Unavailable = 200 + ok:false + a named reason (the page renders an explicit
      // degraded card); never render an empty list pretending "no actions".
      // t261005-12: last_record_failure rides EVERY branch — an empty record with a
      // failure marker must surface the failure, never the silent empty state (the
      // ticket's headline defect face).
      if (!read.ok) return { status: 200, json: { ok: false, source: read.source, reason: read.reason, last_record_failure: read.last_record_failure } }
      return {
        status: 200,
        json: {
          ok: true, source: read.source, actions: read.actions,
          malformed_rows: read.malformed_rows, unknown_op_rows: read.unknown_op_rows,
          deduped_rows: read.deduped_rows, older_rows: read.older_rows,
          gaps_recent: read.gaps_recent, gaps_file: read.gapsFile,
          last_record_failure: read.last_record_failure,
          note: read.older_rows > 0
            ? 'Showing the latest ' + read.actions.length + ' action(s). Older rows are in ' + read.source + '.'
            : undefined,
        },
      }
    }
    // ---- one-shot spawn (t261006-06): forward an APPROVED request to the
    // watchdog ignition route. The panel is a relay, not the gate: the
    // watchdog re-checks the approval ledger itself, so a race between the
    // panel view and the ledger can never widen the gate. This face re-checks
    // "answered" only to fail fast with a readable error.
    if (path === '/sandbar-executor-panel/api/one-shot/spawn') {
      if (method !== 'POST') return bad(405, 'spawn face is POST-only (write operation, explicit trace)')
      const parsed = parseJsonBody(bodyRaw)
      if (!parsed.ok) return bad(400, parsed.error)
      const b = parsed.body
      const key = String(b.project ?? '')
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      const requestId = typeof b.request_id === 'string' ? b.request_id : ''
      if (requestId === '') return bad(400, 'request_id must be a non-empty string')
      const action = typeof b.action === 'string' ? b.action.trim() : ''
      if (action === '') return bad(400, 'action must be a non-empty string naming the exact privileged action')
      // Fail fast: an unanswered request never reaches the watchdog (the
      // watchdog gate stays authoritative either way).
      const read = readRequests(ledgerIo, env, key)
      const row = read.rows.find((r) => r.id === requestId)
      if (!row) return bad(404, `request ${requestId} not found in project ${key} — nothing to spawn`)
      if (row.status !== 'answered') return bad(409, `request ${requestId} is not answered yet — the human approval IS the gate; nothing spawns`)
      const caller = deps.spawnCaller ?? ((a: { project: string; requestId: string; action: string }) => defaultSpawnCaller(a, origin))
      let spawn: Record<string, unknown>
      try {
        const r = await caller({ project: key, requestId, action })
        if (r.ok) spawn = { attempted: true, spawned: true, ...r.receipt }
        else spawn = { attempted: true, spawned: false, reason: r.reason }
      } catch (e) {
        spawn = { attempted: true, spawned: false, reason: `spawn caller threw: ${e instanceof Error ? e.message : String(e)}` }
      }
      return { status: 200, json: { ok: true, spawn } }
    }
    // ---- one-shot sessions (t261004-30 read-only face: settles / locks / runs / cap) ----
    if (path === '/sandbar-executor-panel/api/one-shot') {
      if (method !== 'GET') return bad(405, 'read-only: GET only')
      const key = query.get('project') ?? ''
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      const face = readOneShotFace(deps.oneShotIo ?? fsOneShotIo, env, key)
      return { status: 200, json: { ok: true, one_shot: face, note: 'read-only; settles come from the engine settle ledger, locks/runs from the watchdog data dir' } }
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
    // ---- bridge status (t261004-44, KI-196 way out (2)): a bridge that does not fire must be readable ----
    if (path === '/sandbar-executor-panel/api/bridge/status') {
      if (method !== 'GET') return bad(405, 'read-only face: GET only')
      const read = deps.bridgeStatus
      if (!read) {
        // Read source not wired (headless load / createApi used directly): an explicit
        // unknown shape -- mounted:false says "this face is not wired", not "the bridge
        // is healthy". Named, never silent.
        return { status: 200, json: { ok: true, mounted: false, counters: {},
          last_events: [], at: now(),
          note: 'bridge status sink not wired into this API instance — no bridge health claim, check the host plugin mount log' } }
      }
      let snap: BridgeStatusSnapshot
      try {
        snap = read()
      } catch (e) {
        return bad(500, `bridge status snapshot failed: ${e instanceof Error ? e.message : String(e)}`)
      }
      if (!snap || typeof snap !== 'object' || typeof snap.mounted !== 'boolean'
          || typeof snap.counters !== 'object' || snap.counters === null
          || !Array.isArray(snap.last_events)) {
        return bad(500, 'bridge status snapshot shape is wrong (need {mounted:boolean, counters:object, last_events:[]}) — face refuses to fake a shape')
      }
      return { status: 200, json: { ok: true, ...snap } }
    }
    // ---- inspection trigger records (t261006-15, P4) ----
    if (path === '/sandbar-executor-panel/api/inspection/trigger-records') {
      if (method !== 'GET') return bad(405, 'read-only face: GET only')
      const key = query.get('project') ?? ''
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      const read = readTriggerRecords(deps.triggerIo ?? fsTriggerIo, env, key)
      if (!read.ok) {
        // An empty state is not an error state (200 + ok:false + human reason, same
        // degraded style as the requests read side).
        return { status: 200, json: { ok: false, source: read.source, reason: read.reason, rows: [] } }
      }
      return { status: 200, json: { ok: true, source: read.source, rows: read.rows,
        malformed_rows: read.malformed_rows, hidden_rows: read.hidden_rows,
        note: 'newest first by at; the full history stays in the project trigger record file' } }
    }
    // ---- inspection trigger (t261006-15, P3) — write, KI-193 gated above ----
    if (path === '/sandbar-executor-panel/api/inspection/trigger') {
      if (method !== 'POST') return bad(405, 'trigger face is POST-only (write operation, explicit trace)')
      const parsed = parseJsonBody(bodyRaw)
      if (!parsed.ok) return bad(400, parsed.error)
      const v = validateTriggerInput(parsed.body)
      if (!v.ok) return bad(400, v.error)
      // KI-193: the writer is named by the credential, fixed 'host'; a caller-reported
      // by lands only in by_claimed (writer_mismatch visible).
      const spawnFace: SpawnTriggerFace = deps.spawnTrigger ?? makeDefaultSpawnTrigger(env)
      let spawnRes: Awaited<ReturnType<SpawnTriggerFace>>
      try {
        spawnRes = await spawnFace(v.value)
      } catch (err) {
        spawnRes = { ok: false, error: `trigger spawn face threw: ${err instanceof Error ? err.message : String(err)}` }
      }
      const record = {
        at: now(),
        by: 'host' as const,
        ...(v.by_claimed !== undefined ? { by_claimed: v.by_claimed, writer_mismatch: true } : {}),
        project: v.value.project,
        instance: v.value.instance,
        scope: v.value.scope,
        reason: v.value.reason,
        spawn: spawnRes.ok
          ? { ok: true, ...(spawnRes.ticket_id ? { ticket_id: spawnRes.ticket_id } : {}) }
          : { ok: false, error: spawnRes.error },
      }
      const written = appendTriggerRecord(deps.triggerIo ?? fsTriggerIo, env, v.value.project, record)
      if (!written.ok) return bad(500, written.error)
      // A failed trigger is an explicit 502 carrying the already-written attribution
      // row — the attempt keeps its name, success or failure, never silent.
      if (!spawnRes.ok) {
        return { status: 502, json: { ok: false, error: spawnRes.error, record, written: written.file } }
      }
      return { status: 200, json: { ok: true, record, written: written.file } }
    }
    // ---- concurrency declaration (t261005-10, UI-2): the Overview limit row's face ----
    // ---- concurrency (t261006-17, CL-2): read the engine ledger / save the limit ----
    if (path === '/sandbar-executor-panel/api/concurrency') {
      const key = query.get('project') ?? ''
      if (!PROJECT_KEY_RE.test(key)) return bad(400, malformedProjectMessage(key))
      if (method === 'GET') {
        const read = await (deps.engineConcurrencyRead ?? readConcurrency)(key, env)
        if (!read.ok) {
          // The engine's named refusal travels verbatim (declaration absent/malformed,
          // malformed ledger, engine unreachable): the consumer renders an explicit
          // degraded card, never an "empty list" fake. declared:false + limit:null ride
          // along so the t261005-10 read-only row keeps its fact shape; an ABSENT
          // declaration is reported as a fact (ok:true) with the engine's refusal text
          // carried in `reason` — the engine gate itself still refuses to run without
          // one (rule 9), so nothing here guesses a number.
          const absent = /declaration absent/i.test(read.reason)
          const face: Record<string, unknown> = absent
            ? { ok: true, project: key, declared: false, limit: null, unlimited: false,
                path: concurrencyDeclarationPath(key, env), reason: read.reason,
                note: 'No concurrency limit declaration. The engine gate refuses to run a lane without one (CL-2 boundary: the write control saves through the engine entry).' }
            : { ok: false, project: key, reason: read.reason, declared: false, limit: null,
                path: concurrencyDeclarationPath(key, env) }
          return { status: 200, json: face }
        }
        const audit = readLastLimitAudit(key, env)
        return {
          status: 200,
          json: {
            ok: true, project: key,
            declared: true, path: read.decl,
            limit: read.limit, unlimited: read.unlimited,
            at_work: read.holders.length, waiting: read.queue.length,
            holders: read.holders, queue: read.queue, decl: read.decl,
            audit: audit.ok ? { ok: true, by: audit.row.by, ts: audit.row.ts, from: audit.row.from, to: audit.row.to, file: audit.file }
              : { ok: false, reason: audit.reason, file: audit.file },
            note: 'numbers come from the engine ledger — the panel never recomputes positions or waited seconds',
          },
        }
      }
      if (method !== 'POST') return bad(405, 'GET/POST only (POST = save the limit through the engine entry)')
      const parsed = parseJsonBody(bodyRaw)
      if (!parsed.ok) return bad(400, parsed.error)
      const b = parsed.body as Record<string, unknown>
      const limit = b.limit
      if (limit !== CONCURRENCY_UNLIMITED
        && (typeof limit !== 'number' || !Number.isInteger(limit) || limit < CONCURRENCY_LIMIT_MIN || limit > CONCURRENCY_LIMIT_MAX)) {
        return bad(422, `limit must be an integer ${CONCURRENCY_LIMIT_MIN}..${CONCURRENCY_LIMIT_MAX} or the string "${CONCURRENCY_UNLIMITED}" (got ${JSON.stringify(limit ?? null)})`)
      }
      const byClaimed = typeof b.by === 'string' ? b.by : undefined
      // KI-193: the writer is fixed 'host' (the only identity the credential proves);
      // a body `by` is recorded as a mismatch, never authority.
      const payload = { project: key, limit: limit as number | 'unlimited', by: 'host', source: auditSource(byClaimed) }
      const res = await (deps.engineConcurrencyWrite ?? spawnConcurrencyLimitWrite)(payload)
      const mismatch = byClaimed !== undefined && byClaimed !== null && byClaimed !== 'host'
      if (!res.saved) {
        // A refusal is the editor working (same semantics as settings/grants): 200 +
        // saved:false + the named reason; while CL-2b has not landed the engine
        // answers "unknown subcommand" -> the pinned engine-entry-absent refusal.
        // The claimed identity stays visible on the failure branch too (never
        // swallowed by the save outcome).
        return { status: 200, json: { ok: false, saved: false, error: res.reason, reason: res.reason,
          ...(mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : {}) } }
      }
      return { status: 200, json: { ok: true, saved: true, project: key, limit: res.limit, audit_row: res.audit_row, decl: res.decl,
        ...(mismatch ? { by_claimed: byClaimed, writer_mismatch: true } : {}) } }
    // t261005-10 (UI-2) note: its GET-only declaration read face on this route is
    // SUPERSEDED by this CL-2 face (engine-ledger numbers + save); the response is a
    // superset (limit/unlimited/decl), so the read-only row keeps working off `decl`.
    }
    return bad(404, `未知面板路由：${path}`)
  }

  return { handle }
}

/**
 * concurrency-limit.json parse (t261005-10 pure function, UT-covered; mirrors the
 * server/engine/concurrency.py validate_limit rules — schema {"version":1,"limit":1..10|"unlimited"}):
 *   - "unlimited" -> null (the engine's None synonym);
 *   - int 1..10 -> number; non-integer / out-of-range / missing key / non-object -> throw
 *     (the message goes verbatim into the page's named degraded face).
 * A throw is a refusal: no guessing, no silent default — the caller shows the reason.
 */
export function parseConcurrencyDoc(raw: string): number | null {
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    throw new Error(`concurrency-limit.json is not valid JSON: ${e instanceof Error ? e.message : String(e)}`)
  }
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) {
    throw new Error('concurrency-limit.json must be a JSON object {"version":1,"limit":1..10|"unlimited"}')
  }
  const o = doc as Record<string, unknown>
  if (o.version !== 1) throw new Error(`concurrency-limit.json version must be 1 (got ${JSON.stringify(o.version ?? null)})`)
  const v = o.limit
  if (v === 'unlimited') return null
  if (typeof v !== 'number' || !Number.isInteger(v)) {
    throw new Error(`concurrency-limit.json limit must be an int 1..10 or "unlimited" (got ${JSON.stringify(v ?? null)})`)
  }
  if (v < 1 || v > 10) throw new Error(`concurrency-limit.json limit ${v} is out of range (1..10)`)
  return v
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
