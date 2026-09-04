/**
 * Baseline: code lane declared-checks EXECUTION semantics (t260903-01).
 *
 * Intent:
 *   Contract ②a (v2 列表命令制) promises: every declared check {id, cmd, cwd?, timeout?}
 *   is run by the engine via /bin/sh -c, judged purely by exit code, named by its id,
 *   with cwd resolved against the declaration root and timeout enforced with process
 *   reaping. NOWHERE is this exercised today: every existing test drives the code lane
 *   with skip_slow=true, so the command-execution half of the contract has zero
 *   regression cover — a refactor could break it silently. This baseline owns that face.
 *
 * High-level steps (hermetic: tmp fixture, no git needed — whitelist skips visibly
 * without base):
 *   A. four declared checks: plain cmd green (named by id) / cwd-relative cmd green
 *      (marker only exists in sub/) / exit 3 red with rc in detail / sleep with
 *      timeout=1 red with 超时 detail — and the whole run finishes well under the
 *      sleep duration (process actually reaped at the timeout, not waited out);
 *   B. red_count sums exactly the red items;
 *   C. skip_slow=true skips ALL command checks (only the whitelist note remains).
 *
 * Fault faces: 边界（timeout 到点）+ 资源回收（超时进程被终结而非等满）+ 异常输入
 * 的执行面（exit≠0 判红）。
 *
 * Coverage note (anti-duplication): the approved plan's L2 additions cover ②a key
 * names in the DOC and shape key sets — not execution semantics. Malformed unknown
 * keys are owned there; this file only drives valid declarations.
 *
 * Reference: docs/design/sandbar项目接入契约v1.md ②a/②d；verify_lane.py _code 装配。
 */

import { spawnSync } from 'node:child_process'
import { mkdtemp, writeFile, mkdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const REPO = process.cwd()

function callCode(repo, extra) {
  const p = spawnSync('python3', ['server/admin.py', 'call', 'verify_lane',
    JSON.stringify({ lane: 'code', path: repo, ...extra })],
    { cwd: REPO, encoding: 'utf8', timeout: 120000 })
  if (p.error || p.status !== 0) return { ok: false, stderr: (p.stderr || String(p.error)).slice(-300) }
  try { return JSON.parse(p.stdout) } catch { return { ok: false, stderr: 'unparseable: ' + p.stdout.slice(-200) } }
}

let repo = null
try {
  repo = await mkdtemp(join(tmpdir(), 'v11exec-'))
  const { writeFileSync } = await import('node:fs')
  await mkdir(join(repo, 'src'), { recursive: true })
  await mkdir(join(repo, 'sub'), { recursive: true })
  writeFileSync(join(repo, 'src', 'a.ts'), 'export const a = 1\n')
  writeFileSync(join(repo, 'sub', 'marker.txt'), 'x\n')
  writeFileSync(join(repo, 'verify.yaml'), [
    'schema: v1',
    'lanes:',
    '  code:',
    '    write_allow: ["src/"]',
    '    checks:',
    '      - id: 源在位',
    '        cmd: test -f src/a.ts',
    '        timeout: 10',
    '      - id: 子目录工作目录',
    '        cmd: test -f marker.txt',
    '        cwd: sub',
    '        timeout: 10',
    '      - id: 必红退出码',
    '        cmd: exit 3',
    '        timeout: 10',
    '      - id: 慢命令超时',
    '        cmd: sleep 6',
    '        timeout: 1',
    '',
  ].join('\n'))

  // ---------- A. execution semantics ----------
  section('A. 声明即执行：id 命名 / cwd 生效 / 退出码判红 / 超时回收')
  const t0 = Date.now()
  const res = callCode(repo)
  const elapsed = Date.now() - t0
  ok(res.ok === true, 'A0 调用成功')
  if (res.ok) {
    const r = res.result
    const byName = (n) => (r.checks || []).find(c => c.check === n)
    ok(r.green === false, 'A1 有红项 → 整道红')
    ok(!!byName('源在位') && byName('源在位').level === 'green', 'A2 简单 cmd 绿且以声明 id 命名')
    ok(!!byName('子目录工作目录') && byName('子目录工作目录').level === 'green',
      'A3 checks.cwd 相对声明根生效（marker 仅在 sub/ 下）')
    const red3 = byName('必红退出码')
    ok(!!red3 && red3.level === 'red' && JSON.stringify(red3.items).includes('rc=3'),
      'A4 exit 3 → 红且 detail 带 rc=3（退出码即红绿判据）')
    const slow = byName('慢命令超时')
    ok(!!slow && slow.level === 'red' && JSON.stringify(slow.items).includes('超时'),
      'A5 timeout=1 到点判红，detail 写明超时')
    ok(elapsed < 5000, `A6 超时进程被回收：整道 ${elapsed}ms 收敛（远小于 sleep 6s，未等满）`)
    // ---------- B. red_count sum ----------
    const redItems = (r.checks || []).filter(c => c.level === 'red').reduce((n, c) => n + (c.items || []).length, 0)
    ok(r.red_count === redItems && r.red_count === 2, `B1 red_count=红项 items 之和（=${r.red_count}，恰两条红）`)
  }

  // ---------- C. skip_slow skips all command checks ----------
  section('C. skip_slow：跳过全部命令检查（仅余白名单注记）')
  const res2 = callCode(repo, { skip_slow: true })
  if (res2.ok) {
    const r = res2.result
    const ids = ['源在位', '子目录工作目录', '必红退出码', '慢命令超时']
    ok(ids.every(n => !(r.checks || []).some(c => c.check === n)), 'C1 四条命令检查全部未装配')
    ok(r.green === true, 'C2 白名单注记绿（命令检查跳过不误伤）')
  } else ok(false, 'C0 调用失败: ' + (res2.stderr || ''))
} finally {
  try { await rm(repo, { recursive: true, force: true }) } catch { /* best effort */ }
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
