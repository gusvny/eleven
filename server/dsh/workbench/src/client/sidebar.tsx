/**
 * suyou-workbench · 侧栏接管 —— 双列布局（项目分组+工单 | 四视图）
 *
 * 注册到 sidebar.workspaces 槽（single，priority=-10 抢占 shell 默认浏览器——lowest renders）。
 * Shell 传 ownerProps: wide / expandSidebar。
 * wide=false 时只显品牌图标；wide=true 时显完整双列。
 *
 * 左列：顶部会话入口行（t260831-02：出厂「⊕ New Session」行的原地替换——
 *       「+ 新建会话」+ 本项目最近打开的会话切换，≤5 个 MRU、current 高亮。
 *       出厂钮不在任何槽里（sidebar 包只声明 workspaces/settings/footer.action
 *       三槽，实查平台包），按工单口径走「注入+语义锚」：下方 useHideFactoryNewSession
 *       effect 以 aria-label（session-entry.tsx FACTORY_NEW_LABELS，zh/en 全集）
 *       在 SidebarRoot 直接子 button 上定位出厂钮置 display:none（零 CSS 类名
 *       匹配，t260828-06 死因不复犯），MutationObserver 兜防工厂重渲染复活，
 *       卸载/折叠 cleanup 还原；找不到锚=软退化（出厂钮照常、入口仍在，warn 留痕）。
 *       数据=插件记账层（localStorage 账册，只登记 UI 主动打开/新建；磁盘存量/
 *       工单/subagent 会话不进账册），ctx.sessions.list 只取标题与 current；
 *       规则=shared/sessions.ts 纯函数；组件本体 client/session-entry.tsx 的
 *       <SessionTopEntry>。t260828-02 的左栏「会话」区块已整块移除（t260831-02），
 *       记账层保留在内部只供本入口）
 *       + 项目组（可折叠，项目名分隔，只列进行中工单，两行式条目：行1=title，行2=彩色工单号 + role·创建时长）；
 *       每组头下、工单列表上另有项目内会话区一横排（session-entry 第 3 面①：
 *       正方形「+」+ 正方形数字 tab，编号=项目内登记顺序关闭不回收，超宽换行；
 *       组件 project-session-row.tsx，动作=本组件 useSessionEntry 二号实例——
 *       顶部行过渡期 260904 混排口径不变，R8 验收后退役）。
 *       项目组头行右对齐四个项目级视图入口图标：📋 工单列表 / 📖 知识库 / 🔀 模型路由 / 🗂️ 立项单
 *       （t260827-01：立项单从「左列可折叠列表区」改为项目级图标，与其他三视图同款；
 *       左列不再显示立项列表，点图标后中列显示立项清单）。
 *       项目组 = server/dsh/projects.yaml 注册表（260823 多项目化：project 是逻辑概念，
 *       1:N 对应目录）；每组工单按 ?project=<key> 单独拉取（Temporal ProjectKey SA 过滤）。
 * 中列：四视图由 index.tsx 注入（views prop）——工单台 WorkbenchSection（本插件）、
 *       知识库 KnowledgeSection（knowledge 插件）、模型 ProvidersSection（providers 插件）、
 *       立项单 EpicSection（本插件，t260826-02；空代号=立项清单，带代号=详情）。
 *       260823 起它们不再占 chat 顶部页签。t260903-07 起：点工单只在中列开详情抽屉，
 *       右栏 chat 恒为单全局会话不再切换（每工单会话联动下线，数据留存）。
 *       未选项目时中列显占位（不自动选第一个项目——不造隐形缺省）。
 */

import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import type { ComponentType } from 'react'
// 会话列表快照类型（t260828-02 起只取 displayTitle/current 两字段）：ctx.sessions.list 的面。
import type { ObservableSnapshot, SessionListState } from '@deepseek-ai/dsh-client-runtime/client'
// 顶部会话入口组件与记账层（t260831-02：SessionTopEntry + 出厂钮语义锚；session-entry.tsx
// 持有 LEDGER_KEY / useSessionEntry hook；本文件留侧栏样式、布局与注入 effect）。
import { SessionTopEntry, FACTORY_NEW_LABELS, useSessionEntry } from './session-entry.tsx'
// 项目内会话区（session-entry 第 3 面①，R1–R6）：每项目组头下、工单列表上的
// 一横排（+ 钮 + 数字 tab + 确认弹层）；动作由本组件的 useSessionEntry 二号
// 实例注入（账册=模块级共享 store，与顶部行同帧一致）。
import { ProjectSessionRow } from './project-session-row.tsx'
// 存量编号迁移（第 3 面① 拍板 1）：账册缺 seq 条目按项目内登记序补号（幂等）。
import { backfillProjectSeqs } from '../shared/sessions.ts'
import { getLedgerSnapshot, persistLedger } from './session-ledger-store.ts'
// host 陈旧全局提醒（t260902-03）：useStaleHost 单例挂本组件；横幅渲染在
// .wb-sb-right 共享容器（四视图排他渲染之上），所有页签/视图常驻可见。
import { useStaleHost } from './staleness.ts'
import { startVisibleInterval } from './visibility-poll.ts'
import type { SessionsFace } from './session-entry.tsx'
// 项目索引单态（t260903-07 工单②）：load() 成功分支向 chat 项目 tag 装饰器发布
// 项目集与逐项目工单映射（失败分支不发——KI-018 同族：失败不得顶掉 last-known-good）。
import { publishProjectEntry, publishProjects } from './project-tag-index.ts'
// chat 项目 tag 装饰器（t260903-07 工单②）：挂/卸随本组件生命周期（插件在装即挂）。
import { startChatProjectTagEffect } from './chat-project-tag.ts'
// metrics M2a（t260902-01）：度量面板。t260902-05 起：入口迁出厂侧栏
// footer.action 槽（与 dsh settings 同排，用户反馈①），面板中 pane 化挂进
// .wb-sb-right（反馈②）。槽注册失败软退化回 .wb-sb-foot 兜底钮（console.warn）。
// ⚙ settings 弹层（收 sandbar 驻留输入）保留在中列底部——工单台自有设置，
// 与出厂 settings 语义不同（t260902-05 方案 v2 R6-① 决策）。下钻：关面板后走
// handleTicketClick 开详情抽屉。
import { MetricsPanel } from './metrics.tsx'
import { METRICS_STATE_EVENT, METRICS_TOGGLE_EVENT, footerSlotOk, mountMetricsIntoSettingsRow, shellActiveNow, subscribeShellActive } from './metrics-entry.tsx'

/* ---------------------------------------------------------------- 类型 */

/* t260903-07（用户拍板）：每工单会话联动下线——右侧 chat 恒为单全局会话，
 * 点工单只在中列开详情抽屉，不再建/找/切 `ticket-<id>` 会话。
 * 原 openTicketSessionFlow（t260831-08 会话恢复链）连同 TicketSessionFlowDeps
 * 整体删除（无其他消费方）。服务端 /api/ticket-session/open 路由与既有
 * ticket-* 会话数据按 ③ 口径留存（node.ts 两处留痕注释），回滚面完整。
 * 设计文档《右栏会话入口与hero定制设计.md》目标5/Nongoal 被本票推翻——
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
  blocked_reason?: string
  pending?: { gate: string; reason: string }[]
  session_kb?: number
  agent_alive?: boolean
}

/** 项目注册表条目（GET /wf/projects）。 */
interface Project {
  key: string
  name: string
  dirs: string[]
  /** 主目录（dirs 首个）：知识库/模型路由/会话 cwd 兜底都走它。 */
  primary: string
}

/** 中列视图，由 index.tsx 注入（避免 sidebar→index 循环 import；t260826-02 起三视图 + 立项单第四视图）。 */
interface MiddleViews {
  /** 工单台（WorkbenchSection），focusId=要在详情抽屉里打开的工单；
   *  focusNonce=「又点了一次工单」信号（同 id 重开也触发——setState 同值跳渲染，
   *  只靠 focusId 传达不到）；listNonce=「点 📋 回工单列表」信号（通知关详情抽屉）。
   *  onOpenEpic=工单徽标点击（t260826-02）：中列切立项单视图并定位代号。 */
  board: ComponentType<{ focusId?: string; focusNonce?: number; listNonce?: number; projectKey?: string; onOpenEpic?: (code: string) => void }>
  /** 知识库（KnowledgeSection）。 */
  knowledge: ComponentType<{ projectKey?: string }>
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
   *  t260831-04 gen2 勘误：WorkspaceBrowserInjected 是 ui-workspace 注册者私有
   *  注入，slot owner props 里没有 open——本 prop 恒 undefined，历史分支仅留
   *  兼容，真正的新建语义走下方 workspaces 公开服务。 */
  open?: (sessionId: string) => void
  /** 客户端 workspaces 服务（index.tsx 的 ctx.workspaces）：顶部入口「新建会话」
   *  走 startSession（工厂同款：绑工作区+复用 blank+正确打开，t260831-04）。 */
  workspaces?: {
    list: ObservableSnapshot<{ items: readonly { workspaceId: string; path: string }[] }>
    startSession(workspaceId?: string): void
    create(input: { path: string }): Promise<{ workspaceId: string }>
  }
  /** 中列三视图（index.tsx 注入）。 */
  views: MiddleViews
}

type RightView = 'board' | 'knowledge' | 'routes' | 'epics'

/* ---------------------------------------------------------------- 口径 */

/**
 * 状态色（用户拍板口径）：红=有问题（blocked/rework）、黄=待审核（awaiting-human/settled）、
 * 蓝=运行中（running）、绿=完成（verified/closed）、灰=等待（awaiting）。
 */
function stateColor(t: Ticket): string {
  if (t.stage_state === 'blocked' || t.status === 'rework') return '#ef4444'
  if (t.stage_state === 'awaiting-human' || t.status === 'settled') return '#f59e0b'
  if (t.stage_state === 'running') return '#3b82f6'
  if (t.status === 'verified' || t.status === 'closed') return '#22c55e'
  return '#9ca3af'
}

/** 未完成 = 生命周期未收口（dispatched/settled/rework）。项目组里只列这些。 */
const isOpen = (t: Ticket): boolean => t.status !== 'closed' && t.status !== 'verified'

/* ---- sandbar（沙洲）：已完成工单在左栏的驻留时长（小时），默认 24。
 *  配置项落在 localStorage（工单台「设置」区的输入框写它），侧栏每次轮询渲染时现读。 */
const SANDBAR_KEY = 'suyou-workbench-sandbar-v1'
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

/** 创建时长紧凑格式：45m / 8h / 1d / 1d2h / 1w / 1w3d。 */
function ageOf(created?: number): string {
  if (!created) return '—'
  const s = Math.max(0, Date.now() / 1000 - created)
  const m = Math.floor(s / 60)
  const h = Math.floor(s / 3600)
  const d = Math.floor(s / 86400)
  const w = Math.floor(d / 7)
  if (w > 0) return d % 7 ? `${w}w${d % 7}d` : `${w}w`
  if (d > 0) return h % 24 ? `${d}d${h % 24}h` : `${d}d`
  if (h > 0) return `${h}h`
  return `${m}m`
}

/* ---------------------------------------------------------------- 样式 */

const CSS = `
.wb-sb { display:flex; flex-direction:column; height:100%; background:var(--dsw-specific-sidebar-fill, #1a1a2e); color:var(--dsw-alias-label-primary,#e0e0e0); font-size:12px; }
/* 轨条态：仅图标 */
.wb-sb.rail { width:48px; align-items:center; padding-top:12px; }
.wb-sb.rail .wb-sb-icon { width:28px; height:28px; border-radius:6px; background:var(--dsw-alias-brand-primary,#7c3aed); display:flex; align-items:center; justify-content:center; font-size:14px; cursor:pointer; }
/* 展开态：双列。整窗三栏比例 左(项目+工单)15% : 中(视图)60% : 右(chat)25% ——
   左+中=侧栏占 75%（见下方 frame 第一轨改写），侧栏内部左右子列按 1:4 分。 */
.wb-sb.wide { flex-direction:row; }
.wb-sb-left { flex:1 1 0; min-width:180px; display:flex; flex-direction:column; border-right:1px solid var(--dsw-alias-border-l1,#333); }
/* position:relative —— 工单详情抽屉（index.tsx .wb-drawer，absolute）的定位祖先，
   让抽屉铺满中列而不是全窗（260824 用户拍板：详情显在中列）。 */
.wb-sb-right { flex:4 1 0; display:flex; flex-direction:column; overflow:hidden; min-width:200px; background:var(--dsw-alias-bg-primary,#0f0f1a); position:relative; }
/* host 陈旧全局提醒（t260902-03）：中列共享容器顶部横幅，flex:none 不挤占四视图与
   下栏；琥珀底一眼可辨，与 running 绿/blocked 红色板错开。 */
.wb-stale-banner { flex:none; display:flex; align-items:center; gap:10px; padding:8px 12px;
  background:#7a4a06; color:#ffe9c4; border-bottom:1px solid #b8860b; font-size:12px; }
.wb-stale-banner .wb-stale-msg { flex:1; line-height:1.5; }
.wb-stale-banner .wb-stale-msg strong { color:#ffd166; }
.wb-stale-banner .wb-stale-dismiss { flex:none; border:1px solid #b8860b; background:transparent;
  color:#ffe9c4; border-radius:6px; padding:2px 10px; font:inherit; font-size:12px; cursor:pointer; }
.wb-stale-banner .wb-stale-dismiss:hover { background:rgba(255,255,255,0.12); }
/* metrics M2a（t260902-01）下栏：中列底部固定高度条（UI 规划 §2——左「📊 度量」、
   右 ⚙ settings；高度恒定，内容收进 ⚙ 弹层）。 */
.wb-sb-foot{display:flex;align-items:center;gap:8px;height:34px;padding:0 10px;border-top:1px solid var(--dsw-alias-border-l1,#333);flex:none;font-size:12px}
.wb-sb-foot-btn{display:inline-flex;align-items:center;gap:5px;border:none;background:none;color:var(--dsw-alias-label-primary,#e0e0e0);cursor:pointer;font:inherit;padding:4px 8px;border-radius:6px}
.wb-sb-foot-btn:hover{background:rgba(255,255,255,.08)}
.wb-sb-foot-btn[data-on=true]{color:#7ee787}
.wb-sb-foot-sp{flex:1}
.wb-sb-setpop{position:absolute;right:8px;bottom:40px;z-index:96;background:var(--dsw-alias-bg-primary,#0f0f1a);border:1px solid var(--dsw-alias-border-l1,#333);border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:8px;min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.wb-sb-setpop .row{display:flex;align-items:center;gap:6px;font-size:12px}
.wb-sb-setpop input[type=number]{width:64px;font:inherit;font-size:12px;background:transparent;color:inherit;border:1px solid var(--dsw-alias-border-l1,#333);border-radius:4px;padding:2px 6px}
.wb-sb-setpop .t{font-size:12px;font-weight:600}
.wb-sb-setpop .m2c{font-size:11px;color:#8c959f}
/* 项目组 */
.wb-ticket-list { flex:1; overflow-y:auto; }
.wb-group-head { display:flex; align-items:center; gap:5px; padding:7px 8px 5px; cursor:pointer; font-weight:600; position:sticky; top:0; background:var(--dsw-specific-sidebar-fill,#1a1a2e); z-index:1; }
.wb-group-head:hover { background:rgba(255,255,255,0.05); }
.wb-group-caret { font-size:9px; color:var(--dsw-alias-label-secondary,#888); width:10px; }
.wb-group-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wb-group-count { margin-left:auto; font-size:10px; color:var(--dsw-alias-label-secondary,#888); font-weight:400; }
.wb-group-empty { padding:2px 8px 8px 24px; color:#666; font-size:11px; }
/* 两行式工单条目：行1=title（单行省略），行2=彩色工单号 + role · 创建时长 */
.wb-ticket-row2 { padding:5px 10px 5px 20px; cursor:pointer; border-bottom:1px solid rgba(255,255,255,0.04); }
.wb-ticket-row2:hover { background:rgba(255,255,255,0.06); }
.wb-ticket-row2.selected { background:rgba(124,58,237,0.18); }
/* sandbar 驻留的已完成条目：淡一档，一眼区分「还在跑的」和「刚收口的」 */
.wb-ticket-row2.done { opacity:0.55; }
.wb-ticket-l1 { font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.wb-ticket-l2 { font-size:11px; color:var(--dsw-alias-label-secondary,#888); margin-top:1px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* 视图入口图标：右对齐放在每个项目组头行内（用户拍板 260823：per-project，不占独立行；
   t260827-01 起四个：工单/知识库/模型/立项单） */
.wb-view-icons { display:flex; gap:2px; }
.wb-view-icon { width:22px; height:22px; display:flex; align-items:center; justify-content:center; border-radius:4px; cursor:pointer; font-size:12px; opacity:0.55; }
.wb-view-icon:hover { background:rgba(255,255,255,0.1); opacity:1; }
.wb-view-icon.active { background:rgba(124,58,237,0.25); opacity:1; }
/* 中列：视图容器（四视图自带全套样式，无切换条——视图由左列图标直切） */
.wb-right-content { flex:1; overflow-y:auto; }
.wb-placeholder { padding:32px; color:var(--dsw-alias-label-secondary,#888); font-size:13px; line-height:1.8; }
/* ── 顶部会话入口行（t260831-02：出厂「⊕ New Session」行的原地替换——紧凑一行，
 *     新建 + 本项目最近打开的会话切换；数据=插件记账层，工单/subagent/磁盘存量
 *     会话不混入。类名 wb-sessTop-* 全部自有前缀，与出厂类名零交叉） ── */
.wb-sessTop { flex:none; display:flex; align-items:center; gap:6px; padding:6px 8px;
  border-bottom:1px solid var(--dsw-alias-border-l1,#333); min-width:0; }
.wb-sessTop-new { flex:none; font:inherit; font-size:11.5px; cursor:pointer; padding:2px 9px;
  border-radius:4px; border:1px solid rgba(255,255,255,0.25); color:var(--dsw-alias-label-primary,#e0e0e0);
  background:none; white-space:nowrap; }
.wb-sessTop-new:hover { background:rgba(255,255,255,0.1); }
.wb-sessTop-new.disabled { opacity:0.4; cursor:default; }
.wb-sessTop-new.disabled:hover { background:none; }
.wb-sessTop-rows { display:flex; align-items:center; gap:4px; min-width:0; overflow:hidden; }
.wb-sessTop-empty { font-size:11px; color:#888; white-space:nowrap; }
.wb-sessTop-row { font:inherit; font-size:11.5px; cursor:pointer; padding:2px 8px; border-radius:4px;
  border:1px solid transparent; color:var(--dsw-alias-label-secondary,#b8b8c8); background:none;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:120px; }
.wb-sessTop-row:hover { background:rgba(255,255,255,0.08); color:var(--dsw-alias-label-primary,#e0e0e0); }
.wb-sessTop-row.active { background:rgba(124,58,237,0.25); color:var(--dsw-alias-label-primary,#e0e0e0); }
/* 打开/新建失败的行内提示（t260831-04）：失败不再只打 console——在入口行下
   独占一行显 warn 色小字，8s 自动清除；flex-wrap 让它不挤占切换行。 */
.wb-sessTop { flex-wrap:wrap; }
.wb-sessTop-notice { flex-basis:100%; font-size:10.5px; color:#f59e0b; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
`

/* ---------------------------------------------------------------- 主组件 */

/**
 * 顶部行原地替换的注入面（t260831-02）：出厂「⊕ New Session」钮不在任何槽里
 * （实查 dsh-client-ui-sidebar 包只声明 sidebar.workspaces/settings/footer.action
 * 三槽），按工单口径走「注入+语义锚」——
 *   锚：从本插件侧栏根（rootRef）上溯 SidebarRoot（出厂钮是它的直接子 button，
 *   折叠钮在 logoRow 内部非直接子、不会被误伤），取「aria-label 命中
 *   FACTORY_NEW_LABELS」的直接子 button——零 CSS 类名匹配（t260828-06 死因
 *   不复犯）；命中即置 display:none，让出原位给 .wb-sessTop 一行入口。
 *   兜防：MutationObserver 盯 SidebarRoot 的 childList/attributes——工厂重渲染
 *   复活新钮（或恢复被隐藏钮的可见性）时重新隐藏。
 *   全终态回收：卸载/折叠 cleanup 断开 Observer 并把碰过的钮 style.display
 *   还原为原值；锚找不到=软退化（出厂钮照常显示、入口仍在侧栏顶部，功能不丢，
 *   console.warn 留痕）。作用面仅此一个出厂元素，右栏出厂元素零接触。
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
  const { wide, expandSidebar, sessions, views, open: slotOpen, workspaces } = props
  const [projects, setProjects] = useState<Project[]>([])
  /** 项目 key → 该项目的工单行（按 ?project= 逐组拉取，来源即归属，不做路径猜测）。 */
  const [ticketsByProject, setTicketsByProject] = useState<Record<string, Ticket[]>>({})
  const [selectedId, setSelectedId] = useState<string>('')
  const [rightView, setRightView] = useState<RightView>('board')
  /** 当前中列视图所属项目（左列图标点击行）；空=未选（中列显占位）。 */
  const [viewProject, setViewProject] = useState('')
  /** 「又点了一次工单」信号：随 focusId 传给 WorkbenchSection，
   *  同 id 重开（抽屉被 × 关掉后再点同一行）也能触发——focusId 同值时 effect 不 firing。 */
  const [focusNonce, setFocusNonce] = useState(0)
  /** 「点 📋 回工单列表」信号：viewProject/rightView 同值时 setState 跳渲染，
   *  详情抽屉（WorkbenchSection 内部 state）收不到通知——靠这个单调递增计数传达。 */
  const [listNonce, setListNonce] = useState(0)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  /** 立项单视图定位（t260826-02）：epicCode=当前立项代号；epicNonce=「又点了一次同一立项」
   *  信号（同 focusNonce 先例——同 code 重进也要触发 EpicSection 重拉）。 */
  const [epicCode, setEpicCode] = useState('')
  const [epicNonce, setEpicNonce] = useState(0)
  // metrics M2a（t260902-01）：度量面板开/关 + ⚙ settings 弹层；「度量」钮 ref
  // 供面板关闭时焦点归还（gen2 决策 7 焦点管理最小实现）。
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
  // host 陈旧看守（t260902-03）：磁盘 host 半与进程启动指纹不一致 → stale，渲染全局横幅。
  const staleHost = useStaleHost()
  const [staleDismissed, setStaleDismissed] = useState(false)
  // 顶部行原地替换：隐藏出厂「⊕ New Session」钮（语义锚注入，见函数头注）。
  useHideFactoryNewSession(rootRef, wide)

  /* ── 项目内会话区（session-entry 第 3 面①）──
   * 二号 useSessionEntry 实例：账册是模块级共享 store（t260830-01 为同页多消费
   * 而建，机制现行），两实例同帧一致；动作（handleNew/handleOpen/handleClose）
   * 下传各项目组行，新建落点由行级闭包显式传 target（R3：落点=本组项目）。
   * projectKey 缺省同顶部行（当前视图项目，单项目兜底）——只影响缺省落点与
   * ↺ 恢复归属兜底，项目行走显式 target 不依赖它。 */
  const projectSessions = useSessionEntry({
    sessions,
    workspaces,
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
      try {
        const pr = await fetch('/suyou-workbench/api/wf/projects').then(r => r.json())
        const list: Project[] = pr?.result?.projects ?? []
        if (cancelled) return
        setProjects(list)
        // t260903-07：项目集发布给 chat 项目 tag 装饰器（整体一个请求，成功才发，
        // 失败不发——单态保留 last-known-good）。
        publishProjects(list.map(p => ({ key: p.key, dirs: p.dirs })))
        const entries = await Promise.all(list.map(async (p) => {
          try {
            const tr = await fetch(`/suyou-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`).then(r => r.json())
            const tickets = (tr?.result?.tickets ?? []) as Ticket[]
            // t260903-07：逐项目成功分支才发布工单→项目映射（catch 分支不发，见上方 import 注释）。
            publishProjectEntry(p.key, tickets.map(t => t.id))
            return [p.key, tickets] as const
          } catch {
            return [p.key, [] as Ticket[]] as const
          }
        }))
        if (cancelled) return
        setTicketsByProject(Object.fromEntries(entries))
      } catch { /* 静默 */ }
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
    setViewProject(projectKey)
    setRightView('board')
    setFocusNonce(n => n + 1)
  }, [])

  // chat 项目 tag 装饰器（t260903-07 工单②）：挂/卸随本组件（插件在装即挂，
  // 卸载=全终态回收，见 chat-project-tag.ts teardown 清单）。
  // F1 修复（验收走查 gen0）：走 effect 形态入口——返回值就是 cleanup 函数，
  // 杜绝「useEffect 直接返回 handle 对象被忽略 → 卸载零回收」的接线陷阱。
  useEffect(() => startChatProjectTagEffect({ fetchImpl: fetch.bind(globalThis) }), [])

  // 点项目行的视图图标：中列切到该项目该视图（stopPropagation 不触发折叠）。
  // 📋 额外做两件事（t260825-05：开着详情抽屉点 📋 无反应的修复）——
  // ① 清行选中：focusId 回落 undefined，之后点同一工单行还能再开详情；
  // ② bump listNonce：viewProject/rightView 多半已是同值（点工单时已置），
  //    setState 跳渲染，只有 nonce 变化能把「关抽屉回列表」传达到 WorkbenchSection。
  // 🗂️ 立项单（t260827-01）：点图标=回立项清单（空代号=列表模式），bump epicNonce
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

  /** 项目组：注册表顺序。进行中工单常列；已完成工单在 sandbar 驻留窗口内也列（灰绿标记）。 */
  const groups = useMemo(() => {
    const nowS = Date.now() / 1000
    return projects.map(p => ({
      project: p,
      tickets: (ticketsByProject[p.key] ?? []).filter(t => inSandbar(t, nowS)),
    }))
  }, [projects, ticketsByProject])

  const Board = views.board
  const Knowledge = views.knowledge
  const Routes = views.routes
  const Epics = views.epics

  // 进立项单详情视图（工单徽标点击，t260826-02）：中列切 epics 并定位代号。
  // （t260827-01 起左列不再有立项列表区，清单入口=项目行 🗂️ 图标，走 handleViewIcon。）
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
        <div className="wb-sb-icon" onClick={expandSidebar} title="工单台">⊞</div>
      </div>
    )
  }

  // 展开态：双列
  return (
    <div ref={rootRef} className="wb-sb wide">
      <style>{CSS}</style>
      {/* 左列：顶部会话入口行（t260831-02 出厂 New Session 行原地替换）+ 项目分组（可折叠）+ 插件入口 */}
      <div className="wb-sb-left">
        {/* 顶部会话入口：新建落点=当前视图项目；未选时单项目注册表兜底，多项目未选禁用。
            workspaces/主目录传给入口——新建走 ctx.workspaces.startSession 工厂同款语义（t260831-04）。 */}
        <SessionTopEntry
          sessions={sessions}
          workspaces={workspaces}
          slotOpen={slotOpen}
          projects={projects}
          projectKey={viewProject || (projects.length === 1 ? projects[0].key : '')}
          projectDir={projects.find(p => p.key === (viewProject || (projects.length === 1 ? projects[0].key : '')))?.primary ?? ''}
        />
        <div className="wb-ticket-list">
          {loading ? (
            <div style={{padding:16,color:'#888'}}>加载中…</div>
          ) : groups.map(g => (
            <div key={g.project.key}>
              <div className="wb-group-head" onClick={() => setCollapsed(c => ({ ...c, [g.project.key]: !c[g.project.key] }))}>
                <span className="wb-group-caret">{collapsed[g.project.key] ? '▸' : '▾'}</span>
                <span className="wb-group-name">{g.project.name}</span>
                <span className="wb-group-count">{g.tickets.length || ''}</span>
                {/* 四视图入口 per 项目（用户拍板 260823：每个项目组头行都有，非全局）——
                    按行项目分流：工单列表=该项目 ProjectKey 过滤、知识库=该项目主目录 docs、
                    模型路由=该项目主目录 model-routes.yaml；立项单（t260827-01）=全量立项清单
                    （跨项目语义单元，不按项目过滤，图标只承担「切视图+落点项目」两职）。 */}
                <span className="wb-view-icons" onClick={e => e.stopPropagation()}>
                  <span className={`wb-view-icon ${rightView === 'board' && viewProject === g.project.key ? 'active' : ''}`} title="工单列表" onClick={() => handleViewIcon(g.project.key, 'board')}>📋</span>
                  <span className={`wb-view-icon ${rightView === 'knowledge' && viewProject === g.project.key ? 'active' : ''}`} title="知识库" onClick={() => handleViewIcon(g.project.key, 'knowledge')}>📖</span>
                  <span className={`wb-view-icon ${rightView === 'routes' && viewProject === g.project.key ? 'active' : ''}`} title="模型路由" onClick={() => handleViewIcon(g.project.key, 'routes')}>🔀</span>
                  <span className={`wb-view-icon ${rightView === 'epics' && viewProject === g.project.key ? 'active' : ''}`} title="立项单" onClick={() => handleViewIcon(g.project.key, 'epics')}>🗂️</span>
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
                    <div className="wb-group-empty">无进行中工单</div>
                  ) : g.tickets.map(t => (
                    <div
                      key={t.id}
                      className={`wb-ticket-row2 ${selectedId === t.id ? 'selected' : ''} ${isOpen(t) ? '' : 'done'}`}
                      onClick={() => handleTicketClick(t, g.project.key)}
                    >
                      {t.title && <div className="wb-ticket-l1" title={t.title}>{t.title}</div>}
                      <div className="wb-ticket-l2">
                        <span style={{color: stateColor(t), fontFamily: 'var(--ds-font-family-code, monospace)'}}>{t.id}</span>
                        {' · '}{isOpen(t) ? (t.role || '—') : '已完成'}{' · '}{ageOf(isOpen(t) ? t.created : (t.close_ts || t.created))}
                        {!isOpen(t) && ' 前收口'}
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          ))}
        </div>
      </div>
      {/* 中列：四视图（现成的工单台/知识库/模型/立项单 UI，从 chat 页签迁来；左列图标直切，无 tab 条）。
          未选项目显占位——不自动选第一个项目（project 无默认值，用户拍板 260823）。 */}
      <div className="wb-sb-right">
        {/* host 陈旧全局提醒（t260902-03）：挂中列共享容器（四视图排他渲染之上），
            所有页签/视图常驻可见；「知道了」仅本页签消音（会话级，不持久化）。 */}
        {staleHost && !staleDismissed && (
          <div className="wb-stale-banner" role="alert">
            <span className="wb-stale-msg">
              ⚠️ 控制台代码已更新，请<strong>重启 console</strong>后刷新页面生效（当前页面仍在跑旧代码，度量/diff 可能异常）。
            </span>
            <button className="wb-stale-dismiss" title="本页签暂时隐藏" onClick={() => setStaleDismissed(true)}>知道了</button>
          </div>
        )}
        <div className="wb-right-content">
          {!viewProject && (
            <div className="wb-placeholder">
              从左侧项目行点图标打开视图：
              <br />📋 工单列表 · 📖 知识库 · 🔀 模型路由 · 🗂️ 立项单
              <br />（按行项目分流；立项单为跨项目清单，点 🗂️ 后中列显示列表）
            </div>
          )}
          {viewProject && rightView === 'board' && <Board focusId={selectedId || undefined} focusNonce={focusNonce} listNonce={listNonce} projectKey={viewProject} onOpenEpic={openEpic} />}
          {viewProject && rightView === 'knowledge' && <Knowledge projectKey={viewProject} />}
          {viewProject && rightView === 'routes' && <Routes projectKey={viewProject} />}
          {/* 立项单视图（t260826-02 中列第四视图；t260827-01 起空代号=立项清单，由项目行
              🗂️ 图标进入，详情由清单行/工单徽标定位）：点关联工单行 → 复用 handleTicketClick
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
              title="度量面板（stage 时长 / 交付 / Token / 系统健康）"
              onClick={() => { setSettingsOpen(false); setMetricsOpen(o => !o) }}>📊 度量</button>
          )}
          <span className="wb-sb-foot-sp" />
          <button className="wb-sb-foot-btn" data-on={settingsOpen} title="设置"
            onClick={() => { setMetricsOpen(false); setSettingsOpen(o => !o) }}>⚙</button>
        </div>
        {settingsOpen && (
          <div className="wb-sb-setpop" role="dialog" aria-label="设置">
            <div className="t">设置</div>
            {/* sandbar 驻留输入（原 board 筛选行内联输入迁来；localStorage key 与
                sandbarHours/setSandbarHours 语义不变，侧栏轮询每次现读）。 */}
            <label className="row" title="已完成工单在左栏项目组里再驻留多少小时（0=立即消失）">
              sandbar 驻留
              <input type="number" min={0} step={1} value={sandbar}
                onChange={e => {
                  const h = Math.max(0, Number(e.target.value) || 0)
                  setSandbar(h)
                  setSandbarHours(h)
                }} />
              小时
            </label>
            <div className="m2c">静默在制阈值（分钟）：随 M2c 系统健康 tab 开放。</div>
          </div>
        )}
      </div>
    </div>
  )
}
