// Integration tests for ticket t260831-06 — top session-entry tab interactions
// (stay-in-place + rename + close/reopen).
//
// Intent (black-box, user perspective) — the ticket's three complaints:
//   1. Clicking a tab moves it to the head of the row ("点谁谁置顶") instead of
//      staying in place — a user re-finding tabs by muscle memory is disturbed.
//   2. Tabs cannot be renamed.
//   3. Tabs cannot be closed (and, per the ticket acceptance, after closing,
//      re-opening the same session must bring the tab back — 账册重建).
// Plus regression: switch-away-and-back must retain composer content, and the
// fault surface of the new features (malformed ledger fields, ticket-session
// leakage, close/reopen lifecycle stress).
//
// Scenarios (all DOM-level, semantic anchors only — never CSS/text matching):
//   S0 build-contract (no browser): lib/client.js exists, equals client.cjs,
//      and carries the interaction anchors (row/rename/close/reopen).
//   S1 stay-in-place: click a NON-FIRST tab -> ledger order unchanged (this is
//      THE defect discriminator: pre-fix, opening reorders the ledger array).
//   S2 rename: double-click a tab -> inline input appears; type a label +
//      Enter -> ledger entry gains the title, row shows it, survives reload;
//      renaming to empty clears it back to the default label.
//   S3 close + reopen: click a tab's close button -> tab disappears and the
//      ledger drops the entry; a reopen affordance appears -> picking the
//      closed session re-registers it (tab visible again, at head).
//   S4 switch-back retention (needs real staged sessions; SKIP if the console
//      cannot stage): type into A -> create B -> click A's tab -> A text still
//      in the composer.
//   S5 fault surface: ledger seeded with malformed title (object/number), a
//      ticket- prefixed id, and duplicate ids -> entry renders, no crash,
//      ticket- never renders, no duplicated rows.
//   S6 lifecycle stress: close->reopen the same tab 6 times -> single entry,
//      no unbounded growth, zero pageerrors across all browser scenarios.
//
// Environment: SUYOU_TEST_CONSOLE (default http://127.0.0.1:3199), SUYOU_PLAYWRIGHT_PATH.
// Hard guard: refuses to run against the production console port 3099.
// Console provisioning recipe: see integration/baselines/session-top-entry.mjs
// header (same isolated-console recipe applies).

import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const BASE = (process.env.SUYOU_TEST_CONSOLE ?? 'http://127.0.0.1:3199').replace(/\/$/, '');
const LEDGER_KEY = 'suyou-workbench-opened-sessions-v1';

const results = []; // { name, status: 'pass'|'fail'|'skip', detail }
function record(name, status, detail = '') {
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
}

// ---------- S0: build contract (runs everywhere, no browser) ----------

function buildContract() {
  const libJs = join(process.cwd(), 'server/dsh/workbench/lib/client.js');
  const libCjs = join(process.cwd(), 'server/dsh/workbench/lib/client.cjs');
  if (!existsSync(libJs) || !existsSync(libCjs)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — plugin not built');
    return false;
  }
  const same = readFileSync(libJs, 'utf8') === readFileSync(libCjs, 'utf8');
  if (!same) { record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs are out of sync'); return false; }
  const text = readFileSync(libJs, 'utf8');
  const anchors = ['data-wb-session-row', 'data-wb-session-new'];
  const newAnchors = ['data-wb-session-rename', 'data-wb-session-close', 'data-wb-session-reopen'];
  const missing = [...anchors, ...newAnchors].filter((a) => !text.includes(a));
  if (missing.length) {
    record('S0 build-contract', 'fail', `built bundle missing interaction anchors: ${missing.join(', ')}`);
    return false;
  }
  record('S0 build-contract', 'pass', 'lib twin in sync, all interaction anchors present');
  return true;
}

// ---------- browser scenarios ----------

if (BASE.includes(':3099')) {
  console.error('refusing to run: SUYOU_TEST_CONSOLE points at the production console (3099)');
  process.exit(1);
}

let playwright = null;
async function loadPlaywright() {
  const candidates = [];
  if (process.env.SUYOU_PLAYWRIGHT_PATH) candidates.push(process.env.SUYOU_PLAYWRIGHT_PATH);
  candidates.push('playwright-core');
  candidates.push(new URL('../../server/dsh/ui-check/node_modules/playwright-core/index.mjs', `file://${process.cwd()}/`).href);
  for (const c of candidates) {
    try { return await import(c); } catch { /* try next */ }
  }
  return null;
}

async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) });
    return r.ok;
  } catch { return false; }
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts); } catch { /* next */ }
  }
  return null;
}

async function waitFor(cond, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true; } catch { /* keep polling */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  return cond();
}

// Seed the ledger with fake-but-wellformed entries and reload. Returns the
// seeded ids. project/cwd mirror the seed style of session-top-entry.mjs S5.
async function seedLedger(p, entries) {
  await p.evaluate(([k, v]) => localStorage.setItem(k, v), [LEDGER_KEY, JSON.stringify(entries)]);
  await p.reload({ waitUntil: 'networkidle' });
  await p.waitForTimeout(2500);
  await dismissOverlays(p);
}

const domRowIds = (p) => p.evaluate(() =>
  [...document.querySelectorAll('[data-wb-session-row]')].map((el) => el.getAttribute('title').split('\n')[0]));
const domLedger = (p) => p.evaluate((k) => {
  try { return JSON.parse(localStorage.getItem(k) ?? '[]'); } catch { return []; }
}, LEDGER_KEY);
const domClosedKeys = (p) => p.evaluate(() =>
  Object.keys(localStorage).filter((k) => /closed/i.test(k)));

// First-run dialogs intercept pointer events on fresh contexts (see
// session-top-entry.mjs dismissOverlays for the full rationale).
async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first();
    if (!(await dialog.count())) return;
    const btn = dialog.locator('button:enabled').first();
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {});
    else await p.keyboard.press('Escape').catch(() => {});
    await p.waitForTimeout(600);
  }
}

async function newConsolePage(browser, pageErrors = []) {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  p.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)));
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(3000);
  await dismissOverlays(p);
  return { ctx, p };
}

function rowLocator(p, id) {
  return p.locator(`[data-wb-session-row][title^="${id}"]`).first();
}

async function main() {
  const s0ok = buildContract();

  // 失败现场快照：把「此刻页面上有什么」带回 detail，失败可归因（200 字截断内）。
  const snap = async (p) => {
    try {
      const rows = await p.evaluate(() =>
        [...document.querySelectorAll('[data-wb-session-row]')].map((el) => el.getAttribute('title')?.split('\n')[0] ?? '?'));
      const dialogs = await p.locator('[role="dialog"]').count();
      const closed = await domClosedKeys(p);
      return `rows=[${rows.join(',')}] dialogs=${dialogs} closedKeys=${closed.length}`;
    } catch { return '(snapshot unavailable)'; }
  };
  const failWith = async (name, p, e) => record(name, 'fail', `${String(e).slice(0, 120)} @ ${await snap(p)}`);

  const pw = await loadPlaywright();
  const healthy = await consoleHealthy();
  if (!healthy) {
    record('precheck', 'skip', `test console unreachable at ${BASE} (docker compose -f server/dsh/docker-compose.test.yml up -d)`);
  } else if (!pw) {
    record('precheck', 'skip', 'playwright-core not resolvable (browser scenarios skipped)');
  }
  let browser = null;
  let pageErrors = [];
  if (healthy && pw) browser = await launchBrowser(pw);
  if (healthy && pw && !browser) record('precheck', 'skip', 'no browser could be launched');
  let mounted = null;
  if (browser) {
    const probe = await newConsolePage(browser, pageErrors);
    mounted = await probe.p.evaluate(() => !!document.querySelector('[data-wb-session-entry]')).catch(() => false);
    await probe.ctx.close();
    if (!mounted) record('precheck', 'skip', 'workbench top entry not mounted on test console (plugin not loaded)');
  }
  const uiReady = !!(healthy && pw && browser && mounted);

  const seed = [
    { id: 'chat-int-a', project: 'suyou', cwd: '/tmp/integ-a', lastOpenedAt: 100 },
    { id: 'chat-int-b', project: 'suyou', cwd: '/tmp/integ-b', lastOpenedAt: 200 },
    { id: 'chat-int-c', project: 'suyou', cwd: '/tmp/integ-c', lastOpenedAt: 300 },
  ];

  if (uiReady) {
    pageErrors = [];
    const uiScenarios = async () => {
      // ---- S1 stay-in-place ----
      // 初始序不设死：实现口径是「排序键不随点击更新」（lastOpenedAt 只在登记路径
      // 写），两种等价分支（登记顺序 / 保留排序但打开不写）初始序可能不同。验收
      // 语义 = 点击任意 tab 后顺序不变——先采初始序，点击中间行，再比对。
      {
        const { ctx, p } = await newConsolePage(browser, pageErrors);
        try {
          await seedLedger(p, seed);
          const before = await domRowIds(p);
          const beforeLedger = (await domLedger(p)).map((e) => e.id);
          if (before.length !== 3) {
            record('S1 stay-in-place', 'fail', `expected 3 seeded rows, got: ${before.join(',')}`);
          } else {
            await rowLocator(p, before[1]).click({ timeout: 3000 });
            await p.waitForTimeout(2000); // open path may be slow (fake id); ledger must not move
            const ledger = (await domLedger(p)).map((e) => e.id);
            const rows = await domRowIds(p);
            const orderKept = ledger.join(',') === beforeLedger.join(',') && rows.join(',') === before.join(',');
            record('S1 stay-in-place', orderKept ? 'pass' : 'fail',
              orderKept ? `clicking middle tab left order unchanged (${before.join(',')})`
                : `after click ledger=${ledger.join(',')} rows=${rows.join(',')} (was ${before.join(',')})`);
          }
        } catch (e) { record('S1 stay-in-place', 'fail', String(e).slice(0, 200)); }
        await ctx.close();
      }

      // ---- S2 rename (persist + reload + clear) ----
      // 行锚语义：未改名时 title 属性=显示名=id（fake id 无 list 条目，labelOf 兜底 id）；
      // 改名后 title 属性=自定义名（SessionTab 的 title={`${target.title}…`}），
      // 因此改名后用显示文本定位，不再用 id 前缀。
      {
        const { ctx, p } = await newConsolePage(browser, pageErrors);
        try {
          await seedLedger(p, seed);
          const target = (await domRowIds(p)).at(-1); // 最后一行（改名不重排，位置稳定）
          await rowLocator(p, target).dblclick({ timeout: 3000 });
          const input = p.locator('[data-wb-session-rename]').first();
          const appeared = await waitFor(async () => (await input.count()) > 0, 4000);
          if (!appeared) {
            record('S2 rename', 'fail', 'no rename input appeared after double-click');
          } else {
            await input.fill('我的标签');
            await input.press('Enter');
            await p.waitForTimeout(800);
            const ledger = await domLedger(p);
            const a = ledger.find((e) => e.id === target);
            const shown = await p.getByText('我的标签', { exact: true }).count();
            const renamed = a?.title === '我的标签' && shown > 0;
            // reload: title must survive
            await p.reload({ waitUntil: 'networkidle' });
            await p.waitForTimeout(2500);
            await dismissOverlays(p);
            const ledger2 = await domLedger(p);
            const a2 = ledger2.find((e) => e.id === target);
            const shown2 = await p.getByText('我的标签', { exact: true }).count();
            const persisted = a2?.title === '我的标签' && shown2 > 0;
            // clear: rename to empty restores default display
            await p.locator('[data-wb-session-row][title^="我的标签"]').first().dblclick({ timeout: 3000 });
            const input2 = p.locator('[data-wb-session-rename]').first();
            await input2.waitFor({ timeout: 4000 });
            await input2.fill('');
            await input2.press('Enter');
            await p.waitForTimeout(800);
            const ledger3 = await domLedger(p);
            const cleared = !ledger3.find((e) => e.id === target)?.title;
            if (renamed && persisted && cleared) record('S2 rename', 'pass', 'rename persists across reload; empty rename clears');
            else record('S2 rename', 'fail', `renamed=${renamed} persisted=${persisted} cleared=${cleared}`);
          }
        } catch (e) { await failWith('S2 rename', p, e); }
        await ctx.close();
      }

      // ---- S3 close + reopen ----
      {
        const { ctx, p } = await newConsolePage(browser, pageErrors);
        try {
          await seedLedger(p, seed);
          const row = rowLocator(p, 'chat-int-b');
          await row.hover({ timeout: 3000 }).catch(() => {});
          // 关闭钮必须锁进目标行内取——行外 .first() 会点到别的行的 ×
          await row.locator('[data-wb-session-close]').first().click({ timeout: 3000, force: true });
          await p.waitForTimeout(800);
          const ledger = await domLedger(p);
          const rows = await domRowIds(p);
          const closed = !ledger.some((e) => e.id === 'chat-int-b') && !rows.includes('chat-int-b');
          if (!closed) {
            record('S3 close-reopen', 'fail', `close did not remove tab: ledger=${ledger.map((e) => e.id).join(',')}`);
          } else {
            const reopenBtn = p.locator('[data-wb-session-reopen]').first();
            const reopenVisible = await waitFor(async () => (await reopenBtn.count()) > 0, 4000);
            if (!reopenVisible) {
              record('S3 close-reopen', 'fail', 'no reopen affordance after close (reopen path of acceptance pt.3 missing)');
            } else {
              await reopenBtn.click({ timeout: 3000, force: true });
              // 菜单项锚=data-wb-session-restore（比文本匹配稳；项文本=title||id）
              const item = p.locator('[data-wb-session-restore]').first();
              await item.click({ timeout: 4000, force: true });
              await p.waitForTimeout(1200);
              const ledger2 = await domLedger(p);
              const rows2 = await domRowIds(p);
              const reopened = ledger2.some((e) => e.id === 'chat-int-b') && rows2.includes('chat-int-b');
              record('S3 close-reopen', reopened ? 'pass' : 'fail',
                reopened ? 'close removes tab; reopen re-registers it (账册重建)'
                  : `reopen failed: ledger=${ledger2.map((e) => e.id).join(',')} rows=${rows2.join(',')}`);
            }
          }
        } catch (e) { await failWith('S3 close-reopen', p, e); }
        await ctx.close();
      }

      // ---- S4 switch-back retention (needs real staging) ----
      {
        const { ctx, p } = await newConsolePage(browser, pageErrors);
        try {
          await p.evaluate(([k]) => localStorage.removeItem(k), [LEDGER_KEY]);
          await domClosedKeys(p); // no-op read keeps helper referenced
          await p.reload({ waitUntil: 'networkidle' });
          await p.waitForTimeout(2500);
          await dismissOverlays(p);
          const newBtn = p.locator('[data-wb-session-new]').first();
          if (!(await newBtn.count())) throw new Error('new-session button missing');
          await newBtn.click({ timeout: 3000 });
          const staged = await waitFor(async () =>
            (await p.evaluate(() => document.querySelectorAll('[data-wb-session-row][data-active="true"]').length)) > 0
            && (await p.locator('textarea:visible').count()) > 0, 20000);
          if (!staged) {
            record('S4 switch-retention', 'skip', 'console cannot stage sessions (env lacks workspace/profile seeding)');
          } else {
            await p.locator('textarea:visible').first().fill('integration-marker-A');
            const rowsBefore = await domRowIds(p);
            // create B via startSession (staging control above proves the path works)
            await newBtn.click({ timeout: 3000 });
            await waitFor(async () => (await domRowIds(p)).length > rowsBefore.length, 20000);
            // switch back to A by clicking its tab
            const aTitle = rowsBefore[0];
            await rowLocator(p, aTitle).click({ timeout: 3000 });
            const kept = await waitFor(async () =>
              (await p.locator('textarea:visible').first().inputValue()) === 'integration-marker-A', 15000);
            record('S4 switch-retention', kept ? 'pass' : 'fail', kept ? 'A content retained after A→B→A' : 'content lost on switch-back');
          }
        } catch (e) { record('S4 switch-retention', 'fail', String(e).slice(0, 200)); }
        await ctx.close();
      }

      // ---- S5 fault surface: malformed ledger fields ----
      {
        const { ctx, p } = await newConsolePage(browser, pageErrors);
        try {
          const dirty = [
            { id: 'chat-int-x', project: 'suyou', cwd: '/x', lastOpenedAt: 9, title: { evil: true } },
            { id: 'chat-int-y', project: 'suyou', cwd: '/y', lastOpenedAt: 8, title: 42 },
            { id: 'ticket-t9', project: 'suyou', cwd: '/t', lastOpenedAt: 7 },
            { id: 'chat-int-z', project: 'suyou', cwd: '/z', lastOpenedAt: 6 },
            { id: 'chat-int-z', project: 'suyou', cwd: '/dup', lastOpenedAt: 5 },
          ];
          await seedLedger(p, dirty);
          const rows = await domRowIds(p);
          const noCrash = await p.evaluate(() => !!document.querySelector('[data-wb-session-entry]'));
          const noTicket = !rows.some((r) => r.startsWith('ticket-'));
          const noDup = new Set(rows).size === rows.length;
          if (noCrash && noTicket && noDup && rows.length > 0) {
            record('S5 malformed-ledger', 'pass', `dirty titles/ticket-id/dup tolerated; rows=${rows.join(',')}`);
          } else {
            record('S5 malformed-ledger', 'fail', `crash=${!noCrash} ticketLeak=${!noTicket} dup=${!noDup} rows=${rows.join(',')}`);
          }
        } catch (e) { record('S5 malformed-ledger', 'fail', String(e).slice(0, 200)); }
        await ctx.close();
      }

      // ---- S6 lifecycle stress: close->reopen x6 ----
      {
        const { ctx, p } = await newConsolePage(browser, pageErrors);
        try {
          await seedLedger(p, seed);
          let ok = true;
          let lastDetail = '';
          for (let i = 0; i < 6; i++) {
            const row = rowLocator(p, 'chat-int-c');
            await row.hover({ timeout: 3000 }).catch(() => {});
            // 关闭钮锁进目标行内取（同 S3）
            await row.locator('[data-wb-session-close]').first().click({ timeout: 3000, force: true });
            await p.waitForTimeout(400);
            const reopenBtn = p.locator('[data-wb-session-reopen]').first();
            const vis = await waitFor(async () => (await reopenBtn.count()) > 0, 3000);
            if (!vis) { ok = false; lastDetail = `cycle ${i}: reopen affordance missing`; break; }
            await reopenBtn.click({ timeout: 3000, force: true });
            // 菜单项锚=data-wb-session-restore（同 S3）
            const item = p.locator('[data-wb-session-restore]').first();
            await item.click({ timeout: 3000, force: true });
            await p.waitForTimeout(600);
            const ledger = await domLedger(p);
            const cCount = ledger.filter((e) => e.id === 'chat-int-c').length;
            if (cCount !== 1) { ok = false; lastDetail = `cycle ${i}: chat-int-c count=${cCount}`; break; }
          }
          const ledger = await domLedger(p);
          const sane = ok && ledger.length === 3;
          record('S6 lifecycle-stress', sane ? 'pass' : 'fail', sane ? '6 close/reopen cycles stable' : lastDetail || `ledger=${JSON.stringify(ledger).slice(0, 200)}`);
        } catch (e) { await failWith('S6 lifecycle-stress', p, e); }
        await ctx.close();
      }
    };

    await uiScenarios();
    const errs = pageErrors;
    record('S7 page-errors', errs.length === 0 ? 'pass' : 'fail',
      errs.length === 0 ? 'zero pageerror across browser scenarios' : errs.slice(0, 5).join(' | '));
  } else {
    for (const name of ['S1 stay-in-place', 'S2 rename', 'S3 close-reopen', 'S4 switch-retention', 'S5 malformed-ledger', 'S6 lifecycle-stress', 'S7 page-errors']) {
      record(name, 'skip', 'UI precheck not satisfied');
    }
  }

  const pass = results.filter((r) => r.status === 'pass').length;
  const skip = results.filter((r) => r.status === 'skip').length;
  const fail = results.filter((r) => r.status === 'fail').length;
  console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`);
  process.exit(fail > 0 ? 1 : 0);
}

await main();
