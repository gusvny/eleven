/**
 * smoke/project-color.mjs — smoke for the project color pure functions (t260903-07 ticket 2).
 *
 * Run: node smoke/project-color.mjs (node >= 22.18 native type-stripping).
 *
 * Covers (plan v3 R3 three decidable items + the malformed-input discipline):
 *   a. Same key is deterministic: any number of calls on the same key always return the same
 *      value; no state drift across calls.
 *   b. Palette colors are pairwise distinguishable: dedup + hue-ring distance >= 20 degrees
 *      (the revised criterion and its reason are in the project-color.ts header) + a readable
 *      luminance band for dark backgrounds.
 *   c. Malformed input: ''/null/undefined/number/object/overlong/control chars ->
 *      FALLBACK_COLOR, no throw.
 *   d. projectTagCssRules: base rules present, one coloring rule per project, keys deduped,
 *      keys containing `"` or `\` are blocked (selector-injection guard), the key value
 *      appears faithfully in both the selector and the content source (attr reference).
 */

import { PROJECT_PALETTE, FALLBACK_COLOR, projectColor, projectTagCssRules, fnv1a, isProjectKeyLike } from '../src/shared/project-color.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ------------------------------------------------ a. same-key determinism */

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
  // Known FNV-1a+murmur3 final-mix vectors (post-F2-fix criterion: pure FNV ''=0x811c9dc5/'a'=0xe40c292c
  // run through the final mix; the vectors lock the hash against accidental changes)
  ok(fnv1a('') === 0xab3e7c0b, 'fnv1a("") 已知向量（终混后）')
  ok(fnv1a('a') === 0x1a80b1b3, 'fnv1a("a") 已知向量（终混后）')
  // Distribution: 10 synthetic keys hit >= 5 distinct colors (lower bound on uniformity, not a strict demand)
  const spread = new Set(Array.from({ length: 40 }, (_, i) => projectColor(`proj-${i}`)))
  ok(spread.size >= 5, `跨 key 分布命中 ≥5 色（got ${spread.size}）`)
}

/* ------------------------------------------------ b. pairwise-distinguishable palette */

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

/* ------------------------------------------------ c'. real registry keys land in distinct slots (F2 regression net) */

section("c' 真实注册表键取色两两不同（F2 回归断言，验收走查 gen0）")
{
  // The pair the user explicitly asked to distinguish (original words in the ticket body)
  // + the current real registry (~/.sandbar/projects; projects.yaml has left the repo, only
  // the suyou legacy entry remains). With pure FNV, suyou/sandbar land in the same slot
  // (both %10===2, see the F2 walkthrough report); after the murmur3 final mix they must
  // land in different slots. If a newly registered project collides, this section goes red
  // = go back to the developer to tune the mix/expand the palette; do not delete assertions.
  const realKeys = ['suyou', 'sandbar']
  const slots = realKeys.map(k => fnv1a(k) % PROJECT_PALETTE.length)
  ok(new Set(slots).size === realKeys.length, `真实注册表键槽位两两不同（got ${slots.join(',')}）`)
  ok(projectColor('suyou') !== projectColor('sandbar'), 'suyou/sandbar 颜色不同（用户点名对）')
  // The distribution lower-bound assertion stays: synthetic key collisions remain allowed (a stated probability), real keys are not.
}

/* ------------------------------------------------ c. malformed input */

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
  // In-range legal values
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
