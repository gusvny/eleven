#!/usr/bin/env node
/**
 * golden.mjs —— t260902-05 R7：并发改造前后的一致性基线。
 *
 * --record：用当前实现 + 固定 stub 跑四 view × window 组合，剔除
 *   generated_at/cache.computed_at 后落盘 golden_serial/<case>.json。
 * --compare：同 stub 重跑，与 golden_serial 逐字节比对（剔除同两字段）。
 *
 * stub 由本脚本以「now 相对时间」动态生成（保证窗口归窗跨日可复现），
 * SANDBAR_METRICS_DIR 指到本目录 tmp/（缓存写进工作区，不碰 ~/.sandbar）。
 * 直跑：node golden.mjs --record
 */
import { mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
// 实现路径取 argv[3]：record 用主仓库副本（=改动前串行实现），compare 用本 worktree 改后实现
const IMPL = process.argv[3] ?? './../src/host/metrics.ts'
const { buildMetricsResponse, defaultDeps } = await import(IMPL)

const HERE = new URL('.', import.meta.url).pathname
const MODE = process.argv[2] ?? '--record'
// IMPL 由 argv[3] 提供（见下）

// 固定 now（验收 F5）：动态时钟会让 created_ms/归窗随录制日漂移，7 天后干净环境
// compare 必假红；固定后基线跨日可复现（与 workbench 其余测试同纪律）。
const now = Date.parse('2026-09-03T00:30:00Z')
const iso = (ms) => new Date(ms).toISOString()
const day = 86_400_000
const mkTicket = (id, daysAgo, closedAfterHours, stages) => ({
  id,
  epic: '',
  workflow: 'dev-lane',
  status: closedAfterHours === null ? 'running' : 'closed',
  timeline: [
    { at: iso(now - daysAgo * day), stage: 'create_plan', state: 'running' },
    { at: iso(now - daysAgo * day + 3600_000), stage: 'implement', state: 'running' },
    ...(closedAfterHours === null ? [] : [
      { at: iso(now - daysAgo * day + closedAfterHours * 3600_000), stage: 'implement', state: 'closed' },
    ]),
  ],
  base_ref: 'main',
  worktree: '', // 无泳道：delivery 不可算（软降级路径顺带覆盖）
})

const tickets = [
  mkTicket('gold-01', 0.2, null, []),            // 未结（本日）
  mkTicket('gold-02', 1, 5, []),                 // 已结
  mkTicket('gold-03', 2, 30, []),                // 已结慢票
  mkTicket('gold-04', 8, 6, []),                 // 7d 窗外（30d 内）
  mkTicket('gold-05', 40, 6, []),                // 全窗口外
]
const stub = {
  project: 'gold',
  epics: [],
  workflows: [{ id: 'dev-lane', name: 'dev-lane', lane: 'dev', stages: [{ id: 'create_plan' }, { id: 'implement' }, { id: 'review_plan', exit: 'human' }] }],
  tickets,
  deliveries: {},
}
const stubPath = join0(HERE, `stub-${MODE === '--record' ? 'record' : 'compare'}.json`)
function join0(a, b) { return a + b }
await writeFile(stubPath, JSON.stringify(stub))

process.env.SANDBAR_METRICS_STUB = stubPath
// 缓存写系统临时目录（验收 F5）：不再落工作区 tmp-cache/（运行时产物不入库）
const tmpCache = join(tmpdir(), 'suyou-golden-cache')
process.env.SANDBAR_METRICS_DIR = tmpCache
await rm(tmpCache, { recursive: true, force: true })
await mkdir(tmpCache, { recursive: true })

const repo = '/nonexistent-golden-repo'
const cases = []
// 基线窗口=当前已支持枚举（1d/3d 属本单 S1 新增，由单测另验，不进 golden 面）
for (const view of ['time', 'delivery', 'token', 'health'])
  for (const window of ['7d', '30d', 'all'])
    cases.push({ view, window })

const strip = (body) => {
  const c = { ...body, generated_at: '', cache: { ...body.cache, computed_at: '' } }
  return JSON.stringify(c)
}

let failed = 0
for (const c of cases) {
  // 验收 G1：响应侧时钟也必须钉死——缺省 now=Date.now 会让未结票的开放窗口
  // 分钟数随墙钟增长，time 基线录制完成后立即失配（比对工具自灭）。
  const deps = defaultDeps(repo, () => now)
  const r = await buildMetricsResponse({ view: c.view, window: c.window, epic: 'all', template: 'dev-lane' }, deps)
  if (r.status !== 200) { console.error(`case ${c.view}/${c.window} status=${r.status}`, r.body); failed++; continue }
  const text = strip(r.body)
  if (MODE === '--record') {
    await mkdir(`${HERE}golden_serial`, { recursive: true }) // 空工单/首次录制时目录尚不存在
    await writeFile(`${HERE}golden_serial/${c.view}-${c.window}.json`, text)
    console.log(`record ${c.view}/${c.window} ok`)
  } else {
    let golden
    try { golden = await readFile(`${HERE}golden_serial/${c.view}-${c.window}.json`, 'utf8') } catch { console.error(`compare ${c.view}/${c.window}: golden 缺失`); failed++; continue }
    if (golden === text) console.log(`compare ${c.view}/${c.window} 一致`)
    else { console.error(`compare ${c.view}/${c.window} 不一致!\n  golden=${golden}\n  now    =${text}`); failed++ }
  }
}
await rm(stubPath, { force: true })
process.exit(failed > 0 ? 1 : 0)
