#!/usr/bin/env node
/**
 * Baseline: sandbar ⑧ dsh 兼容区间契约守卫（t260903-08）。
 *
 * Intent (user-perceivable contract):
 *   契约 v1.7 ⑧节的区间声明与四条升版必查项是机器消费面——sandbar 安装器
 *   `upgrade`/`doctor` 探针集按它展示兼容区间、按必查项清单做升版复扫
 *   （消费关系载体：notes/debts/sandbar-m2-c-installer-handoff.md）。守卫断言：
 *   - ⑧节存在且区间口径为「已验证点列举制」（当前唯一点 0.1.1-rc.2），
 *     缺失或丢点 = 消费方展示空区间/假区间；⑧节内锚定走「节内切片」检查，
 *     变更记录行/其他节里的同词不充当掩护（acceptance 走查收紧，见 CHECKS
 *     的 scope 注释与 no-datapoint/no-failclosed 定向注入）；
 *   - 四条升版必查项（settings/resolve 层叠、headless runner 装配、home 布局
 *     与会话存储格式、headless SIGTERM 语义）逐条在场——任一缺失 = dsh 升版
 *     复扫静默漏项（touchpoints 汇总节转正的整条目的即失守）；
 *   - 版本自报口径的结构锚点（sandbar_version / 0.1.0 / temporal_engine_version
 *     原值保留）在场——锚点词表取自契约⑧-4 条文自身定义的关键词，同源
 *     （V4：结构锚点断言，非 prose 措辞断言，改写叙述不误红）；
 *   - 交接单的故障模式取舍清单覆盖 R1 全关键词（port/keepalive/pid/孤儿）且
 *     含 #5/#9 优先级条款（认领仅限真孤儿）与 3099 六词禁词表——交接单是
 *     sandbar 代码票硬输入，丢条款 = 代码票照搬丢半重演。
 *
 * 本场景为只读文档守卫（ro 池）：对受控文件只读，不注入、不改写。
 * 畸形态红测走 --selftest（V3：对 /tmp 临时副本注入六种畸形态，断言转红），
 * 不在受控契约文件上原地删节再恢复。
 */
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const CONTRACT = join(ROOT, 'docs', 'design', 'sandbar项目接入契约v1.md');
const HANDOFF = join(ROOT, 'notes', 'sandbar-m2-c-installer-handoff.md')  // 260904 回迁适配：sandbar 实际位置在 notes/ 根;

// —— ⑧节切片与规范化 ——
// scope='sect' 的断言只对⑧节切片做：节内丢锚即红，变更记录行或其他节的同词
// 不充当掩护（全文级词面检查曾被走查注入实验证实漏检：只删⑧-1 唯一点/⑧-4
// fail-closed 句/⑧-5 整段，全文断言全数不转红）。
// scope='doc' 的断言对全文做：跨节引用（V5 衔接句）与变更记录行本身。
function section8(c) {
  const m = c.match(/### ⑧ dsh 平台兼容区间与升版必查项[\s\S]*?(?=\n### )/);
  return m ? m[0] : '';
}
const norm = s => String(s).replace(/\s+/g, ' ');

// —— 断言词表（V4：与契约⑧条文自身关键词同源，非自由措辞） ——
const CHECKS = [
  ['⑧节存在', 'doc', c => c.includes('### ⑧ dsh 平台兼容区间与升版必查项')],
  ['区间声明面向 @deepseek-ai/dsh', 'sect', c => c.includes('@deepseek-ai/dsh')],
  ['已验证点列举制+唯一点在场', 'sect', c => c.includes('已验证点列举') && c.includes('0.1.1-rc.2')],
  ['扩点须探针绿', 'sect', c => c.includes('探针集全绿')],
  ['必查项1 settings/resolve 层叠', 'sect', c => c.includes('settings/resolve 层叠顺序')],
  ['必查项2 headless runner 装配与启动钩子', 'sect', c => c.includes('headless runner 装配与启动钩子')],
  ['必查项3 home 布局与会话存储格式', 'sect', c => c.includes('dsh home 布局与会话存储格式')],
  ['必查项4 headless SIGTERM 语义', 'sect', c => c.includes('headless SIGTERM 语义')],
  ['矩阵三轴（sandbar 版本 × dsh × 项目 schema）', 'sect', c => c.includes('sandbar 版本 × dsh 已验证点 × 项目 schema')],
  ['矩阵 append 制落点', 'sect', c => c.includes('compat-matrix.json')],
  ['版本自报键 sandbar_version', 'sect', c => c.includes('`sandbar_version`')],
  ['semver 起点 0.1.0', 'sect', c => c.includes('自 `0.1.0` 起')],
  ['历史 int 键原值保留不造映射', 'sect', c => c.includes('`temporal_engine_version`') && c.includes('原值保留') && c.includes('不造历史 semver 映射')],
  ['畸形 sandbar_version fail-closed', 'sect', c => c.includes('fail-closed')],
  ['升版执行序', 'sect', c => c.includes('升版执行序')],
  ['v1.6 两轴衔接句（V5：IDE 轴=sandbar+dsh 复合）', 'doc', c => norm(c).includes('IDE 版本轴 = sandbar 版本 + dsh 区间的复合')],
  ['变更记录含 v1.7 行', 'doc', c => /\|\s*v1\.7\s*\|\s*2026-09-03\s*\|/.test(c)],
];

const HANDOFF_CHECKS = [
  ['取舍清单覆盖 port', 'doc', h => h.includes('端口单例探测')],
  ['取舍清单覆盖 keepalive 复活', 'doc', h => h.includes('keepalive')],
  ['取舍清单覆盖 pid 真源', 'doc', h => h.includes('双 pid 真源')],
  ['取舍清单覆盖孤儿接管', 'doc', h => h.includes('孤儿 server')],
  ['V1：#5/#9 优先级（认领仅限真孤儿，防 keepalive 复活）', 'doc', h => h.includes('认领仅限真孤儿') && h.includes('非活 supervisor 父进程')],
  ['3099 禁词表六词（C1）', 'doc', h => ['kill', 'pkill', '重启', 'spawn', 'start', 'launch'].every(w => h.includes(w))],
  ['四面探针规格在场', 'doc', h => h.includes('probe-home-layout') && h.includes('probe-session-format') && h.includes('probe-runner-assembly') && h.includes('probe-settings-resolve')],
  ['版本化写点与 legacy 键口径', 'doc', h => h.includes('base.py:227') && h.includes('temporal_engine_version')],
  ['C3 升级输入源与畸形态', 'doc', h => h.includes('--to') && h.includes('降版本')],
];

function runChecks(name, text, checks) {
  const sect = section8(text);
  const fails = checks.filter(([, scope, fn]) => {
    const target = scope === 'sect' ? sect : text;
    try { return !fn(target); } catch { return true; }
  });
  return { name, fails: fails.map(([label]) => label) };
}

function main() {
  const results = [
    runChecks('契约⑧守卫', readFileSync(CONTRACT, 'utf8'), CHECKS),
    runChecks('交接单守卫', readFileSync(HANDOFF, 'utf8'), HANDOFF_CHECKS),
  ];
  const red = results.filter(r => r.fails.length);
  for (const r of results) {
    console.log(`${r.fails.length ? 'RED' : 'GREEN'}  ${r.name}${r.fails.length ? ' —— 缺失: ' + r.fails.join('; ') : ''}`);
  }
  if (process.argv.includes('--selftest')) return selftest(red.length);
  // 执行契约（integration/README，三态 §7.3）：末行 SUMMARY 四计数，机读区分真 PASS/产品红/环境红。
  const total = CHECKS.length + HANDOFF_CHECKS.length;
  const failed = red.reduce((n, r) => n + r.fails.length, 0);
  console.log(`\nSUMMARY pass=${total - failed} fail=${failed} env_fail=0 na=0`);
  if (red.length) { console.error(`sc_sandbar_dsh_compat: ${red.length} 组红`); process.exit(1); }
  console.log('sc_sandbar_dsh_compat: all green');
}

// —— V3：畸形态注入（临时副本）+ 红测：每种注入必须让对应组转红 ——
// no-datapoint / no-failclosed / no-section-5 是定向注入：只删⑧节内锚点、
// 变更记录行里的同词原样保留——专门钉死「全文词面检查被变更行掩护」的漏检面
// （acceptance 走查注入实验证实过的盲区），节内切片检查必须对它们转红。
function mutated(src, kind) {
  let t = String(src);
  if (kind === 'no-section') t = t.replace(/### ⑧ dsh 平台兼容区间与升版必查项[\s\S]*?(?=\n### docs 语境合成顺序)/, '\n');
  if (kind === 'no-checklist') t = t.replace(/\*\*⑧-2 升版必查项\*\*[\s\S]*?(?=\n\*\*⑧-3)/, '');
  if (kind === 'no-range') t = t.replace('@deepseek-ai/dsh', 'dsh').replace('0.1.1-rc.2', 'x.y.z-w');
  if (kind === 'no-datapoint') t = t.replace('`0.1.1-rc.2`', '`(deleted)`');
  if (kind === 'no-failclosed') t = t.replace('= fail-closed 红', '= 红');
  if (kind === 'no-upgrade-order') t = t.replace(/\*\*⑧-5 升版执行序\*\*[\s\S]*?(?=\n### docs 语境合成顺序)/, '');
  return t;
}
function selftest(mainRed) {
  const dir = mkdtempSync(join(tmpdir(), 'sc-sandbar-dsh-compat-'));
  let failed = 0;
  for (const kind of ['no-section', 'no-checklist', 'no-range', 'no-datapoint', 'no-failclosed', 'no-upgrade-order']) {
    const p = join(dir, `contract-${kind}.md`);
    writeFileSync(p, mutated(readFileSync(CONTRACT, 'utf8'), kind));
    const r = runChecks(`注入:${kind}`, readFileSync(p, 'utf8'), CHECKS);
    const red = r.fails.length > 0;
    console.log(`${red ? 'RED(as expected)' : 'GREEN(!!)'}  注入 ${kind} → 缺失: ${r.fails.join('; ') || '(无)'}`);
    if (!red) failed++;
  }
  const hp = join(dir, 'handoff-trimmed.md');
  writeFileSync(hp, readFileSync(HANDOFF, 'utf8').replace(/认领仅限真孤儿/g, '（已删）'));
  const hr = runChecks('注入:handoff-去V1条款', readFileSync(hp, 'utf8'), HANDOFF_CHECKS);
  const hred = hr.fails.length > 0;
  console.log(`${hred ? 'RED(as expected)' : 'GREEN(!!)'}  注入 handoff 去V1条款 → 缺失: ${hr.fails.join('; ') || '(无)'}`);
  if (!hred) failed++;
  rmSync(dir, { recursive: true, force: true });
  if (failed || mainRed) { console.error(`selftest 失败：注入未转红 ${failed} 例；主测红组见上`); process.exit(1); }
  console.log('selftest: 全部注入按预期转红，主测全绿');
}

main();
