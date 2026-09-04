#!/usr/bin/env node
/**
 * sc_metrics_universe_reason_cap.mjs —— t260904-04 KI-043② L2 场景（灰盒）。
 *
 * intent（用户可感知）：宿主令「workflow 为空/不匹配被过滤的票要在 reason 计数，
 * 不静默缩宇宙」。用户看到的聚合宇宙缩水必须有人话记账——模板不匹配 notice 在场
 * 且计数正确；且 reason 有 20 条 cap 的世界里，notice 排首不被挤掉（契约块 2：
 * notices 不受 cap 截断的既有承诺对新 notice 同样成立）；被滤票不混入任何图、
 * 不进 KPI 人口（缩宇宙可以，静默不行）。
 *
 * 断言面（锚定 /metrics 响应契约：reason 串/notices 位次/spec categories/kpis）：
 *  A 模板不匹配 notice 排 reason 首、计数=2（吞票显式化）；
 *  B cap 压力下（12 张正常票各贡献多条逐票 reason）reason 总段数 ≤20 且 notice 仍在首位；
 *  C 被滤票（workflow=''）不出现在任何 spec categories、不进 KPI tickets 人口。
 *
 * 与 developer L1（方案第 3 步单测：过滤前计数函数级触发）intent 区别：本场景守
 * 响应级 reason 组成、notice 与 cap 的共存位次、被滤票在图/人口中的缺席——L1 看不到
 * 组装后的整串。预期能力：notice 段实现落地前 A 红，B/C 为现状回归锚（过滤本就存在）。
 * Run: node integration/t260904-04/sc_metrics_universe_reason_cap.mjs（cwd=仓库根）
 */
import {
  NOW, DAY, WORKFLOWS, ticketRow, withStub, callMetrics, findSpecs, makeChecker,
} from '../t260903-09/lib_integration.mjs'

const { ok, done } = makeChecker()

const ORPHANS = ['t-orphan1', 't-orphan2']
const tickets = []
for (let i = 1; i <= 12; i++) {
  tickets.push(ticketRow(`t-cap${String(i).padStart(2, '0')}`, { createdAt: NOW - 2 * DAY, closedAt: NOW - DAY }))
}
for (const id of ORPHANS) {
  // 对照票：除 workflow 外全合格（闭单、带 timeline）——只有模板不匹配这一个被滤原因
  tickets.push(ticketRow(id, { createdAt: NOW - 2 * DAY, closedAt: NOW - DAY, extra: { workflow: '' } }))
}

const stub = {
  project: 'demo',
  epics: [],
  workflows: WORKFLOWS,
  tickets,
  deliveries: {}, // 无 git 桩：12 张正常票各贡献 delivery 不可算 + 无 token 等逐票 reason → cap 压力
}

await withStub(stub, async ({ deps }) => {
  const r = await callMetrics(deps, { view: 'delivery', window: 'all' })
  ok(r.status === 200, 'A0 前门 200（夹具自检）')
  const reason = String(r.body?.reason ?? '')
  const segs = reason.split('；')

  ok(segs[0].includes('模板不匹配') && segs[0].includes('2'), 'A 模板不匹配 notice 排 reason 首且计数=2（吞票显式化）', segs[0])
  ok(segs.length > 0 && segs.length <= 20, 'B cap 压力下 reason 总段数 ≤20 且 notice 保住首位（notices 不受 cap 截断）', `段数=${segs.length}`)

  const specs = findSpecs(r.body?.charts, '')
  const cats = new Set(specs.flatMap((s) => Array.isArray(s.categories) ? s.categories : []))
  ok(!ORPHANS.some((id) => cats.has(id)), 'C1 被滤票不入任何图 categories（不静默混入）')
  ok(r.body?.kpis?.tickets === 12, 'C2 KPI 人口不含被滤票（缩宇宙但显式记账）', `got ${r.body?.kpis?.tickets}`)
})

process.exit(done('t260904-04-universe-reason-cap'))
