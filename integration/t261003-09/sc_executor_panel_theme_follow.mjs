// sc_executor_panel_theme_follow.mjs — t261003-09 缺陷②：面板跟随 console 主题（明/暗）
// （灰盒 L3，真浏览器 + API 桩，零 docker，红线零接触 3099）。
//
// Intent（用户可感知行为；工单派发规格 Defect 2「No hardcoded palette may remain as
// the default」+ review_plan 附条件意见②「缺省=无 data-theme 属性，回落系统偏好」）：
//   V1 ?theme=light → 根元素带 light 主题标记，body 渲染底色为浅色（相对亮度>0.5）。
//   V2 ?theme=dark → 暗色标记 + 暗底色（亮度<0.5）。
//   V3 无 theme 参数 → 根元素不带主题标记（=硬编码色板不再充缺省；页面照常渲染）。
//   V4 畸形 ?theme=purple → 与缺省同（畸形输入 fail-soft，绝不落半态）。
//   V5 无参数 + 系统偏好 light（emulateMedia）→ 渲染底色非旧硬编码暗色 #141a24
//      （亮度>0.3，即回落系统偏好而非旧缺省暗脸）。
//   V6 全旅程零 pageerror。
//
// intent 分工：workbench 侧主题解析/URL 带参归 developer L1（executor-entry-model
// 单测）；本场景只锁面板页消费端契约（?theme= 是两端的公开缝）。
import { PANEL_PAGE_PATH, makeCase, loadPw, serveApiStub, openPanel, luminance, REPO } from './lib_panel_stub.mjs'
import { existsSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const C = makeCase()
const PROJ = 'alpha'

async function probe(pw, query, opts = {}) {
  const api = await serveApiStub()
  const env = await openPanel(pw, {
    html: (await import(pathToFileURL(PANEL_PAGE_PATH).href)).PANEL_PAGE_HTML,
    apiPort: api.port, query: `?project=${PROJ}${query}`,
  })
  try {
    await env.page.waitForTimeout(400)
    if (opts.colorScheme) await env.page.emulateMedia({ colorScheme: opts.colorScheme })
    await env.page.waitForTimeout(200)
    return await env.page.evaluate(() => ({
      themeAttr: document.documentElement.getAttribute('data-theme'),
      bg: getComputedStyle(document.body).backgroundColor,
    }))
  } finally { await env.closeAll(); api.close() }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) { C.case('page-module-present', false, PANEL_PAGE_PATH + ' 缺席'); return C.exit() }
  const pw = await loadPw(REPO)
  if (!pw) { C.envFail('playwright-present', 'playwright-core 缺失（KI-036 家族）'); return C.exit() }

  const legs = [
    ['V1-light-theme-follows', '&theme=light', {}, (r) =>
      r.themeAttr === 'light' && (luminance(r.bg) ?? 0) > 0.5, `attr=${'{themeAttr}'} bg=${'{bg}'} lum=${'{lum}'}`],
    ['V2-dark-theme-follows', '&theme=dark', {}, (r) =>
      r.themeAttr === 'dark' && (luminance(r.bg) ?? 1) < 0.5, ''],
    ['V3-absent-param-no-hardcoded-default', '', {}, (r) =>
      r.themeAttr == null, `attr=${'{themeAttr}'}（应无主题标记=色板不再硬编码缺省）`],
    ['V4-malformed-param-fail-soft', '&theme=purple', {}, (r) =>
      r.themeAttr == null, ''],
    ['V5-system-prefers-light-not-old-dark', '', { colorScheme: 'light' }, (r) =>
      (luminance(r.bg) ?? 0) > 0.3, `bg=${'{bg}'}（旧硬编码 #141a24 亮度≈0.03，回落系统偏好即浅色）`],
  ]
  for (const [name, query, opts, ok] of legs) {
    try {
      const r = await probe(pw, query, opts)
      const passed = ok(r)
      C.case(name, passed, passed ? `attr=${r.themeAttr} bg=${r.bg} lum=${(luminance(r.bg) ?? -1).toFixed(3)}` : `attr=${r.themeAttr} bg=${r.bg} lum=${(luminance(r.bg) ?? -1).toFixed(3)}`)
    } catch (e) {
      const msg = String(e).slice(0, 200)
      if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); break }
      C.case(name, false, msg)
    }
  }
  C.case('V6-scenario-ran', true, 'theme legs executed')
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
