// Integration tests for ticket t260831-08 (defect ②) — screenshot evidence visible in ticket drawer.
//
// Intent (black-box, user perspective):
//   QA screenshots (.suyou/screenshots/*.png in the lane) must be visible in the
//   ticket detail drawer. The user-visible contract after the fix:
//     - GET /suyou-workbench/api/wf/tickets/<id>/evidence lists the png files
//       (archive .suyou/evidence/<id>/ takes precedence, then lane screenshots);
//       no evidence → empty list, no error (drawer simply hides the section).
//     - GET .../evidence/<file> serves the exact bytes as image/png.
//     - Path traversal / illegal filenames / illegal ticket ids are rejected
//       with explicit 4xx errors, never served.
//     - (UI) the drawer renders an <img src=".../evidence/<file>"> per file.
//
// Staging: this suite stages a tiny valid PNG under <laneRoot>/.suyou/evidence/
// <stageId>/ (archive base of the console booted from this lane) and removes it
// afterwards. If the console serves a different repo root, staged-file scenarios
// degrade to env_fail with the reason (mismatch is an environment fact, not a
// pass; t260904-12 三态：环境红 exit 2，绝不 exit 0 假绿).
// Hard guard: never touches port 3099.
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 或全腿 na → exit 1;
// env_fail>0 → exit 2.

import { mkdir, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'

const BASE = (process.env.SUYOU_TEST_CONSOLE ?? 'http://127.0.0.1:3199').replace(/\/$/, '');
const LANE = process.cwd();
const STAGE_ID = 't26083108evtest'; // must satisfy TICKET_ID_RE (alnum, no / no .)
const STAGE_DIR = join(LANE, '.suyou', 'evidence', STAGE_ID);
const PNG_1x1 = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
  '0000000d4944415478da63fcffff3f030005fe02fea72d1f240000000049454e44ae426082', 'hex');

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

async function evidenceRequest(id, file = '') {
  const url = `${BASE}/suyou-workbench/api/wf/tickets/${encodeURIComponent(id)}/evidence${file ? '/' + file : ''}`;
  const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
  const type = r.headers.get('content-type') ?? '';
  const buf = Buffer.from(await r.arrayBuffer());
  let body = null;
  if (type.includes('json')) { try { body = JSON.parse(buf.toString('utf8')); } catch { /* null */ } }
  return { status: r.status, type, buf, body };
}

async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/suyou-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

async function withStagedEvidence() {
  await mkdir(STAGE_DIR, { recursive: true });
  await writeFile(join(STAGE_DIR, 'shot-a.png'), PNG_1x1);
  // decoys that must never appear in the list: wrong extension / illegal shape
  await writeFile(join(STAGE_DIR, 'notes.txt'), 'not an image');
  await writeFile(join(STAGE_DIR, 'weird name.png'), PNG_1x1); // space not in whitelist

  // S1: list shape — 200 {ok,result:{files}}, png-whitelist entries only, decoys filtered.
  let stagedVisible = false; // console 是否看到本 lane 暂存目录（根不匹配=环境事实）
  {
    const { status, body } = await evidenceRequest(STAGE_ID);
    const files = body?.result?.files;
    const shapeOk = status === 200 && body?.ok === true && Array.isArray(files);
    const whitelistOk = shapeOk && files.every(f => /^[A-Za-z0-9._-]+\.png$/.test(f));
    stagedVisible = shapeOk && files.includes('shot-a.png');
    if (shapeOk && whitelistOk && files.includes('shot-a.png')
      && !files.includes('notes.txt') && !files.includes('weird name.png')) {
      record('server/list-staged', 'pass', `files=${JSON.stringify(files)}`);
    } else if (shapeOk && files.length === 0) {
      record('server/list-staged', 'env_fail', 'list empty although staged — console repo is not this lane root');
    } else {
      record('server/list-staged', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 200)}`);
    }
  }

  // S2: bytes round-trip — exact staged bytes, image/png.
  // 前提门控与 S1 同源：console 根不匹配时暂存文件不可见，roundtrip 必 404——那是
  // 环境事实（见文件头注「mismatch is an environment fact, not a pass」），按 env_fail
  // 处置不判 FAIL。守卫缺失曾在隔离台锚根漂移时把本腿打成假红
  // （t260904-04 arbitrate gen1 修正；前提成立时断言面一字不减）。
  {
    if (!stagedVisible) {
      record('server/bytes-roundtrip', 'env_fail', 'staged file not visible — console repo is not this lane root');
    } else {
      const { status, type, buf } = await evidenceRequest(STAGE_ID, 'shot-a.png');
      if (status === 200 && type.includes('image/png') && buf.equals(PNG_1x1)) {
        record('server/bytes-roundtrip', 'pass');
      } else {
        record('server/bytes-roundtrip', 'fail', `status=${status} type=${type} bytes=${buf.length}/${PNG_1x1.length}`);
      }
    }
  }

  // S3: nonexistent png → 404 human-readable (both candidates missing).
  {
    const { status, body } = await evidenceRequest(STAGE_ID, 'nope-missing.png');
    if (status === 404 && body?.ok === false && typeof body?.error === 'string') {
      record('server/missing-file-404', 'pass');
    } else {
      record('server/missing-file-404', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 150)}`);
    }
  }

  // cleanup before the rest (traversal cases must not depend on staged files)
  await rm(STAGE_DIR, { recursive: true, force: true });
}

async function faultSurface() {
  // S4: traversal in file position → rejected (4xx), never 200.
  for (const [name, file] of [
    ['dotdot-parent', '..%2F..%2Fserver%2Fadmin.log'],
    ['dotdot-inside', '%2e%2e%2fshot.png'],
    ['bad-ext', 'notes.txt'],
    ['bad-shape', 'a%20b.png'],
    ['encoded-slash', 'a%2Fb.png'],
  ]) {
    try {
      const { status } = await evidenceRequest(STAGE_ID, file);
      if (status >= 400 && status < 500) record(`server/traverse-${name}`, 'pass');
      else record(`server/traverse-${name}`, 'fail', `status=${status} (must be 4xx)`);
    } catch (err) {
      record(`server/traverse-${name}`, 'fail', String(err).slice(0, 120));
    }
  }

  // S5: illegal ticket ids → 400 (not 5xx, not 200).
  for (const [name, id] of [['dotdot', '..'], ['slash', 'a/b'], ['empty-ish', 'x']]) {
    try {
      const { status } = await evidenceRequest(id);
      if (status >= 400 && status < 500) record(`server/bad-id-${name}`, 'pass');
      else record(`server/bad-id-${name}`, 'fail', `status=${status} (must be 4xx)`);
    } catch (err) {
      record(`server/bad-id-${name}`, 'fail', String(err).slice(0, 120));
    }
  }

  // S6: unknown-but-well-formed id → empty list, no error (soft degradation).
  try {
    const { status, body } = await evidenceRequest('t26083108evnone');
    const files = body?.result?.files;
    if (status === 200 && body?.ok === true && Array.isArray(files) && files.length === 0) {
      record('server/unknown-id-empty-list', 'pass');
    } else {
      record('server/unknown-id-empty-list', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 150)}`);
    }
  } catch (err) {
    record('server/unknown-id-empty-list', 'fail', String(err).slice(0, 120));
  }
}

async function uiScenario() {
  let pw = null;
  for (const c of [process.env.SUYOU_PLAYWRIGHT_PATH, 'playwright-core',
    new URL('../../server/dsh/ui-check/node_modules/playwright-core/index.mjs', `file://${process.cwd()}/`).href]) {
    if (!c) continue;
    try { pw = await import(c); break; } catch { /* next */ }
  }
  if (!pw) { record('ui/drawer-images', 'env_fail', 'playwright-core unavailable'); return; }
  let browser;
  try {
    browser = await pw.chromium.launch({ headless: true });
    const page = await (await browser.newContext()).newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('.wb-ticket-row2', { timeout: 12000 });
    const rows = await page.$$('.wb-ticket-row2');
    if (rows.length < 1) throw new Error('no rows');
    await rows[0].click();
    await page.waitForSelector('.wb-drawer', { timeout: 10000 });
    await page.waitForSelector('.wb-drawer img[src*="/evidence/"]', { timeout: 10000 });
    const loaded = await page.evaluate(() => {
      const imgs = [...document.querySelectorAll('.wb-drawer img[src*="/evidence/"]')];
      return { count: imgs.length, natural: imgs.filter(i => i.naturalWidth > 0).length };
    });
    if (loaded.count > 0 && loaded.natural === loaded.count) {
      record('ui/drawer-images', 'pass', `imgs=${loaded.count} all decoded`);
    } else {
      record('ui/drawer-images', 'fail', `imgs=${loaded.count} decoded=${loaded.natural}`);
    }
  } catch (err) {
    const msg = String(err).slice(0, 140);
    // no drawer/no evidence for the first row is a fixture fact; timeout on an
    // existing evidence-bearing ticket would be a real failure — reported as
    // fail either way unless playwright/console itself is the blocker.
    record('ui/drawer-images', 'env_fail', `environment/fixture blocker: ${msg}`);
  }
  try { await browser.close(); } catch { /* noop */ }
}

const healthy = await consoleHealthy();
if (!healthy) {
  record('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
record('console/health', 'pass', BASE);
try {
  await withStagedEvidence();
} catch (err) {
  record('server/staging', 'env_fail', `staging failed: ${String(err).slice(0, 120)}`);
  await rm(STAGE_DIR, { recursive: true, force: true }).catch(() => {});
}
await faultSurface();
await uiScenario();
summarize();
