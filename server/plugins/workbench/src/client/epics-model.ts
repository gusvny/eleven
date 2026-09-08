/**
 * epics-model.ts —— 工单台「立项单」UI 的纯函数层（epic-linkage Tier 3，t260826-02）。
 *
 * 口径单点（真源=API 渲染，前端不存状态——立项单关键决策 5）：
 *   - 立项单列表/详情数据来自 GET /sandbar-workbench/api/epics*（host epics.ts，t260825-04）；
 *   - 本模块只承载 UI 侧可单测的判定逻辑：状态分桶、排序、徽标文案、新建工单注入文案；
 *   - smoke/epic-ui.mjs 直测（node ≥22.18 type-stripping，跨目录 import .ts 同
 *     smoke/sessions.mjs 先例）。写集约束：只能落 src/client/ 内（不放 src/shared/）。
 */

/** 立项单列表/详情共用的元信息形态（对齐 host src/host/epics.ts EpicMeta）。 */
export interface EpicMeta {
  /** 代号 = 文件名主名（notes/epics/<代号>.md）。 */
  code: string
  /** 标题（首个 # 行剥「立项单：」前缀）。 */
  title: string
  /** 状态（字段表格「状态」行；缺行 ''）。 */
  status: string
  /** 备注（字段表格「备注」行；缺行 ''。t260831-05 起括号细节从状态迁入此列）。 */
  note?: string
  /** 立项日期（字段表格「立项日期」行；缺行 ''）。 */
  created: string
}

/* ---------------------------------------------------- 立项状态枚举（t260831-05） */

/**
 * 立项状态枚举类型与选项清单。真源单点在 host src/host/epics.ts EPIC_STATUSES——
 * 但 host 模块依赖 node:fs，不能进浏览器 bundle（tsdown platform=browser），故按
 * gen1 方案降级：此处复制四值，一致性由 smoke/epics-status.mjs 两端比对断言兜底，
 * 防单边漂移（改一边必须同步另一边）。
 */
export type EpicStatus = '已立项（待开工单）' | '已立项（执行中）' | '已完结' | '已归档'

export const EPIC_STATUS_OPTIONS: readonly EpicStatus[] = [
  '已立项（待开工单）', '已立项（执行中）', '已完结', '已归档',
] as const

/** 枚举精确匹配白名单（前端兜底；后端 setEpicStatus 有同口径最终校验）。 */
export function isEpicStatusValue(s: string): s is EpicStatus {
  return (EPIC_STATUS_OPTIONS as readonly string[]).includes(s)
}

/** 备注输入框长度上限（与 host EPIC_NOTE_MAX 互指，勿单边漂移）。 */
export const EPIC_NOTE_INPUT_MAX = 200

/**
 * 状态筛选（工单台立项单列表，t260831-05）：status 为空串/undefined = 全部不过滤；
 * 其余按枚举值精确过滤。未知值（防御性）返回空数组并 console.warn 一条——
 * 白名单外状态本不该存在（写入已拒收），出现即迁移漏网，值得看见。
 */
export function filterEpicsByStatus<T extends { status?: string }>(rows: T[], status?: string): T[] {
  const s = String(status ?? '').trim()
  if (s === '') return rows
  if (!isEpicStatusValue(s)) {
    console.warn(`filterEpicsByStatus：未知状态 '${s}' 不在枚举内，返回空列表（疑似迁移漏网）`)
    return []
  }
  return rows.filter((r) => String(r?.status ?? '') === s)
}

/** GET /epics/<code>/tickets 的工单行（node.ts map 后的形状）。 */
export interface EpicTicketRow {
  id: string
  title: string
  status: string
  stage: string
  stage_state: string
}

/** GET /epics/<code>/tickets 的响应主体（degraded 降级契约：200 + reason 人话）。 */
export interface EpicTicketsResult {
  code: string
  count?: number
  buckets?: Record<string, number>
  tickets?: EpicTicketRow[]
  degraded?: boolean
  reason?: string
}

/** 状态分桶归一（UI 展示口径）：closed/verified→已完成、terminated→已终止、其余→进行中。 */
export function bucketOf(status: string): string {
  if (status === 'closed' || status === 'verified') return '已完成'
  if (status === 'terminated') return '已终止'
  return '进行中'
}

/** 桶展示顺序：进行中 → 已完成 → 已终止 → 未知桶字典序殿后（稳定、可预期）。 */
const BUCKET_ORDER = ['进行中', '已完成', '已终止']
export function sortBucketKeys(keys: string[]): string[] {
  return [...keys].sort((a, b) => {
    const ia = BUCKET_ORDER.indexOf(a)
    const ib = BUCKET_ORDER.indexOf(b)
    const oa = ia < 0 ? BUCKET_ORDER.length : ia
    const ob = ib < 0 ? BUCKET_ORDER.length : ib
    return oa !== ob ? oa - ob : a.localeCompare(b)
  })
}

/**
 * API 的 buckets 按原始 status 分桶（closed/dispatched/…）——UI 展示前先按 bucketOf
 * 归并求和（验收口径=分桶计数，「已完成 ×3」比「closed ×2 + verified ×1」更可读）。
 */
export function mergeBuckets(buckets: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(buckets ?? {})) {
    const b = bucketOf(k)
    out[b] = (out[b] ?? 0) + (Number(v) || 0)
  }
  return out
}

/** 工单行排序：进行中在前、已收口在后，各自按 id 降序（新工单在上）；缺字段容错不抛。 */
export function sortEpicTickets(rows: EpicTicketRow[]): EpicTicketRow[] {
  const rank = (r: EpicTicketRow): number => (bucketOf(String(r?.status ?? '')) === '进行中' ? 0 : 1)
  return [...rows].sort((a, b) =>
    rank(a) - rank(b) || String(b?.id ?? '').localeCompare(String(a?.id ?? '')))
}

/**
 * 所属立项徽标口径（单点）：有 epic → 可点代号 chip；无 → 灰「未归档」chip。
 * 人门签字确认区不用本口径（review M1：那里「有则显示无则略」，不显示「未归档」字样）。
 */
export function epicBadgeOf(epic?: string): { label: string; code: string | null } {
  const code = (epic ?? '').trim()
  return code === '' ? { label: '未归档', code: null } : { label: code, code }
}

/** 新建工单正文首行注入的归属说明（验收标准 9：代号由界面带入，正文里留痕、不许手输改绑）。 */
export function epicCreateNote(code: string): string {
  return `所属立项：${code}（代号由界面带入，不可修改）`
}

/** integration「继续执行」建议（host epic-next.ts EpicNextSuggestion 互指；suggest-next 路由的 suggestion 形状）。
 *  字段可选以容纳 done 形态（t260828-08：{status:'done',summary} 建议结项）；消费侧一律 String(x ?? '') 容错读。 */
export interface EpicNextSuggestion {
  workflow?: string
  title?: string
  body?: string
  rationale?: string
  /** 'ok'=建议下一单（缺省视为 ok）；'done'=立项可完结（前端出「建议结项」卡片）。 */
  status?: 'ok' | 'done'
  /** status='done' 时的人话说明（立项目标已达成）。 */
  summary?: string
  /** t260829-07：建议的预计改动文件清单（host epic-next.ts sanitizeWriteSet 已清洗：
   *  仓库内相对路径、保序去重）；缺失/全非法为空数组。预填新建工单弹层写集编辑栏。 */
  write_set?: string[]
}

/* ---------------- 写集生命周期（t260829-07）：弹层写集编辑栏纯函数 ---------------- */

/** 单条写集路径合法性（host epic-next.ts validWriteSetEntry 同构互指）：
 *  仓库内相对路径——空串/绝对路径/含 '..'/反斜杠/Windows 盘符一律非法。 */
export function validWriteSetEntry(p: unknown): boolean {
  if (typeof p !== 'string') return false
  const s = p.trim()
  if (s === '' || s.startsWith('/') || s.startsWith('\\') || s.includes('\\')) return false
  if (s.length >= 2 && s[1] === ':' && /[a-zA-Z]/.test(s[0])) return false
  return !s.split('/').includes('..')
}

/** 写集文本 ↔ 数组：每行一条；空行与首尾空白容忍；空白行不产生条目。 */
export function writeSetTextToLines(text: string): string[] {
  return String(text ?? '')
    .split('\n')
    .map((ln) => ln.trim())
    .filter((ln) => ln !== '')
}

/** 弹层提交前校验：返回非法行清单（合法为空数组）。有非法行 → 前端拦截提交并标红。 */
export function invalidWriteSetLines(text: string): string[] {
  return writeSetTextToLines(text).filter((ln) => !validWriteSetEntry(ln))
}

/** 「无文件改动」声明拦截判定（t260901-01）：写集为空且未勾选声明 → 返回拦截文案
 *  （两条出路口径，与引擎 shared.validate_write_set_args 拒收文案同源同义）；
 *  其余（写集非空 / 已勾选声明）返回空串放行。 */
export function createWriteSetBlocked(text: string, allowEmpty: boolean): string {
  if (writeSetTextToLines(text).length > 0) return ''
  if (allowEmpty) return ''
  return ('写集为空：agent 将没有白名单护栏、UI 票判定失效。两条出路：'
    + '① 填写写集，列出本票预计改动文件清单（每行一条）；'
    + '② 确实无文件改动时勾选下方「本票无文件改动（allow_empty_write_set）」显式声明'
    + '（meta 记 no_file_changes）。')
}

/** 建票 POST 体基础字段（submitCreate 组装用）。 */
export interface CreatePayloadBase {
  workflow: string
  title: string
  body: string
  epic: string
}

/** 建票 POST 体组装（t260901-01 单点）：写集文本 → 数组；仅当写集为空且勾选
 *  「无文件改动」声明时才附 allow_empty_write_set=true（引擎空写集+声明才放行，
 *  非空写集带该字段无意义，不附，保持 payload 最小面）。 */
export function buildCreatePayload(
  base: CreatePayloadBase, text: string, allowEmpty: boolean,
): Record<string, unknown> {
  const writeSet = writeSetTextToLines(text)
  const payload: Record<string, unknown> = {
    workflow: base.workflow, title: base.title.trim(), body: base.body, epic: base.epic,
    write_set: writeSet,
  }
  if (writeSet.length === 0 && allowEmpty) payload.allow_empty_write_set = true
  return payload
}

/**
 * 继续执行建议回填正文合成（t260827-02）：首行归属说明（同 epicCreateNote 口径）
 * + 空行 + 建议正文；建议正文为空只留归属行（与 openCreate 的空预填形态一致）。
 */
export function composeSuggestedBody(code: string, suggestedBody: string): string {
  const body = String(suggestedBody ?? '').trim()
  return body === '' ? epicCreateNote(code) + '\n' : `${epicCreateNote(code)}\n\n${body}`
}
