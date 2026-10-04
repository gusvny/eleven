// sc_t26100310_route_shell_parity.mjs — t261003-10 路由注册壳契约（灰盒 L3，
// 生产注册壳驱动，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；工单 Finding 1 + Required outcome 2/3）：控制台用户在
// 生产形态（node.ts 的真实注册表）下访问面板 API——**每一个 api.handle 认的路
// 径都必须可达**。改动前 /api/actions 与 /api/projects 在生产 404（注册表只有
// 5 条 exact 路由，t260930-09 起 /api/projects 静默失联）；旧缝
// （t261003-06 harness）把 /api/* 直通 api.handle，永远看不见这张注册表。
//   P1 生产壳在场：经**真实插件注册壳**（startPluginHarness，非 api.handle 直通）
//      访问 /api/actions、/api/projects 均≠404（改动前双 404=本票点名缺陷回归面）。
//   P2 全注册面巡检：/api/grants、/api/settings、/api/requests 经同一生产壳照旧
//      ≠404（改注册表不许 regress 既有路由）。
//   P3 未知路径照旧 404（巡检不放松 404 语义）。
//   P4 /api/projects 分类=接线（gen1 方案裁定，有真消费面
//      tests/page-projects.test.mjs / tests/projects.test.mjs）：读出 ok:true 且
//      形状为项目列表承诺（非 404 即可判 P1；本条只锁「可达」不锁列表内容）。
//
// 缝契约（developer 随本票实现）：server/plugins/executor-panel/harness.mjs 新增
// startPluginHarness({ panelDir, adminLogPath, port? }) -> { base, close() }——
// 用真实 node.ts apply() + 捕捉式 webServer.register 架真 http.Server。缝缺席或
// 仍只有直通 startHarness = FAIL exit 1 且点名（TDD 期红属预期，arbitrate/merge
// 期必须绿）。三态纪律：node 缺席=ENV_FAIL exit 2；闸内无 SKIP。
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { existsSync } from 'node:fs'
import { makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

export const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const PANEL_ROUTE = '/sandbar-executor-panel'

const C = makeCase()

async function main() {
  if (!existsSync(HARNESS_PATH)) {
    C.case('harness-present', false, 'server/plugins/executor-panel/harness.mjs 缺场')
    return C.exit()
  }
  const mod = await import('file://' + HARNESS_PATH).catch((e) => {
    C.case('harness-loadable', false, String(e).slice(0, 300))
    return null
  })
  if (!mod) return C.exit()
  if (typeof mod.startPluginHarness !== 'function') {
    C.case('plugin-shell-seam-present', false,
      'harness.mjs 缺 startPluginHarness（生产注册壳缝；直通 startHarness 看不见 node.ts 注册表——本票 Finding 3 的缝缺陷面，缝契约见本文件头注）')
    return C.exit()
  }
  const iso = makeIsoDir()
  const H = await mod.startPluginHarness({
    panelDir: join(iso.dir, 'panel'),
    adminLogPath: join(iso.dir, 'admin-log-does-not-exist.jsonl'), // 本场景只锁路由可达，读源缺席属场景 B 面
  })
  try {
    // P1 + P4：改动前生产 404 的两条路径，经生产壳必须可达
    for (const [name, path] of [
      ['actions-route-reachable', PANEL_ROUTE + '/api/actions?project=alpha'],
      ['projects-route-reachable', PANEL_ROUTE + '/api/projects'],
    ]) {
      const r = await fetch(H.base + path).catch((e) => ({ status: 0, body: null, err: String(e) }))
      if (r.status === 404) {
        C.case(name, false, '生产注册壳返回 404（本票点名缺陷仍在：api.handle 认的路由未注册进生产壳）')
      } else if (r.status === 0) {
        C.case(name, false, '请求失败：' + (r.err || 'no status'))
      } else {
        C.case(name, true, 'status=' + r.status)
      }
    }
    // P2：既有五条注册面不得 regress
    for (const path of ['/api/grants', '/api/settings', '/api/requests']) {
      const r = await fetch(H.base + PANEL_ROUTE + path).catch((e) => ({ status: 0, err: String(e) }))
      C.case('legacy-route-' + path.replace(/\W+/g, '-'), r.status !== 404 && r.status !== 0,
        'status=' + r.status)
    }
    // P3：未知路径照旧 404
    const miss = await fetch(H.base + PANEL_ROUTE + '/api/definitely-not-a-route').catch(() => ({ status: 0 }))
    C.case('unknown-route-still-404', miss.status === 404, 'status=' + miss.status)
  } finally {
    await H.close()
  }
  C.exit()
}

main().catch((e) => { console.error('FATAL', e); process.exit(1) })
