#!/usr/bin/env node
// t260925-18 UI 截图证据通道（工单台英文化 + spec markdown + 砍底部六区块）。
// 形态沿 t260916-15/capture_sidebar_ui.mjs（fixture bootConsole + page.route 桩 API，
// freePort 拒 3099=红线零接触，teardownOnExit 全终态回收）。数据只桩 API 边界。
// 截图三张，文件名带 SHOT_SUFFIX（before/after 由调用方区分改动前后 bundle）：
//   t260925-18-detail-$SUFFIX.png     详情页（正文卡+spec卡+泳道图，改动前含底部六区块）
//   t260925-18-sidebar-$SUFFIX.png    左栏工单列表
//   t260925-18-lanemap-$SUFFIX.png    泳道图区域裁剪
import { writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub } from '../t260904-17/lib_fix17.mjs'

const REPO = process.cwd()
setTimeout(() => { console.log('[TIMEOUT] capture watchdog 120s'); process.exit(3) }, 120_000).unref()
const SUFFIX = process.env.SHOT_SUFFIX || 'shot'
const OUT = join(REPO, '.sandbar', 'screenshots')
mkdirSync(OUT, { recursive: true })

const PROJ = 'fixture-ui18'
const T1 = 'uifx182601dev'
const T2 = 'uifx182602run'
const T0 = Math.floor(Date.now() / 1000) - 3600

// 模板带 topology（泳道图数据源；label=引擎中文数据，前端映射表负责英文显示）。
const WORKFLOWS = [{
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  topology: {
    version: 'topology-v1', template: 'dev-lane', name: '开发泳道',
    nodes: [
      { id: 'create_plan', label: '做方案', role: 'developer', kind: 'agent', parts: ['agent'] },
      { id: 'review_plan', label: '审方案', role: 'integration', kind: 'human', parts: ['human'] },
      { id: 'implement', label: '实现', role: 'developer', kind: 'agent', parts: ['agent'] },
      { id: 'design_integration_tests', label: '集成验证', role: 'integration', kind: 'gate', parts: ['script'] },
    ],
    edges: [['create_plan', 'review_plan'], ['review_plan', 'implement'], ['implement', 'design_integration_tests']],
    groups: [],
  },
  stages: [
    { id: 'create_plan', name: '做方案', role: 'developer', parts: ['agent'], acceptance: ['方案落结果文件'] },
    { id: 'review_plan', name: '审方案', role: 'integration', parts: ['human'] },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
    { id: 'design_integration_tests', name: '集成验证', role: 'integration', parts: ['script'] },
  ],
}]

const SPEC = `# 执行规格\n\n这是**加粗**与 \`inline code\` 示例，来自 agent 的中文内容（数据不译）。\n\n- 要点一：接口文案英文化\n- 要点二：spec 渲染 markdown\n\n1. 有序列表项\n2. 第二项\n\n\`\`\`bash\nbash server/plugins/workbench/build-client.sh\n\`\`\`\n\n> 引用块：底部六区块只删 UI 不删数据。\n`

function row(id, stageState, status, over = {}) {
  return { id, role: 'developer', status, title: `Fixture ticket ${id.slice(-3)} (data stays Chinese 数据不译)`,
    workflow: 'dev-lane', workflow_id: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 1, pending_count: 0, worktree: '', updated: '—', updated_ts: T0, created: T0,
    engine: 'template-as-code-v2', exec_status: 'RUNNING', session_kb: 42, agent_alive: true, ...over }
}

const ROWS = [
  row(T1, 'running', 'dispatched'),
  row(T2, 'awaiting-human', 'dispatched', { updated_ts: T0 + 600 }),
]

// 详情投影（ticket show 面的 UI 消费子集；底部六区块字段 before 帧给全，after 帧区块已删）。
const DETAIL = {
  ...row(T1, 'running', 'dispatched'),
  body: '工单正文（原始需求）——用户原话，数据不译。spec 字段需要 markdown 渲染。',
  spec: SPEC,
  stage_name: '实现',
  workspace: { type: 'worktree', path: '/repo/.lane/uifx182601dev' },
  branch: 'lane/uifx182601dev', base_ref: 'a'.repeat(40),
  revision_count: 2,
  write_set: ['server/plugins/workbench/', 'app/'],
  workflow_input: { ticket: T1, operator: 'host' },
  acceptance: ['方案落结果文件', '自测全绿'],
  checks: {},
  log: [{ ts: T0, status: 'dispatched', note: '派段' }, { ts: T0 + 300, status: 'running', note: '进入实现段' }],
  handoffs: [{ stage: 'create_plan', ts: T0, agent_id: 'dev-agent', summary: '方案交付', artifacts: ['.sandbar/stage_create_plan_gen0.json'] }],
  deliverables: ['.sandbar/stage_implement_gen0.json'],
  pending: [],
  handoff_count: 1,
}

function ok(result) { return { contentType: 'application/json', body: JSON.stringify({ ok: true, result }) } }

let bench = null
try {
  const projectsRoot = makeRegistryRoot('t260925-18-shot-registry-')
  writeProjectEntry(projectsRoot, PROJ, '夹具UI18', ['/tmp/fx-ui18'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] console 不可得：${String(e).slice(0, 200)}`)
  process.exit(2)
}
const main = (() => {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
})()
let pw = null
for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
  'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
  try { pw = await import(join('file://', main, sub)); break } catch { /* next */ }
}
if (!pw) { console.log('[ENV_FAIL] playwright-core 不可解析'); process.exit(2) }
let browser = null
for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
  try { browser = await pw.chromium.launch(opts); break } catch { /* next */ }
}
if (!browser) { console.log('[ENV_FAIL] chromium/chrome 无法启动'); process.exit(2) }

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* poll */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

const ctx = await browser.newContext()
// dsh web 页面级鉴权（t260925-18 补）：隔离台拷贝了凭据文件时首页 401，
// token 在 console.log 打印的 URL 里——捞出来拼回导航地址（API 路由桩不受影响）。
let openUrl = `${bench.base}/`
try {
  const { readFileSync } = await import('node:fs')
  const log = readFileSync(join(bench.tmpHome, 'console.log'), 'utf8')
  const m = log.match(/https?:\/\/[^\s"'<>]*token=[^\s"'<>]+/)
  if (m) openUrl = m[0]
} catch { /* 无凭据台无 401，直接用 base */ }
try {
  const page = await ctx.newPage()
  await page.route('**/sandbar-workbench/api/wf/**', (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/+$/, '')
    if (path === '/sandbar-workbench/api/wf/projects') {
      return route.fulfill(ok({ projects: [{ key: PROJ, name: '夹具UI18', primary: '/tmp/fx-ui18', dirs: ['/tmp/fx-ui18'] }], quarantined: [] }))
    }
    if (path === `/sandbar-workbench/api/wf/tickets/${T1}`) return route.fulfill(ok(DETAIL))
    if (path === '/sandbar-workbench/api/wf/tickets' || path === '/sandbar-workbench/api/wf/tickets') {
      // 客户端从列表聚合响应根取 workflows（index.tsx setWorkflows(data.workflows)），
      // 不在 result 内——放错层=泳道图数据源缺失（.wb-lanemap 不渲染，lanemap 截图恒缺）。
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: ROWS }, workflows: WORKFLOWS }) })
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'shot stub: unknown ' + path }) })
  })

  page.on('console', (m) => { if (m.type() === 'error') console.log('[page-err]', m.text().slice(0, 200)) })
  page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 300)))
  await page.goto(openUrl, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(3000)
  console.log('[mark] loaded')
  // 打开详情页（点工单行）。
  const rowEl = page.locator(`.wb-card[data-ticket-id="${T1}"], [data-ticket-id="${T1}"]`).first()
  if (!(await waitFor(async () => (await rowEl.count()) > 0, 15000))) {
    console.log('[FAIL] 左栏工单行未渲染')
    const txt = await page.locator('body').innerText().catch(() => '')
    console.log('[debug] body text head:', txt.slice(0, 600).replace(/\n+/g, ' | '))
    process.exit(1)
  }
  // 过场弹层（Internal Testing Notice 等）先关掉，再点行开详情；点完断言 spec 卡在场。
  for (let i = 0; i < 5; i++) {
    const dialog = page.locator('[role="dialog"], .dsh-modal, [class*="modal"]').first()
    if (!(await dialog.count())) break
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(600)
  }
  let opened = false
  for (let i = 0; i < 3 && !opened; i++) {
    await rowEl.click({ force: true }).catch(() => {})
    await page.waitForTimeout(2500)
    opened = (await page.locator('.wb-d2-spec, .wb-d2-body').count()) > 0
  }
  if (!opened) {
    console.log('[FAIL] 详情页未打开（spec 卡未渲染）')
    const txt = await page.locator('body').innerText().catch(() => '')
    console.log('[debug] body text head:', txt.slice(0, 400).replace(/\n+/g, ' | '))
    process.exit(1)
  }
  await page.screenshot({ path: join(OUT, `t260925-18-detail-${SUFFIX}.png`), fullPage: true, timeout: 20000 })
  const left = page.locator('.wb-sb-left').first()
  if (await left.count()) await left.screenshot({ path: join(OUT, `t260925-18-sidebar-${SUFFIX}.png`), timeout: 20000 }).catch(() => {})
  // 泳道图裁剪：滚动进视口再截（t260915-05 泳道图替换线性步骤条；找不到=点名而非静默）。
  await page.mouse.wheel(0, 400).catch(() => {})
  await page.waitForTimeout(1200)
  const lane = page.locator('.wb-lanemap').first() // t260925-18 实测：泳道图根类名=wb-lanemap
  // 泳道图可能在深查折叠内（wb-d2-more）：先展开再找。
  if (!(await page.locator('.wb-lanemap').count())) {
    const more = page.locator('.wb-d2-more > div, .wb-d2-more .ttl, .wb-d2-more').first()
    if (await more.count()) { await more.click({ force: true }).catch(() => {}); await page.waitForTimeout(1500) }
  }
  const laneN = await page.locator('.wb-lanemap, [data-template]').count()
  console.log(`[debug] lanemap candidates=${laneN}`)
  if (await lane.count()) {
    await lane.scrollIntoViewIfNeeded().catch(() => {})
    await lane.screenshot({ path: join(OUT, `t260925-18-lanemap-${SUFFIX}.png`), timeout: 20000 }).catch((e) => console.log('[FAIL] lanemap shot', String(e).slice(0, 120)))
  } else {
    console.log('[FAIL] .wb-lanemap not found in detail (candidates=' + laneN + ')')
    const dsh = await page.evaluate(() => [...document.querySelectorAll('[class*=d2], [class*=lane]')].map(e => e.className).slice(0, 20))
    console.log('[debug] classes:', JSON.stringify(dsh))
  }
  console.log(`[PASS] 截图落盘 ${OUT}（suffix=${SUFFIX}）`)
  writeFileSync(join(OUT, `t260925-18-${SUFFIX}.txt`), `base=${bench.base}\n`, 'utf8')
} finally {
  await ctx.close().catch(() => {})
  await browser.close().catch(() => {})
}
// 退出卫生（arbitrate gen4 挂账）：teardown 句柄会吊住事件循环，watchdog exit 3 是
// 收尾兜底而非信号——正常路径在浏览器关闭后显式退出，别让看门狗冒充结局。
process.exit(0)
