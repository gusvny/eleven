// sc_wb_contrast_quadrant.mjs — t260907-08 场景①：工单台对比度四象限矩阵看守（KI-055 根治面）。
//
// intent（灰盒，用户可感知行为；宿主 260907 实报两症状＋KI-055「主题家族第三次台面绿×真机红」）：
//   KI-055 病根=主题验收只跑「测试台平台（新版 token 集）×双外观」，从未跑「旧版平台
//   token 集（0.1.1-rc.2：无 --dsw-alias-bg-primary 名、只有 bg-base）×双外观」——平台
//   版本维度缺失。本场景把验收升为四象限矩阵：{新版全令牌集, 旧版 bg-base-only}×{深, 浅}，
//   每格在六张用户台面（工单列表→详情抽屉→文档视图→立项单视图→新建工单弹层→metrics）
//   对全部可见文字实算 WCAG 对比度（正文级 4.5:1，收口行卡 3.0:1——口径沿袭 t260905-08），
//   另有 fallback-only 子用例（零注入，兜底链自洽可读）与变异子用例（低对比注入必咬，守测试本身）。
//   两症状与本矩阵的映射：症状①（浅色文档页不可读）=new-light 格 docs 面；症状②（深色
//   部分子面仍浅色）=new-dark 格各面。hex 看守（t260905-08 场景②，已登记）守「零裸 hex」
//   静态面，本场景守「真渲染可读」动态面——intent 不重叠。
//
// 格与判定（代表值纪律，KI-055 同款「代表值造绿」防御）：
//   new-light / new-dark / legacy-light=硬子用例（违例=0 且未知色形=0 才过）；
//   legacy-light 格带 canvas 精确等值探针（--dsw-derive-canvas===bg-base 代表值 #f5f8fa，
//   沿袭 t260907-03 先例：兜底链接不住旧令牌名=点名红）；
//   legacy-dark=诊断子用例：0.1.1-rc.2 深底 bg-base 代表值**未经宿主确认**，不选方便假值造绿
//   （lib_t260905_08.mjs legacy 查询路径选值约束同源纪律）——本子用例全扫照跑、比值全打印、na 注记
//   入账，不计入四象限判定；宿主确认真值后填入下方 LEGACY_DARK_BG_BASE 常量，本子用例自动
//   升为硬子用例（merge 关卡执行，机械升级路径）；
//   fallback=硬子用例（零注入下兜底链自洽可读——不可失败的子用例是装饰，与 t260905-08 同判）；
//   mutation=变异子用例（浅档＋label-primary:#7a7a85≈3.4:1 → 违例>0 才过）。
//   反空转守卫（KI-052「绿≠真查」教训）：文档/立项单/新建工单弹层三张本票新走查面，
//   若全程一格都没真正入扫（扫描区域计数=0，点击成功≠入扫），coverage/novel-surfaces
//   fail-closed 点名红——防「导航 na 空转绿」。
//
// high-level steps：
//   T0 自举隔离台（10 档 epic 挑码×四态轮换＋无 epic 票；docs=仓树真源 docs/ 定稿库，
//      立项单=t260915-09 起夹具根自植——client 按项目根取数后夹具根无 notes/epics 即
//      列表空、弹层链断、coverage 守卫 fail-closed，自植一枚不弱化守卫）＋ playwright
//      探测（缺失=env_fail 有声红 exit 2，三态契约「闸内无 SKIP」，KI-036/KI-046 口径）。
//   T1 子用例遍历 new-light/new-dark/legacy-light/legacy-dark/fallback：每子用例 goto→:root 注入
//      令牌（legacy 格含 bg-primary knockout，须经忠实注入打到壳层声明点才造得出真缺席
//      态）→开板忠实注入→逐面导航+扫描：工单列表→「看原因」详情抽屉→侧栏「文档」图标
//      开文档视图（点首篇树项载正文）→侧栏「立项单」图标开立项单视图（点首行进详情→
//      「＋ 新建工单」开弹层）→回板面→事件总线开 metrics。每子用例「违例=0 且未知色形=0」
//      硬子用例才过；违例/未知色形打印 台面/元素/色值/比值（数值化取证）。色解析收 rgb()/
//      rgba()/color(srgb …)（fail-closed：未知 computed 形态=点名红，绝不静默计绿——
//      gen0 验收探针实锤旧解析只认 rgb 曾静默漏检 73% 表面，KI-052 同构防复发）。
//   T2 变异子用例＋coverage 反空转守卫＋SUMMARY 末行。
//
// 复用取舍（对 review_plan gen1 意见 A 的交代）：
//   带过来（import ../t260905-08/lib_t260905_08.mjs，跨票 import 先例=该 lib 本身）：
//   隔离台自举/进程树回收 teardownOnExit/playwright 探测 env_fail/notice 关闭/结果记账
//   三态 SUMMARY/令牌集与 cssVarsBlock/忠实注入语义。扫描器 SCAN_FN 与 FAITHFUL_FN 复制
//   自 sc_wb_contrast_guard.mjs（该场景未导出；复制先例=lib 对 fnv1a 的处理，漂移责任=
//   两侧头注对齐，后改方同步）；本票扩展仅两处：区域分类加 docs/modal/epics 标签（阈值
//   逻辑零改动）、coverage 反空转守卫（新增）。
//   不带：t260905-08 走查子用例的行为断言（写监控/T 系）——本场景只做对比度与可达入扫，
//   行为语义归 17 号场景族与 t260905-07。
//   不另立 hex 清零场景：t260905-08-hex-clean（已登记）即「客户端零裸 hex」intent 的
//   唯一看守，本票实现落地使其红→绿即工单验收②，另立薄壳=intent 级重复（设计纪律）。
//   扫描器复制本票扩展共三处（阈值/色解析/半透明合成逻辑零改动）：①区域分类加
//   docs/modal/epics 标签；②coverage 反空转守卫判据；③WCAG 1.4.3 非活动组件豁免
//   （disabled 控件入 inactive 账留痕不静默——epics「保存状态」钮 :disabled opacity:.5
//   实锤误伤面；活动控件与 done 卡 3.0 档零改动）。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na；playwright-core/隔离台依赖缺失=
//   env_fail（exit 2）有声红，绝不静默降级；3099/7233 红线：隔离台端口由 freePort 分配，
//   全程不触碰真控制台。实现落地前红属预期（TDD 信号）；arbitrate/merge 期硬子用例必须绿、
//   legacy-dark 诊断子用例保持 na 注记直到宿主确认代表值。
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import {
  makeRegistryRoot, writeProjectEntry, tmpRoot, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
  pickEpicCodes, TOKEN_SETS, cssVarsBlock,
} from '../t260905-08/lib_t260905_08.mjs';

const { record, summarize } = makeResults();

// 升级契约：宿主确认 0.1.1-rc.2 深底 bg-base 代表值后把 null 换成代表值字符串
// （merge 关卡执行）；填入前 legacy-dark 为诊断子用例（na 注记），填入后自动升硬子用例。
const LEGACY_DARK_BG_BASE = null;

const NOW = Math.floor(Date.now() / 1000);
const wf = { id: 'wf-q08', name: '四象限模板', stages: [
  { id: 'p1', name: '起草' }, { id: 'p2', name: '实现' }, { id: 'p3', name: '验收' },
] };
const STATES = [
  { status: 'running', stage_state: 'awaiting-human' }, // waiting
  { status: 'running', stage_state: 'blocked' },        // blocked（详情抽屉走查源）
  { status: 'running', stage_state: 'running' },        // active
  { status: 'closed', stage_state: 'awaiting' },        // done（3.0 降权档）
];
const slots = pickEpicCodes();
const row = (over) => ({
  id: over.id, project: 'q08a', title: over.title, role: 'developer',
  status: over.status, stage: over.stage ?? 'p2', stage_state: over.stage_state,
  workflow: 'wf-q08', epic: over.epic ?? '', handoff_count: 1, pending_count: 0,
  worktree: `/tmp/q08/${over.id}`, updated: '2026-09-07 12:00:00',
  updated_ts: NOW - 300, created: NOW - 3600,
  blocked_reason: over.reason,
});
const tickets = slots.map((code, i) => {
  const st = STATES[i % 4];
  return row({
    id: `q08-${i}`, title: `四象限票 ${i}（epic 槽 ${slots.indexOf(code)}）`,
    ...st, stage: st.status === 'closed' ? 'p3' : 'p2',
    epic: code, reason: st.stage_state === 'blocked' ? '环境红：四象限注入不可达' : undefined,
  });
});
tickets.push(row({ id: 'q08-noepic', title: '四象限票无epic', status: 'running', stage_state: 'running' }));

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
  const projectsRoot = makeRegistryRoot('q08-quad-reg-');
  // t260915-09 守卫修正：本票后立项单视图按夹具项目根取数（KI-057 client 穿参收口），
  // q08a 根无 notes/epics → 列表空 → 「列表→首行→详情→弹层」链断 → coverage 反空转
  // 守卫（docs/epics/modal 三面全入扫）fail-closed 红。夹具根自植一枚可解析立项单
  // （状态行给合法枚举供详情链消费），不弱化任何守卫。
  const q08Root = tmpRoot('q08-quad-proj-');
  await mkdir(join(q08Root, 'notes', 'epics'), { recursive: true });
  await writeFile(join(q08Root, 'notes', 'epics', 'q08-fixture-epic.md'), [
    '# 立项单：q08-fixture-epic', '', '| 字段 | 值 |', '| --- | --- |',
    '| 代号 | `q08-fixture-epic` |', '| 状态 | 已立项（执行中） |', '| 立项日期 | 2026-09-15 |', '',
    '四象限夹具立项单（t260915-09 自植；对比度走查链「列表→详情→弹层」数据源）。', '',
  ].join('\n'));
  writeProjectEntry(projectsRoot, 'q08a', '四象限夹具', [q08Root]);
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

// 页面内扫描：复制自 sc_wb_contrast_guard.mjs SCAN_FN（漂移责任=两侧头注对齐，后改方同步）。
// 本票扩展（仅此两处，阈值/解析/豁免逻辑零改动）：①区域分类加 modal/docs/epics 标签；
// ②区域计数即「真入扫」凭证（coverage 反空转守卫的判据）。
const SCAN_FN = () => {
  const parseC = (s) => {
    const aOf = (raw) => raw === undefined ? 1 : (String(raw).endsWith('%') ? parseFloat(raw) / 100 : parseFloat(raw));
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,\/\s]+([\d.]+%?))?\s*\)/.exec(s);
    if (m) return [+m[1], +m[2], +m[3], aOf(m[4])];
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
  for (const el of document.querySelectorAll('body *')) {
    if (!el.closest('.wb-root') && !el.closest('.wb-sb')) continue;
    let has = false;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { has = true; break; }
    if (!has) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.closest('.wb-sb-foot')) continue; // 壳层槽豁免（KI-052 边界声明，沿袭看守）
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    // WCAG 1.4.3 非活动组件豁免（本票扩展②）：disabled 控件（epics「保存状态」钮
    // :disabled{opacity:.5} 实锤）不计入断言，进 inactive 账留痕不静默——活动控件、
    // done 行卡（3.0 档）的既有口径零改动
    if (el.closest('button[disabled],input[disabled],select[disabled],textarea[disabled],[aria-disabled="true"]')) {
      out.regions.inactive = (out.regions.inactive || 0) + 1;
      continue;
    }
    out.total += 1;
    const region = el.closest('.wb-m') ? 'metrics'
      : el.closest('.wb-drawer') ? 'drawer'
      : el.closest('.wb-ep-modal') ? 'modal'
      : el.closest('.wb-doc-root') ? 'docs'
      : el.closest('.wb-ep-root') ? 'epics'
      : el.closest('.wb-card') ? 'card'
      : el.closest('.wb-sb') ? 'sidebar' : 'board';
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
      if (pending.length === 0) { out.transparent += 1; continue; }
      bg = [255, 255, 255, 1];
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
const mergeScan = (a, b) => ({
  violations: a.violations.concat(b.violations),
  regions: (() => { const o = { ...a.regions }; for (const [k, v] of Object.entries(b.regions)) o[k] = (o[k] || 0) + v; return o; })(),
  total: a.total + b.total, transparent: a.transparent + b.transparent,
  unchecked: (a.unchecked || []).concat(b.unchecked || []),
});

// 忠实注入：复制自 sc_wb_contrast_guard.mjs FAITHFUL_FN（漂移责任同上）。
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

const clickish = async (loc) => {
  try { await loc.click({ timeout: 4000 }); }
  catch { await loc.evaluate((el) => el.click()).catch(() => {}); }
};

async function openBoard(page) {
  const entry = page.locator('[title="Tickets"], [aria-label="Tickets"]').first();
  const visible = await entry.isVisible().catch(() => false);
  if (visible) await clickish(entry);
  await page.locator('.wb-root').first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});
  const ok = await page.locator('.wb-card[data-ticket-id="q08-0"]')
    .first().waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false);
  return ok;
}

async function canvasProbe(page) {
  return page.evaluate(() => {
    const host = document.querySelector('.wb-root') || document.body;
    const probe = document.createElement('span');
    probe.textContent = 'quad-canvas-probe';
    host.appendChild(probe);
    const v = getComputedStyle(probe).getPropertyValue('--dsw-derive-canvas').trim();
    probe.remove();
    return v;
  }).catch(() => '');
}

const LEGS = ['new-light', 'new-dark', 'legacy-light', 'legacy-dark', 'fallback'];
const setFor = (leg) => {
  if (leg === 'new-light') return TOKEN_SETS.light;
  if (leg === 'new-dark') return TOKEN_SETS.dark;
  if (leg === 'legacy-light') return TOKEN_SETS.legacy;
  if (leg === 'legacy-dark') {
    return {
      ...TOKEN_SETS.dark,
      '--dsw-alias-bg-primary': 'initial',
      '--dsw-alias-bg-base': LEGACY_DARK_BG_BASE ?? TOKEN_SETS.legacy['--dsw-alias-bg-base'],
    };
  }
  return null; // fallback：零注入
};

const seen = { docs: false, epics: false, modal: false }; // 反空转守卫的全程账本

// 逐格截图（merge 走查对照基线，t260907-08 implement 补）：T08Q_SHOT=1 时对三张
// 新走查面落 .suyou/screenshots/t08q-<格>-<面>.png；默认关闭零开销，矩阵断言不依赖截图。
const SHOT = process.env.T08Q_SHOT === '1';
const shot = (page, leg, surface) => SHOT
  ? page.screenshot({ path: `.suyou/screenshots/t08q-${leg}-${surface}.png` }).catch(() => {})
  : Promise.resolve();

try {
  const page = await browser.newPage();

  for (const leg of LEGS) {
    await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
    const set = setFor(leg);
    if (set) await page.addStyleTag({ content: cssVarsBlock(set) });
    await dismissNotice(page);
    const boardOk = await openBoard(page);
    record(`nav/rowcards/${leg}`, boardOk,
      boardOk ? '板面行卡在场' : `板面行卡未达 url=${page.url()}`);
    if (!boardOk) {
      record(`contrast/${leg}`, 'na', `行卡面未达，本子用例无法扫描（区域计数空）`);
      continue;
    }
    if (set) {
      await page.evaluate(FAITHFUL_FN, set).catch(() => {});
      await page.waitForTimeout(300);
    }
    // legacy 格 canvas 精确等值探针（硬子用例断言；legacy-dark 值仅入诊断账）
    if (leg === 'legacy-light' || leg === 'legacy-dark') {
      const canvas = await canvasProbe(page);
      if (leg === 'legacy-light') {
        record('canvas-eq/legacy-light', canvas === '#f5f8fa',
          canvas === '#f5f8fa'
            ? '兜底链接住旧平台 bg-base（canvas 精确=#f5f8fa，bg-primary knockout 生效）'
            : `兜底链未接住旧平台令牌：--dsw-derive-canvas=${canvas || '(unreadable)'} ≠ #f5f8fa`);
      } else {
        record(`canvas-eq/${leg}`, 'na',
          `诊断子用例不判等值：canvas=${canvas || '(unreadable)'}（代表值${LEGACY_DARK_BG_BASE ? '已确认=' + LEGACY_DARK_BG_BASE : '未经宿主确认'}）`);
      }
    }

    await page.waitForTimeout(600); // 渲染静置（沿袭看守：waitFor 后 React 仍有 commit 尾巴）
    let scan = await page.evaluate(SCAN_FN);
    if ((scan.regions.card || 0) === 0) { await page.waitForTimeout(1500); scan = await page.evaluate(SCAN_FN); }

    // 详情抽屉：点 blocked 票「看原因」（blocked=槽 1，票 q08-1）
    const seeWhy = page.locator('[data-ticket-id="q08-1"][data-compact="false"] .wb-card-btn-blue').first();
    let drawerOpened = false;
    if (await seeWhy.isVisible().catch(() => false)) {
      await seeWhy.click({ timeout: 4000 }).catch(() => {});
      drawerOpened = await page.locator('.wb-drawer').waitFor({ state: 'visible', timeout: 8000 })
        .then(() => true).catch(() => false);
      if (drawerOpened) {
        scan = mergeScan(scan, await page.evaluate(SCAN_FN));
        await shot(page, leg, 'drawer');
        await page.locator('.wb-drawer .wb-close').first().click({ timeout: 3000 }).catch(() => {});
        await page.waitForTimeout(300);
      }
    }
    record(`surface/drawer-open/${leg}`, drawerOpened ? true : 'na',
      drawerOpened ? '详情面入扫' : '详情面未开（可达性由 t260905-07 场景守，本子用例条件豁免）');

    // 文档视图：侧栏「文档」图标 → 树载入（等待树项，盲等 1200ms 实锤竞态）→点首篇
    // 载正文（懒加载契约：等正文元素在场再扫，正文文字正是症状①的违例源）
    let docsOpened = false;
    const docsIcon = page.locator('[title="文档"], [aria-label="文档"]').first();
    for (let attempt = 0; attempt < 2 && !docsOpened; attempt++) {
      // 首版实跑偶发：壳 hydration 竞态下首击丢导航——重试一次（同 epics 面竞态修法精神）
      if (attempt > 0) { await page.waitForTimeout(800); }
      if (await docsIcon.isVisible().catch(() => false)) {
        await clickish(docsIcon);
        docsOpened = await page.locator('.wb-doc-root').first().waitFor({ state: 'visible', timeout: 8000 })
          .then(() => true).catch(() => false);
      }
    }
    if (docsOpened) {
      const item = page.locator('.wb-doc-item').first();
      const treeReady = await item.waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false);
      if (treeReady) {
        await clickish(item);
        await page.locator('.wb-doc-body h1, .wb-doc-body p, .wb-doc-body pre')
          .first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
      }
      await page.waitForTimeout(400);
      scan = mergeScan(scan, await page.evaluate(SCAN_FN));
      await shot(page, leg, 'docs');
    }
    record(`surface/docs-open/${leg}`, docsOpened ? true : 'na',
      docsOpened ? `文档面入扫（树就绪+正文懒加载；区域计数 docs=${scan.regions.docs || 0}）` : '文档入口未达（本票新走查面，全程未入扫将被 coverage 守卫点名）');

    // 立项单视图：侧栏「立项单」图标 → 列表（真源 notes/epics/*.md）→点首行进详情→「＋ 新建工单」弹层
    let epicsOpened = false, modalOpened = false;
    const epicsIcon = page.locator('[title="立项单"], [aria-label="立项单"]').first();
    if (await epicsIcon.isVisible().catch(() => false)) {
      await clickish(epicsIcon);
      epicsOpened = await page.locator('.wb-ep-root').first().waitFor({ state: 'visible', timeout: 8000 })
        .then(() => true).catch(() => false);
      if (epicsOpened) {
        // 数据就绪等待：列表行可见再点（首行必须是 tbody 数据行，thead 行无 onClick；
        // 首版实跑 coverage 守卫开火实锤：盲等 800ms+点 thead=弹层永远开不了=场景永不绿）
        const epicRow = page.locator('.wb-ep-table tbody tr').first();
        const rowReady = await epicRow.waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false);
        if (rowReady) {
          await clickish(epicRow);
          await page.waitForTimeout(600);
        }
        scan = mergeScan(scan, await page.evaluate(SCAN_FN));
        const createBtn = page.locator('button', { hasText: '新建工单' }).first();
        const btnReady = await createBtn.waitFor({ state: 'visible', timeout: 6000 }).then(() => true).catch(() => false);
        if (btnReady) {
          await clickish(createBtn);
          modalOpened = await page.locator('.wb-ep-modal').waitFor({ state: 'visible', timeout: 6000 })
            .then(() => true).catch(() => false);
          if (modalOpened) {
            await page.waitForTimeout(400);
            scan = mergeScan(scan, await page.evaluate(SCAN_FN));
            await shot(page, leg, 'new-ticket');
          }
        }
        record(`surface/newticket-modal/${leg}`, modalOpened ? true : 'na',
          modalOpened ? '新建工单弹层入扫' : `弹层未开（列表行就绪=${rowReady}，入口结构变化或 notes/epics 空；全程未入扫将被 coverage 守卫点名）`);
      }
    }
    record(`surface/epics-open/${leg}`, epicsOpened ? true : 'na',
      epicsOpened ? `立项单面入扫（区域计数 epics=${scan.regions.epics || 0}）` : '立项单入口未达');
    // 回板面再开 metrics（弹层随视图卸载，区域账不串）
    const boardIcon = page.locator('[title="Tickets"], [aria-label="Tickets"]').first();
    if (await boardIcon.isVisible().catch(() => false)) await clickish(boardIcon);
    await page.waitForTimeout(400);
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent('wb-metrics-toggle'));
      window.dispatchEvent(new CustomEvent('wb-metrics-toggle'));
    });
    // 数据就绪等待替代盲等：固定 1200ms 实锤 na/pass 跨轮抖动（验收走查轮 na=3 vs 设计轮 na=2），
    // 面板挂载即判（上限 6s）；条件子用例语义不变（不可达仍 na，不假红不假绿）
    const metricsOpened = await page.locator('.wb-m').waitFor({ state: 'visible', timeout: 6000 })
      .then(() => true).catch(() => false);
    if (metricsOpened) scan = mergeScan(scan, await page.evaluate(SCAN_FN));
    record(`surface/metrics-open/${leg}`, metricsOpened ? true : 'na',
      metricsOpened ? 'metrics 文字面入扫' : 'metrics 面板未开（条件豁免子用例）');

    // 反空转账本：点击成功≠入扫，以扫描区域计数为准
    if ((scan.regions.docs || 0) > 0) seen.docs = true;
    if ((scan.regions.epics || 0) > 0) seen.epics = true;
    if ((scan.regions.modal || 0) > 0) seen.modal = true;

    const unchecked = scan.unchecked || [];
    if (leg === 'legacy-dark' && !LEGACY_DARK_BG_BASE) {
      const canvas = await canvasProbe(page);
      record(`contrast/${leg}`, 'na',
        `诊断子用例（不计入四象限判定）：0.1.1-rc.2 深底 bg-base 代表值未经宿主确认，不选方便假值造绿`
        + `（KI-055 同款「代表值造绿」防御）。本子用例以浅底代表值×深字运行，仅为证明该格扫描可运行：`
        + `违例=${scan.violations.length}（首例=${fmtViolations(scan.violations) || '无'}）`
        + `未知色形=${unchecked.length} canvas=${canvas || '(unreadable)'}。`
        + `宿主确认代表值后填入 LEGACY_DARK_BG_BASE 常量，本子用例自动升硬子用例`);
    } else {
      const legOk = scan.violations.length === 0 && unchecked.length === 0;
      record(`contrast/${leg}`, legOk,
        legOk
          ? `六面全扫对比度达标：实查 ${scan.total - unchecked.length - scan.transparent}/${scan.total}（区域=${JSON.stringify(scan.regions)}；透明链=${scan.transparent}；未知色形=0）`
          : `违例 ${scan.violations.length}：${fmtViolations(scan.violations)}`
            + (unchecked.length ? `；未知色形 ${unchecked.length}（fail-closed 点名）：${fmtUnchecked(unchecked)}` : ''));
    }
  }

  // 变异子用例：浅档＋故意低对比正文色——看守必须咬（违例>0=断言在咬）
  await page.goto(`${bench.base}/`, { waitUntil: 'domcontentloaded' });
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

  // coverage 反空转守卫：本票三张新走查面全程（所有子用例合计）必须至少真正入扫一次
  const novelOk = seen.docs && seen.epics && seen.modal;
  record('coverage/novel-surfaces', novelOk,
    novelOk
      ? '文档/立项单/新建工单弹层三面至少在一格真实入扫（区域计数>0）——矩阵非空转'
      : `新走查面未真正入扫（docs=${seen.docs} epics=${seen.epics} modal=${seen.modal}）——四象限对症状面的覆盖是空的，fail-closed 点名`);
} finally {
  await browser.close().catch(() => {});
}

summarize();
