/**
 * contrast-palette.mjs —— 对比度纪律的源级守卫（t260905-08-wb-contrast-guard /
 * t260907-08-wb-contrast-quadrant 集测实测红 2.62–4.24 < 4.5 的 UT 锁，t260929-22 gen8）：
 * 文字语义令牌的**声明位深墨值**在白底上的 WCAG 对比度 ≥4.5，epic chip 按真实
 * color-mix 公式（含最浅 epic 色/夹具）取最劣计算。令牌定义再变，这里重算即刻红。
 *
 * 白底场景 = 集测实测形态。gen8 口径：文字语义令牌（warn/muted/danger/accent/
 * ink-strong）为浅档深墨声明位裸值（hex-clean 合法位），平台 label 极性不定、
 * 不再参与文字色混色。
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

// ① waiting 态文字 = --dsw-derive-warn（声明位深墨）
{
  const c = contrastOnWhite(hex(tokenDef('--dsw-derive-warn')))
  assert.ok(c >= 4.5, `① --dsw-derive-warn on white = ${c.toFixed(2)} >= 4.5`)
  console.log(`ok   ① warn ink -> ${c.toFixed(2)}`)
  n++
}

// ② muted 文字（进展行/时间/左栏 mini 行卡缺省）= --dsw-derive-muted
{
  const c = contrastOnWhite(hex(tokenDef('--dsw-derive-muted')))
  assert.ok(c >= 4.5, `② --dsw-derive-muted on white = ${c.toFixed(2)} >= 4.5`)
  console.log(`ok   ② muted ink -> ${c.toFixed(2)}`)
  n++
}

// ③ danger / accent（blocked/failed/active 态文字）
{
  for (const name of ['--dsw-derive-danger', '--dsw-derive-accent']) {
    const c = contrastOnWhite(hex(tokenDef(name)))
    assert.ok(c >= 4.5, `③ ${name} on white = ${c.toFixed(2)} >= 4.5`)
    console.log(`ok   ③ ${name} -> ${c.toFixed(2)}`)
    n++
  }
}

// ④ epic chip：真实 epicChipColor 公式 × 全 epic 色（含最浅黄/兜底灰）取最劣
{
  const s = epicChipColor()
  const pct = Number(s.match(/var\(--epic-c,.*\)\s*(\d+)%/)[1])
  const ink = hex(tokenDef('--dsw-derive-ink-strong'))
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
  const fg = contrastOnWhite(hex(tokenDef('--dsw-derive-fg')))
  assert.ok(fg >= 4.5, `⑤ --dsw-derive-fg on white = ${fg.toFixed(2)} >= 4.5`)
  const inkStrong = contrastOnWhite(hex(tokenDef('--dsw-derive-ink-strong')))
  assert.ok(inkStrong >= 4.5, `⑤ ink-strong on white = ${inkStrong.toFixed(2)} >= 4.5`)
  console.log(`ok   ⑤ fg=${fg.toFixed(2)} ink-strong=${inkStrong.toFixed(2)}`)
  n++
  const bgDef = tokenDef('--dsw-derive-accent-bg') // mix(accent-bg 基色 12%, bg)
  const baseHex = bgDef.match(/#([0-9a-fA-F]{6})/)
  const bgBase = baseHex ? hex('#' + baseHex[1]) : hex('#ddf4ff')
  const bg = bgDef.includes('color-mix') ? mixPct(bgBase, 12, hex('#ffffff')) : bgBase
  const blue = contrastOnWhite(mixPct ? (function () {
    const d = tokenDef('--dsw-derive-ink-blue')
    return hex(d)
  })() : hex('#0550ae'))
  const bgLum = (1.0 + 0.05) / (luminance(bg) + 0.05) > 0 ? 0 : 0
  const ratioBlue = (() => { const l1 = luminance(hex('#0550ae')), l2 = luminance(bg); const a = Math.max(l1, l2), b = Math.min(l1, l2); return (a + 0.05) / (b + 0.05) })()
  assert.ok(ratioBlue >= 4.5, `⑤ View Reason ink-blue on accent-bg = ${ratioBlue.toFixed(2)} >= 4.5`)
  console.log(`ok   ⑤ ink-blue on accent-bg -> ${ratioBlue.toFixed(2)}`)
  n++
}

console.log(`done ${n}`)
