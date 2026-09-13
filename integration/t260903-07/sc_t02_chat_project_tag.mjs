import { ensureStageConsole } from '../lib_stage_console.mjs';
// playwright-core 依赖解析唯一真源（t260912-01 缺陷③：位置无关四路口径）。
import { loadPlaywright, pwMissingDetail } from '../lib_pw_deps.mjs';
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
// SANDBAR_TEST_CONSOLE (default: lib_stage_console 共享台); hard guard: never 3099.

const BASE = (await ensureStageConsole()).base;
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
  console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)');
  process.exit(1);
}

async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

async function fixture() {
  const pr = await (await fetch(`${BASE}/sandbar-workbench/api/wf/projects`)).json();
  const projects = pr?.result?.projects ?? [];
  const withTickets = [];
  for (const p of projects) {
    try {
      const tr = await (await fetch(`${BASE}/sandbar-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`)).json();
      const list = tr?.result?.tickets ?? [];
      if (list.length > 0) withTickets.push({ key: p.key, ticket: list[0] });
    } catch { /* next */ }
  }
  return withTickets;
}

// 在平台 user 行（data-chat-anchor-key + flow-kind=user，chat-project-tag.ts 公开
// 锚）里找含 marker 的行，直读其 data-wb-projtag 属性与 ::before 渲染色。
// 注意必须是真函数不能是字符串（playwright 把字符串当表达式求值——返回函数
// 本体不可序列化=undefined，chipsFor 拿到 undefined 必炸；260908 实锤）。
// 不用「文本最深元素向上爬 N 层」旧探法：平台 markdown 渲染嵌套可深至 15 层，
// 8 层爬升必扑空（260908 实锤）。
const CHIP_PROBE = (marker) => {
  const rows = [...document.querySelectorAll('[data-chat-anchor-key][data-chat-flow-kind="user"]')];
  const out = [];
  for (const row of rows) {
    if (!(row.textContent || '').includes(marker)) continue;
    const pt = row.getAttribute('data-wb-projtag');
    if (pt) out.push({ text: pt, color: getComputedStyle(row, '::before').color });
  }
  return out;
};

async function browserScenarios(fixtureProjects) {
  // t260912-01：四路探测单源（lib_pw_deps），布局无关；失败文案只报事实不归因环境。
  const pw = await loadPlaywright();
  if (!pw) { record('browser/deps', 'env_fail', pwMissingDetail()); return; }
  let browser, context, page;
  try {
    browser = await pw.chromium.launch({ channel: 'chrome', headless: true }).catch(() => pw.chromium.launch({ headless: true }));
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // 出厂 notice（Continue 遮罩）会拦截新会话按钮点击——先关再断言（lib_browser 同款）。
    try {
      const nb = page.locator('button', { hasText: /continue|继续/i }).first();
      await nb.click({ timeout: 4000 });
      await nb.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    } catch { /* 无 notice=常态 */ }
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
    // 新会话按钮的到场等 20s：冷启动台（profile 首备/插件首载）侧栏行会上得慢，
    // 立即 count 必扑空（260908 重建台实锤）；到点仍无=真缺供，归 env_fail。
    const newBtn = page.locator('[data-wb-psess-new]').first();
    let btnUp = false;
    {
      const t0 = Date.now();
      while (Date.now() - t0 < 20000) {
        if (await newBtn.count()) { btnUp = true; break; }
        await page.waitForTimeout(500);
      }
    }
    if (!btnUp) throw new Error('new-session button missing');
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

  async function pollChips(marker, timeout = 30000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      const chips = await chipsFor(marker);
      if (chips.length > 0) return chips;
      await page.waitForTimeout(500);
    }
    return [];
  }

  // 前置探针（报错必须精确，260911 仲裁实证）：chip 缺席有两种**诊断方向相反**的成因——
  //   ①marker 文本全页缺席＝消息未上屏/会话未恢复（环境面优先，与 t4 的 env 口径一致）；
  //   ②marker 行在场但无 chip＝渲染/着色面（产品面）。
  // 红那轮原文只写「marker 行上未找到 chip；探得=[]」，两者混说，把环境面引向产品方向
  // （闸因此判 2 条产品红并拦）。此处**只加证据不改判定**：行在场仍 FAIL，断言不弱化。
  async function rowProbe(marker) {
    return page.evaluate((m) => {
      const body = document.body ? (document.body.textContent || '') : '';
      return { markerOnPage: body.includes(m) };
    }, marker).catch(() => ({ markerOnPage: null }));
  }

  function rowProbeText(p) {
    if (p.markerOnPage === null) return '前置探针不可得（页面求值失败）';
    return p.markerOnPage
      ? '前置探针：marker 文本在场（行在场→查 chip 渲染/着色=产品面）'
      : '前置探针：marker 文本全页缺席（消息未上屏/会话未恢复→环境面优先，与 t4 同口径）';
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
      const probe = await rowProbe(markerA);
      record('t1/tag-renders', 'fail',
        `marker 行上未找到文本=「${tag0.key}」的 chip；探得=${JSON.stringify(chips).slice(0, 200)}；${rowProbeText(probe)}`);
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
      } else {
        const probe2 = await rowProbe(markerA2);
        record('t2/same-key-same-color', 'fail', `chip 探得=${JSON.stringify(chips).slice(0, 160)}；${rowProbeText(probe2)}`);
      }
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
      } else {
        const probeB = await rowProbe(markerB);
        record('t3/different-key-different-color', 'fail', `chip 探得=${JSON.stringify(chips).slice(0, 160)}；${rowProbeText(probeB)}`);
      }
    } else record('t3/different-key-different-color', 'env_fail', 'send failed (env)');
  } else {
    record('t3/different-key-different-color', 'env_fail', 'fixture has <2 projects with tickets');
  }

  // T4 重载确定性：重载后同项目 chip 颜色不变（会话/消息随账册恢复时才有断言面）。
  // 轮询 ≤30s：chip 依赖 tag 索引（侧栏 10s 轮询/装饰器兜底自取重灌），重载后
  // 固定 3s  sleep 在慢台上必扑空（260908 实锤：索引未回灌时 chips=[]）。
  await page.reload({ waitUntil: 'domcontentloaded' });
  let hit4 = null;
  for (let i = 0; i < 40 && !hit4; i++) {
    await page.waitForTimeout(750);
    const chips = await chipsFor(markerA);
    hit4 = chips.find(c => c.text === tag0.key) ?? null;
  }
  {
    if (hit4 && colorA) {
      record('t4/reload-determinism', hit4.color === colorA ? 'pass' : 'fail',
        hit4.color === colorA ? `stable after reload ${colorA}` : `${colorA} → ${hit4.color}`);
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
