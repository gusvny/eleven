#!/usr/bin/env node
// sc_t26100922_lane_map_mock_chrome.mjs —— 泳道图 mock 261004 chrome 面（t261009-22）。
//
// intent（灰盒 L3，browser-free 池，真浏览器 + page-boundary API 打桩，零 docker，
// 红线零接触 3099）：详情泳道图补齐 mock 261004（notes/discussions/
// 261004-concurrency-limit-mock.html laneMap()，判据=设计稿 §7.6 八条）里缺失的
// chrome 面——头部三色图例（判据2）、`elapsed … · now at …` 摘要（判据3）、
// 当前段为人门时 `waiting for you`（判据5）、标签下方的 `时长 · ×轮` 行（判据4）、
// 人门段的菱形 glyph（判据5）、与段同比例尺的时间轴起止时刻（判据6）、
// skipped=虚线空框（判据3）、now 游标（判据3）、hover 详情含时长（判据8）。
// intent 分界：段宽∝时长、名义宽、并行双带窗、明暗主题捕获归
// t261008-23-lane-map-v5-proportional（不重复断言）；拓扑解析/降级/受阻史归
// t260915-05 与 t260927-05。本条独占上述 chrome 面。
// KI 对齐：KI-055（真浏览器断言）；KI-051（锚语义不锚字面：断言用户可见
// 文本与 DOM 语义锚 data-testid="detail-lane-map"，不锚类名）；畸形输入面
//（坏 `at`、坏 timeline 条目）断言无 `undefined` 字面、零 pageerror。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现未落地段红属预期（TDD 信号）。

import { mkdirSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  PROJ, loadPlaywright, launchBrowser, bootFixture, recorder, waitFor, dismissIntroModal,
} from '../t261008-23/lib_fix23.mjs'

const REPO = process.cwd()
const TID = 't26100922-fix'
const T0 = 1789440000000 // ms，固定基准，起止时刻可预判
const iso = (ms) => new Date(ms).toISOString()
const hhmm = (ms) => {
  const d = new Date(ms)
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
}

// 夹具拓扑（渲染器通用性对拍面：自造四段拓扑，零 dev-lane 业务词）：
//   plan(agent, 2m 实测) → build(agent, 8m 实测) → extra_check(agent, optional，
//   被旁路 → skipped) / qc_gate(gate, 1m) → signoff(human, 当前 awaiting-human)。
const TOPOLOGY = {
  template: 'fx-lane', name: 'fx lane',
  nodes: [
    { id: 'plan', label: 'plan', role: 'developer', kind: 'agent' },
    { id: 'build', label: 'build', role: 'developer', kind: 'agent' },
    { id: 'extra_check', label: 'extra check', role: 'developer', kind: 'agent', optional: 'only UI tickets' },
    { id: 'qc_gate', label: 'qc gate', role: 'script', kind: 'gate' },
    { id: 'signoff', label: 'signoff', role: 'human', kind: 'human' },
  ],
  edges: [
    ['plan', 'build'],
    ['build', 'extra_check'], ['build', 'qc_gate'],
    ['extra_check', 'qc_gate'],
    ['qc_gate', 'signoff'],
  ],
  groups: [],
}

// 时间线：running marks 开窗、下一条 running 收上一窗（lane-durations 契约）。
// plan 2m、build 8m（刻意不等比）、qc_gate 1m、signoff 开窗后 awaiting-human。
// 含一条坏 `at`（非 ISO）与一条坏条目（stage 非字符串）→ 畸形输入面。
function fixtureTimeline() {
  return [
    { at: iso(T0), stage: 'plan', state: 'running', reason: 'plan written' },
    { at: iso(T0 + 120e3), stage: 'build', state: 'running', reason: 'building' },
    { at: 'not-a-date', stage: 'build', state: 'done', reason: 'corrupt at' },
    { stage: 42, state: 'running', reason: 'corrupt entry: stage not a string' },
    { at: iso(T0 + 600e3), stage: 'qc_gate', state: 'running', reason: 'gate ran' },
    { at: iso(T0 + 660e3), stage: 'signoff', state: 'running', reason: 'waiting for the human' },
    { at: iso(T0 + 700e3), stage: 'signoff', state: 'awaiting-human', reason: 'sign-off needed' },
  ]
}

function fixtureDetail() {
  return {
    id: TID,
    title: 'fixture ticket for lane-map chrome scenarios',
    project: PROJ,
    status: 'RUNNING',
    workflow: 'fx-lane',
    workflow_id: 'fx-lane',
    stage: 'signoff',
    stage_state: 'awaiting-human',
    worktree: '',
    base_ref: 'abc123def456',
    write_set: ['server/plugins/workbench/src/client/'],
    meta: {},
    timeline: fixtureTimeline(),
  }
}

function fixtureWorkflow() {
  return {
    id: 'fx-lane', name: 'fx lane', lane: 'worktree',
    stages: TOPOLOGY.nodes.map((n) => ({ id: n.id, name: n.label, role: n.role, parts: ['agent'] })),
    topology: TOPOLOGY,
  }
}

// 打桩路由（镜 lib_fix23 routeDetail 模式，但 workflows envelope 用本票夹具；
// 详情面消费的全部 API 路由都打桩，未知路由诚实 ok:false——不静默假数据）。
function routeDetail(page, detail) {
  return page.route('**/sandbar-workbench/api/wf/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const j = (body) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (method === 'GET' && path === '/sandbar-workbench/api/wf/projects') {
      return j({ ok: true, result: { projects: [{ key: PROJ, name: PROJ, primary: '/tmp/fx-comp', dirs: ['/tmp/fx-comp'] }], quarantined: [] } })
    }
    if (method === 'GET' && path === '/sandbar-workbench/api/wf/tickets') {
      return j({ ok: true, result: { tickets: [detail] }, workflows: [fixtureWorkflow()] })
    }
    if (method === 'GET' && path === `/sandbar-workbench/api/wf/tickets/${TID}`) {
      return j({ ok: true, result: detail })
    }
    if (method === 'GET' && path === '/sandbar-workbench/api/wf/inspection/tickets') {
      return j({ ok: true, result: { tickets: [], count: 0 } })
    }
    return j({ ok: false, error: 'fixture stub: unknown route' })
  })
}

const { record, rec, summarize } = recorder()
let bench = null
try {
  const b = await bootFixture(REPO, 't26100922-lanemap')
  bench = b.bench
  bench.teardownOnExit = b.teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// S0 build-contract：双 bundle 同步（KI-052）+ 新鲜度——stale lib 会把本票全部
// 新面变成神秘红，这里点名根因（重构建入口 build-client.sh），不静默。
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
  record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
} else {
  const js = readFileSync(LIB_JS, 'utf8')
  const sync = js === readFileSync(LIB_CJS, 'utf8')
  record('S0 build-contract', sync ? 'pass' : 'fail', sync ? 'twin bundles in sync' : 'twin bundles out of sync — rebuild (KI-052)')
  const fresh = js.includes('wb-lm-axis') && js.includes('wb-lm-cursor')
  record('S0 bundle freshness (t261009-22 chrome present)',
    fresh ? 'pass' : 'fail',
    fresh ? 'new chrome classes in bundle' : 'STALE BUNDLE: rebuild via server/plugins/workbench/build-client.sh, then rerun')
}

let pw = null, browser = null
try { pw = await loadPlaywright(REPO) } catch { /* handled below */ }
browser = pw ? await launchBrowser(pw) : null
if (!browser) {
  console.log('[ENV_FAIL] playwright-core/chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  try { await bench.teardown() } catch { /* already down */ }
  process.exit(2)
}

const ctx = await browser.newContext()
const pageErrors = []
const page = await ctx.newPage()
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)))

const detail = fixtureDetail()
await routeDetail(page, detail)
await bench.goto(page, { waitUntil: 'networkidle' })
await dismissIntroModal(page)
await page.waitForTimeout(2000)

const opened = await waitFor(async () => {
  const row = await page.$(`[data-ticket-id="${TID}"]`)
  if (!row) return false
  await row.click()
  await page.waitForTimeout(1200)
  return !!(await page.$('[data-testid="detail-columns"]'))
}, 10000)
if (!opened) {
  record('S1 precheck', 'env_fail', `detail drawer never opened for ${TID}`)
  await browser.close(); await bench.teardown()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2)
}
record('S1 precheck', 'pass', 'detail drawer open')

// 泳道图探针：锚 data-testid="detail-lane-map"（语义锚，不绑类名）。
const PROBE = `(() => {
  const lm = document.querySelector('[data-testid="detail-lane-map"]')
  if (!lm) return { found: false }
  const text = lm.textContent || ''
  // 段探针：data-weight-ms / data-band（模型携带的语义锚）+ 几何。
  const segs = [...lm.querySelectorAll('[data-weight-ms], [data-band]')].map(el => {
    const r = el.getBoundingClientRect()
    return {
      w: Math.round(r.width), h: Math.round(r.height),
      ms: Number(el.getAttribute('data-weight-ms')),
      band: el.getAttribute('data-band') || null,
      stage: el.getAttribute('data-stage') || el.getAttribute('data-label') || '',
      borderStyle: getComputedStyle(el).borderTopStyle,
    }
  })
  // svg glyph 探针（菱形=矢量 path；今日图面无 svg）。
  const svgPaths = [...lm.querySelectorAll('svg path')].map(p => (p.getAttribute('d') || '').slice(0, 60))
  // now 游标探针：窄高、虚线边的元素。
  const cursor = [...lm.querySelectorAll('*')].some(el => {
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    return r.height > 16 && r.width <= 8 && (cs.borderLeftStyle === 'dashed' || cs.borderRightStyle === 'dashed' || cs.borderTopStyle === 'dashed')
  })
  const axis = lm.querySelector('[data-testid="lane-map-axis"]')
  const clocks = axis
    ? [...axis.querySelectorAll('span')].map((e) => (e.textContent || '').trim()).filter(Boolean)
    : (text.match(/\b\d{2}:\d{2}\b/g) || [])
  return { found: true, text, segs, svgPaths, cursor, clocks,
    header: (lm.querySelector('header, [class*="head"], [class*="lsum"]') || lm).textContent.slice(0, 200) }
})()`

let lm = null
await waitFor(async () => {
  const v = await page.evaluate(PROBE)
  if (v.found && v.segs.length >= 3) { lm = v; return true }
  return false
}, 10000)
if (!lm) {
  record('S2 lane-map present', 'fail', 'lane map never rendered; probe=' +
    JSON.stringify(await page.evaluate(PROBE)).slice(0, 200))
  await browser.close(); await bench.teardown(); summarize()
}
record('S2 lane-map present', 'pass', `segs=${lm.segs.length}`)
const text = lm.text

// T1 判据2：头部三色图例（agent/gate/you 三项小图例）。
const legendWords = ['agent', 'gate', 'you'].filter((w) => lm.header.toLowerCase().includes(w))
rec('T1 header kind legend has the three kind entries (agent/gate/you)',
  legendWords.length === 3, `header=${lm.header.slice(0, 120)}`)

// T2 判据3：头部摘要 elapsed … · now at …。
rec('T2 header summary carries elapsed and now-at',
  /elapsed/i.test(lm.header) && /now at/i.test(lm.header), lm.header.slice(0, 160))

// T3 判据5：当前段是人门 → 头部 waiting for you。
rec('T3 header says waiting-for-you while parked at the human gate',
  /waiting for you/i.test(lm.header), lm.header.slice(0, 160))

// T4 判据4：耗时写在标签行（灰盒锚：夹具实测 plan=2m、build=8m，模型 fmtDur
// 词面为 `Nm`；断言这两个已知值出现在图面文本里，固定宽/无名实现必红）。
rec('T4 measured durations are printed on the map (plan 2m, build 8m)',
  /(^|[^\d])2m([^\d]|$)/.test(text) && /(^|[^\d])8m([^\d]|$)/.test(text),
  text.replace(/\s+/g, ' ').slice(0, 160))

// T5 判据5：人门段菱形 glyph（矢量 path；虚线圈人形脸退役）。菱形 path 的
// d 形如 M..l3.5 3.5 l-3.5 3.5 l-3.5 -3.5 z（四段等长折线闭合）——按
// KI-051 锚语义：只断 svg path 存在且为闭合四折线族，不锚字面坐标。
const diamondish = lm.svgPaths.some((d) => /l\s*-?[\d.]+\s+-?[\d.]+/.test(d) && /z/.test(d))
rec('T5 human gate drawn as a vector diamond glyph', diamondish, `svgPaths=${JSON.stringify(lm.svgPaths)}`)

// T6 判据6：时间轴=起止两时刻，且与段同一比例尺。起=首条可解析 at=夹具 T0；
// 止=起+elapsed——开着的 signoff 窗随真实时钟增长（模型口径：头部 elapsed 与
// 段宽同一权重和，轴端随之前移，不造假终点的时钟），所以比例尺面断言
// 「止-起 ≥ 闭合窗总和 11m（跨日取模）」而非钉死夹具预判值。
const startClock = hhmm(T0)
const minOf = (s) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5))
const scaleOk = lm.clocks.some((t) => t !== startClock && ((minOf(t) - minOf(startClock)) + 1440) % 1440 >= 11)
rec('T6 time axis shows start and end clock times at the segment scale',
  lm.clocks.includes(startClock) && lm.clocks.length >= 2 && scaleOk,
  `clocks=${lm.clocks.join(',')} expect start=${startClock} end>=start+11m`)

// T7 判据3：skipped=虚线空框（optional 被旁路：extra_check todo 而后段 done）。
const skipped = lm.segs.find((s) => (s.stage || '').includes('extra'))
rec('T7 bypassed optional stage renders as a dashed empty segment',
  Boolean(skipped) && skipped.borderStyle === 'dashed',
  skipped ? `border=${skipped.borderStyle} w=${skipped.w}` : 'extra_check segment not found')

// T8 判据3：now 游标（当前段右缘虚线竖线）。
rec('T8 a now cursor marks the current segment', lm.cursor, `cursor=${lm.cursor}`)

// T9 畸形输入面：坏 `at` + 坏条目不产生 `undefined` 字面、零 pageerror。
rec('T9 malformed timeline entries leak nothing (no undefined literal)',
  !/undefined/i.test(text), text.replace(/\s+/g, ' ').slice(0, 120))
rec('T10 zero pageerror on the detail face', pageErrors.length === 0,
  pageErrors.join(' | ').slice(0, 200))

// T11 判据8 hover：段 title/aria-label 含时长（8m 段）。
const hoverWithDur = await page.evaluate(`(() => {
  const lm = document.querySelector('[data-testid="detail-lane-map"]')
  if (!lm) return false
  return [...lm.querySelectorAll('[title], [aria-label]')]
    .some(el => /8m/.test(el.getAttribute('title') || el.getAttribute('aria-label') || ''))
})()`)
rec('T11 segment hover detail carries the duration (8m on the build segment)',
  hoverWithDur, `hoverWithDur=${hoverWithDur}`)

// T13 判据4 的夹边面（验收 gen0 观察项）：每个标签块都落在图面 padding box 内
// （首/末标签向内对齐后不得越出画布；容差 1px）。
const clampOk = await page.evaluate(`(() => {
  const lm = document.querySelector('[data-testid="detail-lane-map"]')
  if (!lm) return false
  const m = lm.getBoundingClientRect()
  return [...lm.querySelectorAll('.wb-lm-label')].every((el) => {
    const r = el.getBoundingClientRect()
    return r.left >= m.left - 1 && r.right <= m.right + 1
  })
})()`)
rec('T13 edge labels stay inside the map canvas (mock criterion 4 clamp)',
  clampOk, `clampOk=${clampOk}`)

// T12 明暗双主题捕获（KI-055 证据面；尽力而为，不判红）。
const outDir = join(REPO, 'integration', 't261009-22', 'out')
try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
for (const scheme of ['light', 'dark']) {
  try {
    await page.emulateMedia({ colorScheme: scheme })
    await page.waitForTimeout(300)
    const lmEl = await page.$('[data-testid="detail-lane-map"]')
    if (lmEl) { await lmEl.scrollIntoViewIfNeeded(); await page.waitForTimeout(200) }
    const shot = lmEl || page
    await shot.screenshot({ path: join(outDir, `lane-map-chrome-${scheme}.png`) })
    record(`T12 capture-${scheme}`, 'pass', `out/lane-map-chrome-${scheme}.png`)
  } catch (e) {
    record(`T12 capture-${scheme}`, 'na', String(e).slice(0, 120))
  }
}

await browser.close()
try { await bench.teardown() } catch { /* down */ }
summarize()
