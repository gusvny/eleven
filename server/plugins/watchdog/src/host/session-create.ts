/**
 * executor 会话按需代建（t260930-09）——「未声明 = 按需创建；已声明 = 收养」。
 *
 * 宿主决策（260930）：守望者必须自己代建 executor 会话，人不供 id。语义从
 * 「未声明 = 零行为」改为「未声明 = 按需创建；已声明 = 收养（绝不创建、绝不覆盖）」。
 *
 * 创建通路（本机证据，工单 scope 7 定案）：宿主 Session API
 * `ctx.sessionController.create({cwd, agentPreset})`——0.1.5 实装类型
 * （~/.sandbar/dsh-015/.../dsh-api-session-controller/lib/types/index.d.ts）原文：
 *   "Create or idempotently adopt one ordinary Session."（create 即幂等收养语义）
 *   SessionCreateRequest = {workspaceId?, cwd?, sessionId?, agentPreset?}；
 *   失败显式错误族含 `agent-preset/not-found`（点名 preset + available 清单）与
 *   `session/conflict`（同 sessionId 不同 cwd）——preset 缺失由宿主端点名，不猜测。
 * 引擎侧 spawn_agent 是 per-ticket 进程，不是常驻会话——不选它。
 *
 * 结构：纯决策核（decideExecutorSession / 派生面）+ 注入 IO（create/list/事件账），
 * UT 全走桩（零真实宿主、零真实 ~/.sandbar、零 3099/7233）。
 */

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { isValidProjectKey, watchdogConfigDir, writeExecutorSession } from './config.ts'

/** executor preset 名（真源 server/profile/agent-presets/sandbar-executor/ 的 name）。 */
export const EXECUTOR_PRESET_NAME = 'sandbar-executor'

/** 创建/收养通路（node.ts 用宿主 Session API 实现；测试注入桩）。 */
export interface SessionCreateIo {
  /** 宿主 create；失败=显式 error（含宿主点名原因，如 agent-preset/not-found）。 */
  create(input: { cwd: string; agentPreset: string }): Promise<{ ok: true; sessionId: string; agentPreset?: string } | { ok: false; error: string }>
  /** 宿主会话 id 清单；null = 不可读（显式 no-signal，绝不冒充「不在列」）。 */
  listSessionIds(): Promise<string[] | null>
}

/** 代建事件（会话溯源面，scope 6：谁、何时、哪个 preset——与 config-provenance 同纪律）。 */
export interface SessionProvenanceEvent {
  at: number
  project: string
  action: 'create' | 'recreate' | 'adopt' | 'refused'
  session_id: string | null
  preset: string
  by: 'watchdog'
  cwd: string | null
  reason: string
}

/** 事件账路径（dataDir 下按项目一份，append-only JSONL）。 */
export function sessionEventPath(dataDir: string, project: string): string {
  return join(dataDir, `${project}.executor-session.jsonl`)
}

/** 事件落账（追加一行；写失败由调用方点名，不静默）。 */
export function appendSessionEventIo(io: { append(path: string, line: string): Promise<void> }, path: string, ev: SessionProvenanceEvent): Promise<void> {
  return io.append(path, JSON.stringify(ev))
}

/** 事件账读面（面板溯源消费口；坏行跳过并显式计数，不冒充无事件）。 */
export function readSessionEvents(io: { read(path: string): Promise<string> }, path: string): Promise<{ events: SessionProvenanceEvent[]; malformed_rows: number }> {
  return io.read(path).then((raw) => {
    const events: SessionProvenanceEvent[] = []
    let malformed = 0
    for (const line of raw.split('\n')) {
      if (line === '') continue
      try {
        const doc = JSON.parse(line) as SessionProvenanceEvent
        if (typeof doc?.action === 'string' && typeof doc?.at === 'number') events.push(doc)
        else malformed += 1
      } catch {
        malformed += 1
      }
    }
    return { events, malformed_rows: malformed }
  }).catch(() => ({ events: [], malformed_rows: 0 })) // 无事件账 = 还没代建过（真实空），不是错误
}

/**
 * preset 就绪检查（scope 2：preset 缺失必须点名拒绝，绝不猜默认会话）。
 * preset 安装根 = $DSH_HOME/.agent-presets/<name>/preset.yml（本机今天未装——回归
 * 杆自备 temp home，见 tests）。检查面：文件存在且能读出 `name: <name>` 行。
 */
export function presetReady(presetName: string, env: NodeJS.ProcessEnv): { ok: true } | { ok: false; error: string } {
  const home = env.DSH_HOME || join(env.HOME || '', '.dsh')
  const file = join(home, '.agent-presets', presetName, 'preset.yml')
  if (!existsSync(file)) {
    return { ok: false, error: `executor preset 未安装：${presetName}（缺 ${file}）——显式拒绝，绝不代建猜测会话` }
  }
  let raw: string
  try {
    raw = readFileSync(file, 'utf8')
  } catch (e) {
    return { ok: false, error: `executor preset 不可读：${presetName}（${file}）：${e instanceof Error ? e.message : String(e)}` }
  }
  const m = raw.match(/^name:\s*(\S+)\s*$/m)
  if (!m || m[1] !== presetName) {
    return { ok: false, error: `executor preset 名不符：${presetName}（${file} 内 name=${m ? m[1] : '(缺席)'}）——显式拒绝` }
  }
  return { ok: true }
}

/**
 * 项目主目录读面（cwd 来源）：注册表 <root>/<key>/project.yaml 的 project[].dirs 首项。
 * project.yaml 缺席/畸形 = 显式拒绝（绝不拿仓根或 HOME 冒充项目主目录）。
 */
export function projectMainDir(key: string, env: NodeJS.ProcessEnv): { ok: true; cwd: string } | { ok: false; error: string } {
  if (!isValidProjectKey(key)) return { ok: false, error: `项目 key 形状不合法：${String(key)}` }
  const file = join(watchdogConfigDir(env), key, 'project.yaml')
  if (!existsSync(file)) return { ok: false, error: `项目注册表缺席：${key}（无 ${file}）——cwd 无真源，拒绝代建` }
  let raw: string
  try {
    raw = readFileSync(file, 'utf8')
  } catch (e) {
    return { ok: false, error: `project.yaml 不可读：${key}：${e instanceof Error ? e.message : String(e)}` }
  }
  const dirsIdx = raw.search(/^(\s*)dirs:\s*$/m)
  if (dirsIdx < 0) return { ok: false, error: `project.yaml 无 dirs 列表：${key}——cwd 无真源，拒绝代建` }
  const rest = raw.slice(dirsIdx)
  const m = rest.match(/^[ \t]*-[ \t]+(\S[^\n]*)$/m)
  if (!m) return { ok: false, error: `project.yaml dirs 列表为空：${key}——cwd 无真源，拒绝代建` }
  const cwd = m[1].trim().replace(/^['"]|['"]$/g, '')
  if (cwd === '') return { ok: false, error: `project.yaml dirs 首项为空：${key}——拒绝代建` }
  return { ok: true, cwd }
}

export type EnsureAction = 'create' | 'recreate' | 'adopt' | 'none' | 'refused-preset' | 'refused-host' | 'refused-cwd'

/** 纯决策核（UT 逐条钉的主矩阵；输入全显式，无隐藏读取）。 */
export function decideExecutorSession(input: {
  declaredSessionId: string
  knownSessionIds: string[] | null
  hasWork: boolean
  presetOk: boolean
}): { action: EnsureAction; reason: string } {
  const { declaredSessionId, knownSessionIds, hasWork, presetOk } = input
  if (declaredSessionId !== '') {
    // 铁律：人的声明只收养，绝不创建、绝不覆盖（回归杆钉死）。
    if (knownSessionIds !== null && !knownSessionIds.includes(declaredSessionId)) {
      return { action: hasWork ? 'recreate' : 'none', reason: hasWork
        ? `声明会话 ${declaredSessionId} 已不在宿主会话清单（宿主丢失）且有活干——重建并回写声明`
        : `声明会话 ${declaredSessionId} 不在宿主清单但项目无活——不重建（无活不建会话）` }
    }
    return { action: 'adopt', reason: `声明会话 ${declaredSessionId} 收养（人的声明绝不替换）` }
  }
  if (!hasWork) return { action: 'none', reason: '项目无活（无账本事件、无在飞票）——不建会话' }
  if (!presetOk) return { action: 'refused-preset', reason: `executor preset 不可用：${EXECUTOR_PRESET_NAME}——显式拒绝，绝不代建猜测会话` }
  return { action: 'create', reason: '项目有活且未声明会话——守望者按需代建' }
}

export interface EnsureOutcome {
  action: EnsureAction
  sessionId: string | null
  event: SessionProvenanceEvent | null
  /** 声明是否被回写（create/recreate 成功后应为 true；adopt 恒 false——绝不改人的声明）。 */
  declaredWritten: boolean
  reason: string
}

export interface EnsureDeps {
  project: string
  /** 声明里的会话 id（'' = 未声明）。 */
  declaredSessionId: string
  hasWork: boolean
  env: NodeJS.ProcessEnv
  io: SessionCreateIo
  eventIo: { append(path: string, line: string): Promise<void>; read(path: string): Promise<string> }
  dataDir: string
  nowMs: number
  presetName?: string
  /** 主目录/preset 就绪面注入（测试桩）；缺省走本文件的真实读面。 */
  mainDir?: { ok: true; cwd: string } | { ok: false; error: string }
  preset?: { ok: true } | { ok: false; error: string }
}

/**
 * 一次「确保会话」尝试：决策 → 执行 → 落事件 → （create/recreate 才）回写声明。
 * 每条路径至多落一条事件（scope 3/6：每次 create/recreate/adopt 一条）。
 * 任何失败都显式（refused-* + 原因点名），绝不静默降级成「没事」。
 */
export async function ensureExecutorSession(deps: EnsureDeps): Promise<EnsureOutcome> {
  const presetName = deps.presetName ?? EXECUTOR_PRESET_NAME
  const preset = deps.preset ?? presetReady(presetName, deps.env)
  const known = await deps.io.listSessionIds()
  const decision = decideExecutorSession({
    declaredSessionId: deps.declaredSessionId, knownSessionIds: known, hasWork: deps.hasWork, presetOk: preset.ok,
  })
  const evPath = sessionEventPath(deps.dataDir, deps.project)
  const base = { at: deps.nowMs, project: deps.project, preset: presetName, by: 'watchdog' as const }

  if (decision.action === 'none') {
    return { action: 'none', sessionId: deps.declaredSessionId || null, event: null, declaredWritten: false, reason: decision.reason }
  }
  if (decision.action === 'adopt') {
    const ev: SessionProvenanceEvent = { ...base, action: 'adopt', session_id: deps.declaredSessionId, cwd: null, reason: decision.reason }
    await appendSessionEventIo(deps.eventIo, evPath, ev)
    return { action: 'adopt', sessionId: deps.declaredSessionId, event: ev, declaredWritten: false, reason: decision.reason }
  }
  if (decision.action === 'refused-preset') {
    const reason = preset.ok ? decision.reason : preset.error
    const ev: SessionProvenanceEvent = { ...base, action: 'refused', session_id: null, cwd: null, reason }
    await appendSessionEventIo(deps.eventIo, evPath, ev)
    return { action: 'refused-preset', sessionId: null, event: ev, declaredWritten: false, reason }
  }

  const dir = deps.mainDir ?? projectMainDir(deps.project, deps.env)
  if (!dir.ok) {
    const ev: SessionProvenanceEvent = { ...base, action: 'refused', session_id: null, cwd: null, reason: dir.error }
    await appendSessionEventIo(deps.eventIo, evPath, ev)
    return { action: 'refused-cwd', sessionId: null, event: ev, declaredWritten: false, reason: dir.error }
  }
  const created = await deps.io.create({ cwd: dir.cwd, agentPreset: presetName })
  if (!created.ok) {
    const action: EnsureAction = 'refused'
    const reason = `宿主 create 失败（${decision.action}）：${created.error}`
    const ev: SessionProvenanceEvent = { ...base, action, session_id: null, cwd: dir.cwd, reason }
    await appendSessionEventIo(deps.eventIo, evPath, ev)
    return { action, sessionId: null, event: ev, declaredWritten: false, reason }
  }
  const action: EnsureAction = decision.action === 'recreate' ? 'recreate' : 'create'
  const written = writeExecutorSession(deps.project, created.sessionId, deps.env)
  const ev: SessionProvenanceEvent = { ...base, action, session_id: created.sessionId, cwd: dir.cwd, reason: written.written
    ? `${decision.reason}；会话 id 已回写声明`
    : `${decision.reason}；声明回写失败（下次重启会再建一只——需人看）：${written.reason ?? '?'}` }
  await appendSessionEventIo(deps.eventIo, evPath, ev)
  return { action, sessionId: created.sessionId, event: ev, declaredWritten: written.written, reason: ev.reason }
}
