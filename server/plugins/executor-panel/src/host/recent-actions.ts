/**
 * recent-actions.ts —— Overview 右栏「最近动作」只读源（t261003-06，设计 note §6）。
 *
 * 数据来源（plan review N4 裁定）：逐项目事件账本（server/engine/event_ledger.py 产出、
 * watchdog 只读消费的同一份账本；面板同样只读，绝不写）。事件行 schema event-ledger-v1：
 *   { idem, project, ticket, seq, kind?, stage?, stage_state?, reason?, ts?/at? }
 * 受闸写动作映射表（固定词表，与 GRANT_OPS 同族）：账本 kind → 面板动作名 + 凭哪条权限。
 * 认不出的 kind：跳过并计数（unmapped_rows 显式在案），**绝不编造动作**。
 * 来源不可得（账本缺席/不可读）：显式降级对象（点名原因），**绝不渲染成空列表冒充
 * 「最近没动作」**。
 *
 * io 全注入（测试内存桩；缺省 fs）。零引擎改动、零 3099 触碰。
 */

import * as fs from 'node:fs'
import { join } from 'node:path'
import { PROJECT_KEY_RE } from './project-key.ts'

/** 面板动作显示名 + 凭哪条权限（固定映射表——不随项目变，词表与 grants 面一致）。 */
export const ACTION_BY_KIND: Record<string, { action: string; permission: string }> = {
  'sign': { action: 'Sign', permission: 'sign' },
  'merge': { action: 'Sign', permission: 'sign' },
  'send_back': { action: 'Send back', permission: 'send-back' },
  'send-back': { action: 'Send back', permission: 'send-back' },
  'reject': { action: 'Send back', permission: 'send-back' },
  'rerun': { action: 'Rerun', permission: 'rerun' },
  'retry': { action: 'Rerun', permission: 'rerun' },
  'open_ticket': { action: 'Open ticket', permission: 'open-ticket' },
  'open-ticket': { action: 'Open ticket', permission: 'open-ticket' },
  'open': { action: 'Open ticket', permission: 'open-ticket' },
  'pause': { action: 'Pause', permission: 'pause-resume' },
  'resume': { action: 'Resume', permission: 'pause-resume' },
  'pause-resume': { action: 'Pause or resume', permission: 'pause-resume' },
  'cleanup': { action: 'Cancel', permission: 'cleanup' },
  'cancel': { action: 'Cancel', permission: 'cleanup' },
}

/** 面板动作行（Overview 右栏一条）。 */
export interface RecentAction {
  at: number
  action: string
  ticket: string
  result: string
  permission: string
}

export type RecentActionsRead =
  | { ok: true; source: string; actions: RecentAction[]; unmapped_rows: number; malformed_rows: number }
  | { ok: false; source: string; reason: string }

/** io 缝（测试注入内存版；缺省 fs 版）。 */
export interface ActionsIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
}

export const fsActionsIo: ActionsIo = {
  existsSync: fs.existsSync,
  readFileSync: (f) => fs.readFileSync(f, 'utf8'),
}

/** 事件账本文件路径（与 watchdog config.eventLedgerFile 同根同形状：逐项目目录 events.jsonl）。 */
export function eventLedgerFile(key: string, env: NodeJS.ProcessEnv = process.env): string {
  const root = env.SANDBAR_PROJECTS_DIR || env.SANDBAR_WATCHDOG_DIR || env.SANDBAR_PANEL_DIR
    || join(env.HOME || '', '.sandbar', 'projects')
  return join(root, key, 'ledger', 'events.jsonl')
}

/** 单行 → 动作行（认不出的 kind / 缺票号的行 = null，调用方计数，不编造）。 */
export function parseActionLine(line: string): RecentAction | null {
  if (line.trim() === '') return null
  let doc: unknown
  try { doc = JSON.parse(line) } catch { return null }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) return null
  const r = doc as Record<string, unknown>
  const ticket = typeof r.ticket === 'string' ? r.ticket : ''
  const kind = typeof r.kind === 'string' ? r.kind : ''
  const mapped = ACTION_BY_KIND[kind]
  if (ticket === '' || !mapped) return null
  let at = 0
  if (typeof r.at === 'number' && Number.isFinite(r.at)) at = r.at
  else if (typeof r.ts === 'string') at = Date.parse(r.ts) || 0
  const result = typeof r.stage_state === 'string' && r.stage_state !== ''
    ? r.stage_state
    : typeof r.reason === 'string' ? r.reason.slice(0, 120) : ''
  return { at, action: mapped.action, ticket, result, permission: mapped.permission }
}

/**
 * 读最近动作（新的在前，上限 max 条；尾数绝不丢——malformed/unmapped 计数显式在案）。
 */
export function readRecentActions(
  io: ActionsIo, env: NodeJS.ProcessEnv, key: string, max = 12,
): RecentActionsRead {
  if (!PROJECT_KEY_RE.test(key)) {
    return { ok: false, source: eventLedgerFile(key, env), reason: 'project key 形状不合法——读不出动作账' }
  }
  const file = eventLedgerFile(key, env)
  if (!io.existsSync(file)) {
    return { ok: false, source: file,
             reason: 'the event ledger does not exist yet (' + file + ') — no recorded actions to show' }
  }
  let raw = ''
  try {
    raw = io.readFileSync(file)
  } catch (e) {
    return { ok: false, source: file,
             reason: 'the event ledger is unreadable: ' + (e instanceof Error ? e.message : String(e)) }
  }
  const actions: RecentAction[] = []
  let malformed = 0
  let unmapped = 0
  for (const line of raw.split('\n')) {
    if (line.trim() === '') continue
    const a = parseActionLine(line)
    if (a) actions.push(a)
    else {
      // 区分「坏行」与「认不出的 kind」：坏 JSON/缺形状=malformed；形状合法但没进映射表=unmapped。
      let doc: unknown
      try { doc = JSON.parse(line) } catch { malformed++; continue }
      if (typeof doc === 'object' && doc !== null && !Array.isArray(doc)
        && typeof (doc as Record<string, unknown>).ticket === 'string'
        && typeof (doc as Record<string, unknown>).idem === 'string') unmapped++
      else malformed++
    }
  }
  actions.sort((a, b) => b.at - a.at)
  return { ok: true, source: file, actions: actions.slice(0, max), unmapped_rows: unmapped, malformed_rows: malformed }
}
