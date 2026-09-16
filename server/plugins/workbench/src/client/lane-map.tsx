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
import { LANE_KIND_ICON } from './lane-map-model.ts'
import type { LaneMapModel, LaneNodeView, GateRunView } from './lane-map-model.ts'
import type { LaneBlockedHistory } from './lane-states.ts'

const LM_ICON: Record<string, string> = {
  done: '✓', running: '▶', blocked: '✗', 'awaiting-human': '✋', todo: '○', rework: '↺',
}

/** 解除方式人话（hover 经过第三拍「如何解除」；词表=lane-states resolvedBy）。 */
const RESOLVED_HOW: Record<string, string> = {
  rerun: '本段重跑完成',
  advanced: '工作流已推进至后续段',
  closed: '工单已收口',
}

/** 「曾受阻」经过（何时受阻、何因、如何解除）：角标与节点 hover 共用一段话。 */
function everBlockedTitle(h: LaneBlockedHistory): string {
  const bits = [`曾受阻 ${h.passes.length} 次`]
  if (h.last.at) bits.push(h.last.at)
  if (h.last.reason) bits.push(h.last.reason)
  if (h.last.gen !== undefined) bits.push(`第${h.last.gen}轮`)
  if (h.resolved) {
    bits.push(`已解除（${RESOLVED_HOW[h.resolvedBy ?? ''] || '已解除'}${h.resolvedAt ? `：${h.resolvedAt}` : ''}）`)
  }
  return bits.join(' · ')
}

function roundTitle(nv: LaneNodeView, gen: number, state: string): string {
  const r = nv.rounds.find(x => x.gen === gen)
  if (!r) return `第${gen}轮`
  const bits = [`第${r.gen}轮`]
  if (r.at) bits.push(r.at)
  bits.push(state === 'rework' ? '被打回' : state)
  if (r.reason) bits.push(r.reason)
  if (r.phase) bits.push(`相位 ${r.phase}`)
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
  const title = `${n.label} · ${n.role} · ${n.kind}${n.optional ? ` · ${n.optional}` : ''}${everTitle ? ` · ${everTitle}` : ''}`
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
        {n.label}
        {n.optional ? <em className="wb-lm-opt" title={`条件段：${n.optional}`}>{n.optional}</em> : null}
        {nv.badge ? <b className="wb-lm-badge" title={`该段共 ${nv.rounds.length} 轮（返工史见打回横幅）`}>{nv.badge}</b> : null}
        {ever && nv.blockedHistory
          ? <i className="wb-lm-ever" title={everBlockedTitle(nv.blockedHistory)}>曾受阻</i>
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

/** 并行组：虚线框 + 纵排双道（几道都行，mock ④「任意形状」）。 */
function LaneMapGroup({ model, groupId }: { model: LaneMapModel; groupId: string }) {
  const g = model.groups[groupId]
  if (!g) return null
  return (
    <span className="wb-lm-parallel" data-group={g.def.id} data-active={g.active ? 'true' : 'false'} data-done={g.allDone ? 'true' : 'false'}>
      <span className="wb-lm-plabel">并行 · {g.members.length} 道</span>
      <span className="wb-lm-branches">
        {g.members.map(m => <LaneMapNode key={m.node.id} nv={m} inGroup />)}
      </span>
    </span>
  )
}

/**
 * 真泳道图。model=null 时调用方不渲染本组件（回落现行线性步骤条）。
 */
export function LaneMap({ model }: { model: LaneMapModel }) {
  return (
    <div className="wb-lanemap" data-template={model.topology.template}>
      {model.items.map(item => (
        item.kind === 'group'
          ? (
            <span key={item.id} className="wb-lm-item">
              <LaneMapGroup model={model} groupId={item.id} />
            </span>
          )
          : (
            <span key={item.id} className="wb-lm-item">
              <LaneMapNode nv={model.nodes[item.id]} inGroup={false} />
            </span>
          )
      ))}
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
      <div className="wb-checks-ttl">检查明细 · {runs.length} 轮门记录（引擎结构化数据直译，点行展开原始输出）</div>
      {runs.slice(0, cap).map((run, i) => (
        <div key={`${run.stage}-${i}`} className="wb-ck-run" data-stage={run.stage} data-green={run.green ? 'true' : 'false'}>
          <div className="wb-ck-run-head">
            <b>{run.label}</b>
            {run.gen !== undefined ? <span className="wb-ck-run-gen">第 {run.gen} 轮</span> : null}
            <span className="wb-ck-run-verdict">{run.green ? '全绿' : `${run.redCount} 项红灯`}</span>
          </div>
          {run.rows.map((row, j) => (
            <details key={j} className="wb-ck-row" data-green={row.green ? 'true' : 'false'}>
              <summary>
                <b className={`wb-ck-mark ${row.green ? 'g' : 'r'}`}>{row.green ? '✓' : '✗'}</b>
                <span className="wb-ck-name">{row.item || row.checkId || '（未命名检查项）'}</span>
                {row.detail ? <span className="wb-ck-detail">{row.detail}</span> : null}
              </summary>
              <div className="wb-ck-more">
                {row.checkId ? <div>check_id：{row.checkId}</div> : null}
                {row.reasonCode ? <div>reason_code：{row.reasonCode}</div> : null}
                {row.files && row.files.length > 0 ? (
                  <div>文件：{row.files.join('、')}</div>
                ) : null}
                {row.nextAction ? <div>下一步：{row.nextAction}</div> : null}
                {row.detail ? <pre>{row.detail}</pre> : null}
              </div>
            </details>
          ))}
        </div>
      ))}
    </div>
  )
}
