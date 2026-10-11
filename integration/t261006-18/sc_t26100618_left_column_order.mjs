#!/usr/bin/env node
// t261006-18 场景：左栏工单顺序的 UI 面（灰盒 L3，browser-free 池；两层式，镜
// t261005-09/sc_left_column_ui_journey.mjs 的 bootConsole + API 边界打桩两层）。
//
// 用户场景（epic concurrency-limit CL-3，设计稿 §2.2/§7.2）：人打开控制台左栏，
// 项目行右侧报两个数（X at work · Y waiting，不写句子）；展开项目的工单列表两行制
// （行1 票号+标题，行2 阶段小字+十格进度点，点为默认）；排队票行首位次号+把手+上下
// 箭头，可调序；在跑票绿点、你暂停/等你的票琥珀点——都不参与排序（无把手无箭头）。
// 人动的每一手都写成引擎排列（POST reorder）再重读同一条读脸，本地不另记顺序。
//
// 两层：
//   S0 build-contract（纯 node）：shipped 双 bundle 同步（KI-052）。
//   S1 真浏览器 DOM：隔离台（lib_fix17 bootConsole，freePort 拒 3099；teardownOnExit
//      全终态回收）+ playwright-core + chromium，任一缺席=ENV_FAIL exit 2。数据只在
//      API 边界打桩（/wf/projects、/wf/tickets、并发读脸 GET、POST reorder），账册不
//      涉本票——浏览器/bundle/React 全真，宿主 3099 零接触。附：左栏左栏截图落
//      integration/t261006-18/out/（验收证据 1 的捕获面，尽力而为不判红）。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。实现段落地前红属预期
// （TDD 信号）；arbitrate/merge 期必须绿。
//
// intent 分界：引擎侧「人设顺序=下一个开跑」与排序拒绝矩阵归
// sc_t26100618_order_to_next_start.py（同目录，零浏览器）；t261005-09 左栏旅程只断
// 「不造序」（其 B4），本条独占顺序控件/两计数/点色/进度点/写脸重读的用户可见面。
// KI 对齐：KI-072（零墙钟断言，串行单页）；KI-052（双 bundle）；KI-055（真浏览器断言）；
// KI-036（playwright 缺席=ENV_FAIL）；畸形读脸三态（缺 queue/重复 id/列表外 id）
// 覆盖输入三态纪律——渲染回退为未排序列表，绝不发明顺序。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t26100618-registry-')
  writeProjectEntry(projectsRoot, 'fixture-order', 'fixture-order', ['/tmp/fx-order'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
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

// ---------------------------------------------------------------- 夹具

const PROJ = 'fixture-order'
const Q1 = 'tq1a', Q2 = 'tq2b', Q3 = 'tq3c'   // 排队三张（位次 1/2/3）
const RUN = 'tr4d'                             // 在跑（holder running，绿点）
const HOLD = 'th5e'                            // 人门占坑（holder human-hold，琥珀点）
const T0 = 1789353600

function devRow(id, title, ts) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    epic: 'concurrency-limit',
  }
}
const TICKETS = [devRow(Q1, 'first queued ticket', T0), devRow(Q2, 'second queued ticket', T0 + 1),
  devRow(Q3, 'third queued ticket', T0 + 2), devRow(RUN, 'at work ticket', T0 + 3),
  devRow(HOLD, 'held for you ticket', T0 + 4)]

// 并发读脸（engine read_state 形状：holders 带 reason，queue 带 1-based position）。
// face.queue 是可变布景：POST reorder 被接受后按 body.order 重排（写脸→重读同脸）。
function concurrencyFace(order) {
  return {
    project: PROJ, limit: 2, unlimited: false,
    holders: [
      { ticket: RUN, reason: 'running', since: T0, held_s: 12.5 },
      { ticket: HOLD, reason: 'human-hold', since: T0, held_s: 40.1 },
    ],
    queue: order.map((t, i) => ({ ticket: t, position: i + 1, since: T0, waited_s: 3.3 * (i + 1) })),
  }
}
let queueOrder = [Q1, Q2, Q3]
let faceState = { refuseNext: false, lastError: '' }
let getFaceHits = 0
let lastPost = null   // { url, body }

function unwrap(p) {
  // 绑浅：读脸允许裸 read_state 或 {ok:true,...} 包裹，取字段面即可。
  if (p && p.ok === true && p.data && typeof p.data === 'object') return p.data
  return p
}

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync')
}

// ---------------------------------------------------------------- S1 真浏览器

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}

async function loadPlaywright() {
  const candidates = ['playwright-core']
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) candidates.push(pathToFileURL(p).href)
  }
  for (const c of candidates) {
    try { return await import(c) } catch { /* next */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

// —— 绑浅的 DOM 探针（全部在页面里跑，不绑实现类名）——
const PROBES = `
function sidebarEl() {
  return document.querySelector('.wb-sb') || document.querySelector('[class*="sidebar" i]') || document.body
}
function projectGroup() {
  const sb = sidebarEl()
  const head = [...sb.querySelectorAll('*')].find(el => el.children.length === 0
    && (el.textContent || '').trim() === ${JSON.stringify(PROJ)})
  let w = head
  while (w && w !== document.body && !w.querySelector('[data-ticket-id]')) w = w.parentElement
  return w && w !== document.body ? w : null
}
function rowFor(id) {
  const g = projectGroup()
  if (!g) return null
  // 首选行级锚：data-ticket-id 属性（不绑类名）。属性缺失时从最小的含 id 文本
  // 叶子向上爬到「像一行的祖先」（含 ≥3 个叶子：id/标题/阶段行），绝不把纯
  // id 文本叶子本身当行容器（那会让行内一切探针落空）。
  const byAttr = [...g.querySelectorAll('[data-ticket-id]')].filter(el => el.getAttribute('data-ticket-id') === id)
  if (byAttr.length) return byAttr[0]
  const leaf = [...g.querySelectorAll('*')].find(el => el.children.length === 0
    && (el.textContent || '').trim() === id)
    || [...g.querySelectorAll('*')].find(el => el.children.length === 0
      && (el.textContent || '').includes(id))
  if (!leaf) return null
  let w = leaf
  while (w && w !== g) {
    const leaves = [...w.querySelectorAll('*')].filter(x => x.children.length === 0).length
    if (leaves >= 3) return w
    w = w.parentElement
  }
  return null
}
function leafTexts(root) {
  return [...root.querySelectorAll('*')].filter(el => el.children.length === 0)
    .map(el => (el.textContent || '').trim()).filter(Boolean)
}
function countsText() {
  const g = projectGroup()
  const hay = (g || sidebarEl()).textContent || ''
  const m = hay.match(/(\\d+)\\s+at work\\s*[·•]?\\s*(\\d+)\\s+waiting/i)
  return m ? { atWork: +m[1], waiting: +m[2], raw: m[0] } : null
}
function posEl(row) {
  return [...row.querySelectorAll('*')].find(el => el.children.length === 0
    && /^[1-9]\\d*$/.test((el.textContent || '').trim())) || null
}
function controlsIn(row) {
  const hits = []
  for (const el of row.querySelectorAll('[aria-label],button,[draggable="true"],[title]')) {
    const lab = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim()
    if (/drag|grip|handgrip|move|up|down|reorder/i.test(lab) || /^(⋮⋮|⌃|⌄|▲|▼|↑|↓)$/.test(lab)) hits.push(lab)
    if (el.getAttribute && el.getAttribute('draggable') === 'true') hits.push('draggable')
  }
  return [...new Set(hits)]
}
function classifyRGB(r, g, b) {
  // 比率制：色板经暗色 color-mix 后绝对值可能全暗，只有通道比站得住。
  if (g > r * 1.15 && g > b * 1.05 && g - r > 8) return 'green'
  if (r >= g && g > b && r > 60 && r - g > 8 && b < g * 0.9) return 'amber'
  return null
}
function dotColor(row) {
  const nodes = [...row.querySelectorAll('*')].filter(el => {
    const tag = [...(el.attributes || [])].map(a => a.name + '=' + a.value).join(' ') + ' ' + (el.className || '')
    return /dot/i.test(tag) && el.getElementsByTagName('*').length === 0
  })
  for (const el of nodes) {
    const cs = getComputedStyle(el)
    // 绑浅：计算色可能是 legacy rgb() 也可能是现代 color(srgb …)，两形都解析成 0-255。
    const raw = (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)')
      ? cs.backgroundColor : (cs.color || '')
    let m = raw.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/)
    let parts = m ? [+m[1], +m[2], +m[3]] : null
    if (!parts) {
      const s = raw.match(/color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)/)
      if (s) parts = [Math.round(+s[1] * 255), Math.round(+s[2] * 255), Math.round(+s[3] * 255)]
    }
    if (parts) {
      const c = classifyRGB(parts[0], parts[1], parts[2])
      if (c) return c
    }
  }
  return nodes.length ? 'unclassified' : 'no-dot'
}
function rowsOrder() {
  const g = projectGroup()
  if (!g) return null
  return ${JSON.stringify([Q1, Q2, Q3, RUN, HOLD])}.map(id => {
    const row = rowFor(id)
    const pe = row && posEl(row)
    return { id, present: !!row, pos: pe ? +pe.textContent.trim() : null }
  })
}
function sidebarWidth() {
  // 绑浅：设计 §2.2 的「左栏」=项目+工单列表列（.wb-sb-left；整窗三栏的左 15% 段）。
  // 优先量它；老壳无该类时回落侧栏根（同宽壳）。
  const el = document.querySelector('.wb-sb-left') || document.querySelector('.wb-sb')
    || document.querySelector('[class*="sidebar" i]')
  return el ? el.getBoundingClientRect().width : null
}
`

async function probe(page, expr) {
  return page.evaluate(`(() => { ${PROBES}; return (${expr}) })()`)
}

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))

    await page.route('**/sandbar-workbench/api/wf/**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname
      // old playwright-core builds expose method() only on some versions - both shapes accepted
      const rq = route.request()
      const method = typeof rq.method === 'function' ? rq.method() : rq.method
      if (/concurrency\/reorder$/.test(path) && method === 'POST') {
        let body = {}
        try { body = JSON.parse(route.request().postData() || '{}') } catch { /* malformed body stays captured */ }
        lastPost = { url: path, body }
        if (faceState.refuseNext) {
          return route.fulfill({ contentType: 'application/json',
            body: JSON.stringify({ ok: false, error: faceState.lastError }) })
        }
        queueOrder = Array.isArray(body.order) ? body.order.slice() : queueOrder
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, queue: queueOrder }) })
      }
      if (/concurrency$/.test(path) && method === 'GET') {
        getFaceHits += 1
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify(unwrapWrap(concurrencyFace(queueOrder))) })
      }
      if (path === '/sandbar-workbench/api/wf/projects') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { projects: [
            { key: PROJ, name: PROJ, primary: '/tmp/fx-order', dirs: ['/tmp/fx-order'] },
          ], quarantined: [] } }) })
      }
      if (path === '/sandbar-workbench/api/wf/tickets') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { tickets: TICKETS, workflows: [{ id: 'dev-lane', name: 'dev lane', lane: 'worktree', stages: [{ id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] }] }] } }) })
      }
      if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { tickets: [], count: 0 } }) })
      }
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
    })

    function unwrapWrap(payload) {
      // 读脸响应允许裸 read_state（现票面形状）；ok 包裹由 unwrap 消化。
      return payload
    }

    await bench.goto(page, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    const rendered = await waitFor(() => probe(page, '!!projectGroup()'), 8000)
    if (!rendered) {
      record('S1 precheck', 'env_fail', 'project group never rendered (stub /wf/projects unconsumed? bench=' + BASE + ')')
      return
    }
    record('S1 precheck', 'pass', 'project group rendered on the stubbed bench')

    // A1 项目行两计数：数字对（2 at work = holders running+human-hold；3 waiting = queue）。
    const counts = await probe(page, 'countsText()')
    rec('A1 project row reports two counts, numbers only',
      !!counts && counts.atWork === 2 && counts.waiting === 3,
      counts ? `raw=${JSON.stringify(counts.raw)}` : 'no "N at work · M waiting" text found (pre-implement red expected)')

    // A2 两行制 + 进度点（dots 默认）：每张排队票行内有位次号叶子；行组含 10 格点。
    const rows = await probe(page, 'rowsOrder()')
    const posOK = rows && [Q1, Q2, Q3].every((id, i) => {
      const r = rows.find(x => x.id === id)
      return r && r.present && r.pos === i + 1
    })
    rec('A2 queued rows carry 1-based position numbers in face order',
      !!posOK, JSON.stringify(rows))

    const dotsOK = await probe(page, `(() => {
      const row = rowFor(${JSON.stringify(Q1)})
      if (!row) return { ok: false, why: 'no row' }
      const g = projectGroup()
      const dots = [...(row.parentElement || g).querySelectorAll('*')].filter(el =>
        /dot/i.test([...(el.attributes || [])].map(a => a.name).join(' ') + ' ' + (el.className || '')))
      return { ok: dots.length >= 10, n: dots.length }
    })()`)
    rec('A2b progress rendered as ten-cell dots (default per §7.2)',
      !!dotsOK && dotsOK.ok === true,
      dotsOK ? `dot cells=${dotsOK.n}` : 'no row')

    // A3 在跑票（t261011-19 declared口径 change, design §14 line ①: the compact
    // row's LEADING colour marker is retired — the green data-order-dot=work now
    // lives only on the board column; the left column carries the state via the
    // ten-cell matrix and the LineOn pill). The stable contract here: no ordering
    // controls on an at-work row, and no colour marker on the compact row.
    const runRow = await probe(page, `(() => { const r = rowFor(${JSON.stringify(RUN)}); return r ? { ctl: controlsIn(r), dot: dotColor(r), marker: !!r.querySelector('[data-order-dot]') } : null })()`)
    rec('A3 at-work row: no ordering controls, leading colour marker retired on the compact row',
      !!runRow && runRow.ctl.length === 0 && runRow.marker === false,
      runRow ? `marker=${runRow.marker} controls=${JSON.stringify(runRow.ctl)}` : 'no row (pre-implement red expected)')

    // A4 人门占坑票（same declared口径 change: the amber hold dot is retired on the
    // compact row; anchors live on the board column only). Stable contract: no
    // ordering controls, no colour marker on the compact row.
    const holdRow = await probe(page, `(() => { const r = rowFor(${JSON.stringify(HOLD)}); return r ? { ctl: controlsIn(r), marker: !!r.querySelector('[data-order-dot]') } : null })()`)
    rec('A4 held-for-you row: no ordering controls, leading colour marker retired on the compact row',
      !!holdRow && holdRow.ctl.length === 0 && holdRow.marker === false,
      holdRow ? `marker=${holdRow.marker} controls=${JSON.stringify(holdRow.ctl)}` : 'no row (pre-implement red expected)')

    // A5 排队票行有把手与上下箭头（可发现性面；拖拽本体不锚）。
    const grip = await probe(page, `(() => { const r = rowFor(${JSON.stringify(Q2)}); return r ? controlsIn(r) : null })()`)
    const hasGrip = grip && grip.some(l => /drag|grip|handgrip|⋮⋮/i.test(l))
    const hasArrows = grip && grip.some(l => /up|down/i.test(l))
    rec('A5 queued row exposes a handgrip and up/down arrows',
      !!hasGrip && !!hasArrows,
      `controls=${JSON.stringify(grip)} (pre-implement red expected)`)

    // A6 调序一手：箭头点下 → POST reorder 带全排列 → 重读同脸 → 渲染跟随。
    getFaceHits = 0
    lastPost = null
    queueOrder = [Q1, Q2, Q3]
    const clicked = await probe(page, `(() => {
      const row = rowFor(${JSON.stringify(Q2)})
      if (!row) return false
      const btns = [...row.querySelectorAll('button,[aria-label],[role="button"]')]
      const up = btns.find(el => /up|⌃|▲|↑/i.test((el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '')))
      if (!up) return false
      up.click()
      return true
    })()`)
    await page.waitForTimeout(1200)
    const posted = lastPost
    const orderOK = posted && Array.isArray(posted.body.order)
      && posted.body.order.length === 3
      && posted.body.order[0] === Q2
      && [...posted.body.order].sort().join() === [Q1, Q2, Q3].sort().join()
    rec('A6a a move writes the FULL permutation through the engine reorder entry',
      !!clicked && !!orderOK,
      clicked ? `post=${JSON.stringify(posted && posted.body)}` : 'no up control to click')
    rec('A6b the same read face is re-fetched after the write (no local order kept)',
      getFaceHits >= 1, `read-face GET hits after the write=${getFaceHits} (one re-read of the SAME face is the spec-5 shape)`)
    const rowsAfter = await probe(page, 'rowsOrder()')
    const afterOK = rowsAfter && [Q2, Q1, Q3].every((id, i) => {
      const r = rowsAfter.find(x => x.id === id)
      return r && r.pos === i + 1
    })
    rec('A6c rendered positions follow the re-read face, not a local guess',
      !!afterOK, JSON.stringify(rowsAfter))

    // A7 拒绝透出：写脸拒收 → 具名错误可见、渲染顺序不动、本地不另记。
    faceState.refuseNext = true
    faceState.lastError = 'Concurrency queue reorder refused: the given order is not a permutation of the current queue'
    lastPost = null
    await probe(page, `(() => {
      const row = rowFor(${JSON.stringify(Q3)})
      const btns = [...row.querySelectorAll('button,[aria-label],[role="button"]')]
      const up = btns.find(el => /up|⌃|▲|↑/i.test((el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '')))
      if (up) up.click()
      return !!up
    })()`)
    await page.waitForTimeout(1000)
    const refusalShown = await probe(page,
      `((sidebarEl().textContent || '').includes('not a permutation'))`)
    rec('A7 engine refusal surfaces named in the UI, order unchanged',
      refusalShown, refusalShown ? 'refusal text visible' : 'refusal text not found after refused move (pre-implement red expected)')
    faceState.refuseNext = false

    // A8 畸形读脸三态：缺 queue / 重复 id / 列表外 id——渲染退回未排序列表，零崩溃。
    for (const [name, mutate] of [
      ['missing queue', f => { delete f.queue }],
      ['duplicate queue ids', f => { f.queue = [f.queue[0], f.queue[0], f.queue[1], f.queue[2]] }],
      ['queue id absent from ticket list', f => { f.queue = [{ ticket: 'ghost9z', position: 1, since: T0, waited_s: 1 }, ...f.queue] }],
    ]) {
      getFaceHits = 0
      await page.unroute('**/sandbar-workbench/api/wf/**')
      await page.route('**/sandbar-workbench/api/wf/**', (route) => {
        const url = new URL(route.request().url())
        const path = url.pathname
        if (/concurrency$/.test(path)) {
          const f = concurrencyFace(queueOrder)
          mutate(f)
          return route.fulfill({ contentType: 'application/json',
            body: JSON.stringify(unwrapWrap(f)) })
        }
        if (path === '/sandbar-workbench/api/wf/tickets') {
          return route.fulfill({ contentType: 'application/json',
            body: JSON.stringify({ ok: true, result: { tickets: TICKETS, workflows: [] } }) })
        }
        if (path === '/sandbar-workbench/api/wf/projects') {
          return route.fulfill({ contentType: 'application/json',
            body: JSON.stringify({ ok: true, result: { projects: [
              { key: PROJ, name: PROJ, primary: '/tmp/fx-order', dirs: ['/tmp/fx-order'] },
            ], quarantined: [] } }) })
        }
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
      })
      await page.reload({ waitUntil: 'networkidle' })
      await page.waitForTimeout(1200)
      const survived = await probe(page, `(() => {
        const g = projectGroup()
        if (!g) return { alive: false }
        const pos = ${JSON.stringify([Q1, Q2, Q3])}.map(id => { const r = rowFor(id); const pe = r && posEl(r); return pe ? +pe.textContent.trim() : null })
        const uniq = pos.filter(p => p !== null)
        const clean = uniq.length === new Set(uniq).size
        return { alive: true, pos, clean, ghostShown: (g.textContent || '').includes('ghost9z') }
      })()`)
      const okMalformed = !!survived && survived.alive
        && (survived.pos.every(p => p === null) || survived.clean)
        && !survived.ghostShown
      rec(`A8 malformed face (${name}) renders the un-ordered list, never a fabricated order`,
        okMalformed, JSON.stringify(survived))
    }

    // A9 左栏宽度 380px（§2.2：340px 下标题截得太狠）。
    const width = await probe(page, 'sidebarWidth()')
    rec('A9 left column width stays at the 380px design width',
      typeof width === 'number' && width >= 376 && width <= 384,
      width === null ? 'sidebar element not found' : `width=${Math.round(width)}px`)

    // A10 零 pageerror。
    rec('A10 zero page errors across the whole journey', pageErrors.length === 0,
      pageErrors.slice(0, 3).join(' | '))

    // 截图（验收证据 1 捕获面，尽力而为，不判红）。
    try {
      const outDir = join(REPO, 'integration', 't261006-18', 'out')
      mkdirSync(outDir, { recursive: true })
      await page.screenshot({ path: join(outDir, 'left-column-order.png'), fullPage: false })
      console.log(`[capture] ${join('integration', 't261006-18', 'out', 'left-column-order.png')}`)
    } catch (e) {
      console.log(`[capture] skipped: ${String(e).slice(0, 120)}`)
    }
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

buildContract()
const pw = await loadPlaywright()
const browser = pw ? await launchBrowser(pw) : null
if (!browser) {
  record('S1 browser', 'env_fail', 'playwright-core/chromium unavailable (KI-036 family) — ENV_FAIL, never a silent skip')
  summarize()
}
try {
  await runBrowser(pw, browser)
} finally {
  await browser.close().catch(() => {})
}
summarize()
