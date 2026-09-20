// Ticket t260910-05 integration test — board screenshots are content-asserted.
//
// What it locks (black box over capture.mjs's exported surface, user view):
//   The console board shot (工单列表视图) may only be produced when the board
//   is actually ready — filter chips present AND (row cards ≥1 OR a declared
//   human-readable empty-state anchor present). Before t260910-05 the shutter
//   fired before the main list rendered: a dead board shot (no action buttons)
//   sailed through the gate as green evidence nobody could tell was dead
//   (walkthrough agents are text models; the merge gate only checks file
//   existence). The user-visible contract after the fix:
//     - board ready → the shot run resolves (the image gets taken);
//     - board not ready (no cards, no empty-state anchor) → the run REJECTS =
//       no image, and the capture process goes red through the existing
//       run→failures→exitCode chain (capture.mjs failures[]→exitCode=1) —
//       this scenario pins the reject semantics; the exitCode chain itself is
//       pinned by the ui_evidence stage contract, not duplicated here;
//     - the assertion must be WIRED into every board-family view entry
//       (console-board / -dark / -light): an entry that skips the assertion
//       resolves even on a dead board. The runs are taken FROM the exported
//       view-entry surface, never from the bare factory — a factory that is
//       exported but unwired from the entries must fail this scenario
//       (behavioral wiring lock, review P1);
//     - malformed page (DOM probing throws) → loud rejection, never a silent
//       pass; malformed budget env (SANDBAR_UI_CAPTURE_BOARD_MS) must not
//       crash the run (falls back to the default).
//
// How: a stub page (no browser, no console, no network — 3099 red line safe)
// emulates the DOM-counting surface (page.evaluate / page.waitForFunction run
// against a fake document swapped into globalThis, the way real capture code
// queries `document` inside those callbacks; locator click/evaluate mirror
// forceClick's primary+fallback surface). Anchor selectors are NOT hardcoded
// here: the stub's DOM map is keyed by the selectors exported in
// BOARD_ANCHORS (keys matched by role: chip/card/empty), so anchor renames
// cannot desync this guard from the implementation (KI-051: anchor semantics,
// not literal text).
//
// TDD note: before the implement stage lands the capture exports, the surface
// legs record FAIL with an explicit TDD reason — expected red; must be green
// at arbitrate/merge.
//
// Placement: integration/baselines/ (standing contract guard, not a one-shot
// ticket snapshot); registered in run_scenarios.py SCENARIOS, browser-free
// pool (same pool precedent: sc_capture_redline_gate).
//
// Execution contract (three-state, t260904-12): the last stdout line is
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; fail>0 or all-legs-na →
// exit 1; env_fail>0 → exit 2. This scenario has no environment dimension
// (no console, no browser) — env_fail is 0 by construction; na is reserved
// for the system-state-conditioned empty-state leg.

const BUDGET_ENV = 'SANDBAR_UI_CAPTURE_BOARD_MS';
process.env[BUDGET_ENV] = '50'; // pin a tiny assertion budget: red legs must be fast and deterministic

const CAPTURE_URL = new URL('../../server/ui-check/capture.mjs', import.meta.url).href;
const BOARD_FILES = ['console-board.png', 'console-board-dark.png', 'console-board-light.png'];
const WATCHDOG_MS = 10000;

const results = [];
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na']);
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length;
  const e = results.filter(r => r.status === 'env_fail').length;
  const n = results.filter(r => r.status === 'na').length;
  const f = results.filter(r => r.status === 'fail').length;
  const allNa = results.length > 0 && n === results.length;
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
}

function withDeadline(promise, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(`${label}：看门狗 ${WATCHDOG_MS}ms 超时（桩驱动不得挂起）`)), WATCHDOG_MS)),
  ]);
}

// 桩 page：以 BOARD_ANCHORS 的选择器为键的 DOM 计数面 + openView/forceClick
// 所需的导航面。evaluate/waitForFunction 期间把 fakeDoc 换入 globalThis.document
// （capture 的回调以内联 `document.querySelectorAll(...)` 方式查询，与真浏览器
// 同形）；用毕恢复，防污染本进程其余代码。
function makeStubPage(domMap, opts = {}) {
  const fakeDoc = {
    querySelectorAll: (sel) => Array.from({ length: domMap.get(sel) ?? 0 },
      () => ({ textContent: '工单列表 板面文本头部（桩）' })),
    querySelector: (sel) => (domMap.get(sel) ?? 0) > 0
      ? { textContent: '工单列表 板面文本头部（桩）' } : null,
    body: { innerText: '工单列表 板面文本头部（桩）' },
  };
  function runWithFakeDoc(fn, arg) {
    const had = Object.prototype.hasOwnProperty.call(globalThis, 'document');
    const prev = globalThis.document;
    globalThis.document = fakeDoc;
    try {
      return fn.call(null, arg);
    } finally {
      if (had) globalThis.document = prev; else delete globalThis.document;
    }
  }
  function makeLocator(sel) {
    const api = {
      first() { return api; },
      async waitFor(_o) { return api; },
      async click(_o) { return; },
      async evaluate(fn) {
        if (opts.evaluateThrows) throw new Error('桩 locator.evaluate 爆炸（畸形注入）');
        return fn({ click() {}, textContent: '桩元素' });
      },
      async count() {
        if (opts.countThrows) throw new Error('桩 locator.count 爆炸（畸形注入）');
        return domMap.get(sel) ?? 0;
      },
    };
    return api;
  }
  const page = {
    locator(sel, _opts) { return makeLocator(sel); },
    async waitForSelector(_sel, _o) { return {}; },
    async waitForLoadState(_s) { return; },
    async goto(_u, _o) { return {}; },
    async emulateMedia(_m) { return; },
    async evaluate(fn, arg) {
      if (opts.evaluateThrows) throw new Error('桩 page.evaluate 爆炸（畸形注入）');
      if (typeof fn !== 'function') throw new Error('桩仅支持函数型 evaluate（实现传了表达式串？）');
      return runWithFakeDoc(fn, arg);
    },
    waitForFunction(fn, argA, argB) {
      if (opts.wfThrows) return Promise.reject(new Error('桩 waitForFunction 爆炸（畸形注入）'));
      let options = argB;
      if (options === undefined && argA && typeof argA === 'object' && !Array.isArray(argA) && 'timeout' in argA) options = argA;
      const timeout = Number(options?.timeout ?? 3000);
      const realArg = (options === argA) ? undefined : argA;
      const started = Date.now();
      return new Promise((resolve, reject) => {
        const tick = () => {
          let v;
          try { v = runWithFakeDoc(fn, realArg); } catch (e) { return reject(e); }
          if (v) return resolve(v);
          if (Date.now() - started >= timeout) return reject(new Error(`桩 waitForFunction 超时 ${timeout}ms（就绪锚未在场）`));
          setTimeout(tick, 5);
        };
        tick();
      });
    },
  };
  // 汇合修正（t260910-05 implement）：本场景调用点统一取 `.page` 手柄
  // （entry.run(stub.page) / assertBoardReady(stub.page)），桩以 { page } 暴露——
  // 裸返回 api 会让 stub.page=undefined，死板面子用例因错误原因「假绿」、就绪子用例假红。
  return { page };
}

// 从导出的 BOARD_ANCHORS 里按角色收选择器（键名判角色，值须形如选择器）——
// 锚语义不锚字面（KI-051）；实现调整选择器字面本场景无需跟随。
function collectAnchors(boardAnchors) {
  const found = { chips: [], cards: [], empty: [], generic: [] };
  const looksSelector = (v) => typeof v === 'string' && /^[.[]/.test(v);
  const walk = (node, keyTrail) => {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach((n) => walk(n, keyTrail)); return; }
    if (typeof node === 'object') { for (const [k, v] of Object.entries(node)) walk(v, [...keyTrail, k]); return; }
    if (looksSelector(node)) {
      const key = keyTrail.join('.').toLowerCase();
      if (/chip|filter/.test(key)) found.chips.push(node);
      else if (/card|row/.test(key)) found.cards.push(node);
      else if (/empty|blank|zero/.test(key)) found.empty.push(node);
      else found.generic.push(node);
    }
  };
  walk(boardAnchors, []);
  return found;
}

function domMapFrom(anchors, { chips = 0, cards = 0, empty = 0 } = {}) {
  const m = new Map();
  for (const s of anchors.chips) m.set(s, chips);
  for (const s of anchors.cards) m.set(s, cards);
  for (const s of anchors.empty) m.set(s, empty);
  for (const s of anchors.generic) m.set(s, Math.max(chips, 1)); // 未分类锚：非红态给在场
  return m;
}

async function findViewEntries(mod) {
  const candidates = [mod.VIEWS, mod.views, mod.BOARD_VIEWS, mod.boardViews];
  for (const c of candidates) if (Array.isArray(c)) return c;
  for (const name of ['getViews', 'boardViews', 'getBoardViews']) {
    if (typeof mod[name] === 'function') {
      const v = await mod[name]();
      if (Array.isArray(v)) return v;
    }
  }
  return null;
}

const mod = await import(CAPTURE_URL).catch((e) => ({ __importError: e }));

// ── 子用例 1：导出面（TDD 闸门子用例）──
const missing = [];
if (mod.__importError) missing.push(`capture.mjs 动态导入失败：${String(mod.__importError).slice(0, 120)}`);
if (!mod.__importError) {
  if (typeof mod.makeBoardRun !== 'function') missing.push('makeBoardRun');
  if (typeof mod.assertBoardReady !== 'function') missing.push('assertBoardReady');
  if (!mod.BOARD_ANCHORS || typeof mod.BOARD_ANCHORS !== 'object') missing.push('BOARD_ANCHORS');
}
const tdd = missing.length === 0;
record('export/surface', tdd ? 'pass' : 'fail',
  tdd ? 'makeBoardRun/assertBoardReady/BOARD_ANCHORS 导出在位'
      : `缺导出 ${missing.join(' / ')}——TDD 红态（implement 落地后转绿）`);

const anchors = tdd ? collectAnchors(mod.BOARD_ANCHORS) : null;
const anchorsOk = !!anchors && anchors.chips.length > 0 && anchors.cards.length > 0;
record('export/anchors-shape', anchorsOk ? 'pass'
  : (tdd ? 'fail' : 'fail'),
  anchorsOk ? `chips=${anchors.chips.length} cards=${anchors.cards.length} empty=${anchors.empty.length}`
    : (tdd ? `BOARD_ANCHORS 形状不含 chips/cards 角色锚（键名需可辨 chip/filter 与 card/row）——TDD 红态`
           : '前置导出缺失（见 export/surface）'));

const entries = tdd ? await findViewEntries(mod) : null;
const entriesOk = Array.isArray(entries) && entries.length > 0;
record('export/views-surface', entriesOk ? 'pass' : 'fail',
  entriesOk ? `导出条目面 ${entries.length} 条`
    : (tdd ? '板面视图条目未从模块面导出（VIEWS/等价 getter）——接线锁无法成立（review P1）'
           : '前置导出缺失（见 export/surface）'));

const boardEntries = entriesOk
  ? BOARD_FILES.map((f) => ({ file: f, entry: entries.find((e) => e?.file === f) }))
  : [];
for (const { file, entry } of boardEntries) {
  if (!entry) {
    record(`wiring/${file}`, 'fail', tdd
      ? '未在导出条目面找到该板面条目（P1：三条板面 run 须收敛同一导出面；dark/light 不得留在主循环内联）'
      : '前置导出缺失（见 export/surface）');
    continue;
  }
  // 行为锁判别器：零 DOM 桩满足 openView 全部导航面（图标可见可点）——未接断言的
  // 裸 openView 条目会照常 resolve；只有接了 assertBoardReady 的条目才会在零 DOM
  // 下 reject。拒绝=断言在位（本场景的存在意义）；resolve=接线断（真红）。
  const dead = makeStubPage(domMapFrom(anchors, { chips: 0, cards: 0, empty: 0 }));
  try {
    await withDeadline(Promise.resolve().then(() => entry.run(dead.page)), `wiring/${file} dead-board`);
    record(`wiring/${file}`, 'fail', '零 DOM（板面未就绪）条目仍 resolve——断言未接线或未生效（废图全绿复活）');
  } catch (e) {
    record(`wiring/${file}`, 'pass', `未就绪拒绝：${String(e?.message ?? e).slice(0, 80)}`);
  }
}

// ── 就绪绿：board 条目在就绪 DOM 下 resolve 并返回锚串 ──
{
  const { entry } = boardEntries.find((b) => b.file === 'console-board.png') ?? {};
  if (!entry) {
    record('wiring/ready-resolve', 'fail', '前置缺失（无 console-board 条目）');
  } else {
    const ready = makeStubPage(domMapFrom(anchors, { chips: 3, cards: 2, empty: 0 }));
    try {
      const anchor = await withDeadline(Promise.resolve().then(() => entry.run(ready.page)), 'wiring/ready-resolve');
      record('wiring/ready-resolve', typeof anchor === 'string' && anchor.length > 0 ? 'pass' : 'fail',
        `锚=${String(anchor).slice(0, 60)}`);
    } catch (e) {
      record('wiring/ready-resolve', 'fail', `板面就绪却拒绝（断言假阳性？）：${String(e?.message ?? e).slice(0, 100)}`);
    }
  }
}

// ── assertBoardReady 直驱：绿/红/空态/畸形 ──
if (!tdd) {
  record('assert/ready-green', 'fail', '前置导出缺失（见 export/surface）');
  record('assert/not-ready-red', 'fail', '前置导出缺失（见 export/surface）');
  record('assert/empty-state', 'fail', '前置导出缺失（见 export/surface）');
  record('malformed/probe-throw', 'fail', '前置导出缺失（见 export/surface）');
  record('env/malformed-budget', 'fail', '前置导出缺失（见 export/surface）');
} else {
  try {
    await withDeadline(mod.assertBoardReady(makeStubPage(domMapFrom(anchors, { chips: 3, cards: 2 })).page), 'assert/ready-green');
    record('assert/ready-green', 'pass');
  } catch (e) {
    record('assert/ready-green', 'fail', `就绪板面被拒（假阳性）：${String(e?.message ?? e).slice(0, 100)}`);
  }

  try {
    await withDeadline(mod.assertBoardReady(makeStubPage(domMapFrom(anchors, { chips: 0, cards: 0, empty: 0 })).page), 'assert/not-ready-red');
    record('assert/not-ready-red', 'fail', '零 DOM 未就绪却通过——断言失效（本票病灶本体）');
  } catch (e) {
    record('assert/not-ready-red', 'pass', `未就绪拒绝：${String(e?.message ?? e).slice(0, 80)}`);
  }

  if (anchors.empty.length > 0) {
    try {
      await withDeadline(mod.assertBoardReady(makeStubPage(domMapFrom(anchors, { chips: 3, cards: 0, empty: 1 })).page), 'assert/empty-state');
      record('assert/empty-state', 'pass', '空板面（空态锚在场）放行——人话空态不是废图');
    } catch (e) {
      record('assert/empty-state', 'fail', `空态锚在场却被拒：${String(e?.message ?? e).slice(0, 100)}`);
    }
  } else {
    // 系统状态条件子用例：实现未声明空态锚（方案允许的降级口径：筛选条在场+加载指示
    // 消失）→ 本子用例不适用；非全部子用例 na，不影响三态判定。
    record('assert/empty-state', 'na', '实现未声明空态锚（降级口径：筛选条+加载指示消失）——子用例不适用');
  }

  try {
    // 打中实现的真实探针路径（locator.count 炸）：assertBoardReady 必须即刻
    // loud 上抛（其 count 包装重抛），绝不静默吞掉当绿。
    await withDeadline(mod.assertBoardReady(makeStubPage(new Map(), { countThrows: true }).page), 'malformed/probe-throw');
    record('malformed/probe-throw', 'fail', 'DOM 探测抛异常却被吞掉通过——畸形输入必须 loud 拒绝');
  } catch (e) {
    record('malformed/probe-throw', 'pass', `异常 loud 上抛：${String(e?.message ?? e).slice(0, 80)}`);
  }

  const prev = process.env[BUDGET_ENV];
  try {
    process.env[BUDGET_ENV] = 'not-a-number';
    await withDeadline(mod.assertBoardReady(makeStubPage(domMapFrom(anchors, { chips: 3, cards: 2 })).page), 'env/malformed-budget');
    record('env/malformed-budget', 'pass', '畸形预算 env 回落缺省，功能不崩（C3 口径）');
  } catch (e) {
    record('env/malformed-budget', 'fail', `畸形预算 env 致崩溃/拒绝：${String(e?.message ?? e).slice(0, 100)}`);
  } finally {
    process.env[BUDGET_ENV] = prev;
  }
}

summarize();
