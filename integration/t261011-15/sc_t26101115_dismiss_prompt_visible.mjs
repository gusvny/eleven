#!/usr/bin/env node
// t261011-15 场景：摘除理由框在长列表下的可见性面（灰盒 L3，browser-free 池，
// 镜 t261008-08/sc_t26100808_left_column_row_composition.mjs 的 bootConsole +
// API 打桩 + 真浏览器形态）。
//
// 用户场景（工单正文）：在左栏 failed 行点 Dismiss，理由框是滚动容器的最后一个
// 孩子——板面一长（宿主实况：4 项目 / 310 票）框就开在折叠线以下，点击看起来
// 没反应，理由没处填、请求从不发出。修复后：理由框锚到被点行、open effect
// scrollIntoView + focus，列表多长都可见；restore 同一规则。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。playwright 缺席
// =ENV_FAIL（KI-036，经 lib_pw_deps 单点解析）。
//
// intent 分界（防 intent 级重复）：
//   - 行两行组成/悬停/项目块边框/排序控件 → t261008-08 与 t261006-18（本条零重叠）。
//   - dismiss 的 **答案面**（路由→真 ticket.py→journal 落盘→行离板）与 who/reason
//     契约 → t261009-54 的 sc_t26100954_dismiss_seam_engine_answer（真缝端到端，
//     journal 行读取自盘面）。本条只借「请求到达引擎缝」一根针（stub trace 出现
//     ticket:dismiss + 拒收原文上脸），不重复 journal 断言。
//   - 空项目键（unowned 组）不带 ?project= 的 URL 契约 → L1（t261011-15-dismiss-
//     request）钉死；本条只钉「带键的浏览器请求线上确实带 ?project=」。
// KI 对齐：KI-055（真浏览器断言）；KI-052（双 bundle 同步，S0）；KI-036（playwright
// 缺席=ENV_FAIL）；输入三态（拒收原文逐字上脸，绝不被吞）。
// 新故障面登记建议（integration 岗位）：「行内弹层开在滚动容器尾部 ⇒ 折叠线以下
// 不可见」——老测试用短夹具列表看不见此面；长列表可见性断言必须锚 viewport。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, dismissNotice } from '../t260904-17/lib_fix17.mjs';
import { loadPlaywright } from '../lib_pw_deps.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()

// ---------------------------------------------------------------- boot（离线隔离台）

let BASE = ''
let bench = null
const PROJ = 'fixture-dv'   // 长列表主项目（dismiss 脸载体）
const PROJ2 = 'fixture-rs'  // restore 脸载体（折叠行）
// Dwell window is a pinned 24 h (failed rows settle like closed ones) — fixture
// rows must be fresh against the real wall clock or the sidebar retires them.
const T0 = Math.floor(Date.now() / 1000) - 600
const TARGET = 'fd-last'    // 被点的最后一个 failed 行
const RESTORE_TARGET = 'rs-d1'

function devRow(id, title, ts, extra = {}) {
  return {
    id, role: 'developer', status: 'failed', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: 'failed',
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    epic: 'dismiss-visibility', ...extra,
  }
}

// 长 failed 列表：70 行 ≈ 远超 800px 视口（折叠线以下才有内容）。
const rows = []
for (let i = 0; i < 69; i++) rows.push(devRow(`fd${String(i).padStart(2, '0')}`, `bulk failed row ${i}`, T0 + i))
rows.push(devRow(TARGET, 'the failed row the person clicks', T0 + 500))
const rows2 = [
  devRow('rs-ok', 'normal failed row', T0),
  devRow(RESTORE_TARGET, 'dismissed row awaiting restore', T0 + 1,
    { dismissed: { at: '2026-10-11T09:00:00Z', who: 'host', reason: 'duplicate of rs-ok' } }),
]

const stub = makeTicketStub()
stub.setCtrl({
  workflows: [],
  tickets: [
    ...rows.map(t => ({ ...t, project: PROJ })),
    ...rows2.map(t => ({ ...t, project: PROJ2 })),
  ],
  show: {},
})

try {
  const projectsRoot = makeRegistryRoot('t26101115-registry-')
  writeProjectEntry(projectsRoot, PROJ, PROJ, ['/tmp/fx-dv'])
  writeProjectEntry(projectsRoot, PROJ2, PROJ2, ['/tmp/fx-rs'])
  bench = await bootConsole(projectsRoot, stub)
  BASE = bench.base
  await benchAuthUrl(bench)
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function rec(name, cond, detail = '') {
  record(name, cond ? 'pass' : 'fail', detail)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- S0 build contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return false
  }
  if (readFileSync(LIB_JS, 'utf8') !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return false
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync')
  return true
}

// ---------------------------------------------------------------- 浏览器

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* poll */ }
    await new Promise(r => setTimeout(r, 200))
  }
  try { return await cond() } catch { return false }
}

// 断言绑公开行为（viewport 相交 + DOM 锚 data-*），不绑内部布局/类名主体。
const pw = await loadPlaywright()
if (!pw) {
  console.log('[ENV_FAIL] playwright-core unavailable (lib_pw_deps probe came back empty)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}
let browser = null
for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
  try { browser = await pw.chromium.launch(opts); break } catch { /* next */ }
}
if (!browser) {
  console.log('[ENV_FAIL] no chromium/chrome browser launchable')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

if (!buildContract()) { await browser.close(); summarize() }

const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage()
const dismissPosts = []
page.on('request', (req) => {
  const u = req.url()
  if (u.includes('/dismiss') || u.includes('/restore')) {
    dismissPosts.push({ url: u, body: req.postData() ?? '' })
  }
})
try {
  await bench.goto(page, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await dismissNotice(page)   // 出厂 notice 遮罩会截走点击与焦点——先关（t260904-15 面）
} catch (e) {
  console.log(`[ENV_FAIL] page load failed: ${String(e).slice(0, 160)}`)
  await browser.close()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// 等左栏长列表渲染出来（目标行存在 = 列表已就位）。行卡入口的真源是
// ticket-row-card.tsx 的 title 锚（failed 行 "Dismiss:…" / 折叠行 "Restore:…"），
// 不绑类名主体（t261008-08 同纪律）。
const FIND_BTN = `
(id, prefix) => {
  const sb = document.querySelector('.wb-sb') || document.body
  const leaves = [...sb.querySelectorAll('*')].filter(el => el.children.length === 0
    && (el.textContent || '').trim() === id)
  for (const leaf of leaves) {
    let w = leaf
    while (w && w !== document.body) {
      const btn = [...w.querySelectorAll('button')].find(b => (b.title || '').startsWith(prefix))
      if (btn) return btn
      w = w.parentElement
    }
  }
  return null
}
`
const listReady = await waitFor(async () =>
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(TARGET)}, 'Dismiss:') !== null`), 20000)
if (!listReady) {
  console.log('[ENV_FAIL] long failed list never rendered on the isolated bench (boot or fixture face broken)')
  await browser.close()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// S1: 点最后一个 failed 行的 Dismiss —— 理由框必须在视口内（不用人手滚）。
// 修复前该框开在滚动容器尾部 = 折叠线以下，本子用例在旧 bundle 上必红（TDD 信号）。
const prompt = page.locator('[data-wb-dismiss-prompt]')
await page.evaluate(`(${FIND_BTN})(${JSON.stringify(TARGET)}, 'Dismiss:').click()`)
await prompt.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
const inViewport = await prompt.evaluate((el) => {
  const r = el.getBoundingClientRect()
  return r.height > 0 && r.top >= -2 && r.bottom <= window.innerHeight + 2
    && r.left >= -2 && r.right <= window.innerWidth + 2
}).catch(() => false)
rec('S1 dismiss prompt visible in viewport on a long list', inViewport === true,
  inViewport ? 'prompt rect inside the 1280x800 viewport after the click' : 'prompt opened off-screen (or never appeared)')

// S2: 理由框拿到焦点（人可以直接打字——可见性的一部分）。
const focused = await page.evaluate(() => {
  const el = document.querySelector('[data-wb-dismiss-reason]')
  return el !== null && document.activeElement === el
})
rec('S2 reason box holds focus after opening', focused)

// S3: 线上面 —— 请求带 ?project=，body 只有 who/reason（引擎契约不变），且请求
// 真到达引擎缝（stub trace 出现 ticket:dismiss）。journal 落盘面归 t261009-54。
const traceSizeBefore = stub.traceSizeAt()
await page.locator('[data-wb-dismiss-reason]').click()
await page.keyboard.type('failed ticket, duplicating another lane')
await page.locator('[data-dismiss-confirm]').click()
await waitFor(async () => stub.readTrace().length > traceSizeBefore, 10000)
const post = dismissPosts.find(p => p.url.includes('/dismiss'))
rec('S3a dismiss POST carries ?project= on the wire',
  post !== undefined && post.url.includes(`project=${PROJ}`),
  post ? post.url : 'no dismiss POST observed')
let bodyOk = false
try {
  const b = JSON.parse(post?.body ?? '{}')
  bodyOk = typeof b.who === 'string' && b.who.trim() !== ''
    && typeof b.reason === 'string' && b.reason.trim() !== ''
    && !('project' in b)
} catch { bodyOk = false }
rec('S3b body carries who+reason only (engine contract unchanged)', bodyOk,
  post?.body ?? 'no body')
const traced = stub.readTrace().some(t => t.op === 'ticket:dismiss' && t.id === TARGET)
rec('S3c request reached the engine channel', traced)

// 拒收原文上脸（桩对该 op 具名拒收；面板必须逐字呈现，绝不吞）。
const noticeShown = await waitFor(async () =>
  (await page.locator('[data-wb-dismiss-notice]').textContent().catch(() => ''))?.trim() !== '', 8000)
rec('S3d refusal surfaces verbatim on the face (never swallowed)', noticeShown)

// 收掉本框，进 restore 子用例。
await page.locator('[data-dismiss-cancel]').click().catch(() => {})

// S4: restore 同一可见性规则 —— 打开 dismissed 折叠，点 Restore，理由框仍在视口内。
await page.locator(`[data-wb-dismissed-fold="${PROJ2}"] [data-wb-dismissed-toggle]`).click().catch(() => {})
const restoreReady = await waitFor(async () =>
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(RESTORE_TARGET)}, 'Restore:') !== null`), 8000)
if (!restoreReady) {
  record('S4 restore prompt same visibility rule', 'na', 'dismissed fold/restore control never rendered on the fixture face')
} else {
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(RESTORE_TARGET)}, 'Restore:').click()`)
  await prompt.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
  const rIn = await prompt.evaluate((el) => {
    const r = el.getBoundingClientRect()
    return r.height > 0 && r.top >= -2 && r.bottom <= window.innerHeight + 2
      && r.left >= -2 && r.right <= window.innerWidth + 2
  }).catch(() => false)
  rec('S4 restore prompt same visibility rule', rIn,
    rIn ? 'restore prompt rect inside the viewport' : 'restore prompt opened off-screen')
}

await browser.close()
summarize()
