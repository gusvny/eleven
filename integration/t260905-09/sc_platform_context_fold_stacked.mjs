// Integration scenario t260905-09 ② — 平台自启上下文叠台折叠用户旅程（browser，隔离台）。
//
// Intent (gray-box, user perspective, L3 场景层):
//   真控制台新会话开头的刷屏墙=两层叠加：平台自启上下文×N + 工单台 charter 注入×1。
//   16 号（t260905-04/t260904-07）只折了自己的注入腿——台面无平台叠加=假绿（宿主
//   260906 实报「还是显示了一堆，只折叠了开头一小部分」）。本场景=工单「怎么算好」
//   原话的可执行化：夹具把平台启动上下文消息×N + 工单台注入×1 叠进同一会话，断言
//   恰好一个小条、全部候选正文收折、点开全见、点回收折；普通用户消息零误折（负向）；
//   叠加物清走后无幽灵小条（孤儿守卫）。断言面=用户可感知行为（可见性/小条在场/
//   文案），不读实现 attr/类名（内容锚纪律，同 context-fold.ts 头注红线）。
//
// High-level steps:
//   T0 卫兵链：拒 3099 → playwright-core 缺失=ENV_FAIL → 隔离台不可达=ENV_FAIL →
//      锚真源模块不在=fail（TDD 信号，同 16 号折叠面先例）→ 锚模块在而 served
//      bundle 无锚样本=na（已实现未重建/未部署，pre-merge 常态，merge 期自动生效）。
//   T1 前置卫兵（16 号既有行为，不重断其契约）：项目行点 + 新建会话 → charter 小条
//      在场（30s；未上屏且有注入链 console error=fail，零错误=env_fail——无凭据
//      隔离台 kick-off 限制，同 journey T1 分级）。
//   T2 叠台主断言（验收①）：夹具注入平台上下文×3 + 前缀粘贴×1（同气泡双锚去重
//      样本在 fx-02）→ 断言：小条恰 1 条（不是 charter 一条+平台又一条——聚合是
//      本票核心语义）；全部注入气泡 display:none；点小条全开（可见+文案切换）；
//      再点全收。
//   T3 负向（验收②）：注入中段提及普通消息 → 全程可见、小条仍恰 1 条、既有折叠
//      组不动。
//   T4 孤儿守卫（验收③）：移除全部夹具气泡 → 小条随之摘除（无幽灵）；reload 后
//      夹具气泡不复活、无幽灵小条（charter 小条恢复在场属 16 号行为，不在此断）。
//   T5 console 卫生：零 pageerror（React 重渲染 removeChild 类崩溃在此现形——
//      夹具手法≠产品缺陷，崩溃证据随 detail 留痕上报归因，不许静默）。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；fail>0 或全腿 na → exit 1；
// env_fail>0 → 2；全过 → 0。隔离台默认 127.0.0.1:3199，硬守卫绝不 3099。
// 折叠面断言 pre-implement 红属预期（TDD 信号，沿 t260905-04 先例）。

import { existsSync, readFileSync } from 'node:fs';
import { STAGE_SEED_ROW_SEL } from '../lib_stage_console.mjs';
import {
  stageBase, refuseProductionConsole, makeResults, consoleHealthy,
  loadFixtures, injectPlatformBubbles, foldProbe, clickChip,
  ANCHORS_MODULE,
} from './lib_platform_context.mjs';

refuseProductionConsole(await stageBase().catch(() => ':unreachable/'));
let BASE = '';
try {
  BASE = await stageBase();
} catch (e) {
  record('t0/stage-console', 'env_fail', `隔离台供给不可用：${String(e).slice(0, 140)}`);
  summarize();
}
const { record, summarize } = makeResults();
const pageErrors = [];

// 浏览器启动（模块级：T0 探测腿与主旅程共用；同 journey 手法——优先本机 Chrome
// channel 免 playwright 下载二进制，回落纯 chromium）
const launchBrowser = async () => {
  try { return await pw.chromium.launch({ channel: 'chrome', headless: true }); }
  catch { return await pw.chromium.launch({ headless: true }); }
};

// ---- T0 卫兵链 ----
const localPw = new URL('../../server/ui-check/node_modules/playwright-core/index.mjs', import.meta.url).href;
let pw = null;
for (const c of [process.env.SANDBAR_PLAYWRIGHT_PATH, 'playwright-core', localPw]) {
  if (!c) continue;
  try { pw = await import(c); break; } catch { /* next */ }
}
if (!pw) { record('t0/browser-deps', 'env_fail', 'playwright-core unavailable'); summarize(); }
if (!(await consoleHealthy(BASE))) {
  record('t0/console-health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
{
  const bundleSample = loadFixtures().find(f => f.name.startsWith('fx-01'))?.anchor ?? '';
  if (!existsSync(ANCHORS_MODULE)) {
    record('t0/anchors-module', 'fail', `${ANCHORS_MODULE} 不在——平台锚真源未落地（TDD 信号：实现段落地前红属预期，arbitrate/merge 期必须绿）`);
    summarize();
  }
  record('t0/anchors-module', 'pass', ANCHORS_MODULE);
  // bundle 部署归因腿（na 仅给系统状态条件腿）：源在而 served bundle 无锚样本
  // =实现已落地但 bundle 未重建/未部署——本场景行为腿对其余腿无意义，归 na。
  try {
    const browser = await launchBrowser();
    const page = await browser.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    const probe = await page.evaluate(async sample => {
      const srcs = [...document.scripts].map(s => s.src).filter(Boolean);
      for (const src of srcs) {
        try {
          const text = await fetch(src).then(r => r.text());
          if (text.includes(sample)) return { hit: true, src };
        } catch { /* 个别脚本取不到，继续 */ }
      }
      return { hit: false, scripts: srcs.length };
    }, bundleSample.slice(0, 24));
    await browser.close();
    if (!probe.hit) {
      record('t0/bundle-deployed', 'na', `served bundle 无锚样本「${bundleSample.slice(0, 24)}…」——实现未重建/未部署（pre-merge 常态；merge 期仍 na=bundle 重建对齐欠账）`);
      summarize();
    }
    record('t0/bundle-deployed', 'pass', `锚样本在 served bundle：${probe.src ?? ''}`);
  } catch (e) {
    record('t0/bundle-deployed', 'env_fail', `bundle 探测失败：${String(e).slice(0, 120)}`);
    summarize();
  }
}

// ---- 开页 + 建会话（真实 UI 操作，同 journey 手法）----
const browser = await launchBrowser();
const page = await browser.newPage();
page.on('pageerror', err => pageErrors.push(String(err?.message ?? err)));
try {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  const row = page.locator(STAGE_SEED_ROW_SEL).first();
  await row.waitFor({ state: 'visible', timeout: 15000 });
  const plus = row.locator('[aria-label*="新建"]').first();
  try { await plus.click({ timeout: 3000 }); } catch { await plus.evaluate(el => el.click()); }
  await page.waitForTimeout(1500);
} catch (e) {
  record('t1/new-session', 'env_fail', `隔离台项目行/新建入口不可用：${String(e).slice(0, 120)}`);
  await browser.close();
  summarize();
}

// ---- T1 前置卫兵：charter 小条在场（16 号既有行为）----
{
  let ok = false;
  try { await page.waitForFunction(() => [...document.querySelectorAll('[data-conversation-scroll] *')].some(el => (el.textContent ?? '').includes('已注入项目背景') && el.children.length === 0), null, { timeout: 30000 }); ok = true; } catch { /* 未上屏 */ }
  if (!ok) {
    const errs = pageErrors.join(' | ').slice(0, 200);
    record('t1/charter-chip-precondition', errs ? 'fail' : 'env_fail',
      errs ? `charter 小条 30s 未上屏且 console 有错（注入链异常）：${errs}` : 'charter 小条 30s 未上屏、零 console error（无凭据隔离台 kick-off 受限——有凭据环境人工复判）');
    await browser.close();
    summarize();
  }
  record('t1/charter-chip-precondition', 'pass', 'charter 小条在场（工单台注入腿正常）');
}

// ---- T2 叠台主断言（验收①）----
const platformFx = loadFixtures().filter(f => /^fx-0/.test(f.name) || f.name.startsWith('fx-92'));
try {
  const ids = await injectPlatformBubbles(page, platformFx);
  if (!ids) { record('t2/inject', 'env_fail', '滚动体 [data-conversation-scroll] 不在页（会话区未渲染）'); await browser.close(); summarize(); }
  await page.waitForTimeout(800); // Observer 回调+渲染余量
  const probe = await foldProbe(page);
  const all = Object.fromEntries(probe.bubbles.map(b => [b.id, b.state]));
  const foldedAll = probe.bubbles.every(b => b.state === 'hidden');
  record('t2/one-chip', probe.chipCount === 1 ? 'pass' : 'fail',
    `小条数=${probe.chipCount}（聚合语义=恰 1 条；>1=平台上下文另起小条违背「同一折叠件」原话；0=叠加腿未折=宿主实报复现）`);
  record('t2/all-folded', foldedAll ? 'pass' : 'fail',
    foldedAll ? `平台气泡 ${probe.bubbles.length} 条全部收折（含 fx-02 同气泡双锚去重样本）`
              : `未收折：${probe.bubbles.filter(b => b.state !== 'hidden').map(b => `${b.id}=${b.state}`).join(', ')}`);
  // 点开全见 → 再点全收
  await clickChip(page);
  await page.waitForTimeout(300);
  const opened = await foldProbe(page);
  const allOpen = opened.bubbles.every(b => b.state === 'visible');
  record('t2/click-open-all', allOpen && opened.chipLabel !== probe.chipLabel ? 'pass' : 'fail',
    allOpen ? '点小条：叠加组全部展开（整组开）' : `展开不全：${opened.bubbles.filter(b => b.state !== 'visible').map(b => `${b.id}=${b.state}`).join(', ')}；文案切换=${opened.chipLabel !== probe.chipLabel}`);
  await clickChip(page);
  await page.waitForTimeout(300);
  const refolded = await foldProbe(page);
  record('t2/click-refold-all', refolded.bubbles.every(b => b.state === 'hidden') ? 'pass' : 'fail',
    refolded.bubbles.every(b => b.state === 'hidden') ? '再点：整组收折' : `收折不齐：${refolded.bubbles.filter(b => b.state !== 'hidden').map(b => `${b.id}=${b.state}`).join(', ')}`);
  // 截图证据（KI-044 UI 票证据自觉）：叠台折叠态 + 点开态各一张（改动前后视觉对比=
  // 折叠件对平台上下文的可见效果；16 号前的「改前」即未折叠刷屏墙，宿主 260906 实报在案）
  try {
    const { mkdirSync } = await import('node:fs');
    mkdirSync('.suyou/screenshots', { recursive: true });  // naming-compat
    await page.screenshot({ path: '.suyou/screenshots/t260905-09-stacked-folded.png', fullPage: true });  // naming-compat
    await clickChip(page);
    await page.waitForTimeout(300);
    await page.screenshot({ path: '.suyou/screenshots/t260905-09-stacked-open.png', fullPage: true });  // naming-compat
    await clickChip(page); // 回到收折态，不污染后续腿
    await page.waitForTimeout(300);
    record('t2/screenshot-evidence', 'pass', '.suyou/screenshots/t260905-09-stacked-{folded,open}.png（折叠态/展开态对比）');  // naming-compat
  } catch (e) {
    record('t2/screenshot-evidence', 'env_fail', `截图失败：${String(e).slice(0, 100)}`);
  }
} catch (e) {
  record('t2/stacked', 'fail', `叠台断言异常（夹具注入/断言面崩溃须留证归因）：${String(e).slice(0, 200)}`);
}

// ---- T3 负向：普通消息零误折（验收②）----
{
  const negFx = loadFixtures().filter(f => f.name.startsWith('fx-91'));
  await injectPlatformBubbles(page, negFx);
  await page.waitForTimeout(800);
  const probe = await foldProbe(page);
  const neg = probe.bubbles.find(b => b.id.startsWith('fx-91'));
  record('t3/negative-no-fold', neg?.state === 'visible' && probe.chipCount === 1 ? 'pass' : 'fail',
    neg?.state === 'visible' && probe.chipCount === 1
      ? '中段提及普通消息全程可见、小条仍恰 1 条（零误折）'
      : `误折或小条数漂移：fx-91=${neg?.state}，chips=${probe.chipCount}`);
}

// ---- T4 孤儿守卫（验收③：叠加物清走无幽灵）----
try {
  await page.evaluate(() => { for (const el of document.querySelectorAll('[data-fx-id]')) el.remove(); });
  await page.waitForTimeout(800);
  const after = await foldProbe(page);
  record('t4/no-ghost-chip', after.bubbles.length === 0 && after.chipCount === 1 ? 'pass' : 'fail',
    after.bubbles.length === 0 && after.chipCount === 1
      ? '夹具气泡移除后小条回落 charter 配对（chips=1：charter 腿仍在）——幽灵检查通过'
      : `气泡残留=${after.bubbles.length}，chips=${after.chipCount}（0=叠加组小条未随气泡消失=幽灵；>1=残留叠加小条=幽灵）`);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  const reloaded = await foldProbe(page);
  record('t4/reload-no-revive', reloaded.bubbles.length === 0 ? 'pass' : 'fail',
    reloaded.bubbles.length === 0 ? 'reload 后夹具气泡不复活（DOM 夹具不入会话真值）' : `夹具气泡复活 ${reloaded.bubbles.length} 条——reload 前后断言基准被污染`);
} catch (e) {
  record('t4/orphan', 'fail', `孤儿守卫异常：${String(e).slice(0, 200)}`);
}
await browser.close();

// ---- T5 console 卫生（pageerror 面；removeChild 类 React 崩溃在此现形）----
record('t5/console-hygiene', pageErrors.length === 0 ? 'pass' : 'fail',
  pageErrors.length === 0 ? '零 pageerror' : `pageerror ${pageErrors.length} 条（若是 removeChild/appendChild 类 React 崩溃：外来节点×重渲染路径，须归因夹具手法还是产品缺陷，证据上报不许静默）：${pageErrors.join(' | ').slice(0, 240)}`);

summarize();
