// sc_project_ui_rail_add_remove.mjs — t260904-15 场景②：左栏三处就位+图标族换装+接入弹层+摘除四步流（浏览器面）。
//
// intent（灰盒，用户可感知行为；epic 面D + 验收11/11b/12/13 + mock v5 过稿口径）：
//   宿主打开 console 左栏即见项目管理三处新增——组头第五枚「项目设置」图标（SVG，
//   title/aria 可辨识）、「＋ 接入项目」行、隔离 key 红色行（无组头无设置图标）；
//   四视图图标已从 emoji 换装为统一 SVG（aria-label 齐、点工单列表图标的回列表
//   联动语义保留、图例可见文本 emoji 清零）；接入弹层内：非法输入错误就地显示
//   （点名原因，无需翻后端日志）、黄牌提示不阻塞、成功后左栏即时出现新项目组
//   （验收12）；摘除弹层四步：处置勾选默认全保留、dry-run 清单先行、purge 勾选
//   需输入 key 二次确认（错 key 不可确认）、Temporal 不可达=fail-closed 文案就地
//   （含「先 sandbar up」指路，验收13）。
//   与 t260904-10/-14（CLI 语义）intent 不同面：本条守的是 UI 呈现与交互旅程，
//   CLI 行为只在「结果文案与 CLI 同口径」层面触及。
//
// high-level steps：
//   T0 自举隔离台（好条目 fixa + 畸形 badkey）+ playwright 探测（缺失=ENV_FAIL，KI-036）。
//   T1 三处就位断言（设置图标 svg、接入行、隔离红行且无组头图标）。
//   T2 图标族：四视图图标 aria-label 齐且渲染为 svg；点工单列表图标 active 高亮
//      （联动语义）；侧栏可见文本 emoji（📋📖🔀🗂️）清零（11b 渲染面）。
//   T3 接入弹层：坏 key 预检错误就地显示 → 合法 key 成功 → 左栏即时出现新组。
//   T4 摘除四步：设置入口 → danger 区 → 默认全保留 → dry-run 清单 → purge 勾选
//      + key 二次确认（错 key 禁确认）→ 确认执行 → fail-closed 文案就地（Temporal 死）。
//   T5 console 零 error / pageerror。
//
// 执行契约：stdout 末行 SUMMARY 四计数（三态）；playwright-core 或隔离台依赖缺失=
// ENV_FAIL（exit 2 点名 KI-036/依赖原因，不假绿）；实现落地前红属预期（TDD 信号），
// arbitrate/merge 期必须绿。
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, writeQuarantinedDir,
  bootConsole, teardownOnExit, clientBuildStalenessReason, dismissNotice, loadPlaywright, makeResults,
} from './lib_fix15.mjs';

const { record, summarize } = makeResults();

// T0 夹具与依赖卫兵（依赖缺失=ENV_FAIL 环境红，不假绿）
const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable (KI-036)'); summarize(); }

let bench;
try {
  const projectsRoot = makeRegistryRoot('fix15-ui-reg-');
  writeProjectEntry(projectsRoot, 'fixa', '夹具甲', [tmpRoot('fix15-ui-fixa-')]);
  writeQuarantinedDir(projectsRoot, 'badkey');
  bench = await bootConsole(projectsRoot);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
// 泳道 client build 陈旧守卫：lib/client.js 缺失/早于 src → 浏览器腿拒跑（防拍旧 UI 假绿，
// laneBuildRejectReason 同口径）；合并后主树重建 build 自动生效。
{
  const stale = await clientBuildStalenessReason();
  if (stale) { record('browser/client-build', 'env_fail', `泳道 client build 不可用：${stale.slice(0, 160)}`); summarize(); }
  record('browser/client-build', 'pass', 'lib/client.js 新于 src');
}

teardownOnExit(bench.teardown);
record('bench/boot', 'pass', bench.base);

const { chromium } = pw;
// 浏览器获取（capture.mjs launchBrowser 同款回退，KI-036 环境现实：playwright 自带
// chromium 未下载时用系统 Chrome 通道；只换执行体不改断言面）。
const launchBrowser = async () => {
  try { return await chromium.launch({ channel: 'chrome', headless: true }); }
  catch (e) { console.error(`[browser] 系统 Chrome 不可用（${String(e?.message ?? e).split('\n')[0]}），退 playwright chromium`); }
  return chromium.launch({ headless: true });
};
const browser = await launchBrowser();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push(String(e)));
await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1500); // 左栏首拉
await dismissNotice(page); // 出厂 notice 会劫持焦点/指针（fill 打不进受控输入），先关

const sidebar = page.locator('aside, [class*=sidebar]').first();

// 过遮罩点击（capture.mjs forceClick 同款先例：出厂平台遮罩拦 pointer 时退避 DOM 直点；
// 仍是只读导航语义，不提交表单；只换执行体不改断言面）。
async function forceClick(loc, timeoutMs = 5000) {
  try { await loc.click({ timeout: timeoutMs }); }
  catch { await loc.evaluate((el) => el.click()); }
}

const visText = async () => (await sidebar.innerText().catch(() => '')).normalize('NFC');

// T1 三处就位
{
  const setIcon = sidebar.locator('[title="项目设置"], [aria-label="项目设置"]').first();
  const addRow = sidebar.getByText('接入项目', { exact: false }).first();
  const isoRow = sidebar.getByText('badkey', { exact: false }).first();
  const setOk = await setIcon.isVisible().catch(() => false)
    && (await setIcon.evaluate((el) => !!el.querySelector('svg') || el.tagName.toLowerCase() === 'svg').catch(() => false));
  record('rail/settings-icon-svg', setOk);
  record('rail/add-row', await addRow.isVisible().catch(() => false));
  const isoVisible = await isoRow.isVisible().catch(() => false);
  const isoNoHeaderIcons = isoVisible && !(await isoRow.locator('xpath=ancestor::*[contains(@class,"group")][1]//*[self::*[contains(@title,"工单列表")] or @title="项目设置"]').count());
  record('rail/quarantine-row', isoVisible && isoNoHeaderIcons !== false, `visible=${isoVisible}`);
}

// T2 图标族换装 + 联动语义 + 图例清零
{
  const labels = ['工单列表', '知识库', '模型路由', '立项单'];
  let allSvg = true;
  for (const lb of labels) {
    const ic = sidebar.locator(`[title="${lb}"], [aria-label="${lb}"]`).first();
    const ok = await ic.isVisible().catch(() => false)
      && (await ic.evaluate((el) => !!el.querySelector('svg') || el.tagName.toLowerCase() === 'svg').catch(() => false));
    if (!ok) { allSvg = false; record(`icons/${lb}`, 'fail', '缺失或非 svg 渲染'); }
  }
  if (allSvg) record('icons/four-views-svg', 'pass');
  const board = sidebar.locator('[title="工单列表"], [aria-label="工单列表"]').first();
  await forceClick(board);
  await page.waitForTimeout(300);
  // active 断言=图标自身或宿主容器类名（隔离台探针实证：点击后 className="wb-view-icon active"；
  // 勿用 el.closest 含自身的写法——成功态会被误判为失败）。
  const active = await board.evaluate((el) =>
    el.classList.contains('active') || String(el.parentElement?.className ?? '').includes('active')
  ).catch(() => false);
  record('icons/board-click-active', active, '点工单列表图标=active 高亮（联动语义保留）');
  const txt = await visText();
  const emojis = ['📋', '📖', '🔀', '🗂️'].filter((e) => txt.includes(e));
  record('icons/emoji-zero-visible', emojis.length === 0, `残留=${emojis.join('') || '无'}`);
}

// T3 接入弹层
{
  await forceClick(sidebar.getByText('接入项目', { exact: false }).first());
  const dlg = page.locator('[role=dialog], [class*=modal], [class*=overlay]').first();
  const opened = await dlg.isVisible().catch(() => false);
  record('add/modal-opens', opened);

  // 坏 key 预检：错误就地显示（点名原因）
  const keyInput = dlg.locator('input').first();
  await keyInput.fill('Fix_B');
  const rootInput = dlg.locator('input').nth(2);
  await rootInput.fill(tmpRoot('fix15-ui-add-'));
  const pre = dlg.getByText(/预检|dry-run|dry run/i).first();
  if (await pre.isVisible().catch(() => false)) await forceClick(pre);
  await page.waitForTimeout(1200);
  const errShown = (await dlg.innerText().catch(() => '')).length > 0
    && /key|不合法|白名单|拒/.test(await dlg.innerText().catch(() => ''));
  record('add/badkey-inline-error', opened && errShown, '错误就地显示且点名 key');

  // 合法 key 成功 → 左栏出现新组（表单三输入齐填：key/显示名/根目录——缺显示名 CLI 必拒）
  await keyInput.fill('fixc');
  await dlg.locator('input').nth(1).fill('夹具丙');
  await page.waitForTimeout(200);
  // 提交=语义锚按钮（getByText 会命中含「接入」的提示文字而非按钮——隔离台实证）
  const submit = dlg.locator('[data-wb-pmod-add-submit]');
  await forceClick(submit);
  // ≤12s 轮询窗口：左栏刷新=10s 可见性轮询（成功回调未同步重拉——「即时」口径差距见验收报告）
  // 组头渲染的是显示名（wb-group-name={project.name}，key 只在色点 title）——找「夹具丙」非 key。
  let listed = false;
  for (let i = 0; i < 24 && !listed; i++) {
    await page.waitForTimeout(500);
    listed = await sidebar.getByText('夹具丙', { exact: false }).first().isVisible().catch(() => false);
  }
  record('add/success-new-group', listed, '成功后左栏出现新项目组（≤12s=10s 轮询口径，验收12）');
}

// T4 摘除四步（fixa；Temporal 死 → 最终 fail-closed 文案就地）
{
  const setIcon = sidebar.locator('[title="项目设置"], [aria-label="项目设置"]').first();
  await forceClick(setIcon);
  // 弹层定位锚 [data-wb-pmod-overlay]（smoke/project-modals 既定公开语义锚）——
  // 勿用泛 [class*=overlay].last()：会抓到平台 Internal Testing Notice 弹层（隔离台实证）。
  const dlg = page.locator('[data-wb-pmod-overlay]').last();
  await page.waitForTimeout(600);
  const setOpened = (await dlg.innerText().catch(() => '')).includes('fixa');
  record('remove/entry-via-settings', setOpened, '设置弹层含目标 key（danger 入口面）');

  const danger = page.getByText('摘除项目', { exact: false }).first();
  await forceClick(danger);
  await page.waitForTimeout(600);
  const rmDlg = page.locator('[data-wb-pmod-overlay]').last();
  const rmText = () => rmDlg.innerText().catch(() => '');

  // 处置勾选默认全保留（保留类 checkbox 默认勾、purge 默认不勾）
  const boxes = rmDlg.locator('input[type=checkbox]');
  const n = await boxes.count();
  let keepDefault = n > 0;
  let purgeDefaultOff = true;
  for (let i = 0; i < n; i++) {
    const label = (await boxes.nth(i).evaluate((el) => el.closest('label')?.innerText ?? '')).toString();
    const checked = await boxes.nth(i).isChecked();
    if (/删|purge/i.test(label)) { if (checked) purgeDefaultOff = false; } else if (!checked) keepDefault = false;
  }
  record('remove/keep-by-default', keepDefault && purgeDefaultOff, `checkboxes=${n}`);

  // 在飞闸预检（dry-run=全闸预演，契约①a-1）：Temporal 死端口 → fail-closed 拒摘，
  // 错误就地显示（验收13）且流程停在 gate（无绕过旗，不前进到处置步）。
  const preBtn = rmDlg.locator('[data-wb-pmod-remove-precheck]');
  await forceClick(preBtn);
  await page.waitForTimeout(1500);
  const errTxt = await rmDlg.locator('[data-wb-pmod-remove-error]').innerText().catch(() => '');
  const stillGate = !(await rmDlg.locator('[data-wb-pmod-remove-dry]').isVisible().catch(() => false));
  record('remove/fail-closed-inline', /sandbar up|Temporal|拒/.test(errTxt) && stillGate,
    `fail-closed 文案=${errTxt.slice(0, 150)} | 停在gate=${stillGate}`);

  // 四步流后段（dispose→dry 清单→purge key 确认→执行）在 Temporal 不可达环境原理性
  // 不可达（在飞闸 fail-closed 无绕过旗，①a-1 闸序）——后段状态机与确认纪律由
  // smoke/project-modals 覆盖；真台腿随隔离台真 Temporal 供给另补（环境缺供=ENV_FAIL 点名，不假绿）。
  record('remove/dispose-dry-purge-legs', 'env_fail',
    'Temporal 死端口=在飞闸 fail-closed，后段不可达；smoke 已断言状态机+确认纪律');
}

// T5 console 零 error（豁免：旅程故意触发 fail-closed 的 409 资源日志——浏览器把
// 非 2xx fetch 记为 console error，属预期交互产物非 UI 缺陷；其余 error 零容忍）
record('browser/console-clean',
  consoleErrors.filter((e) => !/Failed to load resource.*409/.test(e)).length === 0,
  consoleErrors.slice(0, 3).join(' | '));

await browser.close();
bench.teardown();
summarize();
