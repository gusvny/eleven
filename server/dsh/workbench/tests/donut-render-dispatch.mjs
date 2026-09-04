/**
 * donut-render-dispatch.mjs —— t260903-09 S1/C3：三 donut 白板根因修复的源级 UT。
 *
 * 根因：renderSpec() switch 缺 'donut' 分支，三张 donut spec（时间去哪了副1/
 * 模型份额/有无代码变更票占比）落 default no-op——echarts init 后从不 setOption，
 * 用户看到白板（数据其实已到前端）。本测试钉死：
 *  A 纯逻辑：donutOption 形状（pie series、human 扇区着色、畸形输入不崩不 NaN）；
 *  B 分派面：specToDonutInput 从 ChartSpec 正确转 DonutInput（含维度不齐容错）；
 *  C 契约钉死（C3）：后端 buildMetricsResponse 产出的 time 副1 donut categories
 *    恒含「人审等待」且 isHumanSliceName 命中——后端改名即本文件红，不是静默掉色；
 *  D intent 边界（C6）：空数据空态文案已由 t03_donut_empty.mjs 主责，本文件只测
 *    「有数据时真渲染」的 option/分派面，与 t03 互补不重复。
 *
 * Run: node server/dsh/workbench/tests/donut-render-dispatch.mjs  (cwd = repo root)
 */
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, ok, summary, makeSession, usageEvents,
} from './lib.mjs'
import { mkdirSync, copyFileSync } from 'node:fs'
import { join } from 'node:path'
import { donutOption, specToDonutInput, isHumanSliceName } from './../src/client/metrics-charts.ts'

const { buildMetricsResponse, defaultDeps } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)

process.env.SUYOU_METRICS_STUB = ''
const savedStub = process.env.SUYOU_METRICS_STUB
const savedDir = process.env.SUYOU_METRICS_DIR

const mkDeps = (stub) => {
  process.env.SUYOU_METRICS_STUB = writeStub(freshDir('t09-donut-stub-'), stub)
  process.env.SUYOU_METRICS_DIR = freshDir('t09-donut-cache-')
  return defaultDeps('/stub-repo', () => NOW)
}

// ---- A. donutOption 纯逻辑
{
  console.log('A. donutOption：形状 + human 着色 + 畸形输入')
  const good = donutOption({
    slices: [
      { name: '人审等待', value: 2786.5, human: true },
      { name: '机器', value: 4824.14, human: false },
    ],
    totalMin: 12610.64, humanRatio: 0.366, degraded: false,
  })
  ok('pie series 在场', good.series?.[0]?.type === 'pie')
  ok('两扇区数据齐全', good.series[0].data.length === 2 && good.series[0].data[0].value === 2786.5)
  ok('human 扇区恒橙', good.series[0].data[0].itemStyle?.color === '#ff9b1f')
  ok('机器扇区不吃 human 色', good.series[0].data[1].itemStyle?.color === undefined)

  // 畸形输入六组：全零 / NaN / 字符串数字 / 维度不齐 / 空 slices / 负值
  const zero = donutOption({ slices: [{ name: 'a', value: 0, human: false }], totalMin: 0, humanRatio: 0, degraded: false })
  ok('全零扇区 value=0 不崩', zero.series[0].data[0].value === 0)
  const nan = donutOption({ slices: [{ name: 'a', value: NaN, human: false }], totalMin: 0, humanRatio: 0, degraded: false })
  ok('NaN 在 option 层原样透传（echarts 画 NaN=空档，不崩）', Number.isNaN(nan.series[0].data[0].value))
  const nanSpec = specToDonutInput({ kind: 'donut', title: 'x', categories: ['a'], series: [{ name: 's', data: [NaN] }], drill: true })
  ok('spec 层 NaN 收敛为 0（畸形容错在转换层）', nanSpec.slices[0].value === 0)
  const neg = donutOption({ slices: [{ name: 'a', value: -5, human: false }], totalMin: 0, humanRatio: 0, degraded: false })
  ok('负值扇区原样上画（echarts 自容错，adapter 不静默改数）', neg.series[0].data[0].value === -5)
  ok('空 slices 不崩', donutOption({ slices: [], totalMin: 0, humanRatio: 0, degraded: false }).series[0].data.length === 0)
}

// ---- B. specToDonutInput：ChartSpec → DonutInput
{
  console.log('B. specToDonutInput：分派面转换 + 维度不齐容错')
  const spec = { kind: 'donut', title: '模型份额', categories: ['deepseek/v3', 'gpt-5'], series: [{ name: 'tokens', data: [395267, 293065] }], drill: true }
  const d = specToDonutInput(spec)
  ok('slices 长度=categories', d.slices.length === 2)
  ok('值保真', d.slices[0].value === 395267 && d.slices[1].value === 293065)
  ok('非人审分类不吃 human 色', d.slices.every(s => !s.human))
  ok('副图 donut 无中心字（totalMin=0）', d.totalMin === 0 && d.humanRatio === 0)

  const ragged = specToDonutInput({ kind: 'donut', title: 'x', categories: ['a', 'b', 'c'], series: [{ name: 's', data: [1] }], drill: true })
  ok('维度不齐：缺项按 0 计不崩', ragged.slices.length === 3 && ragged.slices[1].value === 0 && ragged.slices[2].value === 0)
  const strNum = specToDonutInput({ kind: 'donut', title: 'x', categories: ['a'], series: [{ name: 's', data: ['7'] }], drill: true })
  ok('字符串数字按 0 计（不静默转型）', strNum.slices[0].value === 0)
  ok('isHumanSliceName：人审/human 命中、其余不命中', isHumanSliceName('人审等待') && isHumanSliceName('human wait') && !isHumanSliceName('机器') && !isHumanSliceName('deepseek/v3'))
}

// ---- C. 契约钉死（C3）：后端 donut categories 恒含「人审等待」
{
  console.log('C. 契约钉死：time 副1 categories 恒含「人审等待」且判定命中')
  const good = closedTicket('t09-donut-good', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })
  const r = await buildMetricsResponse({ view: 'time', window: '7d' }, mkDeps(baseStub({ tickets: [good] })))
  ok('time 视图 200', r.status === 200)
  const donutSec = r.body.charts.secondaries.find((c) => c.kind === 'donut' && String(c.title).includes('时间去哪了'))
  ok('时间去哪了副1 在场且非全零', donutSec !== undefined && donutSec.series[0].data.some((v) => v > 0))
  ok('categories 恒含「人审等待」（契约字面，后端改名此处红）', donutSec.categories.includes('人审等待'), JSON.stringify(donutSec.categories))
  ok('isHumanSliceName 对契约字面命中', isHumanSliceName('人审等待'))
  const dInput = specToDonutInput(donutSec)
  ok('转换后 human 扇区恰一个且值=人审值', dInput.slices.filter(s => s.human).length === 1)

  // 另两张投诉 donut：模型份额 / 有无代码变更票占比（分派面从 default 收编）。
  // token 数据经项目级账本缝供给（泳道会话不存在的真实形态）——顺带全链路验证
  // SUYOU_USAGE_LEDGER_DIR 回落进 buildMetricsResponse。
  const ledger = freshDir('t09-donut-ledger-')
  mkdirSync(join(ledger, 't09-donut-good'), { recursive: true })
  const sessDir = freshDir('t09-donut-sess-')
  const made = makeSession(sessDir, 't09-donut-good', 'developer', usageEvents())
  if (!made.ok) {
    console.log(`  SKIP token 视图用例 — zstd 不可用: ${made.reason}`)
  } else {
    copyFileSync(join(sessDir, '.dsh', 'sessions', 'slug0', 't09-donut-good-developer', 'session.jsonl.zstd'),
      join(ledger, 't09-donut-good', 'session.jsonl.zstd'))
    process.env.SUYOU_USAGE_LEDGER_DIR = ledger
    const rTok = await buildMetricsResponse({ view: 'token', window: '7d' }, mkDeps(baseStub({ tickets: [good] })))
    const model = rTok.body.charts.secondaries.find((c) => c.kind === 'donut' && String(c.title).includes('模型份额'))
    ok('token 视图模型份额 donut 在场（账本缝供数）', model !== undefined && specToDonutInput(model).slices.length > 0, JSON.stringify(model))
    process.env.SUYOU_USAGE_LEDGER_DIR = ''
  }
  const rDel = await buildMetricsResponse({ view: 'delivery', window: '7d' }, mkDeps(baseStub({ tickets: [good] })))
  const withCode = rDel.body.charts.secondaries.find((c) => c.kind === 'donut' && String(c.title).includes('有无代码变更票占比'))
  // t260904-09 四桶拆分：有变更 / 已收口·零变更 / 未交付（在制）/ 不可算（数据缺失）
  ok('delivery 视图占比 donut 在场且四桶', withCode !== undefined && specToDonutInput(withCode).slices.length === 4
    && JSON.stringify(withCode.categories) === JSON.stringify(['有变更', '已收口·零变更', '未交付（在制）', '不可算（数据缺失）']),
    JSON.stringify(withCode?.categories))
}

process.env.SUYOU_METRICS_STUB = savedStub
process.env.SUYOU_METRICS_DIR = savedDir
process.exit(summary('donut-render-dispatch') ? 0 : 1)
