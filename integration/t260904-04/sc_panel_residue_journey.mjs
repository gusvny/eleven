#!/usr/bin/env node
/**
 * sc_panel_residue_journey.mjs —— t260904-04 A1 面板筛选行收敛 L3 旅程场景（灰盒）。
 *
 * intent（用户可感知）：宿主令「泳道（模板）与立项选择器退役、项目下拉启用」后，
 * 持有旧版 localStorage 残留（template='other-lane' / epic=某代号）的用户重开度量
 * 面板不再被锁死在空面板——验收原话「持久化残留值需归一，防旧 localStorage 锁死
 * 非 dev-lane 模板导致空面板」。归一后的面板查询串必须被 /metrics 前门 200 接受；
 * 对照组证明失败模式真实存在：未归一的残留查询串直打门就是 400（旧世界里残留=
 * 永久 400 空面板）。
 *
 * 断言面（锚定公开面：metrics-model 的 loadPanelState/metricsQueryString 纯逻辑层 +
 * /metrics 前门 4xx{error,reason} 契约形状）：
 *  A 残留归一：template→dev-lane、epic→all（读时归一，保存 effect 写回不在 node 面）；
 *  B 归一后查询串过门 200；
 *  C 对照：template=other-lane 未归一查询串直打门 → 400 且 {error,reason} 双人话在场。
 *
 * 与 developer L1 intent 区别：L1 守 loadPanelState 归一函数本身（含畸形输入）；
 * 本场景守「残留 → 查询串 → 门」的用户旅程与对照红面（证明归一是必要修复而非装饰）。
 * Run: node integration/t260904-04/sc_panel_residue_journey.mjs（cwd=仓库根）
 */
import {
  loadPanelState, metricsQueryString, PANEL_STORAGE_KEY,
} from '../../server/dsh/workbench/src/client/metrics-model.ts'
import { NOW, DAY, WORKFLOWS, ticketRow, withStub, makeChecker } from '../t260903-09/lib_integration.mjs'

const { ok, done } = makeChecker()

const m = await import(new URL('../../server/dsh/workbench/src/host/metrics.ts', import.meta.url).pathname)

/** 旧版残留：用户曾选过非 dev-lane 模板与某立项代号（两个选择器如今均已退役）。 */
const residue = JSON.stringify({ view: 'time', window: '7d', epic: 'e1', project: '', template: 'other-lane', shape: 'donut' })
const fakeStorage = { getItem: (k) => (k === PANEL_STORAGE_KEY ? residue : null), setItem: () => {} }

const st = loadPanelState(fakeStorage)
ok(st.template === 'dev-lane', 'A1 残留 template 归一 dev-lane（选择器退役）', `got ${st.template}`)
ok(st.epic === 'all', 'A2 残留 epic 归一 all（选择器退役）', `got ${st.epic}`)
ok(st.shape === 'donut' && st.window === '7d', 'A3 非退役字段保留（只归一退役维度）')

const qs = metricsQueryString(st)

const stub = {
  project: 'demo',
  epics: [],
  workflows: WORKFLOWS,
  tickets: [ticketRow('t-a', { createdAt: NOW - DAY, closedAt: NOW - DAY / 2 })],
  deliveries: {},
}

await withStub(stub, async ({ deps }) => {
  const good = await m.buildMetricsResponse(new URLSearchParams(qs), deps)
  ok(good.status === 200, `B 归一后查询串过门 200（残留不锁死面板） qs=${qs}`, `got ${good.status} ${JSON.stringify(good.body).slice(0, 160)}`)

  const bad = await m.buildMetricsResponse(new URLSearchParams('view=time&window=7d&epic=all&template=other-lane'), deps)
  ok(bad.status === 400 && String(bad.body?.error ?? '') !== '' && String(bad.body?.reason ?? '') !== '',
    'C 对照：未归一残留 template 直打门 400 且 {error,reason} 双人话（锁死失败模式实证）',
    `got ${bad.status}`)
})

process.exit(done('t260904-04-panel-residue-journey'))
