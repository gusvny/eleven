/**
 * sandbar-workbench —— 工单工作流台 · 浏览器半（侧栏工单中心版）。
 *
 * 260823 改版（用户拍板）：chat 顶部页签只留 chat/trajectory——工单台/文档/模型
 * 三个视图从 conversation.view 环摘除，改由侧栏接管组件的中栏承载：
 * 本插件注册 sidebar.workspaces（priority=-10 抢占 shell 默认浏览器），
 * WorkbenchSidebar 左列=项目分组+进行中工单+插件入口，中列=四视图
 * （WorkbenchSection 本文件 / DocsSection 本插件 ./docs.tsx（t260905-06 起，
 * 顶替 knowledge 插件视图——旧提法退役，界面层不再出现） /
 * ProvidersSection 从 providers 插件 import）。t260903-07 起：点工单只开中列
 * 详情抽屉，右栏 chat 恒为单全局会话不再切换（每工单会话联动下线，数据留存——
 * 见 sidebar.tsx 头注与 notes/debts/design-doc-sync-t260903-07.md）。
 * 数据来自 /sandbar-workbench/api/wf/* 而非会话事件。
 *
 * 页面三区（工单工作流台设计 v0.3 §5/§10）：
 *   ① 台面区：工单卡片网格（id | 工作流 | 阶段进度条 | 当前角色 | 状态色板
 *     running绿/awaiting黄/awaiting-human蓝/blocked红/done灰）+ 状态/工作流/角色筛选。
 *   ② 详情抽屉：泳道图（stages 横排箭头=next，当前高亮，fanout 扇出分叉标注）+
 *     验收清单打勾（evidence 展示）+ handoff 接力时间线 + log 流水 + pending 挂起项 +
 *     worktree 短 slug / base_ref / proposal_id。
 *   ③ 操作区：按 v0.3 §10 操作矩阵只显可用按钮——advance（awaiting-human 时
 *     「审批→推进」走 Temporal sign）/ dispatch-next（生成可复制 prompt）/ 打回 / 解除阻塞 / 完成。
 *
 * 数据通道：同源 fetch 打宿主半（../node.ts）挂在 dsh webServer 上的
 * /sandbar-workbench/api/wf/*；写操作走 admin.py call ticket（run-id 审计
 * 在 server/admin.log，与模型通道同一真源）。
 *
 * M9 PR 式审批台（t260821-m9-pr-approval）：详情抽屉加「变更」页签——
 * 文档 diff 复用 knowledge 渲染态 block diff（renderMarkdown 直接 import
 * knowledge 浏览器半同款渲染器；block diff 由宿主半算好下发）；代码 diff=
 * 文件级 unified 渲染；数据 diff=前后值对账表。审批意见按块/文件留，
 * POST 落盘 server/dsh/reviews/<工单id>.json（多轮；key 含内容哈希，
 * 内容变→旧意见标「已过期」）。签字联动：approve 摘要随 sign 进历史，
 * reject 意见即返工指令一键复制/一键填入打回理由。
 *
 * M6 巡检报告区（t260821-m6-scan-expand）：台面表格下方加「巡检报告」区——
 * 读 /sandbar-workbench/api/wf/scan-report（最新 out/scan/<日期>.json）渲染
 * 待决工单检查表（停留/验收勾选率/脚本门灯/pending/建议三档色 chip），点行
 * 开详情抽屉；无报告走 reason 人话降级。红线显性化：报告 red_line 常驻区底。
 *
 * M12 agent 日志（t260822-m12）：详情抽屉加「Agent 日志」页签——读
 * /sandbar-workbench/api/wf/tickets/<id>/agent-logs 列泳道 .suyou/ 的
 * agent_<stage>_gen<n>.log（子 agent stdout/stderr 流，诊断失败现场）
 * + stage_<stage>_gen<n>.json（段结算结果：status/summary/deliverables），
 * 点文件展开；无目录走 reason 人话降级。
 *
 * t260825-03 运行可见性：详情头部（所有页签可见）加「运行脉搏」行（detail.pulse
 * =Temporal pending activity 心跳：阶段 gen/已运行时长/心跳年龄 + session_kb 增速，
 * 停涨/心跳停超阈值亮疑似卡死提示；无心跳显「无心跳」软降级）与「实时动态」折叠
 * 面板（agent-live 端点：泳道会话 jsonl.zstd 尾 30 条事件流，展开才 8s 轮询）。
 *
 * t260826-02 立项单 UI（epic-linkage Tier 3）：侧栏加「立项单」分区 + 中列第四视图
 * EpicSection（./epics.tsx：左立项单 Markdown 全文 / 右关联工单实时汇总 + 新建工单
 * 入口——epic 界面传值不可手输）；工单列表行与详情头部加所属立项徽标（EpicBadge，
 * 点击跳立项详情，无 epic 显灰「未归档」）；人门签字确认区有 epic 时显示
 * 「所属立项: <代号>」（无则略——review M1，不显示「未归档」字样）。
 *
 * t260828-01 执行主体可见（observability）：阶段链每步按模版 STAGES 的 parts 静态
 * 声明渲染组合徽标（🤖 agent / ⚙️ 脚本 / 👤 人，直接拼接，悬停一行说明），
 * 泳道图/步骤条/进展卡三处复用 PartsBadges；无 parts 旧数据显「—」软降级。
 *
 * t260828-06 hero 整体更换误伤出厂 chat（t260829-01 退场）；t260829-06 又以三槽
 * 槽位替换重进（conversation.hero.workspace→HeroEntry、agentPreset/brand.mark→空），
 * 顶掉了出厂 workspace 选择器与 preset，右栏 chat 不可用（不能选 workspace、不能
 * 开始 chat）——t260831-02 按 UX 契约把 hero 接管**彻底拆除**：不再注册任何
 * conversation.hero.* 槽，出厂落地页（大标题/大输入卡/workspace 选择器）原样回弹，
 * 右栏零定制。会话入口收口到一处：顶部行（deepseek logo 正下方出厂「⊕ New
 * Session」钮的原地替换；该入口行已随票② R8 退役（t260904-05），sidebar.tsx 的
 * 注入锚），见两文件头注。工单会话入口（点工单 handleTicketClick 链路）不受影响。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'
import type { ClientContext, ConversationViewDefinition } from '@deepseek-ai/dsh-client-runtime/client'
// 空具名 type import：把 dsh-client-ui-conversation 的 SlotMap 扩展（conversation.view 槽声明）
// 带进 tsc 检查环境；纯类型副作用，构建时被剥离，不进 bundle。
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
// 渲染态 markdown 复用 knowledge 浏览器半（只读复用，纯函数无依赖，tsdown 直打包）。
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
// 表格行单元格级对齐用 splitCells；BlockDiff 仅取类型。
import { splitCells } from '../../../knowledge/src/shared/blocks.ts'
// M14：工单「工作区」展示纯函数（列表列/详情/悬停 title 共用，冒烟直测）。
import { workspaceInfoOf, workspaceTextOf } from '../shared/workspace.ts'
// t260828-01：阶段链「执行主体」徽标纯函数（🤖⚙️👤 组合拼接 + 悬停说明，冒烟直测）。
import { partsIcons, partsTitle } from '../shared/parts.ts'
// t260901-05：泳道图并行分叉渲染——单值指针 → 活跃步数组推导（纯模块，node 可裸 import 行为测试）。
import { deriveStageStates } from './lane-states.ts'
import type { D2Visual } from './lane-states.ts'
// t260901-12（metrics M1b）：泳道图节点耗时推导（纯模块，node 可裸 import 行为测试；
// 轮/五级收口链/单位换算口径见模块头注）。
import { deriveStageDurations, fmtDur as fmtDurMs, humanWaitTotalMs, stageDurationTitle, stageTotalMs } from './lane-durations.ts'
import type { StageDuration } from './lane-durations.ts'
import { ProvidersSection } from '../../../providers/src/client/index.tsx'
import { WorkbenchSidebar } from './sidebar.tsx'
import { MetricsFooterButton, markFooterSlot } from './metrics-entry.tsx'
// 立项单 Tier 3（t260904-17 保留）：中列第四视图 + 所属立项徽标（口径单点 ./epics-model.ts）。
import { EpicBadge, EpicSection } from './epics.tsx'
// 「文档」视图（t260905-06）：docs/ 定稿库人读视图 + notes/ 观察窗（全仓单例）。
import { DocsSection } from './docs.tsx'
// t260904-17 工单列表 v5（mock 屏⑤⑥）：平铺行卡（一套 UI，中列+侧栏共用）+ 纯函数模型层。
import { TicketRowCard, type CardOp } from './ticket-row-card.tsx'
import {
  deriveTicketState, countByState, filterRows, progressLineOf, epicColorOf,
  STATE4_LABEL, firstSentenceOf, snapshotDigest, type SnapshotDigest,
  type TicketState4,
} from './ticket-list-model.ts'
// t260901-15 多页签共存：在看心跳/写事件广播（tab-presence）+ 不可见页签暂停轮询门。
import { startTabPresence } from './tab-presence.ts'
import type { TabPresence, PeerViewer } from './tab-presence.ts'
import { buildApproveNote } from './approve-note.ts'
import { startVisibleInterval } from './visibility-poll.ts'
// t260903-06 KI-003③：轮询健康度状态机（连续失败阈值/分类/快照保留的纯函数半）。
import {
  classifyPollBody,
  INITIAL_POLL_STATE,
  nextPollState,
  worstOutcome,
  type PollHealthState,
  type PollOutcome,
} from './poll-health.ts'

export const name = 'sandbar-workbench/client'
// workspaces（t260831-04）：顶部会话入口新建走 ctx.workspaces.startSession。
export const inject = ['slots', 'sessions', 'workspaces']
// t260903-07：原 openTicketSessionFlow re-export（t260831-08）随流程体一并删除——
// 每工单会话联动下线，点工单只开中列详情，右栏 chat 恒为全局会话。

/* ---------------------------------------------------------------- 样式 */

const CSS = `${DERIVE_TOKENS_CSS}
/* ── 工单工作流台 · 现代浅色主题（260820 最终版：去 suyou 中式金棕/衬线，
 *     system-ui 无衬线、高对比、细边框+轻阴影、现代状态色，饱和度适中） ── */
.wb-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-fg,#1f2328);min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:16px;height:100%;overflow-y:auto;font-size:13px;line-height:1.55}
.wb-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de);padding-bottom:12px;position:relative}
.wb-title{font-size:20px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-sub{font-size:12px;color:var(--dsw-derive-muted,#57606a)}
.wb-err{background:var(--dsw-derive-danger-bg,#ffebe9);border:1px solid var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);border-radius:6px;
  padding:8px 12px;font-size:12px;white-space:pre-wrap}
.wb-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.wb-select{font:inherit;font-size:13px;background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:5px 10px}
.wb-select:focus{outline:none;border-color:var(--dsw-derive-accent,#0969da);box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.wb-btn{font:inherit;font-size:13px;padding:5px 16px;border-radius:6px;cursor:pointer;
  border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328);transition:background .12s}
.wb-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-btn-danger{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-btn-blue{border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
/* ---- 工单列表 v5（t260904-17，mock 屏⑤⑥）：平铺行卡 + 筛选 chips ---- */
/* 状态/epic 筛选 chips：过滤非分组；「等你」chip（data-state=waiting）>0 时黄调强调 */
.wb-chip-btn{font-size:12px;padding:2px 10px;border-radius:10px;border:1px solid var(--dsw-derive-border,#d0d7de);
  background:var(--dsw-derive-canvas,#fff);color:var(--dsw-derive-muted,#57606a);cursor:pointer;white-space:nowrap}
.wb-chip-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-chip-btn[data-on=true]{border-color:var(--dsw-derive-accent,#0969da);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff);font-weight:600}
.wb-chip-btn[data-state=waiting]{border-color:var(--dsw-derive-warn-border,#d4a72c)}
.wb-chip-btn[data-state=waiting][data-on=false]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-chip-epic{border-style:dashed;border-width:1.5px}
/* 搜索框 */
.wb-search{font-size:12px;padding:3px 10px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;width:180px}
/* 平铺行卡：左缘 epic 彩条由行内 style 注入（哈希色）；等你=黄调行/受阻=红调行
 * （底色由行内 style 注入）、活跃=蓝左条强调、收口=灰折叠 */
.wb-card{display:flex;align-items:center;gap:10px;padding:8px 12px;margin-bottom:6px;
  border:1px solid var(--dsw-derive-border,#d0d7de);border-left-width:4px;border-radius:8px;background:var(--dsw-derive-canvas,#fff);
  cursor:pointer;font-size:13px;flex-wrap:wrap;box-shadow:0 1px 2px rgba(31,35,40,.05)}
/* hover 不再改写底色（会盖掉 waiting/blocked 状态行底）——改阴影提层，主题安全 */
.wb-card:hover{box-shadow:0 1px 4px rgba(31,35,40,.14)}
/* 状态行底=主题令牌派生（t260905-08 根因修复：原行内写死浅色×主题字色=深色不可读） */
.wb-card[data-state=waiting]{background:var(--dsw-derive-warn-bg,#fff8c5)}
.wb-card[data-state=blocked]{background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-card[data-active=true]{border-color:var(--dsw-derive-accent,#0969da);box-shadow:inset 0 0 0 1px var(--dsw-derive-accent,#0969da)}
.wb-card[data-state=done]{color:var(--dsw-derive-muted,#57606a)}
.wb-card-l1{display:flex;align-items:center;gap:8px;min-width:0;flex:1 1 320px}
.wb-card-dot{width:9px;height:9px;flex:none;position:relative}
.wb-card-dot::before{content:'';position:absolute;inset:0;border-radius:50%;background:var(--dsw-derive-muted,#8c959f)}
.wb-card-dot[data-state=waiting]::before{background:var(--dsw-derive-warn,#bf8700)}
.wb-card-dot[data-state=blocked]::before{background:var(--dsw-derive-danger,#cf222e)}
.wb-card-dot[data-state=active]::before{background:var(--dsw-derive-accent,#0969da)}
.wb-card-dot[data-state=done]::before{background:var(--dsw-derive-muted,#8c959f)}
.wb-card-state{font-size:11px;font-weight:600;flex:none}
.wb-card-state[data-state=waiting]{color:var(--dsw-derive-warn,#9a6700)}
.wb-card-state[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e)}
.wb-card-state[data-state=active]{color:var(--dsw-derive-accent,#0969da)}
.wb-card-state[data-state=done]{color:var(--dsw-derive-muted,#57606a)}
.wb-card-id{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dsw-derive-accent,#0969da);flex:none}
.wb-card-title{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.wb-card-epic{font-size:11px;padding:0 8px;border:1px solid;border-radius:10px;flex:none;white-space:nowrap}
.wb-card-l2{display:flex;align-items:center;gap:8px;color:var(--dsw-derive-muted,#57606a);font-size:12px;flex:1 1 260px;min-width:0}
.wb-card-progress{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wb-card-progress[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e)}
.wb-card-progress[data-state=awaiting-human]{color:var(--dsw-derive-warn,#9a6700)}
.wb-card-time{flex:none}
.wb-card-role{flex:none}
.wb-card-pending{font-size:11px;color:var(--dsw-derive-warn-deep,#7d4e00);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#d4a72c);
  border-radius:4px;padding:0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 迷你站道：点数=模板阶段数；绿=已过/状态色=当前/灰=未来（颜色随 data-state 派生） */
.wb-card-lane{display:inline-flex;gap:4px;align-items:center;flex:none}
.wb-card-lane-dot{width:8px;height:8px;border-radius:50%;background:var(--dsw-derive-border,#d0d7de);display:inline-block}
.wb-card-lane-dot[data-visual=done]{background:var(--dsw-derive-success-solid,#2da44e)}
.wb-card-lane-dot[data-visual=current][data-state=waiting]{background:var(--dsw-derive-warn-border,#d4a72c)}
.wb-card-lane-dot[data-visual=current][data-state=blocked]{background:var(--dsw-derive-danger,#cf222e)}
.wb-card-lane-dot[data-visual=current][data-state=active]{background:var(--dsw-derive-accent,#0969da)}
/* 行卡动作位（右侧）：衍生动作（去签字/看原因）+ 管理动作 */
.wb-card-ops{display:flex;gap:6px;align-items:center;flex:none;margin-left:auto}
.wb-card-btn{font-size:12px;padding:2px 10px;border-radius:6px;border:1px solid var(--dsw-derive-border,#d0d7de);
  background:var(--dsw-derive-canvas,#fff);color:var(--dsw-derive-fg,#1f2328);cursor:pointer;white-space:nowrap}
.wb-card-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-card-btn-primary{background:var(--dsw-derive-accent-solid,#1f6feb);border-color:var(--dsw-derive-accent-solid,#1f6feb);color:var(--dsw-derive-on-solid,#fff);font-weight:600}
.wb-card-btn-blue{border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-card-btn-danger{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-card-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
/* 收口折叠计数行 */
.wb-done-row{display:block;width:100%;text-align:left;font-size:12px;color:var(--dsw-derive-muted,#57606a);
  background:var(--dsw-derive-surface,#f6f8fa);border:1px dashed var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:6px 12px;
  margin:8px 0 6px;cursor:pointer}
.wb-done-row:hover{background:var(--dsw-derive-surface-2,#eef1f4)}
/* 旧台面表格样式已随 t260904-17 列表 v5（平铺行卡）退役——行卡/chips 样式族见上。 */
.wb-dot{width:10px;height:10px;border-radius:50%;display:inline-block;vertical-align:middle;flex:none}
.wb-dot[data-state=running]{background:var(--dsw-derive-success-solid,#2da44e)}
.wb-dot[data-state=awaiting]{background:var(--dsw-derive-warn,#bf8700)}
.wb-dot[data-state=awaiting-human]{background:var(--dsw-derive-accent,#1f6feb)}
.wb-dot[data-state=blocked]{background:var(--dsw-derive-danger-solid,#d1242f)}
.wb-dot[data-state=done]{background:var(--dsw-derive-muted,#6e7781)}
.wb-td-id{white-space:nowrap}
.wb-td-id .wb-id{display:block;color:var(--dsw-derive-accent,#0969da);font-weight:600;white-space:nowrap}
.wb-td-role{color:var(--dsw-derive-fg,#1f2328);white-space:nowrap;width:76px}
.wb-type-chip{font-size:12px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;
  padding:1px 8px;white-space:nowrap}
.wb-type-chip[data-empty=true]{color:var(--dsw-derive-muted,#8c959f)}
.wb-td-step{color:var(--dsw-derive-muted,#57606a);white-space:nowrap;width:150px}
.wb-td-desc{width:100%}
.wb-td-desc .wb-desc{display:block;color:var(--dsw-derive-fg,#1f2328);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wb-row-pending{display:block;color:var(--dsw-derive-danger,#cf222e);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wb-td-state{white-space:nowrap;width:130px}
.wb-state-text{font-size:13px;margin-left:6px;color:var(--dsw-derive-muted,#57606a)}
.wb-state-text[data-state=awaiting-human]{color:var(--dsw-derive-accent,#0969da);font-weight:600}
.wb-state-text[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e)}
.wb-state-text[data-state=running]{color:var(--dsw-derive-success,#1a7f37)}
.wb-state-text[data-state=done]{color:var(--dsw-derive-muted,#6e7781)}
.wb-td-time{color:var(--dsw-derive-muted,#57606a);white-space:nowrap;width:104px}
.wb-td-ops{white-space:nowrap;width:250px;text-align:right}
.wb-row-ops{display:inline-flex;gap:6px}
.wb-row-btn{font:inherit;font-size:12px;padding:3px 10px;border-radius:6px;cursor:pointer;
  border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328);white-space:nowrap;transition:background .12s}
.wb-row-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-row-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-row-btn-primary{border-color:var(--dsw-derive-accent-solid,#1f6feb);background:var(--dsw-derive-accent-solid,#1f6feb);color:var(--dsw-derive-on-solid,#fff);font-weight:600}
.wb-row-btn-primary:hover{background:var(--dsw-derive-accent,#0857b6)}
.wb-row-btn-danger{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-row-btn-blue{border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-row-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
/* 详情抽屉徽章（浅底深字，现代状态色） */
.wb-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:500}
.wb-badge[data-state=running]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-badge[data-state=awaiting]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-badge[data-state=awaiting-human]{background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-badge[data-state=blocked]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-badge[data-state=done]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a)}
.wb-badge[data-kind=status]{background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
/* 详情抽屉：absolute 限定在中列视图区内（260824 起不再做全窗 fixed 覆盖——
   定位祖先 = sidebar.tsx 的 .wb-sb-right（position:relative），铺满中列。 */
.wb-drawer{position:absolute;top:0;right:0;bottom:0;left:0;background:var(--dsw-derive-canvas,#ffffff);z-index:90;
  border-left:1px solid var(--dsw-derive-border,#d0d7de);box-shadow:-12px 0 32px rgba(31,35,40,.18);overflow-y:auto;padding:18px 22px 40px;
  display:flex;flex-direction:column;gap:14px;font-size:13px;color:var(--dsw-derive-fg,#1f2328)}
/* flex 列布局里子元素默认可缩——带 overflow 的卡（正文 max-height+scroll）会被压到不足一行
   （260824 实测塌陷）；抽屉自己滚，子元素一律不缩。 */
.wb-drawer>*{flex-shrink:0}
.wb-drawer-head{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de);padding-bottom:10px}
.wb-d2-blocked{margin:8px 0;padding:6px 12px;border:1px solid var(--dsw-derive-danger,#cf222e);border-radius:6px;
  background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e);font-size:12.5px}
.wb-drawer-id{font-size:12px;color:var(--dsw-derive-muted,#57606a);word-break:break-all}
.wb-close{position:absolute;top:14px;right:16px;font-size:22px;color:var(--dsw-derive-muted,#57606a);cursor:pointer;background:none;border:none}
.wb-close:hover{color:var(--dsw-derive-fg,#1f2328)}
.wb-section{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);padding:12px 14px;display:flex;
  flex-direction:column;gap:8px}
.wb-section-title{font-size:14px;font-weight:600;color:var(--dsw-derive-fg,#1f2328);border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding-bottom:6px}
/* M14 详情五分组层次：编号徽标 + 子块分隔 + 基本信息网格 + 操作区高亮 */
.wb-section-num{font-size:11px;font-weight:700;color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff);border-radius:4px;
  padding:1px 6px;margin-right:8px;letter-spacing:.5px;vertical-align:1.5px}
.wb-section-desc{font-size:11px;color:var(--dsw-derive-muted,#8c959f);font-weight:400;margin-left:8px}
.wb-sub-sec{font-size:12px;font-weight:600;color:var(--dsw-derive-muted,#57606a);margin-top:10px;padding-top:8px;
  border-top:1px dashed var(--dsw-derive-surface-2,#e8ebef)}
.wb-section-title + .wb-sub-sec{border-top:none;margin-top:4px;padding-top:0}
.wb-meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:7px 18px}
.wb-meta-grid .wb-meta-item{display:flex;gap:6px;min-width:0;font-size:12px;color:var(--dsw-derive-fg,#1f2328);align-items:baseline}
.wb-meta-grid .wb-meta-item > .wb-meta-k{flex:none}
.wb-meta-grid .wb-meta-item > span:last-child:not(.wb-meta-k){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wb-section[data-kind=ops]{border-color:var(--dsw-derive-accent-border,#96c8f2);background:var(--dsw-derive-accent-bg,#fbfdff)}
.wb-meta-row{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-meta-k{color:var(--dsw-derive-muted,#8c959f)}
.wb-meta-link{color:var(--dsw-derive-accent,#0969da);text-decoration:none}
.wb-meta-link:hover{text-decoration:underline}
.wb-check{display:flex;flex-direction:column;gap:3px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:7px 2px}
.wb-check-line{display:flex;align-items:baseline;gap:8px}
.wb-check-item{flex:1;color:var(--dsw-derive-fg,#1f2328);line-height:1.6}
.wb-check-item[data-done=true]{color:var(--dsw-derive-muted,#6e7781);text-decoration:line-through;text-decoration-color:var(--dsw-derive-muted,#c0c6cc)}
.wb-check-by{font-size:10px;color:var(--dsw-derive-muted,#57606a)}
.wb-evidence{font-size:11px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border-radius:6px;padding:4px 8px;
  white-space:pre-wrap;word-break:break-word;margin:0}
/* ── t260831-08 详情抽屉「截图证据」区（wb-eimgs-*） ── */
.wb-eimgs{margin:10px 0 2px;border-top:1px solid var(--dsw-derive-surface-2,#e8ebef);padding-top:8px}
.wb-eimgs .ttl{font-size:11px;font-weight:600;color:var(--dsw-derive-muted,#57606a);margin-bottom:6px}
.wb-eimgs-grid{display:flex;flex-wrap:wrap;gap:10px}
.wb-eimgs-item{margin:0;max-width:280px}
.wb-eimgs-img{display:block;max-width:280px;max-height:200px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;
  background:var(--dsw-derive-canvas,#fff);object-fit:contain}
.wb-eimgs-item figcaption{font-size:10px;color:var(--dsw-derive-muted,#8c959f);margin-top:3px;word-break:break-all}
.wb-eimgs-miss{font-size:11px;color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9);border-radius:6px;padding:6px 8px}
/* ── t260901-13 截图证据看图灯箱（wb-lb-*）──
 * 参照 wb-modal 取舍：带 inset:0 fixed + flex 居中（同款全屏遮罩语义）；
 * 不带 wb-modal-box 白底卡片/86vh 上限（灯箱主体是大图，非表单容器）。
 * 背景 .8（wb-modal .5 下透出抽屉内容干扰看图）。z-index 120：显式压过
 * 抽屉（90）与通用弹窗（99），灯箱开着时键盘/点击语义独占，不靠 DOM 顺序。 */
.wb-eimgs-item{cursor:zoom-in}
.wb-lb{position:fixed;inset:0;background:rgba(31,35,40,.8);z-index:120;display:flex;
  flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:20px}
.wb-lb-img{max-width:90vw;max-height:80vh;border-radius:8px;background:var(--dsw-derive-canvas,#fff);object-fit:contain;
  box-shadow:0 8px 32px rgba(0,0,0,.5)}
.wb-lb-miss{font-size:13px;color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9);border-radius:8px;padding:10px 16px}
.wb-lb-bar{display:flex;align-items:center;gap:12px;font-size:12px;color:var(--dsw-derive-dark-fg,#f0f3f6);user-select:none}
.wb-lb-nav{font:inherit;font-size:20px;line-height:1;width:36px;height:36px;border-radius:50%;
  border:1px solid rgba(240,243,246,.4);background:rgba(240,243,246,.12);color:var(--dsw-derive-dark-fg,#f0f3f6);
  cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .12s}
.wb-lb-nav:hover{background:rgba(240,243,246,.25)}
.wb-lb-close{font:inherit;font-size:14px;padding:4px 12px;border-radius:6px;cursor:pointer;
  border:1px solid rgba(240,243,246,.4);background:transparent;color:var(--dsw-derive-dark-fg,#f0f3f6)}
.wb-lb-close:hover{background:rgba(240,243,246,.15)}
.wb-lb-name{max-width:50vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;word-break:break-all}
.wb-ev-input{font:inherit;font-size:13px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:5px 8px;width:100%;box-sizing:border-box}
.wb-ev-input:focus{outline:none;border-color:var(--dsw-derive-accent,#0969da);box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.wb-hl{font-size:12px;color:var(--dsw-derive-fg,#1f2328);display:flex;flex-direction:column;gap:5px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);
  padding:7px 2px}
.wb-hl-stage{color:var(--dsw-derive-accent,#0969da);font-weight:600}
.wb-log{font-size:11px;color:var(--dsw-derive-muted,#57606a);display:flex;gap:8px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:4px 2px;
  align-items:baseline}
.wb-log-time{color:var(--dsw-derive-muted,#8c959f);flex:none}
.wb-log-note{word-break:break-word}
.wb-ops{display:flex;gap:8px;flex-wrap:wrap}
.wb-modal{position:fixed;inset:0;background:rgba(31,35,40,.5);z-index:99;display:flex;align-items:center;
  justify-content:center;padding:24px}
.wb-modal-box{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:10px;box-shadow:0 8px 32px rgba(31,35,40,.2);
  max-width:760px;width:100%;max-height:86vh;display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.wb-modal-title{font-size:15px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-modal-body{overflow-y:auto;display:flex;flex-direction:column;gap:10px}
.wb-prompt{font:12px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-surface,#f6f8fa);
  border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;padding:12px;margin:0;white-space:pre-wrap;word-break:break-word;
  max-height:52vh;overflow-y:auto}
.wb-empty{font-size:12px;color:var(--dsw-derive-muted,#57606a);padding:12px 0}
.wb-copied{font-size:11px;color:var(--dsw-derive-success,#1a7f37)}
.wb-pending{border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:5px 2px;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-body-pre{font-size:12px;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;word-break:break-word;background:var(--dsw-derive-surface,#f6f8fa);
  border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;padding:10px;margin:0;max-height:200px;overflow-y:auto}
.wb-chip{font-size:11px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;padding:1px 6px}
/* 内容预览（审批前过目） */
.wb-preview-box{max-width:860px}
.wb-preview-notice{font-size:12px;color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:5px 10px}
.wb-preview-ch{border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:8px 2px 12px}
.wb-preview-ch-title{font-size:15px;font-weight:600;color:var(--dsw-derive-fg,#1f2328);margin-bottom:6px}
.wb-preview-para{font-size:13px;line-height:1.9;color:var(--dsw-derive-fg,#1f2328);margin:0 0 8px;white-space:pre-wrap}
/* Temporal server/worker 状态点（台面头部，t260821-06）：绿=在线 红=离线，悬停见详情 */
.wb-head-spacer{flex:1}
.wb-health{display:inline-flex;align-items:center;gap:10px;flex:none}
.wb-health-link{display:inline-flex;align-items:center;gap:10px;text-decoration:none;border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:3px 8px;background:var(--dsw-derive-canvas,#ffffff)}
.wb-health-link:hover{border-color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-surface,#f6f8fa)}
/* 状态条按钮（workers 数 / 巡检出入口，260824 用户拍板②③）：药丸样式，点开态高亮。 */
.wb-status-btn{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--dsw-derive-muted,#57606a);cursor:pointer;
  background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:999px;padding:3px 10px;font-family:inherit;white-space:nowrap}
.wb-status-btn:hover{border-color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-status-btn[data-open=true]{border-color:var(--dsw-derive-accent,#0969da);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-status-btn[data-online=true]{color:var(--dsw-derive-success,#1a7f37);border-color:var(--dsw-derive-success-border,#7dd9a0);background:var(--dsw-derive-success-bg,#dafbe1)}
.wb-status-btn[data-online=false]{color:var(--dsw-derive-danger,#cf222e);border-color:var(--dsw-derive-danger-border,#ff9b9b);background:var(--dsw-derive-danger-bg,#ffebe9)}
/* workers 下拉面板：定位祖先=.wb-head（position:relative），右对齐贴状态条。 */
.wb-workers-panel{position:absolute;right:0;top:calc(100% + 6px);z-index:30;background:var(--dsw-derive-canvas,#ffffff);
  border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.12);padding:10px 12px;min-width:560px}
.wb-workers-head{font-size:12px;font-weight:600;color:var(--dsw-derive-fg,#1f2328);margin-bottom:6px}
.wb-workers-table{border-collapse:collapse;font-size:12px;width:100%}
.wb-workers-table th,.wb-workers-table td{text-align:left;padding:3px 12px 3px 0;border-bottom:1px solid var(--dsw-derive-border,#eaeef2);
  white-space:nowrap;color:var(--dsw-derive-fg,#1f2328);font-weight:400}
.wb-workers-table th{color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-workers-table tr[data-offline=true] td{color:var(--dsw-derive-muted,#8c959f)}
/* 分页条（260824 用户拍板⑥）。 */
.wb-pager{display:flex;align-items:center;gap:10px;justify-content:flex-end;padding:8px 0}
/* 巡检独立页（260824 用户拍板③）：返回条 + 复用 ScanReportSection 整页铺。 */
.wb-scan-backbar{display:flex;padding-bottom:8px}
.wb-health-item{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--dsw-derive-muted,#57606a);
  background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:999px;padding:3px 10px;cursor:help;white-space:nowrap}
.wb-health-dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:var(--dsw-derive-muted,#8c959f)}
.wb-health-item[data-online=true]{color:var(--dsw-derive-success,#1a7f37);border-color:var(--dsw-derive-success-border,#7dd9a0);background:var(--dsw-derive-success-bg,#dafbe1)}
.wb-health-item[data-online=true] .wb-health-dot{background:var(--dsw-derive-success-solid,#2da44e)}
.wb-health-item[data-online=false]{color:var(--dsw-derive-danger,#cf222e);border-color:var(--dsw-derive-danger-border,#ff9b9b);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-health-item[data-online=false] .wb-health-dot{background:var(--dsw-derive-danger-solid,#d1242f)}
.wb-health-offline{display:flex;flex-direction:column;gap:3px;background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  color:var(--dsw-derive-warn-deep,#7d4e00);border-radius:6px;padding:7px 12px;font-size:12px}
/* ── M9 变更页签（PR 式审批台；制式照 knowledge block diff，类名 wb-d-* 独立自带不依赖 knowledge CSS） ── */
.wb-dtabs{display:flex;gap:2px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de)}
.wb-dtab{font:inherit;font-size:13px;padding:7px 16px;border:none;background:none;color:var(--dsw-derive-muted,#57606a);cursor:pointer;
  border-bottom:2px solid transparent}
.wb-dtab[data-on=true]{color:var(--dsw-derive-accent,#0969da);font-weight:600;border-bottom-color:var(--dsw-derive-accent,#0969da)}
.wb-d-sum{font-size:12px;color:var(--dsw-derive-muted,#57606a);display:flex;gap:14px;flex-wrap:wrap}
.wb-d-file{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);overflow:hidden}
.wb-d-fhead{display:flex;align-items:center;gap:8px;padding:7px 12px;background:var(--dsw-derive-surface,#f6f8fa);
  border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);flex-wrap:wrap}
.wb-d-fpath{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--dsw-derive-fg,#1f2328);
  font-weight:600;word-break:break-all}
.wb-d-block{border-top:1px solid var(--dsw-derive-surface-2,#e8ebef)}
.wb-d-bhead{display:flex;align-items:center;gap:8px;padding:5px 12px;background:var(--dsw-derive-surface,#fbfcfd);flex-wrap:wrap}
.wb-d-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap}
.wb-d-badge[data-s=added]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-d-badge[data-s=removed]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-badge[data-s=modified]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-d-badge[data-s=unchanged]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a)}
.wb-d-badge[data-s=expired]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#8c959f);border:1px dashed var(--dsw-derive-border,#d0d7de)}
.wb-d-type{font-size:11px;color:var(--dsw-derive-muted,#8c959f);border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;padding:0 6px;white-space:nowrap}
.wb-d-md{padding:6px 14px;font-size:13px}
.wb-d-md-add{background:var(--dsw-derive-success-bg,#f0fff4);border-left:4px solid var(--dsw-derive-success-solid,#2da44e)}
.wb-d-md-del{background:var(--dsw-derive-danger-bg,#fff5f5);border-left:4px solid var(--dsw-derive-danger,#cf222e)}
.wb-d-md-old{background:var(--dsw-derive-danger-bg,#fff5f5);border-left:4px solid var(--dsw-derive-danger-border,#ff9b9b);border-bottom:1px dashed var(--dsw-derive-surface-2,#e8ebef)}
.wb-d-md-new{background:var(--dsw-derive-success-bg,#f0fff4);border-left:4px solid var(--dsw-derive-success-border,#7dd9a0)}
.wb-d-md-tag{font-size:11px;font-weight:600;color:var(--dsw-derive-muted,#57606a);letter-spacing:1px}
.wb-d-md-old .wb-d-md-tag{color:var(--dsw-derive-danger,#cf222e)}
.wb-d-md-new .wb-d-md-tag{color:var(--dsw-derive-success-deep,#116329)}
/* 渲染态 markdown 的最小样式（wb-md 作用域，对齐 knowledge kb-md） */
.wb-md h1,.wb-md h2,.wb-md h3,.wb-md h4,.wb-md h5,.wb-md h6{margin:6px 0;font-size:14px;color:var(--dsw-derive-fg,#1f2328)}
.wb-md p{margin:4px 0;line-height:1.7}
.wb-md code{background:var(--dsw-derive-surface-2,#eff1f3);border-radius:4px;padding:0 4px;font-size:12px}
.wb-md pre{background:var(--dsw-derive-surface,#f6f8fa);border-radius:6px;padding:8px 10px;overflow-x:auto;margin:4px 0}
.wb-md pre code{background:none;padding:0}
/* knowledge 出厂件收编（t260907-08）：knowledge 全局 CSS 的 .md-code/.md-cl/.md-copy/
 * .tok-* 固定浅档色不随平台翻——四象限 new-dark 格实锤 epics 详情围栏代码块
 * fg 写死浅档字色 on 派生深底 1.08:1（宿主症状②同族）。knowledge 全局 CSS 与 .wb-md
 * 同特异性且后注入会压过平级规则，故此处全部升一级特异性收编：底=派生 surface（随档翻），
 * 字=派生 fg，语法高亮映到派生语义令牌（fallback=knowledge 原浅档值，浅档视觉不变）。 */
.wb-md .md-code{background:var(--dsw-derive-surface,#f6f8fa);border-color:var(--dsw-derive-border,#d0d7de)}
.wb-md .md-code pre code{color:var(--dsw-derive-fg,#1f2328)}
.wb-md .md-cl{color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface-2,#eaeef2)}
.wb-md .md-copy{border-color:var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-muted,#57606a)}
.wb-md .md-copy:hover{background:var(--dsw-derive-surface-2,#eaeef2);color:var(--dsw-derive-fg,#1f2328)}
.wb-md .tok-c{color:var(--dsw-derive-muted,#6e7781)}
.wb-md .tok-s{color:var(--dsw-derive-accent,#0969da)}
.wb-md .tok-k{color:var(--dsw-derive-danger,#cf222e)}
.wb-md .tok-n{color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-md .tok-v{color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-md blockquote{margin:4px 0;padding:2px 10px;border-left:3px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
.wb-md table{border-collapse:collapse;margin:4px 0}
.wb-md table th,.wb-md table td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:3px 10px;text-align:left;font-size:12px}
.wb-md ul,.wb-md ol{margin:4px 0;padding-left:22px}
.wb-md hr{border:none;border-top:1px solid var(--dsw-derive-border,#d8dee4);margin:8px 0}
/* unified diff（代码文件） */
.wb-d-uni{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.55;
  padding:6px 0;overflow-x:auto}
.wb-d-line{padding:0 12px;white-space:pre-wrap;word-break:break-all}
.wb-d-line[data-k=add]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-d-line[data-k=del]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-line[data-k=hunk]{color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-d-line[data-k=meta]{color:var(--dsw-derive-muted,#8c959f)}
/* 数据对账表 */
.wb-d-recon{border-collapse:collapse;margin:6px 12px;font-size:12px;max-width:calc(100% - 24px);display:block;overflow-x:auto}
.wb-d-recon th,.wb-d-recon td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:4px 10px;text-align:left;
  vertical-align:top;white-space:pre-wrap;word-break:break-word}
.wb-d-recon th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-d-recon td[data-k=path]{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.wb-d-old{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-new{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
/* 表格行单元格级对齐 */
.wb-d-cells{border-collapse:collapse;margin:6px 12px;font-size:12px;max-width:calc(100% - 24px);display:block;overflow-x:auto}
.wb-d-cells th,.wb-d-cells td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:4px 10px;text-align:left;white-space:pre-wrap;word-break:break-word}
.wb-d-cells th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-d-cell-old{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e);text-decoration:line-through}
.wb-d-cell-new{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329);font-weight:600}
/* 意见动作条 */
.wb-d-actions{display:flex;gap:8px;align-items:center;padding:6px 12px;border-top:1px dashed var(--dsw-derive-surface-2,#e8ebef);flex-wrap:wrap}
.wb-d-btn{font-size:12px;padding:2px 12px;border-radius:6px;cursor:pointer;border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#fff);color:var(--dsw-derive-fg,#1f2328)}
.wb-d-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-d-btn-ap{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success-deep,#116329)}
.wb-d-btn-ap.on{background:var(--dsw-derive-success-deep,#116329);color:var(--dsw-derive-canvas,#fff)}
.wb-d-btn-rj{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-btn-rj.on{background:var(--dsw-derive-danger,#cf222e);color:var(--dsw-derive-canvas,#fff)}
.wb-d-cmt{width:100%;min-height:44px;font:inherit;font-size:12px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;
  padding:6px 10px;box-sizing:border-box}
.wb-d-expired{border:1px dashed var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:8px 12px;color:var(--dsw-derive-muted,#57606a);font-size:12px}
.wb-d-expired-item{padding:4px 0;border-bottom:1px solid var(--dsw-derive-border,#f0f2f5)}
.wb-d-expired-item:last-child{border-bottom:none}
.wb-d-conclude{font:inherit;font-size:12px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;padding:3px 8px;background:var(--dsw-derive-canvas,#fff)}
.wb-d-rework{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-surface,#fbfcfd);padding:10px 14px;
  display:flex;flex-direction:column;gap:8px}
.wb-d-rework pre{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  line-height:1.6;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow:auto}
.wb-d-trunc{font-size:11px;color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);border-radius:6px;
  padding:3px 10px;margin:4px 12px}
/* ── M6 巡检报告区（类名 wb-scan-* / wb-sug 独立） ── */
.wb-scan-meta{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-muted,#57606a);align-items:center}
.wb-scan-chips{display:flex;gap:8px;flex-wrap:wrap}
.wb-sug{font-size:12px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap}
.wb-sug[data-sug="可签"]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-sug[data-sug="待补"]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-sug[data-sug="疑似卡死"]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-scan-table{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--dsw-derive-surface-2,#e8ebef);
  border-radius:8px;font-size:12px;overflow:hidden}
.wb-scan-table th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600;text-align:left;padding:6px 10px;
  border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);white-space:nowrap}
.wb-scan-table td{padding:6px 10px;border-bottom:1px solid var(--dsw-derive-border,#f0f2f5);vertical-align:top}
.wb-scan-table tbody tr{cursor:pointer}
.wb-scan-table tbody tr:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-scan-table tbody tr:last-child td{border-bottom:none}
.wb-scan-id{color:var(--dsw-derive-accent,#0969da);font-weight:600;white-space:nowrap}
.wb-scan-title{color:var(--dsw-derive-muted,#57606a);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  max-width:260px}
.wb-scan-reasons{margin:0;padding-left:16px;color:var(--dsw-derive-muted,#57606a);font-size:11px}
.wb-scan-redline{font-size:11px;color:var(--dsw-derive-warn-deep,#7d4e00);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:4px 10px}
/* ── M12 agent 日志（wb-al-*：详情抽屉「Agent」页签） ── */
.wb-al-meta{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-muted,#57606a);align-items:center}
.wb-al-file{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);overflow:hidden}
.wb-al-fhead{display:flex;align-items:center;gap:8px;padding:6px 12px;background:var(--dsw-derive-surface,#f6f8fa);
  border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);cursor:pointer;flex-wrap:wrap}
.wb-al-fhead:hover{background:var(--dsw-derive-surface-2,#eef1f4)}
.wb-al-fname{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--dsw-derive-fg,#1f2328);
  font-weight:600;word-break:break-all}
.wb-al-fmeta{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-al-body{max-height:420px;overflow:auto;background:var(--dsw-derive-surface,#fbfcfd)}
.wb-al-pre{font:11px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-derive-fg,#1f2328);
  white-space:pre-wrap;word-break:break-word;padding:10px 12px;margin:0}
.wb-al-trunc{font-size:11px;color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:3px 10px;margin:8px 12px}
.wb-al-result-sum{display:flex;gap:6px 14px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-fg,#1f2328);
  padding:8px 12px 0}
.wb-al-result-key{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-al-status{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:600}
.wb-al-status[data-ok=true]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-al-status[data-ok=false]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-al-summ{font-size:12px;color:var(--dsw-derive-fg,#1f2328);padding:6px 12px 8px;line-height:1.6}
.wb-al-deliverable{font-size:11px;color:var(--dsw-derive-muted,#57606a)}
/* ── t260825-03 运行脉搏行（wb-pulse）+ 实时动态面板（wb-live） ── */
.wb-pulse{margin:6px 0 0;font-size:12px;line-height:1.6;padding:5px 12px;border-radius:6px;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);color:var(--dsw-derive-muted,#57606a)}
.wb-pulse[data-s=ok]{background:var(--dsw-derive-success-bg,#f0fdf4);border-color:var(--dsw-derive-success-border,#bbf7d0);color:var(--dsw-derive-success-deep,#116329)}
.wb-pulse[data-s=warn]{background:var(--dsw-derive-warn-bg,#fff8e6);border-color:var(--dsw-derive-warn-border,#eac54f);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-pulse[data-s=stuck]{background:var(--dsw-derive-danger-bg,#fff0f0);border-color:var(--dsw-derive-danger-border,#ffb3ad);color:var(--dsw-derive-danger,#cf222e);font-weight:600}
.wb-pulse .wb-pulse-k{color:var(--dsw-derive-muted,#8c959f);margin-right:2px}
.wb-live{margin:6px 0 0;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff);overflow:hidden}
.wb-live-head{display:flex;align-items:center;gap:10px;padding:6px 12px;font-size:12px;
  color:var(--dsw-derive-muted,#57606a);cursor:pointer;user-select:none}
.wb-live-head:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-live-head .wb-live-title{font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-live-meta{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-live-body{border-top:1px solid var(--dsw-derive-surface-2,#e8ebef);max-height:320px;overflow:auto;padding:4px 0;background:var(--dsw-derive-surface,#fbfcfd)}
.wb-live-row{display:flex;gap:8px;padding:2px 12px;font-size:12px;align-items:baseline;line-height:1.7}
.wb-live-ts{flex:0 0 auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-live-type{flex:0 0 auto;font-size:10px;padding:0 6px;border-radius:4px;background:var(--dsw-derive-surface-2,#eef1f4);color:var(--dsw-derive-muted,#57606a)}
.wb-live-type[data-t=tool]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
/* KI-024：轮次/重试行——比工具行更弱的信号，配色去饱和（蓝灰/橙灰），不加新色板 */
.wb-live-type[data-t=step]{background:var(--dsw-derive-surface-2,#eef1f4);color:var(--dsw-derive-muted,#57606a)}
.wb-live-type[data-t=retry]{background:var(--dsw-derive-warn-bg,#fff1e5);color:var(--dsw-derive-warn,#9a6700)}
.wb-live-type[data-t=assistant]{background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-live-type[data-t=user]{background:var(--dsw-derive-warn-bg,#fff1e5);color:var(--dsw-derive-warn-deep,#bc4c00)}
.wb-live-sum{color:var(--dsw-derive-fg,#1f2328);word-break:break-all}

/* ── 详情页 v2（260824 重设计：步骤条/一句话现状/操作条/问题区/阶段卡/深查折叠） ── */
/* v2.1（260824 二轮）：正文置顶卡 / id 内联 / 打回横幅 / 步进条圆点化 / 变更分组 / 日志按步分组 */
.wb-d2-id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--dsw-derive-muted,#8c959f);
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:4px;padding:1px 6px}
/* 步骤条：一步一圆点，色=状态（绿✓完成 蓝▶在跑 红✗卡住 黄✋等人 灰○未到）；
   完成判定按模板链序——当前步之前=done（merge_check 等脚本门不落 results 也能打勾） */
.wb-d2-steps{display:flex;align-items:center;flex-wrap:wrap;gap:0;row-gap:6px;margin:12px 0 4px;
  padding:10px 12px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff)}
.wb-d2-step{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--dsw-derive-muted,#8c959f);padding:3px 8px;border-radius:6px}
.wb-d2-par{font-weight:700;color:var(--dsw-derive-accent,#0969da);cursor:default}
.wb-d2-step .ico{font-style:normal;font-weight:700;width:18px;height:18px;border-radius:50%;
  display:inline-flex;align-items:center;justify-content:center;font-size:11px;flex:0 0 18px;
  background:var(--dsw-derive-surface-2,#e8ebef);color:var(--dsw-derive-muted,#8c959f)}
.wb-d2-step[data-s=done]{color:var(--dsw-derive-success,#1a7f37)}
.wb-d2-step[data-s=done] .ico{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success,#1a7f37)}
.wb-d2-step[data-s=running]{color:var(--dsw-derive-accent-deep,#0550ae);font-weight:600;background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-d2-step[data-s=running] .ico{background:var(--dsw-derive-accent,#0969da);color:var(--dsw-derive-canvas,#fff)}
.wb-d2-step[data-s=blocked]{color:var(--dsw-derive-danger,#cf222e);font-weight:600;background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-d2-step[data-s=blocked] .ico{background:var(--dsw-derive-danger,#cf222e);color:var(--dsw-derive-canvas,#fff)}
.wb-d2-step[data-s=awaiting-human]{color:var(--dsw-derive-warn-deep,#7d4e00);font-weight:600;background:var(--dsw-derive-warn-bg,#fff8c5)}
.wb-d2-step[data-s=awaiting-human] .ico{background:var(--dsw-derive-warn,#bf8700);color:var(--dsw-derive-canvas,#fff)}
.wb-d2-link{flex:0 0 14px;height:1px;background:var(--dsw-derive-border,#d0d7de);margin:0 2px}
/* 一句话现状条 */
.wb-d2-status{margin:8px 0 0;font-size:13px;line-height:1.6;padding:7px 12px;border-radius:6px;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);color:var(--dsw-derive-fg,#1f2328)}
.wb-d2-status[data-s=blocked]{background:var(--dsw-derive-danger-bg,#ffebe9);border-color:var(--dsw-derive-danger-border,#ffb3ad);color:var(--dsw-derive-danger,#cf222e)}
.wb-d2-status[data-s=awaiting-human]{background:var(--dsw-derive-warn-bg,#fff8c5);border-color:var(--dsw-derive-warn-border,#eac54f);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-d2-status[data-s=running]{background:var(--dsw-derive-accent-bg,#ddf4ff);border-color:var(--dsw-derive-accent-border,#9cd6ff);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-d2-status[data-s=done]{background:var(--dsw-derive-success-bg,#dafbe1);border-color:var(--dsw-derive-success-border,#7ddb8a);color:var(--dsw-derive-success-deep,#116329)}
/* 打回横幅：timeline 里 state=rework 的记录（何时/谁/理由/打回到哪步），有才渲染 */
.wb-d2-reworks{margin-top:10px;border:1px solid var(--dsw-derive-warn-border,#eac54f);border-left:4px solid var(--dsw-derive-warn,#bf8700);
  border-radius:6px;background:var(--dsw-derive-warn-bg,#fffdf2);padding:8px 12px}
.wb-d2-reworks .ttl{font-size:12px;font-weight:700;color:var(--dsw-derive-warn-deep,#7d4e00);margin-bottom:4px}
.wb-d2-reworks .row{font-size:12px;color:var(--dsw-derive-warn-deep,#5a4500);line-height:1.7;padding:1px 0}
.wb-d2-reworks .row .when{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
  color:var(--dsw-derive-warn,#a08517);margin-right:6px}
.wb-d2-reworks .row .tgt{font-weight:600}
/* 操作条：钉在头部下方，主操作平铺、低频收「更多」 */
.wb-d2-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0 0;
  padding:8px 10px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);
  position:sticky;top:0;z-index:5}
.wb-d2-actions .wb-d2-hint{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-d2-more{margin-left:auto}
.wb-d2-more>summary{cursor:pointer;font-size:12px;color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d2-more>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-more[open]>summary{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-more-body{display:flex;gap:8px;flex-wrap:wrap;padding-top:8px}
/* 问题区：只在有问题时渲染 */
.wb-d2-problems{margin-top:10px;border:1px solid var(--dsw-derive-danger-border,#ffb3ad);border-left:4px solid var(--dsw-derive-danger,#cf222e);
  border-radius:6px;background:var(--dsw-derive-danger-bg,#fff5f5);padding:8px 12px}
.wb-d2-problems .ttl{font-size:12px;font-weight:700;color:var(--dsw-derive-danger,#cf222e);margin-bottom:4px}
.wb-d2-problems .row{font-size:12px;color:var(--dsw-derive-danger,#7d2222);line-height:1.6;padding:1px 0}
.wb-d2-problems .row .dim{color:var(--dsw-derive-danger,#b06060)}
/* 工单正文（原始需求）：钉在详情最顶部，所有页签可见 */
.wb-d2-body{margin-top:10px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff);
  padding:10px 14px;font-size:13px;line-height:1.75;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;
  word-break:break-word;max-height:320px;overflow-y:auto}
.wb-d2-body .ttl{font-size:11px;color:var(--dsw-derive-muted,#8c959f);margin-bottom:4px;font-weight:600}
/* 执行规格卡（t260904-06）：钉在正文卡正下方，蓝左边条与正文卡做视觉区分（原始需求=用户说的，
   spec=开票会话蒸馏的执行规格）；B 形态=默认展开+限高滚动（样张 260904-spec-card-mockup B 卡）。
   样张已评审拍板进方案（impl 段无需回读样张；样式/文案/结构见下方三条规则）。 */
.wb-d2-spec{margin-top:10px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-left:4px solid var(--dsw-derive-accent,#0969da);border-radius:8px;background:var(--dsw-derive-canvas,#fff);
  padding:10px 14px;font-size:13px;line-height:1.75;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;
  word-break:break-word;max-height:260px;overflow-y:auto}
.wb-d2-spec .ttl{font-size:11px;color:var(--dsw-derive-muted,#57606a);margin-bottom:4px;font-weight:600;
  display:flex;align-items:baseline;gap:8px}
.wb-d2-spec .cnt{font-weight:400;color:var(--dsw-derive-muted,#8c959f);font-family:ui-monospace,Menlo,monospace;font-size:10px}
/* 阶段卡：进展主体 */
.wb-d2-stages{margin-top:10px;display:flex;flex-direction:column;gap:6px}
/* 执行主体徽标（t260828-01）：🤖⚙️👤 直接拼接，软降级「—」 */
.wb-parts{font-size:11px;letter-spacing:1px;color:var(--dsw-derive-muted,#57606a);white-space:nowrap}
/* token 行内数字（t260828-07）：头部合计与阶段行内数字，克制小字、数字进悬停有精确值 */
.wb-usage{font-size:11px;color:var(--dsw-derive-muted,#57606a);white-space:nowrap}
.wb-usage[data-s=none]{color:var(--dsw-derive-muted,#8c959f)}
.wb-stage-usage{font-size:11px;color:var(--dsw-derive-muted,#57606a);white-space:nowrap;margin-left:4px}
/* 节点耗时徽标（t260901-12）：颜色随视觉态（内联 style 取自 D2_COLOR），走秒用等宽数字防跳宽 */
.wb-stage-dur{font-size:11px;white-space:nowrap;margin-left:4px;font-variant-numeric:tabular-nums}
.wb-d2-card{border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;padding:8px 12px;background:var(--dsw-derive-canvas,#fff)}
.wb-d2-card[data-s=running]{border-color:var(--dsw-derive-accent-border,#9cd6ff);background:var(--dsw-derive-accent-bg,#f6fbff)}
.wb-d2-card[data-s=blocked]{border-color:var(--dsw-derive-danger-border,#ffb3ad);background:var(--dsw-derive-danger-bg,#fff8f7)}
.wb-d2-card[data-s=awaiting-human]{border-color:var(--dsw-derive-warn-border,#eac54f);background:var(--dsw-derive-warn-bg,#fffdf2)}
.wb-d2-card[data-s=todo]{opacity:.62}
.wb-d2-card .hd{display:flex;align-items:baseline;gap:8px;font-size:13px}
.wb-d2-card .hd .ico{font-style:normal;font-weight:700}
.wb-d2-card .hd .nm{font-weight:600}
.wb-d2-card .hd .meta{margin-left:auto;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-d2-card .sum{font-size:12px;color:var(--dsw-derive-fg,#1f2328);line-height:1.6;margin-top:3px;
  white-space:pre-wrap;word-break:break-word}
.wb-d2-card .wb-d2-report{margin-top:5px;padding:6px 10px;background:var(--dsw-derive-surface,#fbfcfd);
  border-left:3px solid var(--dsw-derive-border,#d8dee4);border-radius:0 6px 6px 0;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-d2-card details{margin-top:4px}
.wb-d2-card details>summary{cursor:pointer;font-size:11px;color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d2-card details>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-card .ev{font-size:11px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border-radius:4px;
  padding:6px 8px;margin-top:4px;white-space:pre-wrap;word-break:break-word;
  max-height:220px;overflow-y:auto}
/* 深查折叠区 */
.wb-d2-deep{margin-top:12px;border-top:1px solid var(--dsw-derive-surface-2,#e8ebef);padding-top:8px}
.wb-d2-deep>details{border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;margin-bottom:6px;background:var(--dsw-derive-canvas,#fff)}
.wb-d2-deep>details>summary{cursor:pointer;padding:7px 12px;font-size:12px;font-weight:600;
  color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d2-deep>details>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-deep>details>summary::before{content:'▸ '}
.wb-d2-deep>details[open]>summary::before{content:'▾ '}
.wb-d2-deep>details>div{padding:0 12px 10px}
/* ── 快照要点（t260905-07：阶段时间线/最近交接/门与签字记录/工作流快照，ticket show 直读） ──
   （t260907-08：本段是 t260905-08 令牌化 sweep 的漏网点——写死浅档色在深色档不可读，全量归位派生令牌） */
.wb-dsnap-block{margin:6px 0}
.wb-dsnap-block>h4{margin:0 0 4px;font-size:11px;color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-dsnap-row{display:flex;gap:8px;font-size:12px;line-height:1.7;flex-wrap:wrap}
.wb-dsnap-row .st{color:var(--dsw-derive-muted,#57606a);min-width:88px}
.wb-dsnap-row .at{color:var(--dsw-derive-muted,#8c959f);font-size:11px}
.wb-dsnap-row[data-untime=true] .at{color:var(--dsw-derive-danger,#cf222e)}
.wb-dsnap-chip{display:inline-block;padding:0 6px;border-radius:10px;font-size:11px;margin-right:4px}
.wb-dsnap-chip[data-kind=gate]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);border:1px solid var(--dsw-derive-border,#d0d7de)}
.wb-dsnap-chip[data-kind=signature]{background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent,#0969da);border:1px solid var(--dsw-derive-accent-border,#96c8f2)}
.wb-dsnap-empty{font-size:12px;color:var(--dsw-derive-muted,#8c959f)}
/* 变更 tab：文件头 +/− 行数；构建产物（lib/ bundle）折叠组 */
.wb-d-stats{font-size:11px;margin-left:auto;white-space:nowrap}
.wb-d-stats .add{color:var(--dsw-derive-success,#1a7f37)}
.wb-d-stats .del{color:var(--dsw-derive-danger,#cf222e)}
.wb-d-gen{margin-top:10px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-surface,#f6f8fa)}
.wb-d-gen>summary{cursor:pointer;padding:8px 12px;font-size:12px;color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d-gen>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d-gen>summary::before{content:'▸ '}
.wb-d-gen[open]>summary::before{content:'▾ '}
.wb-d-gen .wb-d-gen-list{padding:0 12px 10px}
.wb-d-gen-row{display:flex;gap:8px;align-items:center;font-size:12px;padding:2px 0;color:var(--dsw-derive-muted,#57606a)}
.wb-d-gen-row .p{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all}
/* Agent 日志 tab：按工作流步序的分组卡（每步一卡，内含 gen 尝试行） */
.wb-al-stage{border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff);overflow:hidden;margin-top:8px}
.wb-al-shead{display:flex;align-items:center;gap:8px;padding:7px 12px;background:var(--dsw-derive-surface,#f6f8fa);font-size:12.5px}
.wb-al-shead .nm{font-weight:600}
.wb-al-shead .ico{font-style:normal;font-weight:700}
.wb-al-shead .meta{margin-left:auto;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-al-attempt{border-top:1px solid var(--dsw-derive-surface-2,#eef1f4)}
.wb-al-attempt>summary{cursor:pointer;display:flex;align-items:center;gap:8px;padding:6px 12px;
  font-size:12px;color:var(--dsw-derive-fg,#1f2328);list-style:none}
.wb-al-attempt>summary::before{content:'▸ ';color:var(--dsw-derive-muted,#8c959f)}
.wb-al-attempt[open]>summary::before{content:'▾ '}
.wb-al-attempt>summary:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-al-attempt .sum{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:var(--dsw-derive-muted,#57606a);font-size:11.5px}
.wb-al-attempt .wb-al-body{border-top:1px solid var(--dsw-derive-surface-2,#eef1f4)}
`

const CSS_TAG_ID = 'sandbar-workbench/WorkbenchSection.css'
if (typeof document !== 'undefined'
  && document.querySelector('style[data-plugin-css=' + JSON.stringify(CSS_TAG_ID) + ']') === null) {
  const tag = document.createElement('style')
  tag.dataset.plugin = 'sandbar-workbench'
  tag.dataset.pluginCss = CSS_TAG_ID
  tag.textContent = CSS
  document.head.appendChild(tag)
}

/* -------------------------------------------------------------- 数据通道 */

const API = '/sandbar-workbench/api/wf'

interface CallResult {
  ok: boolean
  result?: any
  error?: string
  run_id?: string
}

/** 多项目化（260823）：当前视图的项目 key，WorkbenchSection 挂载/切换时从 prop 设置。
 *  中列同一时刻只挂一个视图，模块单态安全。空串=不拼参（host 会 400，UI 先显占位）。
 *  t260828-06：单态本体迁到 shared/view-project.ts——hero 接管组件（root 作用域，
 *  不在中列组件树内）也要读它做「当前项目」推导。 */
import { getViewProject, setViewProject } from '../shared/view-project.ts'
import { DERIVE_TOKENS_CSS, epicChipColor, epicChipMuted } from './theme';

/** 统一拼 ?project=（host 侧工单列表必传；详情/健康/巡检等路由多带的 query 无害——按 path 匹配）。 */
function withProject(path: string): string {
  const viewProject = getViewProject()
  if (!viewProject) return path
  return path + (path.includes('?') ? '&' : '?') + 'project=' + encodeURIComponent(viewProject)
}

async function apiGet(path: string): Promise<any> {
  const res = await fetch(withProject(path))
  return res.json()
}

async function apiPost(path: string, body: unknown): Promise<CallResult> {
  const res = await fetch(withProject(path), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  return res.json()
}

/* ---------------------------------------------------------------- 类型 */

interface TicketRow {
  id: string
  role: string
  status: string
  title: string
  /** 无标题票的首句派生（t260905-07）：host enrichment 从 show body 裁剪下发，
   *  仅 title 为空的票带；缺省=行卡回退裸编号（enrichment 失败降级自然）。 */
  title_or_first?: string
  workflow: string
  proposal_id?: string
  /** 所属立项代号（epic-linkage；无 epic 的工单为 ''/缺省 → 徽标显「未归档」）。 */
  epic?: string
  stage: string | null
  stage_state: string
  handoff_count: number
  pending_count: number
  worktree: string
  workspace?: { type: string; path: string } | null
  created?: number
  pending?: { ts: number; note: string }[]
  updated: string
  updated_ts?: number
  engine?: string
  session_kb?: number
  agent_alive?: boolean
  exec_status?: string
  blocked_reason?: string
}

/** 内容预览（book API 返回；审批前过目用）。 */
interface PreviewChapter {
  id: string
  标题: string
  paras: string[]
}
interface PreviewData {
  preview: boolean
  meta: { 主题: string; 类型: string; 期次: string; total_chapters: number; size_kb: number }
  chapters: PreviewChapter[]
}

/** Temporal 健康（temporal-health API 返回；server=端口监听，worker=pid 存活）。 */
interface TemporalHealthPart {
  online: boolean
  detail: string
}
interface TemporalHealth {
  ts: number
  server: TemporalHealthPart & { host: string; port: number }
  worker: TemporalHealthPart & { pid: number | null; pidfile: string }
  restart_hint: { server: string; worker: string }
}

/** 一工单一 worker（260824）：/wf/workers 返回的逐 worker 状态行。 */
interface WorkerRow {
  ticket: string | null
  queue: string
  pid: number | null
  online: boolean
  log_mtime: number | null
}
interface WorkersResult {
  count: number
  count_alive: number
  workers: WorkerRow[]
}

interface WfStage {
  id: string
  role: string
  name: string
  next?: string
  exit?: string
  fanout?: number
  revision_to?: string
  /** 执行主体组合声明（t260828-01，agent/script/human 可组合）；旧数据无此字段→「—」软降级。 */
  parts?: string[]
  acceptance?: string[]
}

interface Wf {
  id: string
  name: string
  lane: string
  stages: WfStage[]
}

interface CheckItem {
  item: string
  done: boolean
  by?: string
  evidence?: string
  agent?: string
}

interface Handoff {
  stage: string
  agent_id?: string
  summary?: string
  artifacts?: string[]
  ts?: number
}

interface TicketDetail {
  id: string
  title: string
  workflow_id: string
  /** 阻塞原因（t260904-17：行卡「看原因」导航锚——ticket show 透传字段）。 */
  blocked_reason?: string
  /** 所属立项代号（epic-linkage；详情 API 已透出，t260825-04）。 */
  epic?: string
  stage: string | null
  stage_state: string
  status: string
  role: string
  lane?: string
  worktree?: string
  workspace?: { type: string; path: string } | null
  branch?: string
  base_ref?: string
  proposal_id?: string
  book_path?: string
  revision_count?: number
  last_advance_stage?: string | null
  acceptance: string[]
  stage_acceptance?: string[]
  stage_name?: string
  checks?: Record<string, CheckItem[]>
  handoffs?: Handoff[]
  pending?: { ts: number; note: string }[]
  log?: { ts: number; status?: string; note: string }[]
  body?: string
  /** 执行规格（t260904-06）：开票会话蒸馏的加工后派发规格，引擎 snapshot 顶层原样透传
   *  （零后端改动），前端只渲染；空/缺省整卡不渲染（老票兼容）。 */
  spec?: string
  write_set?: string[]
  deliverables?: string
  created?: number
  updated?: number
  session_kb?: number
  agent_alive?: boolean
  workflow_input?: Record<string, unknown>
  /** v2 快照补充（详情页 redesign 260824）：程序化门结果 / 阶段流水 / 每步产出——
   *  接口一直返回，前端此前未用（问题区与阶段卡的数据源）。 */
  gate_runs?: GateRun[]
  timeline?: TimelineEntry[]
  results?: Record<string, StageResultEntry>
  last_rework_note?: string
  signatures?: Record<string, { who: string; decision: string; note: string; at: string }>
  /** 运行脉搏（t260825-03）：RUNNING 工单的 pending activity 心跳（client.py 掏出，
   *  ticket show 透传）；无心跳/非 RUNNING → null，脉搏行据此软降级。 */
  pulse?: Pulse | null
  /** KI-024 并行真源（t260903-04）：引擎 snapshot 附 meta 全文；UI 只消费
   *  parallel_stages（并行分叉期活跃边列表）——lane-states 真值优先双显，
   *  缺失/空回落既有 timeline 启发式。 */
  meta?: { parallel_stages?: string[] } | null
}

/** Temporal pending activity 心跳（agent_activities.py 每 5s 上报 {stage,gen,polls,session_kb}）。 */
interface Pulse {
  activity?: string
  attempt?: number
  state?: string
  /** 最近一次心跳时间（epoch 秒），0=还没心跳过。 */
  last_heartbeat_ts?: number
  /** 本次 activity 尝试的启动时间（epoch 秒）。 */
  started_ts?: number
  heartbeat?: { stage?: string; gen?: number; polls?: number; session_kb?: number }
  /** 心跳非 JSON（stub 等）时的原文截断。 */
  heartbeat_raw?: string
}

/** agent-live 端点（t260825-03）返回的一条实时事件。 */
interface AgentLiveEvent {
  ts: number
  type: string
  summary: string
}
interface AgentLiveResult {
  exists: boolean
  path?: string
  sizeKb?: number
  mtime?: number
  events: AgentLiveEvent[]
  truncated: boolean
  reason?: string
  ws_root?: string
}

/** merge_check 等程序化门的一次运行记录（红绿 + 明细，问题区数据源）。 */
interface GateRun {
  stage: string
  label: string
  green: boolean
  red_count?: number
  checks: { item: string; green: boolean; detail?: string }[]
}

/** 阶段流水一条（workflow _mark 落的时间线：running/blocked/rework/awaiting-human…）。 */
interface TimelineEntry {
  at: string
  stage: string
  state: string
  reason: string
}

/** 一个 agent 段的结算（结果文件摘要：summary/evidence/deliverables/files_changed/gen）。 */
interface StageResultEntry {
  status: string
  summary: string
  /** 人读进展报告（markdown：做了什么/怎么验证的/遗留与风险）；旧结果文件无此字段 → 回落 summary。 */
  report?: string
  deliverables?: string[]
  files_changed?: string[]
  evidence?: string
  gen?: number
}

/* ------------------------------------------------ M6 巡检报告（scan-report API） */

/** 一张待决工单的巡检条目（与 temporal-poc shared.ScanTicketItem 同构）。 */
interface ScanItem {
  ticket_id: string
  title: string
  status: string
  stage: string
  stage_state: string
  dwell_hours: number
  acceptance_done: number
  acceptance_total: number
  pending_count: number
  gate_label: string
  gate_green: boolean | null
  suggestion: string          // 疑似卡死 / 待补 / 可签
  reasons: string[]
}

/** 一次巡检的报告（out/scan/<日期>.json 内容）。 */
interface ScanReport {
  generated_at: string
  total_tickets: number
  by_status: Record<string, number>
  pending_decision_count: number
  stuck_threshold_hours: number
  red_line: string
  summary: Record<string, number>
  items: ScanItem[]
}

/** scan-report API 返回（report=null + reason=人话降级）。 */
interface ScanReportResult {
  file: string | null
  report: ScanReport | null
  reason: string
}

/* ------------------------------------------------------------- 台面卡片 */

/** 状态文字（色板对应：running绿/awaiting黄/awaiting-human蓝/blocked红/done灰）。 */
const STATE_LABEL: Record<string, string> = {
  running: '进行中',
  awaiting: '待分派',
  'awaiting-human': '待审批',
  blocked: '卡住',
  closed: '已完成',
  done: '已完成',
}

/**
 * 状态语义优先级（260820 迁移遗留修复，UI 层不改数据）：
 * status=closed 的工单 stage_state 被迁移置成了 awaiting——语义上已完成，
 * 一律按 done（灰点「已完成」）显示，忽略 stage_state；其余按 stage_state。
 */
function ticketState(t: { status: string; stage_state: string }): string {
  return t.status === 'closed' ? 'done' : (t.stage_state || 'awaiting')
}

/**
 * 阶段列语义（同 ticketState 的 closed 优先思路，UI 层不改数据）：
 * status=closed 的老工单没有阶段历史，迁移把 stage 挂到了模板起点——显示 workflow
 * 终态 stage（N/N 全满格式，如 dev-lane→「完成 6/6」、content-pipeline→「发布 7/7」、
 * proofread→「分流 2/2」），忽略迁移挂的 stage 指针；非 closed 照常「阶段名 序号/总数」。
 */
function stageTextOf(t: { status: string; stage: string | null }, wf?: Wf): string {
  if (!wf || wf.stages.length === 0) return '—'
  if (t.status === 'closed') return '已完成'
  const total = wf.stages.length
  const idx = t.stage !== null ? wf.stages.findIndex(s => s.id === t.stage) : -1
  if (idx < 0) return '—'
  return `${wf.stages[idx].name} ${idx + 1}/${total}`
}

function shortSlug(worktree: string): string {
  return worktree.split('/').pop() || worktree
}

/** 操作者标识（本机管理台无登录）：LS 持久，首访生成 op-<随机>；accept 的 by 用它，审计落账。 */
const OPERATOR_KEY = 'sandbar-workbench-operator-v1'
function operatorOf(): string {
  try {
    const old = localStorage.getItem(OPERATOR_KEY)
    if (old) return old
    const id = 'op-' + Math.random().toString(36).slice(2, 8)
    localStorage.setItem(OPERATOR_KEY, id)
    return id
  } catch { return 'op-local' }
}


/* ------------------------------------------------------------- 详情抽屉 */

/** 执行主体徽标（t260828-01，observability「执行主体可见」）：模版 STAGES 的 parts
 *  静态声明按组合态直接拼接（🤖 agent / ⚙️ 脚本 / 👤 人），悬停一行说明；
 *  无 parts 的旧数据软降级「—」，不报错。动态真源仍是 Temporal history，此处只呈现声明。 */
function PartsBadges({ parts }: { parts?: string[] }) {
  return <span className="wb-parts" title={partsTitle(parts)}>{partsIcons(parts)}</span>
}

function fmtTs(ts?: number): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

/** 快照要点的时间显示（t260905-07）：引擎快照时间字段可能是秒级数值、毫秒数值、
 *  数字串或人话时间串（老票/引擎版本差）——数字按量级判别（<1e11 秒 / ≥1e11 毫秒，
 *  toMillis 同款口径），非数字原样显示，null → ''。畸形（NaN/负数）原样透传不猜
 *  （时间失真面显性化，与 untime 标注同纪律）。 */
function fmtSnapshotTs(v: string | null): string {
  if (v === null) return ''
  const n = Number(v)
  if (v !== '' && Number.isFinite(n) && n > 0) {
    // 量级判别（toMillis 同款口径）：<1e11 视为秒、≥1e11 视为毫秒——引擎老票秒级
    // 与 fixture/引擎新面毫秒级两域在可预见时间无重叠。
    const ms = n < 1e11 ? n * 1000 : n
    return new Date(ms).toLocaleString('zh-CN', { hour12: false })
  }
  return v
}

/* ------------------------------------------------- M14 详情五分组（层次化 section） */

/** 编号 section 标题：01/02/… 蓝色编号徽标 + 标题 + 灰色说明（详情分组层次分明）。 */
function SectionTitle({ num, title, desc }: { num: string; title: string; desc?: string }) {
  return (
    <div className="wb-section-title">
      <span className="wb-section-num">{num}</span>{title}
      {desc && <span className="wb-section-desc">{desc}</span>}
    </div>
  )
}

/** 基本信息网格条目：键（灰）值（黑），超长省略悬停全文。 */
function MetaItem({ k, children, title }: { k: string; children: ReactNode; title?: string }) {
  return (
    <span className="wb-meta-item">
      <span className="wb-meta-k">{k}</span>
      <span title={title}>{children}</span>
    </span>
  )
}

/* ------------------------------------------------- 详情页 v2（260824 重设计） */

/** 阶段视觉态推导住在纯模块 lane-states.ts（零依赖，node 可裸 import 做行为测试）；
 *  index.tsx 只做消费。推导口径（优先级/回退/畸形输入）见 lane-states.ts 头注。 */
function d2StageVisual(detail: TicketDetail, stageId: string, order: string[]): D2Visual {
  if (detail.status === 'closed') return 'done'
  const derived = deriveStageStates(detail, order)
  return derived.states[stageId] ?? 'todo'
}

const D2_ICON: Record<D2Visual, string> = {
  done: '✓', running: '▶', blocked: '✗', 'awaiting-human': '✋', todo: '○',
}
/** 图标配色（Agent 日志分组卡头等非 .wb-d2-step 场景用，与步进条同口径）。 */
const D2_COLOR: Record<D2Visual, string> = {
  done: 'var(--dsw-derive-success,#1a7f37)', running: 'var(--dsw-derive-accent,#0969da)', blocked: 'var(--dsw-derive-danger,#cf222e)', 'awaiting-human': 'var(--dsw-derive-warn,#9a6700)', todo: 'var(--dsw-derive-muted,#8c959f)',
}

/** timeline 的 at 是 ISO 串（base.py _mark）；列表/横幅统一显 MM-DD HH:mm。 */
function fmtAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 节点耗时（t260901-12，metrics M1b）：纯模块推导 + 1s 走秒。
 *  起表条件=抽屉开（父组件随 selectedId 条件渲染整树卸载）且有活跃步或人等段在场；
 *  enabled 变 false / 组件卸载即清 interval（全终态回收）。推导本身每次 render 便宜，
 *  仅在 nowMs 跳动（1s）或 detail/selWf 变化时重算。 */
function useStageDurations(detail: TicketDetail | undefined, wf: Wf | undefined): {
  durs: Record<string, StageDuration>
  nowMs: number
} {
  const order = useMemo(() => wf?.stages.map(s => s.id) ?? [], [wf])
  const derived = useMemo(
    () => (detail && order.length > 0) ? deriveStageStates(detail, order) : null,
    [detail, order],
  )
  const ticking = derived !== null && (
    derived.active.length > 0 || order.some(id => derived.states[id] === 'awaiting-human')
  )
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!ticking) return
    const timer = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [ticking])
  const durs = useMemo(
    () => (detail && order.length > 0)
      ? deriveStageDurations(detail.timeline, order, detail.handoffs, {
          closedTs: detail.status === 'closed' ? (detail.updated ?? null) : null,
        })
      : {},
    [detail, order],
  )
  return { durs, nowMs }
}

/** 节点耗时徽标（t260901-12）：done 显定值；running 走秒；人审等待显橙「人等 Xm」实时；
 *  todo/blocked 不显；done/todo 遇开放窗不显（引擎无 done mark，不发明口径）。
 *  总耗时=Σ轮=墙钟占用（含人等/阻塞跨度），tooltip 逐轮 + 人等段单列可拆。 */
function StageDurationInline({ d, vis, nowMs }: { d: StageDuration; vis: D2Visual; nowMs: number }) {
  if (vis === 'todo' || vis === 'blocked') return null
  const openRound = d.rounds.some(r => r.toMs === null)
  if (vis === 'done') {
    if (openRound) return null
    const total = stageTotalMs(d)
    if (total === null) return null
    return (
      <span className="wb-stage-dur" style={{ color: D2_COLOR.done }} title={stageDurationTitle(d)}>
        {fmtDurMs(total)}
      </span>
    )
  }
  // running / awaiting-human：开放窗用 nowMs 实时走秒。
  const openWait = d.humanWaits.some(w => w.toMs === null)
  const text = vis === 'awaiting-human' && openWait
    ? `人等 ${fmtDurMs(humanWaitTotalMs(d, nowMs))}`
    : (() => { const t = stageTotalMs(d, nowMs); return t === null ? null : fmtDurMs(t) })()
  if (text === null) return null
  return (
    <span className="wb-stage-dur" style={{ color: D2_COLOR[vis] }} title={stageDurationTitle(d, nowMs)}>
      {text}
    </span>
  )
}

/** 步骤条：模板步链一字排开，色=状态（与左栏圆点同口径）。
 *  t260901-05：并行分叉期多个步同时 ▶（活跃步数组语义，数据源 deriveStageStates；
 *  回退口径（活跃空/无 timeline）states 已是单值指针结果，直接消费）。 */
function D2Stepper({ detail, wf, usage, durs, nowMs }: {
  detail: TicketDetail
  wf?: Wf
  usage?: AgentUsageResult
  /** 节点耗时（t260901-12）：父组件一次推导两处传参，避免重复算。 */
  durs?: Record<string, StageDuration>
  nowMs?: number
}) {
  if (!wf || wf.stages.length === 0) return null
  const order = wf.stages.map(s => s.id)
  const derived = deriveStageStates(detail, order)
  const isParallel = derived.active.length > 1
  return (
    <div className="wb-d2-steps">
      {wf.stages.map((s, i) => {
        const vis: D2Visual = derived.states[s.id] ?? 'todo'
        const parallelPeers = isParallel && vis === 'running'
          ? derived.active.filter(id => id !== s.id).map(id => wf.stages.find(x => x.id === id)?.name ?? id)
          : []
        return (
          <span key={s.id} style={{ display: 'inline-flex', alignItems: 'center' }}>
            {i > 0 && <span className="wb-d2-link" />}
            <span className="wb-d2-step" data-s={vis} title={`${s.id} · ${s.role} · ${partsTitle(s.parts)}`}>
              <i className="ico">{D2_ICON[vis]}</i>{s.name} <PartsBadges parts={s.parts} />
              {parallelPeers.length > 0 && (
                <span className="wb-d2-par" title={`与 ${parallelPeers.join('、')} 并行（分叉渲染）`}> ∥</span>
              )}
              {(s.parts ?? []).includes('agent') && <StageUsageInline stageId={s.id} usage={usage} />}
              {durs?.[s.id] && nowMs !== undefined && (
                <StageDurationInline d={durs[s.id]} vis={vis} nowMs={nowMs} />
              )}
            </span>
          </span>
        )
      })}
    </div>
  )
}

/** 打回横幅：timeline 里 state=rework 的记录逐条列出（新的在前）——
 *  「什么时候打回的、谁打的、理由、打回到哪步」一眼可见，不用去深查区翻流水。 */
function D2Reworks({ detail, wf }: { detail: TicketDetail; wf?: Wf }) {
  const reworks = (detail.timeline ?? []).filter(t => t.state === 'rework')
  if (reworks.length === 0) return null
  const nameOf = (id: string) => wf?.stages.find(s => s.id === id)?.name ?? id
  return (
    <div className="wb-d2-reworks">
      <div className="ttl">⤺ 被打回过 {reworks.length} 次（最新在最上）</div>
      {[...reworks].reverse().map((t, i) => (
        <div className="row" key={i}>
          <span className="when">{fmtAt(t.at)}</span>
          打回到 <span className="tgt">{nameOf(t.stage)}</span>
          {t.reason ? `：${t.reason}` : ''}
        </div>
      ))}
    </div>
  )
}

/** 一句话现状：从 stage_state + timeline + gate_runs 推导，人话回答「现在到哪了」。
 *  t260901-05：并行分叉期活跃步数组多步时改报并行文案（与步骤条双高亮同口径）。 */
function d2StatusLine(detail: TicketDetail, wf?: Wf): { s: D2Visual | 'done'; text: string } {
  if (detail.status === 'closed') {
    const sig = detail.signatures?.merge
    return { s: 'done', text: `已收口关闭${sig ? `（merge 签字人 ${sig.who}）` : ''}` }
  }
  const name = detail.stage_name || detail.stage || '—'
  if (detail.stage_state === 'blocked') {
    const lastBlocked = [...(detail.timeline ?? [])].reverse().find(t => t.state === 'blocked')
    return { s: 'blocked', text: `卡在 ${name}：${lastBlocked?.reason || '原因见下方问题区'}` }
  }
  if (detail.stage_state === 'awaiting-human') {
    const g = detail.gate_runs?.[detail.gate_runs.length - 1]
    return { s: 'awaiting-human', text: `等你审批：${name}${g?.green ? '（merge_check 全绿）' : ''}` }
  }
  if (detail.stage_state === 'running') {
    // 并行分叉：活跃步数组 ≥2 步时统报并行（避免「文字报单步、图上双高亮」分裂）。
    const order = wf?.stages.map(s => s.id) ?? []
    if (order.length > 0) {
      const derived = deriveStageStates(detail, order)
      if (!derived.fallback && derived.active.length > 1) {
        const names = derived.active.map(id => wf!.stages.find(x => x.id === id)?.name ?? id)
        return { s: 'running', text: `并行分叉中：${names.join(' ∥ ')}` }
      }
    }
    const enters = (detail.timeline ?? []).filter(t => t.stage === detail.stage && t.state === 'running').length
    const kb = detail.session_kb ? `，agent 已读 ${detail.session_kb}KB` : ''
    return { s: 'running', text: `${name} 进行中（第 ${enters || 1} 次进本步${kb}）` }
  }
  return { s: 'todo', text: `${name} · ${STATE_LABEL[detail.stage_state] ?? detail.stage_state}` }
}

/** 时长人话：75s → 1分15秒；3700s → 1时1分。 */
function fmtDur(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s < 60) return `${s}秒`
  if (s < 3600) return `${Math.floor(s / 60)}分${s % 60 > 0 ? `${s % 60}秒` : ''}`
  return `${Math.floor(s / 3600)}时${Math.floor((s % 3600) / 60)}分`
}

/** 运行脉搏行（t260825-03）：当前阶段 gen + 本段已运行时长 + 会话日志 KB 及增速 + 心跳年龄。
 *  数据源：detail.pulse（Temporal pending activity 心跳，详情 5s 静默刷新自动带上）
 *  + detail.session_kb（workbench 侧 stat，宿主半 _sessionKbFast）。
 *  软降级：非 running 整行隐藏；running 但无心跳显「无心跳」。疑似卡死（心跳停 >
 *  120s，或 session_kb 停涨 ≥180s 且心跳延迟）红色提示——只显示不动作。 */
function PulseLine({ detail }: { detail: TicketDetail }) {
  // session_kb 增速/停涨判定：记录「kb 最后一次变化的时间 + 较上次的增量」
  // （详情每 5s 静默刷新驱动重渲染；delta=本次 kb − 上次 kb，首次观测为 null）
  const kbChangeRef = useRef<{ id: string; kb: number; ts: number; delta: number | null } | null>(null)
  const kb = typeof detail.session_kb === 'number' && detail.session_kb > 0 ? detail.session_kb : 0
  useEffect(() => {
    if (kb <= 0) return
    const prev = kbChangeRef.current
    if (prev === null || prev.id !== detail.id) {
      kbChangeRef.current = { id: detail.id, kb, ts: Math.floor(Date.now() / 1000), delta: null }
    } else if (prev.kb !== kb) {
      kbChangeRef.current = { id: detail.id, kb, ts: Math.floor(Date.now() / 1000), delta: kb - prev.kb }
    }
  }, [detail.id, kb])
  if (detail.stage_state !== 'running') return null
  const pulse = detail.pulse ?? null
  if (pulse === null) {
    return <div className="wb-pulse" data-s="none">运行脉搏：无心跳（非 agent 段或 worker 不在）</div>
  }
  const now = Math.floor(Date.now() / 1000)
  const hb = pulse.heartbeat ?? {}
  const gen = typeof hb.gen === 'number' ? hb.gen : null
  const hbTs = pulse.last_heartbeat_ts ?? 0
  const hbAge = hbTs > 0 ? Math.max(0, now - hbTs) : null
  const startedTs = pulse.started_ts ?? 0
  const runSec = startedTs > 0
    ? Math.max(0, now - startedTs)
    : (typeof hb.polls === 'number' ? hb.polls * 5 : null)
  const stallSec = kb > 0 && kbChangeRef.current !== null && kbChangeRef.current.id === detail.id
    ? Math.max(0, now - kbChangeRef.current.ts) : 0
  const stuck = (hbAge !== null && hbAge > 120) || (stallSec >= 180 && (hbAge === null || hbAge > 30))
  const warn = !stuck && ((hbAge !== null && hbAge > 30) || stallSec >= 120)
  return (
    <div className="wb-pulse" data-s={stuck ? 'stuck' : (warn ? 'warn' : 'ok')}>
      运行脉搏：{detail.stage_name || detail.stage || pulse.activity || '—'}
      {gen !== null ? ` · 第 ${gen + 1} 次进段（gen${gen}）` : ''}
      {runSec !== null ? ` · 本段已运行 ${fmtDur(runSec)}${startedTs > 0 ? '' : '（按心跳次数推算）'}` : ''}
      {' · 会话日志 '}{kb > 0
        ? `${kb}KB（${stallSec >= 60
          ? `停涨 ${fmtDur(stallSec)}`
          : (kbChangeRef.current !== null && kbChangeRef.current.id === detail.id && kbChangeRef.current.delta !== null
            ? `较上次 ${kbChangeRef.current.delta >= 0 ? '+' : ''}${kbChangeRef.current.delta}KB`
            : '增长中')}）`
        : '—'}
      {hbAge !== null ? ` · 心跳 ${hbAge < 5 ? '刚刚' : `${hbAge} 秒前`}` : ' · 尚无心跳'}
      {pulse.heartbeat_raw !== undefined ? ` · 心跳原文：${pulse.heartbeat_raw.slice(0, 60)}` : ''}
      {stuck ? ' —— 疑似卡死（只提示，不自动处置）' : ''}
    </div>
  )
}

const LIVE_TYPE_LABEL: Record<string, string> = {
  user: '用户',
  assistant: 'agent',
  tool: '工具',
  result: '结果',
  // KI-024（t260903-04）：轮级新鲜度行——静默窗（spawn 引导/LLM 上游重试）里
  // step/start 与 llm/retry 是唯一规律的「还在干活」信号，各出一行防误读停摆。
  step: '轮次',
  retry: '重试',
}

/**
 * 证据图 src 契约（t260831-08，导出供 smoke 断言）：截图只走服务端端点
 * （归档/泳道读取 + 防穿收口 host 一处），不内联 base64（取舍清单 #4：
 * 不带 data: 支持）。encodeURI 级防呆：id/文件名含怪字符时 encodeURIComponent。
 */
export function evidenceImgSrc(ticketId: string, file: string): string {
  return `/sandbar-workbench/api/wf/tickets/${encodeURIComponent(ticketId)}/evidence/${encodeURIComponent(file)}`
}

/** 灯箱键盘键位契约（t260901-13，导出供 smoke 对齐键位，防 handler 与测试漂移）。 */
export const evidenceLightboxKeys = { close: 'Escape', prev: 'ArrowLeft', next: 'ArrowRight' } as const

/**
 * 灯箱下标导航纯函数（t260901-13，导出供 smoke 直测）：index 循环移动 delta，
 * 非法入参（空列表/越界/非整数 delta）一律兜底到安全下标，不抛——灯箱 open 期间
 * evidence 列表被重拉变短时，同一条兜底保证渲染下标始终落在列表内。
 */
export function evidenceNav(files: readonly unknown[], index: number, delta: number): number {
  const n = files.length
  if (n <= 0) return 0
  const i = Number.isInteger(index) && index >= 0 && index < n ? index : 0
  const d = Number.isInteger(delta) ? delta : 0
  return ((i + d) % n + n) % n
}

/** 详情抽屉「截图证据」区（t260831-08）：拉 evidence 列表端点渲染泳道/归档截图。
 *  降级口径：files 空（无泳道/已合并无归档/端点异常）→ 整区不渲染，不报错；
 *  单图加载失败 → 占位人话，不拖垮整区。
 *  灯箱（t260901-13）：缩略图点击 → EvidenceLightbox 遮罩层放大看图。
 *  C1（review 走查结论）：keydown 挂 document 级，方向键在 input/textarea/select/
 *  contentEditable 内触发时忽略（防一边移动光标一边切图），Esc 任何情况都关——
 *  见 evidenceKeyGuard。 */
function isEditableTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT'
    || t.isContentEditable
}

/** 灯箱 lightbox（t260901-13）：点击放大 + 左右按钮/键盘循环切换 + 计数与文件名
 *  + Esc/点遮罩关闭。键盘挂 document 级（fixed 遮罩不可聚焦，绑元素需 autoFocus
 *  抢抽屉焦点；document 级覆盖天然）。所有关闭路径（Esc/点遮罩/切工单/关抽屉）
 *  都收口到「卸载即 useEffect cleanup removeEventListener」单点回收。 */
function EvidenceLightbox({ ticketId, files, index, onClose, onNav: nav }: {
  ticketId: string; files: string[]; index: number; onClose: () => void
  onNav: (files: string[], index: number, delta: number) => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === evidenceLightboxKeys.close) { e.preventDefault(); onClose() }
      else if (e.key === evidenceLightboxKeys.prev && !isEditableTarget(e.target)) {
        e.preventDefault(); nav(files, index, -1)
      } else if (e.key === evidenceLightboxKeys.next && !isEditableTarget(e.target)) {
        e.preventDefault(); nav(files, index, 1)
      }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [files, index, onClose])
  const f = files[index] ?? files[0]
  const [broken, setBroken] = useState(false)
  return (
    <div className="wb-lb" onClick={onClose}>
      {files.length > 1 && (
        <button type="button" className="wb-lb-nav" aria-label="上一张"
          onClick={(e) => { e.stopPropagation(); nav(files, index, -1) }}>‹</button>
      )}
      {broken
        ? <div className="wb-lb-miss">截图加载失败：{f}</div>
        : (
            <img
              className="wb-lb-img"
              alt={`截图证据 ${f}`}
              src={evidenceImgSrc(ticketId, f)}
              onClick={(e) => e.stopPropagation()}
              onError={() => setBroken(true)}
            />
          )}
      {files.length > 1 && (
        <button type="button" className="wb-lb-nav" aria-label="下一张"
          onClick={(e) => { e.stopPropagation(); nav(files, index, 1) }}>›</button>
      )}
      <div className="wb-lb-bar" onClick={(e) => e.stopPropagation()}>
        <span>{files.length > 0 ? `${index + 1} / ${files.length}` : '0 / 0'}</span>
        <span className="wb-lb-name">{f}</span>
        <button type="button" className="wb-lb-close" onClick={onClose}>关闭（Esc）</button>
      </div>
    </div>
  )
}

/** 灯箱导航动作收口（t260901-13）：EvidenceImages 持 open 下标 state，经 setOpen
 *  落 evidenceNav 结果。抽成模块级函数便于 handler 复用与类型收口。 */
function onNav(files: string[], index: number, delta: number, setOpen: (i: number | null) => void): void {
  setOpen(evidenceNav(files, index, delta))
}

function EvidenceImages({ ticketId }: { ticketId: string }) {
  const [files, setFiles] = useState<string[] | null>(null)
  const [broken, setBroken] = useState<Record<string, boolean>>({})
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => {
    let cancelled = false
    setFiles(null)
    setBroken({})
    setOpen(null)
    // KI-057（t260907-11）：走 apiGet——withProject 统一拼 ?project=，证据列表按项目根枚举。
    apiGet(`/sandbar-workbench/api/wf/tickets/${encodeURIComponent(ticketId)}/evidence`)
      .then((d) => {
        if (!cancelled) setFiles(Array.isArray(d?.result?.files) ? (d.result.files as string[]) : [])
      })
      .catch(() => { if (!cancelled) setFiles([]) })
    return () => { cancelled = true }
  }, [ticketId])
  if (files === null || files.length === 0) return null
  return (
    <div className="wb-eimgs">
      <div className="ttl">截图证据</div>
      <div className="wb-eimgs-grid">
        {files.map((f, i) => (
          <figure key={f} className="wb-eimgs-item" role="button" tabIndex={0}
            aria-label={`放大查看 ${f}`}
            onClick={() => setOpen(i)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(i) } }}>
            {broken[f]
              ? <div className="wb-eimgs-miss">截图加载失败：{f}</div>
              : (
                  <img
                    className="wb-eimgs-img"
                    loading="lazy"
                    alt={`截图证据 ${f}`}
                    title={f}
                    src={evidenceImgSrc(ticketId, f)}
                    onError={() => setBroken(b => ({ ...b, [f]: true }))}
                  />
                )}
            <figcaption>{f}</figcaption>
          </figure>
        ))}
      </div>
      {open !== null && (
        <EvidenceLightbox
          ticketId={ticketId}
          files={files}
          index={evidenceNav(files, open, 0)}
          onClose={() => setOpen(null)}
          onNav={(fs, i, d) => onNav(fs, i, d, setOpen)}
        />
      )}
    </div>
  )
}

/** 「实时动态」折叠面板（t260825-03）：泳道会话文件尾 30 条事件流（agent 最近在干什么）。
 *  折叠时不轮询；展开后每 8s 拉一次 agent-live。降级（exists=false）显 reason，不报错。 */
function AgentLivePanel({ ticketId }: { ticketId: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<AgentLiveResult | undefined>(undefined)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!open) return
    let dead = false
    const load = async () => {
      try {
        const r = await apiGet(`${API}/tickets/${encodeURIComponent(ticketId)}/agent-live?n=30`)
        if (dead) return
        if (r?.ok === true) { setData(r.result as AgentLiveResult); setErr('') }
        else setErr(String(r?.error ?? '读取失败'))
      } catch (e) {
        if (!dead) setErr(String(e instanceof Error ? e.message : e))
      }
    }
    void load()
    // t260901-15：展开才轮询 + 不可见页签暂停（visibility 门，回可见立即补刷）。
    const stop = startVisibleInterval(() => { if (!dead) void load() }, 8000)
    return () => { dead = true; stop() }
  }, [open, ticketId])
  return (
    <div className="wb-live">
      <div className="wb-live-head" onClick={() => setOpen(o => !o)}>
        <span className="wb-live-title">{open ? '▾' : '▸'} 实时动态</span>
        {open && data?.exists === true && (
          <span className="wb-live-meta">
            最近 {data.events.length} 条 · 会话 {data.sizeKb ?? 0}KB · 更新于 {fmtTs(data.mtime)} · 每 8s 自动刷新
          </span>
        )}
        {!open && <span className="wb-live-meta">agent 最近动作流（展开后每 8s 自动刷新）</span>}
      </div>
      {open && (
        <div className="wb-live-body">
          {err !== '' && <div className="wb-err">实时动态读取失败：{err}</div>}
          {err === '' && data === undefined && <div className="wb-empty">加载中…</div>}
          {err === '' && data !== undefined && !data.exists && (
            <div className="wb-empty">{data.reason ?? '暂无会话数据'}</div>
          )}
          {err === '' && data !== undefined && data.exists && (
            <>
              {data.events.length === 0 && <div className="wb-empty">{data.reason ?? '暂无可展示事件'}</div>}
              {[...data.events].reverse().map((ev, i) => (
                <div className="wb-live-row" key={`${ev.ts}-${i}`}>
                  <span className="wb-live-ts">{fmtTs(ev.ts)}</span>
                  <span className="wb-live-type" data-t={ev.type}>{LIVE_TYPE_LABEL[ev.type] ?? ev.type}</span>
                  <span className="wb-live-sum">{ev.summary}</span>
                </div>
              ))}
              {data.truncated && <div className="wb-al-trunc">只显示最近 30 条（完整见泳道会话文件）。</div>}
            </>
          )}
        </div>
      )}
    </div>
  )
}

/** 问题区：只在有问题时渲染（blocked / 最近一次 merge_check 红）。数据源=gate_runs+timeline，
 *  这两个字段接口一直返回、旧版前端没用——「有没有问题一目了然」全靠把它们摆上来。 */
function D2Problems({ detail }: { detail: TicketDetail }) {
  if (detail.status === 'closed' || detail.stage_state !== 'blocked') return null
  const rows: ReactNode[] = []
  const lastBlocked = [...(detail.timeline ?? [])].reverse().find(t => t.state === 'blocked')
  const g = detail.gate_runs?.[detail.gate_runs.length - 1]
  if (g && !g.green) {
    for (const c of g.checks.filter(x => !x.green)) {
      rows.push(
        <div className="row" key={c.item}>
          merge_check 红：{c.item}{c.detail ? <span className="dim"> — {c.detail}</span> : null}
        </div>)
    }
  }
  if (rows.length === 0 && lastBlocked?.reason) {
    rows.push(<div className="row" key="why">{lastBlocked.reason}</div>)
  }
  if (rows.length === 0) rows.push(<div className="row" key="w">卡在 {detail.stage_name || detail.stage}，原因未落档</div>)
  return (
    <div className="wb-d2-problems">
      <div className="ttl">⛔ 有问题，需要处置</div>
      {rows}
    </div>
  )
}

/** agent-usage 端点（t260828-07）返回的 token 聚合：in/out/cacheRead 三列 + 按阶段/按模型分账。 */
interface UsageSum { input: number; output: number; cacheRead: number }
interface AgentUsageResult {
  exists: boolean
  files: number
  total: UsageSum
  byStage: Record<string, UsageSum & { models: Record<string, UsageSum> }>
  models: { provider: string; model: string; input: number; output: number; cacheRead: number }[]
  reason?: string
  ws_root?: string
}

/** token 数人话格式：≥1M 显 x.xxM、≥1k 显 x.xk，否则原值（悬停有精确值）。 */
function fmtTok(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k'
  return String(n)
}

function usageSum(s: UsageSum): string {
  return `in ${fmtTok(s.input)} / out ${fmtTok(s.output)}`
}

/** 阶段/整单的模型名串：≥2 个模型才显示（验收口径：多模型才显示模型名），按消耗排序。 */
function usageModelNames(models: { provider: string; model: string }[]): string {
  if (models.length < 2) return ''
  return models.map(m => m.model).filter(Boolean).join('、')
}

/** 某阶段的使用（无该段数据 → null，UI 软降级不渲染数字）。 */
function stageUsage(u: AgentUsageResult | undefined, stageId: string): (UsageSum & { models: Record<string, UsageSum> }) | null {
  if (!u || u.exists !== true) return null
  return u.byStage[stageId] ?? null
}

/** agent 段数：timeline 中 state==='running' 且该段执行主体含 agent 的进段次数（含重入）。 */
function agentSegmentCount(detail: TicketDetail, wf?: Wf): number {
  const agentStages = new Set((wf?.stages ?? []).filter(s => (s.parts ?? []).includes('agent')).map(s => s.id))
  return (detail.timeline ?? []).filter(t => t.state === 'running' && agentStages.has(t.stage)).length
}

/** 悬停一行：阶段 token 明细（cacheRead 收悬停，验收 6）。 */
function stageUsageTitle(s: UsageSum & { models: Record<string, UsageSum> }): string {
  const parts = [`in ${s.input} / out ${s.output} / cacheRead ${s.cacheRead}`]
  const names = Object.keys(s.models)
  if (names.length > 0) parts.push(`模型：${names.join('、')}`)
  return parts.join(' · ')
}

/** token 消耗拉取（t260828-07）：详情抽屉打开时拉一次 agent-usage（不进轮询，克制）。
 *  降级（exists=false，无会话文件/历史已合并单）→ 调用方显「—」，不报错。 */
function useAgentUsage(ticketId: string, enabled: boolean): AgentUsageResult | undefined {
  const [usage, setUsage] = useState<AgentUsageResult | undefined>(undefined)
  useEffect(() => {
    if (!enabled || ticketId === '') return
    let dead = false
    setUsage(undefined)
    ;(async () => {
      try {
        const r = await apiGet(`${API}/tickets/${encodeURIComponent(ticketId)}/agent-usage`)
        if (!dead && r?.ok === true) setUsage(r.result as AgentUsageResult)
      } catch { /* 拉取失败按无数据降级，不弹错 */ }
    })()
    return () => { dead = true }
  }, [enabled, ticketId])
  return usage
}

/** 头部一行合计（验收 3）：agent 段数 + 输入/输出总量 + 模型；cacheRead 收悬停。 */
function UsageSummaryLine({ detail, wf, usage }: { detail: TicketDetail; wf?: Wf; usage: AgentUsageResult | undefined }) {
  if (usage === undefined) {
    if (detail.status === 'closed') return null // 历史已合并单：泳道已清，连「—」都可省
    return <span className="wb-usage" title="token 消耗加载中…">tokens …</span>
  }
  if (!usage.exists) {
    // 历史已合并工单：泳道清理后无会话文件，只有图标没有数字（验收 5，用户拍板不固化）
    if (detail.status === 'closed') return null
    return (
      <span className="wb-usage" data-s="none" title={usage.reason ?? '无会话数据'}>
        tokens —
      </span>
    )
  }
  const segs = agentSegmentCount(detail, wf)
  const names = usageModelNames(usage.models)
  const title = [
    `agent 段数 ${segs}`,
    `in ${usage.total.input} / out ${usage.total.output} / cacheRead ${usage.total.cacheRead}`,
    names !== '' ? `模型：${names}` : `模型：${usage.models[0]?.model ?? '—'}（单模型不显示模型名）`,
    `会话文件 ${usage.files} 份（多角色加总）`,
  ].join(' · ')
  return (
    <span className="wb-usage" title={title}>
      🤖 {segs} 段 · {usageSum(usage.total)}{names !== '' ? ` · ${names}` : ''}
    </span>
  )
}

/** 阶段行内数字（验收 2）：agent 步显 in/out；多模型才追加模型名；cacheRead 收悬停。
 *  无数据（历史单/该段无 usage）→ 不渲染任何数字（只有图标没有数字，验收 5）。 */
function StageUsageInline({ stageId, usage }: { stageId: string; usage: AgentUsageResult | undefined }) {
  const s = stageUsage(usage, stageId)
  if (s === null) return null
  const names = Object.entries(s.models)
    .sort((a, b) => (b[1].input + b[1].output) - (a[1].input + a[1].output))
    .map(([k]) => k.split('/')[1] ?? k)
  const multi = names.length >= 2 ? ` · ${names.join('、')}` : ''
  return (
    <span className="wb-stage-usage" title={stageUsageTitle(s)}>
      {usageSum(s)}{multi}
    </span>
  )
}

/** 快照要点（t260905-07）：ticket show snapshot 直读的四块观测（阶段时间线/最近
 *  交接/门与签字记录/工作流快照要点），纯裁剪零派生语义（snapshotDigest 纯函数层
 *  承担畸形防御与 KI-019 呈现口径——排序归位+缺 at 沉底标注）。时间线只显尾 20 条
 *  （行卡场景无此诉求，详情下钻要「最近的来龙去脉」），交接尾 5 条，门与签字合并
 *  记录表按时间降序。各块带 data-block 锚（3199 隔离台场景断言用）。 */
function D2SnapshotDigest({ detail }: { detail: TicketDetail }) {
  const digest = useMemo(() => snapshotDigest(detail), [detail])
  const { workflow } = digest
  return (
    <details className="wb-d2-snapshot">
      <summary>快照要点（时间线 · 最近交接 · 门与签字 · 工作流快照）</summary>
      <div>
        <div className="wb-dsnap-block" data-wb-digest="workflow">
          <h4>工作流快照要点</h4>
          <div className="wb-dsnap-row">
            <span className="st">工作流</span><span>{workflow.id || '—'}</span>
            <span className="st">当前段</span><span>{workflow.stage || '—'}{workflow.stageState ? ` · ${STATE_LABEL[workflow.stageState] ?? workflow.stageState}` : ''}</span>
            <span className="st">状态</span><span>{workflow.status || '—'}</span>
            <span className="st">修订</span><span>{workflow.revisions === null ? '—' : `${workflow.revisions} 轮`}</span>
            {workflow.worktree && <><span className="st">工作区</span><span data-wb-digest-worktree>{workflow.worktree}</span></>}
          </div>
        </div>
        <div className="wb-dsnap-block" data-wb-digest="timeline">
          <h4>阶段时间线（最近 {digest.timeline.length} 条，按时间正序）</h4>
          {digest.timeline.length === 0
            ? <div className="wb-dsnap-empty">无时间线条目</div>
            : digest.timeline.map((e, i) => (
              <div className="wb-dsnap-row" key={`${e.stage}-${i}`} data-untime={e.untime}
                data-wb-tl-at={e.at ?? ''} data-wb-tl-stage={e.stage} data-wb-tl-state={e.state}>
                <span className="st">{e.stage || '—'}</span>
                <span>{STATE_LABEL[e.state] ?? e.state}</span>
                <span className="at">{e.untime ? "时间缺失" : fmtSnapshotTs(e.at)}</span>
              </div>
            ))}
        </div>
        <div className="wb-dsnap-block" data-wb-digest="handoffs">
          <h4>最近交接（{digest.handoffs.length} 条）</h4>
          {digest.handoffs.length === 0
            ? <div className="wb-dsnap-empty">无交接记录</div>
            : digest.handoffs.map((h, i) => (
              <div className="wb-dsnap-row" key={i}>
                <span>{h.from || '—'} → {h.to || '—'}</span>
                <span className="at">{h.at === null ? "" : fmtSnapshotTs(h.at)}</span>
              </div>
            ))}
        </div>
        <div className="wb-dsnap-block" data-wb-digest="signatures">
          <h4>门与签字记录（{digest.gates.length} 条，最近在前）</h4>
          {digest.gates.length === 0
            ? <div className="wb-dsnap-empty">无门/签字记录</div>
            : digest.gates.map((g, i) => (
              <div className="wb-dsnap-row" key={`${g.kind}-${g.stage}-${i}`}>
                <span className="wb-dsnap-chip" data-kind={g.kind}>{g.kind === 'signature' ? '签字' : '门'}</span>
                <span className="st">{g.stage || '—'}</span>
                <span>{g.who || '—'} · {g.decision || '—'}</span>
                {g.note && <span>{g.note}</span>}
                <span className="at">{g.at === null ? "" : fmtSnapshotTs(g.at)}</span>
              </div>
            ))}
        </div>
      </div>
    </details>
  )
}

/** 进展主体：一步一张卡（状态图标 + 该步产出摘要一句话 + 可展开 evidence/产物）。 */
function D2Stages({ detail, wf, usage, durs, nowMs }: {
  detail: TicketDetail
  wf?: Wf
  usage?: AgentUsageResult
  /** 节点耗时（t260901-12）：与 D2Stepper 同源（父组件一次推导）。 */
  durs?: Record<string, StageDuration>
  nowMs?: number
}) {
  if (!wf || wf.stages.length === 0) return null
  const tl = detail.timeline ?? []
  const handoffs = detail.handoffs ?? []
  const order = wf.stages.map(s => s.id)
  return (
    <div className="wb-d2-stages">
      {wf.stages.map(s => {
        const vis = d2StageVisual(detail, s.id, order)
        const r = detail.results?.[s.id]
        const h = [...handoffs].reverse().find(x => x.stage === s.id)
        const enters = tl.filter(t => t.stage === s.id && t.state === 'running').length
        return (
          <div className="wb-d2-card" data-s={vis} key={s.id}>
            <div className="hd">
              <i className="ico">{D2_ICON[vis]}</i>
              <span className="nm">{s.name}</span> <PartsBadges parts={s.parts} />
              <span className="meta">
                {s.role}{enters > 1 ? ` · 第 ${enters} 次` : ''}{h?.ts ? ` · ${fmtTs(h.ts)}` : ''}
              </span>
              {(s.parts ?? []).includes('agent') && <StageUsageInline stageId={s.id} usage={usage} />}
              {durs?.[s.id] && nowMs !== undefined && (
                <StageDurationInline d={durs[s.id]} vis={vis} nowMs={nowMs} />
              )}
            </div>
            {r?.summary && <div className="sum">{r.summary}</div>}
            {r?.report && (
              <div
                className="wb-md wb-d2-report"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(r.report) }}
              />
            )}
            {r && (r.evidence || (r.files_changed?.length ?? 0) > 0 || (r.deliverables?.length ?? 0) > 0) && (
              <details>
                <summary>明细（evidence / 产物清单）</summary>
                {(r.files_changed?.length ?? 0) > 0 && (
                  <div className="ev">改动文件：{(r.files_changed ?? []).join('、')}</div>)}
                {(r.deliverables?.length ?? 0) > 0 && (
                  <div className="ev">产物：{(r.deliverables ?? []).join('、')}</div>)}
                {r.evidence && <div className="ev">{r.evidence}</div>}
              </details>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------- 操作矩阵 */

/** 按 v0.3 §10 矩阵计算可用操作（accept 内嵌在验收清单逐项打勾，不进操作区）。
 *  行式台面（TicketRow）与详情抽屉（TicketDetail）共用：两者都带 status/stage_state/stage。 */
function availableOps(t: { status: string; stage_state: string; stage: string | null; engine?: string }, wf?: Wf): string[] {
  const s = t.status
  const ss = t.stage_state
  // M11 v2（模版即代码）：自动推进——无 dispatch-next/逐项 accept；人门=签字（advance 钮），
  // blocked=retry_qc 重跑（unblock 钮），任何进行态可 rework 打回；closed 无操作。
  if (t.engine === 'template-as-code-v2') {
    if (s === 'closed') return []
    const v2ops: string[] = []
    if (ss === 'awaiting-human') v2ops.push('advance', 'rework')
    else if (ss === 'blocked') v2ops.push('unblock', 'rework')
    else v2ops.push('rework')
    return v2ops
  }
  const ops: string[] = []
  if (s === 'dispatched') {
    if (ss === 'awaiting' || ss === 'blocked') ops.push('dispatch-next', 'rework')
  } else if (s === 'settled') {
    if (ss === 'awaiting' || ss === 'awaiting-human') ops.push('advance')
    // 审批完整化：awaiting-human 也提供「打回」（理由输入框，note 落审计），不经过 dispatcher。
    if (ss === 'awaiting-human' || ss === 'blocked') ops.push('rework')
  } else if (s === 'verified') {
    if (ss === 'awaiting') ops.push('dispatch-next')
    if (ss === 'awaiting-human') ops.push('advance', 'rework')
  } else if (s === 'rework') {
    if (ss === 'awaiting' || ss === 'blocked') ops.push('dispatch-next')
    if (ss === 'awaiting') ops.push('rework')
    // rework×awaiting-human：打回后重跑到人工审批段的合法态（如後漢書终审）——
    // 矩阵 v0.3 此格原是「—」会锁死，补与 verified 同款的审批/打回两键。
    if (ss === 'awaiting-human') ops.push('advance', 'rework')
  }
  if (ss === 'blocked') ops.push('unblock')
  // 完成：当前 stage 已是末段（模板末段或无 next）且未完成 → 可标记 closed
  const cur = wf?.stages.find(st => st.id === t.stage)
  const isTerminal = t.stage !== null && cur !== undefined && !cur.next
  if (isTerminal && s !== 'closed' && s !== 'rework') ops.push('close')
  return ops
}

/* ------------------------------------------------------- M9 变更页签（PR 式审批台） */

interface DiffOpLine { k: 'ctx' | 'add' | 'del' | 'mod'; a?: string; b?: string }
interface DiffBlock {
  key: string
  type: string
  status: 'added' | 'removed' | 'modified' | 'unchanged'
  summary: string
  level: number
  oldText?: string
  newText?: string
  ops?: DiffOpLine[]
}
interface ReconEntry { path: string; kind: 'added' | 'removed' | 'changed'; before?: string; after?: string }
interface FileDiffEntry {
  path: string
  kind: 'doc' | 'code' | 'data'
  status: 'added' | 'removed' | 'modified'
  blocks?: DiffBlock[]
  unified?: string
  unifiedTruncated?: boolean
  recon?: ReconEntry[]
  reconTruncated?: boolean
  newHash: string
}
interface TicketDiffResult {
  id: string
  base: string
  hasBase: boolean
  /** worktree=泳道工作树 / main=主树 write_set+git log / merged=收口工单 merge commit 回放 / none=给不出。 */
  source: 'worktree' | 'main' | 'merged' | 'none'
  worktree?: string
  changed: boolean
  emptyReason?: string
  files: FileDiffEntry[]
  filesTruncated: boolean
  /** 泳道道被排除的引擎运行时文件数（.dsh/ .suyou/）；没有该计数时不显示。 */
  excludedEngineFiles?: number
}

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

const TYPE_LABEL: Record<string, string> = {
  frontmatter: 'frontmatter', heading: '标题', paragraph: '段落', 'list-item': '列表项',
  'table-head': '表头', 'table-row': '表格行', code: '代码块', quote: '引用', image: '图片', hr: '分隔线',
  doc: '文档', data: '数据', file: '文件',
}
const STATUS_LABEL: Record<string, string> = { added: '新增', removed: '删除', modified: '修改', unchanged: '未变' }
const KIND_LABEL: Record<string, string> = { doc: '文档', code: '代码', data: '数据' }
const CONCLUDE_LABEL: Record<string, string> = {
  approved: 'approved（通过）', 'changes-requested': 'changes-requested（要求修改）', 'in-progress': 'in-progress（审阅中）',
}

/** 审批意见的稳定 key：doc 块=「路径#块key」（块 key 本身含内容哈希）；
 *  code/data 文件=「种类:路径:内容哈希」——内容变 key 失效，旧意见自然「已过期」。 */
function entryKeyOf(file: FileDiffEntry, block?: DiffBlock): string {
  if (block !== undefined) return `${file.path}#${block.key}`
  return `${file.kind}:${file.path}:${file.newHash}`
}

/** 由一轮 review 生成可贴工单的返工指令（reject 意见即返工指令）。 */
function buildReworkInstruction(ticketId: string, round: ReviewRound, roundNo: number): string {
  const rejected = round.blocks.filter(b => b.decision === 'reject')
  const commented = round.blocks.filter(b => b.decision !== 'reject' && b.comment !== undefined && b.comment !== '')
  const lines: string[] = [
    '## 返工指令（PR 式审批 review）',
    '',
    `- 工单：${ticketId}`,
    `- base：${round.base || '（无）'}`,
    `- 整轮结论：${round.conclude}`,
    `- 轮次：第 ${roundNo} 轮 · ${round.reviewer} · ${fmtTs(round.ts)}`,
    `- 落盘：server/dsh/reviews/${ticketId}.json`,
    '',
  ]
  if (rejected.length === 0 && commented.length === 0) {
    lines.push('无驳回项。')
  } else {
    if (rejected.length > 0) {
      lines.push(`### 驳回项清单（${rejected.length}）`, '')
      rejected.forEach((b, i) => {
        lines.push(`${i + 1}. [${TYPE_LABEL[b.type] ?? b.type} / ${STATUS_LABEL[b.status] ?? b.status}] ${b.summary}`)
        if (b.comment !== undefined && b.comment !== '') lines.push(`   - 意见：${b.comment}`)
        lines.push(`   - key：\`${b.block_key}\``)
      })
    }
    if (commented.length > 0) {
      lines.push('', `### 其他意见（${commented.length}）`, '')
      commented.forEach((b, i) => {
        lines.push(`${i + 1}. [${TYPE_LABEL[b.type] ?? b.type}] ${b.summary} —— ${b.comment ?? ''}`)
      })
    }
  }
  return lines.join('\n')
}

/** approve 摘要（随 sign 进不可变事件历史的 note）。 */
function buildApproveSummary(ticketId: string, file: ReviewFile): string {
  const n = file.rounds.length
  if (n === 0) return ''
  const latest = file.rounds[n - 1]
  const a = latest.blocks.filter(b => b.decision === 'approve').length
  const r = latest.blocks.filter(b => b.decision === 'reject').length
  const c = latest.blocks.filter(b => b.comment !== undefined && b.comment !== '').length
  return `审批意见第${n}轮：conclude=${latest.conclude}，块 approve ${a}/reject ${r}/带注释 ${c}（落盘 server/dsh/reviews/${ticketId}.json，reviewer ${latest.reviewer}）`
}

/** 渲染态 block diff 主视图（制式照 knowledge：未变渲染新文本；新增绿；删除红；修改上下红/绿；表格行单元格级对齐）。 */
function DiffBlockBody({ b }: { b: DiffBlock }) {
  if (b.status === 'unchanged') {
    return <div className="wb-d-md wb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.newText ?? '') }} />
  }
  if (b.status === 'added') {
    return <div className="wb-d-md wb-d-md-add wb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.newText ?? '') }} />
  }
  if (b.status === 'removed') {
    return <div className="wb-d-md wb-d-md-del wb-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.oldText ?? '') }} />
  }
  if (b.type === 'table-row') {
    const oc = splitCells(b.oldText ?? '')
    const nc = splitCells(b.newText ?? '')
    const cols = Math.max(oc.length, nc.length)
    return (
      <table className="wb-d-cells">
        <thead><tr><th style={{ width: 40 }}></th>{Array.from({ length: cols }, (_, c) => <th key={c}>列 {c + 1}</th>)}</tr></thead>
        <tbody>
          <tr>
            <th>旧</th>
            {Array.from({ length: cols }, (_, c) => {
              const chg = (oc[c] ?? '') !== (nc[c] ?? '')
              return <td key={c} className={chg ? 'wb-d-cell-old' : ''}>{oc[c] ?? '—'}</td>
            })}
          </tr>
          <tr>
            <th>新</th>
            {Array.from({ length: cols }, (_, c) => {
              const chg = (oc[c] ?? '') !== (nc[c] ?? '')
              return <td key={c} className={chg ? 'wb-d-cell-new' : ''}>{nc[c] ?? '—'}</td>
            })}
          </tr>
        </tbody>
      </table>
    )
  }
  return (
    <>
      <div className="wb-d-md wb-d-md-old wb-md">
        <div className="wb-d-md-tag">旧</div>
        <div dangerouslySetInnerHTML={{ __html: renderMarkdown(b.oldText ?? '') }} />
      </div>
      <div className="wb-d-md wb-d-md-new wb-md">
        <div className="wb-d-md-tag">新</div>
        <div dangerouslySetInnerHTML={{ __html: renderMarkdown(b.newText ?? '') }} />
      </div>
    </>
  )
}

/** unified diff 文本逐行着色（+绿/-红/@@蓝/头行灰）。 */
function UnifiedDiffView({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <div className="wb-d-uni">
      {lines.map((l, i) => {
        const k = l.startsWith('@@') ? 'hunk'
          : l.startsWith('+') ? 'add'
          : l.startsWith('-') ? 'del'
          : (/^(diff |index |--- |\+\+\+ |new file|deleted file)/.test(l) ? 'meta' : 'ctx')
        return <div key={i} className="wb-d-line" data-k={k}>{l === '' ? ' ' : l}</div>
      })}
    </div>
  )
}

/** 数据前后值对账表。 */
function ReconTable({ recon }: { recon: ReconEntry[] }) {
  if (recon.length === 0) return <div className="wb-empty">结构无差异（仅格式/键序变化或无变化）。</div>
  return (
    <table className="wb-d-recon">
      <thead><tr><th>JSON 路径</th><th>旧值</th><th>新值</th><th>变化</th></tr></thead>
      <tbody>
        {recon.map((e, i) => (
          <tr key={i}>
            <td data-k="path">{e.path}</td>
            <td className={e.kind !== 'added' ? 'wb-d-old' : ''}>{e.before ?? '—'}</td>
            <td className={e.kind !== 'removed' ? 'wb-d-new' : ''}>{e.after ?? '—'}</td>
            <td>{e.kind === 'added' ? '新增' : e.kind === 'removed' ? '删除' : '改'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** 一块/一文件的审批意见动作条（approve/reject 切换 + 注释）。 */
function ReviewActions({ rv, onPatch }: {
  rv: BlockReview | undefined
  onPatch: (patch: Partial<BlockReview>) => void
}) {
  const decision = rv?.decision
  return (
    <div className="wb-d-actions">
      <button className={'wb-d-btn wb-d-btn-ap' + (decision === 'approve' ? ' on' : '')}
        onClick={() => onPatch({ decision: decision === 'approve' ? undefined : 'approve' })}>通过</button>
      <button className={'wb-d-btn wb-d-btn-rj' + (decision === 'reject' ? ' on' : '')}
        onClick={() => onPatch({ decision: decision === 'reject' ? undefined : 'reject', open: decision === 'reject' ? rv?.open : true })}>驳回</button>
      <button className="wb-d-btn" onClick={() => onPatch({ open: !(rv?.open ?? false) })}>
        {rv?.open ? '收起注释' : (rv?.comment ? '注释 ✎' : '注释')}
      </button>
      {decision !== undefined && (
        <span className="wb-d-badge" data-s={decision === 'approve' ? 'added' : 'removed'}>
          {decision === 'approve' ? '已通过' : '已驳回'}
        </span>
      )}
      {(rv?.open ?? false) && (
        <textarea className="wb-d-cmt" placeholder="审批意见（驳回块的意见会进返工指令）"
          value={rv?.comment ?? ''} onChange={e => onPatch({ comment: e.target.value })} />
      )}
    </div>
  )
}

/** 「变更」页签本体：diff 展示 + 按块留意见 + 落盘 + 返工指令。 */
/** 构建产物判定：dsh 插件的 lib/ bundle 是编译生成物（minified 巨行 diff 没有审阅价值，
 *  还会把真源码变更埋掉——260824 -03 实测），折叠成组默认收起。 */
function isGenArtifact(path: string): boolean {
  return /^server\/dsh\/[^/]+\/lib\//.test(path)
}

/** unified diff 的 +/− 行数统计（跳过 +++/--- 头行）。 */
function unifiedStats(text: string): { add: number; del: number } {
  let add = 0
  let del = 0
  for (const l of text.split('\n')) {
    if (l.startsWith('+++') || l.startsWith('---')) continue
    if (l.startsWith('+')) add++
    else if (l.startsWith('-')) del++
  }
  return { add, del }
}

function ChangesTab({ detail, operator, onMsg }: {
  detail: TicketDetail
  operator: string
  onMsg: (m: string) => void
}) {
  const [diff, setDiff] = useState<TicketDiffResult | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [reviewFile, setReviewFile] = useState<ReviewFile | undefined>(undefined)
  const [reviews, setReviews] = useState<Record<string, BlockReview>>({})
  const [expired, setExpired] = useState<ReviewBlockEntry[]>([])
  const [conclude, setConclude] = useState<'approved' | 'changes-requested' | 'in-progress'>('in-progress')
  const [saveState, setSaveState] = useState<{ saving?: boolean; runId?: string; error?: string }>({})
  const [reworkMd, setReworkMd] = useState<string | undefined>(undefined)
  const [copied, setCopied] = useState(false)
  const [showUnchanged, setShowUnchanged] = useState(false)

  useEffect(() => {
    let dead = false
    void (async () => {
      setLoading(true)
      setLoadErr('')
      try {
        const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/diff`)
        if (r?.ok !== true) throw new Error(r?.error ?? 'diff 读取失败')
        if (dead) return
        const d = r.result as TicketDiffResult
        setDiff(d)
        // 回填已存审批意见：按 key 回填最近一轮；当前 diff 里已不存在的 key → 「已过期」不回填。
        try {
          const rv = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/review`)
          if (rv?.ok === true && !dead) {
            const file = rv.result as ReviewFile
            setReviewFile(file)
            const latest = file.rounds.length > 0 ? file.rounds[file.rounds.length - 1] : undefined
            if (latest !== undefined) {
              setConclude(latest.conclude)
              const currentKeys = new Set<string>()
              for (const f of d.files) {
                if (f.kind === 'doc') {
                  for (const b of f.blocks ?? []) currentKeys.add(entryKeyOf(f, b))
                }
                currentKeys.add(entryKeyOf(f))
              }
              const backfill: Record<string, BlockReview> = {}
              const stale: ReviewBlockEntry[] = []
              for (const eb of latest.blocks) {
                if (currentKeys.has(eb.block_key)) backfill[eb.block_key] = { decision: eb.decision, comment: eb.comment }
                else stale.push(eb)
              }
              setReviews(backfill)
              setExpired(stale)
            }
          }
        } catch { /* review 读取失败不阻塞 diff 审阅 */ }
      } catch (err) {
        if (!dead) setLoadErr(String(err instanceof Error ? err.message : err))
      } finally {
        if (!dead) setLoading(false)
      }
    })()
    return () => { dead = true }
  }, [detail.id])

  function patchReview(key: string, patch: Partial<BlockReview>): void {
    setReviews(prev => ({ ...prev, [key]: { ...prev[key], ...patch } }))
  }

  /** 保存一轮审批意见（显式落盘），成功后生成返工指令。 */
  async function saveReview(): Promise<void> {
    if (diff === undefined) return
    setSaveState({ saving: true })
    setReworkMd(undefined)
    try {
      const blocks: ReviewBlockEntry[] = []
      for (const f of diff.files) {
        if (f.kind === 'doc') {
          for (const b of (f.blocks ?? []).filter(x => x.status !== 'unchanged')) {
            const key = entryKeyOf(f, b)
            blocks.push({
              block_key: key, summary: `${f.path}：${b.summary}`, type: b.type, status: b.status,
              decision: reviews[key]?.decision, comment: reviews[key]?.comment,
            })
          }
        } else {
          const key = entryKeyOf(f)
          blocks.push({
            block_key: key, summary: f.path, type: f.kind, status: f.status,
            decision: reviews[key]?.decision, comment: reviews[key]?.comment,
          })
        }
      }
      const r = await apiPost(`${API}/tickets/${encodeURIComponent(detail.id)}/review`, {
        base: diff.base, conclude, reviewer: operator, blocks,
      })
      if (r?.ok !== true) throw new Error(r?.error ?? '保存失败')
      const round = r.result?.round as ReviewRound
      const rounds = Number(r.result?.rounds ?? 0)
      setSaveState({ runId: String(r.run_id ?? '') })
      setReviewFile(prev => ({ path: detail.id, rounds: [...(prev?.rounds ?? []), round] }))
      setReworkMd(buildReworkInstruction(detail.id, round, rounds))
      onMsg(`审批意见已落盘（第 ${rounds} 轮，run_id ${String(r.run_id ?? '')}）`)
    } catch (err) {
      setSaveState({ error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function copyText(text: string): Promise<void> {
    setCopied(false)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy'); setCopied(true) } catch { /* 剪贴板不可用 */ }
      document.body.removeChild(ta)
    }
  }

  if (loading) return <div className="wb-empty">变更集计算中（git diff）…</div>
  if (loadErr !== '') return <div className="wb-err">变更加载失败：{loadErr}</div>
  if (diff === undefined) return null

  const latestRound = reviewFile !== undefined && reviewFile.rounds.length > 0
    ? reviewFile.rounds[reviewFile.rounds.length - 1] : undefined
  const summary = {
    doc: diff.files.filter(f => f.kind === 'doc').length,
    code: diff.files.filter(f => f.kind === 'code').length,
    data: diff.files.filter(f => f.kind === 'data').length,
    approved: Object.values(reviews).filter(r => r.decision === 'approve').length,
    rejected: Object.values(reviews).filter(r => r.decision === 'reject').length,
  }
  // 构建产物（lib/ bundle）与真源码分开：产物折叠成组，真变更一眼可见
  const realFiles = diff.files.filter(f => !isGenArtifact(f.path))
  const genFiles = diff.files.filter(f => isGenArtifact(f.path))
  const sourceLabel = diff.source === 'worktree' ? '泳道 worktree vs base'
    : diff.source === 'merged' ? '已合入 main（merge commit 回放）'
    : diff.source === 'main' ? '主树 write_set + git log' : '无来源'

  return (
    <>
      <div className="wb-section">
        <div className="wb-section-title">变更集（{sourceLabel}）</div>
        <div className="wb-d-sum">
          <span>{diff.source === 'merged' ? 'merge' : 'base'}：<code>{diff.base === '' ? '（无）' : diff.base.slice(0, 12)}</code></span>
          {diff.worktree !== undefined && <span>泳道：{shortSlug(diff.worktree)}</span>}
          <span>文件 {diff.files.length}{diff.filesTruncated ? '（超封顶截断）' : ''}（文档 {summary.doc} / 代码 {summary.code} / 数据 {summary.data}）</span>
          {diff.excludedEngineFiles !== undefined && diff.excludedEngineFiles > 0 && (
            <span style={{color: 'var(--dsw-derive-muted,#57606a)'}}>已排除 {diff.excludedEngineFiles} 个引擎运行时文件</span>
          )}
          <span>意见：通过 {summary.approved} / 驳回 {summary.rejected}</span>
          {latestRound !== undefined && (
            <span>已存 {reviewFile!.rounds.length} 轮（最近：{CONCLUDE_LABEL[latestRound.conclude] ?? latestRound.conclude} · {latestRound.reviewer} · {fmtTs(latestRound.ts)}）</span>
          )}
        </div>
        {diff.emptyReason !== undefined && <div className="wb-empty">{diff.emptyReason}</div>}
        {diff.files.length > 0 && (
          <label style={{ fontSize: 12, color: 'var(--dsw-derive-muted,#57606a)' }}>
            <input type="checkbox" checked={showUnchanged} onChange={e => setShowUnchanged(e.target.checked)} /> 显示文档未变块
          </label>
        )}
      </div>

      {realFiles.map(f => (
        <div className="wb-d-file" key={f.path}>
          <div className="wb-d-fhead">
            <span className="wb-d-badge" data-s={f.status}>{STATUS_LABEL[f.status]}</span>
            <span className="wb-d-type">{KIND_LABEL[f.kind]}</span>
            <span className="wb-d-fpath">{f.path}</span>
            {f.kind === 'code' && f.unified !== undefined && (() => {
              const st = unifiedStats(f.unified)
              return <span className="wb-d-stats"><span className="add">+{st.add}</span>{' '}<span className="del">−{st.del}</span></span>
            })()}
          </div>

          {f.kind === 'doc' && (f.blocks ?? [])
            .filter(b => showUnchanged || b.status !== 'unchanged')
            .map(b => {
              const key = entryKeyOf(f, b)
              return (
                <div className="wb-d-block" key={key}>
                  <div className="wb-d-bhead">
                    <span className="wb-d-badge" data-s={b.status}>{STATUS_LABEL[b.status]}</span>
                    <span className="wb-d-type">{TYPE_LABEL[b.type] ?? b.type}</span>
                    <span className="wb-sub">{b.summary}</span>
                  </div>
                  <DiffBlockBody b={b} />
                  {b.status !== 'unchanged' && (
                    <ReviewActions rv={reviews[key]} onPatch={p => patchReview(key, p)} />
                  )}
                </div>
              )
            })}

          {f.kind === 'code' && (
            <>
              {f.unifiedTruncated === true && <div className="wb-d-trunc">diff 超长已截断（完整见泳道 git diff）。</div>}
              <UnifiedDiffView text={f.unified ?? '（无 unified diff）'} />
              <ReviewActions rv={reviews[entryKeyOf(f)]} onPatch={p => patchReview(entryKeyOf(f), p)} />
            </>
          )}

          {f.kind === 'data' && (
            <>
              {f.reconTruncated === true && <div className="wb-d-trunc">对账条目超封顶已截断。</div>}
              <ReconTable recon={f.recon ?? []} />
              <ReviewActions rv={reviews[entryKeyOf(f)]} onPatch={p => patchReview(entryKeyOf(f), p)} />
            </>
          )}
        </div>
      ))}

      {genFiles.length > 0 && (
        <details className="wb-d-gen">
          <summary>构建产物（{genFiles.length} 个）——编译生成的 lib/ bundle，随源码自动重出，一般不用审</summary>
          <div className="wb-d-gen-list">
            {genFiles.map(f => (
              <div className="wb-d-gen-row" key={f.path}>
                <span className="wb-d-badge" data-s={f.status}>{STATUS_LABEL[f.status]}</span>
                <span className="p">{f.path}</span>
                {f.unified !== undefined && (() => {
                  const st = unifiedStats(f.unified)
                  return <span className="wb-d-stats"><span className="add">+{st.add}</span>{' '}<span className="del">−{st.del}</span></span>
                })()}
              </div>
            ))}
          </div>
        </details>
      )}

      {diff.files.length > 0 && (
        <div className="wb-section">
          <div className="wb-section-title">审批意见（落盘 server/dsh/reviews/{detail.id}.json）</div>
          <div className="wb-ops">
            <select className="wb-d-conclude" value={conclude}
              onChange={e => setConclude(e.target.value as typeof conclude)}>
              {(['in-progress', 'approved', 'changes-requested'] as const).map(c =>
                <option key={c} value={c}>{CONCLUDE_LABEL[c]}</option>)}
            </select>
            <button className="wb-btn wb-btn-blue" disabled={saveState.saving === true}
              onClick={() => { void saveReview() }}>
              {saveState.saving === true ? '保存中…' : '保存审批意见（落盘一轮）'}
            </button>
            <button className="wb-btn"
              disabled={reviewFile === undefined || reviewFile.rounds.length === 0}
              title="reject 意见即返工指令，可复制贴进工单/打回理由"
              onClick={() => {
                const file = reviewFile
                if (file === undefined || file.rounds.length === 0) return
                void copyText(buildReworkInstruction(detail.id, file.rounds[file.rounds.length - 1], file.rounds.length))
              }}>
              {copied ? '已复制 ✓' : '复制返工指令'}
            </button>
            {saveState.runId !== undefined && <span className="wb-copied">已落盘 ✓ run_id {saveState.runId}</span>}
            {saveState.error !== undefined && <span className="wb-err">{saveState.error}</span>}
          </div>

          {expired.length > 0 && (
            <div className="wb-d-expired">
              <div style={{ fontWeight: 600, marginBottom: 4 }}>已过期意见（{expired.length}）——块/文件内容已变，key 失效，不回填：</div>
              {expired.map((eb, i) => (
                <div key={i} className="wb-d-expired-item">
                  <span className="wb-d-badge" data-s="expired">已过期</span>{' '}
                  [{TYPE_LABEL[eb.type] ?? eb.type}] {eb.summary}
                  {eb.comment !== undefined && eb.comment !== '' && ` —— ${eb.comment}`}
                </div>
              ))}
            </div>
          )}

          {reworkMd !== undefined && (
            <div className="wb-d-rework">
              <div className="wb-sub">返工指令（随本轮保存生成；reject 块清单，可贴工单）</div>
              <pre>{reworkMd}</pre>
              <div className="wb-ops">
                <button className="wb-btn" onClick={() => { void copyText(reworkMd) }}>{copied ? '已复制 ✓' : '复制'}</button>
                <button className="wb-btn" onClick={() => setReworkMd(undefined)}>收起</button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}

/* -------------------------------------------------------------- 分区本体 */

/* ------------------------------------------------ M12 Agent 日志（详情抽屉页签） */

interface AgentLogFile {
  name: string
  kind: 'log' | 'result'
  stage: string
  gen: number
  size: number
  mtime: number
  content?: string
  contentTruncated?: boolean
  result?: unknown
  parseError?: string
}
interface AgentLogsResult {
  base: string
  exists: boolean
  files: AgentLogFile[]
  truncated: boolean
  reason?: string
  sessionKb: number
  agentAlive: boolean
  lastActivity: string
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`
  return `${(n / 1024 / 1024).toFixed(1)}MB`
}

/** 「Agent」页签：.suyou/ 的 agent_*.log + stage_*.json 按工作流步序分组——
 *  每步一张卡，里面按 gen 列每次尝试（状态+摘要一行，展开看日志/结果/prompt）。
 *  260824 二轮：原来是按文件名字母序平铺（步序丢失、log/result 拆两行），不可用。 */
function AgentLogsTab({ detail, wf, onMsg }: { detail: TicketDetail; wf?: Wf; onMsg: (m: string) => void }) {
  const [logs, setLogs] = useState<AgentLogsResult | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [promptOpen, setPromptOpen] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let dead = false
    void (async () => {
      setLoading(true)
      setLoadErr('')
      try {
        const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/agent-logs`)
        if (r?.ok !== true) throw new Error(r?.error ?? 'agent 日志读取失败')
        if (dead) return
        setLogs(r.result as AgentLogsResult)
        if (r.result?.reason !== undefined && r.result?.reason !== '') onMsg(String(r.result.reason))
      } catch (err) {
        if (!dead) setLoadErr(String(err instanceof Error ? err.message : err))
      } finally {
        if (!dead) setLoading(false)
      }
    })()
    return () => { dead = true }
  }, [detail.id])

  if (loadErr !== '') return <div className="wb-err">agent 日志加载失败：{loadErr}</div>
  if (loading) return <div className="wb-empty">agent 日志加载中…</div>
  if (logs === undefined) return null

  // 分组：stage → 按 gen 的尝试列表（log 与 result 配对成一次尝试）
  interface Attempt { gen: number; log?: AgentLogFile; result?: AgentLogFile }
  const byStage = new Map<string, Attempt[]>()
  for (const f of logs.files) {
    const arr = byStage.get(f.stage) ?? []
    let at = arr.find(a => a.gen === f.gen)
    if (at === undefined) { at = { gen: f.gen }; arr.push(at) }
    if (f.kind === 'log') at.log = f
    else at.result = f
    byStage.set(f.stage, arr)
  }
  const wfOrder = wf?.stages.map(s => s.id) ?? []
  const stageName = (id: string) => wf?.stages.find(s => s.id === id)?.name ?? id
  const stageIds = [...byStage.keys()].sort((a, b) => {
    const ia = wfOrder.indexOf(a)
    const ib = wfOrder.indexOf(b)
    if (ia >= 0 && ib >= 0) return ia - ib
    if (ia >= 0) return -1
    if (ib >= 0) return 1
    return a < b ? -1 : 1
  })
  // 默认展开：最后一步的最新一次尝试（通常就是当前在跑/刚跑完的现场）
  const lastStage = stageIds[stageIds.length - 1]
  const lastGen = lastStage !== undefined
    ? Math.max(...(byStage.get(lastStage) ?? []).map(a => a.gen)) : -1

  return (
    <>
      <div className="wb-section">
        <div className="wb-section-title">agent 日志（.suyou/）</div>
        <div className="wb-al-meta">
          <span className="wb-meta-k">{logs.base}</span>
          {logs.agentAlive && logs.sessionKb > 0 ? (
            <span style={{color: 'var(--dsw-derive-accent,#0969da)'}}>agent 运行中 · 已读 {logs.sessionKb}KB{logs.lastActivity ? ' · ' + logs.lastActivity : ''}</span>
          ) : null}
          {logs.exists ? (
            <span>{logs.files.length} 个文件{logs.truncated ? `（超出封顶，截断显示）` : ''}</span>
          ) : (
            <span>{logs.reason ?? '目录不存在'}</span>
          )}
          <button className="wb-btn" disabled={loading}
            onClick={() => { void (async () => {
              setLoading(true)
              try {
                const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/agent-logs`)
                if (r?.ok === true) { setLogs(r.result as AgentLogsResult); onMsg('已刷新') }
              } finally { setLoading(false) }
            })() }}>
            刷 新
          </button>
        </div>
        {logs.files.length === 0 && (
          <div className="wb-empty">暂无 agent 日志/段结果文件（{logs.reason ?? '目录为空'}）。</div>
        )}
      </div>

      {stageIds.map(stageId => {
        const attempts = (byStage.get(stageId) ?? []).sort((a, b) => a.gen - b.gen)
        const vis = d2StageVisual(detail, stageId, wfOrder)
        const lastMtime = Math.max(0, ...attempts.flatMap(a => [a.log?.mtime ?? 0, a.result?.mtime ?? 0]))
        return (
          <div className="wb-al-stage" key={stageId}>
            <div className="wb-al-shead">
              <i className="ico" style={{ color: D2_COLOR[vis] }}>{D2_ICON[vis]}</i>
              <span className="nm">{stageName(stageId)}</span>
              <span className="meta">{attempts.length} 次尝试{lastMtime > 0 ? ` · 最近 ${fmtTs(lastMtime)}` : ''}</span>
            </div>
            {attempts.map(a => {
              const r = (a.result !== undefined && typeof a.result.result === 'object' && a.result.result !== null)
                ? a.result.result as Record<string, unknown> : undefined
              const status = r !== undefined ? String(r.status ?? 'ok') : '无结算'
              const summary = typeof r?.summary === 'string' ? r.summary : ''
              const pkey = `${stageId}:${a.gen}`
              return (
                <details className="wb-al-attempt" key={a.gen}
                  open={stageId === lastStage && a.gen === lastGen}>
                  <summary>
                    <span className="wb-al-status" data-ok={status !== 'failed'}>{status}</span>
                    <span>第 {a.gen + 1} 次（gen{a.gen}）</span>
                    <span className="wb-al-fmeta">{fmtTs(a.result?.mtime ?? a.log?.mtime ?? 0)}</span>
                    <span className="sum">{summary}</span>
                  </summary>
                  <div className="wb-al-body">
                    {r !== undefined && (
                      <>
                        <div className="wb-al-result-sum">
                          <span><span className="wb-al-result-key">deliverables</span>{' '}
                            {Array.isArray(r.deliverables) ? (r.deliverables as unknown[]).length : '—'}</span>
                          <span><span className="wb-al-result-key">files_changed</span>{' '}
                            {Array.isArray(r.files_changed) ? (r.files_changed as unknown[]).length : '—'}</span>
                          {Array.isArray(r.files_changed) && (r.files_changed as unknown[]).length > 0 && (
                            <span style={{wordBreak: 'break-all'}}>{(r.files_changed as unknown[]).map(String).join('、')}</span>
                          )}
                        </div>
                        {summary !== '' && <div className="wb-al-summ">{summary}</div>}
                        {Array.isArray(r.deliverables) && (r.deliverables as unknown[]).length > 0 && (
                          <div className="wb-al-summ">
                            {((r.deliverables as unknown[]).map(String)).map((d, i) =>
                              <span className="wb-chip" key={i}>{d}</span>)}
                          </div>
                        )}
                        {typeof r.prompt === 'string' && r.prompt !== '' && (
                          <div style={{marginTop: 6}}>
                            <span className="wb-d-btn"
                              onClick={() => setPromptOpen(o => ({ ...o, [pkey]: !o[pkey] }))}>
                              {promptOpen[pkey] ? '收起注入的 prompt ▲' : '查看注入的 prompt ▼'}
                            </span>
                            {promptOpen[pkey] && (
                              <pre className="wb-al-pre" style={{maxHeight: 360, marginTop: 4}}>{r.prompt}</pre>
                            )}
                          </div>
                        )}
                      </>
                    )}
                    {a.result?.parseError !== undefined && (
                      <div className="wb-al-summ">{a.result.parseError}</div>
                    )}
                    {a.log !== undefined && a.log.content !== undefined && a.log.content.trim() !== '' && (
                      <>
                        <div className="wb-al-result-key" style={{padding: '6px 12px 0'}}>agent 输出尾部（{a.log.name}）</div>
                        <pre className="wb-al-pre">{a.log.content}</pre>
                        {a.log.contentTruncated === true && (
                          <div className="wb-al-trunc">内容过长已截断（完整见 泳道 .suyou/{a.log.name}）。</div>
                        )}
                      </>
                    )}
                    {a.result === undefined && a.log === undefined && (
                      <div className="wb-empty">内容读取失败。</div>
                    )}
                  </div>
                </details>
              )
            })}
          </div>
        )
      })}
    </>
  )
}

/** M6「巡检报告」区：读最新 out/scan/<日期>.json 渲染待决工单检查表（只读；点行进详情）。 */
function ScanReportSection({ scan, onOpen }: {
  scan: ScanReportResult | undefined
  onOpen: (id: string) => void
}) {
  const rep = scan?.report
  return (
    <div className="wb-section">
      <div className="wb-section-title">巡 检 报 告</div>
      <div className="wb-scan-meta">
        {rep !== null && rep !== undefined && (
          <>
            <span>生成于 {rep.generated_at}</span>
            <span>报告文件 {scan?.file}</span>
            <span>全量 {rep.total_tickets} 张 · 待决 {rep.pending_decision_count} 张</span>
            <span>卡死阈值 {rep.stuck_threshold_hours}h</span>
            <span className="wb-scan-chips">
              {['疑似卡死', '待补', '可签'].map(k => (
                <span key={k} className="wb-sug" data-sug={k}>{k} {rep.summary?.[k] ?? 0}</span>
              ))}
            </span>
          </>
        )}
        {(rep === null || rep === undefined) && (
          <span>{scan?.reason || '巡检报告加载中…'}</span>
        )}
      </div>
      {rep !== null && rep !== undefined && (
        <>
          {rep.items.length === 0 && (
            <div className="wb-empty">本轮无待决工单（settled/awaiting-human 为零）。</div>
          )}
          {rep.items.length > 0 && (
            <table className="wb-scan-table">
              <thead>
                <tr>
                  <th>工单</th><th>阶段</th><th>停留</th><th>验收</th><th>脚本门</th>
                  <th>pending</th><th>建议</th><th>理由</th>
                </tr>
              </thead>
              <tbody>
                {rep.items.map(it => (
                  <tr key={it.ticket_id} onClick={() => onOpen(it.ticket_id)}
                    title="点开工单详情">
                    <td>
                      <span className="wb-scan-id">{it.ticket_id}</span>
                      <div className="wb-scan-title">{it.title}</div>
                    </td>
                    <td>{it.stage || '—'}<div className="wb-scan-title">{STATE_LABEL[it.stage_state] ?? it.stage_state}</div></td>
                    <td>{it.dwell_hours}h</td>
                    <td>{it.acceptance_total > 0
                      ? `${it.acceptance_done}/${it.acceptance_total}（${Math.round(it.acceptance_done / it.acceptance_total * 100)}%）`
                      : '—'}</td>
                    <td>
                      <span className="wb-dot" data-state={
                        it.gate_green === true ? 'running' : it.gate_green === false ? 'blocked' : 'done'} />
                      <span className="wb-state-text">{it.gate_label || '无记录'}</span>
                    </td>
                    <td>{it.pending_count > 0 ? it.pending_count : '—'}</td>
                    <td><span className="wb-sug" data-sug={it.suggestion}>{it.suggestion}</span></td>
                    <td>
                      <ul className="wb-scan-reasons">
                        {it.reasons.map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="wb-scan-redline">{rep.red_line}</div>
        </>
      )}
    </div>
  )
}

/** 工单列表分页大小（260824 用户拍板⑥）。 */
const PAGE_SIZE = 20

function WorkbenchSection({ focusId, focusNonce, listNonce, projectKey, onOpenEpic }: {
  focusId?: string
  /** 侧栏「又点了一次工单」信号（t260825-05）：同 id 重开（× 关抽屉后再点同一行）也触发。 */
  focusNonce?: number
  /** 侧栏「点工单列表图标回列表」信号（t260825-05）：变化时关详情抽屉回列表页。 */
  listNonce?: number
  projectKey?: string
  /** 所属立项徽标点击（t260826-02）：由侧栏注入，中列切立项单视图并定位代号。 */
  onOpenEpic?: (code: string) => void
}) {
  const [tickets, setTickets] = useState<TicketRow[] | undefined>(undefined)
  const [workflows, setWorkflows] = useState<Wf[]>([])
  const [operator] = useState(operatorOf)
  const [error, setError] = useState('')
  // t260904-17 列表 v5（mock 屏⑤⑥）：筛选 chips=过滤非分组——四态/epic/搜索词。
  const [filterState4, setFilterState4] = useState<TicketState4 | ''>('')
  const [filterEpic, setFilterEpic] = useState('')
  const [q, setQ] = useState('')
  /** 收口折叠（mock ⑥）：缺省折叠成「✓ 收口 · N」计数行。 */
  const [showDone, setShowDone] = useState(false)
  /** 进展行 enrichment（host /tickets/progress 只读）：仅当前可见页逐票拉取（R5 负载预算）。 */
  const [progressMap, setProgressMap] = useState<Record<string, { state: string; text: string }>>({})
  // 无标题票首句映射（t260905-07）：enrichment 通道 title_or_first 的行级缓存。
  const [titleFirstMap, setTitleFirstMap] = useState<Record<string, string>>({})
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TicketDetail | undefined>(undefined)
  const [detailLoading, setDetailLoading] = useState(false)
  const [opBusy, setOpBusy] = useState(false)
  const [opMsg, setOpMsg] = useState('')
  const [promptBox, setPromptBox] = useState<{ role: string; stage: string; prompt: string } | null>(null)
  const [reworkId, setReworkId] = useState<string | null>(null)
  const [reworkHuman, setReworkHuman] = useState(false)
  const [reworkNote, setReworkNote] = useState('')
  const [reworkTo, setReworkTo] = useState('')
  /** KI-004：approve 签字弹层。summary=自动统计摘要（只读，''=无已存审批意见），
   *  epicLine=所属立项确认行（''=不显示）。 */
  const [approveBox, setApproveBox] = useState<{ id: string; summary: string; epicLine: string } | null>(null)
  const [approveRemark, setApproveRemark] = useState('')
  /** approve 摘要 fetch 的请求序号：迟到回调若与当前弹层不同批，丢弃不误写。 */
  const approveSeqRef = useRef(0)
  const [evInput, setEvInput] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState(false)
  const [preview, setPreview] = useState<PreviewData | undefined>(undefined)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [health, setHealth] = useState<TemporalHealth | undefined>(undefined)
  const [drawerTab, setDrawerTab] = useState<'detail' | 'changes' | 'agent'>('detail')
  const [scan, setScan] = useState<ScanReportResult | undefined>(undefined)
  /** 一工单一 worker（260824）：逐 worker 状态，状态条「N workers」点开列全表。 */
  const [workers, setWorkers] = useState<WorkersResult | undefined>(undefined)
  const [workersOpen, setWorkersOpen] = useState(false)
  /** 中列页：tickets=工单列表；scan=巡检报告独立页（260824 用户拍板③）。 */
  const [page, setPage] = useState<'tickets' | 'scan'>('tickets')
  /** 工单列表分页（260824 用户拍板⑥）：筛选/排序变化时重置回第 1 页。 */
  const [pageNo, setPageNo] = useState(1)
  /** token 消耗聚合（t260828-07）：详情抽屉打开时拉一次，头部合计与阶段行内数字共用。 */
  const usage = useAgentUsage(detail?.id ?? '', detail !== undefined)

  /* t260901-15 多页签共存：在场广播（互见 + 写守门 + 写事件刷新）。 */
  /** 本页签 presence 句柄：挂载即建、卸载 stop（effect 清理收口，见下）。 */
  const presenceRef = useRef<TabPresence | null>(null)
  /** selectedId 的 ref 镜像：异步回调（轮询响应/远端写事件）按发起时刻校验，
   *  旧选中工单的在途响应不得覆盖新选中的详情——「点 13 跳回 11」竞态守卫。 */
  const selectedIdRef = useRef<string | null>(null)
  /** 远端页签刚对本页签在看的工单做过写操作 → 顶部黄条（× 关闭，下一条覆盖）。 */
  const [peerNote, setPeerNote] = useState('')
  /** 1s tick：驱动 👀 徽标/在看提示随心跳 TTL 刷新（纯本地渲染，不发请求）。 */
  const [, setViewerTick] = useState(0)
  /** 轮询健康度（KI-003③ 优雅降级，t260903-06）：连续失败计数 + 错误态。
   *  ref 镜像供异步回调读最新值（setState 异步，回调内直读 state 拿旧值）。 */
  const [pollHealth, setPollHealth] = useState<PollHealthState>(INITIAL_POLL_STATE)
  const pollHealthRef = useRef<PollHealthState>(INITIAL_POLL_STATE)
  /** 最近一次轮询失败的摘要（角标 title / 错误条附注；成功即清）。 */
  const [pollLastError, setPollLastError] = useState('')
  /** in-flight 守卫（review C6）：RUNNING 查询退避后最坏 ~27.5s 未归，5s 节拍
   *  若不设守卫会同票并发堆叠——正是 KI-003 登记的「多页签轮询风暴」共犯路径，
   *  本票 UI 段不得放大它。上一发未归 → 跳过本拍。 */
  const listInFlight = useRef(false)
  const detailInFlight = useRef(false)

  /** 健康度转移唯一写入口：ref 与 state 同步；恢复（ok）清错误条。 */
  function applyPollOutcome(outcome: PollOutcome, errMsg = ''): void {
    const next = nextPollState(pollHealthRef.current, outcome)
    pollHealthRef.current = next
    setPollHealth(next)
    setPollLastError(errMsg)
    if (outcome === 'ok') {
      setError('')
    } else if (next.degraded) {
      setError(outcome === 'retryable'
        ? `工单台连续 ${next.failStreak} 次刷新失败，数据可能滞后；已转慢速自动重试，无需手动刷新。最后错误：${errMsg}`
        : `选中工单不可查（不存在或已终态），详见详情区提示；其余工单数据可能滞后。`)
    }
  }

  const wfById = useMemo(() => {
    const m: Record<string, Wf> = {}
    for (const w of workflows) m[w.id] = w
    return m
  }, [workflows])

  /** 台面列表拉取：返回本拍分类供 pollOnce 记账。失败保留上次成功快照
   *  （不清 tickets/workflows——「保持上次成功快照」是本票硬口径）。 */
  async function reloadTickets(): Promise<PollOutcome> {
    listInFlight.current = true
    try {
      const data = await apiGet(`${API}/tickets`)
      if (data?.ok !== true) throw new Error(data?.error ?? '台面加载失败')
      setTickets((data.result?.tickets ?? []) as TicketRow[])
      setWorkflows((data.workflows ?? []) as Wf[])
      return 'ok'
    } catch (err) {
      // 列表聚合口不产出 kind（Temporal 不可达=瞬时故障）：一律 retryable，
      // 绝不让列表失败冒充「工单不存在」（KI-025 口径）。
      return 'retryable'
    } finally {
      listInFlight.current = false
    }
  }

  /** 一拍轮询（健康度唯一入账口）：列表 + 打开中的详情，取最坏分类。
   *  in-flight 守卫在此收口：上一发未归整拍跳过（不记账不叠加）。 */
  async function pollOnce(): Promise<void> {
    if (listInFlight.current || detailInFlight.current) return
    const detailOpen = selectedIdRef.current !== null
    const [listOut, detailOut] = await Promise.all([
      reloadTickets(),
      detailOpen ? refreshDetailSilent() : Promise.resolve('ok' as PollOutcome),
    ])
    const out = worstOutcome(listOut, detailOut)
    applyPollOutcome(out, out === 'ok' ? '' : 'snapshot 查询瞬时失败（阶段切换窗？）')
  }

  /** Temporal server/worker 状态点：读 temporal-health（真实探测，静默失败灰显）。 */
  async function reloadHealth(): Promise<void> {
    try {
      const data = await apiGet(`${API}/temporal-health`)
      if (data?.ok === true) setHealth(data.result as TemporalHealth)
    } catch { /* 静默：接口不可用（headless 无 webServer）时状态点保持灰显 */ }
  }

  /** 一工单一 worker（260824）：/wf/workers 逐 pidfile 探测；接口未挂载（dsh 未重启）时保持 undefined 灰显。 */
  async function reloadWorkers(): Promise<void> {
    try {
      const data = await apiGet(`${API}/workers`)
      if (data?.ok === true) setWorkers(data.result as WorkersResult)
    } catch { /* 静默 */ }
  }

  /** 巡检报告（M6）：读最新 out/scan/<日期>.json；无报告=reason 降级显示，不算错误。 */
  // 多项目化（260823）：项目 key 落模块持有量（apiGet/apiPost 统一拼参）并立即重拉。
  // 声明在初始加载 effect 之前——effect 按声明顺序执行，保证首次 fetch 已带 project。
  useEffect(() => {
    setViewProject(projectKey ?? '')
    setTickets(undefined)
    const vp = getViewProject()
    if (vp) void pollOnce()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectKey])

  // 侧栏联动：左列点工单 → 中栏工单台直接开该工单的详情抽屉。
  // focusNonce 表达「又点了一次」——focusId 同值（× 关抽屉后再点同一行）时也要重开（t260825-05）；
  // openDetail 幂等（重拉详情覆盖旧态），连点无害。
  useEffect(() => {
    if (focusId) void openDetail(focusId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId, focusNonce])

  // 侧栏「工单列表」图标联动（t260825-05）：viewProject/rightView 同值时 setState 跳渲染，
  // 抽屉开态收不到通知——靠 listNonce 变化关抽屉回列表页（scan 巡检页也一并回 tickets）。
  // 跳过挂载首发：Board 重挂载（如从文档视图切回）时 listNonce 已非 0，
  // 不能误关 focusId effect 正要打开的详情。
  const listNonceRef = useRef(listNonce)
  useEffect(() => {
    if (listNonceRef.current === listNonce) return
    listNonceRef.current = listNonce
    setPage('tickets')
    selectedIdRef.current = null
    setSelectedId(null)
    setDetail(undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listNonce])

  // t260901-15 多页签共存：presence 生命周期。挂载建广播（心跳=当前查看的工单），
  // 卸载 stop（定时器/监听全终态回收）；收到远端写事件时——若正看该工单——
  // 黄条提示 + 台面/详情静默刷新（读后失效，不替用户做决定）。
  useEffect(() => {
    const p = startTabPresence(operator)
    presenceRef.current = p
    const unsub = p.onRemoteWrite((w) => {
      if (selectedIdRef.current !== null && w.ticket === selectedIdRef.current) {
        setPeerNote(`工单 ${w.ticket} 刚被另一页签操作过（${w.op} · ${w.who}），已自动刷新`)
        void pollOnce()
      }
    })
    const stopTick = startVisibleInterval(() => { setViewerTick(t => t + 1) }, 1000)
    return () => {
      unsub()
      stopTick()
      p.stop()
      presenceRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operator])

  // selectedId 同步双镜像：presence 心跳跟随抽屉开/关/切换。
  useEffect(() => {
    selectedIdRef.current = selectedId
    presenceRef.current?.setViewingTicket(selectedId)
  }, [selectedId])

  async function reloadScan(): Promise<void> {
    try {
      const data = await apiGet(`${API}/scan-report`)
      if (data?.ok === true) setScan(data.result as ScanReportResult)
    } catch { /* 静默：接口不可用时巡检区保持「加载中」 */ }
  }

  async function openDetail(id: string): Promise<void> {
    // 同步置 ref：fetch 响应可能先于 React passive effect（effect 里也同步一次兜底）
    // 落地，晚同步会让首次点行的响应被跳单守卫误丢。
    selectedIdRef.current = id
    setSelectedId(id)
    setDrawerTab('detail')
    setDetailLoading(true)
    setOpMsg('')
    try {
      const data = await apiGet(`${API}/tickets/${encodeURIComponent(id)}`)
      if (data?.ok !== true) {
        // KI-025：错误体带 kind（分级产出贯穿 host 503/410/404 分流）——致命类
        // 精确报「不存在/已终态」，瞬时类引导「自动重试中」而非手动刷新。
        const e = new Error(data?.error ?? '详情加载失败') as Error & { kind?: unknown }
        e.kind = data?.kind
        throw e
      }
      // t260901-15 跳单守卫：响应到达时若用户已改看别单，丢弃过期结果（防「点 13 跳 11」）。
      if (selectedIdRef.current !== id) return
      setDetail(data.result as TicketDetail)
    } catch (err) {
      if (selectedIdRef.current === id) {
        const kind = (err as { kind?: unknown } | null)?.kind
        if (kind === 'not_found') {
          setOpMsg(`工单不存在：${id}（Temporal 无此 workflow）`)
        } else if (kind === 'terminal') {
          setOpMsg(String(err instanceof Error ? err.message : err))
        } else {
          // 瞬时故障（超时/连接/取消）：不弹窗打断——保留占位提示，轮询自动补拉。
          setOpMsg(`详情加载失败（查询瞬时故障），自动重试中：${String(err instanceof Error ? err.message : err)}`)
        }
      }
    } finally {
      if (selectedIdRef.current === id) setDetailLoading(false)
    }
  }

  /** t260901-15 写前守门：远端页签守门窗口内写过该工单、或正有其它页签在看 →
   *  confirm 二次确认（管理台宁提醒不强禁，写后广播兑现读后失效）。返回 true=可继续写。
   *  在场通道不可用（presenceRef=null）→ 退化为旧行为不阻断，降级写明不静默。 */
  function peerWriteAllowed(id: string, op: string): boolean {
    const p = presenceRef.current
    if (p === null) return true
    const hit = p.recentRemoteWrite(id)
    const viewers = p.viewersOf(id)
    if (hit === undefined && viewers.length === 0) return true
    const lines: string[] = []
    if (hit !== undefined) {
      lines.push(`另一页签 ${hit.who} ${Math.max(1, Math.round(hit.ageMs / 1000))}s 前刚对该工单执行过「${hit.op}」`)
    }
    if (viewers.length > 0) {
      lines.push(`另一页签正在查看此工单（${viewers.map(v => v.who).join('、')}）`)
    }
    return window.confirm(`确认继续对工单 ${id} 执行「${op}」？\n${lines.join('\n')}`)
  }

  async function doOp(id: string, op: string, args: unknown, msgOk: string): Promise<void> {
    if (!peerWriteAllowed(id, op)) {
      setOpMsg('已取消：另一页签刚操作过该工单')
      return
    }
    setOpBusy(true)
    setOpMsg('')
    try {
      const data = await apiPost(`${API}/tickets/${encodeURIComponent(id)}/${op}`, args)
      if (data?.ok !== true) {
        setOpMsg(`失败：${data?.error ?? '未知错误'}${data?.run_id ? `（run_id ${data.run_id}）` : ''}`)
        return
      }
      const result = data.result
      if (op === 'dispatch-next') {
        setPromptBox({ role: result?.role ?? '', stage: result?.stage ?? '', prompt: result?.prompt ?? '' })
      }
      setOpMsg(msgOk + (data.run_id ? `（run_id ${data.run_id}）` : ''))
      // t260901-15：写成功后广播写事件——其它页签收到即刷新 + 黄条（写前守门据此二次确认）。
      presenceRef.current?.notifyWrite(id, op)
      // 列表必刷；若该行详情已打开（selectedId===id）同步刷详情。
      await Promise.all([reloadTickets(), ...(id === selectedId ? [openDetail(id)] : [])])
    } catch (err) {
      setOpMsg(`操作失败：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setOpBusy(false)
    }
  }

  function doAccept(item: string, done: boolean): void {
    if (!selectedId) return
    const evidence = (evInput[item] ?? '').trim()
    void doOp(selectedId, 'accept', { item, done, by: operator, ...(evidence ? { evidence } : {}) },
      done ? `验收项已打勾：${item.slice(0, 24)}` : `已取消打勾：${item.slice(0, 24)}`)
  }

  /** 读工单审批意见（server/dsh/reviews/<id>.json；没有=undefined，不报错）。 */
  async function fetchReviewFile(id: string): Promise<ReviewFile | undefined> {
    try {
      const r = await apiGet(`${API}/tickets/${encodeURIComponent(id)}/review`)
      if (r?.ok === true) return r.result as ReviewFile
    } catch { /* 静默：无 review 不阻塞签字 */ }
    return undefined
  }

  function doAdvance(id: string, stageState: string, epic?: string): void {
    // 待审批（awaiting-human）走签字：approve=审批放行推进，不再调 advance（引擎对人工审批段只认签字）。
    // M9 签字联动：approve 摘要随 sign 进不可变事件历史（note 带最近一轮 review 统计）。
    // t260826-02 签字确认区「所属立项」（review M1）：epic 由调用方按当前工单现传
    // （列表行=t.epic / 抽屉=detail.epic，不用 detail 兜底——行触发时 detail 可能是别人，
    // 错单 epic 进人审门不可接受）；「有则显示无则略」——无 epic 不输出该行（「未归档」
    // 字样只留在徽标场景，不进签字确认区）。
    if (stageState === 'awaiting-human') {
      const code = (epic ?? '').trim()
      const epicLine = code !== '' ? `所属立项: ${code}` : ''
      // KI-004：先 await 摘要再开弹层（与现状 confirm 前 await 的时序一致，无空态）；
      // 请求序号守卫迟到回调——弹层已取消/换单时不把旧摘要写进来；
      // fetch 失败（fetchReviewFile 静默返回 undefined）照开弹层，摘要位走「无统计摘要」文案，
      // 不阻塞签字（与现状 file===undefined → note='' 直接 confirm 的口径一致）。
      const seq = ++approveSeqRef.current
      void (async () => {
        const file = await fetchReviewFile(id)
        if (approveSeqRef.current !== seq) return
        const summary = file !== undefined ? buildApproveSummary(id, file) : ''
        setApproveBox({ id, summary, epicLine })
        setApproveRemark('')
      })()
      return
    }
    void doOp(id, 'advance', {}, '已推进到下一阶段')
  }

  function doSign(id: string, decision: string, note: string): void {
    void doOp(id, 'sign', { decision, note, who: operator },
      decision === 'approve' ? '已审批通过并推进' : '已打回（sign reject）')
  }

  /** KI-004 approve 弹层确认：同 doRework 口径——先复位弹层 state 再签字，
   *  失败信息由 doOp 的 setOpMsg 外露；buildApproveNote 兜底 remark 可空。 */
  function doApprove(): void {
    if (!approveBox) return
    const { id, summary } = approveBox
    const note = buildApproveNote(summary, approveRemark)
    setApproveBox(null)
    setApproveRemark('')
    doSign(id, 'approve', note)
  }

  /** KI-004 approve 弹层取消：四路径（确认/取消/Esc 外点/换单重开）统一走这里复位。 */
  function closeApprove(): void {
    approveSeqRef.current++ // 使在途的迟到 fetch 回调失效，不复活旧弹层
    setApproveBox(null)
    setApproveRemark('')
  }

  /** 打开打回弹层。M9 签字联动：有已存审批意见且含驳回/注释时，自动把返工指令填进理由框（可改）。 */
  function openRework(id: string, human: boolean): void {
    setReworkId(id)
    setReworkHuman(human)
    setOpMsg('')
    void (async () => {
      const file = await fetchReviewFile(id)
      if (file === undefined || file.rounds.length === 0) return
      const latest = file.rounds[file.rounds.length - 1]
      const hasIssues = latest.blocks.some(b => b.decision === 'reject' || (b.comment ?? '') !== '')
      if (hasIssues) {
        setReworkNote(prev => prev === '' ? buildReworkInstruction(id, latest, file.rounds.length) : prev)
      }
    })()
  }

  function doRework(): void {
    if (!reworkId) return
    if (reworkNote.trim() === '') {
      setOpMsg('需要填写返工理由')
      return
    }
    if (reworkHuman) {
      // 待审批工单打回 = sign reject（理由 note 进事件历史）。
      void doSign(reworkId, 'reject', reworkNote)
    } else {
      void doOp(reworkId, 'rework', { note: reworkNote, ...(reworkTo ? { to_stage: reworkTo } : {}) }, '已打回')
    }
    setReworkNote('')
    setReworkTo('')
    setReworkId(null)
    setReworkHuman(false)
  }

  async function copyPrompt(text: string): Promise<void> {
    setCopied(false)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy'); setCopied(true) } catch { /* 剪贴板不可用 */ }
      document.body.removeChild(ta)
    }
  }

  /** 内容预览（按工单 book_path 定位，审批前过目）：只读 book API，前若干章；无 book_path 不显示入口。 */
  async function openPreview(): Promise<void> {
    if (!detail?.book_path) return
    setPreviewLoading(true)
    setOpMsg('')
    try {
      const data = await apiGet(`${API}/book?path=${encodeURIComponent(detail.book_path)}&limit=5`)
      if (data?.ok !== true) {
        setOpMsg(`预览失败：${data?.error ?? '未知错误'}`)
        return
      }
      setPreview(data.result as PreviewData)
    } catch (err) {
      setOpMsg(`预览失败：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setPreviewLoading(false)
    }
  }

  /** 详情静默刷新（自动轮询用，不置 loading 不闪屏）。t260901-15 跳单守卫：
   *  按发起时刻的 id 校验——响应到达时选中已变则丢弃（旧代码无条件 setDetail 是
   *  「点 13 详情跳回 11」的竞态根因）。t260903-06：返回本拍分类供 pollOnce 记账；
   *  失败保留上次成功快照（不清 detail）；致命类（不存在/终态）在详情区精确提示。 */
  async function refreshDetailSilent(): Promise<PollOutcome> {
    const id = selectedIdRef.current
    if (!id) return 'ok'
    detailInFlight.current = true
    try {
      const data = await apiGet(`${API}/tickets/${encodeURIComponent(id)}`)
      if (data?.ok === true) {
        if (selectedIdRef.current === id) setDetail(data.result as TicketDetail)
        return 'ok'
      }
      const out = classifyPollBody(data)
      if (out !== 'retryable' && selectedIdRef.current === id) {
        setOpMsg(String(data?.error ?? '工单查询失败'))
      }
      return out
    } catch {
      // 网络异常=瞬时：静默保留快照，下一拍自动重试（不弹窗不打断）。
      return 'retryable'
    } finally {
      detailInFlight.current = false
    }
  }

  // 台面自动刷新：5s 轮询（列表+打开中的详情，最坏分类记账）；降级态退 30s 慢轮询
  // （错误态下降低查询通道打击面，恢复探测仍持续——pollMs 变化=重建 interval，
  // React 先跑旧 effect cleanup 再跑新 effect，startVisibleInterval 停表幂等，
  // 终态回收不漏）。t260901-15：不可见页签暂停轮询（visibility 门）。
  // t260903-06 C6：节拍内并发由 pollOnce 的 in-flight 守卫收口（未归跳拍）。
  const pollMs = pollHealth.degraded ? 30_000 : 5_000
  useEffect(() => {
    const stop = startVisibleInterval(() => { void pollOnce() }, pollMs)
    return stop
    // pollOnce 只经 ref/setter 访问组件态，不进 deps；selectedId/pollMs 变化即重建。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, pollMs])

  useEffect(() => { void pollOnce() }, [])

  // Temporal 状态点 + worker 清单：5s 轮询（与台面同节奏，独立于详情选中态）。
  // t260901-15：visibility 门——不可见页签暂停轮询。
  useEffect(() => {
    void reloadHealth()
    void reloadWorkers()
    return startVisibleInterval(() => { void reloadHealth(); void reloadWorkers() }, 5000)
  }, [])

  // 巡检报告：30s 轮询（报告本身按 schedule 45min 才变，30s 足够跟手）。
  // t260901-15：visibility 门——不可见页签暂停轮询。
  useEffect(() => {
    void reloadScan()
    return startVisibleInterval(() => { void reloadScan() }, 30000)
  }, [])

  // t260904-17 列表 v5：过滤/计数/分组全部走纯函数模型层（与行卡同源，单点口径）。
  const filtered = useMemo(() => filterRows(tickets ?? [], {
    state: filterState4 || undefined, epic: filterEpic || undefined, q,
  }), [tickets, filterState4, filterEpic, q])
  const stateCounts = useMemo(() => countByState(tickets ?? []), [tickets])
  const epicList = useMemo(() => {
    const m = new Map<string, number>()
    for (const t of tickets ?? []) { const e = t.epic || ''; if (e) m.set(e, (m.get(e) ?? 0) + 1) }
    return [...m.entries()].map(([code, count]) => ({ code, count })).sort((a, b) => b.count - a.count)
  }, [tickets])

  // 排序缺省=最近活动（t260904-17，mock ⑥ 通用口径；旧缺省=created 倒序，切键在此声明）。
  const [sortKey, setSortKey] = useState<'created' | 'updated'>('updated')
  const [sortAsc, setSortAsc] = useState(false)
  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    const va = (sortKey === 'created' ? a.created : a.updated_ts) ?? 0
    const vb = (sortKey === 'created' ? b.created : b.updated_ts) ?? 0
    return sortAsc ? va - vb : vb - va
  }), [filtered, sortKey, sortAsc])

  // 收口折叠（mock ⑥）：收口票折成计数行，展开才铺卡；分页只算未收口票。
  const openList = useMemo(() => sorted.filter(t => deriveTicketState(t.status, t.stage_state) !== 'done'), [sorted])
  const doneList = useMemo(() => sorted.filter(t => deriveTicketState(t.status, t.stage_state) === 'done'), [sorted])

  // 分页（260824 用户拍板⑥）：筛选/排序一变回第 1 页。
  const pageCount = Math.max(1, Math.ceil(openList.length / PAGE_SIZE))
  const paged = useMemo(() => openList.slice((pageNo - 1) * PAGE_SIZE, pageNo * PAGE_SIZE), [openList, pageNo])
  useEffect(() => { setPageNo(1) }, [filterState4, filterEpic, q, sortKey, sortAsc])

  // 进展行 enrichment（t260904-17）：只拉当前可见页的非收口票（R5 负载预算=可见页×
  // 单票一次/轮询周期）；host 契约=?enrich=progress（主列表零 show，show 只在此阶段）。
  // 失败/缺数据=该票行卡降级只显相对时间，不重试不打错条。
  useEffect(() => {
    const ids = paged.filter(t => deriveTicketState(t.status, t.stage_state) !== 'done').map(t => t.id)
    if (ids.length === 0) return
    let alive = true
    apiGet(`${API}/tickets?project=${encodeURIComponent(projectKey ?? '')}`
      + `&enrich=progress&ids=${encodeURIComponent(ids.join(','))}`)
      .then((data) => {
        if (!alive || data?.ok !== true) return
        const rows = (data.result?.tickets ?? []) as { id: string; progress?: { stage: string; state: string; at?: unknown }; title_or_first?: string }[]
        const next: Record<string, { state: string; text: string }> = {}
        const firsts: Record<string, string> = {}
        for (const r of rows) {
          // 无标题票首句（t260905-07）：enrichment 顺带下发，行卡展示选择函数消费
          if (r?.title_or_first) firsts[r.id] = r.title_or_first
          if (!r?.progress) continue
          const line = progressLineOf([r.progress])
          if (line) next[r.id] = line
        }
        setTitleFirstMap(firsts)
        setProgressMap(next)
      })
      .catch(() => { /* 静默降级 */ })
    return () => { alive = false }
  }, [tickets, pageNo, projectKey])

  // 短序号（时序可见）：按 created 升序编号 #01、#02…，显示在 id 列（悬停 title 显示完整 id）。
  const selWf = detail ? wfById[detail.workflow_id] : undefined
  /** 节点耗时（t260901-12）：泳道图步骤条与阶段卡共用，一次推导两处传参。 */
  const stageDurs = useStageDurations(detail, selWf)
  const detailWs = workspaceInfoOf(detail)
  const instItems = detail?.acceptance?.length ? detail.acceptance
    : (detail?.stage_acceptance?.length ? detail.stage_acceptance : [])
  const curChecks = detail?.checks?.[detail?.stage ?? ''] ?? []
  const ops = detail ? availableOps(detail, selWf) : []
  const reworkStages = selWf?.stages.map(s => s.id) ?? []

  // t260901-15 多页签共存：其它页签正在看的工单映射（presence 心跳 TTL 驱动，
  // viewerTick 1s 刷新渲染；纯本地读，不发请求）。
  const peerViewersByTicket = new Map<string, PeerViewer[]>()
  if (presenceRef.current !== null) {
    for (const t of tickets ?? []) {
      const v = presenceRef.current.viewersOf(t.id)
      if (v.length > 0) peerViewersByTicket.set(t.id, v)
    }
  }
  const drawerPeerViewers = selectedId !== null
    ? (presenceRef.current?.viewersOf(selectedId) ?? []) : []

  if (!projectKey) {
    return (
      <div className="wb-root">
        <div style={{ padding: 32, color: 'var(--dsw-alias-label-secondary, #888)', fontSize: 13 }}>
          从左侧项目行点工单列表图标打开该项目的工单台。
        </div>
      </div>
    )
  }

  return (
    <div className="wb-root">
      <div className="wb-head">
        <span className="wb-title">工 单 台</span>
        <span className="wb-head-spacer" />
        <span className="wb-health">
          <a className="wb-health-link" href="http://127.0.0.1:8233" target="_blank" rel="noreferrer"
            title="打开 Temporal 控制台（http://127.0.0.1:8233）">
            <span className="wb-health-item" data-online={health?.server.online ?? false}
              title={health
                ? `server · ${health.server.detail}${health.server.online ? '' : `\n重启：${health.restart_hint.server}`}`
                : 'temporal server 状态探测中…'}>
              <span className="wb-health-dot" data-online={health?.server.online ?? false} />Temporal 控制台 ↗
            </span>
          </a>
          <button className="wb-status-btn" data-open={workersOpen}
            data-online={workers === undefined ? undefined : workers.count_alive > 0}
            title={workers
              ? `worker ${workers.count_alive}/${workers.count} 在线 · 点开看逐 worker 状态`
              : 'worker 清单接口未挂载（需重启 dsh 后生效）'}
            onClick={() => { if (!workersOpen) void reloadWorkers(); setWorkersOpen(!workersOpen) }}>
            {workers ? `${workers.count_alive} workers` : '— workers'}
          </button>
          <button className="wb-status-btn" data-open={page === 'scan'}
            data-online={scan?.report ? scan.report.pending_decision_count === 0 : undefined}
            title={scan?.report
              ? `巡检报告 · 待决 ${scan.report.pending_decision_count} 张 · 点开看全表`
              : (scan?.reason ?? '巡检报告加载中…')}
            onClick={() => setPage(page === 'scan' ? 'tickets' : 'scan')}>
            巡检{scan?.report ? ` ${scan.report.pending_decision_count}` : ''}
          </button>
        </span>
        {workersOpen && (
          <div className="wb-workers-panel">
            <div className="wb-workers-head">
              worker 清单{workers ? ` · ${workers.count_alive}/${workers.count} 在线` : ''}
            </div>
            {workers === undefined && <div className="wb-empty">接口未挂载（需重启 dsh 后生效）。</div>}
            {workers !== undefined && workers.workers.length === 0 && (
              <div className="wb-empty">没有 worker pidfile。</div>
            )}
            {workers !== undefined && workers.workers.length > 0 && (
              <table className="wb-workers-table">
                <thead>
                  <tr><th>队列</th><th>工单</th><th>pid</th><th>状态</th><th>日志时间</th></tr>
                </thead>
                <tbody>
                  {workers.workers.map(w => (
                    <tr key={w.queue} data-offline={!w.online}>
                      <td className="wb-id">{w.queue}</td>
                      <td>{w.ticket ?? '（共享池）'}</td>
                      <td>{w.pid ?? '—'}</td>
                      <td>
                        <span className="wb-health-dot" data-online={w.online} />
                        {w.online ? ' 在线' : ' 离线'}
                      </td>
                      <td>{w.log_mtime ? new Date(w.log_mtime * 1000).toLocaleString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {health !== undefined && !health.server.online && (
        <div className="wb-health-offline">
          <span>Temporal server 离线（{health.server.detail}）→ {health.restart_hint.server}</span>
        </div>
      )}
      {workers !== undefined && workers.count > 0 && workers.count_alive === 0 && (
        <div className="wb-health-offline">
          <span>所有 worker 离线（{workers.count} 个 pidfile 均不存活）→ {health?.restart_hint.worker ?? '重启 worker'}</span>
        </div>
      )}

      {error !== '' && <div className="wb-err">{error}{'\n'}（工单台 API 未挂载？headless profile 无 webServer。）</div>}

      {page === 'tickets' && (<>
      <div className="wb-filters">
        {/* 状态 chips=过滤非分组（t260904-17，mock J）：四态+计数；「等你」chip 恒显，>0 强调 */}
        {(['waiting', 'blocked', 'active', 'done'] as TicketState4[]).map(s => (
          <button key={s} className="wb-chip-btn" data-state={s} data-on={filterState4 === s}
            onClick={() => setFilterState4(filterState4 === s ? '' : s)}>
            {STATE4_LABEL[s]} {stateCounts[s]}
          </button>
        ))}
        <button className="wb-chip-btn" data-on={filterState4 === ''}
          onClick={() => setFilterState4('')}>全部 {tickets?.length ?? 0}</button>
        {epicList.length > 0 && <span className="wb-sub">epic：</span>}
        {epicList.map(e => (
          <button key={e.code} className="wb-chip-btn wb-chip-epic" data-on={filterEpic === e.code}
            style={{ borderColor: epicColorOf(e.code), ...({ '--epic-c': epicColorOf(e.code) } as React.CSSProperties), color: epicChipColor() }}
            title={`按立项 ${e.code} 过滤`}
            onClick={() => setFilterEpic(filterEpic === e.code ? '' : e.code)}>
            {e.code} ·{e.count}
          </button>
        ))}
        <input className="wb-search" type="search" placeholder="搜索 id / 标题…" value={q}
          onChange={e => setQ(e.target.value)} />
        <select className="wb-select" value={sortKey} onChange={e => setSortKey(e.target.value as 'created' | 'updated')}>
          <option value="updated">最近活动 ↓</option>
          <option value="created">创建时间 ↓</option>
        </select>
        <button className="wb-btn" onClick={() => { void pollOnce() }}>刷 新</button>
        {/* KI-003③（t260903-06）：轮询失败不弹窗——静默重试期间保留上次成功快照，
            角标提示「数据可能滞后」；连续 3 次失败才升错误条（见上方 wb-err）。 */}
        {pollHealth.failStreak > 0 && !pollHealth.degraded && (
          <span
            className="wb-sub"
            title={pollLastError || '上次刷新失败，当前展示的是上次成功快照，正在自动重试'}
          >
            ⟳ 数据可能滞后（自动重试中）
          </span>
        )}
        <span className="wb-sub">{openList.length + doneList.length}/{tickets?.length ?? 0} 张</span>
      </div>

      {/* 平铺行卡列表（t260904-17，mock ⑥）：状态配色不分组、epic 彩条、迷你站道、衍生动作位 */}
      {paged.map(t => {
        const ops = availableOps(t, wfById[t.workflow]) as CardOp[]
        return (
          <TicketRowCard key={t.id} t={{ ...t, title_or_first: t.title_or_first ?? titleFirstMap[t.id] }} wf={wfById[t.workflow]}
            progress={progressMap[t.id]}
            active={t.id === selectedId} busy={opBusy} ops={ops}
            peerViewers={peerViewersByTicket.get(t.id)}
            onOpen={(anchor) => {
              // 衍生动作位=纯导航（R3）：去签字→详情「变更」页签（审批必看 diff 区，本票落点）；
              // 看原因→详情「进展」页签（问题区/阻塞原因）。零写操作。
              if (anchor === 'review') setDrawerTab('changes')
              if (anchor === 'blocked' || anchor === undefined) setDrawerTab('detail')
              void openDetail(t.id)
            }}
            onAdvance={() => { doAdvance(t.id, t.stage_state, t.epic) }}
            onDispatch={() => { void doOp(t.id, 'dispatch-next', {}, '已生成派活指令') }}
            onRework={() => { openRework(t.id, t.stage_state === 'awaiting-human') }}
            onUnblock={() => {
              if (t.engine === 'template-as-code-v2') {
                void doOp(t.id, 'retry-qc', { who: operator }, '已请求重跑（retry_qc）')
              } else {
                void doOp(t.id, 'update', { stage_state: 'awaiting', note: '（工单台）解除阻塞' }, '已解除阻塞')
              }
            }}
            onClose={() => { if (window.confirm('标记为已完成（closed）？')) void doOp(t.id, 'update', { status: 'closed', note: '（工单台）完成' }, '已标记完成') }}
            onOpenEpic={onOpenEpic} />
        )
      })}
      {paged.length === 0 && openList.length === 0 && (
        <div className="wb-empty">没有符合筛选的工单。</div>
      )}

      {/* 收口折叠计数行（mock ⑥）：数据覆盖面以 /wf/tickets 返回集为准（KI-031 注记：
          terminate/直并收口票不在列表数据宇宙，计数偏小非折叠逻辑丢票） */}
      {doneList.length > 0 && (
        showDone ? (
          <>
            <button className="wb-done-row" onClick={() => setShowDone(false)}>▾ 收口 · {doneList.length}（点击折叠）</button>
            {doneList.map(t => (
              <TicketRowCard key={t.id} t={{ ...t, title_or_first: t.title_or_first ?? titleFirstMap[t.id] }} wf={wfById[t.workflow]} compact={false}
                active={t.id === selectedId} busy={opBusy} ops={[]}
                onOpen={() => { setDrawerTab('detail'); void openDetail(t.id) }}
                onOpenEpic={onOpenEpic} />
            ))}
          </>
        ) : (
          <button className="wb-done-row" onClick={() => setShowDone(true)}>✓ 收口 · {doneList.length}（点击展开）</button>
        )
      )}

      {pageCount > 1 && (
        <div className="wb-pager">
          <button className="wb-btn" disabled={pageNo <= 1}
            onClick={() => setPageNo(p => Math.max(1, p - 1))}>上一页</button>
          <span className="wb-sub">第 {pageNo}/{pageCount} 页 · 未收口 {openList.length} 张</span>
          <button className="wb-btn" disabled={pageNo >= pageCount}
            onClick={() => setPageNo(p => Math.min(pageCount, p + 1))}>下一页</button>
        </div>
      )}
      </>)}

      {page === 'scan' && (
        <>
          <div className="wb-scan-backbar">
            <button className="wb-btn" onClick={() => setPage('tickets')}>← 返回工单列表</button>
          </div>
          <ScanReportSection scan={scan} onOpen={(id) => { setPage('tickets'); void openDetail(id) }} />
        </>
      )}

      {selectedId !== null && (
        <div className="wb-drawer">
          <button className="wb-close" onClick={() => { selectedIdRef.current = null; setSelectedId(null); setDetail(undefined) }}>×</button>
          {peerNote !== '' && (
            <div style={{ background: 'var(--dsw-derive-warn-bg,#fff8c5)', border: '1px solid var(--dsw-derive-warn-border,#d4a72c)', borderRadius: 6,
              padding: '6px 10px', fontSize: 12, color: 'var(--dsw-derive-warn-deep,#7d4e00)', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ flex: 1 }}>{peerNote}</span>
              <button className="wb-close" style={{ position: 'static' }}
                onClick={() => { setPeerNote('') }}>×</button>
            </div>
          )}
          {detailLoading && <div className="wb-empty">加载详情…</div>}
          {/* t260901-15 跳单守卫：详情与当前选中不一致不渲染（防在途旧响应顶替新详情）。 */}
          {!detailLoading && detail !== undefined && detail.id === selectedId && (
            <>
              <div className="wb-drawer-head">
                {/* 无标题票首句兜底（t260905-07）：详情通道从 show body 直接裁（列表
                    通道走 enrichment title_or_first，两通道同口径 firstSentenceOf）；
                    body 也空 → 回退工单号，宁显编号不显空白。 */}
                <span className="wb-title" data-title-src={detail.title?.trim() ? 'title' : 'first-or-id'}>
                  {detail.title?.trim() || firstSentenceOf(detail.body) || detail.id}
                </span>
                <code className="wb-d2-id">{detail.id}</code>
                <span className="wb-badge" data-kind="status">{detail.status}</span>
                {detail.status !== 'closed' && (
                  <span className="wb-badge" data-state={detail.stage_state}>{STATE_LABEL[detail.stage_state] ?? detail.stage_state}</span>
                )}
                <span className="wb-sub">{selWf?.name ?? '未挂模板'}</span>
                {/* 所属立项徽标（t260826-02）：点击跳中列立项单详情；无 epic 显灰「未归档」 */}
                <EpicBadge epic={detail.epic} onNavigate={onOpenEpic} />
                {/* token 一行合计（t260828-07，验收 3）：agent 段数 + in/out 总量 + 模型 */}
                <UsageSummaryLine detail={detail} wf={selWf} usage={usage} />
              </div>

              {/* 受阻原因横幅（t260904-17）：行卡「看原因」导航的详情落点——
                  阻塞原文随详情可达，不藏在折叠区 */}
              {detail.blocked_reason && (
                <div className="wb-d2-blocked">⛔ 受阻原因：{detail.blocked_reason}</div>
              )}
              {/* t260901-15 多页签共存：另一页签正在看此工单时提示（心跳驱动，TTL 自动消失）。 */}
              {drawerPeerViewers.length > 0 && (
                <div style={{ background: 'var(--dsw-derive-accent-bg,#ddf4ff)', border: '1px solid var(--dsw-derive-accent-border,#54aeff)', borderRadius: 6,
                  padding: '6px 10px', fontSize: 12, color: 'var(--dsw-derive-accent-deep,#0a3069)' }}>
                  👀 另一页签正在查看此工单：{drawerPeerViewers.map(v => v.who).join('、')}
                </div>
              )}
              {/* 详情页 v2.1（260824 二轮）：工单正文钉最顶（所有页签可见）→ 打回横幅 →
                  步骤条/一句话现状/问题区/操作条——任何页签都能看到状态、直接操作。 */}
              {detail.body && (
                <div className="wb-d2-body">
                  <div className="ttl">工单正文（原始需求）</div>
                  {detail.body}
                </div>
              )}
              {/* 执行规格卡（t260904-06）：正文卡正下方钉顶区，所有页签可见；spec 空/缺省整卡不渲染
                  （老票兼容）。B 形态=默认展开+限高 260px 滚动；字数徽标取 .length（UTF-16 码元）。 */}
              {detail.spec && (
                <div className="wb-d2-spec" data-v="B">
                  <div className="ttl">执行规格（spec）<span className="cnt">{detail.spec.length} 字</span></div>
                  <div className="txt">{detail.spec}</div>
                </div>
              )}
              <D2Reworks detail={detail} wf={selWf} />
              <D2Stepper detail={detail} wf={selWf} usage={usage} durs={stageDurs.durs} nowMs={stageDurs.nowMs} />
              {(() => { const st = d2StatusLine(detail, selWf); return (
                <div className="wb-d2-status" data-s={st.s}>{st.text}</div>
              ) })()}
              {/* t260825-03：运行脉搏行 + 实时动态折叠面板（钉在状态行下，所有页签可见） */}
              <PulseLine detail={detail} />
              <AgentLivePanel ticketId={detail.id} />
              <EvidenceImages ticketId={detail.id} />
              <D2Problems detail={detail} />
              <div className="wb-d2-actions">
                {ops.includes('advance') && (
                  <button className="wb-btn wb-btn-green" disabled={opBusy}
                    onClick={() => { doAdvance(detail.id, detail.stage_state, detail.epic) }}>
                    {detail.stage_state === 'awaiting-human' ? '✓ 审批通过' : '推进'}
                  </button>
                )}
                {ops.includes('unblock') && (
                  <button className="wb-btn wb-btn-blue" disabled={opBusy}
                    onClick={() => {
                      if ((detail as { engine?: string }).engine === 'template-as-code-v2') {
                        void doOp(detail.id, 'retry-qc', { who: operator }, '已请求重跑（retry_qc）')
                      } else {
                        void doOp(detail.id, 'update', { stage_state: 'awaiting', note: '（工单台）解除阻塞' }, '已解除阻塞')
                      }
                    }}>
                    重跑本步
                  </button>
                )}
                {ops.includes('rework') && (
                  <button className="wb-btn wb-btn-danger" disabled={opBusy}
                    onClick={() => { openRework(detail.id, detail.stage_state === 'awaiting-human') }}>
                    打回
                  </button>
                )}
                {detail.stage_state === 'awaiting-human' && (
                  <span className="wb-d2-hint">审批前请先在「变更」页签过 diff</span>
                )}
                {ops.length === 0 && detail.status !== 'closed' && (
                  <span className="wb-d2-hint">当前状态无可用操作（{detail.status}×{detail.stage_state}）</span>
                )}
                <details className="wb-d2-more">
                  <summary>更多</summary>
                  <div className="wb-d2-more-body">
                    {ops.includes('dispatch-next') && (
                      <button className="wb-btn" disabled={opBusy}
                        onClick={() => { void doOp(detail.id, 'dispatch-next', {}, '已生成派活指令') }}>
                        派下一棒
                      </button>
                    )}
                    {ops.includes('close') && (
                      <button className="wb-btn wb-btn-green" disabled={opBusy}
                        onClick={() => { if (window.confirm('标记为已完成（closed）？')) void doOp(detail.id, 'update', { status: 'closed', note: '（工单台）完成' }, '已标记完成') }}>
                        完成
                      </button>
                    )}
                    {detail.book_path && (
                      <button className="wb-btn" disabled={opBusy || previewLoading}
                        onClick={() => { void openPreview() }}>
                        {previewLoading ? '读取中…' : '预览内容'}
                      </button>
                    )}
                    <a className="wb-meta-link"
                      href={`http://127.0.0.1:8233/namespaces/default/workflows/${encodeURIComponent(detail.id)}`}
                      target="_blank" rel="noreferrer">Temporal 执行 ↗</a>
                  </div>
                </details>
              </div>
              {opMsg !== '' && <div className="wb-sub" style={{ marginTop: 6 }}>{opMsg}</div>}

              <div className="wb-dtabs">
                <button className="wb-dtab" data-on={drawerTab === 'detail'} onClick={() => setDrawerTab('detail')}>进展</button>
                <button className="wb-dtab" data-on={drawerTab === 'changes'} onClick={() => setDrawerTab('changes')}>
                  变更{detail.stage_state === 'awaiting-human' ? '（审批必看 diff）' : ''}
                </button>
                <button className="wb-dtab" data-on={drawerTab === 'agent'} onClick={() => setDrawerTab('agent')}>
                  Agent 日志
                </button>
              </div>

              {drawerTab === 'changes' && (
                <ChangesTab detail={detail} operator={operator} onMsg={setOpMsg} />
              )}

              {drawerTab === 'agent' && (
                <AgentLogsTab detail={detail} wf={selWf} onMsg={setOpMsg} />
              )}

              {drawerTab === 'detail' && (<>
              {/* 详情页 v2.1：正文已上移到头部（所有页签可见）；本页签=进展阶段卡 + 深查折叠。
                  旧 M14 五 section 内容全保留在深查区，一项不丢。 */}
              <D2Stages detail={detail} wf={selWf} usage={usage} durs={stageDurs.durs} nowMs={stageDurs.nowMs} />

              {/* 快照要点（t260905-07）：ticket show 直读四块观测（时间线/交接/门与签字/
                  工作流快照），收口成折叠块放深查区首位——下钻即见来龙去脉 */}
              <div className="wb-d2-deep">
                <D2SnapshotDigest detail={detail} />
              </div>

              <div className="wb-d2-deep">
                <details>
                  <summary>基本信息（工作区 · 分支 · 写集 · 时间）</summary>
                  <div>
                    <div className="wb-meta-grid">
                      <MetaItem k="工单">{detail.id}</MetaItem>
                      <MetaItem k="工作流">{selWf?.name ?? '未挂模板'}</MetaItem>
                      <MetaItem k="状态">{detail.status}
                        {detail.status !== 'closed' && detail.stage_state
                          ? ` · ${STATE_LABEL[detail.stage_state] ?? detail.stage_state}` : ''}
                      </MetaItem>
                      <MetaItem k="当前阶段">{detail.stage_name || detail.stage || '—'}</MetaItem>
                      <MetaItem k="角色">{detail.role || '—'}</MetaItem>
                      <MetaItem k="工作区" title={detailWs.path || undefined}>
                        {detailWs.type === 'main' ? (
                          <span className="wb-type-chip" data-empty={true}>主树</span>
                        ) : (
                          <><span className="wb-chip">{detailWs.type === 'worktree' ? '泳道' : '目录'}</span> {detailWs.label}</>
                        )}
                      </MetaItem>
                      {detail.branch && <MetaItem k="分支">{detail.branch}</MetaItem>}
                      {detail.base_ref && <MetaItem k="base" title={detail.base_ref}>{detail.base_ref.slice(0, 12)}</MetaItem>}
                      {detail.proposal_id && <MetaItem k="提案">{detail.proposal_id}</MetaItem>}
                      <MetaItem k="创建">{fmtTs(detail.created)}</MetaItem>
                      <MetaItem k="更新">{fmtTs(detail.updated)}</MetaItem>
                      <MetaItem k="修订">{detail.revision_count ?? 0} 轮</MetaItem>
                      <MetaItem k="接力">{detail.handoffs?.length ?? 0} 棒</MetaItem>
                      <MetaItem k="挂起">{detail.pending?.length ?? 0} 项</MetaItem>
                    </div>
                    {detail.write_set && detail.write_set.length > 0 && (
                      <div className="wb-meta-row"><span className="wb-meta-k">写集</span>
                        {detail.write_set.map(w => <span className="wb-chip" key={w}>{w}</span>)}
                      </div>
                    )}
                  </div>
                </details>

              {detail.workflow_input ? (
                <details>
                  <summary>入参（workflow 启动参数快照）</summary>
                  <div>
                    <div className="wb-md" style={{fontSize: '12px'}}>
                      <table style={{width: '100%', borderCollapse: 'collapse'}}>
                        <tbody>
                          {Object.entries(detail.workflow_input).map(([k, v]) => (
                            <tr key={k}>
                              <td style={{color: 'var(--dsw-derive-muted,#57606a)', padding: '2px 8px', whiteSpace: 'nowrap', verticalAlign: 'top'}}>{k}</td>
                              <td style={{padding: '2px 8px', wordBreak: 'break-word'}}>
                                {Array.isArray(v) ? v.join(', ') : String(v ?? '—')}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </details>
              ) : null}

              <details>
                <summary>验收清单（当前阶段{detail.stage ? ` ${detail.stage}` : ''}）</summary>
                <div>
                  {instItems.length === 0 && <div className="wb-empty">当前阶段无验收清单。</div>}
                  {instItems.map(item => {
                    const c = curChecks.find(x => x.item === item)
                    const done = c?.done ?? false
                    return (
                      <div className="wb-check" key={item}>
                        <div className="wb-check-line">
                          <input type="checkbox" checked={done}
                            disabled={opBusy || detail.status === 'closed' || (detail.stage_state === 'running' && detail.status === 'dispatched')}
                            onChange={() => { doAccept(item, !done) }} />
                          <span className="wb-check-item" data-done={done}>{item}</span>
                          {c?.by && <span className="wb-check-by">by {c.by}</span>}
                          {c?.agent && <span className="wb-check-by">分片 {c.agent}</span>}
                        </div>
                        {c?.evidence && <pre className="wb-evidence">证据：{c.evidence}</pre>}
                        {!done && detail.status === 'settled' && (
                          <input className="wb-ev-input" placeholder="证据（脚本输出原文/产物路径；可选）"
                            value={evInput[item] ?? ''}
                            onChange={e => setEvInput(v => ({ ...v, [item]: e.target.value }))} />
                        )}
                      </div>
                    )
                  })}
                  {detail.pending && detail.pending.length > 0 && (
                    <>
                      <div className="wb-sub-sec">挂起项（审批理由 / 遗留问题）</div>
                      {detail.pending.map((p, i) => (
                        <div className="wb-pending" key={i}>
                          <span className="wb-log-time">{fmtTs(p.ts)}</span> {p.note}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </details>

              <details>
                <summary>流水 log（状态/阶段流转历史）</summary>
                <div>
                  {[...(detail.log ?? [])].reverse().map((l, i) => (
                    <div className="wb-log" key={i}>
                      <span className="wb-log-time">{fmtTs(l.ts)}</span>
                      {l.status && <span className="wb-badge" data-kind="status">{l.status}</span>}
                      <span className="wb-log-note">{l.note}</span>
                    </div>
                  ))}
                </div>
              </details>

              <details>
                <summary>接力时间线（handoff · 每棒带产物）</summary>
                <div>
                  {detail.deliverables && <div className="wb-meta-row"><span className="wb-meta-k">交接物</span>{detail.deliverables}</div>}
                  {detail.handoffs && detail.handoffs.length > 0 ? (
                    [...(detail.handoffs)].reverse().map((h, i) => (
                      <div className="wb-hl" key={i}>
                        <div>
                          <span className="wb-hl-stage">[{h.stage}]</span>
                          <span className="wb-log-time"> {fmtTs(h.ts)}</span>
                          {h.agent_id && <span className="wb-check-by"> · {h.agent_id}</span>}
                        </div>
                        <div>{h.summary || '（无摘要）'}</div>
                        {h.artifacts && h.artifacts.length > 0 && (
                          <div>{h.artifacts.map((a, j) => <span className="wb-chip" key={j}>{a}</span>)}</div>
                        )}
                      </div>
                    ))
                  ) : (
                    <div className="wb-empty">暂无交接记录。</div>
                  )}
                </div>
              </details>
              </div>
              </>)}
            </>
          )}
        </div>
      )}

      {/* t260905-05：四类 wb-modal 补 role="dialog"/aria-modal/aria-label——a11y 语义 +
          集成场景可测性（[role=dialog] 消费面此前恒空）。纯属性零视觉差异。 */}
      {approveBox !== null && (
        <div className="wb-modal" role="dialog" aria-modal="true" aria-label="审批通过并推进">
          <div className="wb-modal-box">
            <div className="wb-modal-title">审批通过并推进 — {approveBox.id}</div>
            <div className="wb-modal-body">
              <div className="wb-ops" style={{ justifyContent: 'flex-start', marginBottom: 6 }}>
                <span className="wb-d-badge" data-s="added">自动摘要（不可编辑）</span>
              </div>
              <pre className="wb-prompt" style={{ maxHeight: 120, overflow: 'auto' }}>
                {approveBox.summary !== '' ? approveBox.summary : '（无已存审批意见，本轮无统计摘要）'}
              </pre>
              {approveBox.epicLine !== '' && <div style={{ margin: '6px 0', color: epicChipMuted() }}>{approveBox.epicLine}</div>}
              <textarea className="wb-ev-input" style={{ minHeight: 80 }} maxLength={2000}
                placeholder="自由备注（可空，有内容随签字进不可变历史，≤2000 字）"
                value={approveRemark} onChange={e => setApproveRemark(e.target.value)} />
            </div>
            <div className="wb-ops">
              <button className="wb-btn wb-btn-green" disabled={opBusy} onClick={doApprove}>确认通过并推进</button>
              <button className="wb-btn" onClick={closeApprove}>取消</button>
            </div>
          </div>
        </div>
      )}

      {reworkId !== null && (
        <div className="wb-modal" role="dialog" aria-modal="true" aria-label="打回">
          <div className="wb-modal-box">
            <div className="wb-modal-title">{reworkHuman ? '打回（走 Temporal sign，decision=reject）' : '打回'} — {reworkId}</div>
            <div className="wb-modal-body">
              <select className="wb-select" value={reworkTo} onChange={e => setReworkTo(e.target.value)}>
                <option value="">回退目标：缺省（按阶段语义自动）</option>
                {reworkStages.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <textarea className="wb-ev-input" style={{ minHeight: 80 }} placeholder="返工原因（必填）"
                value={reworkNote} onChange={e => setReworkNote(e.target.value)} />
            </div>
            <div className="wb-ops">
              <button className="wb-btn wb-btn-danger" disabled={opBusy} onClick={doRework}>确认打回</button>
              <button className="wb-btn" onClick={() => { setReworkId(null); setReworkNote(''); setReworkTo('') }}>取消</button>
            </div>
          </div>
        </div>
      )}

      {promptBox !== null && (
        <div className="wb-modal" role="dialog" aria-modal="true" aria-label="派活指令">
          <div className="wb-modal-box">
            <div className="wb-modal-title">派活指令（dispatch-next · {promptBox.role}@{promptBox.stage}）</div>
            <div className="wb-modal-body">
              <pre className="wb-prompt">{promptBox.prompt}</pre>
              <div className="wb-ops">
                <button className="wb-btn" onClick={() => { void copyPrompt(promptBox.prompt) }}>
                  {copied ? '已复制 ✓' : '复制 prompt'}
                </button>
                <button className="wb-btn" onClick={() => { setPromptBox(null); setCopied(false) }}>关 闭</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {preview !== undefined && (
        <div className="wb-modal" role="dialog" aria-modal="true" aria-label="内容预览">
          <div className="wb-modal-box wb-preview-box">
            <div className="wb-modal-title">
              内容预览 · {preview.meta.主题 || '後漢書'}{preview.meta.期次 ? `（${preview.meta.期次}）` : ''}
              <span className="wb-sub"> {preview.meta.类型} · 共 {preview.meta.total_chapters} 章 · 预览前 {preview.chapters.length} 章 · {preview.meta.size_kb}KB</span>
            </div>
            <div className="wb-preview-notice">预览 · 正式渲染以 app 为准（繁体原文，可滚动浏览）</div>
            <div className="wb-modal-body">
              {preview.chapters.map(ch => (
                <div className="wb-preview-ch" key={ch.id}>
                  <div className="wb-preview-ch-title">{ch.标题}</div>
                  {ch.paras.map((p, i) => (
                    <p className="wb-preview-para" key={i}>{p}</p>
                  ))}
                </div>
              ))}
              {preview.chapters.length === 0 && <div className="wb-empty">该文件无可预览章节。</div>}
            </div>
            <div className="wb-ops">
              <button className="wb-btn" onClick={() => { setPreview(undefined) }}>关 闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- 注册 */

/**
 * Workbench 视图的 per-session snapshot builder（引擎契约空实现）。
 * 工单台数据来自 /sandbar-workbench/api/wf/*（宿主半 API），不消费会话事件流；
 * create 返回的 builder 仅需满足 ConversationViewBuilder 形状（empty/replace/apply）。
 * target 与 conversation.view 槽条目 id（'workbench'）一致，与 chat/trajectory 同机制。
 */

export function apply(ctx: ClientContext): void {
  // 接管侧栏：左列=顶部会话入口行+项目分组+进行中工单，中列=工单台/文档/模型/立项单视图。
  // single 槽「lowest renders」——默认 WorkspaceBrowser 无 priority（=0），我们挂 -10 抢占；
  // 同优先级注册会 throw。chat 顶部页签不再注册（260823 用户拍板移出）。
  // t260831-02：不再注册任何 conversation.hero.* 槽——出厂落地页原样（右栏零定制）。
  // t260831-04：workspaces 传给顶部入口——新建走 ctx.workspaces.startSession
  // （工厂同款语义；详见 session-entry.tsx WorkspacesFace 注释）。
  ctx.slots.inject('sidebar.workspaces', () => ctx.slots.register({
    name: 'sidebar.workspaces',
    priority: -10,
  }, (props: any) => <WorkbenchSidebar
    sessions={ctx.sessions}
    workspaces={ctx.workspaces as any}
    views={{ board: WorkbenchSection, docs: DocsSection, routes: ProvidersSection, epics: EpicSection }}
    {...props} />))

  // 度量入口进出厂 footer.action 槽（t260902-05①）：与 dsh settings 齿轮同排。
  // inject 回调体 try/catch（README 槽纪律：槽未声明时 throw 在 register() 内
  // 延迟执行，外层 catch 接不到）；失败 markFooterSlot(false) → 侧栏 .wb-sb-foot
  // 兜底钮照常渲染（软退化不静默，console.warn 留痕）。
  ctx.slots.inject('sidebar.footer.action', () => {
    try {
      const dispose = ctx.slots.register({ name: 'sidebar.footer.action', priority: -10 }, MetricsFooterButton)
      markFooterSlot(true)
      return dispose
    } catch (err) {
      markFooterSlot(false)
      console.warn('[workbench] sidebar.footer.action 槽注册失败，度量入口软退化回工单台下栏：', err)
    }
  })
}
