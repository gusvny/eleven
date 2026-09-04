/**
 * t04-gate-interlock —— t260901-24「capture-lane 状态注入」门旗联锁与缺省口径基线。
 *
 * 直跑：node integration/t260901-24/t04-gate-interlock.mjs（cwd=泳道根）。
 *
 * 黑盒契约（第 2 稿方案 R2/联锁 + review C1）：
 *   - 注入是显式 opt-in：capture.mjs 带 `--fixtures`（或 env SUYOU_UI_CAPTURE_FIXTURES=1）
 *     而无 allow-seed 通路 → 退出码 2 + 人话拒因（提门旗），直连真生产台绝不允许注假票；
 *   - allow-seed 通路 + fixtures → 参数层放行（--selftest 干跑，不起浏览器）；
 *   - 缺省（无任何 fixture 通路）→ 行为与现 7 视图口径逐字节一致（selftest 视图数不变）；
 *   - capture-lane.mjs --selftest 带/不带 SUYOU_CAPTURE_FIXTURES=1 均全绿
 *     （opt-in 只影响真拍传参，不影响自测）。
 *
 * 全部子进程干跑（--selftest / 参数错误路径），不 boot 控制台、不开浏览器、不碰 3099。
 */

import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const CAPTURE = join(REPO, 'server', 'dsh', 'ui-check', 'capture.mjs')
const CAPTURE_LANE = join(REPO, 'server', 'dsh', 'ui-check', 'capture-lane.mjs')

let passed = 0, failed = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = mkdtempSync(join(tmpdir(), 't260901-24-t04-'))

// 260904 回迁守卫（KI-036）：本树与主树 ui-check 均缺 playwright-core（依赖未随迁移
// 恢复，安装=宿主沙箱外 npm install）→ 干净 SKIP 不假红；依赖恢复后本守卫自动生效，
// 断言面不变。
{
  const pwLane = join(REPO, 'server', 'dsh', 'ui-check', 'node_modules', 'playwright-core')
  const pwMain = join(resolve(REPO, '..', '..'), 'server', 'dsh', 'ui-check',
                      'node_modules', 'playwright-core')
  if (!process.env.SUYOU_PLAYWRIGHT_MODULE && !existsSync(pwLane) && !existsSync(pwMain)) {
    console.log('SKIP（KI-036）：ui-check 缺 playwright-core（本树+主树均无），'
      + '宿主沙箱外安装恢复后本守卫自动生效')
    process.exit(0)
  }
}
try {
  section('联锁拒跑：--fixtures 无 allow-seed 通路 → 退出 2 + 人话提门旗')
  let r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o1'),
    '--fixtures', join(tmp, 'fx')])
  ok(r.status === 2, `旗通路拒跑退出码 2（实际：${r.status}）`)
  ok(/allow-seed|门旗|fixtures/i.test(r.stderr), `拒因人话提门旗（实际：${firstLine(r.stderr)}）`)

  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o2'), '--fixtures', 'x'], {
    SUYOU_UI_CAPTURE_ALLOW_SEED: '', SUYOU_UI_CAPTURE_FIXTURES: '1',
  })
  ok(r.status === 2, `env 通路（UI_CAPTURE_FIXTURES=1 无 allow-seed）拒跑退出 2（实际：${r.status}）`)

  section('联锁放行：allow-seed + fixtures → 参数层放行（selftest 干跑绿）')
  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o3'),
    '--fixtures', join(tmp, 'fx'), '--allow-seed', '--selftest'])
  ok(r.status === 0, `--allow-seed + --fixtures + --selftest 退出 0（实际：${r.status}；stderr：${firstLine(r.stderr)}）`)
  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o4'),
    '--fixtures', join(tmp, 'fx'), '--selftest'], { SUYOU_UI_CAPTURE_ALLOW_SEED: '1' })
  ok(r.status === 0, `env allow-seed 通路 + --fixtures 放行（实际：${r.status}）`)

  section('缺省回归：无任何 fixture 通路 → 7 视图口径不变')
  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o5'), '--selftest'])
  ok(r.status === 0, `缺省 selftest 退出 0（实际：${r.status}）`)
  ok(/视图数=7\b/.test(r.stdout), `缺省视图数=7 不变（实际：${(r.stdout.match(/视图数=\d+/) || ['未找到'])[0]}）`)
  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o6'), '--selftest'],
    { SUYOU_UI_CAPTURE_FIXTURES: '' })
  ok(/视图数=7\b/.test(r.stdout), 'env 显式置空 → 仍 7 视图（env 空串=关闭语义）')

  section('capture-lane selftest：带/不带 SUYOU_CAPTURE_FIXTURES 均全绿')
  r = run(CAPTURE_LANE, ['--selftest'])
  ok(r.status === 0, `capture-lane --selftest 缺省全绿（实际：${r.status}；${firstLine(r.stderr)}）`)
  r = run(CAPTURE_LANE, ['--selftest'], { SUYOU_CAPTURE_FIXTURES: '1' })
  ok(r.status === 0, `capture-lane --selftest 带 SUYOU_CAPTURE_FIXTURES=1 全绿（实际：${r.status}）`)
  ok(/全绿/.test(r.stdout), 'capture-lane selftest 输出含全绿标记')
} finally {
  rmSync(tmp, { recursive: true, force: true })
}

function run(script, args, extraEnv = {}) {
  return spawnSync(process.execPath, [script, ...args], {
    cwd: REPO,
    encoding: 'utf8',
    env: { ...process.env,
      SUYOU_UI_CAPTURE_ALLOW_SEED: '', SUYOU_UI_CAPTURE_FIXTURES: '',
      SUYOU_CAPTURE_FIXTURES: '',
      // 本树 ui-check 缺 playwright-core 时镜像 capture-lane 的回退：主树 ui-check
      // （worktree 布局 <main>/.worktrees/<id> 与引擎泳道布局同构）。环境已设则不覆盖。
      ...(!process.env.SUYOU_PLAYWRIGHT_MODULE && !existsSync(join(REPO, 'server', 'dsh', 'ui-check',
        'node_modules', 'playwright-core'))
        ? { SUYOU_PLAYWRIGHT_MODULE: join(resolve(REPO, '..', '..'), 'server', 'dsh', 'ui-check',
            'node_modules', 'playwright-core') }
        : {}),
      ...extraEnv },
  }) || { status: -1, stdout: '', stderr: 'spawnSync 失败' }
}
function firstLine(s) {
  return String(s || '').split('\n')[0].slice(0, 140) || '（无输出）'
}

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
if (failed > 0) { console.log('FAILURES:\n  - ' + failures.join('\n  - ')); process.exit(1) }
