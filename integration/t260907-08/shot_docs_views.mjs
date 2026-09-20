// shot_docs_views.mjs — t260907-08 走查证据子用例：docs 视图浅/深两档截图（隔离台）。
//
// 用途：UI 票验收证据（工单契约：改动前后截图落 .suyou/screenshots/）。改前/改后
//   各跑一遍（同一脚本、同一导航路径），产出 docs 视图浅档+深档两张截图，供
//   「浅色模式文档页字不可读」症状的肉眼对照。
// 红线：bootConsole 自举隔离台（随机端口），全程不触碰 3099/7233 真控制台；
//   teardownOnExit 全终态回收；playwright 缺失=env_fail exit 2 有声红（三态契约「闸内无 SKIP」）。
// 文档源=真库（docs/testing-guide.md 含围栏代码块，tok-* 高亮色入镜）。
//
// 用法：node integration/t260907-08/shot_docs_views.mjs --out .suyou/screenshots --tag before
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice,
} from '../t260904-17/lib_fix17.mjs';
import { TOKEN_SETS, cssVarsBlock } from '../t260905-08/lib_t260905_08.mjs';
import { mkdirSync } from 'node:fs';

const argOf = (name, def) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
};
const OUT_DIR = argOf('out', '.suyou/screenshots');
const TAG = argOf('tag', 'shot');

const die = (msg) => { console.error(`ENV_FAIL ${msg}`); process.exit(2); };
const pw = await loadPlaywright();
if (!pw) die('playwright-core 不可用（KI-036 家族）');

const stub = makeTicketStub();
let bench;
try {
  const projectsRoot = makeRegistryRoot('t0808-shot-reg-');
  writeProjectEntry(projectsRoot, 't08a', '截图夹具', [tmpRoot('t0808-shot-proj-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) { die(`隔离台自举失败：${String(e?.message ?? e).slice(0, 200)}`); }
teardownOnExit(bench.teardown);
if (bench.port === 3099 || bench.port === 7233) die(`端口红线：${bench.port}`);

mkdirSync(OUT_DIR, { recursive: true });
const { chromium } = pw;
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true }).catch(() => chromium.launch({ headless: true }));
} catch (e) { die(`浏览器缺失：${String(e?.message ?? e).slice(0, 120)}`); }

let fail = 0;
try {
  const page = await browser.newPage();
  // 侧栏入口需先有板面活动项目区——先走一遍工单列表入口把项目组点亮。
  for (const leg of ['light', 'dark']) {
    await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
    await page.addStyleTag({ content: cssVarsBlock(TOKEN_SETS[leg]) });
    await dismissNotice(page);
    // 点「文档」视图（侧栏项目组内图标，aria-label 确定锚）。
    const docBtn = page.locator('[aria-label="文档"], [title="文档"]').first();
    try { await docBtn.click({ timeout: 8000 }); }
    catch { await docBtn.evaluate((el) => el.click()); }
    await page.locator('.wb-doc-root').first().waitFor({ state: 'visible', timeout: 15000 });
    // 开一篇含围栏代码块的真库篇目（tok-* 高亮与复制钮入镜）。
    const item = page.locator('[data-wb-doc-item="testing-guide.md"]').first();
    try { await item.click({ timeout: 8000 }); }
    catch { await item.evaluate((el) => el.click()).catch(() => {}); }
    await page.locator('.wb-doc-body').first().waitFor({ state: 'visible', timeout: 15000 });
    await page.waitForTimeout(800); // 渲染静置
    const file = `${OUT_DIR}/t0808-docs-${leg}-${TAG}.png`;
    await page.screenshot({ path: file, fullPage: false });
    console.log(`[shot] ${leg} -> ${file}`);
  }
} catch (e) {
  fail = 1;
  console.error(`FAIL 截图子用例：${String(e?.message ?? e).slice(0, 300)}`);
} finally {
  await browser.close().catch(() => {});
}
console.log(fail === 0 ? 'SUMMARY pass=1 fail=0 env_fail=0 na=0' : 'SUMMARY pass=0 fail=1 env_fail=0 na=0');
process.exit(fail);
