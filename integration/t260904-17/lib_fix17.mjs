// lib_fix17.mjs —— t260904-17 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 复用面（integration 纪律：前置/基础步骤代码允许共享；boot 骨架自 t260904-15 lib_fix15
// 同款改造，差异=本票需要可桩的票数据源）：
//   - 票数据源桩缝：host 链路 python3 → <repo>/server/admin.py call ticket|workflow 的
//     python3 走 PATH 解析（sandbar-tools.ts runAdminCli execFileP）——给隔离台进程注入
//     shim `python3`（仅拦截 admin.py 的 ticket/workflow call，其余透传真解释器），
//     行为经 FIX17_CTRL（JSON）驱动、调用轨迹落 FIX17_TRACE（JSONL，时序/并发断言面）。
//     全程零真 Temporal 接触（SANDBAR_TARGET_HOST 钉死端口），零 3099 接触。
//   - 隔离台自举（临时 DSH_HOME + 自物化 profile + 随机高端口 + 就绪等待）与四路径回收。
//   - playwright-core 探测 / 出厂 notice 关闭 / SUMMARY 执行契约（t260904-15 同口径）。
import { spawn, spawnSync } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync, openSync, closeSync,
  readdirSync, realpathSync, chmodSync, symlinkSync, unlinkSync,
} from 'node:fs';
import { copyFile, mkdir, symlink } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DEAD_TEMPORAL = '127.0.0.1:1'; // 死端口兜底红线。勿用 17233——那是供给台 Temporal 的实占端口（260910 实锤：列表直走引擎通道后「死端口」连上了供给台，ok:true 空行=隔离假绿）；夹具票源全走桩

// 260926 磁盘泄漏修（同类普查）：tmpRoot 建的夹具目录此前从不回收——宿主 $TMPDIR 实测
// `fix17-shim*` 攒了 12145 个 / 约 75MB（10.7 天）。进程任何终态（正常/走完/抛异常/process.exit）统一同步回收；
// SIGKILL（执行器 900s 超时帽）进程内兜底物理失效，由「同类外壳清理」另议（见验收报告清单）。
const LIVE_TMP = new Set();
process.on('exit', () => {
  for (const d of LIVE_TMP) { try { rmSync(d, { recursive: true, force: true }); } catch { /* 兜底路径不抛 */ } }
});
export function tmpRoot(prefix) {
  const d = mkdtempSync(path.join(tmpdir(), prefix));
  LIVE_TMP.add(d);
  return d;
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
isAdmin = any(a.endswith('admin.py') for a in args)
# 引擎通道拦截（t260910-04 起列表主数据直走 client.py ticket-list，不再经 admin.py
# ticket:list——桩必须同拦两条通道，否则夹具行恒空=整族契约红）。runPocCli 的 venv
# 优先解析会短路 PATH shim，靠 benchEnv 的 SANDBAR_REPO 夹具仓把 .venv/bin/python
# 符链回本桩，引擎通道才落得进拦截面。
isEngineList = (not isAdmin) and any(a.endswith('client.py') for a in args) and ('ticket-list' in args)
if not isAdmin and not isEngineList:
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
if isEngineList:
    i = args.index('ticket-list')
    try:
        epayload = json.loads(args[i + 1]) if i + 1 < len(args) else {}
    except json.JSONDecodeError:
        epayload = {}
    eproj = str(epayload.get('project', ''))
    trace('ticket:list', eproj)
    ectrl = json.load(open(ctrl_path))
    erows = [t for t in ectrl.get('tickets', []) if t.get('project') == eproj]
    emit({'ok': True, 'result': {'count': len(erows), 'tickets': erows}})
tool = None
payload = {}
try:
    i = args.index('call')
    tool = args[i + 1] if i + 1 < len(args) else None
    if i + 2 < len(args):
        payload = json.loads(args[i + 2])
except (ValueError, IndexError, json.JSONDecodeError):
    tool = None
if not isAdmin or tool not in ('ticket', 'workflow'):
    os.execv(REAL, [REAL] + args)  # admin 面外 op：透传真解释器
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
  delete env.SANDBAR_PROJECTS_YAML;
  env.SANDBAR_TARGET_HOST = DEAD_TEMPORAL;
  delete env.SANDBAR_NAMESPACE;
  env.FIX17_CTRL = stub.ctrlPath;
  env.FIX17_TRACE = stub.tracePath;
  // 引擎通道夹具仓（t260910-04 起 handleTickets 直调 runPocCli→client.py；其 python
  // 解析 venv 优先、PATH shim 被短路）——造一个 .venv/bin/python=桩 shim 的假引擎仓，
  // SANDBAR_REPO 把 workbench 的 repo 锚（config.repo ?? SANDBAR_REPO ?? 位置推导）
  // 指过去，引擎通道才落进桩的拦截面。client.py 只放占位（桩按 argv 拦 ticket-list，
  // 拦截面外的引擎调用炸得响=干净失败，不静默漏真 Temporal）。
  const engineRepo = path.join(stub.dir, 'engine-repo');
  const venvBin = path.join(engineRepo, 'server', 'engine', '.venv', 'bin');
  mkdirSync(venvBin, { recursive: true });
  writeFileSync(path.join(engineRepo, 'server', 'engine', 'client.py'),
    '# fix17 夹具占位：引擎通道由 FIX17 桩按 argv 拦截（ticket-list）；拦截面外到此=桩缺口\n');
  try { unlinkSync(path.join(venvBin, 'python')); } catch { /* 首次无 */ }
  symlinkSync(path.join(stub.dir, 'python3'), path.join(venvBin, 'python'));
  // repo 其余可读面投影（t260910-04 验收补）：docs 路由读 <repo>/docs|notes（真库定稿
  // 知识库），repo 锚到夹具仓后必须把这两面软链回真树，否则 t260905-06 文档族
  // 「真库篇目」断言全数假红（260910 实测：docs 树=0 篇）。软链=只读投影，不写真树。
  for (const face of ['docs', 'notes']) {
    const dest = path.join(engineRepo, face);
    try { unlinkSync(dest); } catch { /* 首次无 */ }
    symlinkSync(path.join(REPO_ROOT, face), dest);
  }
  env.SANDBAR_REPO = engineRepo;
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
  const laneProfile = path.join(REPO_ROOT, 'server', 'profile');
  const mainProfileNm = path.join(mainRoot(), 'server', 'profile', 'node_modules');
  const profDir = path.join(tmpHome, 'profiles', 'suyou');
  await mkdir(profDir, { recursive: true });
  for (const f of ['cordis.yml', 'cordis.patch.yml', 'package.json']) {
    const src = path.join(laneProfile, f);
    if (existsSync(src)) await copyFile(src, path.join(profDir, f));
  }
  const tsTools = path.join(laneProfile, 'sandbar-tools.ts');
  if (existsSync(tsTools)) await symlink(tsTools, path.join(profDir, 'sandbar-tools.ts'));
  const nm = path.join(profDir, 'node_modules');
  await mkdir(nm, { recursive: true });
  if (!existsSync(mainProfileNm)) throw new Error(`主树插件依赖缺失：${mainProfileNm} 不存在（env FIX17_MAIN_ROOT 可指主树根）`);
  let overridden = false;
  for (const name of readdirSync(mainProfileNm)) {
    const dest = name === 'sandbar-workbench' ? laneWorkbenchDir
      : (() => { try { return realpathSync(path.join(mainProfileNm, name)); } catch { return null; } })();
    if (!dest) continue;
    await symlink(dest, path.join(nm, name));
    if (name === 'sandbar-workbench') overridden = true;
  }
  if (!overridden) throw new Error(`主树 profile/node_modules 缺 sandbar-workbench：${mainProfileNm}`);
  return profDir;
}

async function waitReady(port, timeoutMs, logPath) {
  const url = `http://127.0.0.1:${port}/sandbar-workbench/api/wf/projects`;
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

/** 自举隔离台（票源=FIX17 桩；env PATH 前置 shim 目录）。失败抛错由调用方转环境红（env_fail 点名）。 */
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
    await buildProfile(tmpHome, path.join(REPO_ROOT, 'server', 'plugins', 'workbench'));
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

/** playwright-core 四路探测（t260904-15 同口径）。null=调用方转环境红（env_fail 点名，KI-036）。 */
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
