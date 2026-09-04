// lib_fix15.mjs —— t260904-15 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 复用面（integration 纪律：前置/基础步骤代码允许共享，步骤级重复不算重复用例）：
//   - 隔离台自举（t260904-06 bench-shot.mjs bootConsole 同款：临时 DSH_HOME +
//     buildTempProfile + 随机高端口 + 等待就绪），并注入本票钉死 env——
//     SANDBAR_PROJECTS_DIR=临时注册表根（host 装载器与其 spawn 的 sandbar CLI 同根，
//     单源不双份）、SUYOU_TARGET_HOST=死端口（Temporal 不可达=降级/fail-closed 断言面）、
//     SUYOU_PROJECTS_YAML 删除（防 legacy 模式外溢）；
//   - boot 进程四路径回收（正常/报错/超时/信号：kill 进程组 + 关 fd + 删临时目录）；
//   - playwright-core 三路探测（t260904-05 lib_browser 同口径，缺失=干净 SKIP，KI-036）；
//   - SUMMARY 执行契约（integration/README.md：末行 pass/skip/fail，FAIL>0 才 exit 1）；
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
const DEAD_TEMPORAL = '127.0.0.1:17233'; // 死端口：本票 UI/路由面的降级与 fail-closed 断言锚

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

/** 隔离台 boot env：本票断言面钉死（读面=临时注册表根；Temporal=死端口）。 */
export function benchEnv(tmpHome, projectsRoot) {
  const env = { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: projectsRoot };
  delete env.SUYOU_PROJECTS_YAML;
  env.SUYOU_TARGET_HOST = DEAD_TEMPORAL;
  delete env.SUYOU_NAMESPACE;
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
 * cordis 配置/suyou-tools.ts 取本仓 profile 目录（committed）；插件 node_modules 逐项
 * realpath 自主树（读主树已装依赖，其余插件不受测），唯 suyou-workbench 改指泳道
 * workbench 源目录（插件宿主入口=node.ts TS 直跑，宿主面测的就是泳道源码）。
 * 不依赖泳道 server/dsh/profile/node_modules（gitignored，泳道恒缺——原 buildTempProfile
 * 在泳道布局下必拒跑，arbitrate gen0 测试资产变更审查有记）。
 */
async function buildProfile(tmpHome, laneWorkbenchDir) {
  const laneProfile = path.join(REPO_ROOT, 'server', 'dsh', 'profile');
  const mainProfileNm = path.join(mainRoot(), 'server', 'dsh', 'profile', 'node_modules');
  const profDir = path.join(tmpHome, 'profiles', 'suyou');
  await mkdir(profDir, { recursive: true });
  for (const f of ['cordis.yml', 'cordis.patch.yml', 'package.json']) {
    const src = path.join(laneProfile, f);
    if (existsSync(src)) await copyFile(src, path.join(profDir, f));
  }
  const tsTools = path.join(laneProfile, 'suyou-tools.ts');
  if (existsSync(tsTools)) await symlink(tsTools, path.join(profDir, 'suyou-tools.ts'));
  const nm = path.join(profDir, 'node_modules');
  await mkdir(nm, { recursive: true });
  if (!existsSync(mainProfileNm)) throw new Error(`主树插件依赖缺失：${mainProfileNm} 不存在（env FIX15_MAIN_ROOT 可指主树根）`);
  let overridden = false;
  for (const name of readdirSync(mainProfileNm)) {
    const dest = name === 'suyou-workbench' ? laneWorkbenchDir
      : (() => { try { return realpathSync(path.join(mainProfileNm, name)); } catch { return null; } })();
    if (!dest) continue;
    await symlink(dest, path.join(nm, name));
    if (name === 'suyou-workbench') overridden = true;
  }
  if (!overridden) throw new Error(`主树 profile/node_modules 缺 suyou-workbench：${mainProfileNm}`);
  return profDir;
}

/** 浏览器腿守卫：泳道 client build（lib/client.js）缺失或陈旧 → 拒跑（防拍旧 UI 假绿，
 * capture-lane.laneBuildRejectReason 同口径）。返回 null=可跑，否则人话拒因。 */
export async function clientBuildStalenessReason() {
  const mod = await import(pathToFileURL(path.join(REPO_ROOT, 'server', 'dsh', 'ui-check', 'capture-lane.mjs')).href);
  return mod.laneBuildRejectReason(path.join(REPO_ROOT, 'server', 'dsh', 'workbench'));
}

async function waitReady(port, timeoutMs, logPath) {
  const url = `http://127.0.0.1:${port}/suyou-workbench/api/wf/projects`;
  const t0 = Date.now();
  for (;;) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (r.ok) return;
    } catch { /* 未就绪，续等 */ }
    if (Date.now() - t0 > timeoutMs) throw new Error(`隔离台就绪超时（${Math.round(timeoutMs / 1000)}s）：log=${logPath}`);
    await new Promise((r) => setTimeout(r, 500));
  }
}

/**
 * 自举隔离台（bench-shot bootConsole 同款 + 本票 env 注入）。
 * 返回 { port, tmpHome, projectsRoot }；失败抛错由调用方转干净 SKIP。
 */
export async function bootConsole(projectsRoot) {
  const tmpHome = mkdtempSync(path.join(tmpdir(), 'fix15-bench-'));
  const clean = () => { try { rmSync(tmpHome, { recursive: true, force: true }); } catch { /* 留警告 */ } };
  try {
    const cred = [
      path.join(process.env.HOME || '', '.sandbar', 'projects', 'suyou', 'credentials.yaml'),
      path.join(process.env.DSH_HOME || '', '.credentials.yaml'),
      path.join(process.env.HOME || '', '.dsh', '.credentials.yaml'),
    ].find((p) => existsSync(p));
    if (cred) await copyFile(cred, path.join(tmpHome, '.credentials.yaml')).catch(() => {});
    await buildProfile(tmpHome, path.join(REPO_ROOT, 'server', 'dsh', 'workbench'));
    const port = await freePort();
    if (port === 3099) throw new Error('freePort 撞 3099（概率≈0，命中即拒跑）');
    const patchFile = path.join(tmpHome, 'port.patch.yml');
    writeFileSync(patchFile, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`);
    const logFd = openSync(path.join(tmpHome, 'console.log'), 'a');
    const proc = spawn('dsh', ['--profile', 'suyou', '--patch', patchFile,
      '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
      cwd: REPO_ROOT, detached: true, stdio: ['ignore', logFd, logFd],
      env: benchEnv(tmpHome, projectsRoot),
    });
    await waitReady(port, 45000, path.join(tmpHome, 'console.log'));
    return {
      port, tmpHome, projectsRoot, proc, logFd, clean,
      base: `http://127.0.0.1:${port}`,
      teardown() {
        if (proc.pid && proc.exitCode === null && proc.signalCode === null) {
          try { process.kill(-proc.pid, 'SIGTERM'); } catch { try { proc.kill('SIGKILL'); } catch { /* 已退 */ } }
        }
        try { closeSync(logFd); } catch { /* 已关 */ }
        clean();
      },
    };
  } catch (e) { clean(); throw e; }
}

/** 进程级兜底：exit/信号时回收（调用方把 bootConsole 返回的 teardown 挂进来）。 */
export function teardownOnExit(teardown) {
  process.on('exit', teardown);
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130); });
}

/** playwright-core 四路探测（env 指定 → 裸包 → 泳道 ui-check 依赖 → 主树已装依赖）。
 * 泳道 ui-check/node_modules gitignored 恒缺；第④路只读借用主树（与 buildProfile 同理，
 * 被测代码仍是泳道 workbench）。null=调用方干净 SKIP（KI-036）。 */
export async function loadPlaywright() {
  const localPw = new URL('../../server/dsh/ui-check/node_modules/playwright-core/index.mjs', import.meta.url).href;
  const mainPw = path.join(mainRoot(), 'server', 'dsh', 'ui-check', 'node_modules', 'playwright-core', 'index.mjs');
  for (const c of [process.env.SUYOU_PLAYWRIGHT_PATH, 'playwright-core', localPw,
    existsSync(mainPw) ? pathToFileURL(mainPw).href : null]) {
    if (!c) continue;
    try { return await import(c); } catch { /* next */ }
  }
  return null;
}

/** 执行契约（integration/README.md）：stdout 末行 SUMMARY pass/skip/fail；FAIL>0 才 exit 1。 */
export function makeResults() {
  const results = [];
  return {
    record(name, status, detail = '') {
      const st = status === true ? 'pass' : status === false ? 'fail' : String(status);
      results.push({ name, status: st, detail });
      console.log(`[${st.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
    },
    summarize() {
      const p = results.filter((r) => r.status === 'pass').length;
      const s = results.filter((r) => r.status === 'skip').length;
      const f = results.filter((r) => r.status === 'fail').length;
      console.log(`SUMMARY pass=${p} skip=${s} fail=${f}`);
      process.exit(f > 0 ? 1 : 0);
    },
  };
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
