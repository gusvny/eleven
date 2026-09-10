/**
 * i03_build_contract.mjs —— 票 t260902-03 全局横幅的构建契约锚（密封）。
 *
 * 用户故事：「重启控制台」提醒必须全局可见——每个 tab/视图（board / knowledge /
 * model routes / epics），不能只待在工单台面视图里（评审第 1 轮打回了只挂
 * Board 的方案）。本基线静态锁定挂载契约，让「退回单视图」类回归无需浏览器
 * 即可捕获：
 *
 *   1. 重建后的客户端 bundle（lib/client.cjs 与 lib/client.js）都带横幅文案
 *      和 build-info 轮询路径——抓住忘跑 tsdown 重建的疏漏。
 *   2. src/client/sidebar.tsx（共享中列壳）承载陈旧 hook（useStaleBanner；
 *      t260905-07 握手矩阵接线改名，单实例挂点契约不变），并把横幅
 *      （wb-stale-banner）渲染在 `.wb-right-content` 视图容器之上——即在四个
 *      互斥视图之外，切视图不消失。
 *   3. index.tsx（WorkbenchSection / board 视图）既无横幅 markup 也无 hook——
 *      防「重新挂回单视图」的回归护栏。
 *
 * 密封：纯文件读取，零端口，零 3099 接触。
 * 退出契约（integration/README.md）：stdout 末行 `SUMMARY pass=N skip=M fail=K`；
 * fail>0 时 exit 1。实现落地前（或 tsdown 重建前）按设计为红。
 */

import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..', '..', '..')

const read = (rel) => {
  const p = join(root, rel)
  if (!existsSync(p)) return null
  return readFileSync(p, 'utf8')
}

section('1. rebuilt bundles carry banner copy + poll path (both cjs and esm)')
for (const rel of ['server/plugins/workbench/lib/client.cjs', 'server/plugins/workbench/lib/client.js']) {
  const src = read(rel)
  if (src === null) {
    ok(false, `${rel} exists (run: cd server/plugins/workbench && bash build-client.sh)`)
    continue
  }
  ok(src.includes('重启控制台生效'), `${rel} contains banner copy 「重启控制台生效」（t260905-07 文案常量同源）`)
  ok(src.includes('sandbar-workbench/api/build-info'), `${rel} contains build-info poll path`)
}

section('2. banner mounted in sidebar shared shell, above the four-view container')
const sidebar = read('server/plugins/workbench/src/client/sidebar.tsx')
if (sidebar === null) {
  ok(false, 'src/client/sidebar.tsx exists')
} else {
  ok(sidebar.includes('useStaleBanner'), 'sidebar.tsx hosts useStaleBanner (single hook instance at shell layer; t260905-07 rename)')
  ok(sidebar.includes('wb-stale-banner'), 'sidebar.tsx renders the wb-stale-banner markup')
  const bannerAt = sidebar.indexOf('role="alert"')
  const contentAt = sidebar.indexOf('className="wb-right-content"')
  ok(bannerAt !== -1, 'banner JSX present (role="alert")')
  ok(contentAt !== -1 && bannerAt < contentAt,
    'banner JSX appears before the .wb-right-content container (outside the mutually-exclusive views)')
}

section('3. board view must not re-mount the banner (regression guard)')
const index = read('server/plugins/workbench/src/client/index.tsx')
ok(index !== null && !index.includes('wb-stale-banner') && !index.includes('useStaleBanner') && !index.includes('useStaleHost'),
  'index.tsx (WorkbenchSection) has no banner markup / hook reference')

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
