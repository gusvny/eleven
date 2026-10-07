#!/usr/bin/env node
// t261008-08 场景：左栏工单行 mock v11 对齐——本条独占面（灰盒 L3，browser-free 池，
// 两层式，镜 t261006-18/sc_t26100618_left_column_order.mjs 的 bootConsole + API 打桩）。
//
// 用户场景（host order 261008 option A）：更新时间与一句进展收进行悬停（行面不再可见
// 时间）；项目块只有下边框（3px 项目左色条拔除）且项目身份仍在徽标+项目名上；你暂停
// 的票行只有琥珀点（无位次号/把手/箭头）；畸形时间输入（updated/updated_ts 双缺）行
// 照常渲染、悬停无 undefined 字面量；明暗两主题捕获（验收证据面）。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。
// intent 分界（防 intent 级重复）：行两行组成、状态词缺席、行零彩条、箭头行尾/位次+
// 把手次序归 t261006-18-left-column-order（A2c/A2d/A2e，本票同步新增）；项目左条拔除
// 的旅程面归 t261005-09-left-column-ui-journey B1（bar!==true）；排序控件可发现性与
// 调序写脸归 t261006-18 既有条目；在跑绿点行归同条 A3。本条独占：悬停收纳面、项目块
// 下边框+身份面、paused 标志行（引擎 pause 脸，区别 human-hold）、畸形时间三态、
// 明暗捕获。
// KI 对齐：KI-055（真浏览器断言+明暗两主题）；KI-052（双 bundle）；KI-036（playwright
// 缺席=ENV_FAIL）；输入三态（缺时间字段不炸、无 undefined）。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t26100808-registry-')
  writeProjectEntry(projectsRoot, 'fixture-comp', 'fixture-comp', ['/tmp/fx-comp'])
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

const PROJ = 'fixture-comp'
const Q1 = 'cq1a'    // 排队（位次 1，悬停断言载体）
const PAU = 'cp3c'   // 你暂停（paused:true，不在并发脸任何一列）
const T0 = 1789353600

function devRow(id, title, ts, extra = {}) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    epic: 'concurrency-limit', ...extra,
  }
}
const TICKETS = [
  devRow(Q1, 'tooltip containment ticket', T0),
  devRow(PAU, 'paused composition ticket', T0 + 2, { paused: true }),
]

function concurrencyFace() {
  return {
    project: PROJ, limit: 2, unlimited: false,
    holders: [],
    queue: [{ ticket: Q1, position: 1, since: T0, waited_s: 3.3 }],
  }
}

let malformTime = false

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

// —— 绑浅的 DOM 探针（页面内跑；行级锚 data-ticket-id / data-order-dot，不绑类名主体）——
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
  const byAttr = [...g.querySelectorAll('[data-ticket-id]')].filter(el => el.getAttribute('data-ticket-id') === id)
  if (byAttr.length) return byAttr[0]
  const leaf = [...g.querySelectorAll('*')].find(el => el.children.length === 0
    && (el.textContent || '').trim() === id)
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
function controlsIn(row) {
  const hits = []
  for (const el of row.querySelectorAll('[aria-label],button,[draggable="true"],[title]')) {
    const lab = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim()
    if (/drag|grip|handgrip|move up|move down|reorder/i.test(lab) || /^(⋮⋮|⌃|⌄|▲|▼|↑|↓)$/.test(lab)) hits.push(lab)
    if (el.getAttribute && el.getAttribute('draggable') === 'true') hits.push('draggable')
  }
  return [...new Set(hits)]
}
function rowFace(id) {
  const row = rowFor(id)
  if (!row) return null
  return {
    leaves: leafTexts(row),
    dot: row.querySelector('[data-order-dot]') ? row.querySelector('[data-order-dot]').getAttribute('data-order-dot') : null,
    pos: !!row.querySelector('[data-order-pos]'),
    grip: !!row.querySelector('[data-order-grip]'),
    controls: controlsIn(row),
    tip: row.getAttribute('title') || '',
    visibleTime: /\\b\\d{1,2}:\\d{2}\\b/.test(row.textContent || '') || /\\bago\\b/.test(row.textContent || ''),
  }
}
function blockFace() {
  const g = projectGroup()
  if (!g) return null
  const cs = getComputedStyle(g)
  return {
    blw: parseFloat(cs.borderLeftWidth) || 0,
    bbw: parseFloat(cs.borderBottomWidth) || 0,
    badge: g.querySelectorAll('svg').length,
    name: leafTexts(g).includes(${JSON.stringify(PROJ)}),
  }
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
      const rq = route.request()
      const method = typeof rq.method === 'function' ? rq.method() : rq.method
      if (/concurrency$/.test(path) && method === 'GET') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify(concurrencyFace()) })
      }
      if (path === '/sandbar-workbench/api/wf/projects') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { projects: [
            { key: PROJ, name: PROJ, primary: '/tmp/fx-comp', dirs: ['/tmp/fx-comp'] },
          ], quarantined: [] } }) })
      }
      if (path === '/sandbar-workbench/api/wf/tickets') {
        const rows = malformTime
          ? TICKETS.map(t => { const c = { ...t }; delete c.updated; delete c.updated_ts; return c })
          : TICKETS
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { tickets: rows, workflows: [{ id: 'dev-lane', name: 'dev lane', lane: 'worktree', stages: [{ id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] }] }] } }) })
      }
      if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { tickets: [], count: 0 } }) })
      }
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
    })

    await bench.goto(page, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    const rendered = await waitFor(() => probe(page, '!!projectGroup()'), 8000)
    if (!rendered) {
      record('S1 precheck', 'env_fail', 'project group never rendered (stub /wf/projects unconsumed? bench=' + BASE + ')')
      return
    }
    record('S1 precheck', 'pass', `left column group rendered (${PROJ})`)

    // T1 悬停收纳：排队行行面不可见时间/ago，悬停（title 属性）带 Updated 事实。
    const q = await probe(page, `rowFace(${JSON.stringify(Q1)})`)
    if (!q) { record('T1 queued-row', 'fail', 'queued row not found'); return }
    rec('T1a timestamp leaves the visible row (lives in the tooltip)',
      !q.visibleTime && /Updated\b/.test(q.tip),
      `visibleTime=${q.visibleTime} tip=${JSON.stringify(q.tip.slice(0, 120))}`)

    // T1b 行面构成（票面点名断言面）：一行=位次号+彩点+编号+标题（无英文状态词、
    // 无 epic chip）；二行=阶段小字+epic chip+十格点（无进展句元素、无相对时间元素）。
    const comp = await probe(page, `(() => {
      const row = rowFor(${JSON.stringify(Q1)})
      if (!row) return null
      return {
        stateWord: !!row.querySelector('.wb-card-state'),
        stage: row.querySelector('.wb-card-stage') ? row.querySelector('.wb-card-stage').textContent.trim() : null,
        epic: row.querySelector('.wb-card-epic') ? row.querySelector('.wb-card-epic').textContent.trim() : null,
        dots: row.querySelectorAll('.wb-stage-dot').length,
        prog: !!row.querySelector('.wb-card-progress'),
        time: !!row.querySelector('.wb-card-time'),
      }
    })()`)
    rec('T1b queued row composition: line1 = pos + dot + id + title (no state word), line2 = stage + epic + ten dots',
      !!comp && comp.stateWord === false && !!comp.stage && !!comp.epic && comp.dots === 10
        && comp.prog === false && comp.time === false,
      comp ? JSON.stringify(comp) : 'no row')

    // T1c 行尾箭头 + 行零左色条：排序控件右缘贴齐行右缘（容差 12px = 行自身 8px 内边距
    // 的合法留白，非浮动偏移），位次号在把手左侧；行本体左边条宽 <2px（4px epic 条已退
    // 役，票 t261008-08）。
    const ends = await probe(page, `(() => {
      const row = rowFor(${JSON.stringify(Q1)})
      if (!row) return null
      const ctl = row.querySelector('[data-order-ctl]')
      const pos = row.querySelector('[data-order-pos]')
      const grip = row.querySelector('[data-order-grip]')
      const blw = parseFloat(getComputedStyle(row).borderLeftWidth) || 0
      if (!ctl || !pos || !grip) return { ctl: !!ctl, pos: !!pos, grip: !!grip, blw }
      const gap = Math.round(row.getBoundingClientRect().right - ctl.getBoundingClientRect().right)
      return { gap, posBeforeGrip: pos.getBoundingClientRect().right <= grip.getBoundingClientRect().left + 2, blw }
    })()`)
    rec('T1c arrows sit at the row end, pos first + grip after, no left colour bar on the row',
      !!ends && typeof ends.gap === 'number' && Math.abs(ends.gap) <= 12
        && ends.posBeforeGrip === true && ends.blw < 2,
      ends ? JSON.stringify(ends) : 'no row')

    // T2 项目块：左条为零、下边框在（mock .proj 面），身份仍在徽标+项目名。
    const blk = await probe(page, 'blockFace()')
    rec('T2 project block: no left bar, bottom border only, identity on badge + name',
      !!blk && blk.blw === 0 && blk.bbw >= 1 && blk.badge >= 1 && blk.name === true,
      blk ? JSON.stringify(blk) : 'no block')

    // T3 你暂停的行：琥珀点（paused），无位次号、无把手、无排序控件（区别 human-hold 行）。
    const p3 = await probe(page, `rowFace(${JSON.stringify(PAU)})`)
    rec('T3 paused row: dot only, no position, no controls',
      !!p3 && p3.dot === 'paused' && !p3.pos && !p3.grip && p3.controls.length === 0,
      p3 ? `dot=${p3.dot} pos=${p3.pos} grip=${p3.grip} controls=${JSON.stringify(p3.controls)}` : 'no row')

    // T4 明暗两主题捕获（验收证据面；尽力而为，不判红）。
    const outDir = join(REPO, 'integration', 't261008-08', 'out')
    try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
    for (const scheme of ['light', 'dark']) {
      try {
        if (scheme === 'dark') await page.emulateMedia({ colorScheme: 'dark' })
        await page.waitForTimeout(400)
        await page.locator('.wb-sb').first().screenshot({ path: join(outDir, `left-column-${scheme}.png`) })
        record(`T4 capture ${scheme}`, 'pass', `integration/t261008-08/out/left-column-${scheme}.png`)
      } catch (e) {
        record(`T4 capture ${scheme}`, 'na', `screenshot unavailable: ${String(e).slice(0, 120)}`)
      }
    }

    // T5 畸形时间输入（三态）：updated/updated_ts 双缺 → 行照常渲染、悬停无 undefined
    // 字面量、零新增 pageerror（独立分支，pageerror 单独计）。
    const errsBefore = pageErrors.length
    malformTime = true
    await page.reload({ waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)
    const mrowReady = await waitFor(() => probe(page, `!!rowFor(${JSON.stringify(Q1)})`), 8000)
    const mrow = mrowReady ? await probe(page, `rowFace(${JSON.stringify(Q1)})`) : null
    rec('T5 malformed timestamps: row renders, tooltip never says undefined, zero crash',
      !!mrow && mrow.leaves.includes(Q1) && !/undefined/.test(mrow.tip)
        && pageErrors.length === errsBefore,
      mrow ? `tip=${JSON.stringify(mrow.tip.slice(0, 120))} pageErrors=+${pageErrors.length - errsBefore}` : 'row missing under malformed face')

    rec('S1 page-health', pageErrors.length === 0,
      pageErrors.length ? `pageerror: ${pageErrors[0]}` : 'zero pageerror across legs')
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

buildContract()
const pw = await loadPlaywright()
if (!pw) {
  record('S1 playwright', 'env_fail', 'playwright-core not resolvable (KI-036 family)')
  summarize()
}
const browser = await launchBrowser(pw)
if (!browser) {
  record('S1 chromium', 'env_fail', 'chromium/chrome cannot start (headless environment)')
  summarize()
}
try {
  await runBrowser(pw, browser)
} catch (e) {
  record('S1 run-browser', 'fail', `uncaught: ${String(e && e.stack || e).slice(0, 500)}`)
} finally {
  await browser.close().catch(() => {})
}
summarize()
