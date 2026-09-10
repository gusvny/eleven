#!/usr/bin/env node
/**
 * sc_toolchain_pinned.mjs —— t260910-15：打包工具链锁定完备负锁。
 *
 * 用户故事：260910 宿主实测 t260908-01 diff 出现 300+ 行「表观抖动」
 * （Infinity↔1/0、花括号风格），病灶=打包工具（tsdown）版本未钉死——仓内两把
 * lockfile 互相矛盾（package-lock 锁 0.22.2、pnpm-lock 锁 0.22.14），谁按哪把
 * 装依赖就得到哪个压缩器。用户可感知承诺：仓内不存在任何会拉到非 0.22.2 tsdown
 * 的活声明口径——lockfile 就是这个承诺的载体。本场景只读断言：
 *   P1 package.json devDependencies.tsdown 恰 "0.22.2"、无 ^/~ 范围前缀；
 *   P2 package-lock.json 根 specifier 与 node_modules/tsdown resolved 均 0.22.2；
 *   P3 pnpm-lock.yaml importers 段 tsdown specifier/version 均 0.22.2；
 *   P4 口径载体文件集（package.json / 两把 lockfile / tsdown.config.ts /
 *      build-client.sh / README.md）零 "0.22.14" 漂移版本词面——出账版本的
 *      活口径只可能长在承诺载体上；叙述面（验收记录/场景/报告）出现版本号
 *      是合法历史叙述，不扫不误咬（t260903-12 验收记录实录此命中形态）。
 *   P5 组件公开构建入口（package.json scripts.build）指向仓内构建脚本，
 *      不再是可漂移的裸 tsdown 入口；
 *  红绿自证（防恒真）：判定函数先吃合成样本——0.22.14 锁样必须判红、
 *  0.22.2 锁样必须判绿，自证不过则真仓的绿不可信。
 *
 * 与 developer L1（workbench/tests/build-determinism.mjs 负锁断言）intent 分工：
 * L1 随实现交付、随实现重写、不作契约网；本场景是闸内常驻契约网，锚仓内文件
 * 终态（lockfile=用户可审的承诺载体）与组件公开接口（package.json scripts），
 * 不锚行号与内部结构。与 t260903-04 bundle-sync（src≡lib 同步面）intent 不同：
 * 那条守「改了 src 别忘重建」，本条守「重建必然可复现」。
 *
 * 灰盒：纯读仓，零端口、零 3099、零网络、零构建、零写。
 * Exit contract（三态，t260904-12 定稿闸内无 SKIP）：末行 SUMMARY pass=N fail=K
 * na=W；fail>0 或全 na → exit 1；env_fail>0 → exit 2。
 */
import { readFileSync } from 'node:fs'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const wb = join(root, 'server/plugins/workbench')

/* 判定核心：输入三份声明文本（package.json / package-lock.json / pnpm-lock.yaml
 * 的相关片段），输出违反项清单。供真仓与合成样本共用（红绿自证的前提是
 * 判定逻辑同一份）。 */
function violationsOf({ pkgJson, npmLockJson, pnpmLockText, expectVersion }) {
  const bad = []
  const EXPECT = expectVersion

  // P1 package.json 精确版本 + 无范围前缀
  let pkg
  try { pkg = JSON.parse(pkgJson) } catch { bad.push('package.json 不可解析'); pkg = null }
  if (pkg) {
    const spec = pkg?.devDependencies?.tsdown
    if (spec === undefined) bad.push('package.json 无 devDependencies.tsdown 声明')
    else if (spec !== EXPECT) bad.push(`package.json tsdown specifier=${spec} ≠ ${EXPECT}`)
    else if (/^[~^]/.test(spec)) bad.push('package.json tsdown 仍为范围版本') // 不可达（上面已挡），防御性留档
  }

  // P2 npm lockfile：根 specifier + resolved 双点
  let lock
  try { lock = JSON.parse(npmLockJson) } catch { bad.push('package-lock.json 不可解析'); lock = null }
  if (lock) {
    const rootSpec = lock?.packages?.['']?.devDependencies?.tsdown
    if (rootSpec !== EXPECT) bad.push(`package-lock 根 specifier=${rootSpec} ≠ ${EXPECT}`)
    const resolved = lock?.packages?.['node_modules/tsdown']?.version
    if (resolved !== EXPECT) bad.push(`package-lock tsdown resolved=${resolved} ≠ ${EXPECT}`)
  }

  // P3 pnpm lockfile：importers 段 specifier/version 双点（锚结构不锚行号）
  const m = pnpmLockText.match(/tsdown:\n\s+specifier: (\S+)\n\s+version: (\S+)/)
  if (!m) bad.push('pnpm-lock.yaml 无可解析的 tsdown specifier/version 块')
  else {
    if (m[1] !== EXPECT) bad.push(`pnpm-lock specifier=${m[1]} ≠ ${EXPECT}`)
    if (m[2] !== EXPECT) bad.push(`pnpm-lock version=${m[2]} ≠ ${EXPECT}`)
  }
  return bad
}

/* P4 词面扫描核心：口径载体内容里出现漂移版本字面=活口径风险。供真仓与
 * 合成样本共用（自证前提=判定逻辑同一份）。定义先于自证段（const 无 TDZ）。 */
const DRIFT_LITERAL = '0.22.14'
function carrierHit(text) { return text.includes(DRIFT_LITERAL) }

/* ------------------------------------------------ 0. 红绿自证（防恒真） */
section('0. 判定器红绿自证（合成样本）')
{
  const green = violationsOf({
    pkgJson: JSON.stringify({ devDependencies: { tsdown: '0.22.2' } }),
    npmLockJson: JSON.stringify({ packages: { '': { devDependencies: { tsdown: '0.22.2' } }, 'node_modules/tsdown': { version: '0.22.2' } } }),
    pnpmLockText: 'importers:\n  .:\n    devDependencies:\n      tsdown:\n        specifier: 0.22.2\n        version: 0.22.2\n',
    expectVersion: '0.22.2',
  })
  ok(green.length === 0, `合法锁样（全 0.22.2）判绿${green.length ? '：' + green.join('；') : ''}`)

  const red = violationsOf({
    pkgJson: JSON.stringify({ devDependencies: { tsdown: '^0.22.2' } }),
    npmLockJson: JSON.stringify({ packages: { '': { devDependencies: { tsdown: '^0.22.2' } }, 'node_modules/tsdown': { version: '0.22.14' } } }),
    pnpmLockText: 'importers:\n  .:\n    devDependencies:\n      tsdown:\n        specifier: ^0.22.2\n        version: 0.22.14\n',
    expectVersion: '0.22.2',
  })
  // 漂移样本必须至少咬出 4 处（pkg 范围 / npm 根 / npm resolved / pnpm 双点）
  ok(red.length >= 4, `漂移锁样（范围 specifier+漂移 resolved）判红且逐点点名（咬出 ${red.length} 处）`)

  ok(carrierHit('version: 0.22.14') === true, '词面扫描：漂移版本字面必咬')
  ok(carrierHit('version: 0.22.2') === false, '词面扫描：0.22.2 不误咬')
}

/* ------------------------------------------------ 1. 真仓锁定完备 */
section('1. 真仓：三份声明 + 口径载体词面负锁 + 公开构建入口')

const pkgPath = join(wb, 'package.json')
const npmLockPath = join(wb, 'package-lock.json')
const pnpmLockPath = join(wb, 'pnpm-lock.yaml')

// 文件在场性缺失=承诺载体缺失，是产品红（锁定面被拆），不是环境问题。
for (const p of [pkgPath, npmLockPath, pnpmLockPath]) {
  ok(existsSync(p), `${p.slice(root.length + 1)} 在场（缺=锁定承诺载体被拆）`)
}

if (existsSync(pkgPath) && existsSync(npmLockPath) && existsSync(pnpmLockPath)) {
  const v = violationsOf({
    pkgJson: readFileSync(pkgPath, 'utf8'),
    npmLockJson: readFileSync(npmLockPath, 'utf8'),
    pnpmLockText: readFileSync(pnpmLockPath, 'utf8'),
    expectVersion: '0.22.2',
  })
  ok(v.length === 0, `三份声明全钉 0.22.2${v.length ? '：' + v.join('；') : ''}`)

  // P4 口径载体文件集零漂移版本词面（叙述面与历史记录合法，不在扫描集合内——
  // t260903-12 验收记录等叙述出现版本号是历史陈述，词面全仓扫会误咬叙述并自咬本场景）。
  const carriers = [pkgPath, npmLockPath, pnpmLockPath,
    join(wb, 'tsdown.config.ts'), join(wb, 'build-client.sh'), join(wb, 'README.md')]
  const hits = []
  for (const p of carriers) {
    if (!existsSync(p)) continue // 缺席件的锁定面/构建面由上面三声明与场景1分别把守
    if (carrierHit(readFileSync(p, 'utf8'))) hits.push(p.slice(root.length + 1))
  }
  ok(hits.length === 0, `口径载体文件零 ${DRIFT_LITERAL} 漂移版本词面${hits.length ? '：命中 ' + hits.join(', ') : ''}`)

  // P5 公开构建入口指向仓内构建脚本（非裸 tsdown）
  let pkg
  try { pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) } catch { pkg = null }
  if (pkg) {
    const build = pkg?.scripts?.build
    ok(typeof build === 'string' && build.includes('build-client.sh'),
      `scripts.build 指向仓内唯一构建脚本（实际=${build}）`)
    ok(!(typeof build === 'string' && /(^|\s)tsdown(\s|$)/.test(build)),
      'scripts.build 不再是裸 tsdown 入口')
  }
}

/* ------------------------------------------------ 2. 汇总 */
console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
process.exit(failed > 0 ? 1 : 0)
