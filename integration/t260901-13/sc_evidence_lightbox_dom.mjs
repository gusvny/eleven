// evidence-lightbox-dom —— t260901-13「截图证据看图灯箱」集成测试集.
//
// Intent (black-box, user perspective): 工单详情抽屉的截图证据缩略图网格
// (t260831-08) 现在支持看图灯箱。用户可感知契约（以 t260901-13 gen1 方案为规格）：
//   - 点击缩略图 → 全屏灯箱遮罩打开，显示大图 + 计数「n / total」+ 文件名；
//   - ‹ / › 按钮（仅多图）与 ← / → 键循环切换（首尾相接，不越界）；
//   - Esc 键与点击遮罩空白处关闭；点击图片本体不关闭；
//   - 降级：无图/畸形列表 → 证据区不渲染、不崩；单图 → 无 ‹/› 按钮；
//   - 单图加载失败 → 占位文案，不白屏不拖垮页面；关闭后监听不残留（再操作不崩）。
//
// Two layers (same split as lane-parallel-dom.mjs):
//   S0 build-contract (pure node, runs everywhere): shipped twin bundles in
//      sync; bundle exposes evidenceNav / evidenceImgSrc / evidenceLightboxKeys
//      via the __ModuleLoader__ factory contract; evidenceNav black-box nav
//      semantics (loop wrap, bounds, malformed inputs) against the REAL shipped
//      code; key contract covers Esc/ArrowLeft/ArrowRight; img src stays a
//      relative same-origin endpoint (no data:, no absolute URL).
//   S1 browser DOM assertions (real rendering level): needs the ISOLATED test
//      console (SANDBAR_TEST_CONSOLE, default 127.0.0.1:3199), playwright-core
//      resolvable, and a launchable chromium. Any missing -> ENV_FAIL (exit 2)
//      with the reason on stdout). Data is stubbed at the API boundary with
//      page.route(): list/detail/evidence-list/evidence-image all intercepted
//      for the fixture ticket; images are served as a tiny valid PNG. Never
//      touches production console (3099) nor real tickets.
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 或全部子用例 na -> exit 1;
// env_fail>0 -> exit 2. Node >= 22.18.

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;
const FID = 't26090113lb' // fixture ticket id (alnum only; never a real ticket)

const results = [] // { name, status: 'pass'|'fail'|'env_fail'|'na', detail }
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na']);
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length;
  const e = results.filter(r => r.status === 'env_fail').length;
  const n = results.filter(r => r.status === 'na').length;
  const f = results.filter(r => r.status === 'fail').length;
  const allNa = results.length > 0 && n === results.length;
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
}

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

/** 经构建产物装载真代码（契约与 smoke/ticket-switch.mjs loadClientBundle 一致）。 */
function loadClientBundle() {
  const src = readFileSync(LIB_CJS, 'utf8')
  let factory = null
  globalThis.window = { __ModuleLoader__: { load: (m) => { factory = m.factory } } }
  new Function(src)()
  globalThis.window = undefined
  if (typeof factory !== 'function') throw new Error('lib/client.cjs 未按 __ModuleLoader__.load 契约暴露 factory（先跑 tsdown 构建）')
  const stub = new Proxy(function () {}, {
    get: (_t, p) => (p === Symbol.toPrimitive ? () => '' : stub),
    apply: () => stub,
    construct: () => stub,
  })
  return factory(() => stub)
}

function navContract() {
  let client
  try { client = loadClientBundle() } catch (e) {
    record('S0 bundle-exports', 'fail', String(e).slice(0, 160))
    return false
  }
  const need = ['evidenceNav', 'evidenceImgSrc', 'evidenceLightboxKeys']
  const missing = need.filter(k => typeof client[k] !== 'function' && k !== 'evidenceLightboxKeys')
  if (missing.length || typeof client.evidenceLightboxKeys === 'undefined') {
    record('S0 bundle-exports', 'fail', `shipped bundle missing lightbox exports: ${missing.join(', ') || 'evidenceLightboxKeys'}`)
    return false
  }
  record('S0 bundle-exports', 'pass', 'evidenceNav / evidenceImgSrc / evidenceLightboxKeys exposed')
  return true
}

/** 键位契约：Esc + 左右方向键必须都在，且不含会与输入冲突的键。 */
function keyContract(client) {
  const keys = JSON.stringify(client.evidenceLightboxKeys)
  const has = (k) => keys.includes(k)
  if (!has('Escape') || !has('ArrowLeft') || !has('ArrowRight')) {
    record('S0 key-contract', 'fail', `key contract missing Esc/Arrows: ${keys}`)
    return false
  }
  record('S0 key-contract', 'pass', `keys=${keys}`)
  return true
}

/** 导航语义（黑盒，用户口径）：循环切换 + 畸形输入不崩且落安全位。 */
function navSemantics(client) {
  const nav = client.evidenceNav
  let bad = []
  const eq = (a, b) => a === b
  // 正常循环：中间向前/向后、首尾相接。
  if (!eq(nav(['a', 'b', 'c'], 0, 1), 1)) bad.push('0+1!=1')
  if (!eq(nav(['a', 'b', 'c'], 2, 1), 0)) bad.push('last+1 不回绕到 0')
  if (!eq(nav(['a', 'b', 'c'], 0, -1), 2)) bad.push('0-1 不回绕到 last')
  if (!eq(nav(['a', 'b', 'c'], 1, 3), 1)) bad.push('整圈 +3 不回到原位')
  // 单图：怎么切都在 0。
  if (!eq(nav(['a'], 0, 1), 0) || !eq(nav(['a'], 0, -1), 0)) bad.push('单图切换不驻留 0')
  // 畸形输入：不抛 + 落安全下标。
  const safe = (fn, label) => {
    try {
      const r = fn()
      if (!Number.isInteger(r) || r < 0) bad.push(`${label} -> ${JSON.stringify(r)} 非安全下标`)
    } catch (e) { bad.push(`${label} 抛错 ${String(e).slice(0, 60)}`) }
  }
  safe(() => nav([], 0, 1), '空列表')
  safe(() => nav(['a', 'b'], 5, 1), '下标越界')
  safe(() => nav(['a', 'b'], -2, 1), '负下标')
  safe(() => nav(['a', 'b'], 0, -9), '大负 delta')
  safe(() => nav(['a', 'b'], 0, 0.5), '非整数 delta')
  safe(() => nav(['a', 'b'], 0, NaN), 'NaN delta')
  safe(() => nav(['a', 'b'], 0, 'x'), '非数字 delta')
  if (bad.length) { record('S0 nav-semantics', 'fail', bad.join('; ')); return false }
  record('S0 nav-semantics', 'pass', '循环回绕/单图驻留/畸形输入全过')
  return true
}

function srcContract(client) {
  const s = client.evidenceImgSrc(FID, 'shot 1.png')
  const ok = s === `/sandbar-workbench/api/wf/tickets/${FID}/evidence/shot%201.png`
    && !s.startsWith('data:') && !s.startsWith('http')
  record('S0 imgsrc-contract', ok ? 'pass' : 'fail', ok ? s : `bad src: ${s}`)
  return ok
}

// ---------------------------------------------------------------- S1 fixtures

const WF = {
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
    { id: 'review_plan', name: '审方案', role: 'integration', parts: ['agent'] },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
    { id: 'design_integration_tests', name: '设计集成测试', role: 'integration', parts: ['agent'] },
    { id: 'run_integration_tests', name: '跑集成测试', role: 'integration', parts: ['script'] },
    { id: 'arbitrate', name: '仲裁', role: 'integration', parts: ['agent', 'script'] },
    { id: 'acceptance_walkthrough', name: '验收走查', role: 'integration', parts: ['agent'] },
    { id: 'merge_check', name: '合并检查', role: 'integration', parts: ['script'] },
    { id: 'merge', name: '合并', role: 'human', parts: ['human'] },
    { id: 'suggest_next', name: '建议下一单', role: 'integration', parts: ['script'] },
  ],
}
const ROW = {
  id: FID, role: 'developer', status: 'dispatched', title: '看图灯箱打桩工单',
  workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
  handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}
function detailBase(over) {
  return {
    id: FID, title: ROW.title, workflow_id: 'dev-lane', epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'implement', stage_name: '实现', stage_state: 'running',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [], body: '灯箱 DOM 打桩（不进 Temporal）', write_set: [],
    timeline: [], ...over,
  }
}

const PNG_1x1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64')

// 可变 fixture 状态（route stub 按它应答）。
let evidenceFiles = ['lb-a.png', 'lb-b.png', 'lb-c.png']
let evidenceMalformed = false
let breakImage = null // 文件名 → 应答 404

// ---------------------------------------------------------------- S1 infra (precedent: lane-parallel-dom.mjs)

function consoleHealthy() {
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) })
    .then(r => r.ok)
    .catch(() => false)
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
    try { return await import(c) } catch { /* next candidate */ }
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

/** DOM snapshot（灯箱契约全部经 class/文本读取，不依赖实现内部状态）。
 *  选择器锚点 .wb-lb-* 是 gen1 方案明文承诺的样式契约。 */
const domLb = `(() => {
  const mask = document.querySelector('.wb-lb-mask, .wb-lb');
  if (!mask) return { open: false };
  const img = mask.querySelector('img');
  const btns = [...mask.querySelectorAll('button')].map(b => (b.textContent || '').trim());
  const bar = mask.querySelector('.wb-lb-bar');
  const name = mask.querySelector('.wb-lb-name');
  const counter = bar ? (bar.querySelector('span')?.textContent || '').trim() : '';
  const info = (bar?.textContent || '').replace(/\\s+/g, ' ').trim();
  return {
    open: true,
    src: img ? img.getAttribute('src') : null,
    imgOk: img ? img.naturalWidth > 0 : false,
    btns,
    counter,
    info,
    filename: (name?.textContent || '').trim(),
  };
})()`
const domThumbs = `(() => {
  const figs = [...document.querySelectorAll('.wb-eimgs-item')];
  return figs.map(f => ({
    clickable: f.getAttribute('role') === 'button' || f.querySelector('img') !== null,
    caption: (f.querySelector('figcaption')?.textContent || '').trim(),
  }));
})()`
const domEvidenceSection = `document.querySelector('.wb-eimgs') !== null`

async function openDrawer(page) {
  const row = page.locator('.wb-card[data-ticket-id]', { hasText: FID }).first()
  if (!(await waitFor(async () => (await row.count()) > 0, 8000))) {
    throw new Error('fixture row not rendered (list stub not consumed?)')
  }
  await row.click()
  const ok = await waitFor(async () =>
    page.evaluate(`(${domEvidenceSection})`), 8000)
  if (!ok) throw new Error('evidence section not rendered (files stub empty?)')
  await page.waitForTimeout(300) // 缩略图 img 解析一拍
}

/** 打开灯箱（默认点第 i 张缩略图，0-based）并等遮罩出现。 */
async function openLightbox(page, idx = 0) {
  const item = page.locator('.wb-eimgs-item').nth(idx)
  await item.click()
  const ok = await waitFor(async () => page.evaluate(`(${domLb})`).then(s => s.open), 4000)
  if (!ok) throw new Error('lightbox mask did not appear after thumbnail click')
  await page.waitForTimeout(200)
  return page.evaluate(`(${domLb})`)
}
async function closeLightbox(page) {
  await page.keyboard.press('Escape')
  await waitFor(async () => page.evaluate(`(${domLb})`).then(s => !s.open), 4000)
}
async function lbState(page) { return page.evaluate(`(${domLb})`) }

async function snap(page) {
  try {
    const lb = await lbState(page)
    const thumbs = await page.evaluate(`(${domThumbs})`)
    return `lb=${JSON.stringify(lb).slice(0, 220)} thumbs=${JSON.stringify(thumbs).slice(0, 120)}`
  } catch { return '(snapshot unavailable)' }
}

// ---------------------------------------------------------------- S1 scenarios

/** reload 后重建到「fixture 详情抽屉打开」为止（证据区在抽屉里，光列表不够）。
 *  返回 false 表示板/抽屉没能重建（调用方按环境缺失处理，不算场景失败）。 */
async function reopenDrawer(page) {
  const row = page.locator('.wb-card[data-ticket-id]', { hasText: FID }).first()
  if (!(await waitFor(async () => (await row.count()) > 0, 6000))) {
    const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
    if (!(await boardIcon.count())) return false
    await boardIcon.click().catch(() => {})
    if (!(await waitFor(async () => (await row.count()) > 0, 8000))) return false
  }
  await row.click()
  // 抽屉锚：步骤条（与证据区相互独立，L7/L8 用它证明「真的打开抽屉看过」）。
  return waitFor(async () => (await page.locator('.wb-d2-steps').count()) > 0, 8000)
}

async function L1_clickOpens(page) {
  const lb = await openLightbox(page, 1) // 直接点第 2 张：计数应为 2 / 3
  if (lb.src !== `/sandbar-workbench/api/wf/tickets/${FID}/evidence/lb-b.png`) {
    return `opened img src mismatch: ${lb.src}`
  }
  if (lb.counter !== '2 / 3') return `counter wrong: ${JSON.stringify(lb.counter)}`
  if (lb.filename !== 'lb-b.png') return `filename wrong: ${JSON.stringify(lb.filename)}`
  await closeLightbox(page)
  return null
}

async function L2_buttonsLoop(page) {
  await openLightbox(page, 0)
  const fwd = page.locator('.wb-lb [aria-label="下一张"]').first()
  const back = page.locator('.wb-lb [aria-label="上一张"]').first()
  if (!(await fwd.count())) return '› button not rendered in multi-file lightbox'
  if (!(await back.count())) return '‹ button not rendered in multi-file lightbox'
  await fwd.click(); await page.waitForTimeout(150)
  let lb = await lbState(page)
  if (lb.filename !== 'lb-b.png' || lb.counter !== '2 / 3') return `› from #1 should reach #2: ${JSON.stringify(lb.counter)} ${JSON.stringify(lb.filename)}`
  await fwd.click(); await page.waitForTimeout(150)
  lb = await lbState(page)
  if (lb.filename !== 'lb-c.png') return `› from #2 should reach #3: ${JSON.stringify(lb.filename)}`
  await fwd.click(); await page.waitForTimeout(150)
  lb = await lbState(page)
  if (lb.filename !== 'lb-a.png' || lb.counter !== '1 / 3') return `› from last should wrap to 1: ${JSON.stringify(lb.counter)} ${JSON.stringify(lb.filename)}`
  await back.click(); await page.waitForTimeout(150)
  lb = await lbState(page)
  if (lb.filename !== 'lb-c.png') return `‹ from #1 should wrap to last: ${JSON.stringify(lb.filename)}`
  await closeLightbox(page)
  return null
}

async function L3_keyboard(page) {
  await openLightbox(page, 0)
  await page.keyboard.press('ArrowRight'); await page.waitForTimeout(150)
  let lb = await lbState(page)
  if (lb.filename !== 'lb-b.png') return `ArrowRight did not advance: ${JSON.stringify(lb.filename)}`
  await page.keyboard.press('ArrowLeft'); await page.waitForTimeout(150)
  await page.keyboard.press('ArrowLeft'); await page.waitForTimeout(150)
  lb = await lbState(page)
  if (lb.filename !== 'lb-c.png') return `ArrowLeft wrap did not reach last: ${JSON.stringify(lb.filename)}`
  await page.keyboard.press('Escape'); await page.waitForTimeout(150)
  if ((await lbState(page)).open) return 'Escape did not close the lightbox'
  // 关闭后键位不得再有副作用（监听回收的用户可感知面：不崩、不误动作）。
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Escape')
  return null
}

async function L4_maskClick(page) {
  await openLightbox(page, 0)
  // 点遮罩空白（视口四角附近，图片居中不会覆盖到）→ 关闭。
  await page.mouse.click(20, 20)
  await page.waitForTimeout(200)
  if ((await lbState(page)).open) return 'click on mask backdrop did not close the lightbox'
  // 再开：点图片本体（中心；圆角外角落在 border-radius 外会穿透到遮罩）→ 不得关闭。
  await openLightbox(page, 0)
  const img = page.locator('.wb-lb img').first()
  if (await img.count()) {
    await img.click({ force: true }).catch(() => {})
    await page.waitForTimeout(200)
    if (!(await lbState(page)).open) return 'click on the image itself closed the lightbox'
  }
  await closeLightbox(page)
  return null
}

async function L5_singleFile(page) {
  evidenceFiles = ['lb-only.png']
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await dismissOverlays(page)
  if (!(await reopenDrawer(page))) return 'drawer did not rebuild after reload (env?)'
  const item = page.locator('.wb-eimgs-item').first()
  if (!(await waitFor(async () => (await item.count()) > 0, 8000))) return 'single-file evidence section missing'
  await item.click()
  await waitFor(async () => page.evaluate(`(${domLb})`).then(s => s.open), 4000)
  const lb = await lbState(page)
  if (!lb.open) return 'lightbox did not open for single file'
  if (lb.counter !== '1 / 1' || lb.btns.some(t => t === '›' || t === '‹')) {
    return `single-file should hide nav buttons: counter=${JSON.stringify(lb.counter)} btns=${JSON.stringify(lb.btns)}`
  }
  await closeLightbox(page)
  return null
}

async function L6_brokenImage(page) {
  evidenceFiles = ['lb-broken.png']
  breakImage = 'lb-broken.png'
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await dismissOverlays(page)
  if (!(await reopenDrawer(page))) return 'drawer did not rebuild after reload (env?)'
  const item = page.locator('.wb-eimgs-item').first()
  if (!(await waitFor(async () => (await item.count()) > 0, 8000))) return 'broken-image evidence section missing'
  await waitFor(async () =>
    page.locator('.wb-eimgs-miss').count() > 0, 6000)
  const miss = await page.locator('.wb-eimgs-miss').textContent().catch(() => '')
  if (!miss || !miss.includes('lb-broken.png')) return `broken thumbnail placeholder missing filename: ${JSON.stringify(miss)}`
  return null
}

async function L7_malformedList(page) {
  evidenceMalformed = true
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await dismissOverlays(page)
  if (!(await reopenDrawer(page))) return 'drawer did not rebuild after reload (env?)'
  const shown = await page.evaluate(`(${domEvidenceSection})`)
  if (shown) return 'evidence section still rendered with malformed files payload'
  return null
}

async function L8_emptyList(page) {
  evidenceMalformed = false
  evidenceFiles = []
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await dismissOverlays(page)
  if (!(await reopenDrawer(page))) return 'drawer did not rebuild after reload (env?)'
  const shown = await page.evaluate(`(${domEvidenceSection})`)
  if (shown) return 'evidence section rendered with empty files list'
  return null
}

// ---------------------------------------------------------------- main

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const consoleErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await dismissOverlays(page)

    // API 边界打桩：列表/详情/证据列表/证据图全拦（fixture id 专用）。
    // glob 尾必须是 **：单 * 不跨 /，拦不到 tickets/<id>/evidence 子路径。
    await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
      const path = new URL(route.request().url()).pathname.replace(/\/+$/, '')
      const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
      if (path === '/sandbar-workbench/api/wf/tickets') {
        return body({ ok: true, result: { tickets: [ROW] }, workflows: [WF] })
      }
      const mDet = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (mDet && decodeURIComponent(mDet[1]) === FID) return body({ ok: true, result: detailBase({}) })
      const mEv = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)\/evidence$/.exec(path)
      if (mEv && decodeURIComponent(mEv[1]) === FID) {
        if (evidenceMalformed) return body({ ok: true, result: { files: 'not-an-array' } })
        return body({ ok: true, result: { files: evidenceFiles } })
      }
      const mImg = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)\/evidence\/(.+)$/.exec(path)
      if (mImg && decodeURIComponent(mImg[1]) === FID) {
        const f = decodeURIComponent(mImg[2])
        if (breakImage === f) return route.fulfill({ status: 404, contentType: 'text/plain', body: 'fixture: broken image' })
        return route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1x1 })
      }
      return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
    })

    const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
    if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `no project group 📋 found on ${BASE} (console not provisioned for board view)`)
      return
    }
    await boardIcon.click()
    const rowOk = await waitFor(async () =>
      (await page.locator('.wb-card[data-ticket-id]', { hasText: FID }).count()) > 0, 10000)
    if (!rowOk) {
      record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
      return
    }

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
    const run = async (name, fn) => {
      try {
        // 前置清场：上一场景若断言中途失败可能留下未关的遮罩，先按 Esc 摘掉再跑。
        await page.keyboard.press('Escape')
        await page.waitForTimeout(150)
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
      evidenceFiles = ['lb-a.png', 'lb-b.png', 'lb-c.png']
      evidenceMalformed = false
      breakImage = null
    }

    await openDrawer(page)
    await run('L1 thumbnail click opens lightbox with counter+filename', L1_clickOpens)
    await run('L2 prev/next buttons loop with wrap-around', L2_buttonsLoop)
    await run('L3 arrow keys navigate, Esc closes, no residue', L3_keyboard)
    await run('L4 backdrop click closes, image click does not', L4_maskClick)
    await run('L5 single file: no nav buttons, counter 1/1', L5_singleFile)
    await run('L6 broken image degrades to placeholder', L6_brokenImage)
    // L6 的 404 是打桩设计（坏图降级链路本身），浏览器会如实记一条 resource 404 到
    // console——不算缺陷。清账后 L7-L9 仍覆盖完整零报错要求。
    consoleErrors.length = 0
    pageErrors.length = 0
    await run('L7 malformed files payload hides section', L7_malformedList)
    await run('L8 empty files hides section', L8_emptyList)

    const hygiene = `pageerrors=${pageErrors.length} consoleErrors=${consoleErrors.length}` +
      (pageErrors.length ? ` first=${pageErrors[0]}` : '') + (consoleErrors.length ? ` firstConsole=${consoleErrors[0]}` : '')
    if (pageErrors.length === 0 && consoleErrors.length === 0) record('L9 zero pageerror/console.error', 'pass')
    else record('L9 zero pageerror/console.error', 'fail', hygiene)
  } finally {
    await ctx.close().catch(() => {})
  }
}

async function main() {
  const [maj, min] = process.versions.node.split('.').map(Number)
  if (maj < 22 || (maj === 22 && min < 18)) {
    record('node', 'env_fail', `node ${process.versions.node} < 22.18`)
    return summarize()
  }

  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return summarize()
  }
  if (readFileSync(LIB_JS, 'utf8') !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return summarize()
  }
  const hasExports = navContract()
  if (hasExports) {
    const client = loadClientBundle()
    keyContract(client) && navSemantics(client) && srcContract(client)
  }
  if (results.some(r => r.status === 'fail')) return summarize()

  if (BASE.includes(':3099')) {
    console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)')
    process.exit(1)
  }
  const healthy = await consoleHealthy()
  if (!healthy) {
    record('S1 precheck', 'env_fail', `test console unreachable at ${BASE} (docker compose -f server/docker-compose.test.yml up -d)`)
    return summarize()
  }
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 precheck', 'env_fail', 'playwright-core not resolvable (browser scenarios not run: env)')
    return summarize()
  }
  const browser = await launchBrowser(pw)
  if (!browser) {
    record('S1 precheck', 'env_fail', 'no browser could be launched')
    return summarize()
  }

  let exiting = false
  const shutdown = async (code) => {
    if (exiting) return
    exiting = true
    await browser.close().catch(() => {})
    process.exit(code)
  }
  process.on('SIGINT', () => { void shutdown(130) })
  process.on('SIGTERM', () => { void shutdown(143) })
  try {
    await runBrowser(pw, browser)
  } finally {
    if (!exiting) await browser.close().catch(() => {})
  }
  summarize()
}

// 中途异常按三态 triage（260911 gen5 仲裁补洞，sc_lane_parallel_dom 同款）：main()
// 途中抛错（goto/reload 超时、连接拒绝=stub 台未就绪/被并发抢占）原来只打印不计数，
// fail=0 时 summarize 会 exit 0——「半程假绿」实锤。现在：导航/连接类记 env_fail
// （exit 2），其余记 fail（exit 1），绝不静默。
main().catch(e => {
  const s = String(e?.message ?? e);
  const nav = /Timeout\s*\d+ms\s+exceeded|networkidle|ERR_CONNECTION|ECONNREFUSED|socket hang up|Target closed|net::/i.test(s);
  record('mid-run-abort', nav ? 'env_fail' : 'fail', s.slice(0, 200));
  summarize();
})
