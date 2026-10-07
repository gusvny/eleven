/**
 * sandbar-workbench · session-charter 渲染纯函数（t260904-07）。
 *
 * 职责：把 `server/session_charter.md`（会话开局注入源，改完即生效）
 * 渲染成单项目的注入文本：
 *   - the general template (after the file-doc comment is stripped, up to the
 *     first `## project:` section — t261008-01 stripLeadingComment) gets its
 *     placeholders filled ({{project_key}}/{{project_name}}/{{primary_dir}}/
 *     {{engine_root}}, including placeholder-like text inside comments — the
 *     unified-rendering rule, 260904 appendix + plan R4);
 *   - 命中 `## project:<key>` 分段（重复取首个）把该段原文追加在通用段后，
 *     段内占位符统一渲染（如 suyou 段的 {{engine_root}}）；
 *   - 文件缺失/读失败/空/渲染结果空 → 回落 DEFAULT_CHARTER_TEMPLATE
 *     （插件内置兜底简化版），由 node.ts 侧保证不 5xx。
 *
 * 本模块**零 node 顶层依赖**（纯字符串函数+常量，文件读取留在 node.ts——
 * node.ts 已有 readFile）：SESSION_CHARTER_PATH 同时被 node.ts 路由注册与
 * 客户端（session-entry.tsx）fetch URL 引用——同源常量派生，一处改动两端
 * 同变（t260904-07 方案 R7，KI-042「两端路径漂移恒 404」的结构性防漂移），
 * 也因此 tsdown 打进浏览器包不破（review C1 落位选型）。
 * smoke/session-charter.mjs 直测本模块 + 源文本断言两端引用。
 */

/** 会话开局 charter 端点路径（node.ts 注册与客户端 fetch 共用常量）。 */
export const SESSION_CHARTER_PATH = '/sandbar-workbench/api/session-charter'

/**
 * 上下文注入机读标记（t260905-04）：引擎侧给注入文本打的「消息元数据 kind=charter」
 * 落地载体。平台 wire 契约 PromptContentPart 无 metadata 字段（仓内冻结镜像
 * server/plugins/workbench/tests/ki046-charter-prompt-shape.mjs WIRE_CONTRACT 实锤），
 * so the marker sits on line 2 of the injected text (since t261008-01 line 1
 * is the human-readable title line — the platform session title takes the
 * first line and must not be a comment; an HTML-comment line is harmless for
 * the model to read; the expanded view showing the full text is the agreed
 * degradation — folded state hides the whole block, so "a new session opens
 * with just a chip" is unaffected). Renderer
 * （src/client/context-fold.ts）认本常量为折叠触发器，同源派生防两端漂移（R7 先例）；
 * 未来任何上下文注入（项目简介、文档引用）带同一标记即走同一折叠件。
 */
export const CHARTER_MARKER = '<!-- workbench:kind:charter -->'

/**
 * First line of the injected text (t261008-01): a short, human-readable title
 * line naming the project. The platform derives the session's durable title
 * from the first message's first line, so this line — not the machine marker —
 * is the session name a person sees. composeCharterInjection places the marker
 * on line 2 (the fold predicate reads the first 3 lines, same-source constant).
 * Tolerance: non-string -> empty-string; empty name -> key; both empty -> the
 * fixed label.
 */
export function charterTitleLine(projectName: string, projectKey: string): string {
  const name = typeof projectName === 'string' ? projectName.trim() : ''
  const key = typeof projectKey === 'string' ? projectKey.trim() : ''
  const label = name !== '' ? name : key !== '' ? key : 'project'
  return key !== '' && key !== label ? `Project session — ${label} (${key})` : `Project session — ${label}`
}

/**
 * Drop a leading HTML comment block from the charter source (t261008-01): the
 * file-doc comment at the top of session_charter.md is editor-facing metadata,
 * not charter content, and must not leak into the injected text (it used to
 * become line 2 of the platform session title). Rule: strip only when the
 * first non-whitespace content starts with `<!--` AND a closing `-->` exists —
 * an unterminated opener returns the text unchanged (never swallow the whole
 * file). No leading comment -> no-op; non-string -> returned as is.
 */
export function stripLeadingComment(raw: string): string {
  if (typeof raw !== 'string') return raw
  const start = raw.search(/\S/)
  if (start === -1 || !raw.startsWith('<!--', start)) return raw
  const end = raw.indexOf('-->', start)
  if (end === -1) return raw
  let cut = end + 3
  if (raw[cut] === '\r') cut += 1
  if (raw[cut] === '\n') cut += 1
  // Everything before the comment opener is whitespace by construction (start
  // = first non-whitespace position) — drop it too, so the body is not indented.
  return raw.slice(cut)
}

/**
 * Compose the full injected text (t261008-01): human-readable title line +
 * machine marker + rendered charter body. The fold predicate
 * (classifyContextFold) scans the first 3 lines for the marker, so the legacy
 * shape (marker on line 1) and this shape both fold. Tolerance: a non-string
 * charter counts as empty (the caller validates first; this function itself
 * never throws); empty name -> key, both empty -> the fixed label.
 */
export function composeCharterInjection(projectName: string, projectKey: string, charter: string): string {
  const body = typeof charter === 'string' ? charter : ''
  return `${charterTitleLine(projectName, projectKey)}\n${CHARTER_MARKER}\n${body}`
}

/** 渲染变量（全部替换为字符串；undefined/null 容错为空串）。 */
export interface CharterVars {
  projectKey: string
  projectName: string
  primaryDir: string
  engineRoot: string
}

/** 项目分段解析产物：通用段（首个 project 分段前全文）+ 分段列表（原文含标题行）。 */
export interface CharterSections {
  general: string
  sections: { key: string; body: string }[]
}

/** `## project:<key>` 分段标题行（行首、允许缩进；key=标题余文 trim）。 */
const PROJECT_HEADING_RE = /^[ \t]*##[ \t]+project:(.*)$/

/**
 * 分段解析：通用段=首个 `## project:` 标题行之前的全文；
 * 每个分段 body 自标题行起、到下一个 project 标题或文末。
 * 畸形输入容错：raw 非字符串 → 空产物；无分段 → sections 空、general=原文。
 */
export function splitProjectSections(raw: string): CharterSections {
  if (typeof raw !== 'string') return { general: '', sections: [] }
  const lines = raw.split('\n')
  const generalLines: string[] = []
  const sections: { key: string; body: string[] }[] = []
  let current: { key: string; body: string[] } | undefined
  for (const line of lines) {
    const m = PROJECT_HEADING_RE.exec(line)
    if (m) {
      current = { key: m[1].trim(), body: [line] }
      sections.push(current)
      continue
    }
    if (current) current.body.push(line)
    else generalLines.push(line)
  }
  return {
    general: generalLines.join('\n'),
    sections: sections.map(s => ({ key: s.key, body: s.body.join('\n') })),
  }
}

/** 单值渲染容错：字符串原样；null/undefined → 空串；其余 String() 化。 */
function varValue(v: unknown): string {
  if (typeof v === 'string') return v
  if (v === undefined || v === null) return ''
  return String(v)
}

/** 四占位符全量替换（含注释/分段内的字样，统一渲染口径）。 */
export function renderSessionCharter(raw: string, vars: CharterVars): string {
  const text = typeof raw === 'string' ? raw : ''
  const safe: CharterVars = {
    projectKey: varValue(vars?.projectKey),
    projectName: varValue(vars?.projectName),
    primaryDir: varValue(vars?.primaryDir),
    engineRoot: varValue(vars?.engineRoot),
  }
  return text
    .replaceAll('{{project_key}}', safe.projectKey)
    .replaceAll('{{project_name}}', safe.projectName)
    .replaceAll('{{primary_dir}}', safe.primaryDir)
    .replaceAll('{{engine_root}}', safe.engineRoot)
}

/**
 * 组装单项目注入文本：通用段渲染 + 命中分段原文追加（段内占位符统一渲染）。
 * - raw 非字符串/空白 → 回落 DEFAULT_CHARTER_TEMPLATE（兜底模板同链路渲染）；
 * - projectKey 畸形（非字符串/空串）→ 只回通用段，不命中任何分段；
 * - 重复分段取首个（find 语义）；
 * - 渲染结果整体空白 → 回落兜底模板渲染结果（保证注入文本非空）。
 */
export function composeSessionCharter(raw: string, projectKey: string, vars: CharterVars): string {
  const source = typeof raw === 'string' && raw.trim() !== '' ? raw : DEFAULT_CHARTER_TEMPLATE
  // The file-doc comment stays out of the injected text (t261008-01): the
  // editor-facing comment at the top of session_charter.md is stripped here
  // (only a closed leading block, see stripLeadingComment); the fallback
  // template has no leading comment -> no-op.
  const { general, sections } = splitProjectSections(stripLeadingComment(source))
  const key = typeof projectKey === 'string' ? projectKey.trim() : ''
  const matched = key === '' ? undefined : sections.find(s => s.key === key)
  const body = renderSessionCharter(general, vars).trimEnd()
  const tail = matched ? renderSessionCharter(matched.body, vars).trimEnd() : ''
  const out = tail !== '' ? `${body}\n\n${tail}` : body
  return out.trim() !== '' ? out : renderSessionCharter(DEFAULT_CHARTER_TEMPLATE, vars)
}

/**
 * 插件内置兜底模板（通用模板的简化版）：session_charter.md 缺失/读失败/空时
 * 回落——注入链路不 5xx、不中断建会话，但注入内容仍是有纪律的 charter。
 */
export const DEFAULT_CHARTER_TEMPLATE = `你是「{{project_name}}」的项目会话（key={{project_key}}，主目录={{primary_dir}}）。
对用户负责，独立于任何在跑工单的 developer/integration 角色。

## 职责
- 与人讨论、确定方案，结论落成可执行文字；notes/ 是过程账本（观察窗）只读，落盘须用户确认后攒批提交，不一小段一提交。
- 检查在跑工单的问题：只定位不修复，修复一律开票走 dev-lane（用户点名直修可进该票 lane，动手前先告知）。
- 带跑跨工单长任务（epic）：拆解为有依赖顺序的工单序列，逐张开票、逐张验收。

## 纪律与红线
- 开票/签字只走引擎 CLI（全部进 Temporal 不可变历史），不走旁路。
- 代签：仅在「在案授权」非空且注明出处时进行；授权为空=请用户亲自签。
- console（127.0.0.1:3099）是用户操作面：不重启/不停止/不占用。

（本模板=插件内置兜底版；项目定制内容见引擎仓 server/session_charter.md，可编辑，改完即生效。）
`
