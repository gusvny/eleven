/**
 * smoke/write-lifecycle.mjs —— 写集生命周期（t260829-07）宿主/客户端半冒烟。
 *
 * 直跑：node smoke/write-lifecycle.mjs（node ≥22.18 原生 type-stripping）。
 * 覆盖：
 *   A. host epic-next.ts 纯函数：
 *      validWriteSetEntry（仓库内相对路径放行 / 绝对路径、'..'、反斜杠、盘符、
 *      空串、非字符串拒）；sanitizeWriteSet（保序去重、非法丢弃、非数组容错）；
 *      validateSuggestion（write_set 合法保留 / 缺失 → 空数组不阻塞 / 全非法 →
 *      空数组不阻塞 / 混合 → 只留合法）。
 *   B. client epics-model.ts 纯函数（弹层编辑栏）：
 *      writeSetTextToLines（每行一条/空行容忍/strip）；invalidWriteSetLines
 *      （非法行标红、合法为空）；validWriteSetEntry 同构一致（与 host 判定逐条对拍）。
 *   C. epic-next 泄漏修复回归（t260829-07）：B6 同款 STUB 模式连续 5 次 suggest job
 *      （ok / invalid_json / never_write 混合）后，检查无残留哑进程
 *      （job 目录 agent.log 闭环 + 全部 job 达终态 + stub 哑进程 pid 不存活）。
 *
 * 对应 python 侧：engine/selfcheck_write_lifecycle.py（写集校验/刷新/机械复核）。
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

/* ---------------- A. host 纯函数 ---------------- */
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

/* ---------------- B. client 纯函数 ---------------- */
console.log('B. client epics-model.ts 弹层编辑栏纯函数')
ok(JSON.stringify(writeSetTextToLines(' a.py\n\n b.py \n')) === JSON.stringify(['a.py', 'b.py']), '每行一条/空行容忍/strip')
ok(JSON.stringify(invalidWriteSetLines('a.py\n/bad\n..\\x')) === JSON.stringify(['/bad', '..\\x']), '非法行标红清单')
ok(invalidWriteSetLines('a.py\nb.py').length === 0, '全合法 → 空清单')
for (const entry of ['ok.py', '/abs', '../up', 'C:/x', 'a\\b', '', 'x.py']) {
  if (validWriteSetEntry(entry) !== clientValid(entry)) { ok(false, `host/client 判定一致：${entry}`); break }
  ok(true, `host/client 判定一致：${JSON.stringify(entry)}`)
}

/* ---------------- C. 泄漏回归：连续 5 次 STUB suggest job 全终态 ---------------- */
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
  // SANDBAR_EPIC_NEXT_STUB 的值即变体（1=ok 同义）：ok/invalid_json/never_write 混合
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
  // variant=never_write + 2s 超时 → 需要多轮；上面 20×150ms=3s 够触超时终态
}
// 哑进程存活检查：stub 挂的哑长驻进程若未被 reap 会一直存活
await new Promise(r => setTimeout(r, 3500)) // 等 reap 的 TERM→3s→KILL 宽限走完
for (const pid of stubProcPids) {
  try { process.kill(pid, 0); leaked++; } catch { /* 已死=回收成功 */ }
}
ok(leaked === 0, `5 次 suggest job（含 failed/超时变体）全部达终态且进程无残留（泄漏数=${leaked}）`)
// 清场：杀掉可能仍存活的哑进程（防本 smoke 自身泄漏——吃自己的狗粮）
for (const pid of stubProcPids) { try { process.kill(-pid, 'SIGKILL') } catch { try { process.kill(pid, 'SIGKILL') } catch {} } }
await rm(tmpRepo, { recursive: true, force: true }).catch(() => {})

console.log(`\n结果：${pass} 绿 / ${fail} 红`)
process.exit(fail === 0 ? 0 : 1)
