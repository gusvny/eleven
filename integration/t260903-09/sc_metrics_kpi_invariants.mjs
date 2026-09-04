#!/usr/bin/env node
/**
 * sc_metrics_kpi_invariants.mjs —— t260903-09 需求③ L3 场景：KPI 单一口径不变量。
 *
 * intent（用户可感知）：度量面板四张 KPI 卡与三视图图人口自洽——用户在任意窗口
 * 下不再见到「关掉比总数多」（工单原话：tickets=创建归窗(8)、closed=闭单归窗(10)），
 * 「有无代码变更票占比」环形图两片之和恰等于卡上票数（工单实测 [2,46] 对 48 票
 * 的人口疑问面），Token 卡跨视图不跳变。
 *
 * 断言面（锚定 /metrics 响应契约形状，不绑实现内部）：
 *  A 悖论不变量：window∈{7d,30d,all}×view∈{time,delivery,token} 下恒 closed ≤ tickets，
 *    且受控人口桩给出精确值（7d: tickets=3 closed=2；30d: 4/2；all: 5/3）——
 *    关键票 B=窗前创建窗内关闭，锚点统一后计入 tickets（创建归窗语义下它缺席=悖论源）。
 *  B 人口自洽：delivery 视图「有无代码变更票占比」spec 两片之和 === kpis.tickets。
 *  C 跨视图一致：tokens_total 三视图恒等（同一 kept 人口）。
 *  D 契约字面：time 视图「时间去哪了」spec categories 含「人审等待」（C3 钉死字面）。
 *
 * 预期状态：S2（锚点归窗统一）落地前 A 红（当前 tickets 按 createdMs）；其余断言
 * 为现状回归锚。Run: node integration/t260903-09/sc_metrics_kpi_invariants.mjs（cwd=仓库根）
 */
import {
  NOW, DAY, WORKFLOWS, STAGES, ticketRow, withStub, callMetrics, findSpecs, specDataSum, makeChecker,
} from './lib_integration.mjs'

const { ok, done } = makeChecker()
const W = (days) => NOW - days * DAY

// 受控人口桩：A/B 窗内闭（B 窗前创建=锚点统一的关键票）、C 未结、D 全窗外(7d/30d)、E 仅 30d 窗
const tickets = [
  ticketRow('t-inv-a', { createdAt: W(3), closedAt: W(1) }),
  ticketRow('t-inv-b', { createdAt: W(10), closedAt: W(1) }),   // 悖论源：窗前创建、窗内闭
  ticketRow('t-inv-c', { createdAt: W(2), closedAt: null }),    // 未结：锚点=创建时刻
  ticketRow('t-inv-d', { createdAt: W(40), closedAt: W(39) }),  // 7d/30d 窗外
  ticketRow('t-inv-e', { createdAt: W(20), closedAt: null }),   // 仅 30d 窗
]
const stub = { project: 'demo', workflows: WORKFLOWS, stages: STAGES, tickets, epics: [] }

const EXPECT = { '7d': { tickets: 3, closed: 2 }, '30d': { tickets: 4, closed: 2 }, all: { tickets: 5, closed: 3 } }
const VIEWS = ['time', 'delivery', 'token']

await withStub(stub, async ({ deps }) => {
  const bodies = {}
  for (const win of ['7d', '30d', 'all']) {
    for (const view of VIEWS) {
      const r = await callMetrics(deps, { view, window: win })
      if (r.status !== 200) { ok(false, `window=${win} view=${view} 200`, `status=${r.status} body=${JSON.stringify(r.body).slice(0, 160)}`); continue }
      bodies[`${win}:${view}`] = r.body
    }
  }

  // ---- A. 悖论不变量 + 精确人口（锚点统一口径）
  for (const win of ['7d', '30d', 'all']) {
    for (const view of VIEWS) {
      const b = bodies[`${win}:${view}`]
      if (!b) continue
      const k = b.kpis ?? {}
      ok(k.closed <= k.tickets, `A ${win}/${view} closed(${k.closed}) ≤ tickets(${k.tickets}) 不悖论`)
      ok(k.tickets === EXPECT[win].tickets && k.closed === EXPECT[win].closed,
        `A ${win}/${view} 人口精确 tickets=${EXPECT[win].tickets} closed=${EXPECT[win].closed}`,
        `实得 tickets=${k.tickets} closed=${k.closed}`)
    }
  }

  // ---- B. 「有无代码变更票占比」donut 两片之和 === tickets（delivery 视图，7d）
  const dBody = bodies['7d:delivery']
  if (dBody) {
    const specs = findSpecs(dBody.charts, '代码变更')
    ok(specs.length === 1, 'B 找到「有无代码变更票占比」spec 恰一个', `hits=${specs.length}`)
    if (specs.length === 1) {
      const sum = specDataSum(specs[0])
      ok(sum === dBody.kpis.tickets, `B donut 两片之和(${sum}) === tickets(${dBody.kpis.tickets})`)
    }
  }

  // ---- C. tokens_total 跨三视图恒等（7d）
  const tokenSet = VIEWS.map((v) => bodies[`7d:${v}`]?.kpis?.tokens_total).filter((x) => x !== undefined)
  ok(tokenSet.length === 3 && new Set(tokenSet).size === 1, `C tokens_total 三视图恒等(${tokenSet.join(',')})`)

  // ---- D. 「时间去哪了」categories 含「人审等待」（契约钉死字面，C3）
  const tBody = bodies['7d:time']
  if (tBody) {
    const specs = findSpecs(tBody.charts, '时间去哪了')
    ok(specs.length === 1, 'D 找到「时间去哪了」spec 恰一个', `hits=${specs.length}`)
    if (specs.length === 1) {
      const cats = Array.isArray(specs[0].categories) ? specs[0].categories : []
      ok(cats.some((c) => String(c).includes('人审等待')), 'D categories 含「人审等待」（C3 契约字面）', JSON.stringify(cats))
    }
  }
})

process.exit(done('sc_metrics_kpi_invariants'))
