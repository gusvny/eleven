/**
 * sandbar-workbench · 侧栏接管 —— 双列布局（项目分组+工单 | 四视图）
 *
 * 注册到 sidebar.workspaces 槽（single，priority=-10 抢占 shell 默认浏览器——lowest renders）。
 * Shell 传 ownerProps: wide / expandSidebar。
 * wide=false 时只显品牌图标；wide=true 时显完整双列。
 *
 * 左列：项目组（可折叠，项目名分隔，只列进行中工单，两行式条目：行1=title，行2=彩色工单号 + role·创建时长）；
 *       每组头名前带项目色点（票② R7，projectColor 确定性色板）；组头下、工单
 *       列表上有项目内会话区一横排（session-entry 第 3 面①：正方形「+」+
 *       正方形数字 tab，编号=项目内登记顺序关闭不回收，超宽换行；+ 钮与激活
 *       tab 带项目色，票② R7；组件 project-session-row.tsx，动作=本组件
 *       useSessionEntry 实例）。
 *       顶部会话入口行已随票② R8 退役（t260904-05：顶部行组件及其
 *       顶部行样式族全清，src 无残留符号）；出厂「⊕ New Session」钮的隐藏注入**留守**
 *       （拍板 1：职责=压制全局新建入口，出厂钮不回显——useHideFactoryNewSession
 *       effect 以 aria-label（session-entry.tsx FACTORY_NEW_LABELS，zh/en 全集）
 *       在 SidebarRoot 直接子 button 上定位出厂钮置 display:none，零 CSS 类名
 *       匹配，MutationObserver 兜防复活，卸载/折叠 cleanup 还原）。
 *       记账层（localStorage 账册，只登记 UI 主动打开/新建；磁盘存量/工单/
 *       subagent 会话不进账册）供项目内会话区消费，规则=shared/sessions.ts。
 *       右栏 chat 项目色带（票② R7）：chat-project-band.ts 装饰器，归属=
 *       listState.current → 账册 project 推导（下方 effect），不在册不渲染。
 *       项目组头行右对齐五个项目级视图入口图标（票③ 11b 统一 SVG 图标族）：工单列表 /
 *       文档 / 模型路由 / 立项单 / 项目设置（第五枚=面D 设置弹层入口）
 *       （t260905-06：旧提法退役，原位换「文档」入口——仓根 docs/ 定稿库人读
 *       视图 + notes/ 观察窗；t260915-10 起默认跟随本行项目，页内选择器可手动切）
 *       （t260827-01：立项单从「左列可折叠列表区」改为项目级图标，与其他三视图同款；
 *       左列不再显示立项列表，点图标后中列显示立项清单）。
 *       项目组 = server/projects.yaml 注册表（260823 多项目化：project 是逻辑概念，
 *       1:N 对应目录）；每组工单按 ?project=<key> 单独拉取（Temporal ProjectKey SA 过滤）。
 *       t260915-19 起左栏收录巡检票：巡检 workflow 因引擎类型过滤隔离进不了
 *       ?project= 通路（client.py cmd_ticket_list 缺省只拼 dev-lane 模板类型），
 *       故左栏并行拉 /wf/inspection/tickets 端点做**客户端分拣**——行 project
 *       （t260915-20 起=ProjectKey SA 真源）命中在册项目后与该项目 dev 行合并、
 *       统一口径排序（t260916-15 宿主实报「巡检票恒沉底」：在等你/受阻→在跑→
 *       已完成，级内 updated_ts 倒序，巡检行不因数据来源沉底），空/不在册
 *       （20 之前老票、隔离 key）落「巡检」兜底组（显式不静默丢失）；巡检行带
 *       类别徽标（INSPECTION_ROW_BADGE chip）一眼可辨数据来源。
 * 中列：四视图由 index.tsx 注入（views prop）——工单台 WorkbenchSection（本插件）、
 *       (since t261008-36 Model routes and Project settings open from the executor
 *       panel's Settings tab; the view registry carries only the WorkbenchSection
 *       overlay host, and executor-view.tsx owns ProvidersSection — index.tsx no
 *       longer injects it). EpicSection (this plugin, t260826-02: empty code =
 *       charter list, a code = detail face).
 *       260823 起它们不再占 chat 顶部页签。t260903-07 起：点工单只在中列开详情抽屉，
 *       右栏 chat 恒为单全局会话不再切换（每工单会话联动下线，数据留存）。
 *       未选项目时中列显占位（不自动选第一个项目——不造隐形缺省）。
 */

import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import type { ComponentType, CSSProperties } from 'react'
// 会话列表快照类型（t260828-02 起只取 displayTitle/current 两字段）：ctx.sessions.list 的面。
import type { ObservableSnapshot, SessionListState } from '@deepseek-ai/dsh-client-runtime/client'
// 会话动作层与出厂钮语义锚（票② R8 后 session-entry.tsx 只剩动作层，无渲染面；
// session-entry.tsx 持有 LEDGER_KEY / useSessionEntry hook）。
import { FACTORY_NEW_LABELS, useSessionEntry } from './session-entry.tsx'
// 项目内会话区（session-entry 第 3 面①，R1–R7）：每项目组头下、工单列表上的
// 一横排（+ 钮 + 数字 tab + 确认弹层）；动作由本组件的 useSessionEntry
// 实例注入（账册=模块级共享 store）。
import { ProjectSessionRow } from './project-session-row.tsx'
// 存量编号迁移（第 3 面① 拍板 1）：账册缺 seq 条目按项目内登记序补号（幂等）。
import { backfillProjectSeqs, labelOf, rowLabelOf } from '../shared/sessions.ts'
import { displayHandle } from '../shared/session-handles.ts'
import { fetchProjectLedger, getLedgerSnapshot, persistLedger } from './session-ledger-store.ts'
// 插件陈旧全局提醒（t260902-03 立；t260905-07 KI-052 握手矩阵接线）：useStaleBanner
// 单例挂本组件；横幅渲染在 .wb-sb-right 共享容器，文案常量同源消费（banner-text.ts，
// 场景断言锚 KI-051 纪律）。
import { useStaleBanner } from './staleness.ts'
import { STALE_BANNER_TEXT, STALE_RELOAD_TEXT } from './banner-text.ts'
import { startVisibleInterval } from './visibility-poll.ts'
import type { SessionsFace } from './session-entry.tsx'
// 项目索引单态（t260903-07 工单②）：load() 成功分支向 chat 项目 tag 装饰器发布
// 项目集与逐项目工单映射（失败分支不发——KI-018 同族：失败不得顶掉 last-known-good）。
import { publishProjectEntry, publishProjects } from './project-tag-index.ts'
// chat 项目 tag 装饰器（t260903-07 工单②）：挂/卸随本组件生命周期（插件在装即挂）。
import { startChatProjectTagEffect } from './chat-project-tag.ts'
// chat 项目色带装饰器（票② R7）：锚=平台自声明 [data-conversation-scroll]，
// 挂/卸随本组件生命周期；归属推导见下方 effect（current→账册 project）。
import { startChatProjectBandEffect, setChatProjectBandInfo } from './chat-project-band.ts'
// 上下文折叠件（t260905-04）：带 CHARTER_MARKER 的注入消息收成可展开小条。
import { startContextFoldEffect } from './context-fold.ts'
// Platform banner-row hide (t261007-07, closing item of the 261004 topbar
// note): hide the platform's left-column logoRow (brand mark + fold toggle).
// Anchor = the fold toggle's aria-label set; root landmark = our own brand row
// [data-wb-brand-row] (review C1: never a blind parentElement — walk up to the
// ancestor containing the landmark and tag the whole chain; unresolved =
// guard, hide nothing + exactly one warn). See platform-banner.ts header.
import { startPlatformBannerHideEffect } from './platform-banner.ts'
// Project colour (ticket 2 R7): deterministic palette, same key always same colour.
// Since UI-4 (t261005-05): the group-head colour dot is retired for the identity
// badge; projectColor stays only a chat-project-band concern, unused in this file.
// UI-4 (t261005-05): project identity badge single source (colour x outline x
// structure, same identity as the panel).
import { projectBadgeSvg } from '../shared/project-identity.ts'
// UI-1 (t261005-09): project colour for the group block (3px left bar + 6% selected
// wash, design source: 261004 chat-identity-and-session-handles note section 2.5,
// Chinese-named file in notes/discussions/). projectColor re-exports
// the UI-4 single-source palette/fallback (same key, same colour).
import { projectColor } from '../shared/project-color.ts'
import { hexToRgba } from './chat-project-band.ts'
// 项目组头图标族（票③验收 11b）：五枚 SVG 线性图标（规格单源见模块头注）。
import { ProjectIcon } from './project-icons.tsx'
import type { ProjectIconName } from './project-icons.tsx'
// 项目生命周期四弹层（票③面D：设置/接入/摘除/隔离详情，验收 11-13）。
import { ProjectAddModal, QuarantineModal } from './project-modals.tsx'
// t260904-17 列表 v5：左栏工单条目=行卡迷你版（一套 UI 裁定，与中列同一组件/模型层）。
import { TicketRowCard } from './ticket-row-card.tsx'
// t260916-15 左栏合并排序：纯函数住 ticket-list-model 模型层（复用 deriveTicketState
// 四态单点投影 tier，不另起状态词表；node 可裸 import UT 直测）。
// t261009-43: the dismissal face readers (dismissed voucher, named note, the
// order-preserving kept/dismissed split) live in the same pure layer.
import { sortMergedTickets, isDismissedRow, splitDismissedRows } from './ticket-list-model.ts'
// t261008-21 (host order 261008 option A): the closed dev-lane dwell window is
// pinned at 24 h; the window rule lives in sandbar-dwell (pure layer, UT-covered)
// and this is its only consumer (two-window split below — inspection rows exempt).
import { inSandbar } from './sandbar-dwell.ts'
// CL-3 (t261006-18) left-column ticket order: concurrency read-face projection
// and move pure functions (node imports them directly for black-box UT).
// Route constants are verbatim same-source with node.ts handleConcurrency
// (KI-042 discipline: change one, sync the other, run both UTs).
import {
  parseConcFace, concFaceFromReply, orderKindOf, moveTicket, reorderMoveTo, permutationOf,
  stageDotsLit, faceCounts,
  type ConcFace,
} from './queue-model.ts'
// t261011-15: the dismiss/restore request URL builder (pure, node-testable).
import { dismissRequestUrl } from './ticket-list-model.ts'
const CONCURRENCY_URL = '/sandbar-workbench/api/wf/concurrency'
const CONCURRENCY_REORDER_URL = '/sandbar-workbench/api/wf/concurrency/reorder'
// t261009-43: the person's dismissal write face (engine ops dismiss/restore,
// t261009-31 CLI behind it; who/reason both required non-empty). KI-042
// discipline: verbatim same-source with node.ts's op route path — NOTE the
// route whitelist entry lives in node.ts, OUTSIDE this ticket's write set
// (named debt on the ticket; the client contract is fixed and stub-tested).
// t261011-15: the URL builders delegate to the model-layer helper — the
// per-request project anchor rides `?project=` (node.ts anchorOf ->
// caller_project; the POST body stays the engine contract {who, reason}).
// A blank project key (unowned inspection group) omits the query: no view
// key, no guessing (the route's own discipline at node.ts:1258-1260).
const DISMISS_URL = (projectKey: string, id: string): string =>
  dismissRequestUrl(projectKey, id, 'dismiss')
const RESTORE_URL = (projectKey: string, id: string): string =>
  dismissRequestUrl(projectKey, id, 'restore')
// t261009-43: the person identity for dismiss/restore. Mirrors index.tsx
// operatorOf (SAME localStorage key = one person identity per browser); a
// local copy because importing index.tsx from the sidebar is a forbidden
// circular import (sidebar is index's child).
const OPERATOR_KEY = 'sandbar-workbench-operator-v1'
function sidebarOperator(): string {
  try {
    const old = localStorage.getItem(OPERATOR_KEY)
    if (old) return old
    const id = 'op-' + Math.random().toString(36).slice(2, 8)
    localStorage.setItem(OPERATOR_KEY, id)
    return id
  } catch { return 'op-local' }
}
// t260929-22 执行器入口视图（GAP A）：项目行=入口，中列 Executor/Chat 切换器；
// 判定纯层在 executor-view-model.ts（tests/executor-entry-model.mjs 看守）。
import { ExecutorView } from './executor-view.tsx'
// t260915-19 左栏收录巡检票：分拣/降级/进展纯函数与端点串单点住 host 层
// （node 可裸 import 黑盒单测，tests/t260915-19-sidebar-inspection.mjs 看守）。
// 照搬取舍收拢（review gen2 落实项）：①viewProject 兜底首项目=openEpic 先例；
// ②降级词表=中列 08 同源不另起；③inspection_filter.degraded 左栏不带横幅
// （理由见渲染处注释）；④场景范式=08 board-ui 两层式 ENV_FAIL 三态。
import {
  INSPECTION_ROW_BADGE, INSPECTION_TICKETS_URL, INSPECTION_TOPOLOGY, isInspectionRow, inspectionDegradedNote,
  inspectionProgressOf, inspectionSplitByProject,
} from '../host/inspection-face.ts'
// metrics M2a（t260902-01）：度量面板。t260902-05 起：入口迁出厂侧栏
// footer.action 槽（与 dsh settings 同排，用户反馈①），面板中 pane 化挂进
// .wb-sb-right（反馈②）。槽注册失败软退化回 .wb-sb-foot 兜底钮（console.warn）。
// ⚙ settings 弹层（收 sandbar 驻留输入）保留在中列底部——工单台自有设置，
// 与出厂 settings 语义不同（t260902-05 方案 v2 R6-① 决策）。下钻：关面板后走
// handleTicketClick 开详情抽屉。
// t261005-10 (UI-2): the sidebar metrics entrance (all three levels) and its
// CustomEvent bus are retired wholesale — Metrics lives in the panel's Metrics tab.
import { DERIVE_TOKENS_CSS } from './theme';

/* ---------------------------------------------------------------- 类型 */

/* t260903-07（用户拍板）：每工单会话联动下线——右侧 chat 恒为单全局会话，
 * 点工单只在中列开详情抽屉，不再建/找/切 `ticket-<id>` 会话。
 * 原 openTicketSessionFlow（t260831-08 会话恢复链）连同 TicketSessionFlowDeps
 * 整体删除（无其他消费方）。服务端 /api/ticket-session/open 路由与既有
 * ticket-* 会话数据按 ③ 口径留存（node.ts 两处留痕注释），回滚面完整。
 * 设计文档《sidebar-session-entry-and-hero-design.md》目标5/Nongoal 被本票推翻——
 * 同步债见 notes/debts/design-doc-sync-t260903-07.md（后续读者以债条目为准）。 */

/** Minimal workflow-topology projection for the left column (CL-3 ten-cell dots; /wf/workflows rows are a superset, extra fields ignored). */
interface WfLite {
  id: string
  stages?: { id?: string }[]
}

interface Ticket {
  id: string
  /** Project key (registry; host ticket-list rows carry the project field). */
  project?: string
  title: string
  stage: string
  stage_state: string
  /** 生命周期状态机：dispatched→settled→verified→closed/rework。 */
  status: string
  workflow: string
  role: string
  worktree: string
  base_ref: string
  /** 创建时间（unix 秒）。 */
  created?: number
  /** 收口时间（unix 秒；COMPLETED 执行的 close_time，sandbar 驻留判定用）。 */
  close_ts?: number
  /** 更新时间（unix 秒；引擎行恒带，t260916-15 组内合并排序的时间源）。 */
  updated_ts?: number
  blocked_reason?: string
  /** t260919-02: Temporal exec status (the five-state derivation's third input;
   *  the left column's dwell failure-class settlement reads it too). */
  exec_status?: string
  /** t261009-43: the engine's dismissal voucher (t261009-31 row augmentation;
   *  truthy plain object = the LAST journal row is a dismiss). Read via
   *  isDismissedRow, never invented, never flipped locally. */
  dismissed?: unknown
  /** t261009-43: the engine's named note when the dismiss journal read failed
   *  (the dismissed key is absent then); the row stays and the note surfaces. */
  dismissed_note?: unknown
  pending?: { gate: string; reason: string }[]
  session_kb?: number
  agent_alive?: boolean
}

/** 巡检端点行的左栏消费形状（t260915-19；引擎行超集投影，多字段不关心）。 */
interface InspectionTicket extends Ticket {
  /** 引擎标记：巡检行="inspection"（行卡 data-engine 发射源，等你黄调作用域键）。 */
  engine?: string
  /** 待签标记（引擎行常带；判定以 stage_state 为准——inspectionProgressOf 单点）。 */
  awaiting_gate?: boolean
  /** 收口健康度判定面（t260921-03 键只加）：行卡健康徽标与合并排序插层（tier2）
   *  经共享模型 closeHealthOf 生效——左栏零新词表，字段只是透传。 */
  kind?: string
  report_path?: string
  close_health?: string
  close_health_reason?: string
}

/** 项目注册表条目（GET /wf/projects）。 */
interface Project {
  key: string
  name: string
  dirs: string[]
  /** 主目录（dirs 首个）：模型路由/会话 cwd 兜底都走它（t260905-06 起「文档」视图=仓根 docs/，不走它）。 */
  primary: string
}

/** 中列视图，由 index.tsx 注入（避免 sidebar→index 循环 import；t260826-02 起三视图 + 立项单第四视图）。 */
interface MiddleViews {
  /** Ticket-detail overlay + machine-level status head host (the middle column's
   *  only host surface since t261005-10; the board view is deleted — the overlay
   *  machinery stays, opened by left-column rows and panel-tab rows). */
  overlay: ComponentType<{ focusId?: string; focusNonce?: number; listNonce?: number; projectKey?: string }>
}

interface SidebarProps {
  /** Shell 侧栏折叠态：true=展开，false=轨条（仅图标）。 */
  wide: boolean
  /** 请求展开侧栏（轨条下点击图标触发）。 */
  expandSidebar: () => void
  /** 客户端 sessions 服务（open 导航到会话；scope 取会话域 ctx 以注入首条上下文；
   *  refresh 强制拉列表——host 新建 session 经 list 流同步有延迟，open 未列出的 id 直接 throw；
   *  list=会话列表快照——t260828-02 起「会话」区只从它取 displayTitle/current
   *  （列表本体=插件记账层）；index.tsx 传的 ctx.sessions 全量本就有它，此处只是补上类型）。 */
  sessions: {
    open(id: string): void
    scope(id: string): any
    refresh?(): Promise<unknown>
    list: ObservableSnapshot<SessionListState>
  }
  /** 槽注入的会话打开动作（WorkspaceBrowserInjected.open，默认浏览器同款路径；
   *  260824 起优先于 sessions.open——后者要求 id 已在客户端 list，ticket 会话
   *  同步稍慢时会 fail loud）。由 slot props 透传（apply() 里 {...props}）。
   *  t260831-04 勘误：WorkspaceBrowserInjected 是 ui-workspace 注册者私有
   *  注入，slot owner props 里没有 open——本 prop 恒 undefined，历史分支仅留
   *  兼容，真正的新建语义走下方 workspaces 公开服务。 */
  open?: (sessionId: string) => void
  /** 客户端 workspaces 服务（index.tsx 的 ctx.workspaces）：0.1.5 起＝**纯控制器**
   *  （dsh-api-workspace-controller），不再是 startSession 的所在面（260923 勘误）。 */
  workspaces?: {
    list: ObservableSnapshot<{ items: readonly { workspaceId: string; path: string }[] }>
    startSession?(workspaceId?: string): void
    create(input: { path: string }): Promise<{ workspaceId: string }>
  }
  /** 免注入的服务查找口（index.tsx 传 `ctx.get` 绑定）：**0.1.5 起** startSession
   *  在 `uiWorkspace` 服务上，须经此口取（属性形式 `ctx.uiWorkspace` 未 inject 即抛
   *  `cannot get property ... without inject`，260923 实弹）。点击时惰性解析。 */
  getService?: (name: string) => unknown
  /** 中列三视图（index.tsx 注入）。 */
  views: MiddleViews
}

// t261005-10 (UI-2): executor panel = the middle column. t261008-36: the 'routes'
// view retired — Model routes and Project settings open from the panel's Settings
// tab (executor-view.tsx face overlay); the More-views escape hatch is gone.
type RightView = 'executor'

/** 巡检行卡的 wf 形状（t260915-19）：compact 无站道点，仅喂悬停阶段短名；
 *  拓扑=宿主声明面单点（host/inspection-face.ts），不 import index.tsx 防循环。 */
const INSPECTION_WF_LIKE = { stages: INSPECTION_TOPOLOGY }

/* ---------------------------------------------------------------- 口径 */

/**
 * 状态色（用户拍板口径）：红=有问题（blocked/rework）、黄=待审核（awaiting-human/settled）、
 * 蓝=运行中（running）、绿=完成（verified/closed）、灰=等待（awaiting）。
 */
/** 未完成 = 生命周期未收口（dispatched/settled/rework）。项目组里只列这些。 */
const isOpen = (t: Ticket): boolean => t.status !== 'closed' && t.status !== 'verified'

/* ---------------------------------------------------------------- 样式 */

const CSS = `${DERIVE_TOKENS_CSS}
.wb-sb { display:flex; flex-direction:column; height:100%; /* t260905-08：底改自适应 alias（平台 fill 层级高于 :root 注入无法跟随看守档位，可读性收敛到 alias 对）；装饰性 fill 见 --dsw-specific-sidebar-fill 保留在 group-head */ background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); color:var(--dsw-derive-fg,#1f2328); font-size:12px; }
/* 轨条态：仅图标 */
.wb-sb.rail { width:48px; align-items:center; padding-top:12px; }
.wb-sb.rail .wb-sb-icon { width:28px; height:28px; border-radius:6px; background:var(--dsw-alias-brand-primary,#7c3aed); display:flex; align-items:center; justify-content:center; font-size:14px; cursor:pointer; }
/* 展开态：双列。整窗三栏比例 左(项目+工单)15% : 中(视图)60% : 右(chat)25% ——
   左+中=侧栏占 75%（见下方 frame 第一轨改写），侧栏内部左右子列按 1:4 分。 */
.wb-sb.wide { flex-direction:row; }
/* t260929-22 gen3 勘误（arbitration A/B 实证）：gen2 曾把左列 min-width 提到
   320px 给入口段让宽——被 t260904-17/t260915-09 双场景 A/B 实证为破坏壳层几何的
   单变量（shell resize handle 压住内容），此处归还 180px。gen4 勘误：gen3 的
   行下悬停图标条同样改了行外命中面（t260915-09 A/B 实证），随之退役；可达性
   最终落点=图标簇行内收纳（见 .wb-view-icons gen4 注）。 */
.wb-sb-left { flex:0 1 380px; min-width:180px; display:flex; flex-direction:column; border-right:1px solid var(--dsw-alias-border-l1,#333); }
/* CL-3 (t261006-18, design §2.2): the left column's width base becomes 380px
   (flex-basis; "below 340px the titles are cut too hard"). min-width keeps the
   frozen 180px contract (t260929-22 arbitration A/B proof: raising min-width
   crushes the shell resize geometry) - normal windows get 380px, the column
   may shrink under shell pressure instead of fighting the shell. */

/* position:relative —— 工单详情抽屉（index.tsx .wb-drawer，absolute）的定位祖先，
   让抽屉铺满中列而不是全窗（260824 用户拍板：详情显在中列）。 */
.wb-sb-right { flex:4 1 0; display:flex; flex-direction:column; overflow:hidden; min-width:200px; background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); position:relative; }
/* host 陈旧全局提醒（t260902-03）：中列共享容器顶部横幅，flex:none 不挤占四视图与
   下栏；琥珀底一眼可辨，与 running 绿/blocked 红色板错开。 */
.wb-stale-banner { flex:none; display:flex; align-items:center; gap:10px; padding:8px 12px;
  background:var(--dsw-derive-dark-warn-bg,#7a4a06); color:var(--dsw-derive-dark-warn-fg,#ffe9c4); border-bottom:1px solid var(--dsw-derive-warn,#b8860b); font-size:12px; }
.wb-stale-banner .wb-stale-msg { flex:1; line-height:1.5; }
.wb-stale-banner .wb-stale-msg strong { color:var(--dsw-derive-dark-amber,#ffd166); }
.wb-stale-banner .wb-stale-dismiss { flex:none; border:1px solid var(--dsw-derive-warn,#b8860b); background:transparent;
  color:var(--dsw-derive-dark-warn-fg,#ffe9c4); border-radius:6px; padding:2px 10px; font:inherit; font-size:12px; cursor:pointer; }
.wb-stale-banner .wb-stale-dismiss:hover { background:rgba(255,255,255,0.12); }
/* Bottom strip under the middle column (fixed height, from metrics M2a).
   t261008-21: the metrics entrance and the gear Settings popover are both
   retired; only the spacer span remains, holding the original height (no reflow). */
.wb-sb-foot{display:flex;align-items:center;gap:8px;height:34px;padding:0 10px;border-top:1px solid var(--dsw-alias-border-l1,#333);flex:none;font-size:12px}
.wb-sb-foot-sp{flex:1}
/* 项目组 */
.wb-ticket-list { flex:1; overflow-y:auto; }
/* UI-1 (t261005-09): brand first row — replaces the old "Projects" header slot.
   26px, zero extra height (the row *is* the header; no separate top banner is
   added). Mark = the "slanting sandbar" logo (261004 topbar-banner design note
   section 3, candidate C: two offset rounded slanted bars; Chinese-named file in
   notes/discussions/). No fold button, no theme button (both
   ruled out in the same design note). Hiding the platform's own topbar banner is
   a named follow-up (anchor+guard discipline), NOT done here — worst accepted
   case is the platform banner remaining visible, never a blank sidebar. */
.wb-brand-row { display:flex; align-items:center; gap:6px; height:26px; flex:none;
  padding:0 10px; border-bottom:1px solid var(--dsw-alias-border-l1,#333); }
.wb-brand-mark { display:inline-flex; flex:none; line-height:0; }
.wb-brand-word { font-weight:600; font-size:12px; }
.wb-brand-count { margin-left:auto; font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; }
/* UI-1 (t261005-09) as revised by t261008-08 (mock v11 alignment): the project
   block drops its 3px project-colour left bar — the mock's .proj carries only a
   bottom hairline; project identity stays on the badge + name. The selected
   block keeps its 6% colour wash (colour is not the only channel). */
.wb-project-block { border-bottom:1px solid var(--dsw-derive-border,#d0d7de); }
.wb-project-block[data-selected=true] { background:color-mix(in srgb, var(--wb-proj-color, transparent) 6%, transparent); }
.wb-group-head { display:flex; align-items:center; gap:5px; padding:7px 8px 5px; cursor:pointer; font-weight:600; position:sticky; top:0; background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); z-index:1; }
.wb-group-head:hover { background:rgba(255,255,255,0.05); }
.wb-group-caret { font-size:9px; color:var(--dsw-derive-muted,#57606a); width:10px; }
/* t260929-22 gen1（acceptance 打回）：入口段=名字+计数+弹性空档，flex:1 吃掉
   行内非图标区——1280 宽默认窗下项目名可读可点（行中部点击落入口段不落图标）；
   name min-width:0 只为 ellipsis 生效，宽度由入口段保证。 */
.wb-group-entry { flex:1 1 0; min-width:0; display:flex; align-items:center; gap:5px; cursor:pointer; }
.wb-group-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.wb-group-count { margin-left:auto; font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; flex:none; }
/* CL-3 (t261006-18): the project row reports two numbers on the right, X at work / Y waiting (numbers only, no sentences). */
.wb-group-conc { font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; flex:none; white-space:nowrap; }
/* Line-1 order marks: queued = leading position number; at-work = green dot; human-hold / paused = amber dot (no ordering controls). */
.wb-order-pos { flex:none; min-width:14px; text-align:center; font-size:10px; font-weight:600;
  color:var(--dsw-derive-accent,#0969da); background:color-mix(in srgb,var(--dsw-derive-accent,#0969da) 12%,transparent);
  border-radius:4px; padding:0 3px; line-height:14px; }
.wb-order-dot { flex:none; width:8px; height:8px; border-radius:50%; }
.wb-order-dot[data-order-dot=work] { background:var(--dsw-derive-success,#1a7f37); }
.wb-order-dot[data-order-dot=hold], .wb-order-dot[data-order-dot=paused] { background:var(--dsw-derive-warn,#b8860b); }
/* Ordering controls: handgrip (drag anchor) + up/down arrows, rendered on data-order-kind=queued rows only.
   t261008-08 (mock v11): the controls sit at the ROW END (margin-left:auto eats
   the slack after the title); the position number stays first, grip right after it. */
.wb-order-ctl { display:inline-flex; align-items:center; gap:1px; flex:none; margin-left:auto; }
.wb-order-grip { cursor:grab; font-size:9px; letter-spacing:-1px; color:var(--dsw-derive-muted,#57606a); user-select:none; line-height:1; }
.wb-order-grip:active { cursor:grabbing; }
.wb-order-arrow { border:none; background:none; cursor:pointer; font:inherit; font-size:9px; line-height:1;
  color:var(--dsw-derive-muted,#57606a); padding:1px 2px; border-radius:3px; }
.wb-order-arrow:hover { background:rgba(255,255,255,.08); color:var(--dsw-alias-label-primary,#1f2328); }
.wb-order-arrow:disabled { opacity:.4; cursor:default; }
/* Line-2 ten-cell progress dots (design §7.2 default): lit up to the current stage, zero extra row height. */
.wb-stage-dots { display:inline-flex; align-items:center; gap:2px; flex:none; }
.wb-stage-dot { width:5px; height:5px; border-radius:1px; background:var(--dsw-derive-border,#d0d7de); }
.wb-stage-dot[data-on=true] { background:var(--dsw-derive-accent,#0969da); }
/* Reorder-refusal notice (A7): one line with the engine's refusal verbatim (same token family as .wb-insp-degraded, no new palette). */
.wb-order-notice { margin:2px 8px 6px 14px; padding:4px 8px; font-size:10px; line-height:1.5;
  color:var(--dsw-derive-dark-warn-fg,#ffe9c4); background:var(--dsw-derive-dark-warn-bg,#7a4a06);
  border:1px solid var(--dsw-derive-warn,#b8860b); border-radius:5px; word-break:break-all; }
.wb-group-empty { padding:2px 8px 8px 24px; color:var(--dsw-derive-fg,#666); font-size:11px; }
/* t260904-17 list v5: ticket entries = compact TicketRowCard — dark-theme
 * overrides: transparent base, inherited text colour, selected violet wash;
 * closed (data-state=done) dimmed one step.
 * t261008-08 (mock v11): left-column rows drop the inherited 4px epic bar (the
 * mock's .tk row has none) — border-left-width:0 offsets the board baseline
 * (index.tsx .wb-card border-left-width:4px); belt-and-braces with the
 * component side, which no longer writes the borderLeftColor inline colour
 * when compact. */
.wb-sb .wb-card { background:transparent; border-color:var(--dsw-derive-border,#d0d7de);
  border-left-width:0;
  box-shadow:none; color:var(--dsw-derive-fg,#1f2328); margin:0 6px 4px 14px; padding:5px 8px; }
.wb-sb .wb-card:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-sb .wb-card[data-active=true] { background:color-mix(in srgb,var(--dsw-derive-active,#7c3aed) 18%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); border-color:color-mix(in srgb,var(--dsw-derive-active,#7c3aed) 50%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); }
.wb-sb .wb-card[data-state=done] { opacity:0.72; } /* 对齐板面 .72：0.55 时次级字混底后 <3:1（看守实测） */
.wb-sb .wb-card-title { color:inherit; font-weight:400; }
/* t261008-08 (mock v11): compact line 2 stage small text — 10px muted, same
   token family as the l2 meta (stage · epic · dots per the mock's .tk .l2). */
.wb-sb .wb-card-stage { flex:none; font-size:10px; color:var(--dsw-derive-muted,#57606a);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
/* t260929-22 gen8（对比度打回实测 rgb(122,122,133)≈4.24 元凶）：左栏 mini 行卡
   状态字曾一律 inherit（继承左栏弱化灰），改按四态消费语义令牌（gen8 起令牌为
   浅档深墨声明位，白底全部 ≥4.5）。 */
.wb-sb .wb-card-state { color:var(--dsw-derive-muted,#57606a); }
.wb-sb .wb-card-state[data-state=waiting] { color:var(--dsw-derive-warn,#7d4e00); }
.wb-sb .wb-card-state[data-state=blocked],.wb-sb .wb-card-state[data-state=failed] { color:var(--dsw-derive-danger,#cf222e); }
.wb-sb .wb-card-state[data-state=active] { color:var(--dsw-derive-accent,#0969da); }
/* t260905-08：原深档固定蓝字——平台浅档下失读（宿主实报同病），归主规则令牌 */
.wb-sb .wb-card-id { color:var(--dsw-derive-accent,#0969da); }
/* t260915-19 左栏「等你」黄调（巡检行）：与中列同 token（index.tsx
 * .wb-root .wb-card[data-state=waiting] 同源色板）——作用域=data-engine=inspection
 * 等值选择器（review C1：dev-lane 行 data-engine 在场-异值 "template-as-code-v2"，
 * 等值判定天然零命中；测试禁写「属性缺席」断言）。项目组行渲染零变化。 */
.wb-sb .wb-card[data-engine=inspection][data-state=waiting] { background:var(--dsw-derive-warn-bg,#fff8c5); }
/* t260916-15 巡检行类别徽标：行1 小 chip（琥珀描边字色=等你黄调族 token，透明底
 * 不与 data-state 底色语义混写）。作用域 .wb-sb=只有左栏消费 kindBadge（中列板面
 * 零变化）；任何状态（在跑/收口）都恒带徽标=数据来源可辨不依赖状态/位置。 */
.wb-sb .wb-card-kind { display:inline-flex; align-items:center; flex:none; padding:0 5px;
  border:1px solid var(--dsw-derive-warn,#b8860b); border-radius:5px;
  color:var(--dsw-derive-warn,#b8860b); font-size:10px; line-height:15px; }
/* t260915-19 巡检降级横幅：色板同 .wb-stale-banner 族（琥珀），不另起色板。 */
.wb-insp-degraded { padding:6px 10px; font-size:11px; line-height:1.5;
  color:var(--dsw-derive-dark-warn-fg,#ffe9c4); background:var(--dsw-derive-dark-warn-bg,#7a4a06);
  border-bottom:1px solid var(--dsw-derive-warn,#b8860b); }
/* t261009-43: the dismissed fold — a count row per project ("N dismissed",
   never a done-family word), caret + count + hint, rows expand in place. */
.wb-dismissed-fold { margin:2px 6px 6px 14px; }
.wb-dismissed-head { display:flex; align-items:center; gap:5px; padding:3px 6px; cursor:pointer;
  border-radius:5px; color:var(--dsw-derive-muted,#57606a); font-size:11px; user-select:none; }
.wb-dismissed-head:hover { background:rgba(255,255,255,0.05); }
.wb-dismissed-label { font-weight:600; }
.wb-dismissed-hint { font-weight:400; font-size:10px; color:var(--dsw-derive-muted,#57606a); }
/* t261009-43: the dismiss affordance is deliberately low-key (a quiet action,
   never a close/done button): transparent, muted ink, border only. */
.wb-sb .wb-card-btn-dismiss { background:transparent; color:var(--dsw-derive-muted,#57606a);
  border:1px solid var(--dsw-derive-border,#d0d7de); }
.wb-sb .wb-card-btn-dismiss:hover { color:var(--dsw-alias-label-primary,#1f2328); }
/* t261009-43: the journal-read-failure note chip (amber family, same tokens as
   .wb-card-kind — an explicit "the dismissal face is unreadable", never silent). */
.wb-sb .wb-card-dismiss-note { display:inline-flex; align-items:center; flex:none; padding:0 5px;
  border:1px solid var(--dsw-derive-warn,#b8860b); border-radius:5px;
  color:var(--dsw-derive-warn,#b8860b); font-size:10px; line-height:15px; }
/* t261009-43: the reason prompt (bottom of the left column, one at a time). */
.wb-dismiss-prompt { flex:none; margin:6px; padding:8px; border:1px solid var(--dsw-alias-border-l1,#333);
  border-radius:8px; display:flex; flex-direction:column; gap:6px;
  background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); }
.wb-dismiss-prompt-title { font-size:11px; font-weight:600; }
.wb-dismiss-reason { font:inherit; font-size:11px; min-height:44px; resize:vertical;
  border:1px solid var(--dsw-alias-border-l1,#555); border-radius:5px; padding:4px 6px;
  background:transparent; color:inherit; }
.wb-dismiss-prompt-actions { display:flex; gap:6px; }
/* 视图入口图标：右对齐放在每个项目组头行内（用户拍板 260823：per-project，不占独立行；
   t260827-01 起四个：工单/文档/模型/立项单；t260905-06 旧提法退役换文档）。
   t260929-22 gen4（宿主 260929 裁决落地：260927 设计胜、260823 放宽由 developer 落地、
   栏宽 180 冻结、行外不许有改命中面的层——gen3 的行下悬停条被 t260915-09 A/B 实证
   截住 .wb-psess 会话行的点击，此形态整体退役）：行内常驻=工单+立项单两枚场景钉住的
   图标 + 一枚「More views」展开钮；其余三枚（文档/模型路由/项目设置）收进展开位，
   展开也在流内（行自身盒内，零绝对定位、零外溢命中面）；展开时入口段名字瞬态让位，
   (expansion stays in flow; anchor behavior unchanged; the geometry contract of
   gen1 times holds: row height, rail width, 26x26 hit area). t261008-36: the More-views toggle and both remaining icons retired wholesale —
   Model routes and Project settings open from the executor panel's Settings tab
   (one face, one home; no second door). The .wb-view-icons/.wb-view-icon styles
   below stay as a neutral geometry contract with no consumer today. */
.wb-view-icons { display:flex; gap:2px; }
/* 图标族统一（票③ 11b）：命中区 26×26 radius 6，显形 18px（svg 由 ProjectIcon 定）；
   三态 idle/hover/active 沿用本侧栏既有色板（深色语境；mock 规格卡三态色为浅色
   语境定稿——图标本体吃 currentColor，几何规格统一是本模块契约）。 */
/* 图标族统一（票③ 11b）：命中区 26×26 radius 6，显形 18px（svg 由 ProjectIcon 定）；
   三态 idle/hover/active 沿用本侧栏既有色板（深色语境；mock 规格卡三态色为浅色
   语境定稿——图标本体吃 currentColor，几何规格统一是本模块契约）。
   t260929-22 gen2 勘误：gen1 曾把命中区缩到 20px 给入口段让宽——被 t260904-17
   A/B 实证为该场景新红单变量，此处恢复冻结契约 26×26（入口可达性见 .wb-view-icons
   gen3 注：悬停现形，不再动任何几何）。 */
.wb-view-icon { width:26px; height:26px; display:flex; align-items:center; justify-content:center; border-radius:6px; cursor:pointer; opacity:0.55; }
.wb-view-icon:hover { background:rgba(255,255,255,0.1); opacity:1; }
.wb-view-icon.active { background:rgba(124,58,237,0.25); opacity:1; }
/* t260929-22 直修（宿主令 260930，integration 执行）：.wb-view-icon 静息档 0.55 透明度
   用在**文字字符**图标（⋯ 更多视图）上时，合成后的有效色在白底只到 3.50、旧平台面
   3.43——透明度压不出 AA（0.55 时即便纯黑也只 4.75，实际墨色达不到）。本元素改走
   muted 墨色（极性自适应）：静息仍是弱化观感，两档都 ≥4.5，几何零改动。
   其余 view icon 不用文字字符（SVG），不受本规则影响。 */
/* t261008-36: the More-views rest-state rule retired with the toggle —
   no consumer remains (the affordance is gone from the project row). */
/* 隔离行（票③验收 11）：红色一行，常驻可辨。 */
.wb-quar-row { display:flex; align-items:center; gap:8px; padding:7px 10px; font-size:12px;
  color:var(--dsw-derive-danger-border,#ff8183); background:rgba(255,235,233,.08); cursor:pointer; border-bottom:1px solid rgba(255,255,255,.04); }
.wb-quar-row:hover { background:rgba(255,235,233,.16); }
/* 「＋ 接入项目」行（票③面D）：项目组列表末尾，方框＋语言同会话区（.wb-psess-* 方框同款）。 */
.wb-project-add-row { display:flex; align-items:center; gap:8px; padding:9px 10px; font-size:12px;
  color:var(--dsw-derive-muted,#57606a); cursor:pointer; }
.wb-project-add-row:hover { background:rgba(255,255,255,0.06); color:var(--dsw-alias-label-primary,#1f2328); }
.wb-project-add-plus { width:22px; height:22px; border:1px dashed var(--dsw-alias-border-l1,#555); border-radius:6px;
  display:flex; align-items:center; justify-content:center; font-size:14px; flex:none; }
/* Middle column container. Since t261005-10 (UI-2) the content is the machine-level
   status head (carried by the overlay host) plus the executor panel (fills the rest)
   — a vertical flex stack; the overlay covers both when open. */
.wb-right-content { flex:1; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
/* t261008-05: the overlay host must not size itself out of the middle column.
 * The legacy global .wb-root rule (index.tsx) carries height:100% AND
 * min-height:100%; for a flex:none item both resolve against the column's
 * definite height, so the host takes the whole column and leaves the executor
 * panel (flex:1 1 0%; min-height:0) at zero height. height:auto + min-height:0
 * makes the host shrink to its own content. The legacy global rule is
 * intentionally NOT rewritten — views that still use .wb-root as their
 * full-height root keep it. */
.wb-right-content > .wb-root { flex:none; height:auto; min-height:0; }
.wb-right-content > .wb-executor-view { flex:1; min-height:0; }
.wb-right-content > .wb-placeholder { flex:none; }
.wb-placeholder { padding:32px; color:var(--dsw-derive-muted,#57606a); font-size:13px; line-height:1.8; }

/* 顶部会话入口行样式已随票② R8 退役（t260904-05，顶部行样式族全清）。 */
`

/* ---------------------------------------------------------------- 主组件 */

/**
 * 出厂「⊕ New Session」钮压制注入面（t260831-02 建；票② R8 后职责=压制全局
 * 新建入口，拍板 1——移除注入=出厂全局钮回显，落点非项目归属）：出厂钮不在任何槽里
 * （实查 dsh-client-ui-sidebar 包只声明 sidebar.workspaces/settings/footer.action
 * 三槽），按工单口径走「注入+语义锚」——
 *   锚：从本插件侧栏根（rootRef）上溯 SidebarRoot（出厂钮是它的直接子 button，
 *   折叠钮在 logoRow 内部非直接子、不会被误伤），取「aria-label 命中
 *   FACTORY_NEW_LABELS」的直接子 button——零 CSS 类名匹配（t260828-06 死因
 *   不复犯）；命中即置 display:none——职责=压制全局新建入口（票②拍板 1，
 *   出厂钮不回显；顶部行已退役，无「让位」对象）。
 *   兜防：MutationObserver 盯 SidebarRoot 的 childList/attributes——工厂重渲染
 *   复活新钮（或恢复被隐藏钮的可见性）时重新隐藏。
 *   全终态回收：卸载/折叠 cleanup 断开 Observer 并把碰过的钮 style.display
 *   还原为原值；锚找不到=软退化（出厂钮照常显示，功能不丢，console.warn 留痕）。
 *   作用面仅此一个出厂元素，右栏出厂元素零接触。
 */
function useHideFactoryNewSession(rootRef: { current: HTMLElement | null }, wide: boolean): void {
  useEffect(() => {
    if (!wide) return
    const root = rootRef.current
    if (!root) return
    // 上溯找 SidebarRoot：出厂 newSession 钮与 slot outlet 同层，必是我们的祖先。
    let sidebarRoot: HTMLElement | null = null
    for (let e = root.parentElement, i = 0; e && i < 10; i++, e = e.parentElement) {
      const hit = Array.from(e.children).some(c =>
        c instanceof HTMLElement && c.tagName === 'BUTTON' && FACTORY_NEW_LABELS.includes(c.getAttribute('aria-label') ?? ''))
      if (hit) { sidebarRoot = e; break }
    }
    if (!sidebarRoot) {
      console.warn('[workbench] 未找到出厂 New Session 钮（软退化：出厂钮照常显示，入口仍在侧栏顶部）')
      return
    }
    const sb = sidebarRoot
    // 隐藏锚定钮 + 记录原 display（还原用）；返回是否命中。
    const hidden = new Map<HTMLElement, string>()
    const hide = (): void => {
      for (const c of Array.from(sb.children)) {
        if (!(c instanceof HTMLElement) || c.tagName !== 'BUTTON') continue
        if (!FACTORY_NEW_LABELS.includes(c.getAttribute('aria-label') ?? '')) continue
        if (!hidden.has(c)) hidden.set(c, c.style.display)
        if (c.style.display !== 'none') c.style.display = 'none'
      }
    }
    hide()
    const mo = new MutationObserver(hide)
    mo.observe(sb, { childList: true, subtree: false, attributes: true, attributeFilter: ['style', 'aria-label'] })
    return () => {
      mo.disconnect()
      for (const [el, prev] of hidden) el.style.display = prev
    }
  }, [rootRef, wide])
}

export function WorkbenchSidebar(props: SidebarProps) {
  const { wide, expandSidebar, sessions, views, open: slotOpen, workspaces, getService } = props
  const [projects, setProjects] = useState<Project[]>([])
  /** 项目 key → 该项目的工单行（按 ?project= 逐组拉取，来源即归属，不做路径猜测）。 */
  const [ticketsByProject, setTicketsByProject] = useState<Record<string, Ticket[]>>({})
  // CL-3 (t261006-18): project key -> concurrency read face (GET /wf/concurrency
  // thin projection). null = face failed/malformed (rows carry zero order marks,
  // never a locally invented order); undefined = not fetched yet.
  const [concByProject, setConcByProject] = useState<Record<string, ConcFace | null>>({})
  /** Reorder in flight (project key -> true): controls disabled against double writes; every write ends in POST -> re-read the same face. */
  const [reorderBusy, setReorderBusy] = useState<Record<string, boolean>>({})
  /** Named reorder refusal (project key -> verbatim error; '' = none): renders as the group's notice line (acceptance A7). */
  const [orderNotice, setOrderNotice] = useState<Record<string, string>>({})
  /** Currently dragged ticket (project key -> id): the drop row computes the move-to from it; zero local order kept - one permutation, then POST. */
  const dragTicketRef = useRef<{ project: string; id: string } | null>(null)
  /** Workflow topology (stage-order source of the ten-cell dots; minimal Wf projection). */
  const [wfList, setWfList] = useState<WfLite[]>([])
  // t260915-19 巡检分支：最近一次成功的巡检行快照（端点失败=保快照+显式降级横幅，
  // 绝不静默清空——KI-008/t260910-04 R3 同纪律，与中列 reloadTickets 同款）。
  const [inspectionRows, setInspectionRows] = useState<InspectionTicket[]>([])
  const [inspectionNote, setInspectionNote] = useState('')
  const inspectionRowsRef = useRef<InspectionTicket[]>([])
  // 兜底组折叠态：独立布尔——collapsed 的键是项目注册表 key，不与它混用（防撞名）。
  const [inspCollapsed, setInspCollapsed] = useState(false)
  const [selectedId, setSelectedId] = useState<string>('')
  const [rightView, setRightView] = useState<RightView>('executor')
  /** 当前中列视图所属项目（左列图标点击行）；空=未选（中列显占位）。 */
  const [viewProject, setViewProject] = useState('')
  /** 「又点了一次工单」信号：随 focusId 传给 WorkbenchSection，
   *  同 id 重开（抽屉被 × 关掉后再点同一行）也能触发——focusId 同值时 effect 不 firing。 */
  const [focusNonce, setFocusNonce] = useState(0)
  /** 「点工单列表图标回列表」信号：viewProject/rightView 同值时 setState 跳渲染，
   *  详情抽屉（WorkbenchSection 内部 state）收不到通知——靠这个单调递增计数传达。 */
  const [listNonce, setListNonce] = useState(0)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  // t261009-43: the per-project dismissed fold (separate key family from
  // `collapsed` — the collapsed key is the project registry key, and mixing
  // fold families on one record would let a dismissal open/close the whole
  // group; same discipline as the inspCollapsed comment above).
  const [dismissedOpen, setDismissedOpen] = useState<Record<string, boolean>>({})
  const [unownedDismissedOpen, setUnownedDismissedOpen] = useState(false)
  // t261009-43: the reason prompt (one row, one action at a time — a person's
  // action, never bulk). The engine refuses an empty reason, so the face asks
  // first and disables Confirm until the reason is non-blank.
  const [dismissPrompt, setDismissPrompt] = useState<
    { projectKey: string; ticketId: string; action: 'dismiss' | 'restore' } | null
  >(null)
  const [dismissReason, setDismissReason] = useState('')
  // t261011-15: visibility of the reason prompt. The prompt used to render as
  // the LAST child of .wb-ticket-list — on a long board it opened below the
  // fold, the click looked inert and no request was ever sent. Now the prompt
  // renders anchored to the row that opened it (slot per group), and this
  // effect scrolls it into view and focuses the reason box on open (restore
  // gets the same rule for free — same slot, same effect).
  const dismissPromptRef = useRef<HTMLDivElement | null>(null)
  const dismissReasonRef = useRef<HTMLTextAreaElement | null>(null)
  useEffect(() => {
    if (dismissPrompt === null) return
    dismissPromptRef.current?.scrollIntoView({ block: 'nearest' })
    dismissReasonRef.current?.focus()
  }, [dismissPrompt])
  /** Write in flight (ticket id -> true): controls disabled against double writes. */
  const [dismissBusy, setDismissBusy] = useState<Record<string, boolean>>({})
  /** Named refusal (ticket id -> verbatim error; '' = none) rendered in the prompt panel. */
  const [dismissNotice, setDismissNotice] = useState<Record<string, string>>({})
  /** t261009-43: bump to force the data load effect to re-run right after a
   *  successful dismiss/restore (the row leaves / returns on the ENGINE's
   *  payload, never a local flip; the 10 s poll would catch it eventually —
   *  the spec says "immediately"). */
  const [reloadNonce, setReloadNonce] = useState(0)
  const [loading, setLoading] = useState(true)
  // Project-lifecycle modals (ticket 3 face D): two kinds. t261008-36: the
  // settings->remove chain retired here — its only entrance was the More-views
  // icon, and both faces now open from the executor panel's Settings tab
  // (executor-view.tsx hosts the same components; one face, one home).
  const [modal, setModal] = useState<
    | { kind: 'add' }
    | { kind: 'quarantine'; entry: { key: string; dir: string; error: string } }
    | null
  >(null)
  /** 隔离条目（GET /wf/projects 的 quarantined 面，票③验收 11）：红色行渲染源。 */
  const [quarantined, setQuarantined] = useState<{ key: string; dir: string; error: string }[]>([])
  // t261008-21: the sidebar Settings popover (gear + dwell input) is retired
  // with host order 261008 option A; its state went with the markup.
  const rootRef = useRef<HTMLDivElement>(null)
  // 插件陈旧看守（t260902-03 立；t260905-07 KI-052 握手矩阵接线）：classifyHandshake
  // 三元组判定 → restart（服务端旧）/reload（浏览器旧，跨重启存活页面）两支横幅。
  const staleBanner = useStaleBanner()
  const [staleDismissed, setStaleDismissed] = useState(false)
  // 顶部行原地替换：隐藏出厂「⊕ New Session」钮（语义锚注入，见函数头注）。
  useHideFactoryNewSession(rootRef, wide)

  /* ── 项目内会话区（session-entry 第 3 面①）──
   * useSessionEntry 实例：账册是模块级共享 store（t260830-01 为同页多消费
   * 而建，机制现行）；动作（handleNew/handleOpen/handleClose）下传各项目组行，
   * 新建落点由行级闭包显式传 target（R3：落点=本组项目）。
   * projectKey 缺省（当前视图项目，单项目兜底）只影响缺省新建落点，
   * 项目行走显式 target 不依赖它。 ↺ 恢复归属兜底已随顶部行退役（拍板 2）。 */
  const projectSessions = useSessionEntry({
    sessions,
    workspaces,
    getService,
    slotOpen,
    projectKey: viewProject || (projects.length === 1 ? projects[0].key : ''),
    projectDir: projects.find(p => p.key === (viewProject || (projects.length === 1 ? projects[0].key : '')))?.primary ?? '',
  })

  // 存量编号迁移（第 3 面① 拍板 1，幂等）：账册缺 seq 的旧条目（本面前登记）
  // 按项目内登记序补号；无缺号时 backfillProjectSeqs 原样返回入参引用，引用
  // 相等即免 persist（不会循环）。依赖 ledger：异常路径再现缺号条目时自愈。
  useEffect(() => {
    if (!wide) return
    const snapshot = getLedgerSnapshot()
    const backfilled = backfillProjectSeqs(snapshot)
    if (backfilled !== snapshot) persistLedger(backfilled)
  }, [wide, projectSessions.ledger])

  // Chat identity band (UI-5, t261005-06, design 2.1): head style + body
  // subtree Observer + a body-level band overlay (key + handle + the Sessions
  // menu, which is the second new-session entrance of design 2.6). F1 guard:
  // the effect returns startChatProjectBandEffect's cleanup itself (returning
  // the handle directly is silently ignored by useEffect -> zero cleanup on
  // unload). All actions go through the existing projectSessions chain
  // (handleNew with an explicit target; the handleOpen unified chain) - the
  // menu does not invent a second create/switch semantic.
  useEffect(() => {
    if (!wide) return
    return startChatProjectBandEffect({
      getSessions: () => {
        const pk = projectSessions.listState?.current
          ? projectSessions.ledger.find(e => e.id === projectSessions.listState?.current)?.project
          : undefined
        const current = projectSessions.listState?.current
        const byId = (projectSessions.listState?.byId ?? {}) as Record<string, { displayTitle?: string } | undefined>
        return projectSessions.ledger
          .filter(e => (pk ? e.project === pk : false))
          .map(e => {
            // Session labels (t261008-01, Measure 1): a charter-injection raw
            // title shows the handle (executor keeps its fixed name); the raw
            // text rides along in rawTitle for the row tooltip.
            const raw = labelOf(byId[e.id], e.id)
            const handle = displayHandle({ session_id: e.id, handle: e.handle }) || String(e.seq ?? '')
            return {
              id: e.id,
              handle,
              title: rowLabelOf(byId[e.id], e.id, handle),
              rawTitle: raw,
              active: e.id === current,
            }
          })
      },
      onNewSession: () => {
        const pk = projectSessions.listState?.current
          ? projectSessions.ledger.find(e => e.id === projectSessions.listState?.current)?.project
          : (viewProject || (projects.length === 1 ? projects[0].key : ''))
        const dir = projects.find(p => p.key === pk)?.primary ?? ''
        if (!pk) return
        void projectSessions.handleNew({ key: pk, dir })
      },
      onOpenSession: (id) => { void projectSessions.handleOpen(id) },
    })
  }, [wide]) // actions ride the module-level shared store; the effect only mounts/unmounts with `wide`

  // 上下文折叠件（t260905-04）：把带 CHARTER_MARKER 的注入消息收成可展开小条。
  // 与色带同为「chat 滚动体装饰器」，接线同位对齐（同 hook 体内相邻 effect，
  // 生命周期同源、卸载同路径——方案 review C5 定稿）。F1 防呆接线同款。
  useEffect(() => {
    if (!wide) return
    return startContextFoldEffect()
  }, [wide])

  // Platform banner-row hide (t261007-07, closing item of the 261004 topbar
  // note): hide the platform's left-column logoRow (brand mark + fold toggle).
  // Anchor, landmark walk, and guard discipline live in platform-banner.ts.
  // NOT gated on `wide`: the platform row is present in the narrow rail too
  // (36px mark), and hiding it in both shapes is the declared behavior.
  // F1 wiring same as the band/fold decorators.
  useEffect(() => startPlatformBannerHideEffect(), [])

  // Band ownership derivation (UI-5 upgrade of the ticket-2 R7 project-only
  // face): current -> the ledger project plus the handle go out together.
  // Not in the ledger (ticket sessions / on-disk sessions / blank hero /
  // empty current) -> null = remove, render nothing - declared behavior, no
  // invisible default.
  useEffect(() => {
    if (!wide) return
    const cur = projectSessions.listState?.current
    const entry = cur ? projectSessions.ledger.find(e => e.id === cur) : undefined
    setChatProjectBandInfo({
      project: entry?.project ?? null,
      handle: entry ? displayHandle({ session_id: entry.id, handle: entry.handle }) : undefined,
    })
  }, [wide, projectSessions.listState?.current, projectSessions.ledger])

  // Project-file ledger fetch (UI-5 R5 freshness contract, merged from main): on
  // mount and on project switch the cache is refreshed from sessions.json
  // (file-wins); failures stay silent (cache fallback, declared inside
  // fetchProjectLedger). The metrics shell-row mount effect that used to live in
  // this slot is retired by t261005-10 (UI-2): the module it mounted was deleted
  // and Metrics lives in the panel's Metrics tab.
  const bandProjectKey = viewProject || (projects.length === 1 ? projects[0].key : '')
  useEffect(() => {
    if (!wide || bandProjectKey === '') return
    void fetchProjectLedger(bandProjectKey)
  }, [wide, bandProjectKey])
  // 撑宽侧栏：两处关卡都要过——
  // ① frame 是 grid 三轨（inline grid-template-columns），把第一轨改为 75%（左15%+中60%，右栏 chat 由 1fr 得 25%）；
  // ② SidebarRoot 自身带 inline width（layout store 供值、上限 420px），轨再宽它也只占 store 宽度——改为 100% 撑满轨道。
  // MutationObserver 盯住两处 style——React 重渲染/store 改写后自动复写。卸载/折叠还原。纯运行时 DOM，不碰 shell。
  useEffect(() => {
    if (!wide) return
    const root = rootRef.current
    if (!root) return
    // ① 向上找 frame：inline 样式含 Npx/N% 三轨者
    let el = root.parentElement
    let frame: HTMLElement | null = null
    for (let i = 0; el && i < 10; i++, el = el.parentElement) {
      if (/^\d+px\s|^\d+%\s/.test(el.style.gridTemplateColumns ?? '')) { frame = el; break }
    }
    // ② 向上找 SidebarRoot：第一个带 inline width: Npx 的祖先
    let sb: HTMLElement | null = null
    for (let i = 0, e = root.parentElement; e && i < 6; i++, e = e.parentElement) {
      if (/^\d+px$/.test(e.style.width ?? '')) { sb = e; break }
    }
    const observers: MutationObserver[] = []
    let origCols: string | undefined
    let origW: string | undefined
    if (frame) {
      const fr = frame
      origCols = fr.style.gridTemplateColumns
      const applyCols = () => {
        const cols = (fr.style.gridTemplateColumns || '').split(/\s+/)
        if (cols.length < 3) return
        if (cols[0] === '75%') return
        cols[0] = '75%'
        fr.style.gridTemplateColumns = cols.join(' ')
      }
      applyCols()
      const mo = new MutationObserver(applyCols)
      mo.observe(fr, { attributes: true, attributeFilter: ['style'] })
      observers.push(mo)
    }
    if (sb) {
      const s = sb
      origW = s.style.width
      const applyW = () => { if (s.style.width !== '100%') s.style.width = '100%' }
      applyW()
      const mo = new MutationObserver(applyW)
      mo.observe(s, { attributes: true, attributeFilter: ['style'] })
      observers.push(mo)
    }
    return () => {
      observers.forEach(mo => mo.disconnect())
      if (frame && origCols !== undefined) (frame as HTMLElement).style.gridTemplateColumns = origCols
      if (sb && origW !== undefined) (sb as HTMLElement).style.width = origW
    }
  }, [wide])

  // 加载数据（wide 期间 10s 轮询——工单状态随 agent 推进变化）：
  // 项目组=注册表（/wf/projects），每组工单按 ?project= 逐组拉取（Temporal ProjectKey 过滤）。
  useEffect(() => {
    if (!wide) return
    let cancelled = false
    async function load() {
      // t260915-19：巡检板面并行拉取（先发车，项目组加载完再收口）——独立 try
      // 不拖垮项目组渲染；失败=保快照+显式降级横幅（原文透传），成功=清 note。
      const inspPromise = fetch(INSPECTION_TICKETS_URL)
        .then(r => r.json())
        .catch((err: unknown) => ({ ok: false, error: err instanceof Error ? err.message : String(err) }))
      try {
        const pr = await fetch('/sandbar-workbench/api/wf/projects').then(r => r.json())
        const list: Project[] = pr?.result?.projects ?? []
        if (cancelled) return
        setProjects(list)
        // 隔离条目（票③）：装载器 fail-closed 面，红色行呈现；空/全隔离注册表
        // 不再 500（loadRegistry 改造）——零分组仍渲染「＋ 接入项目」行。
        setQuarantined(Array.isArray(pr?.result?.quarantined) ? pr.result.quarantined : [])
        // t260903-07：项目集发布给 chat 项目 tag 装饰器（整体一个请求，成功才发，
        // 失败不发——单态保留 last-known-good）。
        publishProjects(list.map(p => ({ key: p.key, dirs: p.dirs })))
        const entries = await Promise.all(list.map(async (p) => {
          try {
            const tr = await fetch(`/sandbar-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`).then(r => r.json())
            const tickets = (tr?.result?.tickets ?? []) as Ticket[]
            // t260903-07：逐项目成功分支才发布工单→项目映射（catch 分支不发，见上方 import 注释）。
            // t260915-19 取舍：映射只含 dev-lane 行——巡检行不进 chat 项目 tag 装饰器
            // （其语义=工单会话归属，巡检票无会话；行仍在左栏组内可见，非静默丢失）。
            publishProjectEntry(p.key, tickets.map(t => t.id))
            return [p.key, tickets] as const
          } catch {
            return [p.key, [] as Ticket[]] as const
          }
        }))
        // CL-3 (t261006-18): fetch the concurrency face per project in parallel
        // (a failed/malformed fetch = null for that project, rows degrade with
        // zero order marks - the queue is never recomputed locally; rule 8).
        const concEntries = await Promise.all(list.map(async (p) => {
          try {
            const cr = await fetch(`${CONCURRENCY_URL}?project=${encodeURIComponent(p.key)}`).then(r => r.json())
            return [p.key, parseConcFace(concFaceFromReply(cr))] as const
          } catch {
            return [p.key, null] as const
          }
        }))
        if (cancelled) return
        setTicketsByProject(Object.fromEntries(entries))
        setConcByProject(Object.fromEntries(concEntries))
      } catch { /* 静默 */ }
      // CL-3 ten-cell dots (design §7.2): fetch the topology once (/wf/workflows
      // global template face, same source as the epics create dialog, zero host
      // change); on failure keep the previous snapshot, dots degrade to hidden.
      try {
        const wr = await fetch('/sandbar-workbench/api/wf/workflows').then(r => r.json())
        if (!cancelled && wr?.ok === true) setWfList((wr.result ?? []) as WfLite[])
      } catch { /* silent: keep the previous snapshot */ }
      // 巡检分支收口（独立于项目组 try：项目组失败不影响巡检，反之亦然）。
      try {
        const ir = await inspPromise as { ok?: boolean; error?: unknown; result?: { tickets?: unknown } } | undefined
        if (cancelled) return
        if (ir?.ok === true) {
          inspectionRowsRef.current = (ir.result?.tickets ?? []) as InspectionTicket[]
          setInspectionRows(inspectionRowsRef.current)
          setInspectionNote('')
        } else {
          // ok:false（host 502 body 原文）或网络错：原文进横幅不进数据（KI-018①），
          // 快照保持不动（不吞成空列表——review gen0 意见与 t260910-04 R3 同纪律）。
          setInspectionNote(inspectionDegradedNote(
            ir?.error !== undefined ? ir.error : `HTTP response has no JSON body: ${JSON.stringify(ir).slice(0, 120)}`))
        }
      } catch (err) {
        if (cancelled) return
        setInspectionNote(inspectionDegradedNote(err instanceof Error ? err.message : String(err)))
      }
      finally { if (!cancelled) setLoading(false) }
    }
    load()
    // t260901-15：不可见页签暂停轮询（隐藏零请求、回可见立即补刷）。
    const stopPoll = startVisibleInterval(() => { void load() }, 10_000)
    return () => { cancelled = true; stopPoll() }
    // t261009-43: reloadNonce re-runs the whole load after a successful
    // dismiss/restore POST (re-read the same face, never a local flip).
  }, [wide, reloadNonce])

  // CL-3 (t261006-18): re-fetch one project's face (the "re-read the same face"
  // half of every POST). failure/malformed = null (rows carry zero marks) -
  // never keep the stale face and pretend the move succeeded.
  const refreshConc = useCallback(async (projectKey: string) => {
    try {
      const cr = await fetch(`${CONCURRENCY_URL}?project=${encodeURIComponent(projectKey)}`).then(r => r.json())
      setConcByProject(m => ({ ...m, [projectKey]: parseConcFace(concFaceFromReply(cr)) }))
    } catch {
      setConcByProject(m => ({ ...m, [projectKey]: null }))
    }
  }, [])

  // One manual reorder: locally compute only the PERMUTATION (pure function,
  // and it must be a permutation of the engine's current queue), then POST
  // reorder -> re-read the same face. Zero local order state (the ticket's
  // iron rule). A refusal (409 non-permutation / write face absent, network
  // error) surfaces verbatim in the group's notice line (acceptance A7: a
  // refusal must be visible, never swallowed) - then only re-read the face so
  // the rows fall back to the engine's truth; never fake a done move.
  const handleReorder = useCallback(async (projectKey: string, order: string[]) => {
    const face = concByProject[projectKey] ?? null
    const want = permutationOf(face?.queue ?? [], order)
    if (want === null) {
      // t261009-03: a refused move must be VISIBLE (ticket outcome 3). The
      // face is null or stale — refusing the move is right, but refusing
      // silently is exactly the "drag looks inert" the host reported. Set
      // the same notice line the 409 path uses; the poll restores truth.
      setOrderNotice(m => ({ ...m, [projectKey]:
        'concurrency reorder not applied: the queue face is unavailable or stale — no move made' }))
      return
    }
    setReorderBusy(m => ({ ...m, [projectKey]: true }))
    let refused = ''
    try {
      const r = await fetch(CONCURRENCY_REORDER_URL, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ project: projectKey, order: want }),
      }).then(x => x.json()) as { ok?: boolean; error?: unknown } | undefined
      if (r?.ok !== true) refused = String(r?.error ?? 'reorder failed (HTTP body without ok:true)')
    } catch (err) {
      refused = err instanceof Error ? err.message : String(err)
    }
    try {
      await refreshConc(projectKey)
    } finally {
      setOrderNotice(m => ({ ...m, [projectKey]: refused }))
      setReorderBusy(m => ({ ...m, [projectKey]: false }))
    }
  }, [concByProject, refreshConc])

  // t261009-43: one person's dismiss/restore. POST the op (who + reason both
  // required non-empty — the engine refuses an empty reason, so the face asks
  // first), surface a refusal verbatim, and on success re-read the face (the
  // row leaves / returns because the ENGINE payload says so — the client never
  // invents or locally flips the dismissed key). The outcome lands when the
  // reloadNonce effect re-pulls ticket-list (immediate, not waiting for the
  // 10 s poll).
  const submitDismissal = useCallback(async (projectKey: string, ticketId: string,
    action: 'dismiss' | 'restore', reason: string) => {
    if (reason.trim() === '') {
      setDismissNotice(m => ({ ...m, [ticketId]: 'a reason is required (recorded with the disposition)' }))
      return
    }
    setDismissBusy(m => ({ ...m, [ticketId]: true }))
    let refused = ''
    try {
      const r = await fetch(action === 'dismiss'
        ? DISMISS_URL(projectKey, ticketId) : RESTORE_URL(projectKey, ticketId), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ who: sidebarOperator(), reason }),
      }).then(x => x.json()) as { ok?: boolean; error?: unknown } | undefined
      if (r?.ok !== true) refused = String(r?.error ?? `${action} failed (HTTP body without ok:true)`)
    } catch (err) {
      refused = err instanceof Error ? err.message : String(err)
    }
    setDismissNotice(m => ({ ...m, [ticketId]: refused }))
    setDismissBusy(m => ({ ...m, [ticketId]: false }))
    if (refused === '') {
      setDismissPrompt(null)
      setDismissReason('')
      setReloadNonce(n => n + 1)
    }
  }, [])

  // 点工单（t260903-07 起）：只在中列开工单详情抽屉，右栏 chat 恒为全局会话
  // 不切换（联动下线口径见本文件头部注释）。左列行/立项单关联行/度量下钻三入口共用。
  const handleTicketClick = useCallback((t: Ticket, projectKey: string) => {
    setSelectedId(t.id)
    // t260915-19：projectKey 空（巡检兜底组行，无项目身份）时保持现值、无现值
    // 兜底首项目（openEpic 同款先例）——Board 挂载门（index.tsx !projectKey 早退）
    // 需要非空 projectKey 才能开详情抽屉；零注册项目时选中态在、中列保持占位
    // （既有边界交回，本票不做 index.tsx 结构手术）。项目组行传非空 key=原行为。
    setViewProject(p => projectKey || p || (projects.length > 0 ? projects[0].key : ''))
    // t261005-10 (UI-2): the board view is gone — the overlay opens on top of the
    // executor panel (the overlay carries the content replacement; the panel iframe
    // never unmounts).
    setRightView('executor')
    setFocusNonce(n => n + 1)
  }, [projects])

  // chat 项目 tag 装饰器（t260903-07 工单②）：挂/卸随本组件（插件在装即挂，
  // 卸载=全终态回收，见 chat-project-tag.ts teardown 清单）。
  // F1 修复：走 effect 形态入口——返回值就是 cleanup 函数，
  // 杜绝「useEffect 直接返回 handle 对象被忽略 → 卸载零回收」的接线陷阱。
  useEffect(() => startChatProjectTagEffect({ fetchImpl: fetch.bind(globalThis) }), [])

  // 点项目行的视图图标：中列切到该项目该视图（stopPropagation 不触发折叠）。
  // 工单列表图标额外做两件事（t260825-05：开着详情抽屉点它无反应的修复）——
  // ① 清行选中：focusId 回落 undefined，之后点同一工单行还能再开详情；
  // ② bump listNonce：viewProject/rightView 多半已是同值（点工单时已置），
  //    setState 跳渲染，只有 nonce 变化能把「关抽屉回列表」传达到 WorkbenchSection。
  // 立项单（t260827-01）：点图标=回立项清单（空代号=列表模式），bump epicNonce
  //    保证「看过详情再点图标」与「同项目重复点图标」都能触发 EpicSection 重拉回列表
  //    （epicCode/rightView/viewProject 多半已是同值，setState 跳渲染——同 listNonce 先例）。
  // A view icon on a project row switches the middle column (stopPropagation keeps
  // the group fold closed). t261005-10 (UI-2): the Tickets/Epics/Docs icons retired
  // with their views. t261008-36: the More-views affordance retired too — Model
  // routes and Project settings open from the panel's Settings tab, so only the
  // 'executor' view remains on RightView.

  const handleViewIcon = useCallback((projectKey: string, view: RightView) => {
    setViewProject(projectKey)
    setRightView(view)
  }, [])

  // t260929-22（GAP A）：按面板声明的会话 id 打开 executor 对话——直接走平台
  // sessions.open（项目内会话 tab 的 openSession 链收敛在 hook 内部，不外露）；
  // throw（未列出 id）= false，ExecutorView 出显式提示，不静默。
  const openExecutorSessionById = useCallback((sessionId: string): boolean => {
    try { sessions.open(sessionId); return true } catch (err) {
      console.warn('[workbench] open executor session failed:', err)
      return false
    }
  }, [sessions])

  /** 项目组：注册表顺序。进行中工单常列；已完成工单在 sandbar 驻留窗口内也列（灰绿标记）。 */
  // 巡检行分拣（t260915-19 方案 v2）：按行 project（t260915-20 起=ProjectKey SA
  // 真源）归位——命中在册项目进对应组、空/不在册（20 之前老票、注册表隔离 key、
  // 摘除项目）进 unowned 兜底组。纯查表零请求；分拣纯函数在 host 层有 UT 看守。
  const inspectionSplit = useMemo(
    () => inspectionSplitByProject(inspectionRows, projects.map(p => p.key)) as {
      byProject: Record<string, InspectionTicket[]>
      unowned: InspectionTicket[]
    },
    [inspectionRows, projects],
  )
  const groups = useMemo(() => {
    const nowS = Date.now() / 1000
    return projects.map(p => {
      const dev = ticketsByProject[p.key] ?? []
      const insp = inspectionSplit.byProject[p.key] ?? []
      // t261009-43: a DISMISSED row leaves the left column — on BOTH sources
      // (the dev-lane list and the inspection board face merge here, and a
      // dismissal that worked on only one would look broken). The dismissed
      // key is read from the engine payload (isDismissedRow; the client never
      // invents it), and a row carrying only `dismissed_note` (journal read
      // failure) is NOT dismissed: it stays visible with the note surfaced.
      // Remaining rows keep their order: the filters preserve input order and
      // sortMergedTickets is stable, so a dismissal never re-shuffles the
      // project's other rows.
      // Two-window split (pinned by review gen2 comment 2, t260916-15/t260915-19):
      // the client's sandbarHours window governs ONLY the dev-lane rows
      // (inSandbar); inspection rows never pass it — their closed-row window is
      // the engine's R8 window (over-window / close_ts-missing rows never reach
      // the board, t260915-08 board-rows scenario). This is NOT a missed filter;
      // do not "fix" it. t261009-43 asymmetry, stated rather than left
      // implicit: inspection rows never pass the client's 24 h dwell window
      // (their window is the engine's), so for an inspection row the human
      // dismissal IS the retirement mechanism on this face.
      const dismissed = sortMergedTickets([...dev, ...insp].filter(isDismissedRow))
      return {
        project: p,
        tickets: sortMergedTickets([
          ...dev.filter(t => !isDismissedRow(t) && inSandbar(t, nowS)),
          ...insp.filter(t => !isDismissedRow(t)),
        ]),
        dismissed,
      }
    })
  }, [projects, ticketsByProject, inspectionSplit])

  // t261005-10 (UI-2): Ws = the overlay + machine-status-head host (no board view).
  // t261008-36: views.routes is gone — Model routes opens from the panel Settings.
  const Ws = views.overlay

  // 轨条态
  if (!wide) {
    return (
      <div ref={rootRef} className="wb-sb rail">
        <style>{CSS}</style>
        <div className="wb-sb-icon" onClick={expandSidebar} title="Console">⊞</div>
      </div>
    )
  }

  // 展开态：双列
  // t261011-15: the reason prompt — one row, one action at a time. Rendered
  // ANCHORED to the group that owns the row (slot per project block and one
  // in the unowned inspection group) instead of as the last child of the
  // scroll container: on a board taller than the viewport the old position
  // opened below the fold, the click looked inert and no request was ever
  // sent. The open effect (dismissPromptRef above) scrolls the slot into
  // view and focuses the reason box; restore keeps the same rule (same slot,
  // same effect). The engine refuses an empty reason, so Confirm stays
  // disabled until the reason is non-blank; a refusal surfaces verbatim
  // (never swallowed); a success closes the prompt and re-reads the face.
  const renderDismissPrompt = () => {
    if (dismissPrompt === null) return null
    const p = dismissPrompt
    const notice = dismissNotice[p.ticketId] ?? ''
    return (
      <div ref={dismissPromptRef} className="wb-dismiss-prompt" data-wb-dismiss-prompt=""
        role="dialog" aria-label={`${p.action} ${p.ticketId}`}>
        <div className="wb-dismiss-prompt-title">
          {p.action === 'dismiss'
            ? `Dismiss ${p.ticketId} — off the board, not done (restorable)`
            : `Restore ${p.ticketId} — back on the board`}
        </div>
        <textarea ref={dismissReasonRef} className="wb-dismiss-reason" data-wb-dismiss-reason=""
          value={dismissReason}
          placeholder="Reason (required, recorded)"
          onChange={(e) => setDismissReason(e.target.value)} />
        {notice !== '' && (
          <div className="wb-order-notice" data-wb-dismiss-notice="" role="alert">{notice}</div>
        )}
        <div className="wb-dismiss-prompt-actions">
          <button type="button" className="wb-card-btn wb-card-btn-dismiss" data-dismiss-confirm=""
            disabled={dismissBusy[p.ticketId] === true || dismissReason.trim() === ''}
            onClick={() => { void submitDismissal(p.projectKey, p.ticketId, p.action, dismissReason) }}>
            {p.action === 'dismiss' ? 'Dismiss' : 'Restore'}
          </button>
          <button type="button" className="wb-card-btn" data-dismiss-cancel=""
            onClick={() => { setDismissPrompt(null); setDismissReason(''); setDismissNotice(m => ({ ...m, [p.ticketId]: '' })) }}>
            Cancel
          </button>
        </div>
      </div>
    )
  }
  return (
    <div ref={rootRef} className="wb-sb wide">
      <style>{CSS}</style>
      {/* 左列：项目分组（可折叠）+ 插件入口。顶部会话入口行已随票② R8 退役
          （t260904-05）：入口收口为各组的项目内会话区，出厂全局钮由注入 effect 压制。 */}
      <div className="wb-sb-left">
        {/* UI-1 (t261005-09): brand first row (26px; see .wb-brand-row CSS note). */}
        <div className="wb-brand-row" data-wb-brand-row="">
          <span className="wb-brand-mark" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 14 14">
              <rect x="1.2" y="2.6" width="9" height="3.4" rx="1.7" transform="rotate(-18 5.7 4.3)"
                fill="var(--dsw-alias-brand-primary,#7c3aed)" />
              <rect x="3.8" y="7.6" width="9" height="3.4" rx="1.7" transform="rotate(-18 8.3 9.3)"
                fill="var(--dsw-alias-brand-primary,#7c3aed)" opacity="0.55" />
            </svg>
          </span>
          <span className="wb-brand-word">Sandbar</span>
          <span className="wb-brand-count">{loading ? '' : `${groups.length} project${groups.length === 1 ? '' : 's'}`}</span>
        </div>
        <div className="wb-ticket-list">
          {/* t260915-19 巡检板面降级横幅：端点 ok:false/网络失败=保快照+显式原文
              （不吞成空列表，KI-008/t260910-04 R3）。单点挂左栏顶部——巡检行分散
              进各组后无统一组头可挂。inspection_filter.degraded（引擎白名单声明
              降级）左栏**不带**横幅：行级显式降级已由引擎 degraded 行形状保证不
              静默（「巡检收口快照读取失败，刷新重试」行正常进分拣呈现），中列
              横幅仍在，左栏不重复（review gen0 意见②要求的取舍声明）。 */}
          {inspectionNote !== '' && (
            <div className="wb-insp-degraded" data-testid="sidebar-inspection-degraded" role="alert">
              {inspectionNote}
            </div>
          )}
          {loading ? (
            <div style={{padding:16,color:'var(--dsw-derive-fg,#888)'}}>Loading…</div>
          ) : groups.map(g => (
            <div key={g.project.key}
              className="wb-project-block"
              data-wb-project-block=""
              data-selected={viewProject === g.project.key}
              style={{ '--wb-proj-color': projectColor(g.project.key) } as CSSProperties}>
              {/* t260929-22（GAP A）：项目名行本身=执行器入口（设计稿 260927 §界面与命名：
                  一个项目一行、项目名即 project executor 的入口，不单列 Tick 行）——
                  折叠退到 caret 单独承担（一次点击只做一件事）；五个视图图标语义不变。 */}
              <div className="wb-group-head" style={{ cursor: 'pointer' }}>
                <span className="wb-group-caret" title={collapsed[g.project.key] ? 'Expand' : 'Collapse'}
                  onClick={(e) => { e.stopPropagation(); setCollapsed(c => ({ ...c, [g.project.key]: !c[g.project.key] })) }}>{collapsed[g.project.key] ? '▸' : '▾'}</span>
                {/* UI-4 (t261005-05): 14px project identity badge (design note §2.5
                    size rule), replacing the old 8px colour dot; colour x outline x
                    structure from the single-source project-identity module, dedupe
                    set = this registry's keys (the sidebar-side input of the same
                    rule the panel runs). */}
                <span className="wb-group-dot" data-wb-psess-dot="" data-wb-identity-badge=""
                  style={{ display: 'inline-flex', flex: 'none', lineHeight: 0 }}
                  title={g.project.key}
                  aria-label={`${g.project.name} identity badge`}
                  dangerouslySetInnerHTML={{ __html: projectBadgeSvg(g.project.key, 14, groups.map(x => x.project.key)) }} />
                {/* gen1 可达性修（acceptance 打回）：入口=名字+计数+弹性空档整段
                    （.wb-group-entry，flex:1 吃掉行内非图标区）——普通窗口宽度下项目名
                    不再被图标簇挤成 0 宽、行中部点击必落入入口段而非图标；图标簇命中区
                    26→20px（显形 svg 18px 不变）。 */}
                <span className="wb-group-entry" data-wb-executor-entry=""
                  role="button" tabIndex={0}
                  title={`Open ${g.project.name} executor panel`}
                  aria-label={`Open ${g.project.name} executor panel`}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleViewIcon(g.project.key, 'executor') }}
                  onClick={() => handleViewIcon(g.project.key, 'executor')}>
                  <span className="wb-group-name">{g.project.name}</span>
                  {/* CL-3 (t261006-18): two numbers on the row's right, "X at work
                      . Y waiting" (design §2.2: numbers, no sentences). Source =
                      the concurrency face projection (faceCounts); a missing or
                      malformed face renders nothing (degrades with zero marks). */}
                  {concByProject[g.project.key] !== undefined && concByProject[g.project.key] !== null && (() => {
                    const c = faceCounts(concByProject[g.project.key] ?? null)
                    return (
                      <span className="wb-group-conc" data-wb-conc-counts=""
                        data-at-work={c.atWork} data-waiting={c.waiting}
                        title="At work · waiting (project concurrency)">
                        {c.atWork} at work · {c.waiting} waiting
                      </span>
                    )
                  })()}
                  <span className="wb-group-count">{g.tickets.length || ''}</span>
                </span>
                {/* View entries per project (user decision 260823; gen4 host ruling
                    t260929-22: row-resident icons = tickets + charter only, pinned by
                    their scenarios t260904-17 / t260915-09).
                    t261008-36: the whole More-views affordance retired — Model routes
                    and Project settings open from the executor panel's Settings tab
                    (one face, one home; no second door), and no third face remained
                    inside the expansion. */}
              </div>
              {!collapsed[g.project.key] && (
                <>
                  {/* 项目内会话区（第 3 面① R1）：组头之下、工单列表之上，随组折叠
                      同隐。+ 落本项目主目录（R3，handleNew 显式 target 工厂同款链）；
                      tab=项目内登记序号（关闭不回收，R2）；点 tab 切换（R4）；关闭钮
                      确认弹层后剔入口（R5）；current 高亮唯一（R6）。数据=账册按
                      project 过滤，工单/磁盘存量/subagent 不进账册口径不变。 */}
                  <ProjectSessionRow
                    projectKey={g.project.key}
                    projectName={g.project.name}
                    projectDir={g.project.primary}
                    ledger={projectSessions.ledger}
                    current={projectSessions.listState?.current}
                    byId={projectSessions.listState?.byId as Record<string, { displayTitle?: string } | undefined> | undefined}
                    creating={projectSessions.creating}
                    notice={projectSessions.entryNotice}
                    noticeProject={projectSessions.noticeProject}
                    onNew={() => { void projectSessions.handleNew({ key: g.project.key, dir: g.project.primary }) }}
                    onOpen={(id) => { void projectSessions.handleOpen(id) }}
                    onClose={projectSessions.handleClose}
                  />
                  {g.tickets.length === 0 ? (
                    <div className="wb-group-empty">No active tickets</div>
                  ) : g.tickets.map(t => {
                    // UI-1 (t261005-09) boundary with concurrency-limit CL-2/CL-3:
                    // queue position numbers and drag/arrow ordering of QUEUED
                    // tickets belong to CL — landed here (t261006-18) and nowhere
                    // else. The order face is the ENGINE's (GET /wf/concurrency);
                    // this list never computes order locally: every move is
                    // POST reorder -> re-read the same face.
                    // t260915-19：组内巡检行（t260915-20 起带项目身份，ProjectKey SA
                    // 归组）走最小适配——行1 标题引擎已给「巡检 <实例> · 期 <期号>」
                    // 零适配；行2 传本地纯函数合成进展（等你签字 · 发现 高x/中y/低z，
                    // 词表与中列同源）；「等你」黄调由 data-engine=inspection 等值
                    // 选择器接管（见 CSS 注释，项目行零变化）。
                    // t260916-15：行1 加类别徽标（INSPECTION_ROW_BADGE chip，词表
                    // 单点在 host 层）——合并排序后巡检行混入组内各位置，数据来源
                    // 须行随身可辨，不靠「恒在组尾」的旧位置线索。
                    const insp = isInspectionRow(t)
                    // CL-3 order projection (queue-model pure functions; a missing or
                    // malformed face = null -> every row renders with zero marks).
                    const conc = concByProject[g.project.key] ?? null
                    const kind = insp ? undefined : orderKindOf(t.id, conc, t.paused === true)
                    const pos = kind === 'queued' && conc !== null ? conc.queue.indexOf(t.id) + 1 : undefined
                    // Ten-cell dots: the stage's index inside the topology (§7.2 default dots; the bar alternative is out of this ticket's scope).
                    const wfl = wfList.find(w => w.id === t.workflow) ?? null
                    const stageIdx = wfl && Array.isArray(wfl.stages)
                      ? wfl.stages.findIndex(s => s?.id === t.stage) : -1
                    return (
                      /* t260904-17 列表 v5（mock 屏⑤）：左栏工单条目=行卡迷你版（一套 UI；
                       * compact 省略站道/管理动作位）。状态短名/配色由四态枚举驱动
                       * （与中列同一模型层口径）。 */
                      <TicketRowCard key={t.id} t={t} compact
                        wf={insp ? INSPECTION_WF_LIKE : undefined}
                        progress={insp ? inspectionProgressOf(t) : undefined}
                        kindBadge={insp ? { text: INSPECTION_ROW_BADGE } : undefined}
                        ordering={kind === undefined ? undefined : {
                          kind,
                          pos,
                          dotsLit: kind === 'queued' || kind === 'atwork' || kind === 'hold'
                            ? stageDotsLit(stageIdx, t.status === 'closed') : undefined,
                          busy: reorderBusy[g.project.key] === true,
                          onMove: (dir) => {
                            if (conc === null) return
                            const next = moveTicket(conc.queue, t.id, dir)
                            if (next !== null) void handleReorder(g.project.key, next)
                          },
                          onDragStart: () => { dragTicketRef.current = { project: g.project.key, id: t.id } },
                          onDrop: () => {
                            const drag = dragTicketRef.current
                            dragTicketRef.current = null
                            if (conc === null || drag === null || drag.project !== g.project.key) return
                            const next = reorderMoveTo(conc.queue, drag.id, t.id)
                            if (next !== null) void handleReorder(g.project.key, next)
                          },
                        }}
                        active={selectedId === t.id}
                        updatedTsMs={(isOpen(t) ? t.created : (t.close_ts || t.created)) !== undefined
                          ? (isOpen(t) ? t.created : (t.close_ts || t.created))! * 1000 : undefined}
                        onOpen={() => handleTicketClick(t, g.project.key)}
                        onDismiss={() => setDismissPrompt({ projectKey: g.project.key, ticketId: t.id, action: 'dismiss' })} />
                    )
                  })}
                  {/* t261011-15: the reason prompt slot — anchored to this group,
                      right after the clicked row's list (the open effect scrolls
                      it into view and focuses the reason box; a long board can
                      no longer push it below the fold). Restore opens from the
                      dismissed fold below but lands in the same slot. */}
                  {dismissPrompt?.projectKey === g.project.key && renderDismissPrompt()}
                  {/* Reorder-refusal notice (t261006-18 A7): the engine write face's
                      named refusal verbatim - visible, order untouched (the face
                      re-read restores truth), never silently swallowed. */}
                  {orderNotice[g.project.key] && (
                    <div className="wb-order-notice" data-wb-order-notice=""
                      role="alert">{orderNotice[g.project.key]}</div>
                  )}
                  {/* t261009-43: the dismissed fold for this project. Label says
                      "dismissed", never done — a dismissed row is off the board,
                      NOT a completed ticket. Expanded, each row offers Restore
                      (the undo path; no database edit). */}
                  {g.dismissed.length > 0 && (
                    <div className="wb-dismissed-fold" data-wb-dismissed-fold={g.project.key}
                      data-dismissed-count={g.dismissed.length}>
                      <div className="wb-dismissed-head" role="button" tabIndex={0}
                        aria-expanded={dismissedOpen[g.project.key] === true}
                        aria-label={`${g.dismissed.length} dismissed in ${g.project.name}`}
                        data-wb-dismissed-toggle=""
                        onClick={(e) => { e.stopPropagation(); setDismissedOpen(m => ({ ...m, [g.project.key]: !m[g.project.key] })) }}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); setDismissedOpen(m => ({ ...m, [g.project.key]: !m[g.project.key] })) } }}>
                        <span className="wb-group-caret">{dismissedOpen[g.project.key] ? '▾' : '▸'}</span>
                        <span className="wb-dismissed-label">{g.dismissed.length} dismissed</span>
                        <span className="wb-dismissed-hint">off the board, not done</span>
                      </div>
                      {dismissedOpen[g.project.key] && g.dismissed.map(t => (
                        <TicketRowCard key={t.id} t={t} compact
                          wf={isInspectionRow(t) ? INSPECTION_WF_LIKE : undefined}
                          progress={isInspectionRow(t) ? inspectionProgressOf(t) : undefined}
                          kindBadge={isInspectionRow(t) ? { text: INSPECTION_ROW_BADGE } : undefined}
                          active={selectedId === t.id}
                          onOpen={() => handleTicketClick(t, g.project.key)}
                          onRestore={() => setDismissPrompt({ projectKey: g.project.key, ticketId: t.id, action: 'restore' })} />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {/* Unowned inspection group (t260915-19): inspection tickets whose
              project is empty (pre-20 legacy tickets) or not in the registry
              (quarantined key / removed project) land here EXPLICITLY — never
              silently dropped. No such rows = the whole group is not rendered;
              rows render with the same adaptation as project-group inspection
              rows (incl. the t260916-15 kind badge), merged-sorted the same
              way; clicks go through handleTicketClick (empty projectKey ->
              first-project fallback, see its comment).
              t261009-43: dismissed rows leave this group too (second-source
              symmetry); their fold lives under the same group head. */}
          {!loading && inspectionSplit.unowned.length > 0 && (() => {
            const { kept: unownedKept, dismissed: unownedDismissed } =
              splitDismissedRows(sortMergedTickets(inspectionSplit.unowned))
            return (
            <div>
              <div className="wb-group-head" data-testid="sidebar-inspection-head"
                onClick={() => setInspCollapsed(c => !c)}>
                <span className="wb-group-caret">{inspCollapsed ? '▸' : '▾'}</span>
                <span className="wb-group-name">{INSPECTION_ROW_BADGE}</span>
                <span className="wb-group-count">{unownedKept.length}</span>
              </div>
              {!inspCollapsed && unownedKept.map(t => (
                <TicketRowCard key={t.id} t={t} compact
                  wf={INSPECTION_WF_LIKE} progress={inspectionProgressOf(t)}
                  kindBadge={{ text: INSPECTION_ROW_BADGE }}
                  active={selectedId === t.id}
                  updatedTsMs={(isOpen(t) ? t.created : (t.close_ts || t.created)) !== undefined
                    ? (isOpen(t) ? t.created : (t.close_ts || t.created))! * 1000 : undefined}
                  onOpen={() => handleTicketClick(t, '')}
                  onDismiss={() => setDismissPrompt({ projectKey: '', ticketId: t.id, action: 'dismiss' })} />
              ))}
              {/* t261011-15: the unowned group's own prompt slot (blank project key
                  — the URL builder omits ?project= for it, no guessing). */}
              {dismissPrompt?.projectKey === '' && renderDismissPrompt()}
              {/* t261009-43: the unowned group's own dismissed fold (separate
                  boolean from the project-keyed record — no registry key exists
                  here to key it by). */}
              {!inspCollapsed && unownedDismissed.length > 0 && (
                <div className="wb-dismissed-fold" data-wb-dismissed-fold="unowned"
                  data-dismissed-count={unownedDismissed.length}>
                  <div className="wb-dismissed-head" role="button" tabIndex={0}
                    aria-expanded={unownedDismissedOpen}
                    aria-label={`${unownedDismissed.length} dismissed inspection rows`}
                    data-wb-dismissed-toggle=""
                    onClick={(e) => { e.stopPropagation(); setUnownedDismissedOpen(v => !v) }}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); setUnownedDismissedOpen(v => !v) } }}>
                    <span className="wb-group-caret">{unownedDismissedOpen ? '▾' : '▸'}</span>
                    <span className="wb-dismissed-label">{unownedDismissed.length} dismissed</span>
                    <span className="wb-dismissed-hint">off the board, not done</span>
                  </div>
                  {unownedDismissedOpen && unownedDismissed.map(t => (
                    <TicketRowCard key={t.id} t={t} compact
                      wf={INSPECTION_WF_LIKE} progress={inspectionProgressOf(t)}
                      kindBadge={{ text: INSPECTION_ROW_BADGE }}
                      active={selectedId === t.id}
                      onOpen={() => handleTicketClick(t, '')}
                      onRestore={() => setDismissPrompt({ projectKey: '', ticketId: t.id, action: 'restore' })} />
                  ))}
                </div>
              )}
            </div>
            )
          })()}
          {/* 隔离行（票③验收 11）：装载器隔离的 key 红色一行，点击看原因与修复指路；
              隔离期间无组头无项目设置入口（无装载条目可设置）。 */}
          {quarantined.map(q => (
            <div key={q.key} className="wb-quar-row" data-wb-quarantine-row=""
              role="button" aria-label={`Quarantined entry ${q.key}`}
              onClick={() => setModal({ kind: 'quarantine', entry: q })}>
              ⚠ {q.key} · registry entry quarantined
            </div>
          ))}
          {/* 「＋ 接入项目」行（票③面D）：项目组列表末尾常驻——空/全隔离注册表
              也渲染（首个项目接入恰恰发生在空注册表时）。方框＋，语言同会话区。 */}
          <div className="wb-project-add-row" data-wb-project-add-row=""
            role="button" aria-label="Add project"
            onClick={() => setModal({ kind: 'add' })}>
            <span className="wb-project-add-plus">＋</span>Add project
          </div>
          {/* t261011-15: the tail-of-container prompt render retired here — the
              prompt now renders anchored to the group that owns the row
              (renderDismissPrompt slots above), so a long board cannot push it
              below the fold. */}
        </div>
      </div>
      {/* 中列：四视图（现成的工单台/文档/模型/立项单 UI，从 chat 页签迁来；左列图标直切，无 tab 条）。
          未选项目显占位——不自动选第一个项目（project 无默认值，用户拍板 260823）。 */}
      <div className="wb-sb-right">
        {/* 插件陈旧全局提醒（t260905-07 KI-052）：挂中列共享容器（四视图排他渲染
            之上），所有页签/视图常驻可见；「知道了」仅本页签消音（会话级，不持久化）。
            文案两支与消除动作一一对应：restart=重启控制台（服务端旧），reload=刷新
            页面（浏览器旧——重启无效，跨重启存活页面的正确动作）。 */}
        {staleBanner && !staleDismissed && (
          <div className="wb-stale-banner" data-stale-kind={staleBanner} role="alert">
            <span className="wb-stale-msg">
              ⚠️ {staleBanner === 'restart' ? STALE_BANNER_TEXT : STALE_RELOAD_TEXT}
              ({staleBanner === 'restart' ? 'console process still runs old code' : 'this page still runs old code'}; metrics/diff may be stale).
            </span>
            <button className="wb-stale-dismiss" title="Hide in this tab" onClick={() => setStaleDismissed(true)}>Got it</button>
          </div>
        )}
        <div className="wb-right-content">
          {!viewProject && (
            <div className="wb-placeholder">
              Open a project from the left (click a project name row to open its Executor panel,
              <br />or click a ticket row to open its detail overlay).
            </div>
          )}
          {/* t261005-10 (UI-2): the middle column is the executor panel (home of the
              consolidated tab strip) plus the overlay host (Ws) — the machine-level
              head sits above the panel; the ticket overlay covers both. */}
          {viewProject && rightView === 'executor' && (
            <>
              <Ws focusId={selectedId || undefined} focusNonce={focusNonce} listNonce={listNonce} projectKey={viewProject} />
              <ExecutorView
                projectKey={viewProject}
                openExecutorSession={openExecutorSessionById}
                openTicketOverlay={(id) => handleTicketClick({ id } as Ticket, viewProject)} />
            </>
          )}
        </div>
        {/* Bottom strip: since t261008-21 the gear Settings popover (with the
            dwell input and the M2c placeholder) is retired — host order 261008
            option A pins the dwell window at 24 h (rule lives in sandbar-dwell).
            Only the spacer span remains, holding the original height. */}
        <div className="wb-sb-foot">
          <span className="wb-sb-foot-sp" />
        </div>
        {/* Project-lifecycle modals (ticket 3 face D): add (dry-run precheck with
            in-place errors) -> quarantine detail. t261008-36: the settings->remove
            chain moved to the executor panel's Settings tab (executor-view.tsx mounts
            the same components); the sidebar keeps add + quarantine. Write path =
            the host thin shell spawning the installer CLI (single source); the
            success callback re-pulls the registry (new project groups appear /
            removed groups vanish in the left column). */}
        {modal?.kind === 'add' && (
          <ProjectAddModal
            onClose={() => setModal(null)}
            onAdded={() => { setModal(null) }} />
        )}
        {modal?.kind === 'quarantine' && (
          <QuarantineModal entry={modal.entry} onClose={() => setModal(null)} />
        )}
      </div>
    </div>
  )
}
