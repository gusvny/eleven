#!/usr/bin/env node
// t260915-08 场景②：工单板巡检行 UI——「等你=黄调行」一眼可见 + 详情下钻 + 签字 POST 带 gate
// （灰盒 L3 渲染层，browser-free 池；镜 baselines/sc_lane_parallel_dom.mjs 两层式，取舍见方案 §3.5 镜B）。
//
// 用户场景（工单正文②③④+验收①）：宿主在操作面必须能感知「有巡检票等你签」——
// mock ⑤H 口径=等你行黄底+「去签字→」；点行下钻看到 阶段时间线/发现摘要/报告路径/
// 人门「签什么」；签字 POST 必须带 gate=inspection-close（工作台同款通道零旁路的数据面）。
//
// 两层（与 baseline 同拆）：
//   S0 build-contract（纯 node 处处可跑）：shipped 双 bundle 同步 + 巡检锚点在位
//      （合流端点串/gate 常量/签什么段/awaiting_gate 消费）+ node.ts sign gate 透传源锚。
//   S1 真浏览器 DOM 断言：隔离台（SANDBAR_TEST_CONSOLE，缺省 127.0.0.1:3199）+
//      playwright-core 可解析 + chromium 可起，任一缺席=ENV_FAIL exit 2 点名。
//      数据只在 API 边界打桩（page.route）：浏览器/console/shipped bundle/React 渲染
//      路径全真；绝不碰生产 3099/真票。
// 三态（t260904-12）：stdout 末行 SUMMARY pass/fail/env_fail/na；fail>0 或全 na=exit 1；
// env_fail>0=exit 2。与镜 B 的 intent 分工：彼守泳道图并行渲染，本条守巡检行卡/详情/签字通道。
// 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
let BASE = ''
try {
  BASE = (await ensureStageConsole()).base
} catch (e) {
  console.log(`[ENV_FAIL] stage console 不可得：${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
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

// ---------------------------------------------------------------- 夹具（API 桩数据面）

const FID = 'inspfixture0915a'   // 夹具票 id（纯字母数字；绝非真票号）
const INS_ID = 'inspection-fixture-20260915' // 巡检夹具票号（instance=fixture 期=20260915）

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
    { id: 'merge', name: '合并', role: 'integration', parts: ['human'] },
    { id: 'suggest_next', name: '建议下一单', role: 'integration', parts: ['script'] },
  ],
}
const DEV_ROW = {
  id: FID, role: 'developer', status: 'dispatched', title: 'UI 桩 dev 对照票',
  workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
  handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: 0,
  created: 1789354800, engine: 'template-as-code-v2', exec_status: 'RUNNING',
}
// 方案 R4 行形状（验收①「实例/期号/段/发现数/人门态」）+ awaiting-human=黄行数据源
const INS_ROW = {
  id: INS_ID, kind: 'inspection', engine: 'inspection', project: '', epic: '',
  title: '巡检 fixture · 期 20260915', template: 'inspection-lite',
  instance_id: 'fixture', period: '20260915', stage: 'close', stage_state: 'awaiting-human',
  status: 'running', decision: '', findings: { high: 1, med: 2, low: 0, total: 3 },
  heartbeat: true, report_path: 'out/inspection/inspection-fixture-20260915.json',
  awaiting_gate: true, human_gate: null, blocked_reason: '', gate_error: '',
  created: 1789354800, updated: '09-15 07:30', updated_ts: 1789354800,
  paused: false, paused_phase: '', handoff_count: 0, pending_count: 0,
  worktree: '', workspace: null, role: null, proposal_id: '', workflow: '',
  close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
}
const tle = (stage, state, reason = '') => ({ at: '2026-09-15T07:30:00', stage, state, reason })
function insDetail(over) {
  return {
    id: INS_ID, kind: 'inspection', engine: 'inspection', template: 'inspection-lite',
    title: INS_ROW.title, stage: 'close', stage_state: 'awaiting-human', status: 'running',
    decision: '', gate_id: 'inspection-close', instance_id: 'fixture', period: '20260915',
    report_path: INS_ROW.report_path, red_line: '巡检只出报告与开票建议，绝不直接改码。',
    heartbeat: true, summary: { high: 1, med: 2, low: 0 },
    findings: [
      { id: 'f1', scan: 'test', severity: 'high', subject: '高危样例', evidence: 'evidence-high', suggestion: '开票修' },
      { id: 'f2', scan: 'test', severity: 'med', subject: '中危样例', evidence: 'evidence-med', suggestion: '人审后定' },
      { id: 'f3', scan: 'test', severity: 'med', subject: '中危样例2', evidence: 'evidence-med2', suggestion: '人审后定' },
    ],
    suggested_fix_tickets: [], blocked_reason: '', human_gate: null, gate_error: '',
    worktree: '', workspace: null,
    timeline: [tle('scan', 'done'), tle('report', 'done'), tle('close', 'running', '人审发现清单')],
    ...over,
  }
}
const INS_DETAIL = insDetail()
const INS_DETAIL_MALFORMED = 'not-a-json-object'

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const NODE_TS = join(REPO, 'server', 'plugins', 'workbench', 'node.ts')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return
  }
  const anchors = ['wf/inspection/tickets', 'inspection-close', '签什么', 'awaiting_gate']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 bundle-anchors', 'fail', `shipped bundle missing inspection anchors: ${missing.join(', ')}`)
  } else {
    record('S0 bundle-anchors', 'pass', 'twin bundles in sync, inspection anchors present')
  }
  if (!existsSync(NODE_TS)) {
    record('S0 host-gate-passthrough', 'fail', 'node.ts missing')
    return
  }
  const host = readFileSync(NODE_TS, 'utf8')
  if (/body\.gate/.test(host)) {
    record('S0 host-gate-passthrough', 'pass', 'node.ts sign 透传 body.gate（不再是写死空串）')
  } else {
    record('S0 host-gate-passthrough', 'fail', 'node.ts op=sign 未见 body.gate 透传（gate 写死空串=巡检签字必被拒收）')
  }
}

// ---------------------------------------------------------------- S1 真浏览器

function consoleHealthy() {
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) }).then(r => r.ok).catch(() => false)
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

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await dismissOverlays(page)

    let detailPayload = INS_DETAIL
    const signPosts = []
    await page.route('**/sandbar-workbench/api/wf/**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      const isSign = /\/sign$/.test(path) && route.request().method() === 'POST'
      if (isSign) {
        try { signPosts.push(route.request().postData() || '') } catch { signPosts.push('') }
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true }) })
      }
      if (path === '/sandbar-workbench/api/wf/tickets') {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: [DEV_ROW] }, workflows: [WF] }) })
      }
      if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: [INS_ROW] } }) })
      }
      const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && decodeURIComponent(m[1]) === INS_ID) {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: detailPayload }) })
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown ticket or sub-route' }) })
    })

    // 开板：workbench 需要项目视图才渲染工单列表（镜 B 同款入口）
    const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
    if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `no project group 📋 found on ${BASE} (console not provisioned for board view)`)
      return
    }
    await boardIcon.click()
    const anyCard = page.locator('.wb-card[data-ticket-id]')
    if (!(await waitFor(async () => (await anyCard.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
      return
    }
    record('S1 precheck', 'pass', 'board renders with stubbed list')

    // ① 巡检行上板（合流入通用板，R5/R9）
    const insCard = page.locator('.wb-card[data-ticket-id]', { hasText: '巡检' }).first()
    const insById = page.locator(`.wb-card[data-ticket-id="${INS_ID}"]`).first()
    const card = (await insById.count()) ? insById : insCard
    if (!(await waitFor(async () => (await card.count()) > 0, 8000))) {
      record('S1 row-on-board', 'fail', `巡检行未上板（dev 对照行在而巡检行缺席=收录/合流面未落地）；cards=${await anyCard.count()}`)
      return
    }
    const rowText = await card.innerText()
    record('S1 row-on-board', 'pass', `巡检行在场：${rowText.replace(/\s+/g, ' ').slice(0, 120)}`)

    // ② 字段齐：实例/期号/发现数在行文本可见
    const missingFields = [['期号 20260915', rowText.includes('20260915')],
    ['发现数 1/2/0', /1\s*\/?\s*2|发现/.test(rowText)],
    ['段 close/人门', /close|签|人审/.test(rowText)]]
      .filter(([, good]) => !good).map(([label]) => label)
    record('S1 row-fields', missingFields.length ? 'fail' : 'pass',
      missingFields.length ? `行文本缺字段：${missingFields.join(',')}；text=${rowText.slice(0, 160)}` : '实例/期号/发现数/段可见')

    // ③ 等你=黄调行（mock ⑤H 核心诉求）：data-state=waiting + 计算样式非默认白底
    const state = await card.getAttribute('data-state')
    const bg = await card.evaluate(el => getComputedStyle(el).backgroundColor)
    // t260915-08 实证加严：rgba(0,0,0,0)=透明（blanket 规则压平时的现形）——断言必须
    // 解析出非透明且非纯白的底色。计算值有两种序列化：rgba?(r,g,b[,a]) 与
    // CSS Color 4 的 color(srgb r g b[/ a])（color-mix 令牌解析产物），两种都吃。
    const mRgba = /^rgba?\(([^)]+)\)$/.exec(bg || '')
    const mColor = /^color\(srgb\s+([^)]+)\)$/.exec(bg || '')
    const parts = mRgba ? mRgba[1].split(/[,/]/).map(s => parseFloat(s))
      : mColor ? mColor[1].split(/[\s,/]+/).filter(Boolean).map(s => parseFloat(s) * 255)
      : []
    const alpha = mColor ? 1 : (parts.length >= 4 ? parts[3] : (parts.length === 3 ? 1 : 0))
    const isWhiteish = parts.length >= 3 && parts[0] > 250 && parts[1] > 250 && parts[2] > 250
    const yellowish = state === 'waiting' && alpha > 0 && !isWhiteish
    if (yellowish) {
      record('S1 waiting-yellow', 'pass', `data-state=waiting 底色已上漆 bg=${bg}`)
    } else {
      // 失败取证：命中的带 background 的规则全列（cascade 谁赢）+ 令牌现值——
      // 规则在 bundle、令牌合法、浏览器支持 color-mix 三者齐而仍透明=必须点名赢家规则
      const rulesDump = await card.evaluate(el => {
        const out = []
        for (const sheet of document.styleSheets) {
          let list
          try { list = [...sheet.cssRules] } catch { continue }
          const walk = (rs) => {
            for (const r of rs) {
              // 注意：Chrome 的 CSSStyleRule.cssRules 恒存在（空列表 truthy）——
              // 以「有无 selectorText/style」判样式规则，不能以 cssRules 判组规则
              if (!r.selectorText || !r.style) {
                if (r.cssRules) walk([...r.cssRules])
                continue
              }
              let hit = false
              try { hit = el.matches(r.selectorText) } catch { continue }
              if (hit && (r.style.background || r.style.backgroundColor)) {
                out.push(`${r.selectorText} -> background:${r.style.background || r.style.backgroundColor}`)
              }
              if (r.cssRules && r.cssRules.length) walk([...r.cssRules])
            }
          }
          walk(list)
        }
        const root = getComputedStyle(document.documentElement)
        out.push(`token --dsw-derive-warn-bg=${root.getPropertyValue('--dsw-derive-warn-bg').slice(0, 90) || '(未定义)'}`)
        return out
      }).catch(e => [`introspect 失败：${String(e).slice(0, 80)}`])
      record('S1 waiting-yellow', 'fail',
        `等你行未上漆：data-state=${JSON.stringify(state)} bg=${bg}（mock ⑤H 一眼可见诉求）；命中规则=${JSON.stringify(rulesDump)}`)
    }

    // ④「去签字→」钮在场
    const signBtn = card.locator('button', { hasText: '去签字' }).first()
    const hasSignBtn = await waitFor(async () => (await signBtn.count()) > 0, 3000)
    record('S1 sign-nav-button', hasSignBtn ? 'pass' : 'fail',
      hasSignBtn ? '「去签字 →」钮在场' : '等你行缺「去签字 →」导航钮（ticket-row-card waiting 面）')

    // ⑤ 点行 → 详情下钻：时间线/发现摘要/报告路径/签什么
    await card.click()
    const drawer = page.locator('.wb-drawer, [role="dialog"]').first()
    const drawerOk = await waitFor(async () => (await drawer.count()) > 0, 8000)
    // 等巡检面内容而非抽屉壳（壳=×按钮先渲染，详情 fetch 后到——竞态教训）
    const faceOk = drawerOk && await waitFor(
      async () => (await page.locator('[data-testid="inspection-face"]').count()) > 0, 10000)
    if (!drawerOk || !faceOk) {
      record('S1 detail-drilldown', 'fail',
        `点巡检行后详情未渲染（drawer=${drawerOk} face=${faceOk}；text=${(await drawer.innerText().catch(() => '')).slice(0, 120)}）`)
      return
    }
    const dText = await drawer.innerText().catch(() => '')
    const missDetail = [['阶段时间线', /scan|report|close|时间线|阶段/.test(dText)],
    ['发现摘要', /发现/.test(dText) && dText.includes('1')],
    ['报告路径', dText.includes('out/inspection/')],
    ['签什么', /签什么|签字/.test(dText)]]
      .filter(([, good]) => !good).map(([label]) => label)
    record('S1 detail-drilldown', missDetail.length ? 'fail' : 'pass',
      missDetail.length ? `详情缺段：${missDetail.join(',')}；drawer text=${dText.slice(0, 200)}` : '时间线/发现摘要/报告路径/签什么齐')

    // ⑥ 「去签字→」锚点 → 签什么段可见（R6 anchor 衔接）
    if (hasSignBtn) {
      // 先关抽屉（覆盖层拦截板面点击——竞态实测）；关=等详情壳消失（双壳形态都等：
      // .wb-drawer 与 [role="dialog"]；关闭候选走基线同款双选择器+Escape 兜底）
      await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
      await waitFor(async () => (await page.locator('.wb-drawer, [role="dialog"]').count()) === 0, 5000)
      if ((await page.locator('.wb-drawer, [role="dialog"]').count()) > 0) {
        await page.keyboard.press('Escape').catch(() => {})
        await page.waitForTimeout(600)
      }
      let anchorEvidence = ''
      try {
        await signBtn.click({ timeout: 8000 })
      } catch (e) {
        // 点击失败=取证先行：谁在挡？（overlay 计数+按钮中心 elementFromPoint）
        anchorEvidence = await page.evaluate(() => {
          const b = [...document.querySelectorAll('.wb-card-btn')].find(x => x.textContent.includes('去签字'))
          if (!b) return '去签字钮不在 DOM'
          const r = b.getBoundingClientRect()
          const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
          return `overlays: .wb-drawer=${document.querySelectorAll('.wb-drawer').length} [role=dialog]=${document.querySelectorAll('[role="dialog"]').length}; btn rect=[${[r.x, r.y, r.width, r.height].map(Math.round)}]; elementFromPoint=${top ? top.tagName + '.' + String(top.className).slice(0, 50) : 'null'}; topInDrawer=${!!(top && top.closest('.wb-drawer, [role="dialog"]'))}`
        }).catch(e => `introspect 失败：${String(e).slice(0, 80)}`)
      }
      // 等「签什么」段真实渲染（数据面在位），不看壳
      const gateOk = anchorEvidence === '' && await waitFor(
        async () => (await page.locator('[data-testid="inspection-gate"]').count()) > 0, 10000)
      const dText2 = gateOk ? await page.locator('[data-testid="inspection-gate"]').innerText().catch(() => '') : ''
      record('S1 review-anchor', gateOk && /签什么/.test(dText2) ? 'pass' : 'fail',
        gateOk && /签什么/.test(dText2) ? '去签字→落人门「签什么」段（review 锚点衔接）'
          : `去签字→未落签什么段：${anchorEvidence || `gate=${gateOk} text=${dText2.slice(0, 100)}`}`)
    } else {
      record('S1 review-anchor', 'na', '无「去签字→」钮可点（前腿已红）')
    }

    // ⑦ 签字 POST 带 gate（工作台同款通道零旁路的数据面）
    const approveBtn = page.locator('[data-testid="inspection-sign-approve"]').first()
    if (await approveBtn.count()) {
      await approveBtn.click({ timeout: 3000 }).catch(() => {})
      await waitFor(async () => signPosts.length > 0, 5000)
      await page.waitForTimeout(300)
      const hit = signPosts.find(b => /gate/.test(b) && /decision/.test(b))
      let gateOk = false
      let detailMsg = `captured=${JSON.stringify(signPosts).slice(0, 200)}`
      if (hit) {
        try {
          const parsed = JSON.parse(hit)
          gateOk = parsed.gate === 'inspection-close' && parsed.decision === 'approve'
          detailMsg = `gate=${JSON.stringify(parsed.gate)} decision=${JSON.stringify(parsed.decision)}`
        } catch (e) { detailMsg = `POST body 非合法 JSON：${String(e).slice(0, 80)}` }
      }
      record('S1 sign-post-gate', gateOk ? 'pass' : 'fail',
        gateOk ? `签字 POST 带 gate=inspection-close&decision=approve（${detailMsg}）` : `签字 POST 未按契约带 gate/decision：${detailMsg}`)
    } else {
      record('S1 sign-post-gate', 'na', '详情内未见可点的签字钮（前腿面缺失）')
    }

    // ⑧ 畸形详情回执不崩（消费外部输入=不可信，畸形腿必带）
    await page.locator('.wb-drawer .wb-close').first().click({ timeout: 3000 }).catch(() => {})
    await waitFor(async () => (await page.locator('.wb-drawer').count()) === 0, 5000)
    detailPayload = INS_DETAIL_MALFORMED
    await card.click()
    await page.waitForTimeout(1500)
    record('S1 malformed-detail', pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `畸形 show 回执触发 pageerror：${pageErrors[0]}` : '畸形详情回执零 pageerror（不崩）')

    if (pageErrors.length) {
      record('S1 page-health', 'fail', `pageerror 计 ${pageErrors.length}：${pageErrors.slice(0, 3).join(' | ')}`)
    } else {
      record('S1 page-health', 'pass', '全程零 pageerror')
    }
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- 主流程

buildContract()
if (!consoleHealthy()) {
  record('S1 console', 'env_fail', `测试控制台不可达：${BASE}（supply 台未起？宿主 3099 红线不碰）`)
} else {
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 playwright', 'env_fail', 'playwright-core 不可解析（lib_pw_deps 候选路径全落空）')
  } else {
    const browser = await launchBrowser(pw)
    if (!browser) {
      record('S1 chromium', 'env_fail', 'chromium/chrome 无法启动（headless 环境缺浏览器）')
    } else {
      try {
        await runBrowser(pw, browser)
      } catch (e) {
        // 三态纪律：任何腿的意外异常=FAIL 落账 + SUMMARY 收口，绝不裸异常逃逸
        // （逃逸=无 SUMMARY 行，闸侧计数失真）。
        record('S1 run-browser', 'fail', `未捕获异常：${String(e).slice(0, 300)}`)
      } finally {
        await browser.close().catch(() => {})
      }
    }
  }
}
summarize()
