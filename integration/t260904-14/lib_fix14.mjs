// lib_fix14.mjs — t260904-14 场景共享脚手架（非 sc_ 前缀 = 共享代码，不登记、不报警）。
// 沿 lib_fix10.mjs 模式复制改造（跨票目录不引用，票① lib 不被本票写集耦合）。
// 只用 node stdlib；零真台零 3099/7233/8233。断言锚公开契约（CLI 旗标面/装载器/报告
// 词汇/env 契约），不锚实现内部结构。
//
// 本票特有两件缝（gen2 方案 R2/C3 定稿）：
// 1. 桩 poc_dir：`--root <stub>` 全局旗标 → InstallPaths.poc_dir=<stub>/server/dsh/
//    temporal-poc（runtime.py L54 缝）。桩内放真身 shared.py（复制，注册表根仍走
//    SANDBAR_PROJECTS_DIR env）+ 假 client.py（票号级 ticket-list 通道替身，行为由
//    FIX14_CTRL 控制文件驱动：ok/exit/badjson/sdk 四模）。在飞闸语义腿全部走此缝，
//    不可 SKIP（C3 表）。
// 2. 真票腿：本库提供 temporalite 自举探测（provisionRealRig），任一依赖缺席=有声
//    SKIP（唯一豁免腿，C3 表）。
import { spawnSync, spawn } from 'node:child_process';
import {
  mkdtempSync, readFileSync, writeFileSync, mkdirSync, existsSync,
  readdirSync, statSync, copyFileSync,
} from 'node:fs';
import { createHash } from 'node:crypto';
import { createConnection, createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SANDBAR = path.join(REPO_ROOT, 'sandbar');
export const POC_REAL = path.join(REPO_ROOT, 'server', 'dsh', 'temporal-poc');
export const DEAD_TARGET = '127.0.0.1:1';

export function tmpRoot(prefix) {
  return mkdtempSync(path.join(tmpdir(), prefix));
}

// 注册表根隔离（env 契约）+ legacy env 只在 legacy 腿显式注入（沿 lib_fix10 语义）
export function sbEnv(root, extra = {}) {
  const env = { ...process.env, SANDBAR_PROJECTS_DIR: root };
  delete env.SUYOU_PROJECTS_YAML;
  delete env.SUYOU_TARGET_HOST;   // 票计数通道 env 只逐腿显式注入，防 ambient 外溢生产 7233
  delete env.SUYOU_NAMESPACE;
  return Object.assign(env, extra);
}

// CLI 真跑。args 里调用方自行放 '--root'（全局旗标必须在子命令前——argparse 语义）。
export function runCli(args, env) {
  const r = spawnSync('python3', [SANDBAR, ...args], {
    cwd: REPO_ROOT, env, encoding: 'utf8', timeout: 120000,
  });
  const code = r.status === null ? -1 : r.status;
  let out = (r.stdout || '');
  if (r.stderr && r.stderr.trim()) out += '\n--stderr--\n' + r.stderr;
  return { code, out };
}

// Python 侧装载探针（公开装载器 shared.load_projects_registry；真身 poc，cwd=仓根）
export function pyRegistry(root, extraEnv = {}) {
  const code = [
    "import sys,json",
    "sys.path.insert(0,'server/dsh/temporal-poc')",
    "import shared",
    "p,q=shared.load_projects_registry()",
    "print(json.dumps({'projects':p,'quarantined':q}))",
  ].join(';');
  const r = spawnSync('python3', ['-c', code], {
    cwd: REPO_ROOT, env: sbEnv(root, extraEnv), encoding: 'utf8', timeout: 60000,
  });
  if (r.status !== 0) throw new Error('python 装载探针失败: ' + (r.stderr || r.stdout || ''));
  return JSON.parse(r.stdout);
}

// 非抛版按 key 查询探针（空表抛错语义面=lookup_project→assert_registry_nonempty，
// 契约①a「零条目=抛错列原因」的落地面）：返回 {code,out}
export function pyLookupRaw(root, key, extraEnv = {}) {
  const code = [
    "import sys,json",
    "sys.path.insert(0,'server/dsh/temporal-poc')",
    "import shared",
    "p=shared.lookup_project(" + JSON.stringify(key) + ")",
    "print(json.dumps(p))",
  ].join(';');
  const r = spawnSync('python3', ['-c', code], {
    cwd: REPO_ROOT, env: sbEnv(root, extraEnv), encoding: 'utf8', timeout: 60000,
  });
  return { code: r.status === null ? -1 : r.status, out: (r.stdout || '') + (r.stderr || '') };
}

export function extractJson(out) {
  const t = (out || '').trim();
  if (!t) return null;
  try { return JSON.parse(t); } catch { /* fallthrough */ }
  const lines = t.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const cand = lines.slice(i).join('\n').trim();
    if (!cand.startsWith('{') && !cand.startsWith('[')) continue;
    try { return JSON.parse(cand); } catch { /* keep looking */ }
  }
  return null;
}

export function deepFind(obj, keyName, keyVal, hits = []) {
  if (Array.isArray(obj)) { obj.forEach((x) => deepFind(x, keyName, keyVal, hits)); return hits; }
  if (obj && typeof obj === 'object') {
    if (obj[keyName] === keyVal) hits.push(obj);
    Object.values(obj).forEach((x) => deepFind(x, keyName, keyVal, hits));
  }
  return hits;
}

// 全树字节快照：相对路径 → 目录标记/内容 sha256 前缀+字节数（零现场变更/字节不变断言基线）
export function treeSnapshot(dir) {
  const out = {};
  if (!existsSync(dir)) return out;
  const walk = (rel) => {
    const abs = path.join(dir, rel);
    const st = statSync(abs);
    if (st.isDirectory()) {
      out[rel + '/'] = '<dir>';
      for (const n of readdirSync(abs).sort()) walk(path.join(rel, n));
    } else {
      const h = createHash('sha256').update(readFileSync(abs)).digest('hex').slice(0, 20);
      out[rel] = h + ':' + String(st.size);
    }
  };
  for (const n of readdirSync(dir).sort()) walk(n);
  return out;
}

// 子树不变断言辅助：before 中以 prefix（'data/' 等）开头的键在 after 中全等
export function subtreeUnchanged(before, after, prefix) {
  const bk = Object.keys(before).filter((k) => k.startsWith(prefix));
  return bk.every((k) => after[k] === before[k]) &&
    Object.keys(after).filter((k) => k.startsWith(prefix)).length === bk.length;
}

// fixture 注册条目（schema v1 严格子集）
export function writeProjectEntry(root, key, name, dirs) {
  const d = path.join(root, key);
  mkdirSync(d, { recursive: true });
  const lines = [
    '# fixture entry (t260904-14 场景自建，非真源)',
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

// ①c 归档 fixture：variant = valid | missing（目录在 manifest 缺）| badjson | noschema
export function writeArchive(root, key, id, variant = 'valid') {
  const d = path.join(root, key, 'data', 'tickets', id);
  mkdirSync(path.join(d, 'stages'), { recursive: true });
  writeFileSync(path.join(d, 'stages', 'stage_t.json'), '{"note":"fixture"}');
  if (variant === 'missing') return; // 目录在、archive.json 缺 = ①c 缺失态（未归档）
  if (variant === 'badjson') {
    writeFileSync(path.join(d, 'archive.json'), '{oops-not-json');
    return;
  }
  if (variant === 'noschema') {
    writeFileSync(path.join(d, 'archive.json'), JSON.stringify({ ticket_id: id }));
    return;
  }
  writeFileSync(path.join(d, 'archive.json'), JSON.stringify({
    schema: 'v1', ticket_id: id, legacy: false, archived_at: '2026-09-04T00:00:00Z',
    meta: {}, files: [], absent: [], excluded_rules: [], reason: 'fixture t260904-14',
  }));
}

// 项目根 .lane/ 泳道残骸 fixture（验收10：报告只报不删）
export function writeLaneDebris(projectDir, tid) {
  mkdirSync(path.join(projectDir, '.lane', tid), { recursive: true });
  writeFileSync(path.join(projectDir, '.lane', tid, 'note.txt'), 'lane debris fixture\n');
}

// ---------- 桩 poc_dir（在飞闸语义腿的注入缝，C3 表：不可 SKIP 腿全走这里） ----------

const CLIENT_SHIM = `# t260904-14 场景桩：client.py ticket-list 通道替身（行为由 FIX14_CTRL 控制文件驱动）
import json, os, sys
ctrl = json.load(open(os.environ['FIX14_CTRL']))
mode = ctrl.get('mode', 'ok')
if mode == 'exit':
    sys.stderr.write(ctrl.get('stderr', 'stub: channel unreachable') + '\\n')
    sys.exit(int(ctrl.get('code', 3)))
if mode == 'badjson':
    print('not-json-at-all')
    sys.exit(0)
if mode == 'sdk':
    sys.stderr.write("ModuleNotFoundError: No module named 'temporalio'\\n")
    sys.exit(1)
# 真通道语义：按 ProjectKey（sa_project）过滤——桩必须同构，否则他票串账（tk1 教训）
args = {}
if len(sys.argv) > 2:
    try:
        args = json.loads(sys.argv[2])
    except ValueError:
        args = {}
proj = str(args.get('project') or '')
rows = [t for t in ctrl.get('tickets', [])
        if not proj or t.get('sa_project', '') == proj]
print(json.dumps({'ok': True, 'result': {'tickets': rows}}))
`;

export function makeStubRoot() {
  const stubRoot = tmpRoot('fix14-stub-');
  const poc = path.join(stubRoot, 'server', 'dsh', 'temporal-poc');
  mkdirSync(poc, { recursive: true });
  copyFileSync(path.join(POC_REAL, 'shared.py'), path.join(poc, 'shared.py'));
  const ctrlPath = path.join(stubRoot, 'ctrl.json');
  writeFileSync(ctrlPath, JSON.stringify({ mode: 'ok', tickets: [] }));
  writeFileSync(path.join(poc, 'client.py'), CLIENT_SHIM);
  return {
    stubRoot, poc, ctrlPath,
    setCtrl(obj) { writeFileSync(ctrlPath, JSON.stringify(obj)); },
    // remove 命令面（桩缝：--root 指桩树；注册表根仍走 SANDBAR_PROJECTS_DIR）
    remove(regRoot, key, flags = [], extraEnv = {}) {
      return runCli(
        ['--root', stubRoot, 'project', 'remove', '--key', key, ...flags],
        sbEnv(regRoot, { FIX14_CTRL: ctrlPath, ...extraEnv }));
    },
  };
}

// ---------- 真票腿自举（C3 唯一有声 SKIP 豁免腿）：依赖齐才跑，缺什么报什么 ----------

function probeTcp(port, host = '127.0.0.1', timeoutMs = 800) {
  return new Promise((resolve) => {
    const s = createConnection(port, host);
    s.setTimeout(timeoutMs);
    s.on('connect', () => { s.destroy(); resolve(true); });
    s.on('error', () => resolve(false));
    s.on('timeout', () => { s.destroy(); resolve(false); });
  });
}

export function freePort() {
  return new Promise((resolve) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
  });
}

// 返回 { ok, reason?, target?, namespace?, child? }——调用方负责 finally 里 kill child。
export async function provisionRealRig() {
  // 依赖①：CLI 子进程同款解释器可 import temporalio（remove 的票通道用 sys.executable）
  const imp = spawnSync('python3', ['-c', 'import temporalio'], { encoding: 'utf8' });
  if (imp.status !== 0) return { ok: false, reason: 'python3 缺 temporalio SDK' };
  // 依赖②：temporal 二进制（env 显式指路 或 PATH）
  const bin = process.env.SANDBAR_TEST_TEMPORAL_BIN || 'temporal';
  const ver = spawnSync(bin, ['--version'], { encoding: 'utf8' });
  if (ver.status !== 0) return { ok: false, reason: `temporal 二进制不可用（${bin}）` };
  // 依赖③：自举 start-dev（dev server；namespace 用 default，SUYOU_NAMESPACE 同步钉）
  const port = await freePort();
  const db = path.join(tmpRoot('fix14-rig-'), 'dev.db');
  const child = spawn(bin, [
    'server', 'start-dev', '--ip', '127.0.0.1', '--port', String(port),
    '--db', db, '--log-level', 'error',
  ], { stdio: 'ignore' });
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await probeTcp(port, '127.0.0.1', 500)) {
      return { ok: true, target: `127.0.0.1:${port}`, namespace: 'default', child };
    }
    if (child.exitCode !== null) return { ok: false, reason: 'temporal start-dev 秒退' };
    await new Promise((r) => setTimeout(r, 400));
  }
  child.kill('TERM');
  return { ok: false, reason: 'temporal start-dev 20s 未就绪' };
}

// 断言收集器（沿 lib_fix10 语义）
export function makeChecks(title) {
  const oks = [];
  const fails = [];
  return {
    check(name, cond, detail = '') {
      if (cond) { oks.push(name); return; }
      fails.push(name);
      console.log(`  [FAIL] ${name}${detail ? ' — ' + detail : ''}`);
    },
    skip(name, reason = '') {
      console.log(`  [SKIP] ${name}${reason ? '：' + reason : ''}`);
    },
    finish() {
      console.log(`\n${title}: pass=${oks.length} fail=${fails.length}`);
      if (fails.length > 0) {
        console.log(`RESULT FAIL (${fails.length})`);
        process.exit(1);
      }
      console.log('RESULT PASS');
    },
  };
}
