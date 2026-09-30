/**
 * contrast-palette.mjs —— 对比度纪律的源级守卫（t260905-08-wb-contrast-guard /
 * t260907-08-wb-contrast-quadrant 集测实测红 2.62–4.24 < 4.5 的 UT 锁，t260929-22 gen8）：
 * 文字语义令牌的**声明位深墨值**在白底上的 WCAG 对比度 ≥4.5，epic chip 按真实
 * color-mix 公式（含最浅 epic 色/夹具）取最劣计算。令牌定义再变，这里重算即刻红。
 *
 * 白底场景 = 集测实测形态。260930 直修口径（取代 gen8「浅档深墨裸值」）：九个文字墨
 * 一律为「深基色 P% × 平台 label」形态——裸值治不了两档（固定深墨在暗档整片不可读，
 * 闸 contrast/dark 违例 375），能翻转的只有 label。判据=墨 × {白底, 四族淡底} ×
 * {浅/暗两档极性} 全矩阵 ≥4.5（真台中层灰档只记录不断言）。
 *
 * 已知不可调和项（升级中，UT 不为其背书）：psess「＋ New session」文字被
 * t260904-05 t3 锁定为 45% 项目色×平台前景派生（180px 台实测 2.64），与 ≥4.5
 * 数学不可两全——证明与宿主裁决请求见 integration/t260929-22/DESIGN-CONFLICT.md。
 */
import assert from 'node:assert/strict'
import { PROJECT_PALETTE, FALLBACK_COLOR } from '../src/shared/project-color.ts'
import { epicChipColor, DERIVE_TOKENS_CSS } from '../src/client/theme.ts'

let n = 0

/** WCAG 2.x：相对亮度 + 对白底对比度。 */
function luminance([r, g, b]) {
  const f = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
function contrastOnWhite(rgb) {
  return (1.0 + 0.05) / (luminance(rgb) + 0.05)
}
function hex(s) {
  const v = String(s).trim().replace(/^#/, '')
  assert.ok(/^[0-9a-fA-F]{6}$/.test(v), `hex parse: ${s}`)
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255)
}
/** DERIVE_TOKENS_CSS 里取某令牌的声明值（去注释后按 `--dsw-derive-名:值` 切）。 */
function tokenDef(name) {
  const defs = DERIVE_TOKENS_CSS.replace(/\/\*[\s\S]*?\*\//g, '').split(';').map((x) => x.trim())
  const d = defs.find((x) => x.includes(name + ':'))
  assert.ok(d, `token ${name} declared in DERIVE_TOKENS_CSS`)
  return d.slice(d.indexOf(name + ':') + name.length + 1)
}
function mixPct(a, p, b) {
  const t = p / 100
  return a.map((c, i) => c * t + b[i] * (1 - t))
}
/** 任意两色的 WCAG 相对对比度（不限白底——本册要压「墨 × 淡底」全矩阵）。 */
function contrast(a, b) {
  const l1 = luminance(a), l2 = luminance(b)
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
}
/** 两档平台前景代表值：①闸 light 档位注入值 ②真台中层灰（t260929-22 gen9 实测值）。 */
const LABEL_LIGHT = hex('#1f2328')
const LABEL_STAGE = hex('#7a7a85')
const LABEL_DARK = hex('#e6e6e9')
/** 文字墨令牌在某一档平台前景下的**生效值**：裸 hex 直读；`color-mix(基色 P%, label)`
 * 按声明里的 P 与给定 label 混出（t260930 直修口径：九个墨一律回到极性自适应形态，
 * 固定深墨在暗档整片不可读——t260905-08 contrast/dark 违例 375 的根因）。 */
function inkOn(name, label) {
  const d = tokenDef(name)
  if (!d.includes('color-mix')) return hex(d)
  const base = hex('#' + d.match(/#([0-9a-fA-F]{6})/)[1])
  const p = Number(d.match(/(\d+)%/)[1])
  return mixPct(base, p, label)
}
/** 四族淡底（家族底色的 12%，warn 为 16%——与集成场景同一派生口径）。 */
function tintOf(baseHex, pct, surface) {
  return mixPct(hex(baseHex), pct, surface)
}
const LIGHT_SURFACE = hex('#ffffff')
const DARK_SURFACE = hex('#16181d')
const TINTS = {
  accent: '#0969da', danger: '#cf222e', success: '#1a7f37', warn: '#eac54f',
}
const TINT_PCT = { accent: 12, danger: 12, success: 12, warn: 16 }

// ① waiting 态文字 = --dsw-derive-warn（极性自适应墨 × 浅档平台前景）
{
  const c = contrastOnWhite(inkOn('--dsw-derive-warn', LABEL_LIGHT))
  assert.ok(c >= 4.5, `① --dsw-derive-warn on white = ${c.toFixed(2)} >= 4.5`)
  console.log(`ok   ① warn ink -> ${c.toFixed(2)}`)
  n++
}

// ② muted 文字（进展行/时间/左栏 mini 行卡缺省）= --dsw-derive-muted
{
  const c = contrastOnWhite(inkOn('--dsw-derive-muted', LABEL_LIGHT))
  assert.ok(c >= 4.5, `② --dsw-derive-muted on white = ${c.toFixed(2)} >= 4.5`)
  console.log(`ok   ② muted ink -> ${c.toFixed(2)}`)
  n++
}

// ③ 全部九个文字墨 × 白底/四族淡底 × **两档平台极性**（t260930 直修口径）
//    真故障=固定深墨（gen8/gen9）在暗档整片不可读：闸 contrast/dark 违例 375、
//    首例 sidebar/wb-group-name 1.21。本矩阵把「两档都要过」和「跨族淡底」一起锁：
//    只锁白底浅档的写法正是当初漏掉暗档的原因。
{
  const INKS = ['--dsw-derive-fg', '--dsw-derive-muted', '--dsw-derive-warn', '--dsw-derive-danger',
    '--dsw-derive-accent', '--dsw-derive-success', '--dsw-derive-ink-strong',
    '--dsw-derive-ink-blue', '--dsw-derive-active']
  for (const [leg, label, surface] of [['light', LABEL_LIGHT, LIGHT_SURFACE], ['dark', LABEL_DARK, DARK_SURFACE]]) {
    let worst = Infinity, worstAt = ''
    for (const name of INKS) {
      const ink = inkOn(name, label)
      const surfaces = { white: surface, ...Object.fromEntries(Object.entries(TINTS)
        .map(([k, v]) => [k, tintOf(v, TINT_PCT[k], surface)])) }
      for (const [sn, bg] of Object.entries(surfaces)) {
        const r = contrast(ink, bg)
        if (r < worst) { worst = r; worstAt = `${name} on ${sn}` }
      }
    }
    assert.ok(worst >= 4.5, `③ ${leg} 全矩阵最差 = ${worst.toFixed(2)} (${worstAt}) >= 4.5`)
    console.log(`ok   ③ ${leg} 墨×底全矩阵最差 -> ${worst.toFixed(2)} (${worstAt})`)
    n++
  }
  // 真台中层灰前景下的同一矩阵：**只记录不断言**（诚实边界——main 现行 fg=平台 label
  // 本身在该档只有 4.24，本册不把比自己更严的口径当判据；数值留痕供后续收口）。
  let stageWorst = Infinity, stageAt = ''
  for (const name of INKS) {
    const ink = inkOn(name, LABEL_STAGE)
    for (const [k, v] of Object.entries(TINTS)) {
      const r = contrast(ink, tintOf(v, TINT_PCT[k], LIGHT_SURFACE))
      if (r < stageWorst) { stageWorst = r; stageAt = `${name} on ${k}` }
    }
  }
  console.log(`info ③ 真台中层灰档（非判据）最差 -> ${stageWorst.toFixed(2)} (${stageAt})`)
}

// ④ epic chip：真实 epicChipColor 公式 × 全 epic 色（含最浅黄/兜底灰）取最劣
{
  const s = epicChipColor()
  const pct = Number(s.match(/var\(--epic-c,.*\)\s*(\d+)%/)[1])
  const ink = inkOn('--dsw-derive-ink-strong', LABEL_LIGHT)
  assert.ok(pct <= 35, `④ epic hue share kept minority (${pct}%)`)
  let worst = Infinity
  for (const e of [...PROJECT_PALETTE, FALLBACK_COLOR, '#eac54f', '#cee76a']) {
    worst = Math.min(worst, contrastOnWhite(mixPct(hex(e), pct, ink)))
  }
  assert.ok(worst >= 4.5, `④ epic chip worst-case ${worst.toFixed(2)} >= 4.5 (formula: ${s})`)
  console.log(`ok   ④ epic chip worst-case -> ${worst.toFixed(2)}`)
  n++
}

// ⑤ gen9 行级补收：fg 深墨（一切继承正文）、wb-card-title/wb-title 深墨、
// View Reason 深蓝墨在其浅蓝底（--dsw-derive-accent-bg 派生定义解析）上 ≥4.5
{
  const fg = contrastOnWhite(inkOn('--dsw-derive-fg', LABEL_LIGHT))
  assert.ok(fg >= 4.5, `⑤ --dsw-derive-fg on white = ${fg.toFixed(2)} >= 4.5`)
  const inkStrong = contrastOnWhite(inkOn('--dsw-derive-ink-strong', LABEL_LIGHT))
  assert.ok(inkStrong >= 4.5, `⑤ ink-strong on white = ${inkStrong.toFixed(2)} >= 4.5`)
  console.log(`ok   ⑤ fg=${fg.toFixed(2)} ink-strong=${inkStrong.toFixed(2)}`)
  n++
  const bgDef = tokenDef('--dsw-derive-accent-bg') // mix(accent-bg 基色 12%, bg)
  const baseHex = bgDef.match(/#([0-9a-fA-F]{6})/)
  const bgBase = baseHex ? hex('#' + baseHex[1]) : hex('#ddf4ff')
  const bg = bgDef.includes('color-mix') ? mixPct(bgBase, 12, hex('#ffffff')) : bgBase
  const inkBlue = inkOn('--dsw-derive-ink-blue', LABEL_LIGHT)
  const ratioBlue = contrast(inkBlue, bg)
  assert.ok(ratioBlue >= 4.5, `⑤ View Reason ink-blue on accent-bg = ${ratioBlue.toFixed(2)} >= 4.5`)
  console.log(`ok   ⑤ ink-blue on accent-bg -> ${ratioBlue.toFixed(2)}`)
  n++
}

console.log(`done ${n}`)
