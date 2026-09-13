// Integration scenario t260904-07 ③ — charter 注入用户旅程（browser，隔离台）。
//
// Intent (gray-box, user perspective):
//   用户在项目行点 + 新建会话后，不输入任何内容即应看到 charter 收成「已注入项目
//   背景」可展开小条（t260905-04：新会话开头只见小条、默认折叠、点开见全文；
//   占位符已实值化、命中分段在文，t260904-07 拍板④/注入机制结论不变）——这是
//   「每个 session 创建时注入我们想要的 prompt」的原话验收面；随后切换 tab、刷新
//   重进既有会话，都不得再注入第二条（守卫：恢复/切换路径绝不注入，沿
//   t260831-08 ⑥ 口径）。与 t260904-05 生命周期场景（tab 形态/续号/关闭链）intent
//   级不同层：本场景锚「注入内容可感知行为」，不锚 tab 形态；与随票 smoke（源文本
//   守卫锚）不同层：本场景锚真实浏览器端到端。
//
// High-level steps:
//   T0 卫兵链：拒 3099 → playwright-core 缺失=ENV_FAIL → 隔离台不可达=ENV_FAIL →
//      项目行未渲染=ENV_FAIL → charter 端点 404=源锚复核（已接线未部署=fail，
//      pre-merge=na）。
//   T1 新建注入：点 + → 新 tab 出现 → 会话区出现 charter 特征串（实值化，无 {{ 残留；
//      折叠态文本仍在 DOM=D2 口径，textContent 计数断言兼容不动）→ 折叠小条在场
//      （「已注入项目背景」文案）→ 默认折叠（打标消息视觉隐藏）→ 点击小条展开见
//      全文 → 截图证据（.suyou/screenshots/，KI-044 UI 票证据自觉）。折叠面断言  // naming-compat
//      pre-implement 红属预期（TDD 信号，t260905-04）。
//      分级：30s 未上屏且 console 有注入链错误=fail；未上屏且零错误=env_fail（无凭据
//      隔离台 kick-off 链路受限——本场景断言上限=注入链 UI 面，agent 回复链不在
//      断言面，有凭据环境人工复判）。
//   T2 切换零注入：切到相邻 tab 再切回 → 「的项目会话」特征串出现次数不变（无第二条
//      charter）、tab 集合不变（守卫没把切换当新建）；切换目标会话的小条在场性必须
//      与该会话是否含 charter 一致——无 charter 会话不留幽灵小条（t260905-04 review
//      条件 A③：React 不移除外部节点，锚定失效须摘除）。单 tab 环境该腿 ENV_FAIL。
//   T3 恢复零注入：reload → 过模态网 → 点原 tab → 特征串次数仍不变、tab 集合不变、
//      小条恢复在场且在场性与特征串一致（折叠件重启全树兜底扫描兑现——恢复路径
//      折叠面不丢）。
//   T4 console 卫生：零 console error / pageerror（过滤无凭据环境已知凭据类噪音）。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; 依赖缺失一律 env_fail (exit 2，
// 含「未上屏且仅凭据类错误」——凭据缺失归环境)；FAIL>0 或全腿 na → exit 1。
// 隔离台 SANDBAR_TEST_CONSOLE
// （默认 127.0.0.1:3199）；硬守卫：绝不 3099。

import { STAGE_SEED_ROW_SEL } from '../lib_stage_console.mjs';
// playwright-core 依赖解析唯一真源（t260912-01 缺陷③：位置无关四路口径）。
import { loadPlaywright, pwMissingDetail } from '../lib_pw_deps.mjs';
import { mkdirSync } from 'node:fs';
import { BASE, CHARTER_EP, refuseProductionConsole, makeResults, consoleHealthy } from './lib_charter.mjs';

refuseProductionConsole();
const { record, summarize } = makeResults();

// ---- T0 卫兵链 ----
// t260912-01：四路探测单源（lib_pw_deps），布局无关；失败文案只报事实不归因环境。
const pw = await loadPlaywright();
if (!pw) { record('t0/browser-deps', 'env_fail', pwMissingDetail()); summarize(); }
if (!(await consoleHealthy())) {
  record('t0/console-health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
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
        const node = readFileSync('server/plugins/workbench/node.ts', 'utf8');
        const mod = readFileSync('server/plugins/workbench/src/host/session-charter.ts', 'utf8');
        anchored = node.includes(CHARTER_EP) || (node.includes('session-charter') && mod.includes(CHARTER_EP));
      } catch { /* 按未实现 */ }
      record('t0/endpoint-live', anchored ? 'fail' : 'na',
        anchored ? '源码已接线但活体 404——lib 未重建或测试台未载新代码' : 'endpoint not implemented yet (pre-merge)');
      summarize();
    }
    live = r.ok;
    if (!live) { record('t0/endpoint-live', 'env_fail', `charter 端点 → ${r.status}，旅程前置不满足`); summarize(); }
  } catch (e) {
    record('t0/endpoint-live', 'env_fail', `charter 端点不可达：${String(e).slice(0, 100)}`);
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
  record('t0/page-open', 'env_fail', `browser/page unreachable: ${String(e).slice(0, 120)}`);
  try { await browser?.close(); } catch { /* noop */ }
  summarize();
}

try {
  await page.waitForSelector('[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])', { timeout: 12000 });
} catch {
  record('t0/fixture-psess-row', 'env_fail', 'no project session row rendered in test console sidebar');
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
  const row = document.querySelector('[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])');
  return [...(row?.querySelectorAll('[data-wb-psess-tab]') ?? [])].map(t => (t.title ?? '').split('\n').pop() ?? '');
});
const chatText = () => page.evaluate(() => document.querySelector('[data-conversation-scroll]')?.textContent ?? '');
const CHARTER_MARK = '的项目会话'; // 真源模板首句「你是「{{project_name}}」的项目会话」实值化后的稳定特征
const markCount = (t) => t.split(CHARTER_MARK).length - 1;

// ---- t260905-04 折叠面锚（灰盒：锚方案定稿的小条自有属性与打标容器属性 +
// 小条文案「已注入项目背景」，不锚内部实现——契约不变的实现重构不得打破本场景）----
const CHIP_SEL = '[data-wb-context-fold-chip]';
const FOLD_SEL = '[data-wb-context-fold]';
const chipRead = () => page.evaluate(({ CHIP_SEL, FOLD_SEL }) => {
  const chip = document.querySelector(CHIP_SEL);
  const fold = document.querySelector(FOLD_SEL);
  const hidden = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    return el.clientHeight === 0 || cs.display === 'none' || cs.visibility === 'hidden';
  };
  return {
    chipPresent: !!chip,
    chipText: (chip?.textContent ?? '').trim(),
    foldPresent: !!fold,
    foldHidden: hidden(fold),
  };
}, { CHIP_SEL, FOLD_SEL });

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
  record('t1/charter-first-message', noise ? 'env_fail' : 'fail',
    noise ? '30s 未上屏且仅凭据类错误——无凭据隔离台 kick-off 链路受限（有凭据环境人工复判）'
          : `30s 内会话区未出现 charter 特征串${injectedErr ? `；console: ${injectedErr}` : '；console 零错误'}`);
} else {
  const txt = await chatText();
  const residue = txt.includes('{{project_');
  record('t1/charter-first-message', residue ? 'fail' : 'pass',
    residue ? 'charter 上屏但残留 {{project_ 占位符（统一渲染未生效）' : `charter 已上屏（特征串 ×${markCount(txt)}）`);
  try {
    mkdirSync('.suyou/screenshots', { recursive: true });  // naming-compat
    await page.screenshot({ path: '.suyou/screenshots/t260904-07-charter-first-message.png', fullPage: true });  // naming-compat
    record('t1/screenshot-evidence', 'pass', '.suyou/screenshots/t260904-07-charter-first-message.png（KI-044 证据自觉）');  // naming-compat
  } catch (e) {
    record('t1/screenshot-evidence', 'env_fail', `截图失败：${String(e).slice(0, 100)}`);
  }

  // ---- t1 折叠面：小条在场 + 默认折叠 + 展开见全文（t260905-04 验收①②）----
  const chip = await chipRead();
  record('t1/context-chip-present', chip.chipPresent && chip.chipText.includes('已注入项目背景') ? 'pass'
    : 'fail', chip.chipPresent ? `小条在场，文案「${chip.chipText.slice(0, 40)}」` : '折叠小条不在场（整段仍直接刷屏，或折叠件未部署——pre-implement 红属预期）');
  record('t1/context-default-collapsed', chip.foldPresent && chip.foldHidden ? 'pass'
    : 'fail', `打标容器${chip.foldPresent ? (chip.foldHidden ? '默认折叠（视觉隐藏）' : '在场但未折叠——整段仍可见') : '不在场'}`);
  if (chip.chipPresent) {
    await safeClick(CHIP_SEL);
    await page.waitForTimeout(600);
    const expanded = await chipRead();
    record('t1/context-expand-shows-full', !expanded.foldHidden ? 'pass'
      : 'fail', expanded.foldHidden ? '点击小条后打标内容仍视觉隐藏（展开交互未生效）' : '点击小条后全文可见（特征串在文与占位符实值化已由上两条断言覆盖）');
  } else {
    record('t1/context-expand-shows-full', 'fail', '小条不在场，展开交互无从验证');
  }

  // ---- T2 切换零注入 ----
  let tabs = await rowRead();
  if (tabs.length < 2) {
    // 切换面自供给：+ 入口在场即可经同一用户路径再建一个会话（夹具事实不该直接
    // env_fail——原实现把「第二 tab 缺失」当环境缺供，260908 修：自造切换面再断言）。
    // 轮询 24s 且失效率新点击：会话创建走 agent preset kick-off 链，冷台下首建
    // 可 >6s（260909 实锤：12×500ms 轮询窗口内创建未完成即误报缺供）；创建中 +
    // 钮 disabled，重点击须等钮回弹。点击锚必须与 rowRead 同row（SeedWs 行）——
    // 全局 first-match 点到 seedq 行时第二 tab 落在 seedq 行，rowRead 只读 SeedWs
    // 行恒单 tab=假缺供（260909 实锤）。
    const SELF_PROV_SEL = '[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"]) [data-wb-psess-new]';
    for (let i = 0; i < 24 && tabs.length < 2; i++) {
      const btn = page.locator(SELF_PROV_SEL).first();
      if (i === 0 || ((await btn.isEnabled().catch(() => false)) && i % 4 === 0)) {
        await safeClick(SELF_PROV_SEL);
      }
      await page.waitForTimeout(1000);
      tabs = await rowRead();
    }
  }
  if (tabs.length < 2) {
    record('t2/switch-no-reinject', 'env_fail', '自建第二个会话后仍单 tab——切换面真缺供');
  } else {
    const before = markCount(await chatText());
    const curIdx = 0; // 新建后 active=新 tab（先例语义）；切相邻再切回
    await page.evaluate((i) => document.querySelectorAll('[data-wb-psess-row] [data-wb-psess-tab]')[i].click(), (curIdx + 1) % tabs.length);
    await page.waitForTimeout(1200);
    // 幽灵小条守卫（t260905-04 review 条件 A③）：切换目标会话的小条在场性必须
    // 与该会话是否含 charter 一致——外部插入的兄弟节点 React 不清，锚定失效须摘除。
    const ghost = await chipRead();
    const ghostMark = markCount(await chatText());
    record('t2/context-chip-no-ghost', ghost.chipPresent === (ghostMark > 0) ? 'pass'
      : 'fail', `切换目标会话特征串 ×${ghostMark} 而小条${ghost.chipPresent ? '在场' : '不在场'}——${ghostMark > 0 ? '含 charter 应有小条' : '无 charter 会话不得残留幽灵小条'}`);
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
  await page.waitForSelector('[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])', { timeout: 12000 });
  await page.evaluate(() => document.querySelectorAll('[data-wb-psess-row] [data-wb-psess-tab]')[0]?.click());
  await page.waitForTimeout(1500);
  const afterReload = markCount(await chatText());
  const tabsReloaded = await rowRead();
  record('t3/restore-no-reinject', (afterReload === 1 && tabsReloaded.length === tabsSnap.length) ? 'pass'
    : 'fail', `恢复后特征串 ×${afterReload}（应仍 ×1=无第二条注入），tab ×${tabsReloaded.length}（应 ×${tabsSnap.length}）`);
  // 折叠面恢复（t260905-04）：reload 后折叠件重启，全树兜底扫描应恢复小条与折叠态
  const chipReloaded = await chipRead();
  record('t3/context-chip-restored', chipReloaded.chipPresent === (afterReload > 0) ? 'pass'
    : 'fail', `恢复后特征串 ×${afterReload} 而小条${chipReloaded.chipPresent ? '在场' : '不在场'}——折叠面应随会话恢复（含 charter=小条在场），不丢不幽灵`);
}

// ---- T4 console 卫生（过滤无凭据环境已知凭据类噪音）----
const realErrors = consoleErrors.filter(t => !/api[_ ]?key|credential|unauthorized|401/i.test(t));
record('t4/console-clean', realErrors.length === 0 ? 'pass' : 'fail',
  realErrors.length ? `console error ×${realErrors.length}: ${realErrors[0].slice(0, 160)}` : '零 console error / pageerror');

try { await browser.close(); } catch { /* noop */ }
summarize();
