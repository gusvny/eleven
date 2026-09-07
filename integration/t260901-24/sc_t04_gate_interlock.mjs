/**
 * t04-gate-interlock —— t260901-24「capture-lane 状态注入」门旗联锁与缺省口径基线。
 *
 * 直跑：node integration/t260901-24/t04-gate-interlock.mjs（cwd=泳道根）。
 *
 * 黑盒契约（第 2 稿方案 R2/联锁 + review C1）：
 *   - 注入是显式 opt-in：capture.mjs 带 `--fixtures`（或 env SUYOU_UI_CAPTURE_FIXTURES=1）
 *     而无 allow-seed 通路 → 退出码 2 + 人话拒因（提门旗），直连真生产台绝不允许注假票；
 *   - allow-seed 通路 + fixtures → 参数层放行（--selftest 干跑，不起浏览器）；
 *   - 缺省（无任何 fixture 通路）→ 行为通路无关：缺省与 env 置空的 selftest 视图数
 *     一致且非零（视图数字面不锚——capture 工具合法加视图随票演进，t260907-05 gen4 起）；
 *   - capture-lane.mjs --selftest 带/不带 SUYOU_CAPTURE_FIXTURES=1 均全绿
 *     （opt-in 只影响真拍传参，不影响自测）。前提守卫：泳道 worktree 缺 gitignored
 *     的 profile/node_modules 时（环境事实），selftest 按设计 fail-closed——
 *     该形态改验「拒跑+报因精确、可跑前段计绿不假报」，见 capture-lane selftest 节。
 *
 * 全部子进程干跑（--selftest / 参数错误路径），不 boot 控制台、不开浏览器、不碰 3099。
 *
 * t260904-07 仲裁迭代（tests-fault 修正）：capture-lane selftest 段补环境前提卫兵——
 * <repo>/server/dsh/profile/node_modules 软链族是环境工件不入 git，fresh worktree 泳道
 * 布局缺失时该段三腿曾假红（违反 t260904-12 三态「缺环境=ENV_FAIL，绝不 exit 0」执行契约）；缺失→ENV_FAIL+归因，
 * 前提在位环境断言面逐条不变。
 *
 * t260904-11 仲裁 gen1（tests-fault 修正②）：capture-lane 容差修复镜像合入+验收段
 * 供给升级（泳道残留「断链」sandbar-workbench 软链）后，existsSync 复刻谓词与工具实际
 * 就绪脱钩（链断而工具全绿），选错分支三腿假红。教训=前提判定不得复刻被测物内部
 * 谓词，只认可观测行为：分支依据改为本 run 退出码，两套契约断言逐字保留。
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

let passed = 0, failed = 0, envFailed = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function envFail(label) {
  envFailed++; console.log(`  ENV_FAIL ${label}（环境缺件，没验成——原因归环境，exit 2）`)
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = mkdtempSync(join(tmpdir(), 't260901-24-t04-'))

// 260904 回迁守卫（KI-036）：本树与主树 ui-check 均缺 playwright-core（依赖未随迁移
// 恢复，安装=宿主沙箱外 npm install）→ ENV_FAIL（exit 2）不假红；依赖恢复后本守卫自动生效，
// 断言面不变。
{
  const pwLane = join(REPO, 'server', 'dsh', 'ui-check', 'node_modules', 'playwright-core')
  const pwMain = join(resolve(REPO, '..', '..'), 'server', 'dsh', 'ui-check',
                      'node_modules', 'playwright-core')
  if (!process.env.SUYOU_PLAYWRIGHT_MODULE && !existsSync(pwLane) && !existsSync(pwMain)) {
    console.log('ENV_FAIL（KI-036）：ui-check 缺 playwright-core（本树+主树均无），'
      + '宿主沙箱外安装恢复后本守卫自动生效')
    process.exit(2)
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

  section('缺省回归：无任何 fixture 通路 → 视图口径通路无关（视图数不随 fixtures 通路改变）')
  // t260907-05 arbitrate gen4 修正：原断言钉死「视图数=7」属快照型锚（capture 工具
  // 合法加视图即 rot——gen4 扩 docs/providers 视图后 7→9 假红）。守卫本意（本场景
  // docstring）=通路无关性：缺省与 env 置空的 selftest 行为一致、视图清单非空。
  // 视图数字面不锚（随工具演进）；两次运行相等 + 非零承载契约。
  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o5'), '--selftest'])
  ok(r.status === 0, `缺省 selftest 退出 0（实际：${r.status}）`)
  const viewsDefault = (r.stdout.match(/视图数=(\d+)/) || [])[1]
  ok(viewsDefault !== undefined && Number(viewsDefault) > 0,
    `缺省 selftest 报告非零视图数（实际：${viewsDefault ?? '未找到'}）`)
  r = run(CAPTURE, ['--url', 'http://127.0.0.1:9', '--out', join(tmp, 'o6'), '--selftest'],
    { SUYOU_UI_CAPTURE_FIXTURES: '' })
  const viewsEmptyEnv = (r.stdout.match(/视图数=(\d+)/) || [])[1]
  ok(viewsEmptyEnv === viewsDefault,
    `env 显式置空 → 视图数与缺省一致（env 空串=关闭语义；实际：${viewsEmptyEnv ?? '未找到'} vs ${viewsDefault ?? '未找到'}）`)

  section('capture-lane selftest：带/不带 SUYOU_CAPTURE_FIXTURES 均全绿')
  // 前提守卫（合并版：t260904-04 arbitrate gen3 双模断言 × t260904-06 arbitrate KI-036②
  // 守卫，两边守的是同一条硬前提=<repo>/server/dsh/profile/node_modules/sandbar-workbench
  // 软链——组临时 profile 要改指泳道 build；gitignored 实体，主树有、worktree 泳道不随迁，
  // KI-036② 泳道依赖软链未随迁移恢复）。取两边语义之强：前提在=跑原三条全绿断言（两边
  // 断言逐字相同）；前提缺=工具按设计 fail-closed，验「拒跑+报因说到点上+不假报全绿」
  // 而非旧口径放行放过（旧 skip 语义已退役，被本侧正向断言覆盖；软链补齐自动切回真
  // 跑，断言面不变）。谜底记录：本场景此前在此泳道一直走旧跳过通路（主树 ui-check 装
  // playwright-core 后守卫翻转才首跑，t260904-06 泳道实锤 selftest 2/6 绿后在
  // buildTempProfile 掷错），泳道缺 profile/node_modules 属环境事实非实现回归。
  const laneProfileWb = join(REPO, 'server', 'dsh', 'profile', 'node_modules', 'sandbar-workbench')
  // 分支依据=工具可观测行为（本 run 退出码），不再复刻其内部就绪谓词。
  // t260904-11 仲裁 gen1（tests-fault 修正②）：容差修复镜像合入 + 验收段供给升级
  // （泳道出现「断链」的 sandbar-workbench 软链——验收残留物，指向 ../workbench 解析
  // 到不存在的 profile/workbench）后，existsSync 复刻谓词与工具实际就绪脱钩：软链
  // 断链 → 旧判定取 fail-closed 分支，工具实际按容差语义全绿 → 三腿全假红。改按
  // 每次 run 自身退出码分支；全绿形态与 fail-closed 形态两套断言逐字保留（谁在位
  // 验谁），断言强度零变化。laneProfileWb 仅余诊断用途。
  const laneLinkState = existsSync(laneProfileWb) ? '在'
    : (existsSync(join(REPO, 'server', 'dsh', 'profile', 'node_modules')) ? '断链' : '缺')
  r = run(CAPTURE_LANE, ['--selftest'])
  const profileReady = r.status === 0
  if (profileReady) {
    ok(/全绿/.test(r.stdout), `capture-lane --selftest 缺省全绿（实际：exit ${r.status}；` +
      `${(/全绿[^\n]*/.exec(r.stdout) || ['（无全绿标记）'])[0]}；泳道软链${laneLinkState}）`)
  } else {
    ok(r.status !== 0 && r.stderr.includes('主树 profile/node_modules 缺 sandbar-workbench 软链'),
      `泳道缺 profile/node_modules → selftest fail-closed 且报因精确（实际：${r.status}；${firstLine(r.stderr)}）`)
  }
  r = run(CAPTURE_LANE, ['--selftest'], { SUYOU_CAPTURE_FIXTURES: '1' })
  if (profileReady) {
    ok(r.status === 0, `capture-lane --selftest 带 SUYOU_CAPTURE_FIXTURES=1 全绿（实际：${r.status}）`)
  } else {
    ok(r.status !== 0, `泳道缺 profile/node_modules → fixtures=1 通路同样 fail-closed 拒跑（实际：${r.status}）`)
  }
  if (profileReady) {
    ok(/全绿/.test(r.stdout), 'capture-lane selftest 输出含全绿标记')
  } else {
    ok(/selftest 1\/6 绿/.test(r.stdout) && !/全绿（/.test(r.stdout),
      '泳道缺 profile/node_modules → 可跑前段仍计绿、不假报全绿（实际：'
      + (/selftest \d\/6 绿[^\n]*/.exec(r.stdout) || ['（无进度标记）'])[0] + '）')
  }
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

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFailed}`)
if (failed > 0) { console.log('FAILURES:\n  - ' + failures.join('\n  - ')); process.exit(1) }
