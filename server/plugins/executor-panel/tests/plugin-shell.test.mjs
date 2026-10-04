/**
 * plugin-shell.test.mjs —— 生产路由壳 UT（t261003-10 票面要求④的单元侧；
 * t261004-11 换源：actions 夹具=项目执行器动作账 executor-actions.jsonl，schema v1）：
 * startPluginHarness 经 node.ts 真 apply() 注册面起真 http 服务，验证：
 *   - /api/actions、/api/projects（旧漏注册面）经壳可达；
 *   - 表外路径生产同形 404；
 *   - close() 收口服务器并还原 process.env（零残留）。
 * 隔离目录 + 注入项目账本夹具（引擎产出真行逐字拷贝），零 3099/7233 触碰。
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import { startPluginHarness } from '../harness.mjs'

const here = dirname(fileURLToPath(import.meta.url))
// 引擎产出真行的逐字拷贝（真行 verbatim 纪律）：allowed + refused ×2 + 夜间档溯源。
const realRows = readFileSync(join(here, 'fixtures', 'executor-actions-real.jsonl'), 'utf8')
const iso = freshDir('ep-shell-')
const panelDir = join(iso, 'panel')
const watchdogDir = join(iso, 'watchdog')
mkdirSync(panelDir, { recursive: true })
mkdirSync(watchdogDir, { recursive: true })
const actionsDir = join(iso, 'ledger')
mkdirSync(actionsDir, { recursive: true })
const ledgerFile = join(actionsDir, 'sandbar.jsonl')
writeFileSync(ledgerFile, realRows)

let n = 0
const beforeEnv = { ...process.env }
const H = await startPluginHarness({ panelDir, watchdogDir, executorActionsDir: actionsDir })
try {
  // 漏注册过的路径（生产 404 的两条）经壳可达；真行经壳展示。
  const g = await fetch(H.base + '/sandbar-executor-panel/api/actions?project=sandbar').then((r) => r.json())
  const rows = (g && g.actions) || []
  assert(g.ok === true && rows.length === 4 && rows.every((x) => x.action && x.result),
    'GET /api/actions routed through the production shell: real schema-v1 rows served')
  assert(rows.some((x) => x.result === 'refused' && x.reason), 'refused rows carry the reason for the hover text')
  const p = await fetch(H.base + '/sandbar-executor-panel/api/projects').then((r) => r.json())
  assert(p.ok === true && Array.isArray(p.projects), 'GET /api/projects routed through the production shell')
  // 表外路径：生产同形 404。
  const r404 = await fetch(H.base + '/sandbar-executor-panel/api/nope')
  assert(r404.status === 404, 'off-table path → shell 404 (same shape as production)')
  // 注册集合含全部表内路径。
  assert(H.registeredRoutes.includes('/sandbar-executor-panel/api/actions') && H.registeredRoutes.includes('/sandbar-executor-panel/api/projects'),
    'shell registered the full route table')
  // 只读红线：读前后项目账本字节一致。
  assert(readFileSync(ledgerFile, 'utf8') === realRows, 'project ledger byte-identical after reads (R5)')
  n += 6

  // 源缺席：ok:false + 新空态文案（记录自本票启动 + 点名文件路径），不冒充空列表。
  const H3 = await startPluginHarness({ panelDir, watchdogDir, executorActionsDir: join(iso, 'no-such-ledger') })
  try {
    const g3 = await fetch(H3.base + '/sandbar-executor-panel/api/actions?project=sandbar').then((r) => r.json())
    assert(g3.ok === false && g3.reason.includes('no recorded executor action') && g3.reason.includes('sandbar.jsonl'),
      'absent source degrades with the new empty copy naming the file')
    n += 1
  } finally {
    await H3.close()
  }
} finally {
  await H.close()
}
assert(process.env.SANDBAR_PANEL_DIR === beforeEnv.SANDBAR_PANEL_DIR
  && process.env.SANDBAR_EXECUTOR_ACTIONS_DIR === beforeEnv.SANDBAR_EXECUTOR_ACTIONS_DIR
  && process.env.HOME === beforeEnv.HOME, 'close() restores process.env (zero residue)')
n += 1

cleanup([iso])
done(n)
