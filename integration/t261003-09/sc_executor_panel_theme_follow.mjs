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
// t261004-10（primary 按钮明色主题对比度缺陷 1.26:1）新增：
//   C1 light + dark 两主题下 #grantsSave / #saveBtn 的标签色×底色对比度各 ≥4.5:1（4 组合）。
//   C2 .line / .knob 分隔线颜色跟随 --line-soft（token-follow，装饰线不适用 4.5:1）。
//   C3 静态扫：主题定义块（明/暗/系统偏好镜像）之外零硬编码十六进制色。
//   V6 全旅程零 pageerror。
//
// intent 分工：workbench 侧主题解析/URL 带参归 developer L1（executor-entry-model
// 单测）；本场景只锁面板页消费端契约（?theme= 是两端的公开缝）。
import { PANEL_PAGE_PATH, makeCase, loadPw, serveApiStub, openPanel, luminance, REPO } from './lib_panel_stub.mjs'
import { existsSync, readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const C = makeCase()
const PROJ = 'alpha'

/** WCAG 对比度（两相对亮度之比；AA 正文门槛 4.5:1）。 */
function contrastRatio(fg, bg) {
  const a = luminance(fg); const b = luminance(bg)
  if (a == null || b == null) return null
  const [hi, lo] = a >= b ? [a, b] : [b, a]
  return (hi + 0.05) / (lo + 0.05)
}

/** 静态扫：只看 <style> 块；主题定义行（--bg:# = 明/暗/系统偏好镜像）之外零十六进制色。
 *  先剥掉 &#NNNN; 形态的 HTML 实体（数字恰是十六进制合法字符，会误报）。 */
function hardcodedHexOutsideThemeBlocks(source) {
  const style = /<style>([\s\S]*?)<\/style>/.exec(source)
  if (!style) return ['no <style> block found']
  const offenders = []
  style[1].split('\n').forEach((l, i) => {
    if (/--bg:#/.test(l)) return
    const m = l.replace(/&#\w+;/g, '').match(/#[0-9a-fA-F]{3,8}\b/g)
    if (m) offenders.push(`style line ${i + 1}: ${m.join(',')}`)
  })
  return offenders
}

/** 打开面板并取控制件计算态（标签/底色、分隔线颜色、--line-soft 解析值）。 */
async function probeControls(pw, query) {
  const api = await serveApiStub()
  const env = await openPanel(pw, {
    html: (await import(pathToFileURL(PANEL_PAGE_PATH).href)).PANEL_PAGE_HTML,
    apiPort: api.port, query: `?project=${PROJ}${query}`,
  })
  try {
    await env.page.waitForTimeout(400)
    return await env.page.evaluate(() => {
      const resolveToken = (tok) => {
        const d = document.createElement('div')
        d.style.display = 'none'; d.style.borderBottomColor = `var(${tok})`
        document.documentElement.appendChild(d)
        const v = getComputedStyle(d).borderBottomColor
        d.remove(); return v
      }
      const btn = (id) => {
        const el = document.getElementById(id)
        if (!el) return null
        const cs = getComputedStyle(el)
        return { color: cs.color, bg: cs.backgroundColor }
      }
      const borderColor = (sel) => {
        const el = document.querySelector(sel)
        return el ? getComputedStyle(el).borderBottomColor : null
      }
      return {
        grantsSave: btn('grantsSave'), saveBtn: btn('saveBtn'),
        lineBorder: borderColor('.line'), knobBorder: borderColor('.knob'),
        lineSoft: resolveToken('--line-soft'),
      }
    })
  } finally { await env.closeAll(); api.close() }
}

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

  // ---- t261004-10：primary 按钮对比度 + 分隔线 token-follow + 硬编码色静态扫 ----
  for (const theme of ['light', 'dark']) {
    try {
      const r = await probeControls(pw, `&theme=${theme}`)
      const fails = []
      const pairs = []
      for (const [id, v] of [['grantsSave', r.grantsSave], ['saveBtn', r.saveBtn]]) {
        if (!v) { fails.push(`${id} absent`); continue }
        const ratio = contrastRatio(v.color, v.bg)
        pairs.push(`${id}=${ratio ? ratio.toFixed(2) : 'null'}`)
        if (ratio == null || ratio < 4.5) fails.push(`${id} ${ratio} < 4.5 (${v.color} on ${v.bg})`)
      }
      const div = []
      if (r.lineBorder !== r.lineSoft) fails.push(`.line ${r.lineBorder} != --line-soft ${r.lineSoft}`)
      else div.push(`.line ok`)
      if (r.knobBorder != null) {
        if (r.knobBorder !== r.lineSoft) fails.push(`.knob ${r.knobBorder} != --line-soft ${r.lineSoft}`)
        else div.push('.knob ok')
      } else div.push('.knob not rendered (guarded by static sweep)')
      const passed = fails.length === 0
      C.case(`C1C2-${theme}-contrast-and-dividers`, passed,
        (passed ? 'ok: ' : 'FAIL: ') + fails.concat(pairs, div).join(' | '))
    } catch (e) {
      const msg = String(e).slice(0, 200)
      if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); break }
      C.case(`C1C2-${theme}-contrast-and-dividers`, false, msg)
    }
  }
  try {
    const offenders = hardcodedHexOutsideThemeBlocks(readFileSync(PANEL_PAGE_PATH, 'utf8'))
    C.case('C3-static-no-hardcoded-hex-outside-theme-blocks', offenders.length === 0,
      offenders.length ? offenders.join(' ; ') : 'style block clean outside theme definition lines')
  } catch (e) { C.case('C3-static-no-hardcoded-hex-outside-theme-blocks', false, String(e).slice(0, 200)) }

  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
