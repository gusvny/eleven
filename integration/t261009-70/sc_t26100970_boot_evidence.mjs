#!/usr/bin/env node
/**
 * sc_t26100970_boot_evidence.mjs — a stage-console boot failure leaves evidence
 * a steward can attribute (ticket t261009-70).
 *
 * Run directly: node integration/t261009-70/sc_t26100970_boot_evidence.mjs
 * (cwd = repo root), or through the registry entry in integration/run_scenarios.py.
 *
 * Grey-box L3, offline seconds, zero docker / Temporal-server / real browser,
 * never touches 3099/7233. The incident (host report 261010): two tickets could
 * not be verified because the isolated stage console would not boot in 45 s and
 * the receipt named only "ready timeout" while pointing at a console.log the
 * harness's own reclamation had already deleted — "never ran" was
 * indistinguishable from "environment red". The user-perceivable contract this
 * entry owns:
 *
 *   A named boot failure: a readiness timeout rejects (never resolves) with a
 *   message that names the timeout AND carries the console's own last words —
 *   a bounded tail of the log, not just the timeout line.
 *   Evidence survives teardown: the message names a survivor log path OUTSIDE
 *   the temp home that the reclamation deletes, and that file exists with the
 *   log's content after the temp home is gone.
 *   Honesty on malformed evidence: a missing / empty / unreadable log degrades
 *   to a NAMED absence inside the message — the helper never throws a second,
 *   misleading error and never fabricates log lines.
 *   The gate stays honest: a boot failure is still a failure (the promise
 *   rejects); nothing here converts it into a pass.
 *
 * Face: the PUBLIC exports of integration/t260904-17/lib_fix17.mjs
 * (`waitReady` / a failure-capture export), discovered by contract name —
 * a contract-preserving refactor that keeps the exports green stays green;
 * a missing capability is a NAMED FAIL (TDD signal pre-implement). The 45 s
 * default and bootConsole's real spawn path are NOT exercised (that is the
 * browser family's job); the timeout under test is injected short.
 *
 * Pre-implement tree red on A/B/E = the expected TDD signal; green required at
 * the integration gate / merge. lib_fix17 unparseable = ENV_FAIL exit 2.
 */
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync, readFileSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { specCase, emitCase } from '../lib_result.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const started = Date.now();
const cases = [];
let envRed = null;

function record(name, status, reason, evidence) {
  cases.push({ name, status, reason, evidence });
  emitCase({ name, suite: 't261009-70-boot-evidence', status,
    cause: status === 'fail' ? 'self' : 'unknown',
    reason, evidence, dur_s: (Date.now() - started) / 1000 });
}

// ---- load the contract face -------------------------------------------------
let fix17 = null;
try {
  fix17 = await import(path.toNamespacedPath(path.join(REPO, 'integration/t260904-17/lib_fix17.mjs')));
} catch (e) {
  console.error(`ENV_FAIL: integration/t260904-17/lib_fix17.mjs unimportable: ${e}`);
  process.exit(2);
}
if (typeof fix17.waitReady !== 'function') {
  record('boot-failure-leaves-evidence', 'fail',
    'missing capability: lib_fix17.mjs does not export waitReady (contract face absent)',
    'import succeeded but typeof waitReady !== function');
  process.exit(1);
}

const TAIL_MARK = 'LAST-WORDS-BEFORE-DEATH line-999';

/** Build a temp home with a console.log of the given shape; returns {tmpHome, logPath}. */
function makeHome(logContent) {
  const tmpHome = mkdtempSync(path.join(os.tmpdir(), 't26100970-home-'));
  const logPath = path.join(tmpHome, 'console.log');
  if (logContent !== undefined) writeFileSync(logPath, logContent);
  return { tmpHome, logPath };
}

async function timeOutReady(tmpHome, logPath, timeoutMs) {
  // A guaranteed-dead port: this process holds no listener; port 1 on loopback
  // is refused without touching any real service (never 3099/7233).
  const t0 = Date.now();
  let err = null;
  try {
    await fix17.waitReady(1, timeoutMs, logPath);
  } catch (e) { err = e; }
  return { err, dur: Date.now() - t0 };
}

// ---- A + D: named rejection with tail + survivor, and it STAYS a failure ----
{
  const { tmpHome, logPath } = makeHome(`boot line 1\nport bind ok\n${TAIL_MARK}\n`);
  const { err } = await timeOutReady(tmpHome, logPath, 300);
  try {
    if (!err) throw new Error('waitReady resolved on a dead port — a boot failure became a pass');
    const msg = String(err.message || err);
    const misses = [];
    if (!/45|time|ready|超时/i.test(msg)) misses.push('message does not name the readiness timeout');
    if (!msg.includes(TAIL_MARK)) misses.push('message does not quote the log tail (the console\'s last words)');
    const paths = msg.match(/\/\S*console[^\s'"]*|\/\S*boot[^\s'"]*/g) || [];
    const survivor = paths.find((p) => existsSync(p) && !p.startsWith(tmpHome));
    if (!survivor) misses.push('message names no existing survivor log path outside the temp home');
    else {
      const survivorText = readFileSync(survivor, 'utf8');
      if (!survivorText.includes(TAIL_MARK)) misses.push('survivor file exists but lost the log content');
    }
    record('boot-timeout-names-reason-and-survivor', misses.length ? 'fail' : 'pass',
      misses.length ? misses.join('; ') : 'rejection carries timeout + tail + existing survivor outside tmpHome',
      `msg=${JSON.stringify(msg.slice(0, 300))} tmpHome=${tmpHome} survivor=${survivor || 'NONE'}`);
  } catch (e) {
    record('boot-timeout-names-reason-and-survivor', 'fail', String(e).slice(0, 300), `tmpHome=${tmpHome}`);
  }
  rmSync(tmpHome, { recursive: true, force: true });
}

// ---- B: the tail is bounded, not the whole log ----
{
  const big = Array.from({ length: 20000 }, (_, i) => `filler line ${i}`).join('\n')
    + `\n${TAIL_MARK}\n`;
  const { tmpHome, logPath } = makeHome(big);
  const { err } = await timeOutReady(tmpHome, logPath, 300);
  const msg = err ? String(err.message || err) : '';
  const ok = err && msg.includes(TAIL_MARK) && msg.length < 20000;
  record('boot-timeout-tail-is-bounded', ok ? 'pass' : 'fail',
    ok ? `message carries the LAST line while staying bounded (${msg.length} chars for a ${(big.length / 1024) | 0}KB log)`
       : `message unbounded or missing tail: len=${msg.length} hasTail=${msg.includes(TAIL_MARK)} rejected=${!!err}`,
    `msgLen=${msg.length} logLen=${big.length}`);
  rmSync(tmpHome, { recursive: true, force: true });
}

// ---- C: malformed evidence degrades to a NAMED absence, never a crash ----
for (const [label, content] of [
  ['missing', undefined],
  ['empty', ''],
  ['binary', Buffer.from([0xff, 0xfe, 0x00, 0x01, 0x9c])],
]) {
  const { tmpHome, logPath } = makeHome(content);
  let outcome;
  try {
    const { err } = await timeOutReady(tmpHome, logPath, 300);
    outcome = { rejected: !!err, msg: err ? String(err.message || err) : '(resolved)' };
  } catch (e) {
    outcome = { rejected: true, msg: `SECONDARY THROW: ${e}` };
  }
  const named = /absent|no console|读不到|cannot|unreadable|empty|not found|不存在/i.test(outcome.msg);
  // A MISSING or EMPTY log must be a NAMED ABSENCE (the worst lie would be to
  // quote invented lines). A PRESENT but non-UTF8 log is evidence, not
  // absence — the settled contract (rework 261010, aligns lib_fix17
  // captureBootFailure + the registry D text + this design doc): the survivor
  // copy is BYTE-EXACT (raw bytes in, raw bytes out — the first utf8-reading
  // cut corrupted binary logs), and the quoted tail names the lossy decode
  // instead of printing replacement garbage.
  let ok;
  if (label === 'binary') {
    const m = outcome.msg.match(/full log preserved at: (\S+)/);
    const raw = content;
    const exact = !!m && existsSync(m[1])
      && Buffer.compare(readFileSync(m[1]), raw) === 0;
    const noGarbage = !outcome.msg.includes('\uFFFD');
    ok = outcome.rejected && !outcome.msg.includes('SECONDARY THROW')
      && exact && noGarbage;
  } else {
    ok = outcome.rejected && named && !outcome.msg.includes('SECONDARY THROW');
  }
  record(`boot-timeout-${label}-log-named`, ok ? 'pass' : 'fail',
    ok ? `${label} log handled honestly inside the rejection`
       : `${label} log: rejected=${outcome.rejected} named=${named} msg=${outcome.msg.slice(0, 200)}`,
    `msg=${JSON.stringify(outcome.msg.slice(0, 240))}`);
  rmSync(tmpHome, { recursive: true, force: true });
}

// ---- verdict ---------------------------------------------------------------
const fails = cases.filter((c) => c.status === 'fail');
if (fails.length) {
  console.error(`FAIL t261009-70 boot evidence: ${fails.length}/${cases.length} red — first: ${fails[0].name}: ${fails[0].reason}`);
  process.exit(1);
}
console.log(`PASS t261009-70 boot evidence: ${cases.length}/${cases.length} green`);
