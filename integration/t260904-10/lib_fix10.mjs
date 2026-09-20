// lib_fix10.mjs — t260904-10 场景共享脚手架（非 sc_ 前缀 = 共享代码，不登记、不报警）。
// 只用 node stdlib；零真台零 3099/7233（Temporal 降级注入用死端口 127.0.0.1:1，
// 可达子用例探测只连测试台 17233）。断言锚公开契约（CLI 旗标面/装载器/env 契约），不锚实现。
import { spawnSync, spawn } from 'node:child_process';
import {
  mkdtempSync, readFileSync, writeFileSync, mkdirSync, existsSync,
  readdirSync, statSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SANDBAR = path.join(REPO_ROOT, 'sandbar');
export const DEAD_TARGET = '127.0.0.1:1';
export const TEST_TARGET = '127.0.0.1:17233';

export function tmpRoot(prefix) {
  return mkdtempSync(path.join(tmpdir(), prefix));
}

// 本票 CLI 契约面（三场景共同冻结；改动须三场景+ops 手册同步）：
//   python3 sandbar project add --key <key> --name <name> --dir <abs> [--dir <abs>]... [--json]
//   python3 sandbar project list [--json]
//   python3 sandbar project remove --key <key> [--json]
export function sbEnv(root, extra = {}) {
  const env = { ...process.env, SANDBAR_PROJECTS_DIR: root };
  delete env.SANDBAR_PROJECTS_YAML; // legacy env 只在 legacy 查询路径显式注入，绝不 ambient 泄漏
  return Object.assign(env, extra); // extra 在清理之后注入（legacy 查询路径靠它）
}

export function runCli(args, env) {
  const r = spawnSync('python3', [SANDBAR, ...args], {
    cwd: REPO_ROOT, env, encoding: 'utf8', timeout: 120000,
  });
  const code = r.status === null ? -1 : r.status;
  let out = (r.stdout || '');
  if (r.stderr && r.stderr.trim()) out += '\n--stderr--\n' + r.stderr;
  return { code, out };
}

// Python 侧装载探针（公开装载器 shared.load_projects_registry，cwd=仓根）
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

// --json 输出提取（契约：stdout 机器可判；信封形状不钉，容忍尾行/整段 JSON）
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

// 深度收集 obj[keyName]===keyVal 的对象（字段名 key=schema v1 词汇，可钉）
export function deepFind(obj, keyName, keyVal, hits = []) {
  if (Array.isArray(obj)) { obj.forEach((x) => deepFind(x, keyName, keyVal, hits)); return hits; }
  if (obj && typeof obj === 'object') {
    if (obj[keyName] === keyVal) hits.push(obj);
    Object.values(obj).forEach((x) => deepFind(x, keyName, keyVal, hits));
  }
  return hits;
}

// 注册表根快照：子目录名 → project.yaml 字节（零残留断言基线；.tmp. 泄漏在此现形）
export function snapshotRoot(root) {
  if (!existsSync(root)) return null;
  const out = {};
  for (const name of readdirSync(root).sort()) {
    const p = path.join(root, name);
    if (statSync(p).isDirectory()) {
      const py = path.join(p, 'project.yaml');
      out[name] = existsSync(py) ? readFileSync(py, 'utf8') : '<dir:no-project-yaml>';
    } else {
      out[name] = '<file>';
    }
  }
  return out;
}

export function assertNoTmpLeak(snapshot) {
  return !Object.keys(snapshot || {}).some((n) => n.includes('.tmp.'));
}

// fixture 注册条目（schema v1 严格子集；值不含 # / 换行）
export function writeProjectEntry(root, key, name, dirs) {
  const d = path.join(root, key);
  mkdirSync(d, { recursive: true });
  const lines = [
    '# fixture entry (t260904-10 场景自建，非真源)',
    'schema: v1',
    'project:',
    `  - key: ${key}`,
    `    name: ${name}`,
    '    dirs:',
    ...dirs.map((x) => `      - ${x}`),
    '',
  ];
  writeFileSync(path.join(d, 'project.yaml'), lines.join('\n'));
}

// add/remove 旗标面自适应（拼写无契约锚——epic/方案只钉命令族与 --json；语义钉全部硬）：
// 探针用非法 key（大写）保证两种拼法都零副作用（语义拒收 or 用法错，均不写注册表）。
let addSurfaceCache = null; // 'flag' | 'positional'
export function detectAddSurface(root) {
  if (addSurfaceCache) return addSurfaceCache;
  const probeDir = tmpRoot('fix10-surface-probe-');
  const probe = runCli(
    ['project', 'add', '--key', 'ZZPROBE', '--name', 'P', '--dir', probeDir], sbEnv(root));
  addSurfaceCache = /unrecognized arguments|the following arguments are required/i.test(probe.out)
    ? 'positional' : 'flag';
  return addSurfaceCache;
}

export function cliAdd(root, key, name, dirs, extraEnv = {}, asJson = false) {
  const jsonArgs = asJson ? ['--json'] : [];
  if (detectAddSurface(root) === 'flag') {
    return runCli(['project', 'add', '--key', key, '--name', name,
      ...dirs.flatMap((d) => ['--dir', d]), ...jsonArgs], sbEnv(root, extraEnv));
  }
  return runCli(['project', 'add', key, name, ...dirs, ...jsonArgs], sbEnv(root, extraEnv));
}

export function cliRemove(root, key, extraEnv = {}, asJson = false) {
  const jsonArgs = asJson ? ['--json'] : [];
  if (detectAddSurface(root) === 'flag') {
    return runCli(['project', 'remove', '--key', key, ...jsonArgs], sbEnv(root, extraEnv));
  }
  return runCli(['project', 'remove', key, ...jsonArgs], sbEnv(root, extraEnv));
}

// 断言收集器：逐条落地、末尾统一结算（fail>0 → exit 1）
export function makeChecks(title) {
  const oks = [];
  const fails = [];
  return {
    check(name, cond, detail = '') {
      if (cond) { oks.push(name); return; }
      fails.push(name);
      console.log(`  [FAIL] ${name}${detail ? ' — ' + detail : ''}`);
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
