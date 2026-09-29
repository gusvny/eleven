/**
 * contrast-palette.mjs —— t260929-22 gen5 对比度红的源级守卫（t260905-08/t260907-08
 * 集测场景实测红 4.18/4.24/2.62/2.64 < 4.5 的 UT 锁）：
 * 本项目 owns 的四个文字角色在白底上的 WCAG 对比度必须 ≥4.5，且按**真实取色路径**
 * 计算（projectColor 十色板全枚举取最劣、epic 色取色板+最浅黄夹具），不锚个别 hex——
 * 将来调色板或混色比例再变，这里重算即刻红。
 *
 * 白底场景 = 集测实测形态（t260905-08-wb-contrast-guard 的断言面）。
 */
import assert from 'node:assert/strict'
import { PROJECT_PALETTE, FALLBACK_COLOR } from '../src/shared/project-color.ts'
import { epicChipColor } from '../src/client/theme.ts'

let n = 0

/** WCAG 2.x 相对亮度 + 对比度（vs 白底）。 */
function luminance([r, g, b]) {
  const f = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
function contrastOnWhite(rgb) {
  const l = luminance(rgb)
  return (1.0 + 0.05) / (l + 0.05)
}
function hex(s) {
  const m = s.trim().match(/^#([0-9a-fA-F]{6})$/)
  assert.ok(m, `hex parse: ${s}`)
  const v = m[1]
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255)
}
/** CSS color-mix(in srgb, a p%, b) 的直角坐标近似（srgb 空间线性插值，与浏览器一致）。 */
function mixPct(a, p, b) {
  const t = p / 100
  return a.map((c, i) => c * t + b[i] * (1 - t))
}
/** 从 theme.ts 的 epicChipColor() 输出解析 mix 结构并求值（epic-c pct% × 内层 label/dark mix）。 */
function evalEpicChip(epicHex) {
  const s = epicChipColor()
  const pct = Number(s.match(/var\(--epic-c,\s*#[0-9a-f]{6}\)\s*(\d+)%/)[1])
  const label = hex(s.match(/var\(--dsw-alias-label-primary,\s*(#[0-9a-f]{6})\)/)[1])
  const innerPct = Number(s.match(/var\(--dsw-alias-label-primary,\s*#[0-9a-f]{6}\)\s*(\d+)%/)[1])
  const dark = hex('#' + s.match(/#([0-9a-f]{6})\)\)$/)[1])
  const innerMix = mixPct(label, innerPct, dark)
  return mixPct(hex(epicHex), pct, innerMix)
}

/** 「More/new」系：项目色 pct% × 近黑（project-session-row.tsx 的 psess-new/active 形状）。 */
function evalPsessTint(projectHex) {
  // 与 CSS 同式：color-mix(in srgb, var(--wb-psess-color,…,fallback) 25%, #1f2328)
  const pct = 25
  return mixPct(hex(projectHex), pct, hex('#1f2328'))
}

const NEED = 4.5

// ① 行卡 waiting 态：固定深棕
{
  const c = contrastOnWhite(hex('#7d4e00'))
  assert.ok(c >= NEED, `① wb-card-state waiting #7d4e00 on white = ${c.toFixed(2)} >= 4.5`)
  console.log(`ok   ① waiting #7d4e00 -> ${c.toFixed(2)}`)
  n++
}

// ② 进展行：#57606a
{
  const c = contrastOnWhite(hex('#57606a'))
  assert.ok(c >= NEED, `② wb-card-progress #57606a on white = ${c.toFixed(2)} >= 4.5`)
  console.log(`ok   ② progress #57606a -> ${c.toFixed(2)}`)
  n++
}

// ③ epic chip：theme.ts mix × 全 epic 色板（含最浅黄 #eac54f 夹具）取最劣
{
  const s = epicChipColor()
  const sampleEpics = [...PROJECT_PALETTE, FALLBACK_COLOR, '#eac54f', '#cee76a']
  let worst = Infinity
  for (const e of sampleEpics) worst = Math.min(worst, contrastOnWhite(evalEpicChip(e)))
  assert.ok(worst >= NEED, `③ epic chip worst-case ${worst.toFixed(2)} >= 4.5 (formula: ${s})`)
  console.log(`ok   ③ epic chip worst-case -> ${worst.toFixed(2)} (formula: ${s})`)
  n++
}

// ④ psess「＋ New session」/激活 tab：projectColor 十色板全枚举 + 兜底灰取最劣
{
  const sample = [...PROJECT_PALETTE, FALLBACK_COLOR]
  let worst = Infinity
  for (const p of sample) worst = Math.min(worst, contrastOnWhite(evalPsessTint(p)))
  assert.ok(worst >= NEED, `④ psess text worst-case ${worst.toFixed(2)} >= 4.5`)
  console.log(`ok   ④ psess text worst-case -> ${worst.toFixed(2)}`)
  n++
}

console.log(`done ${n}`)
