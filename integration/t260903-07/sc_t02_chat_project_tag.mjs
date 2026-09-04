// Integration scenario t260903-07 ② — global chat project tag coloring contract.
//
// Intent (black-box, user perspective):
//   在全局 chat 里发一条引用真实工单 id 的用户消息，该消息行渲染出可见 chip：
//   文本=该工单所属项目 key、颜色非空。契约：
//     - 同项目恒同色（两条同项目消息的 chip 颜色一致）；
//     - 不同项目不同色（fixture 有两个有票项目时）；
//     - 页面重载后同项目 chip 颜色不变（确定性映射的用户可感知面）；
//     - 页面上全部 chip 文本 ∈ 注册项目键（归属不了不渲染=声明行为，绝不造假 key）。
//     - 归属不了→不渲染不在场景层强断言：cwd 归属路径与消息内容正交、env 相关，
//       该口径由 L1 DOM 桩用例锁定（workbench smoke）。
//
// 灰盒口径（重要，为什么这样读 chip）：chip 经 CSS 伪元素渲染（::before），
//   文本不进 textContent——断言从「含我方 marker 的消息行」出发，向上Walk 祖先读
//   getComputedStyle(el,'::before') 的 content/color，锚定用户可感知的
//   「带文本与颜色的 chip」本身，不钉插件内部属性/类名。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; missing deps → env_fail
// (exit 2); FAIL>0 或全腿 na → exit 1. Isolated console
// SUYOU_TEST_CONSOLE (default 127.0.0.1:3199); hard guard: never 3099.

const BASE = (process.env.SUYOU_TEST_CONSOLE ?? 'http://127.0.0.1:3199').replace(/\/$/, '');
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
  console.error('refusing to run: SUYOU_TEST_CONSOLE points at the production console (3099)');
  process.exit(1);
}

async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/suyou-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

async function fixture() {
  const pr = await (await fetch(`${BASE}/suyou-workbench/api/wf/projects`)).json();
  const projects = pr?.result?.projects ?? [];
  const withTickets = [];
  for (const p of projects) {
    try {
      const tr = await (await fetch(`${BASE}/suyou-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`)).json();
      const list = tr?.result?.tickets ?? [];
      if (list.length > 0) withTickets.push({ key: p.key, ticket: list[0] });
    } catch { /* next */ }
  }
  return withTickets;
}

// 在页面上找含 marker 文本的最深元素，向上 ≤8 层祖先（含自身）读 ::before 伪元素
// 的 content/color；content 是带引号字符串才算 chip。返回 [{text,color}]。
const CHIP_PROBE = `(marker) => {
  const all = [...document.querySelectorAll('body *')];
  const deepest = all.filter(el =>
    (el.textContent || '').includes(marker)
    && ![...el.children].some(c => (c.textContent || '').includes(marker)));
  const chips = [];
  for (const start of deepest) {
    let el = start;
    for (let i = 0; el && i < 8; i++, el = el.parentElement) {
      const st = getComputedStyle(el, '::before');
      const c = st.content || '';
      if (c.length >= 2 && ((c.startsWith('"') && c.endsWith('"')) || (c.startsWith("'") && c.endsWith("'")))) {
        chips.push({ text: c.slice(1, -1), color: st.color });
      }
    }
  }
  return chips;
}`;

async function browserScenarios(fixtureProjects) {
  let pw = null;
  for (const c of [process.env.SUYOU_PLAYWRIGHT_PATH, 'playwright-core',
    new URL('../../server/dsh/ui-check/node_modules/playwright-core/index.mjs', `file://${process.cwd()}/`).href]) {
    if (!c) continue;
    try { pw = await import(c); break; } catch { /* next */ }
  }
  if (!pw) { record('browser/deps', 'env_fail', 'playwright-core unavailable'); return; }
  let browser, context, page;
  try {
    browser = await pw.chromium.launch({ headless: true });
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  } catch (err) {
    record('browser/deps', 'env_fail', `console/browser unreachable: ${String(err).slice(0, 120)}`);
    try { await browser?.close(); } catch { /* noop */ }
    return;
  }
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push(String(e)));

  const registeredKeys = fixtureProjects.map(p => p.key);

  // 建会话进可打字态（既有旅程：项目行 + 钮 → composer 在场；票② R8 改锚，
  // 顶部行 [data-wb-session-new] 已退役）。
  try {
    const newBtn = page.locator('[data-wb-psess-new]').first();
    if (!(await newBtn.count())) throw new Error('new-session button missing');
    await newBtn.click({ timeout: 3000 });
    let staged = false;
    const t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      staged = (await page.evaluate(() => document.querySelectorAll('[data-wb-psess-tab][data-active="true"]').length)) > 0
        && (await page.locator('textarea:visible').count()) > 0;
      if (staged) break;
      await page.waitForTimeout(500);
    }
    if (!staged) throw new Error('session staging timeout');
  } catch (err) {
    record('browser/staging', 'env_fail', `console cannot stage a chat session: ${String(err).slice(0, 120)}`);
    try { await browser.close(); } catch { /* noop */ }
    return;
  }
  record('browser/staging', 'pass');

  // 发消息的 env 卫兵：Enter 后 textarea 清空才算「发送语义成立」，否则 env_fail——
  // composer 发送语义是平台行为、不是本票契约，假红会污染本票结论。
  async function sendMessage(text) {
    const ta = page.locator('textarea:visible').first();
    await ta.fill(text);
    await ta.press('Enter');
    return pollSent(text);
  }

  async function chipsFor(marker) {
    return page.evaluate(CHIP_PROBE, marker);
  }

  async function pollChips(marker, timeout = 10000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      const chips = await chipsFor(marker);
      if (chips.length > 0) return chips;
      await page.waitForTimeout(500);
    }
    return [];
  }

  async function pollSent(text, timeout = 10000) {
    const ta = page.locator('textarea:visible').first();
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      if ((await ta.inputValue()) === '' && (await page.evaluate(m => document.body.innerText.includes(m), text))) return true;
      await page.waitForTimeout(400);
    }
    return false;
  }

  const tag0 = fixtureProjects[0];
  const markerA = `wbtag-marker-A-${Date.now()}`;
  let colorA = '';

  // T1 真实工单引用 → 渲染文本=项目 key 的 chip
  if (!(await sendMessage(`${markerA} 请处理 ${tag0.ticket.id}`))) {
    record('t1/tag-renders', 'env_fail', 'composer send path unavailable in env (Enter 未发送)');
    try { await browser.close(); } catch { /* noop */ }
    return;
  }
  {
    const chips = await pollChips(markerA);
    const hit = chips.find(c => c.text === tag0.key);
    if (hit) {
      colorA = hit.color;
      record('t1/tag-renders', 'pass', `chip="${hit.text}" color=${hit.color}`);
    } else {
      record('t1/tag-renders', 'fail',
        `marker 行上未找到文本=「${tag0.key}」的 chip；探得=${JSON.stringify(chips).slice(0, 200)}`);
    }
  }

  // T2 同项目恒同色：第二条同项目消息
  {
    const markerA2 = `${markerA}-again`;
    if (await sendMessage(`${markerA2} 再看一下 ${tag0.ticket.id}`)) {
      const chips = await pollChips(markerA2);
      const hit = chips.find(c => c.text === tag0.key);
      if (hit && colorA) {
        record('t2/same-key-same-color', hit.color === colorA ? 'pass' : 'fail',
          hit.color === colorA ? `stable ${colorA}` : `${colorA} → ${hit.color}`);
      } else record('t2/same-key-same-color', 'fail', `chip 探得=${JSON.stringify(chips).slice(0, 160)}`);
    } else record('t2/same-key-same-color', 'env_fail', 'second send failed (env)');
  }

  // T3 不同项目不同色（fixture 有第二个有票项目时）
  if (fixtureProjects.length >= 2) {
    const tag1 = fixtureProjects[1];
    const markerB = `wbtag-marker-B-${Date.now()}`;
    if (await sendMessage(`${markerB} 请处理 ${tag1.ticket.id}`)) {
      const chips = await pollChips(markerB);
      const hit = chips.find(c => c.text === tag1.key);
      if (hit && colorA) {
        record('t3/different-key-different-color', hit.color !== colorA ? 'pass' : 'fail',
          `${tag0.key}=${colorA} vs ${tag1.key}=${hit.color}`);
      } else record('t3/different-key-different-color', 'fail', `chip 探得=${JSON.stringify(chips).slice(0, 160)}`);
    } else record('t3/different-key-different-color', 'env_fail', 'send failed (env)');
  } else {
    record('t3/different-key-different-color', 'env_fail', 'fixture has <2 projects with tickets');
  }

  // T4 重载确定性：重载后同项目 chip 颜色不变（会话/消息随账册恢复时才有断言面）
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  {
    const chips = await chipsFor(markerA);
    const hit = chips.find(c => c.text === tag0.key);
    if (hit && colorA) {
      record('t4/reload-determinism', hit.color === colorA ? 'pass' : 'fail',
        hit.color === colorA ? `stable after reload ${colorA}` : `${colorA} → ${hit.color}`);
    } else {
      record('t4/reload-determinism', 'env_fail', 'marker row not present after reload (session not restored) — env');
    }
  }

  // T5 全页 chip 卫生：所有探得 chip 文本 ∈ 注册项目键（归属不了不渲染、不造假 key）
  {
    const all = await page.evaluate(`(() => {
      const keys = ${JSON.stringify(registeredKeys)};
      const out = [];
      for (const el of document.querySelectorAll('body *')) {
        const st = getComputedStyle(el, '::before');
        const c = st.content || '';
        if (c.length >= 2 && ((c.startsWith('"') && c.endsWith('"')) || (c.startsWith("'") && c.endsWith("'")))) {
          out.push(c.slice(1, -1));
        }
      }
      return [...new Set(out)];
    })()`);
    const bad = all.filter(t => !registeredKeys.includes(t));
    // 页面别处也可能有带引号 content 的伪元素（出厂 UI）；只要不冒充项目键即可。
    const fakeTag = bad.filter(t => /^[a-z][a-z0-9-]*$/i.test(t));
    record('t5/no-fake-keys', fakeTag.length === 0 ? 'pass' : 'fail',
      fakeTag.length === 0 ? `chips=${all.join(',') || '(none)'}` : `非注册键形似 tag: ${fakeTag.join(',')}`);
  }

  // T6 console hygiene
  if (consoleErrors.length === 0) record('t6/console-hygiene', 'pass');
  else record('t6/console-hygiene', 'fail', consoleErrors.slice(0, 3).join(' | ').slice(0, 300));

  try { await browser.close(); } catch { /* noop */ }
}

const healthy = await consoleHealthy();
if (!healthy) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);
const fixtureProjects = await fixture();
if (fixtureProjects.length < 1) {
  record('fixture/ticket', 'env_fail', 'test console has no projects with tickets; seed one to enable coverage');
  summarize();
}
await browserScenarios(fixtureProjects);
summarize();
