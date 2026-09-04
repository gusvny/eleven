// Integration scenario t260904-07 ③ — charter 注入用户旅程（browser，隔离台）。
//
// Intent (gray-box, user perspective):
//   用户在项目行点 + 新建会话后，不输入任何内容即应看到会话以 charter 为首条消息
//   开局（占位符已实值化、命中分段在文，t260904-07 拍板④/注入机制结论）——这是
//   「每个 session 创建时注入我们想要的 prompt」的原话验收面；随后切换 tab、刷新
//   重进既有会话，都不得再注入第二条（守卫：恢复/切换路径绝不注入，沿
//   t260831-08 ⑥ 口径）。与 t260904-05 生命周期场景（tab 形态/续号/关闭链）intent
//   级不同层：本场景锚「注入内容可感知行为」，不锚 tab 形态；与随票 smoke（源文本
//   守卫锚）不同层：本场景锚真实浏览器端到端。
//
// High-level steps:
//   T0 卫兵链：拒 3099 → playwright-core 缺失=SKIP → 隔离台不可达=SKIP → 项目行
//      未渲染=SKIP → charter 端点 404=源锚复核（已接线未部署=fail，pre-merge=skip）。
//   T1 新建注入：点 + → 新 tab 出现 → 会话区出现 charter 特征串（实值化，无 {{ 残留）
//      → 截图证据（.suyou/screenshots/，KI-044 UI 票证据自觉）。
//      分级：30s 未上屏且 console 有注入链错误=fail；未上屏且零错误=skip（无凭据
//      隔离台 kick-off 链路受限——本场景断言上限=注入链 UI 面，agent 回复链不在
//      断言面，有凭据环境人工复判）。
//   T2 切换零注入：切到相邻 tab 再切回 → 「的项目会话」特征串出现次数不变（无第二条
//      charter）、tab 集合不变（守卫没把切换当新建）。单 tab 环境该腿 SKIP。
//   T3 恢复零注入：reload → 过模态网 → 点原 tab → 特征串次数仍不变、tab 集合不变。
//   T4 console 卫生：零 console error / pageerror（过滤无凭据环境已知凭据类噪音）。
//
// Execution contract: stdout last line `SUMMARY pass=<n> skip=<m> fail=<k>`;
// 依赖缺失一律干净 SKIP (exit 0)；FAIL>0 → exit 1。隔离台 SUYOU_TEST_CONSOLE
// （默认 127.0.0.1:3199）；硬守卫：绝不 3099。

import { mkdirSync } from 'node:fs';
import { BASE, CHARTER_EP, refuseProductionConsole, makeResults, consoleHealthy } from './lib_charter.mjs';

refuseProductionConsole();
const { record, summarize } = makeResults();

// ---- T0 卫兵链 ----
const localPw = new URL('../../server/dsh/ui-check/node_modules/playwright-core/index.mjs', import.meta.url).href;
let pw = null;
for (const c of [process.env.SUYOU_PLAYWRIGHT_PATH, 'playwright-core', localPw]) {
  if (!c) continue;
  try { pw = await import(c); break; } catch { /* next */ }
}
if (!pw) { record('t0/browser-deps', 'skip', 'playwright-core unavailable'); summarize(); }
if (!(await consoleHealthy())) {
  record('t0/console-health', 'skip', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}

// 端点活性前置（404=旅程无意义；源锚复核精确归因，同 sc② 口径）
{
  let live = false, anchored = false;
  try {
    const r = await fetch(`${BASE}${CHARTER_EP}?project=sandbar`, { signal: AbortSignal.timeout(5000) });
    if (r.status === 404) {
      const { readFileSync } = await import('node:fs');
      try {
        const node = readFileSync('server/dsh/workbench/node.ts', 'utf8');
        const mod = readFileSync('server/dsh/workbench/src/host/session-charter.ts', 'utf8');
        anchored = node.includes(CHARTER_EP) || (node.includes('session-charter') && mod.includes(CHARTER_EP));
      } catch { /* 按未实现 */ }
      record('t0/endpoint-live', anchored ? 'fail' : 'skip',
        anchored ? '源码已接线但活体 404——lib 未重建或测试台未载新代码' : 'endpoint not implemented yet (pre-merge)');
      summarize();
    }
    live = r.ok;
    if (!live) { record('t0/endpoint-live', 'skip', `charter 端点 → ${r.status}，旅程前置不满足`); summarize(); }
  } catch (e) {
    record('t0/endpoint-live', 'skip', `charter 端点不可达：${String(e).slice(0, 100)}`);
    summarize();
  }
  record('t0/endpoint-live', 'pass', 'charter 端点活体可达');
}

// ---- 打开隔离台页面（fresh context=等价新用户；口径同 t260904-05/lib_browser）----
const consoleErrors = [];
let browser = null;
const dismissModals = async (page) => {
  try {
    const btn = page.locator('button', { hasText: /continue|继续/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 4000 });
    await btn.click({ timeout: 3000 }).catch(() => btn.evaluate(el => el.click()));
    await btn.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
  } catch { /* 首屏模态未出现，继续 */ }
  if (await page.locator('[role="dialog"]').count()) {
    const later = page.locator('button:has-text("Configure later")').first();
    try { if (await later.isVisible()) await later.click({ timeout: 2000 }); }
    catch {
      const dialog = page.locator('[role="dialog"]').first();
      const btn = dialog.locator('button:enabled').first();
      if (await btn.count()) await btn.click({ timeout: 2000 }).catch(() => {});
      else await page.keyboard.press('Escape').catch(() => {});
    }
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline && await page.locator('[role="dialog"]').count()) await page.waitForTimeout(400);
  }
};

let page = null;
try {
  const launch = async () => {
    try { return await pw.chromium.launch({ channel: 'chrome', headless: true }); }
    catch { return await pw.chromium.launch({ headless: true }); }
  };
  browser = await launch();
  const context = await browser.newContext();
  page = await context.newPage();
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push(String(e)));
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await dismissModals(page);
} catch (e) {
  record('t0/page-open', 'skip', `browser/page unreachable: ${String(e).slice(0, 120)}`);
  try { await browser?.close(); } catch { /* noop */ }
  summarize();
}

try {
  await page.waitForSelector('[data-wb-psess-row]', { timeout: 12000 });
} catch {
  record('t0/fixture-psess-row', 'skip', 'no project session row rendered in test console sidebar');
  try { await browser.close(); } catch { /* noop */ }
  summarize();
}
record('t0/guards', 'pass', '卫兵链全过');

// 遮罩退避直点（先例 safeClick 口径：mask 拦合成点击时先过模态网再 DOM 直点）
const safeClick = async (sel) => {
  try { await page.click(sel, { timeout: 3000 }); return; } catch { /* mask/时序 */ }
  try { await dismissModals(page); } catch { /* 尽力 */ }
  const loc = page.locator(sel).first();
  try { await loc.click({ timeout: 3000 }); } catch { await loc.evaluate(el => el.click()); }
};
const rowRead = () => page.evaluate(() => {
  const row = document.querySelector('[data-wb-psess-row]');
  return [...(row?.querySelectorAll('[data-wb-psess-tab]') ?? [])].map(t => (t.title ?? '').split('\n').pop() ?? '');
});
const chatText = () => page.evaluate(() => document.querySelector('[data-conversation-scroll]')?.textContent ?? '');
const CHARTER_MARK = '的项目会话'; // 真源模板首句「你是「{{project_name}}」的项目会话」实值化后的稳定特征
const markCount = (t) => t.split(CHARTER_MARK).length - 1;

// ---- T1 新建注入：charter 为首条消息 ----
const tabsBefore = await rowRead();
await safeClick('[data-wb-psess-row] [data-wb-psess-new]');
let injected = false, injectedErr = '';
try {
  await page.waitForFunction(
    (mark) => (document.querySelector('[data-conversation-scroll]')?.textContent ?? '').includes(mark),
    CHARTER_MARK, { timeout: 30000 },
  );
  injected = true;
} catch { injectedErr = consoleErrors.join(' | ').slice(0, 200); }

if (!injected) {
  const noise = /api[_ ]?key|credential|unauthorized|401/i.test(injectedErr);
  record('t1/charter-first-message', noise ? 'skip' : 'fail',
    noise ? '30s 未上屏且仅凭据类错误——无凭据隔离台 kick-off 链路受限（有凭据环境人工复判）'
          : `30s 内会话区未出现 charter 特征串${injectedErr ? `；console: ${injectedErr}` : '；console 零错误'}`);
} else {
  const txt = await chatText();
  const residue = txt.includes('{{project_');
  record('t1/charter-first-message', residue ? 'fail' : 'pass',
    residue ? 'charter 上屏但残留 {{project_ 占位符（统一渲染未生效）' : `charter 已上屏（特征串 ×${markCount(txt)}）`);
  try {
    mkdirSync('.suyou/screenshots', { recursive: true });
    await page.screenshot({ path: '.suyou/screenshots/t260904-07-charter-first-message.png', fullPage: true });
    record('t1/screenshot-evidence', 'pass', '.suyou/screenshots/t260904-07-charter-first-message.png（KI-044 证据自觉）');
  } catch (e) {
    record('t1/screenshot-evidence', 'skip', `截图失败：${String(e).slice(0, 100)}`);
  }

  // ---- T2 切换零注入 ----
  const tabs = await rowRead();
  if (tabs.length < 2) {
    record('t2/switch-no-reinject', 'skip', '单 tab 环境无切换面');
  } else {
    const before = markCount(await chatText());
    const curIdx = 0; // 新建后 active=新 tab（先例语义）；切相邻再切回
    await page.evaluate((i) => document.querySelectorAll('[data-wb-psess-row] [data-wb-psess-tab]')[i].click(), (curIdx + 1) % tabs.length);
    await page.waitForTimeout(1200);
    await page.evaluate((i) => document.querySelectorAll('[data-wb-psess-row] [data-wb-psess-tab]')[i].click(), curIdx);
    await page.waitForTimeout(1200);
    const after = markCount(await chatText());
    const tabsAfter = await rowRead();
    record('t2/switch-no-reinject', (after === before && tabsAfter.length === tabs.length) ? 'pass'
      : 'fail', `切换前后特征串 ×${before}→×${after}，tab ×${tabs.length}→×${tabsAfter.length}（守卫不得把切换当新建再注入）`);
  }

  // ---- T3 恢复零注入 ----
  const tabsSnap = await rowRead();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await dismissModals(page);
  await page.waitForSelector('[data-wb-psess-row]', { timeout: 12000 });
  await page.evaluate(() => document.querySelectorAll('[data-wb-psess-row] [data-wb-psess-tab]')[0]?.click());
  await page.waitForTimeout(1500);
  const afterReload = markCount(await chatText());
  const tabsReloaded = await rowRead();
  record('t3/restore-no-reinject', (afterReload === 1 && tabsReloaded.length === tabsSnap.length) ? 'pass'
    : 'fail', `恢复后特征串 ×${afterReload}（应仍 ×1=无第二条注入），tab ×${tabsReloaded.length}（应 ×${tabsSnap.length}）`);
}

// ---- T4 console 卫生（过滤无凭据环境已知凭据类噪音）----
const realErrors = consoleErrors.filter(t => !/api[_ ]?key|credential|unauthorized|401/i.test(t));
record('t4/console-clean', realErrors.length === 0 ? 'pass' : 'fail',
  realErrors.length ? `console error ×${realErrors.length}: ${realErrors[0].slice(0, 160)}` : '零 console error / pageerror');

try { await browser.close(); } catch { /* noop */ }
summarize();
