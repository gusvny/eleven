// sc_hex_clean.mjs — t260905-08 场景②：工单台写死色清零断言（宿主令 260906 22:1X 裁定②）。
//
// intent（裁定②原文「#fff8c5/#ffebe9 等 hex 现场清零（grep 断言）」的机械化）：
//   server/plugins/workbench/src/client/ 全目录（.ts/.tsx/.css）不得出现「样式消费位」的
//   裸 hex——写死色全部退役，颜色一律经 token 声明位（自定义属性定义值 / var() fallback）
//   供出，深浅两档由平台令牌翻转。allowlist 三类零特例（gen2 方案 C1-b：派生基色统一
//   var() 包裹后全部落第三类）：
//     A. 数据性调色板：EPIC_PALETTE 10 档＋EPIC_FALLBACK_COLOR（ticket-list-model.ts，
//        确定性哈希色，17 号 T6/walkthrough 断言守着）——按「值级」豁免：从该文件解析出
//        色值集合，任何文件命中集合内的值放行；
//     B. echarts 数据系列色：metrics-charts.ts 整文件（数据可视化编码色，非文本对比度
//        语义，WCAG 1.4.3 不适用；宿主若裁定连数据色也主题化，另开独立票）；
//     C. token 声明位：hex 位于自定义属性定义值（--name: #hex 形式）或 var(...) 内
//        （fallback 位；行级判定，var() 跨行写法不在保证面，头注即契约）。
//   非颜色「#」上下文（id 选择器/锚点）由 hex 语法（#RRGGBB[#AA] / #RGB[#A]，后随边界）
//   天然排除；若未来出现全 hex 字符的 id 误伤，逐项登记理由而非放宽断言。
//
// 执行契约：零外部依赖、零浏览器，CI 恒真跑（无 env_fail 路径）；实现落地前红属预期
//   （TDD 信号：存量 ~351 处裸 hex），arbitrate/merge 期必须绿；stdout 末行 SUMMARY。
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const REPO = new URL('../..', import.meta.url).pathname;
const CLIENT = join(REPO, 'server/plugins/workbench/src/client');
const EXT = /\.tsx?$|\.css$/;

// allowlist A：值级解析 ticket-list-model.ts 的 EPIC_PALETTE 与 EPIC_FALLBACK_COLOR
const modelSrc = readFileSync(join(CLIENT, 'ticket-list-model.ts'), 'utf8');
const paletteValues = new Set();
const arrM = /EPIC_PALETTE[^=]*=\s*\[([^\]]*)\]/.exec(modelSrc);
if (arrM) for (const m of arrM[1].matchAll(/#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])/g)) paletteValues.add(m[0].toLowerCase());
const fbM = /EPIC_FALLBACK_COLOR\s*=\s*'(#[0-9a-fA-F]{3,8})'/.exec(modelSrc);
if (fbM) paletteValues.add(fbM[1].toLowerCase());
if (paletteValues.size < 11) {
  console.log(`FAIL hex-clean/allowlist-parse — 调色板解析异常（期望≥11 值，得 ${paletteValues.size}）：ticket-list-model.ts 结构漂移，先修本场景解析再断言`);
  console.log('SUMMARY pass=0 fail=1 env_fail=0 na=0');
  process.exit(1);
}

// allowlist B：echarts 数据编码色（整文件豁免，理由见头注）
const FILE_ALLOW = new Set(['metrics-charts.ts']);

const inTokenPosition = (line, idx) => {
  // 自定义属性定义值：hex 前最近的声明边界（; { 行首）之后是 --name: 形式 → 位于定义值内
  const start = Math.max(line.lastIndexOf(';', idx - 1), line.lastIndexOf('{', idx - 1)) + 1;
  if (/--[a-zA-Z0-9-]+\s*:/.test(line.slice(start, idx))) return true;
  // var() fallback 位：向左找最近未配对 '('，其前是 var
  let depth = 0;
  for (let i = idx - 1; i >= 0; i--) {
    const ch = line[i];
    if (ch === ')') depth += 1;
    else if (ch === '(') {
      if (depth > 0) { depth -= 1; continue; }
      return line.slice(Math.max(0, i - 3), i).toLowerCase() === 'var';
    } else if (ch === ';' || ch === '{' || ch === '}') return false;
  }
  return false;
};

const violations = [];
let scanned = 0;
const walk = (dir, rel) => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const relP = rel ? `${rel}/${name}` : name;
    if (statSync(p).isDirectory()) { walk(p, relP); continue; }
    if (!EXT.test(name)) continue;
    scanned += 1;
    if (FILE_ALLOW.has(name)) continue;
    const lines = readFileSync(p, 'utf8').split('\n');
    lines.forEach((line, li) => {
      for (const m of line.matchAll(/#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])/g)) {
        const v = m[0].toLowerCase();
        if (paletteValues.has(v)) continue;                       // allowlist A（值级）
        if (inTokenPosition(line, m.index)) continue;             // allowlist C（token 声明位）
        violations.push(`server/plugins/workbench/src/client/${relP}:${li + 1} ${v}  ${line.trim().slice(0, 90)}`);
      }
    });
  }
};
walk(CLIENT, '');

const pass = ['hex-clean/allowlist-parse', 'hex-clean/scan-breadth'];
console.log(`[PASS] hex-clean/allowlist-parse — EPIC_PALETTE 值级豁免 ${paletteValues.size} 值解析正常`);
console.log(`[PASS] hex-clean/scan-breadth — 扫描 ${scanned} 个源文件（client 全目录 .ts/.tsx/.css；豁免文件=${[...FILE_ALLOW].join(',')}）`);
if (violations.length > 0) {
  console.log(`[FAIL] hex-clean/no-raw-hex — 样式消费位裸 hex 残留 ${violations.length} 处（写死色退役未完成，宿主裁定②）：`);
  // 每文件聚合计数先行（t260907-03：明细有 slice(0,40) 显示截断，曾把 44 处的分布
  // 看成 40 处误导归因——聚合行永远全量，截断只发生在明细层）
  const byFile = {};
  for (const v of violations) {
    const f = v.replace(/^server\/dsh\/workbench\/src\/client\//, '').split(':')[0];
    byFile[f] = (byFile[f] || 0) + 1;
  }
  for (const [f, n] of Object.entries(byFile).sort((a, b) => b[1] - a[1])) console.log(`  聚合 ${f} = ${n} 处`);
  for (const v of violations.slice(0, 40)) console.log('  ' + v);
  if (violations.length > 40) console.log(`  …其余 ${violations.length - 40} 处略（分布以聚合行为准）`);
  console.log('SUMMARY pass=2 fail=1 env_fail=0 na=0');
  process.exit(1);
}
console.log('[PASS] hex-clean/no-raw-hex — 样式消费位零裸 hex（token 声明位/数据调色板除外）');
console.log('SUMMARY pass=3 fail=0 env_fail=0 na=0');
