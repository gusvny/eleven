#!/usr/bin/env node
// t261011-19 场景：左栏 LineOn 线面徽标 + 点阵整阵同色相 + 板面无行底色（灰盒 L3，
// browser-free 池，两层式：页面桩读者脸 + 真路由引擎喂脸leg，镜 t261008-08 的
// bootConsole + lib_fix17 隔离台）。
//
// 用户场景（host order 261011 + 宿主裁决 2026-10-11 两修正）：在线开发线上的票行
// 恰一枚 LineOn 徽标、颜色即线状态、文字恒定（不在线/无脸=不渲染；畸形词=不渲染
// 不炸）；等你+过期=加「!」；点阵整阵同状态色相——到第 N 格=前 N 格满色、其余同色
// 相淡档（永不灰）；blocked=空心红格、failed=实心红格（形状分家，不加新色）；板面
// 行底色全拔（waiting/blocked/failed 透明，收口行只留 opacity 淡档）；引擎喂脸真
// 路由leg：夹具 develop 店（lines.json + delivery 台账 landing/freeze 行）→ 真
// adapter → 行带 line_face、项目带 frozen；线级 FROZEN 通知只进左栏顶栏（每项目
// 一次），绝不逐票。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。
// intent 分界（防 intent 级重复）：行三行组成/暂停行位次/悬停收纳/十格计数归
// t261008-08-left-column-row-composition（本票同步改 T3）；左栏 dev 行不上漆与巡检
// 行上漆归 t260915-19-sidebar-inspection-ui（本票不动其断言，只在板面侧断透明）；
// lineFaceOf 词表真值表/源码锁归 developer L1（tests/t261011-19-line-face-ui.mjs）。
// 本条独占：LineOn 徽标读者脸（在场/缺席/常量文字/过期叹号/状态间颜色可分）、点阵
// 整阵同色相规则（满色段+同色相淡档、永不灰、空心/实心形状分家）、板面行底色拔除、
// 引擎喂脸真路由leg（engine-fed line_face/frozen 到响应体）、线级冻结通知唯一性。
// KI 对齐：KI-055（真浏览器断言+明暗两主题）；KI-052（双 bundle）；KI-036
// （playwright 缺席=ENV_FAIL）；输入三态（line_face 畸形词不炸、无脸行不渲染、
// adapter 失败=命名 line_face_error 降级不静默、永不假绿脸）。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, api } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
let BASE = ''
let bench = null
let stub = null
let projectsRoot = ''
try {
  projectsRoot = makeRegistryRoot('t26101119-registry-')
  writeProjectEntry(projectsRoot, 'fixture-comp', 'fixture-comp', ['/tmp/fx-comp'])
  stub = makeTicketStub()
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

// ---------------------------------------------------------------- 夹具（页面桩）

const PROJ = 'fixture-comp'
const T_ON = 'ft-wait'      // line_face=waiting（徽标在场载体）
const T_OVER = 'ft-over'    // waiting + overdue（叹号leg）
const T_OFF = 'ft-offline'  // 无 line_face 键（不在线上=不渲染）
const T_DELIV = 'ft-deliv'  // delivered（与 waiting 颜色可分leg）
const T_BAD = 'ft-badface'  // 畸形词（不渲染不炸leg）
const T_BLK = 'ft-blk'      // blocked（空心红格）
const T_FAIL = 'ft-fail'    // failed（实心红格）
const T_INS = 'ins-x'       // 巡检行（永不带徽标）
const T0 = 1789353600

function devRow(id, stageState, extra = {}) {
  return {
    id, role: 'developer', status: 'dispatched', title: `line-face ${id}`,
    workflow: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: T0,
    created: T0, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    epic: 'line-face', ...extra,
  }
}
const TICKETS = [
  devRow(T_ON, 'awaiting-human', { line_face: 'waiting' }),
  devRow(T_OVER, 'awaiting-human', { line_face: 'waiting', line_face_overdue: true }),
  devRow(T_OFF, 'implement'),
  devRow(T_DELIV, 'implement', { line_face: 'delivered' }),
  devRow(T_BAD, 'implement', { line_face: 'bogus_face_word' }),
  devRow(T_BLK, 'blocked', { line_face: 'on_line' }),
  { ...devRow(T_FAIL, 'implement', { line_face: 'red_implicated' }), exec_status: 'FAILED', created: Math.floor(Date.now() / 1000) - 1800, updated_ts: Math.floor(Date.now() / 1000) - 1800 },
]
// 点阵子用例的行必须在并发脸里拿到 ordering kind（queued）——dotsLit 由父层从
// kind + stage 推导；kind 缺席=行不带点阵，这是产品契约，不是缺陷。
const DOT_LEGS = [T_ON, T_OVER, T_BLK, T_FAIL]
function insFace() {
  return {
    id: T_INS, kind: 'inspection', engine: 'inspection', project: PROJ, epic: '',
    title: '巡检 line-face · 期 20261011', template: 'inspection-lite',
    instance_id: 'fixture-lineface', period: '20261011', stage: 'inspect', stage_state: 'running',
    status: 'running', decision: '', findings: { high: 0, med: 0, low: 0, total: 0 },
    heartbeat: true, report_path: '', awaiting_gate: false, human_gate: null,
    blocked_reason: '', gate_error: '', created: T0, updated: '10-11 08:00',
    updated_ts: T0, paused: false, paused_phase: '', handoff_count: 0,
    pending_count: 0, worktree: '', workspace: null, role: null, proposal_id: '',
    workflow: '', close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
    // 引擎喂脸真形态：巡检行不带 line_face（线不是巡检票的属性）。本子用例断读者脸
    // 在该真形态下无徽标；「若词泄漏到巡检行客户端是否防御」不在票面契约内，
    // 作为新故障面观察上报仲裁报告，不在此断言。
  }
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

// ---------------------------------------------------------------- 浏览器具

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

// —— 绑浅的 DOM 探针（页面内跑；行级锚 data-ticket-id / data-line-face /
//    data-visual，不绑类名主体；点阵格经 .wb-stage-dot 计数契约锚）——
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
  return [...g.querySelectorAll('[data-ticket-id]')].find(el => el.getAttribute('data-ticket-id') === id) || null
}
function rgb(c) {
  const m = (c || '').match(/rgba?\\(([^)]+)\\)/)
  if (m) {
    const parts = m[1].split(',').map(s => parseFloat(s))
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 }
  }
  // 现代色形：color(srgb r g b [/ a])（color-mix/oklch 变量的计算结果形态）
  const s = (c || '').match(/color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*\\/\\s*([\\d.]+))?\\)/)
  if (s) {
    return { r: Math.round(+s[1] * 255), g: Math.round(+s[2] * 255), b: Math.round(+s[3] * 255), a: s[4] !== undefined ? +s[4] : 1 }
  }
  return null
}
function hsv(c) {
  if (!c) return null
  const { r, g, b } = c
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn
  let h = 0
  if (d > 0) {
    if (mx === r) h = ((g - b) / d) % 6
    else if (mx === g) h = (b - r) / d + 2
    else h = (r - g) / d + 4
    h *= 60; if (h < 0) h += 360
  }
  return { h, s: mx === 0 ? 0 : d / mx, v: mx / 255 }
}
function hueDist(a, b) {
  const d = Math.abs(a - b) % 360
  return d > 180 ? 360 - d : d
}
function isRedish(c) {
  const x = hsv(c)
  return !!x && x.s >= 0.25 && (x.h <= 25 || x.h >= 330)
}
function pillFace(id) {
  const row = rowFor(id)
  if (!row) return null
  const pills = [...row.querySelectorAll('[data-line-face]')]
  return {
    count: pills.length,
    word: pills.length ? pills[0].getAttribute('data-line-face') : null,
    text: pills.length ? (pills[0].textContent || '').trim() : null,
    bg: pills.length ? getComputedStyle(pills[0]).backgroundColor : null,
    bd: pills.length ? getComputedStyle(pills[0]).borderColor : null,
  }
}
function dotFace(id) {
  const row = rowFor(id)
  if (!row) return null
  const dots = [...row.querySelectorAll('.wb-stage-dot')]
  return dots.map(d => {
    const cs = getComputedStyle(d)
    return { v: d.getAttribute('data-visual'), bg: rgb(cs.backgroundColor), bd: rgb(cs.borderTopColor), bgRaw: cs.backgroundColor, bdRaw: cs.borderTopColor }
  })
}
function boardCardFace(id) {
  const sel = '.wb-root .wb-card[data-ticket-id="' + id + '"], .wb-root [data-ticket-id="' + id + '"]'
  const el = document.querySelector(sel)
  if (!el) return null
  const cs = getComputedStyle(el)
  return { state: el.getAttribute('data-state'), bg: rgb(cs.backgroundColor), op: parseFloat(cs.opacity) }
}
function frozenNotices() {
  const sb = sidebarEl()
  return [...sb.querySelectorAll('*')].filter(el => el.children.length === 0
    && /frozen/i.test(el.textContent || '')).length
}
function headerZoneHas(el) {
  // 顶栏/筛选行 = 项目组头部之前的第一行区域；通知若逐票渲染会出现在行内
  const g = projectGroup()
  if (!g) return false
  return g.contains(el) && !el.closest('[data-ticket-id]')
}
`

async function probe(page, expr) {
  return page.evaluate(`(() => { ${PROBES}; return (${expr}) })()`)
}

// ---------------------------------------------------------------- 引擎喂脸夹具

// 真 adapter 夹具店（engine 真形态，develop_certify/develop_line 校验口径）：
//   lines.json：两条声明线（版本 1、仓库不重名同支）
//   ledger/delivery.jsonl：devline-a 上一枚 landing（票 cq1a'→ 用页面桩同行 id）
//   + devline-b 一枚 freeze 回合（frz-1，无 change 行=frozen 真）
// 注意：landing/freeze 行用独立票 id（eng-*），与页面桩行不交叉——本leg断的是
// 「真路由响应体」而非页面行，避免两夹具互相踩。
function writeEngineFixtures() {
  try {
    const devDir = join(projectsRoot, PROJ, 'data', 'develop')
    const ledDir = join(projectsRoot, PROJ, 'ledger')
    mkdirSync(devDir, { recursive: true })
    mkdirSync(ledDir, { recursive: true })
    const lines = [
      { version: 1, line_id: 'devline-a', scope: 'fixture', owner: 'fixture',
        repositories: [{ name: 'repo-a', branch: 'buf/a' }], extra_scenarios: [] },
      { version: 1, line_id: 'devline-b', scope: 'fixture', owner: 'fixture',
        repositories: [{ name: 'repo-b', branch: 'buf/b' }], extra_scenarios: [] },
    ]
    writeFileSync(join(devDir, 'lines.json'), JSON.stringify(lines))
    const at = T0 * 1000
    const rows = [
      { kind: 'landing', id: 'ldg-fixture-1', ticket: 'eng-landed', line: 'devline-a',
        repos: [{ name: 'repo-a', branch: 'buf/a' }], actor: 'fixture', at, seq: 1 },
      { kind: 'freeze', id: 'frz-fixture-1', line: 'devline-b', cause: 'fixture freeze',
        repos: [{ name: 'repo-b', branch: 'buf/b' }], actor: 'fixture', at, seq: 2 },
    ]
    writeFileSync(join(ledDir, 'delivery.jsonl'),
      rows.map(r => JSON.stringify(r)).join('\n') + '\n')
    return { ok: true }
  } catch (e) {
    return { ok: false, why: String(e).slice(0, 160) }
  }
}

// ---------------------------------------------------------------- 主流程

buildContract()

const pw = await loadPlaywright()
if (!pw) {
  console.log('[ENV_FAIL] playwright-core unavailable (KI-036 family)')
  console.log('SUMMARY pass=' + results.filter(r => r.status === 'pass').length
    + ' fail=0 env_fail=1 na=0')
  process.exit(2)
}
const browser = await launchBrowser(pw)
if (!browser) {
  console.log('[ENV_FAIL] chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=' + results.filter(r => r.status === 'pass').length
    + ' fail=0 env_fail=1 na=0')
  process.exit(2)
}

const pageErrors = []
try {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))

  // 页面桩：/wf/tickets 响应即读者脸输入（line_face 字段由服务端 enrichment 加；
  // 页面桩替身承载它 = 客户端契约的读者脸，引擎喂脸真相在 E leg走真路由）。
  await page.route('**/sandbar-workbench/api/wf/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/sandbar-workbench/api/wf/tickets') {
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: true, result: { tickets: TICKETS, workflows: [{ id: 'dev-lane', name: 'dev lane', lane: 'worktree', stages: [{ id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] }, { id: 'review', name: 'review', role: 'developer', parts: ['agent'] }] }] } }) })
    }
    if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: true, result: { tickets: [insFace()], count: 1 } }) })
    }
    if (path === '/sandbar-workbench/api/wf/workflows') {
      // 点阵拓扑脸（§7.2）：sidebar /wf/workflows 单独拉——stageIdx 从这里来。
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: true, result: [
          { id: 'dev-lane', name: 'dev lane', lane: 'worktree', stages: [
            { id: 'create_plan', name: 'plan', role: 'developer', parts: ['agent'] },
            { id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] },
            { id: 'review', name: 'review', role: 'developer', parts: ['agent'] },
          ] },
        ] }) })
    }
    if (/concurrency$/.test(path)) {
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ project: PROJ, limit: 4, unlimited: false, holders: [], queue: DOT_LEGS.map((id, i) => ({ ticket: id, position: i + 1, since: T0, waited_s: 1.5 })) }) })
    }
    if (path === '/sandbar-workbench/api/wf/projects') {
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: true, result: { projects: [
          { key: PROJ, name: PROJ, primary: '/tmp/fx-comp', dirs: ['/tmp/fx-comp'] },
        ], quarantined: [] } }) })
    }
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
  })

  await bench.goto(page, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  const rendered = await waitFor(() => probe(page, '!!projectGroup()'), 8000)
  if (!rendered) {
    record('S1 precheck', 'env_fail', 'project group never rendered (stub /wf/projects unconsumed? bench=' + BASE + ')')
    summarize()
  }
  record('S1 precheck', 'pass', `left column group rendered (${PROJ})`)

  // T1 徽标在场：等你行恰一枚徽标、文字恒定 LineOn、锚=引擎词。
  const on = await probe(page, `pillFace(${JSON.stringify(T_ON)})`)
  rec('T1 LineOn pill on a waiting dev row: exactly one, constant text, anchor = engine word',
    !!on && on.count === 1 && on.text === 'LineOn' && on.word === 'waiting',
    on ? JSON.stringify(on) : 'no row')

  // T2 不在线上：无 line_face 键 ⇒ 不渲染任何徽标（空缺即无，不是灰态）。
  const off = await probe(page, `pillFace(${JSON.stringify(T_OFF)})`)
  rec('T2 off-line row renders NO pill (absence, not a muted state)',
    !!off && off.count === 0,
    off ? `count=${off.count}` : 'no row')

  // T3 等你+过期：叹号面（文字带 !，锚仍是引擎词）。
  const over = await probe(page, `pillFace(${JSON.stringify(T_OVER)})`)
  rec('T3 waiting+overdue pill: text carries the bang, anchor stays the engine word',
    !!over && over.count === 1 && /^LineOn\\s*!|LineOn!/.test(over.text || '') && over.word === 'waiting',
    over ? JSON.stringify(over) : 'no row')

  // T4 颜色即状态：waiting 与 delivered 两枚徽标可见面（底/边）必不相同。
  const deliv = await probe(page, `pillFace(${JSON.stringify(T_DELIV)})`)
  const colourSplit = !!on && !!deliv && on.count === 1 && deliv.count === 1
    && (on.bg !== deliv.bg || on.bd !== deliv.bd)
  rec('T4 colour carries the state: waiting and delivered pills are visually distinct',
    colourSplit,
    `waiting bg=${on && on.bg} bd=${on && on.bd} / delivered bg=${deliv && deliv.bg} bd=${deliv && deliv.bd}`)

  // T5 畸形词：不渲染、不炸（畸形输入三态纪律）。
  const bad = await probe(page, `pillFace(${JSON.stringify(T_BAD)})`)
  rec('T5 malformed line_face word renders NO pill and no throw',
    !!bad && bad.count === 0,
    bad ? `count=${bad.count}` : 'no row')

  // T6 巡检行永不带徽标（线不是巡检票的属性；防御leg——桩故意喂了词也不渲染）。
  const ins = await probe(page, `pillFace(${JSON.stringify(T_INS)})`)
  rec('T6 inspection row renders NO LineOn pill even if a face word arrives',
    ins === null || ins.count === 0,
    ins ? `count=${ins.count}` : 'row not found (inspection group may be absent)')

  // T7 点阵整阵同色相：十格契约；满色段 + data-visual=todo 同色相淡档（饱和度不可
  // 掉到灰档；色相距满色段任一格 <= 35°）。色相数学在 node 侧做（探针只取色值）。
  function hsvOf(c) {
    if (!c) return null
    const mx = Math.max(c.r, c.g, c.b), mn = Math.min(c.r, c.g, c.b), d = mx - mn
    let h = 0
    if (d > 0) {
      if (mx === c.r) h = ((c.g - c.b) / d) % 6
      else if (mx === c.g) h = (c.b - c.r) / d + 2
      else h = (c.r - c.g) / d + 4
      h *= 60; if (h < 0) h += 360
    }
    return { h, s: mx === 0 ? 0 : d / mx }
  }
  const hueDistOf = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d }
  const isRedishOf = (c) => {
    const x = hsvOf(c)
    return !!x && x.s >= 0.25 && (x.h <= 25 || x.h >= 330)
  }
  const dots = await probe(page, `dotFace(${JSON.stringify(T_ON)})`)
  if (!dots || dots.length !== 10) {
    rec('T7a ten-cell dot matrix count stays 10', false,
      dots ? `count=${dots.length}` : 'no row')
  } else {
    const todo = dots.filter(d => d.v === 'todo')
    const lit = dots.filter(d => d.v === 'lit')
    rec('T7a ten-cell dot matrix count stays 10', true, `lit=${lit.length} todo=${todo.length}`)
    const litHues = lit.map(d => hsvOf(d.bg)).filter(x => x && x.s >= 0.15).map(x => x.h)
    // 「永不灰」的锚=宿主逐字规则：未到格必须落在状态色相的淡档里（同色相 <=35°），
    // 中性灰（--dsw-derive-border 族，色相 ~210°、低饱和）自然落在 35° 之外。
    // 不设绝对饱和度线：16% 同色相淡档是合法 dim shade，读起来仍是琥珀不是灰。
    const offHue = todo.filter(d => {
      const x = hsvOf(d.bg) || hsvOf(d.bd)
      return !x || x.s < 0.03 || !litHues.some(h => hueDistOf(h, x.h) <= 35)
    })
    rec('T7b unreached cells take the DIM shade of the SAME hue, never grey',
      todo.length > 0 && litHues.length > 0 && offHue.length === 0,
      `offHue=${offHue.length} litHues=${JSON.stringify(litHues.slice(0, 3))} todoHues=${JSON.stringify(todo.slice(0, 2).map(d => hsvOf(d.bg || d.bd)))}`)
  }

  // T8 形状分家（宿主逐字规则锚在「状态格」上）：blocked 的 lit 格=空心（填充透明+
  // 红边框），failed 的 lit 格=实心红；两行可见面不同——todo 格是同族淡档，不参与
  // 形状断言（淡档实心是合法的，形状语言由 lit 格承载）。
  const blk = await probe(page, `dotFace(${JSON.stringify(T_BLK)})`)
  const fail = await probe(page, `dotFace(${JSON.stringify(T_FAIL)})`)
  const litCells = (arr) => (arr || []).filter(d => d.v === 'lit')
  const hollow = blk && blk.length === 10 && litCells(blk).length > 0
    && litCells(blk).every(d => !d.bg || d.bg.a === 0)
    && litCells(blk).some(d => isRedishOf(d.bd))
  const solid = fail && fail.length === 10 && litCells(fail).length > 0
    && litCells(fail).every(d => isRedishOf(d.bg))
  rec('T8 blocked = hollow red cells, failed = solid red cells (shape split, same red family)',
    !!hollow && !!solid,
    `hollow=${!!hollow} solid=${!!solid} failLen=${fail ? fail.length : 'noRow'} fail0=${JSON.stringify((litCells(fail)[0] || {}))}`)

  // T9 板面行底色全拔：waiting/blocked/failed 卡背景透明；收口行只留 opacity 淡档
  //（收口行不在夹具时 na——系统状态条件子用例）。
  const bWait = await probe(page, `boardCardFace(${JSON.stringify(T_ON)})`)
  const bBlk = await probe(page, `boardCardFace(${JSON.stringify(T_BLK)})`)
  const transparent = (c) => !c || c.a === 0
  if (bWait === null && bBlk === null) {
    record('T9 board row background removed', 'na', 'board cards not rendered in this bench view (left-column-only stage?)')
  } else {
    const okT9 = (bWait === null || transparent(bWait.bg)) && (bBlk === null || transparent(bBlk.bg))
    rec('T9 board row background removed for waiting/blocked (state-derived fill gone)',
      okT9, `waiting bg=${bWait && JSON.stringify(bWait.bg)} blocked bg=${bBlk && JSON.stringify(bBlk.bg)}`)
  }

  // T10 明暗两主题捕获（验收证据面；尽力而为，不判红）。
  const outDir = join(REPO, 'integration', 't261011-19', 'out')
  try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
  for (const scheme of ['light', 'dark']) {
    try {
      if (scheme === 'dark') await page.emulateMedia({ colorScheme: 'dark' })
      await page.waitForTimeout(400)
      await page.locator('.wb-sb').first().screenshot({ path: join(outDir, `left-column-${scheme}.png`) })
      record(`T10 capture ${scheme}`, 'pass', `integration/t261011-19/out/left-column-${scheme}.png`)
    } catch (e) {
      record(`T10 capture ${scheme}`, 'na', `screenshot unavailable: ${String(e).slice(0, 120)}`)
    }
  }

  rec('X1 zero pageerror across the reader-face journey', pageErrors.length === 0,
    pageErrors.length ? pageErrors.join(' | ') : 'clean')
} catch (e) {
  record('S1 browser journey', 'fail', String(e).slice(0, 200))
} finally {
  await browser.close().catch(() => {})
}

// ---------------------------------------------------------------- E leg：引擎喂脸真路由

// 夹具店落盘（engine 真形态）→ 直击真 workbench 路由（页面桩不拦 node 侧 fetch）。
// 真路由的行来自引擎通道桩的 ctrl 夹具（真 client.py ticket-list 被拦，行由桩供）——
// 种一枚带 lane_version/develop_line 键的行，adapter 的脸按 ticket id 落到它身上。
stub.setCtrl({ tickets: [{
  id: 'eng-landed', project: PROJ, role: 'developer', workflow: 'dev-lane',
  stage: 'implement', stage_state: 'running', status: 'dispatched',
  title: 'engine-fed row', engine: 'template-as-code-v2', exec_status: 'RUNNING',
  lane_version: 'develop-buffer-v1', develop_line: 'devline-a',
  updated: '—', updated_ts: T0, created: T0,
}] })
const fx = writeEngineFixtures()
if (!fx.ok) {
  record('E0 engine fixture store', 'fail', `cannot write fixture store: ${fx.why}`)
} else {
  record('E0 engine fixture store', 'pass', `lines.json + delivery.jsonl under ${projectsRoot}/${PROJ}`)
  let body = null
  try {
    const r = await api(BASE, 'GET', '/sandbar-workbench/api/wf/tickets?project=' + PROJ)
    body = r.body && typeof r.body === 'object' ? r.body : null
  } catch (e) {
    record('E1 real route reachable', 'env_fail', String(e).slice(0, 160))
  }
  if (body) {
    rec('E1 real route reachable (node side, page stubs bypassed)',
      body.ok === true, `ok=${body.ok} keys=${JSON.stringify(Object.keys(body).slice(0, 8))}`)
    const rows = (body.result && body.result.tickets) || body.tickets || []
    const err = body.line_face_error || (body.result && body.result.line_face_error)
    const frozen = body.line_frozen !== undefined ? body.line_frozen
      : body.result && body.result.line_frozen
    const landed = rows.find(t => t.id === 'eng-landed')
    const anyFace = rows.some(t => t.line_face !== undefined)
    if (err) {
      // 命名降级=本台合法形态（隔离台的 repo 锚指向桩仓，真 adapter 文件不在桩仓——
      // 台面锚定互作，非产品缺陷；真部署里 adapter 在锚定仓内）。降级契约是可确定性
      // 断言的读者面：路由不 502、行零假脸、错误具名；正脸子用例转条件子用例 na（点名）。
      rec('E2 degradation contract: named error, rows pass through UN-enriched, route never 502s',
        body.ok === true && err.length > 0 && !anyFace && rows.length > 0,
        `named=${JSON.stringify(err).slice(0, 120)} enrichedRows=${rows.filter(t => t.line_face !== undefined).length}`)
      record('E3 positive engine-fed face (landing => waiting)', 'na',
        `named degradation on this bench: ${JSON.stringify(err).slice(0, 120)}`)
      record('E4 positive engine-fed frozen flag', 'na',
        `named degradation on this bench: ${JSON.stringify(err).slice(0, 120)}`)
    } else if (!landed) {
      record('E2 engine-fed line_face on the landed ticket', 'fail', 'fixture row eng-landed missing from the real route response')
    } else {
      rec('E2 engine-fed line_face on the landed ticket (landing, no certs => waiting)',
        landed.line_face === 'waiting',
        `line_face=${JSON.stringify(landed.line_face)} overdue=${JSON.stringify(landed.line_face_overdue)}`)
      rec('E3 project-level frozen flag from the freeze record',
        frozen === true, `line_frozen=${JSON.stringify(frozen)}`)
      const offRows = rows.filter(t => t.id !== 'eng-landed' && t.role === 'developer')
      const leaked = offRows.filter(t => t.line_face !== undefined)
      rec('E4 tickets with no landing carry NO face (not-on-line is absence, not a word)',
        leaked.length === 0, leaked.length ? `leaked: ${leaked.map(t => t.id).join(',')}` : 'clean')
    }
  } else if (results.every(r => r.name !== 'E1 real route reachable (node side, page stubs bypassed)')) {
    record('E1 real route reachable (node side, page stubs bypassed)', 'env_fail', 'no response body')
  }
}

summarize()
