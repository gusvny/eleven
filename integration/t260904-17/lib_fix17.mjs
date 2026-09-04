// lib_fix17.mjs —— t260904-17 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 复用面（integration 纪律：前置/基础步骤代码允许共享；boot 骨架自 t260904-15 lib_fix15
// 同款改造，差异=本票需要可桩的票数据源）：
//   - 票数据源桩缝：host 链路 python3 → <repo>/server/admin.py call ticket|workflow 的
//     python3 走 PATH 解析（suyou-tools.ts runAdminCli execFileP）——给隔离台进程注入
//     shim `python3`（仅拦截 admin.py 的 ticket/workflow call，其余透传真解释器），
//     行为经 FIX17_CTRL（JSON）驱动、调用轨迹落 FIX17_TRACE（JSONL，时序/并发断言面）。
//     全程零真 Temporal 接触（SUYOU_TARGET_HOST 钉死端口），零 3099 接触。
//   - 隔离台自举（临时 DSH_HOME + 自物化 profile + 随机高端口 + 就绪等待）与四路径回收。
//   - playwright-core 探测 / 出厂 notice 关闭 / SUMMARY 执行契约（t260904-15 同口径）。
import { spawn, spawnSync } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync, openSync, closeSync,
  readdirSync, realpathSync, chmodSync,
} from 'node:fs';
import { copyFile, mkdir, symlink } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DEAD_TEMPORAL = '127.0.0.1:17233'; // 死端口：本票票源全走桩，真 Temporal 不可达=兜底红线

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
  writeFileSync(path.join(root, '.migrated'), 'source: fix17 fixture\n');
  return root;
}

export function writeProjectEntry(root, key, name, dirs) {
  const d = path.join(root, key);
  mkdirSync(d, { recursive: true });
  const lines = [
    '# fixture entry (t260904-17 场景自建，非真源)',
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

/** 真 python3 绝对路径（PATH 注入前解析；shim 透传与 execv 目标都用它）。 */
export function realPython() {
  const r = spawnSync('which', ['python3'], { encoding: 'utf8' });
  const p = (r.stdout || '').trim();
  if (r.status !== 0 || !p) throw new Error('which python3 失败：无法构建桩解释器');
  return p;
}

/**
 * 票/模板数据源桩：shim python3 + 控制文件 + 调用轨迹。
 * ctrl 形状：
 *   { workflows: [{id,name,stages:[{id,name}...]}...],
 *     tickets: [{id,project,title,status,stage,stage_state,epic,updated_ts,workflow,...}...],
 *     show: { <ticketId>: {mode:'ok', timeline:[{at,stage,state}...]} |
 *                          {mode:'fail'} | {mode:'delay', ms:N, then:'ok'|'fail'} } }
 * 轨迹：每次被拦截的调用追加一行 {op,id,t0,t1}（时序/并发断言面）。
 */
export function makeTicketStub() {
  const dir = tmpRoot('fix17-shim-');
  const ctrlPath = path.join(dir, 'ctrl.json');
  const tracePath = path.join(dir, 'trace.jsonl');
  writeFileSync(ctrlPath, JSON.stringify({ workflows: [], tickets: [], show: {} }));
  writeFileSync(tracePath, '');
  const REAL = realPython();
  const shim = `#!${REAL}
import sys, json, os, time
REAL = ${JSON.stringify(REAL)}
args = sys.argv[1:]
tool = None
payload = {}
try:
    i = args.index('call')
    tool = args[i + 1] if i + 1 < len(args) else None
    if i + 2 < len(args):
        payload = json.loads(args[i + 2])
except (ValueError, IndexError, json.JSONDecodeError):
    tool = None
isAdmin = any(a.endswith('admin.py') for a in args)
if not isAdmin or tool not in ('ticket', 'workflow'):
    os.execv(REAL, [REAL] + args)  # 非本桩面：透传真解释器
ctrl_path = os.environ['FIX17_CTRL']
trace_path = os.environ['FIX17_TRACE']
t0 = time.time()
def trace(op, tid):
    try:
        with open(trace_path, 'a') as f:
            f.write(json.dumps({'op': op, 'id': tid, 't0': t0, 't1': time.time()}) + chr(10))
    except OSError:
        pass
def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.exit(0)
if tool == 'workflow':
    op = payload.get('op', 'list')
    trace('workflow:' + str(op), '')
    if op in ('list', ''):
        ctrl = json.load(open(ctrl_path))
        emit({'ok': True, 'result': {'workflows': ctrl.get('workflows', [])}})
    emit({'ok': False, 'error': 'fix17 桩不认识 workflow op=' + str(op)})
if tool == 'ticket':
    op = payload.get('op', '')
    tid = str(payload.get('id', ''))
    trace('ticket:' + str(op), tid)
    ctrl = json.load(open(ctrl_path))
    if op == 'list':
        proj = payload.get('project', '')
        rows = [t for t in ctrl.get('tickets', []) if t.get('project') == proj]
        emit({'ok': True, 'result': {'count': len(rows), 'tickets': rows}})
    if op == 'show':
        spec = ctrl.get('show', {}).get(tid, {'mode': 'fail'})
        mode = spec.get('mode', 'fail')
        if mode == 'delay':
            time.sleep(min(float(spec.get('ms', 0)), 30000) / 1000.0)
            mode = spec.get('then', 'fail')
        if mode == 'fail':
            emit({'ok': False, 'error': 'fix17 注入：show 失败', 'kind': 'transient'})
        detail = dict([t for t in ctrl.get('tickets', []) if t.get('id') == tid][0] or {})
        detail['timeline'] = spec.get('timeline', [])
        detail['pending'] = spec.get('pending', [])
        emit({'ok': True, 'result': detail})
    emit({'ok': False, 'error': 'fix17 桩不认识 ticket op=' + str(op)})
emit({'ok': False, 'error': 'fix17 桩不可达'})
`;
  writeFileSync(path.join(dir, 'python3'), shim);
  chmodSync(path.join(dir, 'python3'), 0o755);
  return {
    dir, ctrlPath, tracePath,
    setCtrl(obj) { writeFileSync(ctrlPath, JSON.stringify(obj)); },
    readTrace() {
      const txt = require$read(tracePath);
      return txt.split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    },
    traceSizeAt() { return require$read(tracePath).length; },
    traceSince(size) {
      return require$read(tracePath).slice(size).split('\n').filter(Boolean)
        .map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    },
  };
}

// 小工具：同步读文本（避免顶部 import 复杂化）
import { readFileSync } from 'node:fs';
function require$read(p) { try { return readFileSync(p, 'utf8'); } catch { return ''; } }

function benchEnv(tmpHome, projectsRoot, stub) {
  const env = { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: projectsRoot };
  delete env.SUYOU_PROJECTS_YAML;
  env.SUYOU_TARGET_HOST = DEAD_TEMPORAL;
  delete env.SUYOU_NAMESPACE;
  env.FIX17_CTRL = stub.ctrlPath;
  env.FIX17_TRACE = stub.tracePath;
  env.PATH = `${stub.dir}${path.delimiter === ':' ? ':' : ':'}${process.env.PATH || ''}`;
  return env;
}

/** 主树根解析（泳道 worktree 布局下借用主树已装依赖；只读主树，不写）。 */
export function mainRoot() {
  if (process.env.FIX17_MAIN_ROOT) return process.env.FIX17_MAIN_ROOT;
  try {
    const r = spawnSync('git', ['-C', REPO_ROOT, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { encoding: 'utf8' });
    const dir = (r.stdout || '').trim();
    if (r.status === 0 && dir) return path.dirname(dir);
  } catch { /* fallthrough */ }
  return REPO_ROOT;
}

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
  if (!existsSync(mainProfileNm)) throw new Error(`主树插件依赖缺失：${mainProfileNm} 不存在（env FIX17_MAIN_ROOT 可指主树根）`);
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

/** 自举隔离台（票源=FIX17 桩；env PATH 前置 shim 目录）。失败抛错由调用方转干净 SKIP。 */
export async function bootConsole(projectsRoot, stub) {
  const tmpHome = mkdtempSync(path.join(tmpdir(), 'fix17-bench-'));
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
      env: benchEnv(tmpHome, projectsRoot, stub),
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

export function teardownOnExit(teardown) {
  process.on('exit', teardown);
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130); });
}

/** playwright-core 四路探测（t260904-15 同口径）。null=调用方干净 SKIP（KI-036）。 */
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

/** 出厂 notice 关闭（t260904-15 dismissNotice 同款：只读导航语义）。 */
export async function dismissNotice(page) {
  try {
    const btn = page.locator('button', { hasText: /continue|继续/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 4000 });
    try { await btn.click({ timeout: 3000 }); } catch { await btn.evaluate((el) => el.click()); }
    await btn.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => { /* 已消失即可 */ });
    return '出厂 notice 已关闭（Continue）';
  } catch { return null; }
}

export async function api(base, method, pathname, payload) {
  const r = await fetch(`${base}${pathname}`, {
    method,
    signal: AbortSignal.timeout(120000),
    ...(payload === undefined ? {} : {
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  });
  const text = await r.text();
  let body = text;
  try { body = JSON.parse(text); } catch { /* 保持 raw */ }
  return { status: r.status, body, text };
}

/** 执行契约（integration/README.md）：stdout 末行 SUMMARY pass/fail/env_fail/na（12 号三态形状）；exit=FAIL>0→1，env_fail>0→2，绿=0。 */
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
      const f = results.filter((r) => r.status === 'fail').length;
      const e = results.filter((r) => r.status === 'env_fail').length;
      const na = results.filter((r) => r.status === 'na').length;
      console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${na}`);
      process.exit(f > 0 ? 1 : (e > 0 || (p === 0 && f === 0 && na > 0) ? 2 : 0));
    },
  };
}
