import { ensureStageConsole } from '../lib_stage_console.mjs';
// playwright-core 依赖解析唯一真源（t260912-01 缺陷③：位置无关四路口径，
// 旧「../.. 位置算术 + unavailable 文案」退役）。
import { loadPlaywright, pwMissingDetail } from '../lib_pw_deps.mjs';
// Integration scenario t260903-07 ① — clicking a ticket must NOT switch the right chat.
//
// Intent (black-box, user perspective):
//   用户点工单行：中列照常开工单详情抽屉（既有行为不陪葬），右侧 chat 上下文
//   原地不动——不进入 ticket-<id> 会话、不注入【工单上下文】快照、data-phase 不变、
//   会话顶入口不出现 ticket- 行。这是对旧契约「点工单→切会话」的显式反转；
//   全局场景 ticket-session-restore 的 browser 半已随本票同步反转为同一契约。
//
// High-level steps:
//   T1 卫兵：拒 3099；测试台健康检查；playwright-core 缺失/台不可达=ENV_FAIL；
//      侧栏无工单行=ENV_FAIL（环境无 fixture）——t260904-12 三态，绝不 exit 0。
//   T2 基线快照：data-phase、【工单上下文】消息计数、顶入口 ticket- 行。
//   T3 点行 1：中列详情开（.wb-d2-steps 在场，t260901-13 同款抽屉锚）；4s 观察窗后
//      快照计数不变、phase 不变、顶入口无 ticket- 行。
//   T4 点行 2 → 点回行 1：同样零注入（反复点击零 churn）。
//   T5 console 零 error / pageerror。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; missing deps → env_fail
// (exit 2); FAIL>0 或全腿 na → exit 1. Isolated console
// SANDBAR_TEST_CONSOLE (default: lib_stage_console 共享台); hard guard: never 3099.

const BASE = (await ensureStageConsole()).base;
const results = [];
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na']);;
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);;
  results.push({ name, status, detail });;
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);;
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length;;
  const e = results.filter(r => r.status === 'env_fail').length;;
  const n = results.filter(r => r.status === 'na').length;;
  const f = results.filter(r => r.status === 'fail').length;;
  const allNa = results.length > 0 && n === results.length;;
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);;
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);;
}

if (BASE.includes(':3099')) {
  console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)');
  process.exit(1);
}

async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

async function browserScenarios() {
  // t260912-01：四路探测单源（lib_pw_deps），布局无关；失败文案只报事实不归因环境。
  const pw = await loadPlaywright();
  if (!pw) { record('browser/deps', 'env_fail', pwMissingDetail()); return; }
  let browser, context, page;
  try {
    browser = await pw.chromium.launch({ channel: 'chrome', headless: true }).catch(() => pw.chromium.launch({ headless: true }));
    context = await browser.newContext();   // fresh profile: no ledger, chat at hero
    page = await context.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // 出厂 notice（Continue 遮罩）会拦截行卡点击——先关再断言（lib_browser 同款）。
    try {
      const nb = page.locator('button', { hasText: /continue|继续/i }).first();
      await nb.click({ timeout: 4000 });
      await nb.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    } catch { /* 无 notice=常态 */ }
  } catch (err) {
    record('browser/deps', 'env_fail', `console/browser unreachable: ${String(err).slice(0, 120)}`);
    try { await browser?.close(); } catch { /* noop */ }
    return;
  }
  const consoleErrors = [];
  const badResponses = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push(String(e)));
  // URL 感知卫生面（260910 gen1 仲裁）：console error 文本只有状态码没有 URL，
  // 另收响应面才能按端点点名豁免（一次性夹具幽灵行的 agent-usage 400，见 t5 注）。
  page.on('response', r => { if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`); });

  try {
    await page.waitForSelector('.wb-card[data-ticket-id]', { timeout: 12000 });
  } catch {
    record('browser/fixture-ticket-row', 'env_fail', 'no ticket row rendered in test console sidebar');
    try { await browser.close(); } catch { /* noop */ }
    return;
  }

  const readState = () => page.evaluate(() => ({
    phase: document.querySelector('[data-phase]')?.getAttribute('data-phase') ?? '',
    snapshots: document.body.innerText.split('【工单上下文】').length - 1,
    // 票② R8 改锚（t260904-05）：顶部行已退役，判据平移到项目行 tab 全集
    ticketInTopEntry: Array.from(document.querySelectorAll('[data-wb-psess-tab]')).some(el => (el.textContent ?? '').includes('ticket-')),
  }));

  // T2 baseline
  const before = await readState();
  record('t2/baseline', 'pass', `phase=${before.phase || '(none)'} snapshots=${before.snapshots}`);

  const clickRowAndAssertNoSwitch = async (idx, label) => {
    await page.evaluate((i) => { const el = document.querySelectorAll('.wb-card[data-ticket-id]')[i]; el && el.click(); }, idx);
    // 中列详情照常开（既有行为回归面；抽屉锚与 t260901-13 同款）。
    let drawerOpened = true;
    try {
      await page.waitForSelector('.wb-d2-steps', { timeout: 8000 });
    } catch { drawerOpened = false; }
    if (!drawerOpened) {
      record(`${label}/detail-opens`, 'fail', '点工单后中列详情抽屉未出现（.wb-d2-steps 缺席）');
      return;
    }
    record(`${label}/detail-opens`, 'pass');
    // 观察窗：旧实现 refresh→waitForListed→open→注入需数秒，给足 4s 让「错误的会话切换」落地。
    await page.waitForTimeout(4000);
    const after = await readState();
    const checks = [
      ['snapshot-unchanged', after.snapshots === before.snapshots, `snapshots ${before.snapshots}→${after.snapshots}`],
      ['phase-unchanged', after.phase === before.phase, `phase ${before.phase || '(none)'}→${after.phase || '(none)'}`],
      ['no-ticket-entry', !after.ticketInTopEntry, 'project session tabs contain ticket- row'],
    ];
    for (const [nm, good, bad] of checks) {
      record(`${label}/${nm}`, good ? 'pass' : 'fail', good ? '' : bad);
    }
  };

  // T3 single click
  await clickRowAndAssertNoSwitch(0, 't3-single-click');

  // T4 repeat clicks across rows
  const rowCount = await page.evaluate(() => document.querySelectorAll('.wb-card[data-ticket-id]').length);
  if (rowCount >= 2) {
    await clickRowAndAssertNoSwitch(1, 't4-second-row');
    await clickRowAndAssertNoSwitch(0, 't4-back-first');
  } else {
    record('t4-repeat-clicks', 'env_fail', 'need >=2 ticket rows');
  }

  // T5 console hygiene
  // console-hygiene（260910 gen1 仲裁实锤升级为 URL 感知）：一次性夹具的幽灵行
  // （早轮场景 terminate 掉的票，worktree 指向已删 tmp 目录）会让 agent-usage 端点
  // 被路径守卫按设计拒读（400「工单 worktree 越界（拒绝读取）」——护栏行为本身正确，
  // 生产面行 worktree 在项目根内不会触发）。只豁免这一点名端点的 400；其余任何
  // >=400 响应或 pageerror 照旧红。
  const GHOST = /\/api\/wf\/tickets\/[^/?]+\/agent-usage\?/;
  const stray = badResponses.filter((u) => !GHOST.test(u));
  const other = consoleErrors.filter((t) => !/Failed to load resource/.test(t));
  if (stray.length === 0 && other.length === 0) record('t5/console-hygiene', 'pass');
  else record('t5/console-hygiene', 'fail', [...stray, ...other].slice(0, 3).join(' | ').slice(0, 300));

  try { await browser.close(); } catch { /* noop */ }
}

const healthy = await consoleHealthy();
if (!healthy) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);
await browserScenarios();
summarize();
