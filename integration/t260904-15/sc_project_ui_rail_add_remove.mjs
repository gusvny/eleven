// sc_project_ui_rail_add_remove.mjs — t260904-15 场景②：左栏三处就位+退役面守夜+接入弹层+摘除四步流（浏览器面）。
//
// intent（灰盒，用户可感知行为；epic 面D + 验收11/11b/12/13 + mock v5 过稿口径）：
//   宿主打开 console 左栏即见项目管理三处新增——「＋ 接入项目」行、隔离 key 红色行
//   （无组头、无设置入口）、项目设置面可达。
//   Since t261008-36 (host order 261008, "one face, one home") the settings face has
//   ONE door: the project row's executor panel Settings tab (project row →
//   [data-wb-executor-entry] → [data-tab="settings"] →
//   [data-wb-panel-face="project-settings"]). That order retired the whole
//   group-header icon family (the four view icons had already gone with their views
//   in t261005-10 UI-2), so this scenario asserts the family ABSENT by name — a
//   resurrection turns it red — and no longer asserts icon rendering or icon-click
//   highlighting (a subject those icons gave the rail; see the T2 retirement note).
//   The sidebar visible text still carries zero emoji (acceptance 11b rendering face).
//   接入弹层内：非法输入错误就地显示
//   （点名原因，无需翻后端日志）、黄牌提示不阻塞、成功后左栏即时出现新项目组
//   （验收12）；摘除弹层四步：处置勾选默认全保留、dry-run 清单先行、purge 勾选
//   需输入 key 二次确认（错 key 不可确认）、Temporal 不可达=fail-closed 文案就地
//   （含「先 sandbar up」指路，验收13）。
//   与 t260904-10/-14（CLI 语义）intent 不同面：本条守的是 UI 呈现与交互旅程，
//   CLI 行为只在「结果文案与 CLI 同口径」层面触及。
//
// high-level steps：
//   T0 自举隔离台（好条目 fixa + 畸形 badkey）+ playwright 探测（缺失=ENV_FAIL，KI-036）。
//   T1 three additions: the settings face is reachable through the panel door
//      ([data-wb-executor-entry] → panel Settings tab → project-settings face),
//      the add row is present, the quarantined red row names its key and hangs
//      under no group header.
//   T2 retirement watch: the group-header icon family (four view icons, the
//      settings icon and the More-views toggle) is absent by name; visible
//      sidebar text carries zero emoji (📋📖🔀🗂️) (11b rendering face).
//   T3 接入弹层：坏 key 预检错误就地显示 → 合法 key 成功 → 左栏即时出现新组。
//   T4 摘除四步：设置面（面板门）→ danger 区 → 默认全保留 → dry-run 清单 → purge 勾选
//      + key 二次确认（错 key 禁确认）→ 确认执行 → fail-closed 文案就地（Temporal 死）。
//   T5 console 零 error / pageerror。
//
// 执行契约：stdout 末行 SUMMARY 四计数（三态）；playwright-core 或隔离台依赖缺失=
// ENV_FAIL（exit 2 点名 KI-036/依赖原因，不假绿）；实现落地前红属预期（TDD 信号），
// arbitrate/merge 期必须绿。
import { mkdirSync, readdirSync } from 'node:fs';
import path from 'node:path';
import {
  tmpRoot, makeFixtures, writeProjectEntry, writeQuarantinedDir,
  bootConsole, teardownOnExit, clientBuildStalenessReason, dismissNotice, loadPlaywright, makeResults, dismissShellNotice,
  openProjectSettings, waitFor } from './lib_fix15.mjs';

const { record, summarize } = makeResults();

// T0 夹具与依赖卫兵（依赖缺失=ENV_FAIL 环境红，不假绿）
const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable (KI-036)'); summarize(); }

let bench;
try {
  const fx = makeFixtures('fix15-ui-reg-');
  writeProjectEntry(fx.reg, 'fixa', '夹具甲', [path.join(fx.root, 'proj-fixa')]);
  writeQuarantinedDir(fx.reg, 'badkey');
  bench = await bootConsole(fx.root);
  bench.__fixtures = fx;
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
// 泳道 client build 陈旧守卫：lib/client.js 缺失/早于 src → 浏览器子用例拒跑（防拍旧 UI 假绿，
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
// 隔离台偶发半死（bootConsole 健康判据过了但面没起来——t260905-08 gen2 机械段实锤
// 21100 导航炸）：首导航失败=台装配环境红，env_fail 点名而非异常抛穿（exit 1 谎报产品红）。
try {
  await bench.goto(page, { waitUntil: 'domcontentloaded', timeout: 20000 });
} catch (e) {
  record('bench/first-nav', 'env_fail',
    `隔离台 ${bench.base} 首导航失败（boot 健康判据过但面未起=台装配环境红）：${String(e?.message ?? e).split('\n')[0].slice(0, 140)}`);
  await browser.close().catch(() => { /* 已退 */ });
  summarize();
}
  await dismissShellNotice(page);
await page.waitForTimeout(1500); // 左栏首拉
await dismissNotice(page); // 出厂 notice 会劫持焦点/指针（fill 打不进受控输入），先关

const sidebar = page.locator('aside, [class*=sidebar]').first();

// 过遮罩点击（capture.mjs forceClick 同款先例：出厂平台遮罩拦 pointer 时退避 DOM 直点；
// 仍是只读导航语义，不提交表单；只换执行体不改断言面）。
// Missing-anchor discipline (t261022-11): returns false instead of throwing. The
// leg that owns an absent anchor then records a NAMED fail; before this change a
// retired anchor (the settings icon) surfaced as an unhandled Playwright timeout
// that killed the whole scenario — half the defect this repair removes.
async function forceClick(loc, timeoutMs = 5000) {
  try { await loc.click({ timeout: timeoutMs }); return true; }
  catch { try { await loc.evaluate((el) => el.click()); return true; } catch { return false; } }
}

const visText = async () => (await sidebar.innerText().catch(() => '')).normalize('NFC');

// T1 三处就位
{
  // (a) Settings face reachable through the panel door. RETIRED LEG
  // rail/settings-icon-svg asserted a group-header Settings icon (SVG, title/aria
  // identifiable). t261008-36 (host order 261008, "one face, one home") retired
  // that icon: the settings modal now opens from the project row's executor panel
  // Settings tab and mounts the SAME modal inside a face overlay. The door is the
  // shared helper (lib_fix15.openProjectSettings — reuse, no local copy); it
  // returns a plain-words reason instead of throwing, so a missing anchor is a
  // NAMED fail here.
  const doorErr = await openProjectSettings(page, '夹具甲');
  record('settings/face-via-panel-door', doorErr === null,
    doorErr ?? 'project row → executor panel → Settings → project-settings face');
  // Leave the face before the add journey: Escape closes the settings modal, Back
  // unmounts the overlay. T3's dialog locator is generic, so a stale face layer
  // would shadow the add modal it means to drive.
  await page.keyboard.press('Escape').catch(() => { /* focus may sit in the panel iframe */ });
  if (await page.locator('[data-wb-face-overlay]').count()) {
    await forceClick(page.locator('[data-wb-face-overlay] [data-wb-face-back]').first());
    await waitFor(async () => (await page.locator('[data-wb-face-overlay]').count()) === 0, 5000);
  }

  // 接入行锚=产品机读属性 [data-wb-project-add-row]（宿主令 260925 英文化后旧中文
  // 文案「＋ 接入项目」退役为「＋Add project」；文案锚会随下一次改词再断，机读锚不断）。
  const addRow = sidebar.locator('[data-wb-project-add-row]').first();
  record('rail/add-row', await addRow.isVisible().catch(() => false), 'add row present ([data-wb-project-add-row])');

  // 隔离 key 红色行（验收11）：形状=点名被隔离的 key、无组头、无设置入口（隔离期间无
  // 装载条目可设置）。The old shape probe counted the group-header icons above the
  // row; that family is gone now, so the same shape is judged as "the row hangs
  // under no group header" (the family's absence has its own leg in T2).
  const isoRow = sidebar.locator('[data-wb-quarantine-row]').first();
  const isoVisible = await isoRow.isVisible().catch(() => false)
    && (await isoRow.innerText().catch(() => '')).includes('badkey');
  const noHead = isoVisible
    && (await isoRow.locator('xpath=ancestor::*[contains(@class,"wb-group-head")]').count()) === 0;
  record('rail/quarantine-row', isoVisible && noHead,
    `namesKey=${isoVisible} noGroupHead=${noHead}`);
}

// T2 退役面守夜 + 旧提法/emoji 面
{
  // RETIRED LEGS — named here, never silently dropped (t261008-36, host order 261008
  // "one face, one home"):
  //   icons/Tickets, icons/Docs, icons/Model Routes, icons/Epics — per-name svg
  //     presence of the four view icons. The tickets/docs/epics icons retired with
  //     their views (t261005-10 UI-2); Model routes and Project settings left the
  //     row with 261008.
  //   icons/four-views-svg — their aggregate ("all four render as svg").
  //   icons/board-click-active — "click the Tickets icon → it takes the active
  //     highlight". 261008 removed the last row-resident icon and the More-views
  //     toggle wholesale, so the project row holds nothing left to click; both
  //     faces now open from the executor panel's Settings tab. What replaced the
  //     door is asserted positively as settings/face-via-panel-door (T1); what
  //     replaced "nothing else may grow back in the row" is the absence leg below.
  const retiredFamily = ['Tickets', 'Docs', 'Model Routes', 'Epics', 'Project Settings', 'More views'];
  // Scope = the rail (where the family lived), judged by accessible name only —
  // never by CSS class, so the assertion survives an implementation rewrite that
  // keeps a resurrected entry. Zero project rows would make "absent" vacuously
  // true, so the row anchor has to be on stage for the absence to mean anything.
  const projectRows = await page.locator('[data-wb-project-block]').count().catch(() => 0);
  const resurrected = [];
  for (const nm of retiredFamily) {
    const n = await sidebar.locator(`[title="${nm}"], [aria-label="${nm}"]`).count().catch(() => 0);
    if (n > 0) resurrected.push(`${nm}×${n}`);
  }
  record('icons/group-header-family-retired', projectRows > 0 && resurrected.length === 0,
    `projectRows=${projectRows} resurrected=${resurrected.join(',') || 'none'}（261008 全族退役，按名零命中）`);

  // t260905-06 仲裁同步：「知识库」提法退役（宿主令+本票验收③），原位换「文档」
  // （t260905-06）。本清单随产品契约演进更新——「文档」图标在位=新口径，同时守护
  // 旧「知识库」不回流（与 wording_retired 场景互补：这里守 DOM 呈现面，那边守源码）。
  // The "Docs icon in place" half of that note retired with the family (261008);
  // the guard's live half — the old wording must not come back — is unchanged.
  const retired = await sidebar.locator('[title="知识库"], [aria-label="知识库"]').count();
  record('icons/knowledge-retired', retired === 0, `旧「知识库」图标计数=${retired}（应为 0，宿主令退役）`);

  const txt = await visText();
  const emojis = ['📋', '📖', '🔀', '🗂️'].filter((e) => txt.includes(e));
  record('icons/emoji-zero-visible', emojis.length === 0, `残留=${emojis.join('') || '无'}`);
}

// T3 接入弹层
{
  // Missing-anchor discipline: no step of this journey may throw out of the block.
  // The three legs are recorded at the end, so a dialog that never opens (or a form
  // field that is absent) yields NAMED fails carrying the throw site, never an
  // unhandled Playwright timeout.
  let opened = false, errShown = false, listed = false, preDetail = '', crash = '';
  try {
    await forceClick(sidebar.locator('[data-wb-project-add-row]').first());
    const dlg = page.locator('[role=dialog], [class*=modal], [class*=overlay]').first();
    opened = await dlg.isVisible().catch(() => false);
    if (opened) {
      // 坏 key 预检：错误就地显示（点名原因）
      const keyInput = dlg.locator('input').first();
      await keyInput.fill('Fix_B');
      const rootInput = dlg.locator('input').nth(2);
      {
        // 容器内 CLI 验目录存在（add 不代建）——预建在 fixtures 根下（容器内外同读写）
        mkdirSync(path.join(bench.__fixtures.root, 'proj-ui-add'), { recursive: true });
      }
      await rootInput.fill(bench.toStage(path.join(bench.__fixtures.root, 'proj-ui-add'))); // 容器路径：CLI 在容器里验目录
      // Precheck button = machine anchor [data-wb-pmod-add-precheck]. Rotted anchor
      // repaired (t261022-11): this leg used to locate the button by wording
      // (getByText /预检|dry-run/i); host order 260925 relabelled it "Precheck
      // (local shape check, nothing written)", the lookup stopped matching, the pre
      // region never appeared AND Confirm (disabled={busy || !pre}) could never be
      // pressed — both T3 legs went red while the product was correct. Machine
      // anchors do not rot with copy (same rule as [data-wb-project-add-row]).
      const preBtn = dlg.locator('[data-wb-pmod-add-precheck]');
      const preClicked = await forceClick(preBtn);
      await page.waitForTimeout(1200);
      // 坏 key 预检（本地形状检查）的就地显示=**预检黄牌区** [data-wb-pmod-add-pre]
      // （project-modals.tsx：预检 onClick=setPre({problems}) 且 setError('')——problems
      // 以「⚠ key 形状非法：…」黄牌行渲染；[data-wb-pmod-add-error] 只承载提交失败的
      // 服务端错误，锚它会永远扑空。gen10 归因修正：产品语义对齐，非断言放松——仍要求
      // 节点在场且文本点名 key；上一版锚 error 节点与全文匹配「拒」字（恒真假绿）均废）。
      const preNode = dlg.locator('[data-wb-pmod-add-pre]');
      const preVisible = await preNode.isVisible().catch(() => false);
      const preText = preVisible ? await preNode.innerText().catch(() => '') : '';
      // The pre region's first line is conditional ("Local shape check passed"),
      // so the bad-key face is the WARNING line: the ⚠ marker plus the key named.
      // Detail names which half failed instead of a bare boolean.
      const hasWarn = preText.includes('⚠');
      const namesKey = /key/i.test(preText);
      preDetail = preVisible
        ? `warn=${hasWarn} namesKey=${namesKey} pre=${preText.replace(/\s+/g, ' ').slice(0, 160)}`
        : `pre region absent (precheck anchor clicked=${preClicked})`;
      errShown = preVisible && hasWarn && namesKey;

      // 合法 key 成功 → 左栏出现新组（表单三输入齐填：key/显示名/根目录——缺显示名 CLI 必拒）
      await keyInput.fill('fixc');
      await dlg.locator('input').nth(1).fill('夹具丙');
      await page.waitForTimeout(200);
      // 提交=语义锚按钮（getByText 会命中含「接入」的提示文字而非按钮——隔离台实证）
      const submit = dlg.locator('[data-wb-pmod-add-submit]');
      await forceClick(submit);
      // ≤12s 轮询窗口：左栏刷新=10s 可见性轮询（成功回调未同步重拉——「即时」口径差距见验收报告）
      // 组头渲染的是显示名（wb-group-name={project.name}，key 只在色点 title）——找「夹具丙」非 key。
      for (let i = 0; i < 24 && !listed; i++) {
        await page.waitForTimeout(500);
        listed = await sidebar.getByText('夹具丙', { exact: false }).first().isVisible().catch(() => false);
      }
    }
  } catch (e) { crash = String(e?.message ?? e).split('\n')[0].slice(0, 160); }
  record('add/modal-opens', opened, crash ? `journey threw: ${crash}` : '');
  record('add/badkey-inline-error', opened && errShown,
    crash ? `journey threw: ${crash}` : `坏 key 预检黄牌就地显示且点名 key（pre 区锚）pre=${preDetail}`);
  record('add/success-new-group', listed,
    crash ? `journey threw: ${crash}` : '成功后左栏出现新项目组（≤12s=10s 轮询口径，验收12）');
}

// T4 摘除四步（fixa；Temporal 死 → 最终 fail-closed 文案就地）
{
  // Door: RETIRED LEG (was `forceClick(sidebar.locator('[title="Project Settings"]…'))`).
  // t261008-36 (host order 261008) retired that group-header icon; the settings
  // face opens from the executor panel's Settings tab through the shared helper.
  // Re-opened here because T1 left the face to run the add journey. The old leg
  // clicked a zero-node locator and died on an unhandled Playwright timeout — a
  // door that cannot be found is now a NAMED fail on this leg.
  const doorErr = await openProjectSettings(page, '夹具甲');
  // 弹层定位锚 [data-wb-pmod-overlay]（smoke/project-modals 既定公开语义锚）——
  // 勿用泛 [class*=overlay].last()：会抓到平台 Internal Testing Notice 弹层（隔离台实证）。
  const dlg = page.locator('[data-wb-pmod-overlay]').last();
  await page.waitForTimeout(600);
  const setText = await dlg.innerText().catch(() => '');
  const setOpened = doorErr === null && setText.includes('fixa');
  record('remove/entry-via-settings', setOpened,
    `door=${doorErr ?? 'panel Settings face'} dialogNamesKey=${setText.includes('fixa')}（danger 入口面）`);

  if (!setOpened) {
    // Downstream legs need the remove modal the door opens; they are unverifiable,
    // so they are named red here instead of crashing later.
    record('remove/keep-by-default', 'fail', 'settings face unreachable — remove flow not entered');
    record('remove/fail-closed-inline', 'fail', 'settings face unreachable — remove flow not entered');
  } else {
    // danger 摘除入口=产品机读属性 [data-wb-pmod-remove-danger]（按钮文案现为「Remove project…」）
    const danger = page.locator('[data-wb-pmod-remove-danger]').first();
    await forceClick(danger);
    await page.waitForTimeout(600);
    const rmDlg = page.locator('[data-wb-pmod-overlay]').last();
    const rmText = () => rmDlg.innerText().catch(() => '');

    // 处置勾选默认全保留（purge 默认不勾；可逆摘除口径）
    // Rotted anchor repaired (t261022-11): the leg classified boxes by LABEL TEXT
    // (/删|purge/i). Host order 260925 relabelled the two purge boxes "Delete data/
    // …" and "Delete credentials.yaml", so both fell into the "keep" branch, which
    // expects them CHECKED — red while the product's default (nothing purged =
    // reversible removal) was exactly right. The boxes are now read by their own
    // machine anchors, and the leg also requires the user-visible reversible note.
    const purgeBoxes = rmDlg.locator('[data-wb-pmod-remove-purge-data], [data-wb-pmod-remove-purge-cred]');
    const nPurge = await purgeBoxes.count();
    const purgeChecked = [];
    for (let i = 0; i < nPurge; i++) {
      if (await purgeBoxes.nth(i).isChecked().catch(() => true)) purgeChecked.push(i); // unreadable = fail-closed
    }
    const reversible = /Reversible by default|reversible removal/i.test(await rmText());
    record('remove/keep-by-default', nPurge === 2 && purgeChecked.length === 0 && reversible,
      `purgeBoxes=${nPurge} checked=${purgeChecked.join(',') || 'none'} reversibleNote=${reversible}`);

    // 在飞闸预检（dry-run=全闸预演，契约①a-1）：Temporal 死端口 → fail-closed 拒摘，
    // 错误就地显示（验收13）且流程停在 gate（无绕过旗，不前进到处置步）。
    const preBtn = rmDlg.locator('[data-wb-pmod-remove-precheck]');
    await forceClick(preBtn);
    await page.waitForTimeout(1500);
    const errTxt = await rmDlg.locator('[data-wb-pmod-remove-error]').innerText().catch(() => '');
    const stillGate = !(await rmDlg.locator('[data-wb-pmod-remove-dry]').isVisible().catch(() => false));
    record('remove/fail-closed-inline', /sandbar up|Temporal|拒/.test(errTxt) && stillGate,
      `fail-closed 文案=${errTxt.slice(0, 150)} | 停在gate=${stillGate}`);
  }
}

// T4b 四步流后段真台子用例（260908 补：原占位 ENV_FAIL「随隔离台真 Temporal 供给另补」——
// 供给=stage_docker services:'full'，dsh+temporal 健康 wiring，SA 随台注册）。
// 死端口台上在飞闸恒拒，后段（dispose→dry 清单→确认执行）只能在真台走真。
{
  let fullBench, fx2;
  try {
    fx2 = makeFixtures('fix15-ui-full-');
    mkdirSync(path.join(fx2.root, 'proj-keepb'), { recursive: true });
    mkdirSync(path.join(fx2.root, 'proj-rmb'), { recursive: true });
    writeProjectEntry(fx2.reg, 'keepb', '真台甲', [fx2.toStage(path.join(fx2.root, 'proj-keepb'))]);
    writeProjectEntry(fx2.reg, 'rmb', '真台乙', [fx2.toStage(path.join(fx2.root, 'proj-rmb'))]);
    fullBench = await bootConsole(fx2.root, { services: 'full' });
    teardownOnExit(fullBench.teardown);
    record('remove-real/bench-boot', 'pass', fullBench.base);
  } catch (e) {
    record('remove-real/bench-boot', 'env_fail',
      `full 台装配失败（dsh+temporal 供给缺失）：${String(e?.message ?? e).slice(0, 180)}`);
    fullBench = null;
  }

  if (fullBench) {
    const page2 = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page2.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page2.on('pageerror', (e) => consoleErrors.push(String(e)));
    try {
      await page2.goto(`${fullBench.base}/`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await dismissShellNotice(page2);
      await page2.waitForTimeout(1500);
      await dismissNotice(page2);
      // RETIRED LEG (was: anchor the 真台乙 group, then click its group-header
      // [title="Project Settings"] icon). t261008-36 (host order 261008) retired
      // that icon family — the settings face opens from the project row's executor
      // panel Settings tab. The shared helper resolves the group by name, so the
      // two-project rail still targets 真台乙 (a global first-entry click would
      // mis-anchor on 真台甲).
      const doorErr2 = await openProjectSettings(page2, '真台乙');
      const dlg = page2.locator('[data-wb-pmod-overlay]').last();
      await page2.waitForTimeout(600);
      const entryTxt = await dlg.innerText().catch(() => '');
      record('remove-real/entry', doorErr2 === null && entryTxt.includes('rmb'),
        `door=${doorErr2 ?? 'panel Settings face'} dialogNamesKey=${entryTxt.includes('rmb')}（真台组锚）`);
      await forceClick(page2.locator('[data-wb-pmod-remove-danger]').first());
      await page2.waitForTimeout(600);
      const rmDlg = page2.locator('[data-wb-pmod-overlay]').last();

      // 步骤1→2：预检过在飞闸 → dispose 步（「摘除清单（dry-run）」钮=干燥清单面）。
      await forceClick(rmDlg.locator('[data-wb-pmod-remove-precheck]'));
      await page2.waitForTimeout(2000);
      const disposed = await rmDlg.locator('[data-wb-pmod-remove-dry]').isVisible().catch(() => false);
      // 红时回显错误面全文（e43ac45 同口径：仅布尔旗无法归因 transient 红——
      // 并发下 precheck 拒因只有文案能分辨「台没起好」与「产品真红」）。
      const preErr = await rmDlg.locator('[data-wb-pmod-remove-error]').innerText().catch(() => '');
      record('remove-real/precheck-to-dispose', disposed,
        `disposed=${disposed}（真台预检过→处置步；死端口台恒停 gate——对照面） err=${preErr.slice(0, 200)}`);

      // 步骤2→3：dry 清单 → confirm 步（清单 pre 在场且点名退役改名=将执行面）。
      if (disposed) {
        await forceClick(rmDlg.locator('[data-wb-pmod-remove-dry] button').first());
        await page2.waitForTimeout(2000);
        const confirmVisible = await rmDlg.locator('[data-wb-pmod-remove-confirm]').isVisible().catch(() => false);
        const dryTxt = await rmDlg.locator('[data-wb-pmod-remove-confirm] pre').innerText().catch(() => '');
        record('remove-real/dry-list', confirmVisible && /退役|retire/.test(dryTxt),
          `confirm=${confirmVisible} dry=${dryTxt.slice(0, 120)}`);
        // 步骤3→4：无 purge 勾选 → 免 key 二次确认直接执行。成功语义两路皆认：
        // ① 结果步文本「摘除完成」上屏；② 弹层被 onRemoved 整体卸载（sidebar 的
        // 成功回调=setModal(null)，结果面与卸载同 tick，单读 result 必扑空——
        // 260908 双跑实锤：result 恒空而 retired 文件恒在位）。② 路必须同时
        // 确认错误面不在场，防把失败闪断误当成功。
        await forceClick(rmDlg.locator('[data-wb-pmod-remove-submit]'));
        let okTxt = '', modalGone = false, errTxt = '';
        for (let i = 0; i < 20 && !/Removal done/.test(okTxt) && !modalGone && !errTxt; i++) {
          await page2.waitForTimeout(500);
          modalGone = (await rmDlg.count()) === 0;
          if (!modalGone) {
            errTxt = await rmDlg.locator('[data-wb-pmod-remove-error]').innerText().catch(() => '');
            okTxt = await rmDlg.locator('[data-wb-pmod-remove-result]').innerText().catch(() => '');
          }
        }
        record('remove-real/execute-ok', /Removal done/.test(okTxt) || (modalGone && !errTxt),
          `result=${okTxt.slice(0, 120)} modalGone=${modalGone} err=${errTxt.slice(0, 200)}`);
        // 现场核验：注册表根（宿主侧挂载）退役文件在位 = 可逆摘除真落地。
        const retired = readdirSync(path.join(fx2.reg, 'rmb'))
          .some((n) => n.startsWith('project.yaml.retired-'));
        record('remove-real/retired-on-disk', retired, 'project.yaml.retired-* 在位');
      } else {
        record('remove-real/dry-list', 'fail', 'dispose 步未达，dry 清单无从断言');
        record('remove-real/execute-ok', 'fail', 'dispose 步未达');
        record('remove-real/retired-on-disk', 'fail', 'dispose 步未达');
      }
    } catch (e) {
      record('remove-real/entry', 'env_fail', `真台旅程异常：${String(e?.message ?? e).slice(0, 140)}`);
    }
    await page2.close().catch(() => { /* noop */ });
    fullBench.teardown();
  }
}

// T5 console 零 error（豁免：旅程故意触发 fail-closed 的 409 资源日志——浏览器把
// 非 2xx fetch 记为 console error，属预期交互产物非 UI 缺陷；t260910-04 R3 起本台
// （容器内引擎地址钉死不可达=降级断言面）的工单列表显式 502 同属预期产物，同款豁免；
// 其余 error 零容忍）
// The detail must carry the OFFENDING errors: it used to print the first three
// entries of the whole list, which can all be exempted resource logs — a red then
// named nothing (t261022-11 counted 20/21 with three 502 lines printed).
{
  const flagged = consoleErrors.filter((e) => !/Failed to load resource.*(409|502)/.test(e));
  record('browser/console-clean', flagged.length === 0,
    flagged.length ? `flagged=${flagged.length}: ${flagged.slice(0, 3).join(' | ').slice(0, 400)}` : '');
}

await browser.close();
bench.teardown();
summarize();
