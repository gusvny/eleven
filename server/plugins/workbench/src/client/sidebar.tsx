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
 *       文档 DocsSection（本插件，t260905-06）、模型 ProvidersSection（providers 插件）、
 *       立项单 EpicSection（本插件，t260826-02；空代号=立项清单，带代号=详情）。
 *       260823 起它们不再占 chat 顶部页签。t260903-07 起：点工单只在中列开详情抽屉，
 *       右栏 chat 恒为单全局会话不再切换（每工单会话联动下线，数据留存）。
 *       未选项目时中列显占位（不自动选第一个项目——不造隐形缺省）。
 */

import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import type { ComponentType } from 'react'
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
import { backfillProjectSeqs } from '../shared/sessions.ts'
import { getLedgerSnapshot, persistLedger } from './session-ledger-store.ts'
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
import { startChatProjectBandEffect, setChatProjectBand } from './chat-project-band.ts'
// 上下文折叠件（t260905-04）：带 CHARTER_MARKER 的注入消息收成可展开小条。
import { startContextFoldEffect } from './context-fold.ts'
// 项目色（票② R7）：确定性色板，同 key 恒同色。
import { projectColor } from '../shared/project-color.ts'
// 项目组头图标族（票③验收 11b）：五枚 SVG 线性图标（规格单源见模块头注）。
import { ProjectIcon } from './project-icons.tsx'
import type { ProjectIconName } from './project-icons.tsx'
// 项目生命周期四弹层（票③面D：设置/接入/摘除/隔离详情，验收 11-13）。
import { ProjectAddModal, ProjectRemoveModal, ProjectSettingsModal, QuarantineModal } from './project-modals.tsx'
// t260904-17 列表 v5：左栏工单条目=行卡迷你版（一套 UI 裁定，与中列同一组件/模型层）。
import { TicketRowCard } from './ticket-row-card.tsx'
// t260916-15 左栏合并排序：纯函数住 ticket-list-model 模型层（复用 deriveTicketState
// 四态单点投影 tier，不另起状态词表；node 可裸 import UT 直测）。
import { sortMergedTickets } from './ticket-list-model.ts'
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
import { MetricsPanel } from './metrics.tsx'
import { METRICS_STATE_EVENT, METRICS_TOGGLE_EVENT, footerSlotOk, mountMetricsIntoSettingsRow, shellActiveNow, subscribeShellActive } from './metrics-entry.tsx'
import { DERIVE_TOKENS_CSS } from './theme';

/* ---------------------------------------------------------------- 类型 */

/* t260903-07（用户拍板）：每工单会话联动下线——右侧 chat 恒为单全局会话，
 * 点工单只在中列开详情抽屉，不再建/找/切 `ticket-<id>` 会话。
 * 原 openTicketSessionFlow（t260831-08 会话恢复链）连同 TicketSessionFlowDeps
 * 整体删除（无其他消费方）。服务端 /api/ticket-session/open 路由与既有
 * ticket-* 会话数据按 ③ 口径留存（node.ts 两处留痕注释），回滚面完整。
 * 设计文档《sidebar-session-entry-and-hero-design.md》目标5/Nongoal 被本票推翻——
 * 同步债见 notes/debts/design-doc-sync-t260903-07.md（后续读者以债条目为准）。 */

interface Ticket {
  id: string
  /** 项目 key（注册表；host ticket-list 行带 project 字段）。 */
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
  /** 工单台（WorkbenchSection），focusId=要在详情抽屉里打开的工单；
   *  focusNonce=「又点了一次工单」信号（同 id 重开也触发——setState 同值跳渲染，
   *  只靠 focusId 传达不到）；listNonce=「点工单列表图标回列表」信号（通知关详情抽屉）。
   *  onOpenEpic=工单徽标点击（t260826-02）：中列切立项单视图并定位代号。 */
  board: ComponentType<{ focusId?: string; focusNonce?: number; listNonce?: number; projectKey?: string; onOpenEpic?: (code: string) => void }>
  /** 文档视图（t260905-06 立；t260915-10 接壳层）：初值/跟随=壳层当前项目，页内选择器
   *  可手动切且手动优先；''=无项目上下文→缺省引擎仓回落（既有语义不删）。 */
  docs: ComponentType<{ projectKey?: string }>
  /** 模型/路由（ProvidersSection）。 */
  routes: ComponentType<{ projectKey?: string }>
  /** 立项单（EpicSection，t260826-02）：epicCode/epicNonce=定位信号（同 code 重进靠 nonce，
   *  同 focusNonce 先例）；onOpenTicket=点关联工单行跳工单详情（复用 handleTicketClick 链路）。 */
  epics: ComponentType<{ epicCode?: string; epicNonce?: number; projectKey?: string; onOpenTicket?: (ticketId: string) => void }>
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

type RightView = 'board' | 'docs' | 'routes' | 'epics' | 'executor'

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

/* ---- sandbar（沙洲）：已完成工单在左栏的驻留时长（小时），默认 24。
 *  配置项落在 localStorage（工单台「设置」区的输入框写它），侧栏每次轮询渲染时现读。 */
const SANDBAR_KEY = 'sandbar-workbench-sandbar-v1'
const SANDBAR_DEFAULT_H = 24
export function sandbarHours(): number {
  const v = Number(localStorage.getItem(SANDBAR_KEY))
  return Number.isFinite(v) && v >= 0 && localStorage.getItem(SANDBAR_KEY) !== null ? v : SANDBAR_DEFAULT_H
}
export function setSandbarHours(h: number): void {
  localStorage.setItem(SANDBAR_KEY, String(h))
}

/** sandbar 驻留判定：已收口且 close_ts 还在驻留窗口内（close_ts 缺失时用 created 兜底）。 */
const inSandbar = (t: Ticket, nowS: number): boolean => {
  if (isOpen(t)) return true
  const h = sandbarHours()
  if (h <= 0) return false
  const ts = t.close_ts || t.created || 0
  return ts > 0 && nowS - ts < h * 3600
}

/* ---------------------------------------------------------------- 样式 */

const CSS = `${DERIVE_TOKENS_CSS}
.wb-sb { display:flex; flex-direction:column; height:100%; /* t260905-08：底改自适应 alias（平台 fill 层级高于 :root 注入无法跟随看守档位，可读性收敛到 alias 对）；装饰性 fill 见 --dsw-specific-sidebar-fill 保留在 group-head */ background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); color:var(--dsw-derive-fg,#1f2328); font-size:12px; }
/* 轨条态：仅图标 */
.wb-sb.rail { width:48px; align-items:center; padding-top:12px; }
.wb-sb.rail .wb-sb-icon { width:28px; height:28px; border-radius:6px; background:var(--dsw-alias-brand-primary,#7c3aed); display:flex; align-items:center; justify-content:center; font-size:14px; cursor:pointer; }
/* 展开态：双列。整窗三栏比例 左(项目+工单)15% : 中(视图)60% : 右(chat)25% ——
   左+中=侧栏占 75%（见下方 frame 第一轨改写），侧栏内部左右子列按 1:4 分。 */
.wb-sb.wide { flex-direction:row; }
.wb-sb-left { flex:1 1 0; min-width:180px; display:flex; flex-direction:column; border-right:1px solid var(--dsw-alias-border-l1,#333); }
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
/* metrics M2a（t260902-01）下栏：中列底部固定高度条（UI 规划 §2——左「📊 度量」、
   右 ⚙ settings；高度恒定，内容收进 ⚙ 弹层）。 */
.wb-sb-foot{display:flex;align-items:center;gap:8px;height:34px;padding:0 10px;border-top:1px solid var(--dsw-alias-border-l1,#333);flex:none;font-size:12px}
.wb-sb-foot-btn{display:inline-flex;align-items:center;gap:5px;border:none;background:none;color:var(--dsw-alias-label-primary,#1f2328);cursor:pointer;font:inherit;padding:4px 8px;border-radius:6px}
.wb-sb-foot-btn:hover{background:rgba(255,255,255,.08)}
.wb-sb-foot-btn[data-on=true]{color:var(--dsw-derive-accent,#0969da)}
.wb-sb-foot-sp{flex:1}
.wb-sb-setpop{position:absolute;right:8px;bottom:40px;z-index:96;background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff));border:1px solid var(--dsw-alias-border-l1,#333);border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:8px;min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.wb-sb-setpop .row{display:flex;align-items:center;gap:6px;font-size:12px}
.wb-sb-setpop input[type=number]{width:64px;font:inherit;font-size:12px;background:transparent;color:inherit;border:1px solid var(--dsw-alias-border-l1,#333);border-radius:4px;padding:2px 6px}
.wb-sb-setpop .t{font-size:12px;font-weight:600}
.wb-sb-setpop .m2c{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
/* 项目组 */
.wb-ticket-list { flex:1; overflow-y:auto; }
.wb-group-head { display:flex; align-items:center; gap:5px; padding:7px 8px 5px; cursor:pointer; font-weight:600; position:sticky; top:0; background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); z-index:1; }
.wb-group-head:hover { background:rgba(255,255,255,0.05); }
.wb-group-caret { font-size:9px; color:var(--dsw-derive-muted,#57606a); width:10px; }
.wb-group-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wb-group-count { margin-left:auto; font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; }
.wb-group-empty { padding:2px 8px 8px 24px; color:var(--dsw-derive-fg,#666); font-size:11px; }
/* t260904-17 列表 v5：工单条目=行卡迷你版（TicketRowCard compact）——暗色主题覆写：
 * 透明底、继承字色、选中紫调高亮；收口（data-state=done）淡一档 */
.wb-sb .wb-card { background:transparent; border-color:var(--dsw-derive-border,#d0d7de);
  box-shadow:none; color:var(--dsw-derive-fg,#1f2328); margin:0 6px 4px 14px; padding:5px 8px; }
.wb-sb .wb-card:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-sb .wb-card[data-active=true] { background:color-mix(in srgb,var(--dsw-derive-active,#7c3aed) 18%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); border-color:color-mix(in srgb,var(--dsw-derive-active,#7c3aed) 50%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); }
.wb-sb .wb-card[data-state=done] { opacity:0.72; } /* 对齐板面 .72：0.55 时次级字混底后 <3:1（看守实测） */
.wb-sb .wb-card-title { color:inherit; font-weight:400; }
.wb-sb .wb-card-state { color:inherit; }
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
/* 视图入口图标：右对齐放在每个项目组头行内（用户拍板 260823：per-project，不占独立行；
   t260827-01 起四个：工单/文档/模型/立项单；t260905-06 旧提法退役换文档） */
.wb-view-icons { display:flex; gap:2px; }
/* 图标族统一（票③ 11b）：命中区 26×26 radius 6，显形 18px（svg 由 ProjectIcon 定）；
   三态 idle/hover/active 沿用本侧栏既有色板（深色语境；mock 规格卡三态色为浅色
   语境定稿——图标本体吃 currentColor，几何规格统一是本模块契约）。 */
.wb-view-icon { width:26px; height:26px; display:flex; align-items:center; justify-content:center; border-radius:6px; cursor:pointer; opacity:0.55; }
.wb-view-icon:hover { background:rgba(255,255,255,0.1); opacity:1; }
.wb-view-icon.active { background:rgba(124,58,237,0.25); opacity:1; }
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
/* 中列：视图容器（四视图自带全套样式，无切换条——视图由左列图标直切） */
.wb-right-content { flex:1; overflow-y:auto; }
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
  // t260915-19 巡检分支：最近一次成功的巡检行快照（端点失败=保快照+显式降级横幅，
  // 绝不静默清空——KI-008/t260910-04 R3 同纪律，与中列 reloadTickets 同款）。
  const [inspectionRows, setInspectionRows] = useState<InspectionTicket[]>([])
  const [inspectionNote, setInspectionNote] = useState('')
  const inspectionRowsRef = useRef<InspectionTicket[]>([])
  // 兜底组折叠态：独立布尔——collapsed 的键是项目注册表 key，不与它混用（防撞名）。
  const [inspCollapsed, setInspCollapsed] = useState(false)
  const [selectedId, setSelectedId] = useState<string>('')
  const [rightView, setRightView] = useState<RightView>('board')
  /** 当前中列视图所属项目（左列图标点击行）；空=未选（中列显占位）。 */
  const [viewProject, setViewProject] = useState('')
  /** 「又点了一次工单」信号：随 focusId 传给 WorkbenchSection，
   *  同 id 重开（抽屉被 × 关掉后再点同一行）也能触发——focusId 同值时 effect 不 firing。 */
  const [focusNonce, setFocusNonce] = useState(0)
  /** 「点工单列表图标回列表」信号：viewProject/rightView 同值时 setState 跳渲染，
   *  详情抽屉（WorkbenchSection 内部 state）收不到通知——靠这个单调递增计数传达。 */
  const [listNonce, setListNonce] = useState(0)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  // 项目生命周期弹层（票③面D，验收 11-13）：kind 区分四弹层；settings→remove 由
  // 设置弹层 danger 区切换（同弹层面，非叠层）。
  const [modal, setModal] = useState<
    | { kind: 'settings'; project: Project }
    | { kind: 'remove'; project: Project }
    | { kind: 'add' }
    | { kind: 'quarantine'; entry: { key: string; dir: string; error: string } }
    | null
  >(null)
  /** 隔离条目（GET /wf/projects 的 quarantined 面，票③验收 11）：红色行渲染源。 */
  const [quarantined, setQuarantined] = useState<{ key: string; dir: string; error: string }[]>([])
  /** 立项单视图定位（t260826-02）：epicCode=当前立项代号；epicNonce=「又点了一次同一立项」
   *  信号（同 focusNonce 先例——同 code 重进也要触发 EpicSection 重拉）。 */
  const [epicCode, setEpicCode] = useState('')
  const [epicNonce, setEpicNonce] = useState(0)
  // metrics M2a（t260902-01）：度量面板开/关 + ⚙ settings 弹层；「度量」钮 ref
  // 供面板关闭时焦点归还（焦点管理最小实现）。
  const [metricsOpen, setMetricsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const metricsBtnRef = useRef<HTMLButtonElement | null>(null)
  // 兜底钮显隐（响应式）：footerSlotOk() 是注册回调的滞后快照（首次渲染时常为
  // false，探针实锤兜底钮与覆盖层并存）——以 shell 覆盖层激活态订阅兜底，
  // 覆盖层激活即隐兜底钮（双入口消除），注册失败且覆盖层不可用才显示。
  const [shellActive, setShellActive] = useState(shellActiveNow)
  useEffect(() => subscribeShellActive(setShellActive), [])
  // 入口联动（t260902-05①）：footer.action 槽钮（另一棵 React 子树）经事件总线
  // 开/关面板；面板开合状态回播给钮做高亮。cleanup 双向都摘。
  useEffect(() => {
    const onToggle = () => { setSettingsOpen(false); setMetricsOpen(o => !o) }
    document.addEventListener(METRICS_TOGGLE_EVENT, onToggle)
    return () => { document.removeEventListener(METRICS_TOGGLE_EVENT, onToggle) }
  }, [])
  useEffect(() => {
    document.dispatchEvent(new CustomEvent(METRICS_STATE_EVENT, { detail: { open: metricsOpen } }))
  }, [metricsOpen])
  const [sandbar, setSandbar] = useState(sandbarHours)
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

  // chat 项目色带（票② R7）：挂 head 自有 style + body 子树 Observer。
  // F1 防呆接线：effect 返回 startChatProjectBandEffect 的清理函数本身
  // （直接返回 handle 会被 useEffect 静默忽略→卸载零回收，t260903-07 F1 实案）。
  useEffect(() => {
    if (!wide) return
    return startChatProjectBandEffect({})
  }, [wide])

  // 上下文折叠件（t260905-04）：把带 CHARTER_MARKER 的注入消息收成可展开小条。
  // 与色带同为「chat 滚动体装饰器」，接线同位对齐（同 hook 体内相邻 effect，
  // 生命周期同源、卸载同路径——方案 review C5 定稿）。F1 防呆接线同款。
  useEffect(() => {
    if (!wide) return
    return startContextFoldEffect()
  }, [wide])

  // 色带归属推导（票② R7）：current → 账册 project（纯查表，不在装饰器内
  // 推导）。不在册（工单会话/磁盘存量/blank hero/current 为空）→ 传 null=
  // 摘除属性不渲染——声明行为，不造隐形缺省。
  useEffect(() => {
    if (!wide) return
    const cur = projectSessions.listState?.current
    const entry = cur ? projectSessions.ledger.find(e => e.id === cur) : undefined
    setChatProjectBand(entry?.project ?? null)
  }, [wide, projectSessions.listState?.current, projectSessions.ledger])

  // 度量入口首选注入 shell Settings 行（t260902-05① 验收打回修订：footer.action
  // 槽落点=侧栏包 footer，与 shell Settings 不同排）。锚找不到软退化回 footer.action
  // 槽（metrics-entry 内广播 METRICS_SHELL_EVENT 控制槽钮显隐）；卸载/折叠全回收。
  useEffect(() => {
    if (!wide) return
    const root = rootRef.current
    if (!root) return
    return mountMetricsIntoSettingsRow(root)
  }, [wide])

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
        if (cancelled) return
        setTicketsByProject(Object.fromEntries(entries))
      } catch { /* 静默 */ }
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
  }, [wide])

  // 点工单（t260903-07 起）：只在中列开工单详情抽屉，右栏 chat 恒为全局会话
  // 不切换（联动下线口径见本文件头部注释）。左列行/立项单关联行/度量下钻三入口共用。
  const handleTicketClick = useCallback((t: Ticket, projectKey: string) => {
    setSelectedId(t.id)
    // t260915-19：projectKey 空（巡检兜底组行，无项目身份）时保持现值、无现值
    // 兜底首项目（openEpic 同款先例）——Board 挂载门（index.tsx !projectKey 早退）
    // 需要非空 projectKey 才能开详情抽屉；零注册项目时选中态在、中列保持占位
    // （既有边界交回，本票不做 index.tsx 结构手术）。项目组行传非空 key=原行为。
    setViewProject(p => projectKey || p || (projects.length > 0 ? projects[0].key : ''))
    setRightView('board')
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
  const handleViewIcon = useCallback((projectKey: string, view: RightView) => {
    if (view === 'board') {
      setSelectedId('')
      setListNonce(n => n + 1)
    }
    if (view === 'epics') {
      setEpicCode('')
      setEpicNonce(n => n + 1)
    }
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
    return projects.map(p => ({
      project: p,
      // t260916-15 合并排序：dev 行与巡检行拼接后按统一口径排（在等你/受阻→在跑→
      // 已完成，级内 updated_ts 倒序）——巡检行不因数据来源沉底（宿主 260916 实报）。
      // 排序纯函数 sortMergedTickets 住 ticket-list-model 层，UT/场景双看守。
      tickets: sortMergedTickets([
        ...(ticketsByProject[p.key] ?? []).filter(t => inSandbar(t, nowS)),
        // 驻留窗分工（review gen2 意见2 钉一句话）：客户端 sandbarHours 窗只管上面
        // dev-lane 行（inSandbar）；巡检行不经此窗——闭合行窗由引擎 R8 窗承担
        // （超窗/close_ts 缺失不上板，t260915-08 board-rows 场景看守）。
        // 此非「漏过滤」，勿当缺陷误修。
        ...(inspectionSplit.byProject[p.key] ?? []),
      ]),
    }))
  }, [projects, ticketsByProject, inspectionSplit])

  const Board = views.board
  const Docs = views.docs
  const Routes = views.routes
  const Epics = views.epics

  // 进立项单详情视图（工单徽标点击，t260826-02）：中列切 epics 并定位代号。
  // （t260827-01 起左列不再有立项列表区，清单入口=项目行立项单图标，走 handleViewIcon。）
  // viewProject 兜底注册表首项——立项单列表/详情本身不需要 project，但详情页「新建工单」
  // 与点关联工单行需要（?project= 必传）；立项单是跨项目语义单元（EpicCode SA 不带项目维度）。
  const openEpic = useCallback((code: string) => {
    setEpicCode(code)
    setEpicNonce(n => n + 1)
    setRightView('epics')
    setViewProject(p => p || (projects.length > 0 ? projects[0].key : ''))
  }, [projects])

  // 轨条态
  if (!wide) {
    return (
      <div ref={rootRef} className="wb-sb rail">
        <style>{CSS}</style>
        <div className="wb-sb-icon" onClick={expandSidebar} title="Ticket Board">⊞</div>
      </div>
    )
  }

  // 展开态：双列
  return (
    <div ref={rootRef} className="wb-sb wide">
      <style>{CSS}</style>
      {/* 左列：项目分组（可折叠）+ 插件入口。顶部会话入口行已随票② R8 退役
          （t260904-05）：入口收口为各组的项目内会话区，出厂全局钮由注入 effect 压制。 */}
      <div className="wb-sb-left">
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
            <div key={g.project.key}>
              {/* t260929-22（GAP A）：项目名行本身=执行器入口（设计稿 260927 §界面与命名：
                  一个项目一行、项目名即 project executor 的入口，不单列 Tick 行）——
                  折叠退到 caret 单独承担（一次点击只做一件事）；五个视图图标语义不变。 */}
              <div className="wb-group-head" style={{ cursor: 'pointer' }}
                title={`Open ${g.project.name} executor panel`}
                onClick={() => handleViewIcon(g.project.key, 'executor')}>
                <span className="wb-group-caret" title={collapsed[g.project.key] ? 'Expand' : 'Collapse'}
                  onClick={(e) => { e.stopPropagation(); setCollapsed(c => ({ ...c, [g.project.key]: !c[g.project.key] })) }}>{collapsed[g.project.key] ? '▸' : '▾'}</span>
                {/* 项目色点（票② R7 拍板 5）：8px 常驻项目色标识，色=projectColor 确定性色板 */}
                <span className="wb-group-dot" data-wb-psess-dot="" style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, flex: 'none', background: projectColor(g.project.key) }} title={g.project.key} />
                <span className="wb-group-name" data-wb-executor-entry=""
                  role="button" tabIndex={0}
                  aria-label={`Open ${g.project.name} executor panel`}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleViewIcon(g.project.key, 'executor') }}
                  onClick={() => handleViewIcon(g.project.key, 'executor')}>{g.project.name}</span>
                <span className="wb-group-count">{g.tickets.length || ''}</span>
                {/* 视图入口 per 项目（用户拍板 260823：每个项目组头行都有，非全局）——
                    按行项目分流：工单列表=该项目 ProjectKey 过滤、模型路由=该项目主目录
                    model-routes.yaml；立项单（t260827-01）=全量立项清单（跨项目语义单元，
                    不按项目过滤）；文档（t260905-06 立；t260915-10 接壳层）=点哪组图标
                    默认开哪组 docs（初值/跟随=本行项目），页内选择器可手动切且手动优先
                    （重开文档页=重新跟随壳层，收敛口径见 docs.tsx 头注）；
                    active 高亮只判 rightView（跨组同亮，t260915-10 口径不变）。 */}
                <span className="wb-view-icons" onClick={e => e.stopPropagation()}>
                  <span
                    className={`wb-view-icon ${rightView === 'board' && viewProject === g.project.key ? 'active' : ''}`}
                    title="Tickets" aria-label="Tickets"
                    onClick={() => handleViewIcon(g.project.key, 'board')}><ProjectIcon name="board" /></span>
                  {/* 键盘可达（t260905-06 验收①）：span 非原生可聚焦——role+tabIndex+Enter 键位补齐。 */}
                  <span
                    className={`wb-view-icon ${rightView === 'docs' ? 'active' : ''}`}
                    role="button" tabIndex={0}
                    title="Docs" aria-label="Docs"
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleViewIcon(g.project.key, 'docs') }}
                    onClick={() => handleViewIcon(g.project.key, 'docs')}><ProjectIcon name="docs" /></span>
                  <span
                    className={`wb-view-icon ${rightView === 'routes' && viewProject === g.project.key ? 'active' : ''}`}
                    title="Model Routes" aria-label="Model Routes"
                    onClick={() => handleViewIcon(g.project.key, 'routes')}><ProjectIcon name="routes" /></span>
                  <span
                    className={`wb-view-icon ${rightView === 'epics' && viewProject === g.project.key ? 'active' : ''}`}
                    title="Epics" aria-label="Epics"
                    onClick={() => handleViewIcon(g.project.key, 'epics')}><ProjectIcon name="epics" /></span>
                  {/* 第五枚=项目设置（票③面D）：常驻可见，开设置弹层（只读+danger 区摘除）。 */}
                  <span className="wb-view-icon" data-wb-project-settings-entry=""
                    title="Project Settings" aria-label="Project Settings"
                    onClick={() => { setModal({ kind: 'settings', project: g.project }) }}><ProjectIcon name="settings" /></span>
                </span>
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
                    // t260915-19：组内巡检行（t260915-20 起带项目身份，ProjectKey SA
                    // 归组）走最小适配——行1 标题引擎已给「巡检 <实例> · 期 <期号>」
                    // 零适配；行2 传本地纯函数合成进展（等你签字 · 发现 高x/中y/低z，
                    // 词表与中列同源）；「等你」黄调由 data-engine=inspection 等值
                    // 选择器接管（见 CSS 注释，项目行零变化）。
                    // t260916-15：行1 加类别徽标（INSPECTION_ROW_BADGE chip，词表
                    // 单点在 host 层）——合并排序后巡检行混入组内各位置，数据来源
                    // 须行随身可辨，不靠「恒在组尾」的旧位置线索。
                    const insp = isInspectionRow(t)
                    return (
                      /* t260904-17 列表 v5（mock 屏⑤）：左栏工单条目=行卡迷你版（一套 UI；
                       * compact 省略站道/管理动作位）。状态短名/配色由四态枚举驱动
                       * （与中列同一模型层口径）。 */
                      <TicketRowCard key={t.id} t={t} compact
                        wf={insp ? INSPECTION_WF_LIKE : undefined}
                        progress={insp ? inspectionProgressOf(t) : undefined}
                        kindBadge={insp ? { text: INSPECTION_ROW_BADGE } : undefined}
                        active={selectedId === t.id}
                        updatedTsMs={(isOpen(t) ? t.created : (t.close_ts || t.created)) !== undefined
                          ? (isOpen(t) ? t.created : (t.close_ts || t.created))! * 1000 : undefined}
                        onOpen={() => handleTicketClick(t, g.project.key)} />
                    )
                  })}
                </>
              )}
            </div>
          ))}
          {/* 巡检兜底组（t260915-19）：project 为空（20 之前老票）或不在注册表
              （隔离 key/摘除项目）的巡检票显式落此组——不静默丢失（工单④）。
              无此类行=整组不渲染（不占位不报错，组头计数同款）；行渲染与项目组
              巡检行同款适配（含 t260916-15 类别徽标），组内行序同口径合并排序；
              点击走 handleTicketClick（projectKey 空→兜底首项目，见其注释）。 */}
          {!loading && inspectionSplit.unowned.length > 0 && (
            <div>
              <div className="wb-group-head" data-testid="sidebar-inspection-head"
                onClick={() => setInspCollapsed(c => !c)}>
                <span className="wb-group-caret">{inspCollapsed ? '▸' : '▾'}</span>
                <span className="wb-group-name">{INSPECTION_ROW_BADGE}</span>
                <span className="wb-group-count">{inspectionSplit.unowned.length}</span>
              </div>
              {!inspCollapsed && sortMergedTickets(inspectionSplit.unowned).map(t => (
                <TicketRowCard key={t.id} t={t} compact
                  wf={INSPECTION_WF_LIKE} progress={inspectionProgressOf(t)}
                  kindBadge={{ text: INSPECTION_ROW_BADGE }}
                  active={selectedId === t.id}
                  updatedTsMs={(isOpen(t) ? t.created : (t.close_ts || t.created)) !== undefined
                    ? (isOpen(t) ? t.created : (t.close_ts || t.created))! * 1000 : undefined}
                  onOpen={() => handleTicketClick(t, '')} />
              ))}
            </div>
          )}
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
              Open a view from a project row on the left:
              <br />Tickets · Docs · Model Routes · Epics · Project Settings
              <br />or click a project name row to open its Executor panel
              <br />(routed by the row's project; Epics is a cross-project list — clicking its icon shows the list in the middle column)
            </div>
          )}
          {/* 执行器视图（t260929-22 GAP A）：项目行入口点进来；iframe 嵌同源面板页，
              Chat 分支按声明开 executor 会话（判定在 executor-view-model，绝不自 declare）。 */}
          {viewProject && rightView === 'executor' && (
            <ExecutorView
              projectKey={viewProject}
              listedSessionIds={Object.keys((projectSessions.listState?.byId ?? {}) as Record<string, unknown>)}
              openExecutorSession={openExecutorSessionById} />
          )}
          {viewProject && rightView === 'board' && <Board focusId={selectedId || undefined} focusNonce={focusNonce} listNonce={listNonce} projectKey={viewProject} onOpenEpic={openEpic} />}
          {/* 文档视图（t260905-06 立；t260915-10 接壳层 projectKey）：与 per-project 视图
              同通路穿参，但不要求已选项目（''=缺省引擎仓回落）——渲染行不带 viewProject
              守卫（Board 渲染守卫不带，取舍清单见 t260915-10 方案 §1.6）。 */}
          {rightView === 'docs' && <Docs projectKey={viewProject} />}
          {viewProject && rightView === 'routes' && <Routes projectKey={viewProject} />}
          {/* 立项单视图（t260826-02 中列第四视图；t260827-01 起空代号=立项清单，由项目行
              立项单图标进入，详情由清单行/工单徽标定位）：点关联工单行 → 复用 handleTicketClick
              链路（中列工单详情抽屉 + 右栏会话）；handleTicketClick 只用 t.id，最小形状安全。 */}
          {viewProject && rightView === 'epics' && (
            <Epics epicCode={epicCode} epicNonce={epicNonce} projectKey={viewProject}
              onOpenTicket={(id) => { void handleTicketClick({ id } as Ticket, viewProject) }} />
          )}
          {/* 度量面板（t260902-05② 中 pane 化）：挂在 .wb-sb-right（position:relative）
              内的覆盖层，inset:0 随中列自适应——不再全幅。打开才挂载，关闭即释放
              全部图表实例。 */}
          {metricsOpen && (
            <MetricsPanel
              openerRef={metricsBtnRef}
              onClose={() => { setMetricsOpen(false) }}
              onPickTicket={(id) => { void handleTicketClick({ id } as Ticket, viewProject) }} />
          )}
        </div>
        {/* 下栏（t260902-05 修订）：度量入口已迁出厂 footer.action 槽（与 dsh settings
            同排）；此处仅剩 ⚙ settings 弹层（工单台自有 sandbar 驻留设置 + M2c 预留位）。
            槽注册失败（软退化）时兜底「📊 度量」钮回此排，功能不丢。 */}
        <div className="wb-sb-foot">
          {!footerSlotOk() && !shellActive && (
            <button ref={metricsBtnRef} className="wb-sb-foot-btn" data-on={metricsOpen}
              title="Metrics (stage durations / delivery / tokens / system health)"
              onClick={() => { setSettingsOpen(false); setMetricsOpen(o => !o) }}>📊 Metrics</button>
          )}
          <span className="wb-sb-foot-sp" />
          <button className="wb-sb-foot-btn" data-on={settingsOpen} title="Settings"
            onClick={() => { setMetricsOpen(false); setSettingsOpen(o => !o) }}>⚙</button>
        </div>
        {settingsOpen && (
          <div className="wb-sb-setpop" role="dialog" aria-label="Settings">
            <div className="t">Settings</div>
            {/* sandbar 驻留输入（原 board 筛选行内联输入迁来；localStorage key 与
                sandbarHours/setSandbarHours 语义不变，侧栏轮询每次现读）。 */}
            <label className="row" title="How long closed tickets stay in the sidebar groups (hours; 0 = hide immediately)">
              Sandbar dwell
              <input type="number" min={0} step={1} value={sandbar}
                onChange={e => {
                  const h = Math.max(0, Number(e.target.value) || 0)
                  setSandbar(h)
                  setSandbarHours(h)
                }} />
              hours
            </label>
            <div className="m2c">Quiet in-progress threshold (minutes): ships with the M2c system-health tab.</div>
          </div>
        )}
        {/* 项目生命周期四弹层（票③面D）：设置（只读+danger 区）→ 摘除四步流 →
            接入（预检 dry-run+就地错误）→ 隔离详情。写路径=host 薄壳 spawn 安装器
            CLI（单源）；成功回调重拉注册表（左栏即时出现新项目组/即时消失被摘组）。 */}
        {modal?.kind === 'settings' && (
          <ProjectSettingsModal
            project={modal.project}
            onClose={() => setModal(null)}
            onRemove={() => setModal({ kind: 'remove', project: modal.project })} />
        )}
        {modal?.kind === 'remove' && (
          <ProjectRemoveModal
            project={modal.project}
            onClose={() => setModal(null)}
            onRemoved={() => { setModal(null) }} />
        )}
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
