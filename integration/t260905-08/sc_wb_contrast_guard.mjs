// sc_wb_contrast_guard.mjs — t260905-08 场景①：工单台全台面对比度看守（隔离台浏览器走查）。
//
// intent（灰盒，用户可感知行为；宿主令 260906 22:1X 裁定②④⑤＋KI-052 回归用例）：
//   「在场断言≠可读」（17 号场景族全绿但深色主题下人眼不可用，宿主实报）——本场景对
//   工单台全部可达文字表面实算 WCAG 对比度（computed color vs 沿祖先链合成到不透明的
//   有效底色），在平台浅档令牌/深档令牌/零注入（fallback-only）三档下都必须达标：
//   正文级 4.5:1（WCAG AA）；收口（done）行卡文字按「至少可分辨」3.0:1 卡（终态
//   降权设计意图，红线不动信息架构，豁免理由在此；口径已随 96c699c 热修正——板面
//   done 卡降权由整行 opacity:.72 改 muted 静音色（深底可读），侧栏 done 卡仍
//   opacity:.72，两处同按 3.0 卡）。epic 色板
//   10 档全播入（fnv1a 槽位确定性挑码，防「只测种子色」采样盲区）。变异子用例故意注入
//   低对比正文色断言看守必咬（变异测试守测试本身；改造前经侧栏 alias 消费面咬合）。
//   病灶本质声明：改造前主区写死浅色自洽、注入无效，三子用例全绿=KI-052 同构（场景绿
//   真台红）；本场景的守护价值在实现落地后（令牌消费面）与宿主真值确认后兑现。
//
// high-level steps：
//   T0 自举隔离台（FIX17 桩：10 档 epic 挑码×四态轮换＋无 epic 票）＋ playwright 探测
//      （缺失=env_fail 有声红，三态契约「闸内无 SKIP」，KI-036/KI-046 口径）。
//   T1 子用例遍历 light/dark/fallback-only/legacy（t260907-03 增旧平台子用例：knockout
//   bg-primary 模拟 0.1.1-rc.2 无此名，bg-base=可辨识代表值，断言 --dsw-derive-canvas
//   精确等值——兜底链接住旧平台令牌名的契约看守）：每子用例 goto→:root 注入令牌
//   （addStyleTag）→
//   开板后忠实注入（壳层在 BODY 级祖先声明 label 覆盖值=真实换档作用域，:root 翻不动；
//   探针实锤「底翻了字没翻」裂脑态——忠实注入=自 .wb-card 向上找最高 label≠:root 值
//   祖先，inline+important 打整套令牌，保证被测态=令牌组真实生效态）
//      →导航工单列表→全文档可见文字扫描（板面/行卡/侧栏）→点「看原因」开详情
//      （受阻横幅面）→扫描→关详情→开 metrics 面板（事件总线，不可达=na 条件子用例）→
//      扫描。每子用例「违例=0 且未知色形=0」才过；违例/未知色形打印 区域/元素/色值/比值
//      （数值化取证）。色解析收 rgb()/rgba() 与 color(srgb …)——后者是 color-mix 派生色
//      的 computed 序列化形态（gen0 验收探针实锤：旧解析只认 rgb 曾静默漏检 73% 表面，
//      epic chip 就在漏检面里）；其余未知 computed 色形态=fail-closed 点名该子用例红，
//      绝不静默计入达标（防「绿≠全台面真查」KI-052 同构在看守自身复发）。
//   T2 变异子用例：浅档＋label-primary:#7a7a85（on #fff≈3.4:1）→断言违例>0（看守咬合）。
//   T3 红线：端口≠3099/7233；finally 回收进程树/浏览器/临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na；playwright-core/隔离台依赖
//   缺失=env_fail（exit 2）有声红（KI-046 第三层：「闸内无 SKIP」，旧式穿闸=错误交付通道）；
//   arbitrate/merge 期必须绿。3099 红线：全程不触碰真控制台。
import {
  makeRegistryRoot, writeProjectEntry, tmpRoot, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
  pickEpicCodes, TOKEN_SETS, cssVarsBlock,
} from './lib_t260905_08.mjs';

const { record, summarize } = makeResults();

const NOW = Math.floor(Date.now() / 1000);
const wf = { id: 'wf-t08', name: '看守模板', stages: [
  { id: 'p1', name: '起草' }, { id: 'p2', name: '实现' }, { id: 'p3', name: '验收' },
] };
const STATES = [
  { status: 'running', stage_state: 'awaiting-human' }, // waiting
  { status: 'running', stage_state: 'blocked' },        // blocked
  { status: 'running', stage_state: 'running' },        // active
  { status: 'closed', stage_state: 'awaiting' },        // done
];
const slots = pickEpicCodes();
const row = (over) => ({
  id: over.id, project: 't08a', title: over.title, role: 'developer',
  status: over.status, stage: over.stage ?? 'p2', stage_state: over.stage_state,
  workflow: 'wf-t08', epic: over.epic ?? '', handoff_count: 1, pending_count: 0,
  worktree: `/tmp/t08/${over.id}`, updated: '2026-09-06 12:00:00',
  updated_ts: NOW - 300, created: NOW - 3600,
  blocked_reason: over.reason,
});
// 10 档 epic × 四态轮换（同档同态稳定复现）＋1 张无 epic 票（chip 缺省分支）
const tickets = slots.map((code, i) => {
  const st = STATES[i % 4];
  return row({
    id: `t08-${i}`, title: `看守票 ${i}（epic 槽 ${fnvSlotOf(code)}）`,
    ...st, stage: st.status === 'closed' ? 'p3' : 'p2',
    epic: code, reason: st.stage_state === 'blocked' ? '环境红：看守注入不可达' : undefined,
  });
});
tickets.push(row({ id: 't08-noepic', title: '看守票无epic', status: 'running', stage_state: 'running' }));
function fnvSlotOf(code) { return slots.indexOf(code); }

const stub = makeTicketStub();
stub.setCtrl({
  workflows: [wf], tickets,
  show: Object.fromEntries(tickets.map((t) => [t.id, {
    mode: 'ok', timeline: [{ at: NOW - 60, stage: t.stage ?? 'p1', state: t.stage_state }], pending: [],
  }])),
});

const pw = await loadPlaywright();
if (!pw) {
  record('playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：浏览器走查子用例环境红（三态契约「闸内无 SKIP」）');
  summarize();
}

let bench;
try {
  const projectsRoot = makeRegistryRoot('t08-guard-reg-');
  writeProjectEntry(projectsRoot, 't08a', '看守夹具', [tmpRoot('t08-guard-proj-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', true, bench.base);
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

// 页面内扫描：工单台子树（.wb-root 内）可见文字元素，computed color vs 沿祖先链合成到
// 不透明的有效底色，
// WCAG 相对亮度比值；收口卡阈值 3.0（豁免理由见头注），其余 4.5。失败返回违例明细。
const SCAN_FN = () => {
  const parseC = (s) => {
    const aOf = (raw) => raw === undefined ? 1 : (String(raw).endsWith('%') ? parseFloat(raw) / 100 : parseFloat(raw));
    // 旧式 rgb()/rgba()（逗号/空格分隔，alpha 小数或百分比）
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,\/\s]+([\d.]+%?))?\s*\)/.exec(s);
    if (m) return [+m[1], +m[2], +m[3], aOf(m[4])];
    // color(srgb r g b [/ a])——color-mix() 派生色的 computed 序列化形态（gen0 验收探针
    // 实锤：本票新令牌系的派生文字——epic chip/muted/meta——全部落此形态，旧解析器只认
    // rgb 曾静默漏检 73% 表面）。srgb 通道 0..1 折算 0..255 并钳位。
    const c = /color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+%?))?\s*\)/.exec(s);
    if (c) return [0, 1, 2].map((i) => Math.min(255, Math.max(0, +c[i + 1] * 255))).concat([aOf(c[4])]);
    return null; // 未知形态→unchecked（fail-closed 点名，不静默漏检）
  };
  const lum = (r, g, b) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (c1, c2) => { const a = lum(c1[0], c1[1], c1[2]), b = lum(c2[0], c2[1], c2[2]); return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); };
  const blend = (top, bottom) => {
    const a = top[3] + bottom[3] * (1 - top[3]);
    if (a === 0) return [0, 0, 0, 0];
    return [0, 1, 2].map((i) => (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / a).concat([a]);
  };
  const describe = (el) => (el.tagName + '.' + String(el.className).split(/\s+/).slice(0, 2).join('.') + '「' + (el.textContent || '').trim().slice(0, 12) + '」').slice(0, 60);
  const out = { violations: [], regions: {}, total: 0, transparent: 0, unchecked: [] };
  // 被测域=工单台面：板面根（.wb-root）∪侧栏子树（.wb-sb，metrics 面挂侧栏内、
  // 实测随侧栏挂平台壳 regionArea——探针 probe_t08_metrics_dom 实锤不在 .wb-root 内）。
  // 平台壳自有面（欢迎横幅/座位钮等，两域之外）不入扫：壳面配对由壳自身换档保证
  // （KI-052 边界声明，.wb-sb-foot ⚙ 槽同款先例）。
  for (const el of document.querySelectorAll('body *')) {
    if (!el.closest('.wb-root') && !el.closest('.wb-sb')) continue;
    let has = false;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { has = true; break; }
    if (!has) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    // shell footer 槽豁免（KI-052 边界声明，gen1 验收探针修正机制表述）：.wb-sb-foot
    // 行的 label 色被平台壳在挂载区容器级局部覆盖（实测覆盖值=#0f1115，:root 注入被
    // 子树自有声明隔断）——底色随壳层换档联动（真实部署配对归壳层；bench 深档注入×
    // 浅壳的混合态下该钮 1.05:1 不可读，但该混合态真实部署不可达）。非工单台可修面，
    // 注入子用例硬翻会制造假配对；壳层真值待宿主确认（看守头注既有交接项）。
    if (el.closest('.wb-sb-foot')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    out.total += 1;
    // 分类序：card 先于 sidebar（板面行卡可能位于 .wb-sb 子树内，dbg 实证）——
    // 分类先于色解析：未实查的元素也必须留在区域账上（旧版先解析后分类，漏检元素凭空消失）
    const region = el.closest('.wb-m') ? 'metrics' : el.closest('.wb-drawer') ? 'drawer'
      : el.closest('.wb-card') ? 'card' : el.closest('.wb-sb') ? 'sidebar' : 'board';
    out.regions[region] = (out.regions[region] || 0) + 1;
    const fg = parseC(cs.color);
    if (!fg) { out.unchecked.push({ el: describe(el), region, color: cs.color }); continue; }
    let opAcc = 1, bg = null; const pending = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const s = getComputedStyle(node);
      opAcc *= parseFloat(s.opacity);
      if (bg === null) {
        const c = parseC(s.backgroundColor);
        if (c && c[3] >= 1) bg = c;
        else if (c && c[3] > 0) pending.push(c);
      }
    }
    if (bg === null) {
      if (pending.length === 0) { out.transparent += 1; continue; } // 全透明链=无法判定，单记不误伤
      bg = [255, 255, 255, 1];                                      // 半透明底叠白纸面（声明性兜底，见头注）
      for (const c of pending.reverse()) bg = blend(c, bg);
    }
    const fgA = fg[3] * opAcc;
    const fgEff = fgA >= 1 ? fg : blend([fg[0], fg[1], fg[2], fgA], bg);
    const need = el.closest('.wb-card[data-state="done"]') ? 3.0 : 4.5;
    const rt = ratio(fgEff, bg);
    if (rt < need - 1e-3) out.violations.push(
      { el: describe(el), region, need, ratio: rt.toFixed(2), color: cs.color, bg: 'rgb(' + bg.slice(0, 3).join(',') + ')' });
  }
  return out;
};

const fmtViolations = (v) => v.slice(0, 8).map((x) =>
  `${x.region}/${x.el} need=${x.need} got=${x.ratio} color=${x.color} bg=${x.bg}`).join('；');

const fmtUnchecked = (u) => u.slice(0, 8).map((x) =>
  `${x.region}/${x.el} color=${x.color}`).join('；');

async function openBoard(page) {
  const board = page.locator('[title="Tickets"], [aria-label="Tickets"]').first();
  const clickish = async (loc) => {
    try { await loc.click({ timeout: 4000 }); }
    catch { await loc.evaluate((el) => el.click()).catch(() => {}); }
  };
  // 入口=侧栏项目行「工单列表」图标（dbg 实证：点图标直接开 .wb-root 板面；
  // 项目行文字点击会改变焦点反而丢板面——本夹具按实测导航，不入投机等待）。
  const entryVisible = await board.isVisible().catch(() => false);
  if (entryVisible) await clickish(board);
  await page.locator('.wb-root').first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});
  const ok = await page.locator('.wb-card[data-ticket-id="t08-0"]')
    .first().waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false);
  record('nav/rowcards', ok,
    ok ? '板面行卡在场' : `板面行卡未达（入口可见=${entryVisible} url=${page.url()} body 头 200 字=${(await page.locator('body').innerText().catch(() => '')).slice(0, 200).replace(/\n+/g, '|')})`);
  return ok;
}

// 忠实注入（页面函数）：找壳层区域覆盖声明所在的祖先（自 .wb-card 向上最高一个
// label 值 ≠ :root 值者=壳层真正声明点），inline+important 打整套令牌——模拟真实
// 壳层换档的作用域。无声明点（平台壳未覆盖）则原样返回，:root 注入已足。
const FAITHFUL_FN = (vars) => {
  const rootV = getComputedStyle(document.documentElement).getPropertyValue('--dsw-alias-label-primary').trim();
  let el = document.querySelector('.wb-card') || document.body.firstElementChild;
  let declarer = null, cur = el;
  while (cur && cur !== document.documentElement) {
    const v = getComputedStyle(cur).getPropertyValue('--dsw-alias-label-primary').trim();
    if (v && v !== rootV) declarer = cur;
    cur = cur.parentElement;
  }
  if (!declarer) return { patched: false };
  for (const [k, val] of Object.entries(vars)) declarer.style.setProperty(k, val, 'important');
  return { patched: true, at: declarer.tagName + '.' + String(declarer.className).split(/\s+/).slice(0, 2).join('.') };
};

try {
  const page = await browser.newPage();

  // T1 子用例：light / dark / fallback-only（零注入）/ legacy（旧平台 bg-base 兜底链，t260907-03）
  for (const leg of ['light', 'dark', 'fallback', 'legacy']) {
    await bench.goto(page, { waitUntil: 'domcontentloaded' });
    const set = TOKEN_SETS[leg];
    if (set) await page.addStyleTag({ content: cssVarsBlock(set) });
    await dismissNotice(page);
    await openBoard(page);
    if (set) {
      const fp = await page.evaluate(FAITHFUL_FN, set).catch(() => ({ patched: false }));
      await page.waitForTimeout(300); // inline patch 生效静置（探针同参）
      // legacy 查询路径核心断言（C5 精确等值）：knockout 生效且兜底链接住时，
      // --dsw-derive-canvas（纯 var 链）的 computed 值必须精确等于 bg-base 代表值
      // #f5f8fa——链被拆/名被删 → 落 #fff；knockout 失效（平台 bg-primary 现值穿透）
      // → 落平台现值。都不是 #f5f8fa，fail-closed 点名红，绝不静默计绿。
      if (leg === 'legacy') {
        const canvas = await page.evaluate(() => {
          const host = document.querySelector('.wb-root') || document.body;
          const probe = document.createElement('span');
          probe.textContent = 'legacy-canvas-probe';
          host.appendChild(probe);
          const v = getComputedStyle(probe).getPropertyValue('--dsw-derive-canvas').trim();
          probe.remove();
          return v;
        }).catch(() => '');
        record('contrast/legacy-canvas-eq-bg-base', canvas === '#f5f8fa',
          canvas === '#f5f8fa'
            ? '兜底链接住旧平台 bg-base（canvas 精确=#f5f8fa，bg-primary knockout 生效）'
            : `兜底链未接住旧平台令牌：--dsw-derive-canvas=${canvas || '(unreadable)'} ≠ #f5f8fa`);
      }
    }

    if (process.env.T08_SHOT) await page.screenshot({ path: '.suyou/screenshots/t08-' + leg + '.png', fullPage: true }).catch(() => {});  // naming-compat
    await page.waitForTimeout(600); // 渲染静置：waitFor visible 后 React 仍有 commit 尾巴，立即扫描会漏板面（实测竞态）
    let scan = await page.evaluate(SCAN_FN);
    if ((scan.regions.card || 0) === 0) {
      await page.waitForTimeout(1500);
      scan = await page.evaluate(SCAN_FN);
    }
    if ((scan.regions.card || 0) === 0) {
      record(`contrast/${leg}`, 'na', `行卡面未达：区域计数=${JSON.stringify(scan.regions)} 总=${scan.total}`);
      continue;
    }
    // 详情面：点 blocked 票「看原因」（blocked=槽 1，票 t08-1）
    const seeWhy = page.locator('[data-ticket-id="t08-1"][data-compact="false"] .wb-card-btn-blue').first();
    let drawerOpened = false;
    if (await seeWhy.isVisible().catch(() => false)) {
      await seeWhy.click({ timeout: 4000 }).catch(() => {});
      drawerOpened = await page.locator('.wb-drawer').waitFor({ state: 'visible', timeout: 8000 })
        .then(() => true).catch(() => false);
      if (drawerOpened) {
        const s2 = await page.evaluate(SCAN_FN);
        scan = { violations: scan.violations.concat(s2.violations), regions: mergeRegions(scan.regions, s2.regions), total: scan.total + s2.total, transparent: scan.transparent + s2.transparent, unchecked: (scan.unchecked || []).concat(s2.unchecked || []) };
        await page.locator('.wb-drawer .wb-close').first().click({ timeout: 3000 }).catch(() => {});
        await page.waitForTimeout(300);
      }
    }
    record(`surface/drawer-open/${leg}`, drawerOpened ? true : 'na',
      drawerOpened ? '详情面（含受阻横幅）入扫' : '详情面未开（导航结构变化时由 fix17 场景守其可达性，本子用例条件豁免）');
    // metrics 面板：事件总线开面板（不可达=na 条件子用例，非全部子用例 na 不红）
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent('wb-metrics-toggle'));
      window.dispatchEvent(new CustomEvent('wb-metrics-toggle'));
    });
    await page.waitForTimeout(1200);
    const metricsOpened = await page.locator('.wb-m').isVisible().catch(() => false);
    if (metricsOpened) {
      const s3 = await page.evaluate(SCAN_FN);
      scan = { violations: scan.violations.concat(s3.violations), regions: mergeRegions(scan.regions, s3.regions), total: scan.total + s3.total, transparent: scan.transparent + s3.transparent, unchecked: (scan.unchecked || []).concat(s3.unchecked || []) };
    }
    record(`surface/metrics-open/${leg}`, metricsOpened ? true : 'na',
      metricsOpened ? 'metrics 文字面入扫（宿主裁定④全台面）' : 'metrics 面板未开（入口结构变化，条件豁免子用例）');
    const unchecked = scan.unchecked || [];
    const legOk = scan.violations.length === 0 && unchecked.length === 0;
    record(`contrast/${leg}`, legOk,
      legOk
        ? `全台面文字对比度达标：实查 ${scan.total - unchecked.length - scan.transparent}/${scan.total}（区域计数=${JSON.stringify(scan.regions)}；透明链=${scan.transparent}；未知色形=0）`
        : `违例 ${scan.violations.length}：${fmtViolations(scan.violations)}`
          + (unchecked.length ? `；未知色形 ${unchecked.length}（fail-closed 点名）：${fmtUnchecked(unchecked)}` : ''));
  }

  // T2 变异子用例：浅档＋故意低对比正文色——看守必须咬（违例>0=断言在咬）
  await bench.goto(page, { waitUntil: 'domcontentloaded' });
  await page.addStyleTag({ content: cssVarsBlock(TOKEN_SETS.mutation) });
  await dismissNotice(page);
  await openBoard(page);
  await page.evaluate(FAITHFUL_FN, TOKEN_SETS.mutation).catch(() => {});
  await page.waitForTimeout(300);
  const mut = await page.evaluate(SCAN_FN);
  record('contrast/mutation-captured', mut.violations.length > 0,
    mut.violations.length > 0
      ? `低对比变异被咬（违例 ${mut.violations.length}，首例=${fmtViolations(mut.violations)}）——对比度断言真实生效`
      : '低对比变异未被咬：看守失效（主区/侧栏均未消费 label-primary？实现未落地或断言失效）');
} finally {
  await browser.close().catch(() => {});
}

function mergeRegions(a, b) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b)) out[k] = (out[k] || 0) + v;
  return out;
}

summarize();
