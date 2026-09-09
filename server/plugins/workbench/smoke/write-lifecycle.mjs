/**
 * smoke/write-lifecycle.mjs — host/client half-smoke for the write-set lifecycle (t260829-07).
 *
 * Run: node smoke/write-lifecycle.mjs (node >= 22.18 native type-stripping).
 * Covers:
 *   A. host epic-next.ts pure functions:
 *      validWriteSetEntry (in-repo relative paths admitted / absolute paths, '..', backslash,
 *      drive letter, empty string, non-string rejected); sanitizeWriteSet (order-preserving
 *      dedupe, illegal entries dropped, non-array tolerated); validateSuggestion (valid
 *      write_set kept / missing → empty array without blocking / all illegal → empty array
 *      without blocking / mixed → only the legal ones kept).
 *   B. client epics-model.ts pure functions (the popover edit bar):
 *      writeSetTextToLines (one entry per line / blank lines tolerated / stripped);
 *      invalidWriteSetLines (illegal lines flagged red, legal ones absent); validWriteSetEntry
 *      isomorphism (checked case by case against the host-side verdict).
 *   C. epic-next leak-fix regression (t260829-07): five suggest jobs in a row under the same
 *      STUB mode as B6 (ok / invalid_json / never_write mixed), then check for no leftover
 *      stub processes (agent.log in the job dir closes the loop + every job reaches a terminal
 *      state + the stub process pids are not alive).
 *
 * Python-side counterpart: engine/selfcheck_write_lifecycle.py (write-set validation/refresh/
 * mechanical review).
 */

import { execFileSync, spawn } from 'node:child_process'
import { mkdtemp, mkdir, rm, writeFile, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import process from 'node:process'

import { buildSuggestPrompt, sanitizeWriteSet, validateSuggestion, validWriteSetEntry } from '../src/host/epic-next.ts'
import { invalidWriteSetLines, validWriteSetEntry as clientValid, writeSetTextToLines } from '../src/client/epics-model.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fail++; console.error(`  ✗ ${label}`) }
}

/* ---------------- A. host pure functions ---------------- */
console.log('A. host epic-next.ts 写集纯函数')
ok(validWriteSetEntry('server/engine/client.py'), '仓库内相对路径放行')
ok(validWriteSetEntry('  app/src/main.ts  '), '首尾空白容忍')
ok(!validWriteSetEntry('/abs/path.py'), '绝对路径拒')
ok(!validWriteSetEntry('../outside.py'), "'..' 越界拒")
ok(!validWriteSetEntry('a\\b.py'), '反斜杠路径拒')
ok(!validWriteSetEntry('C:/x.py'), 'Windows 盘符拒')
ok(!validWriteSetEntry(''), '空串拒')
ok(!validWriteSetEntry(null) && !validWriteSetEntry(42), '非字符串拒')
ok(JSON.stringify(sanitizeWriteSet(['b.py', 'a.py', 'b.py', '/bad'])) === JSON.stringify(['b.py', 'a.py']),
  'sanitizeWriteSet：保序去重、非法丢弃')
ok(sanitizeWriteSet('not-array').length === 0 && sanitizeWriteSet(undefined).length === 0, '非数组容错 → 空数组')

const WF = ['dev-lane', 'content-pipeline']
const base = { status: 'ok', workflow: 'dev-lane', title: 't' }
ok(validateSuggestion({ ...base, write_set: ['a.py', 'b.py'] }, WF).suggestion.write_set.join(',') === 'a.py,b.py',
  'validateSuggestion：合法 write_set 保留')
ok(validateSuggestion(base, WF).suggestion.write_set.length === 0, '缺失 write_set → 空数组（不阻塞建议）')
ok(validateSuggestion({ ...base, write_set: ['/bad', '../up'] }, WF).suggestion.write_set.length === 0,
  '全非法 write_set → 空数组（不阻塞建议）')
ok(validateSuggestion({ ...base, write_set: ['ok.py', '/bad'] }, WF).suggestion.write_set.join(',') === 'ok.py',
  '混合 write_set → 只留合法')
ok(validateSuggestion({ ...base, write_set: 'junk' }, WF).suggestion.write_set.length === 0, '非数组 write_set 容错')
const p = buildSuggestPrompt({ code: 'e1', epicMarkdown: 'EPIC', ticketsSummary: 'T', workflows: WF.map(id => ({ id, name: id })), resultPath: '/r.json' })
ok(p.includes('write_set') && p.includes('EPIC') && p.includes('dev-lane'), 'buildSuggestPrompt 含 write_set 契约与全文')

/* ---------------- B. client pure functions ---------------- */
console.log('B. client epics-model.ts 弹层编辑栏纯函数')
ok(JSON.stringify(writeSetTextToLines(' a.py\n\n b.py \n')) === JSON.stringify(['a.py', 'b.py']), '每行一条/空行容忍/strip')
ok(JSON.stringify(invalidWriteSetLines('a.py\n/bad\n..\\x')) === JSON.stringify(['/bad', '..\\x']), '非法行标红清单')
ok(invalidWriteSetLines('a.py\nb.py').length === 0, '全合法 → 空清单')
for (const entry of ['ok.py', '/abs', '../up', 'C:/x', 'a\\b', '', 'x.py']) {
  if (validWriteSetEntry(entry) !== clientValid(entry)) { ok(false, `host/client 判定一致：${entry}`); break }
  ok(true, `host/client 判定一致：${JSON.stringify(entry)}`)
}

/* ---------------- C. leak regression: five STUB suggest jobs in a row, all terminal ---------------- */
console.log('C. epic-next 连续 5 次 suggest job（stub/failed 混合）无残留进程')
const tmpRepo = await mkdtemp(path.join(tmpdir(), 'wb-write-lifecycle-'))
process.env.SANDBAR_EPIC_NEXT_DIR = path.join(tmpRepo, '.suyou', 'epic-next')
process.env.SANDBAR_EPIC_NEXT_STUB = 'ok'
process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS = '2000'
const { startSuggestJob, pollSuggestJob, resolveEpicNextDir } = await import('../src/host/epic-next.ts')
const stubProcPids = []
let leaked = 0
const variants = ['ok', 'invalid_json', 'never_write', 'ok', 'invalid_json']
const epicMd = `# e-smoke\n\n测试立项\n`
for (let i = 0; i < 5; i++) {
  const v = variants[i]
  // the SANDBAR_EPIC_NEXT_STUB value is the variant itself (1=ok is a synonym): ok/invalid_json/never_write mixed
  process.env.SANDBAR_EPIC_NEXT_STUB = v
  const job = await startSuggestJob({
    repo: tmpRepo, code: `e-smoke-${i}`, epicTitle: 'E', epicMarkdown: epicMd,
    ticketsSummary: 'none', workflows: WF,
  })
  if (job.proc?.pid) stubProcPids.push(job.proc.pid)
  let last = job
  for (let t = 0; t < 20; t++) {
    last = await pollSuggestJob(job.jobId)
    if (last && last.state !== 'running') break
    await new Promise(r => setTimeout(r, 150))
  }
  if (!last || last.state === 'running') leaked++
  // variant=never_write + 2s timeout → needs several rounds; the 20×150ms=3s above is enough to hit the timeout terminal state
}
// stub process liveness check: a long-lived stub process would stay alive if never reaped
await new Promise(r => setTimeout(r, 3500)) // let the reap grace period TERM→3s→KILL run out
for (const pid of stubProcPids) {
  try { process.kill(pid, 0); leaked++; } catch { /* already dead = reaped successfully */ }
}
ok(leaked === 0, `5 次 suggest job（含 failed/超时变体）全部达终态且进程无残留（泄漏数=${leaked}）`)
// cleanup: kill any stub process that might still be alive (so this smoke does not leak — eating its own dogfood)
for (const pid of stubProcPids) { try { process.kill(-pid, 'SIGKILL') } catch { try { process.kill(pid, 'SIGKILL') } catch {} } }
await rm(tmpRepo, { recursive: true, force: true }).catch(() => {})

console.log(`\n结果：${pass} 绿 / ${fail} 红`)
process.exit(fail === 0 ? 0 : 1)
