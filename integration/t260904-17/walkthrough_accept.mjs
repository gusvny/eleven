// walkthrough_accept.mjs — t260904-17 验收走查（acceptance_walkthrough 段证据脚本）。
//
// 定位：**验收走查证据脚本，非回归基线**——不登记 SCENARIOS（非 sc_ 前缀）；
// 回归面已由 sc_ticket_list_http_contract（host 契约）与 sc_ticket_list_rowcard_ui
// （行卡可感知面）覆盖，本脚本只补验收合同里场景未钉的走查面：
//   WT1 验收②全脸：epic 哈希色跨刷新恒同色（页面 reload 前后比对）＋新增无关 epic
//       后原 epic 色不漂移（纯函数确定性在 DOM 接线上的实证）；
//   WT2 收口折叠=计数行可展开（用户点开能真看到收口卡，非哑行）；
//   WT3 并行期 UI 呈现（验收合同专项检查项）：并行分叉 ticket 详情步骤条双边同亮
//       （两步同帧 data-s=running 且各带 ∥ 标记）＋状态行报「并行分叉中」——
//       隔离台 DOM 断言＋实拍输出为证；并顺带核迷你站道在并行票上的退化表现
//       （模型层已声明单指针取舍，这里钉「点数仍=模板阶段数、不崩溃」）。
//
// 夹具：FIX17 桩票源（lib_fix17 同缝）＋第三模板 wf-par（k1→k2a∥k2b→k3，
// ticket.meta.parallel_stages=['k2a','k2b']——引擎并行真源口径，lane-states 消费）。
// 红线：隔离台随机高端口，3099/7233 零接触；四路径回收沿 lib_fix17。
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
} from './lib_fix17.mjs';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

const { record, summarize } = makeResults();

const NOW = Math.floor(Date.now() / 1000);
const wfAlpha = { id: 'wf-alpha', name: '模板甲', stages: [
  { id: 's1', name: '起草' }, { id: 's2', name: '核验' }, { id: 's3', name: '实现' },
  { id: 's4', name: '审批' }, { id: 's5', name: '发布' },
] };
const wfBeta = { id: 'wf-beta', name: '模板乙', stages: [
  { id: 'b1', name: '分诊' }, { id: 'b2', name: '修复' }, { id: 'b3', name: '验收' },
] };
// 并行分叉模板（形状四形承诺之「并行分叉」在列表面+详情面的走查载体）。
const wfPar = { id: 'wf-par', name: '模板丙', stages: [
  { id: 'k1', name: '准备' }, { id: 'k2a', name: '并行甲' }, { id: 'k2b', name: '并行乙' },
  { id: 'k3', name: '收尾' },
] };
const row = (over) => ({
  id: over.id, project: 'fixa', title: over.title, role: 'developer',
  status: over.status, stage: over.stage ?? null, stage_state: over.stage_state,
  workflow: over.workflow,
  // show 形状对齐引擎真源（base.py meta 原生 workflow_id；list 行才改名 workflow）
  // ——缺它则详情抽屉模板查找扑空（「未挂模板」，D2Stepper 不渲）。
  workflow_id: over.workflow,
  epic: over.epic ?? '', handoff_count: 2, pending_count: 1,
  worktree: `/tmp/fix17/${over.id}`, updated: '2026-09-05 00:00:00',
  updated_ts: over.updated_ts ?? NOW - 300, created: NOW - 3600,
  blocked_reason: over.reason,
});
const tickets = [
  row({ id: 'trun', title: '行卡样例活跃票', status: 'running', stage_state: 'running', stage: 's3', workflow: 'wf-alpha', epic: 'alpha-epic' }),
  row({ id: 'twait', title: '行卡样例等你票', status: 'running', stage_state: 'awaiting-human', stage: 's4', workflow: 'wf-alpha', epic: 'alpha-epic', updated_ts: NOW - 60 }),
  row({ id: 'tblock', title: '行卡样例受阻票', status: 'running', stage_state: 'blocked', stage: 'b2', workflow: 'wf-beta', reason: '环境红：临时目录不可写' }),
  row({ id: 'tawait', title: '行卡样例排队票', status: 'running', stage_state: 'awaiting', workflow: 'wf-beta' }),
  row({ id: 'tclosed', title: '行卡样例收口票', status: 'closed', stage_state: 'awaiting', stage: 's5', workflow: 'wf-alpha' }),
  // 并行分叉票：真源=meta.parallel_stages（引擎快照口径），timeline 两步同时在跑。
  row({ id: 'tpar', title: '并行分叉样例票', status: 'running', stage_state: 'running', stage: 'k2a', workflow: 'wf-par', epic: 'beta-epic', updated_ts: NOW - 120 }),
];
tickets.find((x) => x.id === 'tpar').meta = { parallel_stages: ['k2a', 'k2b'] };
const parTimeline = [
  { at: NOW - 600, stage: 'k1', state: 'done' },
  { at: NOW - 120, stage: 'k2a', state: 'running' },
  { at: NOW - 120, stage: 'k2b', state: 'running' },
];

const stub = makeTicketStub();
stub.setCtrl({
  workflows: [wfAlpha, wfBeta, wfPar], tickets,
  show: Object.fromEntries(tickets.map((t) => [t.id, {
    mode: 'ok', timeline: t.id === 'tpar' ? parTimeline
      : [{ at: NOW - 60, stage: t.stage ?? 's1', state: t.stage_state }],
    pending: [],
  }])),
});

const OUT_DIR = path.join(process.cwd(), '.suyou', 'screenshots', 't260904-17');

const pw = await loadPlaywright();
if (!pw) {
  record('wt/playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：走查腿干净 SKIP');
  summarize();
}

let bench;
try {
  const projectsRoot = makeRegistryRoot('fix17-wt-reg-');
  writeProjectEntry(projectsRoot, 'fixa', '夹具甲', [tmpRoot('fix17-wt-fixa-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('wt/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('wt/boot', true, bench.base);
record('wt/redline-ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}（3099/7233 零接触）`);

const { chromium } = pw;
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => chromium.launch({ headless: true }));
} catch (e) {
  record('wt/browser', 'env_fail', `浏览器不可用：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`);
  summarize();
}

// ── 定位契约（与 sc_ticket_list_rowcard_ui 同口径）：板面卡=compact=false，避左栏撞车 */
const boardCard = (page, id) => page.locator(`[data-ticket-id="${id}"][data-compact="false"]`);
const barColor = (page, id) => boardCard(page, id).evaluate((el) => {
  for (const e of [el, ...el.querySelectorAll('*')]) {
    const cs = getComputedStyle(e);
    if (parseInt(cs.borderLeftWidth, 10) >= 3) return cs.borderLeftColor;
  }
  return '';
});
const rgbOf = (hex) => {
  const n = hex.replace('#', '');
  return `rgb(${parseInt(n.slice(0, 2), 16)}, ${parseInt(n.slice(2, 4), 16)}, ${parseInt(n.slice(4, 6), 16)})`;
};
const FALLBACK_RGB = 'rgb(156, 163, 175)'; // EPIC_FALLBACK_COLOR #9ca3af

async function gotoBoard(page) {
  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  const board = page.locator('[title="工单列表"], [aria-label="工单列表"]').first();
  try { await board.click({ timeout: 4000 }); } catch { await board.evaluate((el) => el.click()).catch(() => {}); }
  await boardCard(page, 'trun').waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(400);
}

async function clickish(page, loc) {
  try { await loc.click({ timeout: 4000 }); }
  catch { await loc.evaluate((el) => el.click()).catch(() => {}); }
}

try {
  const page = await browser.newPage();
  mkdirSync(OUT_DIR, { recursive: true });

  // WT0 导航
  await gotoBoard(page);
  record('wt/nav-rowcards', await boardCard(page, 'trun').isVisible().catch(() => false),
    '板面行卡在场（走查基座）');

  // WT1 验收②：跨刷新恒同色
  const c1 = await barColor(page, 'trun');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await gotoBoardNavOnly(page);
  const c2 = await barColor(page, 'trun');
  record('wt/epic-color-cross-refresh', c1 !== '' && c1 === c2 && c1 !== FALLBACK_RGB,
    `reload 前后 alpha-epic 彩条色=${c1} → ${c2}（同码恒同色且非兜底灰）`);

  // WT1b 验收②：新增无关 epic 不漂移
  tickets.push(row({ id: 'tnew', title: '新增无关 epic 票', status: 'running', stage_state: 'running', stage: 's1', workflow: 'wf-alpha', epic: 'zz-brand-new-epic' }));
  stub.setCtrl({
    workflows: [wfAlpha, wfBeta, wfPar], tickets,
    show: Object.fromEntries(tickets.map((t) => [t.id, {
      mode: 'ok', timeline: t.id === 'tpar' ? parTimeline
        : [{ at: NOW - 60, stage: t.stage ?? 's1', state: t.stage_state }],
      pending: [],
    }])),
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await dismissNotice(page);
  await gotoBoardNavOnly(page);
  const c3 = await barColor(page, 'trun');
  const cNew = await barColor(page, 'tnew');
  record('wt/epic-color-no-drift', c3 === c1 && cNew !== '' && cNew !== FALLBACK_RGB,
    `新增 epic 后 alpha-epic 仍=${c3}（与刷新前一致）；新 epic 色=${cNew}（色板内非兜底）`);

  // WT2 收口折叠：计数行点击展开
  const before = await boardCard(page, 'tclosed').count();
  const foldRow = page.locator('.wb-done-row').first();
  const foldTxt = await foldRow.innerText().catch(() => '');
  await clickish(page, foldRow);
  await page.waitForTimeout(500);
  const after = await boardCard(page, 'tclosed').count();
  record('wt/collapse-expand', before === 0 && after === 1 && /收口\s*·\s*1/.test(foldTxt),
    `展开前收口卡=${before}（折叠态），折叠行文案=「${foldTxt.trim().slice(0, 24)}」，点击后收口卡=${after}`);

  // WT2b F2 回归（验收①时间语义）：引擎秒级 updated_ts → toMillis 归一 → 人话相对时间。
  // UT 只锁 relativeTime∘toMillis 组合，本腿锁行卡消费点全链（回归前此位显「2 万天前」）。
  {
    const t = (await boardCard(page, 'twait').locator('.wb-card-time').innerText().catch(() => '')).trim();
    record('wt/reltime-unit-fix', /^(刚刚|\d+ 分钟前)$/.test(t),
      `twait（updated_ts=NOW-60s）行卡时间文案=「${t}」（期望「N 分钟前」档；禁「N 天前」级错值）`);
  }

  // WT3 迷你站道：并行票点数仍=模板阶段数、当前点恰 1（单指针取舍的退化表现）
  {
    const card = boardCard(page, 'tpar');
    const dots = await card.locator('.wb-card-lane-dot').count();
    const cur = await card.locator('.wb-card-lane-dot[data-visual="current"]').count();
    record('wt/minilane-parallel-degradation', dots === 4 && cur === 1,
      `并行票迷你站道点数=${dots}（=模板丙 4 阶段）、当前点=${cur}（单指针口径：并行另一 active 步渲灰=模型层已声明取舍）`);
  }

  // WT4 并行期 UI 呈现（验收合同专项）：详情步骤条双边同亮+∥+状态行
  {
    await page.screenshot({ path: path.join(OUT_DIR, 'wt-board-rowcards.png') });
    await clickish(page, boardCard(page, 'tpar'));
    await page.waitForTimeout(1500);
    const drawer = page.locator('.wb-drawer').first();
    const drawerVisible = await drawer.isVisible().catch(() => false);
    const runningSteps = await drawer.locator('.wb-d2-steps .wb-d2-step[data-s="running"]').count();
    const parMarks = await drawer.locator('.wb-d2-par').count();
    const body = await page.locator('body').innerText();
    const statusLine = body.includes('并行分叉中');
    record('wt/parallel-double-lit', drawerVisible && runningSteps === 2,
      `详情抽屉=${drawerVisible}，同帧 data-s=running 步骤数=${runningSteps}（期望 2：k2a∥k2b）`);
    record('wt/parallel-markers', parMarks >= 1,
      `∥ 分叉标记数=${parMarks}（每并行步各带一枚）`);
    record('wt/parallel-status-line', statusLine,
      statusLine ? '状态行报「并行分叉中」' : '状态行未报并行文案');
    const shotErr = await drawer.screenshot({ path: path.join(OUT_DIR, 'wt-parallel-drawer.png') })
      .then(() => null).catch((e) => String(e).slice(0, 120));
    record('wt/parallel-drawer-shot', shotErr === null, shotErr === null
      ? path.join(OUT_DIR, 'wt-parallel-drawer.png') : `抽屉实拍失败：${shotErr}`);
  }
} finally {
  await browser.close().catch(() => {});
}
record('wt/screenshots-dir', true, OUT_DIR);
summarize();

/** reload 后工单列表视图会回落缺省——补一次导航（首次 gotoBoard 内含首次导航）。 */
async function gotoBoardNavOnly(page) {
  const board = page.locator('[title="工单列表"], [aria-label="工单列表"]').first();
  try { await board.click({ timeout: 4000 }); } catch { await board.evaluate((el) => el.click()).catch(() => {}); }
  await boardCard(page, 'trun').waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(400);
}
