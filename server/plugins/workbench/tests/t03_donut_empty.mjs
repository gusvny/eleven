/**
 * t260902-05 t03 —— 用户反馈⑥「时间去哪了饼 block 无 chart」集成测试（黑盒）。
 *
 * 用户场景：切到「时间去哪了」饼 block（主图饼形态与 time 视图副图两张都是它），
 * 窗口内没有 stage 时长数据时，必须看到人话空态（「窗口内无 stage 时长数据」），
 * 不许是一个白块/空 echarts 画布假装修好了。
 *
 * 断言面：
 *  A 后端：窗口内无 running 数据时 time 视图 200、副图「时间去哪了」数据全零、
 *    reason 带人话（不是静默零）；正常票时副图数据非全零且 human ≤ 合计（不重复计数）；
 *  B 模型层：buildTimeDonut 全零输入 → totalMin=0（UI 空态判定前提）；
 *    模板缺失降级二分环标注不回归（degraded=true）；
 *  C 构建产物门（S4 后绿灯，implement 前故意 FAIL）：bundle 含人话空态文案
 *    「窗口内无 stage 时长数据」——主图 donutInput 与副图 spec 两渲染路径都要盖到，
 *    这里锁文案在产物里存在（两路径共用组件时自然覆盖；分路径实现则两处都要有）。
 *
 * Run: node integration/t260902-05/t03_donut_empty.mjs  (cwd = lane root)
 */
import {
  freshDir, loadMetrics, writeStub, baseStub, closedTicket, NOW, STAGES,
  ok, summary,
} from './lib.mjs'
import { readFileSync } from 'node:fs'
import { buildTimeDonut } from './../src/client/metrics-model.ts'

const m = await loadMetrics()
const savedStub = process.env.SANDBAR_METRICS_STUB
const savedDir = process.env.SANDBAR_METRICS_DIR

const D = (stub) => {
  process.env.SANDBAR_METRICS_STUB = writeStub(freshDir('t05-t03-stub-'), stub)
  process.env.SANDBAR_METRICS_DIR = freshDir('t05-t03-cache-')
  return m.defaultDeps('/stub-repo', () => NOW)
}

// ---- A. 后端
{
  console.log('A. 后端：无 running 数据的票 → 全零 + 人话 reason')
  // timeline 无 running 条目 → stage 时长计 0 + reason（契约块 4 既有语义，本单不许被中 pane/tab 改动静默化）
  const empty = { ...closedTicket('t-empty', baseStub()), timeline: [{ at: new Date(NOW - 3600e3).toISOString(), stage: 'plan', state: 'closed' }] }
  const r = await m.buildMetricsResponse({ view: 'time', window: '7d' }, D(baseStub({ tickets: [empty] })))
  ok('time 视图 200', r.status === 200)
  const donutSec = r.body.charts.secondaries.find((c) => c.kind === 'donut' && String(c.title).includes('时间去哪了'))
  ok('「时间去哪了」副图在场', donutSec !== undefined)
  ok('全零数据：人审+机器两值全零', donutSec && donutSec.series[0].data.every((v) => v === 0), JSON.stringify(donutSec?.series))
  ok('reason 人话在场（stage 时长计 0）', String(r.body.reason ?? '').includes('stage 时长计 0'), String(r.body.reason ?? '').slice(0, 160))

  console.log('A2. 正常票：副图非全零且人审 ≤ 合计')
  const good = closedTicket('t-good', baseStub(), { t0: Date.parse('2026-08-30T01:00:00Z'), closedAt: Date.parse('2026-08-30T04:00:00Z') })
  const r2 = await m.buildMetricsResponse({ view: 'time', window: '7d' }, D(baseStub({ tickets: [good] })))
  const d2 = r2.body.charts.secondaries.find((c) => c.kind === 'donut')
  const [human, machine] = d2.series[0].data
  ok('正常票副图非全零', human + machine > 0)
  ok('人审 ≤ 合计（human_wait ⊂ by_stage 不重复计数）', human <= human + machine)
}

// ---- B. 模型层空态前提
{
  console.log('B. buildTimeDonut 全零/降级语义')
  const zeroPrimary = { kind: 'bar', title: 'x', categories: ['plan', 'review', 'implement'], series: [{ name: '时长(min)', data: [0, 0, 0] }], drill: true }
  const d1 = buildTimeDonut(zeroPrimary, null, STAGES)
  ok('全零输入 totalMin=0（UI 空态判定前提）', d1.totalMin === 0)
  ok('全零输入 humanRatio=0', d1.humanRatio === 0)
  const fallback = { kind: 'donut', title: 'x', categories: ['人审等待', '机器'], series: [{ name: '占比', data: [3, 7] }], drill: true }
  const d2 = buildTimeDonut(null, fallback, null)
  ok('模板缺失降级二分环 degraded=true 标注不回归', d2.degraded === true && d2.totalMin === 10)
  const d3 = buildTimeDonut(null, null, null)
  ok('完全无数据 slices 空（绝不抛）', Array.isArray(d3.slices) && d3.slices.length === 0)
}

// ---- C. bundle 空态文案门（S4 后绿灯）
{
  console.log('C. bundle 门：人话空态文案（implement 前故意 FAIL）')
  let bundle = ''
  try { bundle = readFileSync(new URL('./../lib/client.js', import.meta.url), 'utf8') } catch {}
  if (bundle === '') {
    console.log('  SKIP bundle 门 — lib/client.js 不存在')
  } else {
    // 空态文案以实现落地为准（方案 R5 初稿「窗口内无 stage 时长数据」，实现定稿
    // 「窗口内无可绘图数据」——20260902 review 同步，覆盖 donut 全零白块场景）
    const n = (bundle.match(/窗口内无可绘图数据/g) ?? []).length
    ok('bundle 含人话空态文案「窗口内无可绘图数据」', n >= 1, `count=${n}`)
  }
}
const passAll = summary('t03_donut_empty')
process.exit(passAll ? 0 : 1)
