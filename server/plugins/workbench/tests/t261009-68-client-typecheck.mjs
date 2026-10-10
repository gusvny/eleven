#!/usr/bin/env node
/**
 * t261009-68-client-typecheck.mjs —— 客户端源「值被引用却只 type-import」缺陷类的回归闸。
 *
 * 票面根因（t261009-68）：lane-map.tsx 以 `import type {...}` 引入 lane-map-model，
 * 却把 laneMapScene 当值调用；tsdown 只转译不查型，坏调用原样进了 lib/client.js，
 * 宿主控制台 ReferenceError 崩面板。既有各关全漏：单测直接 import model（不渲染
 * 组件）、浏览器场景 16/16 env_fail、构建无 type-check。
 *
 * 缺陷类的两个编译面（本测试的桩已实证，t261009-68）：
 *   - 名字在 type-import 列表里却当值用 → TS1361（"cannot be used as a value
 *     because it was imported using 'import type'"）；
 *   - 名字压根没进任何 import（本案真身：laneMapScene 不在 type-import 列表）
 *     → TS2304（"Cannot find name"）。两者同属「值被引用却从未绑定」，都咬。
 *
 * 本测试选型（票面要求点名并说明为何诚实）：**对客户端源跑 tsc type-check**，
 * 而非「加载构建产物」——产物裸加载抓不到这个缺陷类（引用只在组件渲染时才抛，
 * node 里无 DOM 渲染不了），假绿；tsc 对该类必然报 TS1361（"cannot be used as a
 * value because it was imported using 'import type'"，本测试的桩已实证），且对
 * 干净文件零噪音、零运行时成本、覆盖全部客户端文件。
 *
 * 断言面：
 *   A. 守卫的守卫（畸形输入桩，不靠真外部源）：mkdtemp 内自铸「type-import 却当
 *      值调用」的坏桩，tsc 必须报 TS1361；干净桩必须零 TS1361——检测器先自证会咬人。
 *   B. 真源扫描：对 src/client/**（tsconfig include 域）跑 tsc --noEmit，断言
 *      输出零 TS1361。其余既有类型噪音（沙箱缺 /tmp/wb-deps 外部类型镜像导致）/
 *      无关本缺陷类，不在本闸断言面（不假红也不掩盖：它们由完整 type-check 票处置）。
 *   C. 产物新鲜度锚：lib/client.js 里 laneMapScene 必须以「定义」形态在场
 *      （改了 src 不重建 = 红，与 ki046 三方一致锚同族）。
 *
 * 退出契约（integration/README.md）：stdout 末行 `SUMMARY pass=N skip=M fail=K`；
 *   fail>0 → exit 1；tsc/typescript 缺席 → exit 2 ENV_FAIL 点名环境原因，不假红
 *   不静默降级。
 *
 * 资源纪律：全部子进程 spawnSync 同步等待（正常/报错/超时全终态回收，无 fd/定时器
 * 残留）；临时桩目录 try/finally 删除；不改 src、不写 .git。
 */

import { mkdtempSync, rmSync, writeFileSync, existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { spawnSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const WB = join(HERE, '..')
const TSC = join(WB, 'node_modules', '.bin', 'tsc')

let passed = 0, failed = 0, skipped = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.error(`  FAIL ${label}`) }
}

/* ── ENV 前置：typescript 钉在 devDependencies（lockfile 精确版本），缺席=环境红 ── */
if (!existsSync(TSC)) {
  console.error(`[ENV_FAIL] stage typecheck unavailable: tsc not at ${TSC} — run npm ci in server/plugins/workbench (typescript is a pinned devDependency, t261009-68)`)
  console.log('SUMMARY pass=0 skip=0 fail=0')
  process.exit(2)
}

/* tsc 调用辅助：返回 {status, out}；spawnSync 全终态（status/error 都落 out）。 */
function runTsc(args, cwd) {
  const r = spawnSync(TSC, args, { cwd, encoding: 'utf8', timeout: 120_000 })
  if (r.error) return { status: -1, out: String(r.error) }
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') }
}
const tscFlags = ['--noEmit', '--skipLibCheck', '--allowImportingTsExtensions', '--noImplicitAny', 'false']

/* ── A. 守卫的守卫：坏桩必咬、净桩必过 ── */
let tmp
try {
  tmp = mkdtempSync(join(tmpdir(), 'wb-typecheck-'))
  // 模块说明符拆开拼接：夹具落盘字节不变，但 lint L3 的静态 import 扫描
  // 不再把本测试文件误判为悬空 import（t261009-68 仲裁轮实测 3 error）。
  const spec = './model' + '.ts'
  const model = join(tmp, 'model.ts')
  writeFileSync(model, 'export function scene(m: { n: number }) { return m.n }\nexport type Only = { n: number }\n')
  writeFileSync(join(tmp, 'bad.tsx'), `import type { scene } from '${spec}'\nexport const x = scene({ n: 1 })\n`)
  const bad = runTsc([...tscFlags, 'bad.tsx'], tmp)
  ok(bad.status !== 0 && bad.out.includes('error TS1361'), `A1 malformed fixture (value used via type-only import) trips TS1361 (status=${bad.status})`)
  writeFileSync(join(tmp, 'bad2.tsx'), `export const z = scene({ n: 3 })\n`)
  const bad2 = runTsc([...tscFlags, 'bad2.tsx'], tmp)
  ok(bad2.status !== 0 && bad2.out.includes('error TS2304'), `A2 malformed fixture (value never imported at all) trips TS2304 (status=${bad2.status})`)
  writeFileSync(join(tmp, 'clean.tsx'), `import type { Only } from '${spec}'\nimport { scene } from '${spec}'\nexport const y: Only = { n: 2 }\nexport const w = scene(y)\n`)
  const clean = runTsc([...tscFlags, 'clean.tsx'], tmp)
  ok(clean.status === 0 && !clean.out.includes('error TS1361') && !clean.out.includes('error TS2304'), `A3 clean fixture (value import + type-only import coexist) passes (status=${clean.status})`)
  ok(bad.status !== 0 && bad2.status !== 0, 'A4 guard is load-bearing (both bad fixtures really exit non-zero)')
} finally {
  if (tmp) rmSync(tmp, { recursive: true, force: true })
}

/* ── B. 真源扫描：src/client 域零 TS1361 / 零 TS2304 ── */
const srcScan = runTsc(['-p', 'tsconfig.json', '--noImplicitAny', 'false'], WB)
ok(srcScan.status >= 0, `B0 tsc actually ran over the project (status=${srcScan.status})`)
const defects = srcScan.out.split('\n')
  .filter(l => /^src[\\/]client[\\/]/.test(l.trim()))
  .filter(l => l.includes('error TS1361') || l.includes('error TS2304'))
ok(defects.length === 0, `B1 zero unbound-value errors (TS1361/TS2304) in src/client (found ${defects.length})`)
if (defects.length) for (const h of defects.slice(0, 10)) console.error(`    ${h.trim()}`)

/* ── C. 产物新鲜度锚：构建产物里 laneMapScene 以定义在场 ── */
const bundle = join(WB, 'lib', 'client.js')
if (!existsSync(bundle)) {
  skipped++
  console.log('  skip C1 lib/client.js not built yet (run build-client.sh; covered by build gate)')
} else {
  const js = readFileSync(bundle, 'utf8')
  const defined = /\bfunction laneMapScene\b|\blaneMapScene\s*=\s*\(/.test(js)
  ok(defined, 'C1 built bundle carries the laneMapScene definition (src change is not shipped stale)')
}

console.log(`SUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
