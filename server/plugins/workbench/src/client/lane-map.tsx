/**
 * lane-map.tsx —— 真泳道图（拓扑驱动）+ 检查明细区组件（t260915-05，mock ①③④）。
 *
 * 渲染器通用性承诺（mock callout G）：本组件只认「节点+边+kind+组」，
 * 标签/顺序/并行/人门全部来自 LaneMapModel（引擎 template_topology 导出契约），
 * 组件内零 dev-lane 业务词——换模板换项目同一组件（fixture-two-step 对拍锚）。
 *
 * 图面语义（mock 屏③）：
 *   - 并行组=虚线框，成员纵排双道，任一成员 running 时框高亮（active）；
 *   - 人门（kind=human）=虚线圈 👤，到站时状态卡变蓝（蓝卡在 status-card）；
 *   - 条件段（optional）=虚节点+条件注记；
 *   - 轮次带=同段多轮逐轮一格，hover title=该轮证据/打回原因（数据=gen/phase）；
 *   - 不画返工弧：返工史归打回横幅与本组件 ×N 徽章，图面单向流
 *     （守卫：组件永不渲染 .wb-lm-arc，DOM 场景断言其恒零）；
 *   - 受阻着色（t260916-04）：当前受阻=实心红（data-vis=blocked，CSS 实底）；
 *     历史已解除受阻=完成色+「曾受阻」角标（.wb-lm-ever，黄点），节点/角标
 *     hover 出经过（何时受阻、何因、如何解除；数据=blockedHistory）。
 */
import { stageDisplayLabel } from './ui-labels.ts'
import { LANE_KIND_ICON } from './lane-map-model.ts'
import type { LaneMapModel, LaneNodeView, GateRunView, LaneGroupView } from './lane-map-model.ts'
import type { LaneBlockedHistory } from './lane-states.ts'

/* v5 time-share geometry (t261008-23, mock 261004 612-690):
 *   band width = MIN_PCT + flex x (weight / totalWeight) - the fixed floor
 *   keeps narrow stages readable; flex is shared by weight; an unstarted stage
 *   carries the nominal weight from the model (LANE_NOMINAL_MS) so the first
 *   stage cannot swallow the row.
 *   Parallel window: the main band spans the window; a partner band takes
 *   window x min(1, partner/window) (the mock's own clamp - a partner longer
 *   than the head never overflows); the window is a dashed box + the parallel
 *   mark.
 * The renderer only maps weight to width; all policy lives in LaneMapModel
 * (the generic-renderer promise is unchanged). */
const LM_MIN_PCT = 6

const LM_ICON: Record<string, string> = {
  done: '✓', running: '▶', blocked: '✗', 'awaiting-human': '✋', todo: '○', rework: '↺',
}

/** 解除方式人话（hover 经过第三拍「如何解除」；词表=lane-states resolvedBy）。 */
const RESOLVED_HOW: Record<string, string> = {
  rerun: 'stage rerun completed',
  advanced: 'workflow advanced to later stages',
  closed: 'ticket closed',
}

/** 「曾受阻」经过（何时受阻、何因、如何解除）：角标与节点 hover 共用一段话。 */
function everBlockedTitle(h: LaneBlockedHistory): string {
  const bits = [`Blocked ${h.passes.length}× before`]
  if (h.last.at) bits.push(h.last.at)
  if (h.last.reason) bits.push(h.last.reason)
  if (h.last.gen !== undefined) bits.push(`Round ${h.last.gen}`)
  if (h.resolved) {
    bits.push(`Resolved (${RESOLVED_HOW[h.resolvedBy ?? ''] || 'resolved'}${h.resolvedAt ? `: ${h.resolvedAt}` : ''})`)
  }
  return bits.join(' · ')
}

function roundTitle(nv: LaneNodeView, gen: number, state: string): string {
  const r = nv.rounds.find(x => x.gen === gen)
  if (!r) return `Round ${gen}`
  const bits = [`Round ${r.gen}`]
  if (r.at) bits.push(r.at)
  bits.push(state === 'rework' ? 'reworked' : state)
  if (r.reason) bits.push(r.reason)
  if (r.phase) bits.push(`Phase ${r.phase}`)
  if (r.handoffSummary) bits.push(r.handoffSummary)
  return bits.join(' · ')
}

/** 单个站点（主道与并行道内共用；道内竖排由父级 flex 方向控制）。 */
function LaneMapNode({ nv, inGroup }: { nv: LaneNodeView; inGroup: boolean }) {
  const n = nv.node
  const glyph = n.kind === 'human' ? LANE_KIND_ICON.human : (LM_ICON[nv.vis] ?? LM_ICON.todo)
  // t260916-04：历史已解除受阻=完成色+角标；当前受阻（未解除）不带角标（保守红）。
  const ever = nv.blockedHistory?.resolved === true
    && nv.blockedHistory.passes.length > 0 && nv.vis === 'done'
  const everTitle = ever && nv.blockedHistory ? everBlockedTitle(nv.blockedHistory) : ''
  const title = `${stageDisplayLabel(n.id, n.label)} · ${n.role} · ${n.kind}${n.optional ? ` · ${n.optional}` : ''}${everTitle ? ` · ${everTitle}` : ''}`
  return (
    <span
      className={`wb-lm-node${inGroup ? ' wb-lm-node-inlane' : ''}`}
      data-id={n.id}
      data-kind={n.kind}
      data-vis={nv.vis}
      data-ever-blocked={ever ? 'true' : undefined}
      title={title}
    >
      <i className="wb-lm-dot">{glyph}</i>
      <span className="wb-lm-name">
        {stageDisplayLabel(n.id, n.label)}
        {n.optional ? <em className="wb-lm-opt" title={`Conditional stage: ${n.optional}`}>{n.optional}</em> : null}
        {nv.badge ? <b className="wb-lm-badge" title={`${nv.rounds.length} rounds at this stage (rework history in the rework banner)`}>{nv.badge}</b> : null}
        {ever && nv.blockedHistory
          ? <i className="wb-lm-ever" title={everBlockedTitle(nv.blockedHistory)}>was blocked</i>
          : null}
      </span>
      {nv.rounds.length > 0 && (
        <span className="wb-lm-rounds">
          {nv.rounds.map(r => (
            <span
              key={r.gen}
              className="wb-lm-round"
              data-gen={r.gen}
              data-state={r.state}
              title={roundTitle(nv, r.gen, r.state)}
            >
              g{r.gen}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

/** Parallel group: dashed window + parallel mark + same-window bands (v5: the
 *  main band spans the window, every further band takes its own weight share
 *  clamped to the window - any lane count works). */
function LaneMapGroup({ model, groupId }: { model: LaneMapModel; groupId: string }) {
  const g = model.groups[groupId]
  if (!g) return null
  return (
    <span
      className="wb-lm-parallel"
      data-group={g.def.id}
      data-active={g.active ? 'true' : 'false'}
      data-done={g.allDone ? 'true' : 'false'}
      data-window-ms={g.windowMs}
    >
      <span className="wb-lm-plabel">
        Parallel · {g.members.length} lanes <i className="wb-lm-par-mark" aria-label="parallel">∥</i>
      </span>
      <span className="wb-lm-branches">
        {g.members.map((m, i) => (
          <span
            key={m.node.id}
            className="wb-lm-band"
            data-band={i === 0 ? 'main' : 'partner'}
            style={i === 0 ? undefined : { width: `${lmBandPct(m.weightMs, g.windowMs)}%` }}
          >
            <LaneMapNode nv={m} inGroup />
          </span>
        ))}
      </span>
    </span>
  )
}

/** Partner band width (%): min(1, partner/window) x 100 (the mock line ~677 clamp). */
function lmBandPct(partnerMs: number, windowMs: number): number {
  if (!(windowMs > 0)) return 100
  return Math.min(1, partnerMs / windowMs) * 100
}

/** v5 time-share main lane: band width = MIN_PCT + flex x (weight/totalWeight)
 *  (the mock's own formula). */
function lmWidths(model: LaneMapModel): Array<{ id: string; weightMs: number; pct: number }> {
  const weights = model.items.map(it => ({
    id: it.id,
    weightMs: it.kind === 'group' ? (model.groups[it.id]?.windowMs ?? 0) : (model.nodes[it.id]?.weightMs ?? 0),
  }))
  const total = weights.reduce((a, r) => a + r.weightMs, 0)
  const flex = 100 - LM_MIN_PCT * weights.length
  return weights.map(w => ({
    ...w,
    pct: LM_MIN_PCT + (total > 0 ? flex * (w.weightMs / total) : flex / Math.max(1, weights.length)),
  }))
}

/**
 * 真泳道图。model=null 时调用方不渲染本组件（回落现行线性步骤条）。
 */
export function LaneMap({ model }: { model: LaneMapModel }) {
  const widths = lmWidths(model)
  const pctOf = new Map(widths.map(w => [w.id, w]))
  return (
    <div className="wb-lanemap" data-template={model.topology.template}>
      {model.items.map(item => {
        const w = pctOf.get(item.id)
        return (
          <span
            key={item.id}
            className="wb-lm-item"
            data-weight-ms={w?.weightMs}
            style={w ? { width: `${w.pct.toFixed(2)}%` } : undefined}
          >
            {item.kind === 'group'
              ? <LaneMapGroup model={model} groupId={item.id} />
              : <LaneMapNode nv={model.nodes[item.id]} inGroup={false} />}
          </span>
        )
      })}
    </div>
  )
}

/**
 * 检查明细区（mock ① ck-rows）：gate_runs 逐轮逐条 ✓/✗ + item + detail，
 * 原始输出 details 折叠可展开；红行带文件点名与下一步（与状态卡同一
 * blocked_detail/gate_runs 数据源，天然联动）。最新一轮在最上，最多显 3 轮。
 */
export function ChecksDetail({ runs, cap = 3 }: { runs: GateRunView[]; cap?: number }) {
  if (!runs || runs.length === 0) return null
  return (
    <div className="wb-checks">
      <div className="wb-checks-ttl">Check details · {runs.length} gate runs (engine structured data verbatim; click a row for raw output)</div>
      {runs.slice(0, cap).map((run, i) => (
        <div key={`${run.stage}-${i}`} className="wb-ck-run" data-stage={run.stage} data-green={run.green ? 'true' : 'false'}>
          <div className="wb-ck-run-head">
            <b>{run.label}</b>
            {run.gen !== undefined ? <span className="wb-ck-run-gen">Round {run.gen}</span> : null}
            <span className="wb-ck-run-verdict">{run.green ? 'all green' : `${run.redCount} red`}</span>
          </div>
          {run.rows.map((row, j) => (
            <details key={j} className="wb-ck-row" data-green={row.green ? 'true' : 'false'}>
              <summary>
                <b className={`wb-ck-mark ${row.green ? 'g' : 'r'}`}>{row.green ? '✓' : '✗'}</b>
                <span className="wb-ck-name">{row.item || row.checkId || '(unnamed check)'}</span>
                {row.detail ? <span className="wb-ck-detail">{row.detail}</span> : null}
              </summary>
              <div className="wb-ck-more">
                {row.checkId ? <div>check_id: {row.checkId}</div> : null}
                {row.reasonCode ? <div>reason_code: {row.reasonCode}</div> : null}
                {row.files && row.files.length > 0 ? (
                  <div>Files: {row.files.join(', ')}</div>
                ) : null}
                {row.nextAction ? <div>Next: {row.nextAction}</div> : null}
                {row.detail ? <pre>{row.detail}</pre> : null}
              </div>
            </details>
          ))}
        </div>
      ))}
    </div>
  )
}
