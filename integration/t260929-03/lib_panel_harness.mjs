// lib_panel_harness — t260929-03 executor-panel 集成场景的公共缝（灰盒 L2/L3）。
//
// 测试缝协议（锚定 seam，不锚实现细节；watchdog harness.mjs 同款先例）：
// 插件包须提供 `server/plugins/executor-panel/harness.mjs`，导出：
//   startHarness({ port = 0, panelDir, watchdogDir, workbenchBase = '' })
//     -> Promise<{ base, close(): Promise<void> }>
// 语义：把插件**真实的路由处理面**（console 挂载的同一 handler）架在临时端口上；
//   panelDir/watchdogDir 即 SANDBAR_PANEL_DIR / SANDBAR_WATCHDOG_DIR 语义的注入点
//   （请求台账与 watchdog.json 都落在调用方给的隔离目录）；workbenchBase 是 grants
//   推导读模板拓扑的远端基址（测试可指向死端口或本地桩）。close() 收口服务器与
//   定时器，零残留。缺省端口 0=内核分配（永不撞 3099/7233）。
//
// 三态纪律：node 缺席=ENV_FAIL exit 2；harness/实现未落地=FAIL exit 1 且点名
// 缺什么（TDD 期红属预期，arbitrate/merge 期必须绿）。
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'

export const REPO = fileURLToPath(new URL('../../', import.meta.url))
export const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')

/** 动态装载插件测试缝；缺席返回 null（调用方点名 FAIL）。 */
export async function loadPanelHarness() {
  if (!existsSync(HARNESS_PATH)) return null
  try {
    return await import('file://' + HARNESS_PATH)
  } catch (e) {
    throw new Error('harness.mjs 在场但装载失败: ' + String(e).slice(0, 300))
  }
}

/** 隔离目录夹具（进程退出全回收——lint L8 tmp 卫生纪律）。 */
export function makeIsoDir(prefix = 'panel-sc-') {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  let cleaned = false
  const clean = () => { if (!cleaned) { cleaned = true; rmSync(dir, { recursive: true, force: true }) } }
  process.on('exit', clean)
  process.on('SIGINT', () => { clean(); process.exit(130) })
  return { dir, clean }
}

/** 三态 SUMMARY 出口（t260904-12：0=全过；1=有 FAIL；2=有 ENV_FAIL）。 */
export function makeCase() {
  const cases = []
  return {
    case(name, ok, reason = '') {
      cases.push({ name, ok, reason })
      console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
    },
    envFail(name, reason) {
      cases.push({ name, env: true })
      console.log(`[ENV_FAIL] ${name} — ${reason}`)
    },
    exit() {
      const pass = cases.filter(c => c.env !== true && c.ok).length
      const fail = cases.filter(c => c.env !== true && !c.ok).length
      const env = cases.filter(c => c.env === true).length
      console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${env} na=0`)
      process.exit(env > 0 ? 2 : fail > 0 ? 1 : 0)
    },
  }
}
