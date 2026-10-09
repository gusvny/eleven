// sc_executor_panel_unfold_layout.mjs — t261003-09 缺陷①：展开请求不得推移另一栏/下方内容
// （灰盒 L3，真浏览器 + API 桩，零 docker，红线零接触 3099；页面 HTML 取自插件真实
// 页面模块 PANEL_PAGE_HTML seam）。
//
// Intent（用户可感知行为；工单派发规格 Defect 1 + review_plan 附条件意见①「锁不变量
// 不锁机制」）：
//   U1 窄容器（~700px，两栏叠放形态——console 中列 .wb-sb-right flex:4 1 0 min-width:200px
//      的真实再现）：展开任一请求条目后，「Recent actions」区块包围盒不动（±1px），
//      其下方内容不被推下。
//   U2 宽容器（~900px，两栏并列形态）：同一不变量照旧成立（另一列不动）。
//   U3 展开详情仍限高且可内滚（t261003-06 契约面不回退；t261004-16 仲裁修订：
//      不再锚 ≤220 旧值——该票把详情上限抬到 ≥420，此处只锁「有限高 + 可内滚」
//      不变量，上限数值随当期验收口径走）。
//   U4 全旅程零 pageerror。
//
// intent 分工：页面结构/五页签/选项按钮归 t261003-06-executor-panel-page-redesign；
// 主题面色归本票 sc_executor_panel_theme_follow；入口/开柜按钮归 sc_executor_panel_open_session。
// 缝/页面模块未落地=FAIL 点名（TDD 期红属预期）；playwright/chromium 缺席=ENV_FAIL exit 2。
import { PANEL_PAGE_PATH, makeCase, loadPw, serveApiStub, openPanel, REPO } from './lib_panel_stub.mjs'
import { existsSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const C = makeCase()
const PROJ = 'alpha'

const WAITING = [
  { id: 'req-1', project: PROJ, question: 'Which ticket does the executor verify first?', detail: ('Two tickets wait. Pick the first one. This detail text is long enough to fill the capped detail block. ').repeat(40) + 'The cap must hold.', raised_by: 'bench:plan', default_action: 'verify t1', state: 'waiting', created_at: 1 },
  { id: 'req-2', project: PROJ, question: 'How should the executor proceed?', detail: 'two viable paths', raised_by: 'bench', default_action: 'Open a new ticket', state: 'waiting', created_at: 2 },
]

async function run(viewport, label) {
  const api = await serveApiStub({ requests: WAITING })
  const env = await openPanel(await loadPw(REPO), {
    html: (await import(pathToFileURL(PANEL_PAGE_PATH).href)).PANEL_PAGE_HTML,
    apiPort: api.port, query: `?project=${PROJ}`, viewport,
  })
  try {
    await env.page.waitForTimeout(400)
    const rect0 = await env.page.evaluate(() => {
      // t261009-37: the Recent actions head moved into the Overview block chrome
      // (.blk > .bhd > span.sect) — the locator must also match SPAN leaves, the
      // no-shift invariant itself is unchanged.
      const els = [...document.querySelectorAll('h1,h2,h3,h4,div,section,span')].filter(e => /^recent actions$/i.test((e.textContent || '').trim()) && e.children.length === 0)
      const el = els[0]
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { top: r.top, height: r.height }
    })
    if (!rect0) return `Recent actions block not found (${label})`
    // 展开第一条等待请求（按用户点条目正文）
    const clicked = await env.page.click(`text=/${WAITING[0].question.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/`, { timeout: 5000 }).then(() => true).catch(() => false)
    if (!clicked) return `waiting request row not clickable (${label})`
    await env.page.waitForTimeout(400)
    const rect1 = await env.page.evaluate(() => {
      const els = [...document.querySelectorAll('h1,h2,h3,h4,div,section,span')].filter(e => /^recent actions$/i.test((e.textContent || '').trim()) && e.children.length === 0)
      const r = els[0].getBoundingClientRect()
      return { top: r.top, height: r.height }
    })
    // t261009-37 arbitration (declared口径 change): the mock moved the page from
    // column-internal scroll to PAGE scroll, so at the stacked (narrow) width the
    // blocks legitimately reflow downward when a request unfolds — the no-shift
    // invariant only binds the SIDE-BY-SIDE face. Narrow keeps its own face: the
    // unfold must introduce NO horizontal overflow and the actions block must
    // stay below the requests column (stack order kept).
    const moved = Math.abs(rect1.top - rect0.top) > 1 || Math.abs(rect1.height - rect0.height) > 1
    if (label === 'wide' && moved) return `unfold moved the other column: top ${rect0.top}->${rect1.top}, height ${rect0.height}->${rect1.height} (wide)`
    if (label === 'narrow') {
      const sw = await env.page.evaluate(() => ({ doc: document.documentElement.scrollWidth, inner: window.innerWidth }))
      if (sw.doc > sw.inner + 1) return `unfold introduced horizontal overflow: docW=${sw.doc} inner=${sw.inner} (narrow)`
      if (rect1.top <= rect0.top && rect0.top > 0) return `stack order broke: actions head not below requests after unfold (${rect0.top}->${rect1.top})`
    }
    // U3 详情限高可滚（只在窄容器这趟顺带查，避免重复断言面）。
    // t261004-16 仲裁修订：上限数值不再锚旧 170px 时代的 ≤220 硬数（该票 Req 4 把
    // 详情上限抬高到 ≥420，现实现 440px——旧界把新验收钉成假红）。不变量照旧：
    // 详情块被限高（clientHeight 有界）且内容超高时可内滚；夹具文本加长到超过
    // 当期上限（t261004-16 抬帽后 12 次重复在窄宽重排下装得下，滚动面不再触发
    // ——夹具跟帽走，断言不放松）。
    // 详情块被限高（clientHeight 有界）且内容超高时可内滚（scrollHeight>clientHeight）。
    if (label === 'narrow') {
      const detail = await env.page.evaluate(() => {
        const els = [...document.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 4 && e.clientHeight > 0 && e.clientHeight <= 600)
        return els.length > 0
      })
      if (!detail) return 'unfolded detail is neither height-capped nor inner-scrollable (cap/inner-scroll contract regressed)'
    }
    return null
  } finally { await env.closeAll(); api.close() }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) { C.case('page-module-present', false, PANEL_PAGE_PATH + ' 缺席'); return C.exit() }
  const pw = await loadPw(REPO)
  if (!pw) { C.envFail('playwright-present', 'playwright-core 缺失（KI-036 家族）'); return C.exit() }
  const errors = []
  for (const [viewport, label] of [[{ width: 700, height: 900 }, 'narrow'], [{ width: 1000, height: 900 }, 'wide']]) {
    try {
      const err = await run(viewport, label)
      C.case(`U-${label}-unfold-face`, !err, err || `viewport=${viewport.width}px`)
    } catch (e) {
      const msg = String(e).slice(0, 200)
      if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail(`chromium-launch-${label}`, msg); break }
      C.case(`U-${label}-unfold-does-not-push`, false, msg)
    }
  }
  C.case('U-scenario-ran', true, 'layout invariant legs executed')
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
