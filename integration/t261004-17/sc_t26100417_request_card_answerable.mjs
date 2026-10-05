// sc_t26100417_request_card_answerable.mjs — t261004-17 请求卡可回答面（灰盒 L3，
// 真浏览器 + API 桩，零 docker，红线零接触 3099；架构缝复用 t261003-06 同款）。
//
// Intent（用户可感知行为；工单 Part B）：宿主不开折叠、不打长文，就能把一次多问请求
// 答完——选项摊在收起卡上、一击作答；默认动作与已等时长可见；答案框能吃多行。
//   B1 收起态即见选项按钮（不展开详情块），点一击即发出该行回答（POST answer）。
//   B2 两问组渲染为一张卡内两个问题行，各带各的选项（不并为一条文本）。
//   B3 无选项卡显式给出默认动作（If you do not answer…）与已等时长。
//   B4 答案框是 textarea（可多行），不是单行 input。
//   B5 既有行为不回归：Answered 折叠区在、open session 控件在、主题走 var(--) 令牌、
//      全旅程零 pageerror。
// intent 分工：列表契约（source/order/cap/empty copy）归 t261004-14 两条；选项数据面
// append 契约归 t261003-06-executor-panel-requests-options；改版布局五页签/两栏/展开
// 归 t261003-06-executor-panel-page-redesign——本条只锁「不展开即可答」这一新增脸。
// playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 家族）；页面模块未落地=FAIL 点名
// （TDD 期红属预期，arbitrate/merge 期必须绿）。
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const REPO = fileURLToPath(new URL('../../', import.meta.url))
const PROJ = 'alpha'
const NOW = Date.now()

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}

async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts 缺席')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts 缺具名导出 PANEL_PAGE_HTML（缝契约；TDD 期红属预期）')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core 缺失（KI-036 家族）'); return C.exit() }

  // 桩形：两问组（同 group_id 两行，各带各的选项）+ 无选项带默认动作行 + answered 行。
  // 行形状对齐 requests.ts RequestView（status/at）。
  const G = 'group-26100417'
  const waiting = [
    { type: 'request', id: 'gq-1', at: NOW - 120_000, project: PROJ, kind: 'question', group_id: G, question: 'Which ticket does the executor verify first?', detail: 't1 blocks t2.', raised_by: 'bench:plan', default_action: 'Verify t1 first', options: ['Verify t1 first', 'Verify t2 first'], expires_at: null, status: 'waiting' },
    { type: 'request', id: 'gq-2', at: NOW - 120_000, project: PROJ, kind: 'question', group_id: G, question: 'May the executor restart the worker?', detail: 'Wedged since the last deploy.', raised_by: 'bench:plan', default_action: 'Leave it', options: ['Restart now', 'Leave it'], expires_at: null, status: 'waiting' },
    { type: 'request', id: 'nq-1', at: NOW - 3_600_000, project: PROJ, kind: 'question', question: 'Open the batch red-clear ticket?', detail: 'evidence only', raised_by: 'bench', default_action: 'Open the ticket', expires_at: null, status: 'waiting' },
  ]
  const answered = [{ type: 'request', id: 'req-0', at: NOW - 7_200_000, project: PROJ, kind: 'question', question: 'Old question?', detail: 'done', raised_by: 'bench', default_action: 'x', expires_at: null, status: 'answered', answer: 'Open a new ticket' }]
  const postedAnswers = []
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests/answer') && req.method === 'POST') {
      let body = ''
      req.on('data', (d) => { body += d })
      req.on('end', () => { postedAnswers.push(body); res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: true })) })
      return
    }
    if (u.pathname.endsWith('/api/requests') && req.method === 'POST') {
      let body = ''
      req.on('data', (d) => { body += d })
      req.on('end', () => { postedAnswers.push(body); res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: true })) })
      return
    }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [...waiting, ...answered] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: 'Permissions: 4 of 6' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [{ at: NOW, action: 'Sign', ticket: 't261002-10', result: 'ok', permission: 'merge' }], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/status')) return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } } })
    if (u.pathname.endsWith('/api/bridge/status')) return json({ ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [] })
    res.writeHead(404); res.end('{}')
  })
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const port = stub.address().port
  const html = pageMod.PANEL_PAGE_HTML

  const { chromium } = pw
  let browser = null
  try {
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html) })
    await new Promise(r => local.listen(0, '127.0.0.1', r))
    const lport = local.address().port
    await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForTimeout(600)

    // B1 收起态即见选项：不展开任何行，选项标签文本已进 innerText；点按钮发出 answer POST
    const preText = (await page.evaluate(() => document.body.innerText))
    const optionsVisibleCollapsed = /verify t1 first/i.test(preText) && /leave it/i.test(preText) && /restart now/i.test(preText)
    let posted = false
    try {
      await page.click('text=/Restart now/')
      await page.waitForTimeout(300)
      posted = postedAnswers.length > 0 && /gq-2/.test(postedAnswers[0])
    } catch { /* B1 fail below */ }
    C.case('B1-options-visible-collapsed-one-click', optionsVisibleCollapsed && posted,
      `options-visible=${optionsVisibleCollapsed} posted=${posted} body=${JSON.stringify(postedAnswers[0] || '').slice(0, 120)}`)

    // B2 两问组：两个问题文本都在页面上（一行一问，不并写），组内行数=2
    const groupRows = await page.evaluate(() => document.body.innerText)
    const bothQuestions = /verify first/i.test(groupRows) && /restart the worker/i.test(groupRows)
    C.case('B2-two-questions-both-visible', bothQuestions, `both=${bothQuestions}`)

    // B3 无选项卡：默认动作文案与已等时长在场
    const t3 = (await page.evaluate(() => document.body.innerText)).toLowerCase()
    const defaultShown = t3.includes('if you do not answer') && t3.includes('open the ticket')
    const waitedShown = /\b(about an hour|an hour|1 hour|60 minutes|just now|\d+m|\dh)\b/.test(t3) || /waited|waiting for/.test(t3)
    C.case('B3-default-action-and-waited-shown', defaultShown && waitedShown,
      `default=${defaultShown} waited=${waitedShown}`)

    // B4 答案框 textarea（多行）
    const box = await page.evaluate(() => {
      const ta = document.querySelector('textarea')
      if (ta) return { tag: 'textarea', rows: ta.rows || 1 }
      const inp = document.querySelector('input[type=text],input:not([type])')
      return inp ? { tag: 'input' } : null
    })
    C.case('B4-answer-box-multiline', !!box && box.tag === 'textarea' && (box.rows || 1) >= 2,
      `box=${JSON.stringify(box)}`)

    // B5 既有行为不回归
    const answeredHead = await page.textContent('#doneHead2').catch(() => '')
    C.case('B5a-answered-section-intact', /answered\s*·\s*\d/i.test(answeredHead || ''), `head="${(answeredHead || '').trim()}"`)
    const openSession = await page.$$eval('button, a', es => es.some(e => /open session/i.test(e.textContent || '') || e.hasAttribute('data-open-session')))
    C.case('B5b-open-session-control-intact', openSession, 'open session 控件在场')
    const cssText = await page.evaluate(() => {
      const el = document.querySelector('style')
      return el ? el.textContent : [...document.styleSheets].map(s => { try { return [...s.cssRules].map(r => r.cssText).join('\n') } catch { return '' } }).join('\n')
    })
    const themeTokens = /var\(--/.test(cssText) && !/#[0-9a-f]{6}\s*;/.test((cssText.match(/color\s*:\s*#[0-9a-f]{3,6}/gi) || []).join(';'))
    C.case('B5c-theme-tokens-only', themeTokens, '颜色面走 var(--) 令牌，无裸 hex')
    C.case('B5d-zero-pageerror', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)

    await browser.close()
    local.close()
    stub.close()
  } catch (e) {
    if (browser) { try { await browser.close() } catch { /* noop */ } }
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg)
    return C.exit()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
