// check_contrast_offline.mjs — t260905-08 对比度看守的数值核心（离线腿）。
//
// 从 theme.ts 的 DERIVE_TOKENS_CSS 解析派生令牌定义，按平台两档 alias 代表值
// （浅档/深档）解析 var 链与 color-mix（srgb 伽马域混合，同 CSS 语义），
// 逐关键前/背景对实算 WCAG 相对亮度比值，双档断言 ≥4.5（AA 正文）。
// 另输出浅档解析值 vs fallback 原值的逐项 diff（R7 浅色回归数值化口径）。
//
// 边界（如实声明）：本腿验证**令牌公式**的两档可读性；DOM 级逐表面实算
// （挂载路径/继承链/hover）由 sc_wb_contrast_guard.mjs 浏览器腿承担
// （KI-036：缺 playwright=env_fail 有声红，「闸内无 SKIP」，arbitrate/merge 期必须真跑）。
// 代表值为模拟值（平台定义侧不在本仓）：深档代表值若与平台真值偏差大，
// 本腿结论需随真值复跑（merge 关卡观测点）。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const themeSrc = readFileSync(join(here, '../../server/dsh/workbench/src/client/theme.ts'), 'utf8');
const m = themeSrc.match(/export const DERIVE_TOKENS_CSS = `([\s\S]*?)`/);
if (!m) { console.log('SUMMARY pass=0 fail=1 (DERIVE_TOKENS_CSS 解析失败)'); process.exit(1); }

// ---- 解析定义（去注释；--name:value;）----
const defs = {};
for (const dm of m[1].replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(--dsw-derive-[a-z0-9-]+)\s*:\s*([^;]+);?/g)) {
  defs[dm[1]] = dm[2].trim();
}

// ---- 平台两档 alias 代表值（模拟；来源与风险见头注）----
const LIGHT = { '--dsw-alias-bg-primary': '#ffffff', '--dsw-alias-border-l': '#d0d7de', '--dsw-alias-brand-primary': '#0969da', '--dsw-alias-label-primary': '#1f2328', '--dsw-alias-label-secondary': '#57606a' };
const DARK = { '--dsw-alias-bg-primary': '#16181d', '--dsw-alias-border-l': '#30363d', '--dsw-alias-brand-primary': '#4493f8', '--dsw-alias-label-primary': '#e6e6e9', '--dsw-alias-label-secondary': '#9ea2ad' };
// 旧平台档（t260907-03 腿①）：0.1.1-rc.2 无 bg-primary 名（'initial'=knockout 哨兵，
// 解析器视同「名不存在」走下一级 fallback）、只有 bg-base=可辨识代表值 #f5f8fa（近白平台底，选值约束见 lib_t260905_08 头注）。
const LEGACY = { '--dsw-alias-bg-primary': 'initial', '--dsw-alias-bg-base': '#f5f8fa', '--dsw-alias-border-l': '#d0d7de', '--dsw-alias-brand-primary': '#0969da', '--dsw-alias-label-primary': '#1f2328', '--dsw-alias-label-secondary': '#57606a' };

const HEX = (s) => /^#[0-9a-fA-F]{6}$/.test(s) || /^#[0-9a-fA-F]{3}$/.test(s);
const norm = (h) => { h = h.slice(1); if (h.length === 3) h = [...h].map(c => c + c).join(''); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };

// 解析一个值（递归 var/color-mix）；memo 按档缓存
function resolve(value, pal, memo) {
  value = value.trim();
  if (HEX(value)) return norm(value);
  const vm = value.match(/^var\(\s*(--[a-z0-9-]+)\s*,\s*([\s\S]+)\)$/);
  // 'initial' 哨兵=该名 knockout（guaranteed-invalid），同「名不存在」→ 走 fallback 链
  if (vm) return pal[vm[1]] !== undefined && pal[vm[1]] !== 'initial' ? norm(pal[vm[1]]) : resolve(vm[2], pal, memo);
  if (value.startsWith('--')) { // 裸令牌引用（定义间引用）
    if (memo[value] === undefined) memo[value] = resolve(defs[value], pal, memo);
    return memo[value];
  }
  const mm = value.match(/^color-mix\(in srgb,\s*([\s\S]+?)\s+(\d+)%,\s*([\s\S]+)\)$/);
  if (mm) {
    const a = resolve(mm[1], pal, memo), pct = Number(mm[2]) / 100, b = resolve(mm[3], pal, memo);
    return [0, 1, 2].map(i => Math.round(a[i] * pct + b[i] * (1 - pct)));
  }
  throw new Error(`不可解析的令牌值: ${value}`);
}

// WCAG 相对亮度与对比度
const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (fg, bg) => { const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x); return (a + 0.05) / (b + 0.05); };
const fmt = (rgb) => '#' + rgb.map(v => v.toString(16).padStart(2, '0')).join('');

let pass = 0, fail = 0; const report = [];
function check(name, fgVal, bgVal) {
  const rows = [];
  for (const [tier, pal] of [['light', LIGHT], ['dark', DARK]]) {
    const memo = {};
    const memo1 = {}, memo2 = {};
    const fg = resolve(fgVal.startsWith('--') ? fgVal : defs['--dsw-derive-' + fgVal], pal, memo1);
    const bg = resolve(bgVal.startsWith('--') ? bgVal : defs['--dsw-derive-' + bgVal], pal, memo2);
    const r = ratio(fg, bg);
    const okTier = r >= 4.5;
    rows.push(`${tier}=${r.toFixed(2)}${okTier ? '' : ' ❌'} (${fmt(fg)} on ${fmt(bg)})`);
    if (!okTier) fail++; else pass++;
  }
  report.push(`  ${name}: ${rows.join('  ')}`);
}

// ---- 关键前/背景对（全台文字面归并到这些角色组合）----
check('正文 fg × 画布', 'fg', 'canvas');
check('正文 fg × 次级表面', 'fg', 'surface');
check('正文 fg × 次级表面2', 'fg', 'surface-2');
check('次级 muted × 画布', 'muted', 'canvas');
check('次级 muted × 状态底(warn)', 'muted', 'warn-bg');
check('次级 muted × 状态底(danger)', 'muted', 'danger-bg');
check('强调 accent × 画布', 'accent', 'canvas');
check('强调 accent × 信息底', 'accent', 'accent-bg');
check('强调深 accent-deep × 画布', 'accent-deep', 'canvas');
check('危险 danger × 画布', 'danger', 'canvas');
check('危险 danger × 危险底', 'danger', 'danger-bg');
check('成功 success × 画布', 'success', 'canvas');
check('成功 success × 成功底', 'success', 'success-bg');
check('成功深 success-deep × 成功底', 'success-deep', 'success-bg');
check('警告 warn × 画布', 'warn', 'canvas');
check('警告 warn × 警告底', 'warn', 'warn-bg');
check('警告深 warn-deep × 警告底', 'warn-deep', 'warn-bg');
check('警告深 warn-deep × 画布', 'warn-deep', 'canvas');

// ---- 旧平台档（t260907-03 腿①，LEGACY）：验「兜底链接得住旧平台 bg-base」----
// ① 精确等值（核心，对应浏览器腿 contrast/legacy-canvas-eq-bg-base）：
//    --dsw-derive-canvas（纯 var 链）在 bg-primary knockout 下必须精确解析到
//    bg-base 代表值 #f5f8fa——链被拆/名被删 → 落 #fff；值写错 → 别的色，都可辨。
{
  const memo = {};
  const got = fmt(resolve('--dsw-derive-canvas', LEGACY, memo));
  const ok = got === '#f5f8fa';
  report.push(`  legacy canvas 精确等值: got=${got} 期望=#f5f8fa${ok ? '' : ' ❌（兜底链未接住旧平台令牌名）'}`);
  if (ok) pass++; else fail++;
}
// ② 画布锚定的关键文字对在 legacy 档仍须 AA（knockout 后 canvas/surface 系全部
//    偏移到 bg-base 代表值，正文/次级/强调对的可读性不可因换档塌陷）；
//    状态底/accent 混色对的账本由 light/dark 腿全量承担，legacy 只加链关键面。
for (const [n, f, b] of [['legacy 正文 fg × 画布', 'fg', 'canvas'], ['legacy 次级 muted × 画布', 'muted', 'canvas'],
  ['legacy 正文 fg × 次级表面', 'fg', 'surface'], ['legacy 正文 fg × 次级表面2', 'fg', 'surface-2'],
  ['legacy 强调 accent × 画布', 'accent', 'canvas']]) {
  const memo1 = {}, memo2 = {};
  const fg = resolve(defs['--dsw-derive-' + f], LEGACY, memo1);
  const bg = resolve(defs['--dsw-derive-' + b], LEGACY, memo2);
  const r = ratio(fg, bg);
  const ok = r >= 4.5;
  report.push(`  ${n}: legacy=${r.toFixed(2)}${ok ? '' : ' ❌'} (${fmt(fg)} on ${fmt(bg)})`);
  if (ok) pass++; else fail++;
}

// epic chip：EPIC_PALETTE 全 10 档 × 兜底灰，chip 文字=45% epic 混平台前景（与 theme.ts epicChipColor 同源同步），两档断言
const modelSrc = readFileSync(join(here, '../../server/dsh/workbench/src/client/ticket-list-model.ts'), 'utf8');
const palMatch = modelSrc.match(/EPIC_PALETTE[^=]*=\s*\[([\s\S]*?)\]/);
const epicColors = [...palMatch[1].matchAll(/#[0-9a-fA-F]{6}/g)].map(x => x[0]);
epicColors.push('#9ca3af');
function chipFg(epic, pal) { // 与 theme.ts epicChipColor() 同式
  const base = norm(epic), fg = norm(pal['--dsw-alias-label-primary']);
  return [0, 1, 2].map(i => Math.round(base[i] * 0.45 + fg[i] * 0.55));
}
for (const ec of epicColors) {
  const rows = [];
  for (const [tier, pal] of [['light', LIGHT], ['dark', DARK]]) {
    const bg = resolve('--dsw-derive-canvas', pal, {});
    const r = ratio(chipFg(ec, pal), bg);
    const okTier = r >= 4.5;
    rows.push(`${tier}=${r.toFixed(2)}${okTier ? '' : ' ❌'}`);
    if (!okTier) fail++; else pass++;
  }
  report.push(`  epic chip ${ec}: ${rows.join('  ')}`);
}

// 固定暗面板（自备深底，单档自洽即可）
for (const [fgv, bgv, nm] of [['dark-fg', 'dark-bg', '暗面板正文'], ['dark-muted', 'dark-bg', '暗面板次级'],
  ['dark-green', 'dark-bg', '暗面板绿'], ['dark-red', 'dark-bg', '暗面板红'],
  ['dark-amber', 'dark-bg', '暗面板琥珀'], ['dark-accent', 'dark-bg', '暗面板蓝'],
  ['dark-warn-fg', 'dark-warn-bg', '暗面板警告条']]) {
  const r = ratio(resolve(defs['--dsw-derive-' + fgv], LIGHT, {}), resolve(defs['--dsw-derive-' + bgv], LIGHT, {}));
  const okTier = r >= 4.5;
  report.push(`  ${nm}: fixed=${r.toFixed(2)}${okTier ? '' : ' ❌'}`);
  if (okTier) pass++; else fail++;
}

// R7：浅档解析值 vs fallback 原值 diff（数值对照，不设阈值——供人审差异表）
console.log('== 浅档解析值 vs 改造前原值（R7 diff） ==');
for (const [name, d] of Object.entries(defs)) {
  if (name.startsWith('--dsw-derive-dark-')) continue;
  const fb = d.match(/,?\s*(#[0-9a-fA-F]{3,6})\s*\)\s*$/)?.[1] ?? d.match(/^#[0-9a-fA-F]{6}$/)?.[0];
  if (!fb) continue;
  const light = resolve(name, LIGHT, {});
  const base = norm(fb);
  report.unshift(`  ${name}: 原=${fb} 浅档解析=${fmt(light)} (Δrgb=${light.map((v, i) => v - base[i]).join('/')})`);
}

console.log(report.join('\n'));
console.log(`SUMMARY pass=${pass} fail=${fail}`);
process.exit(fail === 0 ? 0 : 1);
