/**
 * kpi-anchor-unified.mjs —— t260903-09 S2：KPI 单一口径（锚点归窗统一）。
 *
 * 根因：tickets 按 createdMs 归窗、closed/kept/charts/tokens 按 anchor 归窗
 * （closed 票=闭单时刻、未结票=创建时刻），三套人口并存 →「关闭数(10) >
 * 工单数(8)」悖论。修复后四指标同一 anchor。
 *
 * C2 红线：客户端 kpiCards title 文案本就是锚点口径——本文件顺带锁文案不回改。
 *
 * Run: node server/plugins/workbench/tests/kpi-anchor-unified.mjs  (cwd = repo root)
 */
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, STAGES, ok, summary,
} from './lib.mjs'

const { buildMetricsResponse, defaultDeps } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)

const savedStub = process.env.SANDBAR_METRICS_STUB
const savedDir = process.env.SANDBAR_METRICS_DIR

const mkDeps = (stub) => {
  process.env.SANDBAR_METRICS_STUB = writeStub(freshDir('t09-kpi-stub-'), stub)
  process.env.SANDBAR_METRICS_DIR = freshDir('t09-kpi-cache-')
  return defaultDeps('/stub-repo', () => NOW)
}

// NOW=2026-09-01T00:30Z，window=7d → from=2026-08-25T00:30Z
const IN_W = (d, h) => Date.parse('2026-08-28T00:00:00Z') + d * 86400e3 + h * 3600e3 // 窗内
const BEFORE_W = Date.parse('2026-08-20T00:00:00Z') // 窗前创建

{
  console.log('A. 悖论复现→消失：窗内关闭 10 票（2 票窗前创建）+ 窗内创建未结 3 票')
  const tickets = []
  for (let i = 0; i < 8; i++) tickets.push(closedTicket(`t09-a${i}`, baseStub(), { t0: IN_W(0, i), closedAt: IN_W(1, i) }))
  // 窗前创建、窗内关闭：锚点=闭单时刻 → 计入 tickets+closed（旧实现 tickets 漏数）
  for (let i = 0; i < 2; i++) tickets.push(closedTicket(`t09-old${i}`, baseStub(), { t0: BEFORE_W, closedAt: IN_W(1, i) }))
  // 窗内创建、未结：锚点=创建时刻 → 计入 tickets
  for (let i = 0; i < 3; i++) {
    tickets.push({
      id: `t09-open${i}`, epic: '', workflow: 'dev-lane', status: 'running',
      base_ref: 'main', worktree: '',
      timeline: [{ at: new Date(IN_W(2, i)).toISOString(), stage: 'plan', state: 'running' }],
    })
  }
  // 窗前创建、未结：锚点=创建时刻（窗外）→ 不计入（旧实现也不计，双保险）
  tickets.push({
    id: 't09-oldopen', epic: '', workflow: 'dev-lane', status: 'running',
    base_ref: 'main', worktree: '',
    timeline: [{ at: new Date(BEFORE_W).toISOString(), stage: 'plan', state: 'running' }],
  })
  const r = await buildMetricsResponse({ view: 'time', window: '7d' }, mkDeps(baseStub({ tickets })))
  ok('200', r.status === 200, JSON.stringify(r.body).slice(0, 200))
  const k = r.body.kpis
  ok(`tickets=13（窗内关闭 10 + 窗内未结 3；窗前未结不计）`, k.tickets === 13, JSON.stringify(k))
  ok(`closed=10（悖论消失：closed ≤ tickets）`, k.closed === 10, JSON.stringify(k))
  ok('closed ≤ tickets 恒成立（本例 10 ≤ 13）', k.closed <= k.tickets)
  ok('tokens_total 为窗内票合计（本例全票无会话数据=0，不是 undefined）', k.tokens_total === 0)

  console.log('A2. charts 与 KPI 同人口：Top 票数 ≤ kept')
  const tops = r.body.charts.secondaries.find((c) => String(c.title).includes('Top 票'))
  ok('Top 票图 categories ≤ tickets', tops === undefined || tops.categories.length <= k.tickets)
}

{
  console.log('B. 边角：closed 票缺 closed 时刻 → 锚点回退创建时刻')
  const tickets = [{
    id: 't09-noclosed', epic: '', workflow: 'dev-lane', status: 'closed',
    base_ref: 'main', worktree: '',
    // 有 running 条目（创建于窗内）但无 closed 条目 → closedMs=null
    timeline: [{ at: new Date(IN_W(0, 1)).toISOString(), stage: 'plan', state: 'running' }],
  }]
  const r = await buildMetricsResponse({ view: 'time', window: '7d' }, mkDeps(baseStub({ tickets })))
  const k = r.body.kpis
  ok('锚点回退创建时刻：tickets=1', k.tickets === 1, JSON.stringify(k))
  ok('closed=1（状态 closed，锚点在窗）', k.closed === 1, JSON.stringify(k))
}

{
  console.log('C. C2 红线：kpiCards title 仍是锚点口径文案（不许回改）')
  const mod = await import(new URL('./../src/client/metrics-model.ts', import.meta.url).pathname)
  const cards = mod.kpiCards({ tickets: 1, closed: 1, avg_delivery_min: 1, tokens_total: 1 })
  const t = cards[0].title
  ok('工单数 title 含「闭单时刻」锚点语义', t.includes('闭单时刻'), t)
}

process.env.SANDBAR_METRICS_STUB = savedStub
process.env.SANDBAR_METRICS_DIR = savedDir
process.exit(summary('kpi-anchor-unified') ? 0 : 1)
