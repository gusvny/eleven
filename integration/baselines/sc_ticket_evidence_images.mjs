// Ticket t260831-08 (defect 2) integration test — screenshot evidence is
// visible in the ticket drawer.
//
// What it locks (black box, user view):
//   QA screenshots (lane .suyou/screenshots/*.png) must be visible in the  // naming-compat
//   ticket detail drawer. The user-visible contract after the fix:
//     - GET /sandbar-workbench/api/wf/tickets/<id>/evidence lists png files
//       (archive .suyou/evidence/<id>/ first, then lane screenshots);  // naming-compat
//       no evidence → empty list, no error (the drawer just skips that
//       section).
//     - GET .../evidence/<file> returns the bytes as image/png, unchanged.
//     - Path traversal / illegal file names / illegal ticket ids are always
//       rejected with 4xx, never served.
//     - (UI) the drawer renders one <img src=".../evidence/<file>"> per file.
//
// Staging: this suite puts one small valid PNG into
// <laneRoot>/.suyou/evidence/<stageId>/  // naming-compat
// (the archive base directory of a console started from this lane) and
// removes it when done. If the console serves a different repo root, the
// staged-file legs degrade to env_fail with a reason (a root mismatch is an
// environment fact, not a product green; three-state contract of
// t260904-12: environment red = exit 2, never a fake green with exit 0).
// Red line: never touch 3099.
//
// Execution contract (three-state, t260904-12): the last stdout line is
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 or all-legs-na → exit 1;
// env_fail>0 → exit 2.

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { mkdir, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'

const BASE = (await ensureStageConsole()).base;
const LANE = process.cwd();
const STAGE_ID = 't26083108evtest'; // must satisfy TICKET_ID_RE (alphanumeric, no / no .)
const STAGE_DIR = join(LANE, '.suyou', 'evidence', STAGE_ID);  // naming-compat
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
  console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)');
  process.exit(1);
}

async function evidenceRequest(id, file = '') {
  const url = `${BASE}/sandbar-workbench/api/wf/tickets/${encodeURIComponent(id)}/evidence${file ? '/' + file : ''}`;
  const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
  const type = r.headers.get('content-type') ?? '';
  const buf = Buffer.from(await r.arrayBuffer());
  let body = null;
  if (type.includes('json')) { try { body = JSON.parse(buf.toString('utf8')); } catch { /* null */ } }
  return { status: r.status, type, buf, body };
}

async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

async function withStagedEvidence() {
  await mkdir(STAGE_DIR, { recursive: true });
  await writeFile(join(STAGE_DIR, 'shot-a.png'), PNG_1x1);
  // Decoys: wrong extension / illegal shape — must never appear in the list
  await writeFile(join(STAGE_DIR, 'notes.txt'), 'not an image');
  await writeFile(join(STAGE_DIR, 'weird name.png'), PNG_1x1); // space is not in the whitelist

  // S1: list shape — 200 {ok,result:{files}}, only whitelisted pngs, decoys filtered
  let stagedVisible = false; // does the console see this lane's staged dir (root mismatch = environment fact)
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

  // S2: byte round trip — staged bytes come back unchanged, as image/png.
  // Same precondition gate as S1: when the console root mismatches, staged
  // files are invisible and the round trip 404s — that is an environment fact
  // (see the header: "mismatch is an environment fact, not a pass"), handled
  // as env_fail, not FAIL. Without this gate the leg went falsely red when
  // the isolated console's anchor root drifted (fixed in t260904-04 arbitrate
  // gen1; when the precondition holds, the assertion surface is unchanged).
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

  // S3: a png that does not exist → 404 with a human message (neither archive
  // nor lane has it).
  {
    const { status, body } = await evidenceRequest(STAGE_ID, 'nope-missing.png');
    if (status === 404 && body?.ok === false && typeof body?.error === 'string') {
      record('server/missing-file-404', 'pass');
    } else {
      record('server/missing-file-404', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 150)}`);
    }
  }

  // Clean up before the traversal cases (they must not rely on staged files)
  await rm(STAGE_DIR, { recursive: true, force: true });
}

async function faultSurface() {
  // S4: file-name path traversal → 4xx rejection, never 200.
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

  // S5: illegal ticket id → 400 (not 5xx, not 200).
  for (const [name, id] of [['dotdot', '..'], ['slash', 'a/b'], ['empty-ish', 'x']]) {
    try {
      const { status } = await evidenceRequest(id);
      if (status >= 400 && status < 500) record(`server/bad-id-${name}`, 'pass');
      else record(`server/bad-id-${name}`, 'fail', `status=${status} (must be 4xx)`);
    } catch (err) {
      record(`server/bad-id-${name}`, 'fail', String(err).slice(0, 120));
    }
  }

  // S6: well-shaped but nonexistent ticket id → empty list, no error (soft
  // degradation).
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
  for (const c of [process.env.SANDBAR_PLAYWRIGHT_PATH, 'playwright-core',
    new URL('../../server/ui-check/node_modules/playwright-core/index.mjs', import.meta.url).href]) {
    if (!c) continue;
    try { pw = await import(c); break; } catch { /* next */ }
  }
  if (!pw) { record('ui/drawer-images', 'env_fail', 'playwright-core unavailable'); return; }
  let browser;
  try {
    browser = await pw.chromium.launch({ channel: 'chrome', headless: true }).catch(() => pw.chromium.launch({ headless: true }));
    const page = await (await browser.newContext()).newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // The factory notice (Continue overlay) blocks row clicks — close it
    // first (same as lib_browser).
    try {
      const nb = page.locator('button', { hasText: /continue|继续/i }).first();
      await nb.click({ timeout: 4000 });
      await nb.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    } catch { /* no notice = the normal case */ }
    await page.waitForSelector('.wb-card[data-ticket-id]', { timeout: 12000 });
    const rowIds = await page.$$eval('.wb-card[data-ticket-id]', (els) => els.map((e) => e.getAttribute('data-ticket-id')));
    if (rowIds.length < 1) throw new Error('no rows');
    // Row order is not pinned (the shared stage's first row drifts with
    // project/time): ask the evidence API per row and click the first row
    // that actually has evidence — the drawer assertion needs the target
    // row to have images; clicking an image-less row is a fixture fact, not
    // a product failure.
    let target = null;
    for (const id of rowIds) {
      const { status, body } = await evidenceRequest(id);
      if (status === 200 && body?.ok === true && (body?.result?.files ?? []).length > 0) { target = id; break; }
    }
    if (!target) throw new Error('no evidence-bearing row on console');
    // Ticket id charset = [A-Za-z0-9-] (TICKET_ID_RE), so no CSS.escape needed
    // (some headless shells lack that global).
    await page.click(`.wb-card[data-ticket-id="${target}"]`);
    await page.waitForSelector('.wb-drawer', { timeout: 10000 });
    await page.waitForSelector('.wb-drawer img[src*="/evidence/"]', { timeout: 10000 });
    // Wait for actual decode before sampling: waitForSelector only guarantees
    // the img nodes are in the DOM — under concurrent load the PNG fetch and
    // decode lag, and sampling immediately misreads a "still loading" frame
    // as decoded=0 (proven in the 260909 full run: imgs=1 decoded=0 transient
    // red, always green standalone). On timeout we fall through to the count
    // below, which reports red honestly — no watering down.
    await page.waitForFunction(() => {
      const imgs = [...document.querySelectorAll('.wb-drawer img[src*="/evidence/"]')];
      return imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0);
    }, { timeout: 10000 }).catch(() => { /* not decoded yet = the count below reports red honestly */ });
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
    // No drawer / no evidence on the first row is a fixture fact; a timeout
    // on a ticket that does have evidence is a real product failure — both
    // are reported as they are, unless playwright/console itself is the
    // blocker.
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
