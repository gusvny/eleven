// Integration scenario t260904-05 ④ — 账册外部输入三态的真实 boot 对抗（畸形/缺失/旧版）。
//
// Intent (gray-box, user perspective):
//   localStorage 账册是用户手可改的外部输入（持久化 JSON）。用户拿旧版数据升级、
//   手改坏数据、甚至写坏 JSON 后打开控制台：页面必须照常 boot、项目行照常渲染、
//   什么数据进什么 tab 严格守门（工单会话/ticket- 条目永不进 tab；project 字段坏
//   的条目不得落进任何项目组）；色带对畸形归属不渲染。 journey J4（t260904-01）
//   已在纯函数层对抗过同族输入——本条在真实 boot 路径（store 惰性读写+backfill
//   effect+装饰器接线全链在场）复验同一纪律，intent=「boot 韧性」而非「函数容错」。
//
// High-level steps:
//   T0 卫兵：拒 3099；playwright/隔离台缺失=ENV_FAIL（exit 2）。
//   Case A 旧顶部行时代账册升级：seed 无 seq 的合法条目（真实 fixture 项目 key）
//      + 一条 ticket- 前缀条目 → boot 后合法条目以补号 tab 呈现（num≥1）、
//      ticket- 条目不进任何 tab、无 pageerror。
//   Case B 畸形 project 字段：seed project=42（非字符串）条目 → 不进任何项目组
//      tab、无 pageerror、+ 钮仍可用（页面活着）。
//   Case C 坏 JSON：LEDGER/SEQ 计数器两键全写垃圾字节 → boot 干净、项目行空态
//      不崩（坏数据按丢失处理）、无 pageerror。
//   各 Case 独立 fresh context；console error 零容忍。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; missing deps → env_fail
// (exit 2); FAIL>0 或全腿 na → exit 1. Isolated console
// SUYOU_TEST_CONSOLE (default: lib_stage_console 共享台); hard guard: never 3099.

import { STAGE_SEED_ROW_SEL } from '../lib_stage_console.mjs';
import {
  BASE, refuseProductionConsole, loadPlaywright, consoleHealthy,
  fetchProjects, makeResults,
} from './lib_browser.mjs';

refuseProductionConsole();
const { record, summarize } = makeResults();

// 账册/计数器存储键（迁移测试的必然绑定：测的就是这几个键里的数据格式；
// 键名换版时本场景红=迁移测试该跟着换版的正确红）
const LEDGER_KEY = 'suyou-workbench-opened-sessions-v1';
const SEQ_COUNTER_KEY = 'suyou-workbench-project-seq-v1';

const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable'); summarize(); }
if (!(await consoleHealthy())) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);

const projects = await fetchProjects();
const fixtureKey = projects[0]?.key ?? null;
if (!fixtureKey) {
  record('fixture/projects', 'env_fail', '隔离台无项目 fixture（projects API 空不胜任 boot 注入）');
  summarize();
}

async function bootCase(seed) {
  const consoleErrors = [];
  let browser;
  // 系统 Chrome 回退（同 lib_browser.openTestPage：playwright-core 无自带二进制时用本机 Chrome）
  const launch = async () => {
    try { return await pw.chromium.launch({ channel: 'chrome', headless: true }); }
    catch { return await pw.chromium.launch({ headless: true }); }
  };
  try {
    browser = await launch();
    const context = await browser.newContext();
    await context.addInitScript((s) => {
      for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v);
    }, seed);
    const page = await context.newPage();
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => consoleErrors.push(String(e)));
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1200); // backfill/装饰器首扫窗
    const state = await page.evaluate(() => ({
      tabIds: [...document.querySelectorAll('[data-wb-psess-tab]')]
        .map(t => (t.title ?? '').split('\n').pop() ?? ''),
      tabNums: [...document.querySelectorAll('.wb-psess-num')]
        .map(el => parseInt(el.textContent ?? '', 10)).filter(n => Number.isFinite(n)),
      plusPresent: !!document.querySelector('[data-wb-psess-new]'),
      bandCount: document.querySelectorAll('[data-wb-chat-projband]').length,
      newSessionVisible: [...document.querySelectorAll('[aria-label]')]
        .some(el => ['新建会话', 'New session'].includes(el.getAttribute('aria-label')) && el.offsetParent !== null),
    }));
    await browser.close();
    return { state, consoleErrors, bootFailed: false };
  } catch (e) {
    try { await browser?.close(); } catch { /* noop */ }
    return { state: null, consoleErrors, bootFailed: true, err: String(e).slice(0, 160) };
  }
}

try {
  // Case A 旧账册升级（无 seq + title 字段 + ticket- 条目守门）
  {
    const legacy = [
      { id: 'chat-legacy-a1', title: '旧顶部行时代甲', project: fixtureKey, cwd: '/tmp/a', lastOpenedAt: 3 },
      { id: 'chat-legacy-a2', project: fixtureKey, cwd: '/tmp/a', lastOpenedAt: 2 },
      { id: 'ticket-t260904-05', project: fixtureKey, lastOpenedAt: 1 },
    ];
    const r = await bootCase({ [LEDGER_KEY]: JSON.stringify(legacy) });
    if (r.bootFailed) { record('a/boot', 'fail', r.err); }
    else {
      const inTabs = r.state.tabIds.filter(id => id.startsWith('chat-legacy'));
      const ticketLeak = r.state.tabIds.some(id => id.startsWith('ticket-'));
      const seqsOk = r.state.tabNums.length > 0 && r.state.tabNums.every(n => n >= 1);
      record('a/legacy-upgrade', inTabs.length === 2 && seqsOk ? 'pass' : 'fail',
        `合法条目进 tab=${inTabs.length}/2 nums=[${r.state.tabNums}]`);
      record('a/ticket-not-in-tabs', !ticketLeak ? 'pass' : 'fail',
        ticketLeak ? 'ticket- 条目泄漏进项目 tab' : '');
      record('a/boot-clean', r.consoleErrors.length === 0 ? 'pass' : 'fail',
        r.consoleErrors.slice(0, 2).join(' | ').slice(0, 200));
    }
  }

  // Case B 畸形 project 字段（非字符串 → 不落任何项目组）
  {
    const r = await bootCase({
      [LEDGER_KEY]: JSON.stringify([
        { id: 'chat-bad-proj', project: 42, lastOpenedAt: 5 },
        { id: 'chat-empty-proj', project: '', lastOpenedAt: 4 },
      ]),
    });
    if (r.bootFailed) { record('b/boot', 'fail', r.err); }
    else {
      const leak = r.state.tabIds.some(id => id.startsWith('chat-bad') || id.startsWith('chat-empty'));
      const clean = r.consoleErrors.length === 0 && r.state.plusPresent && !leak;
      record('b/malformed-project', clean ? 'pass' : 'fail',
        clean ? '' : `泄漏=${leak} +钮在场=${r.state.plusPresent} errors=${r.consoleErrors.length}`);
      record('b/band-absent', r.state.bandCount === 0 ? 'pass' : 'fail',
        `畸形归属下色带出现 ${r.state.bandCount} 个（应不渲染）`);
    }
  }

  // Case C 坏 JSON（账册+计数器双键垃圾字节 → 按丢失处理不崩）
  {
    const r = await bootCase({
      [LEDGER_KEY]: 'not-json{{{',
      [SEQ_COUNTER_KEY]: '}}{{{garbage',
    });
    if (r.bootFailed) { record('c/boot', 'fail', r.err); }
    else {
      const clean = r.consoleErrors.length === 0 && r.state.plusPresent && r.state.tabIds.length === 0;
      record('c/bad-json', clean ? 'pass' : 'fail',
        clean ? '' : `tab=${r.state.tabIds.length} +钮=${r.state.plusPresent} errors=${r.consoleErrors.slice(0, 2).join('|').slice(0, 160)}`);
    }
  }
} finally {
  // 各 case 已自关 browser；此处无共享资源
}
summarize();
