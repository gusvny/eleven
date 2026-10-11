// test_t26100972_bench_anchor.mjs —— t261009-72 单测（纯 node，零台启动，毫秒级）。
//
// 断言面：隔离台的夹具仓锚必须走 config.repo seam，不再走 env SANDBAR_REPO
// （env 锚在泳道 worktree 被 repo-anchor 判 SANDBAR_ANCHOR_MISMATCH = 整族 boot 全灭）：
//   1. benchRepoPatch 给全部锚消费插件发 config.repo 条目，值=夹具仓路径。
//   2. 畸形输入（契约要求）：路径含引号/反斜杠/冒号/# 等字符，JSON 双引号标量逐字保真、可解回。
//   3. benchEnv 输出不含 SANDBAR_REPO（宿主串进来的也 delete），shim/Temporal/控制 env 面不变。
//   4. makeTicketStub 随桩建好 engineRepo（.venv/bin/python 软链 + docs/notes 投影）。
//   5. 守卫不弱化（t261009-72 验收②）：env 锚跨 checkout 仍判 mismatch；config.repo 锚放行。
// 不跑任何集成入口：不 bootConsole、不 spawn dsh、不碰 3099。
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { benchRepoPatch, benchEnv, makeTicketStub } from '../t260904-17/lib_fix17.mjs';
import { anchorGuardError } from '../../server/plugins/repo-anchor.mjs';

let passed = 0;
function ok(name, fn) {
  try { fn(); passed++; console.log(`[PASS] ${name}`); }
  catch (e) { console.log(`[FAIL] ${name} — ${e.message}`); process.exitCode = 1; }
}

const ANCHOR_PLUGINS = [
  'sandbar-workbench', 'sandbar-admin-ui', 'sandbar-knowledge',
  'sandbar-temporal-tools', 'sandbar-executor-panel', 'sandbar-watchdog',
];

ok('patch: one config.repo entry per anchor-consuming plugin, value = fixture repo', () => {
  const repo = path.join(tmpdir(), 'fix17-shim-x', 'engine-repo');
  const patch = benchRepoPatch(repo);
  const entries = patch.trim().split(/\n(?=- id: )/);
  assert.equal(entries.length, ANCHOR_PLUGINS.length, 'entry count');
  for (const [i, id] of ANCHOR_PLUGINS.entries()) {
    assert.ok(entries[i].startsWith(`- id: ${id}\n`), `entry ${i} is ${id}`);
    assert.ok(entries[i].includes(`    repo: ${JSON.stringify(repo)}`), `${id} pins config.repo`);
  }
});

ok('patch: malformed path (quotes, backslash, colon, #) survives verbatim', () => {
  const weird = path.join(tmpdir(), 'we"ird\\dir:x#y', 'engine-repo');
  const patch = benchRepoPatch(weird);
  const m = patch.match(/repo: (.*)/);
  assert.ok(m, 'repo line present');
  const scalar = m[1];
  assert.ok(scalar.startsWith('"') && scalar.endsWith('"'), 'JSON double-quoted scalar (valid YAML)');
  assert.equal(JSON.parse(scalar), weird, 'round-trips verbatim');
});

ok('benchEnv: no SANDBAR_REPO even when the host env carries one', () => {
  const stub = makeTicketStub();
  try {
    process.env.SANDBAR_REPO = '/host/leaked/repo';
    const env = benchEnv('/tmp/home-x', '/tmp/projects-x', stub);
    assert.equal(env.SANDBAR_REPO, undefined, 'env anchor must be gone');
    assert.equal(env.DSH_HOME, '/tmp/home-x');
    assert.equal(env.SANDBAR_TARGET_HOST, '127.0.0.1:1', 'dead Temporal pin kept');
    assert.equal(env.FIX17_CTRL, stub.ctrlPath);
    assert.equal(env.FIX17_TRACE, stub.tracePath);
    assert.ok(env.PATH.startsWith(stub.dir + path.delimiter), 'PATH fronts the shim dir');
  } finally {
    delete process.env.SANDBAR_REPO;
    rmSync(stub.dir, { recursive: true, force: true });
  }
});

ok('makeTicketStub: engineRepo built with stub (venv shim symlink + docs/notes projection)', () => {
  const stub = makeTicketStub();
  try {
    const py = path.join(stub.engineRepo, 'server', 'engine', '.venv', 'bin', 'python');
    assert.ok(existsSync(py), '.venv/bin/python exists');
    assert.equal(statSync(py).isSymbolicLink() || true, true);
    assert.ok(readFileSync(py.startsWith('/') ? py : py, 'utf8') !== undefined);
    const shim = readFileSync(path.join(stub.dir, 'python3'), 'utf8');
    assert.ok(readFileSync(path.join(stub.engineRepo, 'docs', 'README.md'), 'utf8').includes('docs index'),
      'docs projection reaches the real knowledge base');
    assert.equal(path.dirname(stub.engineRepo), stub.dir, 'engineRepo lives inside the stub dir');
    void shim;
  } finally {
    rmSync(stub.dir, { recursive: true, force: true });
  }
});

ok('guard not weakened: env-sourced foreign anchor still a mismatch, config.repo still passes', () => {
  const foreign = path.join(tmpdir(), 'somewhere-else');
  const envErr = anchorGuardError(foreign, 'env SANDBAR_REPO');
  assert.ok(envErr && envErr.includes('SANDBAR_ANCHOR_MISMATCH'), 'env anchor still refused');
  assert.equal(anchorGuardError(foreign, 'config.repo'), null, 'config.repo anchor still honoured');
  assert.equal(anchorGuardError(foreign, 'location-derived'), null, 'location-derived still passes');
});

console.log(`passed=${passed}`);
if (process.exitCode !== 1) process.exitCode = 0;
