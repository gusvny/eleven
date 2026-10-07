#!/usr/bin/env node
// t261007-07 场景：平台横幅压制（设计稿 notes/discussions/261004-顶栏横幅-设计稿.md 最后一项，宿主令 261007）。
// （灰盒 L3 渲染层，browser-free 池；两层式，镜 t261005-09/sc_left_column_ui_journey.mjs。）
//
// 用户场景（工单 t261007-07 派发规格）：人打开控制台，第一眼看到的表头是我们自己的——
// 左栏第一行是品牌行（t261005-09 已交付），中栏是自己的执行器表头，平台自己的横幅行
// （DeepSeek Harness 品牌钮 + 折叠钮）不再出现在它们之上；无空白条、无重影叠层。
// 锚纪律（设计稿 §2）：锚不在时**什么都不藏**并显式记一行——绝不半藏半留、绝不静默变样；
// 最坏退化=平台横幅仍在（允许），不能是白屏。
//
// 两层：
//   S0 build-contract（纯 node，秒级）：shipped 双 bundle 同步（KI-052）+ 折叠钮 aria-label
//      全集字面在 shipped bundle（KI-051：锚语义、不锚实现命名——四条 label 是平台 locale
//      字面，锚它们=锚平台契约本身）。
//   S1 真浏览器 DOM：隔离台（lib_fix17 bootConsole，freePort 拒 3099；teardownOnExit 全终态
//      回收）+ playwright-core + chromium，任一缺席=ENV_FAIL exit 2。数据只在 API 边界打桩
//      （/wf/projects、/wf/tickets），账册经 localStorage 种子——浏览器/bundle/React 全真，
//      宿主 3099 零接触。浅/深两外观各跑一遍核心面（KI-055 主题矩阵纪律：UI 面只验一种
//      外观=台面绿真机红的温床）。
//   S1-C 守卫分支（锚缺席注入）：init 脚本从文档起点持续把折叠钮的 aria-label 改名，模拟
//      平台 locale 漂移——锚缺席时平台横幅必须**仍在**（什么都不藏），且控制台**恰好一行**
//      点名锚的告警（warn-once，重复扫描不得刷屏）。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。实现段落地前红属预期
// （TDD 信号）；arbitrate/merge 期必须绿。
//
// intent 分界：品牌行本体（首行/26px/行内零钮）归 t261005-09-left-column-ui-journey B0
// （本条只做轻量回归守卫 A3，不复断品牌面）；中栏内容语义归 executor 面各票（本条只断
// 「中栏自己的表头在场」）；工单行/排序/句柄各族各归其票。本条独占：平台横幅行的压制、
// 空白条/叠层缺陷面、守卫退化路径、document.title 不被本插件抢写。
// KI 对齐：KI-052（双 bundle 同步）、KI-055（浅/深双外观）、KI-051（锚语义优先）、
// KI-036（playwright 缺席=ENV_FAIL）、KI-046 族（守卫子用例缺席=红，不是干净跳过）。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
const OUT_DIR = join(REPO, 'integration', 't261007-07', 'out')
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t261007-07-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', 'fixture-alpha', ['/tmp/fx-alpha'])
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
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- 夹具（模块/数据面）

const PROJ_A = 'fixture-alpha'
const RUN_ID = 'devfixa1007run'
const T2 = 1789353600
const LEDGER_KEY = 'sandbar-workbench-opened-sessions-v1'

// 折叠钮 aria-label 全集（平台 locale 字面，真源=dsh-client-ui-sidebar/lib/client.js
// zh 312–313 行 / en 320–321 行；展开态用 collapse 面，收起态用 open 面——全集都锚，
// 不锚哪一个态=锚语义不锚时机）。
const FOLD_LABELS = ['收起侧边栏', '打开侧边栏', 'Collapse sidebar', 'Open sidebar']
// 平台 theme 面不属本条断言面（归平台设置/我们面板跟随面）；本条只确保深外观下不新破。

function devRow(id, stageState, title, ts) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
  }
}
const DEV_ROWS = [devRow(RUN_ID, 'running', 'alpha banner ticket', T2)]
const WORKFLOWS = [{
  id: 'dev-lane', name: 'dev lane', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: 'plan', role: 'developer', parts: ['agent'] },
    { id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] },
  ],
}]

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
  const missing = FOLD_LABELS.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 bundle-anchors', 'fail', `shipped bundle missing fold-anchor labels: ${missing.join(', ')}（pre-implement red expected / KI-052）`)
  } else {
    record('S0 bundle-anchors', 'pass', 'twin bundles in sync, all four fold aria-label anchors present')
  }
}

// ---------------------------------------------------------------- S1 真浏览器

function consoleHealthy() {
  const url = bench.authUrl ?? `${BASE}/`
  return fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(5000) })
    .then(r => r.status === 303 || r.ok).catch(() => false)
}

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

async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await p.keyboard.press('Escape').catch(() => {})
    await p.waitForTimeout(600)
  }
}

function routeStubs(route) {
  const url = new URL(route.request().url())
  const path = url.pathname.replace(/\/+$/, '')
  if (path === '/sandbar-workbench/api/wf/projects') {
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { projects: [
        { key: PROJ_A, name: 'fixture-alpha', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
      ], quarantined: [] } }),
    })
  }
  if (path === '/sandbar-workbench/api/wf/tickets') {
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { tickets: DEV_ROWS, workflows: WORKFLOWS } }) })
  }
  if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { tickets: [], count: 0 } }) })
  }
  return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
}

// 页内评估（绑浅：左栏=品牌行所在列；可见性按几何算，不绑平台/实现类名）。
async function bannerFaces(page) {
  return page.evaluate((foldLabels) => {
    const visible = (el) => {
      const r = el.getBoundingClientRect()
      if (r.width < 2 || r.height < 2) return false
      const cs = getComputedStyle(el)
      return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') > 0.05
    }
    const brand = document.querySelector('[data-wb-brand-row]')
    const brandRect = brand ? brand.getBoundingClientRect() : null
    // A1 折叠钮：任何可见 button 的可及名命中折叠 label 全集=平台横幅仍在。
    const foldHits = [...document.querySelectorAll('button')]
      .filter(b => foldLabels.includes(b.getAttribute('aria-label') || '') && visible(b))
      .map(b => b.getAttribute('aria-label'))
    // A2 空白条/叠层检测器：品牌行之上、左栏横向范围内，任何高度 ≥6px 的可见元素
    // （平台横幅残行或空白条都落在这里；1–5px 的 padding/描边不算缺陷面）。
    const stripHits = []
    if (brandRect) {
      for (const el of document.querySelectorAll('body *')) {
        if (!visible(el)) continue
        const r = el.getBoundingClientRect()
        if (r.height < 6) continue
        if (r.bottom > brandRect.top + 1) continue                       // 不在品牌行之上
        if (r.right < brandRect.left - 2 || r.left > brandRect.right + 2) continue // 不在左栏横向范围
        if (el.contains(brand) || brand.contains(el)) continue
        stripHits.push(`${el.tagName}.${String(el.className).slice(0, 40)} h=${Math.round(r.height)}`)
      }
    }
    // A4 中栏自己的表头：中栏以**我们自己的** chrome 开场（非平台横幅）。
    // 两个等价在场面（产品现状=工单台头与执行器面板同列排布，wb-root flex:none
    // 可把执行器面板挤到 0 高——t260905-10 布局的既有形态，非本票改动面）：
    //   a) 执行器面板根可见（executor 面在场）；
    //   b) 中列自有机器头 .wb-head 可见（wb-root 在场时它就是中栏第一屏表头）。
    const mid = document.querySelector('[data-wb-executor-view]')
    const midVisible = !!mid && visible(mid)
    const ownHead = document.querySelector('.wb-right-content .wb-head')
    const ownHeadVisible = !!ownHead && visible(ownHead)
    const placeholder = document.querySelector('.wb-placeholder')
    return {
      brandPresent: !!brand,
      brandH: brandRect ? Math.round(brandRect.height) : null,
      brandTop: brandRect ? Math.round(brandRect.top) : null,
      foldHits,
      stripHits,
      midVisible,
      ownHeadVisible,
      ownHeadText: ownHead ? ownHead.textContent.slice(0, 40) : null,
      diag: {
        entryCount: document.querySelectorAll('[data-wb-executor-entry]').length,
        midCount: document.querySelectorAll('[data-wb-executor-view]').length,
        midHidden: !!mid && !visible(mid),
        midRect: mid ? (r => ({ w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), left: Math.round(r.left) }))(mid.getBoundingClientRect()) : null,
        midStyle: mid ? (cs => ({ display: cs.display, visibility: cs.visibility, opacity: cs.opacity }))(getComputedStyle(mid)) : null,
        parentStyle: mid && mid.parentElement ? (cs => ({ display: cs.display, visibility: cs.visibility, opacity: cs.opacity, h: Math.round(mid.parentElement.getBoundingClientRect().height) }))(getComputedStyle(mid.parentElement)) : null,
        siblings: mid && mid.parentElement ? Array.from(mid.parentElement.children).map(c => `${c.tagName}.${String(c.className).slice(0, 30)}@${Math.round(c.getBoundingClientRect().top)}+${Math.round(c.getBoundingClientRect().height)}`) : null,
        placeholder: placeholder ? placeholder.textContent.slice(0, 60) : null,
      },
      title: document.title,
    }
  }, FOLD_LABELS)
}

async function settleLeftColumn(page) {
  const landed = await waitFor(async () => {
    return page.evaluate(() => !!document.querySelector('[data-wb-brand-row]')).catch(() => false)
  }, 15000)
  if (!landed) return false
  await page.waitForTimeout(2500)   // 压制 effect / observer 再扫一遍的余量
  await dismissOverlays(page)
  return true
}

async function runSuppressLeg(browser, colorScheme, shotName) {
  const ctx = await browser.newContext()
  const warns = []
  try {
    await ctx.addInitScript(([key, val]) => { try { localStorage.setItem(key, val) } catch { /* fresh */ } },
      [LEDGER_KEY, JSON.stringify([])])
    const page = await ctx.newPage()
    page.on('console', (m) => {
      if (m.type() === 'warning' || m.type() === 'error') warns.push(m.text().slice(0, 200))
    })
    const pageErrors = []
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    if (colorScheme) await page.emulateMedia({ colorScheme })
    await bench.goto(page, { waitUntil: 'networkidle' })
    if (!(await settleLeftColumn(page))) {
      record(`S1 ${shotName} precheck`, 'env_fail', `左栏品牌行未渲染（stub /wf/projects 未被消费？台面=${BASE}）`)
      return { warns }
    }
    record(`S1 ${shotName} precheck`, 'pass', `左栏渲染就绪（${colorScheme || 'light（默认）'}）`)

    // A4 前置：中栏默认面不保证是执行器视图（t260929-22 的入口=项目行上的
    // 执行器图标，深浅两轮的落地默认面可能不同）——best-effort 点第一枚执行
    // 入口并轮询到执行器面在场（有界）；点不到=保持现状，A4 只断「表头在场」
    // 不另造导航语义。
    try {
      await waitFor(async () => {
        await page.evaluate(() => {
          const entry = document.querySelector('[data-wb-executor-entry]')
          if (entry) entry.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await page.waitForTimeout(600)
        return page.evaluate(() => {
          const mid = document.querySelector('[data-wb-executor-view]')
          if (!mid) return false
          const r = mid.getBoundingClientRect()
          const cs = getComputedStyle(mid)
          return r.width > 2 && r.height > 2 && cs.display !== 'none' && cs.visibility !== 'hidden'
        }).catch(() => false)
      }, 8000)
    } catch { /* 导航尝试失败不冒充断言失败 */ }

    const f = await bannerFaces(page)

    // A1 平台横幅行不可见：折叠钮零可见命中（HIDE 的用户可感知面；机制/属性名不绑）。
    const a1ok = f.foldHits.length === 0
    record(`A1 banner-hidden (${shotName})`, a1ok ? 'pass' : 'fail',
      a1ok ? 'no visible fold-toggle button — platform banner row suppressed'
        : `fold toggle still visible: ${JSON.stringify(f.foldHits)}（pre-implement red expected）`)

    // A2 无空白条/无叠层：品牌行之上左栏横向范围内零 ≥6px 可见元素（最坏退化只许
    // 「横幅仍在=A1 红」，不许「横幅没了但留白条」这种半藏形态）。
    const a2ok = f.brandPresent && f.stripHits.length === 0
    record(`A2 no-blank-strip (${shotName})`, a2ok ? 'pass' : 'fail',
      a2ok ? `nothing visible between the column top and the brand row (top=${f.brandTop})`
        : `blank strip / overlap artifact above the brand row: ${JSON.stringify(f.stripHits)}（pre-implement red expected）`)

    // A3 品牌行 26px 回归守卫（本条只防本票改动把它挤高/挤走；品牌面本体归 t261005-09 B0）。
    const a3ok = f.brandH !== null && f.brandH > 16 && f.brandH <= 34
    record(`A3 brand-row-height-guard (${shotName})`, a3ok ? 'pass' : 'fail',
      a3ok ? `brand row h=${f.brandH}px (26px design, ≤34 tolerance)`
        : `brand row height drift: ${JSON.stringify(f.brandH)}（pre-implement red expected）`)

    // A4 中栏自己的表头（判据见 bannerFaces 内注释；执行器面板或中列自有机器头，
    // 二者任一可见=中栏以自己的 chrome 开场，平台横幅不是表头）。
    const a4ok = f.midVisible || f.ownHeadVisible
    record(`A4 middle-header-present (${shotName})`, a4ok ? 'pass' : 'fail',
      a4ok ? `middle column opens with our own chrome (${f.midVisible ? 'executor view' : 'workbench machine head'} visible)`
        : `middle column header not visible diag=${JSON.stringify(f.diag ?? null)}（pre-implement red expected）`)

    // A5 document.title 不被本插件抢写：非空、且不是我们品牌字面（平台写它的契约不动）。
    const a5ok = typeof f.title === 'string' && f.title.length > 0 && f.title !== 'Sandbar'
    record(`A5 title-untouched (${shotName})`, a5ok ? 'pass' : 'fail',
      a5ok ? `document.title owned by the platform: "${f.title.slice(0, 60)}"`
        : `document.title violated: ${JSON.stringify(f.title)}`)

    // 截图（验收证据面；目录缺席则补建，截图失败不冒充断言失败）。
    try {
      mkdirSync(OUT_DIR, { recursive: true })
      await page.screenshot({ path: join(OUT_DIR, shotName), fullPage: false })
    } catch (e) {
      console.log(`[WARN] screenshot ${shotName} failed: ${String(e).slice(0, 120)}`)
    }

    record(`S1 page-health (${shotName})`, pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `pageerror ×${pageErrors.length}: ${pageErrors.slice(0, 3).join(' | ')}` : 'zero pageerror')
    return { warns }
  } finally {
    await ctx.close().catch(() => {})
  }
}

// 守卫分支：锚缺席注入——init 脚本从文档起点装 MutationObserver，把折叠 label 全集的
// aria-label 持续改名为陌生词（模拟平台 locale 漂移）。期望：什么都不藏（横幅仍在）
// + 恰好一行点名锚的告警（warn-once）。
const GUARD_RENAME = 'wb-guard-renamed'

async function runGuardLeg(browser) {
  const ctx = await browser.newContext()
  const warns = []
  try {
    await ctx.addInitScript(([fold, renamed]) => {
      try { localStorage.setItem('sandbar-workbench-opened-sessions-v1', '[]') } catch { /* fresh */ }
      const scan = () => {
        for (const b of document.querySelectorAll('button')) {
          if (fold.includes(b.getAttribute('aria-label') || '')) b.setAttribute('aria-label', renamed)
        }
      }
      // 文档起点 documentElement 可能尚未存在（init 早于 DOM 建树）——observe
      // 必须等根在场合法；install 失败=守卫注入未生效，C1/C2 会红，不许静默。
      const install = () => {
        try {
          new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-label'] })
          return true
        } catch { return false }
      }
      let installed = false
      if (document.documentElement) installed = install()
      if (!installed) {
        document.addEventListener('DOMContentLoaded', () => { installed = install(); if (installed) scan() }, { once: true })
      }
      scan()
      document.addEventListener('DOMContentLoaded', scan)
      window.addEventListener('load', scan)
    }, [FOLD_LABELS, GUARD_RENAME])
    const page = await ctx.newPage()
    page.on('console', (m) => {
      if (m.type() === 'warning' || m.type() === 'error') warns.push(m.text().slice(0, 300))
    })
    const pageErrors = []
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    await bench.goto(page, { waitUntil: 'networkidle' })
    // 守卫判定的读面要等 observer 再扫几轮（重复扫描不得刷屏=warn-once 的判定窗）。
    await page.waitForTimeout(6000)

    const g = await page.evaluate(([fold, renamed]) => {
      const visible = (el) => {
        const r = el.getBoundingClientRect()
        if (r.width < 2 || r.height < 2) return false
        const cs = getComputedStyle(el)
        return cs.display !== 'none' && cs.visibility !== 'hidden'
      }
      const renamedBtn = [...document.querySelectorAll('button')]
        .find(b => b.getAttribute('aria-label') === renamed)
      const brand = document.querySelector('[data-wb-brand-row]')
      return {
        bannerVisible: !!renamedBtn && visible(renamedBtn),
        brandPresent: !!brand,
        foldLeft: [...document.querySelectorAll('button')]
          .filter(b => fold.includes(b.getAttribute('aria-label') || '')).length,
      }
    }, [FOLD_LABELS, GUARD_RENAME])

    // C1 锚缺席=什么都不藏：平台横幅钮仍可见（允许的退化形态），品牌行照常渲染。
    const c1ok = g.bannerVisible && g.brandPresent
    record('C1 guard-nothing-hidden', c1ok ? 'pass' : 'fail',
      c1ok ? 'anchor absent → platform banner still visible (allowed degradation), brand row intact'
        : `guard violated: bannerVisible=${g.bannerVisible} brandPresent=${g.brandPresent}（pre-implement red expected）`)

    // C2 恰好一行点名锚的告警：含任一折叠 label 字面的 warning/error 恰 1 条。
    const anchorWarns = warns.filter(t => FOLD_LABELS.some(l => t.includes(l)))
    const c2ok = anchorWarns.length === 1
    record('C2 guard-one-explicit-line', c2ok ? 'pass' : 'fail',
      c2ok ? `exactly one explicit guard line naming the anchor: "${anchorWarns[0].slice(0, 120)}"`
        : `expected exactly 1 anchor-naming warn line, got ${anchorWarns.length}: ${JSON.stringify(anchorWarns.slice(0, 4))}（pre-implement red expected）`)

    try {
      mkdirSync(OUT_DIR, { recursive: true })
      await page.screenshot({ path: join(OUT_DIR, 'banner-guard-anchor-absent.png'), fullPage: false })
    } catch (e) {
      console.log(`[WARN] guard screenshot failed: ${String(e).slice(0, 120)}`)
    }
    record('C3 guard page-health', pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `pageerror ×${pageErrors.length}: ${pageErrors.slice(0, 3).join(' | ')}` : 'zero pageerror under the guard leg')
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- 主流程

buildContract()
if (!(await consoleHealthy())) {
  record('S1 console', 'env_fail', `test console unreachable: ${BASE}`)
} else {
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 playwright', 'env_fail', 'playwright-core not resolvable (KI-036 family)')
  } else {
    const browser = await launchBrowser(pw)
    if (!browser) {
      record('S1 chromium', 'env_fail', 'chromium/chrome cannot start (headless environment)')
    } else {
      try {
        await runSuppressLeg(browser, null, 'banner-light.png')
        await runSuppressLeg(browser, 'dark', 'banner-dark.png')
        await runGuardLeg(browser)
      } catch (e) {
        record('S1 run-browser', 'fail', `uncaught: ${String(e).slice(0, 300)}`)
      } finally {
        await browser.close().catch(() => {})
      }
    }
  }
}
summarize()
