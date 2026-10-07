// theme-tokens.mjs — t260905-08 主题令牌 UT：fallback 三态纪律＋派生定义语法守卫。
// 消费外部令牌（平台 --dsw-alias-*）的缺失态必须恒有 fallback（review 条件1/R2）；
// 任何 var() 引用不带 fallback = 本 UT 红。
import { readFileSync } from 'node:fs';
import assert from 'node:assert';
import { ALIAS, TOKEN, DERIVE_TOKENS_CSS, epicChipColor, epicChipMuted } from '../src/client/theme.ts';
// TS 直接导入：node ≥22 type-stripping（同 tests/t260904-17-ticket-list-model.mjs 先例）

const STR = (s) => String(s);
let pass = 0, fail = 0;
const ok = (name, fn) => { try { fn(); pass++; } catch (e) { fail++; console.log(`FAIL ${name}: ${e.message}`); } };

// 合法 fallback 形态两式（t260907-08 钉死）：
//   扁平式 var(--x, #hex) —— 常规令牌；
//   平台契约式 var(--a, var(--b, #hex)) —— 仅限 bgPrimary 双兜底（t260907-03 评审门
//   正名的旧平台 0.1.1-rc.2 兼容：宿主平台无 bg-primary 名时落 bg-base；UT 此前只认
//   扁平式，双兜底入账时漏更=存量红，本票随四象限验收一并修正）。嵌套只认这一名，
//   不放开任意嵌套（防无 fallback 的 var 链混入）。
const VAR_RE = /^var\(--[a-z0-9-]+,\s*#[0-9a-fA-F]{3,8}\)$/;
const VAR_NESTED_RE = /^var\(--[a-z0-9-]+,\s*var\(--[a-z0-9-]+,\s*#[0-9a-fA-F]{3,8}\)\)$/;
const hasFallback = (v) => VAR_RE.test(STR(v)) || VAR_NESTED_RE.test(STR(v));

ok('ALIAS 每个 var() 带 fallback', () => {
  for (const [k, v] of Object.entries(ALIAS)) assert.ok(hasFallback(v), `${k}=${v}`);
});
ok('TOKEN 每个 var() 带 fallback', () => {
  for (const [k, v] of Object.entries(TOKEN)) assert.match(STR(v), VAR_RE, `${k}=${v}`);
});
ok('epicChipColor 带 --epic-c 与强墨令牌缝（t260929-22 gen8：文字色不再混平台 label）', () => {
  const s = epicChipColor();
  assert.ok(s.includes('var(--epic-c,'), s);
  assert.ok(s.includes('--dsw-derive-ink-strong'), s);
});
ok('epicChipMuted 带 fallback', () => assert.match(epicChipMuted(), VAR_RE));

// ---- DERIVE_TOKENS_CSS 结构守卫 ----
const defs = DERIVE_TOKENS_CSS.replace(/\/\*[\s\S]*?\*\//g, '').split(';').map(s => s.trim()).filter(s => s.startsWith('--dsw-derive-'));
ok('派生定义逐条语法：名字=值；值内每个 var( 带逗号 fallback；color-mix 只混 alias/hex', () => {
  assert.ok(defs.length >= 24, `定义数 ${defs.length}`);
  for (const d of defs) {
    const eq = d.indexOf(':');
    const name = d.slice(0, eq), val = d.slice(eq + 1);
    assert.ok(/^--dsw-derive-[a-z0-9-]+$/.test(name), name);
    // 每个 var( 跨度内必须有逗号（fallback 在场）
    for (const m of val.matchAll(/var\(/g)) {
      let i = m.index + m[0].length, depth = 1, span = '';
      while (i < val.length && depth) {
        const ch = val[i];
        if (ch === '(') depth++; if (ch === ')') depth--;
        if (depth) span += ch; i++;
      }
      assert.ok(span.includes(','), `${name}: var() 无 fallback -> var(${span})`);
    }
    // color-mix 派生必须消费 alias（保证随平台翻转），固定暗面板除外
    if (val.includes('color-mix')) {
      assert.ok(val.includes('--dsw-alias-'), `${name}: color-mix 未消费平台 alias`);
      assert.ok(/#\s*[0-9a-fA-F]{3,8}/.test(val), `${name}: color-mix 缺基色 hex`);
    }
  }
});
ok('固定暗面板恰 12 个且为裸 hex（自备深底不随平台翻转；12=核心 9＋t260907-08 面位扩展 3）', () => {
  // 名字精确点名：家族成员是登记制（theme.ts 头注），UT 同步钉名防顺手混入非成对面。
  // t261008-07: the sheet declares the same block at :root AND body[data-ds-dark-theme]
  // (dark-scope re-declaration so color-mix recomputes against the dark aliases) —
  // dedupe by unique declaration; the contract is 12 DISTINCT dark tokens.
  const EXPECT = ['bg', 'fg', 'muted', 'green', 'red', 'amber', 'accent', 'warn-bg', 'warn-fg',
    'border', 'surface', 'surface-2'];
  const dark = [...new Set(defs.filter(d => d.startsWith('--dsw-derive-dark-')))];
  const names = dark.map(d => d.slice('--dsw-derive-dark-'.length).split(':')[0]).sort();
  assert.deepStrictEqual(names, [...EXPECT].sort(), dark.join(' | '));
  for (const d of dark) assert.match(d, /^--dsw-derive-dark-[a-z0-9-]+:#[0-9a-f]{6}$/);
});
ok('DERIVE_TOKENS_CSS 与 TOKEN 名字对齐（TSX 行内引用的令牌都在 CSS 定义）', () => {
  for (const v of Object.values(TOKEN)) {
    const name = STR(v).match(/var\((--[a-z0-9-]+),/)?.[1];
    assert.ok(DERIVE_TOKENS_CSS.includes(`${name}:`), `${name} 未在 :root 定义`);
  }
});

console.log(`SUMMARY pass=${pass} fail=${fail}`);
process.exit(fail === 0 ? 0 : 1);
