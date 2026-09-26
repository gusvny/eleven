// lib_fix14.mjs — t260904-14 场景共享脚手架（非 sc_ 前缀 = 共享代码，不登记、不报警）。
// 沿 lib_fix10.mjs 模式复制改造（跨票目录不引用，票① lib 不被本票写集耦合）。
// 只用 node stdlib；零真台零 3099/7233/8233。断言锚公开契约（CLI 旗标面/装载器/报告
// 词汇/env 契约），不锚实现内部结构。
//
// 本票特有两件缝（gen2 方案 R2/C3 定稿）：
// 1. 桩 poc_dir：`--root <stub>` 全局旗标 → InstallPaths.poc_dir=<stub>/server/
//    engine（runtime.py L54 缝）。桩内放真身 shared.py（复制，注册表根仍走
//    SANDBAR_PROJECTS_DIR env）+ 假 client.py（票号级 ticket-list 通道替身，行为由
//    FIX14_CTRL 控制文件驱动：ok/exit/badjson/sdk 四模）。在飞闸语义子用例全部走此缝，
//    无环境依赖（C3 表）。
// 2. 真票子用例：本库提供 temporalite 自举探测（provisionRealRig），任一依赖缺席=
//    env_fail（三态契约 §7.3：缺测试环境绝不 exit 0 假绿，exit 2；C3 表唯一豁免子用例）。
import { spawnSync, spawn } from 'node:child_process';
import {
  mkdtempSync, readFileSync, writeFileSync, mkdirSync, existsSync, rmSync,
  readdirSync, statSync, copyFileSync,
} from 'node:fs';
import { createHash } from 'node:crypto';
import { createConnection, createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SANDBAR = path.join(REPO_ROOT, 'sandbar');
export const POC_REAL = path.join(REPO_ROOT, 'server', 'engine');
export const DEAD_TARGET = '127.0.0.1:1';

// 260926 磁盘泄漏修（同类普查）：tmpRoot 建的夹具目录此前从不回收——宿主 $TMPDIR 实测
// `fix14-*` 攒了 37519 个 / 约 1.76GB（13.9 天）。进程任何终态（正常/走完/抛异常/process.exit）统一同步回收；
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

// 注册表根隔离（env 契约）+ legacy env 只在 legacy 查询路径显式注入（沿 lib_fix10 语义）
export function sbEnv(root, extra = {}) {
  const env = { ...process.env, SANDBAR_PROJECTS_DIR: root };
  delete env.SANDBAR_PROJECTS_YAML;
  delete env.SANDBAR_TARGET_HOST;   // 票计数通道 env 只逐子用例显式注入，防 ambient 外溢生产 7233
  delete env.SANDBAR_NAMESPACE;
  return Object.assign(env, extra);
}

// CLI 真跑。args 里调用方自行放 '--root'（全局旗标必须在子命令前——argparse 语义）。
// 解释器必须用带 temporalio 的那支（enginePy：venv 优先）——installer 内部用
// sys.executable 起票号通道（projects.py L404/518），系统 python3 无 SDK 时
// CLI 子用例会假报 sdk-missing（260908 实锤）。
export function runCli(args, env) {
  const r = spawnSync(enginePy() || 'python3', [SANDBAR, ...args], {
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
    "sys.path.insert(0,'server/engine')",
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
    "sys.path.insert(0,'server/engine')",
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

// ---------- 桩 poc_dir（在飞闸语义子用例的注入缝，C3 表：零环境依赖语义子用例全走这里） ----------

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
  const poc = path.join(stubRoot, 'server', 'engine');
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

// ---------- 真票子用例自举（C3 唯一 env_fail 豁免子用例）：依赖齐才跑，缺什么报什么 ----------

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

/** 引擎解释器解析：优先仓内 venv（temporalio 真源），回落 PATH python3。
 *  返回可执行路径或 null（两路都缺 SDK）。真票子用例与 client.py 直呼必须用同一个。 */
export function enginePy() {
  const candidates = [
    path.join(POC_REAL, '.venv', 'bin', 'python'),
    'python3',
  ];
  for (const c of candidates) {
    const r = spawnSync(c, ['-c', 'import temporalio'], { encoding: 'utf8' });
    if (r.status === 0) return c;
  }
  return null;
}

// 返回 { ok, reason?, target?, namespace?, child? }——调用方负责 finally 里 kill child。
export async function provisionRealRig() {
  // 依赖①：解释器可 import temporalio——优先引擎 venv（仓内真源），回落 python3
  // （260908 修：此前只探 python3，宿主系统解释器无 SDK 时真票子用例恒 env_fail）。
  const py = enginePy();
  if (!py) return { ok: false, reason: '无可用 temporalio SDK（引擎 venv 与 python3 均缺）' };
  // 依赖②：temporal 二进制（env 显式指路 > 仓内 bin/（引擎同款 dev server 真源）
  // > PATH）——260908 修：此前只探 PATH，仓内自带二进制被漏探，真票子用例恒 env_fail。
  const bin = process.env.SANDBAR_TEST_TEMPORAL_BIN
    || [path.join(POC_REAL, 'bin', 'temporal'), 'temporal']
      .find((c) => spawnSync(c, ['--version'], { encoding: 'utf8' }).status === 0);
  if (!bin) return { ok: false, reason: 'temporal 二进制不可用（env SANDBAR_TEST_TEMPORAL_BIN 可指路）' };
  // 依赖③：自举 start-dev（dev server；namespace 用 default，SANDBAR_NAMESPACE 同步钉）
  const port = await freePort();
  const db = path.join(tmpRoot('fix14-rig-'), 'dev.db');
  const child = spawn(bin, [
    'server', 'start-dev', '--ip', '127.0.0.1', '--port', String(port),
    '--db-filename', db, '--log-level', 'error',
  ], { stdio: 'ignore' });
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await probeTcp(port, '127.0.0.1', 500)) {
      // 依赖④：default namespace 注册 ProjectKey/EpicCode SA——fresh start-dev 不带 SA，
      // 在飞闸按 ProjectKey 过滤查询会报 invalid search attribute 而假红（260908 实锤）。
      // 幂等（容忍 already exist）；注册不上=env_fail 不硬跑。
      const target = `127.0.0.1:${port}`;
      let saErr = '';
      for (const name of ['ProjectKey', 'EpicCode']) {
        const p = spawnSync(bin, ['operator', 'search-attribute', 'create',
          '--namespace', 'default', '--name', name, '--type', 'Keyword',
          '--address', target], { encoding: 'utf8', timeout: 15000 });
        const low = ((p.stdout || '') + (p.stderr || '')).toLowerCase();
        if (p.status !== 0 && !low.includes('already exist') &&
            !low.includes('already defined') && !low.includes('already registered')) {
          saErr = ((p.stderr || '') + (p.stdout || '')).trim().split('\n').filter(Boolean).pop() || 'rc 非零无输出';
          break;
        }
      }
      if (saErr) {
        child.kill('SIGTERM');
        return { ok: false, reason: `SA 注册失败（default ns）：${saErr}` };
      }
      return { ok: true, target, namespace: 'default', child };
    }
    if (child.exitCode !== null) return { ok: false, reason: 'temporal start-dev 秒退' };
    await new Promise((r) => setTimeout(r, 400));
  }
  child.kill('TERM');
  return { ok: false, reason: 'temporal start-dev 20s 未就绪' };
}

// 断言收集器（四态：pass/fail/env_fail/na，三态契约 §7.3——缺环境=env_fail
// 绝不 exit 0 假绿；exit 码 f>0→1，e>0→2，否则 0）
export function makeChecks(title) {
  const oks = [];
  const fails = [];
  const envFails = [];
  return {
    check(name, cond, detail = '') {
      if (cond) { oks.push(name); return; }
      fails.push(name);
      console.log(`  [FAIL] ${name}${detail ? ' — ' + detail : ''}`);
    },
    envFail(name, reason = '') {
      envFails.push(name);
      console.log(`  [ENV_FAIL] ${name}${reason ? '：' + reason : ''}`);
    },
    finish() {
      console.log(`\n${title}: pass=${oks.length} fail=${fails.length} env_fail=${envFails.length} na=0`);
      if (fails.length > 0) {
        console.log(`RESULT FAIL (${fails.length})`);
        process.exit(1);
      }
      if (envFails.length > 0) {
        console.log(`RESULT ENV_FAIL (${envFails.length})`);
        process.exit(2);
      }
      console.log('RESULT PASS');
    },
  };
}
