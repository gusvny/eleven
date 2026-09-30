// sc_docs_follow_project.mjs — t260915-10 场景：文档页跟随当前项目（DocsSection 接壳层
// projectKey，KI-057 同族第二形态的回归闸，隔离台浏览器走查）。
//
// intent（灰盒，用户可感知行为；方案 §3 S5 T1-T5，review_plan 第 2 轮 pass 稿）：
//   壳层当前项目驱动文档页初值与跟随：经某项目组「文档」图标进入=初值该项目（树随切换、
//   wire 带 project=<该项目>）；页内 Project 选择器手动切换后，同挂载期内壳层项目真变化
//   不冲掉手动选择（userTouched guard，spec 验收②）；重挂载（视图切走再进）=重新跟随
//   （touched 生命周期另一端，收敛口径评审已裁）；目标项目无 docs/notes 目录=空态+指引
//   锚（data-wb-doc-empty-hint）且绝无引擎库内容冒充（spec ③不回落）。断言锚=公开契约锚
//   data-wb-docs-root / data-wb-doc-project-key / data-wb-doc-empty-hint / [data-wb-doc-item]
//   +元素角色/可见文本，不锚内部类名。wire 层证据=监听 /api/wf/docs/ 请求 URL。
//   与 t260910-10-docs-ui-mock-v1 不同面：那条锁 mock v1 版面旅程（chip/大纲/折叠/Search，
//   本票回归归它）；与 t260910-10-docs-project-anchor 不同层：那条锁 API 锚解析契约；
//   本条锁「壳层接线」语义（初值跟随/手动优先/重挂载重跟/空态不冒充）——guard 是本票
//   新语义里唯一无既有场景可兜底的行为面，子用例二必须真变化点击（点另一组图标，
//   同组同值点击=React bail out 空转，review_plan R1 教训）。
//   playwright-core/浏览器缺失=env_fail（KI-036 家族）；实现落地前红属预期（TDD 信号），
//   arbitrate/merge 期必须绿。
//
// high-level steps：
//   T0 自举隔离台（lib_fix17：临时注册表 + fixa「夹具甲」docs/指南.md+notes/备忘.md、
//      fixb「夹具乙」空根无 docs/ 无 notes/）+ playwright 探测；监听 docs API 请求；
//      组序自检（夹具甲在夹具乙前，nth 定位的排序前提）。
//   T1 跟随初值：点夹具甲组「文档」图标 → 选择器值=fixa（data-wb-doc-project-key）+
//      选中项文本含「夹具甲」+ 树=夹具篇目（sandbar 篇目退场）+ wire 带 project=fixa。
//   T2 手动优先：子用例一 选择器手动选 sandbar/default → 引擎库篇目在场 + wire 出无 project
//      请求（缺省回落零回归）；子用例二 点夹具乙组「文档」图标（viewProject fixa→fixb 真变化、
//      同挂载、touched=true）→ 选择器仍=default + 无新 project=fixb 请求 + 树仍引擎库
//      篇目（判别力：无 guard → 选择器跳 fixb+请求发出+树变空，两态可辨）。
//   T3 空态不冒充（承接 T2 壳层已=fixb）：点夹具乙「工单列表」图标（中列切 board，
//      文档视图卸载）→ 点夹具乙「文档」图标（重挂载→touched 重置→重新跟随=fixb）→
//      空态+指引锚在场（文案含 fixb 与「回落」语义）+ 引擎库篇目不串入 + wire 带
//      project=fixb；Notes 页签同理诚实空态+指引仍在。
//   T4 既有面回归：选择器手动选回夹具甲 → 树随切（t260910-10 面不破）+ wire 带 project=fixa。
//   T5 红线：端口 ≠3099/7233；finally 回收浏览器+进程树+临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na（三态=闸内无 SKIP 的现行定稿）。
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
} from '../t260904-17/lib_fix17.mjs';

const { record, summarize } = makeResults();

const stub = makeTicketStub();

const pw = await loadPlaywright();
if (!pw) {
  record('playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：浏览器走查子用例环境红');
  summarize();
}

// ---- 夹具：fixa=docs/指南.md（含 h2 供树上篇目断言）+notes/备忘.md；fixb=空根（无 docs/ 无 notes/）----
function writeFxa(root) {
  const docs = path.join(root, 'docs');
  mkdirSync(docs, { recursive: true });
  mkdirSync(path.join(root, 'notes'), { recursive: true });
  writeFileSync(path.join(docs, '指南.md'), [
    '---',
    'title: 夹具甲指南',
    'status: active',
    'updated: 2026-09-15',
    'category: reference',
    '---',
    '',
    '# 夹具甲正文标题',
    '',
    '夹具甲独有内容哨兵。',
    '',
    '## 小节甲',
    '',
    '小节甲正文。',
    '',
  ].join('\n'));
  writeFileSync(path.join(root, 'notes', '备忘.md'), [
    '---',
    'title: 夹具甲备忘',
    '---',
    '',
    '# 夹具甲备忘正文',
    '',
  ].join('\n'));
}

const regRoot = makeRegistryRoot('t260915-10-reg-');
const fixaRoot = tmpRoot('t260915-10-fixa-');
writeFxa(fixaRoot);
writeProjectEntry(regRoot, 'fixa', '夹具甲', [fixaRoot]);
const fixbRoot = tmpRoot('t260915-10-fixb-'); // 空根：不建 docs/ 与 notes/（空态子用例载体）
writeProjectEntry(regRoot, 'fixb', '夹具乙', [fixbRoot]);

let bench;
try {
  bench = await bootConsole(regRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', 'pass', bench.base);
record('redline/ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}`);

// ---- 浏览器（channel chrome 优先，回落裸 chromium——read_through 同款）----
const { chromium } = pw;
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => chromium.launch({ headless: true }));
} catch (e) {
  record('browser', 'env_fail', `浏览器可执行档缺失（npx playwright install 可解，KI-036 家族）：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`);
  summarize();
}

// docs API 请求监听（wire 层证据）
const docReqs = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on('request', (r) => {
    const u = r.url();
    if (u.includes('/api/wf/docs/')) docReqs.push(u);
  });
  await bench.goto(page, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await page.waitForTimeout(600);

  const rootSel = page.locator('[data-wb-docs-root]');
  const items = rootSel.locator('[data-wb-doc-item]');

  // 组序自检（nth 定位的排序前提；组名渲染属左列既有面，此处只做夹具前提自证）
  let names = [];
  for (let i = 0; i < 12; i++) {
    names = await page.locator('.wb-group-name').allTextContents().catch(() => []);
    if (names.length >= 2) break;
    await page.waitForTimeout(500);
  }
  const fxaIdx = names.findIndex((t) => t.includes('夹具甲'));
  const fxbIdx = names.findIndex((t) => t.includes('夹具乙'));
  record('bench/group-order', fxaIdx >= 0 && fxbIdx > fxaIdx,
    `组序=${JSON.stringify(names.slice(0, 6))}（夹具甲 idx=${fxaIdx} < 夹具乙 idx=${fxbIdx}）`);
  if (fxaIdx < 0 || fxbIdx < 0) {
    record('ui/entry-present', 'fail', '项目组未渲染齐全（左列既有面，链路无从走起）');
    summarize();
  }
  // 组名 scope + span 标签限定（导航用；断言仍锚公开契约）：每枚图标的可点击 span 内嵌
  // ProjectIcon svg 同名 aria-label（project-icons.tsx :105 role=img aria-label 恒同值）
  // ——全局 aria-label 序数会被组内 svg 错位（本台实证：nth(1)=夹具甲的 svg，点击冒泡到
  // 夹具甲 span=空转假绿）；组头 hasText 找图标 + span 标签限定双保险，消去序数与装饰
  // 节点两类错位。.wb-group-head 仅作导航定位不作断言锚。
  // 入口钉 aria-label（无障碍名=入口用户可感知契约本身；宿主令 260925 控制台 UI 文案一律
  // 英文后取值 "Docs"，迁移前旧值为「文档」）；限定 span 是为排除 ProjectIcon svg 的同名
  // aria-label（project-icons.tsx role=img 恒同值）。

// t260929-22 宿主裁 1（260929）：Docs/模型路由/项目设置收进组内「More views」展开位
// （260823 常驻可见放宽为展开显现）——取用前先展开全部组的展开位（data-on 缺席=未展开）。
async function expandMoreViews(page) {
  const btns = page.locator('[data-wb-more-views]:not([data-on])')
  const n = await btns.count().catch(() => 0)
  for (let i = 0; i < n; i++) await btns.nth(i).click({ timeout: 4000 }).catch(() => {})
  await page.waitForTimeout(300)
}
  const docsIconOf = (name) => page.locator('.wb-group-head', { hasText: name }).locator('span[aria-label="Docs"]');
  const boardIconOf = (name) => page.locator('.wb-group-head', { hasText: name }).locator('span[aria-label="Tickets"]');
  const projKeyOf = () => page.evaluate(() => document.querySelector('[data-wb-docs-root]')?.getAttribute('data-wb-doc-project-key') ?? null);
  const waitProjKey = (want, timeout = 8000) => page.waitForFunction(
    (w) => document.querySelector('[data-wb-docs-root]')?.getAttribute('data-wb-doc-project-key') === w,
    want, { timeout },
  ).then(() => true).catch(() => false);

  // ---- T1 跟随初值：经夹具甲组「文档」图标进入=初值 fixa ----
  {
    // 入口探针=deadline 内轮询不单点取样（KI-072 族，mock_v1 同款口径）
    await expandMoreViews(page);
    let iconSeen = false;
    for (let i = 0; i < 12; i++) {
      if (await docsIconOf("夹具甲").isVisible().catch(() => false)) { iconSeen = true; break; }
      await page.waitForTimeout(500);
    }
    if (!iconSeen) {
      record('ui/entry-present', 'fail', '夹具甲组 aria-label="Docs" 图标不在场（入口面由 t260905-06-doc-entry-present 专守，本场景链路无从走起）');
      summarize();
    }
  await expandMoreViews(page)
    await docsIconOf("夹具甲").click();
    const keyOk = await waitProjKey('fixa');
    await page.waitForTimeout(1200);
    record('follow/init-key', keyOk, `初值=夹具甲：data-wb-doc-project-key='fixa'=${keyOk}（壳层接线=病灶修复的用户可感知面）`);
    const selText = await page.evaluate(() => document.querySelector('[data-wb-docs-root] select')?.selectedOptions[0]?.textContent?.trim() ?? '');
    record('follow/init-selected', selText.includes('夹具甲'), `初值选中项=「${selText.slice(0, 30)}」期望含夹具甲`);
    const fxaShown = await items.filter({ hasText: '夹具甲指南' }).first().isVisible().catch(() => false);
    const sandbarGone = !(await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false));
    record('follow/init-tree', fxaShown && sandbarGone, `首屏树=夹具篇目（指南=${fxaShown}）且 sandbar 篇目退场=${sandbarGone}`);
    const wire = docReqs.some((u) => u.includes('/api/wf/docs/tree') && u.includes('project=fixa'));
    record('wire/init-project-param', wire, `初载 tree 请求带 project=fixa=${wire}（壳层入口直开的线上证据）`);
  }

  // ---- T2 手动优先 ----
  {
    // 子用例一：手动选缺省 sandbar/default → 引擎库 + wire 无 project 请求（缺省回落零回归）
    await rootSel.locator('select').first().selectOption('').catch(() => {});
    await page.waitForTimeout(1400);
    const termBack = await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false);
    const noProjWire = docReqs.some((u) => u.includes('/api/wf/docs/tree') && !u.includes('project='));
    record('manual/default-fallback', termBack && noProjWire,
      `手动选缺省：引擎库篇目回场=${termBack} wire 出无 project 请求=${noProjWire}（缺省回落零回归）`);
    // 子用例二：点夹具乙组图标（viewProject fixa→fixb 真变化、同挂载、touched=true）→ 不被冲掉
    const fixbCntBefore = docReqs.filter((u) => u.includes('project=fixb')).length;
    await docsIconOf("夹具乙").click();
    await page.waitForTimeout(1600);
    const keyAfter = await projKeyOf();
    const fixbCntAfter = docReqs.filter((u) => u.includes('project=fixb')).length;
    const termStill = await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false);
    const alive = await rootSel.isVisible().catch(() => false);
    record('manual/touched-guard', alive && keyAfter === '' && fixbCntAfter === fixbCntBefore && termStill,
      `壳层真变化（fixa→fixb）手动选择不被冲掉：选择器仍=''（实际=${String(keyAfter)}） 无新 project=fixb 请求（${fixbCntBefore}→${fixbCntAfter}） 树仍引擎库=${termStill}`
      + `（判别力：无 guard 实现下此处=选择器跳 fixb+请求发出+树变空——review_plan R1 空转子用例教训的反面）`);
  }

  // ---- T3 空态不冒充（承接 T2 壳层已=fixb；经 board 卸载重挂载=touched 重置重新跟随）----
  {
    await boardIconOf("夹具乙").click();
    await page.waitForTimeout(800);
    const docsUnmounted = !(await rootSel.isVisible().catch(() => false));
    record('remount/docs-unmounted', docsUnmounted, `切 board 后文档视图卸载=${docsUnmounted}（重挂载子用例前提）`);
    await docsIconOf("夹具乙").click();
    const keyOk = await waitProjKey('fixb');
    await page.waitForTimeout(1400);
    const keyActual = await projKeyOf();
    const emptyHint = await page.evaluate(() => {
      const el = document.querySelector('[data-wb-doc-empty-hint]');
      return el ? (el.textContent || '').trim() : null;
    });
    const zeroItems = (await items.count()) === 0 || !(await items.first().isVisible().catch(() => false));
    const noEngineBleed = !(await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false));
    const wire = docReqs.some((u) => u.includes('/api/wf/docs/tree') && u.includes('project=fixb'));
    record('empty/follows-fixb', keyOk, `重挂载重新跟随=夹具乙：data-wb-doc-project-key='fixb'=${keyOk}（实际=${String(keyActual)}；touched 生命周期另一端）`);
    record('empty/hint-present', !!emptyHint && emptyHint.includes('fixb') && /回落|引擎仓/.test(emptyHint),
      `空态指引锚在场=${!!emptyHint} 点名项目键（fixb）+不回落语义（/回落|引擎仓/ 不锚整串措辞）：「${String(emptyHint).slice(0, 80)}」（spec ③；文案点名 key=组件只持 projectKey，与 UT 真值表同口径）`);
    record('empty/no-engine-bleed', zeroItems && noEngineBleed,
      `空目录零条目=${zeroItems} 引擎库篇目不串入=${noEngineBleed}（不许静默回落冒充有文档）`);
    record('wire/empty-project-param', wire, `空态 tree 请求带 project=fixb=${wire}（显式传键，后端诚实降级 200+empty+reason）`);
    // Notes 页签：同构诚实空态 + 指引仍在
    const notesTab = rootSel.getByText('Notes', { exact: true }).first();
    if (!(await notesTab.isVisible().catch(() => false))) {
      record('empty/notes-scope', 'fail', 'Notes 页签不在场（空态 Notes 子用例无从走起）');
    } else {
      await notesTab.click();
      await page.waitForTimeout(1200);
      const hint2 = await page.evaluate(() => document.querySelector('[data-wb-doc-empty-hint]')?.textContent?.trim() ?? null);
      const alive = await rootSel.isVisible().catch(() => false);
      record('empty/notes-scope', alive && !!hint2, `Notes 空目录：视图存活=${alive} 指引在场=${!!hint2}（诚实降级不炸）`);
    }
  }

  // ---- T4 既有面回归：选择器手动选回夹具甲 → 树随切（t260910-10 面不破）----
  // （先复位回 Docs 页签：T3 子用例把 scope 留在了 Notes——不复位则选 fixa 后树=fixa 的
  //   notes 树，「夹具甲指南」恒不在场，对正确实现误报红=测试写错。锚=data-wb-docs-scope-docs
  //   公开契约锚，read_through 同款定位。）
  {
    const docsTab = page.locator('[data-wb-docs-scope-docs]').first();
    if (await docsTab.isVisible().catch(() => false)) {
      await docsTab.click();
      await page.waitForTimeout(1000);
    }
    const fixaCntBefore = docReqs.filter((u) => u.includes('project=fixa')).length;
    await rootSel.locator('select').first().selectOption('fixa').catch(() => {});
    await page.waitForTimeout(1400);
    const fxaShown = await items.filter({ hasText: '夹具甲指南' }).first().isVisible().catch(() => false);
    const fixaCntAfter = docReqs.filter((u) => u.includes('project=fixa')).length;
    record('switch/manual-back-to-fixa', fxaShown && fixaCntAfter > fixaCntBefore,
      `选择器手动切夹具甲：篇目回场=${fxaShown} project=fixa 请求（${fixaCntBefore}→${fixaCntAfter}）（t260910-10 切换面不破）`);
  }
} finally {
  await browser.close().catch(() => {});
  bench.teardown();
}
summarize();
