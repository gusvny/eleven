/**
 * metrics.tsx —— metrics 度量面板（t260902-05 中 pane 化）。
 *
 * 版式（UI 规划 §3 骨架 + t260902-05 反馈②）：不再全幅——挂在侧栏中列
 * （.wb-sb-right，position:relative）内的覆盖层，inset:0 随中列自适应；
 * 头部=标题/筛选行/口径ⓘ/✕；KPI 条四卡常驻；Tab 条四 tab 全开放（后端四视图
 * 本就同实现，t260902-05③）；主图（时间视图柱↔饼双形态，其余视图单形态）；副图两格。
 *
 * 交互纪律（create_plan gen2 决策 7/9 + t260902-05 修订）：
 * - Esc/✕ 关闭；打开才 fetch，关闭 unmount 释放全部 echarts 实例（adapter release）。
 * - 滚动：面板容器自身 overflow-y:auto（中 pane 不锁全页 body 滚动——全幅时代的
 *   body overflow 锁已随中 pane 化移除）。
 * - 焦点管理（最小实现）：open 移入面板容器，close 归还「度量」钮（入口组件保证 ref）。
 * - 不自动轮询：打开/参数变更各 fetch 一次，同参数切 tab/形态不重复 fetch；
 *   手动「刷新」钮重新取数。board 轮询与面板数据通道独立、互不影响。
 * - 下钻（副2 Top 票 stackBar）：先关面板（状态已持久化，重开恢复）再走父组件
 *   既有 handleTicketClick 链路开详情抽屉——面板与抽屉不同时在场，z-index 95 防御性。
 * - 空态显式（t260902-05⑥）：donut/bar 数据全零或 spec 缺失时不渲染空画布，
 *   显「窗口内无可绘图数据」文案——不静默（用户看到的「饼 block 无 chart」白块）。
 *
 * 纯逻辑全在 metrics-model.ts（node 直测）；本文件只渲染与交互时序。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildTimeDonut, donutIsBlank, kpiCards, loadPanelState, metricsQueryString, savePanelState,
  sanitizeMetricsResponse, specIsBlank, PANEL_WINDOWS,
  type ChartSpec, type DonutInput, type MetricsResponse, type PanelState,
} from './metrics-model.ts'
import { donut, renderSpec, type ChartHandle } from './metrics-charts.ts'
import { DERIVE_TOKENS_CSS } from './theme';

const API = '/sandbar-workbench/api/wf'

const CSS = `${DERIVE_TOKENS_CSS}
.wb-m{position:absolute;inset:0;background:var(--dsw-derive-surface,#f6f8fa);z-index:95;display:flex;flex-direction:column;font-size:13px;color:var(--dsw-derive-fg,#1f2328)}
.wb-m-head{display:flex;align-items:center;gap:10px;padding:10px 16px;background:var(--dsw-derive-canvas,#ffffff);border-bottom:1px solid var(--dsw-derive-border,#d0d7de);flex-wrap:wrap}
.wb-m-title{font-size:15px;font-weight:600}
.wb-m-head select{font:inherit;font-size:12px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;padding:4px 8px}
.wb-m-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:12px 16px 0}
.wb-m-kpi{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:10px 14px}
.wb-m-kpi .lb{font-size:11px;color:var(--dsw-derive-muted,#57606a)}
.wb-m-kpi .vl{font-size:20px;font-weight:600;margin-top:2px}
.wb-m-tabs{display:flex;gap:2px;padding:12px 16px 0;border-bottom:1px solid var(--dsw-derive-border,#d0d7de)}
.wb-m-tab{padding:6px 14px;font-size:13px;cursor:pointer;border:1px solid transparent;border-bottom:none;color:var(--dsw-derive-muted,#57606a)}
.wb-m-tab[data-on=true]{color:var(--dsw-derive-accent,#0969da);font-weight:600;border-color:var(--dsw-derive-border,#d0d7de);border-bottom:1px solid var(--dsw-derive-surface,#f6f8fa);margin-bottom:-1px;background:var(--dsw-derive-canvas,#ffffff)}
.wb-m-tab[data-dis=true]{color:var(--dsw-derive-muted,#8c959f);cursor:not-allowed}
.wb-m-body{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:12px}
.wb-m-main{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:12px 14px}
.wb-m-main-head{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.wb-m-main-head .t{font-size:13px;font-weight:600}
.wb-m-shape{margin-left:auto;display:flex;gap:2px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;overflow:hidden}
.wb-m-shape button{font:inherit;font-size:12px;border:none;background:var(--dsw-derive-canvas,#ffffff);padding:3px 10px;cursor:pointer;color:var(--dsw-derive-muted,#57606a)}
.wb-m-shape button[data-on=true]{background:var(--dsw-derive-accent,#0969da);color:var(--dsw-derive-canvas,#ffffff)}
.wb-m-degrade{font-size:11px;color:var(--dsw-derive-warn,#9a6700);background:var(--dsw-derive-warn-bg,#fff8c5);border-radius:6px;padding:2px 8px}
.wb-m-chart{width:100%;height:340px}
.wb-m-chart-sm{width:100%;height:260px}
.wb-m-subs{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.wb-m-sub{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:10px 14px}
.wb-m-sub .t{font-size:12px;font-weight:600;margin-bottom:4px}
.wb-m-donut-wrap{position:relative}
.wb-m-donut-center{position:absolute;left:0;right:0;top:38%;text-align:center;pointer-events:none}
.wb-m-donut-center .n{font-size:20px;font-weight:600}
.wb-m-donut-center .s{font-size:11px;color:var(--dsw-derive-warn,#9a6700)}
.wb-m-empty{padding:40px 16px;text-align:center;color:var(--dsw-derive-muted,#57606a)}
.wb-m-x{font:inherit;font-size:14px;border:none;background:none;cursor:pointer;color:var(--dsw-derive-muted,#57606a);padding:2px 6px}
.wb-m-x:hover{color:var(--dsw-derive-danger,#cf222e)}
.wb-m-refresh{font:inherit;font-size:12px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;background:var(--dsw-derive-canvas,#ffffff);padding:3px 10px;cursor:pointer;color:var(--dsw-derive-fg,#1f2328)}
.wb-m-hint{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
`

/** 图表挂载盒：chart/donut 变更或卸载时释放旧实例（adapter release 幂等）。 */
function ChartMount(props: { spec?: ChartSpec | null; donutInput?: DonutInput | null; onPick?: (name: string) => void; small?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    let handle: ChartHandle | null = null
    if (props.donutInput) handle = donut({ mount: el, donut: props.donutInput })
    else if (props.spec) handle = renderSpec({ mount: el, spec: props.spec, onPick: props.onPick })
    return () => { handle?.release() }
  }, [props.spec, props.donutInput, props.onPick])
  return <div ref={ref} className={props.small ? 'wb-m-chart-sm' : 'wb-m-chart'} />
}

export function MetricsPanel(props: {
  /** 关闭面板（Esc/✕）。 */
  onClose: () => void
  /** 下钻：关面板后由父组件走 handleTicketClick 开详情抽屉。 */
  onPickTicket: (ticketId: string) => void
  /** 「度量」钮 DOM：关闭时焦点归还。 */
  openerRef?: { current: HTMLElement | null }
}) {
  const [state, setState] = useState<PanelState>(loadPanelState)
  const [data, setData] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [workflows, setWorkflows] = useState<unknown[]>([])
  /** 项目注册表（GET /wf/projects）：启用项目下拉（t260904-04，KI-042）。 */
  const [projects, setProjects] = useState<{ key: string; name?: string }[]>([])
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [nonce, setNonce] = useState(0)

  /* 状态持久化：每次变更落 localStorage（容错在 model 层）。 */
  useEffect(() => { savePanelState(state) }, [state])

  /* Esc 关闭（捕获阶段；epics modal 无此先例，本单自带——gen2 决策 7）。 */
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') props.onClose() }
    document.addEventListener('keydown', h, true)
    return () => { document.removeEventListener('keydown', h, true) }
  }, [props.onClose])

  /* 中 pane 化（t260902-05②）：不锁 body 滚动，面板容器自身滚动（CSS overflow-y）。 */

  /* 焦点管理（最小实现）：移入面板容器；关闭时归还「度量」钮。 */
  useEffect(() => { rootRef.current?.focus() }, [])
  useEffect(() => () => { props.openerRef?.current?.focus() }, [props.openerRef])

  /* 模板链 + 项目注册表（t260904-04）：workflows 仍取全量后客户端只取 dev-lane 的
     stages（饼形态模板链需要；选择器已退役、模板恒 dev-lane，不加后端按模板取参
     的契约面）。立项代号取数死代码已删（原 ${API}/epics 恒 404，KI-042：死路由
     不留静默吞错的 fetch）。projects 取数失败=降级只剩「项目：默认」（活路由的
     瞬时失败有意静默，与 epics 死代码整删口径不同；重开面板即重试）。 */
  useEffect(() => {
    const ac = new AbortController()
    ;(async () => {
      try {
        const w = await fetch(`${API}/workflows`, { signal: ac.signal }).then(r => r.json())
        if (!ac.signal.aborted) setWorkflows((w?.result?.workflows ?? (Array.isArray(w?.result) ? w.result : [])) as unknown[])
      } catch { /* 静默：模板缺失走饼形态降级 */ }
      try {
        const p = await fetch(`${API}/projects`, { signal: ac.signal }).then(r => r.json())
        const list = (p?.result?.projects ?? p?.projects ?? []) as unknown[]
        if (!ac.signal.aborted) {
          setProjects(list
            .map((x: any) => ({ key: typeof x?.key === 'string' ? x.key : '', name: typeof x?.name === 'string' ? x.name : undefined }))
            .filter((x: { key: string }) => x.key.length > 0))
        }
      } catch { /* 静默：项目下拉退化为「默认」 */ }
    })()
    return () => { ac.abort() }
  }, [])

  /* 数据 fetch（t260903-09 cache-first 两段式）：先 mode=fast 只读缓存快照——
     有缓存毫秒级先渲染（角标「缓存快照 · 刷新中」），随后台全量替换摘角标；
     全量失败保留快照+降级说明不白屏。冷缓存快照为空（reason 显式 fast 跳过），
     加载态持续到全量回来——不假快。打开/参数变更/手动刷新各一轮；同参数切
     形态不重复取（shape 不进查询串，切柱↔饼零请求）。 */
  const [refreshing, setRefreshing] = useState(false)
  const metricsQuery = metricsQueryString(state)
  useEffect(() => {
    const ac = new AbortController()
    setLoading(true)
    setRefreshing(true)
    ;(async () => {
      try {
        const fast = await fetch(`${API}/metrics?${metricsQuery}&mode=fast`, { signal: ac.signal }).then(r => r.json())
        if (!ac.signal.aborted) {
          setData(sanitizeMetricsResponse(fast))
          setLoading(false) // 快照先上台（可能为空态，全量在后台）
        }
      } catch { /* fast 失败不打扰用户，直接等全量 */ }
      try {
        const res = await fetch(`${API}/metrics?${metricsQuery}`, { signal: ac.signal })
        const body = await res.json()
        if (!ac.signal.aborted) setData(sanitizeMetricsResponse(body))
      } catch (err) {
        if (!ac.signal.aborted) {
          const msg = err instanceof Error && err.name === 'AbortError' ? '' : String(err instanceof Error ? err.message : err)
          // 全量失败：已有快照则保留快照+降级说明（不白屏），无快照才报错
          setData(prev => prev !== null && prev.error === null && prev.cache?.status === 'stale'
            ? { ...prev, reason: `全量刷新失败（保留缓存快照）：${msg || '网络错误'}` }
            : sanitizeMetricsResponse({ error: `请求失败：${msg || '网络错误'}` }))
        }
      } finally {
        if (!ac.signal.aborted) {
          setLoading(false)
          setRefreshing(false)
        }
      }
    })()
    return () => { ac.abort() }
  }, [metricsQuery, nonce])

  const templateStages = useMemo(() => {
    const wf = (workflows as any[]).find(w => w?.id === state.template)
    return wf?.stages ?? null
  }, [workflows, state.template])

  const donutInput: DonutInput | null = useMemo(
    () => (data && state.shape === 'donut' && state.view === 'time')
      ? buildTimeDonut(data.primary, data.secondaries[0] ?? null, templateStages)
      : null,
    [data, state.shape, state.view, templateStages],
  )

  /* 下钻（副2 Top 票）：先关面板再开抽屉——面板状态已持久化，重开恢复（gen2 决策 9(a)）。
     依赖收窄到父级回调本身，避免父组件重渲染导致副图反复重建。 */
  const pickTicket = useCallback((ticketId: string) => {
    props.onClose()
    props.onPickTicket(ticketId)
  }, [props.onClose, props.onPickTicket])

  const cards = useMemo(() => (data ? kpiCards(data.kpis) : []), [data])
  const cacheStatus = data?.cache?.status
  const cacheTitle = `时长 v1 = handoff 近似（v2 = 08 终态精确）；token 不含 cacheRead、按窗口内票的全生涯 in+out 合计（口径对账见 integration/t260902-05）；饼图 = 全窗口合计占比（单票平均口径待契约 bump）；归档口径交付含多提交（预解/记账提交计入，行数可能高于 squash 真值，见契约增补段）；缓存 ${typeof cacheStatus === 'string' ? cacheStatus : '—'} · source_version ${typeof data?.cache?.source_version === 'string' ? data.cache.source_version : '—'}${data?.generatedAt ? ` · ${data.generatedAt}` : ''}`
  const isTime = state.view === 'time'

  /* 四 tab（t260902-05③）：后端四视图同实现，全部开放。 */
  const TABS: { key: PanelState['view']; label: string }[] = [
    { key: 'time', label: '时间' },
    { key: 'delivery', label: '交付' },
    { key: 'token', label: 'Token' },
    { key: 'health', label: '系统健康' },
  ]

  /* 空态显式（t260902-05⑥）：spec/donut 全零或缺失 → 文案，不渲染空白画布。 */
  const blankText = '窗口内无可绘图数据（或聚合被 SKIP，见降级说明）。'

  return (
    <div ref={rootRef} className="wb-m" tabIndex={-1} role="dialog" aria-label="度量面板">
      <style>{CSS}</style>
      {/* 头部：标题/筛选/口径ⓘ/刷新/✕（§3 骨架第一行） */}
      <div className="wb-m-head">
        <span className="wb-m-title">度量</span>
        <select value={state.window} title="时间窗"
          onChange={e => setState(s => ({ ...s, window: e.target.value }))}>
          {PANEL_WINDOWS.map(w => <option key={w} value={w}>{w}</option>)}
        </select>
        <select value={state.project} title="项目（多项目注册表筛选；默认=后端缺省项目）"
          onChange={e => setState(s => ({ ...s, project: e.target.value }))}>
          <option value="">项目：默认</option>
          {projects.map(p => <option key={p.key} value={p.key}>{p.name ? `项目：${p.name}（${p.key}）` : `项目：${p.key}`}</option>)}
        </select>
        {/* 泳道（模板）与立项下拉已退役（t260904-04 宿主令，KI-042）：模板恒 dev-lane、
            立项恒 all，由 loadPanelState 归一常量透传后端，不渲染选择器。 */}
        <span className="wb-m-hint" title={cacheTitle}>口径ⓘ</span>
        {data?.cache?.status === 'stale' && (
          <span className="wb-m-degrade" title="当前展示的是缓存快照（可能缺最新票），后台全量刷新中，完成后自动替换">缓存快照 · 刷新中</span>
        )}
        <button className="wb-m-refresh" onClick={() => { setNonce(n => n + 1) }}>刷 新</button>
        <button className="wb-m-x" title="关闭（Esc）" onClick={props.onClose}>✕</button>
      </div>

      {/* KPI 条：四卡常驻（§3 第二行，任何 tab 都显示） */}
      <div className="wb-m-kpis">
        {cards.map(c => (
          <div className="wb-m-kpi" key={c.label} title={c.title}>
            <div className="lb">{c.label}</div>
            <div className="vl">{c.value}</div>
          </div>
        ))}
      </div>

      {/* Tab 条：四 tab 全开放（t260902-05③，后端 view=time|delivery|token|health 同实现） */}
      <div className="wb-m-tabs">
        {TABS.map(t => (
          <span key={t.key} className="wb-m-tab" data-on={state.view === t.key}
            onClick={() => setState(s => ({ ...s, view: t.key }))}>{t.label}</span>
        ))}
      </div>

      <div className="wb-m-body">
        {loading && <div className="wb-m-empty">加载中…</div>}
        {!loading && data?.error && <div className="wb-m-empty">{data.error}</div>}
        {/* 快照空态不显「无数据」（后台全量在途，refreshing=true 时保持加载语义） */}
        {!loading && refreshing && !data?.error && <div className="wb-m-empty">缓存快照已上台，全量刷新中…</div>}
        {!loading && !refreshing && !data?.error && !data?.primary && data?.secondaries.length === 0 && (
          <div className="wb-m-empty">窗口内无可聚合数据（或聚合被 SKIP）。</div>
        )}
        {!loading && !data?.error && data?.reason && (
          <div className="wb-m-degrade" title={data.reason}>降级说明：{data.reason.length > 120 ? `${data.reason.slice(0, 120)}…` : data.reason}</div>
        )}
        {!loading && !data?.error && data && (data.primary || data.secondaries.length > 0) && (
          <>
            {/* 主图：时间视图柱↔饼双形态；其余视图按后端 primary 单形态渲染（全零→空态） */}
            <div className="wb-m-main">
              <div className="wb-m-main-head">
                <span className="t">{isTime && state.shape === 'donut' ? '时间去哪了' : (data.primary?.title ?? '')}</span>
                {isTime && donutInput?.degraded && <span className="wb-m-degrade" title="模板数据缺失，退化为「人审 vs 机器」二分环">模板缺失 · 已降级</span>}
                {isTime && (
                  <span className="wb-m-shape">
                    <button data-on={state.shape === 'bar'} title="柱形态（stage 时长合计）"
                      onClick={() => setState(s => ({ ...s, shape: 'bar' }))}>柱</button>
                    <button data-on={state.shape === 'donut'} title="饼形态（占比环形，人审等待独立橙块）"
                      onClick={() => setState(s => ({ ...s, shape: 'donut' }))}>饼</button>
                  </span>
                )}
              </div>
              {isTime && state.shape === 'donut' && donutInput
                ? (donutIsBlank(donutInput)
                  ? <div className="wb-m-empty">{blankText}</div>
                  : (
                    <div className="wb-m-donut-wrap">
                      <ChartMount donutInput={donutInput} />
                      <div className="wb-m-donut-center">
                        <div className="n">{donutInput.totalMin} 分钟</div>
                        <div className="s">其中人等 {Math.round(donutInput.humanRatio * 100)}%</div>
                      </div>
                    </div>
                  ))
                : (specIsBlank(data.primary)
                  ? <div className="wb-m-empty">{blankText}</div>
                  : <ChartMount spec={data.primary!} />)}
            </div>
            {/* 副图两格（§3 骨架）：各视图后端 secondaries；spec 全零→空态（t260902-05⑥，
                用户投诉的「时间去哪了」白块即 time 视图副1 donut 全零路径）。
                副2 Top 票（票 id 下钻）保留 pickTicket。 */}
            <div className="wb-m-subs">
              {data.secondaries.map((spec, i) => (
                <div className="wb-m-sub" key={i}>
                  <div className="t">{spec.title}</div>
                  {specIsBlank(spec)
                    ? <div className="wb-m-empty">{blankText}</div>
                    : <ChartMount spec={spec} small onPick={isTime && i === 1 ? pickTicket : undefined} />}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
