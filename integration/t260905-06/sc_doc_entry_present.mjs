// sc_doc_entry_present.mjs — t260905-06 场景①：「文档」入口在场且键盘可达（隔离台浏览器走查）。
//
// intent（灰盒，用户可感知行为；工单验收① + gen1 方案改动清单3/4 + review R2①）：
//   用户在工单台左列项目组头图标枚里能找到「文档」入口（原「知识库」图标位，17 号
//   栅格语言原位替换），且不依赖鼠标：图标可键盘聚焦、Enter 触发切换——切换的用户
//   可感知面=中列打开文档视图并发起目录加载（GET /api/wf/docs/tree 200），图标进入
//   active 态（方案承诺的排他视图栅格语言）。「知识库」入口同步退场（同位不同名，
//   字样清零由场景③专守，此处只断言「知识库」aria-label 不在场）。
//   浏览器走查依赖 playwright-core（KI-036 家族）——缺失=环境红 env_fail 点名（干净跳过已退役，现行口径=闸内无 SKIP）。
//   实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// high-level steps：
//   T0 自举隔离台（lib_fix17 复用：临时注册表根+夹具项目+FIX17 桩；真库 docs/notes
//      即泳道仓根 committed 内容，服务端 DEFAULT_REPO 直读——不写仓根防污染）。
//      playwright 四路探测（缺失=env_fail）。
//   T1 入口在场：左列存在 [aria-label="文档"] 图标且 title=「文档」；
//      [aria-label="知识库"] 不在场（旧提法退役的入口面）。
//   T2 键盘可达：图标 .focus() 成功（可聚焦性）→ keyboard Enter →
//      中列发起 GET /api/wf/docs/tree?scope=docs 且 200（目录加载的用户可感知面）。
//      并发载荷下该腿曾间歇红（260911 仲裁实证：空闲 6/6 绿/请求 105ms，争抢下 1/3 红）
//      ——按 KI-072 处置方向②加**有界重试 ≤3 轮**（断言不变：三轮全无=真红；证据记命中轮次
//      与焦点归属，不掩盖竞态频率）。
//   T3 active 态：切换后图标 class 含 active（方案承诺排他视图高亮语言）。
//   T4 红线：端口 ≠ 3099/7233；finally 回收进程树/浏览器/临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na（三态=闸内无 SKIP 的现行定稿，旧 SKIP 语义退役）。
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
} from '../t260904-17/lib_fix17.mjs';

const { record, summarize } = makeResults();

const stub = makeTicketStub(); // 本票不消费票数据，bootConsole 形参必需；空 ctrl 即可

const pw = await loadPlaywright();
if (!pw) {
  record('playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：浏览器走查腿环境红');
  summarize();
}

let bench;
try {
  const projectsRoot = makeRegistryRoot('t090506-entry-reg-');
  writeProjectEntry(projectsRoot, 'fixa', '夹具甲', [tmpRoot('t090506-entry-fixa-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', 'pass', bench.base);
record('redline/ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}`);

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
  const page = await browser.newPage();
  const docTreeHits = [];
  page.on('response', (r) => {
    if (r.url().includes('/api/wf/docs/tree')) docTreeHits.push({ url: r.url(), status: r.status() });
  });

  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await page.waitForTimeout(500);

  // T1 入口在场（公开契约：方案承诺 title/aria-label=「文档」）
  const docIcon = page.locator('[aria-label="文档"]').first();
  const present = await docIcon.isVisible().catch(() => false);
  record('entry/icon-present', present, present ? 'aria-label=「文档」图标在场' : '左列未见 aria-label=「文档」图标（入口缺席或未实现）');
  if (present) {
    const title = await docIcon.getAttribute('title');
    record('entry/title', title === '文档', `title=${String(title)}`);
    const oldIcon = await page.locator('[aria-label="知识库"]').count();
    record('entry/old-icon-gone', oldIcon === 0, `aria-label=「知识库」图标计数=${oldIcon}（应为 0）`);
  }

  if (present) {
    // T2 键盘可达：聚焦 + Enter 触发目录加载（tree 请求 200）
    await docIcon.focus();
    const focused = await docIcon.evaluate((el) => el === document.activeElement);
    record('entry/focusable', focused, focused ? '图标可键盘聚焦' : '图标 focus() 后非 activeElement（不可聚焦/被吞）');
    // 有界重试（≤3 轮）=KI-072 处置方向②「这些检查需加时序容忍/重试」的落地点：
    // 260911 仲裁实证该腿在并发载荷下间歇红（单跑 3 连 2 绿 1 红、套件内 1 红；
    // 空闲诊断 6/6 绿、请求 105ms 到达、焦点始终在手——产品行为健康，红=墙钟窗口
    // 在争抢下不够）。**契约不变**：focus+Enter 必须触发 200 目录加载，三轮全无=真红；
    // 证据面记录命中轮次与每轮焦点归属，使重试不掩盖竞态频率（报错必须精确）。
    let okTree = false;
    let treeHits = [];
    let attempt = 0;
    const focusLog = [];
    for (let i = 1; i <= 3 && !okTree; i++) {
      attempt = i;
      await docIcon.focus();
      const held = await docIcon.evaluate((el) => el === document.activeElement);
      focusLog.push(`#${i}${held ? '焦点在' : '焦点丢'}`);
      const hitsBefore = docTreeHits.length;
      await page.keyboard.press('Enter');
      await page.waitForTimeout(1500);
      treeHits = docTreeHits.slice(hitsBefore);
      okTree = treeHits.some((h) => h.status === 200);
    }
    record('entry/enter-loads-tree', okTree,
      okTree ? `Enter 触发 docs/tree 200：${treeHits.map((h) => h.url.split('?')[1] ?? '').join(' ; ')}（命中第 ${attempt}/3 轮；${focusLog.join(' ')}）` : `Enter 三轮后仍无 200 的 tree 请求（hits=${JSON.stringify(treeHits)}；${focusLog.join(' ')}）`);

    // T3 active 态（方案承诺的排他视图高亮）
    if (okTree) {
      const active = await docIcon.evaluate((el) => el.className.includes('active')).catch(() => false);
      record('entry/active-state', active, active ? '图标进入 active 态' : '切换后图标无 active 类（高亮语言缺席）');
    }
  }
} finally {
  await browser.close().catch(() => {});
  bench.teardown();
}
summarize();
