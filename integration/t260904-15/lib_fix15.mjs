// lib_fix15.mjs —— t260904-15 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 复用面（integration 纪律：前置/基础步骤代码允许共享，步骤级重复不算重复用例）：
//   - 隔离台自举（t260904-19 起=docker 测试台，integration/stage_docker.py 单点入口；
//     自搭进程 boot 随票退役）：dsh-only 舞台（容器内 SANDBAR_TARGET_HOST 钉死
//     127.0.0.1:1=Temporal 不可达的降级/fail-closed 断言面）、fixtures 根挂 /fixtures
//     （容器内外同读写，注册表 fixture 单源）、预组 profile 经 buildStageProfile
//     容器内路径物化（测泳道 workbench 源码，克缝始终不变）；
//   - 拆台=stage_docker down（零残留核验在 CLI 内建）；
//   - playwright-core 四路探测（t260904-05 lib_browser 同口径，缺失=ENV_FAIL 点名，KI-036）；
//   - SUMMARY 执行契约（integration/README.md 三态：末行四计数，FAIL>0→1、ENV_FAIL>0→2）；
//   - 注册表 fixture（好条目/畸形条目/空根，.migrated 标记防误触真迁移）。
// 安全红线：零 3099 接触（端口随机，自检断言）；env 逐项显式钉死防缺省外溢生产 7233。
import { spawn, spawnSync } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync, openSync, closeSync,
  readdirSync, realpathSync,
} from 'node:fs';
import { copyFile, mkdir, symlink } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SANDBAR = path.join(REPO_ROOT, 'sandbar');
const DEAD_TEMPORAL = '127.0.0.1:1'; // 死端口：宿主侧 CLI 降级断言锚。原 17233 是缺省测试台端口，
// t260904-19 起有 supply 常驻台=恒可达，锚会静默失效——换 127.0.0.1:1（lib_fix10 先例）

export function tmpRoot(prefix) {
  return mkdtempSync(path.join(tmpdir(), prefix));
}

export function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
    srv.on('error', reject);
  });
}

/** 注册表根 fixture：带 .migrated 标记（防首装载误触真迁移读真 HOME 旧表）。 */
export function makeRegistryRoot(prefix) {
  const root = tmpRoot(prefix);
  writeFileSync(path.join(root, '.migrated'), 'source: fix15 fixture\n');
  return root;
}

/** docker 台 fixtures 根（t260904-19）：root 挂容器 /fixtures（rw），reg=注册表根
 *  在容器内的路径 /fixtures/reg。场景的一切 fixture 目录建在 root 下（容器内外同读写），
 *  API payload 里的目录一律经 toStage() 换成容器路径。 */
export function makeFixtures(prefix) {
  const root = tmpRoot(prefix);
  const reg = path.join(root, 'reg');
  mkdirSync(reg, { recursive: true });
  writeFileSync(path.join(reg, '.migrated'), 'source: fix15 fixture (docker stage)\n');
  return { root, reg, toStage: (p) => '/fixtures/' + path.relative(root, p) };
}

/** 好条目 fixture（形状=t260904-14 writeProjectEntry 同款最小 YAML 子集）。 */
export function writeProjectEntry(root, key, name, dirs) {
  const d = path.join(root, key);
  mkdirSync(d, { recursive: true });
  const lines = [
    '# fixture entry (t260904-15 场景自建，非真源)',
    'schema: v1',
    'project:',
    `  - key: ${key}`,
    `    name: ${name}`,
    '    dirs:',
    ...dirs.map((x) => `      - ${x}`),
    '',
  ];
  writeFileSync(path.join(d, 'project.yaml'), lines.join('\n'));
  return d;
}

/** 隔离条目 fixture：畸形 project.yaml（非法 YAML）→ 装载器单条目隔离，error 含定位。 */
export function writeQuarantinedDir(root, key) {
  const d = path.join(root, key);
  mkdirSync(d, { recursive: true });
  writeFileSync(path.join(d, 'project.yaml'), 'key: [oops 未闭合流\n');
  return d;
}

/** 宿主侧 CLI 子进程 env（t260904-19 起控制台在容器里，本 env 只管场景自己 spawn
 *  的 sandbar CLI 降级子用例：Temporal=死端口锚）。 */
export function benchEnv(tmpHome, projectsRoot) {
  const env = { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: projectsRoot };
  delete env.SANDBAR_PROJECTS_YAML;
  env.SANDBAR_TARGET_HOST = DEAD_TEMPORAL;
  delete env.SANDBAR_NAMESPACE;
  return env;
}

/** 主树根解析（泳道 worktree 布局下借用主树已装依赖；只读主树，不写）：
 * worktree 的 .git 是 gitfile → git rev-parse --git-common-dir 取主库 .git → 上级即主树根。
 * env FIX15_MAIN_ROOT 可覆盖（无 git 环境逃生门）。 */
export function mainRoot() {
  if (process.env.FIX15_MAIN_ROOT) return process.env.FIX15_MAIN_ROOT;
  try {
    const r = spawnSync('git', ['-C', REPO_ROOT, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { encoding: 'utf8' });
    const dir = (r.stdout || '').trim();
    if (r.status === 0 && dir) return path.dirname(dir);
  } catch { /* fallthrough */ }
  return REPO_ROOT; // 主 checkout 直接跑时即主树
}

/**
 * 自物化临时 profile（capture-lane.buildTempProfile 的泳道自适应版，克缝始终=测泳道代码）：
 * cordis 配置/sandbar-tools.ts 取本仓 profile 目录（committed）；插件 node_modules 逐项
 * realpath 自主树（读主树已装依赖，其余插件不受测），唯 sandbar-workbench 改指泳道
 * workbench 源目录（插件宿主入口=node.ts TS 直跑，宿主面测的就是泳道源码）。
 * 不依赖泳道 server/profile/node_modules（gitignored，泳道恒缺——原 buildTempProfile
 * 在泳道布局下必拒跑，arbitrate gen0 测试资产变更审查有记）。
 */
async function buildProfile(tmpHome, laneWorkbenchDir) {
  // t260904-19：容器内路径物化（stage_docker.mjs 单点实现）；其余插件软链容器
  // /usr/local/lib/node_modules（dsh 全局树），缺失由健康探针/启动自愈兜底。
  const stage = await import(pathToFileURL(path.join(REPO_ROOT, 'integration', 'stage_docker.mjs')).href);
  return stage.buildStageProfile({
    repoProfileDir: path.join(REPO_ROOT, 'server', 'profile'),
    laneWorkbenchDir: laneWorkbenchDir ?? '/repo/server/plugins/workbench',
    tmpHome,
  });
}

/** 浏览器子用例守卫：泳道 client build（lib/client.js）缺失或陈旧 → 拒跑（防拍旧 UI 假绿，
 * capture-lane.laneBuildRejectReason 同口径）。返回 null=可跑，否则人话拒因。 */
export async function clientBuildStalenessReason() {
  const mod = await import(pathToFileURL(path.join(REPO_ROOT, 'server', 'ui-check', 'capture-lane.mjs')).href);
  return mod.laneBuildRejectReason(path.join(REPO_ROOT, 'server', 'plugins', 'workbench'));
}

/**
 * 自举隔离台（bench-shot bootConsole 同款 + 本票 env 注入）。
 * 返回 { port, tmpHome, projectsRoot }；失败抛错由调用方转 ENV_FAIL（缺环境=环境红，不 exit 0 假绿）。
 * opts.services：'dsh'（默认，容器内引擎地址钉死不可达回环口=降级断言面）|
 *   'full'（dsh+temporal 健康 wiring——真 Temporal 语义子用例用，260908 补供给）。
 */
export async function bootConsole(fixturesRoot, opts = {}) {
  // t260904-19：docker 舞台（dsh-only：容器内引擎地址钉死不可达回环口=降级断言面）。
  // fixturesRoot 挂容器 /fixtures（rw），注册表根=<fixturesRoot>/reg（容器内 /fixtures/reg）。
  // 返回 { base, teardown, reg, toStage, project }；失败抛错由调用方转 ENV_FAIL
  // （docker 缺席/镜像缺席/起台不健康=CLI 三态文案点名，环境红不 exit 0 假绿）。
  const stage = await import(pathToFileURL(path.join(REPO_ROOT, 'integration', 'stage_docker.mjs')).href);
  const tmpHome = mkdtempSync(path.join(tmpdir(), 'fix15-bench-'));
  const clean = () => { try { rmSync(tmpHome, { recursive: true, force: true }); } catch { /* 留警告 */ } };
  try {
    await buildProfile(tmpHome, path.join(REPO_ROOT, 'server', 'plugins', 'workbench'));
    const project = `fix15-${path.basename(fixturesRoot).toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 24)}-${process.pid}`;
    const st = stage.stageUp({
      project,
      services: opts.services ?? 'dsh',
      fixturesDir: fixturesRoot,
      profileDir: path.join(tmpHome, 'profiles', 'suyou'),
      projectsDir: '/fixtures/reg',
      timeoutSec: Number(process.env.FIX15_STAGE_TIMEOUT_SEC ?? 600),
    });
    return {
      project: st.project,
      base: `http://127.0.0.1:${st.ports.console}`,
      reg: '/fixtures/reg',
      toStage: (p) => '/fixtures/' + path.relative(fixturesRoot, p),
      // 261012：补回 goto——72e010c1（260928 token 门批）把两个场景改写成
      // `bench.goto(page, opts)`，但那是 lib_fix17（直起形态，token 兑换）的方法，
      // 本 bench（docker 台，无 token 门——同批遗留的 page2.goto 裸导航即证）从未
      // 提供过它，两条场景自此 `bench.goto is not a function` 恒挂。docker 台的导航
      // 语义=旧绿版的裸 page.goto(base)。
      goto(page, options) { return page.goto(`${this.base}/`, { waitUntil: 'domcontentloaded', ...options }); },
      tmpHome, clean,
      teardown() {
        try { stage.stageDown(st.project); } catch (e) { console.error(`[fix15] stage down：${e.message}`); }
        clean();
      },
    };
  } catch (e) { clean(); throw e; }
}

/** dsh 壳层首启对话框 dismissal（gen4 实锤：容器台每次新 DSH_HOME 首启都弹
 *  「Internal Testing Notice」，其遮罩全屏拦截指针——真实用户点 Continue 后即可用，
 *  场景旅程前如实 dismiss=模拟真人首启动作，非绕过）。幂等：无对话框即跳过。 */
export async function dismissShellNotice(page) {
  try {
    const btn = page.locator('[class*=jLrgrW] button, [role=dialog] button')
      .filter({ hasText: /^Continue$/ }).first();
    await btn.click({ timeout: 3000 });
    await page.waitForTimeout(400);
    console.log('[fix15] 壳层首启通知已 dismiss（Continue）');
  } catch { /* 无首启对话框=正常路径 */ }
}

/** 进程级兜底：exit/信号时回收（调用方把 bootConsole 返回的 teardown 挂进来）。 */
export function teardownOnExit(teardown) {
  process.on('exit', teardown);
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130); });
}

/** playwright-core 四路探测（env 指定 → 裸包 → 泳道 ui-check 依赖 → 主树已装依赖）。
 * 泳道 ui-check/node_modules gitignored 恒缺；第④路只读借用主树（与 buildProfile 同理，
 * 被测代码仍是泳道 workbench）。null=调用方转 ENV_FAIL 点名（KI-036；环境缺供不假绿）。 */
export async function loadPlaywright() {
  const localPw = new URL('../../server/ui-check/node_modules/playwright-core/index.mjs', import.meta.url).href;
  const mainPw = path.join(mainRoot(), 'server', 'ui-check', 'node_modules', 'playwright-core', 'index.mjs');
  for (const c of [process.env.SANDBAR_PLAYWRIGHT_PATH, 'playwright-core', localPw,
    existsSync(mainPw) ? pathToFileURL(mainPw).href : null]) {
    if (!c) continue;
    try { return await import(c); } catch { /* next */ }
  }
  return null;
}

// 执行契约（integration/README.md，t260904-12 三态化）：stdout 末行
// SUMMARY pass/fail/env_fail/na 四计数（ran=pass+fail+env_fail 双向净）；
// exit 码 f>0 或全 N/A→1（产品红），否则 e>0→2（环境红），否则 0。
// 词表只认 pass/fail/env_fail/na，越界抛错（不静默吞未知状态）。
export function makeResults() {
  const results = [];
  const WORDS = new Set(['pass', 'fail', 'env_fail', 'na']);
  return {
    record(name, status, detail = '') {
      const st = status === true ? 'pass' : status === false ? 'fail' : String(status);
      if (!WORDS.has(st)) throw new Error(`非法状态词：${st}（三态词表 pass/fail/env_fail/na）`);
      results.push({ name, status: st, detail });
      console.log(`[${st.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
    },
    summarize() {
      const p = results.filter((r) => r.status === 'pass').length;
      const e = results.filter((r) => r.status === 'env_fail').length;
      const na = results.filter((r) => r.status === 'na').length;
      const f = results.filter((r) => r.status === 'fail').length;
      const ran = p + f + e + na;
      console.log(`SUMMARY ran=${ran} pass=${p} fail=${f} env_fail=${e} na=${na}`);
      if (ran === 0 || (f === 0 && na === ran && ran > 0)) process.exit(1);  // 零场景/全 N/A=产品红
      process.exit(f > 0 ? 1 : e > 0 ? 2 : 0);
    },
  };
}

/** Poll a predicate until it is true or the deadline passes. */
export async function waitFor(pred, timeoutMs = 8000, stepMs = 200) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    try { if (await pred()) return true; } catch { /* keep polling */ }
    if (Date.now() >= end) return false;
    await new Promise((r) => setTimeout(r, stepMs));
  }
}

/**
 * Entrance to the Project Settings dialog (shared precondition, no assertions here).
 *
 * t261008-36 (host order 261008) retired the whole group-header icon family: the
 * entry moved to the executor panel's Settings tab. The console mounts the SAME
 * ProjectSettingsModal inside a face overlay, so the dialog's own anchors
 * (data-wb-pmod-overlay and friends) are unchanged — only the door moved.
 *
 * Steps: click the project row's executor entry ([data-wb-executor-entry],
 * t260929-22 face), then the panel's Settings tab ([data-tab="settings"]), then
 * the face row ([data-wb-panel-face="project-settings"]).
 *
<<<<<<< ours
=======
 * The entry click is scoped to the named group's own row (t261022-11): a
 * page-wide first match would open the wrong project's panel on a rail that
 * carries more than one project (the remove journey drives two).
 *
>>>>>>> theirs
 * Returns null when the dialog is on screen, else a plain-words reason (a door
 * that cannot be found is a red, never a silent skip).
 */
export async function openProjectSettings(page, groupText) {
  const head = page.locator('.wb-group-head', { hasText: groupText }).first();
  if (!(await head.count())) {
    return `project group row containing "${groupText}" is not rendered (registry fixture not consumed?)`;
  }
<<<<<<< ours
  const entry = page.locator('[data-wb-executor-entry]').first();
  if (!(await entry.count())) {
    return 'project row carries no executor entry anchor ([data-wb-executor-entry], t260929-22 face)';
=======
  const entry = head.locator('[data-wb-executor-entry]').first();
  if (!(await entry.count())) {
    return `project row for "${groupText}" carries no executor entry anchor ([data-wb-executor-entry], t260929-22 face)`;
>>>>>>> theirs
  }
  await entry.click({ force: true, timeout: 8000 });
  const iframeSrc = () => page.evaluate(() => {
    const f = [...document.querySelectorAll('iframe')].find((x) => /sandbar-executor-panel/.test(x.src || ''));
    return f ? f.src : '';
  });
  if (!(await waitFor(async () => /sandbar-executor-panel/.test(await iframeSrc()), 20000))) {
    return 'executor panel iframe did not mount after clicking the project row entry';
  }
  const frame = page.frameLocator('iframe[src*="sandbar-executor-panel"]');
  try {
    await frame.locator('[data-tab="settings"]').first().click({ timeout: 20000 });
  } catch {
    return 'panel page has no Settings tab anchor ([data-tab="settings"])';
  }
  if (!(await waitFor(async () => (await frame.locator('[data-wb-panel-face]').count()) >= 2, 10000))) {
    return 'panel Settings pane does not list both face entries ([data-wb-panel-face] count < 2)';
  }
  try {
    await frame.locator('[data-wb-panel-face="project-settings"]').first().click({ timeout: 10000 });
  } catch {
    return 'panel Settings pane has no "project-settings" face row';
  }
  const mounted = await waitFor(async () =>
    (await page.locator('[data-wb-face-overlay][data-face="project-settings"]').count()) === 1
    && (await page.locator('[data-wb-pmod-overlay]').count()) >= 1, 10000);
  if (!mounted) return 'clicking the project-settings face row mounted no settings dialog (face overlay or data-wb-pmod-overlay absent)';
  return null;
}

/** 出厂「Internal Testing Notice」关闭（capture.mjs dismissNotice 同款先例）：全新
 * DSH_HOME 首开即弹并劫持焦点/指针（fill 打不进受控输入——t260904-15 验收走查实锤），
 * 点 Continue 关闭（只读导航语义，不提交任何表单），超时未出现则继续。 */
export async function dismissNotice(page) {
  try {
    const btn = page.locator('button', { hasText: /continue|继续/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 4000 });
    try { await btn.click({ timeout: 3000 }); } catch { await btn.evaluate((el) => el.click()); }
    await btn.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => { /* 已消失即可 */ });
    return '出厂 notice 已关闭（Continue）';
  } catch { return null; }
}

/** workbench API 薄封装（隔离台 base）。返回 {status, body}；body 解析失败=raw 字符串。 */
export async function api(base, method, pathname, payload) {
  const r = await fetch(`${base}${pathname}`, {
    method,
    signal: AbortSignal.timeout(60000),
    ...(payload === undefined ? {} : {
      headers: { 'content-type': payload === '\x00raw' ? 'text/plain' : 'application/json' },
      body: payload === '\x00raw' ? '{broken json' : JSON.stringify(payload),
    }),
  });
  const text = await r.text();
  let body = text;
  try { body = JSON.parse(text); } catch { /* 保持 raw */ }
  return { status: r.status, body, text };
}

/** CLI 直呼（CLI 侧交叉断言用；env 必须与隔离台同根，见 benchEnv）。 */
export function runCli(args, projectsRoot) {
  const env = benchEnv(process.env.DSH_HOME || tmpdir(), projectsRoot);
  const r = spawnSync('python3', [SANDBAR, ...args], { cwd: REPO_ROOT, env, encoding: 'utf8', timeout: 120000 });
  return { code: r.status === null ? -1 : r.status, out: (r.stdout || '') + (r.stderr || '') };
}
