/**
 * Baseline: contract v1.1 next-project onboarding journey (t260903-01).
 *
 * Intent (user-perceivable, black-box via the real execution API):
 *   The ticket's acceptance statement is 「让下一个项目接入有真源可依」. This journey
 *   simulates that next project: it writes a MINIMAL verify.yaml using only what
 *   contract ②a~②e declare (schema v1, block-list write_allow, checks list-of-maps
 *   with id/cmd/cwd/timeout, one integration.cmd), then drives BOTH lanes through
 *   `server/admin.py call verify_lane` — the sole programmable entry a project uses.
 *   Green path must be green with the documented return shapes; the two classic
 *   failure faces (out-of-set write; failing scenario) must be red and name the cause.
 *
 * High-level steps (fully hermetic: tmp fixture repo + git + admin.py; no network):
 *   A. Fixture: tmp git repo with contract-shaped verify.yaml (checks exercising
 *      plain cmd + cwd) and a three-line-protocol integ stub.
 *   B. In-bounds change (src/) -> lane=code green; result keys EXACTLY
 *      {lane, green, red_count, checks}; check names = declared ids.
 *      lane=integ green; keys EXACTLY {lane, green, ran, pass, fail, scenarios, err}.
 *   C. Out-of-bounds change (other/) -> lane=code red, red_count>=1, file named.
 *   D. Failing scenario (FAIL line + exit 1) -> lane=integ green=false, fail=1,
 *      scenarios[].exit carries the executor exit code.
 *
 * Coverage note (anti-duplication): verify-lane-config.mjs (L2) tests the code lane
 * three states with skip_slow=true — checks NEVER execute there; the integ lane has
 * no L2 fixture today. This journey is the system-level user path across both lanes.
 *
 * Reference: .suyou/stage_review_plan_gen2.json (approved plan ②a~②e);
 * contract doc docs/design/sandbar项目接入契约v1.md ②.
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

/** git helper inside the fixture repo. */
function fx(repo, ...args) {
  const p = spawnSync('git', args, { cwd: repo, encoding: 'utf8' })
  if (p.status !== 0) throw new Error(`git ${args.join(' ')}: ${p.stderr}`)
  return p.stdout.trim()
}

/** The real execution API a project drives: admin.py call verify_lane. */
function callLane(args) {
  const p = spawnSync('python3', ['server/admin.py', 'call', 'verify_lane', JSON.stringify(args)],
    { cwd: REPO, encoding: 'utf8', timeout: 120000 })
  if (p.error || p.status !== 0) {
    return { ok: false, stderr: (p.stderr || String(p.error)).slice(-300) }
  }
  try { return JSON.parse(p.stdout) } catch { return { ok: false, stderr: 'unparseable: ' + p.stdout.slice(-200) } }
}

const VERIFY_YAML = [
  'schema: v1',
  'lanes:',
  '  code:',
  '    write_allow:',
  '      - src/',
  '    checks:',
  '      - id: 源文件在位',
  '        cmd: test -f src/a.ts',
  '        timeout: 10',
  '      - id: 子目录探测',
  '        cmd: test -f marker.txt',
  '        cwd: sub',
  '        timeout: 10',
  'integration:',
  '  cmd: python3 integ_stub.py',
  '',
].join('\n')

const STUB_OK = "print('PASS [接入冒烟]')\nprint('SCENARIOS ran=1 pass=1 fail=0 (0s)')\n"
const STUB_FAIL = "print('PASS [接入冒烟]')\nprint('FAIL [坏场景] exit=1')\nprint('SCENARIOS ran=2 pass=1 fail=1 (0s)')\nimport sys\nsys.exit(1)\n"

let root = null
try {
  root = await mkdtemp(join(tmpdir(), 'v11onb-'))
  const repo = join(root, 'proj')
  const { mkdirSync, writeFileSync } = await import('node:fs')
  mkdirSync(join(repo, 'src'), { recursive: true })
  mkdirSync(join(repo, 'sub'), { recursive: true })
  writeFileSync(join(repo, 'src', 'a.ts'), 'export const a = 1\n')
  writeFileSync(join(repo, 'sub', 'marker.txt'), 'x\n')
  writeFileSync(join(repo, 'verify.yaml'), VERIFY_YAML)
  writeFileSync(join(repo, 'integ_stub.py'), STUB_OK)
  fx(repo, 'init', '-q', '-b', 'main')
  fx(repo, 'config', 'user.email', 't@example.com')
  fx(repo, 'config', 'user.name', 't')
  fx(repo, 'add', '-A')
  fx(repo, 'commit', '-qm', 'base')

  // ---------- B. in-bounds change: both lanes green with documented shapes ----------
  section('B. 界内改动：双道绿，返回形状逐键符合契约 ②b-(b)')
  writeFileSync(join(repo, 'src', 'b.ts'), 'export const b = 2\n')
  fx(repo, 'add', '-A')
  fx(repo, 'commit', '-qm', 'in-bounds')

  const codeRes = callLane({ lane: 'code', path: repo, base: 'HEAD~1' })
  ok(codeRes.ok === true, 'B0 admin.py call 真入口可用（lane=code）')
  if (codeRes.ok) {
    const r = codeRes.result
    ok(JSON.stringify(Object.keys(r).sort()) === JSON.stringify(['checks', 'green', 'lane', 'red_count']),
      'B1 code 道返回键集恰为 {lane,green,red_count,checks}（契约 ②b-(b)）')
    ok(r.green === true, 'B2 界内改动 code 道绿')
    const names = (r.checks || []).map(c => c.check)
    ok(names.includes('源文件在位'), 'B3 检查名=声明 id「源文件在位」（列表命令制）')
    ok(names.includes('子目录探测'), 'B4 检查名=声明 id「子目录探测」')
    const sub = (r.checks || []).find(c => c.check === '子目录探测')
    ok(!!sub && sub.level === 'green', 'B5 checks.cwd 相对声明根生效（sub/marker.txt 探测绿）')
  }

  const integRes = callLane({ lane: 'integ', path: repo })
  ok(integRes.ok === true, 'B6 admin.py call 真入口可用（lane=integ）')
  if (integRes.ok) {
    const r = integRes.result
    // t260904-12 乙段：契约 ②b-2 env_fail 转必含 → 键集锚随契约反转（守卫随闸同票，R4 修法①）
    ok(JSON.stringify(Object.keys(r).sort()) === JSON.stringify(['env_fail', 'err', 'fail', 'green', 'lane', 'pass', 'ran', 'scenarios']),
      'B7 integ 道返回键集恰为 {lane,green,ran,pass,fail,env_fail,scenarios,err}（契约 ②b-2 v2.1 起必含，非 content 形状）')
    ok(r.green === true && r.ran === 1 && r.pass === 1, 'B8 声明 integration.cmd 真跑：ran=1 pass=1 绿')
  }

  // ---------- C. out-of-bounds write: red, names the file ----------
  section('C. 越界写：code 道红并点名')
  await mkdir(join(repo, 'other'), { recursive: true })
  writeFileSync(join(repo, 'other', 'evil.ts'), 'export const evil = 1\n')
  fx(repo, 'add', '-A')
  fx(repo, 'commit', '-qm', 'out-of-bounds')
  const cRes = callLane({ lane: 'code', path: repo, base: 'HEAD~1' })
  if (cRes.ok) {
    const r = cRes.result
    ok(r.green === false && r.red_count >= 1, 'C1 越界写 code 道红（red_count>=1）')
    ok(JSON.stringify(r.checks).includes('other/evil.ts'), 'C2 红字点名越界文件 other/evil.ts')
  } else {
    ok(false, 'C0 lane=code 调用失败: ' + (cRes.stderr || ''))
  }

  // ---------- D. failing scenario: integ red with executor exit code ----------
  section('D. 场景失败：integ 道红，exit 码随 scenarios 透出')
  writeFileSync(join(repo, 'integ_stub.py'), STUB_FAIL)
  const dRes = callLane({ lane: 'integ', path: repo })
  if (dRes.ok) {
    const r = dRes.result
    ok(r.green === false && r.fail === 1, 'D1 FAIL 行 + exit 1 → integ 道红（fail=1）')
    const bad = (r.scenarios || []).find(s => s.name === '坏场景')
    ok(!!bad && bad.exit === 1, 'D2 scenarios[].exit 透传执行器退出码（红因可仲裁）')
  } else {
    ok(false, 'D0 lane=integ 调用失败: ' + (dRes.stderr || ''))
  }
} finally {
  try { await rm(root, { recursive: true, force: true }) } catch { /* best effort */ }
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
