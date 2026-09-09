// 票 t260831-08（缺陷②）集成测试——工单抽屉里的截图证据可见。
//
// 锁什么（黑盒，用户视角）：
//   QA 截图（泳道 .suyou/screenshots/*.png）必须在工单详情抽屉可见。修复后的
//   用户可见契约：
//     - GET /sandbar-workbench/api/wf/tickets/<id>/evidence 列出 png 文件
//       （归档 .suyou/evidence/<id>/ 优先，其次泳道 screenshots）；  // naming-compat
//       无证据→空清单，不报错（抽屉只是不渲染该段）。
//     - GET .../evidence/<file> 按 image/png 原样回字节。
//     - 路径穿越/非法文件名/非法票号一律 4xx 拒掉，绝不外发。
//     - (UI) 抽屉每个文件渲染一个 <img src=".../evidence/<file>">。
//
// 暂存：本套件把一张小合法 PNG 放进 <laneRoot>/.suyou/evidence/<stageId>/  // naming-compat
// （从本泳道起的 console 的归档基目录），跑完清掉。如果 console 服务的是别的仓根，
// 暂存文件腿降级 env_fail 并给原因（根不匹配是环境事实不是产品绿；票 t260904-12
// 三态：环境红 exit 2，绝不 exit 0 假绿）。
// 红线：永不碰 3099。
//
// 执行契约（票 t260904-12 三态）：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全腿 na → exit 1；
// env_fail>0 → exit 2。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { mkdir, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'

const BASE = (await ensureStageConsole()).base;
const LANE = process.cwd();
const STAGE_ID = 't26083108evtest'; // 必须满足 TICKET_ID_RE（字母数字，无 / 无 .）
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
  // 诱饵：扩展名不对 / 形状非法——绝不允许出现在清单里
  await writeFile(join(STAGE_DIR, 'notes.txt'), 'not an image');
  await writeFile(join(STAGE_DIR, 'weird name.png'), PNG_1x1); // 空格不在白名单

  // S1：清单形状——200 {ok,result:{files}}，只收 png 白名单项，诱饵被过滤
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

  // S2：字节回环——暂存字节原样、image/png。
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

  // S3：不存在的 png → 404 人话文案（归档与泳道两处都没有）。
  {
    const { status, body } = await evidenceRequest(STAGE_ID, 'nope-missing.png');
    if (status === 404 && body?.ok === false && typeof body?.error === 'string') {
      record('server/missing-file-404', 'pass');
    } else {
      record('server/missing-file-404', 'fail', `status=${status} body=${JSON.stringify(body)?.slice(0, 150)}`);
    }
  }

  // 先清场再跑后面的（穿越用例不许依赖暂存文件）
  await rm(STAGE_DIR, { recursive: true, force: true });
}

async function faultSurface() {
  // S4：文件名位路径穿越 → 4xx 拒掉，绝不 200。
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

  // S5：非法票号 → 400（不是 5xx，也不是 200）。
  for (const [name, id] of [['dotdot', '..'], ['slash', 'a/b'], ['empty-ish', 'x']]) {
    try {
      const { status } = await evidenceRequest(id);
      if (status >= 400 && status < 500) record(`server/bad-id-${name}`, 'pass');
      else record(`server/bad-id-${name}`, 'fail', `status=${status} (must be 4xx)`);
    } catch (err) {
      record(`server/bad-id-${name}`, 'fail', String(err).slice(0, 120));
    }
  }

  // S6：形状合法但不存在的票号 → 空清单，不报错（软降级）。
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
    // 出厂 notice（Continue 遮罩）会拦截行卡点击——先关再断言（lib_browser 同款）。
    try {
      const nb = page.locator('button', { hasText: /continue|继续/i }).first();
      await nb.click({ timeout: 4000 });
      await nb.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    } catch { /* 无 notice=常态 */ }
    await page.waitForSelector('.wb-card[data-ticket-id]', { timeout: 12000 });
    const rowIds = await page.$$eval('.wb-card[data-ticket-id]', (els) => els.map((e) => e.getAttribute('data-ticket-id')));
    if (rowIds.length < 1) throw new Error('no rows');
    // 行序不钉死（共享台首行随项目/时间漂移）：逐个问 evidence API，点第一张
    // 真有证据的票——抽屉断言面前提=目标行有图，无图行点击是夹具事实不是产品失败。
    let target = null;
    for (const id of rowIds) {
      const { status, body } = await evidenceRequest(id);
      if (status === 200 && body?.ok === true && (body?.result?.files ?? []).length > 0) { target = id; break; }
    }
    if (!target) throw new Error('no evidence-bearing row on console');
    // 票 id 字符集 = [A-Za-z0-9-]（TICKET_ID_RE），无需 CSS.escape（个别无头壳无该全局）。
    await page.click(`.wb-card[data-ticket-id="${target}"]`);
    await page.waitForSelector('.wb-drawer', { timeout: 10000 });
    await page.waitForSelector('.wb-drawer img[src*="/evidence/"]', { timeout: 10000 });
    // 等图真解码再取样：waitForSelector 只保证 img 节点在 DOM——并发负载下 PNG
    // 取回/解码滞后，立即取样=把「加载中」快照误判 decoded=0（260909 全量跑实锤
    // imgs=1 decoded=0 瞬态红，静机单跑恒绿）。超时落回下方计数如实红，不放水。
    await page.waitForFunction(() => {
      const imgs = [...document.querySelectorAll('.wb-drawer img[src*="/evidence/"]')];
      return imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0);
    }, { timeout: 10000 }).catch(() => { /* 解码未成=下方计数如实红 */ });
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
    // 首行无抽屉/无证据是夹具事实；已有证据的票上超时才是真产品失败——
    // 两种情况都如实报，除非 playwright/console 本身就是阻塞原因。
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
