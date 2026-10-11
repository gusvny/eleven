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

// t261009-72 harness invariant (read before touching the repo anchor again):
//   The bench console's OWN TREE is the lane worktree this module is loaded from —
//   the plugins load from there, so `repo-anchor.mjs` derives the guard's own root
//   from that tree, and a lane worktree must never receive writes aimed at another
//   checkout. The shim fixture repo (`$TMPDIR/fix17-shim-*/engine-repo`) is NOT that
//   tree: it is SERVED FIXTURE DATA the harness owns for the length of one scenario —
//   a `.venv/bin/python` symlink onto the stub shim (engine channel interception) plus
//   read-only `docs`/`notes` projections of the real knowledge base. Because it is
//   foreign, the fixture repo must be declared through the documented primary seam —
//   per-plugin `config.repo` in the harness-generated profile patch (see
//   `benchRepoPatch`) — never through `env SANDBAR_REPO`. The env seam is exactly what
//   `repo-anchor.mjs` refuses in lane worktrees (`SANDBAR_ANCHOR_MISMATCH`, the
//   t261009-72 root cause: every lib_fix17 scenario env-failed at the 45 s boot);
//   `config.repo` is an explicit, co-located choice by the process owner, which the
//   guard deliberately honours. Do NOT weaken the guard to re-admit the env seam.

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
/** 造引擎通道夹具仓（t260910-04 起 handleTickets 直调 runPocCli→client.py；其 python
 * 解析 venv 优先、PATH shim 被短路）——在 <stubDir>/engine-repo 造一个
 * .venv/bin/python=桩 shim 的假引擎仓，插件 repo 锚指过去，引擎通道才落进桩的
 * 拦截面。client.py 只放占位（桩按 argv 拦 ticket-list，拦截面外的引擎调用炸得响=
 * 干净失败，不静默漏真 Temporal）。t261009-72 起独立导出：makeTicketStub 建桩时
 * 一并调用；自带 stub 的调用方（如 t261009-03 的透传桩）由 bootConsole 兜底调用，
 * 路径同款，shim 内的锚替换不受影响。 */
export function buildEngineRepo(stubDir) {
  const engineRepo = path.join(stubDir, 'engine-repo');
  const venvBin = path.join(engineRepo, 'server', 'engine', '.venv', 'bin');
  mkdirSync(venvBin, { recursive: true });
  writeFileSync(path.join(engineRepo, 'server', 'engine', 'client.py'),
    '# fix17 夹具占位：引擎通道由 FIX17 桩按 argv 拦截（ticket-list）；拦截面外到此=桩缺口\n');
  try { unlinkSync(path.join(venvBin, 'python')); } catch { /* 首次无 */ }
  symlinkSync(path.join(stubDir, 'python3'), path.join(venvBin, 'python'));
  // repo 其余可读面投影（t260910-04 验收补）：docs 路由读 <repo>/docs|notes（真库定稿
  // 知识库），repo 锚到夹具仓后必须把这两面软链回真树，否则 t260905-06 文档族
  // 「真库篇目」断言全数假红（260910 实测：docs 树=0 篇）。软链=只读投影，不写真树。
  for (const face of ['docs', 'notes']) {
    const dest = path.join(engineRepo, face);
    try { unlinkSync(dest); } catch { /* 首次无 */ }
    symlinkSync(REPO_ROOT + '/' + face, dest);
  }
  return engineRepo;
}

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
# 优先解析会短路 PATH shim，靠夹具仓（stub.dir/engine-repo，经 config.repo 锚补丁
# 声明，t261009-72）把 .venv/bin/python 符链回本桩，引擎通道才落得进拦截面。
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
  // 引擎通道夹具仓随桩一并建好（bootConsole 靠它生成 config.repo 锚补丁，见模块头）。
  const engineRepo = buildEngineRepo(dir);
  return {
    dir, ctrlPath, tracePath, engineRepo,
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

/** 隔离台进程 env（t261009-72 起导出供单测断言面）。
 * 锚纪律见模块头：夹具仓经 benchRepoPatch 的 config.repo 声明——env SANDBAR_REPO
 * 在泳道 worktree 里会被 repo-anchor 判 SANDBAR_ANCHOR_MISMATCH（boot 全灭根因），
 * 这里显式 delete，防宿主环境串进来的 SANDBAR_REPO 复活同一条错锚。 */
export function benchEnv(tmpHome, projectsRoot, stub) {
  const env = { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: projectsRoot };
  delete env.SANDBAR_PROJECTS_YAML;
  delete env.SANDBAR_REPO;
  env.SANDBAR_TARGET_HOST = DEAD_TEMPORAL;
  delete env.SANDBAR_NAMESPACE;
  env.FIX17_CTRL = stub.ctrlPath;
  env.FIX17_TRACE = stub.tracePath;
  env.PATH = `${stub.dir}${path.delimiter === ':' ? ':' : ':'}${process.env.PATH || ''}`;
  return env;
}

/** 锚补丁插件面：隔离台里所有走共享锚链（config.repo → SANDBAR_REPO → 位置推导）的
 * 插件都把 repo 显式钉到夹具仓——与旧 env.SANDBAR_REPO 的可见面逐插件对齐
 * （t261009-72 前=六个插件全读到 env；现在=同六插件全读到 config.repo，行为等价，
 * 只是锚来源换了 seam）。config.repo 是 repo-anchor 判定的 documented primary seam，
 * 泳道 worktree 里也放行。 */
const ANCHOR_PLUGIN_IDS = [
  'sandbar-workbench',
  'sandbar-admin-ui',
  'sandbar-knowledge',
  'sandbar-temporal-tools',
  'sandbar-executor-panel',
  'sandbar-watchdog',
];

/** 生成把各插件 repo 锚钉到夹具仓的 patch 追加块（t261009-72）。
 * 纯函数，单测断言面。路径用 JSON 双引号标量（合法 YAML），$tmpdir 含引号/反斜杠/
 * 冒号/# 等畸形字符也逐字保真。 */
export function benchRepoPatch(engineRepo) {
  const repo = JSON.stringify(String(engineRepo));
  return ANCHOR_PLUGIN_IDS.map((id) => `- id: ${id}\n  config:\n    repo: ${repo}\n`).join('');
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

// t261009-70: a boot failure must leave evidence. The old behavior threw
// "隔离台就绪超时（45s）：log=<tmpHome>/console.log" and the caller's clean() deleted
// exactly that log on the way out, so "harness broken" was indistinguishable from
// "scenario boot path broken". Now: on timeout we read the log BEFORE reclamation,
// embed a bounded tail in the error text, and copy a bounded slice (last 256 KB) to a
// survivor file in $TMPDIR that no reclamation path touches. The machine-facing fact
// stays the scenario's env_fail exit code — the message text is for humans only; no
// parser may match on it (grep 261010: nothing matches the old string today either).
const LOG_TAIL_CHARS = 4000;
const SURVIVOR_MAX_BYTES = 256 * 1024;

/**
 * Snapshot console.log for a boot failure, before tmpHome reclamation deletes it.
 * Never throws: a missing/empty/unreadable log is reported honestly instead.
 *
 * Evidence contract (settled t261009-70 rework, byte-exact survivor):
 *   - a MISSING or EMPTY log is a NAMED ABSENCE (the worst lie would be to quote
 *     invented lines) — no survivor;
 *   - a PRESENT log gets a byte-exact survivor copy: the file is read as raw bytes
 *     and the last SURVIVOR_MAX_BYTES bytes are copied verbatim (rework item: the
 *     first cut read utf8 and corrupted binary logs — 5 non-UTF8 bytes came back as
 *     10 replacement-sequence bytes); console.log is a text face in practice, but
 *     the copy must never be lossier than the source;
 *   - the message tail is a TEXT face: a valid-UTF8 log quotes its last
 *     LOG_TAIL_CHARS chars; a log that is not valid UTF-8 names the lossy decode
 *     instead of printing replacement-character garbage (named absence stays
 *     reserved for missing/empty — present-but-binary is evidence, not absence).
 *
 * @returns {{survivor: string|null, tail: string}} survivor = preserved bounded log
 *   path (filename carries the label for attribution), or null; tail = bounded text
 *   for the error message.
 */
export function captureBootFailure(logPath, label = 'boot') {
  let bytes = null;
  try { bytes = readFileSync(logPath); } catch { /* absent or unreadable */ }
  if (!bytes) {
    return { survivor: null, tail: '(console.log absent or unreadable — child died before writing anything)' };
  }
  if (bytes.length === 0) {
    return { survivor: null, tail: '(console.log empty — child produced no output)' };
  }
  const safeLabel = String(label).replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 64) || 'boot';
  let survivor = null;
  try {
    const bounded = bytes.length > SURVIVOR_MAX_BYTES ? bytes.subarray(bytes.length - SURVIVOR_MAX_BYTES) : bytes;
    survivor = path.join(tmpdir(), `fix17-console-${safeLabel}-${Date.now()}-${process.pid}.log`);
    writeFileSync(survivor, bounded);
  } catch { survivor = null; /* copy failed: the tail in the message is the fallback */ }
  const strict = new TextDecoder('utf-8', { fatal: true });
  let tail;
  let textAll = null;
  try { textAll = strict.decode(bytes); } catch { textAll = null; }
  if (textAll !== null) {
    tail = textAll.slice(-LOG_TAIL_CHARS);
  } else {
    // not valid UTF-8: quote the tail only if the tail slice itself is clean text,
    // otherwise name the lossy decode instead of printing replacement garbage
    const loose = new TextDecoder('utf-8');
    const sliced = loose.decode(bytes.subarray(Math.max(0, bytes.length - LOG_TAIL_CHARS)));
    tail = sliced.includes('\uFFFD')
      ? `(console.log is ${bytes.length} bytes and not valid UTF-8 — text tail withheld rather than quoted as replacement garbage; byte-exact survivor preserved)`
      : sliced;
  }
  return { survivor, tail };
}

/** Build the ready-timeout error with embedded evidence (tail + survivor path). */
function bootFailureError(timeoutMs, logPath, label) {
  const { survivor, tail } = captureBootFailure(logPath, label);
  return new Error(
    `stage console not ready in ${Math.round(timeoutMs / 1000)}s (env red — boot failure, not a scenario fail); `
    + `log tail: ${JSON.stringify(tail)}; full log preserved at: ${survivor || '(copy failed or log empty)'}`,
  );
}

// t261009-70: exported for the contract face (sc_t26100970_boot_evidence.mjs +
// integration/tests/test_t261009_70_boot_evidence.mjs) — the timeout-under-test is
// injected short; the 45 s boot path stays the browser family's job.
export async function waitReady(port, timeoutMs, logPath, label = 'ready') {
  const url = `http://127.0.0.1:${port}/sandbar-workbench/api/wf/projects`;
  const t0 = Date.now();
  for (;;) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (r.ok) return;
    } catch { /* 未就绪，续等 */ }
    if (Date.now() - t0 > timeoutMs) throw bootFailureError(timeoutMs, logPath, label);
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
    const patchFile = path.join(tmpHome, 'bench.patch.yml');
    // 单个 patch 文件合并两面：webserver 端口 + 插件 repo 锚（t261009-72，见模块头不变量）。
    // 兜底 buildEngineRepo：自带 stub 的调用方（t261009-03 等）没带 engineRepo 时，
    // 在同款路径 <stub.dir>/engine-repo 现造，锚与其 shim 内替换路径必然一致。
    writeFileSync(patchFile, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`
      + benchRepoPatch(stub.engineRepo ?? buildEngineRepo(stub.dir)));
    const logFd = openSync(path.join(tmpHome, 'console.log'), 'a');
    const proc = spawn('dsh', ['--profile', 'suyou', '--patch', patchFile,
      '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
      cwd: REPO_ROOT, detached: true, stdio: ['ignore', logFd, logFd],
      env: benchEnv(tmpHome, projectsRoot, stub),
    });
    await waitReady(port, 45000, path.join(tmpHome, 'console.log'),
      `boot-${path.basename(String(projectsRoot))}`);
    const bench = {
      port, tmpHome, projectsRoot, proc, logFd, clean,
      base: `http://127.0.0.1:${port}`,
      /** 导航进本台控制台（带 token 首页跳一次落会话 cookie）。见 gotoConsole 头注。 */
      goto(page, options) { return gotoConsole(page, bench, options); },
      teardown() {
        if (proc.pid && proc.exitCode === null && proc.signalCode === null) {
          try { process.kill(-proc.pid, 'SIGTERM'); } catch { try { proc.kill('SIGKILL'); } catch { /* 已退 */ } }
        }
        try { closeSync(logFd); } catch { /* 已关 */ }
        clean();
      },
    };
    return bench;
  } catch (e) {
    // t261009-70: evidence before reclamation, for every failure path of bootConsole
    // (profile build, spawn, anything) — not just the waitReady timeout. Skip if the
    // error already carries its own snapshot (avoid duplicate attachment).
    try {
      const logPath = path.join(tmpHome, 'console.log');
      if (existsSync(logPath) && !(e instanceof Error && String(e.message).includes('log preserved at'))) {
        const { survivor, tail } = captureBootFailure(logPath,
          `bootfail-${path.basename(String(projectsRoot))}`);
        const note = `boot failure evidence — log tail: ${JSON.stringify(tail)}; full log preserved at: ${survivor || '(copy failed)'}`;
        if (e instanceof Error) e.message += `\n${note}`; else throw new Error(`${String(e)}\n${note}`);
      }
    } catch { /* evidence attachment must never mask the original failure */ }
    clean();
    throw e;
  }
}

export function teardownOnExit(teardown) {
  process.on('exit', teardown);
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130); });
}

/**
 * 取隔离台的**带 token 首页地址**（dsh 0.1.5 浏览器会话门，实测定性 260928）。
 *
 * 背景：dsh web 对首页与 /api 走「会话 cookie 认证」——匿名 GET `/` 恒 401
 * （body=`dsh web authentication required; ...`），页面里一个 DOM 都渲染不出来。
 * 历史绿跑用的是无此门的旧 bits，所以本夹具过去直接 `page.goto(base)` 才成立；
 * 现在必须先按 dsh 自己打印的那行
 *   `dsh web: http://127.0.0.1:<port>/?token=<launchToken>`
 * 走一次 `GET /?token=…`（303 + Set-Cookie），之后同源导航才有 DOM。
 * 不兑 token 的后果不是产品红而是**假红**（元素找不到被当成产品缺陷），故此处
 * 取不到就响亮 env_fail（exit 2），绝不回落成匿名 401 页继续断言——报错必须精确。
 *
 * @param bench bootConsole 返回值（读其 tmpHome/console.log）。
 * @param timeoutMs token 行可能晚于 API 就绪出现（loader settle 后才 announce），缺省等 20s。
 * @returns 带 token 的首页 URL；超时/日志畸形则打印 `ENV_FAIL: …` 并 exit 2。
 */
export async function benchAuthUrl(bench, timeoutMs = 20000) {
  if (bench.authUrl) return bench.authUrl;
  const logPath = path.join(bench.tmpHome, 'console.log');
  const t0 = Date.now();
  for (;;) {
    try {
      const log = readFileSync(logPath, 'utf8');
      const m = log.match(/https?:\/\/[^\s"'<>]*[?&]token=[A-Za-z0-9._~-]+/);
      if (m) { bench.authUrl = m[0]; return m[0]; }
    } catch { /* 日志尚未落盘：续等 */ }
    if (Date.now() - t0 > timeoutMs) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  const tail = (() => { try { return readFileSync(logPath, 'utf8').slice(-400); } catch { return '(读不到 console.log)'; } })();
  console.log(`ENV_FAIL: 隔离台未打印带 token 首页地址（等 ${timeoutMs}ms，日志尾=${JSON.stringify(tail)}）——dsh 浏览器会话门需 /?token= 兑换 cookie，拿不到不得按 401 页继续断言`);
  process.exit(2);
}

/**
 * 导航进隔离台控制台（带 token 首页跳一次，落会话 cookie）。
 * 401 页=环境红点名，不当作「元素缺席」的产品红。
 */
export async function gotoConsole(page, bench, options = {}) {
  const url = await benchAuthUrl(bench);
  const res = await page.goto(url, { waitUntil: 'domcontentloaded', ...options });
  const unauthorized = await page.evaluate(() => (document.body?.innerText ?? '').includes('authentication required')).catch(() => false);
  if (unauthorized || (res && res.status() === 401)) {
    console.log(`ENV_FAIL: 隔离台首页仍要求认证（token 兑换未生效，响应=${res ? res.status() : 'n/a'}）——环境红，不按缺元素判产品红`);
    process.exit(2);
  }
  return page;
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
