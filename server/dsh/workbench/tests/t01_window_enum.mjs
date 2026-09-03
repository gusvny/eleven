/**
 * t260902-05 t01 —— 用户反馈⑤「时间窗加 1d/3d」集成测试（黑盒）。
 *
 * 用户场景：点开面板时间窗下拉，能看到并选中 1d / 3d；选中后 KPI 与图表
 * 真的只统计最近 1 天 / 3 天；选错参数时后端报错文案如实列出全部合法枚举
 * （报错精确纪律：不许漏掉新枚举）。
 *
 * 断言面：
 *  A 后端参数面：parseMetricsQuery 接受 1d/3d；非法值 400 且文案含 1d|3d；
 *  B 归窗正确性：同一 stub 三票（2h/2d/5d 前），window=1d→1 票、3d→2 票、
 *    7d→3 票、all→3 票（1d/3d 不是只改枚举不做过滤）；
 *  C 前端模型面：PANEL_WINDOWS 含 1d/3d；localStorage 持久化往返 1d/3d 不被
 *    当毒化丢弃；非法窗口（2d）仍回默认；旧存值（7d/30d/all）不回归。
 *
 * Run: node integration/t260902-05/t01_window_enum.mjs  (cwd = lane root)
 */
import {
  freshDir, loadMetrics, writeStub, baseStub, closedTicket, NOW,
  ok, skipCase, summary,
} from './lib.mjs'
import { PANEL_WINDOWS, loadPanelState, metricsQueryString } from './../src/client/metrics-model.ts'

const m = await loadMetrics()
const savedStub = process.env.SUYOU_METRICS_STUB
const savedDir = process.env.SUYOU_METRICS_DIR

const D = (stub) => {
  process.env.SUYOU_METRICS_STUB = writeStub(freshDir('t05-t01-stub-'), stub)
  process.env.SUYOU_METRICS_DIR = freshDir('t05-t01-cache-')
  return m.defaultDeps('/stub-repo', () => NOW)
}

// ---- A. 参数面
{
  console.log('A. parseMetricsQuery：1d/3d 合法，非法值文案含全枚举')
  const r1 = m.parseMetricsQuery({ window: '1d', view: 'time' })
  ok('window=1d 合法', r1.ok === true)
  const r3 = m.parseMetricsQuery({ window: '3d', view: 'time' })
  ok('window=3d 合法', r3.ok === true)
  const bad = m.parseMetricsQuery({ window: '2d', view: 'time' })
  ok('window=2d 仍 400', bad.ok === false && bad.status === 400)
  ok('错误文案列出 1d 与 3d（不漏新枚举）', bad.ok === false && String(bad.error).includes('1d') && String(bad.error).includes('3d'),
    String(bad.error))
  ok('缺 window 默认仍 7d', m.parseMetricsQuery({ view: 'time' }).ok === true
    && m.parseMetricsQuery({ view: 'time' }).params.window === '7d')
}

// ---- B. 归窗正确性
{
  console.log('B. 归窗：1d/3d 真的按窗过滤')
  const mk = (id, hoursAgo) => {
    const closedAt = NOW - hoursAgo * 3600e3
    return closedTicket(id, baseStub(), { t0: closedAt - 3600e3, closedAt })
  }
  const tickets = [mk('t-w1', 2), mk('t-w2', 48), mk('t-w3', 120)] // 2h 前 / 2d 前 / 5d 前
  const deps = D(baseStub({ tickets }))
  const counts = {}
  for (const w of ['1d', '3d', '7d', 'all']) {
    const r = await m.buildMetricsResponse({ view: 'time', window: w }, deps)
    if (r.status !== 200) { ok(`window=${w} 200 信封`, false, JSON.stringify(r.body).slice(0, 200)); continue }
    counts[w] = r.body.kpis.tickets
  }
  ok('1d → 1 票', counts['1d'] === 1, JSON.stringify(counts))
  ok('3d → 2 票', counts['3d'] === 2, JSON.stringify(counts))
  ok('7d → 3 票（旧窗不回归）', counts['7d'] === 3, JSON.stringify(counts))
  ok('all → 3 票', counts.all === 3, JSON.stringify(counts))
  // 重复参数防穿不回归
  const dup = m.parseMetricsQuery(new URLSearchParams([['window', '1d'], ['window', '3d'], ['view', 'time']]))
  ok('同名重复 window 仍 400（防穿不放松）', dup.ok === false && dup.status === 400)
}

// ---- C. 前端模型面
{
  console.log('C. 面板模型：PANEL_WINDOWS 与持久化容错')
  ok('PANEL_WINDOWS 含 1d', PANEL_WINDOWS.includes('1d'))
  ok('PANEL_WINDOWS 含 3d', PANEL_WINDOWS.includes('3d'))
  ok('旧枚举不丢', ['7d', '30d', 'all'].every((w) => PANEL_WINDOWS.includes(w)))

  const mem = {
    getItem: (k) => (k === 'suyou-workbench-metrics-panel-v1' ? JSON.stringify({ window: '3d', view: 'time' }) : null),
    setItem: () => {},
  }
  ok('存值 window=3d 被接受（不被当毒化丢）', loadPanelState(mem).window === '3d')
  const mem1d = {
    getItem: (k) => (k === 'suyou-workbench-metrics-panel-v1' ? JSON.stringify({ window: '1d' }) : null),
    setItem: () => {},
  }
  ok('存值 window=1d 被接受', loadPanelState(mem1d).window === '1d')
  const memBad = {
    getItem: (k) => (k === 'suyou-workbench-metrics-panel-v1' ? JSON.stringify({ window: '2d' }) : null),
    setItem: () => {},
  }
  ok('非法窗口 2d 回默认 7d', loadPanelState(memBad).window === '7d')
  const memOld = {
    getItem: (k) => (k === 'suyou-workbench-metrics-panel-v1' ? JSON.stringify({ window: '30d' }) : null),
    setItem: () => {},
  }
  ok('升级用户旧存值 30d 不回归', loadPanelState(memOld).window === '30d')
  ok('查询串带 window=1d', metricsQueryString({ view: 'time', window: '1d', epic: 'all', project: '', template: 'dev-lane', shape: 'bar' }).includes('window=1d'))
}

if (typeof savedStub === 'undefined') delete process.env.SUYOU_METRICS_STUB; else process.env.SUYOU_METRICS_STUB = savedStub
if (typeof savedDir === 'undefined') delete process.env.SUYOU_METRICS_DIR; else process.env.SUYOU_METRICS_DIR = savedDir
const passAll = summary('t01_window_enum')
process.exit(passAll ? 0 : 1)
