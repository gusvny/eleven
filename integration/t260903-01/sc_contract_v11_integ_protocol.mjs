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
 *   - a summary-only stdout (no PASS/FAIL lines, no spec rows, no INTEG_SUMMARY ran>0)
 *     is the KI-116 explicit-red face (t260924-05: the old "zero-scenario green" escape
 *     hatch is gone — an idle/broken executor must never fake a green);
 *   - the err shape ({lane, green:false, err}) must NOT leak content-shape keys
 *     (red_count / checks / ran / scenarios / …) — consumers branch on err, not on
 *     absent fields. Additive non-content keys (metering/warning face) are allowed.
 *
 * High-level steps (hermetic: per-case tmp fixture + admin.py call lane=integ):
 *   A. well-formed mixed protocol -> per-scenario parse, tail capture, 4-space rule
 *      (2-space lines are not tail), exit codes carried;
 *   B. malformed FAIL line -> fail counted, name=raw line, exit=-1;
 *   C. summary contradicts lines -> verdict follows the LINES (green stays green);
 *   D. legacy summary-only stdout -> explicit zero-signal red (never a fake green);
 *   D2.INTEG_SUMMARY(ran>0) alone -> the guard does not misfire (not red);
 *   E. executor absent -> err shape, required keys {lane, green, err}, no content-shape leak.
 *
 * Coverage note (anti-duplication): the approved plan's L2 additions cover the integ
 * happy path + three states + zero-scenario + shape key sets; this baseline owns the
 * protocol-mutation faces (A tail/indent detail, B fallback, C inconsistency, E leak).
 *
 * Reference: docs/design/sandbar-project-onboarding-contract-v1.md ②b-(a)（真源 verify_lane.py _integ
 * 解析循环与红绿判据）；review_plan gen1 F2（汇总行=参考性，不构成判据）。
 */

import { cleanNarrowingEnv } from '../lib_env.mjs'  // 260930 收窄旋钮清理单点
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
    { cwd: REPO, encoding: 'utf8', timeout: 120000, env: cleanNarrowingEnv() })
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
  // 261001 契约修订（KI-171，integration 岗位判词）：畸形行的**名字**从「整行」改为
  // **合成面** `__malformed__ …`——整行当名字会让一段人话经红名集进下一轮快反馈面，
  // 而它不在册 ⇒ 执行器 fail-closed ⇒ 每轮复读同一个假名、票永远出不了 blocked
  // （t261001-10 第 5/6/7 轮实案）。**「畸形可仲裁不丢失」的性质不变**：红照记
  // （fail=1、exit=-1），原文逐字进 `output_tail`——本段 B2/B3 两条锁把它一起钉住：
  // 名字必须是合成面（防回灌），原文必须可读（可仲裁）。
  section('B. 畸形 FAIL 行：不静默吞，name=合成面（__malformed__）、原文进 output_tail')
  fx = await makeFixture()
  fx.write("print('FAIL [broken-no-exit-bracket')\nimport sys\nsys.exit(1)\n")
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      ok(r.green === false && r.fail === 1, 'B1 畸形 FAIL 行仍计败（fail=1，整道红）')
      const s = (r.scenarios || [])[0]
      ok(!!s && typeof s.name === 'string' && s.name.startsWith('__malformed__') && s.exit === -1,
        'B2 合成名 + exit=-1（畸形不进面、仍计红）')
      ok(!!s && (s.output_tail || '').includes('broken-no-exit-bracket'),
        'B3 原文逐字进 output_tail（畸形可仲裁不丢失）')
    } else ok(false, 'B0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()

  // ---------- C. summary contradicts the lines ----------
  // t260904-12 时序注记：本段与 D 段断言的是 **verify_lane 闸行为**（闸解析器改动
  // 在乙段票）。甲段（执行器三态化）不动闸，故本段保持现行 F2 语义=真；断言反转
  // 必须与乙段 verify_lane 改动同票落地（R4 拆两截），不得提前改弱/反转。
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
  // t260924-05 KI-116 有意契约变更（非放水，工单必做③「零信号必须红」）：旧断言
  // 「仅汇总行无明细=零场景绿」与 KI-116 病象（ran=0 静默绿 ≥6 期）同源——本票
  // 在 verify_lane 装设零信号守卫：文本结果行 ∨ '{'·'[' 规范行 ∨ INTEG_SUMMARY
  // 汇总行 ran>0，三者全空且 exit==0 = 显式红。旧式 'SCENARIOS ran=' 行不在信号
  // 判据集（v1.8 起已退役为参考性）→ 本段夹具（仅旧式汇总行）由绿改红。
  section('D. 仅旧式汇总行无明细无规范行：零场景信号显式红（KI-116 新契约）')
  fx = await makeFixture()
  fx.write("print('SCENARIOS ran=3 pass=3 fail=0 (0s)')\n")
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      // 260928 修（main 红直修）：原判据钉中文短语「零场景信号」，而 260927/260930 的执行器
      // 收口改造把 verify_lane 回执文案换成英文（'zero scenario signal (exit=0 with no
      // PASS/FAIL/ENV_FAIL rows, …)'）——**意图不变、文案漂移**，属「契约不变的实现重构打破
      // 集成测试=测试写错」一型。判据改绑浅（不钉可翻译文案）：显式红（green===false）+ 具名
      // err（非空串）+ 不冒充内容面（不带 ran 计数）。KI-116 逃逸口复发（静默绿）时 green 会是
      // true，本判据照样咬得住。
      const zeroSignalRed = r.green === false && typeof r.err === 'string'
        && r.err.length > 0 && (r.ran === undefined || r.ran === 0)
      ok(zeroSignalRed,
        'D1 无文本行/规范行/INTEG_SUMMARY(ran>0) → 零场景信号显式红（不冒充绿）：'
        + 'green=' + r.green + ' err=' + JSON.stringify(String(r.err).slice(0, 80)))
    } else ok(false, 'D0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()

  // ---------- D2. 仅 INTEG_SUMMARY(ran>0) 无明细：信号在场，不红（KI-116） ----------
  // 判据与闸判定面同源：汇总行 ran>0 构成信号（防守卫误杀规范行协议回执——
  // arbitrate 打回令修正点）；绿红仍由闸用例判定面/重算复核决定，此处只锁「不红」。
  section('D2. 仅 INTEG_SUMMARY(ran>0)：信号在场，零信号守卫不触发')
  fx = await makeFixture()
  // 260928 修（main 红直修，本条此前是**假绿**）：原夹具把 JS 语句写进了 .py——
  //   print('INTEG_SUMMARY ' + JSON.stringify({ran: 2, …}))
  // 该文件被 python3 执行即 SyntaxError、exit=1，于是回执走的是「执行器没产出任何结果
  // （exit=1）」分支，err 里当然不含被断言的中文短语 ⇒ 断言恒真、而**被测的
  // INTEG_SUMMARY(ran>0) 信号路径根本没被走到**（守卫误杀面一次未验）。今按真 Python
  // 重造夹具，并同步把判据改绑浅（err 面缺席=守卫未误杀 + 绿，不钉文案）。
  fx.write("import json\nprint('INTEG_SUMMARY ' + json.dumps({'ran': 2, 'pass': 2, 'fail': 0, 'wall_s': 1, 'concurrency': 1}))\n")
  {
    const res = fx.call()
    if (res.ok) {
      const r = res.result
      ok(r.green === true && !r.err,
        'D2 汇总行 ran>0 在场 → 不判零场景信号（守卫不误杀协议形态）：'
        + 'green=' + r.green + ' err=' + JSON.stringify(String(r.err)))
    } else ok(false, 'D2-0 调用失败: ' + (res.stderr || ''))
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
      // 260928 修（main 红直修）：原判据钉「键集**恰为** {lane,green,err}」，而 260927/260930
      // 的收口改造给 err 态回执加了**合法非内容附加键**（warnings / supply_used_sec /
      // runner_used_sec 这类计量与告警面）——原意图（err 态不泄漏**内容形状**键、消费方按 err
      // 分流）没变，是「断言钉死了实现形状」一型。判据改绑浅且不放宽：三个契约键必在场 +
      // 内容形状键（red_count/checks/ran/pass/fail/env_fail/scenarios/cases/detail_red/
      // summary）**一律不许在场**——code 道的 red_count/checks 泄漏进来照样咬红。
      const keys = Object.keys(r).sort()
      const required = ['err', 'green', 'lane']
      const contentShape = ['red_count', 'checks', 'ran', 'pass', 'fail', 'env_fail',
        'scenarios', 'cases', 'detail_red', 'summary']
      const leaked = contentShape.filter(k => keys.includes(k))
      ok(required.every(k => keys.includes(k)) && leaked.length === 0,
        'E2 err 态不泄漏 content 形状键：必在场 {lane,green,err}、零内容键（消费方按 err 分流）'
        + '；实得键集=[' + keys.join(',') + '] 泄漏=[' + leaked.join(',') + ']')
    } else ok(false, 'E0 调用失败: ' + (res.stderr || ''))
  }
  await fx.cleanup()
} finally {
  if (fx) { try { await fx.cleanup() } catch { /* already cleaned */ } }
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
