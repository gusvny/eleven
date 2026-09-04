// Integration scenario t260904-05 ① — 顶部行退役后的入口形态与项目色契约（R8+R7 左栏面）。
//
// Intent (gray-box, user perspective):
//   用户打开控制台：左栏顶部的旧「新建会话 + 最近会话 tabs + ↺ 最近关闭」整行消失
//   （唯一会话入口=各项目组内的项目行）；出厂全局新建钮继续被压制不回显（拍板 1，
//   只是职责改名）；项目关闭确认弹层只说「仅关闭入口，不删除会话内容」（拍板 2，
//   不再许诺 ↺ 找回）。项目色（拍板 5）：组头色点、+ 钮、激活 tab 同一项目恒同色，
//   且刷新后不变（验收 5「确定性」）。lib 产物与源同批收口（无退役符号残留）。
//
// High-level steps:
//   P0 产物静态收口（node 侧，无浏览器也跑）：lib/client.js 无 SessionTopEntry/
//      wb-sessTop/pickSwitchTargets/renameEntry/data-wb-session-*；含
//      data-wb-chat-projband、data-wb-psess-dot、--wb-psess-color 新锚。
//   T0 卫兵：拒 3099；playwright/隔离台/侧栏夹具缺失=ENV_FAIL（exit 2）。
//   T1 顶部行退役形态：data-wb-session-{entry,new,row,reopen} 全不在 DOM；
//      无 wb-sessTop* 类名元素。
//   T2 出厂钮压制：aria-label 恰为出厂 label（新建会话/New session）的元素零可见。
//   T3 项目色三处同源：组头色点色 == + 钮边框色 == 根容器 CSS 变量
//      --wb-psess-color（∈ project-color 确定性色板）。
//   T4 刷新恒色：reload 后色点色不变。
//   T5 确认弹层文案（有机会断言：已有 tab 才点）：含「仅关闭入口」「不删除」，
//      不含「↺」「最近关闭」；取消不关闭。
//   T6 console 零 error / pageerror。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; missing deps → env_fail
// (exit 2); FAIL>0 或全腿 na → exit 1. Isolated console
// SUYOU_TEST_CONSOLE (default 127.0.0.1:3199); hard guard: never 3099.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { PROJECT_PALETTE } from '../../server/dsh/workbench/src/shared/project-color.ts';
import {
  BASE, refuseProductionConsole, loadPlaywright, consoleHealthy,
  fetchProjects, makeResults, openTestPage, waitProjectRowOrSkip,
  dismissFirstRunModals,
} from './lib_browser.mjs';

refuseProductionConsole();
const { record, summarize } = makeResults();

function hexToRgbString(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex ?? '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

// ── P0 产物静态收口（退役符号零残留 + 新锚在场；与 lib 重建同批为前提）──
{
  const libPath = join(dirname(fileURLToPath(import.meta.url)), '../../server/dsh/workbench/lib/client.js');
  try {
    const built = readFileSync(libPath, 'utf8');
    const retired = ['SessionTopEntry', 'wb-sessTop', 'pickSwitchTargets', 'renameEntry', 'data-wb-session-'];
    const leaked = retired.filter(s => built.includes(s));
    record('p0/lib-retired-gone', leaked.length === 0 ? 'pass' : 'fail',
      leaked.length === 0 ? '' : `产物残留退役符号：${leaked.join(', ')}`);
    const fresh = ['data-wb-chat-projband', 'data-wb-psess-dot', '--wb-psess-color'];
    const missing = fresh.filter(s => !built.includes(s));
    record('p0/lib-new-anchors', missing.length === 0 ? 'pass' : 'fail',
      missing.length === 0 ? '' : `产物缺新锚：${missing.join(', ')}`);
  } catch (e) {
    record('p0/lib-read', 'fail', `lib/client.js 不可读：${String(e).slice(0, 120)}`);
  }
}

// ── 浏览器段 ──
const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable'); summarize(); }
if (!(await consoleHealthy())) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);

const consoleErrors = [];
const opened = await openTestPage(pw, { results: { record }, tag: 'browser', consoleErrors });
if (!opened) summarize();
const { browser, page } = opened;

try {
  if (!(await waitProjectRowOrSkip(page, { record }, 'browser'))) { summarize(); }

  // T1 顶部行退役形态：四锚 + wb-sessTop 类名全不在场
  const retired = await page.evaluate(() => ({
    anchors: ['data-wb-session-entry', 'data-wb-session-new', 'data-wb-session-row', 'data-wb-session-reopen']
      .map(a => ({ a, n: document.querySelectorAll(`[${a}]`).length })),
    sessTopClassEls: document.querySelectorAll('[class*="wb-sessTop"]').length,
  }));
  const leakedAnchors = retired.anchors.filter(x => x.n > 0);
  record('t1/top-entry-anchors-gone', leakedAnchors.length === 0 && retired.sessTopClassEls === 0 ? 'pass' : 'fail',
    leakedAnchors.length === 0 && retired.sessTopClassEls === 0 ? ''
      : `残留锚=${JSON.stringify(leakedAnchors)} wb-sessTop 元素=${retired.sessTopClassEls}`);

  // T2 出厂全局新建钮继续被压制（拍板 1：隐藏不回显）
  // 口径注记（t260904-05 验收走查 gen0 实测修正）：dsh 现版本的 logoRow 品牌钮
  // aria-label 同为 "New session" 但无新建行为（点击零请求零状态变化，隔离台
  // 实测）——纯品牌展示位的平台侧 aria 误标。压制断言只认「可感知的新建钮」：
  // aria-label 命中 + 可见 + 带非空可见文本（真出厂 New Session 钮有字样文本，
  // 品牌钮是纯图标）。不绑任何 CSS 类名（css-module 哈希类纪律）。
  const factoryVisible = await page.evaluate(() => {
    const labels = ['新建会话', 'New session']; // FACTORY_NEW_LABELS zh/en（hero.mjs 同源）
    return [...document.querySelectorAll('[aria-label]')]
      .filter(el => labels.includes(el.getAttribute('aria-label')))
      .filter(el => el.offsetParent !== null)
      .filter(el => (el.textContent ?? '').trim() !== '')
      .length;
  });
  record('t2/factory-new-suppressed', factoryVisible === 0 ? 'pass' : 'fail',
    factoryVisible === 0 ? '' : `出厂新建钮可见 ${factoryVisible} 个（应被压制）`);

  // T3 项目色三处同源（色点 / + 钮 / 根容器 CSS 变量 ∈ 确定性色板）
  const colors = await page.evaluate(() => {
    const root = document.querySelector('[data-wb-psess-row]');
    const dot = document.querySelector('[data-wb-psess-dot]');
    const plus = document.querySelector('[data-wb-psess-new]');
    if (!root || !dot || !plus) return null;
    const cs = el => getComputedStyle(el);
    return {
      varColor: cs(root).getPropertyValue('--wb-psess-color').trim(),
      // 色点视觉通道=background（8px 纯色块无文字，color 是继承噪音——t260904-05
      // 验收走查 gen0 实测修正：读 color 恒得继承深底色，三处同色断言假阳性）
      dotColor: cs(dot).backgroundColor,
      plusBorder: cs(plus).borderTopColor,
      plusColorText: cs(plus).color,
    };
  });
  if (colors === null) {
    record('t3/psess-anchors', 'env_fail', 'psess 色断言锚不全（root/dot/plus 缺一）——实现未落地或夹具变异');
  } else {
    const varRgb = hexToRgbString(colors.varColor);
    const inPalette = PROJECT_PALETTE.includes(colors.varColor);
    const same = varRgb !== null && varRgb === colors.dotColor && varRgb === colors.plusBorder;
    record('t3/three-spot-same-color', same && inPalette ? 'pass' : 'fail',
      same && inPalette ? '' : `var=${colors.varColor}(palette=${inPalette}) dotBg=${colors.dotColor} plusBorder=${colors.plusBorder}`);
    record('t3/plus-text-color', colors.plusColorText === colors.dotColor ? 'pass' : 'fail',
      `plusText=${colors.plusColorText} dot=${colors.dotColor}`);
  }

  // T4 刷新恒色（验收 5：刷新不变；读色点 background 通道，同 t3 口径）
  const before = await page.evaluate(() => getComputedStyle(document.querySelector('[data-wb-psess-dot]'))?.backgroundColor ?? '');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-wb-psess-dot]', { timeout: 12000 }).catch(() => {});
  const after = await page.evaluate(() => getComputedStyle(document.querySelector('[data-wb-psess-dot]'))?.backgroundColor ?? '');
  record('t4/color-stable-reload', before !== '' && before === after ? 'pass' : 'fail',
    `reload 色点色 ${before || '(none)'} → ${after || '(none)'}`);

  // T5 确认弹层文案（拍板 2：无 ↺/最近关闭 表述）。无已有 tab 时主动点 + 造一个
  // （t260904-05 验收走查 gen0 升级：原「机会性跳过」在可造数环境必漏过真实
  // 渲染文案断言——文案是拍板 2 的唯一用户可感知面，尽力而为而非放弃）。
  // 造数后新建 tab 不关闭（取消收起），残留条目不影响本场景其余断言（已全部跑完）。
  let closeBtn = await page.$('[data-wb-psess-close]');
  if (!closeBtn) {
    try {
      await page.click('[data-wb-psess-new]', { timeout: 3000 });
    } catch { /* mask 拦截退避：过模态网后 DOM 直点（forceClick 同语义） */ }
    if (!(await page.$('[data-wb-psess-close]'))) {
      try { await dismissFirstRunModals(page); } catch { /* 尽力清场 */ }
      await page.evaluate(() => document.querySelector('[data-wb-psess-new]')?.click());
    }
    try {
      await page.waitForSelector('[data-wb-psess-close]', { timeout: 20000 });
    } catch { /* 造数失败，下方仍走 env_fail */ }
    closeBtn = await page.$('[data-wb-psess-close]');
  }
  if (!closeBtn) {
    record('t5/confirm-copy', 'env_fail', '无已有会话 tab 且造数未成（+ 链路异常，见场景③）');
  } else {
    await page.evaluate(el => el.click(), closeBtn);
    await page.waitForSelector('[data-wb-psess-confirm]', { timeout: 5000 }).catch(() => {});
    const confirmText = await page.evaluate(() =>
      document.querySelector('[data-wb-psess-confirm]')?.textContent ?? '');
    const good = confirmText.includes('仅关闭入口') && confirmText.includes('不删除')
      && !confirmText.includes('↺') && !confirmText.includes('最近关闭');
    record('t5/confirm-copy', good ? 'pass' : 'fail', good ? '' : `弹层文案：${confirmText.slice(0, 80)}`);
    await page.evaluate(() => document.querySelector('[data-wb-psess-confirm-cancel]')?.click());
  }

  // T6 console 卫生
  if (consoleErrors.length === 0) record('t6/console-hygiene', 'pass');
  else record('t6/console-hygiene', 'fail', consoleErrors.slice(0, 3).join(' | ').slice(0, 300));
} finally {
  try { await browser.close(); } catch { /* noop */ }
}
summarize();
