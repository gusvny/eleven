/**
 * ticket-row-card —— 工单列表平铺行卡（t260904-17，mock v5 屏⑤⑥；一套 UI 裁定）。
 *
 * 中列列表页与左栏迷你版共用本组件（compact prop 区分：迷你版省略站道与管理动作位）。
 * 判定/推导全部住在 ticket-list-model.ts 纯函数层，本组件只消费——零 dev-lane
 * 专属词（守卫测试整文件扫描看住）。
 *
 * 导航语义（票 t260904-17 方案 R3）：衍生动作位「去签字/看原因」=纯导航（onOpen 带
 * 锚点），**零写操作**——不复用 advance 写通路（行内静默签字=「没看过就签了」危害）；
 * 管理动作位（推进/派下一棒/打回/解除阻塞/完成）回调由父注入，busy 禁用 +
 * stopPropagation 防误触行卡导航。
 */

import type { DragEvent, MouseEvent } from 'react'
import { epicChipColor } from './theme'
import type { OrderKind } from './queue-model.ts'
import {
  deriveTicketState, STATE4_LABEL, epicColorOf, stageShortOf, relativeTime,
  laneDots, toMillis, ticketDisplayTitle, pausedBadgeText, closeHealthOf, closeHealthBadgeOf,
  dismissedFaceOf, dismissedNoteOf, lineFaceOf, linePillText,
  type WfLike,
} from './ticket-list-model.ts'
import { stageDisplayLabel } from './ui-labels.ts'

/** 行卡消费的工单最小字段面（对齐 index.tsx TicketRow，多字段不关心）。 */
export interface CardTicket {
  id: string
  title?: string
  /** 无标题票的首句派生（t260905-07）：host enrichment 下发，仅 title 空的票带。 */
  title_or_first?: string
  epic?: string
  status: string
  stage: string | null
  stage_state: string
  role?: string
  updated?: string
  updated_ts?: number
  created?: number
  blocked_reason?: string
  /** t261008-22: voided (engine row key; truthy = the row re-classifies to done + the card shows "Voided by ..."). */
  voided?: { at?: unknown; who?: unknown; reason?: unknown } | unknown
  /** 段间暂停二态（t260908-01，host 行形状透传）：paused=已受理；
   *  paused_phase=pending（待段间生效）/ at_gate（已停在段间门口）。 */
  paused?: boolean
  paused_phase?: string
  /** 引擎标记（t260915-19 左栏黄调作用域数据源）：值由引擎行下发（dev-lane=
   *  "template-as-code-v2"；巡检族行=另一标记串）——本组件保持通用零业务词表
   *  （t260915-08 守卫），左栏以该值等值选择器作用域「等你」黄调，异值零命中。 */
  engine?: string
  /** Temporal 执行状态（t260919-02：五态推导第三参；失败类终态行显「已失败」）。 */
  exec_status?: string
  /** 收口健康度判定面（t260921-03：异常收口徽标数据源；全可缺=兜底推导）。 */
  kind?: string
  report_path?: string
  close_health?: string
  /** 收口健康度事实原因（引擎下发；悬停 title 透传，绝不编造）。 */
  close_health_reason?: string
  /** t261009-43: the engine's dismissal voucher (dismissed:{at,who,reason};
   *  truthy plain object = dismissed). Read, never invented, never flipped
   *  locally — see dismissedFaceOf in ticket-list-model.ts. A dismissed row is
   *  NOT done: the five-state derivation does not see this key. */
  dismissed?: unknown
  /** t261009-43: the engine's named note when the dismiss journal could not be
   *  read (the dismissed key is absent then). Non-empty = keep the row visible
   *  and surface the note; never read as "dismissed". */
  dismissed_note?: unknown
  /** t261011-19: the ENGINE's line-face word (host list route enrichment fed by
   *  src/host/line-face-adapter.py) + its overdue flag. Read through
   *  lineFaceOf — a mapping, never a derivation; absent/unknown => no pill. */
  line_face?: unknown
  line_face_overdue?: unknown
}

/** 进展行（host enrichment 透传；缺省=行卡降级只显相对时间）。 */
export interface CardProgress {
  state: string
  text: string
}

/** 管理动作位键集（与台面 availableOps 的返回键同名单）。 */
export type CardOp = 'advance' | 'dispatch-next' | 'rework' | 'unblock' | 'close' | 'pause' | 'resume'

/**
 * CL-3 (t261006-18) ordering face for one row, projected by the parent from the
 * ENGINE's concurrency read face (GET /sandbar-workbench/api/wf/concurrency) —
 * this component never classifies on its own. undefined = the row takes no
 * part in ordering: nothing is rendered, every existing consumer is unchanged.
 *   queued: leading position number + handgrip + up/down arrows (draggable);
 *   atwork: green dot; hold: amber dot (the human gate); paused: amber dot;
 *   atwork/hold/paused carry NO ordering controls (design §2.2).
 * `dotsLit` renders the ten-cell progress dots on line 2 (design §7.2 default).
 * Every move callback ends in POST reorder -> re-read the same face; no local
 * order is kept anywhere.
 */
export interface RowOrdering {
  kind: OrderKind
  /** 1-based engine position (queued rows only; parent reads it from the face). */
  pos?: number
  /** Lit cells for the ten-cell progress dots (0..10; undefined = not rendered). */
  dotsLit?: number
  /** A reorder write is in flight: controls disabled (never a double move). */
  busy?: boolean
  onMove?: (dir: -1 | 1) => void
  onDragStart?: () => void
  onDrop?: () => void
}


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
  /** 类别徽标（t260916-15）：行1 的小 chip，文本由父层给（本组件零业务词表——
   *  侧栏用它标「巡检」来源行；缺省=不渲染，中列板面零消费零影响）。
   *  data-kind-badge=值即文本，渲染断言/样式作用域选择器锚。 */
  kindBadge?: { text: string }
  /** CL-3 ordering face (queue-model projection; undefined = row not ordered, zero render change). */
  ordering?: RowOrdering
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
  onPause?: () => void
  onResume?: () => void
  onOpenEpic?: (code: string) => void
  /** t261009-43: the person's dismiss action. The parent passes it ONLY for a
   *  failure-class row the person is looking at (one row, never bulk) and the
   *  component double-guards on the failed state; the label is "Dismiss" —
   *  never a close/done word. undefined = not offered, zero render change. */
  onDismiss?: () => void
  /** t261009-43: undo path from the dismissed fold. Rendered only on a
   *  dismissed row; undefined = not offered. */
  onRestore?: () => void
}

/** Row tooltip title: id + stage context (C2 consumer: stage-short topology) +
 *  blocked reason + exec-status verbatim (t260919-02: a failed row is
 *  distinguishable in the tooltip by its Temporal terminal word) + the
 *  close-health reason (t260921-03: never an unexplained abnormal close).
 *  t261008-08 (mock v11): the compact (left-column) row moves the progress
 *  sentence and the updated time into the tooltip — the visible row keeps only
 *  id/title on line 1 and stage+epic+dots on line 2; absent parts are skipped,
 *  never rendered as `undefined`.
 *  (Exported for unit tests only — the malformed-input truth table runs in
 *  tests/; render assertions belong to the scenarios.) */
export function cardTitle(t: CardTicket, wf?: WfLike | null, compact = false,
  progress?: CardProgress, rel?: string | null): string {
  const parts = [t.id]
  const stage = (wf?.stages ?? []).find(s => s?.id === t.stage)
  const short = stageDisplayLabel(stage?.id ?? t.stage, stageShortOf(stage))
  if (short !== '') parts.push(`Stage: ${short}`)
  if (t.blocked_reason) parts.push(`Blocked: ${t.blocked_reason}`)
  // t261008-22: the void fact goes into the tooltip (who/why — the disposition
  // voucher travels with the row; malformed voided shape = say "voided" only, never
  // invent a who).
  if (t.voided && typeof t.voided === 'object') {
    const v = t.voided as { who?: unknown; reason?: unknown }
    const who = typeof v.who === 'string' && v.who.trim() !== '' ? v.who : 'unknown'
    const why = typeof v.reason === 'string' && v.reason.trim() !== '' ? `: ${v.reason}` : ''
    parts.push(`Voided by ${who}${why} (findings were rejected, not erased)`)
  } else if (t.voided) {
    parts.push('Voided (findings were rejected, not erased)')
  }
  if (t.exec_status) parts.push(`Exec: ${t.exec_status}`)
  if (t.close_health_reason) parts.push(`Close: ${t.close_health_reason}`)
  // t261009-43: the dismissal voucher travels with the row tooltip (who/why —
  // a dismissed row is a human disposition, not a done ticket); a malformed
  // voucher says "Dismissed" only, never an invented who.
  if (t.dismissed && typeof t.dismissed === 'object' && !Array.isArray(t.dismissed)) {
    const d = t.dismissed as { who?: unknown; reason?: unknown }
    const who = typeof d.who === 'string' && d.who.trim() !== '' ? d.who : 'unknown'
    const why = typeof d.reason === 'string' && d.reason.trim() !== '' ? `: ${d.reason}` : ''
    parts.push(`Dismissed by ${who}${why} (off the board, not done — restorable)`)
  } else if (t.dismissed) {
    parts.push('Dismissed (off the board, not done — restorable)')
  }
  // t261009-43: the engine's named note (journal read failed) surfaces verbatim
  // in the tooltip AND as a visible row chip below — a row with a note stays.
  if (typeof t.dismissed_note === 'string' && t.dismissed_note.trim() !== '') {
    parts.push(`Dismiss note: ${t.dismissed_note}`)
  }
  if (compact && progress?.text) parts.push(progress.text)
  if (t.updated) parts.push(`Updated ${t.updated}`)
  else if (compact && rel) parts.push(`Updated ${rel}`)
  return parts.join('\n')
}

export function TicketRowCard({
  t, wf, progress, compact = false, active = false, busy = false, updatedTsMs, kindBadge, ordering,
  ops = [], peerViewers = [], onOpen, onAdvance, onDispatch, onRework, onUnblock, onClose, onPause, onResume, onOpenEpic,
  onDismiss, onRestore,
}: TicketRowCardProps) {
  // t260919-02：exec_status 进五态推导（失败类终态行 → 'failed'「已失败」红标）。
  // t261009-43: the dismissed key is deliberately NOT an input — a dismissed
  // row keeps its true state class (a dismissed failure stays failed, never
  // re-reads as done); leaving the board is the parent filter's job.
  const dismissedVoucher = dismissedFaceOf(t) !== null
  const state4 = deriveTicketState(t.status, t.stage_state, t.exec_status, t.voided)
  const epicColor = epicColorOf(t.epic)
  const dots = compact ? [] : laneDots(wf, t)
  const rel = relativeTime(toMillis(t.updated_ts ?? updatedTsMs))
  // t261008-08 (mock v11): the compact line-2 stage short text (same single
  // derivation the tooltip consumes).
  const stageLabel = stageDisplayLabel(
    (wf?.stages ?? []).find(s => s?.id === t.stage)?.id ?? t.stage,
    stageShortOf((wf?.stages ?? []).find(s => s?.id === t.stage)))
  const stop = (fn?: () => void) => (ev: MouseEvent) => {
    ev.stopPropagation()
    if (!busy) fn?.()
  }
  // CL-3 drag: only queued rows are draggable (draggable sits on the
  // data-order-kind=queued row); onDragOver preventDefault is the HTML5 DnD
  // drop-allowance protocol for dropping over other rows.
  const orderable = ordering?.kind === 'queued'
  const onDragStart = (ev: DragEvent) => {
    if (!orderable) return
    ev.dataTransfer.effectAllowed = 'move'
    ev.dataTransfer.setData('text/plain', t.id)
    ordering?.onDragStart?.()
  }
  const onDrop = (ev: DragEvent) => {
    ev.preventDefault()
    ev.stopPropagation()
    ordering?.onDrop?.()
  }
  // t260905-08：状态行底色不再行内写死——CSS 按 data-state 接管
  // （.wb-card[data-state=waiting/blocked]，主题令牌派生，深浅两档自适应；
  //   原 rowTone 行内浅色写死=深色主题浅字撞浅底根因，宿主 260906 实报）。
  // 彩条 borderLeftColor 保留 epicColor 原色（装饰不承载文字；17 号 T6/walkthrough
  // 断言直读此值，R8 已核平）。
  // t261011-19: shared row fragments. The compact (left-column) card becomes a
  // THREE-line card (design contract §14 #1): L1 = id -> rank -> LineOn pill ->
  // pause icon -> row-end ordering controls; L2 = the title alone; L3 = step
  // name -> category chip -> the ten-cell dot matrix at the right edge. The
  // board (non-compact) card keeps its current two-line composition unchanged.
  const lineFace = compact ? lineFaceOf(t) : null
  const idSpan = <span className="wb-card-id">{t.id}</span>
  const posSpan = ordering?.kind === 'queued' && (
    <span className="wb-order-pos" data-order-pos={ordering.pos ?? 0}
      title={`Queue position ${ordering.pos ?? 0}`}>{ordering.pos ?? ''}</span>
  )
  const pillSpan = lineFace && (
    <span className="wb-line-pill" data-line-face={t.line_face}
      data-line-overdue={lineFace.overdue ? '1' : undefined}
      title={`Line ${t.line_face === 'on_line' ? 'on the develop line, not landed' : `state: ${String(t.line_face)}`}`}>
      {linePillText(lineFace)}
    </span>
  )
  const pauseIcon = compact && t.paused && (
    <span className="wb-card-paused" data-paused="1"
      data-paused-phase={t.paused_phase || 'pending'} role="img"
      aria-label={pausedBadgeText(t.paused_phase)}
      title={t.paused_phase === 'at_gate'
        ? 'Halted at the stage gate: next stage not dispatched; click Resume to continue'
        : 'Pause accepted: the current stage (incl. in-flight agent) finishes, then stops'}>
      ⏸
    </span>
  )
  const ctlSpan = orderable && (
    <span className="wb-order-ctl" data-order-ctl="">
      <span className="wb-order-grip" data-order-grip="" title="Drag to reorder"
        aria-label={`Drag to reorder ${t.id}`}>⋮⋮</span>
      <button type="button" className="wb-order-arrow" disabled={ordering?.busy}
        aria-label={`Move ${t.id} up`} title="Move up"
        onClick={(ev) => { ev.stopPropagation(); ordering?.onMove?.(-1) }}>⌃</button>
      <button type="button" className="wb-order-arrow" disabled={ordering?.busy}
        aria-label={`Move ${t.id} down`} title="Move down"
        onClick={(ev) => { ev.stopPropagation(); ordering?.onMove?.(1) }}>⌄</button>
    </span>
  )
  const titleSpan = (
    <span className="wb-card-title" data-wb-row-title={ticketDisplayTitle(t)}
      data-title-src={t.title?.trim() ? 'title' : t.title_or_first ? 'first' : 'id'}>
      {ticketDisplayTitle(t)}
    </span>
  )
  const kindSpan = kindBadge && (
    <span className="wb-card-kind" data-kind-badge={kindBadge.text}
      title={`Kind: ${kindBadge.text}`}>
      {kindBadge.text}
    </span>
  )
  const healthSpan = (() => {
    const badge = closeHealthBadgeOf(t)
    return badge !== '' && (
      <span className="wb-card-health" data-close-health={closeHealthOf(t)}
        title={t.close_health_reason || badge}>
        {badge}
      </span>
    )
  })()
  const noteSpan = dismissedNoteOf(t) !== '' && (
    <span className="wb-card-dismiss-note" data-dismiss-note="1"
      title={dismissedNoteOf(t)}>Dismiss note</span>
  )
  const viewersSpan = (peerViewers?.length ?? 0) > 0 && (
    <span title={`Viewed from another tab: ${(peerViewers ?? []).map(v => v.who).join(', ')}`}>👀</span>
  )
  const epicChip = t.epic && (
    <span className="wb-card-epic"
      style={{ borderColor: epicColor, ['--epic-c' as string]: epicColor, color: epicChipColor() }}
      title={`Epic: ${t.epic}`}
      onClick={(ev) => { ev.stopPropagation(); onOpenEpic?.(t.epic ?? '') }}>
      {t.epic}
    </span>
  )
  const stageSpan = compact && stageLabel !== '' && (
    <span className="wb-card-stage" data-wb-row-stage={stageLabel}>{stageLabel}</span>
  )
  // t261011-19: the compact ten-cell matrix carries the state on every cell —
  // container data-state + per-cell data-visual (lit = reached, dim = not yet
  // reached; CSS paints both in the SAME state hue, dim shade for todo; blocked
  // vs failed split by SHAPE: hollow vs solid red). data-on stays for the
  // existing lit-count anchor; the count stays exactly 10.
  const dotsSpan = compact && ordering?.dotsLit !== undefined && (
    <span className="wb-stage-dots" data-lit={ordering.dotsLit} data-state={state4}
      title={`Stage dots: ${ordering.dotsLit} of 10`}>
      {Array.from({ length: 10 }, (_, i) => {
        const lit = i < (ordering.dotsLit ?? 0)
        return (
          <span key={i} className="wb-stage-dot"
            data-on={lit || undefined} data-visual={lit ? 'lit' : 'todo'} />
        )
      })}
    </span>
  )
  return (
    <div
      className="wb-card" data-ticket-id={t.id}
      data-state={state4} data-active={active} data-compact={compact}
      data-engine={t.engine}
      data-dismissed={dismissedVoucher ? '1' : undefined}
      data-order-kind={ordering?.kind}
      draggable={orderable}
      onDragStart={onDragStart}
      onDragOver={orderable ? undefined : (ev) => { if (ordering !== undefined) ev.preventDefault() }}
      onDrop={ordering !== undefined ? onDrop : undefined}
      style={compact ? undefined : { borderLeftColor: epicColor }}
      title={cardTitle(t, wf, compact, progress, rel)}
      onClick={() => onOpen()}
      role="button"
    >
      <div className="wb-card-l1">
        {compact ? (
          /* t261011-19 three-line card, L1: id FIRST -> rank -> LineOn pill ->
             pause icon -> row-end ordering controls (queued rows only). */
          <>
            {idSpan}
            {posSpan}
            {pillSpan}
            {pauseIcon}
            {ctlSpan}
          </>
        ) : (
          // Board column: the existing composition, byte-for-byte in order.
          <>
            {/* CL-3 order marks (t261006-18): queued = leading position number;
                at-work = green dot; human-hold / paused = amber dot. At-work,
                hold and paused rows render NO ordering controls - everything
                comes from the parent's ordering projection, never judged here. */}
            {ordering?.kind === 'queued' && (
              <span className="wb-order-pos" data-order-pos={ordering.pos ?? 0}
                title={`Queue position ${ordering.pos ?? 0}`}>{ordering.pos ?? ''}</span>
            )}
            {ordering?.kind === 'atwork' && (
              <span className="wb-order-dot" data-order-dot="work" title="At work" />
            )}
            {(ordering?.kind === 'hold' || ordering?.kind === 'paused') && (
              <span className="wb-order-dot" data-order-dot={ordering.kind === 'hold' ? 'hold' : 'paused'}
                title={ordering.kind === 'hold' ? 'Holding a slot at the human gate' : 'Paused by you (no slot)'} />
            )}
            {/* State dot colouring rides the CSS ::before pseudo-element — the
                element itself stays borderless and uncoloured so it never joins
                the mini-lane dot count (the UI scenario counts dots geometrically). */}
            <span className="wb-card-dot" data-state={state4} />
            <span className="wb-card-state" data-state={state4}>{STATE4_LABEL[state4]}</span>
            {/* Inter-stage pause badge (t260908-01): two-phase wording guards
                against the "paused but still running" misread — pending = signal
                accepted, the current stage (incl. an in-flight agent) finishes;
                at_gate = halted at the stage gate. */}
            {t.paused && (
              <span className="wb-card-paused" data-paused="1"
                data-paused-phase={t.paused_phase || 'pending'}
                title={t.paused_phase === 'at_gate'
                  ? 'Halted at the stage gate: next stage not dispatched; click Resume to continue'
                  : 'Pause accepted: the current stage (incl. in-flight agent) finishes, then stops'}>
                {pausedBadgeText(t.paused_phase)}
              </span>
            )}
            {kindSpan}
            {healthSpan}
            {noteSpan}
            {idSpan}
            {viewersSpan}
            {titleSpan}
            {ctlSpan}
            {!compact && t.epic && epicChip}
          </>
        )}
      </div>
      {compact ? (
        <>
          {/* L2: the title alone (t261011-19, design §14 #1). */}
          <div className="wb-card-l2">{titleSpan}</div>
          {/* L3: step name -> category chip -> the ten-cell dot matrix at the
              right edge; every element the compact row already had stays
              (kind/health/dismiss-note/viewers/epic chips; a synthesized
              progress face keeps its at-a-glance exception). */}
          <div className="wb-card-l3">
            {stageSpan}
            {kindSpan}
            {healthSpan}
            {noteSpan}
            {viewersSpan}
            {t.epic && epicChip}
            {progress && (
              <span className="wb-card-progress" data-state={progress.state}>{progress.text}</span>
            )}
            {dotsSpan}
          </div>
        </>
      ) : (
        <div className="wb-card-l2">
          {/* Progress sentence: the host timeline's last human-readable line; falls
              back to the relative/absolute time when absent. */}
          <span className="wb-card-progress" data-state={progress?.state ?? ''}>
            {progress ? progress.text : (t.updated || '')}
          </span>
          <span className="wb-card-time">{rel ?? (t.updated || '')}</span>
          {t.role && <span className="wb-card-role">· {t.role}</span>}
          {dots.length > 0 && (
            <span className="wb-card-lane" title={`Stage dots (${dots.length})`}>
              {dots.map((d, i) => (
                <span key={i} className="wb-card-lane-dot" data-visual={d} data-state={state4} />
              ))}
            </span>
          )}
        </div>
      )}
      <div className="wb-card-ops" onClick={ev => ev.stopPropagation()}>
        {/* 衍生动作位=纯导航（R3）：等你→去签字（详情审批区）；受阻→看原因（阻塞原因区） */}
        {state4 === 'waiting' && (
          <button className="wb-card-btn wb-card-btn-primary" onClick={(ev) => { ev.stopPropagation(); onOpen('review') }}>
            Sign →
          </button>
        )}
        {state4 === 'blocked' && (
          <button className="wb-card-btn wb-card-btn-blue" onClick={(ev) => { ev.stopPropagation(); onOpen('blocked') }}>
            View Reason
          </button>
        )}
        {!compact && ops.includes('advance') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onAdvance)}>Advance</button>
        )}
        {!compact && ops.includes('dispatch-next') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onDispatch)}>Dispatch next</button>
        )}
        {!compact && ops.includes('unblock') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onUnblock)}>Unblock</button>
        )}
        {!compact && ops.includes('rework') && (
          <button className="wb-card-btn wb-card-btn-danger" disabled={busy} onClick={stop(onRework)}>Rework</button>
        )}
        {!compact && ops.includes('pause') && (
          <button className="wb-card-btn" disabled={busy} onClick={stop(onPause)}
            title="Pause between stages: current stage (incl. in-flight agent) finishes, then stops; no next stage">Pause</button>
        )}
        {!compact && ops.includes('resume') && (
          <button className="wb-card-btn wb-card-btn-green" disabled={busy} onClick={stop(onResume)}
            title="Resume: release the stage gate and keep dispatching">Resume</button>
        )}
        {!compact && ops.includes('close') && (
          <button className="wb-card-btn wb-card-btn-green" disabled={busy} onClick={stop(onClose)}>Done</button>
        )}
        {/* t261009-43: the person's dismiss action — one failed row the person
            is looking at, never bulk, never worded close/done. The parent opens
            the reason prompt (the engine refuses an empty reason; the face asks
            first). Restore is the fold's undo path, dismissed rows only. */}
        {state4 === 'failed' && !dismissedVoucher && onDismiss && (
          <button className="wb-card-btn wb-card-btn-dismiss" data-dismiss-ctl={t.id} disabled={busy}
            title="Dismiss: take this failed ticket off the board (reversible; a reason is asked and recorded)"
            onClick={stop(onDismiss)}>Dismiss</button>
        )}
        {dismissedVoucher && onRestore && (
          <button className="wb-card-btn wb-card-btn-green" data-restore-ctl={t.id} disabled={busy}
            title="Restore: put this dismissed ticket back on the board"
            onClick={stop(onRestore)}>Restore</button>
        )}
      </div>
    </div>
  )
}
