/**
 * docs.tsx —— 工单台「文档」视图（t260905-06 起；mock v1 版面重做 + KI-070 项目根解析
 * = t260910-10）：docs/ 定稿库 + notes/ 观察窗人读视图。
 *
 * 语义（KI-070 修复 + t260915-10 接壳层 projectKey）：docs tree/doc 按 ?project= 项目根
 * 解析——组件自带 Project 选择器，选择态初值=壳层当前项目（props.projectKey；''=缺省
 * 引擎仓回落，既有语义不删）；mounted 期壳层变更→跟随，但用户手动动过选择器后不再被
 * 壳层冲掉（userTouched guard，spec ②手动优先；重挂载=重新跟随，收敛口径评审已裁）。
 * 切换器与请求源仍同源：请求按本视图选择态显式拼 project=，不用 withProject 隐式上下文
 * （gen1 R1-8 的同源关切保留，仅初值/跟随的来源改为壳层——旧「不继承壳层 viewProject」
 * 裁定随 t260915-10 推翻）。数据源=宿主半
 * GET /sandbar-workbench/api/wf/docs/tree|doc?scope=…[&project=…]（node.ts
 * handleDocsTree/handleDocsDoc）。
 *
 * 版面（mock notes/discussions/260910-docs-view-mock.html 过稿）：顶部条=面包屑 +
 * Project 选择器 + Search；左栏上下分区——上部 Docs/Notes 文件浏览器（分组可折叠），
 * 下部 On this page 当前文档大纲；右栏正文全宽（chip 元信息条：Status/Verified/
 * Category/Updated/Path，Verified=新鲜度时间戳，数据源未就绪显式 'pending' 占位）。
 * 固定 UI 元素英文；正文内容保持原文语言。
 *
 * On this page 锚点机制（C3）：renderMarkdown 不产 heading id——渲染后按 DOM 顺序给
 * 容器内 h2/h3 赋 `doc-h-<i>`（与 outlineFromHtml 提取序号一一对应），点击
 * scrollIntoView 跳转 + IntersectionObserver 滚动高亮（root=本视图滚动容器）。
 *
 * 渲染：markdown 复用 knowledge 插件 renderMarkdown（转义先行/危险 URL 拒绝/高亮
 * guard 全量随 import 带入），经 dangerouslySetInnerHTML 落容器；代码块等宽只作用于
 * 本视图容器（.wb-doc-body），零出厂元素 CSS 压制（t260829-06 纪律）。
 *
 * 资源终态（R1 取舍清单 4）：scope/project/选篇切换与组件卸载时 AbortController.abort
 * 收口 in-flight fetch，IntersectionObserver.disconnect 收口观察（正常/报错/取消
 * 三路径都落定）；目录/正文请求分离，正文懒加载（点目录项才取）。壳层跟随 effect
 * （t260915-10）纯 setState 零新资源零新监听，fetch 回收仍归上述 abort cleanup。
 *
 * 窄栏（R2③）：<=720px 单栏流——选中篇时目录收起、显「← Docs」返回钮；无横向溢出
 * 断言由集成场景锚 .wb-doc-root 容器（V1②口径）。
 *
 * 契约锚（t260905-06 立约，t260910-10 承诺可新增不可移除/改名）：data-wb-docs-root /
 * frame / toc / back / item / scope(-docs/-notes) / skipped / article / title / body。
 * 本票新增：data-wb-doc-topbar / breadcrumb / project(-key) / project-error / search /
 * group-head / group(-collapsed) / outline / outline-item / chips / chip。
 * t260915-10 新增：data-wb-doc-empty-hint（项目语境空目录指引行，spec ③不冒充口径）。
 */
import { useEffect, useRef, useState } from 'react'
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import { DERIVE_TOKENS_CSS } from './theme'
import type { DocTreeGroup, DocsScope } from '../shared/docs-model.ts'
import {
  filterGroups, outlineFromHtml, verifiedChipValue, chipPath, projectOptions,
  emptyGuidance, followProjectKey,
  HEADING_ID_PREFIX, type OutlineEntry, type ProjectOption,
} from './docs-view-model.ts'

const API = '/sandbar-workbench/api/wf/docs'
const PROJECTS_API = '/sandbar-workbench/api/wf/projects'

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

const DOCS_STYLE = `${DERIVE_TOKENS_CSS}
/* 窄可用=容器级响应（@container）：中列被压缩/窄设备都走单栏流，不依赖视口媒体查询
 * （壳在窄视口会卸载本插件槽——视口级断点对「移动窄栏」不可达，探针实证见场景②）。 */
/* 主题（t260907-08，KI-055）：本视图样式全量令牌化（theme.ts 派生令牌体系）。
 * 普通面走 --dsw-derive-*（深浅两档随平台令牌翻转）；代码块/pre/.md-code/.md-cl/
 * .md-copy 与 tok-* 语法高亮属「自备深底的固定暗面板」，走 --dsw-derive-dark-* 家族。 */
.wb-doc-root { container-type: inline-size; height:100%; min-height:0; display:flex; flex-direction:column; }
.wb-doc-topbar { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:8px 12px; border-bottom:1px solid var(--dsw-derive-border,#d0d7de); min-width:0; }
.wb-doc-crumb { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--dsw-derive-muted,#57606a); min-width:0; overflow:hidden; }
.wb-doc-crumb b { color:var(--dsw-derive-fg,#1f2328); font-weight:600; overflow-wrap:anywhere; }
/* 对比度纪律（t260910-10 rework）：分隔符/键名不透明度稀释前景被 contrast 四分支扫描判红
 * （2.16–2.92 < 4.5）——改全强度主题令牌前景，不写死浅灰。 */
.wb-doc-crumb .sep { color:var(--dsw-derive-fg,#1f2328); }
.wb-doc-crumb-root { color:var(--dsw-derive-fg,#1f2328); font-weight:600; }
.wb-doc-proj { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--dsw-derive-muted,#57606a); }
.wb-doc-project-select { border:1px solid var(--dsw-derive-border,#d0d7de); background:var(--dsw-derive-surface,#f6f8fa);
  color:var(--dsw-derive-fg,#1f2328); border-radius:6px; padding:3px 6px; font-size:12px; max-width:200px; }
.wb-doc-search { border:1px solid var(--dsw-derive-border,#d0d7de); background:transparent; color:var(--dsw-derive-fg,#1f2328);
  border-radius:6px; padding:3px 8px; font-size:12px; width:150px; min-width:90px; }
.wb-doc-project-error { font-size:12px; color:var(--dsw-derive-warn,#9a6700); padding:4px 12px; overflow-wrap:anywhere; }
.wb-doc-frame { display:flex; gap:0; flex:1; min-height:0; }
.wb-doc-toc { width:280px; flex:none; overflow:hidden; padding:10px; border-right:1px solid var(--dsw-derive-border,#d0d7de);
  display:flex; flex-direction:column; min-height:0; }
.wb-doc-side { flex:1; overflow-y:auto; min-height:0; }
.wb-doc-scope-row { display:flex; gap:6px; margin-bottom:10px; }
.wb-doc-scope-btn { border:1px solid var(--dsw-derive-border,#d0d7de); background:transparent; color:var(--dsw-derive-fg,#1f2328);
  padding:4px 12px; border-radius:6px; cursor:pointer; font-size:13px; }
.wb-doc-scope-btn.active { background:var(--dsw-derive-accent-solid,#1f6feb); border-color:var(--dsw-derive-accent-solid,#1f6feb); color:var(--dsw-derive-on-solid,#fff); }
.wb-doc-group-head { display:flex; align-items:center; gap:4px; width:100%; text-align:left; border:0; background:transparent;
  color:var(--dsw-derive-muted,#57606a); font-size:12px; margin:12px 0 4px; padding:2px 8px; cursor:pointer; text-transform:none; }
.wb-doc-group-head:hover { color:var(--dsw-derive-fg,#1f2328); }
.wb-doc-group-arrow { display:inline-block; width:12px; }
.wb-doc-item { display:block; width:100%; text-align:left; border:0; background:transparent;
  color:var(--dsw-derive-fg,#1f2328); padding:5px 8px; border-radius:6px; cursor:pointer; font-size:13px;
  line-height:1.5; overflow-wrap:anywhere; }
.wb-doc-item:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-doc-item.active { background:var(--dsw-derive-accent-solid,#1f6feb); color:var(--dsw-derive-on-solid,#fff); }
.wb-doc-skip-note { font-size:12px; color:var(--dsw-derive-warn,#9a6700); margin-top:14px; line-height:1.6; }
.wb-doc-outline { flex:none; max-height:42%; overflow-y:auto; border-top:1px solid var(--dsw-derive-border,#d0d7de); padding-top:8px; margin-top:8px; }
.wb-doc-outline-head { font-size:11px; letter-spacing:.04em; color:var(--dsw-derive-muted,#57606a); margin:0 0 6px; padding:0 8px; }
.wb-doc-outline-list { list-style:none; margin:0; padding:0; }
.wb-doc-outline-item { display:block; width:100%; text-align:left; border:0; background:transparent; color:var(--dsw-derive-fg,#1f2328);
  font-size:12px; line-height:1.5; padding:3px 8px; border-radius:6px; cursor:pointer; overflow-wrap:anywhere; }
.wb-doc-outline-item.lvl3 { padding-left:20px; opacity:.85; }
.wb-doc-outline-item:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-doc-outline-item.active { background:var(--dsw-derive-accent-solid,#1f6feb); color:var(--dsw-derive-on-solid,#fff); }
.wb-doc-outline-empty { font-size:12px; color:var(--dsw-derive-muted,#57606a); padding:2px 8px; }
.wb-doc-main { flex:1; overflow-y:auto; padding:16px 22px; min-width:0; }
.wb-doc-title { font-size:18px; margin:0 0 6px; }
.wb-doc-chips { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 14px; }
.wb-doc-chip { font-size:11px; padding:1px 9px; border-radius:12px; border:1px solid var(--dsw-derive-border,#d0d7de);
  color:var(--dsw-derive-muted,#57606a); background:var(--dsw-derive-surface,#f6f8fa); max-width:100%; overflow-wrap:anywhere; }
.wb-doc-chip .k { color:var(--dsw-derive-fg,#1f2328); margin-right:4px; }
.wb-doc-chip.verified { border-color:var(--dsw-derive-accent-border,#b6e3c6); color:var(--dsw-derive-success,#1a7f37); }
.wb-doc-chip.status { border-color:var(--dsw-derive-warn,#ffd8a8); color:var(--dsw-derive-warn,#9a6700); }
.wb-doc-empty { color:var(--dsw-derive-muted,#57606a); padding:20px 4px; line-height:1.7; }
.wb-doc-back { display:none; border:1px solid var(--dsw-derive-border,#d0d7de); background:transparent; color:var(--dsw-derive-fg,#1f2328);
  padding:4px 12px; border-radius:6px; cursor:pointer; margin-bottom:10px; }
.wb-doc-body { line-height:1.75; overflow-wrap:anywhere; color:var(--dsw-derive-fg,#1f2328); font-size:14px; }
.wb-doc-body h1, .wb-doc-body h2, .wb-doc-body h3 { line-height:1.4; scroll-margin-top:12px; }
.wb-doc-body pre { background:var(--dsw-derive-dark-bg,#1e1e24); border:1px solid var(--dsw-derive-dark-border,#2a2f3a); border-radius:8px;
  padding:10px 12px; overflow-x:auto; }
/* 代码块自持样式（t260905-06 验收 A 附带项）：renderMarkdown 产出的 .md-code/.md-copy/
 * .tok-* 出厂样式由 knowledge 插件全局 CSS 注入供给——本视图自带一份（固定暗面板），
 * knowledge 退役另票时本视图不随之破相。复制行为委托见下方 onDocCopy。 */
.wb-doc-body .md-code { position:relative; margin:10px 0; border:1px solid var(--dsw-derive-dark-border,#2a2f3a);
  border-radius:8px; background:var(--dsw-derive-dark-bg,#1e1e24); overflow:hidden; }
.wb-doc-body .md-code pre { margin:0; border:0; border-radius:0; }
.wb-doc-body .md-cl { position:absolute; top:6px; right:60px; font-size:11px; color:var(--dsw-derive-dark-muted,#b8b8c8);
  background:var(--dsw-derive-dark-surface,#21262d); border-radius:4px; padding:0 8px; line-height:18px; }
.wb-doc-body .md-copy { position:absolute; top:6px; right:8px; font-size:11px; padding:1px 10px;
  line-height:18px; cursor:pointer; border:1px solid var(--dsw-derive-dark-border,#2a2f3a); background:var(--dsw-derive-dark-surface,#21262d);
  color:var(--dsw-derive-dark-fg,#f0f3f6); border-radius:4px; }
.wb-doc-body .md-copy:hover { background:var(--dsw-derive-dark-surface-2,#30363d); color:var(--dsw-derive-on-solid,#fff); }
.wb-doc-body .tok-c { color:var(--dsw-derive-dark-muted,#b8b8c8); font-style:italic; }
.wb-doc-body .tok-s { color:var(--dsw-derive-dark-accent,#7ab8ff); }
.wb-doc-body .tok-k { color:var(--dsw-derive-dark-red,#f87171); font-weight:600; }
.wb-doc-body .tok-n { color:var(--dsw-derive-dark-accent,#7ab8ff); }
.wb-doc-body .tok-v { color:var(--dsw-derive-dark-amber,#ffd166); }
.wb-doc-body pre code, .wb-doc-body code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.wb-doc-body table { border-collapse:collapse; }
.wb-doc-body th, .wb-doc-body td { border:1px solid var(--dsw-derive-border,#d0d7de); padding:4px 8px; }
.wb-doc-body blockquote { margin:10px 0; padding:2px 12px; border-left:3px solid var(--dsw-derive-border,#d0d7de);
  color:var(--dsw-derive-muted,#57606a); }
.wb-doc-body a { color:var(--dsw-derive-accent,#0969da); }
@container (max-width: 720px) {
  .wb-doc-frame { flex-direction:column; }
  .wb-doc-toc { width:100%; border-right:0; max-height:60%; }
  .wb-doc-main { padding:12px; }
  .wb-doc-frame.has-doc .wb-doc-toc { display:none; }
  .wb-doc-frame.has-doc .wb-doc-back { display:inline-block; }
  .wb-doc-search { flex:1; width:auto; }
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

export function DocsSection({ projectKey: shellProjectKey }: { projectKey?: string }) {
  const [scope, setScope] = useState<DocsScope>('docs')
  // 选择态（t260915-10）：初值=壳层当前项目；''=缺省引擎仓（后端 source='default' 回落，
  // 既有语义不删）。userTouched=用户手动动过选择器——其后壳层变更不再冲掉手动选择
  // （跟随 effect 走 followProjectKey 单源判定，docs-view-model UT 真值表=行为断言）。
  const [projectKey, setProjectKey] = useState(shellProjectKey ?? '')
  const userTouched = useRef(false)
  useEffect(() => {
    setProjectKey((cur) => followProjectKey(shellProjectKey, cur, userTouched.current))
  }, [shellProjectKey])
  const [projects, setProjects] = useState<ProjectOption[]>([])
  const [projErr, setProjErr] = useState('')
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [tree, setTree] = useState<TreeResult | null>(null)
  const [treeErr, setTreeErr] = useState('')
  const [selected, setSelected] = useState<string>('')
  const [doc, setDoc] = useState<DocResult | null>(null)
  const [outline, setOutline] = useState<OutlineEntry[]>([])
  const [activeId, setActiveId] = useState('')
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const mainRef = useRef<HTMLElement | null>(null)

  const projQs = projectKey !== '' ? `&project=${encodeURIComponent(projectKey)}` : ''

  // 项目清单（选择器选项；初值不依赖本请求——synthesized 缺省项恒在，
  // 装载失败走显式错误态不静默，方案 gen1 R1-9）。
  useEffect(() => {
    const ac = new AbortController()
    fetch(PROJECTS_API, { signal: ac.signal })
      .then((r) => r.json())
      .then((j) => {
        if (j?.ok) { setProjects(j?.result?.projects ?? []); setProjErr('') }
        else setProjErr(String(j?.error ?? 'response not ok'))
      })
      .catch((err) => { if (!ac.signal.aborted) setProjErr(String(err?.message ?? err)) })
    return () => ac.abort()
  }, [])

  // 目录树：scope/项目切换即重取并清选篇；in-flight 取消（卸载/切换双路径）。
  useEffect(() => {
    const ac = new AbortController()
    setTree(null); setTreeErr(''); setSelected(''); setQuery(''); setCollapsed({})
    fetch(`${API}/tree?scope=${scope}${projQs}`, { signal: ac.signal })
      .then((r) => r.json())
      .then((j) => { setTree(j?.result ?? { empty: true, reason: '响应缺 result', groups: [], skipped: [] }) })
      .catch((err) => { if (!ac.signal.aborted) setTreeErr(String(err?.message ?? err)) })
    return () => ac.abort()
  }, [scope, projectKey])

  // 正文：点目录项才取（懒加载）；切篇/切项目/卸载取消 in-flight。
  useEffect(() => {
    if (!selected) { setDoc(null); setOutline([]); return }
    const ac = new AbortController()
    setDoc(null); setOutline([]); setActiveId('')
    fetch(`${API}/doc?scope=${scope}${projQs}&path=${encodeURIComponent(selected)}`, { signal: ac.signal })
      .then((r) => r.json())
      .then((j) => { setDoc(j?.result ?? { empty: true, reason: '响应缺 result' }) })
      .catch((err) => { if (!ac.signal.aborted) setDoc({ empty: true, reason: String(err?.message ?? err) }) })
    return () => ac.abort()
  }, [scope, projectKey, selected])

  // On this page 锚点（C3）：正文渲染进 DOM 后单遍处理——大纲从渲染产物（容器
  // innerHTML，即 renderMarkdown 产出）提取；按 DOM 顺序给 h2/h3 赋 doc-h-<i>
  // （与 outlineFromHtml 序号一一对应；畸形漏配时按索引兜底，跳转不哑）。
  useEffect(() => {
    const el = bodyRef.current
    if (!el || !doc || doc.empty) { setOutline([]); return }
    const os = outlineFromHtml(el.innerHTML)
    el.querySelectorAll('h2, h3').forEach((h, i) => { h.id = os[i]?.id ?? `${HEADING_ID_PREFIX}${i}` })
    setOutline(os)
  }, [doc, selected])

  // 滚动高亮：IntersectionObserver 以本视图滚动容器为 root；换篇/卸载 disconnect 收口。
  useEffect(() => {
    const mainEl = mainRef.current
    if (!mainEl || outline.length === 0) { setActiveId(''); return }
    const heads = outline.map((o) => document.getElementById(o.id)).filter((h): h is HTMLElement => h !== null)
    const io = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (vis.length > 0) setActiveId(vis[0].target.id)
    }, { root: mainEl, rootMargin: '0px 0px -70% 0px', threshold: 0 })
    heads.forEach((h) => io.observe(h))
    return () => io.disconnect()
  }, [outline, selected])

  const jumpTo = (id: string): void => {
    setActiveId(id)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const visibleGroups = filterGroups(tree?.groups, query)
  // 项目语境空目录指引（t260915-10）：emptyGuidance 对缺省语境/非空返回 ''，既有文案不动。
  const emptyHint = tree?.empty === true ? emptyGuidance(tree.empty, projectKey) : ''
  const docLoaded = doc !== null && !doc.empty
  const crumbTitle = docLoaded && doc.title ? doc.title : selected
  const chips: [string, string, string][] = docLoaded
    ? [
      ['status', 'Status', doc.meta?.status || '—'],
      ['verified', 'Verified', verifiedChipValue(doc.meta)],
      ['category', 'Category', doc.meta?.category || '—'],
      ['updated', 'Updated', doc.meta?.updated || '—'],
      ['path', 'Path', chipPath(scope, selected)],
    ]
    : []

  return (
    // has-doc=已选中篇（窄容器据此收目录显返回钮）——跟随 selected，不写死。
    <div
      className="wb-doc-root" data-wb-docs-root="" data-wb-docs-scope={scope}
      data-wb-docs-selected={selected} data-wb-doc-project-key={projectKey}
    >
      <style>{DOCS_STYLE}</style>
      <header className="wb-doc-topbar" data-wb-doc-topbar="">
        <div className="wb-doc-crumb" data-wb-doc-breadcrumb="">
          <span className="wb-doc-crumb-root">Docs</span>
          <span className="sep">/</span>
          {crumbTitle !== ''
            ? (<><span>{scope}</span><span className="sep">/</span><b>{crumbTitle}</b></>)
            : <b>{scope}</b>}
        </div>
        <label className="wb-doc-proj"><span className="wb-doc-label-word">Project</span>
          <select
            className="wb-doc-project-select" data-wb-doc-project="" aria-label="Project"
            value={projectKey}
            onChange={(e) => { userTouched.current = true; setProjectKey(e.target.value) }}
          >
            {projectOptions(projects).map((o) => (
              <option key={o.key} value={o.key}>{o.label}</option>
            ))}
          </select>
        </label>
        <input
          className="wb-doc-search" data-wb-doc-search="" aria-label="Search"
          placeholder="Search" value={query}
          onChange={(e) => { setQuery(e.target.value) }}
        />
      </header>
      {projErr !== '' && <div className="wb-doc-project-error" data-wb-doc-project-error="">Project list unavailable: {projErr}</div>}
      <div className={`wb-doc-frame ${selected ? 'has-doc' : ''}`} data-wb-docs-frame="">
        <nav className="wb-doc-toc" data-wb-docs-toc="" aria-label="Docs browser">
          <div className="wb-doc-side">
            <div className="wb-doc-scope-row" role="tablist" aria-label="Docs scope">
              <button className={`wb-doc-scope-btn ${scope === 'docs' ? 'active' : ''}`} role="tab"
                aria-selected={scope === 'docs'} data-wb-docs-scope-docs=""
                onClick={() => { setSelected(''); setScope('docs') }}>Docs</button>
              <button className={`wb-doc-scope-btn ${scope === 'notes' ? 'active' : ''}`} role="tab"
                aria-selected={scope === 'notes'} data-wb-docs-scope-notes=""
                onClick={() => { setSelected(''); setScope('notes') }}>Notes</button>
            </div>
            {treeErr !== '' && <div className="wb-doc-empty">目录加载失败：{treeErr}</div>}
            {treeErr === '' && tree === null && <div className="wb-doc-empty">Loading…</div>}
            {tree?.empty === true && <div className="wb-doc-empty">目录为空：{tree.reason}</div>}
            {emptyHint !== '' && <div className="wb-doc-empty" data-wb-doc-empty-hint="">{emptyHint}</div>}
            {visibleGroups.map((g) => {
              const isCollapsed = collapsed[g.dir] === true
              return (
                <div key={g.dir}>
                  <button
                    className="wb-doc-group-head" data-wb-doc-group-head={g.dir}
                    aria-expanded={!isCollapsed} data-wb-doc-group-collapsed={isCollapsed ? 'true' : 'false'}
                    onClick={() => { setCollapsed((c) => ({ ...c, [g.dir]: !c[g.dir] })) }}
                  >
                    <span className="wb-doc-group-arrow">{isCollapsed ? '▸' : '▾'}</span>{g.label}
                  </button>
                  {!isCollapsed && g.files.map((f) => (
                    <button key={f.rel} className={`wb-doc-item ${selected === f.rel ? 'active' : ''}`}
                      data-wb-doc-item={f.rel} onClick={() => setSelected(f.rel)}>{f.title}</button>
                  ))}
                </div>
              )
            })}
            {tree !== null && !tree.empty && query.trim() !== '' && visibleGroups.length === 0 && (
              <div className="wb-doc-empty">No matches.</div>
            )}
            {tree !== null && !tree.empty && tree.skipped.length > 0 && query.trim() === '' && (
              <div className="wb-doc-skip-note" data-wb-docs-skipped="">
                未入视图 {tree.skipped.length} 个文件（{tree.skipped.map((s) => `${s.path}：${s.reason}`).join('；')}）
              </div>
            )}
          </div>
          <div className="wb-doc-outline" data-wb-doc-outline="">
            <div className="wb-doc-outline-head">On this page</div>
            {outline.length > 0 ? (
              <ul className="wb-doc-outline-list">
                {outline.map((o) => (
                  <li key={o.id}>
                    <button
                      className={`wb-doc-outline-item ${o.level === 3 ? 'lvl3' : ''} ${activeId === o.id ? 'active' : ''}`}
                      data-wb-doc-outline-item={o.id}
                      onClick={() => { jumpTo(o.id) }}
                    >{o.text}</button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="wb-doc-outline-empty">—</div>
            )}
          </div>
        </nav>
        <main className="wb-doc-main" data-wb-docs-main="" ref={mainRef}>
          <button className="wb-doc-back" data-wb-docs-back="" onClick={() => setSelected('')}>← Docs</button>
          {selected === '' && <div className="wb-doc-empty">Select a document from the list.</div>}
          {selected !== '' && !docLoaded && <div className="wb-doc-empty">Loading…</div>}
          {selected !== '' && doc !== null && doc.empty && <div className="wb-doc-empty">{doc.reason}</div>}
          {docLoaded && (
            <article data-wb-doc-article="">
              <h1 className="wb-doc-title" data-wb-doc-title="">{doc!.title}</h1>
              <div className="wb-doc-chips" data-wb-doc-chips="">
                {chips.map(([name, label, value]) => (
                  <span key={name} className={`wb-doc-chip ${name}`} data-wb-doc-chip={name}>
                    {/* 键/值各自成元素：固定英文键=独立文本（场景 getByText exact 可达），
                        值=叶元素（pending 占位/真值可被叶级断言扫到）。 */}
                    <span className="k">{label}</span><span className="v">{value}</span>
                  </span>
                ))}
              </div>
              {/* renderMarkdown 全量安全口径（转义先行/危险 URL 拒绝/高亮 guard）随 import 带入，
                  见本文件头注渲染节。 */}
              <div
                className="wb-doc-body" data-wb-doc-body="" ref={bodyRef} onClick={onDocCopy}
                dangerouslySetInnerHTML={{ __html: renderMarkdown(doc!.body ?? '') }}
              />
            </article>
          )}
        </main>
      </div>
    </div>
  )
}
