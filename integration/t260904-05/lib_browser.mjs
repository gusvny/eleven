import { STAGE_SEED_ROW_SEL } from '../lib_stage_console.mjs';
import { ensureStageConsole } from '../lib_stage_console.mjs';
// lib_browser.mjs —— t260904-05 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 复用面（integration 岗位纪律：前置/基础步骤代码允许共享，步骤级重复不算重复用例）：
//   - 隔离台基址与 3099 红线拒绝；
//   - playwright-core 三路探测加载（同 t260903-07/sc_t01 口径，缺失=ENV_FAIL）；
//   - 浏览器 fresh context 打开（无账册残留，等价新用户）；
//   - results/record/summarize 执行契约（SUMMARY pass/fail/env_fail/na；退出码 0/1/2）。
// 安全红线：本目录场景只碰隔离台（默认 lib_stage_console 供给（共享台/显式 SUYOU_TEST_CONSOLE）），绝不连生产 3099。

export const BASE = (await ensureStageConsole()).base;

/** 生产控制台红线：命中 3099 直接拒跑（宁可自家测试不跑）。 */
export function refuseProductionConsole() {
  if (BASE.includes(':3099')) {
    console.error('refusing to run: SUYOU_TEST_CONSOLE points at the production console (3099)');
    process.exit(1);
  }
}

/** playwright-core 三路探测（env 指定 → 裸包 → ui-check 本地依赖）。缺失返回 null=调用方记 ENV_FAIL。
 *  第③路 t260904-05 验收走查 gen0 修正：原按 process.cwd() 相对拼路径，泳道开在
 *  主仓 .lane/ 子目录时 ../../ 会指到主仓树（其 ui-check 无 node_modules）——改为
 *  基于本模块 import.meta.url 解析，与泳道布局解耦。 */
export async function loadPlaywright() {
  const localPw = new URL('../../server/dsh/ui-check/node_modules/playwright-core/index.mjs', import.meta.url).href;
  for (const c of [process.env.SUYOU_PLAYWRIGHT_PATH, 'playwright-core', localPw]) {
    if (!c) continue;
    try { return await import(c); } catch { /* next */ }
  }
  return null;
}

/** 隔离台健康检查（workbench API 可达）。 */
export async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/suyou-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

/** 项目清单（name→key 映射；健康检查同源接口）。失败返回 []。
 *  响应三态兼容（t260904-05 验收走查 gen0 修正）：workbench API 实测返回
 *  {ok:true,result:{projects:[...]}} 包装；夹具原只解裸数组/{projects} 两态，
 *  map 落空 →「组头无法映射到 key」假绿/FALL 链。 */
export async function fetchProjects() {
  try {
    const r = await fetch(`${BASE}/suyou-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    if (!r.ok) return [];
    const data = await r.json();
    const list = Array.isArray(data) ? data
      : (data?.result?.projects ?? data?.projects ?? []);
    return list.map(p => ({ key: p.key ?? p.id ?? '', name: p.name ?? p.key ?? '' }));
  } catch { return []; }
}

/** 执行契约（integration/README.md「执行契约」，t260904-12 三态化）：状态词表只认
 *  pass / fail / env_fail / na——环境缺失一律 env_fail（绝不 exit 0 假绿）；na 仅给
 *  以系统状态为条件的腿。退出码：fail>0 或全腿 na → 1（产品红优先，C7/C9）；
 *  env_fail>0 → 2；全过 → 0。SUMMARY 末行 pass= fail= env_fail= na=（skip= 退役）。 */
export function makeResults() {
  const results = [];
  const OK = new Set(['pass', 'fail', 'env_fail', 'na']);
  return {
    record(name, status, detail = '') {
      if (!OK.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
      results.push({ name, status, detail });
      console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
    },
    summarize() {
      const p = results.filter(r => r.status === 'pass').length;
      const e = results.filter(r => r.status === 'env_fail').length;
      const n = results.filter(r => r.status === 'na').length;
      const f = results.filter(r => r.status === 'fail').length;
      const allNa = results.length > 0 && n === results.length;
      console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
      process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
    },
  };
}

/** 出厂遮罩退避直点（同 ui-check/capture.mjs forceClick 先例：mask 拦 pointer 时
 *  普通点击超时后退避为 DOM 直点；只读导航语义，不提交表单）。 */
async function forceClick(locator, timeoutMs = 5000) {
  try { await locator.click({ timeout: timeoutMs }); }
  catch { await locator.evaluate(el => el.click()); }
}

/**
 * 首屏模态网（同 capture.mjs dismissNotice/dismissAdmissionModal 先例，t260904-05
 * 验收走查 gen0 补）：全新 DSH_HOME 隔离台首次打开会弹「Internal Testing Notice」
 * （Continue）与无凭据时的「Add an API key」准入模态（Configure later），mask 拦截
 * 一切后续指针交互——点掉后轮询等 [role=dialog] 消失。只读导航语义。
 * 返回人话锚点（null=无模态）；模态让路失败=throw（污染后续全部断言，loud 失败）。
 */
export async function dismissFirstRunModals(page) {
  const anchors = [];
  // ① Internal Testing Notice（Continue/继续）
  try {
    const btn = page.locator('button', { hasText: /continue|继续/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 4000 });
    await forceClick(btn);
    await btn.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    anchors.push('出厂 notice 已关闭（Continue）');
  } catch { /* 未出现，继续 */ }
  // ② Add an API key 准入模态（Configure later → 首个可用钮 → Escape 逐级退避）
  if (await page.locator('[role="dialog"]').count()) {
    const later = page.locator('button:has-text("Configure later")').first();
    try {
      if (await later.isVisible()) await later.click({ timeout: 2000 });
      else throw new Error('no Configure later');
    } catch {
      const dialog = page.locator('[role="dialog"]').first();
      try {
        const btn = dialog.locator('button:enabled').first();
        if (await btn.count()) await btn.click({ timeout: 2000 }).catch(() => {});
        else await page.keyboard.press('Escape').catch(() => {});
      } catch { /* 轮询兜底 */ }
    }
    const deadline = Date.now() + 8000;
    let gone = false;
    while (Date.now() < deadline) {
      if (!(await page.locator('[role="dialog"]').count())) { gone = true; break; }
      await page.waitForTimeout(400);
    }
    if (!gone) throw new Error('准入模态让路后仍残留（[role=dialog] 8s 未消失）——后续断言将被遮挡');
    anchors.push('准入模态已关闭');
  }
  return anchors.length ? anchors.join('；') : null;
}

/**
 * 打开隔离台页面（fresh context=无账册残留；返回 null=环境不可用已记 ENV_FAIL）。
 * consoleErrors 数组由调用方传入收集 console error/pageerror（卫生断言用）。
 * 打开后先过首屏模态网（准入模态 mask 会拦截一切点击——场景②实测）。
 */
export async function openTestPage(pw, { results, tag, consoleErrors, initScript } = {}) {
  let browser;
  // playwright-core 不自带浏览器二进制（泳道无 ms-playwright 缓存）：优先系统
  // Chrome（channel:"chrome"，同 ui-check/capture.mjs launchBrowser 先例），
  // 探测不到再退自带 chromium（有缓存的环境照旧）。
  const launch = async () => {
    try { return await pw.chromium.launch({ channel: 'chrome', headless: true }); }
    catch { return await pw.chromium.launch({ headless: true }); }
  };
  try {
    browser = await launch();
    const context = await browser.newContext();
    if (initScript) await context.addInitScript(initScript);
    const page = await context.newPage();
    page.on('console', m => { if (m.type() === 'error') consoleErrors?.push(m.text()); });
    page.on('pageerror', e => consoleErrors?.push(String(e)));
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    try { await dismissFirstRunModals(page); } catch (e) {
      results.record(`${tag}/first-run-modals`, 'env_fail', `首屏模态网未过：${String(e).slice(0, 120)}`);
      try { await browser.close(); } catch { /* noop */ }
      return null;
    }
    return { browser, context, page };
  } catch (err) {
    results.record(`${tag}/browser`, 'env_fail', `console/browser unreachable: ${String(err).slice(0, 120)}`);
    try { await browser?.close(); } catch { /* noop */ }
    return null;
  }
}

/** 侧栏项目会话区在场的夹具前提；不在场=ENV_FAIL（环境无 fixture，同 t01 卫兵口径）。 */
export async function waitProjectRowOrSkip(page, results, tag) {
  try {
    await page.waitForSelector('[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])', { timeout: 12000 });
    return true;
  } catch {
    results.record(`${tag}/fixture-psess-row`, 'env_fail', 'no project session row rendered in test console sidebar');
    return false;
  }
}
