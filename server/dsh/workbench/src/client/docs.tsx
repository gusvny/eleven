/**
 * docs.tsx —— 工单台「文档」视图（t260905-06）：docs/ 定稿库人读视图 + notes/ 观察窗。
 *
 * 语义（C1 写死）：全仓单例——docs/ 定稿库属仓不属项目，组件签名不收 projectKey；
 * 侧栏任一项目组头的「文档」图标都开同一个仓根库。数据源=宿主半
 * GET /suyou-workbench/api/wf/docs/tree|doc（见 node.ts handleDocsTree/handleDocsDoc）。
 *
 * 渲染（R1 取舍清单 1）：markdown 复用 knowledge 插件 renderMarkdown（转义先行/
 * 危险 URL 拒绝/高亮 guard 全量随 import 带入，一个不拆），经 dangerouslySetInnerHTML
 * 落容器（index.tsx 同款先例）；代码块等宽只作用于本视图容器（.wb-doc-body），
 * 零出厂元素 CSS 压制（t260829-06 纪律）。
 *
 * 资源终态（R1 取舍清单 4）：scope 切换/组件卸载时 AbortController.abort 收口
 * in-flight fetch（正常/报错/取消三路径都落定）；目录/正文请求分离，正文懒加载
 * （点目录项才取，同 MetricsPanel open 才挂载的懒加载精神）。
 *
 * 窄栏（R2③）：<=720px 单栏流——选中篇时目录收起、显「← 目录」返回钮；
 * 无横向溢出断言由集成场景锚 .wb-doc-root 容器（V1②口径）。
 */
import { useEffect, useState } from 'react'
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import type { DocTreeGroup, DocsScope } from '../shared/docs-model.ts'

const API = '/suyou-workbench/api/wf/docs'

interface TreeResult {
  empty: boolean
  reason?: string
  groups: DocTreeGroup[]
  skipped: { path: string; reason: string }[]
}

interface DocResult {
  empty: boolean
  reason?: string
  title?: string
  meta?: Record<string, string | undefined>
  body?: string
}

const DOCS_STYLE = `
/* 窄可用=容器级响应（@container）：中列被压缩/窄设备都走单栏流，不依赖视口媒体查询
 * （壳在窄视口会卸载本插件槽——视口级断点对「移动窄栏」不可达，探针实证见场景②）。 */
.wb-doc-root { container-type: inline-size; height:100%; min-height:0; }
.wb-doc-frame { display:flex; gap:0; height:100%; min-height:0; }
.wb-doc-toc { width:280px; flex:none; overflow-y:auto; padding:10px; border-right:1px solid #2a2f3a; }
.wb-doc-main { flex:1; overflow-y:auto; padding:16px 22px; min-width:0; }
.wb-doc-scope-row { display:flex; gap:6px; margin-bottom:10px; }
.wb-doc-scope-btn { border:1px solid #3a404c; background:transparent; color:#c9d1d9;
  padding:4px 12px; border-radius:6px; cursor:pointer; font-size:13px; }
.wb-doc-scope-btn.active { background:#1f6feb; border-color:#1f6feb; color:#fff; }
.wb-doc-group-head { font-size:12px; color:#8b949e; margin:12px 0 4px; text-transform:none; }
.wb-doc-item { display:block; width:100%; text-align:left; border:0; background:transparent;
  color:#c9d1d9; padding:5px 8px; border-radius:6px; cursor:pointer; font-size:13px;
  line-height:1.5; overflow-wrap:anywhere; }
.wb-doc-item:hover { background:rgba(255,255,255,0.08); }
.wb-doc-item.active { background:#1f6feb; color:#fff; }
.wb-doc-skip-note { font-size:12px; color:#d29922; margin-top:14px; line-height:1.6; }
.wb-doc-title { font-size:18px; margin:0 0 4px; }
.wb-doc-meta { font-size:12px; color:#8b949e; margin-bottom:14px; }
.wb-doc-empty { color:#8b949e; padding:20px 4px; line-height:1.7; }
.wb-doc-back { display:none; border:1px solid #3a404c; background:transparent; color:#c9d1d9;
  padding:4px 12px; border-radius:6px; cursor:pointer; margin-bottom:10px; }
.wb-doc-body { line-height:1.75; overflow-wrap:anywhere; color:#e6edf3; font-size:14px; }
.wb-doc-body h1, .wb-doc-body h2, .wb-doc-body h3 { line-height:1.4; }
.wb-doc-body pre { background:#161b22; border:1px solid #2a2f3a; border-radius:8px;
  padding:10px 12px; overflow-x:auto; }
/* 代码块自持样式（t260905-06 验收 A 附带项）：renderMarkdown 产出的 .md-code/.md-copy/
 * .tok-* 出厂样式由 knowledge 插件全局 CSS 注入供给——本视图自带一份（深色适配），
 * knowledge 退役另票时本视图不随之破相。复制行为委托见下方 onDocCopy。 */
.wb-doc-body .md-code { position:relative; margin:10px 0; border:1px solid #2a2f3a;
  border-radius:8px; background:#161b22; overflow:hidden; }
.wb-doc-body .md-code pre { margin:0; border:0; border-radius:0; }
.wb-doc-body .md-cl { position:absolute; top:6px; right:60px; font-size:11px; color:#8b949e;
  background:#21262d; border-radius:4px; padding:0 8px; line-height:18px; }
.wb-doc-body .md-copy { position:absolute; top:6px; right:8px; font-size:11px; padding:1px 10px;
  line-height:18px; cursor:pointer; border:1px solid #3a404c; background:#21262d;
  color:#c9d1d9; border-radius:4px; }
.wb-doc-body .md-copy:hover { background:#30363d; color:#fff; }
.wb-doc-body .tok-c { color:#8b949e; font-style:italic; }
.wb-doc-body .tok-s { color:#a5d6ff; }
.wb-doc-body .tok-k { color:#ff7b72; font-weight:600; }
.wb-doc-body .tok-n { color:#79c0ff; }
.wb-doc-body .tok-v { color:#ffa657; }
.wb-doc-body pre code, .wb-doc-body code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.wb-doc-body table { border-collapse:collapse; }
.wb-doc-body th, .wb-doc-body td { border:1px solid #2a2f3a; padding:4px 8px; }
@container (max-width: 720px) {
  .wb-doc-frame { flex-direction:column; }
  .wb-doc-toc { width:100%; border-right:0; }
  .wb-doc-main { padding:12px; }
  .wb-doc-frame.has-doc .wb-doc-toc { display:none; }
  .wb-doc-frame.has-doc .wb-doc-back { display:inline-block; }
}
`

/** 复制按钮委托（验收走查打回项 A）：renderMarkdown 产出的 .md-copy 出厂无行为——
 * 行为委托原本只在已不被工单台挂载的 KnowledgeSection 里，本视图自带同款（点按钮
 * 写 data-code 解码原文进剪贴板；剪贴板 API 不可用静默=出厂同款取舍）。 */
function onDocCopy(e: React.MouseEvent): void {
  const btn = (e.target as HTMLElement).closest('.md-copy') as HTMLElement | null
  if (!btn) return
  const code = btn.getAttribute('data-code') ?? ''
  try { void navigator.clipboard?.writeText(decodeURIComponent(code)) } catch { /* 静默 */ }
}

export function DocsSection(_props: Record<string, never>) {
  const [scope, setScope] = useState<DocsScope>('docs')
  const [tree, setTree] = useState<TreeResult | null>(null)
  const [treeErr, setTreeErr] = useState('')
  const [selected, setSelected] = useState<string>('')
  const [doc, setDoc] = useState<DocResult | null>(null)

  // 目录树：scope 切换即重取；in-flight 取消（卸载/scope 变更双路径）。
  useEffect(() => {
    const ac = new AbortController()
    setTree(null)
    setTreeErr('')
    fetch(`${API}/tree?scope=${scope}`, { signal: ac.signal })
      .then((r) => r.json())
      .then((j) => { setTree(j?.result ?? { empty: true, reason: '响应缺 result', groups: [], skipped: [] }) })
      .catch((err) => { if (!ac.signal.aborted) setTreeErr(String(err?.message ?? err)) })
    return () => ac.abort()
  }, [scope])

  // 正文：点目录项才取（懒加载）；切篇/卸载取消 in-flight。
  useEffect(() => {
    if (!selected) { setDoc(null); return }
    const ac = new AbortController()
    setDoc(null)
    fetch(`${API}/doc?scope=${scope}&path=${encodeURIComponent(selected)}`, { signal: ac.signal })
      .then((r) => r.json())
      .then((j) => { setDoc(j?.result ?? { empty: true, reason: '响应缺 result' }) })
      .catch((err) => { if (!ac.signal.aborted) setDoc({ empty: true, reason: String(err?.message ?? err) }) })
    return () => ac.abort()
  }, [scope, selected])

  const groups = tree?.groups ?? []
  return (
    // has-doc=已选中篇（窄容器据此收目录显返回钮）——跟随 selected，不写死。
    <div className="wb-doc-root" data-wb-docs-root="" data-wb-docs-scope={scope} data-wb-docs-selected={selected}>
      <style>{DOCS_STYLE}</style>
      <div className={`wb-doc-frame ${selected ? 'has-doc' : ''}`} data-wb-docs-frame="">
      <nav className="wb-doc-toc" data-wb-docs-toc="" aria-label="文档目录">
        <div className="wb-doc-scope-row" role="tablist" aria-label="文档范围">
          <button className={`wb-doc-scope-btn ${scope === 'docs' ? 'active' : ''}`} role="tab"
            aria-selected={scope === 'docs'} data-wb-docs-scope-docs=""
            onClick={() => { setSelected(''); setScope('docs') }}>定稿库</button>
          <button className={`wb-doc-scope-btn ${scope === 'notes' ? 'active' : ''}`} role="tab"
            aria-selected={scope === 'notes'} data-wb-docs-scope-notes=""
            onClick={() => { setSelected(''); setScope('notes') }}>notes 观察窗</button>
        </div>
        {treeErr && <div className="wb-doc-empty">目录加载失败：{treeErr}</div>}
        {!treeErr && !tree && <div className="wb-doc-empty">加载中…</div>}
        {tree?.empty && <div className="wb-doc-empty">目录为空：{tree.reason}</div>}
        {groups.map((g) => (
          <div key={g.dir}>
            <div className="wb-doc-group-head">{g.label}</div>
            {g.files.map((f) => (
              <button key={f.rel} className={`wb-doc-item ${selected === f.rel ? 'active' : ''}`}
                data-wb-doc-item={f.rel} onClick={() => setSelected(f.rel)}>{f.title}</button>
            ))}
          </div>
        ))}
        {tree && tree.skipped.length > 0 && (
          <div className="wb-doc-skip-note" data-wb-docs-skipped="">
            未入视图 {tree.skipped.length} 个文件（{tree.skipped.map((s) => `${s.path}：${s.reason}`).join('；')}）
          </div>
        )}
      </nav>
      <main className="wb-doc-main" data-wb-docs-main="">
        <button className="wb-doc-back" data-wb-docs-back="" onClick={() => setSelected('')}>← 目录</button>
        {!selected && <div className="wb-doc-empty">从左侧目录选一篇查看正文。</div>}
        {selected && !doc && <div className="wb-doc-empty">加载中…</div>}
        {selected && doc?.empty && <div className="wb-doc-empty">{doc.reason}</div>}
        {selected && doc && !doc.empty && (
          <article data-wb-doc-article="">
            <h1 className="wb-doc-title" data-wb-doc-title="">{doc.title}</h1>
            <div className="wb-doc-meta">
              {[doc.meta?.status, doc.meta?.updated, doc.meta?.category].filter(Boolean).join(' · ')}
            </div>
            {/* renderMarkdown 全量安全口径（转义先行/危险 URL 拒绝/高亮 guard）随 import 带入，
                见本文件头注 R1 取舍清单 1。 */}
            <div className="wb-doc-body" data-wb-doc-body="" onClick={onDocCopy}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(doc.body ?? '') }} />
          </article>
        )}
      </main>
      </div>
    </div>
  )
}
