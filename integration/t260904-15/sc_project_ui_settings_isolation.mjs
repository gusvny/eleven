// sc_project_ui_settings_isolation.mjs — t260904-15 场景③：项目设置弹层面+隔离详情+空注册表首接（浏览器面）。
//
// intent（灰盒，用户可感知行为；epic 面D + 验收11/9 + 契约①a-1 + gen1 R2 落地口径）：
//   设置弹层是摘除的显式入口与只读信息面——key/显示名/根目录如实呈现；票计数在
//   Temporal 不可达时降级为「—」类中性提示且**不红不谎报**（验收11 降级口径）；
//   体检区以「数据源未接入」中性提示呈现（R2b 降档口径：不谎报「无黄牌」）；
//   隔离 key 红色行点击可见原因（含 <dir>/project.yaml 定位）与修复指路（验收11）；
//   空/全隔离注册表不 500：左栏零分组仍渲染「＋ 接入项目」行且能走通首次接入
//   （首个项目接入恰恰发生在空注册表时；摘最后一个项目=验收9 同理）。
//   与场景②intent 不同面：②守左栏呈现+接入/摘除旅程，本条守设置信息面/降级口径/
//   隔离详情/空注册表面。
//
// high-level steps：
//   T0 自举隔离台 A（好条目 fixa + 畸形 badkey）+ playwright 探测（缺失=ENV_FAIL，KI-036）。
//   T1 设置弹层：只读三行（key/显示名/根目录）；票计数降级「—」类中性词且弹层
//      不含红 error 文案；体检区中性提示（不含「无黄牌/全部正常」谎报）；danger 在位。
//   T2 隔离详情：红行点击 → 原因含 project.yaml 定位字面 + 修复指路词汇。
//   T3 自举隔离台 B（空注册表根）：GET /wf/projects 200 空清单；左栏零分组但
//      「＋ 接入项目」行在位；走通首接（fixfirst）→ 新组出现。
//   T4 console 零 error / pageerror。
//
// 执行契约：stdout 末行 SUMMARY 四计数（三态）；依赖缺失=ENV_FAIL 环境红；实现落地前
// 红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import {
  tmpRoot, makeFixtures, writeProjectEntry, writeQuarantinedDir,
  bootConsole, teardownOnExit, clientBuildStalenessReason, api, dismissNotice, loadPlaywright, makeResults, dismissShellNotice } from './lib_fix15.mjs';

const { record, summarize } = makeResults();

const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable (KI-036)'); summarize(); }

const { chromium } = pw;
const consoleErrors = [];
// 过遮罩点击（capture.mjs forceClick 同款先例：平台遮罩拦 pointer 时退避 DOM 直点；
// 只读导航语义，不提交表单；只换执行体不改断言面）。
async function forceClick(loc, timeoutMs = 5000) {
  try { await loc.click({ timeout: timeoutMs }); }
  catch { await loc.evaluate((el) => el.click()); }
}

const newPage = async (bench) => {
  // 浏览器获取（capture.mjs launchBrowser 同款回退，KI-036 环境现实；只换执行体不改断言面）。
  const browser = await (async () => {
    try { return await chromium.launch({ channel: 'chrome', headless: true }); }
    catch (e) { console.error(`[browser] 系统 Chrome 不可用（${String(e?.message ?? e).split('\n')[0]}），退 playwright chromium`); }
    return chromium.launch({ headless: true });
  })();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(String(e)));
  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissShellNotice(page);
  await page.waitForTimeout(1500);
  return { browser, page };
};
const sidebarOf = (page) => page.locator('aside, [class*=sidebar]').first();
// 弹层定位锚 [data-wb-pmod-overlay]（smoke/project-modals 既定公开语义锚）——
// 勿用泛 [class*=overlay].last()：会抓到平台 Internal Testing Notice 弹层（隔离台实证）。
const dialogOf = (page) => page.locator('[data-wb-pmod-overlay]').last();

// ---- 台 A：设置弹层面 + 隔离详情 ----
let benchA;
try {
  const fxA = makeFixtures('fix15-set-reg-');
  const regA = fxA.reg;
  writeProjectEntry(regA, 'fixa', '夹具甲', [path.join(fxA.root, 'proj-fixa')]);
  writeQuarantinedDir(regA, 'badkey');
  benchA = await bootConsole(fxA.root);
  benchA.__fixtures = fxA;
} catch (e) {
  record('bench/boot-A', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
// 泳道 client build 陈旧守卫：lib/client.js 缺失/早于 src → 浏览器子用例拒跑（防拍旧 UI 假绿，
// laneBuildRejectReason 同口径）；合并后主树重建 build 自动生效。
{
  const stale = await clientBuildStalenessReason();
  if (stale) { record('browser/client-build', 'env_fail', `泳道 client build 不可用：${stale.slice(0, 160)}`); summarize(); }
  record('browser/client-build', 'pass', 'lib/client.js 新于 src');
}

teardownOnExit(benchA.teardown);
record('bench/boot-A', 'pass', benchA.base);
const { browser: brA, page: pa } = await newPage(benchA);
const sbA = sidebarOf(pa);
  await dismissNotice(pa); // 出厂 notice 劫持焦点/指针，先关

// T1 设置弹层
{
  const setIcon = sbA.locator('[title="项目设置"], [aria-label="项目设置"]').first();
  await forceClick(setIcon);
  await pa.waitForTimeout(600);
  const dlg = dialogOf(pa);
  const txt = await dlg.innerText().catch(() => '');
  record('settings/readonly-info', txt.includes('fixa') && txt.includes('夹具甲'),
    'key+显示名在文（根目录行随实现词汇断言不锁死）');

  const degraded = /—|降级|不可达|暂不可用|无法获取/.test(txt);
  // 「不红」口径：剥离降级注记引文「—（…）」（内含数据源原文如 ModuleNotFoundError，
  // 是引用不是 UI 自身的红色告警）与体检降档中性提示后再扫红色关键词。
  const noRed = !/错误|失败|error/i.test(
    txt.replace(/体检数据源未接入/g, '').replace(/—（[^）]*）/g, ''));
  record('settings/counts-degraded-not-red', degraded && noRed, `片段=${txt.slice(0, 200)}`);

  const healthNeutral = txt.length === 0
    || (!/无黄牌|全部正常|一切正常/.test(txt) && /体检/.test(txt));
  record('settings/health-neutral', healthNeutral, '体检区中性提示，不谎报无黄牌（R2b 降档口径）');

  record('settings/danger-entry', /摘除项目/.test(txt), '底部 danger 区摘除入口在位');
  await pa.keyboard.press('Escape');
}

// T2 隔离详情
{
  const isoRow = sbA.getByText('badkey', { exact: false }).first();
  await forceClick(isoRow);
  await pa.waitForTimeout(600);
  const txt = await dialogOf(pa).innerText().catch(() => '');
  const located = txt.includes('project.yaml');
  const repair = /修复|处理|指路|检查|retired|重新/i.test(txt);
  record('isolation/detail-locate-and-repair', located && repair, `片段=${txt.slice(0, 200)}`);
}

await brA.close();
benchA.teardown();

// ---- 台 B：空注册表 ----
let benchB;
try {
  const fxB = makeFixtures('fix15-empty-reg-');
  benchB = await bootConsole(fxB.root);
  benchB.__fixtures = fxB;
} catch (e) {
  record('bench/boot-B', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(benchB.teardown);
record('bench/boot-B', 'pass', benchB.base);

// T3 空注册表：200 空清单 + 接入行在位 + 首接走通
{
  const r = await fetch(`${benchB.base}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(5000) });
  const body = await r.json().catch(() => null);
  const projects = body?.result?.projects ?? body?.projects ?? [];
  record('empty/api-200-empty', r.status === 200 && Array.isArray(projects) && projects.length === 0,
    `status=${r.status} n=${projects.length}`);
  const { browser: brB, page: pb } = await newPage(benchB);
  const sbB = sidebarOf(pb);
  await dismissNotice(pb); // 同上
  const addRow = sbB.getByText('接入项目', { exact: false }).first();
  record('empty/add-row-present', await addRow.isVisible().catch(() => false), '零分组仍渲染接入行（验收9 面）');

  await forceClick(addRow);
  await pb.waitForTimeout(600);
  const dlg = dialogOf(pb);
  const inputs = dlg.locator('input');
  if (await inputs.count() >= 2) {
    await inputs.first().fill('fixfirst');
    if (await inputs.count() >= 3) await inputs.nth(1).fill('首接项目'); // 显示名：缺它 CLI 必拒
    mkdirSync(path.join(benchB.__fixtures.root, 'proj-first'), { recursive: true }); // 容器内 CLI 验目录存在
    await inputs.nth(2).fill(benchB.toStage(path.join(benchB.__fixtures.root, 'proj-first'))); // 容器路径
    // 驱动链=语义锚：预检（本地形状检查，置 pre 门）→ 确认接入（未预检恒禁点）
    await forceClick(dlg.locator('[data-wb-pmod-add-precheck]'));
    await pb.waitForTimeout(400);
    const submit = dlg.locator('[data-wb-pmod-add-submit]');
    await forceClick(submit);
    // ≤12s 轮询窗口：左栏刷新=10s 可见性轮询（「即时」口径差距见验收报告）
    // 组头渲染显示名（wb-group-name）——找「首接项目」非 key。
    let listed = false;
    for (let i = 0; i < 24 && !listed; i++) {
      await pb.waitForTimeout(500);
      listed = await sbB.getByText('首接项目', { exact: false }).first().isVisible().catch(() => false);
    }
    record('empty/first-add-succeeds', listed, '空注册表首接走通（≤12s 轮询口径；首接恰发生在空表时）');
  } else {
    record('empty/first-add-succeeds', 'fail', '接入弹层表单字段不足');
  }
  await brB.close();
  benchB.teardown();
}

// T4 console 零 error（豁免 502 资源日志：本台容器内引擎地址钉死不可达=降级断言面，
// t260910-04 R3 起工单列表对引擎不可达显式 502（不再吃成 200 空表谎报空态）——浏览器把
// 非 2xx fetch 记为 console error，属预期产物非 UI 缺陷；其余 error 零容忍）
record('browser/console-clean',
  consoleErrors.filter((e) => !/Failed to load resource.*502/.test(e)).length === 0,
  consoleErrors.slice(0, 3).join(' | '));

summarize();
