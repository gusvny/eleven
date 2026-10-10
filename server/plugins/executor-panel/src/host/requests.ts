/**
 * requests.ts —— 执行器请求账（epic project-executor 面板半，t260929-03）。
 *
 * 是什么：面板自有的请求账文件（设计稿 260927：Requests＝请你做点什么，等你答复；
 * Alerts＝告诉你发生了什么——两者边界不得混）。**追加式 JSONL，长保留**：
 *   - 未答复的请求永不删除、永不被自动选中、永不被自动应答（本模块不存在任何
 *     「自动应答/自动过期关闭」路径——到期只影响界面上的 waiting 时长显示与过期标记）；
 *   - 应答=追加一条 answer 行（按 id 关联，不改写原行），全程留痕可回放；
 *   - 畸形行（坏 JSON/缺键）计数并显式上报，绝不静默丢弃（守望者账本同纪律）。
 *
 * io 全注入（测试零真实 ~/.sandbar）；路径纪律与 watchdog 同款：
 * 根 = env SANDBAR_PANEL_DIR || ~/.sandbar/projects，文件 = <root>/<key>/requests.jsonl。
 * 生产者面：真实 executor 侧投递是后续票；本票落显式 append API（bench/executor 消费）。
 */

import * as fs from 'node:fs'
import { PROJECT_KEY_RE, malformedProjectMessage } from './project-key.ts'
// t261003-04：请求账根兜底走 watchdog 的实例根（instanceProjectsRoot）——非缺省实例
// （场景/泳道，自带 DSH_HOME）的请求账落 <DSH_HOME>/sandbar/projects，**绝不再顺
// $HOME 兜底读生产请求账**（真机 261001-261003 实测：临时实例据此把生产执行器判成
// waiting_on_itself，232 条 redline）。词表一处定，禁再各算一份。
import { instanceProjectsRoot } from '../../../watchdog/src/host/config.ts'

/**
 * 请求种类：开放词表（设计稿 260927 常见=决定/授权/签字/提问，但引擎事件种类不封口——
 * 这里的 kind 只是显示数据；判定点在引擎）。校验只要求非空短字符串。
 */
export const REQUEST_KINDS = ['decision', 'approval', 'sign', 'question'] as const

/** 单条请求行（追加面）。raised_by = 发起方会话 id（t260929-08 自锁归属面）；'' = 未归属
 *  （历史行/未声明归属）——守望者自锁判定只认非空归属，未归属行显式点名、绝不冒充匹配。 */
export interface RequestRow {
  type: 'request'
  id: string
  at: number
  project: string
  kind: string
  question: string
  detail: string
  default_action: string
  /** t261003-06 选项数据面（设计 note §6）：提出方一并给出选项；有选项=页面渲染按钮，
   *  没选项=才退回自由文本框。可缺省（历史行/开放问句）；给了就必须是非空短字符串
   *  数组（≤8 项、单项 ≤80 字符、去重保序）——畸形在 append 时 fail-closed 拒收。 */
  options?: string[]
  expires_at: number | null
  raised_by: string
  /** t261004-17（一问一行镜像）：同一 ask_user_question 镜像出的多行共享一个组 id，
   *  面板据此把多问渲染成一张多问卡；单问行/历史行可缺省。给了就必须是非空短字符串
   *  （≤120 字符，同 raised_by 口径）——畸形在 append 时 fail-closed 拒收。 */
  group_id?: string
  /** t261007-02 thread face: the owning fields and the judged source. All optional =
   *  legacy rows (pre-thread) stay valid history; the view renders them empty and the
   *  host's classification call on those rows is still pending (out of scope here). */
  subject?: string
  epic?: string
  epic_reason?: string
  source_class?: 'executor-session' | 'project-session' | 'lane-agent'
  source_ticket?: string
}

/** 应答行（按 id 关联；追加不改写）。 */
export interface AnswerRow {
  type: 'answer'
  answer_for: string
  at: number
  answer: string
  by: string
  /** t261004-18 (KI-193): writer-mismatch visibility — when the caller self-reports a
   *  different writer in the body, the row keeps both the claim (by_claimed) and the
   *  mismatch sentinel; the recorded `by` is always the server-derived name. */
  by_claimed?: string
  writer_mismatch?: boolean
}

/** t261007-02 reply row (append-only; the thread's prose face). Delegated answers
 *  carry the three-field split: by (who decided) / via (who filed it) / anchor (the
 *  host's words) — shown as separate columns. Writers are gated by identity, not by
 *  the head's state (design note; review round 1 comment 3). */
export interface ReplyRow {
  type: 'reply'
  id: string
  reply_for: string
  at: number
  text: string
  by: string
  intent: 'answer' | 'fact' | 'ask'
  source_class?: string
  via?: string
  anchor?: string
}

/** t261007-02 state row: every state change is its own row, never a rewrite. */
export interface StateRow {
  type: 'state'
  id: string
  state_for: string
  state: 'answered' | 'resolved' | 'dismissed' | 'superseded'
  at: number
  by: string
  /** resolved only: a ticket id or a commit id — no evidence means no resolved. */
  evidence?: string
  note?: string
}

/** t261007-02 link row (supersedes / duplicates / follows_up / blocks). A duplicate
 *  re-file opens NO head: the row omits `from` (the denied filing never became a row)
 *  and carries the triple snapshot (dup_subject / dup_epic / dup_source_ticket) — the
 *  panel renders it as a one-way link to `to` and never resolves a dangling id. */
export interface LinkRow {
  type: 'link'
  id: string
  kind: 'supersedes' | 'duplicates' | 'follows_up' | 'blocks'
  from?: string
  to: string
  at: number
  by: string
  dup_subject?: string
  dup_epic?: string
  dup_source_ticket?: string
}

export type LedgerLine = RequestRow | AnswerRow | ReplyRow | StateRow | LinkRow | DismissRow

/** The five thread states. `open` is the only waiting state — the waiting list keeps
 *  its meaning (ticket item 10); expiry never moves a row between states (item 8). */
export type ThreadState = 'open' | 'answered' | 'resolved' | 'dismissed' | 'superseded'

/** Read view: request rows merged with answer/reply/state/link rows (malformed
 *  rows counted, never silently dropped).
 *  status (the legacy consumer face): waiting = open in the five-state model,
 *  the other four states keep their value -- the waiting list takes open only
 *  (page-logic splitWaiting narrows in step); state is the five-state truth. */
export interface RequestView extends RequestRow {
  status: 'waiting' | 'answered' | 'resolved' | 'dismissed' | 'superseded'
  state: ThreadState
  replies: ReplyRow[]
  links: LinkRow[]
  answer?: string
  answered_at?: number
  answered_by?: string
  dismissed_at?: number
  dismissed_by?: string
}

export interface RequestsRead {
  file: string
  rows: RequestView[]
  malformed_rows: number
}

/** 账本 io 缝（测试注入内存版；缺省 fs 版见下）。 */
export interface LedgerIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
  appendFileSync(file: string, line: string): void
  mkdirSync(dir: string, opts: { recursive: true }): void
}

export const fsLedgerIo: LedgerIo = {
  existsSync: fs.existsSync,
  readFileSync: (f) => fs.readFileSync(f, 'utf8'),
  appendFileSync: (f, line) => fs.appendFileSync(f, line),
  mkdirSync: fs.mkdirSync,
}

/** 账本文件路径（形状白名单由调用方先过 isValidProjectKey）。
 *  根 = env SANDBAR_PANEL_DIR > 实例 projects 根（t261003-04：非缺省实例 = <DSH_HOME>/
 *  sandbar/projects——自锁判定只消费同实例 scope 的请求账，见 instanceProjectsRoot）。 */
export function requestsLedgerFile(key: string, env: NodeJS.ProcessEnv = process.env): string {
  const root = env.SANDBAR_PANEL_DIR || instanceProjectsRoot(env)
  return join2(root, key, 'requests.jsonl')
}

/** 不 import node:path 到顶层（strip-mode 下无碍，但保持纯函数面可移植）。 */
function join2(...parts: string[]): string {
  return parts.filter(p => p !== '').join('/').replace(/\/+/g, '/')
}

let idSeq = 0
/** 请求 id（单调时钟+序号，测试可预测；不含随机面——确定性纪律）。 */
export function makeRequestId(nowMs: number): string {
  idSeq += 1
  return `req-${nowMs}-${String(idSeq).padStart(4, '0')}`
}

/** 追加一条请求（字段校验 fail-closed；id/时间戳服务端定，不信任消费方）。 */
export function appendRequest(
  io: LedgerIo, env: NodeJS.ProcessEnv, key: string,
  body: { kind: unknown; question: unknown; detail?: unknown; default_action?: unknown; options?: unknown; expires_at?: unknown; raised_by?: unknown; group_id?: unknown },
  nowMs: number,
): { ok: true; row: RequestRow } | { ok: false; error: string } {
  if (typeof key !== 'string' || !PROJECT_KEY_RE.test(key)) {
    return { ok: false, error: malformedProjectMessage(key) }
  }
  if (typeof body.question !== 'string' || body.question.trim() === '') {
    return { ok: false, error: 'question 必须是非空字符串（一句人话的问句——设计稿措辞纪律）' }
  }
  if (typeof body.kind !== 'string' || body.kind.trim() === '' || body.kind.length > 40) {
    return { ok: false, error: 'kind 必须是非空短字符串（≤40 字符；词表开放——判定点在引擎）' }
  }
  let expires: number | null = null
  if (body.expires_at !== undefined && body.expires_at !== null) {
    if (typeof body.expires_at === 'string') {
      const parsed = Date.parse(body.expires_at)
      if (!Number.isFinite(parsed)) return { ok: false, error: `expires_at 字符串须可解析为时刻（ISO 8601）：${body.expires_at}` }
      expires = parsed
    } else if (typeof body.expires_at === 'number' && Number.isFinite(body.expires_at) && body.expires_at >= 0) {
      expires = body.expires_at
    } else {
      return { ok: false, error: 'expires_at 必须是毫秒时间戳、ISO 8601 字符串或 null' }
    }
  }
  // raised_by（t260929-08 自锁归属面）：可缺省；给了就必须是非空短字符串（≤120 字符），
  // 畸形显式拒绝（fail-closed）——绝不静默丢归属让自锁判定瞎转。
  let raisedBy = ''
  if (body.raised_by !== undefined && body.raised_by !== null) {
    if (typeof body.raised_by !== 'string' || body.raised_by.trim() === '' || body.raised_by.length > 120) {
      return { ok: false, error: 'raised_by 必须是非空短字符串（≤120 字符的会话 id）；不给 = 未归属（自锁判定不认）' }
    }
    raisedBy = body.raised_by
  }
  // t261004-17 组 id（一问一行镜像）：可缺省；给了就必须是非空短字符串（≤120 字符），
  // 畸形显式拒绝——绝不静默丢组让多问卡散架。
  let groupId: string | undefined
  if (body.group_id !== undefined && body.group_id !== null) {
    if (typeof body.group_id !== 'string' || body.group_id.trim() === '' || body.group_id.length > 120) {
      return { ok: false, error: 'group_id 必须是非空短字符串（≤120 字符）；不给 = 单问行（不进多问卡）' }
    }
    groupId = body.group_id
  }
  // t261003-06 选项数据面：给了就必须是「非空短字符串数组」（≤8 项、单项 ≤80 字符、
  // 去重保序）——畸形在提出时 fail-closed 拒收（页面渲染面拿到的选项恒可信）。
  let options: string[] | undefined
  if (body.options !== undefined && body.options !== null) {
    if (!Array.isArray(body.options)) {
      return { ok: false, error: `options 必须是字符串数组（收到 ${typeof body.options}）；不给 = 自由文本请求` }
    }
    options = []
    for (const o of body.options as unknown[]) {
      if (typeof o !== 'string' || o.trim() === '') {
        return { ok: false, error: 'options 每项必须是非空字符串（空白项不给静默承认）' }
      }
      const label = o.trim()
      if (label.length > 80) return { ok: false, error: `options 项超限（${label.length} > 80 字符）` }
      if (!options.includes(label)) options.push(label)
    }
    if (options.length === 0) return { ok: false, error: 'options 空数组=无意义（不给 = 自由文本请求，不要传空表）' }
    if (options.length > 8) return { ok: false, error: `options 至多 8 项（收到 ${options.length}）` }
  }
  // Scope-6 re-file guard (t261007-01): after a dismiss, the executor must not
  // re-file the same request verbatim. Mechanical rule here = a byte-identical
  // question on a dismissed, still-unanswered request is refused. The full rule
  // (a re-raise must name the prior dismiss and the new evidence in the question
  // line) is prose, not machine-checkable at this layer — "names the new
  // evidence" cannot be validated mechanically; a different question text passes.
  const prior = readRequests(io, env, key)
  const dup = prior.rows.find(r => r.status === 'dismissed' && r.question === body.question)
  if (dup) {
    return { ok: false, error: `request ${dup.id} was dismissed by the host — do not re-file the same ask verbatim; a re-raise with new evidence must name the prior dismiss and the new evidence in the question line` }
  }
  const row: RequestRow = {
    type: 'request', id: makeRequestId(nowMs), at: nowMs, project: key,
    kind: body.kind,
    question: body.question,
    detail: typeof body.detail === 'string' ? body.detail : '',
    default_action: typeof body.default_action === 'string' ? body.default_action : '',
    ...(options ? { options } : {}),
    expires_at: expires,
    raised_by: raisedBy,
    ...(groupId ? { group_id: groupId } : {}),
  }
  const file = requestsLedgerFile(key, env)
  io.mkdirSync(file.slice(0, file.lastIndexOf('/')), { recursive: true })
  io.appendFileSync(file, JSON.stringify(row) + '\n')
  return { ok: true, row }
}

/**
 * Answer a request (the explicit refusal face, review comment #2's API-level
 * defense): unknown id / no longer open -> named error, never a silent second
 * close, never an auto-answer.
 * t261007-02: a successful answer also lands an answered state row (the
 * invariant: the write path never skips the state row; the answer row lands
 * first, the state row second -- a crash between them still yields answered
 * status from the answer row's merge).
 */
export function answerRequest(
  io: LedgerIo, env: NodeJS.ProcessEnv, key: string, id: unknown, answer: unknown, by: string, nowMs: number,
  writerMeta?: { by_claimed?: string; writer_mismatch?: boolean },
): { ok: true; answerRow: AnswerRow; stateRow?: StateRow } | { ok: false; error: string } {
  if (typeof key !== 'string' || !PROJECT_KEY_RE.test(key)) {
    return { ok: false, error: malformedProjectMessage(key) }
  }
  if (typeof id !== 'string' || id === '') return { ok: false, error: 'id must be a non-empty string' }
  if (typeof answer !== 'string' || answer.trim() === '') return { ok: false, error: 'answer must be a non-empty string' }
  const read = readRequests(io, env, key)
  const target = read.rows.find(r => r.id === id)
  if (!target) return { ok: false, error: `no such request id: ${id} (nothing to answer in this project's ledger)` }
  // t261007-01 §9 (merged from main): answer-after-dismiss wins — the host may
  // change their mind; a dismiss is not a decision. Only a real decision
  // (answered) or a doer terminal state (resolved/superseded) refuses.
  if (target.state === 'answered' || target.state === 'resolved' || target.state === 'superseded') {
    return { ok: false, error: `request ${id} is already ${target.state} — second close refused (the trail is never rewritten)` }
  }
  const answerRow: AnswerRow = { type: 'answer', answer_for: id, at: nowMs, answer, by, ...writerMeta }
  const file = requestsLedgerFile(key, env)
  io.appendFileSync(file, JSON.stringify(answerRow) + '\n')
  const stateRow: StateRow = { type: 'state', id: `st-${nowMs}-a`, state_for: id,
    state: 'answered', at: nowMs, by }
  io.appendFileSync(file, JSON.stringify(stateRow) + '\n')
  return { ok: true, answerRow, stateRow }
}

/** t261007-02 host state change (panel face): dismissed only. The fixed setters:
 *  answered is the answer route's word; resolved belongs to the doer with evidence
 *  (engine entry request_thread.py op=state); superseded is set by the machine when
 *  a newer item links this one. Terminal states accept no further state rows.
 *  A refusal carries an HTTP status hint so the route layer never re-matches
 *  message text. */
export function setThreadState(
  io: LedgerIo, env: NodeJS.ProcessEnv, key: string, id: unknown, state: unknown, by: string, nowMs: number,
): { ok: true; stateRow: StateRow } | { ok: false; error: string; status?: number } {
  if (typeof key !== 'string' || !PROJECT_KEY_RE.test(key)) {
    return { ok: false, error: malformedProjectMessage(key), status: 400 }
  }
  if (typeof id !== 'string' || id === '') return { ok: false, error: 'id must be a non-empty string', status: 400 }
  if (state !== 'dismissed') {
    return { ok: false, status: 400, error: 'state must be dismissed (the panel sets only the host side: answered goes through the answer face, resolved is the doer\'s with evidence, superseded is the machine\'s with a link; got ' + String(state) + ')' }
  }
  const read = readRequests(io, env, key)
  const target = read.rows.find(r => r.id === id)
  if (!target) return { ok: false, status: 404, error: `no such request id: ${id} (nothing to dismiss in this project's ledger)` }
  if (target.state === 'resolved' || target.state === 'dismissed' || target.state === 'superseded') {
    return { ok: false, status: 409, error: `request ${id} is already ${target.state} (terminal) — a state row is never rewritten, second close refused` }
  }
  const stateRow: StateRow = { type: 'state', id: `st-${nowMs}-d`, state_for: id,
    state: 'dismissed', at: nowMs, by }
  io.appendFileSync(requestsLedgerFile(key, env), JSON.stringify(stateRow) + '\n')
  return { ok: true, stateRow }
}

/** Read view: request rows merged with answer/reply/state/link rows (malformed
 *  rows counted, never silently dropped).
 *  status (the legacy consumer face): waiting = open in the five-state model,
 *  the other four states keep their value -- the waiting list takes open only
 *  (page-logic splitWaiting narrows in step); state is the five-state truth. */
export interface RequestView extends RequestRow {
  status: 'waiting' | 'answered' | 'resolved' | 'dismissed' | 'superseded'
  state: ThreadState
  replies: ReplyRow[]
  links: LinkRow[]
  answer?: string
  answered_at?: number
  answered_by?: string
}

export interface RequestsRead {
  file: string
  rows: RequestView[]
  malformed_rows: number
}


/** Read the ledger and merge answers/replies/states/links into the view (malformed rows counted, never silently dropped -- the ledger discipline shared with the watchdog). */

/**
 * Dismiss a request (t261007-01, host ruling 261004, design note §9): "I saw it,
 * I do not rule on it". Never approval — the default action still applies and
 * the executor still runs it. Explicit refusal faces, mirroring answerRequest:
 * no silent double-close, and a dismissed request stays dismissed. Dismissing an
 * already-answered request is refused too (developer decision, fault-mode item 4
 * of plan_t261007-01: a decision exists; a dismiss adds nothing — the design
 * note §9 rules only answer-after-dismiss, not dismiss-after-answer).
 */
export function dismissRequest(
  io: LedgerIo, env: NodeJS.ProcessEnv, key: string, id: unknown, by: string, nowMs: number,
  writerMeta?: { by_claimed?: string; writer_mismatch?: boolean },
): { ok: true; dismissRow: DismissRow } | { ok: false; error: string } {
  if (typeof key !== 'string' || !PROJECT_KEY_RE.test(key)) {
    return { ok: false, error: malformedProjectMessage(key) }
  }
  if (typeof id !== 'string' || id === '') return { ok: false, error: 'id must be a non-empty string' }
  const read = readRequests(io, env, key)
  const target = read.rows.find(r => r.id === id)
  if (!target) return { ok: false, error: `no such request id: ${id} (this project ledger has no such row)` }
  if (target.status === 'dismissed') {
    return { ok: false, error: `request ${id} was already dismissed at ${new Date(target.dismissed_at ?? 0).toISOString()} — second dismiss refused (the trace is never rewritten)` }
  }
  if (target.status === 'answered') {
    return { ok: false, error: `request ${id} was answered (by ${target.answered_by ?? '?'}) — dismiss refused: a decision is on record, a dismiss adds nothing` }
  }
  const dismissRow: DismissRow = { type: 'dismiss', dismiss_for: id, at: nowMs, by, ...writerMeta }
  io.appendFileSync(requestsLedgerFile(key, env), JSON.stringify(dismissRow) + '\n')
  return { ok: true, dismissRow }
}

/** Read the ledger and merge answers and dismisses into the view (malformed
 *  rows counted, never silently dropped — the same ledger discipline as the
 *  watchdog). */
export function readRequests(io: LedgerIo, env: NodeJS.ProcessEnv, key: string): RequestsRead {
  const file = requestsLedgerFile(key, env)
  const out: RequestsRead = { file, rows: [], malformed_rows: 0 }
  if (!io.existsSync(file)) return out
  let raw = ''
  try { raw = io.readFileSync(file) } catch { out.malformed_rows += 1; return out }
  const lines = raw.split('\n').filter(l => l.trim() !== '')
  const requests = new Map<string, RequestView>()
  const answers: AnswerRow[] = []
  const replies: ReplyRow[] = []
  const states: StateRow[] = []
  const links: LinkRow[] = []
  const dismisses: DismissRow[] = []
  for (const line of lines) {
    let doc: unknown
    try { doc = JSON.parse(line) } catch { out.malformed_rows += 1; continue }
    if (isRequestRow(doc)) {
      // 历史行（t260929-08 前落账）没有 raised_by：读出统一归一化为 ''（未归属哨兵），不畸形。
      requests.set(doc.id, { ...doc, raised_by: typeof doc.raised_by === 'string' ? doc.raised_by : '',
        status: 'waiting', state: 'open', replies: [], links: [] })
    } else if (isAnswerRow(doc)) {
      answers.push(doc)
    } else if (isReplyRow(doc)) {
      replies.push(doc)
    } else if (isStateRow(doc)) {
      states.push(doc)
    } else if (isLinkRow(doc)) {
      links.push(doc)
    } else if (isDismissRow(doc)) {
      dismisses.push(doc)
    } else {
      out.malformed_rows += 1
    }
  }
  // t261007-01 merge order: dismisses first, then answers — answer-after-dismiss
  // wins (design note §9: the host may change their mind); both rows stay in the
  // ledger trace. Dismiss-after-answer cannot occur (dismissRequest refuses it).
  for (const d of dismisses) {
    const t = requests.get(d.dismiss_for)
    if (!t) { out.malformed_rows += 1; continue } // ghost dismiss (points at no request row) = malformed trace, never silent
    t.status = 'dismissed'; t.state = 'dismissed'; t.dismissed_at = d.at; t.dismissed_by = d.by
  }
  for (const a of answers) {
    const t = requests.get(a.answer_for)
    if (!t) { out.malformed_rows += 1; continue } // 指向不存在请求的应答行=畸形留痕，不静默
    if (t.state === 'open' || t.state === 'dismissed') { t.state = 'answered' } // answer-after-dismiss wins (§9)
    t.status = t.state as RequestView['status']
    t.answer = a.answer; t.answered_at = a.at; t.answered_by = a.by
  }
  for (const r of replies) {
    const t = requests.get(r.reply_for)
    if (!t) { out.malformed_rows += 1; continue }
    t.replies.push(r)
  }
  // State rows take effect in landing order (the later one wins); torn-op
  // tolerance: a supersedes link without its derived state row -> the reader
  // recomputes superseded (torn-op repair only, never a write-path license).
  for (const s of states) {
    const t = requests.get(s.state_for)
    if (!t) { out.malformed_rows += 1; continue }
    t.state = s.state as ThreadState
    t.status = t.state as RequestView['status']
    if (s.state === 'answered' && !t.answer) { t.answer = ''; t.answered_by = s.by }
  }
  for (const l of links) {
    const t = requests.get(l.to)
    if (t) {
      t.links.push(l)
      if (l.kind === 'supersedes' && t.state !== 'superseded') {
        t.state = 'superseded'; t.status = 'superseded' // torn-op tolerance (see above)
      }
    }
    if (l.from && !requests.has(l.from)) out.malformed_rows += 1 // a dangling from is recorded as malformed
  }
  out.rows = [...requests.values()].sort((a, b) => b.at - a.at) // 新的在前；旧的永不丢
  return out
}

function isRequestRow(v: unknown): v is RequestRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'request' && typeof r.id === 'string' && typeof r.at === 'number'
    && typeof r.project === 'string' && typeof r.kind === 'string'
    && typeof r.question === 'string'
}

/** Canonical answer-row shape -- ONE shape, declared once, enforced by BOTH
 *  readers (KI-01M4HPGHVWAKB62TXYV4G7ENEB, t261009-75). This predicate is the
 *  truth source; the engine's read face (server/engine/request_thread.py
 *  `is_answer_row`) mirrors it exactly, and a shape-off answer row clears a
 *  head on NEITHER face: it is counted as malformed below and the head stays
 *  waiting -- the safe direction. Historical panel-written rows always carry
 *  a numeric `at` (the panel also lands an answered state row), so only
 *  out-of-writer rows are affected. */
function isAnswerRow(v: unknown): v is AnswerRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'answer' && typeof r.answer_for === 'string' && typeof r.at === 'number'
    && typeof r.answer === 'string'
}

function isReplyRow(v: unknown): v is ReplyRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'reply' && typeof r.reply_for === 'string' && typeof r.at === 'number'
    && typeof r.text === 'string' && typeof r.by === 'string'
}

function isStateRow(v: unknown): v is StateRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'state' && typeof r.state_for === 'string' && typeof r.at === 'number'
    && (r.state === 'answered' || r.state === 'resolved' || r.state === 'dismissed' || r.state === 'superseded')
}

function isLinkRow(v: unknown): v is LinkRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'link' && typeof r.to === 'string' && typeof r.at === 'number'
    && (r.kind === 'supersedes' || r.kind === 'duplicates' || r.kind === 'follows_up' || r.kind === 'blocks')
}

/** Strict dismiss-row guard (t261007-01): anything shape-off falls to the
 *  malformed counter — a dismiss row is never guessed into existence. */
function isDismissRow(v: unknown): v is DismissRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'dismiss' && typeof r.dismiss_for === 'string' && typeof r.at === 'number'
    && typeof r.by === 'string'
}

/** 等待时长与过期（纯函数，界面渲染用；到期只是标记，永不自动关闭）。 */
export function requestUrgency(row: RequestView, nowMs: number): {
  waiting_ms: number; expired: boolean; answered: boolean
} {
  return {
    waiting_ms: Math.max(0, nowMs - row.at),
    expired: row.status === 'waiting' && row.expires_at !== null && nowMs > row.expires_at,
    answered: row.status === 'answered',
  }
}

/** POST 体解析（API 级畸形输入防线：非 JSON / 非对象都点名，review 意见 #2）。 */
export function parseJsonBody(raw: string): { ok: true; body: Record<string, unknown> } | { ok: false; error: string } {
  let doc: unknown
  try { doc = JSON.parse(raw) } catch (e) {
    return { ok: false, error: `请求体不是合法 JSON：${e instanceof Error ? e.message : String(e)}` }
  }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) {
    return { ok: false, error: '请求体顶层必须是 JSON 对象' }
  }
  return { ok: true, body: doc as Record<string, unknown> }
}
