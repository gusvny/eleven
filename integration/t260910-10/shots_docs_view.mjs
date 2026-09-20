// shots_docs_view.mjs — t260910-10 走查证据子用例：docs 视图改前/改后截图（隔离台）。
//
// 用途：UI 票验收证据（工单契约：改动前后截图落 .sandbar/screenshots/）。改前/改后
//   各跑一遍（同一脚本、同一导航路径，--tag 区分），产出宽栏+窄容器两张截图，
//   供 KI-070 UI 重做的肉眼对照。
// 红线：bootConsole 自举隔离台（随机端口），全程不触碰 3099/7233 真控制台；
//   teardownOnExit 全终态回收；playwright 缺失=env_fail exit 2 有声红（三态契约）。
// 文档源：夹具项目 docp 自带 docs/（KI-070 改后=项目锚下读夹具自己的 docs；
//   改前=旧单仓硬编码，夹具 docs 不可读——这正是本票症状，截图如实记录）。
//
// 用法：node integration/t260910-10/shots_docs_view.mjs --tag before [--out .sandbar/screenshots]
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice,
} from '../t260904-17/lib_fix17.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const argOf = (name, def) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
};
const OUT_DIR = argOf('out', '.sandbar/screenshots');
const TAG = argOf('tag', 'shot');

const die = (msg) => { console.error(`ENV_FAIL ${msg}`); process.exit(2); };
const pw = await loadPlaywright();
if (!pw) die('playwright-core 不可用（KI-036 家族）');

// 夹具项目：自带 docs/ 与 notes/（非 sandbar 内容，KI-070 场景真读面）。
const projDir = tmpRoot('t0910-shot-proj-');
mkdirSync(join(projDir, 'docs', 'guide'), { recursive: true });
mkdirSync(join(projDir, 'notes'), { recursive: true });
writeFileSync(join(projDir, 'docs', 'handbook.md'),
  '---\ntitle: 项目手册\nstatus: draft\nupdated: 2026-09-10\ncategory: guide\n---\n\n# 项目手册\n\n夹具项目自己的文档。\n\n## 快速上手\n\n第一段。\n\n### 前置条件\n\n第二段。\n\n## 常见问题\n\n第三段。\n');
writeFileSync(join(projDir, 'docs', 'guide', 'deep.md'), '---\ntitle: 深层篇目\n---\n\n# 深层篇目\n\n正文。\n');
writeFileSync(join(projDir, 'notes', 'README.md'), '# 观察窗\n\n夹具 notes。\n');

const stub = makeTicketStub();
let bench;
try {
  const projectsRoot = makeRegistryRoot('t0910-shot-reg-');
  writeProjectEntry(projectsRoot, 'docp', '文档夹具', [projDir]);
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
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await page.waitForTimeout(500);
  const docBtn = page.locator('[aria-label="文档"], [title="文档"]').first();
  try { await docBtn.click({ timeout: 8000 }); }
  catch { await docBtn.evaluate((el) => el.click()); }
  await page.locator('.wb-doc-root').first().waitFor({ state: 'visible', timeout: 15000 });
  // 开一篇真库篇目入镜（改前=引擎仓 docs；改后同路径，版面新旧对照锚同一篇）。
  const item = page.locator('[data-wb-doc-item="testing-guide.md"]').first();
  if (await item.isVisible().catch(() => false)) {
    await item.click();
    await page.waitForTimeout(1200);
  }
  await page.screenshot({ path: join(OUT_DIR, `t260910-10-${TAG}-wide.png`) });

  // 窄容器形态（@container 360px 单栏流）。
  await page.evaluate(() => {
    const el = document.querySelector('[data-wb-docs-root], .wb-doc-root');
    if (el) { el.style.width = '360px'; el.style.maxWidth = '360px'; el.style.height = '480px'; }
  });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(OUT_DIR, `t260910-10-${TAG}-narrow.png`) });
  console.log(`SHOTS_OK tag=${TAG} out=${OUT_DIR}`);
} catch (e) {
  fail = 1;
  console.error(`SHOTS_FAIL tag=${TAG}: ${String(e?.message ?? e).slice(0, 200)}`);
} finally {
  await browser.close().catch(() => {});
  bench.teardown();
}
process.exit(fail === 0 ? 0 : 1);
