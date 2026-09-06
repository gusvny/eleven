/**
 * suyou-workbench · session-charter 渲染纯函数（t260904-07）。
 *
 * 职责：把 `server/dsh/session_charter.md`（会话开局注入源，改完即生效）
 * 渲染成单项目的注入文本：
 *   - 首段通用模板（文件顶部注释到第一个 `## project:` 分段之间）占位符
 *     统一现填（{{project_key}}/{{project_name}}/{{primary_dir}}/{{engine_root}}，
 *     注释内的占位符字样一并替换——真源口径，260904 附录+方案 R4 钉死）；
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
export const SESSION_CHARTER_PATH = '/suyou-workbench/api/session-charter'

/**
 * 上下文注入机读标记（t260905-04）：引擎侧给注入文本打的「消息元数据 kind=charter」
 * 落地载体。平台 wire 契约 PromptContentPart 无 metadata 字段（仓内冻结镜像
 * server/dsh/workbench/tests/ki046-charter-prompt-shape.mjs WIRE_CONTRACT 实锤），
 * 故标记拼在注入文本首行（HTML 注释样式的行，模型读无害；展开态随全文可见属
 * 已定降级——折叠态随内容区整体隐藏，「新会话开头只见小条」不受影响）。渲染端
 * （src/client/context-fold.ts）认本常量为折叠触发器，同源派生防两端漂移（R7 先例）；
 * 未来任何上下文注入（项目简介、文档引用）带同一标记即走同一折叠件。
 */
export const CHARTER_MARKER = '<!-- workbench:kind:charter -->'

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
  const { general, sections } = splitProjectSections(source)
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

（本模板=插件内置兜底版；项目定制内容见引擎仓 server/dsh/session_charter.md，可编辑，改完即生效。）
`
