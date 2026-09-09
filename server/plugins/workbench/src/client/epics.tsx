/**
 * epics.tsx —— 工单台「立项单」中列第四视图 + 所属立项徽标（epic-linkage Tier 3，t260826-02）。
 *
 * 落地口径（方案 + 评审拍板）：
 *   - 不加路由/不加顶层 tab：本视图挂进 sidebar 中列四视图体系（views.epics），
 *     由项目行立项单图标（t260827-01，空代号=立项清单）/ 工单徽标点击（定位详情）切换进来；
 *   - 真源=API 渲染、前端不存状态（立项单关键决策 5）：列表=GET /api/epics，
 *     详情=GET /api/epics/<code> + /api/epics/<code>/tickets（8s 轮询实时汇总）；
 *   - Markdown 渲染复用 knowledge 浏览器半 renderMarkdown（index.tsx 同款 import，
 *     零新依赖；立项单是仓库可信内容，与 M9 block diff 同前提）；
 *   - 新建工单（验收标准 9）：模板下拉（GET /api/wf/workflows）+ 标题 + 正文，
 *     epic 由界面传值（只读行展示，无手输框）→ POST /api/wf/tickets（host
 *     handleTicketCreate，t260826-02 新增，需重启 dsh 生效）。
 *   - 继续执行（t260827-02）：详情头部按钮 → POST /api/epics/<code>/suggest-next
 *     启动 integration 建议 job → 3s 轮询 GET .../suggest-next/<jobId>；done 把建议
 *     （模板/标题/正文）预填进新建工单弹层并展示理由横幅，人确认后才走上面的创建
 *     通路；failed/超时黄条降级并照常打开空白弹层——建议链路永不阻塞手动新建。
 *   - EpicBadge 同时供 index.tsx 工单列表行/详情头部复用；口径单点=epics-model.ts。
 *
 * 不做（工单红线）：归档按钮/快照 UI（archive API 另单）；立项单编辑 UI（真源=文件，编辑走仓库）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
// 渲染态 markdown 复用 knowledge 浏览器半（与 index.tsx:57 同款，纯函数无依赖）。
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import {
  buildCreatePayload, composeSuggestedBody, createWriteSetBlocked, epicBadgeOf, epicCreateNote,
  filterEpicsByStatus, invalidWriteSetLines, mergeBuckets, sortBucketKeys, sortEpicTickets,
} from './epics-model.ts'
import type { EpicMeta, EpicNextSuggestion, EpicStatus, EpicTicketsResult } from './epics-model.ts'
import { EPIC_NOTE_INPUT_MAX, EPIC_STATUS_OPTIONS, isEpicStatusValue } from './epics-model.ts'
import { startVisibleInterval } from './visibility-poll.ts'
import { DERIVE_TOKENS_CSS } from './theme';

/** 详情响应的「下一步建议」投影（host epic-next.ts EpicNextHint 互指；全 string 宿主已收口）。 */
interface EpicNextHint {
  status: 'ok' | 'done'
  workflow: string
  title: string
  body: string
  rationale: string
  summary: string
}

/** 列表行（host epics.ts EpicMeta + nextHintCached 标记；epics-model.ts 不在本票写集，
 *  本地扩展类型对齐，字段缺省 undefined=未命中）。 */
type EpicListRow = EpicMeta & { nextHintCached?: boolean }

/* ---------------------------------------------------------------- 样式（wb-ep-* 独立前缀） */

const CSS = `${DERIVE_TOKENS_CSS}
.wb-ep-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-fg,#1f2328);min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:14px;height:100%;overflow-y:auto;font-size:13px;line-height:1.55}
.wb-ep-head{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de);padding-bottom:10px;flex-wrap:wrap}
.wb-ep-title{font-size:18px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--dsw-derive-accent,#0969da);
  background:var(--dsw-derive-accent-bg,#ddf4ff);border:1px solid var(--dsw-derive-accent-border,#96c8f2);border-radius:6px;padding:1px 8px}
.wb-ep-sub{font-size:12px;color:var(--dsw-derive-muted,#57606a)}
.wb-ep-btn{font:inherit;font-size:13px;padding:4px 14px;border-radius:6px;cursor:pointer;
  border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
/* 禁用态（t260907-08）：弃 opacity 降权（四象限 new-light 格实锤 3.16<4.5），
 * 改灰字＋浅底的令牌化禁用态——对比度全档达标且保留「不可点」affordance。 */
.wb-ep-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-ep-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
.wb-ep-cols{display:flex;gap:14px;align-items:flex-start;min-height:0}
.wb-ep-md{flex:55 1 0;min-width:0;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);
  padding:12px 16px;overflow-x:auto}
.wb-ep-side{flex:45 1 0;min-width:240px;display:flex;flex-direction:column;gap:10px}
.wb-ep-panel{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);padding:10px 12px;
  display:flex;flex-direction:column;gap:8px}
.wb-ep-panel-title{font-size:13px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-chips{display:flex;gap:8px;flex-wrap:wrap}
.wb-ep-bucket{font-size:12px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
.wb-ep-bucket[data-b=进行中]{background:var(--dsw-derive-accent-bg,#ddf4ff);border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-ep-bucket[data-b=已完成]{background:var(--dsw-derive-success-bg,#dafbe1);border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success-deep,#116329)}
.wb-ep-bucket[data-b=已终止]{background:var(--dsw-derive-danger-bg,#ffebe9);border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e)}
.wb-ep-ticket{padding:6px 8px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;cursor:pointer;background:var(--dsw-derive-canvas,#ffffff)}
.wb-ep-ticket:hover{background:var(--dsw-derive-surface,#f6f8fa);border-color:var(--dsw-derive-accent-border,#96c8f2)}
.wb-ep-ticket .l1{display:flex;align-items:baseline;gap:8px;font-size:12px}
.wb-ep-ticket .l1 .id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-derive-accent,#0969da);font-weight:600;flex:none}
.wb-ep-ticket .l1 .ti{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-ticket .l2{font-size:11px;color:var(--dsw-derive-muted,#8c959f);margin-top:2px}
.wb-ep-degraded{font-size:12px;color:var(--dsw-derive-warn-deep,#7d4e00);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:6px 10px;white-space:pre-wrap;word-break:break-word}
.wb-ep-empty{font-size:12px;color:var(--dsw-derive-muted,#57606a);padding:8px 0}
.wb-ep-err{background:var(--dsw-derive-danger-bg,#ffebe9);border:1px solid var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);border-radius:6px;
  padding:8px 12px;font-size:12px;white-space:pre-wrap}
.wb-ep-msgok{font-size:12px;color:var(--dsw-derive-success-deep,#116329);background:var(--dsw-derive-success-bg,#dafbe1);border:1px solid var(--dsw-derive-success-border,#7dd9a0);
  border-radius:6px;padding:6px 10px}
/* 建议结项卡片（t260828-08）：绿色横条 + 说明 + 确认结项按钮 */
.wb-ep-done-card{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  border:1px solid var(--dsw-derive-success-border,#7dd9a0);background:var(--dsw-derive-success-bg,#dafbe1);border-radius:6px;padding:8px 12px}
.wb-ep-done-title{font-size:12px;font-weight:600;color:var(--dsw-derive-success-deep,#116329)}
.wb-ep-hint-badge{display:inline-block;margin-left:8px;font-size:10px;border-radius:6px;
  padding:0 6px;color:var(--dsw-derive-success-deep,#116329);background:var(--dsw-derive-success-bg,#dafbe1);border:1px solid var(--dsw-derive-success-border,#a6e0b1)}
.wb-ep-done-reason{font-size:12px;color:var(--dsw-derive-success-deep,#116329);flex:1;min-width:200px}
/* 立项清单表（未选代号时的落列表） */
.wb-ep-table{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);font-size:13px;overflow:hidden}
.wb-ep-table th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600;text-align:left;padding:8px 12px;
  border-bottom:1px solid var(--dsw-derive-border,#d0d7de);font-size:12px;white-space:nowrap}
.wb-ep-table td{padding:8px 12px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);vertical-align:middle}
.wb-ep-table tbody tr{cursor:pointer}
.wb-ep-table tbody tr:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-ep-table tbody tr:last-child td{border-bottom:none}
/* 新建工单弹层（制式照 index.tsx wb-modal） */
.wb-ep-modal{position:fixed;inset:0;background:rgba(31,35,40,.5);z-index:99;display:flex;align-items:center;
  justify-content:center;padding:24px}
.wb-ep-modal-box{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:10px;
  box-shadow:0 8px 32px rgba(31,35,40,.2);max-width:640px;width:100%;max-height:86vh;
  display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.wb-ep-modal-title{font-size:15px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--dsw-derive-muted,#57606a)}
.wb-ep-input{font:inherit;font-size:13px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:6px 10px;box-sizing:border-box;width:100%}
.wb-ep-input:focus{outline:none;border-color:var(--dsw-derive-accent,#0969da);box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.wb-ep-readonly{font-size:13px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);
  border-radius:6px;padding:6px 10px}
.wb-ep-ops{display:flex;gap:8px;align-items:center}
/* 所属立项徽标（wb-epic-chip：列表行/详情头部复用；灰=未归档，蓝=有归属可点） */
.wb-epic-chip{display:inline-block;font-size:11px;border-radius:6px;padding:1px 7px;flex:none;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap;vertical-align:1px}
.wb-epic-chip[data-archived=true]{color:var(--dsw-derive-muted,#8c959f);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);font-family:inherit}
.wb-epic-chip[data-archived=false]{color:var(--dsw-derive-accent-deep,#0550ae);background:var(--dsw-derive-accent-bg,#ddf4ff);border:1px solid var(--dsw-derive-accent-border,#96c8f2);cursor:pointer}
.wb-epic-chip[data-archived=false]:hover{background:var(--dsw-derive-accent-border,#bfe3ff);border-color:var(--dsw-derive-accent,#0969da)}
`

/* ---------------------------------------------------------------- 数据通道 */

const EPICS_API = '/sandbar-workbench/api/epics'
const WF_API = '/sandbar-workbench/api/wf'

async function getJson(path: string): Promise<any> {
  const res = await fetch(path)
  return res.json()
}

/* ---------------------------------------------------------------- EpicBadge（所属立项徽标） */

/**
 * 所属立项徽标（验收标准 8）：有 epic → 蓝 chip 显代号、点击 onNavigate(code) 跳立项详情；
 * 无 epic → 灰 chip「未归档」（不可点，与有归属视觉区分）。口径单点=epicBadgeOf。
 * onNavigate 缺省时一律纯展示（不可点）。
 */
export function EpicBadge({ epic, onNavigate }: {
  epic?: string
  onNavigate?: (code: string) => void
}) {
  const b = epicBadgeOf(epic)
  return (
    <span
      className="wb-epic-chip"
      data-archived={b.code === null}
      title={b.code !== null ? `所属立项：${b.code}（点击查看立项单）` : '未归档到任何立项单'}
      onClick={b.code !== null && onNavigate ? (ev) => { ev.stopPropagation(); onNavigate(b.code as string) } : undefined}
    >{b.label}</span>
  )
}

/* ---------------------------------------------------------------- EpicSection（中列第四视图） */

interface WfTemplate {
  id: string
  name: string
}

export function EpicSection({ epicCode, epicNonce, projectKey, onOpenTicket }: {
  /** 侧栏图标/徽标点进来的立项代号；空串=显立项清单。 */
  epicCode?: string
  /** 「又点了一次」信号：同 code 重进 / 点立项单图标回清单（空代号）也触发重拉——同 focusNonce 先例。 */
  epicNonce?: number
  /** 新建工单落点项目（?project=；空=禁用创建并提示）。 */
  projectKey?: string
  /** 点关联工单行 → 跳工单详情（复用侧栏 handleTicketClick 链路）。 */
  onOpenTicket?: (ticketId: string) => void
}) {
  /** 内部选中代号：prop 驱动（外部点击）+ 返回列表可清空（内部导航）。 */
  const [code, setCode] = useState(epicCode ?? '')
  const [list, setList] = useState<EpicListRow[] | undefined>(undefined)
  const [detail, setDetail] = useState<(EpicMeta & { markdown: string }) | undefined>(undefined)
  const [tickets, setTickets] = useState<EpicTicketsResult | undefined>(undefined)
  const [error, setError] = useState('')
  const [templates, setTemplates] = useState<WfTemplate[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [createWf, setCreateWf] = useState('')
  const [createTitle, setCreateTitle] = useState('')
  const [createBody, setCreateBody] = useState('')
  /** 写集编辑栏（t260829-07 写集生命周期）：每行一条，建议预填，人可增删。 */
  const [createWsText, setCreateWsText] = useState('')
  /** 「本票无文件改动」显式声明（t260901-01）：空写集 + 勾选 → 引擎放行建票（meta 记
   *  no_file_changes）。复位纪律：建议回填 / 关弹层 / 切模板三处都复位，防脏状态跨票残留。 */
  const [createAllowEmpty, setCreateAllowEmpty] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [createMsg, setCreateMsg] = useState('')
  /** 弹层顶部横幅：integration 建议理由（可改提示）或建议不可用的降级说明（t260827-02）。 */
  const [createHint, setCreateHint] = useState('')
  const [suggestBusy, setSuggestBusy] = useState(false)
  /** 继续执行：integration 建议 job 进行中（按钮禁用态 + 轮询停表函数句柄；
   *  t260901-15 起为 visibility 门停表函数，非定时器 id）。 */
  const suggestTimer = useRef<(() => void) | null>(null)
  /** 建议结项卡片（t260828-08）：suggestion.status==='done' 时置位，出绿色「确认结项」卡。 */
  const [suggestDone, setSuggestDone] = useState<Partial<EpicNextSuggestion> | null>(null)
  const [closeBusy, setCloseBusy] = useState(false)
  const [closeMsg, setCloseMsg] = useState('')
  // 下一步建议可见性（t260829-02）：详情响应的 nextHint（host readPrecacheHint 投影，
  // state_key 已对齐才命中）；status='done' 复用 suggestDone 结项卡，'ok' 出预填小卡。
  const [hint, setHint] = useState<EpicNextHint | null>(null)
  const [hintBusy, setHintBusy] = useState(false)
  /** 立项列表状态筛选（t260831-05）：'' = 全部，其余为四枚举值之一（纯前端过滤）。 */
  const [statusFilter, setStatusFilter] = useState<EpicStatus | ''>('')
  /** 状态编辑栏（t260831-05）：详情页状态下拉 + 备注输入框 → POST /epics/<code>/status。 */
  const [editStatus, setEditStatus] = useState<EpicStatus | ''>('')
  const [editNote, setEditNote] = useState('')
  /** 备注是否被改动过（评审拍板）：未改动 → 请求体省略 note 字段（不动备注，
   *  防误清空丢自由文本）；改动过 → 传新值（''=用户显式清空）。显式 dirty 标记比
   *  字符串比较少边界（改了又改回原文仍视为未动，取安全侧）。 */
  const [noteDirty, setNoteDirty] = useState(false)
  const [saveBusy, setSaveBusy] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  // 外部点击（项目行立项单图标/工单徽标）：code+nonce 变化 → 完全同步到内部选中代号——
  // 空串=外部要求回清单（t260827-01：图标入口以空代号进入；「看过详情再点图标」靠 nonce 触发，
  // 不能只同步非空值，否则详情态永远无法从外部回到列表）。内部「← 返回列表」走 setCode，
  // 不触发改 effect（deps 是 prop），两种导航互不干扰。
  useEffect(() => {
    setCode(epicCode ?? '')
  }, [epicCode, epicNonce])

  // 立项清单（列表模式 10s 轮询——状态随归档/新立项变化；失败静默留旧数据，同侧栏 load 先例）。
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const d = await getJson(EPICS_API)
        if (!cancelled && d?.ok === true) setList((d.result?.epics ?? []) as EpicListRow[])
      } catch { /* 静默：接口不可用（headless）保持旧数据 */ }
    }
    load()
    // t260901-15：不可见页签暂停轮询。
    const stopPoll = startVisibleInterval(() => { void load() }, 10_000)
    return () => { cancelled = true; stopPoll() }
  }, [])

  // 立项单详情（Markdown 全文）：code 变化即重拉。
  useEffect(() => {
    if (!code) { setDetail(undefined); return }
    let cancelled = false
    setDetail(undefined)
    setError('')
    setHint(null)
    void (async () => {
      try {
        const d = await getJson(`${EPICS_API}/${encodeURIComponent(code)}`)
        if (cancelled) return
        if (d?.ok !== true) { setError(d?.error ?? '立项单加载失败'); return }
        setDetail(d.result as EpicMeta & { markdown: string })
        // 下一步建议（t260829-02）：done 形态复用结项卡；ok 形态出预填小卡
        const h = (d.result?.nextHint ?? null) as EpicNextHint | null
        if (h !== null && String(h.status ?? '') === 'done') {
          setSuggestDone(h as Partial<EpicNextSuggestion>)
        } else {
          setHint(h)
        }
      } catch (err) {
        if (!cancelled) setError(String(err instanceof Error ? err.message : err))
      }
    })()
    return () => { cancelled = true }
  }, [code])

  /** [忽略] 下一步建议（t260829-02）：删预跑缓存（host 幂等）→ 刷新详情清卡。 */
  const dismissHint = useCallback(async () => {
    if (hintBusy) return
    setHintBusy(true)
    try {
      const res = await fetch(`${EPICS_API}/${encodeURIComponent(code)}/next-hint/dismiss`, { method: 'POST' })
      const d = await res.json()
      if (d?.ok === true) {
        setHint(null)
        try {
          const e = await getJson(`${EPICS_API}/${encodeURIComponent(code)}`)
          if (e?.ok === true) setDetail(e.result as EpicMeta & { markdown: string })
        } catch { /* 静默：保留旧详情 */ }
      }
    } catch { /* 网络抖动静默：卡保留，下次可再点 */ } finally {
      setHintBusy(false)
    }
  }, [code, hintBusy])

  // 状态编辑栏随详情重置（t260831-05）：详情刷新（首次加载/保存后重拉/忽略建议重拉）
  // 都把下拉与备注框归位到档案现值，清 dirty 标记与保存提示——在编辑中途刷新不残留半成品。
  useEffect(() => {
    if (detail === undefined) return
    setEditStatus(isEpicStatusValue(detail.status) ? detail.status : '')
    setEditNote(String(detail.note ?? ''))
    setNoteDirty(false)
    setSaveMsg('')
  }, [detail])

  /** 状态编辑保存（t260831-05）：POST /epics/<code>/status——noteDirty 时带 note 字段，
   *  未改动省略（后端语义：缺省=不动备注，''=清空）。成功后重拉详情（上面 effect
   *  自动归位），失败人话报错（后端 422 枚举/备注校验原样透出）。 */
  const saveStatus = useCallback(async () => {
    if (saveBusy) return
    if (editStatus === '') { setSaveMsg('保存失败：请先选择一个状态'); return }
    setSaveBusy(true)
    setSaveMsg('')
    try {
      const res = await fetch(`${EPICS_API}/${encodeURIComponent(code)}/status`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(noteDirty ? { status: editStatus, note: editNote } : { status: editStatus }),
      })
      const d = await res.json()
      if (d?.ok !== true) {
        setSaveMsg(`保存失败：${String(d?.error ?? '未知错误')}`)
        return
      }
      setSaveMsg(`已保存：${String(d?.result?.status ?? '')}`)
      try {
        const e = await getJson(`${EPICS_API}/${encodeURIComponent(code)}`)
        if (e?.ok === true) setDetail(e.result as EpicMeta & { markdown: string })
      } catch { /* 静默：保存已成功，详情留旧值 */ }
    } catch (err) {
      setSaveMsg(`保存请求异常：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setSaveBusy(false)
    }
  }, [saveBusy, editStatus, noteDirty, editNote, code])

  // 关联工单实时汇总：详情打开期间 8s 轮询；degraded=true 走黄条人话降级（不静默）。
  useEffect(() => {
    if (!code) { setTickets(undefined); return }
    let cancelled = false
    async function load() {
      try {
        const d = await getJson(`${EPICS_API}/${encodeURIComponent(code)}/tickets`)
        if (!cancelled && d?.ok === true) setTickets(d.result as EpicTicketsResult)
      } catch { /* 静默：保持旧数据 */ }
    }
    load()
    // t260901-15：不可见页签暂停轮询。
    const stopPoll = startVisibleInterval(() => { void load() }, 8_000)
    return () => { cancelled = true; stopPoll() }
  }, [code])

  // 模板下拉（新建工单弹层首次打开时拉一次；GET /wf/workflows 无 project 强校验，零 host 改动）。
  useEffect(() => {
    if (!createOpen || templates.length > 0) return
    void (async () => {
      try {
        const d = await getJson(`${WF_API}/workflows`)
        if (d?.ok === true) setTemplates((d.result ?? []) as WfTemplate[])
      } catch { /* 静默：下拉为空时提交按钮仍挡必填 */ }
    })()
  }, [createOpen, templates.length])

  const openCreate = useCallback(() => {
    setCreateWf('')
    setCreateTitle('')
    // 正文首行注入归属说明（留痕；epic 字段本体由界面传值，不靠正文解析）。
    setCreateBody(epicCreateNote(code) + '\n')
    setCreateWsText('')
    setCreateAllowEmpty(false)
    setCreateMsg('')
    setCreateHint('')
    setCreateOpen(true)
  }, [code])

  /** 停轮询（建议落地/失败/换立项/组件卸载都走这里；t260901-15 起调停表函数）。 */
  const stopSuggestPoll = useCallback(() => {
    if (suggestTimer.current !== null) {
      suggestTimer.current()
      suggestTimer.current = null
    }
  }, [])

  // 换立项/卸载：停轮询、解除忙碌态（旧 code 的 job 结果不再回填新弹层）。
  useEffect(() => {
    return () => {
      stopSuggestPoll()
      setSuggestBusy(false)
    }
  }, [code, stopSuggestPoll])

  /** 建议落地处理（done 分流，t260828-08 抽局部函数）：status='done' 出绿色结项卡；
   *  其余（ok/缺省）走既有预填新建工单弹层。 */
  const applySuggestion = useCallback((s: Partial<EpicNextSuggestion>) => {
    if (String(s.status ?? '') === 'done') {
      setSuggestDone(s)
      return
    }
    setCreateWf(String(s.workflow ?? ''))
    setCreateTitle(String(s.title ?? ''))
    setCreateBody(composeSuggestedBody(code, String(s.body ?? '')))
    // 写集预填（t260829-07）：建议 write_set（host 已清洗）每行一条，人可增删。
    setCreateWsText((Array.isArray(s.write_set) ? s.write_set : []).join('\n'))
    setCreateAllowEmpty(false)
    setCreateMsg('')
    setCreateHint(`integration 建议（可直接修改后再提交）：${String(s.rationale ?? '').trim() || '（agent 未给理由）'}`)
    setCreateOpen(true)
  }, [code])

  /** 确认结项（t260828-08）：POST /epics/<code>/close（人审确认语义）→ 刷新详情与工单汇总。 */
  const confirmClose = useCallback(async () => {
    if (closeBusy) return
    setCloseBusy(true)
    setCloseMsg('')
    try {
      const res = await fetch(`${EPICS_API}/${encodeURIComponent(code)}/close`, { method: 'POST' })
      const d = await res.json()
      if (d?.ok !== true) {
        setCloseMsg(`结项失败：${String(d?.error ?? '未知错误')}`)
        return
      }
      setSuggestDone(null)
      setCreateMsg(`立项 ${code} 已标记完结（notes/epics/${code}.md 状态已更新）`)
      // 刷新详情（状态行）与关联工单汇总
      try {
        const e = await getJson(`${EPICS_API}/${encodeURIComponent(code)}`)
        if (e?.ok === true) setDetail(e.result as EpicMeta & { markdown: string })
      } catch { /* 静默：保留旧详情 */ }
    } catch (err) {
      setCloseMsg(`结项请求异常：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setCloseBusy(false)
    }
  }, [closeBusy, code])

  // 建议结项卡片随立项切换清空（旧 code 的 done 结论不属于新立项）。
  useEffect(() => {
    setSuggestDone(null)
    setCloseMsg('')
  }, [code])

  /**
   * 继续执行（t260827-02）：POST 启动 integration 建议 job → 3s 轮询（封顶 10 分钟）。
   * done → 建议预填进新建工单弹层 + 理由横幅；failed/超时/启动失败 → 黄条降级
   * 并照常打开空白弹层（建议链路永不阻塞手动新建）。工单只在人点「创建工单」后
   * 才真正创建（走 submitCreate 既有通路）。
   */
  const openSuggest = useCallback(async () => {
    if (suggestBusy) return
    /** 降级出口：停轮询 + 打开空白弹层 + 黄条写明原因。 */
    const failOpen = (reason: string) => {
      stopSuggestPoll()
      setSuggestBusy(false)
      openCreate()
      setCreateHint(`integration 建议不可用：${reason}。已打开空白新建工单，可手工填写提交。`)
    }
    setSuggestBusy(true)
    let jobId = ''
    try {
      const res = await fetch(`${EPICS_API}/${encodeURIComponent(code)}/suggest-next`, { method: 'POST' })
      const d = await res.json()
      if (d?.ok !== true) {
        failOpen(`启动失败——${String(d?.error ?? '未知错误')}`)
        return
      }
      // 预跑缓存命中（t260828-08）：跳过轮询直接走 done 处理，秒开不再等 1~5 分钟
      if (d.result?.cached === true && String(d.result?.state ?? '') === 'done') {
        setSuggestBusy(false)
        applySuggestion((d.result?.suggestion ?? {}) as Partial<EpicNextSuggestion>)
        return
      }
      jobId = String(d.result?.job_id ?? '')
      if (jobId === '') {
        failOpen('启动失败——响应缺 job_id')
        return
      }
    } catch (err) {
      failOpen(`启动请求异常——${String(err instanceof Error ? err.message : err)}`)
      return
    }
    const deadline = Date.now() + 10 * 60_000
    stopSuggestPoll()
    // t260901-15：建议 job 轮询同样吃可见性门（隐藏时停查、回可见补查——
    // 轮询体自带 done/failed/deadline 判定，补跑一拍不会丢状态）。
    suggestTimer.current = startVisibleInterval(() => {
      void (async () => {
        try {
          const d = await getJson(`${EPICS_API}/${encodeURIComponent(code)}/suggest-next/${encodeURIComponent(jobId)}`)
          if (d?.ok !== true) {
            failOpen(`查询建议状态失败——${String(d?.error ?? '未知错误')}`)
            return
          }
          const st = String(d.result?.state ?? '')
          if (st === 'done') {
            stopSuggestPoll()
            setSuggestBusy(false)
            applySuggestion((d.result?.suggestion ?? {}) as Partial<EpicNextSuggestion>)
          } else if (st === 'failed') {
            failOpen(String(d.result?.reason ?? 'agent 未给出原因'))
          } else if (Date.now() > deadline) {
            failOpen('等待超过 10 分钟仍未产出建议（已停止轮询；宿主侧 job 会自行超时终止）')
          }
          // running：等下个周期
        } catch { /* 网络抖动静默，下个周期重试 */ }
      })()
    }, 3000)
  }, [code, suggestBusy, openCreate, stopSuggestPoll, applySuggestion])

  const submitCreate = useCallback(async () => {
    if (createBusy) return
    if (!projectKey) { setCreateMsg('未知新建落点项目——请先从左侧点选一个项目'); return }
    if (!createWf) { setCreateMsg('请选择工单模板'); return }
    if (createTitle.trim() === '') { setCreateMsg('请填写工单标题'); return }
    // 写集校验（t260829-07）：有非法行 → 拦截提交（建票口空写集拒收，宁可在前端挡）。
    const badWs = invalidWriteSetLines(createWsText)
    if (badWs.length > 0) {
      setCreateMsg(`写集含非法路径（须为仓库内相对路径，禁绝对路径与 '..'）：${badWs.slice(0, 3).join('、')}`)
      return
    }
    // 空写集拦截（t260901-01）：未勾「无文件改动」声明 → 前端先挡（文案=两条出路口径）。
    const wsBlocked = createWriteSetBlocked(createWsText, createAllowEmpty)
    if (wsBlocked !== '') {
      setCreateMsg(wsBlocked)
      return
    }
    // POST 体组装单点（t260901-01）：空写集+声明才附 allow_empty_write_set=true。
    const payload = buildCreatePayload(
      { workflow: createWf, title: createTitle.trim(), body: createBody, epic: code },
      createWsText, createAllowEmpty)
    setCreateBusy(true)
    setCreateMsg('')
    try {
      const res = await fetch(`${WF_API}/tickets?project=${encodeURIComponent(projectKey)}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const d = await res.json()
      if (d?.ok !== true) {
        // epic 强校验拒收等引擎错误原文透传（host 只透传不重复校验）。
        setCreateMsg(`创建失败：${d?.error ?? '未知错误'}`)
        return
      }
      const newId = String(d.result?.id ?? '')
      // 立即刷新关联工单汇总（新单落入本立项）；成功横幅显示在详情头部下方。
      try {
        const t = await getJson(`${EPICS_API}/${encodeURIComponent(code)}/tickets`)
        if (t?.ok === true) setTickets(t.result as EpicTicketsResult)
      } catch { /* 静默 */ }
      setCreateOpen(false)
      setCreateMsg(`已创建工单 ${newId}（所属立项 ${code}）`)
    } catch (err) {
      setCreateMsg(`创建请求异常：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setCreateBusy(false)
    }
  }, [createBusy, projectKey, createWf, createTitle, createBody, createWsText, createAllowEmpty, code])

  /* ---- 列表模式（未选代号） ---- */
  if (!code) {
    return (
      <div className="wb-ep-root">
        <style>{CSS}</style>
        <div className="wb-ep-head">
          <span className="wb-ep-title">立项单</span>
          <span className="wb-ep-sub">真源 = notes/epics/*.md（编辑走仓库，此处只读）</span>
          <span style={{ flex: 1 }} />
          {/* 状态筛选（t260831-05）：按四枚举值纯前端过滤，'' = 全部。 */}
          <label className="wb-ep-sub" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            状态筛选
            <select className="wb-ep-input" data-testid="epic-status-filter"
              value={statusFilter} onChange={(ev) => setStatusFilter((ev.target.value || '') as EpicStatus | '')}>
              <option value="">全部</option>
              {EPIC_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        </div>
        {list === undefined ? (
          <div className="wb-ep-empty">加载中…</div>
        ) : list.length === 0 ? (
          <div className="wb-ep-empty">暂无立项单（notes/epics/ 目录为空或不存在）。</div>
        ) : (
          <table className="wb-ep-table">
            <thead>
              <tr><th>代号</th><th>标题</th><th>状态</th><th>备注</th><th>立项日期</th></tr>
            </thead>
            <tbody>
              {filterEpicsByStatus(list, statusFilter).map(e => (
                <tr key={e.code} onClick={() => setCode(e.code)}>
                  <td><span className="wb-ep-code">{e.code}</span>
                    {e.nextHintCached === true && (
                      <span className="wb-ep-hint-badge" data-testid="epic-next-hint-badge"
                        title="上一单收口时已预跑「下一步建议」缓存，进详情可直接预填开票">下一步已备</span>
                    )}
                  </td>
                  <td>{e.title || '—'}</td>
                  <td>{e.status || '—'}</td>
                  <td>{e.note || '—'}</td>
                  <td>{e.created || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    )
  }

  /* ---- 详情模式：左 Markdown / 右工单汇总 ---- */
  const sorted = sortEpicTickets(tickets?.tickets ?? [])
  const merged = mergeBuckets(tickets?.buckets ?? {})
  const bucketKeys = sortBucketKeys(Object.keys(merged))
  return (
    <div className="wb-ep-root">
      <style>{CSS}</style>
      <div className="wb-ep-head">
        <button className="wb-ep-btn" onClick={() => setCode('')}>← 返回列表</button>
        <span className="wb-ep-code">{code}</span>
        <span className="wb-ep-title">{detail?.title ?? ''}</span>
        {detail?.created && <span className="wb-ep-sub">立项 {detail.created}</span>}
        {/* 状态编辑（t260831-05）：下拉只出四枚举值（白名单内），备注输入框未改动时
            保存不携带 note 字段（防误清空）；后端写前自动 /tmp 备份。 */}
        <select className="wb-ep-input" data-testid="epic-status-edit" style={{ maxWidth: 180 }}
          title="立项状态（枚举四值，保存即外科改写 notes/epics/<代号>.md 状态行）"
          value={editStatus} disabled={detail === undefined}
          onChange={(ev) => setEditStatus((ev.target.value || '') as EpicStatus | '')}>
          <option value="">选择状态…</option>
          {EPIC_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className="wb-ep-input" data-testid="epic-note-edit" style={{ width: 260 }}
          title="备注（单行，≤200 字符；留空保存 = 清空备注；不改动 = 不动备注列）"
          placeholder="备注（可空）" maxLength={EPIC_NOTE_INPUT_MAX}
          value={editNote} disabled={detail === undefined}
          onChange={(ev) => { setEditNote(ev.target.value); setNoteDirty(true) }} />
        <button className="wb-ep-btn" data-testid="epic-status-save" disabled={saveBusy || detail === undefined || editStatus === ''}
          title="保存状态（可选备注）到 notes/epics/<code>.md（写前 /tmp 备份）"
          onClick={() => { void saveStatus() }}>
          {saveBusy ? '保存中…' : '保存状态'}
        </button>
        {saveMsg !== '' && <span className="wb-ep-sub">{saveMsg}</span>}
        <span style={{ flex: 1 }} />
        <button className="wb-ep-btn" disabled={suggestBusy}
          onClick={() => { void openSuggest() }}
          title="调用 integration 角色分析本立项现状，建议下一步工单并预填到新建工单弹层（人工确认后才会真正创建）">
          {suggestBusy ? 'integration 分析中…' : '▶ 继续执行'}
        </button>
        <button className="wb-ep-btn wb-ep-btn-green" onClick={openCreate}
          title="从本立项发起新工单（代号自动带入，不可手输）">＋ 新建工单</button>
      </div>
      {createMsg !== '' && !createOpen && <div className="wb-ep-msgok">{createMsg}</div>}
      {error !== '' && <div className="wb-ep-err">{error}</div>}
      {/* 下一步建议小卡（t260829-02）：预跑缓存命中（state_key 与当前工单集合对齐）——
          建议标题+理由 + [预填开票]（走既有缓存命中路径秒开弹层）/[忽略]（删缓存） */}
      {hint !== null && (
        <div className="wb-ep-done-card" data-testid="epic-next-hint-card">
          <span className="wb-ep-done-title">🧭 下一步建议已就绪</span>
          <span className="wb-ep-done-reason">
            {hint.title !== '' ? `建议工单：${hint.title}` : ''}{hint.rationale !== '' ? ` —— ${hint.rationale}` : ''}
          </span>
          <button className="wb-ep-btn wb-ep-btn-green" data-testid="epic-next-hint-apply"
            onClick={() => applySuggestion(hint as Partial<EpicNextSuggestion>)}
            title="用这份建议预填新建工单弹层（人工确认后才会真正创建）">预填开票</button>
          <button className="wb-ep-btn" disabled={hintBusy}
            onClick={() => { void dismissHint() }}
            title="删除预跑缓存（可重新点「继续执行」再算）">{hintBusy ? '忽略中…' : '忽略'}</button>
        </div>
      )}
      {/* 建议结项卡片（t260828-08）：agent 判定立项目标已达成，人审确认后正经结项 */}
      {suggestDone !== null && (
        <div className="wb-ep-done-card" data-testid="epic-done-card">
          <span className="wb-ep-done-title">✅ integration 建议结项</span>
          <span className="wb-ep-done-reason">
            {String(suggestDone.summary ?? '').trim() || 'integration 判定本立项目标已全部达成。'}
          </span>
          {closeMsg !== '' && <span className="wb-ep-err">{closeMsg}</span>}
          <button className="wb-ep-btn wb-ep-btn-green" disabled={closeBusy}
            onClick={() => { void confirmClose() }}
            title="把 notes/epics 状态表改为「已完结」（写前自动备份，可回滚）">
            {closeBusy ? '结项中…' : '确认结项'}
          </button>
          <button className="wb-ep-btn" onClick={() => setSuggestDone(null)}>暂不</button>
        </div>
      )}
      <div className="wb-ep-cols">
        {/* 左：立项单 Markdown 全文（renderMarkdown 复用 knowledge 渲染器 + wb-md 样式作用域） */}
        <div className="wb-ep-md">
          {detail === undefined ? (
            <div className="wb-ep-empty">加载立项单…</div>
          ) : (
            <div className="wb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.markdown) }} />
          )}
        </div>
        {/* 右：关联工单状态汇总（8s 轮询；degraded 黄条人话降级） */}
        <div className="wb-ep-side">
          <div className="wb-ep-panel">
            <div className="wb-ep-panel-title">关联工单{tickets?.count !== undefined ? `（${tickets.count}）` : ''}</div>
            {tickets?.degraded === true ? (
              <div className="wb-ep-degraded">{tickets.reason ?? '工单状态查询降级'}</div>
            ) : tickets === undefined ? (
              <div className="wb-ep-empty">加载工单状态…</div>
            ) : (
              <>
                <div className="wb-ep-chips">
                  {bucketKeys.map(k => (
                    <span key={k} className="wb-ep-bucket" data-b={k}>{k} × {merged[k] ?? 0}</span>
                  ))}
                  {bucketKeys.length === 0 && <span className="wb-ep-empty">本立项暂无关联工单。</span>}
                </div>
                {sorted.map(t => (
                  <div key={t.id} className="wb-ep-ticket"
                    title={onOpenTicket ? `${t.id}\n${t.title}\n点击查看工单详情` : t.id}
                    onClick={() => onOpenTicket?.(t.id)}>
                    <div className="l1"><span className="id">{t.id}</span><span className="ti">{t.title}</span></div>
                    <div className="l2">{t.status}{t.stage ? ` · ${t.stage}` : ''}{t.stage_state ? ` · ${t.stage_state}` : ''}</div>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </div>

      {/* 新建工单弹层（验收标准 9：模板下拉 + epic 界面传值只读展示，无手输框） */}
      {createOpen && (
        <div className="wb-ep-modal">
          <div className="wb-ep-modal-box">
            <div className="wb-ep-modal-title">新建工单 — 从立项 {code} 发起</div>
            {createHint !== '' && <div className="wb-ep-degraded">{createHint}</div>}
            <div className="wb-ep-field">
              所属立项（界面带入，不可修改）
              <div className="wb-ep-readonly">{code}</div>
            </div>
            <div className="wb-ep-field">
              工单模板
              <select className="wb-ep-input" value={createWf} onChange={e => { setCreateWf(e.target.value); setCreateAllowEmpty(false) }}>
                <option value="">请选择模板…</option>
                {templates.map(w => <option key={w.id} value={w.id}>{w.name}（{w.id}）</option>)}
              </select>
            </div>
            <div className="wb-ep-field">
              工单标题
              <input className="wb-ep-input" value={createTitle} onChange={e => setCreateTitle(e.target.value)}
                placeholder="一句话说明这张工单要做什么" />
            </div>
            <div className="wb-ep-field">
              工单正文（首行归属说明自动注入，可续写需求原文）
              <textarea className="wb-ep-input" style={{ minHeight: 140 }} value={createBody}
                onChange={e => setCreateBody(e.target.value)} />
            </div>
            <div className="wb-ep-field">
              写集（预计改动文件，每行一条；建票后为 agent 白名单护栏，方案定稿后自动扩展）
              <textarea className="wb-ep-input" style={{ minHeight: 64, fontFamily: 'monospace' }}
                value={createWsText} onChange={e => setCreateWsText(e.target.value)}
                placeholder={'server/engine/client.py\nserver/plugins/workbench/src/client/epics.tsx'} />
            </div>
            {/* 「无文件改动」显式声明（t260901-01）：空写集 + 勾选 → 建票放行（meta 记
                no_file_changes）。护栏警示：有文件改动的票必须填写集，勾了也绕不开 review。 */}
            <label className="wb-ep-sub" style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
              <input type="checkbox" style={{ marginTop: 3 }} checked={createAllowEmpty}
                onChange={e => setCreateAllowEmpty(e.target.checked)} />
              <span>
                本票无文件改动（allow_empty_write_set）——勾选后建票放行，meta 记 no_file_changes；
                <strong style={{ color: 'var(--dsw-derive-warn,#9a6700)' }}>仅限确无文件改动的票，有改动请填写集</strong>
              </span>
            </label>
            {createMsg !== '' && <div className="wb-ep-err">{createMsg}</div>}
            <div className="wb-ep-ops">
              <button className="wb-ep-btn wb-ep-btn-green" disabled={createBusy || !projectKey}
                onClick={() => { void submitCreate() }}
                title={projectKey ? '' : '先在左侧点选一个项目'}>
                {createBusy ? '创建中…' : '创建工单'}
              </button>
              <button className="wb-ep-btn" onClick={() => { setCreateAllowEmpty(false); setCreateOpen(false) }}>取消</button>
              {!projectKey && <span className="wb-ep-sub">未知新建落点项目——请先从左侧点选一个项目</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
