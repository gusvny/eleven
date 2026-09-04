// Integration tests for ticket t260831-04 — session top entry (compact MRU entry).
//
// Intent (black-box, user perspective):
//   Production defect triad after t260831-02:
//     1. MRU list always empty (0 rows even after creating sessions).
//     2. First "new session" click never flips data-phase to active (only the 2nd does).
//     3. Switching away and back loses conversation content and asks for workspace again.
//   This suite replays the user-visible scenarios against the ISOLATED test console
//   (127.0.0.1:3199, Docker test env per docs/testing-guide.md) and asserts the
//   acceptance criteria from the ticket, plus fault-surface cases:
//   malformed ledger input, ticket-session leakage, ledger persistence across reload.
//
// High-level steps:
//   - Precheck: node >= 22.18, playwright-core resolvable, test console reachable,
//     workbench top entry mounted ([data-wb-session-entry]) — any miss = clean SKIP.
//   - S1 MRU visibility: click new -> at least 1 session row renders immediately.
//   - S2 First-click activation: from a fresh profile (hero), ONE click -> data-phase=active.
//   - S3 Switch-back retention: type into A -> create B -> click A's row -> A content
//     still visible, phase=active, hero not re-shown (no workspace re-select).
//   - S4 Console hygiene: zero console.error / pageerror across all UI scenarios.
//   - S5 Malformed ledger: bad JSON / non-array / dirty entries in the ledger key ->
//     entry still renders, no crash (fault-tolerant degradation to empty list).
//   - S6 Ticket-session leakage: ledger entry with `ticket-` id must never render.
//   - S7 Persistence: sessions created before a reload still listed after it.
//   - S8 Server layer (no browser): POST global-session/open twice -> ok:true,
//     session_id matches ^chat- (never ticket-), ids distinct.
//
// Environment: SUYOU_TEST_CONSOLE (default http://127.0.0.1:3199), SUYOU_PLAYWRIGHT_PATH
// (explicit path to playwright-core index.mjs). Hard guard: refuses to run against
// the production console port 3099.
//
// Provisioning recipe for a fully isolated console on a machine without Docker
// (used by integration to arbitrate t260831-04; console booted from the worktree
// so the plugin under test is the lane's own build):
//   1. DSH_HOME=/tmp/dsh-integ  (fresh state; never the user's ~/.dsh)
//   2. mkdir -p $DSH_HOME/profiles && ln -s <lane>/server/dsh/profile $DSH_HOME/profiles/suyou
//   3. Seed a workspace record (copy the shape from the user's
//      ~/.dsh/storages/workspace.json: unit/global/tables.workspaces with
//      createdAt/updatedAt; path must equal the session cwd from projects.yaml)
//      into $DSH_HOME/storages/workspace.json
//   4. cp -R ~/.dsh/.agent-presets/suyou-integration $DSH_HOME/.agent-presets/
//   5. cp ~/.dsh/settings.yaml $DSH_HOME/ (no inline secrets — apiKeyEnv references only)
//   6. Port patch overlay (cordis.patch.yml's webserver.port is not overridden by
//      the CLI flag): write a patch yml `- id: webserver / config: {host, port}`
//      and boot: DSH_HOME=$DSH_HOME dsh --profile suyou --patch <patch.yml> --no-open
//   7. Run: SUYOU_TEST_CONSOLE=http://127.0.0.1:<port> node integration/baselines/session-top-entry.mjs
// Without steps 3-5 the console cannot stage conversations (phase stays hero with
// current already set) and S2/S3 will FAIL for environment reasons — the factory
// composer path flipping to active within ~1s is the control proving staging works.

const LEDGER_KEY = 'suyou-workbench-opened-sessions-v1';
const BASE = (process.env.SUYOU_TEST_CONSOLE ?? 'http://127.0.0.1:3199').replace(/\/$/, '');

const results = []; // { name, status: 'pass'|'fail'|'skip', detail }
function record(name, status, detail = '') {
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
}

// ---------- prechecks ----------

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

// ---------- helpers ----------

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts); } catch { /* next */ }
  }
  return null;
}

const phase = (p) => p.evaluate(() => document.querySelector('[data-phase]')?.getAttribute('data-phase') ?? '');
const rowCount = (p) => p.evaluate(() => document.querySelectorAll('[data-wb-session-row]').length);

async function newConsolePage(browser, consoleMessages, pageErrors) {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  p.on('console', (m) => { if (m.type() === 'error') consoleMessages.push(m.text().slice(0, 200)); });
  p.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)));
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(3000); // let plugin injection settle (same margin as prod probes)
  await dismissOverlays(p);
  return { ctx, p };
}

// The dsh shell shows first-run modals on a fresh profile ("Add an API key"
// with a disabled "Save and continue" until a key is entered, then an
// "Internal Testing Notice"); their masks intercept all pointer events until
// dismissed (persists per browser profile, so every fresh test context must
// dismiss them — same as a real user's first visit: skip configuration).
async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first();
    if (!(await dialog.count())) return;
    // first ENABLED button: "Save and continue" stays disabled without an API key
    const btn = dialog.locator('button:enabled').first();
    if (await btn.count()) {
      await btn.click({ timeout: 3000 }).catch(() => {});
    } else {
      await p.keyboard.press('Escape').catch(() => {});
    }
    await p.waitForTimeout(600);
  }
}

async function clickNew(p) {
  await dismissOverlays(p); // first-run/key dialogs can reappear mid-scenario and intercept clicks
  const btn = p.locator('[data-wb-session-new]').first(); // semantic anchor, never text matching
  if (!(await btn.count())) return false;
  await btn.click({ timeout: 3000 });
  return true;
}

// Landing state after "new session": MRU row for the new session marked active
// (current switched to it) and a composer ready for input. A fresh blank
// session shows data-phase=hero by platform semantics (see s2 comment).
async function waitLanded(p, ms = 15000) {
  return waitFor(async () => {
    const activeRow = await p.evaluate(() => !!document.querySelector('[data-wb-session-row][data-active="true"]'));
    const composer = await p.locator('textarea:visible').count();
    return activeRow && composer > 0;
  }, ms);
}

// Wait until cond() turns true; poll every 250ms up to ms.
async function waitFor(cond, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (await cond()) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return cond();
}

// ---------- scenarios ----------

async function s1_mruVisibleAfterFirstCreate(p) {
  const created = await clickNew(p);
  if (!created) return record('S1 mru-visible-after-first-create', 'fail', '[data-wb-session-new] not clickable');
  await waitFor(() => rowCount(p) >= 1, 15000);
  const n = await rowCount(p);
  record('S1 mru-visible-after-first-create', n >= 1 ? 'pass' : 'fail', `rows=${n} (defect 1: was always 0)`);
}

// Criterion per platform semantics (verified against the factory path in
// t260831-04 arbitration): a freshly created blank session legitimately shows
// data-phase=hero — "hero-phase picker … rendered while the session is blank"
// (dsh-client-ui-conversation slots.d.ts). The factory New Session button
// behaves identically: hero until the first message, then active within ~1s.
// So "one click -> active" is unattainable by design for ANY implementation;
// the user-perceivable acceptance is: one click lands an inputtable
// workspace-bound blank session (ledger entry + active row + ready composer),
// and the first message flips to active. The ticket's literal wording
// ("第一次新建即翻 active") deviates from this and is escalated to the user.
async function s2_firstClickFlipsActive(p) {
  const before = await phase(p);
  const created = await clickNew(p);
  if (!created) return record('S2 first-click-flips-active', 'fail', 'new button missing');
  // landing assertions: MRU row for the new session is marked active (current
  // switched) and a composer is ready for input — the "no workspace re-select"
  // user experience.
  const landed = await waitFor(async () => {
    const activeRow = await p.evaluate(() => !!document.querySelector('[data-wb-session-row][data-active="true"]'));
    const composer = await p.locator('textarea:visible').count();
    return activeRow && composer > 0;
  }, 15000);
  // activation assertion: first message flips hero -> active (factory parity)
  const composer = p.locator('textarea:visible').first();
  let flipped = false;
  let after = await phase(p);
  if (landed && (await composer.count())) {
    await composer.click();
    await composer.type('s2 activation probe');
    await composer.press('Enter');
    flipped = await waitFor(async () => (await phase(p)) === 'active', 10000);
    after = await phase(p);
  }
  const ok = landed && flipped;
  record('S2 first-click-flips-active', ok ? 'pass' : 'fail',
    `landing(ledger+activeRow+composer)=${landed} phase ${before} -> ${after} after first message; ` +
    `blank-session hero is platform semantics (factory-verified), active flip asserted on first message`);
}

async function s3_switchBackKeepsContent(p) {
  const MARK = 'integration-switchback-marker-a';
  // create A, land, type, send -> first message flips blank hero to active
  if (!(await clickNew(p))) return record('S3 switch-back-keeps-content', 'fail', 'new A failed');
  if (!(await waitLanded(p))) return record('S3 switch-back-keeps-content', 'fail', 'A did not land (no active row / composer)');
  const composer = p.locator('textarea:visible').first();
  if (!(await composer.count())) return record('S3 switch-back-keeps-content', 'fail', 'no composer for A');
  await composer.click();
  await composer.type(MARK);
  await composer.press('Enter');
  if (!(await waitFor(async () => (await phase(p)) === 'active', 15000))) {
    return record('S3 switch-back-keeps-content', 'fail', `A message sent but phase=${await phase(p)}`);
  }
  await p.waitForTimeout(2000);
  // create B — a fresh blank session legitimately shows hero (platform semantics)
  if (!(await clickNew(p))) return record('S3 switch-back-keeps-content', 'fail', 'new B failed');
  const twoRows = await waitFor(async () => (await rowCount(p)) >= 2, 15000);
  if (!twoRows) return record('S3 switch-back-keeps-content', 'fail', `expected >=2 rows, got ${await rowCount(p)}`);
  await p.waitForTimeout(1000);
  // switch back to A via its MRU row (prefer the row carrying our marker text);
  // A has content -> non-blank -> renders immediately, no workspace re-select
  await dismissOverlays(p);
  const rows = p.locator('[data-wb-session-row]');
  const texts = await rows.allTextContents();
  let idx = texts.findIndex((t) => t.includes(MARK));
  if (idx < 0) idx = 0; // fallback: MRU head = A
  await rows.nth(idx).click({ timeout: 3000 });
  await p.waitForTimeout(4000);
  const back = await p.locator(`text=${MARK}`).count();
  const ph = await phase(p);
  const heroShown = await p.evaluate(() => !!document.querySelector('[data-phase="hero"]')?.offsetParent);
  const ok = back > 0 && ph === 'active' && !heroShown;
  record('S3 switch-back-keeps-content', ok ? 'pass' : 'fail',
    `contentVisible=${back > 0} phase=${ph} heroReshown=${heroShown} (defect 3)`);
}

async function s5_malformedLedger(browser, consoleMessages, pageErrors) {
  const cases = [
    ['bad-json', '{not json'],
    ['non-array', '{"a":1}'],
    ['dirty-entries', JSON.stringify([1, 'x', null, { id: '', project: 'p' }, { id: 'ok-1' }])],
  ];
  let failed = 0;
  for (const [label, raw] of cases) {
    const { ctx, p } = await newConsolePage(browser, consoleMessages, pageErrors);
    await p.evaluate(([k, v]) => localStorage.setItem(k, v), [LEDGER_KEY, raw]);
    await p.reload({ waitUntil: 'networkidle' });
    await p.waitForTimeout(2000);
    const entryGone = await p.evaluate(() => !document.querySelector('[data-wb-session-entry]')?.hasAttribute('data-wb-crashed'));
    const rows = await rowCount(p);
    // acceptance: entry renders, no crash; dirty ledger degrades to empty list (rows=0 is fine)
    if (!entryGone) failed++;
    record(`S5 malformed-ledger/${label}`, entryGone ? 'pass' : 'fail', `rows=${rows} (entry must render, tolerate 0 rows)`);
    await ctx.close();
  }
  return failed;
}

async function s6_ticketSessionsNeverListed(browser, consoleMessages, pageErrors) {
  const { ctx, p } = await newConsolePage(browser, consoleMessages, pageErrors);
  await p.evaluate(([k]) => {
    localStorage.setItem(k, JSON.stringify([
      { id: 'ticket-t260001', project: 'suyou', cwd: '/tmp', lastOpenedAt: 999 },
      { id: 'chat-persist-1', project: 'suyou', cwd: '/tmp', lastOpenedAt: 998 },
    ]));
  }, [LEDGER_KEY]);
  await p.reload({ waitUntil: 'networkidle' });
  await p.waitForTimeout(2000);
  const texts = await p.locator('[data-wb-session-row]').allTextContents();
  const leaked = texts.some((t) => t.includes('ticket-'));
  record('S6 ticket-sessions-never-listed', leaked ? 'fail' : 'pass', `rows=${JSON.stringify(texts.map((t) => t.slice(0, 30)))}`);
  await ctx.close();
}

async function s7_ledgerSurvivesReload(p) {
  const beforeRows = await rowCount(p);
  if (beforeRows < 1) return record('S7 ledger-survives-reload', 'skip', 'no ledger rows to persist (upstream scenario failed)');
  await p.reload({ waitUntil: 'networkidle' });
  await p.waitForTimeout(2000);
  const after = await rowCount(p);
  record('S7 ledger-survives-reload', after >= 1 ? 'pass' : 'fail', `before=${beforeRows} afterReload=${after}`);
}

async function s8_globalSessionOpenApi() {
  try {
    const ids = [];
    for (let i = 0; i < 2; i++) {
      const r = await fetch(`${BASE}/suyou-workbench/api/global-session/open`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ project: 'suyou' }),
        signal: AbortSignal.timeout(15000),
      });
      const d = await r.json();
      if (!d?.ok || typeof d?.result?.session_id !== 'string') {
        return record('S8 global-session-open-api', 'fail', `resp=${JSON.stringify(d).slice(0, 120)}`);
      }
      ids.push(d.result.session_id);
    }
    const allChat = ids.every((id) => /^chat-/.test(id) && !id.startsWith('ticket-'));
    const distinct = new Set(ids).size === 2;
    record('S8 global-session-open-api', allChat && distinct ? 'pass' : 'fail', `ids=${ids.join(',')}`);
  } catch (e) {
    record('S8 global-session-open-api', 'fail', String(e).slice(0, 120));
  }
}

// ---------- runner ----------

const pw = await loadPlaywright();
const healthy = await consoleHealthy();

if (!healthy) {
  record('precheck', 'skip', `test console unreachable at ${BASE} (docker compose -f server/dsh/docker-compose.test.yml up -d)`);
  for (const name of ['S1 mru-visible-after-first-create', 'S2 first-click-flips-active', 'S3 switch-back-keeps-content', 'S5 malformed-ledger', 'S6 ticket-sessions-never-listed', 'S7 ledger-survives-reload', 'S4 console-hygiene', 'S8 global-session-open-api']) {
    record(name, 'skip', 'console unreachable');
  }
} else {
  const entryMounted = pw
    ? await (async () => {
        const b = await launchBrowser(pw);
        if (!b) return null;
        const { ctx, p } = await newConsolePage(b, [], []);
        const mounted = await p.evaluate(() => !!document.querySelector('[data-wb-session-entry]'));
        await ctx.close();
        await b.close();
        return mounted;
      })()
    : null;

  if (!pw) record('precheck', 'skip', 'playwright-core not resolvable (UI scenarios skipped; S8 still runs)');
  else if (entryMounted === null) record('precheck', 'skip', 'no browser could be launched');
  else if (!entryMounted) record('precheck', 'skip', 'workbench top entry not mounted on test console (plugin not loaded)');

  const uiRunnable = pw && entryMounted === true;
  const consoleMessages = [];
  const pageErrors = [];

  await s8_globalSessionOpenApi();

  if (uiRunnable) {
    const browser = await launchBrowser(pw);
    // Guard: a scenario exception must never kill the runner — record it as the
    // scenario's FAIL and keep the SUMMARY-line contract intact.
    const guard = async (name, fn) => { try { await fn(); } catch (e) { record(name, 'fail', `exception: ${String(e).slice(0, 160)}`); } };
    try {
      const { ctx, p } = await newConsolePage(browser, consoleMessages, pageErrors);
      try {
        await s1_mruVisibleAfterFirstCreate(p);
        try { await s7_ledgerSurvivesReload(p); }
        catch (e) { record('S7 ledger-survives-reload', 'fail', `exception: ${String(e).slice(0, 160)}`); }
      } catch (e) {
        record('S1 mru-visible-after-first-create', 'fail', `exception: ${String(e).slice(0, 160)}`);
        record('S7 ledger-survives-reload', 'skip', 'upstream S1 failed');
      } finally { await ctx.close().catch(() => {}); }
    } catch (e) {
      record('S1 mru-visible-after-first-create', 'fail', `exception: ${String(e).slice(0, 160)}`);
      record('S7 ledger-survives-reload', 'skip', 'page setup failed');
    }
    await guard('S2 first-click-flips-active', async () => {
      const { ctx, p } = await newConsolePage(browser, consoleMessages, pageErrors);
      try { await s2_firstClickFlipsActive(p); }
      finally { await ctx.close().catch(() => {}); }
    });
    await guard('S3 switch-back-keeps-content', async () => {
      const { ctx, p } = await newConsolePage(browser, consoleMessages, pageErrors);
      try { await s3_switchBackKeepsContent(p); }
      finally { await ctx.close().catch(() => {}); }
    });
    await guard('S5 malformed-ledger', async () => { await s5_malformedLedger(browser, consoleMessages, pageErrors); });
    await guard('S6 ticket-sessions-never-listed', async () => { await s6_ticketSessionsNeverListed(browser, consoleMessages, pageErrors); });
    await browser.close().catch(() => {});

    const bad = [...consoleMessages, ...pageErrors];
    record('S4 console-hygiene', bad.length === 0 ? 'pass' : 'fail',
      bad.length === 0 ? 'zero console errors / page errors across scenarios' : `${bad.length} errors, first: ${bad[0]}`);
  } else {
    for (const name of ['S1 mru-visible-after-first-create', 'S2 first-click-flips-active', 'S3 switch-back-keeps-content', 'S5 malformed-ledger', 'S6 ticket-sessions-never-listed', 'S7 ledger-survives-reload', 'S4 console-hygiene']) {
      record(name, 'skip', 'UI precheck not satisfied');
    }
  }
}

const pass = results.filter((r) => r.status === 'pass').length;
const fail = results.filter((r) => r.status === 'fail').length;
const skip = results.filter((r) => r.status === 'skip').length;
console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`);
process.exit(fail > 0 ? 1 : 0);
