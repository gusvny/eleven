// sc_docs_ui_mock_v1.mjs — t260910-10 场景③：文档视图 mock v1 终态旅程（KI-070 UI 半 + 260910 过稿版式，隔离台浏览器走查）。
//
// intent（灰盒，用户可感知行为；工单必含③ + review 条件意见 N1-N4 的终态化）：
//   用户在文档视图里能完成 mock v1 版式承诺的完整旅程：打开文档页初值=壳层当前项目
//   （t260915-10 接壳层语义——经夹具甲组「文档」图标进入=初值夹具甲；语义变更留痕：
//   t260910-10 旧稿锁「初值=缺省引擎仓、初载无 project=」，那正是 t260915-10 修的病灶
//   语义，缺省回落旅程移到 T1b 手动子用例，跟随初值由 t260915-10 新场景专守）、顶部 Project
//   切换器换到任一注册项目后树随所选项目切换（KI-070 的用户可感知面）、固定 UI 元素一律
//   英文、开篇后正文带五枚元信息 chip（Verified 无数据源=显式 pending 占位不留假值）、
//   On this page 大纲随选中文档渲染且点击真跳转、分组可折叠、Search 在当前项目内过滤、
//   空 scope 目录诚实降级不炸。断言锚=公开契约锚 data-wb-docs-root/[data-wb-doc-item]
//   （t260905-06 立下的契约锚，gen1 方案承诺保留可新增不可移除）+ 元素角色/可见文本
//   （select、input、固定英文词），不锚内部类名。线上证据子用例：监听 /api/wf/docs/ 请求
//   URL——初载带 project=fixa（壳层接线）、手动选缺省后无 project= 参数（缺省回落）、
//   切项目后带 ?project=<夹具>（客户端显式传键=反 viewProject 漂移，KI-070 在 wire 层
//   的判据）。
//   与 t260905-06-doc-read-through intent 不同面：那条锁单仓阅读链路+代码块渲染+窄栏
//   单栏流+无溢出（本票回归面，既有场景跑，不重复设计）；本条锁 mock v1 新元素与新旅程。
//   与 t260910-10-docs-project-anchor 不同层：那条锁 API 锚解析契约，本条锁 DOM 终态旅程。
//   playwright-core/浏览器缺失=env_fail（KI-036 家族）；实现落地前红属预期（TDD 信号），
//   arbitrate/merge 期必须绿。
//
// high-level steps：
//   T0 自举隔离台（lib_fix17：临时注册表 + fixa「夹具甲」docs/mini.md(含 h2 小节甲/乙)
//      +docs/sub/深篇.md+notes/备忘.md、fixb「夹具乙」docs/单篇.md 无 notes/）+
//      playwright 探测；监听 docs API 请求；点「文档」入口进视图。
//   T1 初值与固定元素（t260915-10 接壳层语义）：经夹具甲组「文档」图标进入=初值夹具甲
//      （data-wb-doc-project-key='fixa'、选中项含「夹具甲」、首屏树=夹具篇目、初载 tree
//      请求带 project=fixa）、固定英文元素在场（Project/Docs/Notes/Search 输入框/
//      On this page）。
//   T1b 缺省回落旅程（手动子用例，t260915-10 留痕：旧稿 T1 的「无 project=」断言移到本子用例）：
//      选择器手动选 sandbar/default → 引擎库篇目回场 + wire 出无 project 请求。
//   T2 项目切换旅程：选择器选夹具甲 → 请求带 ?project=fixa（wire）→ 树出夹具篇目、
//      sandbar 篇目退场（DOM 终态）。
//   T3 开篇+chip+大纲：点「夹具甲指南」→ 正文真渲染（夹具甲正文标题）、五枚 chip 键
//      （Status/Verified/Category/Updated/Path）在场、Verified 面显式 pending 且无日期
//      形状（不留假值终态化）、On this page 出 h2 条目（小节乙，正文标题+大纲条目≥2 处）
//      且点击大纲条目目标标题滚入视口（点击跳转真生效）。
//   T4 分组折叠：组头（总目录）点按 → 组内条目隐藏 → 再点恢复（可见性翻转终态）。
//   T5 Search 过滤：输入「深篇」→ 列表收窄到路径/标题匹配（指南隐、深篇在）、
//      清空 → 还原。
//   T6 空态退化：切夹具乙 → 单篇在场；切 Notes 页签 → 零条目+诚实 reason 在场
//      （/不存在/ 语义，措辞不锚字面）+On this page 空+不残留夹具甲内容+视图不炸。
//   T7 红线：端口 ≠3099/7233；finally 回收浏览器+进程树+临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na（三态=闸内无 SKIP 的现行定稿，旧 SKIP 语义退役）。
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

// ---- 夹具（与 sc_docs_project_anchor 同构：真目录真文件；mini.md 含双 h2 供大纲子用例）----
function writeFxa(root) {
  const docs = path.join(root, 'docs');
  mkdirSync(path.join(docs, 'sub'), { recursive: true });
  mkdirSync(path.join(root, 'notes'), { recursive: true });
  writeFileSync(path.join(docs, 'mini.md'), [
    '---',
    'title: 夹具甲指南',
    'status: active',
    'updated: 2026-09-10',
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
    '## 小节乙',
    '',
    '小节乙正文。',
    '',
  ].join('\n'));
  writeFileSync(path.join(docs, 'sub', '深篇.md'), [
    '---',
    'title: 夹具甲深篇',
    '---',
    '',
    '# 夹具甲深篇正文',
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

function writeFxb(root) {
  const docs = path.join(root, 'docs');
  mkdirSync(docs, { recursive: true });
  writeFileSync(path.join(docs, '单篇.md'), [
    '---',
    'title: 夹具乙单篇',
    '---',
    '',
    '# 夹具乙单篇正文',
    '',
  ].join('\n'));
}

const regRoot = makeRegistryRoot('t260910-10-uireg-');
const fixaRoot = tmpRoot('t260910-10-uifxa-');
writeFxa(fixaRoot);
writeProjectEntry(regRoot, 'fixa', '夹具甲', [fixaRoot]);
const fixbRoot = tmpRoot('t260910-10-uifxb-');
writeFxb(fixbRoot);
writeProjectEntry(regRoot, 'fixb', '夹具乙', [fixbRoot]);

let bench;
try {
  bench = await bootConsole(regRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', true, bench.base);
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

// docs API 请求监听（wire 层证据：初载无 project / 切换后带 project）
const docReqs = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on('request', (r) => {
    const u = r.url();
    if (u.includes('/api/wf/docs/')) docReqs.push(u);
  });
  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await page.waitForTimeout(600);

  const rootSel = page.locator('[data-wb-docs-root]');
  const items = rootSel.locator('[data-wb-doc-item]');

  const docIcon = page.locator('[aria-label="文档"]').first();
  // 入口探针=耐心等待而非单点取样（t260913-02 arbitrate 实证：大跑负载下左列渲染慢，
  // 固定 600ms 单点取样把「还没渲染完」记成「图标不在场」——条目自带注释也写明这是
  // 入口面，由 t260905-06-doc-entry-present 专守；同一断言两处写法，单点取样这处会假红）。
  // 口径对齐 905-06：deadline 内轮询 isVisible，不裸 sleep 单点长等（KI-072 族）。
  let docIconSeen = false;
  for (let i = 0; i < 12; i++) {              // 12 × 500ms = 6s 上限
    if (await docIcon.isVisible().catch(() => false)) { docIconSeen = true; break; }
    await page.waitForTimeout(500);
  }
  if (!docIconSeen) {
    record('ui/entry-present', 'fail', '「文档」图标不在场（入口面由场景 t260905-06-doc-entry-present 专守，本场景链路无从走起）');
    summarize();
  }
  await docIcon.click();
  await page.waitForTimeout(1400);

  // ---- T1 初值=壳层当前项目（t260915-10 接壳层）+ 固定英文元素 + wire 带 project ----
  // （语义变更留痕：t260905-06/t260910-10 旧稿锁「初值=缺省引擎仓、初载无 project=」——
  //   那正是 t260915-10 修的病灶语义；本条改锁经组图标进入=初值该组项目，缺省回落旅程
  //   移到 T1b 手动子用例，跟随初值由 t260915-10 新场景专守。）
  const initKeyOk = await page.waitForFunction(
    () => document.querySelector('[data-wb-docs-root]')?.getAttribute('data-wb-doc-project-key') === 'fixa',
    { timeout: 8000 },
  ).then(() => true).catch(() => false);
  await page.waitForTimeout(1000);
  record('ui/init-follow-key', initKeyOk, `初值=壳层当前项目：data-wb-doc-project-key='fixa'=${initKeyOk}（t260915-10 接壳层语义）`);

  const initTree = await items.filter({ hasText: '夹具甲指南' }).first().isVisible().catch(() => false);
  const sandbarAbsent = !(await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false));
  record('ui/init-follow-tree', initTree && sandbarAbsent, `初值态首屏树=夹具篇目=${initTree} sandbar 篇目退场=${sandbarAbsent}（跟随初值）`);

  const selInfo = await page.evaluate(() => {
    const sel = document.querySelector('[data-wb-docs-root] select');
    if (!sel) return { present: false };
    const opt = sel.selectedOptions[0];
    return {
      present: true,
      selectedText: opt ? opt.textContent.trim() : '',
      optionCount: sel.options.length,
      texts: [...sel.options].map((o) => o.textContent.trim()).slice(0, 12),
    };
  });
  record('ui/project-select-present', selInfo.present === true, selInfo.present ? `Project 选择器在场（选项 ${selInfo.optionCount} 个）` : '文档视图内无 select（Project 切换器缺席；实现落地前红属预期）');
  record('ui/init-follow-selected', !!selInfo.present && /夹具甲/.test(selInfo.selectedText),
    `初值选中项=「${String(selInfo.selectedText).slice(0, 40)}」期望含夹具甲（synthesized 缺省项仍在选项列，但不再是初值选中态——t260915-10）`);

  const initWire = docReqs.some((u) => u.includes('/api/wf/docs/tree') && u.includes('project=fixa'));
  record('wire/init-project-param', initWire, `初载 docs 请求带 project=fixa=${initWire}（壳层入口直开的线上证据；共监听 ${docReqs.length} 条）`);

  for (const t of ['Project', 'Docs', 'Notes', 'On this page']) {
    const vis = await rootSel.getByText(t, { exact: true }).first().isVisible().catch(() => false);
    record(`ui/fixed-en-${t.replace(/\s/g, '-').toLowerCase()}`, vis, `固定英文元素「${t}」在场=${vis}`);
  }
  const searchBox = rootSel.locator('input').first();
  const searchPresent = (await searchBox.count()) > 0 && (await rootSel.locator('input').first().isVisible().catch(() => false));
  record('ui/fixed-en-search', searchPresent, 'Search 输入框在场（input 元素，角色级定位）');

  // ---- T1b 缺省回落旅程（手动子用例，t260915-10 留痕：旧稿 T1 的「无 project=」断言移到本子用例
  //      ——缺省回落=显式手动选择态，不再是打开文档页的初值）----
  await rootSel.locator('select').first().selectOption('').catch(() => {});
  await page.waitForTimeout(1400);
  const termBack = await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false);
  const manualNoProject = docReqs.some((u) => u.includes('/api/wf/docs/tree') && !u.includes('project='));
  record('manual/default-fallback', termBack && manualNoProject,
    `手动选缺省：引擎库篇目回场=${termBack} wire 出无 project 请求=${manualNoProject}（缺省回落零回归）`);

  // ---- T2 项目切换旅程（wire + DOM 终态）----
  const picked = await page.evaluate(() => {
    const sel = document.querySelector('[data-wb-docs-root] select');
    if (!sel) return null;
    for (const o of sel.options) {
      if (/夹具甲/.test(o.textContent)) return { value: o.value };
    }
    return { value: null, texts: [...sel.options].map((o) => o.textContent.trim()) };
  });
  if (!picked || picked.value === null) {
    record('ui/switch-fixture', 'fail', `选择器中无夹具甲选项（options=${JSON.stringify(picked?.texts ?? selInfo.texts ?? [])}）`);
  } else {
    await rootSel.locator('select').first().selectOption(picked.value);
    await page.waitForTimeout(1400);
    const wire = docReqs.some((u) => u.includes('/api/wf/docs/') && u.includes('project=fixa'));
    record('wire/project-param', wire, `切换后请求带 ?project=fixa=${wire}（客户端显式传键=反 viewProject 漂移）`);
    const fxaShown = await items.filter({ hasText: '夹具甲指南' }).first().isVisible().catch(() => false);
    const sandbarGone = !(await items.filter({ hasText: /terminology|项目术语表/ }).first().isVisible().catch(() => false));
    record('ui/switch-fixture-tree', fxaShown && sandbarGone,
      `树随所选项目切换：夹具甲指南=${fxaShown} sandbar 篇目退场=${sandbarGone}（KI-070 用户可感知面）`);

    // ---- T3 开篇 + chip + 大纲 ----
    const guide = items.filter({ hasText: '夹具甲指南' }).first();
    await guide.click().catch(() => {});
    await page.waitForTimeout(1200);
    const bodyShown = await rootSel.getByText('夹具甲正文标题').first().isVisible().catch(() => false);
    record('ui/doc-body-renders', bodyShown, bodyShown ? '正文真渲染（夹具甲正文标题在场）' : '开篇后正文标题未渲染');
    // 面包屑（N1 终态化：mock v1 顶条元素——随选篇更新，含「Docs」根词+篇目标题）
    const crumb = await page.evaluate(() => {
      const el = document.querySelector('[data-wb-doc-breadcrumb]');
      return el ? (el.textContent || '').trim() : '';
    });
    record('ui/breadcrumb-updates', crumb.includes('Docs') && crumb.includes('夹具甲指南'),
      `面包屑随选篇更新：「${crumb.slice(0, 60)}」（根词 Docs+篇目标题）`);

    for (const k of ['Status', 'Verified', 'Category', 'Updated', 'Path']) {
      const vis = await rootSel.getByText(k, { exact: true }).first().isVisible().catch(() => false);
      record(`ui/chip-${k.toLowerCase()}`, vis, `chip 键「${k}」在场=${vis}`);
    }
    const vinfo = await page.evaluate(() => {
      const root = document.querySelector('[data-wb-docs-root]');
      if (!root) return { present: false, texts: [], dated: [], pending: false };
      const leaves = [...root.querySelectorAll('*')].filter((el) => el.children.length === 0 && /Verified/.test(el.textContent || ''));
      const texts = leaves.map((el) => (el.textContent || '').trim());
      return {
        present: texts.length > 0,
        texts,
        dated: texts.filter((t) => /\d{2,4}[-/.]\d{1,2}/.test(t)),
        pending: texts.some((t) => /pending/i.test(t)) || [...root.querySelectorAll('*')].some((el) => el.children.length === 0 && /pending/i.test(el.textContent || '')),
      };
    });
    record('ui/verified-pending-placeholder', vinfo.present && vinfo.pending && vinfo.dated.length === 0,
      `Verified=pending 显式占位=${vinfo.pending} 无日期形状=${vinfo.dated.length === 0}（texts=${JSON.stringify(vinfo.texts).slice(0, 120)}；不留假值口径终态化）`);

    const outlineHeader = await rootSel.getByText('On this page', { exact: true }).first().isVisible().catch(() => false);
    const outlineCount = await rootSel.getByText('小节乙').count();
    record('ui/outline-renders', outlineHeader && outlineCount >= 2,
      `On this page 在场=${outlineHeader} 大纲条目+正文标题出现次数=${outlineCount}（≥2=大纲随选中文档渲染出 h2 条目）`);
    // 点击跳转：逐个候选点击（大纲条目/正文标题序不可锚），断言目标 h2 滚入视口
    let jumped = false;
    const candidates = await rootSel.getByText('小节乙').all();
    for (const m of candidates) {
      if (!(await m.isVisible().catch(() => false))) continue;
      await m.click().catch(() => {});
      await page.waitForTimeout(900);
      const pos = await page.evaluate(() => {
        const h = [...document.querySelectorAll('h2,h3')].find((x) => (x.textContent || '').includes('小节乙'));
        if (!h) return null;
        const r = h.getBoundingClientRect();
        return { top: r.top, vh: window.innerHeight };
      });
      if (pos && pos.top >= -80 && pos.top < pos.vh) { jumped = true; break; }
    }
    record('ui/outline-click-jumps', jumped, jumped ? '点大纲条目目标 h2 入视口（点击跳转生效）' : '大纲条目点击后目标标题未入视口');
  }

  // ---- T4 分组折叠（组头点按 → 条目可见性翻转；组头=含「总目录」的最内层元素）----
  const headBox = await page.evaluate(() => {
    const root = document.querySelector('[data-wb-docs-root]');
    if (!root) return null;
    const cands = [...root.querySelectorAll('*')].filter((el) => {
      const t = (el.textContent || '').trim();
      return t.includes('总目录') && t.length < 20 && !el.querySelector('[data-wb-doc-item]');
    });
    const innermost = cands.filter((el) => !cands.some((o) => o !== el && el.contains(o)));
    if (!innermost.length) return null;
    const r = innermost[0].getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  if (!headBox) {
    record('ui/group-fold-toggle', 'fail', '未见「总目录」组头（根级文件单列总目录组=docs-model C2 既有口径；实现落地前红属预期）');
  } else {
    const guideItem = items.filter({ hasText: '夹具甲指南' }).first();
    const beforeVis = await guideItem.isVisible().catch(() => false);
    await page.mouse.click(headBox.x, headBox.y);
    await page.waitForTimeout(700);
    const afterVis = await guideItem.isVisible().catch(() => false);
    await page.mouse.click(headBox.x, headBox.y);
    await page.waitForTimeout(700);
    const restoredVis = await guideItem.isVisible().catch(() => false);
    record('ui/group-fold-toggle', beforeVis && !afterVis && restoredVis,
      `折叠翻转：折叠前=${beforeVis} 点组头后隐藏=${!afterVis} 再点恢复=${restoredVis}`);
  }

  // ---- T5 Search 过滤（当前项目内按标题/路径收窄）----
  const searchInput = rootSel.locator('input').first();
  await searchInput.fill('深篇').catch(() => {});
  await page.waitForTimeout(800);
  const deepShown = await items.filter({ hasText: '夹具甲深篇' }).first().isVisible().catch(() => false);
  const guideHidden = !(await items.filter({ hasText: '夹具甲指南' }).first().isVisible().catch(() => false));
  record('ui/search-narrows', deepShown && guideHidden,
    `输入「深篇」后：深篇条目=${deepShown} 指南条目被滤=${guideHidden}（标题/路径匹配收窄）`);
  await searchInput.fill('').catch(() => {});
  await page.waitForTimeout(600);
  const guideBack = await items.filter({ hasText: '夹具甲指南' }).first().isVisible().catch(() => false);
  record('ui/search-clear-restores', guideBack, `清空后列表还原=${guideBack}`);

  // ---- T6 空态退化（夹具乙无 notes/：诚实 reason + 不残留 + 不炸）----
  const pickedB = await page.evaluate(() => {
    const sel = document.querySelector('[data-wb-docs-root] select');
    if (!sel) return null;
    for (const o of sel.options) {
      if (/夹具乙/.test(o.textContent)) return { value: o.value };
    }
    return null;
  });
  if (!pickedB) {
    record('ui/empty-notes-degraded', 'fail', '选择器中无夹具乙选项（空态子用例无载体）');
  } else {
    await rootSel.locator('select').first().selectOption(pickedB.value);
    await page.waitForTimeout(1400);
    const fxbShown = await items.filter({ hasText: '夹具乙单篇' }).first().isVisible().catch(() => false);
    const notesTab = rootSel.getByText('Notes', { exact: true }).first();
    if (!(await notesTab.isVisible().catch(() => false))) {
      record('ui/empty-notes-degraded', 'fail', 'Notes 页签不在场（空态子用例无从走起）');
    } else {
      await notesTab.click();
      await page.waitForTimeout(1200);
      const alive = await rootSel.isVisible().catch(() => false);
      const zeroItems = (await items.count()) === 0 || !(await items.first().isVisible().catch(() => false));
      // 残留检查锚内容区（data-wb-docs-frame=目录+正文+t260910-10 新增大纲），不锚整根：
      // 原生 <select>（T1/T2 钦定的切换器形态）的 innerText 必含全部 option 文本——
      // 「夹具甲」作为注册项目选项在场是切换器本职，不是上一项目内容残留（t260910-10
      // 实现段修正：整根 innerText 判残留与本项目切换器存在性自相矛盾，永假；语义不变，
      // 面收窄到阅读区）。
      const viewText = await rootSel.locator('[data-wb-docs-frame]').innerText().catch(() => '');
      const honest = /不存在|为空|没有|empty/i.test(viewText);
      const noStale = !viewText.includes('夹具甲');
      record('ui/empty-notes-degraded', alive && zeroItems && honest && noStale,
        `空 scope 退化：视图存活=${alive} 零条目=${zeroItems} 诚实 reason 在场=${honest} 不残留夹具甲=${noStale}（On this page 空与 reason 措辞不锚字面）`);
    }
  }
} finally {
  await browser.close().catch(() => {});
  bench.teardown();
}
summarize();
