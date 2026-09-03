/**
 * smoke/project-color.mjs —— t260903-07 工单② 项目色纯函数冒烟。
 *
 * 直跑：node smoke/project-color.mjs（node ≥22.18 原生 type-stripping）。
 *
 * 覆盖（方案 v3 R3 可判定三条 + 畸形输入纪律）：
 *   a. 同 key 确定性：同 key 任意次调用恒同值；跨调用无状态漂移。
 *   b. 色板两两可辨：去重 + hue 环距 ≥20°（口径修订与理由见 project-color.ts 头注）
 *      + 亮度可读带（暗底可读）。
 *   c. 畸形输入：''/null/undefined/数字/对象/超长/控制字符 → FALLBACK_COLOR，不 throw。
 *   d. projectTagCssRules：基础规则在、每项目一条着色规则、key 去重、含 `"`/`\` 的
 *      key 被拦（防选择器注入）、key 值忠实出现在选择器与 content 来源（attr 引用）。
 */

import { PROJECT_PALETTE, FALLBACK_COLOR, projectColor, projectTagCssRules, fnv1a, isProjectKeyLike } from '../src/shared/project-color.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ------------------------------------------------ a 同 key 确定性 */

section('a 同 key 确定性')
{
  const keys = ['suyou', 'sandbar', 'a', 'project-with-dashes', '中文项目']
  let deterministic = true
  for (const k of keys) {
    const first = projectColor(k)
    for (let i = 0; i < 100; i++) {
      if (projectColor(k) !== first) { deterministic = false; break }
    }
  }
  ok(deterministic, '同 key 100 次取色一致')
  // FNV-1a+murmur3 终混已知向量（F2 修复后口径：纯 FNV ''=0x811c9dc5/'a'=0xe40c292c
  // 经终混变换；向量锁定防误改哈希）
  ok(fnv1a('') === 0xab3e7c0b, 'fnv1a("") 已知向量（终混后）')
  ok(fnv1a('a') === 0x1a80b1b3, 'fnv1a("a") 已知向量（终混后）')
  // 分布：10 个合成 key 命中 ≥5 种色（均匀性下限，不苛求）
  const spread = new Set(Array.from({ length: 40 }, (_, i) => projectColor(`proj-${i}`)))
  ok(spread.size >= 5, `跨 key 分布命中 ≥5 色（got ${spread.size}）`)
}

/* ------------------------------------------------ b 色板两两可辨 */

section('b 色板两两可辨（hue 环距 + 亮度带）')
{
  ok(PROJECT_PALETTE.length === new Set(PROJECT_PALETTE).size, '色板去重（v1 重复色笔误不复犯）')
  const hexToHsl = (hex) => {
    const v = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    const max = Math.max(...v), min = Math.min(...v)
    const l = (max + min) / 2
    let h = 0, s = 0
    if (max !== min) {
      const d = max - min
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
      if (max === v[0]) h = ((v[1] - v[2]) / d + (v[1] < v[2] ? 6 : 0))
      else if (max === v[1]) h = (v[2] - v[0]) / d + 2
      else h = (v[0] - v[1]) / d + 4
      h *= 60
    }
    return { h, s, l }
  }
  const hues = PROJECT_PALETTE.map(hexToHsl)
  let minHueGap = 360
  for (let i = 0; i < hues.length; i++) {
    for (let j = i + 1; j < hues.length; j++) {
      const d = Math.abs(hues[i].h - hues[j].h)
      const ring = Math.min(d, 360 - d)
      if (ring < minHueGap) minHueGap = ring
    }
  }
  ok(minHueGap >= 20, `任意两色 hue 环距 ≥20°（got ${minHueGap.toFixed(1)}°）`)
  ok(hues.every(x => x.l > 0.35 && x.l < 0.85), '亮度带：全部在暗底可读区间 (0.35,0.85)')
  ok(hues.every(x => x.s > 0.3), '饱和度带：全部 >0.3（低饱和灰不进色板）')
}

/* ------------------------------------------------ c' 真实注册表键两两不同槽（F2 回归网） */

section("c' 真实注册表键取色两两不同（F2 回归断言，验收走查 gen0）")
{
  // 用户点名区分的第一对项目（工单正文②原话）+ 现注册表真源（~/.sandbar/projects，
  // projects.yaml 已出仓只剩 suyou 存量）。纯 FNV 时 suyou/sandbar 同槽（均 %10===2，
  // 实锤见走查报告 F2）；murmur3 终混后必须错槽。新增注册项目撞槽时本节红=回到
  // developer 调混合/扩色板，不得删断言了事。
  const realKeys = ['suyou', 'sandbar']
  const slots = realKeys.map(k => fnv1a(k) % PROJECT_PALETTE.length)
  ok(new Set(slots).size === realKeys.length, `真实注册表键槽位两两不同（got ${slots.join(',')}）`)
  ok(projectColor('suyou') !== projectColor('sandbar'), 'suyou/sandbar 颜色不同（用户点名对）')
  // 分布下限断言保留：合成 key 撞色仍允许（概率声明），真实键不允许。
}

/* ------------------------------------------------ c 畸形输入 */

section('c 畸形输入不炸')
{
  const bads = ['', null, undefined, 42, {}, ['suyou'], 'x'.repeat(65), 'bad\u0000key', '\u0007']
  let stable = true
  for (const b of bads) {
    try {
      if (projectColor(b) !== FALLBACK_COLOR) stable = false
      if (isProjectKeyLike(b) !== false) stable = false
    } catch { stable = false }
  }
  ok(stable, '全部畸形输入 → FALLBACK_COLOR / 非 key，不 throw')
  // 边界内合法值
  ok(isProjectKeyLike('a'.repeat(64)), '64 字符 key 合法（上限内）')
  ok(projectColor('suyou') !== FALLBACK_COLOR, '合法 key 进色板（非兜底色）')
}

/* ------------------------------------------------ d projectTagCssRules */

section('d projectTagCssRules 契约')
{
  const css = projectTagCssRules(['suyou', 'sandbar', 'suyou'])
  ok(css.includes('[data-wb-projtag]::before'), '含基础规则（::before + attr 出文本）')
  ok((css.match(/\[data-wb-projtag="/g) ?? []).length === 2, `key 去重：3 入 2 规则（got ${(css.match(/\[data-wb-projtag="/g) ?? []).length}）`)
  ok(css.includes('content:attr(data-wb-projtag)'), 'chip 文本来自 attr()（零 childList 机制）')
  const c1 = projectColor('suyou')
  ok(css.includes(`[data-wb-projtag="suyou"]::before{color:${c1}`), '着色规则与 projectColor 同源')
  const evil = projectTagCssRules(['a"b', 'c\\d'])
  ok(!evil.includes('"a"b"') && !evil.includes('"c\\d"'), '含引号/反斜杠 key 被拦（防选择器注入）')
  ok(projectTagCssRules([null, 42, '']).split('\n').length === 1, '全畸形输入 → 仅基础规则')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
