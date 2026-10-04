/**
 * recent-actions.ts —— Overview 右栏「最近动作」只读源（t261003-06 引入；t261003-10 换源重写）。
 *
 * 数据来源（t261003-10 plan gen1 定稿，review 通过）：引擎自审计 admin.log
 * （server/engine/audit.py 唯一写口 `_append_line`，轮转/保留窗同文件文档化；面板只读，
 * 绝不写；env SANDBAR_ADMIN_LOG 覆盖与引擎同键，测试隔离用）。选它的理由：审计行自带
 * 「做了什么」（source/sub + summary.result）与 caller_project，同处一行；
 * 「凭哪条权限」= executor_grant_op / executor_grant_source / executor_channel——
 * 这三键与 caller_project 同在 **summary 解析后对象的顶层**（gen5 实测裁定，纠正
 * gen1/gen4 的层读错：引擎把 API 回执整体序列化进 summary；行级确实没有，但行级
 * 不是正确的读层）。带键行展示动作+权限；summary 无键的行（旧窗口/未带键直调）进
 * missing_authorization_rows，面板渲染**显式降级卡**（点名该窗口无可归因行），
 * 绝不渲染成空列表冒充「最近没动作」，也绝不给行编造权限。
 *
 * 行语义（t261003-06 R1-R5 保持）：
 *   R1 每行 {at, action, ticket, result, permission}；
 *   R2 permission 非空才展示（词表=grants 面 GRANT_OPS 同族）；
 *   R3 畸形行 / sub 认不出 / 缺授权键 分别计数，绝不静默丢、绝不编造；
 *   R4 不可得（文件缺席/不可读/无可展示行）→ ok:false + 人类可读原因点名源路径；
 *   R5 只读：读前后文件字节一致（场景红线）。
 *
 * io 全注入（测试内存桩；缺省 fs + 尾读）。零引擎改动、零 3099 触碰。
 */

import * as fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { PROJECT_KEY_RE } from './project-key.ts'

/** sub（引擎审计的操作名）→ 面板动作显示名。固定表；认不出的 sub 计数不编造。 */
export const ACTION_BY_SUB: Record<string, string> = {
  'ticket.sign': 'Sign',
  'ticket-start': 'Open ticket',
  'ticket.create': 'Open ticket',
  'ticket.update': 'Update',
  'ticket.pause': 'Pause',
  'ticket.resume': 'Resume',
  'worker-restart': 'Rerun',
  'ticket.send-back': 'Send back',
  'ticket.cancel': 'Cancel',
}

/**
 * executor_grant_op（授权词表，与 grants 面 GRANT_OPS 同族）→ 面板动作显示名。
 * 优先于 sub：实测在案（gen4 rework 点名样本）存在 sub='ticket'（泛化名）+
 * executor_grant_op='send-back'（真授权操作）的授权行——动作名从授权键取才不误计。
 */
export const ACTION_BY_OP: Record<string, string> = {
  'sign': 'Sign',
  'send-back': 'Send back',
  'send_back': 'Send back',
  'rerun': 'Rerun',
  'open-ticket': 'Open ticket',
  'open_ticket': 'Open ticket',
  'pause-resume': 'Pause or resume',
  'cleanup': 'Cancel',
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
  | {
      ok: true; source: string; actions: RecentAction[]
      unmapped_rows: number; malformed_rows: number; missing_authorization_rows: number
    }
  | { ok: false; source: string; reason: string }

/** io 缝（测试注入内存版；缺省 fs 版 + 尾读，绝不整读 242MB 生产文件）。 */
export interface ActionsIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
  /** 尾读（生产路径）；缺省由调用方回落 readFileSync（内存桩用）。 */
  readTail?(file: string, maxBytes: number): string
}

/** 尾读窗口：约 512KB，足够覆盖近期动作；更早的动作不展示（窗口语义，代码内文档化）。 */
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

/** 审计文件路径：env SANDBAR_ADMIN_LOG（与引擎 audit.py 同键）→ 模块相对 <repo>/server/admin.log。 */
export function adminLogFile(env: NodeJS.ProcessEnv = process.env): string {
  if (env.SANDBAR_ADMIN_LOG) return env.SANDBAR_ADMIN_LOG
  // 本文件在 <repo>/server/plugins/executor-panel/src/host/ → 上跳四级 = <repo>/server。
  return fileURLToPath(new URL('../../../../admin.log', import.meta.url))
}

function parseTicketFromSummary(summary: unknown): string {
  if (typeof summary !== 'string' || summary === '') return ''
  try {
    const doc = JSON.parse(summary) as { result?: { ticket_id?: unknown; ticket?: unknown; id?: unknown } }
    const r = doc?.result
    if (!r || typeof r !== 'object') return ''
    for (const k of ['ticket_id', 'ticket', 'id'] as const) {
      if (typeof r[k] === 'string' && (r[k] as string) !== '') return r[k] as string
    }
  } catch { /* summary 不是合法 JSON：票号留空（计数照常，不编造） */ }
  return ''
}

/**
 * summary 解析后对象顶层的 caller_project / executor_grant_op（gen5 实测裁定，纠正
 * gen1/gen4 的层读错）：引擎把 API 回执整体序列化进 summary，caller_project 与三个
 * 授权键（executor_grant_op / executor_grant_source / executor_channel）在 **summary
 * 顶层**，不在 admin.log 行级。行级 caller_project 作老形状兜底；读不到 = 缺席，
 * 走既有显式计数，绝不静默丢行。
 */
function summaryKeys(summary: unknown): { caller_project: string; executor_grant_op: string } {
  const out = { caller_project: '', executor_grant_op: '' }
  if (typeof summary !== 'string' || summary === '') return out
  try {
    const sd = JSON.parse(summary) as unknown
    if (sd && typeof sd === 'object' && !Array.isArray(sd)) {
      const o = sd as Record<string, unknown>
      if (typeof o.caller_project === 'string') out.caller_project = o.caller_project
      if (typeof o.executor_grant_op === 'string') out.executor_grant_op = o.executor_grant_op
    }
  } catch { /* summary 不合法：授权键视同缺席（显式计数，不编造） */ }
  return out
}

export type AdminLineVerdict =
  | { kind: 'action'; row: RecentAction }
  | { kind: 'missing_auth' }
  | { kind: 'unmapped'; permission: string }
  | { kind: 'other' }
  | { kind: 'malformed' }

/**
 * 单行 → 判定（受闸写动作 / 缺授权键 / sub 认不出 / 非执行器写行 / 畸形）。
 * 项目过滤：caller_project 在场且 ≠ key → other（别的项目的行）；缺席 = 引擎进程内
 * 直调（ticket.py-direct 行无此键，实测在案）= 本项目（引擎进程本身的服务对象），
 * 不据此丢行——丢行必须显式，不静默。
 */
export function parseAdminLine(line: string, key = ''): AdminLineVerdict {
  if (line.trim() === '') return { kind: 'other' }
  let doc: unknown
  try { doc = JSON.parse(line) } catch { return { kind: 'malformed' } }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) return { kind: 'malformed' }
  const r = doc as Record<string, unknown>
  const sKeys = summaryKeys(r.summary)
  // caller_project：summary 顶层优先（现行引擎形状），行级兜底（老形状）；两者都缺席 =
  // 引擎进程内直调 = 本项目（引擎进程本身的服务对象），不据此丢行。
  const caller = sKeys.caller_project !== ''
    ? sKeys.caller_project
    : (typeof r.caller_project === 'string' ? r.caller_project : '')
  if (key !== '' && caller !== '' && caller !== key) return { kind: 'other' }
  const sub = typeof r.sub === 'string' ? r.sub : ''
  const grantOp = sKeys.executor_grant_op !== ''
    ? sKeys.executor_grant_op
    : (typeof r.executor_grant_op === 'string' ? r.executor_grant_op : '')
  // 只展示「执行器受闸写动作」：有授权键的行才谈得上「凭哪条权限」。
  if (grantOp === '') {
    // 缺授权键但 sub 在动作词表 = 该行无授权可归因（旧窗口行/未带键的直调行），显式计数。
    if (sub !== '' && ACTION_BY_SUB[sub] !== undefined) return { kind: 'missing_auth' }
    return { kind: 'other' }
  }
  // 动作名：授权词表优先（executor_grant_op 是真授权操作；sub 可能是泛化名如 'ticket'），
  // sub 表兜底；两者都认不出 → unmapped（计数，不编造）。
  const action = ACTION_BY_OP[grantOp] ?? ACTION_BY_SUB[sub]
  if (action === undefined) return { kind: 'unmapped', permission: grantOp }
  const at = typeof r.ts === 'number' && Number.isFinite(r.ts) ? r.ts * 1000 : 0
  const result = (r.ok === false ? 'refused' : 'ok')
  return {
    kind: 'action',
    row: { at, action, ticket: parseTicketFromSummary(r.summary), result, permission: grantOp },
  }
}

/**
 * 读最近动作（新的在前，上限 max 条）。R4 纪律：任何「无可展示」都有点名原因，
 * 绝不返回 ok:true + 空列表冒充「最近没动作」。
 */
export function readRecentActions(
  io: ActionsIo, env: NodeJS.ProcessEnv, key: string, max = 12,
): RecentActionsRead {
  const source = adminLogFile(env)
  if (!PROJECT_KEY_RE.test(key)) {
    return { ok: false, source, reason: 'project key 形状不合法——读不出动作账' }
  }
  if (!io.existsSync(source)) {
    return { ok: false, source,
             reason: 'the executor audit log does not exist (' + source + ') — no recorded actions to show' }
  }
  let raw = ''
  try {
    raw = io.readTail ? io.readTail(source, TAIL_BYTES) : io.readFileSync(source)
  } catch (e) {
    return { ok: false, source,
             reason: 'the executor audit log is unreadable: ' + (e instanceof Error ? e.message : String(e)) }
  }
  const actions: RecentAction[] = []
  let malformed = 0
  let unmapped = 0
  let missingAuth = 0
  for (const line of raw.split('\n')) {
    const v = parseAdminLine(line, key)
    if (v.kind === 'action') actions.push(v.row)
    else if (v.kind === 'malformed') malformed++
    else if (v.kind === 'unmapped') unmapped++
    else if (v.kind === 'missing_auth') missingAuth++
  }
  actions.sort((a, b) => b.at - a.at)
  const shown = actions.slice(0, max)
  if (shown.length === 0) {
    if (missingAuth > 0) {
      return { ok: false, source,
        reason: missingAuth + ' executor action row(s) exist in ' + source
          + ' but none of them records which permission authorized it (no executor_grant_op in the parsed summary of these rows). Nothing is shown rather than permission-less rows.' }
    }
    return { ok: false, source,
             reason: 'no gated executor actions (nothing in the recent window records a permission-bearing executor write) in ' + source }
  }
  return { ok: true, source, actions: shown, unmapped_rows: unmapped, malformed_rows: malformed, missing_authorization_rows: missingAuth }
}
