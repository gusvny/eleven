/**
 * ticket-row-card —— 工单列表平铺行卡（t260904-17，mock v5 屏⑤⑥；一套 UI 裁定）。
 *
 * 中列列表页与左栏迷你版共用本组件（compact prop 区分：迷你版省略站道与管理动作位）。
 * 判定/推导全部住在 ticket-list-model.ts 纯函数层，本组件只消费——零 dev-lane
 * 专属词（守卫测试整文件扫描看住）。
 *
 * 导航语义（方案 gen1 R3 钉死）：衍生动作位「去签字/看原因」=纯导航（onOpen 带
 * 锚点），**零写操作**——不复用 advance 写通路（行内静默签字=「没看过就签了」危害）；
 * 管理动作位（推进/派下一棒/打回/解除阻塞/完成）回调由父注入，busy 禁用 +
 * stopPropagation 防误触行卡导航。
 */

import type { MouseEvent } from 'react'
import {
  deriveTicketState, STATE4_LABEL, epicColorOf, stageShortOf, relativeTime,
  laneDots, toMillis, type WfLike,
} from './ticket-list-model.ts'

/** 行卡消费的工单最小字段面（对齐 index.tsx TicketRow，多字段不关心）。 */
export interface CardTicket {
  id: string
  title?: string
  epic?: string
  status: string
  stage: string | null
  stage_state: string
  role?: string
  updated?: string
  updated_ts?: number
  created?: number
  blocked_reason?: string
}

/** 进展行（host enrichment 透传；缺省=行卡降级只显相对时间）。 */
export interface CardProgress {
  state: string
  text: string
}

/** 管理动作位键集（与台面 availableOps 的返回键同名单）。 */
export type CardOp = 'advance' | 'dispatch-next' | 'rework' | 'unblock' | 'close'

export interface TicketRowCardProps {
  t: CardTicket
  /** 模板拓扑（站道点数/阶段短名数据源）；缺省=不渲染站道、悬停无阶段语境。 */
  wf?: WfLike | null
  /** host enrichment 的进展行；undefined=降级。 */
  progress?: CardProgress
  compact?: boolean
  active?: boolean
  busy?: boolean
  /** 相对时间备选时间源（unix ms；侧栏 Ticket 只有 created/close_ts 秒级字段时用）。 */
  updatedTsMs?: number
  /** 可用管理动作键集（父层 availableOps 结果原样传入）。 */
  ops?: CardOp[]
  peerViewers?: { who: string }[]
  /** 纯导航：anchor='review'（等你→审批/人门区）| 'blocked'（受阻→原因区）| 缺省=普通打开。 */
  onOpen: (anchor?: 'review' | 'blocked') => void
  onAdvance?: () => void
  onDispatch?: () => void
  onRework?: () => void
  onUnblock?: () => void
  onClose?: () => void
  onOpenEpic?: (code: string) => void
}

/** 悬停 title：id＋阶段语境（C2 消费点：阶段短名拓扑驱动）＋阻塞原因。 */
function cardTitle(t: CardTicket, wf?: WfLike | null): string {
  const parts = [t.id]
  const stage = (wf?.stages ?? []).find(s => s?.id === t.stage)
  const short = stageShortOf(stage)
  if (short !== '') parts.push(`阶段：${short}`)
  if (t.blocked_reason) parts.push(`阻塞原因：${t.blocked_reason}`)
  if (t.updated) parts.push(`更新 ${t.updated}`)
  return parts.join('\n')
}

export function TicketRowCard({
  t, wf, progress, compact = false, active = false, busy = false, updatedTsMs,
  ops = [], peerViewers = [], onOpen, onAdvance, onDispatch, onRework, onUnblock, onClose, onOpenEpic,
}: TicketRowCardProps) {
  const state4 = deriveTicketState(t.status, t.stage_state)
  const epicColor = epicColorOf(t.epic)
  const dots = compact ? [] : laneDots(wf, t)
  const rel = relativeTime(toMillis(t.updated_ts ?? updatedTsMs))
  const stop = (fn?: () => void) => (ev: MouseEvent) => {
    ev.stopPropagation()
    if (!busy) fn?.()
  }
  const rowTone = state4 === 'waiting' ? '#fff8c5' : state4 === 'blocked' ? '#ffebe9' : undefined
  return (
    <div
      className="wb-card" data-ticket-id={t.id}
      data-state={state4} data-active={active} data-compact={compact}
      style={{ borderLeftColor: epicColor, background: rowTone }}
      title={cardTitle(t, wf)}
      onClick={() => onOpen()}
      role="button"
    >
      <div className="wb-card-l1">
        {/* 状态点着色走 CSS 伪元素（::before）——元素本体无圆角无底色，
            不与迷你站道圆点混数（UI 场景 T5 以几何特征数点） */}
        <span className="wb-card-dot" data-state={state4} />
        <span className="wb-card-state" data-state={state4}>{STATE4_LABEL[state4]}</span>
        <span className="wb-card-id">{t.id}</span>
        {(peerViewers?.length ?? 0) > 0 && (
          <span title={`另一页签正在查看：${(peerViewers ?? []).map(v => v.who).join('、')}`}>👀</span>
        )}
        <span className="wb-card-title">{t.title || '（无标题）'}</span>
        {/* epic 独立字段：彩 chip，点击=按 epic 筛（stopPropagation 不触发行卡导航） */}
        {t.epic && (
          <span className="wb-card-epic" style={{ borderColor: epicColor, color: epicColor }}
            title={`所属立项：${t.epic}`}
            onClick={(ev) => { ev.stopPropagation(); onOpenEpic?.(t.epic ?? '') }}>
            {t.epic}
          </span>
        )}
      </div>
      <div className="wb-card-l2">
        {/* 一句进展：host 时间线末条人话；缺省降级只显相对时间（绝对时间字符串兜底） */}
        <span className="wb-card-progress" data-state={progress?.state ?? ''}>
          {progress ? progress.text : (t.updated || '')}
        </span>
        <span className="wb-card-time">{rel ?? (t.updated || '')}</span>
        {t.role && !compact && <span className="wb-card-role">· {t.role}</span>}
        {!compact && dots.length > 0 && (
          <span className="wb-card-lane" title={`站道（${dots.length} 站）`}>
            {dots.map((d, i) => (
              <span key={i} className="wb-card-lane-dot" data-visual={d} data-state={state4} />
            ))}
          </span>
        )}
      </div>
      <div className="wb-card-ops" onClick={ev => ev.stopPropagation()}>
        {/* 衍生动作位=纯导航（R3）：等你→去签字（详情审批区）；受阻→看原因（阻塞原因区） */}
        {state4 === 'waiting' && (
          <button className="wb-card-btn wb-card-btn-primary" onClick={(ev) => { ev.stopPropagation(); onOpen('review') }}>
            去签字 →
          </button>
        )}
        {state4 === 'blocked' && (
          <button className="wb-card-btn wb-card-btn-blue" onClick={(ev) => { ev.stopPropagation(); onOpen('blocked') }}>
            看原因
          </button>
        )}
        {!compact && ops.includes('advance') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onAdvance)}>推进</button>
        )}
        {!compact && ops.includes('dispatch-next') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onDispatch)}>派下一棒</button>
        )}
        {!compact && ops.includes('unblock') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onUnblock)}>解除阻塞</button>
        )}
        {!compact && ops.includes('rework') && (
          <button className="wb-card-btn wb-card-btn-danger" disabled={busy} onClick={stop(onRework)}>打回</button>
        )}
        {!compact && ops.includes('close') && (
          <button className="wb-card-btn wb-card-btn-green" disabled={busy} onClick={stop(onClose)}>完成</button>
        )}
      </div>
    </div>
  )
}
