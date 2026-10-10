// test_t26100916_26_boot_evidence.mjs — t261009-73 unit tier (node, no external
// sources, no console boot). Asserts the evidence contract of
// integration/t260916-26/lib_t260916_26_bench.mjs:
//   1. waitReady timeout REJECTS (never resolves) with the fix17 evidence template:
//      timeout seconds + bounded tail + survivor path.
//   2. Survivor lives under $TMPDIR (outside the reclaimed tmpHome) and survives a
//      simulated rmSync of the temp home; content matches the log tail.
//   3. Bounded tail on a large log keeps the LAST line, never the whole file.
//   4. Honesty on malformed evidence: missing/empty log → named absence, no
//      survivor, no fabricated lines; non-UTF8 log → named lossy decode +
//      byte-exact survivor; unreadable log → named absence.
//   5. attachBootEvidence: appends evidence before reclamation, dedupes on the
//      "log preserved at" marker, is a no-op for a missing log, never masks the
//      original error message.
//   6. Hostile label chars (label derives from consumer input basename) sanitized.
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, chmodSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { waitReady, attachBootEvidence } from '../t260916-26/lib_t260916_26_bench.mjs';
import { captureBootFailure } from '../t260904-17/lib_fix17.mjs';

let pass = 0;
function ok(name) { pass++; console.log(`  ok ${name}`); }

const dir = mkdtempSync(path.join(tmpdir(), 't26100973-test-'));

// 1+2: waitReady timeout rejection carries tail + survivor; survivor outlives reclamation
{
  const home = mkdtempSync(path.join(tmpdir(), 't26100973-home-'));
  const log = path.join(home, 'console.log');
  writeFileSync(log, 'boot line 1\nboot line 2\nlast words before death\n');
  let err = null;
  try { await waitReady(1, 1, log); } catch (e) { err = e; }
  assert.ok(err, 'waitReady resolved on a dead port — a boot failure became a pass');
  assert.match(err.message, /not ready in 0s/);
  assert.match(err.message, /env red/);
  assert.match(err.message, /last words before death/);
  const m = err.message.match(/full log preserved at: (\S+)/);
  assert.ok(m, 'message does not name a survivor path');
  const survivor = m[1];
  assert.ok(survivor.startsWith(tmpdir()), `survivor not under $TMPDIR: ${survivor}`);
  assert.ok(!survivor.startsWith(home), 'survivor inside the reclaimed temp home');
  assert.ok(existsSync(survivor), 'survivor missing');
  assert.match(readFileSync(survivor, 'utf8'), /last words before death/);
  rmSync(home, { recursive: true, force: true }); // the reclamation that used to destroy the evidence
  assert.ok(existsSync(survivor), 'survivor deleted by reclamation');
  assert.ok(!existsSync(log), 'precondition: original log IS reclaimed');
  ok('waitReady timeout: rejection with tail + survivor that outlives reclamation');
}

// 3: bounded tail on a large log keeps the LAST line only
{
  const big = Array.from({ length: 5000 }, (_, i) => `line ${i}`).join('\n');
  const log = path.join(dir, 'big.log');
  writeFileSync(log, big);
  let err = null;
  try { await waitReady(1, 1, log); } catch (e) { err = e; }
  assert.ok(err && err.message.length < 8000, 'message not bounded');
  assert.match(err.message, /line 4999/, 'tail lost the LAST line');
  assert.doesNotMatch(err.message, /line 100 /, 'whole file leaked into the message');
  ok('large log: bounded message keeps the last line');
}

// 4a: missing log → named absence, no fabricated lines
{
  let err = null;
  try { await waitReady(1, 1, path.join(dir, 'nope.log')); } catch (e) { err = e; }
  assert.ok(err);
  assert.match(err.message, /absent or unreadable/);
  assert.match(err.message, /full log preserved at: \(copy failed or log empty\)/,
    'named absence must not present a survivor path');
  ok('missing log: named absence');
}

// 4b: empty log → named absence
{
  const log = path.join(dir, 'empty.log');
  writeFileSync(log, '');
  let err = null;
  try { await waitReady(1, 1, log); } catch (e) { err = e; }
  assert.ok(err);
  assert.match(err.message, /console\.log empty/);
  ok('empty log: named absence');
}

// 4c: unreadable log → named absence (malformed-input case)
{
  const log = path.join(dir, 'locked.log');
  writeFileSync(log, 'secret');
  chmodSync(log, 0o000);
  let err = null;
  try { await waitReady(1, 1, log); } catch (e) { err = e; }
  assert.ok(err);
  assert.match(err.message, /absent or unreadable/);
  chmodSync(log, 0o644);
  ok('unreadable log: named absence');
}

// 4d: non-UTF8 log → named lossy decode + byte-exact survivor (evidence, not absence)
{
  const log = path.join(dir, 'bin.log');
  writeFileSync(log, Buffer.from([0x68, 0x65, 0xff, 0xfe, 0x00, 0x01]));
  let err = null;
  try { await waitReady(1, 1, log); } catch (e) { err = e; }
  assert.ok(err);
  assert.match(err.message, /not valid UTF-8/);
  const m = err.message.match(/full log preserved at: (\S+)/);
  assert.ok(m, 'binary log lost its survivor');
  assert.deepEqual(readFileSync(m[1]), Buffer.from([0x68, 0x65, 0xff, 0xfe, 0x00, 0x01]),
    'survivor is not byte-exact');
  ok('binary log: named lossy decode + byte-exact survivor');
}

// 5: attachBootEvidence — append, dedupe, missing-log no-op, original message kept
{
  const log = path.join(dir, 'ev.log');
  writeFileSync(log, 'the real cause: EADDRINUSE\n');
  const e1 = new Error('profile build failed');
  attachBootEvidence(e1, log, 'case5');
  assert.match(e1.message, /^profile build failed/);
  assert.match(e1.message, /boot failure evidence/);
  assert.match(e1.message, /the real cause: EADDRINUSE/);
  assert.match(e1.message, /full log preserved at: \S/);
  const before = e1.message;
  attachBootEvidence(e1, log, 'case5');
  assert.equal(e1.message, before, 'double attachment');
  const e2 = new Error('no log case');
  attachBootEvidence(e2, path.join(dir, 'absent.log'), 'case5');
  assert.match(e2.message, /absent or unreadable/, 'missing log degrades to a named absence');
  assert.match(e2.message, /full log preserved at: \(copy failed\)/, 'named absence must not invent a survivor path');
  ok('attachBootEvidence: append + dedupe + missing-log named absence');
}

// 6: hostile label chars sanitized (label derives from basename(projectsRoot))
{
  const log = path.join(dir, 'hostile.log');
  writeFileSync(log, 'x\n');
  const { survivor } = captureBootFailure(log, '../../evil name;rm');
  assert.ok(survivor.startsWith(tmpdir()));
  assert.doesNotMatch(path.basename(survivor), /[^A-Za-z0-9._-]/);
  assert.ok(existsSync(survivor));
  ok('hostile label: sanitized into the survivor filename');
}

rmSync(dir, { recursive: true, force: true });
console.log(`RESULT PASS (${pass} cases)`);
