/**
 * inspection-report-model —— 巡检票详情「报告面」纯函数层（t260926-05）。
 *
 * 零 react / 平台依赖，node 可裸 import 黑盒单测
 * （tests/t260926-05-inspection-report-model.mjs）——形态借 ticket-list-model.ts
 * （纯函数层先例），故障模式取舍见票 t260926-05 方案 rev2。
 *
 * 渲染契约（工单验收②）：任何深嵌/未知形状的值都经 asText 走安全文本路径——
 * 绝不产出 `[object Object]`、绝不把对象直接喂给 React child；畸形形状走防御
 * 回退行，页面不炸。所有 label 英文（260904 宿主令：英文界面 + 数据不译）。
 *
 * 宿主半（src/host/inspection-report.ts）复用 reportDigest 生成报告 JSON
 * 的可读摘要——同源渲染契约：端点摘要与浏览器兜底渲染走同一函数，不各写一套。
 */

/* ------------------------------------------------------------- 安全文本 */

/** 对象/数组 → 可读文本（260926 宿主报「report UI 都是 [object Object]」）：
 *  字符串原样（超长截断）、数字/布尔 String()、其余走紧凑 JSON（超长截断），
 *  **绝不产出 `[object Object]`**；null/undefined → 空串（调用方据此决定是否渲染该行）。 */
export function asText(v: unknown, limit = 400): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v.length > limit ? v.slice(0, limit) + '…' : v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    const s = JSON.stringify(v)
    if (!s) return ''
    return s.length > limit ? s.slice(0, limit) + '…' : s
  } catch {
    // JSON.stringify 失败（环引用/BigInt）绝不回落 String(v)——那正是
    // `[object Object]` 的出生点。给显式占位，类型尽力标注。
    const kind = Array.isArray(v) ? 'array' : typeof v === 'object' ? 'object' : typeof v
    return `(unserializable ${kind}, truncated)`
  }
}

/* ------------------------------------------------------------- 通用行模型 */

/** 一行「label: value」；warn=true 时 UI 用警示色（预算耗尽/迟到回执等异常态）。 */
export interface LabeledRow {
  label: string
  value: string
  warn?: boolean
}

/** 摘要行：depth=缩进层数（每层 14px），text=已安全化的单行文本。 */
export interface DigestLine {
  depth: number
  text: string
}

/** 单元格值取行值：键存在且 asText 非空才给行（缺键=老载荷形态，不造假行）。 */
function rowOf(obj: Record<string, unknown>, key: string, label: string, limit = 400): LabeledRow | null {
  if (!(key in obj)) return null
  const value = asText(obj[key], limit)
  if (value === '') return null
  return { label, value }
}

/* ------------------------------------------------------------- 套件证据段 */

/** face["suite"]（engine inspection_deadman.suite_section 形状）→ 有标签行 +
 *  逐场景红绿 + blockers。畸形（非 dict）→ 单行安全文本，不炸不漏。 */
export function suiteSectionView(suite: unknown): {
  rows: LabeledRow[]
  cases: { name: string; exit: string }[]
  blockers: string[]
} {
  if (suite === null || suite === undefined) return { rows: [], cases: [], blockers: [] }
  if (typeof suite !== 'object' || Array.isArray(suite)) {
    return { rows: [{ label: 'Suite', value: asText(suite, 2000) }], cases: [], blockers: [] }
  }
  const s = suite as Record<string, unknown>
  const rows: LabeledRow[] = []
  // 核心计数恒在（缺键给 '—'：老回放形态也要可读，不静默整段消失）。
  const cnt = (k: string) => (k in s ? asText(s[k], 40) : '—')
  rows.push({ label: 'Suite ok', value: s.ok === undefined ? '—' : (s.ok ? 'yes' : 'no'), warn: s.ok === false })
  if (typeof s.error === 'string' && s.error.trim() !== '') rows.push({ label: 'Suite error', value: s.error, warn: true })
  rows.push({ label: 'Ran', value: cnt('ran') })
  rows.push({ label: 'Passed', value: cnt('passed') })
  rows.push({ label: 'Failed', value: cnt('failed'), warn: Number(s.failed) > 0 })
  rows.push({ label: 'Env fail', value: cnt('env_fail'), warn: Number(s.env_fail) > 0 })
  for (const [key, label] of [
    ['wall_seconds', 'Wall clock total (wall_seconds)'],
    ['supply_used_sec', 'Supply phase wall clock (supply_used_sec)'],
    ['runner_used_sec', 'Runner phase wall clock (runner_used_sec)'],
    ['run_budget_sec', 'Runner budget (run_budget_sec)'],
    ['supply_timeout_sec', 'Supply timeout (supply_timeout_sec)'],
    ['suite_timeout_sec', 'Suite timeout budget (suite_timeout_sec)'],
  ] as const) {
    const r = rowOf(s, key, label)
    if (r) rows.push(r)
  }
  if (s.suite_timeout) {
    rows.push({ label: 'Suite timeout', value: `YES — budget exhausted${s.suite_timeout_sec !== undefined ? ` (${asText(s.suite_timeout_sec, 40)}s)` : ''}`, warn: true })
  }
  if (s.late) {
    rows.push({ label: 'Late receipt', value: `YES — orphan receipt written after activity timeout${typeof s.late_error === 'string' && s.late_error ? `: ${s.late_error}` : ''}`, warn: true })
  }
  for (const [key, label] of [
    ['worktree', 'Worktree'],
    ['base_ref', 'Base ref'],
    ['report_path', 'Full suite receipt'],
  ] as const) {
    const r = rowOf(s, key, label, 2000)
    if (r) rows.push(r)
  }
  const rawCases = Array.isArray(s.cases) ? s.cases : []
  const cases = rawCases.map((c) => {
    if (c === null || typeof c !== 'object' || Array.isArray(c)) return { name: asText(c, 200), exit: '' }
    const cc = c as Record<string, unknown>
    return { name: asText(cc.name, 200), exit: asText(cc.exit, 20) }
  })
  const blockers = Array.isArray(s.blockers) ? s.blockers.map((b) => asText(b, 400)).filter((b) => b !== '') : []
  return { rows, cases, blockers }
}

/* ------------------------------------------------------------- 通用 face 行 */

/** 有专属渲染块（或有专属展示位）的键：faceRows 不再重复出泛化行。 */
const FACE_DEDICATED = new Set([
  // 泛化行已给出的 curated 键
  'heartbeat_note', 'budget_note', 'scan_meta', 'redirect',
  // 详情抽屉既有专属块（工单通用字段 + 巡检专属块），重复上屏=噪音
  'id', 'ticket_id', 'kind', 'instance_id', 'period', 'template', 'gate_id',
  'title', 'status', 'decision', 'stage', 'stage_state', 'project',
  'heartbeat', 'summary', 'findings', 'suggested_fix_tickets', 'red_line',
  'human_gate', 'gate_error', 'timeline', 'report_path', 'suite',
  'worktree', 'base_ref', 'session_kb', 'agent_alive', 'meta', 'handoff',
  'paused', 'engine', 'exec_status', 'close_health', 'urgency',
  'source_inspection', 'authz', 'authz_active', 'authorizations',
  'blocked_detail', 'parallel_stages',
])

/** curated 泛化行（有专属英文名的巡检报告面字段）。 */
const FACE_CURATED: [string, string][] = [
  ['heartbeat_note', 'Heartbeat note'],
  ['budget_note', 'Budget note'],
  ['scan_meta', 'Scan meta'],
  ['redirect', 'Redirect'],
]

/** 详情 face → 有标签行：curated 四键在前，其余未知键逐键 asText 兜底
 *  （引擎未来加键=自动可读，绝不裸对象）。畸形 detail → 空表（不炸）。 */
export function faceRows(detail: unknown): LabeledRow[] {
  if (detail === null || detail === undefined || typeof detail !== 'object' || Array.isArray(detail)) return []
  const d = detail as Record<string, unknown>
  const rows: LabeledRow[] = []
  for (const [key, label] of FACE_CURATED) {
    const r = rowOf(d, key, label, 2000)
    if (r) rows.push(r)
  }
  for (const key of Object.keys(d)) {
    if (FACE_DEDICATED.has(key)) continue
    const r = rowOf(d, key, key, 2000)
    if (r) rows.push(r)
  }
  return rows
}

/* ------------------------------------------------------------- 报告 JSON 摘要 */

/** 任意 JSON 值 → 缩进式可读摘要行（全部经 asText；环引用/超深/超行数都有界）。
 *  maxLines 封顶防巨报告刷爆 DOM——截断行显式点名，不静默。 */
export function reportDigest(v: unknown, maxLines = 2000): DigestLine[] {
  const lines: DigestLine[] = []
  const seen = new Set<object>()
  const walk = (node: unknown, depth: number, label: string): void => {
    if (lines.length >= maxLines) return
    const push = (text: string): void => { if (lines.length < maxLines) lines.push({ depth, text }) }
    if (node !== null && typeof node === 'object') {
      if (seen.has(node)) { push(`${label}: (circular reference — omitted)`); return }
      seen.add(node)
      if (lines.length + 1 >= maxLines) { push(`${label}: …(digest truncated at ${maxLines} lines)`); return }
      if (Array.isArray(node)) {
        push(`${label}: ${node.length} entries`)
        node.forEach((item, i) => walk(item, depth + 1, `[${i}]`))
      } else {
        const keys = Object.keys(node as Record<string, unknown>)
        push(`${label}: {${keys.length} keys}`)
        for (const k of keys) walk((node as Record<string, unknown>)[k], depth + 1, k)
      }
      seen.delete(node)
    } else {
      const text = asText(node, 2000)
      push(text === '' ? `${label}: (empty)` : `${label}: ${text}`)
    }
  }
  // 根节点没有名字——用 'report' 兜底，深度 0 起排。
  if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
    const keys = Object.keys(v as Record<string, unknown>)
    if (keys.length === 0) return [{ depth: 0, text: 'report: (empty object)' }]
    for (const k of keys) walk((v as Record<string, unknown>)[k], 0, k)
  } else if (Array.isArray(v)) {
    walk(v, 0, 'report')
  } else {
    const text = asText(v, 2000)
    return [{ depth: 0, text: text === '' ? 'report: (empty)' : `report: ${text}` }]
  }
  if (lines.length >= maxLines) lines.push({ depth: 0, text: `…(digest truncated at ${maxLines} lines)` })
  return lines
}

/* ------------------------------------------------------------- 发现项防御视图 */

/** 证据条目：loc=`path:line`（line 仅在 number 时拼接），quote=原句摘录。 */
export interface EvidenceView {
  loc: string
  quote: string
}

/** 单条发现项的安全视图（t260926-05 验收②③）：任何形状都有可读出路——
 *  非对象发现项 → fallback 一行；对象字段全走 asText；evidence 非数组 →
 *  evidenceFallback；证据条目非对象 → loc=asText 整条。 */
export function findingView(f: unknown, i: number): {
  fallback?: string
  sev: string
  scan: string
  confidence: string
  verified: string
  subject: string
  why: string
  suggestion: string
  evidence: EvidenceView[]
  evidenceFallback?: string
} {
  const empty = { sev: '', scan: '', confidence: '', verified: '', subject: '', why: '', suggestion: '', evidence: [] as EvidenceView[] }
  if (f === null || f === undefined) return { ...empty, fallback: `Finding ${i}: (empty entry)` }
  if (typeof f !== 'object' || Array.isArray(f)) {
    return { ...empty, fallback: `Finding ${i}: ${asText(f, 2000)}` }
  }
  const o = f as Record<string, unknown>
  const evidence: EvidenceView[] = []
  let evidenceFallback: string | undefined
  if (Array.isArray(o.evidence)) {
    for (const e of o.evidence) {
      if (e !== null && typeof e === 'object' && !Array.isArray(e)) {
        const ee = e as Record<string, unknown>
        const path = asText(ee.path, 300)
        const line = typeof ee.line === 'number' ? `:${ee.line}` : ''
        evidence.push({ loc: `${path}${line}`, quote: asText(ee.quote, 200) })
      } else {
        evidence.push({ loc: asText(e, 300), quote: '' })
      }
    }
  } else if (o.evidence !== undefined && o.evidence !== null) {
    evidenceFallback = asText(o.evidence, 2000)
  }
  return {
    fallback: undefined,
    sev: asText(o.severity, 40),
    scan: asText(o.scan, 200),
    confidence: typeof o.confidence === 'number' ? String(o.confidence) : asText(o.confidence, 40),
    verified: asText(o.verified, 200),
    subject: asText(o.subject, 400),
    why: asText(o.why, 2000),
    suggestion: asText(o.suggestion, 2000),
    evidence,
    evidenceFallback,
  }
}
