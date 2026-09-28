// sc_ticket_detail_panel.mjs — t260905-07 场景①：工单详情下钻面板用户可感知面（隔离台浏览器真点）。
//
// intent（灰盒，用户可感知行为；工单验收①② + gen2 方案改动清单 6/7/9 + review 三轮口径）：
//   工单列表点行=详情面板（宿主看进度的主入口）：行点击开详情抽屉（.wb-drawer 在场）。
//   契约变更留痕（260925 t260925-18 收口 645cc62，本场景 260928 随 main 红对齐）：
//   原意图「抽屉内四块观测数据在场——阶段时间线/最近交接/门与签字记录/工作流快照要点
//   （data-wb-digest=…，KI-019 乱序归位/缺 at 沉底口径）」**已被产品契约取代**——该折叠
//   面板（.wb-d2-snapshot）与四区块整体移除（E3「底部六区块移除」），移除面之反面归
//   t260925-18-ui-english-spec-markdown E3 专守；本场景相应 9 条子用例注销（见 T5 段注），
//   不重复该 intent。KI-019 数据模型面（缺轮次/并行维度）本就不属本场景写集。
//   无标题老票（t260903-10 现场）列表行显示正文首句、不裸编号（首句截断口径：含首句、
//   不含第二句）；数据通道=enrich=progress 既有链路加派生字段 title_or_first（show body
//   裁句，零新请求；title 非空票跳过裁剪=实现声明口径，本场景只硬钉无标题票的值）——
//   主请求窗口零 show 由 17 号契约场景看守，此处不重复（intent 查重：t260904-17 只断言
//   「详情面在场」，无下钻区块渲染 intent）。行导航=纯导航零写 API（写端点请求=0）。
//
// 绑定锚（灰盒：绑实现已交付的可测性锚与用户可感知文案，不绑内部结构）：
//   - 行卡展示标题 span.wb-card-title 的 data-wb-row-title 属性（值=展示标题，
//     data-title-src=title/first/id 源标注；与 run_scenarios 注册文本 data-wb-*
//     契约一致）；
//   - 详情抽屉 .wb-drawer（现存契约锚）。
//   实现落地后本场景应在 3199 隔离台全绿；playwright-core 或隔离台依赖缺失=ENV_FAIL
//   （exit 2，KI-036 家族，环境红不假绿、不静默放行）。
//
// high-level steps：
//   T0 自举隔离台（FIX 桩票源：无标题老票+有标题运行票；show 含乱序 timeline/缺 at 条目/
//      signatures/gate_runs/handoffs）+ playwright 探测（缺失=环境红）。
//   T1 导航：开台 → 关出厂 notice → 工单列表（行卡在场）。
//   T2 无标题票行卡标题=首句（含首句、不含第二句、非裸编号）；有题票显示标题原文。
//   T3 enrich=progress 契约：t260903-10 的 title_or_first=正文首句（含句读符）。
//   T4 行点击 → 详情抽屉开合（.wb-drawer 在场）。
//   T5（注销）快照要点四区块：原断四 data-wb-digest 区块在场 + timeline 乱序归位 +
//      交接/门与签字/工作流内容可达——产品随 t260925-18 移除该面，子用例注销（见 T5 段注）。
//   T6 零写 API：行点击+抽屉打开全程写端点请求=0。
//   T7 红线：端口 ≠ 3099/7233；finally 回收进程树/浏览器/临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na。

import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import {
  makeRegistryRoot, writeProjectEntry, makeTicketStub, bootConsole,
  teardownOnExit, loadPlaywright, dismissNotice, makeResults, tmpRoot,
} from '../t260904-17/lib_fix17.mjs'

const { record, summarize } = makeResults();

const NOW = Date.now();
const FIRST_SENT = '这是一张老工单的正文首句';
const SECOND_SENT = '第二句不该出现在首句截断里';
// firstSentenceOf 口径：第一个句读符（。！？!?；）截断且句读符随句。
const FIRST_SENT_FULL = `${FIRST_SENT}。`;

const wfAlpha = { id: 'wf-alpha', name: '模板甲', stages: [
  { id: 's1', name: '起草' }, { id: 's2', name: '核验' }, { id: 's3', name: '实现' },
  { id: 's4', name: '审批' }, { id: 's5', name: '发布' },
] };

const row = (over) => ({
  id: over.id, project: 'proj-a', title: over.title, role: 'developer',
  status: over.status ?? 'running', stage: over.stage ?? null, stage_state: over.stage_state ?? 'running',
  workflow: over.workflow, workflow_id: over.workflow, epic: '',
  handoff_count: 1, pending_count: 0, worktree: over.worktree,
  updated: '2026-09-05 00:00:00', updated_ts: over.updated_ts ?? NOW - 300_000, created: NOW - 3_600_000,
  // show 扁平 detail 透传面（client 消费 detail.signatures/gate_runs/handoffs/body——扁平键；
  // gates/handoffs 的 at 口径=字符串时间戳，timeline 的 at=数值 ms 亦可）。
  body: over.body, signatures: over.signatures, gate_runs: over.gate_runs, handoffs: over.handoffs,
});

const tickets = [
  row({
    id: 't260903-10', title: null, body: `${FIRST_SENT_FULL}${SECOND_SENT}。`,
    stage: 's2', workflow: 'wf-alpha', worktree: '.lane/t260903-10',
    signatures: { merge: { who: 'gen0', decision: 'approved', at: '2026-09-05T10:05:00Z' } },
    gate_runs: [{ stage: '核验', kind: 'verify', result: 'pass', at: '2026-09-05T10:00:00Z' }],
    handoffs: [{ from: 'developer', to: 'integration', at: '2026-09-05T09:30:00Z', note: '交接说明' }],
  }),
  row({
    id: 't-run-2', title: '有标题的运行票', body: '有题票的正文首句。',
    stage: 's3', workflow: 'wf-alpha', worktree: '.lane/t-run-2', updated_ts: NOW - 60_000,
    signatures: {}, gate_runs: [], handoffs: [],
  }),
];

// 乱序 timeline（KI-019 触及面）：s3 晚事件在前、s2 早事件在后 + 一条缺 at（沉底标注）。
const messyTimeline = [
  { at: NOW - 60_000, stage: 's3', state: 'done' },
  { at: NOW - 300_000, stage: 's2', state: 'done' },
  { stage: 's2', state: 'started' },
];

const stub = makeTicketStub();
stub.setCtrl({
  workflows: [wfAlpha], tickets,
  show: Object.fromEntries(tickets.map((t) => [t.id, {
    mode: 'ok', timeline: t.id === 't260903-10' ? messyTimeline
      : [{ at: NOW - 60_000, stage: t.stage ?? 's1', state: 'running' }],
    pending: [],
  }])),
});

const pw = await loadPlaywright();
if (!pw) {
  record('dp/playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：真点子用例环境红');
  summarize();
}

let bench;
try {
  const projectsRoot = makeRegistryRoot('t260905-dp-reg-');
  writeProjectEntry(projectsRoot, 'proj-a', '夹具甲', [tmpRoot('t260905-dp-fixa-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('dp/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('dp/boot', true, bench.base);
record('dp/redline-ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}（3099/7233 零接触）`);

const { chromium } = pw;
const boardCard = (page, id) => page.locator(`[data-ticket-id="${id}"][data-compact="false"]`);
const clickish = async (page, loc) => {
  try { await loc.click({ timeout: 4000 }); }
  catch { await loc.evaluate((el) => el.click()).catch(() => {}); }
};
const gotoBoard = async (page) => {
  await bench.goto(page, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  const board = page.locator('[title="Tickets"], [aria-label="Tickets"]').first();
  try { await board.click({ timeout: 4000 }); } catch { await board.evaluate((el) => el.click()).catch(() => {}); }
  await boardCard(page, 't260903-10').waitFor({ state: 'visible', timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(400);
};

let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => chromium.launch({ headless: true }));
} catch (e) {
  record('dp/browser', 'env_fail', `浏览器不可用：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`);
  summarize();
}

const OUT_DIR = join(process.cwd(), '.suyou', 'screenshots', 't260905-07');  // naming-compat
const writeApis = [];

try {
  const page = await browser.newPage();
  mkdirSync(OUT_DIR, { recursive: true });
  page.on('request', (req) => {
    const m = req.method();
    if (m !== 'GET' && req.url().includes('/sandbar-workbench/api/')) writeApis.push(`${m} ${req.url()}`);
  });

  // T1 导航
  await gotoBoard(page);
  record('dp/nav-rowcards', await boardCard(page, 't260903-10').isVisible().catch(() => false)
    && await boardCard(page, 't-run-2').isVisible().catch(() => false), '两票行卡在场（走查基座）');

  // T2 无标题票=首句不裸编号（验收②）
  {
    // data-wb-row-title=展示标题（含源标注 data-title-src）——注册契约锚
    const noTitle = (await boardCard(page, 't260903-10').locator('.wb-card-title')
      .getAttribute('data-wb-row-title').catch(() => '')) ?? '';
    const titled = (await boardCard(page, 't-run-2').locator('.wb-card-title')
      .getAttribute('data-wb-row-title').catch(() => '')) ?? '';
    const noTitleSrc = (await boardCard(page, 't260903-10').locator('.wb-card-title')
      .getAttribute('data-title-src').catch(() => '')) ?? '';
    record('dp/row-title-first-sentence',
      noTitle.includes(FIRST_SENT) && !noTitle.includes(SECOND_SENT) && noTitle !== 't260903-10',
      `无标题票行卡标题=「${noTitle.slice(0, 40)}」（含首句、不含第二句、非裸编号）`);
    record('dp/row-title-src-first', noTitleSrc === 'first',
      `data-title-src=${noTitleSrc}（首句来源标注=first，非裸编号兜底）`);
    record('dp/row-title-kept', titled === '有标题的运行票', `有题票行卡标题=「${titled}」（原文不动）`);
  }

  // T3 enrich=progress 派生字段（数据通道契约；title 非空票跳过裁剪=实现声明口径，不硬钉）
  {
    let ok = false, got = '', detail = '';
    try {
      const res = await fetch(`${bench.base}/sandbar-workbench/api/wf/tickets?project=proj-a&enrich=progress`);
      const j = await res.json();
      const rows = (j?.result?.tickets ?? j?.tickets ?? []);
      const r = rows.find((x) => x?.id === 't260903-10');
      got = r?.title_or_first ?? '';
      ok = res.ok && got === FIRST_SENT_FULL;
      detail = `HTTP ${res.status}，title_or_first=「${String(got).slice(0, 40)}」`;
    } catch (e) { detail = `enrich 请求失败：${String(e?.message ?? e).slice(0, 120)}`; }
    record('dp/enrich-title-or-first', ok, `${detail}（期望=「${FIRST_SENT_FULL}」：首句含句读符）`);
  }

  // T4 行点击 → 详情抽屉开合（验收①开合面）
  await clickish(page, boardCard(page, 't260903-10'));
  const drawerVisible = await page.locator('.wb-drawer').waitFor({ state: 'visible', timeout: 8000 })
    .then(() => true).catch(() => false);
  record('dp/row-opens-drawer', drawerVisible, '行点击后详情抽屉在场（.wb-drawer）');
  await page.screenshot({ path: join(OUT_DIR, 'detail-panel-open.png') }).catch(() => {});

  // T5 快照要点四区块：**已随 t260925-18 契约变更注销**（该票 260925 收口 645cc62）。
  //   原意图（本场景立项时）：抽屉内 `.wb-d2-snapshot` 折叠面板里的四块观测数据
  //     ——data-wb-digest="workflow|timeline|handoffs|signatures"，含 KI-019 呈现口径
  //     （timeline 乱序按 at 升序归位、缺 at 条目沉底带「时间缺失」标注）。
  //   新契约（t260925-18 票面 E3「底部六区块移除」，已入 main）：该折叠面板与四区块
  //     **整体不再渲染**——产品源码与构建产物 grep `data-wb-digest` / `wb-d2-snapshot`
  //     均 0 命中；移除面之反面（这些区块不得在抽屉出现）由场景
  //     t260925-18-ui-english-spec-markdown E3 专守，本场景不重复该 intent（integration
  //     纪律：同一意图已有用例覆盖时不另起）。故此处**注销**这组子用例——
  //     不是放宽以求绿：所断言的 UI 已不存在，硬留即永久假红且会把诊断引向幽灵缺陷。
  //   原 9 条子用例与该面板同进退，注销清单见本文件头注 T5 行。
// T6 零写 API（行导航纯导航；「没看过就签了」危害面）
  record('dp/zero-write-api', writeApis.length === 0,
    writeApis.length ? `写端点被触发：${writeApis.slice(0, 3).join(' | ')}` : '全程写端点请求=0');
} catch (e) {
  record('dp/unexpected', false, `场景异常：${String(e?.message ?? e).slice(0, 200)}`);
} finally {
  try { await browser?.close(); } catch { /* 已关 */ }
}
summarize();
