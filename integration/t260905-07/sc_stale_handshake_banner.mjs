// sc_stale_handshake_banner.mjs — t260905-07 场景②：插件 staleness 握手横幅注入实验（KI-052 根治面）。
//
// intent（灰盒，用户可感知行为；工单验收③ + gen2 判定矩阵 M1-M7 + gen1 打回①序列全覆盖）：
//   「盘上 bundle×进程内存模块」版本错窗可见化——fixture 真拷贝 server/dsh（boot/盘指纹
//   都算 fixture 文件，capture-stale-banner.mjs 先例：控制台行为全真，只有「落账」由脚本
//   触发），五分支双向断言（在场方向×3 + 不在场方向×2）：
//     M5 新鲜态：boot==disk==注入 → 横幅不在场（等满一个 30s 轮询窗才判「不在场」）。
//     M1 盘新内存旧：改 fixture node.ts → 新开页（注入=新盘指纹）≠ boot → 「重启控制台
//        生效」横幅在场，且「刷新」文案不在场（文案与消除动作绑定：M1 消除动作=重启）。
//     M2 看守自身内存旧（KI-052 主现场）：拦截 build-info 应答 405 → 重启横幅在场
//        （旧看守把 405 静默=立案现场，根治判据=405 也出横幅）。
//     M4 跨重启存活页面（gen1 打回①序列）：改盘+同端口重起台 → 同一页面继续轮询
//        （boot==disk 一致、注入=旧盘态）→ 出「刷新页面生效」支且重启文案不在场
//        （重启对该态无效，消除动作=刷新）→ 刷新页面后横幅消失（M5 复验）。
//        该序列是 gen1 前方案「测过但现场翻车」的同构复发窗：场景时序必须同页跨重启。
//     M5 复验：盘码未动+重起台 → 新开页 → 不在场（同构消失方向：重启不制造假横幅）。
//   文案断言锚=源码常量 banner-text.ts（KI-051 锚纪律）：常量模块缺失=FAIL 点名
//   「锚常量未落地」，不以裸字面量蒙混该断言（机制分支的文案比对才回退字面量保跑通）。
//
// 红线：临时端口 + 临时 DSH_HOME（退出即删）+ 零 3099/7233 接触 + 不 seed 真数据。
// 依赖：主树 playwright-core（KI-036 家族，缺失=ENV_FAIL exit 2）；preset 源缺失=ENV_FAIL。
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na；实现落地前红属预期（TDD 信号），
//   arbitrate/merge 期必须绿。
//
// high-level steps：
//   T0 fixture 注入台起台（拷贝/临时 profile/preset）+ playwright 探测 + 锚常量加载。
//   T1 page1 新开页新鲜态：等满轮询窗 → 横幅不在场（M5）。
//   T2 改 fixture node.ts → page2 新开页 → 「重启」横幅在场且「刷新」文案不在场（M1）。
//   T3 page3 拦截 build-info=405 → 「重启」横幅在场（M2，KI-052 主现场）。
//   T4 同端口重起台（盘已改）→ page1 同页轮询 → 「刷新」横幅在场且「重启」文案不在场
//      （M4）→ page1 刷新 → 等满轮询窗 → 横幅不在场（M5 消失）。
//   T5 再重起台（盘码未动）→ page4 新开页 → 横幅不在场（M5 复验）。
//   T6 红线：端口 ≠ 3099/7233；finally 回收进程树/浏览器/临时目录。

import { appendFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  loadPlaywright, dismissNotice, teardownOnExit, makeResults, loadBannerTexts, FALLBACK_TEXTS,
  makeFixtureConsole,
} from './lib_t260905.mjs'

const { record, summarize } = makeResults();

// 轮询窗：客户端 30s 可见性轮询。「不在场」断言必须等满一个完整轮询窗才有判据。
const POLL_WAIT_MS = Number(process.env.SANDBAR_T07_POLL_WAIT_MS || 40_000);
// 在场等待：≥2 个轮询窗（重起台就绪后首个轮询即可命中，留抖动余量）。
const APPEAR_WAIT_MS = Number(process.env.SANDBAR_T07_APPEAR_WAIT_MS || 75_000);

const texts = await loadBannerTexts();
const BANNER = texts?.STALE_BANNER_TEXT ?? FALLBACK_TEXTS.STALE_BANNER_TEXT;
const RELOAD = texts?.STALE_RELOAD_TEXT ?? FALLBACK_TEXTS.STALE_RELOAD_TEXT;

let fixture;
try {
  fixture = await makeFixtureConsole();
} catch (e) {
  record('sb/fixture-boot', 'env_fail', `注入台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
try {
  await fixture.start();
} catch (e) {
  record('sb/fixture-boot', 'env_fail', `注入台起台失败：${String(e?.message ?? e).slice(0, 200)}`);
  await fixture.teardown();
  summarize();
}
teardownOnExit(fixture.teardown);
record('sb/fixture-boot', true, fixture.base);
record('sb/redline-ports', fixture.port !== 3099 && fixture.port !== 7233, `port=${fixture.port}（3099/7233 零接触）`);

// (v) 文案锚常量：源码侧加载（KI-051）。缺失=FAIL 点名——此断言不回退字面量。
record('sb/anchor-constants', texts !== null,
  texts ? `banner-text.ts 常量在：重启支=「${BANNER}」/刷新支=「${RELOAD}」`
        : 'banner-text.ts 锚常量未落地（KI-051 纪律：场景断言必须 import 常量）');

const pw = await loadPlaywright();
if (!pw) {
  record('sb/playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：真点腿环境红');
  summarize();
}
const { chromium } = pw;
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => chromium.launch({ headless: true }));
} catch (e) {
  record('sb/browser', 'env_fail', `浏览器不可用：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`);
  summarize();
}

const bannerTextOf = (page) => page.evaluate(() =>
  [...document.querySelectorAll('.wb-stale-banner')].map((e) => e.textContent || '').join('\n'));
const bannerCount = (page) => page.locator('.wb-stale-banner').count();
const newPage = async () => {
  const page = await browser.newPage();
  await page.goto(`${fixture.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  return page;
};
const waitBannerAppear = (page, timeout) => page.locator('.wb-stale-banner')
  .first().waitFor({ state: 'visible', timeout }).then(() => true).catch(() => false);
// 等横幅文案包含目标支（30s 轮询粒度：横幅可能已在场、文案要等下一轮询才翻转——
// 例如 M4 序列里页面在「改盘→重启」窗口先目击 stale=true 的重启支（当时真实），
// 重启后首个轮询才翻到刷新支；断言必须等翻转完成，不得见横幅即取文本）。
const waitBannerText = async (page, needle, timeout) => {
  const t0 = Date.now();
  for (;;) {
    const txt = await bannerTextOf(page).catch(() => '');
    if (txt.includes(needle)) return true;
    if (Date.now() - t0 > timeout) return false;
    await page.waitForTimeout(1000);
  }
};

const OUT_DIR = join(process.cwd(), '.suyou', 'screenshots', 't260905-07');  // naming-compat

try {
  // T1 M5 新鲜态：boot==disk==注入 → 不在场
  const page1 = await newPage();
  await page1.waitForTimeout(POLL_WAIT_MS);
  record('sb/m5-fresh-absent', (await bannerCount(page1)) === 0,
    `新鲜态等满 ${Math.round(POLL_WAIT_MS / 1000)}s 轮询窗：横幅数=${await bannerCount(page1)}（期望 0）`);

  // T2 M1 盘新内存旧（注入实验 (i)）：改盘 → 新开页（注入新指纹）≠ boot
  appendFileSync(join(fixture.fixtureWb, 'node.ts'), '\n// t260905-07 stale mutation M1\n');
  const page2 = await newPage();
  const m1 = await waitBannerAppear(page2, APPEAR_WAIT_MS);
  const m1Text = m1 ? await bannerTextOf(page2) : '';
  record('sb/m1-restart-banner', m1 && m1Text.includes(BANNER) && !m1Text.includes(RELOAD),
    `M1 横幅在场=「${m1Text.slice(0, 40)}」（须重启支、非刷新支——消除动作=重启正确）`);
  await page2.screenshot({ path: join(OUT_DIR, 'stale-m1-restart.png') }).catch(() => {});

  // T3 M2 看守自身内存旧（注入实验 (iii)）：build-info 405（KI-052 主现场：内存无此路由）
  const page3 = await browser.newPage();
  await page3.route('**/sandbar-workbench/api/build-info', (route) => route.fulfill({
    status: 405, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'build-info 只支持 GET（只读看守）' }),
  }));
  await page3.goto(`${fixture.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page3);
  const m2 = await waitBannerAppear(page3, APPEAR_WAIT_MS);
  const m2Text = m2 ? await bannerTextOf(page3) : '';
  record('sb/m2-405-ki052-banner', m2 && m2Text.includes(BANNER),
    `405 注入后横幅在场=「${m2Text.slice(0, 40)}」（旧看守 405 静默=立案现场，根治判据）`);
  await page3.screenshot({ path: join(OUT_DIR, 'stale-m2-405.png') }).catch(() => {});
  await page3.unroute('**/sandbar-workbench/api/build-info');
  await page3.close();

  // T4 M4 跨重启存活页面（gen1 打回①序列）：同端口重起台（boot 收编已改盘）→ page1 同页轮询
  //   page1 注入=改盘前指纹（下载时刻盘态）；重起后 boot==disk（一致）而注入旧 → 刷新支。
  await fixture.restart();
  const m4 = await waitBannerText(page1, RELOAD, APPEAR_WAIT_MS + 60_000);
  const m4Text = m4 ? await bannerTextOf(page1) : '';
  record('sb/m4-cross-restart-refresh', m4 && m4Text.includes(RELOAD) && !m4Text.includes(BANNER),
    `跨重启存活页面横幅=「${m4Text.slice(0, 40)}」（须翻转并稳定在刷新支、重启文案不得在场——重启对该态无效）`);
  await page1.screenshot({ path: join(OUT_DIR, 'stale-m4-refresh.png') }).catch(() => {});
  await page1.reload({ waitUntil: 'domcontentloaded' });
  await dismissNotice(page1);
  await page1.waitForTimeout(POLL_WAIT_MS);
  record('sb/m4-after-reload-absent', (await bannerCount(page1)) === 0,
    `刷新后（注入=新盘态）等满轮询窗：横幅数=${await bannerCount(page1)}（期望 0=消除动作可达）`);
  await page1.close();
  await page2.close();

  // T5 M5 复验（注入实验 (ii)）：盘码未动+重起台 → 新开页 → 不在场
  await fixture.restart();
  const page4 = await newPage();
  await page4.waitForTimeout(POLL_WAIT_MS);
  record('sb/m5-restart-unchanged-absent', (await bannerCount(page4)) === 0,
    `盘码未动重起台后新开页：横幅数=${await bannerCount(page4)}（期望 0=重启不制造假横幅）`);
  await page4.close();
} catch (e) {
  record('sb/unexpected', false, `场景异常：${String(e?.message ?? e).slice(0, 200)}`);
} finally {
  try { await browser?.close(); } catch { /* 已关 */ }
}
summarize();
