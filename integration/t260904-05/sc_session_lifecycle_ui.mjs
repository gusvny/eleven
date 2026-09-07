// Integration scenario t260904-05 ③ — 项目行会话生命周期 UI 全链（R2/R3/R4/R5+拍板 1/BO-1 的用户路径）。
//
// Intent (gray-box, user perspective):
//   项目行是顶部行退役后的唯一会话入口：点 + 在该项目新建会话并切入右栏；tab 以
//   项目内序号呈现；点 tab 切换且当前 tab 高亮唯一；关闭走确认弹层（取消不动，
//   确认才关）；序号不回收（拍板 1：关掉的号不作 fill，新会话续更大号）；关完全
//   部后再新建，号仍不与历史（含 closed 号域，BO-1）相撞；刷新后整组 tab 持久。
//   本条接管已退役的 session-tab-interactions 的用户路径 intent（对象从顶部行换成
//   项目行），与 t260904-01 journey（纯函数账册状态机）intent 级不同层。
//
// High-level steps:
//   T0 卫兵：拒 3099；playwright/隔离台/侧栏夹具缺失=ENV_FAIL。
//   T1 读现状：第一个项目组当前 tab 序号全集 N（相对断言，容忍历史残留）。
//   T2 新建①：点 + → 出现 num > max(N) 的 tab；active 恰一。
//   T3 新建②：再点 + → 再出现更大 num。
//   T4 关闭取消：点新 tab 关闭钮 → 弹层出现 → 取消 → tab 还在、弹层收起。
//   T5 关闭确认：再点关闭 → 确认 → tab 消失，其余 tab 序号原样保留（不回收）。
//   T6 续号：再新建 → num > 被关那个号（不填洞）。
//   T7 刷新持久：reload → tab 的 id 集合不变（id 取自 tab title 末行）。
//   T8 BO-1 号域：关完全部 → 再新建 → num 大于本 run 见过的全部历史号
//      （closed 账册参与防撞，计数器不回退）。
//   T9 console 零 error / pageerror。
//
// Execution contract (t260904-12 three-state): SUMMARY pass= fail= env_fail= na=;
// missing deps → env_fail (exit 2); FAIL>0 → exit 1; all-na → exit 1. Isolated console
// SUYOU_TEST_CONSOLE (default lib_stage_console 供给（共享台/显式 SUYOU_TEST_CONSOLE）); hard guard: never 3099.

import { STAGE_SEED_ROW_SEL } from '../lib_stage_console.mjs';
import {
  BASE, refuseProductionConsole, loadPlaywright, consoleHealthy,
  makeResults, openTestPage, waitProjectRowOrSkip, dismissFirstRunModals,
} from './lib_browser.mjs';

refuseProductionConsole();
const { record, summarize } = makeResults();

const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable'); summarize(); }
if (!(await consoleHealthy())) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);

const consoleErrors = [];
const opened = await openTestPage(pw, { results: { record }, tag: 'browser', consoleErrors });
if (!opened) summarize();
const { browser, page } = opened;

// 第一个项目行的局部查询（夹具=第一组；全操作限定该行内，多组互不干扰）
const rowSel = '[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])';
const readRow = () => page.evaluate((sel) => {
  const row = document.querySelector(sel);
  const tabs = [...(row?.querySelectorAll('[data-wb-psess-tab]') ?? [])];
  return {
    nums: tabs.map(t => parseInt(t.querySelector('.wb-psess-num')?.textContent ?? '', 10))
      .filter(n => Number.isFinite(n)),
    ids: tabs.map(t => (t.title ?? '').split('\n').pop() ?? ''),
    activeCount: row.querySelectorAll('[data-wb-psess-tab][data-active="true"]').length,
  };
}, rowSel);
const newTabNum = (base) => page.waitForFunction(
  ([sel, floor]) => {
    const row = document.querySelector(sel);
    const nums = [...(row?.querySelectorAll('.wb-psess-num') ?? [])]
      .map(el => parseInt(el.textContent ?? '', 10)).filter(n => Number.isFinite(n));
    return nums.some(n => n > floor);
  }, [rowSel, base], { timeout: 20000 });

async function closeTab(index, confirm) {
  // 新建→会话激活的窗口期会弹「Add an API key」准入模态（无凭据隔离台已知时序），
  // 其 mask 拦合成点击、其「点外收起」会收掉确认弹层——先清场再走确认链。
  try { await dismissFirstRunModals(page); } catch { /* 尽力清场 */ }
  const ok = await page.evaluate(([sel, i]) => {
    const btn = document.querySelectorAll(`${sel} [data-wb-psess-close]`)[i];
    if (!btn) return false;
    btn.click();
    return true;
  }, [rowSel, index]);
  if (!ok) return false;
  await page.waitForSelector('[data-wb-psess-confirm]', { timeout: 5000 });
  // 确认/取消=插件自有 fixed 弹层按钮，DOM 直点等价用户点击且免疫第三方 mask
  // （forceClick 退避语义）；弹层若已被点外收起则本步未做成，返回 false 交上层判定。
  const clicked = await page.evaluate((sel) => {
    const b = document.querySelector(sel);
    if (!b) return false;
    b.click();
    return true;
  }, confirm ? '[data-wb-psess-confirm-ok]' : '[data-wb-psess-confirm-cancel]');
  if (!clicked) return false;
  await page.waitForSelector('[data-wb-psess-confirm]', { state: 'detached', timeout: 5000 }).catch(() => {});
  return true;
}

/**
 * mask 退避点击（t260904-05 验收走查 gen0 补，同 capture.mjs forceClick 语义升档）：
 * 隔离台无凭据环境下，「+ 新建→会话激活」窗口期会再弹「Add an API key」准入模态
 * （capture.mjs L349 同款已知时序），mask 拦截后续一切普通 click——普通点击短超时
 * 失败后先过首屏模态网（点掉准入模态）再重试，仍失败退避 DOM 直点。
 */
async function safeClick(sel) {
  try {
    await page.click(sel, { timeout: 3000 });
    return;
  } catch { /* mask 拦截或时序——走退避 */ }
  try { await dismissFirstRunModals(page); } catch { /* 模态网已尽力 */ }
  const loc = page.locator(sel).first();
  try {
    await loc.click({ timeout: 3000 });
  } catch {
    await loc.evaluate(el => el.click());
  }
}

try {
  if (!(await waitProjectRowOrSkip(page, { record }, 'browser'))) { summarize(); }

  // T1 现状
  const s1 = await readRow();
  const histMax = Math.max(0, ...s1.nums);
  record('t1/baseline', 'pass', `现有 tab nums=[${s1.nums}]`);

  // T2 新建①：续号 + active 唯一
  await safeClick(`${rowSel} [data-wb-psess-new]`);
  try { await newTabNum(histMax); record('t2/new-seq-continues', 'pass', `续号 > ${histMax}`); }
  catch { record('t2/new-seq-continues', 'fail', `20s 内未出现 num>${histMax} 的新 tab`); }
  const s2 = await readRow();
  record('t2/active-unique', s2.activeCount === 1 ? 'pass' : 'fail', `active=${s2.activeCount}（应恰一）`);

  // T3 新建②
  const s3 = await readRow();
  await safeClick(`${rowSel} [data-wb-psess-new]`);
  try { await newTabNum(Math.max(...s3.nums)); record('t3/second-new', 'pass'); }
  catch { record('t3/second-new', 'fail', `20s 内未出现 num>${Math.max(...s3.nums)} 的新 tab`); }

  // T4 关闭取消：tab 不动
  const s4 = await readRow();
  if (!(await closeTab(s4.nums.length - 1, false))) {
    record('t4/close-cancel', 'env_fail', '无关闭钮可点（测试台无 tab 夹具）');
  } else {
    const s4b = await readRow();
    record('t4/close-cancel', s4b.ids.length === s4.ids.length ? 'pass' : 'fail',
      `取消后 tab 数 ${s4.ids.length}（应仍 ${s4.ids.length}）`);
  }

  // T5 关闭确认：tab 消失、余号原样（拍板 1 不回收）
  const s5 = await readRow();
  const closedNum = s5.nums[s5.nums.length - 1];
  const survivors = s5.nums.slice(0, -1);
  if (!(await closeTab(s5.nums.length - 1, true))) {
    record('t5/close-confirm', 'env_fail', '无关闭钮可点（测试台无 tab 夹具）');
  } else {
    await page.waitForFunction(
      ([sel, n]) => document.querySelectorAll(`${sel} [data-wb-psess-tab]`).length === n,
      [rowSel, survivors.length], { timeout: 8000 }).catch(() => {});
    const s5b = await readRow();
    const kept = survivors.every(n => s5b.nums.includes(n));
    record('t5/close-confirm', s5b.nums.length === survivors.length && kept ? 'pass' : 'fail',
      `关闭后 nums=[${s5b.nums}]（期望恰=[${survivors}]，关掉的是 ${closedNum}）`);
  }

  // T6 续号不填洞
  const s6 = await readRow();
  await safeClick(`${rowSel} [data-wb-psess-new]`);
  try { await newTabNum(closedNum); record('t6/no-hole-refill', 'pass', `新号 > 被关号 ${closedNum}`); }
  catch { record('t6/no-hole-refill', 'fail', `20s 内未出现 num>${closedNum} 的新 tab（疑似填洞/回退）`); }

  // T7 刷新持久（tab id 集合不变）
  const s7 = await readRow();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector(rowSel, { timeout: 12000 }).catch(() => {});
  await page.waitForTimeout(800);
  const s7b = await readRow();
  const sameIds = s7.ids.length === s7b.ids.length && [...s7.ids].sort().join() === [...s7b.ids].sort().join();
  record('t7/reload-persist', sameIds && s7.ids.length > 0 ? 'pass' : 'fail',
    `reload 前 ids=[${s7.ids}] 后=[${s7b.ids}]`);

  // T8 BO-1 号域（t260904-05 验收走查 gen0 断言重构）：全关 + **计数器丢失** →
  // 新建仍不重发已关号（closed 账册参与续号兜底——BO-1 的精确形态；原「要求新号
  // >硬编码 30」与 run 内仅 2-3 个号的前置数据不匹配，属断言照搬拍板例子未随
  // 前置缩放）。清光 tab 后删计数器键（localStorage=用户手可改外部输入，场景④
  // 同款口径），reload 后新建：号只能从 closed/账册现存域兜底 → 必须大于本 run
  // 见过的最大号（已关的号不重发，拍板 1 稳定身份）。纯函数同语义在 smoke B3。
  const s8 = await readRow();
  let runMax = Math.max(histMax, ...s8.nums);
  let guard = 0;
  while (s8.nums.length > 0 && guard++ < 30) {
    if (!(await closeTab(s8.nums.length - 1, true))) break;
    await page.waitForTimeout(300);
    const cur = await readRow();
    runMax = Math.max(runMax, ...cur.nums);
    if (cur.nums.length >= s8.nums.length) break; // 关不动防死旋
    s8.nums = cur.nums;
  }
  const cleared = (await readRow()).nums.length === 0;
  if (!cleared) {
    record('t8/bo1-closed-domain', 'env_fail', '未能清空该项目 tab（关闭链异常，见 T5）');
  } else {
    await page.evaluate(k => localStorage.removeItem(k), 'sandbar-workbench-project-seq-v1');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector(rowSel, { timeout: 12000 }).catch(() => {});
    await page.waitForTimeout(800);
    const before8 = (await readRow()).nums.length;
    await safeClick(`${rowSel} [data-wb-psess-new]`);
    try {
      await page.waitForFunction(
        ([sel, n]) => {
          const row = document.querySelector(sel);
          const nums = [...(row?.querySelectorAll('.wb-psess-num') ?? [])]
            .map(el => parseInt(el.textContent ?? '', 10)).filter(Number.isFinite);
          return nums.some(v => v > n);
        }, [rowSel, runMax], { timeout: 20000 });
      const nums8 = (await readRow()).nums.filter(n => n > runMax);
      record('t8/bo1-closed-domain', nums8.length >= 1 && before8 === 0 ? 'pass' : 'fail',
        `计数器丢失全关后新建 num=[${nums8}] > run 最大 ${runMax}（closed 号域不重发）`);
    } catch {
      record('t8/bo1-closed-domain', 'fail', `计数器丢失全关后新建未续出 >${runMax} 的号（疑似重发 closed 号）`);
    }
  }

  // T9 console 卫生
  if (consoleErrors.length === 0) record('t9/console-hygiene', 'pass');
  else record('t9/console-hygiene', 'fail', consoleErrors.slice(0, 3).join(' | ').slice(0, 300));
} finally {
  try { await browser.close(); } catch { /* noop */ }
}
summarize();
