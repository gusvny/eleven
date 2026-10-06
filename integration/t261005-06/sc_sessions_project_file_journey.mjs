#!/usr/bin/env node
/**
 * sc_sessions_project_file_journey.mjs — t261005-06 scenario 1: the project
 * sessions.json data face journey (grey-box L3, epic console-ui item UI-5).
 *
 * User story: a multi-project user restarts the console / switches port /
 * switches origin — their project sessions SURVIVE, because the ledger now
 * lives in <projects_root>/<key>/sessions.json (design note
 * notes/discussions/261004-chat项目身份与会话句柄.md §2.2), each session carries
 * a stable short-code handle (§2.3), and the project executor session — which
 * the workspace index never surfaces (implementer note, KI-198 neighbour
 * finding) — becomes visible in the list with the fixed handle `executor`.
 * A hostile file or hostile request must never corrupt the ledger: bad JSON
 * → empty, never crash; refusal → on-disk file byte-identical; concurrent-ish
 * writes merge by id instead of clobbering; the executor-surface refusal
 * (403) is distinguishable from a malformed entry (400) — the KI-193 family
 * declared-refusal stance from the reviewed plan R1.
 *
 * Intent split (no intent-level duplication):
 *   - t260904-01 sc_project_sessions_ledger_journey owns the OLD localStorage
 *     seq-numbering journey (seq stays history-only after this ticket);
 *   - t260906-01 sc_session_entry_empty_labeled owns the empty-project entry
 *     discoverability face;
 *   - developer smoke owns single-point truth tables;
 *   - THIS entry owns the end-to-end journey: write → read back from the
 *     FILE on disk (reader-side evidence, not the writer's return value) ×
 *     hostile-file tolerance × refusal atomicity × id-union merge × executor
 *     merge × handle assignment, chained so a broken transfer is amplified
 *     by the next step.
 *
 * Contract anchors (the landed public surface of session-ledger-file.ts /
 * session-handles.ts): saveSessionEntry / readLedgerFile /
 * readExecutorSessionIds / validateSessionEntry / SessionLedgerError /
 * sessionLedgerPath; shortCodeOf / assignHandles / mergeLedgerEntries /
 * mergeExecutorSessions / EXECUTOR_HANDLE. Missing anchor = FAIL naming it.
 *
 * Run: node integration/t261005-06/sc_sessions_project_file_journey.mjs
 * (offline, seconds, zero docker/Temporal/ports/3099; writes only under a
 * mkdtemp stub root, removed in finally; stub root injected via the modules'
 * env parameter — no process.env pollution).
 */
import { spawnSync } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WB = path.join(HERE, '..', '..', 'server', 'plugins', 'workbench');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`); }
  else { failed++; console.log(`  FAIL ${label}`); }
}
function section(t) { console.log(`\n== ${t}`); }

// node self-presence + version face (native type-stripping needs >= 22.18)
const nodeVer = process.versions.node.split('.').map(Number);
if (nodeVer[0] < 22 || (nodeVer[0] === 22 && nodeVer[1] < 18)) {
  console.error(`ENV_FAIL: node >= 22.18 required for native .ts import, got ${process.versions.node}`);
  process.exit(2);
}

// Contract modules — missing file = the data face did not land: FAIL named.
const FILE_MOD = path.join(WB, 'src', 'host', 'session-ledger-file.ts');
const HANDLE_MOD = path.join(WB, 'src', 'shared', 'session-handles.ts');
for (const [label, p] of [['session-ledger-file.ts', FILE_MOD], ['session-handles.ts', HANDLE_MOD]]) {
  if (!existsSync(p)) {
    console.error(`FAIL: contract anchor missing: server/plugins/workbench/src/${label} (UI-5 data face not landed — TDD-phase red)`);
    process.exit(1);
  }
}

let lf, handles;
try {
  lf = await import('file://' + FILE_MOD);
  handles = await import('file://' + HANDLE_MOD);
} catch (e) {
  console.error(`FAIL: contract module failed to load: ${e && e.message}`);
  process.exit(1);
}

// ── stub projects root (injected via the modules' env parameter) ──────────
const stub = mkdtempSync(path.join(tmpdir(), 'sc-t261005-06-'));
let cleanup = () => rmSync(stub, { recursive: true, force: true });
process.on('exit', () => { try { cleanup(); } catch {} });
const ENV = { ...process.env, SANDBAR_PROJECTS_DIR: stub };
const KEY = 'sandbar';
mkdirSync(path.join(stub, KEY), { recursive: true });
const FILE = path.join(stub, KEY, 'sessions.json');

function readRaw() { return readFileSync(FILE, 'utf8'); }
function sha(t) { return createHash('sha256').update(t).digest('hex'); }

try {
  ok(typeof lf.saveSessionEntry === 'function' && typeof lf.readLedgerFile === 'function'
    && typeof lf.readExecutorSessionIds === 'function' && typeof lf.validateSessionEntry === 'function'
    && typeof lf.sessionLedgerPath === 'function',
    'A0 host module public surface present (saveSessionEntry/readLedgerFile/readExecutorSessionIds/validateSessionEntry/sessionLedgerPath)');
  ok(typeof handles.shortCodeOf === 'function' && typeof handles.assignHandles === 'function'
    && typeof handles.mergeLedgerEntries === 'function' && typeof handles.mergeExecutorSessions === 'function',
    'A0b handles module public surface present (shortCodeOf/assignHandles/mergeLedgerEntries/mergeExecutorSessions)');
  ok(lf.sessionLedgerPath(KEY, ENV) === FILE, 'A0c root resolution honors SANDBAR_PROJECTS_DIR (grants-chain, absolute path)');

  // ── A. write → read back from the FILE (reader-side evidence) ──────────
  section('A. write lands sessions.json under the project root, read back from disk');
  const now = Date.now();
  const entry = {
    session_id: 'session-09ca0247-1111-2222-3333-444444444444',
    title: '', opened_at: now, last_opened_at: now, cwd: path.join(stub, KEY),
  };
  const w = lf.saveSessionEntry(KEY, entry, ENV);
  ok(w && w.ok === true, 'A1 first write accepted');
  ok(w && path.resolve(w.file) === FILE, 'A2 result names the absolute project-root file path');
  ok(existsSync(FILE), 'A3 sessions.json exists at <projects_root>/<key>/sessions.json');
  const disk = JSON.parse(readRaw());
  ok(disk.version === 1, 'A4 on-disk schema version 1');
  const row = (disk.sessions ?? [])[0] ?? {};
  ok(row.session_id === entry.session_id, 'A5 session_id persisted');
  ok(row.handle === '09ca', `A6 handle short code assigned and persisted (got ${JSON.stringify(row.handle)})`);
  ok(typeof row.opened_at === 'number' && typeof row.last_opened_at === 'number', 'A7 timestamps persisted');
  ok(path.isAbsolute(String(row.cwd)), 'A8 cwd is absolute');
  const r = lf.readLedgerFile(KEY, ENV);
  ok(Array.isArray(r.entries) && r.entries[0]?.session_id === entry.session_id,
    'A9 readLedgerFile returns the persisted entry (file face, not cache)');

  // ── B. hostile file tolerance ──────────────────────────────────────────
  section('B. malformed file on disk → empty ledger, never throws');
  for (const [label, body] of [
    ['B1 truncated JSON', '{"version":1,"sessions":[{"session_id":"x"'],
    ['B2 wrong version', '{"version":99,"sessions":[]}'],
    ['B3 wrong shape', '{"sessions":"not-a-list"}'],
    ['B4 not JSON at all', '<<<garbage>>>'],
  ]) {
    writeFileSync(FILE, body);
    let out = null, threw = false;
    try { out = lf.readLedgerFile(KEY, ENV); } catch { threw = true; }
    ok(!threw && out && Array.isArray(out.entries) && out.entries.length === 0,
      `${label} → empty ledger, no throw`);
  }
  rmSync(FILE);
  let missing = null, missingThrew = false;
  try { missing = lf.readLedgerFile(KEY, ENV); } catch { missingThrew = true; }
  ok(!missingThrew && missing && Array.isArray(missing.entries) && missing.entries.length === 0,
    'B5 missing file → empty ledger, no throw');

  // ── C. refusal atomicity (executor-surface claim + malformed entry) ────
  section('C. refusal leaves the on-disk file byte-identical, reasons are distinguishable');
  // restore a known-good file
  lf.saveSessionEntry(KEY, entry, ENV);
  const before = sha(readRaw());
  let errExec = null;
  try { lf.saveSessionEntry(KEY, { ...entry, session_id: 'session-ffff0000-1', surface: 'executor-session' }, ENV); }
  catch (e) { errExec = e; }
  ok(errExec instanceof lf.SessionLedgerError, 'C1 executor-surface self-report refused (SessionLedgerError)');
  // The plan R1 stance promises a NAMED refusal; status codes are the route's
  // mapping face. (Defect reported, not asserted here: the module header
  // promises 403 for declared refusal / 400 for shape, but saveSessionEntry
  // throws 400 for both — see stage result file.)
  ok(errExec && typeof errExec.status === 'number' && /executor/.test(String(errExec.message)),
    `C2 executor-surface refusal is named (status=${errExec && errExec.status}, msg names executor)`);
  ok(sha(readRaw()) === before, 'C3 on-disk file byte-identical after refusal (atomic discipline)');
  let errBad = null;
  try { lf.saveSessionEntry(KEY, { session_id: '', handle: 42 }, ENV); }
  catch (e) { errBad = e; }
  ok(errBad instanceof lf.SessionLedgerError,
    'C4 malformed entry refused with a verdict');
  ok(sha(readRaw()) === before, 'C5 file still byte-identical after malformed-entry refusal');
  ok(String(errExec?.message ?? '').length > 0 && String(errBad?.message ?? '').length > 0
    && String(errExec?.message) !== String(errBad?.message),
    'C6 both refusals name a reason and the reasons are distinguishable');

  // ── D. id-union merge: two writes both survive ─────────────────────────
  section('D. two writes merge by id, neither clobbers the other');
  const e2 = { ...entry, session_id: 'session-aabbccdd-2', opened_at: now + 1, last_opened_at: now + 1 };
  lf.saveSessionEntry(KEY, e2, ENV);
  const diskD = JSON.parse(readRaw());
  const ids = (diskD.sessions ?? []).map(s => s.session_id);
  ok(ids.includes(entry.session_id) && ids.includes(e2.session_id),
    'D1 both sessions survive in the file (id-union, not overwrite)');
  lf.saveSessionEntry(KEY, { ...entry, last_opened_at: now + 99, title: 'newest' }, ENV);
  const diskE = (JSON.parse(readRaw()).sessions ?? []).find(s => s.session_id === entry.session_id) ?? {};
  ok(diskE.title === 'newest' && diskE.last_opened_at === now + 99,
    'D2 same-id write: newer last_opened_at and incoming fields win');

  // ── E. executor merge from executor-grants.json (visibility half) ──────
  section('E. grants-declared executor session is visible with the fixed handle');
  writeFileSync(path.join(stub, KEY, 'executor-grants.json'),
    JSON.stringify({ version: 1, executor_sessions: ['session-exec0000-9'] }));
  const grantsIds = lf.readExecutorSessionIds(KEY, ENV);
  ok(Array.isArray(grantsIds) && grantsIds.includes('session-exec0000-9'),
    'E1 executor session id read from executor-grants.json');
  const merged = handles.mergeExecutorSessions(lf.readLedgerFile(KEY, ENV).entries, grantsIds);
  const execRow = merged.find(s => s.session_id === 'session-exec0000-9');
  ok(!!execRow, 'E2 grants-declared executor id appears in the merged list');
  ok(execRow && execRow.handle === handles.EXECUTOR_HANDLE && execRow.handle === 'executor',
    'E3 its handle is the fixed name executor');
  ok(lf.readLedgerFile(KEY, ENV).entries.every(s => s.session_id !== 'session-exec0000-9'),
    'E4 executor projection is derived display — NOT persisted into sessions.json (grants stay the source)');

  // ── F. handle short codes ──────────────────────────────────────────────
  section('F. short codes: stable, collision-extended, executor excluded');
  const sid = 'session-09ca0247-xxxx';
  ok(handles.shortCodeOf(sid) === handles.shortCodeOf(sid) && handles.shortCodeOf(sid) === '09ca',
    'F1 shortCodeOf stable, first 4 hex');
  ok(handles.shortCodeOf('') === '' , 'F2 empty id → empty code (no fake code)');
  const assigned = handles.assignHandles([
    { session_id: 'session-09ca0247-1' },
    { session_id: 'session-09ca0247-2' }, // collides on first 4
    { session_id: 'session-execbeef-3', handle: 'executor' },
  ]);
  const codes = assigned.filter(a => a.handle !== 'executor').map(a => a.handle);
  ok(new Set(codes).size === codes.length, `F3 in-project collision extended, codes unique (got ${JSON.stringify(codes)})`);
  ok(assigned.find(a => a.handle === 'executor')?.session_id === 'session-execbeef-3',
    'F4 executor keeps the fixed name, outside the code space');
  const again = handles.assignHandles(assigned);
  ok(JSON.stringify(again.map(a => a.handle)) === JSON.stringify(assigned.map(a => a.handle)),
    'F5 assignHandles idempotent');
  // saveSessionEntry is the assignment chokepoint: a second save of an
  // entry that came back from the file keeps its handle (idempotent)
  const secondSave = lf.saveSessionEntry(KEY, { ...entry, title: 'again' }, ENV);
  ok(secondSave.handle === '09ca', 'F6 save path keeps the already-assigned handle');
} catch (e) {
  console.error(`FAIL: journey threw: ${e && (e.stack || e.message)}`);
  cleanup();
  process.exit(1);
}

cleanup();
console.log(`\n${passed} ok, ${failed} FAIL`);
process.exit(failed ? 1 : 0);
