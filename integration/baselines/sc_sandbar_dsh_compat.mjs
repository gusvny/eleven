#!/usr/bin/env node
/**
 * Baseline: sandbar ⑧ dsh compatibility-range contract guard (t260903-08).
 *
 * Intent (user-perceivable contract):
 *   Section ⑧'s range declaration in contract v1.7 and its four upgrade
 *   re-check items are machine-consumed — the sandbar installer's
 *   `upgrade`/`doctor` probe set renders the compatibility range from it and
 *   re-scans the checklist on upgrade (the consumer relationship is recorded
 *   in notes/debts/sandbar-m2-c-installer-handoff.md). The guard asserts:
 *   - section ⑧ exists and its range policy is the "enumerated verified
 *     points" style (currently the single point 0.1.1-rc.2); a missing section
 *     or a dropped point = the consumer renders an empty/fake range. Anchors
 *     inside ⑧ are checked against the section-⑧ slice only, so the same words
 *     on a change-record line or in another section cannot act as cover (an
 *     acceptance-walkthrough tightening; see the scope comment in CHECKS and
 *     the no-datapoint/no-failclosed targeted injections);
 *   - the four upgrade re-check items (settings/resolve layering, headless
 *     runner assembly, home layout and session storage format, headless
 *     SIGTERM semantics) are each present — any miss = the dsh upgrade re-scan
 *     silently skips an item (defeating the whole point of promoting the
 *     touchpoints summary section);
 *   - the structural anchors of the version self-report policy
 *     (sandbar_version / 0.1.0 / temporal_engine_version kept verbatim) are
 *     present — the anchor vocabulary comes from the keywords that contract
 *     §⑧-4 itself defines, same source (V4: structural anchor assertions, not
 *     prose-wording assertions, so rewording the narrative does not fake a
 *     red);
 *   - the handoff doc's fault-mode tradeoff list covers every R1 keyword
 *     (port/keepalive/pid/orphan) and carries the #5/#9 priority clause
 *     (adoption only for true orphans) plus the 3099 six-word forbidden list —
 *     the handoff doc is a hard input to sandbar code tickets; dropping a
 *     clause = the code ticket copies the omission and half the incident
 *     replays.
 *
 * This scenario is a read-only documentation guard (the ro pool): it only
 * reads the controlled files, never injects into or rewrites them.
 * Malformed-state red tests go through --selftest (V3: inject six malformed
 * states into a /tmp temporary copy and assert they turn red), never by
 * trimming the controlled contract file in place and restoring it.
 */
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const CONTRACT = join(ROOT, 'docs', 'design', 'sandbar项目接入契约v1.md');
const HANDOFF = join(ROOT, 'notes', 'sandbar-m2-c-installer-handoff.md')  // 260904 migration-back adjustment: sandbar's actual location is the notes/ root;

// —— section-⑧ slice and normalization ——
// scope='sect' assertions run against the section-⑧ slice only: an anchor
// dropped inside the section goes red, and the same words on a change-record
// line or in another section cannot act as cover (a document-level word check
// was proven to miss things by the walkthrough injection experiment: deleting
// only ⑧-1's single point / ⑧-4's fail-closed sentence / ⑧-5's whole block
// left every document-level assertion green).
// scope='doc' assertions run against the whole document: the cross-section
// reference (the V5 bridge sentence) and the change-record line itself.
function section8(c) {
  const m = c.match(/### ⑧ dsh 平台兼容区间与升版必查项[\s\S]*?(?=\n### )/);
  return m ? m[0] : '';
}
const norm = s => String(s).replace(/\s+/g, ' ');

// —— assertion vocabulary (V4: same source as contract §⑧'s own keywords, not free-form wording) ——
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
  // Execution contract (integration/README, three-state §7.3): the last line
  // is a SUMMARY with four counts, so a machine can tell a real PASS from a
  // product red and an environmental red.
  const total = CHECKS.length + HANDOFF_CHECKS.length;
  const failed = red.reduce((n, r) => n + r.fails.length, 0);
  console.log(`\nSUMMARY pass=${total - failed} fail=${failed} env_fail=0 na=0`);
  if (red.length) { console.error(`sc_sandbar_dsh_compat: ${red.length} 组红`); process.exit(1); }
  console.log('sc_sandbar_dsh_compat: all green');
}

// —— V3: malformed-state injection (into a temporary copy) + red tests: every
// injection must turn its group red ——
// no-datapoint / no-failclosed / no-section-5 are targeted injections: only
// the anchor inside section ⑧ is removed while the same words on the
// change-record line stay intact — pinning down exactly the blind spot where
// "a document-level word check is covered by a change line" (a blind spot the
// acceptance-walkthrough injection experiment demonstrated); the section-slice
// checks must turn red on them.
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
