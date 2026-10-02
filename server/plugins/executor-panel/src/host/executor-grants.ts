/**
 * executor-grants.ts —— 执行器授权声明读写面（t260930-14）：面板从「派生显示」
 * 变成项目级声明 executor-grants.json 的读写编辑器；引擎写路径
 * （server/engine/executor_grants.py）按同一声明判定执行器身份的写操作。
 *
 * 声明真源（与引擎项目注册表同根——SANDBAR_PROJECTS_DIR 优先，缺省 ~/.sandbar/projects）：
 *   <root>/<key>/executor-grants.json         声明本体（本模块写、引擎 Python 读判）
 *   <root>/<key>/executor-grants-audit.jsonl  审计账（每次授予变更各记一行，append-only；
 *                                             引擎侧拒收也写同 schema 行）
 *
 * schema（version 1，与引擎 validate_declaration 镜像——两侧测试互锁）：
 *   {"version":1, "grants":{"sign":true,...}, "night_tier":{"enabled":true,"until":<ms>,"note"?},
 *    "updated_by":"...","updated_at":<ms>}
 *
 * 纪律（与 settings.ts 同一族）：
 *  - 溯源逐项可答「哪个声明哪条键定的」（KI-148/149）——provenance.keys 直接给
 *    键路径（grants.<op> / night_tier / not-declared），不二次推导；
 *  - 保存=先过本模块校验 → tmp → 回读字节再校验 → 原子 rename；任一步拒收：
 *    tmp 删除、盘上原文件逐字节不动、人话理由；
 *  - 元权限反锁：请求带 executor 身份标记（caller_surface=executor-session）时
 *    一律拒收——改/扩/缩授予清单是宿主特权，执行器永远不能自己做。标记是
 *    尽力面（同引擎 injected_by 档位）：它回答「谁自称执行器」，反锁的硬保证
 *    在引擎侧（executor_grants.META_OP 先于声明读取拒收）。
 */

import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync, appendFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { malformedProjectMessage } from './project-key.ts'

/** 引擎固定授予操作面（真源=引擎 executor_grants.GRANT_OPS / 设计稿决定 10 词表；
 *  面板历史显示名 'reject' = 声明键 'send-back' 的别名，DISPLAY_ALIAS 双向映射）。 */
export const GRANT_OPS = ['sign', 'send-back', 'rerun', 'open-ticket', 'pause-resume', 'cleanup'] as const
export type GrantOp = (typeof GRANT_OPS)[number]

/** 面板显示名 ↔ 声明键（grants.ts FIXED_OPS 的 'reject' 与设计稿 'send-back' 同物）。 */
export const DISPLAY_ALIAS: Record<string, string> = { reject: 'send-back' }
export function toGrantOp(name: string): string {
  return (DISPLAY_ALIAS as Record<string, string>)[name] ?? name
}

export const DECL_VERSION = 1
/** 执行器身份通道标记（POST body 顶层；引擎侧同名语义=SANDBAR_CALLER_IDENTITY_SRC='cwd'）。 */
export const EXECUTOR_SURFACE = 'executor-session'
/** 夜间档时间盒上限（毫秒，与引擎 NIGHT_TIER_MAX_MS 镜像：最长 7 天）。 */
export const NIGHT_TIER_MAX_MS = 7 * 24 * 3600 * 1000

export interface NightTier { enabled: boolean; until: number; note?: string }

export interface GrantsDecl {
  version: number
  grants: Partial<Record<GrantOp, true>>
  /** 本项目执行器会话 id（dsh session id，t261001-20）：宿主点名「谁算本项目执行器」
   *  ——引擎判闸把调用方会话 id（env DSH_SESSION_ID / DSH_HEADLESS_SESSION）与本表
   *  比对，被点名才以执行器身份受闸。与引擎 EXECUTOR_SESSIONS_MAX(8)/
   *  EXECUTOR_SESSION_ID_MAX(128) 镜像。 */
  executor_sessions?: string[]
  night_tier?: NightTier
  updated_by?: string
  updated_at?: number
}

/**
 * 声明根（与引擎 perkey_projects_root 同根：生产形态两个 env 都缺席 →
 * ~/.sandbar/projects）。注入优先级仅服务隔离台测试（watchdog/panel 测试惯例
 * 已注入各自 env）：SANDBAR_PROJECTS_DIR（引擎注册表根语义）> SANDBAR_WATCHDOG_DIR
 * > SANDBAR_PANEL_DIR > 缺省 ~/.sandbar/projects。 */
export function grantsConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_PROJECTS_DIR || env.SANDBAR_WATCHDOG_DIR || env.SANDBAR_PANEL_DIR
    || join(env.HOME || '', '.sandbar', 'projects')
}

export function declarationPath(key: string, env: NodeJS.ProcessEnv = process.env): string {
  return join(grantsConfigDir(env), key, 'executor-grants.json')
}

export function auditPath(key: string, env: NodeJS.ProcessEnv = process.env): string {
  return join(grantsConfigDir(env), key, 'executor-grants-audit.jsonl')
}

/** 审计落账（追加一行；失败不掩盖主流程——审计是尽力面）。 */
export function appendAudit(key: string, row: Record<string, unknown>, env: NodeJS.ProcessEnv = process.env): void {
  try {
    const file = auditPath(key, env)
    mkdirSync(dirname(file), { recursive: true })
    appendFileSync(file, JSON.stringify(row) + '\n', 'utf8')
  } catch { /* 尽力面：审计写失败不掩盖主结果 */ }
}

/** 声明形状校验（镜像引擎 validate_declaration；返回 [normalized, error]。 */
export function validateDeclaration(doc: unknown): [GrantsDecl, string | null] {
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) {
    return [{} as GrantsDecl, `声明顶层必须是 JSON 对象（收到 ${doc === null ? 'null' : typeof doc}）`]
  }
  const d = doc as Record<string, unknown>
  if (d.version !== DECL_VERSION) return [{} as GrantsDecl, `声明 version 必须是 ${DECL_VERSION}（收到 ${String(d.version)}）`]
  const grantsIn = (d.grants ?? {}) as unknown
  if (typeof grantsIn !== 'object' || grantsIn === null || Array.isArray(grantsIn)) {
    return [{} as GrantsDecl, `grants 必须是 JSON 对象（收到 ${typeof grantsIn}）`]
  }
  const grants: GrantsDecl['grants'] = {}
  for (const [k, v] of Object.entries(grantsIn as Record<string, unknown>)) {
    if (!(GRANT_OPS as readonly string[]).includes(k)) {
      return [{} as GrantsDecl, `grants 键 ${k} 不在固定操作面 [${GRANT_OPS.join(', ')}] 内——未知操作不给静默承认`]
    }
    if (typeof v !== 'boolean') return [{} as GrantsDecl, `grants.${k} 必须是 boolean（收到 ${String(v)}）`]
    if (v) (grants as Record<string, true>)[k] = true
  }
  const out: GrantsDecl = { version: DECL_VERSION, grants }
  // t261001-20：执行器会话点名（镜像引擎 validate_declaration 的 executor_sessions 规则：
  // 非空字符串数组、去重保序、单 id ≤128 字符、至多 8 个）。
  const MAX_SESSIONS = 8
  const MAX_SESSION_ID = 128
  const sessionsIn = d.executor_sessions
  if (sessionsIn !== undefined && sessionsIn !== null) {
    if (!Array.isArray(sessionsIn) || sessionsIn.some((s) => typeof s !== 'string' || !s.trim())) {
      return [{} as GrantsDecl, `executor_sessions 必须是非空字符串数组（收到 ${JSON.stringify(sessionsIn)}）`]
    }
    const sessions: string[] = []
    for (const s of sessionsIn as string[]) {
      const sid = s.trim()
      if (sid.length > MAX_SESSION_ID) {
        return [{} as GrantsDecl, `executor_sessions 项超限（${sid.length} > ${MAX_SESSION_ID} 字符）`]
      }
      if (!sessions.includes(sid)) sessions.push(sid)
    }
    if (sessions.length > MAX_SESSIONS) {
      return [{} as GrantsDecl, `executor_sessions 至多 ${MAX_SESSIONS} 个会话 id（收到 ${sessions.length}）——缩表后再存`]
    }
    out.executor_sessions = sessions
  }
  const night = d.night_tier
  if (night !== undefined && night !== null) {
    if (typeof night !== 'object' || Array.isArray(night)) {
      return [{} as GrantsDecl, `night_tier 必须是对象 {enabled, until, note?}（收到 ${typeof night}）`]
    }
    const n = night as Record<string, unknown>
    if (typeof n.enabled !== 'boolean' || typeof n.until !== 'number' || !Number.isFinite(n.until)) {
      return [{} as GrantsDecl, `night_tier 需 {enabled: boolean, until: 毫秒时间戳}（收到 enabled=${String(n.enabled)} until=${String(n.until)}）`]
    }
    if (n.note !== undefined && typeof n.note !== 'string') {
      return [{} as GrantsDecl, `night_tier.note 必须是字符串（收到 ${String(n.note)}）`]
    }
    out.night_tier = { enabled: n.enabled, until: Math.trunc(n.until), ...(typeof n.note === 'string' ? { note: n.note.slice(0, 500) } : {}) }
  }
  if (typeof d.updated_by === 'string') out.updated_by = d.updated_by
  if (typeof d.updated_at === 'number') out.updated_at = d.updated_at
  return [out, null]
}

export interface DeclRead {
  ok: boolean
  declared: boolean
  file: string
  declaration: GrantsDecl | null
  /** 拒收种类（absent=项目还没声明过；malformed/unreadable=声明坏了 fail-closed）。 */
  kind?: 'absent' | 'malformed' | 'unreadable'
  error?: string
}

/** 声明读面（GET 消费）：缺席=absent（真声明缺席，不冒充空授予）；坏=点名种类。 */
export function readDeclaration(key: string, env: NodeJS.ProcessEnv = process.env): DeclRead {
  const file = declarationPath(key, env)
  if (!existsSync(file)) {
    return { ok: false, declared: false, kind: 'absent', file, declaration: null,
             error: `项目 ${key} 尚无执行器授权声明（缺 ${file}）——零授予=只读与问` }
  }
  let raw: string
  try {
    raw = readFileSync(file, 'utf8')
  } catch (e) {
    return { ok: false, declared: true, kind: 'unreadable', file, declaration: null,
             error: `执行器授权声明不可读（${file}）：${e instanceof Error ? e.message : String(e)}——引擎侧 fail-closed 拒收` }
  }
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { ok: false, declared: true, kind: 'malformed', file, declaration: null,
             error: `执行器授权声明 JSON 解析失败（${file}）：${e instanceof Error ? e.message : String(e)}——引擎侧 fail-closed 拒收` }
  }
  const [decl, err] = validateDeclaration(doc)
  if (err) {
    return { ok: false, declared: true, kind: 'malformed', file, declaration: null,
             error: `执行器授权声明被拒收（${file}）：${err}——引擎侧 fail-closed 拒收` }
  }
  return { ok: true, declared: true, file, declaration: decl }
}

/**
 * 某 op 此刻是否被真声明授予（声明键 grants.<op>=true，或活跃夜间档）。
 * t261001-21：读出面专用——派生能力矩阵每行带 granted，行存在≠已授予；
 * 判定语义仍只在引擎写路径（本函数只回答「读出面显示什么」，不放行任何写操作）。
 */
export function isOpGranted(read: DeclRead, op: string, nowMs: number): boolean {
  const key = toGrantOp(op)
  if (read.ok && read.declaration?.grants?.[key as GrantOp] === true) return true
  const nt = read.declaration?.night_tier
  return !!(nt?.enabled && nt.until > nowMs)
}

/** 溯源面：「哪个声明键定了当前值」——逐 op 直接给键路径，不二次推导。 */
export function provenanceKeys(read: DeclRead, nowMs: number): Record<string, string> {
  const keys: Record<string, string> = {}
  for (const op of GRANT_OPS) {
    if (read.ok && read.declaration?.grants?.[op] === true) {
      keys[op] = `grants.${op} @ ${read.file}`
      continue
    }
    const nt = read.declaration?.night_tier
    if (nt?.enabled && nt.until > nowMs) {
      keys[op] = `night_tier.until=${nt.until} @ ${read.file}`
      continue
    }
    keys[op] = read.ok
      ? `not-declared (default: refuse) @ ${read.file}`
      : `no-usable-declaration (${read.kind}) @ ${read.file}`
  }
  return keys
}

export interface SaveOutcome {
  saved: boolean
  reason?: string
  file: string | null
  resolved?: GrantsDecl
}

/**
 * 声明保存（写时回读校验，全失败路径原文件逐字节不动）。
 * 反锁：callerSurface=executor-session 一律拒收（元权限归宿主）。
 */
export function saveGrantsDecl(
  key: string, next: unknown, by: string, env: NodeJS.ProcessEnv, nowMs: number,
  callerSurface = '',
): SaveOutcome {
  const file = declarationPath(key, env)
  if (callerSurface === EXECUTOR_SURFACE) {
    return { saved: false, file,
             reason: '执行器元权限反锁：执行器身份不能改/扩/缩自己的授予清单（manage-grants 是宿主特权）——由宿主在执行器面板 Grants 页操作' }
  }
  if (!/^[a-z0-9][a-z0-9-]{0,40}$/.test(String(key ?? ''))) {
    return { saved: false, file: null, reason: malformedProjectMessage(String(key ?? '')) }
  }
  const who = String(by ?? '').trim()
  if (!who) return { saved: false, file, reason: '缺 by（谁在改授予清单——授予变更必须记名）' }
  if (typeof next !== 'object' || next === null || Array.isArray(next)) {
    return { saved: false, file, reason: '声明顶层必须是 JSON 对象' }
  }
  const b = next as Record<string, unknown>
  const doc: Record<string, unknown> = {
    version: DECL_VERSION,
    grants: b.grants ?? {},
    updated_by: who.slice(0, 64),
    updated_at: Math.trunc(nowMs),
  }
  if (b.night_tier !== undefined) doc.night_tier = b.night_tier
  const [normalized, err] = validateDeclaration(doc)
  if (err) return { saved: false, file, reason: err }
  const prev = readDeclaration(key, env)
  const tmp = file + '.tmp'
  try {
    mkdirSync(dirname(file), { recursive: true })
    const serialized = JSON.stringify(normalized, null, 2) + '\n'
    writeFileSync(tmp, serialized, 'utf8')
    const back = JSON.parse(readFileSync(tmp, 'utf8'))
    const [, reErr] = validateDeclaration(back)
    if (reErr) {
      unlinkSync(tmp)
      return { saved: false, file, reason: `回读校验被拒收（不落一份坏声明）：${reErr}` }
    }
    renameSync(tmp, file)
  } catch (e) {
    try { if (existsSync(tmp)) unlinkSync(tmp) } catch { /* tmp 收尸失败不掩盖主错 */ }
    return { saved: false, file, reason: `写盘失败：${e instanceof Error ? e.message : String(e)}` }
  }
  appendAudit(key, {
    at: Math.trunc(nowMs), action: 'grant-change', project: key, who: who.slice(0, 64),
    from: prev.declaration?.grants ?? {}, to: normalized.grants,
    night_tier: normalized.night_tier ?? null,
  }, env)
  return { saved: true, file, resolved: normalized }
}
