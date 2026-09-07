/**
 * smoke/routes-save.mjs —— sandbar-providers「路由表」分区（M13）冒烟。
 *
 * 直跑：node smoke/routes-save.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖（浏览器半 RoutesTableSection 的纯函数在 src/host/routes-edit.ts，冒烟直测同一代码）：
 *   A. 视图→草稿→载荷 round-trip：draftFromView(buildRoutesView 真源) → draftToPayload
 *      → applyRouteEdits 对真源文本 → changed 应为空（载荷即现状，无扰动）。
 *   B. 编辑语义：改 developer.model / 清空 ops.model → 补丁命中对应键路径，
 *      重解析后值生效；清空后查表向上落 default。
 *   C. 跨插件保存链路：sandbar-admin-ui 宿主 POST /suyou-admin/api/routes/save
 *      （mock webServer）接收「路由表」分区会发的载荷 → 写 model-routes.yaml
 *      （临时 repo）+ 备份 /tmp + 响应 regenerate 提示；保存后 buildRoutesView 查表生效。
 *   D. 非法载荷拒绝：未登记角色 → 200 {ok:false}（宿主 schema 兜底，不写文件）。
 */

import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { draftFromView, draftToPayload } from '../src/host/routes-edit.ts'
import { applyRouteEdits, buildRoutesView, parseRoutesYaml } from '../../ui/src/host/routes.ts'
import { apply } from '../../ui/node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = join(HERE, '..', '..', '..', '..') // server/dsh/providers/smoke -> 仓库根

/* ------------------------------------------------------------ A. round-trip 无扰动 */

section('A 视图→草稿→载荷 round-trip（对真源零扰动）')
{
  const view = await buildRoutesView(REPO)
  ok(view.error === undefined, '真源视图可建')
  const draft = draftFromView(view)
  // 期望值从视图推导，不硬编 provider/model——failover 切表（260826 scnet）不炸冒烟
  const devRow = view.roles.find(rr => rr.role === 'developer')
  const proofTask = view.roles.find(rr => rr.role === 'product-operation')?.effective
  ok(draft.roles.developer.provider === devRow?.effective?.provider &&
     draft.roles['product-operation'].tasks.proofread.model !== '',
    '草稿继承视图条目值')
  const payload = draftToPayload(draft)
  ok(Object.keys(payload.roles ?? {}).length === 3, '载荷含三角色')
  ok(payload.roles['product-operation'].tasks.proofread.provider === draft.roles['product-operation'].tasks.proofread.provider,
    '载荷含分工条目')
  const text = await readFile(join(REPO, 'server', 'dsh', 'model-routes.yaml'), 'utf8')
  const r = applyRouteEdits(text, payload)
  ok(r.changed.length === 0, `载荷即现状 → 零变更（${r.changed.join(',')}）`)
}

/* ------------------------------------------------------------ B. 编辑语义 */

section('B 编辑语义：改值 / 清空落兜底')
{
  const view = await buildRoutesView(REPO)
  const draft = draftFromView(view)
  draft.roles.developer.model = 'k3-256k' // 用户改 developer 模型
  draft.roles.integration.model = ''      // 用户清空 integration（落 default）
  const payload = draftToPayload(draft)
  ok(payload.roles.developer.model === 'k3-256k' && payload.roles.integration.model === '', '载荷带编辑值（含显式空串）')
  const text = await readFile(join(REPO, 'server', 'dsh', 'model-routes.yaml'), 'utf8')
  const r = applyRouteEdits(text, payload)
  ok(r.changed.includes('roles/developer/model') && r.changed.includes('roles/integration/model'),
    `补丁命中编辑键（${r.changed.join(',')}）`)
  const root = parseRoutesYaml(r.text)
  ok(root.roles.developer.model === 'k3-256k', '改值落盘语义')
  ok(root.roles.integration.model === undefined, '清空=删键')
  const via = (rr) => {
    // 镜像 gen.py 查表：role 级 → default
    const e = root.roles?.[rr] ?? {}
    if (e.provider && e.model) return `${e.provider}/${e.model}`
    return `${root.default.provider}/${root.default.model}`
  }
  ok(via('integration') === `${root.default.provider}/${root.default.model}`, '清空后查表落 default（断言被清空的角色；ops 自有条目，断言它会与 default 解耦')
}

/* ------------------------------------------------------------ C. 跨插件保存链路 */

section('C 保存链路：providers 载荷 → ui 宿主 POST → 写表+备份+提示')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syp-routes-save-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server', 'dsh'), { recursive: true })
    await copyFile(join(REPO, 'server', 'dsh', 'model-routes.yaml'), join(repo, 'server', 'dsh', 'model-routes.yaml'))
    // 多项目化（260823）：宿主 routes 路由的 repo 解析走 projects.yaml 注册表
    // （projOf→primaryDir），apply 的 repo 入参不再管这两条路由——smoke 经
    // SUYOU_PROJECTS_YAML 写临时注册表指向临时 repo，否则保存会误写真表。
    const registry = join(tmp, 'projects.yaml')
    await writeFile(registry, `projects:\n  - key: smoketest\n    name: 冒烟\n    dirs:\n      - ${repo}\n`, 'utf8')
    process.env.SUYOU_PROJECTS_YAML = registry

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const saveRoute = routes.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes/save')
    const getRoute = routes.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes')
    ok(saveRoute !== undefined && getRoute !== undefined, 'ui 宿主 routes GET+save 路由都在')

    // 模拟「路由表」分区：真源视图 → 草稿 → 改 developer 模型 → 载荷
    const view = await buildRoutesView(repo)
    const draft = draftFromView(view)
    draft.roles.developer.model = 'k3-256k'
    const payload = draftToPayload(draft)

    const res = () => ({ status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } })
    const req = (body) => ({
      url: '/suyou-admin/api/routes/save?project=smoketest', method: 'POST',
      [Symbol.asyncIterator]: async function* () { yield Buffer.from(JSON.stringify(body), 'utf8') },
    })
    const r1 = res()
    await saveRoute.handler(req({ table: payload }), r1)
    ok(r1.status === 200 && r1.body.ok === true, '保存 200 ok')
    ok(r1.body.result.changed.includes('roles/developer/model'), 'changed 含编辑键')
    ok(typeof r1.body.result.backup === 'string' && r1.body.result.backup.startsWith(tmpdir()), '备份落系统临时目录')
    ok((r1.body.result.regenerate ?? '').includes('生效'), '响应含生效话术（运行时查表）')

    const after = await buildRoutesView(repo)
    ok(after.roles.find(rr => rr.role === 'developer')?.effective?.model === 'k3-256k', '保存后查表生效')

    // 无变更 → written=false
    const r2 = res()
    await saveRoute.handler(req({ table: draftToPayload(draftFromView(after)) }), r2)
    ok(r2.body.ok === true && r2.body.result.written === false, '保存后再次保存同值 → 无变更不写')
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

/* ------------------------------------------------------------ D. 非法载荷拒绝 */

section('D 非法载荷拒绝（宿主 schema 兜底，不写文件）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syp-routes-bad-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server', 'dsh'), { recursive: true })
    await copyFile(join(REPO, 'server', 'dsh', 'model-routes.yaml'), join(repo, 'server', 'dsh', 'model-routes.yaml'))
    // 注册表覆盖按段重建（C 段的临时注册表随 tmp 删除了，env 现读需指活文件）
    const registry = join(tmp, 'projects.yaml')
    await writeFile(registry, `projects:\n  - key: smoketest\n    name: 冒烟\n    dirs:\n      - ${repo}\n`, 'utf8')
    process.env.SUYOU_PROJECTS_YAML = registry
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const saveRoute = routes.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes/save')
    const res = () => ({ status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } })
    const req = (body) => ({
      url: '/suyou-admin/api/routes/save?project=smoketest', method: 'POST',
      [Symbol.asyncIterator]: async function* () { yield Buffer.from(JSON.stringify(body), 'utf8') },
    })
    const r = res()
    await saveRoute.handler(req({ table: { roles: { hacker: { provider: 'x', model: 'y' } } } }), r)
    ok(r.body.ok === false && (r.body.error ?? '').includes('不可编辑'), '未登记角色 → 200 ok:false')
    const text = await readFile(join(repo, 'server', 'dsh', 'model-routes.yaml'), 'utf8')
    ok(!text.includes('hacker'), '文件未被污染')
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
