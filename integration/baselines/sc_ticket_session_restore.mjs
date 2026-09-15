import { ensureStageConsole } from '../lib_stage_console.mjs';
// playwright-core 依赖解析唯一真源（t260912-01 缺陷③：位置无关四路口径）。
import { loadPlaywright, pwMissingDetail } from '../lib_pw_deps.mjs';
// Integration tests for the ticket-session surface (t260831-08 origin;
// browser half reversed by t260903-07 — chat slimmed down to a single global
// session).
//
// Intent (black-box, user perspective):
//   Server layer (the route is kept by t260903-07 as a rollback surface; the
//   client has no callers left):
//     POST /api/ticket-session/open keeps the find-or-create contract —
//     session id `ticket-<id>`, created flag present, reopen → created:false
//     (one ticket, one session); malformed ticket_id / missing or unknown
//     project / nonexistent ticket fail with explicit 4xx human-readable
//     errors.
//   Browser layer (t260903-07 reversed the contract; the old assertions now
//   point the other way):
//     clicking a ticket row opens the middle detail drawer and must NOT open or
//     switch the right chat — zero 【工单上下文】 snapshot injection, data-phase
//     unchanged, repeated clicks across rows stay zero-injection.
//
// Server-layer scenarios talk HTTP to the ISOLATED test console
// (SANDBAR_TEST_CONSOLE, default 127.0.0.1:3199; hard guard: never 3099).
// Browser-layer scenarios use playwright-core against the same console and
// record env_fail (exit 2) when it is unavailable (see integration/README.md
// provisioning; t260904-12 three-state contract: a missing environment never
// exits 0 with a fake green).
//
// Execution contract (t260904-12 three-state): stdout's last line is
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; missing deps → env_fail
// (exit 2); FAIL>0 or every leg na → exit 1.

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

// ---------- server layer ----------
// t260903-07: the route is kept as a rollback surface (the client has no
// callers left); the server-side contract below still holds.

async function firstTicket() {
  const pr = await (await fetch(`${BASE}/sandbar-workbench/api/wf/projects`)).json();
  const projects = pr?.result?.projects ?? [];
  for (const p of projects) {
    try {
      const tr = await (await fetch(`${BASE}/sandbar-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`)).json();
      const list = tr?.result?.tickets ?? [];
      if (list.length > 0) return { project: p.key, ticket: list[0] };
    } catch { /* next project */ }
  }
  return null;
}

async function openSession(ticketId, project) {
  const r = await fetch(`${BASE}/sandbar-workbench/api/ticket-session/open`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(ticketId === undefined ? { project } : { ticket_id: ticketId, project }),
    signal: AbortSignal.timeout(8000),
  });
  let body = null;
  try { body = await r.json(); } catch { /* leave null */ }
  return { status: r.status, body };
}

async function serverScenarios() {
  const found = await firstTicket();
  if (!found) {
    record('server/fixture-ticket', 'env_fail', 'test console has no tickets; seed one in the test env to enable coverage');
    return;
  }
  const { project, ticket } = found;
  const tid = ticket.id;

  // S1: open → deterministic session id ticket-<id>, created flag present.
  {
    const { status, body } = await openSession(tid, project);
    const sid = body?.result?.session_id;
    if (status === 200 && body?.ok && sid === `ticket-${tid}` && typeof body?.result?.created === 'boolean') {
      record('server/open-shape', 'pass', `session_id=${sid} created=${body.result.created}`);
    } else {
      record('server/open-shape', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 200)}`);
    }
  }

  // S2: reopen → same session id, created:false (no duplicate session per ticket).
  {
    const { status, body } = await openSession(tid, project);
    const sid = body?.result?.session_id;
    if (status === 200 && sid === `ticket-${tid}` && body?.result?.created === false) {
      record('server/reopen-no-duplicate', 'pass');
    } else {
      record('server/reopen-no-duplicate', 'fail', `status=${status} created=${body?.result?.created} sid=${sid}`);
    }
  }

  // S3: malformed ticket_id → 400 with human-readable error (no silent 200).
  {
    const { status, body } = await openSession('../etc/passwd', project);
    if (status === 400 && body?.ok === false && typeof body?.error === 'string' && body.error.length > 0) {
      record('server/malformed-ticket-id', 'pass');
    } else {
      record('server/malformed-ticket-id', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 200)}`);
    }
  }

  // S4: missing project → 400 (multi-project contract: no default).
  {
    const { status, body } = await openSession(undefined, undefined);
    if (status === 400 && body?.ok === false) record('server/missing-project', 'pass');
    else record('server/missing-project', 'fail', `status=${status}`);
  }

  // S5: unknown project → 400 naming the registry miss.
  {
    const { status } = await openSession(tid, 'no-such-project-zzz');
    if (status === 400) record('server/unknown-project', 'pass');
    else record('server/unknown-project', 'fail', `status=${status}`);
  }

  // S6: well-formed but nonexistent ticket → 404 (no orphan session created).
  {
    const { status, body } = await openSession('t9999999999nope', project);
    if (status === 404 && body?.ok === false) record('server/nonexistent-ticket-404', 'pass');
    else record('server/nonexistent-ticket-404', 'fail', `status=${status}`);
  }
}

// ---------- browser layer ----------

async function browserScenarios() {
  // t260912-01：四路探测单源（lib_pw_deps），布局无关；失败文案只报事实不归因环境。
  const pw = await loadPlaywright();
  if (!pw) { record('browser/deps', 'env_fail', pwMissingDetail()); return; }
  let browser, context, page;
  try {
    browser = await pw.chromium.launch({ channel: 'chrome', headless: true }).catch(() => pw.chromium.launch({ headless: true }));
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // The factory notice (the Continue overlay) blocks ticket-row clicks —
    // dismiss it before asserting (same as lib_browser).
    try {
      const nb = page.locator('button', { hasText: /continue|继续/i }).first();
      await nb.click({ timeout: 4000 });
      await nb.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    } catch { /* no notice = the normal case */ }
  } catch (err) {
    record('browser/deps', 'env_fail', `console/browser unreachable: ${String(err).slice(0, 120)}`);
    try { await browser?.close(); } catch { /* noop */ }
    return;
  }
  const consoleErrors = [];
  const badResponses = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push(String(e)));
  // URL 感知卫生面（260910 gen1 仲裁）：console error 文本只有状态码没有 URL，
  // 另收响应面才能按端点点名豁免（一次性夹具幽灵行的 agent-usage 400，见尾部注）。
  page.on('response', r => { if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`); });

  try {
    // rows render at all (sidebar polls every 10s)
    await page.waitForSelector('.wb-card[data-ticket-id]', { timeout: 12000 });
  } catch {
    record('browser/fixture-ticket-row', 'env_fail', 'no ticket row rendered in test console sidebar');
    try { await browser.close(); } catch { /* noop */ }
    return;
  }

  // 260909 提速战役③终验 run D 误红复盘：data-phase 属出厂 ConversationRoot
  // （宿主面，非本仓代码）。服务端半 S1 开好全局 ticket 会话后，宿主的会话
  // 激活是页外异步——负载下可落在本腿原 12s 观察窗内（hero→active 与点击
  // 无关：现行 onOpen=纯导航 openDetail，不可能切会话；snapshots 0→0 亦自证
  // 零注入）。基线纪律：点击前先等根相位到达稳态（每秒复读、连续两次一致，
  // 最多 20s——链池杆有 engine 约 280s 封顶，最坏 +20s 零墙钟代价），只对
  // 稳态基线断言「点击零切换」。稳态若是 active（宿主已如实展示既有会话），
  // 相位腿的判别力让位给快照零注入腿——共享全局根的结构性边界，detail 如实记。
  const readPhase = () => page.evaluate(
    () => document.querySelector('[data-phase]')?.getAttribute('data-phase') ?? '');
  let phaseStable = await readPhase();
  {
    let last = phaseStable;
    for (let i = 0; i < 20; i++) {
      await page.waitForTimeout(1000);
      const cur = await readPhase();
      if (cur === last) { phaseStable = cur; break; }
      last = cur;
      phaseStable = cur;
    }
  }

  const contextMsgCount = () => page.evaluate(
    () => document.body.innerText.split('【工单上下文】').length - 1,
  );

  // S7 (reversed contract, t260903-07): click row A → middle detail opens, right chat
  // context untouched (no snapshot injection, phase unchanged).
  const rows = await page.$$('.wb-card[data-ticket-id]');
  if (rows.length < 1) {
    record('browser/click-no-session-open', 'env_fail', 'need >=1 ticket row');
  } else {
    try {
      const beforeSnapshots = await contextMsgCount();
      const phaseBefore = phaseStable;
      await rows[0].click();
      // t260915-05：拓扑在场=真泳道图（.wb-lanemap）替代步骤条——「详情开了」锚渲染器族。
      await page.waitForSelector('.wb-lanemap, .wb-d2-steps', { timeout: 8000 }); // middle detail opens as usual
      await page.waitForTimeout(4000); // the old path refresh→waitForListed→open→inject takes seconds; give it a full observation window
      const afterSnapshots = await contextMsgCount();
      const phaseAfter = await readPhase();
      if (afterSnapshots === beforeSnapshots && phaseAfter === phaseBefore) {
        record('browser/click-no-session-open', 'pass', `snapshots=${afterSnapshots} phase=${phaseAfter || '(none)'} 不变`);
      } else {
        record('browser/click-no-session-open', 'fail',
          `snapshots ${beforeSnapshots}→${afterSnapshots} phase ${phaseBefore || '(none)'}→${phaseAfter || '(none)'}（点工单仍在切会话？）`);
      }
    } catch (err) {
      record('browser/click-no-session-open', 'fail', String(err).slice(0, 140));
    }
  }

  // S8 (t260903-07): repeated clicks across rows — still zero injection (no churn).
  if (rows.length >= 2) {
    try {
      const before = await contextMsgCount();
      await page.evaluate(() => { const el = document.querySelectorAll('.wb-card[data-ticket-id]')[1]; el && el.click(); });
      await page.waitForTimeout(3000);
      await page.evaluate(() => { const el = document.querySelectorAll('.wb-card[data-ticket-id]')[0]; el && el.click(); });
      await page.waitForTimeout(4000);
      const after = await contextMsgCount();
      if (after === before) record('browser/repeat-click-zero-injection', 'pass', `snapshot count stable=${after}`);
      else record('browser/repeat-click-zero-injection', 'fail', `snapshot count ${before}→${after}`);
    } catch (err) {
      record('browser/repeat-click-zero-injection', 'fail', String(err).slice(0, 140));
    }
  } else {
    record('browser/repeat-click-zero-injection', 'env_fail', 'need >=2 ticket rows');
  }

  // S9: console hygiene across all UI scenarios.
  // console-hygiene（260910 gen1 仲裁实锤升级为 URL 感知）：一次性夹具的幽灵行
  // （早轮场景 terminate 掉的票，worktree 指向已删 tmp 目录）会让 agent-usage 端点
  // 被路径守卫按设计拒读（400「工单 worktree 越界（拒绝读取）」——护栏行为本身正确，
  // 生产面行 worktree 在项目根内不会触发）。只豁免这一点名端点的 400；其余任何
  // >=400 响应或 pageerror 照旧红。
  const GHOST = /\/api\/wf\/tickets\/[^/?]+\/agent-usage\?/;
  const stray = badResponses.filter((u) => !GHOST.test(u));
  const other = consoleErrors.filter((t) => !/Failed to load resource/.test(t));
  if (stray.length === 0 && other.length === 0) record('browser/console-hygiene', 'pass');
  else record('browser/console-hygiene', 'fail', [...stray, ...other].slice(0, 3).join(' | ').slice(0, 300));

  try { await browser.close(); } catch { /* noop */ }
}

const healthy = await consoleHealthy();
if (!healthy) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);
await serverScenarios();
await browserScenarios();
summarize();
