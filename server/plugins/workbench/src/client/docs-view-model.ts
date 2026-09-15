/**
 * docs-view-model.ts —— 「文档」视图客户端纯函数层（t260910-10，无 DOM / 无 IO，
 * node 可裸 import 直测——tests/t260910_10_docs_view.mjs）。
 *
 * 职责（mock v1 版面拆出的可判定逻辑，UI 组件只做装配）：
 *   1. filterGroups —— Search 过滤：当前项目树内按 title/rel 子串收窄（大小写不敏感）；
 *      过滤后空组整体隐藏（空结果=空列表，不渲染空组头）。
 *   2. outlineFromHtml —— On this page 大纲提取：renderMarkdown 产物里按 DOM 顺序抓
 *      h2/h3 文本（第 i 个 h2/h3 与渲染后容器内第 i 个 heading 一一对应，id 由组件
 *      侧按同一顺序赋 `doc-h-<i>`——单一顺序源，两侧不漂移）。
 *   3. verifiedChipValue —— Verified chip 取值：meta.verified 真值透传；数据源未就绪
 *      （缺失/空/非字符串）显式英文占位 'pending'，不留假日期（doc-lifecycle 面 B 口径）。
 *   4. chipPath —— Path chip 展示串：`<scope>/<rel>`（与 mock 的 docs/design/x.md 同形）。
 *   5. projectOptions —— Project 选择器选项：首项恒为 synthesized 缺省项
 *      'sandbar / default'（key=''，后端缺省回落引擎仓）——不依赖 registry 真有 sandbar
 *      条目（隔离台只注册夹具项目时选择器仍有合法初值）；registry 项目随后。
 *
 * 畸形输入纪律：外部消费面（fetch 响应 / 用户输入 / DOM 产物）一律定值分支，
 * 不 throw、不产出误导值。
 */
import type { DocTreeGroup } from '../shared/docs-model.ts'

/** On this page 锚点 id 前缀（组件侧按 DOM 顺序赋 `doc-h-<i>`，本前缀单源）。 */
export const HEADING_ID_PREFIX = 'doc-h-'

export interface OutlineEntry {
  level: 2 | 3
  text: string
  /** 点击跳转目标 = 渲染后 heading 的 DOM id。 */
  id: string
}

/** Search 过滤（大小写不敏感子串，title+rel 双字段命中）。畸形输入定值：非数组→[]，非字符串 query→原样。 */
export function filterGroups(groups: unknown, query: unknown): DocTreeGroup[] {
  if (!Array.isArray(groups)) return []
  const q = typeof query === 'string' ? query.trim().toLowerCase() : ''
  if (q === '') return groups
  return groups
    .map((g) => {
      const files = (Array.isArray(g?.files) ? g.files : []).filter((f) => {
        const title = typeof f?.title === 'string' ? f.title : ''
        const rel = typeof f?.rel === 'string' ? f.rel : ''
        return title.toLowerCase().includes(q) || rel.toLowerCase().includes(q)
      })
      return { ...g, files }
    })
    .filter((g) => g.files.length > 0)
}

/** renderMarkdown 产物里的 h2/h3 文本提取（DOM 顺序；标签内富文本剥标签+基础实体解码）。 */
export function outlineFromHtml(html: unknown): OutlineEntry[] {
  if (typeof html !== 'string' || html === '') return []
  const out: OutlineEntry[] = []
  const re = /<h([23])(?:\s[^>]*)?>([\s\S]*?)<\/h\1>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    const text = m[2]
      .replace(/<[^>]+>/g, '')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, '\'')
      .trim()
    if (text === '') continue
    out.push({ level: m[1] === '2' ? 2 : 3, text, id: `${HEADING_ID_PREFIX}${out.length}` })
  }
  return out
}

/** Verified chip 取值：真值透传，数据源未就绪显式 'pending' 占位（非日期形状）。 */
export function verifiedChipValue(meta: unknown): string {
  const v = (meta && typeof meta === 'object') ? (meta as Record<string, unknown>).verified : undefined
  return typeof v === 'string' && v.trim() !== '' ? v : 'pending'
}

/** Path chip 展示串：`<scope>/<rel>`。 */
export function chipPath(scope: string, rel: string): string {
  return `${scope}/${rel}`
}

export interface ProjectOption {
  /** '' = 缺省引擎仓（后端 source='default' 回落语义）。 */
  key: string
  label: string
}

/** Project 选择器选项：synthesized 缺省项恒在首（不依赖 registry 有 sandbar 条目）。 */
export function projectOptions(projects: unknown): ProjectOption[] {
  const opts: ProjectOption[] = [{ key: '', label: 'sandbar / default' }]
  if (!Array.isArray(projects)) return opts
  for (const p of projects) {
    const key = typeof p?.key === 'string' && p.key !== '' ? p.key : null
    if (key === null) continue
    const name = typeof p?.name === 'string' && p.name !== '' ? p.name : key
    opts.push({ key, label: name === key ? key : `${name} / ${key}` })
  }
  return opts
}

/**
 * 壳层跟随判定（t260915-10）：DocsSection 初值/跟随的单源纯函数（组件侧以 setState
 * updater 形态消费，本 UT 真值表=生产行为断言）。
 * touched=false（用户没动过选择器）→ 跟随壳层当前项目；非字符串/缺省 → ''=缺省引擎仓
 * 回落（既有语义不删）。touched=true（用户手动动过选择器）→ 保持现值，壳层变更不冲掉
 * （spec ②手动优先）。畸形输入定值分支，不 throw。
 */
export function followProjectKey(shellKey: unknown, currentKey: string, touched: boolean): string {
  if (touched) return currentKey
  return typeof shellKey === 'string' ? shellKey : ''
}

/**
 * 项目语境空目录指引（t260915-10，spec ③）：选择态≠'' 且 scope 目录空诚实降级时，
 * 给一行指引——点名项目键、scope 目录与「不回落引擎仓」（不许空态冒充有文档）；
 * 缺省引擎仓语境维持既有文案面（返回 ''，既有「目录为空：reason」行不重复）。畸形输入
 * 定值 ''，不 throw。
 */
export function emptyGuidance(treeEmpty: unknown, projectKey: unknown): string {
  if (treeEmpty !== true) return ''
  if (typeof projectKey !== 'string' || projectKey === '') return ''
  return `该项目（${projectKey}）根下暂无此 scope 目录——在项目根创建 docs/ 或 notes/ 目录后，文档会出现在这里；此处不回落引擎仓。`
}
