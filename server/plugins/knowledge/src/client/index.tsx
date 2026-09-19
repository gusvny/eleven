/**
 * sandbar-knowledge —— docs 知识库 · 浏览器半。
 *
 * 槽位契约沿革：本插件曾向会话视图环注册页签 + `conversationViews.register`
 * （260823 前）；260823 起知识库 UI 移到工单台侧栏中栏、由 sandbar-workbench
 * 直接 import 本插件的 KnowledgeSection 渲染，apply 改为空操作——插件对
 * conversationViews/uiConversation 零消费、零注册。
 *
 * 功能（工单 t260821-09 → t260821-10 M2/M3）：
 *   ① 列表按分类（design/content/ops/reference）/标签/状态过滤；
 *   ② 关键词检索（标题 + frontmatter tags）；
 *   ③ 读全文（点条目中栏内嵌 list→doc 两态切换）：markdown render（HTML，非 raw；表格/代码块
 *      高亮+复制/链接/列表），可切 raw 查看原文；头部「← 返回」按钮回到列表，筛选条件不丢；
 *   ④ review（提示缺 frontmatter / status=deprecated / updated 过旧，三组清单）；
 *   ⑤ block 级 diff 审阅（t260821-14）：细粒度 block（标题/段落/列表项/表格行/
 *      代码块…），主视图=渲染后 markdown（未变渲染新文本/新增绿底/删除红底/
 *      修改上下红绿，表格行单元格级对齐），raw 行级 ops 为可切换次要视图（只留
 *      变更行）；逐块 approve/reject/注释按稳定 block_key 持久化——进入 diff
 *      自动回填最近一轮，「保存 review」显式落盘（含整篇结论），保存后生成
 *      可贴工单的 rework 指令；内容变了 key 失效的旧意见标「已过期」不回填。
 *
 * 数据通道：同源 fetch 打宿主半（../node.ts）挂在 dsh webServer 上的
 * /sandbar-knowledge/api/*；写操作只有 review/save（宿主半落 docs/reviews/ +
 * server/admin.log 审计）。
 *
 * 【inject 收窄史（t260916-26）】曾声明 `inject = ['slots','conversationViews']`；
 * dsh 0.1.5 起 conversationViews 服务随 dsh-client-runtime 整包移除，声明即
 * 永久 pending（UI 报 Failed to load plugins）。现改从 ./inject-contract 导入
 * CLIENT_INJECT（=['slots']，双版本稳定白名单），同一 bundle 在 0.1.1/0.1.5
 * 都能激活；本插件无页签注册行为（apply 空操作），收窄零行为差异。
 */

import { useEffect, useMemo, useState } from 'react'
import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
// 空具名 type import：把 dsh-client-ui-conversation 的 SlotMap 扩展（conversation.view 槽声明）
// 带进 tsc 检查环境；纯类型副作用，构建时被剥离，不进 bundle。
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import { CLIENT_INJECT } from './inject-contract'
import { renderMarkdown } from './markdown'
import { splitCells } from '../shared/blocks'

export const name = 'sandbar-knowledge/client'
export const inject = CLIENT_INJECT

/* ---------------------------------------------------------------- 样式 */

const CSS = `
.kb-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:#f6f8fa;color:#1f2328;min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:14px;height:100%;overflow-y:auto;font-size:13px;line-height:1.55}
.kb-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid #d0d7de;padding-bottom:12px;flex-wrap:wrap}
.kb-title{font-size:20px;font-weight:600;color:#1f2328}
.kb-sub{font-size:12px;color:#57606a}
.kb-spacer{flex:1}
.kb-err{background:#ffebe9;border:1px solid #ff9b9b;color:#cf222e;border-radius:6px;
  padding:8px 12px;font-size:12px;white-space:pre-wrap}
.kb-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.kb-select{font:inherit;font-size:13px;background:#ffffff;color:#1f2328;border:1px solid #d0d7de;
  border-radius:6px;padding:5px 10px}
.kb-select:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.kb-input{font:inherit;font-size:13px;background:#ffffff;color:#1f2328;border:1px solid #d0d7de;
  border-radius:6px;padding:5px 10px;min-width:220px}
.kb-input:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.kb-btn{font:inherit;font-size:13px;padding:5px 16px;border-radius:6px;cursor:pointer;
  border:1px solid #d0d7de;background:#ffffff;color:#1f2328;transition:background .12s}
.kb-btn:hover{background:#f6f8fa}
.kb-btn:disabled{opacity:.5;cursor:default}
.kb-btn-blue{border-color:#96c8f2;color:#0969da;background:#ddf4ff}
.kb-btn-active{border-color:#0969da;color:#ffffff;background:#0969da}
.kb-table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;border:1px solid #d0d7de;
  border-radius:8px;background:#ffffff;box-shadow:0 1px 3px rgba(31,35,40,.06);font-size:13px;overflow:hidden}
.kb-table thead th{position:sticky;top:0;z-index:1;background:#f6f8fa;color:#57606a;font-weight:600;
  text-align:left;padding:9px 12px;border-bottom:1px solid #d0d7de;font-size:12px;white-space:nowrap}
.kb-table tbody td{padding:9px 12px;border-bottom:1px solid #e8ebef;vertical-align:middle}
.kb-table tbody tr{cursor:pointer}
.kb-table tbody tr:hover{background:#f6f8fa}
.kb-table tbody tr:last-child td{border-bottom:none}
.kb-cat{font-size:12px;color:#57606a;background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;
  padding:1px 8px;white-space:nowrap}
.kb-cat[data-cat=design]{background:#ddf4ff;color:#0550ae;border-color:#96c8f2}
.kb-cat[data-cat=content]{background:#dafbe1;color:#116329;border-color:#7dd9a0}
.kb-cat[data-cat=ops]{background:#fff8c5;color:#7d4e00;border-color:#eac54f}
.kb-cat[data-cat=reference]{background:#fbefff;color:#6f42c1;border-color:#d3b9f0}
.kb-tag{font-size:11px;color:#57606a;background:#f6f8fa;border:1px solid #e8ebef;border-radius:6px;
  padding:1px 6px;margin-right:4px}
.kb-title-cell{font-weight:600;color:#0969da}
.kb-path{color:#8c959f;font-size:11px}
.kb-status{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:500}
.kb-status[data-status=active]{background:#dafbe1;color:#116329}
.kb-status[data-status=draft]{background:#fff8c5;color:#7d4e00}
.kb-status[data-status=deprecated]{background:#ffebe9;color:#cf222e}
.kb-empty{font-size:12px;color:#57606a;padding:12px 0}
.kb-back-btn{font:inherit;font-size:13px;padding:3px 12px;border-radius:6px;cursor:pointer;
  border:1px solid #d0d7de;background:#ffffff;color:#1f2328;transition:background .12s}
.kb-back-btn:hover{background:#f6f8fa}
.kb-body{font-size:13px;line-height:1.9;color:#1f2328;white-space:pre-wrap;word-break:break-word;
  border:1px solid #e8ebef;border-radius:8px;padding:14px 16px;background:#fbfcfd;margin:0;overflow:auto}
.kb-review-box{border:1px solid #d0d7de;border-radius:8px;background:#ffffff;padding:12px 14px;display:flex;
  flex-direction:column;gap:8px}
.kb-review-title{font-size:14px;font-weight:600;color:#1f2328;border-bottom:1px solid #e8ebef;padding-bottom:6px}
.kb-review-item{color:#0969da;cursor:pointer}
.kb-review-item:hover{text-decoration:underline}
.kb-review-empty{color:#57606a;font-size:12px}
.kb-warn{font-size:12px;color:#bf8700;background:#fff8c5;border:1px solid #eac54f;border-radius:6px;padding:5px 10px}
/* markdown render */
.kb-md{font-size:13.5px;line-height:1.7;color:#1f2328;word-break:break-word}
.kb-md h1,.kb-md h2,.kb-md h3,.kb-md h4,.kb-md h5,.kb-md h6{margin:18px 0 8px;font-weight:600;line-height:1.3}
.kb-md h1{font-size:22px;border-bottom:1px solid #d8dee4;padding-bottom:6px}
.kb-md h2{font-size:18px;border-bottom:1px solid #d8dee4;padding-bottom:4px}
.kb-md h3{font-size:15px}
.kb-md h4,.kb-md h5,.kb-md h6{font-size:14px}
.kb-md p{margin:6px 0}
.kb-md a{color:#0969da;text-decoration:none}
.kb-md a:hover{text-decoration:underline}
.kb-md ul,.kb-md ol{margin:6px 0;padding-left:22px}
.kb-md li{margin:2px 0}
.kb-md blockquote{margin:8px 0;padding:2px 12px;border-left:4px solid #d0d7de;color:#57606a;background:#f6f8fa}
.kb-md code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  background:#eff1f3;border-radius:4px;padding:1px 5px}
.kb-md table{border-collapse:collapse;margin:10px 0;max-width:100%;display:block;overflow-x:auto}
.kb-md table th,.kb-md table td{border:1px solid #d0d7de;padding:6px 12px;text-align:left}
.kb-md table th{background:#f6f8fa;font-weight:600}
.kb-md hr{border:none;border-top:1px solid #d8dee4;margin:14px 0}
.kb-md img{max-width:100%}
.md-code{position:relative;margin:10px 0;border:1px solid #d0d7de;border-radius:8px;background:#f6f8fa;overflow:hidden}
.md-code pre{margin:0;padding:12px 14px;overflow-x:auto}
.md-code pre code{background:none;padding:0;font-size:12px;line-height:1.6;color:#1f2328}
.md-cl{position:absolute;top:6px;right:60px;font-size:11px;color:#57606a;background:#eaeef2;
  border-radius:4px;padding:0 8px;line-height:18px}
.md-copy{position:absolute;top:6px;right:8px;font-size:11px;padding:1px 10px;line-height:18px;cursor:pointer;
  border:1px solid #d0d7de;background:#ffffff;color:#57606a;border-radius:4px}
.md-copy:hover{background:#eaeef2;color:#1f2328}
.tok-c{color:#6e7781;font-style:italic}
.tok-s{color:#0a3069}
.tok-k{color:#cf222e;font-weight:600}
.tok-n{color:#0550ae}
.tok-v{color:#953800}
/* block diff review */
.kb-diff-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kb-diff-sum{font-size:12px;color:#57606a;display:flex;gap:14px;flex-wrap:wrap}
.d-block{border:1px solid #d0d7de;border-radius:8px;background:#ffffff;overflow:hidden}
.d-head{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#f6f8fa;border-bottom:1px solid #e8ebef;flex-wrap:wrap}
.d-head-t{font-weight:600;font-size:13px;color:#1f2328}
.d-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap}
.d-badge[data-s=added]{background:#dafbe1;color:#116329}
.d-badge[data-s=removed]{background:#ffebe9;color:#cf222e}
.d-badge[data-s=modified]{background:#fff8c5;color:#7d4e00}
.d-badge[data-s=unchanged]{background:#f6f8fa;color:#57606a}
.d-ops{padding:6px 0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.6}
.d-line{padding:1px 12px;white-space:pre-wrap;word-break:break-all}
.d-ctx{color:#1f2328}
.d-add{background:#dafbe1;color:#116329}
.d-del{background:#ffebe9;color:#cf222e}
.d-mod{background:#fff8c5}
.d-mod .d-del{background:none;text-decoration:line-through;color:#7d4e00}
.d-mod .d-add{background:none;color:#116329;font-weight:600}
.d-actions{display:flex;gap:8px;align-items:center;padding:8px 12px;border-top:1px solid #e8ebef;flex-wrap:wrap}
.d-btn{font-size:12px;padding:2px 12px;border-radius:6px;cursor:pointer;border:1px solid #d0d7de;background:#fff;color:#1f2328}
.d-btn:hover{background:#f6f8fa}
.d-btn-ap{border-color:#7dd9a0;color:#116329}
.d-btn-ap.on{background:#116329;color:#fff}
.d-btn-rj{border-color:#ff9b9b;color:#cf222e}
.d-btn-rj.on{background:#cf222e;color:#fff}
.d-cmt{width:100%;min-height:52px;font:inherit;font-size:12px;border:1px solid #d0d7de;border-radius:6px;padding:6px 10px}
.d-expand{font-size:11px;color:#0969da;cursor:pointer;background:none;border:none}
/* 渲染态 diff 主视图 */
.d-md{padding:8px 14px;font-size:13px}
.d-md-add{background:#f0fff4;border-left:4px solid #2da44e}
.d-md-del{background:#fff5f5;border-left:4px solid #cf222e}
.d-md-old{background:#fff5f5;border-left:4px solid #ff9b9b}
.d-md-new{background:#f0fff4;border-left:4px solid #7dd9a0}
.d-md-tag{font-size:11px;font-weight:600;color:#57606a;letter-spacing:1px}
.d-md-old .d-md-tag{color:#cf222e}
.d-md-new .d-md-tag{color:#116329}
.d-md-half{border-bottom:1px dashed #e8ebef}
.d-type{font-size:11px;color:#8c959f;border:1px solid #e8ebef;border-radius:6px;padding:0 6px;white-space:nowrap}
/* 表格行单元格级对齐 */
.d-cells{border-collapse:collapse;margin:8px 12px;font-size:12px;max-width:calc(100% - 24px);display:block;overflow-x:auto}
.d-cells th,.d-cells td{border:1px solid #d0d7de;padding:4px 10px;text-align:left;white-space:pre-wrap;word-break:break-word}
.d-cells th{background:#f6f8fa;color:#57606a;font-weight:600}
.cell-old-chg{background:#ffebe9;color:#cf222e;text-decoration:line-through}
.cell-new-chg{background:#dafbe1;color:#116329;font-weight:600}
/* review 持久化 */
.d-conclude{font:inherit;font-size:12px;border:1px solid #d0d7de;border-radius:6px;padding:3px 8px;background:#fff}
.kb-rework{border:1px solid #d0d7de;border-radius:8px;background:#fbfcfd;padding:10px 14px;display:flex;flex-direction:column;gap:8px}
.kb-rework pre{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  line-height:1.6;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto}
.kb-expired{border:1px dashed #d0d7de;border-radius:8px;padding:8px 12px;color:#57606a;font-size:12px}
.kb-expired-item{padding:4px 0;border-bottom:1px solid #f0f2f5}
.kb-expired-item:last-child{border-bottom:none}
.d-badge[data-s=expired]{background:#f6f8fa;color:#8c959f;border:1px dashed #d0d7de}
`

const CSS_TAG_ID = 'sandbar-knowledge/KnowledgeSection.css'
if (typeof document !== 'undefined'
  && document.querySelector('style[data-plugin-css=' + JSON.stringify(CSS_TAG_ID) + ']') === null) {
  const tag = document.createElement('style')
  tag.dataset.plugin = 'sandbar-knowledge'
  tag.dataset.pluginCss = CSS_TAG_ID
  tag.textContent = CSS
  document.head.appendChild(tag)
}

/* -------------------------------------------------------------- 数据通道 */

const API = '/sandbar-knowledge/api'

/** 多项目化（260823）：当前视图的项目 key，KnowledgeSection 挂载/切换时从 prop 设置。
 *  中列同一时刻只挂一个视图，模块单态安全。空串=不拼参（host 会 400，UI 先显占位）。 */
let viewProject = ''

/** 统一拼 ?project=（host 六条路由全部必传）。 */
function withProject(path: string): string {
  if (!viewProject) return path
  return path + (path.includes('?') ? '&' : '?') + 'project=' + encodeURIComponent(viewProject)
}

async function apiGet(path: string): Promise<any> {
  const res = await fetch(withProject(path))
  return res.json()
}

async function apiPost(path: string, body: unknown): Promise<any> {
  const res = await fetch(withProject(path), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
}

/* ---------------------------------------------------------------- 类型 */

interface DocEntry {
  path: string
  file: string
  title: string
  category: string
  tags: string[]
  status: string
  updated: string
  has_frontmatter: boolean
}

interface IndexData {
  /** 项目无 docs/index.json 时 host 回 {empty:true, reason}（人话降级）。 */
  empty?: boolean
  reason?: string
  generated_at: string
  total: number
  categories: string[]
  docs: DocEntry[]
  review: { missing_frontmatter: string[]; deprecated: string[]; stale: string[] }
}

interface DiffOp { k: 'ctx' | 'add' | 'del' | 'mod'; a?: string; b?: string }
interface DiffBlock {
  key: string
  type: string
  status: 'added' | 'removed' | 'modified' | 'unchanged'
  summary: string
  level: number
  oldText?: string
  newText?: string
  ops?: DiffOp[]
}
interface DiffData { path: string; base: string; hasBase: boolean; changed: boolean; blocks: DiffBlock[] }

interface ReviewBlockEntry {
  block_key: string; summary: string; type: string; status: string
  decision?: 'approve' | 'reject'; comment?: string
}
interface ReviewRound {
  base: string; ts: number; reviewer: string
  conclude: 'approved' | 'changes-requested' | 'in-progress'
  blocks: ReviewBlockEntry[]
}
interface ReviewFile { path: string; rounds: ReviewRound[] }

interface BlockReview { decision?: 'approve' | 'reject'; comment?: string; open?: boolean }

/** 去掉正文前 YAML frontmatter 块（读全文展示用，正文保持原样）。 */
function stripFrontmatter(md: string): string {
  if (!md.startsWith('---\n')) return md
  const lines = md.split('\n')
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === '---') {
      return lines.slice(i + 1).join('\n').replace(/^\n+/, '')
    }
  }
  return md
}

const TYPE_LABEL: Record<string, string> = {
  frontmatter: 'frontmatter', heading: '标题', paragraph: '段落', 'list-item': '列表项',
  'table-head': '表头', 'table-row': '表格行', code: '代码块', quote: '引用', image: '图片', hr: '分隔线',
}

const STATUS_LABEL: Record<string, string> = { added: '新增', removed: '删除', modified: '修改', unchanged: '未变' }

const CONCLUDE_LABEL: Record<string, string> = {
  approved: 'approved（通过）', 'changes-requested': 'changes-requested（要求修改）', 'in-progress': 'in-progress（审阅中）',
}

/** 生成可贴进工单的 rework 指令（驳回块清单+注释+文档路径+base）。 */
function buildReworkMd(path: string, diff: DiffData, conclude: string, blocks: ReviewBlockEntry[], runId: string): string {
  const rejected = blocks.filter(b => b.decision === 'reject')
  const lines: string[] = [
    '## rework 指令（知识库 review）',
    '',
    `- 文档：docs/${path}`,
    `- base：${diff.base}`,
    `- 整篇结论：${conclude}`,
    `- review run-id：${runId}`,
    '',
  ]
  if (rejected.length === 0) {
    lines.push('无驳回块。')
  } else {
    lines.push(`### 驳回块清单（${rejected.length}）`, '')
    rejected.forEach((b, i) => {
      lines.push(`${i + 1}. [${TYPE_LABEL[b.type] ?? b.type} / ${STATUS_LABEL[b.status] ?? b.status}] ${b.summary}`)
      if (b.comment !== undefined && b.comment !== '') lines.push(`   - 注释：${b.comment}`)
      lines.push(`   - block_key：\`${b.block_key}\``)
    })
  }
  return lines.join('\n')
}

/* -------------------------------------------------------------- 分区本体 */

export function KnowledgeSection({ projectKey }: { projectKey?: string }) {
  const [data, setData] = useState<IndexData | undefined>(undefined)
  const [error, setError] = useState('')
  const [filterCat, setFilterCat] = useState('')
  const [filterTag, setFilterTag] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [kw, setKw] = useState('')
  const [showReview, setShowReview] = useState(false)
  const [doc, setDoc] = useState<{ path: string; title: string; content: string } | undefined>(undefined)
  const [docLoading, setDocLoading] = useState(false)
  const [view, setView] = useState<'render' | 'raw' | 'diff'>('render')

  // block diff 审阅态
  const [diff, setDiff] = useState<DiffData | undefined>(undefined)
  const [diffLoading, setDiffLoading] = useState(false)
  const [diffBase, setDiffBase] = useState('HEAD')
  const [reviews, setReviews] = useState<Record<string, BlockReview>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [rawOps, setRawOps] = useState<Record<string, boolean>>({})
  // review 持久化：已存轮次 / 过期意见 / 保存态 / rework 指令
  const [reviewInfo, setReviewInfo] = useState<{ rounds: number; latest?: ReviewRound } | undefined>(undefined)
  const [expired, setExpired] = useState<ReviewBlockEntry[]>([])
  const [conclude, setConclude] = useState<'approved' | 'changes-requested' | 'in-progress'>('in-progress')
  const [saveState, setSaveState] = useState<{ saving?: boolean; runId?: string; error?: string }>({})
  const [reworkMd, setReworkMd] = useState<string | undefined>(undefined)

  async function reload(): Promise<void> {
    try {
      const r = await apiGet(`${API}/index`)
      if (r?.ok !== true) throw new Error(r?.error ?? '知识库索引加载失败')
      setData(r.result as IndexData)
      setError('')
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    }
  }

  async function openDoc(path: string, title: string): Promise<void> {
    setDocLoading(true)
    setDoc({ path, title, content: '' })
    setView('render')
    setDiff(undefined)
    setReviews({})
    try {
      const r = await apiGet(`${API}/doc?path=${encodeURIComponent(path)}`)
      if (r?.ok !== true) throw new Error(r?.error ?? '文档读取失败')
      setDoc({ path, title, content: stripFrontmatter(String(r.result?.content ?? '')) })
    } catch (err) {
      setDoc({ path, title, content: `（读取失败：${String(err instanceof Error ? err.message : err)}）` })
    } finally {
      setDocLoading(false)
    }
  }

  async function refresh(): Promise<void> {
    setError('')
    try {
      const r = await apiGet(`${API}/refresh`)
      if (r?.ok !== true) throw new Error(r?.error ?? '索引重建失败')
      setData(r.result as IndexData)
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    }
  }

  async function loadDiff(): Promise<void> {
    if (!doc) return
    setDiffLoading(true)
    setReviews({})
    setExpired([])
    setReworkMd(undefined)
    setSaveState({})
    try {
      const r = await apiGet(`${API}/diff?path=${encodeURIComponent(doc.path)}&base=${encodeURIComponent(diffBase)}`)
      if (r?.ok !== true) throw new Error(r?.error ?? 'diff 读取失败')
      const d = r.result as DiffData
      setDiff(d)
      // 自动加载已存 review：按 block_key 回填最近一轮的 decision/comment；
      // 当前 diff 里已不存在的 key → 「已过期」不回填。
      try {
        const rv = await apiGet(`${API}/review?path=${encodeURIComponent(doc.path)}`)
        if (rv?.ok === true) {
          const file = rv.result as ReviewFile
          const latest = file.rounds.length > 0 ? file.rounds[file.rounds.length - 1] : undefined
          setReviewInfo({ rounds: file.rounds.length, latest })
          if (latest !== undefined) {
            setConclude(latest.conclude)
            const currentKeys = new Set(d.blocks.map(b => b.key))
            const backfill: Record<string, BlockReview> = {}
            const stale: ReviewBlockEntry[] = []
            for (const eb of latest.blocks) {
              if (currentKeys.has(eb.block_key)) {
                backfill[eb.block_key] = { decision: eb.decision, comment: eb.comment }
              } else {
                stale.push(eb)
              }
            }
            setReviews(backfill)
            setExpired(stale)
          }
        }
      } catch {
        /* review 读取失败不阻塞 diff 审阅 */
      }
    } catch (err) {
      setDiff(undefined)
      setError(`block diff 失败：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setDiffLoading(false)
    }
  }

  /** 保存 review（显式落盘一轮），成功后生成 rework 指令。 */
  async function saveReview(): Promise<void> {
    if (!doc || !diff) return
    setSaveState({ saving: true })
    setReworkMd(undefined)
    try {
      const blocks: ReviewBlockEntry[] = diff.blocks
        .filter(b => b.status !== 'unchanged')
        .map(b => ({
          block_key: b.key,
          summary: b.summary,
          type: b.type,
          status: b.status,
          decision: reviews[b.key]?.decision,
          comment: reviews[b.key]?.comment,
        }))
      const r = await apiPost(`${API}/review/save`, {
        path: doc.path, base: diff.base, conclude, reviewer: 'user', blocks,
      })
      if (r?.ok !== true) throw new Error(r?.error ?? '保存失败')
      setSaveState({ runId: String(r.run_id ?? '') })
      setReviewInfo(prev => ({ rounds: (prev?.rounds ?? 0) + 1, latest: r.result?.round as ReviewRound }))
      setReworkMd(buildReworkMd(doc.path, diff, conclude, blocks, String(r.run_id ?? '')))
    } catch (err) {
      setSaveState({ error: String(err instanceof Error ? err.message : err) })
    }
  }

  // 多项目化（260823）：项目 key 落模块持有量（apiGet/apiPost 统一拼参）并重拉；
  // 声明在初始加载 effect 之前（effect 按声明顺序执行）。切项目清详情/审阅态。
  useEffect(() => {
    viewProject = projectKey ?? ''
    setData(undefined)
    setDoc(undefined)
    setDiff(undefined)
    setReviewInfo(undefined)
    if (viewProject) void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectKey])

  useEffect(() => { void reload() }, [])

  // 文档内容区上的复制按钮委托（renderMarkdown 产出 .md-copy 按钮）。
  function onDocClick(e: React.MouseEvent): void {
    const btn = (e.target as HTMLElement).closest('.md-copy') as HTMLElement | null
    if (!btn) return
    const code = btn.getAttribute('data-code') ?? ''
    try {
      void navigator.clipboard?.writeText(decodeURIComponent(code))
    } catch {
      /* 剪贴板不可用时静默 */
    }
  }

  const allTags = useMemo(() => {
    const s = new Set<string>()
    for (const d of data?.docs ?? []) for (const t of d.tags) s.add(t)
    return [...s].sort()
  }, [data])

  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase()
    return (data?.docs ?? []).filter(d => {
      if (filterCat !== '' && d.category !== filterCat) return false
      if (filterTag !== '' && !d.tags.includes(filterTag)) return false
      if (filterStatus !== '' && d.status !== filterStatus) return false
      if (q !== '') {
        const hay = (d.title + ' ' + d.tags.join(' ')).toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    }).sort((a, b) => a.category.localeCompare(b.category) || a.path.localeCompare(b.path))
  }, [data, filterCat, filterTag, filterStatus, kw])

  const review = data?.review

  function setReview(key: string, patch: Partial<BlockReview>): void {
    setReviews(prev => ({ ...prev, [key]: { ...prev[key], ...patch } }))
  }

  /** raw 行级次要视图：只留变更行（ctx 噪音去掉）。 */
  function renderOps(ops: DiffOp[]): React.ReactNode {
    const changed = ops.filter(op => op.k !== 'ctx')
    if (changed.length === 0) return <div className="d-line d-ctx">（行级无差异：仅块级别/格式变化）</div>
    return changed.map((op, i) => {
      if (op.k === 'add') return <div key={i} className="d-line d-add">+ {op.b ?? ''}</div>
      if (op.k === 'del') return <div key={i} className="d-line d-del">- {op.a ?? ''}</div>
      return (
        <div key={i} className="d-line d-mod">
          <div className="d-del">- {op.a ?? ''}</div>
          <div className="d-add">+ {op.b ?? ''}</div>
        </div>
      )
    })
  }

  /** 表格行修改：单元格级对齐（同列对比，变格高亮）。 */
  function renderCellDiff(oldLine: string, newLine: string): React.ReactNode {
    const oc = splitCells(oldLine)
    const nc = splitCells(newLine)
    const cols = Math.max(oc.length, nc.length)
    return (
      <table className="d-cells">
        <thead><tr><th style={{ width: 40 }}></th>{Array.from({ length: cols }, (_, c) => <th key={c}>列 {c + 1}</th>)}</tr></thead>
        <tbody>
          <tr>
            <th>旧</th>
            {Array.from({ length: cols }, (_, c) => {
              const chg = (oc[c] ?? '') !== (nc[c] ?? '')
              return <td key={c} className={chg ? 'cell-old-chg' : ''}>{oc[c] ?? '—'}</td>
            })}
          </tr>
          <tr>
            <th>新</th>
            {Array.from({ length: cols }, (_, c) => {
              const chg = (oc[c] ?? '') !== (nc[c] ?? '')
              return <td key={c} className={chg ? 'cell-new-chg' : ''}>{nc[c] ?? '—'}</td>
            })}
          </tr>
        </tbody>
      </table>
    )
  }

  /** 渲染态 diff 主视图：未变渲染新文本；新增绿底；删除红底；修改上下红/绿。 */
  function renderBlockBody(b: DiffBlock): React.ReactNode {
    if (b.status === 'unchanged') {
      return <div className="d-md kb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.newText ?? '') }} />
    }
    if (b.status === 'added') {
      return <div className="d-md d-md-add kb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.newText ?? '') }} />
    }
    if (b.status === 'removed') {
      return <div className="d-md d-md-del kb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.oldText ?? '') }} />
    }
    // modified：表格行走单元格级对齐，其余上下 旧渲染（红调）/新渲染（绿调）
    if (b.type === 'table-row') {
      return renderCellDiff(b.oldText ?? '', b.newText ?? '')
    }
    return (
      <>
        <div className="d-md d-md-old d-md-half kb-md">
          <div className="d-md-tag">旧</div>
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(b.oldText ?? '') }} />
        </div>
        <div className="d-md d-md-new kb-md">
          <div className="d-md-tag">新</div>
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(b.newText ?? '') }} />
        </div>
      </>
    )
  }

  const diffSummary = diff !== undefined ? {
    added: diff.blocks.filter(b => b.status === 'added').length,
    removed: diff.blocks.filter(b => b.status === 'removed').length,
    modified: diff.blocks.filter(b => b.status === 'modified').length,
    unchanged: diff.blocks.filter(b => b.status === 'unchanged').length,
    approved: Object.values(reviews).filter(r => r.decision === 'approve').length,
    rejected: Object.values(reviews).filter(r => r.decision === 'reject').length,
  } : undefined

  if (!projectKey) {
    return (
      <div className="kb-root">
        <div style={{ padding: 32, color: 'var(--dsw-alias-label-secondary, #888)', fontSize: 13 }}>
          从左侧项目行点 📖 图标打开该项目的知识库。
        </div>
      </div>
    )
  }

  if (data?.empty) {
    return (
      <div className="kb-root">
        <div className="kb-head">
          <span className="kb-title">知 识 库</span>
          <span className="kb-sub">项目 {projectKey}</span>
        </div>
        <div style={{ padding: 32, color: 'var(--dsw-alias-label-secondary, #888)', fontSize: 13 }}>
          {data.reason ?? '该项目还没有 docs 知识库。'}
        </div>
      </div>
    )
  }

  return (
    <div className="kb-root">
      {doc === undefined ? (
        /* ---------- list 态：文档列表 ---------- */
        <>
          <div className="kb-head">
            <span className="kb-title">知 识 库</span>
            <span className="kb-sub">docs 四分类 · 共 {data?.total ?? '…'} 篇 · 索引 {data?.generated_at ?? '…'}</span>
            <span className="kb-spacer" />
            <button className="kb-btn" onClick={() => { setShowReview(v => !v) }}>
              {showReview ? '收起 review' : 'review'}
              {(review && (review.missing_frontmatter.length + review.deprecated.length + review.stale.length) > 0)
                ? `（${review.missing_frontmatter.length + review.deprecated.length + review.stale.length}）` : ''}
            </button>
            <button className="kb-btn kb-btn-blue" onClick={() => { void refresh() }}>重建索引</button>
          </div>

          {error !== '' && <div className="kb-err">{error}{'\n'}（知识库 API 未挂载？headless profile 无 webServer。）</div>}

          {showReview && review !== undefined && (
            <div className="kb-review-box">
              <div className="kb-review-title">review（frontmatter 完整性 / 时效性）</div>
              <div>
                <span className="kb-sub">缺 frontmatter（{review.missing_frontmatter.length}）：</span>
                {review.missing_frontmatter.length === 0
                  ? <span className="kb-review-empty">无</span>
                  : review.missing_frontmatter.map(p => (
                    <div key={p} className="kb-review-item" onClick={() => { void openDoc(p, p) }}>{p}</div>
                  ))}
              </div>
              <div>
                <span className="kb-sub">status=deprecated（{review.deprecated.length}）：</span>
                {review.deprecated.length === 0
                  ? <span className="kb-review-empty">无</span>
                  : review.deprecated.map(p => (
                    <div key={p} className="kb-review-item" onClick={() => { void openDoc(p, p) }}>{p}</div>
                  ))}
              </div>
              <div>
                <span className="kb-sub">updated 过旧（{'>'}180 天，{review.stale.length}）：</span>
                {review.stale.length === 0
                  ? <span className="kb-review-empty">无</span>
                  : review.stale.map(p => (
                    <div key={p} className="kb-review-item" onClick={() => { void openDoc(p, p) }}>{p}</div>
                  ))}
              </div>
            </div>
          )}

          <div className="kb-filters">
            <select className="kb-select" value={filterCat} onChange={e => setFilterCat(e.target.value)}>
              <option value="">分类：全部</option>
              {(data?.categories ?? []).map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select className="kb-select" value={filterTag} onChange={e => setFilterTag(e.target.value)}>
              <option value="">标签：全部</option>
              {allTags.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select className="kb-select" value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
              <option value="">状态：全部</option>
              {['active', 'draft', 'deprecated'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <input className="kb-input" placeholder="检索标题 / 标签…" value={kw}
              onChange={e => setKw(e.target.value)} />
            <span className="kb-sub">{filtered.length}/{data?.total ?? 0} 篇</span>
          </div>

          <table className="kb-table">
            <colgroup>
              <col style={{ width: 240 }} />
              <col style={{ width: 84 }} />
              <col />
              <col style={{ width: 96 }} />
              <col style={{ width: 104 }} />
            </colgroup>
            <thead>
              <tr>
                <th>标题</th>
                <th>分类</th>
                <th>标签</th>
                <th>状态</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(d => (
                <tr key={d.path} onClick={() => { void openDoc(d.path, d.title) }}>
                  <td>
                    <span className="kb-title-cell">{d.title}</span>
                    <span className="kb-path">　{d.path}</span>
                  </td>
                  <td><span className="kb-cat" data-cat={d.category}>{d.category}</span></td>
                  <td>{d.tags.map(t => <span className="kb-tag" key={t}>{t}</span>)}</td>
                  <td><span className="kb-status" data-status={d.status}>{d.status}</span></td>
                  <td>{d.updated}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={5} className="kb-empty">没有符合筛选的文档。</td></tr>
              )}
            </tbody>
          </table>
        </>
      ) : (
        /* ---------- doc 态：文档全文（中栏内嵌） ---------- */
        <>
          <div className="kb-head">
            <button className="kb-back-btn" onClick={() => setDoc(undefined)}>← 返回</button>
            <span className="kb-title">{doc.title}</span>
            <span className="kb-path">{doc.path}</span>
          </div>
          <div className="kb-filters">
            <button className={view === 'render' ? 'kb-btn kb-btn-active' : 'kb-btn'} onClick={() => setView('render')}>渲染</button>
            <button className={view === 'raw' ? 'kb-btn kb-btn-active' : 'kb-btn'} onClick={() => setView('raw')}>raw</button>
            <button className={view === 'diff' ? 'kb-btn kb-btn-active' : 'kb-btn'}
              onClick={() => { setView('diff'); void loadDiff() }}>diff 审阅</button>
            {view === 'diff' && (
              <>
                <span className="kb-sub">base</span>
                <input className="kb-input" style={{ minWidth: 120 }} value={diffBase}
                  onChange={e => setDiffBase(e.target.value)} />
                <button className="kb-btn" onClick={() => { void loadDiff() }}>拉取 diff</button>
              </>
            )}
          </div>

          <div onClick={onDocClick}>
            {docLoading && <div className="kb-empty">读取全文…</div>}

            {!docLoading && view === 'render' && (
              <div className="kb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(doc.content) }} />
            )}
            {!docLoading && view === 'raw' && <pre className="kb-body">{doc.content}</pre>}

            {!docLoading && view === 'diff' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {diffLoading && <div className="kb-empty">计算 block diff…</div>}
                {!diffLoading && diff === undefined && (
                  <div className="kb-empty">diff 不可用（文档尚未进入 git，或 base 无此文件）。</div>
                )}
                {!diffLoading && diff !== undefined && diffSummary !== undefined && (
                  <>
                    <div className="kb-diff-sum">
                      <span>base：{diff.base}</span>
                      <span style={{ color: diff.changed ? '#bf8700' : '#57606a' }}>{diff.changed ? '有改动' : '无改动'}</span>
                      <span>新增 {diffSummary.added}</span>
                      <span>删除 {diffSummary.removed}</span>
                      <span>修改 {diffSummary.modified}</span>
                      <span>未变 {diffSummary.unchanged}</span>
                      <span style={{ color: '#116329' }}>已通过 {diffSummary.approved}</span>
                      <span style={{ color: '#cf222e' }}>已驳回 {diffSummary.rejected}</span>
                      {reviewInfo !== undefined && (
                        <span>已存 review {reviewInfo.rounds} 轮
                          {reviewInfo.latest !== undefined && `（最近：${reviewInfo.latest.reviewer} · ${reviewInfo.latest.conclude}）`}
                        </span>
                      )}
                    </div>
                    {!diff.hasBase && (
                      <div className="kb-warn">base（{diff.base}）下无此文件，整篇按新增处理。</div>
                    )}
                    {expired.length > 0 && (
                      <div className="kb-expired">
                        <div style={{ fontWeight: 600, marginBottom: 4 }}>已过期意见（{expired.length}）——块内容已变，key 失效，不回填：</div>
                        {expired.map((eb, i) => (
                          <div key={i} className="kb-expired-item">
                            <span className="d-badge" data-s="expired">已过期</span>{' '}
                            [{TYPE_LABEL[eb.type] ?? eb.type}] {eb.summary}
                            {eb.decision !== undefined && ` · ${eb.decision === 'approve' ? '曾通过' : '曾驳回'}`}
                            {eb.comment !== undefined && eb.comment !== '' && ` · 注释：${eb.comment}`}
                          </div>
                        ))}
                      </div>
                    )}
                    {diff.blocks.map((b) => {
                      const key = b.key
                      const rv = reviews[key] ?? {}
                      const isUnchanged = b.status === 'unchanged'
                      const open = isUnchanged ? (expanded[key] ?? false) : true
                      const showRaw = rawOps[key] ?? false
                      return (
                        <div key={key} className="d-block">
                          <div className="d-head">
                            <span className="d-badge" data-s={b.status}>{STATUS_LABEL[b.status]}</span>
                            <span className="d-type">{TYPE_LABEL[b.type] ?? b.type}{b.type === 'heading' ? ` H${b.level}` : ''}</span>
                            <span className="d-head-t">{b.summary}</span>
                            {isUnchanged && (
                              <button className="d-expand" onClick={() => setExpanded(prev => ({ ...prev, [key]: !(prev[key] ?? false) }))}>
                                {open ? '收起' : '展开'}
                              </button>
                            )}
                            {!isUnchanged && b.ops !== undefined && b.ops.length > 0 && (
                              <button className="d-expand" onClick={() => setRawOps(prev => ({ ...prev, [key]: !showRaw }))}>
                                {showRaw ? '看渲染' : '看行级'}
                              </button>
                            )}
                          </div>
                          {open && (showRaw && b.ops !== undefined
                            ? <div className="d-ops">{renderOps(b.ops)}</div>
                            : renderBlockBody(b))}
                          {!isUnchanged && (
                            <div className="d-actions">
                              <button
                                className={'d-btn d-btn-ap' + (rv.decision === 'approve' ? ' on' : '')}
                                onClick={() => setReview(key, { decision: rv.decision === 'approve' ? undefined : 'approve' })}
                              >通过</button>
                              <button
                                className={'d-btn d-btn-rj' + (rv.decision === 'reject' ? ' on' : '')}
                                onClick={() => setReview(key, { decision: rv.decision === 'reject' ? undefined : 'reject' })}
                              >驳回</button>
                              <button
                                className="d-btn"
                                onClick={() => setReview(key, { open: !(rv.open ?? false) })}
                              >注释</button>
                              {rv.comment !== undefined && rv.comment !== '' && (
                                <span className="kb-sub">已注：{rv.comment.slice(0, 40)}{rv.comment.length > 40 ? '…' : ''}</span>
                              )}
                              {(rv.open ?? false) && (
                                <textarea className="d-cmt" placeholder="写审阅注释…"
                                  value={rv.comment ?? ''}
                                  onChange={e => setReview(key, { comment: e.target.value })} />
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                    <div className="d-actions" style={{ border: '1px solid #d0d7de', borderRadius: 8, background: '#fff' }}>
                      <span className="kb-sub">整篇结论：</span>
                      <select className="d-conclude" value={conclude}
                        onChange={e => setConclude(e.target.value as 'approved' | 'changes-requested' | 'in-progress')}>
                        {(['in-progress', 'approved', 'changes-requested'] as const).map(c => (
                          <option key={c} value={c}>{CONCLUDE_LABEL[c]}</option>
                        ))}
                      </select>
                      <button className="kb-btn kb-btn-blue" disabled={saveState.saving === true}
                        onClick={() => { void saveReview() }}>
                        {saveState.saving === true ? '保存中…' : '保存 review'}
                      </button>
                      {saveState.runId !== undefined && saveState.runId !== '' && (
                        <span className="kb-sub" style={{ color: '#116329' }}>已保存（run-id {saveState.runId}）</span>
                      )}
                      {saveState.error !== undefined && (
                        <span className="kb-sub" style={{ color: '#cf222e' }}>保存失败：{saveState.error}</span>
                      )}
                    </div>
                    {reworkMd !== undefined && (
                      <div className="kb-rework">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontWeight: 600 }}>rework 指令（可贴进工单派返工活）</span>
                          <button className="d-btn" onClick={() => {
                            try { void navigator.clipboard?.writeText(reworkMd) } catch { /* 剪贴板不可用静默 */ }
                          }}>复制</button>
                        </div>
                        <pre>{reworkMd}</pre>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- 注册 */

/**
 * 260823 起知识库 UI 不再占 chat 顶部页签——移到工单台侧栏中栏，
 * 由 sandbar-workbench 的侧栏直接 import KnowledgeSection 渲染（用户拍板：chat 页签只留 chat/trajectory）。
 * apply 保留为空操作（宿主装载契约要求导出）。
 * t260916-26 注：0.1.5 的会话视图扩展面若将来恢复插件自持页签，走
 * uiConversation.views.register（0.1.5）/ conversationViews.register（0.1.1）
 * 双轨探测——见 ./inject-contract 白名单纪律。
 */
export function apply(_ctx: ClientContext): void {
  /* 无注册：视图经 sandbar-workbench 侧栏中栏承载 */
}
