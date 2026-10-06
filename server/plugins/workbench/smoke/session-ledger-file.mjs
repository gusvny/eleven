/**
 * smoke/session-ledger-file.mjs — smoke for the sessions.json host file face
 * (console-ui UI-5, t261005-06).
 *
 * Run: node smoke/session-ledger-file.mjs (node >= 22.18 native type-stripping).
 * Under test: src/host/session-ledger-file.ts against a stub projects root
 * (env-injected SANDBAR_PROJECTS_DIR to a temp dir — no real instance state).
 *
 * Covers (plan steps 2 + review R1/R4/R5 contracts):
 *   A. read: missing file / bad JSON / wrong shape -> ok + empty entries, never throw;
 *      mtime surfaces (null when absent).
 *   B. save round-trip: entry lands in <root>/<key>/sessions.json (acceptance reads
 *      the FILE back from its absolute path, not the return value — reader-side
 *      evidence discipline); handle auto-assigned; idempotent re-save.
 *   C. KI-193 declared refusal (injection cases): executor-identity write refused
 *      (403) and malformed entries refused (400) — on-disk file byte-identical.
 *   D. R4 merge: two saves for different sessions both survive; older timestamp
 *      does not overwrite a newer one.
 *   E. executor projection read: executor-grants.json executor_sessions merged at
 *      read time (derived display; grants file untouched); malformed grants file
 *      degrades to no projection.
 */

import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import {
  SessionLedgerError,
  readExecutorSessionIds,
  readLedgerFile,
  saveSessionEntry,
  sessionLedgerPath,
  validateSessionEntry,
} from '../src/host/session-ledger-file.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

// Stub projects root (fresh per run; no real instance state touched)
const root = join(tmpdir(), `wb-sessions-smoke-${process.pid}-${Date.now()}`)
mkdirSync(join(root, 'sandbar'), { recursive: true })
const env = { SANDBAR_PROJECTS_DIR: root }

try {
  section('A read：缺文件/坏文件=空册不抛（容错纪律）')
  {
    const r0 = readLedgerFile('sandbar', env)
    ok(r0.ok === true && r0.entries.length === 0 && r0.mtime === null, '缺文件=ok+空册+mtime null')
    writeFileSync(sessionLedgerPath('sandbar', env), '{broken json', 'utf8')
    const r1 = readLedgerFile('sandbar', env)
    ok(r1.ok === true && r1.entries.length === 0 && typeof r1.mtime === 'number', '坏 JSON=空册，mtime 在场')
    writeFileSync(sessionLedgerPath('sandbar', env), '{"version":9,"sessions":[]}', 'utf8')
    ok(readLedgerFile('sandbar', env).entries.length === 0, 'version 不对=空册')
  }

  section('B save round-trip：验收读回的是绝对路径文件本体（非返回值）')
  {
    const res = saveSessionEntry('sandbar', { session_id: 'session-09ca0247-1', cwd: '/x' }, env)
    ok(res.ok === true && res.handle === '09ca', '保存成功 + 短码分配收口')
    // Reader-side evidence: read the file back from its absolute path
    const file = sessionLedgerPath('sandbar', env)
    const onDisk = JSON.parse(readFileSync(file, 'utf8'))
    ok(onDisk.version === 1 && onDisk.sessions.length === 1, '文件落 <root>/<key>/sessions.json，version 1')
    ok(onDisk.sessions[0].session_id === 'session-09ca0247-1' && onDisk.sessions[0].handle === '09ca', '文件内条目=入舱条目+句柄')
    ok(readFileSync(file, 'utf8').endsWith('\n'), '文件尾换行（可 grep 可 diff 的稳定形态）')
    const res2 = saveSessionEntry('sandbar', { session_id: 'session-09ca0247-1', cwd: '/x' }, env)
    ok(res2.handle === '09ca' && JSON.parse(readFileSync(file, 'utf8')).sessions.length === 1, '重存幂等（句柄不重排、条目不重复）')
    ok(res.file === file, '返回 file=绝对路径（验收锚）')
  }

  section('C KI-193 声明拒收（注入用例；拒收=盘上逐字节不动）')
  {
    const file = sessionLedgerPath('sandbar', env)
    const before = readFileSync(file, 'utf8')
    // injection 1: executor-identity write (KI-193: surface is caller-self-reported;
    // this is a DECLARED refusal behavior, not an auth guarantee)
    let err1 = null
    try { saveSessionEntry('sandbar', { session_id: 'session-evil0000', surface: 'executor-session' }, env) }
    catch (e) { err1 = e }
    ok(err1 instanceof SessionLedgerError && err1.status === 403, 'executor 身份写=403 拒收')
    ok(readFileSync(file, 'utf8') === before, '拒收后盘上文件逐字节不动')
    // injection 2: malformed entries (validator faces)
    for (const bad of [null, 'x', {}, { session_id: '' }, { session_id: 7 }, { session_id: 's', last_opened_at: 'x' }]) {
      let err = null
      try { saveSessionEntry('sandbar', bad, env) } catch (e) { err = e }
      ok(err instanceof SessionLedgerError && err.status === 400, `畸形入舱拒收 400（${JSON.stringify(bad).slice(0, 24)}）`)
    }
    ok(readFileSync(file, 'utf8') === before, '全部畸形拒收后文件仍逐字节不动')
    const [norm, e1] = validateSessionEntry({ session_id: 's', title: 'x'.repeat(600) })
    ok(e1 === null && norm.title.length === 500, 'title 截断到 500（长度限面）')
    let e2 = null
    try { validateSessionEntry({ session_id: 'x'.repeat(300) }) } catch { /* validator returns, not throws */ }
    ok(validateSessionEntry({ session_id: 'x'.repeat(300) })[1] !== null, 'session_id 超长=具名拒收')
    void e2
  }

  section('D R4 合并：两会话并存 + 旧时间戳不覆盖新')
  {
    saveSessionEntry('sandbar', { session_id: 'session-aaaa0000', last_opened_at: 100 }, env)
    saveSessionEntry('sandbar', { session_id: 'session-bbbb0000', last_opened_at: 200 }, env)
    const entries = readLedgerFile('sandbar', env).entries
    ok(entries.some(e => e.session_id === 'session-aaaa0000') && entries.some(e => e.session_id === 'session-bbbb0000'), '两次 POST 的会话都在文件里（合并不丢）')
    saveSessionEntry('sandbar', { session_id: 'session-aaaa0000', last_opened_at: 1, cwd: '/stale' }, env)
    const after = readLedgerFile('sandbar', env).entries.find(e => e.session_id === 'session-aaaa0000')
    ok(after.last_opened_at === 100 && after.cwd === undefined, '旧时间戳写不覆盖新（last_opened_at 新者胜）')
  }

  section('E 执行器投影：grants 声明读侧合并（授权面真源不动）')
  {
    const grants = { version: 1, grants: {}, executor_sessions: ['session-exec0000', 'session-09ca0247-1'] }
    writeFileSync(join(root, 'sandbar', 'executor-grants.json'), JSON.stringify(grants), 'utf8')
    ok(readExecutorSessionIds('sandbar', env).length === 2, 'grants 声明读取')
    writeFileSync(join(root, 'sandbar', 'executor-grants.json'), '{broken', 'utf8')
    ok(readExecutorSessionIds('sandbar', env).length === 0, '坏 grants=空投影不抛')
    writeFileSync(join(root, 'sandbar', 'executor-grants.json'), JSON.stringify(grants), 'utf8')
    const file = sessionLedgerPath('sandbar', env)
    const before = readFileSync(file, 'utf8')
    ok(!before.includes('session-exec0000'), '投影不落 sessions.json（派生显示）')
    ok(readFileSync(join(root, 'sandbar', 'executor-grants.json'), 'utf8') === JSON.stringify(grants), 'grants 文件逐字节不动（只读）')
  }
} finally {
  try { rmSync(root, { recursive: true, force: true }) } catch { /* 清台失败不掩盖结果 */ }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
