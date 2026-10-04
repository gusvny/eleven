/**
 * plugin-shell.test.mjs —— 生产路由壳 UT（t261003-10 票面要求④的单元侧）：
 * startPluginHarness 经 node.ts 真 apply() 注册面起真 http 服务，验证：
 *   - /api/actions、/api/projects（旧漏注册面）经壳可达；
 *   - 表外路径生产同形 404；
 *   - close() 收口服务器并还原 process.env（零残留）。
 * 隔离目录 + 注入 admin.log 夹具（真行拷贝），零 3099/7233 触碰。
 */
import { readFileSync, writeFileSync, mkdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import { startPluginHarness } from '../harness.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const realLine = readFileSync(join(here, 'fixtures', 'admin-log-real-current.jsonl'), 'utf8').split('\n')[0]
const iso = freshDir('ep-shell-')
const panelDir = join(iso, 'panel')
const watchdogDir = join(iso, 'watchdog')
mkdirSync(panelDir, { recursive: true })
mkdirSync(watchdogDir, { recursive: true })
const adminLog = join(iso, 'admin.log')
writeFileSync(adminLog, realLine + '\n')

let n = 0
const beforeEnv = { ...process.env }
const H = await startPluginHarness({ panelDir, watchdogDir, adminLogPath: adminLog })
try {
  // 漏注册过的路径（生产 404 的两条）经壳可达。
  const g = await fetch(H.base + '/sandbar-executor-panel/api/actions?project=sandbar').then((r) => r.json())
  assert(g.ok === false && g.reason.includes('none of them records which permission authorized it'),
    'GET /api/actions routed through the production shell (degraded honestly: this window has no permission-bearing rows)')
  const p = await fetch(H.base + '/sandbar-executor-panel/api/projects').then((r) => r.json())
  assert(p.ok === true && Array.isArray(p.projects), 'GET /api/projects routed through the production shell')
  // 表外路径：生产同形 404。
  const r404 = await fetch(H.base + '/sandbar-executor-panel/api/nope')
  assert(r404.status === 404, 'off-table path → shell 404 (same shape as production)')
  // 注册集合含全部表内路径。
  assert(H.registeredRoutes.includes('/sandbar-executor-panel/api/actions') && H.registeredRoutes.includes('/sandbar-executor-panel/api/projects'),
    'shell registered the full route table')
  // 只读红线：读前后 admin.log 字节一致。
  assert(readFileSync(adminLog, 'utf8') === realLine + '\n', 'admin.log byte-identical after reads (R5)')
  n += 5

  // 正面（真授权行夹具）：带 summary 顶层授权键的真行经壳展示动作+权限行。
  const grantRows = readFileSync(join(here, 'fixtures', 'admin-log-real-grant-rows.jsonl'), 'utf8')
  const adminLog2 = join(iso, 'admin-log-grant.log')
  writeFileSync(adminLog2, grantRows)
  const H2 = await startPluginHarness({ panelDir, watchdogDir, adminLogPath: adminLog2 })
  try {
    const g2 = await fetch(H2.base + '/sandbar-executor-panel/api/actions?project=sandbar').then((r) => r.json())
    const rows = (g2 && g2.actions) || []
    assert(g2.ok === true && rows.length === 3 && rows.every((x) => x.permission && x.ticket && x.action),
      'real grant rows served through the shell: action+ticket+permission on every row (summary-level keys)')
    assert(readFileSync(adminLog2, 'utf8') === grantRows, 'grant-rows fixture byte-identical after reads (R5)')
    n += 2
  } finally {
    await H2.close()
  }
} finally {
  await H.close()
}
assert(process.env.SANDBAR_PANEL_DIR === beforeEnv.SANDBAR_PANEL_DIR
  && process.env.SANDBAR_ADMIN_LOG === beforeEnv.SANDBAR_ADMIN_LOG
  && process.env.HOME === beforeEnv.HOME, 'close() restores process.env (zero residue)')
n += 1

cleanup([iso])
done(n)
