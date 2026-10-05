/**
 * recent-actions.ts —— Overview 右栏「最近动作」只读源（t261003-06 引入；
 * t261004-11 换源=项目自己的执行器动作账，机器级 admin.log 读取在此退役）。
 *
 * 数据来源：引擎在执行器授权闸真实裁决时逐行落账的
 * `<projects_root>/<key>/ledger/executor-actions.jsonl`（写口=server/engine/
 * executor_actions.py，schema v1；本文件只读，绝不写，R5 只读红线不变）。
 * 选它的理由（票面裁定）：账随项目走、行自带 op/ticket/decision/grant/
 * grant_source/session/channel——「凭哪条权限」与「谁在动」同处一行，不再依赖
 * 机器级审计行的 summary 解析层（该层曾因行形漂移静默打碎读方）。
 *
 * 行语义：
 *   R1 每行 {at, action, ticket, result, permission, session, reason?}；
 *   R2 permission/grant 缺席显式展示为 none（绝不编造）；
 *   R3 畸形行 / 认不出的 op / 重复 idem 分别计数，绝不静默丢、绝不编造；
 *   R4 不可得（文件缺席/不可读）→ ok:false + 人类可读原因点名源路径；
 *   R5 只读：读前后文件字节一致（场景红线）。
 *   新增（t261004-11）：refused 行带 reason（hover 用）；gaps 旁账
 *   （executor-actions.gaps.jsonl）尾计数作 gaps_recent 上报——引擎落账失败
 *   的「status face」；上限 50 行，更早的行指向项目账本文件。
 *
 * io 全注入（测试内存桩；缺省 fs + 尾读）。零引擎改动、零 3099 触碰。
 */

import * as fs from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { PROJECT_KEY_RE } from './project-key.ts'
import { LIST_CONTRACTS } from './list-contracts.ts'

/** 列表上限一处声明（t261004-14）：默认截断数=契约 overview_recent_actions.cap，不再内联 12。 */
export const RECENT_ACTIONS_CAP: number = LIST_CONTRACTS.overview_recent_actions.cap as number

/** 上限行数（票面口径「约 50 行」）；更早的行在源文件里，响应带指针。 */
/** 上限一处声明（t261004-14 × t261004-11 合并）：MAX_ROWS 与 RECENT_ACTIONS_CAP 同源，
 *  均取契约 overview_recent_actions.cap——上限数字不内联两份。 */
export const MAX_ROWS: number = RECENT_ACTIONS_CAP

/** 引擎 op（授予面原词 + 引擎写 op 名）→ 面板动作显示名。认不出的 op 计数不编造。 */
export const ACTION_BY_OP: Record<string, string> = {
  'sign': 'Sign',
  'send-back': 'Send back',
  'send_back': 'Send back',
  'rerun': 'Rerun',
  'open-ticket': 'Open ticket',
  'open_ticket': 'Open ticket',
  'ticket-start': 'Open ticket',
  'ticket.create': 'Open ticket',
  'pause-resume': 'Pause or resume',
  'cleanup': 'Cancel',
  'ticket-cancel': 'Cancel',
  'cancel': 'Cancel',
  'close_out': 'Cancel',
  'manage-grants': 'Change grants',   // 元权限反锁的拒收行（宿主特权操作）
}

/** One panel action row (Overview right column). reason is present only on refused
 *  rows. epic is present only on open-ticket rows (t261004-19; see
 *  epicFromGrantSource). */
export interface RecentAction {
  at: number
  action: string
  ticket: string
  result: string
  permission: string
  session: string
  reason?: string
  epic?: string
}

/**
 * Parse the epic code out of a row's grant_source / reason text (t261004-19;
 * C3 fail-soft). The source shape = the engine provenance key
 * `open_ticket_epics.<code> @ <file>` (an allowed row's grant_source); a refused
 * row's reason also names `epic <code>` (the engine refusal copy). Unparseable
 * (absent / legacy row / shape drift) returns '' — never throws, never drops the
 * row: a missing epic is a missing label on that row, not a row failure. */
export function epicFromGrantSource(grantSource: string, reason: string): string {
  const m = /\bopen_ticket_epics\.([a-z0-9][a-z0-9-]{0,40})\b/.exec(String(grantSource ?? ''))
  if (m) return m[1]
  // The reason fallback only accepts the engine's three exact named-refusal
  // phrasings ("epic X is not on", "epic X has no epic file", "epic X already has")
  // — a loose "epic X" would mistake English prose (e.g. "epic mentioned") for a code.
  const r = /\bepic ([a-z0-9][a-z0-9-]{0,40})(?: is not on| has no epic file| already has)/.exec(String(reason ?? ''))
  return r ? r[1] : ''
}

export type RecentActionsRead =
  | {
      ok: true; source: string; gapsFile: string; actions: RecentAction[]
      malformed_rows: number; unknown_op_rows: number; deduped_rows: number
      older_rows: number; gaps_recent: number
      last_record_failure: LastRecordFailure | null
    }
  | { ok: false; source: string; reason: string
      last_record_failure: LastRecordFailure | null }

/** t261005-12: the engine-written last-failure marker face (reader-visible
 *  recording failure; the engine writes it at the PROJECT ROOT in the default
 *  shape because the ledger directory itself is the usual thing that is
 *  unwritable). The panel only READS it — the R5 read-only red line is
 *  unchanged. */
export interface LastRecordFailure {
  at: number
  why: string
  error: string
}

/** Engine marker basename (server/engine/executor_actions.py FAILURE_BASENAME;
 *  cross-language drift pinned by tests on both sides). */
export const LAST_FAILURE_BASENAME = 'executor-actions.last-failure.json'

/**
 * Marker path (mirrors the engine's last_failure_path shape exactly):
 * - env SANDBAR_EXECUTOR_ACTIONS_DIR (flat test seam) ⇒ `<dir>/<marker>`;
 * - env SANDBAR_EXECUTOR_ACTIONS_FILE ⇒ next to that file;
 * - default ⇒ `<projects_root>/<key>/executor-actions.last-failure.json`
 *   (project root, NOT the ledger/ subdir — see the interface comment).
 */
export function executorActionsFailureFile(
  env: NodeJS.ProcessEnv = process.env, key = '', source = '',
): string {
  const dir = env.SANDBAR_EXECUTOR_ACTIONS_DIR
  if (dir) return join(dir, LAST_FAILURE_BASENAME)
  if (env.SANDBAR_EXECUTOR_ACTIONS_FILE) return join(source, '..', LAST_FAILURE_BASENAME)
  const root = env.SANDBAR_PROJECTS_DIR || join(homedir(), '.sandbar', 'projects')
  return join(root, key, LAST_FAILURE_BASENAME)
}

/**
 * Read the last-failure marker. Fail-soft three-state: absent / unreadable /
 * MALFORMED (bad JSON, array, scalar, or no why+error text) all read as
 * `null` — a broken marker never crashes the read and never fabricates a
 * failure claim (external-input discipline; the empty-state copy stays honest).
 */
export function readLastRecordFailure(
  io: ActionsIo, env: NodeJS.ProcessEnv, key: string, source: string,
): LastRecordFailure | null {
  const file = executorActionsFailureFile(env, key, source)
  if (!io.existsSync(file)) return null
  let raw = ''
  try {
    raw = io.readFileSync(file)
  } catch { return null }
  let doc: unknown
  try { doc = JSON.parse(raw) } catch { return null }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) return null
  const r = doc as Record<string, unknown>
  const why = typeof r.why === 'string' ? r.why : ''
  const error = typeof r.error === 'string' ? r.error : ''
  if (!why && !error) return null
  return {
    at: typeof r.at === 'number' && Number.isFinite(r.at) ? r.at : 0,
    why, error,
  }
}

/** io 缝（测试注入内存版；缺省 fs 版 + 尾读）。 */
export interface ActionsIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
  /** 尾读（生产路径）；缺省由调用方回落 readFileSync（内存桩用）。 */
  readTail?(file: string, maxBytes: number): string
}

/** 尾读窗口：项目账本行小（≤4KB/行），512KB 覆盖数百行，远超 50 行展示上限。 */
export const TAIL_BYTES = 512 * 1024

function fsReadTail(file: string, maxBytes: number): string {
  const fd = fs.openSync(file, 'r')
  try {
    const size = fs.fstatSync(fd).size
    const start = Math.max(0, size - maxBytes)
    const len = size - start
    const buf = Buffer.alloc(len)
    fs.readSync(fd, buf, 0, len, start)
    let text = buf.toString('utf8')
    // 首行大概率被窗口切断：丢弃残行（残 JSON 会进 malformed，丢掉更诚实）。
    if (start > 0) text = text.slice(text.indexOf('\n') + 1)
    return text
  } finally {
    fs.closeSync(fd) // 全终态：fd 每条路径都收口
  }
}

export const fsActionsIo: ActionsIo = {
  existsSync: fs.existsSync,
  readFileSync: (f) => fs.readFileSync(f, 'utf8'),
  readTail: fsReadTail,
}

/**
 * 项目动作账文件路径（与引擎 executor_actions.actions_path 逐字同式，跨语言
 * 漂移由两侧 tests 双向钉死）：
 * - env SANDBAR_EXECUTOR_ACTIONS_FILE ⇒ 直连文件路径（最高优先；场景/壳缝）；
 * - env SANDBAR_EXECUTOR_ACTIONS_DIR ⇒ 平铺 `<dir>/<key>.jsonl`（测试缝）；
 * - 缺省 ⇒ `<projects_root>/<key>/ledger/executor-actions.jsonl`
 *   （projects_root=SANDBAR_PROJECTS_DIR || ~/.sandbar/projects）。
 */
export function executorActionsFile(env: NodeJS.ProcessEnv = process.env, key = ''): string {
  const direct = env.SANDBAR_EXECUTOR_ACTIONS_FILE
  if (direct) return direct
  const dir = env.SANDBAR_EXECUTOR_ACTIONS_DIR
  if (dir) return join(dir, key + '.jsonl')
  const root = env.SANDBAR_PROJECTS_DIR || join(homedir(), '.sandbar', 'projects')
  return join(root, key, 'ledger', 'executor-actions.jsonl')
}

/** gaps 旁账路径（status face；引擎落点=账本文件同目录固定名）。 */
export function executorActionsGapsFile(source: string): string {
  return join(source, '..', 'executor-actions.gaps.jsonl')
}

export type ActionLineVerdict =
  | { kind: 'blank' }
  | { kind: 'action'; row: RecentAction }
  | { kind: 'unknown_op'; op: string }
  | { kind: 'deduped' }
  | { kind: 'malformed' }

/**
 * 单行 → 判定（动作 / op 认不出 / 重复 idem / 畸形）。项目过滤不需要：
 * 文件本身就是 per-project 的（这正是本票换源的意义）。
 * seenIdems（调用方逐窗携带）：重复 idem 行=良性伪影，显式计数不渲染。
 */
export function parseActionLine(line: string, seenIdems?: Set<string>): ActionLineVerdict {
  if (line.trim() === '') return { kind: 'blank' }   // 空行/文件尾：跳过不计
  let doc: unknown
  try { doc = JSON.parse(line) } catch { return { kind: 'malformed' } }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) return { kind: 'malformed' }
  const r = doc as Record<string, unknown>
  if (r.gap === true) return { kind: 'malformed' }  // gaps 行混进活动文件=形状外，计数不渲染
  const decision = r.decision === 'allowed' || r.decision === 'refused' ? r.decision : ''
  if (!decision) return { kind: 'malformed' }
  const idem = typeof r.idem === 'string' ? r.idem : ''
  if (!idem) return { kind: 'malformed' }
  if (seenIdems) {
    if (seenIdems.has(idem)) return { kind: 'deduped' }
    seenIdems.add(idem)
  }
  const op = typeof r.op === 'string' ? r.op : ''
  const action = ACTION_BY_OP[op]
  if (action === undefined) return { kind: 'unknown_op', op }
  const grant = typeof r.grant === 'string' ? r.grant : ''
  const session = typeof r.session === 'string' ? r.session : ''
  const ticket = typeof r.ticket === 'string' ? r.ticket : ''
  const at = typeof r.at === 'number' && Number.isFinite(r.at) ? r.at : 0
  const row: RecentAction = { at, action, ticket, result: decision, permission: grant, session }
  if (decision === 'refused') {
    row.reason = typeof r.reason === 'string' && r.reason !== '' ? r.reason : 'refused (no reason recorded)'
  }
  // t261004-19: an open-ticket row carries the epic (allowed = the grant_source
  // shape; refused = named in the reason). Fail-soft: unparseable = no key set, the
  // row renders as usual (C3).
  const epic = epicFromGrantSource(typeof r.grant_source === 'string' ? r.grant_source : '',
                                   row.reason ?? '')
  if (epic !== '') row.epic = epic
  return { kind: 'action', row }
}

/**
 * 读最近动作（新的在前，上限 MAX_ROWS）。R4 纪律：任何「无可展示」都有点名
 * 原因；文件缺席=「记录启动以来本项目无执行器动作」（不冒充读得动）。
 */
export function readRecentActions(
  io: ActionsIo, env: NodeJS.ProcessEnv, key: string, max = MAX_ROWS,
): RecentActionsRead {
  const source = executorActionsFile(env, key)
  if (!PROJECT_KEY_RE.test(key)) {
    return { ok: false, source, last_record_failure: null,
             reason: 'the project key is malformed — no action record can be read' }
  }
  // t261005-12: the engine-written last-failure marker is read on EVERY path —
  // an empty ledger with a marker must surface the failure, not the silent
  // empty-state copy (the ticket's headline defect face).
  const lastRecordFailure = readLastRecordFailure(io, env, key, source)
  if (!io.existsSync(source)) {
    return { ok: false, source, last_record_failure: lastRecordFailure,
             reason: 'This project has no recorded executor action. The record started with this change; the file is ' + source + '.' }
  }
  let raw = ''
  try {
    raw = io.readTail ? io.readTail(source, TAIL_BYTES) : io.readFileSync(source)
  } catch (e) {
    return { ok: false, source, last_record_failure: lastRecordFailure,
             reason: 'This project has no readable executor action record: ' +
               (e instanceof Error ? e.message : String(e)) + ' — the file is ' + source + '.' }
  }
  const actions: RecentAction[] = []
  let malformed = 0
  let unknownOp = 0
  let deduped = 0
  const seenIdems = new Set<string>()
  for (const line of raw.split('\n')) {
    const v = parseActionLine(line, seenIdems)
    if (v.kind === 'action') actions.push(v.row)
    else if (v.kind === 'malformed') malformed++
    else if (v.kind === 'unknown_op') unknownOp++
    else if (v.kind === 'deduped') deduped++
  }
  actions.sort((a, b) => b.at - a.at)
  const shown = actions.slice(0, max)
  // gaps 尾计数（status face）：引擎落账失败在此可见；读不到/缺席=0，不致命。
  const gapsFile = executorActionsGapsFile(source)
  let gapsRecent = 0
  if (io.existsSync(gapsFile)) {
    try {
      const g = io.readTail ? io.readTail(gapsFile, 64 * 1024) : io.readFileSync(gapsFile)
      gapsRecent = g.split('\n').filter((l) => l.trim() !== '').length
    } catch { gapsRecent = 0 }
  }
  return {
    ok: true, source, gapsFile, actions: shown,
    malformed_rows: malformed, unknown_op_rows: unknownOp,
    deduped_rows: deduped, older_rows: Math.max(0, actions.length - shown.length),
    gaps_recent: gapsRecent,
    last_record_failure: lastRecordFailure,
  }
}
