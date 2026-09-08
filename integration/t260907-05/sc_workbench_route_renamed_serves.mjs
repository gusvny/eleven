#!/usr/bin/env node
/**
 * sc_workbench_route_renamed_serves.mjs —— 工单台路由前缀迁移契约（t260907-05，灰盒 L3）。
 *
 * intent（用户可感知）：宿主令命名迁移②落地后，工单台 API 只以 /sandbar-workbench/
 * 一个前缀对外服务，旧前缀 /suyou-workbench/ 死透（直接换不留旧=无 301/308/410 兼容层，
 * 工单正文旧前缀策略的机器化）。用户可感知面=「新前缀路由在位并真实应答、旧前缀
 * 一律 404、浏览器 bundle 内自洽同一前缀」——路由注册与产物里留旧名=用户按界面/
 * 文档打出死链接。
 *
 * 断言面（锚定路由契约与产物自洽，不绑 handler 内部实现）：
 *  T1 新前缀真 handler 应答：GET /sandbar-workbench/api/wf/temporal-health → 200
 *     （该 handler 恒 200 人话信封、零引擎 spawn——探测 Temporal 端口只读，生产
 *     Temporal 只读红线允许面；7233 离线也 200+detail，不锚业务数字）；
 *  T2 旧前缀同路径 → 404（无兼容层：非 301/308/410/200）；
 *  T3 旧前缀 tickets 列表路径 → 404（旧 exact 死透；不 fetch 新 tickets——那会
 *     spawn 真 admin CLI 查引擎，红线面归隔离台场景族与宿主走查，本条不越界）；
 *  T4 注册面收口：mock webServer 收到的全部路由注册 path 含 /sandbar-workbench/
 *     且零 /suyou-workbench/（含 src/host 常量挂载的 session-charter 路由——
 *     KI-042 同源防漂移设计在这里一并收口）；
 *  T5 bundle 双产物自洽：workbench/lib/client.js 与 client.cjs 均含
 *     /sandbar-workbench/ 且零 /suyou-workbench/（src 改了产物没重建=浏览器半仍打旧名）。
 *
 * 与既有资产 intent 区别（防 intent 级重复）：
 * - t260903-13/sc_workbench_bundle_loads 守 bundle 可加载（产物完整性的加载面）；
 *   本条守前缀迁移后的路由服务契约与产物内命名自洽——加载成功不等于名字改对。
 * - 工单台业务旅程（tickets 生命周期）归既有场景族与隔离台；本条只守「名字」这一层，
 *   不消费引擎链路（3099 全程零接触，server 只绑 127.0.0.1 ephemeral 端口）。
 *
 * harness：黑盒 import workbench/node.ts（type-stripping 直跑）＋mock ctx
 * （webServer.register 收集注册、effect 就地执行、logger 静默）→ 自起 http server
 * 按 exact/prefix 语义分发 → fetch 断言。node.ts 依赖零 npm 包（六插件 dependencies
 * 全空），全仓内相对导入。unhandledRejection 兜底吞 apply 内 void 异步（boot 指纹
 * 探测容错面），守卫自身不得成为新报错源。
 *
 * 预期状态：实现段已迁 node.ts/import/主文件——T1~T5 应绿；bundle 未随票重建则 T5 红
 * （该红正是本条的存在意义）。Run: node integration/t260907-05/sc_workbench_route_renamed_serves.mjs（cwd=仓库根）
 * 三态契约：无外部环境依赖（stdlib+仓内文件）——不设 ENV_FAIL 路径；末行
 * SUMMARY pass=N fail=N；exit 1 iff fail>0。
 */
import http from 'node:http'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = join(HERE, '..', '..')

process.on('unhandledRejection', () => {}) // apply 内 void 异步容错面；断言失败走 FAIL 不走崩溃

// ---- mock ctx：只实现 node.ts apply 消费的面 ----
const routes = []
const webServer = {
  register: (r) => {
    routes.push(r)
    return () => {}
  },
}
const ctx = {
  get: (key) => (key === 'webServer' ? webServer : undefined),
  effect: (fn) => {
    try { fn() } catch { /* effect 注册失败随实现容错，不在这里放大 */ }
  },
  logger: { info: () => {}, warn: () => {}, error: () => {} },
}

let nodeApi
try {
  nodeApi = await import(join(REPO, 'server/plugins/workbench/node.ts'))
} catch (err) {
  console.log('  FAIL import workbench/node.ts: %s', String(err?.message ?? err))
  console.log('SUMMARY pass=0 fail=1')
  process.exit(1)
}
nodeApi.apply(ctx, { repo: REPO })

if (routes.length === 0) {
  console.log('  FAIL apply 未挂载任何路由（webServer 注入面断裂）')
  console.log('SUMMARY pass=0 fail=1')
  process.exit(1)
}

// ---- exact/prefix 语义分发（照 dsh webServer 契约的最小面） ----
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://local').pathname
  const hit = routes.find((r) => r.kind === 'exact' && r.path === pathname)
    ?? routes.find((r) => r.kind === 'prefix' && pathname.startsWith(r.path))
  if (!hit) {
    res.writeHead(404)
    res.end()
    return
  }
  Promise.resolve(hit.handler(req, res)).catch(() => {
    try { res.writeHead(500); res.end() } catch { /* 已提交头 */ }
  })
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const base = 'http://127.0.0.1:' + server.address().port

let passed = 0
let failed = 0
const check = (cond, label, ...args) => {
  const text = args.length ? label.replace(/%s/g, () => args.shift()) : label
  if (cond) { passed++; console.log('  ok   %s', text) } else { failed++; console.log('  FAIL %s', text) }
}
const statusOf = async (p) => {
  try {
    const r = await fetch(base + p, { redirect: 'manual' })
    await r.arrayBuffer()
    return r.status
  } catch { return -1 }
}

try {
  console.log('== 1. 新前缀真 handler 应答（temporal-health：零 spawn、恒 200 人话信封）')
  const s1 = await statusOf('/sandbar-workbench/api/wf/temporal-health')
  check(s1 === 200, 'GET /sandbar-workbench/api/wf/temporal-health → 200（实得 %s）', s1)

  console.log('== 2. 旧前缀死透（直接换不留旧：404，非 3xx/410/200）')
  const s2 = await statusOf('/suyou-workbench/api/wf/temporal-health')
  check(s2 === 404, '旧前缀 temporal-health → 404（实得 %s）', s2)
  const s3 = await statusOf('/suyou-workbench/api/wf/tickets')
  check(s3 === 404, '旧前缀 tickets → 404（实得 %s；此腿不 fetch 新 tickets——spawn 面归隔离台）', s3)

  console.log('== 3. 注册面收口：全部路由 path 只认新前缀')
  const staleRoutes = routes.filter((r) => r.path.includes('/suyou-workbench/'))
  const foreign = routes.filter((r) => !r.path.startsWith('/sandbar-workbench/'))
  check(staleRoutes.length === 0,
    '注册路由零 /suyou-workbench/ 残留%s', staleRoutes.length ? '——' + staleRoutes.map((r) => r.path).join(', ') : '')
  check(foreign.length === 0,
    '注册路由全部 /sandbar-workbench/ 前缀（含 session-charter 常量路由）%s',
    foreign.length ? '——' + foreign.map((r) => r.path).join(', ') : '')

  console.log('== 4. bundle 双产物自洽（src 改了产物没重建=浏览器半仍打旧名）')
  for (const f of ['lib/client.js', 'lib/client.cjs']) {
    const p = join(REPO, 'server/plugins/workbench', f)
    let text = null
    try { text = await readFile(p, 'utf8') } catch { text = null }
    check(text !== null && text.includes('/sandbar-workbench/') && !text.includes('/suyou-workbench/'),
      'workbench/%s 含新前缀且零旧前缀%s', f, text === null ? '（文件缺席）' : '')
  }
} finally {
  server.close()
}

console.log('SUMMARY pass=%d fail=%d', passed, failed)
process.exit(failed ? 1 : 0)
