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
  expires_at: number | null
  raised_by: string
}

/** 应答行（按 id 关联；追加不改写）。 */
export interface AnswerRow {
  type: 'answer'
  answer_for: string
  at: number
  answer: string
  by: string
}

export type LedgerLine = RequestRow | AnswerRow

/** 读出视图：请求行 + 应答合流（waiting/answered），畸形行计数显式在案。 */
export interface RequestView extends RequestRow {
  status: 'waiting' | 'answered'
  answer?: string
  answered_at?: number
  answered_by?: string
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

/** 账本文件路径（形状白名单由调用方先过 isValidProjectKey）。 */
export function requestsLedgerFile(key: string, env: NodeJS.ProcessEnv = process.env): string {
  const root = env.SANDBAR_PANEL_DIR || join2(env.HOME || '', '.sandbar', 'projects')
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
  body: { kind: unknown; question: unknown; detail?: unknown; default_action?: unknown; expires_at?: unknown; raised_by?: unknown },
  nowMs: number,
): { ok: true; row: RequestRow } | { ok: false; error: string } {
  if (typeof key !== 'string' || !/^[a-z0-9][a-z0-9-]{0,40}$/.test(key)) {
    return { ok: false, error: `project 形状不合法：${String(key)}` }
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
  const row: RequestRow = {
    type: 'request', id: makeRequestId(nowMs), at: nowMs, project: key,
    kind: body.kind,
    question: body.question,
    detail: typeof body.detail === 'string' ? body.detail : '',
    default_action: typeof body.default_action === 'string' ? body.default_action : '',
    expires_at: expires,
    raised_by: raisedBy,
  }
  const file = requestsLedgerFile(key, env)
  io.mkdirSync(file.slice(0, file.lastIndexOf('/')), { recursive: true })
  io.appendFileSync(file, JSON.stringify(row) + '\n')
  return { ok: true, row }
}

/**
 * 应答一条请求（显式拒绝面，review 意见 #2 的 API 级防线）：
 * 无此 id / 已应答 → 显式报错，绝不静默二次关闭、绝不自动应答。
 */
export function answerRequest(
  io: LedgerIo, env: NodeJS.ProcessEnv, key: string, id: unknown, answer: unknown, by: string, nowMs: number,
): { ok: true; answerRow: AnswerRow } | { ok: false; error: string } {
  if (typeof key !== 'string' || !/^[a-z0-9][a-z0-9-]{0,40}$/.test(key)) {
    return { ok: false, error: `project 形状不合法：${String(key)}` }
  }
  if (typeof id !== 'string' || id === '') return { ok: false, error: 'id 必须是非空字符串' }
  if (typeof answer !== 'string' || answer.trim() === '') return { ok: false, error: 'answer 必须是非空字符串' }
  const read = readRequests(io, env, key)
  const target = read.rows.find(r => r.id === id)
  if (!target) return { ok: false, error: `无此请求 id：${id}（该项目的账里没有这一条）` }
  if (target.status === 'answered') {
    return { ok: false, error: `请求 ${id} 已于 ${new Date(target.answered_at ?? 0).toISOString()} 由 ${target.answered_by ?? '?'} 应答——拒绝二次应答（留痕不可改写）` }
  }
  const answerRow: AnswerRow = { type: 'answer', answer_for: id, at: nowMs, answer, by }
  io.appendFileSync(requestsLedgerFile(key, env), JSON.stringify(answerRow) + '\n')
  return { ok: true, answerRow }
}

/** 读账并合流应答（畸形行计数显式在案，绝不静默丢弃——账本纪律同守望者）。 */
export function readRequests(io: LedgerIo, env: NodeJS.ProcessEnv, key: string): RequestsRead {
  const file = requestsLedgerFile(key, env)
  const out: RequestsRead = { file, rows: [], malformed_rows: 0 }
  if (!io.existsSync(file)) return out
  let raw = ''
  try { raw = io.readFileSync(file) } catch { out.malformed_rows += 1; return out }
  const lines = raw.split('\n').filter(l => l.trim() !== '')
  const requests = new Map<string, RequestView>()
  const answers: AnswerRow[] = []
  for (const line of lines) {
    let doc: unknown
    try { doc = JSON.parse(line) } catch { out.malformed_rows += 1; continue }
    if (isRequestRow(doc)) {
      // 历史行（t260929-08 前落账）没有 raised_by：读出统一归一化为 ''（未归属哨兵），不畸形。
      requests.set(doc.id, { ...doc, raised_by: typeof doc.raised_by === 'string' ? doc.raised_by : '', status: 'waiting' })
    } else if (isAnswerRow(doc)) {
      answers.push(doc)
    } else {
      out.malformed_rows += 1
    }
  }
  for (const a of answers) {
    const t = requests.get(a.answer_for)
    if (!t) { out.malformed_rows += 1; continue } // 指向不存在请求的应答行=畸形留痕，不静默
    t.status = 'answered'; t.answer = a.answer; t.answered_at = a.at; t.answered_by = a.by
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

function isAnswerRow(v: unknown): v is AnswerRow {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return r.type === 'answer' && typeof r.answer_for === 'string' && typeof r.at === 'number'
    && typeof r.answer === 'string'
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
