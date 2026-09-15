// sc_doc_read_through.mjs — t260905-06 场景②：目录→篇→正文真渲染 + notes 观察窗 + 移动窄栏（隔离台浏览器走查）。
//
// intent（灰盒，用户可感知行为；工单验收②⑤ + 「移动窄栏可用」 + gen1 方案改动清单2/3 + review R2③⑤/V1）：
//   用户点开「文档」入口后能完成完整阅读链路：目录出真库篇目 → 点篇 → 正文 markdown
//   真渲染（标题文本在场、围栏代码块等宽）。断言锚=真库 committed 稳定篇目
//   （docs/terminology.md 根级无嵌套 / docs/testing-guide.md 含围栏代码块 /
//   notes/README.md）——真库即夹具：committed 内容稳定、天然覆盖 frontmatter/中文路径/
//   嵌套子目录形状，且不向仓根写夹具文件（防污染真源）。API 契约面顺链守：tree 200
//   含锚篇目、skipped 可见性字段在场（人读视图完整性可判定）、畸形 path fail-closed
//   不外泄正文；notes 观察窗页签切换后 notes 树真出内容（scope=notes 200 含 epics/ 篇目）。
//   窄栏腿按 review V1①基线对照口径，落地=容器级（@container 360px 压缩）：壳在窄视口
//   会卸载本插件槽（探针实证），容器级响应才对「中列被压缩」这一真实窄形态成立；宽栏
//   先量全局溢出基线，窄容器走通目录→返回→再开篇后断言不新增全局溢出
//   视图完成同链路后断言「不新增全局溢出」——不锚内部类名，存量布局欠账不误伤。
//   浏览器依赖缺失=env_fail（KI-036 家族）；实现落地前红属预期（TDD），arbitrate/merge 期必须绿。
//
// high-level steps：
//   T0 自举隔离台（lib_fix17 复用）+ playwright 探测（缺失=env_fail）。
//   T1 API 契约面（真库）：GET /api/wf/docs/tree?scope=docs → 200、JSON 含
//      README.md 与 terminology.md、skipped 数组字段在场；scope=notes → 200 含
//      README.md 且存在 epics/ 前缀篇目；GET doc?scope=docs&path=terminology.md →
//      200 body 含「项目术语表」；畸形 path（../ 穿越）→ fail-closed：非 200 或
//      empty=true 带 reason，响应不含穿出文件内容。
//   T2 UI 链路（宽栏）：点「文档」→ 目录含 terminology 条目 → 点开 → 正文区出现
//      「项目术语表」标题文本；切 testing-guide 条目 → 正文含「测试环境隔离指南」
//      且视图内 pre code computed font-family 含 mono（代码块等宽渲染）。
//   T3 notes 观察窗：点 notes 页签 → scope=notes 的 tree 请求 200 且目录区出现
//      notes 篇目条目（README）。
//   T4 移动窄栏（V1①基线对照，容器级落地）：量宽栏全局溢出基线 → 复位 scope 页签 →
//      容器压 360px（@container 单栏流触发）→ has-doc 收目录+返回钮往返+再开篇
//      （「项目术语表」在场）→ 断言终态 scrollWidth ≤ 基线（不新增全局溢出）。
//   T5 红线：端口 ≠ 3099/7233；finally 回收进程树/浏览器/临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na（三态=闸内无 SKIP 的现行定稿，旧 SKIP 语义退役）。
import {
  REPO_ROOT, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
} from '../t260904-17/lib_fix17.mjs';

const { record, summarize } = makeResults();

const stub = makeTicketStub();

const pw = await loadPlaywright();
if (!pw) {
  record('playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：浏览器走查腿环境红');
  summarize();
}

let bench;
try {
  const projectsRoot = makeRegistryRoot('t090506-read-reg-');
  // t260915-10 夹具根变更留痕：旧值=空临时目录，旧文档页语义（无 project= 缺省回落）下
  // UI 腿靠回落见引擎库；t260915-10 起文档页初值跟随壳层项目（经 fixa 组图标进入=带
  // project=fixa 请求），空目录会诚实空态断红——夹具根改指引擎仓根（REPO_ROOT，真库
  // docs/notes committed 内容即本场景「真库即夹具」载体），「单仓阅读链路」intent 不变。
  writeProjectEntry(projectsRoot, 'fixa', '夹具甲', [REPO_ROOT]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', 'pass', bench.base);
record('redline/ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}`);

// ---- T1 API 契约面（真库，HTTP 直读隔离台）----
async function getJson(pathname) {
  try {
    const r = await fetch(`${bench.base}${pathname}`, { signal: AbortSignal.timeout(15000) });
    return { status: r.status, body: await r.json().catch(() => null) };
  } catch (e) { return { status: 0, body: null, err: String(e) }; }
}
// 树结构未知（嵌套/聚合形状属实现自由度）——扁平化收集所有 path 字段与字符串叶，
// 断言只锚「篇目可达」不锚树形（灰盒浅绑定）。
function collectPaths(node, out) {
  if (!node || typeof node !== 'object') return out;
  if (Array.isArray(node)) { for (const x of node) collectPaths(x, out); return out; }
  for (const [k, v] of Object.entries(node)) {
    if (typeof v === 'string' && /\.(md)$/.test(v)) out.push(v);
    else if (k === 'path' && typeof v === 'string') out.push(v);
    else collectPaths(v, out);
  }
  return out;
}

const treeDocs = await getJson('/sandbar-workbench/api/wf/docs/tree?scope=docs');
if (treeDocs.status !== 200 || !treeDocs.body) {
  record('api/tree-docs', 'fail', `GET tree?scope=docs → ${treeDocs.status}（目录加载契约未兑现；实现落地前红属预期）`);
} else {
  const paths = collectPaths(treeDocs.body, []);
  const hasReadme = paths.some((p) => p.endsWith('README.md') && !p.includes('/'));
  const hasTerm = paths.some((p) => p.endsWith('terminology.md'));
  record('api/tree-docs-anchors', hasReadme && hasTerm, `docs 树锚篇目 README.md=${hasReadme} terminology.md=${hasTerm}（共 ${paths.length} 篇）`);
  record('api/tree-skipped-field', Array.isArray(treeDocs.body?.result?.skipped), `skipped 字段=${Array.isArray(treeDocs.body?.result?.skipped) ? `array(${treeDocs.body.result.skipped.length})` : '缺席'}（拒收可见性契约；{ok,result} 包装风格）`);
}
const treeNotes = await getJson('/sandbar-workbench/api/wf/docs/tree?scope=notes');
if (treeNotes.status !== 200 || !treeNotes.body) {
  record('api/tree-notes', 'fail', `GET tree?scope=notes → ${treeNotes.status}`);
} else {
  const npaths = collectPaths(treeNotes.body, []);
  record('api/tree-notes-anchors', npaths.some((p) => p.endsWith('README.md')) && npaths.some((p) => p.includes('epics/')),
    `notes 树锚：README.md=${npaths.some((p) => p.endsWith('README.md'))} epics/ 篇目=${npaths.some((p) => p.includes('epics/'))}（共 ${npaths.length} 篇）`);
}
const docTerm = await getJson(`/sandbar-workbench/api/wf/docs/doc?scope=docs&path=${encodeURIComponent('terminology.md')}`);
record('api/doc-term-readme', docTerm.status === 200 && JSON.stringify(docTerm.body ?? '').includes('项目术语表'),
  `doc terminology.md → ${docTerm.status}，含「项目术语表」=${JSON.stringify(docTerm.body ?? '').includes('项目术语表')}`);
const docEscape = await getJson('/sandbar-workbench/api/wf/docs/doc?scope=docs&path=..%2Fpackage.json');
const escBody = JSON.stringify(docEscape.body ?? {});
record('api/doc-path-traversal-failclosed', (docEscape.status !== 200 || docEscape.body?.result?.empty === true) && !escBody.includes('"type"') && !escBody.includes('"private"'),
  `穿路径 ../package.json → ${docEscape.status} result.empty=${docEscape.body?.result?.empty}（fail-closed；文件内容泄漏=${escBody.includes('"private"')}`);

// ---- 浏览器腿（T2/T3/T4）----
const { chromium } = pw;
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => chromium.launch({ headless: true }));
} catch (e) {
  record('browser', 'env_fail', `浏览器可执行档缺失（npx playwright install 可解，KI-036 家族）：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`);
  summarize();
}

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  // 剪贴板权限（复制回归腿）：Chromium 剪贴板 API 需授权；拒绝=该腿 env_fail 由下方 catch 兜
  await browser.contexts()[0].grantPermissions(['clipboard-read', 'clipboard-write'], { origin: bench.base })
    .catch(() => {});
  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await page.waitForTimeout(500);

  const docIcon = page.locator('[aria-label="文档"]').first();
  const present = await docIcon.isVisible().catch(() => false);
  if (!present) {
    record('ui/entry-present', 'fail', '「文档」图标不在场（场景①已钉入口，本场景链路无从走起；实现落地前红属预期）');
    summarize();
  }

  // T2 宽栏链路：目录→篇→正文
  await docIcon.click();
  await page.waitForTimeout(1200);
  const termItem = page.getByText(/terminology|项目术语表/).first();
  const dirShown = await termItem.isVisible().catch(() => false);
  record('ui/dir-shows-anchor', dirShown, dirShown ? '目录出现 terminology 条目' : '目录未见 terminology 条目（真库篇目未进目录）');
  if (dirShown) {
    await termItem.click();
    await page.waitForTimeout(1000);
    const bodyTitle = await page.getByText('项目术语表').first().isVisible().catch(() => false);
    record('ui/doc-renders-title', bodyTitle, bodyTitle ? '正文渲染出「项目术语表」标题' : '正文区未见标题文本（真渲染断言）');
    // 代码块等宽：切 testing-guide 篇（真库含 14 围栏块）
    const guideItem = page.getByText(/testing-guide|测试环境隔离指南/).first();
    if (await guideItem.isVisible().catch(() => false)) {
      await guideItem.click();
      await page.waitForTimeout(1000);
      const mono = await page.evaluate(() => {
        const code = document.querySelector('pre code');
        if (!code) return null;
        return getComputedStyle(code).fontFamily;
      });
      record('ui/code-mono', mono !== null && /mono/i.test(mono), `pre code font-family=${String(mono).slice(0, 80)}`);
      // 复制按钮行为回归（验收走查打回项 A 防回退腿）：出厂按钮无委托曾是死控件——
      // 点击后剪贴板必须含该代码块原文（data-code 解码语义）。
      try {
        await page.evaluate(() => navigator.clipboard.writeText('SENTINEL-t26090506'));
        const copyBtn = page.locator('.wb-doc-body .md-copy').first();
        const btnPresent = await copyBtn.isVisible().catch(() => false);
        if (!btnPresent) {
          record('ui/copy-button-works', 'fail', '代码块「复制」按钮不在场（A 回归：自持委托缺失）');
        } else {
          await copyBtn.click();
          await page.waitForTimeout(400);
          const clip = await page.evaluate(() => navigator.clipboard.readText());
          const expected = await page.evaluate(() => {
            const btn = document.querySelector('.wb-doc-body .md-copy');
            return btn ? decodeURIComponent(btn.getAttribute('data-code') ?? '') : null;
          });
          record('ui/copy-button-works', clip === expected && clip !== 'SENTINEL-t26090506',
            `点击后剪贴板=「${String(clip).slice(0, 40)}」期望=代码块原文（哨兵被覆写=${clip !== 'SENTINEL-t26090506'}，A 死控件复现判据=哨兵原样）`);
        }
      } catch (e) {
        record('ui/copy-button-works', 'env_fail', `剪贴板腿环境不可用（权限拒绝等）：${String(e?.message ?? e).slice(0, 120)}`);
      }
    } else {
      record('ui/code-mono', 'fail', '目录未见 testing-guide 条目（代码块等宽断言无载体）');
    }
  }

  // T3 notes 观察窗：页签切换 → notes 篇目出现
  // （finder 更新=t260910-10：页签文案随 mock v1 固定元素英文化改为 "Notes"，定位改走
  //   契约锚 data-wb-docs-scope-notes——断言语义不变：notes 页签在场且切换后出 notes 篇目。）
  const notesTab = page.locator('[data-wb-docs-scope-notes]').first();
  if (await notesTab.isVisible().catch(() => false)) {
    await notesTab.click();
    await page.waitForTimeout(1200);
    // notes 链路走全：目录→打开 notes/README（无 frontmatter 回落文件名）→正文锚文本
    const notesItem = page.locator('[data-wb-doc-item]').filter({ hasText: /README|notes/ }).first();
    if (await notesItem.isVisible().catch(() => false)) {
      await notesItem.click();
      await page.waitForTimeout(1000);
    }
    const notesShown = await page.getByText(/毕业规则|讨论与立项/).first().isVisible().catch(() => false);
    record('ui/notes-scope-shown', notesShown, notesShown ? 'notes 页签切换+开篇后 notes 正文锚文本在场' : 'notes 切换/开篇后未见 notes/README 正文锚文本（毕业规则）');
  } else {
    record('ui/notes-scope-shown', 'fail', '未见 notes 页签（观察窗切换缺席）');
  }

  // T4 窄可用（R2③ + V1①基线对照，容器级口径）：不缩视口（壳在窄视口卸载本插件
  // 槽，探针实证）——直接把文档视图容器压到 360px（中列被压缩的真实形态，
  // @container 单栏流由此触发）。断言=选中态收目录+返回钮往返+再开篇可达。
  const root = page.locator('[data-wb-docs-root]');
  const frame = page.locator('[data-wb-docs-frame]');
  const baseline = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
  }));
  // T3 可能把 scope 留在 notes——先在宽栏（目录可见态）复位回定稿库页签；
  // 压窄后 has-doc 会收起目录，届时点不到页签（首跑实锚）。
  const docsTabN = page.locator('[data-wb-docs-scope-docs]');
  if (await docsTabN.isVisible().catch(() => false)) { await docsTabN.click(); await page.waitForTimeout(1000); }
  await page.evaluate(() => {
    const el = document.querySelector('[data-wb-docs-root]');
    el.style.width = '360px'; el.style.maxWidth = '360px'; el.style.height = '480px';
  });
  await page.waitForTimeout(800);
  record('ui/narrow-frame-present', (await root.count()) === 1, '360px 容器压下（T3 已选中篇，has-doc 单栏流生效中）');
  // 选中一篇 → has-doc 单栏流：目录收起、返回钮在场（定位走契约锚 data-wb-doc-item）
  const termNarrow = page.locator('[data-wb-doc-item]').filter({ hasText: /terminology/ }).first();
  if (await termNarrow.isVisible().catch(() => false)) { await termNarrow.click(); await page.waitForTimeout(800); }
  const frameCls = (await frame.getAttribute('class').catch(() => '')) ?? '';
  const backVisible = await page.locator('[data-wb-docs-back]').isVisible().catch(() => false);
  record('ui/narrow-single-column-flow', frameCls.includes('has-doc') && backVisible,
    `窄容器选中态=has-doc(${frameCls.includes('has-doc')}) 返回钮在场(${backVisible})`);
  if (backVisible) {
    await page.locator('[data-wb-docs-back]').click();
    await page.waitForTimeout(600);
    const tocAgain = await page.locator('[data-wb-docs-toc]').isVisible().catch(() => false);
    record('ui/narrow-back-to-toc', tocAgain, tocAgain ? '返回钮回目录成功（窄容器目录重现）' : '点返回后目录未重现');
    if (tocAgain) {
      const again = page.locator('[data-wb-doc-item]').filter({ hasText: /terminology/ }).first();
      if (await again.isVisible().catch(() => false)) { await again.click(); }
      const narrowTitle = await page.getByText('项目术语表').first().waitFor({ state: 'visible', timeout: 6000 })
        .then(() => true).catch(() => false);
      const diag = narrowTitle ? '窄容器 360px 走通目录→返回→再开篇'
        : `窄容器链路断：selected=${await page.locator('[data-wb-docs-root]').getAttribute('data-wb-docs-selected')} scope=${await page.locator('[data-wb-docs-root]').getAttribute('data-wb-docs-scope')} itemVisible=${await again.isVisible().catch(() => false)} itemCount=${await page.locator('[data-wb-doc-item]').count()} tocHead=${(await page.locator('[data-wb-docs-toc]').innerText().catch(() => '')).slice(0, 150)}`;
      record('ui/narrow-link-through', narrowTitle, diag);
    }
  }
  const after = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
  }));
  const noNewOverflow = after.sw <= Math.max(baseline.sw, baseline.cw);
  record('ui/narrow-no-new-overflow', noNewOverflow,
    `基线 sw=${baseline.sw}/cw=${baseline.cw} → 窄容器后 sw=${after.sw}/cw=${after.cw}（V1① 全局不新增溢出）`)
} finally {
  await browser.close().catch(() => {});
  bench.teardown();
}
summarize();
