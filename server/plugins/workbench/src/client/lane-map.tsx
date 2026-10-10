/**
 * lane-map.tsx —— 真泳道图（拓扑驱动）+ 检查明细区组件（t260915-05，mock ①③④）。
 *
 * 渲染器通用性承诺（mock callout G）：本组件只认「节点+边+kind+组」，
 * 标签/顺序/并行/人门全部来自 LaneMapModel（引擎 template_topology 导出契约），
 * 组件内零 dev-lane 业务词——换模板换项目同一组件（fixture-two-step 对拍锚）。
 *
 * Scene (t261009-53, a value-for-value copy of the mock's laneMap(t) in
 * notes/discussions/261004-concurrency-limit-mock.html, design doc 261004
 * section 7.6 criteria 1-8):
 *   - every main-track segment = a slim bar (rect h 12, rx 3) on ONE shared
 *     baseline; width = its time share (the v5 weight formula is untouched,
 *     t261008-23 does not regress); a segment is no longer a filled block;
 *   - labels float above the pipe in two alternating levels (baseline-4 /
 *     baseline-13), middle-anchored on their bar, clamped into the canvas,
 *     with a dotted leader down to the bar top; duration and rounds ride in
 *     the same caption (`38m · ×2`; criterion 7: rework is carried by ×n -
 *     the round chips are retired, their evidence folded into the hover title);
 *   - the human gate diamond sits at the LEFT head of the bar (the mock's
 *     7px path), not inside a box;
 *   - the parallel partner bar sits on a second track below, at its own width,
 *     inside a dashed window that surrounds BOTH tracks, with the ∥ mark;
 *   - state is carried by fill (criterion 3): done = 22% tint of the kind
 *     colour, current = solid + the now cursor (a dashed vertical line spanning
 *     both tracks), not started = grey, skipped = dashed empty box, blocked =
 *     solid red (t260916-04 rule); ever-blocked = an inline amber badge in the
 *     label (title carries the story; the t260916-04 face stays);
 *   - header / legend / time axis rows untouched (t261009-22 faces all kept).
 */
import { laneMapScene } from './lane-map-model.ts'
import type { LaneMapModel, GateRunView, LaneScene } from './lane-map-model.ts'

/** Scene -> SVG (the truth is laneMapScene; this only draws). Public anchor
 *  contract (DOM scenarios assert on these data-* keys, not on internals):
 *  g.wb-lm-node[data-id/kind/vis/skipped/now], g.wb-lm-band[data-band=partner],
 *  rect.wb-lm-parallel[data-group], text.wb-lm-label, tspan.wb-lm-opt /
 *  wb-lm-round / wb-lm-ever, path.wb-lm-diamond, line.wb-lm-cursor. */
export function LaneSceneSvg({ scene }: { scene: LaneScene }) {
  return (
    <svg
      className="wb-lm-svg"
      viewBox={`0 0 ${scene.width} ${scene.height}`}
      preserveAspectRatio="xMinYMin meet"
      role="img"
      aria-label="lane map"
    >
      {scene.windows.map(wn => (
        <rect
          key={`win-${wn.groupId}`}
          className="wb-lm-parallel"
          data-group={wn.groupId}
          data-active={wn.active ? 'true' : 'false'}
          data-done={wn.allDone ? 'true' : 'false'}
          data-window-ms={wn.windowMs}
          x={wn.x}
          y={wn.y}
          width={wn.w}
          height={wn.h}
          rx={6}
          fill="none"
          stroke="var(--dsw-derive-border,#8c959f)"
          strokeDasharray="3 3"
        />
      ))}
      {scene.leaders.map((l, i) => (
        <line
          key={`lead-${i}`}
          className="wb-lm-leader"
          x1={l.x}
          y1={l.y1}
          x2={l.x}
          y2={l.y2}
          stroke="var(--dsw-derive-border,#d0d7de)"
          strokeDasharray="1 2"
        />
      ))}
      {scene.bars.map(b => (
        <g
          key={b.id}
          className={`wb-lm-node${b.track === 'partner' ? ' wb-lm-band' : ''}`}
          data-id={b.stageId}
          data-band={b.track === 'partner' ? 'partner' : undefined}
          data-kind={b.kind ?? undefined}
          data-vis={b.vis ?? undefined}
          data-skipped={b.skipped ? 'true' : undefined}
          data-now={b.now ? 'true' : undefined}
          data-ever-blocked={b.ever ? 'true' : undefined}
          data-stage={b.stageId}
          data-weight-ms={b.weightMs}
          title={b.title}
        >
          <title>{b.title}</title>
          <rect
            x={b.x}
            y={b.y}
            width={b.w}
            height={b.h}
            rx={3}
            fill={b.fill}
            fillOpacity={b.fillOpacity}
            stroke={b.dashed ? 'var(--dsw-derive-border,#d0d7de)' : undefined}
            strokeDasharray={b.dashed ? '3 2' : undefined}
          />
          {b.diamond && b.track === 'main'
            ? (
                <path
                  className="wb-lm-diamond"
                  /* absolute coordinates (the DOM probe parses the d string
                   * pairwise; the mock's relative form carries the same shape) */
                  d={`M${b.x + 1.5} ${b.y + b.h / 2} L${b.x + 5} ${b.y + b.h / 2 + 3.5} L${b.x + 8.5} ${b.y + b.h / 2} L${b.x + 5} ${b.y + b.h / 2 - 3.5} Z`}
                  fill="var(--dsw-derive-canvas,#fff)"
                  stroke="var(--dsw-derive-warn,#bf8700)"
                />
              )
            : null}
        </g>
      ))}
      {scene.parMarks.map((p, i) => (
        <text key={`par-${i}`} className="wb-lm-par-mark" x={p.x} y={p.y} fontSize="8" fill="var(--dsw-derive-muted,#8c959f)">∥</text>
      ))}
      {scene.labels.map((l, i) => (
        <text
          key={`lab-${i}`}
          className={`wb-lm-label${l.now ? ' wb-lm-label-now' : ''}${l.track === 'partner' ? ' wb-lm-plabel' : ''}`}
          x={l.x}
          y={l.y}
          textAnchor={l.anchor}
        >
          {l.text}
          {l.opt ? <tspan className="wb-lm-opt">{` ${l.opt}`}</tspan> : null}
          {l.roundBadge ? <tspan className="wb-lm-round">{` · ${l.roundBadge}`}</tspan> : null}
          {l.everTitle ? <tspan className="wb-lm-ever" title={l.everTitle}> was blocked</tspan> : null}
        </text>
      ))}
      {scene.cursor
        ? (
            <line
              className="wb-lm-cursor"
              x1={scene.cursor.x}
              y1={scene.cursor.y1}
              x2={scene.cursor.x}
              y2={scene.cursor.y2}
              stroke="var(--dsw-derive-accent,#0969da)"
              strokeWidth={1.5}
              strokeDasharray="3 2"
            />
          )
        : null}
    </svg>
  )
}

/**
 * 真泳道图。model=null 时调用方不渲染本组件（回落现行线性步骤条）。
 *
 * t261009-22 (mock 261004 criteria 2/3/5/6): the header row = topology name
 * (degrades to "N stages" without one - no business words pasted here, review
 * comment 1) + the three-swatch kind legend + `elapsed ... · now at ...`
 * (plus `(waiting for you)` at the arrival human gate); the footer time axis
 * shows start/end clocks at the segment scale (same width truth as the
 * segments), and renders the line only when clocks are missing - never a
 * made-up time. t261009-53: the segments themselves are the mock's slim pipe
 * (see laneMapScene).
 */
export function LaneMap({ model }: { model: LaneMapModel }) {
  const scene = laneMapScene(model)
  const h = model.header
  const groupCount = Object.keys(model.groups).length
  return (
    <div className="wb-lanemap" data-template={model.topology.template} data-testid="detail-lane-map">
      <div className="wb-lm-head" data-testid="lane-map-header">
        <b>{model.topology.name || `${model.items.length} stages`}</b>
        <span>{model.items.length} stages{groupCount > 0 ? ` · ${groupCount} parallel` : ''}</span>
        <span className="wb-lm-lkind" aria-label="legend">
          <i className="wb-lm-k k-agent" />agent<i className="wb-lm-k k-gate" />gate<i className="wb-lm-k k-human" />you
        </span>
        <span className="wb-lm-lsum" data-testid="lane-map-summary">
          elapsed {h.elapsedText} · now at <b>{h.nowLabel}</b>{h.waitingForYou ? ' (waiting for you)' : ''}
        </span>
      </div>
      <LaneSceneSvg scene={scene} />
      <div className="wb-lm-axis" data-testid="lane-map-axis" data-clock={h.startClock ? 'true' : 'false'}>
        <span className="wb-lm-axis-t">{h.startClock ?? ''}</span>
        <i className="wb-lm-axis-line" aria-hidden="true" />
        <span className="wb-lm-axis-t">{h.endClock ?? ''}</span>
      </div>
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
