// lib_panel_seam.mjs — t261003-06 executor-panel 改版场景的公共缝（灰盒 L2/L3）。
//
// 复用 t260929-03 的缝协议（同款先例，不另立契约）：插件包须提供
// `server/plugins/executor-panel/harness.mjs`，导出 startHarness({...}) ->
// Promise<{ base, close() }>，把插件真实路由处理面架在临时端口（缺省 0=内核
// 分配，永不接触 3099）。t261003-06 扩展两项注入（向后兼容，均可选）：
//   eventsPath —— （t261003-06，已被 t261003-10 取代）「最近动作」读源的每项目事件账本路径。
//   t261003-10 扩展：startPluginHarness —— 生产路由壳缝（node.ts 真 apply() + stub
//   webServer 起 http 服务，请求流经生产注册面；漏注册的路径在此 404 与生产同形），
//   选项 { panelDir, watchdogDir, adminLogPath }——adminLogPath 注入「最近动作」读源
//   （引擎自审计 admin.log，SANDBAR_ADMIN_LOG 同键），close() 还原 env 零残留。
// 本文件只做装载/夹具/三态出口，零行为断言。三态纪律（t260904-12）：
// node 缺席=ENV_FAIL exit 2；harness/契约面未落地=FAIL exit 1 且点名（TDD 期红属
// 预期，arbitrate/merge 期必须绿）。
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'

export const REPO = fileURLToPath(new URL('../../', import.meta.url))
export const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
export const PANEL_PAGE_PATH = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')

export async function loadPanelHarness() {
  if (!existsSync(HARNESS_PATH)) return null
  try {
    return await import('file://' + HARNESS_PATH)
  } catch (e) {
    throw new Error('harness.mjs 在场但装载失败: ' + String(e).slice(0, 300))
  }
}

/** 隔离目录夹具（lint L8：进程退出全回收）。 */
export function makeIsoDir(prefix = 't261003-06-') {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  let cleaned = false
  const clean = () => { if (!cleaned) { cleaned = true; rmSync(dir, { recursive: true, force: true }) } }
  process.on('exit', clean)
  process.on('SIGINT', () => { clean(); process.exit(130) })
  return { dir, clean }
}

/** 三态 SUMMARY 出口（0=全过；1=有 FAIL；2=有 ENV_FAIL；闸内无 SKIP）。 */
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
