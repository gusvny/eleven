// Integration scenario t260904-05 ② — 右栏 chat 项目色带的归属通道（R7 核心新意，用户需求③）。
//
// Intent (gray-box, user perspective):
//   用户在项目行新建会话后，右栏 chat 顶部出现该项目颜色的色带 + 项目 key 角标
//   （「色+名」双通道，一眼分辨归属）；色带颜色与左栏该项目颜色同源；点工单行不
//   改变归属（chat 不切换，t01 同契约）；刷新后归属不丢（账册持久）；会话不在册
//   （fresh 打开/blank）不渲染色带（声明行为，不造隐形缺省）；色带是对平台滚动体
//   设自有属性，不插入任何包裹节点（零 childList 侵入的用户可感知面）。
//
// High-level steps:
//   T0 卫兵：拒 3099；playwright/隔离台/侧栏夹具缺失=干净 SKIP。
//   T1 初态不在册：fresh 装载（空账册）→ 色带属性不在场。
//   T2 新建会话→色带出现：点第一个项目组 + → tab 出现 →
//      [data-conversation-scroll] 上带 data-wb-chat-projband=<该组项目 key>。
//   T3 色带形态：head 自有 style 在场且含 border-top；滚动体 computed
//      border-top-width==3px；色 == 左栏该项目 --wb-psess-color。
//   T4 属性锚非包裹节点：band 属性所在元素即 [data-conversation-scroll] 本体，
//      且两者数量一一对应（无插入的 wrapper/sibling）。
//   T5 点工单行归属不动：点第一张工单行 → 色带属性值不变（chat 不切换）。
//   T6 刷新恢复：reload → 色带属性仍在且 key 不变。
//   T7 console 零 error / pageerror。
//
// Execution contract: stdout last line `SUMMARY pass=<n> skip=<m> fail=<k>`;
// missing deps → clean SKIP (exit 0); FAIL>0 → exit 1. Isolated console
// SUYOU_TEST_CONSOLE (default 127.0.0.1:3199); hard guard: never 3099.

import {
  BASE, refuseProductionConsole, loadPlaywright, consoleHealthy,
  fetchProjects, makeResults, openTestPage, waitProjectRowOrSkip,
} from './lib_browser.mjs';

refuseProductionConsole();
const { record, summarize } = makeResults();

function hexToRgbString(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex ?? '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

const pw = await loadPlaywright();
if (!pw) { record('browser/deps', 'skip', 'playwright-core unavailable'); summarize(); }
if (!(await consoleHealthy())) {
  record('console/health', 'skip', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);

const consoleErrors = [];
const opened = await openTestPage(pw, { results: { record }, tag: 'browser', consoleErrors });
if (!opened) summarize();
const { browser, page } = opened;

const bandState = () => page.evaluate(() => {
  const scroll = document.querySelector('[data-conversation-scroll]');
  const bandEl = document.querySelector('[data-wb-chat-projband]');
  return {
    scrollCount: document.querySelectorAll('[data-conversation-scroll]').length,
    bandCount: document.querySelectorAll('[data-wb-chat-projband]').length,
    bandKey: bandEl?.getAttribute('data-wb-chat-projband') ?? null,
    sameNode: scroll !== null && bandEl !== null && scroll === bandEl,
    headStyle: document.querySelector('style[data-wb-chat-projband-style]')?.textContent ?? null,
    bandBorderWidth: bandEl ? getComputedStyle(bandEl).borderTopWidth : null,
    bandBorderColor: bandEl ? getComputedStyle(bandEl).borderTopColor : null,
    rowVarColor: getComputedStyle(document.querySelector('[data-wb-psess-row]') ?? document.body)
      .getPropertyValue('--wb-psess-color').trim(),
  };
});

try {
  if (!(await waitProjectRowOrSkip(page, { record }, 'browser'))) { summarize(); }

  // T1 初态（fresh context=空账册 → 不在册不渲染色带）
  await page.waitForTimeout(1500); // 给装饰器首扫一窗
  const t1 = await bandState();
  record('t1/fresh-no-band', t1.bandCount === 0 ? 'pass' : 'fail',
    t1.bandCount === 0 ? '' : `空账册下色带已出现 ${t1.bandCount} 个（应不渲染）`);

  // T2 新建会话 → 色带出现且 key=该组项目
  const projects = await fetchProjects();
  const groupName = await page.evaluate(() =>
    document.querySelector('.wb-group-name')?.textContent?.trim() ?? '');
  const expectKey = projects.find(p => p.name === groupName)?.key ?? null;
  const tabsBefore = await page.evaluate(() => document.querySelectorAll('[data-wb-psess-tab]').length);
  await page.click('[data-wb-psess-new]');
  // 新 tab 出现 = 新会话已登记并切入右栏
  try {
    await page.waitForFunction(
      (n) => document.querySelectorAll('[data-wb-psess-tab]').length > n, tabsBefore,
      { timeout: 20000 },
    );
    record('t2/new-tab-appears', 'pass');
  } catch {
    record('t2/new-tab-appears', 'fail', '点 + 后 20s 内项目行未出现新 tab');
    record('t2/band-appears', 'skip', '前置失败');
  }
  if (expectKey === null) {
    record('t2/band-appears', 'skip', `组头「${groupName}」无法映射到 projects API key（映射面变异）`);
  } else {
    try {
      await page.waitForFunction(
        (k) => document.querySelector('[data-conversation-scroll]')?.getAttribute('data-wb-chat-projband') === k,
        expectKey, { timeout: 15000 },
      );
      record('t2/band-appears', 'pass', `band key=${expectKey}`);
    } catch {
      const st = await bandState();
      record('t2/band-appears', 'fail', `15s 内色带未出现/不匹配：bandKey=${st.bandKey} scrollCount=${st.scrollCount}`);
    }
  }

  // T3 色带形态：3px 项目色横带 + head style + 与左栏同源色
  const t3 = await bandState();
  if (t3.bandCount === 0) {
    record('t3/band-form', 'skip', '色带未在场（T2 失败连带）');
  } else {
    const styleOk = t3.headStyle !== null && t3.headStyle.includes('border-top');
    const widthOk = t3.bandBorderWidth === '3px';
    const bandRgb = hexToRgbString(t3.rowVarColor);
    const colorOk = bandRgb !== null && bandRgb === t3.bandBorderColor;
    record('t3/band-form', styleOk && widthOk ? 'pass' : 'fail',
      `style含border-top=${styleOk} borderTopWidth=${t3.bandBorderWidth}`);
    record('t3/band-color-same-source', colorOk ? 'pass' : 'fail',
      colorOk ? '' : `band=${t3.bandBorderColor} 左栏var=${t3.rowVarColor}`);
  }

  // T4 属性锚非包裹节点（零 childList 侵入的用户可感知面）
  {
    const [st, detail] = t4Judge(t1.scrollCount, t3.scrollCount, t3.sameNode, t3.bandCount);
    record('t4/attr-on-scroll-self', st, detail);
  }

  // T5 点工单行归属不动（chat 不切换 → 色带保持）
  const ticketRow = await page.$('.wb-ticket-row2');
  if (!ticketRow) {
    record('t5/ticket-click-band-stays', 'skip', '无工单行 fixture');
  } else {
    const keyBefore = (await bandState()).bandKey;
    await ticketRow.click();
    await page.waitForTimeout(4000); // t01 同款观察窗：等「错误的会话切换」落地
    const keyAfter = (await bandState()).bandKey;
    record('t5/ticket-click-band-stays', keyBefore !== null && keyBefore === keyAfter ? 'pass' : 'fail',
      `点工单行后 band key ${keyBefore} → ${keyAfter}`);
  }

  // T6 刷新恢复（账册持久 → 归属不丢；映射失败时无期望值可断=skip 不自相矛盾）
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-wb-psess-row]', { timeout: 12000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const t6 = await bandState();
  if (expectKey === null) {
    record('t6/band-restored-reload', 'skip', '组头→key 映射失败（T2 连带），无期望值可断');
  } else {
    record('t6/band-restored-reload', t6.bandKey !== null && t6.bandKey === expectKey ? 'pass' : 'fail',
      `reload 后 bandKey=${t6.bandKey}（期望 ${expectKey}）`);
  }

  // T7 console 卫生
  if (consoleErrors.length === 0) record('t7/console-hygiene', 'pass');
  else record('t7/console-hygiene', 'fail', consoleErrors.slice(0, 3).join(' | ').slice(0, 300));
} finally {
  try { await browser.close(); } catch { /* noop */ }
}
summarize();

function t4Judge(scrollBefore, scrollAfter, sameNode, bandCount) {
  if (scrollAfter === 0) return ['skip', '滚动体不在场（T2 失败连带）'];
  if (!bandCount) return ['skip', '色带不在场（T2 失败连带，无从判 sameNode）'];
  const ok = sameNode === true && scrollBefore === scrollAfter;
  return ok ? ['pass', 'band 属性=滚动体本体，滚动体数量稳定']
    : ['fail', `sameNode=${sameNode} scrollCount ${scrollBefore}→${scrollAfter}（出现包裹节点即侵入）`];
}
