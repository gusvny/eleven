// test_t261009_70_boot_evidence.mjs —— t261009-70 单测（纯 node，零台启动，毫秒级）。
//
// 断言面：隔离台 boot 失败必须留下证据（t261009-70）：
//   1. captureBootFailure 正常路径：tail 有界、survivor 文件落在 $TMPDIR 且内容保全、
//      文件名带 label（steward 归因面）。
//   2. 畸形输入（契约要求）：log 缺失 / 空 / 不可读 / 超 256KB 截界 —— honest 报告，
//      helper 不抛。
//   3. waitReady 超时路径：抛错文本带 log tail + survivor 路径（不再只是裸超时），
//      survivor 确实存在。
// 不跑任何集成入口：不 bootConsole、不 spawn dsh、不碰 3099。
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, chmodSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { captureBootFailure, waitReady } from '../t260904-17/lib_fix17.mjs';

let passed = 0;
function ok(name, fn) {
  try { fn(); passed++; console.log(`[PASS] ${name}`); }
  catch (e) { console.log(`[FAIL] ${name} — ${e.message}`); process.exitCode = 1; }
}

const dir = mkdtempSync(path.join(tmpdir(), 't26100970-test-'));
const survivorsAtStart = new Set(
  readdirSync(tmpdir()).filter((n) => n.startsWith('fix17-console-')),
);

ok('capture: normal log → bounded tail, survivor exists with full content and label', () => {
  const log = path.join(dir, 'console.log');
  writeFileSync(log, 'line1\ndsh web: http://127.0.0.1:5/p?token=abc\nline3\n');
  const { survivor, tail } = captureBootFailure(log, 't26100953-lanemap');
  assert.ok(survivor, 'survivor path expected');
  assert.ok(path.dirname(survivor) === tmpdir(), 'survivor must live in $TMPDIR, outside tmpHome');
  assert.ok(path.basename(survivor).includes('t26100953-lanemap'), 'survivor name carries label');
  assert.ok(readFileSync(survivor, 'utf8').includes('token=abc'), 'survivor holds log content');
  assert.ok(tail.includes('token=abc') && tail.length <= 4000, 'tail bounded and informative');
  rmSync(survivor);
});

ok('capture: oversized log → survivor capped at 256KB and holds the tail end', () => {
  const log = path.join(dir, 'big.log');
  writeFileSync(log, 'HEAD-MARKER' + 'x'.repeat(300 * 1024) + 'TAIL-MARKER');
  const { survivor, tail } = captureBootFailure(log, 'big');
  assert.ok(survivor, 'survivor expected');
  const saved = readFileSync(survivor, 'utf8');
  assert.ok(saved.length <= 256 * 1024, `survivor bounded, got ${saved.length}`);
  assert.ok(!saved.includes('HEAD-MARKER'), 'head dropped');
  assert.ok(saved.endsWith('TAIL-MARKER'), 'tail end preserved');
  assert.ok(tail.includes('TAIL-MARKER') && tail.length <= 4000, 'message tail bounded');
  rmSync(survivor);
});

ok('capture: absent log → honest marker, no survivor, no throw', () => {
  const { survivor, tail } = captureBootFailure(path.join(dir, 'nope.log'), 'absent');
  assert.equal(survivor, null);
  assert.ok(tail.includes('absent or unreadable'), tail);
});

ok('capture: empty log → honest marker, no survivor', () => {
  const log = path.join(dir, 'empty.log');
  writeFileSync(log, '');
  const { survivor, tail } = captureBootFailure(log, 'empty');
  assert.equal(survivor, null);
  assert.ok(tail.includes('empty'), tail);
});

ok('capture: unreadable log (chmod 000) → honest marker, no throw', () => {
  const log = path.join(dir, 'locked.log');
  writeFileSync(log, 'secret');
  chmodSync(log, 0o000);
  try {
    const { survivor, tail } = captureBootFailure(log, 'locked');
    assert.equal(survivor, null);
    assert.ok(tail.includes('absent or unreadable'), tail);
  } finally { chmodSync(log, 0o644); }
});

ok('capture: non-UTF8 log → byte-exact survivor, tail names the lossy decode (no replacement garbage)', () => {
  const log = path.join(dir, 'bin.log');
  const raw = Buffer.from([0xff, 0xfe, 0x00, 0x01, 0x9c]);
  writeFileSync(log, raw);
  const { survivor, tail } = captureBootFailure(log, 'bin');
  assert.ok(survivor && existsSync(survivor), 'survivor expected');
  assert.equal(Buffer.compare(readFileSync(survivor), raw), 0, 'survivor is byte-exact (rework 261010: utf8 cut corrupted binary logs)');
  assert.ok(!tail.includes('\uFFFD'), `no replacement garbage in tail: ${JSON.stringify(tail)}`);
  assert.ok(/not valid UTF-8/.test(tail), `tail names the lossy decode: ${tail}`);
  rmSync(survivor);
});

ok('capture: valid-UTF8 log larger than tail bound still quotes its real text tail', () => {
  const log = path.join(dir, 'bigutf.log');
  writeFileSync(log, ' '.repeat(5000) + 'REAL-LAST-LINE');
  const { survivor, tail } = captureBootFailure(log, 'bigutf');
  assert.ok(tail.endsWith('REAL-LAST-LINE'), 'clean text tail preserved even past the char bound');
  assert.ok(!/not valid UTF-8/.test(tail), 'valid UTF-8 must not be misnamed lossy');
  rmSync(survivor);
});

ok('capture: hostile label chars sanitized for the survivor filename', () => {
  const log = path.join(dir, 'l.log');
  writeFileSync(log, 'x');
  const { survivor } = captureBootFailure(log, '../../evil name;rm');
  assert.ok(survivor && /^[\w.-]+$/.test(path.basename(survivor)), `safe name, got ${survivor}`);
  rmSync(survivor);
});

try {
  // dead port (127.0.0.1:1) → every probe fails fast; 1ms timeout → immediate timeout path
  const log = path.join(dir, 'wait.log');
  writeFileSync(log, 'dsh: fatal: profile loader cannot resolve plugin X\n');
  await assert.rejects(
    () => waitReady(1, 1, log, 'ready-wait-test'),
    (e) => {
      const m = String(e.message);
      assert.ok(m.includes('not ready in 0s'), `names the timeout: ${m}`);
      assert.ok(m.includes('log tail:'), `carries the tail: ${m}`);
      assert.ok(m.includes('profile loader cannot resolve plugin X'), `quotes log lines: ${m}`);
      const s = m.match(/full log preserved at: (\S+)/);
      assert.ok(s && existsSync(s[1]), `survivor exists: ${m}`);
      rmSync(s[1]);
      return true;
    },
  );
  passed++;
  console.log('[PASS] waitReady timeout: error names the reason with tail + survivor path');
} catch (e) {
  console.log(`[FAIL] waitReady timeout evidence — ${e.message}`);
  process.exitCode = 1;
}

// reclamation invariant: tmpHome deletion still removes the original log; only the
// survivor (validated above, cleaned per-case) may outlive it. Simulate by rm'ing dir.
ok('reclaim: original log gone with tmpHome while survivor already captured', () => {
  const home = mkdtempSync(path.join(tmpdir(), 'fix17-bench-test-'));
  const log = path.join(home, 'console.log');
  writeFileSync(log, 'evidence');
  const { survivor } = captureBootFailure(log, 'reclaim');
  assert.ok(readFileSync(survivor, 'utf8') === 'evidence');
  rmSync(home, { recursive: true, force: true });
  assert.ok(!existsSync(log), 'original deleted with tmpHome (unchanged reclamation)');
  assert.ok(existsSync(survivor), 'survivor outlives it');
  rmSync(survivor);
});

// no stray survivor files leaked by this run
ok('no survivor leak: this test cleaned up every file it created', () => {
  const now = new Set(
    readdirSync(tmpdir()).filter((n) => n.startsWith('fix17-console-')),
  );
  for (const n of now) if (!survivorsAtStart.has(n)) rmSync(path.join(tmpdir(), n));
  assert.equal(now.size - survivorsAtStart.size, 0, 'all survivors cleaned');
});

rmSync(dir, { recursive: true, force: true });
console.log(`SUMMARY pass=${passed} fail=${process.exitCode ? 1 : 0}`);
