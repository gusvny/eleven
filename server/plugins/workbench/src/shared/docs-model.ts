/**
 * docs-model.ts —— 「文档」视图纯函数层（t260905-06，无 DOM / 无 IO，node 可裸 import 直测）。
 *
 * 职责：工单台「文档」入口（docs/ 定稿库 + notes/ 观察窗）三件共用的模型口径：
 *   1. 路径白名单 isSafeDocRel —— 服务端（node.ts docs 端点）与客户端（目录项合法性）
 *      单源；白名单外的文件进 tree 响应 skipped 列表（拒收可见，C3），不静默消失。
 *   2. parseFrontmatter —— docs/ 定稿库每篇头部 YAML 简版解析（title/status/updated）；
 *      畸形输入（缺闭合符/嵌套 ---/空文件）一律定值分支不 throw。
 *   3. buildDocTree —— 扁平文件清单 → 按实际子目录动态聚合（C2：不写死 design/ops 名单，
 *      客户端分组跟着树渲染）；无子目录的根级文件单列「总目录」组。
 *
 * 纪律（R1 取舍清单 2 承接）：白名单拒绝必须可判定——skipped 计数+理由随响应下发，
 * 「人读视图完整性」不靠猜。
 */

/** scope 词表：docs=仓根定稿库 / notes=观察窗。 */
export type DocsScope = 'docs' | 'notes'

export const DOCS_SCOPES: readonly DocsScope[] = ['docs', 'notes']

export function isDocsScope(v: unknown): v is DocsScope {
  return v === 'docs' || v === 'notes'
}

/**
 * docs/notes 下 .md 相对路径白名单：
 * 段字符集 = 字母数字下划线 + 中文 + 连字符（\w 含下划线）；`/` 分段；必须 .md 结尾。
 * 显式拒绝：绝对路径、`..` 段、反斜杠、空格、全角符号、URL 编码残留（%xx）、空串。
 * （真库 31 篇全过；后续新增带空格/全角文件名会被拒收并进 skipped，可见。）
 */
const DOC_REL_RE = /^(?:[\w\u4e00-\u9fff-]+\/)*[\w\u4e00-\u9fff-]+\.md$/

/** 白名单判定。非字符串/空串/非法段一律 false（fail-closed，穿路径进不来）。 */
export function isSafeDocRel(rel: unknown): rel is string {
  if (typeof rel !== 'string' || rel === '') return false
  if (rel.includes('\\') || rel.includes('%')) return false
  if (!DOC_REL_RE.test(rel)) return false
  return !rel.split('/').includes('..')
}

/** frontmatter 简版元数据（仅取标量键，YAML 不做嵌套/列表——定稿库头部是平面键）。 */
export interface DocMeta {
  title?: string
  status?: string
  updated?: string
  category?: string
  [key: string]: string | undefined
}

export interface ParsedDoc {
  meta: DocMeta
  /** 去 frontmatter 后正文（无 frontmatter=原文）。 */
  body: string
  /** 是否解析到合法 frontmatter 块。 */
  hasFrontmatter: boolean
}

/**
 * 剥离首部 `---` frontmatter 块。畸形定值分支：
 * - 非 `---` 开头 → 原文返回；
 * - 开了 `---` 没闭合 → 原文返回（hasFrontmatter=false，不吞正文）；
 * - 空文件 → {meta:{}, body:'', hasFrontmatter:false}。
 */
export function parseFrontmatter(text: string): ParsedDoc {
  if (typeof text !== 'string') return { meta: {}, body: '', hasFrontmatter: false }
  if (!text.startsWith('---')) return { meta: {}, body: text, hasFrontmatter: false }
  const end = text.indexOf('\n---', 3)
  if (end === -1) return { meta: {}, body: text, hasFrontmatter: false }
  const head = text.slice(4, end) // 跳过首行 '---\n'
  const body = text.slice(end + 4).replace(/^\n+/, '')
  const meta: DocMeta = {}
  for (const line of head.split('\n')) {
    const m = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
    if (m) meta[m[1]] = m[2].trim()
  }
  return { meta, body, hasFrontmatter: true }
}

/** 目录树节点：dir=相对根的目录路径（''=根级），files=该目录下的篇（按路径排序）。 */
export interface DocTreeGroup {
  dir: string
  /** 客户端展示名：根级='总目录'，子目录=目录名最后一段。 */
  label: string
  files: { rel: string; title: string }[]
}

/** 单篇条目（rel=相对路径，title=展示标题，可空）。 */
export interface DocEntry {
  rel: string
  title?: string
}

/**
 * 扁平清单 → 目录分组。动态聚合（C2）：组=实际出现的目录集合；
 * 同目录内按 rel 字典序；组按目录名字典序、根级组恒在最前。
 * 白名单非法条目不进组（调用方应在入口处归入 skipped——本函数不重复判定）。
 */
export function buildDocTree(entries: DocEntry[]): DocTreeGroup[] {
  const byDir = new Map<string, { rel: string; title: string }[]>()
  for (const e of entries) {
    if (!isSafeDocRel(e.rel)) continue
    const dir = e.rel.includes('/') ? e.rel.slice(0, e.rel.lastIndexOf('/')) : ''
    if (!byDir.has(dir)) byDir.set(dir, [])
    const title = typeof e.title === 'string' && e.title !== '' ? e.title : e.rel
    byDir.get(dir)!.push({ rel: e.rel, title })
  }
  const dirs = [...byDir.keys()].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : a < b ? -1 : 1))
  return dirs.map((dir) => ({
    dir,
    label: dir === '' ? '总目录' : dir.slice(dir.lastIndexOf('/') + 1),
    files: byDir.get(dir)!.sort((a, b) => (a.rel < b.rel ? -1 : 1)),
  }))
}

/**
 * 篇标题推导：frontmatter title > 文件名去扩展名。
 * （parseFrontmatter 之后调用；无 frontmatter 的篇回落文件名。）
 */
export function docTitleOf(meta: DocMeta, rel: string): string {
  const t = meta?.title
  if (typeof t === 'string' && t !== '') return t
  const base = rel.slice(rel.lastIndexOf('/') + 1)
  return base.endsWith('.md') ? base.slice(0, -3) : base
}
