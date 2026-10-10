#!/usr/bin/env node
/**
 * sc_t26091626_boot_evidence.mjs — a lane-bench boot failure on the t260916-26
 * face leaves evidence a steward can attribute (ticket t261009-73).
 *
 * Run directly: node integration/t260916-26/sc_t26091626_boot_evidence.mjs
 * (cwd = repo root), or through the registry entry in integration/run_scenarios.py.
 *
 * Grey-box L3, offline seconds, zero docker / Temporal-server / real browser,
 * never touches 3099/7233. The incident: the t260916-26 bench lib carries a
 * line-copy of lib_fix17's boot skeleton whose readiness timeout threw a message
 * pointing at a console.log that bootLaneConsole's own clean() deleted on the
 * failure path — the same unattributable-boot-failure shape t261009-70 fixed on
 * the fix17 face (that face owns the generic contract; entry
 * t261009-70-boot-evidence). This entry owns the SAME user-perceivable contract
 * on the t260916-26 bench lib, one family member over:
 *
 *   A named boot failure: the failure path annotates the error with the
 *   console's own last words — a bounded tail of the log, plus the timeout /
 *   failure context.
 *   Evidence survives reclamation: the message names a survivor log path
 *   OUTSIDE the temp home that clean() deletes, and that file exists holding
 *   the log's content after the temp home is gone.
 *   Honesty on malformed evidence: a missing / empty log degrades to a NAMED
 *   absence inside the message — no fabricated lines, no secondary misleading
 *   error; a present but non-UTF8 log is EVIDENCE, not absence: the survivor
 *   copy is byte-exact and the quoted tail names the lossy decode instead of
 *   printing replacement garbage.
 *   One annotation, not two: an error that already carries its own snapshot
 *   (dedupe marker `log preserved at`) is left unchanged.
 *   The gate stays honest: a boot failure is still a failure — the bench lib
 *   never converts a rejection into a resolution, and a boot that fails before
 *   any log exists rejects NAMED with zero fabricated survivor files.
 *
 * Face: the PUBLIC exports of integration/t260916-26/lib_t260916_26_bench.mjs
 * (the evidence seam `attachBootEvidence(err, logPath, label)` pinned by the
 * reviewed plan, plus `bootLaneConsole`), discovered by contract name — a
 * contract-preserving refactor that keeps the exports green stays green; a
 * missing capability is a NAMED FAIL (TDD signal pre-implement). The real 45 s
 * spawn path is NOT exercised (browser family's job, same split as the fix17
 * entry); timeouts are injected short.
 *
 * Pre-implement tree red on A-F = the expected TDD signal; green required at
 * the integration gate / merge. The bench lib unparseable = ENV_FAIL exit 2.
 */
import { mkdtempSync, writeFileSync, rmSync, existsSync, readFileSync, readdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { specCase, emitCase } from '../lib_result.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const started = Date.now();
const cases = [];

function record(name, status, reason, evidence) {
  cases.push({ name, status, reason, evidence });
  emitCase({ name, suite: 't260916-26-boot-evidence', status,
    cause: status === 'fail' ? 'self' : 'unknown',
    reason, evidence, dur_s: (Date.now() - started) / 1000 });
}

// ---- load the contract face -------------------------------------------------
let bench = null;
try {
  bench = await import(path.toNamespacedPath(path.join(REPO, 'integration/t260916-26/lib_t260916_26_bench.mjs')));
} catch (e) {
  console.error(`ENV_FAIL: integration/t260916-26/lib_t260916_26_bench.mjs unimportable: ${e}`);
  process.exit(2);
}

// ---- A: contract discovery --------------------------------------------------
const seam = bench.attachBootEvidence;
if (typeof seam !== 'function') {
  record('lane-bench-boot-evidence', 'fail',
    'missing capability: lib_t260916_26_bench.mjs does not export attachBootEvidence (contract face absent)',
    'import succeeded but typeof attachBootEvidence !== function');
  process.exit(1);
}

const TAIL_MARK = 'LANE-BENCH-LAST-WORDS line-999';

/** Temp home with a console.log of the given shape. */
function makeHome(logContent) {
  const tmpHome = mkdtempSync(path.join(os.tmpdir(), 't26100973-home-'));
  const logPath = path.join(tmpHome, 'console.log');
  if (logContent !== undefined) writeFileSync(logPath, logContent);
  return { tmpHome, logPath };
}

function survivorsNow() {
  return new Set(readdirSync(os.tmpdir()).filter((n) => n.startsWith('fix17-console-')));
}

// ---- B + reclamation invariant: annotation carries tail + living survivor ----
{
  const { tmpHome, logPath } = makeHome(`boot line 1\nport bind ok\n${TAIL_MARK}\n`);
  let annotated = null;
  let secondary = null;
  try {
    annotated = seam(new Error('隔离台就绪超时（45s）：log=' + logPath), logPath, 'lane-bench');
  } catch (e) { secondary = e; }
  rmSync(tmpHome, { recursive: true, force: true }); // the caller's reclamation, before the steward reads
  const misses = [];
  if (secondary) misses.push(`evidence attachment threw a secondary error: ${secondary}`);
  else {
    const msg = String(annotated && annotated.message);
    if (!/超时|time|ready/i.test(msg)) misses.push('message lost the timeout context');
    if (!msg.includes(TAIL_MARK)) misses.push('message does not quote the log tail');
    if (!msg.includes('log tail:') || !msg.includes('full log preserved at:')) {
      misses.push('message does not use the shared evidence phrases (log tail: / full log preserved at:)');
    }
    const paths = msg.match(/\/\S*console[^\s'"]*/g) || [];
    const survivor = paths.find((p) => existsSync(p) && !p.startsWith(tmpHome));
    if (!survivor) misses.push('message names no existing survivor path outside the reclaimed temp home');
    else if (!readFileSync(survivor, 'utf8').includes(TAIL_MARK)) {
      misses.push('survivor file exists but lost the log content');
    }
  }
  record('lane-bench-boot-annotates-and-survives', misses.length ? 'fail' : 'pass',
    misses.length ? misses.join('; ')
      : 'annotated rejection carries timeout + tail + survivor that outlives the reclamation',
    `msg=${JSON.stringify(String(annotated && annotated.message).slice(0, 300))} tmpHome=${tmpHome}`);
}

// ---- C: the tail is bounded, not the whole log ------------------------------
{
  const big = Array.from({ length: 20000 }, (_, i) => `filler line ${i}`).join('\n') + `\n${TAIL_MARK}\n`;
  const { tmpHome, logPath } = makeHome(big);
  let annotated = null;
  try { annotated = seam(new Error('boot timeout'), logPath, 'lane-bench'); } catch { /* below */ }
  const msg = annotated ? String(annotated.message) : '';
  const ok = annotated && msg.includes(TAIL_MARK) && msg.length < 20000;
  record('lane-bench-tail-is-bounded', ok ? 'pass' : 'fail',
    ok ? `message carries the LAST line while staying bounded (${msg.length} chars for a ${(big.length / 1024) | 0}KB log)`
       : `message unbounded or missing tail: len=${msg.length}`,
    `msgLen=${msg.length} logLen=${big.length}`);
  rmSync(tmpHome, { recursive: true, force: true });
}

// ---- D: malformed evidence degrades to a NAMED absence / byte-exact survivor -
for (const [label, content] of [['missing', undefined], ['empty', ''],
    ['binary', Buffer.from([0xff, 0xfe, 0x00, 0x01, 0x9c])]]) {
  const { tmpHome, logPath } = makeHome(content);
  let annotated = null;
  let secondary = null;
  try { annotated = seam(new Error('boot timeout'), logPath, 'lane-bench'); } catch (e) { secondary = e; }
  const msg = annotated ? String(annotated.message) : (secondary ? String(secondary) : '');
  const named = /absent|unreadable|empty|not valid UTF-8|不存在|无日志/i.test(msg);
  let ok;
  if (label === 'binary') {
    const m = msg.match(/full log preserved at: (\S+)/);
    const exact = !!m && existsSync(m[1]) && Buffer.compare(readFileSync(m[1]), content) === 0;
    ok = !secondary && exact && !msg.includes('\uFFFD');
  } else {
    ok = !secondary && named && !/filler line|LAST-WORDS/i.test(msg);
  }
  record(`lane-bench-${label}-log-named`, ok ? 'pass' : 'fail',
    ok ? `${label} log handled honestly inside the annotation`
       : `${label} log: named=${named} secondary=${!!secondary} msg=${msg.slice(0, 160)}`,
    `msg=${JSON.stringify(msg.slice(0, 240))}`);
  rmSync(tmpHome, { recursive: true, force: true });
}

// ---- E: one annotation, not two ---------------------------------------------
{
  const { tmpHome, logPath } = makeHome(`first tail\n`);
  const before = `boot timeout\nlog tail: "kept"; full log preserved at: /tmp/kept.log`;
  const err = new Error(before);
  let out = null;
  let secondary = null;
  try { out = seam(err, logPath, 'lane-bench'); } catch (e) { secondary = e; }
  const msg = out ? String(out.message) : '';
  const ok = !secondary && msg.includes('kept') && !msg.includes('first tail');
  record('lane-bench-no-double-annotation', ok ? 'pass' : 'fail',
    ok ? 'an error already carrying its own snapshot (dedupe marker) is left unchanged'
       : `double annotation or secondary throw: secondary=${!!secondary} msg=${msg.slice(0, 160)}`,
    `msg=${JSON.stringify(msg.slice(0, 240))}`);
  rmSync(tmpHome, { recursive: true, force: true });
}

// ---- F: pre-log boot failure stays a NAMED failure, zero fabricated evidence -
{
  const before = survivorsNow();
  const hostileHome = mkdtempSync(path.join(os.tmpdir(), 't26100973-hostile-'));
  const prev = process.env.FIX17_MAIN_ROOT;
  process.env.FIX17_MAIN_ROOT = path.join(hostileHome, 'no-such-main-tree');
  let err = null;
  try { await bench.bootLaneConsole(path.join(hostileHome, 'projects'), { dir: hostileHome, ctrlPath: path.join(hostileHome, 'ctrl.json'), tracePath: path.join(hostileHome, 'trace.jsonl') }); }
  catch (e) { err = e; }
  finally {
    if (prev === undefined) delete process.env.FIX17_MAIN_ROOT; else process.env.FIX17_MAIN_ROOT = prev;
  }
  const after = survivorsNow();
  const fabricated = [...after].filter((n) => !before.has(n));
  const msg = err ? String(err.message || err) : '(resolved)';
  const ok = err && !msg.includes('log tail:') && fabricated.length === 0;
  record('lane-bench-pre-log-failure-named-no-fabrication', ok ? 'pass' : 'fail',
    ok ? 'boot failure before any log exists rejects named, quoting nothing, fabricating no survivor'
       : `resolved=${!err} evidenceQuotedWithoutLog=${msg.includes('log tail:')} fabricatedSurvivors=${fabricated.join(',') || 'none'} msg=${msg.slice(0, 160)}`,
    `msg=${JSON.stringify(msg.slice(0, 240))} fabricated=${fabricated.length}`);
  rmSync(hostileHome, { recursive: true, force: true });
}

// ---- verdict ---------------------------------------------------------------
const fails = cases.filter((c) => c.status === 'fail');
if (fails.length) {
  console.error(`FAIL t260916-26 boot evidence: ${fails.length}/${cases.length} red — first: ${fails[0].name}: ${fails[0].reason}`);
  process.exit(1);
}
console.log(`PASS t260916-26 boot evidence: ${cases.length}/${cases.length} green`);
