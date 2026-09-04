/**
 * Baseline: integration lane output-contract adversarial faces (t260903-01).
 *
 * Intent:
 *   Contract ②b-(a) admits the scenario-executor stdout protocol as the integ lane's
 *   character-level sub-contract: PASS line / FAIL line (4-space indent tail) /
 *   trailing SCENARIOS summary line. This baseline attacks the protocol the way a
 *   sloppy next-project executor would, locking the ENGINE's judging semantics:
 *   - malformed FAIL line (regex miss) must NOT be silently dropped: counted as fail
 *     with name=raw line, exit=-1;
 *   - the SCENARIOS summary line is a REFERENCE line: the engine never reads it, so a
 *     summary inconsistent with PASS/FAIL lines must not change the verdict;
 *   - a summary-only stdout (no PASS/FAIL lines) is the documented zero-scenario face;
 *   - the err shape ({lane, green:false, err}) must NOT leak content-shape keys
 *     (red_count / checks) — consumers branch on err, not on absent fields.
 *
 * High-level steps (hermetic: per-case tmp fixture + admin.py call lane=integ):
 *   A. well-formed mixed protocol -> per-scenario parse, tail capture, 4-space rule
 *      (2-space lines are not tail), exit codes carried;
 *   B. malformed FAIL line -> fail counted, name=raw line, exit=-1;
 *   C. summary contradicts lines -> verdict follows the LINES (green stays green);
 *   D. summary-only stdout -> zero-scenario green (ran=0);
 *   E. executor absent -> err shape, exact keys {lane, green, err}, no shape leak.
 *
 * Coverage note (anti-duplication): the approved plan's L2 additions cover the integ
 * happy path + three states + zero-scenario + shape key sets; this baseline owns the
 * protocol-mutation faces (A tail/indent detail, B fallback, C inconsistency, E leak).
 *
 * Reference: docs/design/sandbar项目接入契约v1.md ②b-(a)（真源 verify_lane.py _integ
 * 解析循环与红绿判据）；review_plan gen1 F2（汇总行=参考性，不构成判据）。
 */

import { spawnSync } from 'node:child_process'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const REPO = process.cwd()

function callInteg(repo) {
  const p = spawnSync('python3', ['server/admin.py', 'call', 'verify_lane',
    JSON.stringify({ lane: 'integ', path: repo })],
    { cwd: REPO, encoding: 'utf8', timeout: 120000 })
  if (p.error || p.status !== 0) return { ok: false, stderr: (p.stderr || String(p.error)).slice(-300) }
  try { return JSON.parse(p.stdout) } catch { return { ok: false, stderr: 'unparseable: ' + p.stdout.slice(-200) } }
}

/** Fresh fixture: verify.yaml declaring integration.cmd -> stub; returns writer+caller. */
async function makeFixture() {
  const repo = await mkdtemp(join(tmpdir(), 'v11integ-'))
  const { writeFileSync } = await import('node:fs')
  const write = (stub) => {
    // write_allow 必填（引擎契约：verify.yaml 在位即须非空 write_allow，无每键关闭态）
    writeFileSync(join(repo, 'verify.yaml'),
      'schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\nintegration:\n  cmd: python3 integ_stub.py\n')
    writeFileSync(join(repo, 'integ_stub.py'), stub)
  }
  write('')
  return { repo, write, call: () => callInteg(repo), cleanup: () => rm(repo, { recursive: true, force: true }) }
}

let fx = null
try {
  // ---------- A. well-formed mixed protocol ----------
  section('A. 三行协议正常解析：逐场景拆解、缩进尾段、4 空格规则、exit 透传')
  fx = await makeFixture()
  fx.write([
    "print('PASS [好场景]')",
    "print('FAIL [坏场景] exit=2')",
    "print('    tail line one')",
    "print('  two-space line (not tail)')",
    "print('    tail line two')",
    "print('SCENARIOS ran=2 pass=1 fail=1 (1s)')",
    'import sys',
    'sys.exit(1)',
    '',
  ].join('\n'))
  {
    const res = fx.call()
    ok(res.ok === true, 'A0 调用成功')
    if (res.ok) {
      const r = res.result
      ok(r.green === false && r.ran === 2 && r.pass === 1 && r.fail === 1, 'A1 计数随 PASS/FAIL 行：ran=2 pass=1 fail=1，整道红')
      const bad = (r.scenarios || []).find(s => s.name === '坏场景')
      ok(!!bad && bad.exit === 2, 'A2 FAIL 行 exit=2 透传进 scenarios[].exit')
      ok(!!bad && bad.output_tail.includes('tail line one') && bad.output_tail.includes('tail line two'),
        'A3 FAIL 后四空格缩进行收进 output_tail')
      ok(!!bad && !bad.output_tail.includes('two-space line'), 'A4 两空格行不收尾段（4 空格边界）')
      const good = (r.scenarios || []).find(s => s.name === '好场景')
      ok(!!good && good.output_tail === '', 'A5 PASS 行无尾段')
    }
  }
  await fx.cleanup()

  // ---------- B. malformed FAIL line ----------
  section('B. 畸形 FAIL 行：不静默吞，name=整行、exit=-1 计红')
  fx = await makeFixture()
  fx.write("print('FAIL [broken-no-exit-bracket')\nimport sys\nsys.exit(1)\n")
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      ok(r.green === false && r.fail === 1, 'B1 畸形 FAIL 行仍计败（fail=1，整道红）')
      const s = (r.scenarios || [])[0]
      ok(!!s && s.name === 'FAIL [broken-no-exit-bracket' && s.exit === -1,
        'B2 fallback：name=整行、exit=-1（畸形可仲裁不丢失）')
    } else ok(false, 'B0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()

  // ---------- C. summary contradicts the lines ----------
  section('C. 汇总行与明细矛盾：判据跟随明细行，汇总行不读不校验')
  fx = await makeFixture()
  fx.write("print('PASS [唯一场景]')\nprint('SCENARIOS ran=9 pass=0 fail=9 (0s)')\n")
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      ok(r.green === true && r.ran === 1 && r.pass === 1 && r.fail === 0,
        'C1 汇总行谎报 ran=9 fail=9 不改变判定（绿保持绿，ran=1）')
    } else ok(false, 'C0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()

  // ---------- D. summary-only stdout ----------
  section('D. 仅汇总行无明细：零场景绿（ran=0，引擎不读汇总）')
  fx = await makeFixture()
  fx.write("print('SCENARIOS ran=3 pass=3 fail=0 (0s)')\n")
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      ok(r.green === true && r.ran === 0, 'D1 无 PASS/FAIL 行 → ran=0 绿（汇总行不构成明细）')
    } else ok(false, 'D0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()

  // ---------- E. err shape has no content-shape leak ----------
  section('E. err 态形状：{lane,green,err}，不泄漏 content 形状键')
  fx = await makeFixture()
  fx.write("import sys\nsys.exit(7)\n")  // executor fails, produces zero result lines
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      ok(r.green === false && typeof r.err === 'string' && r.err.length > 0, 'E1 rc≠0 且零结果行 → err 态（非红非绿）')
      ok(JSON.stringify(Object.keys(r).sort()) === JSON.stringify(['err', 'green', 'lane']),
        'E2 err 态键集恰为 {lane,green,err}：无 red_count/checks 泄漏（消费方按 err 分流）')
    } else ok(false, 'E0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()
} finally {
  if (fx) { try { await fx.cleanup() } catch { /* already cleaned */ } }
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
