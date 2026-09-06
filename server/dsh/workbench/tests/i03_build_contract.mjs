/**
 * i03_build_contract.mjs — t260902-03 build-contract anchors for the global banner (hermetic).
 *
 * User story: the "restart console" reminder must be globally visible — on every tab/view
 * (board / knowledge / model routes / epics), not only inside the ticket-board view
 * (review round 1 rejected the Board-only mount). This baseline locks the mounting
 * contract statically so a regression back into a single view is caught without a browser:
 *
 *   1. Rebuilt client bundles (lib/client.cjs AND lib/client.js) both carry the banner copy
 *      and the build-info poll path — catches a forgotten tsdown rebuild.
 *   2. src/client/sidebar.tsx (the shared middle-column shell) hosts the staleness hook
 *      (useStaleBanner; t260905-07 握手矩阵接线改名，单实例挂点契约不变) and renders the banner (wb-stale-banner) ABOVE the
 *      `.wb-right-content` view container — i.e. outside the four mutually-exclusive
 *      views, so it persists across view switches.
 *   3. index.tsx (WorkbenchSection / board view) carries neither the banner markup nor the
 *      hook — regression guard against re-mounting it inside a single view.
 *
 * Hermetic: plain file reads, zero ports, zero 3099 contact.
 * Exit contract (integration/README.md): last stdout line `SUMMARY pass=N skip=M fail=K`;
 * exit 1 iff fail>0. Pre-implementation (or before the tsdown rebuild) RED by design.
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
for (const rel of ['server/dsh/workbench/lib/client.cjs', 'server/dsh/workbench/lib/client.js']) {
  const src = read(rel)
  if (src === null) {
    ok(false, `${rel} exists (run: cd server/dsh/workbench && npx -y tsdown@0.22.2 -c tsdown.config.ts)`)
    continue
  }
  ok(src.includes('重启控制台生效'), `${rel} contains banner copy 「重启控制台生效」（t260905-07 文案常量同源）`)
  ok(src.includes('suyou-workbench/api/build-info'), `${rel} contains build-info poll path`)
}

section('2. banner mounted in sidebar shared shell, above the four-view container')
const sidebar = read('server/dsh/workbench/src/client/sidebar.tsx')
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
const index = read('server/dsh/workbench/src/client/index.tsx')
ok(index !== null && !index.includes('wb-stale-banner') && !index.includes('useStaleBanner') && !index.includes('useStaleHost'),
  'index.tsx (WorkbenchSection) has no banner markup / hook reference')

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
