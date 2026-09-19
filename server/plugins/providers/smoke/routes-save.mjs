/**
 * smoke/routes-save.mjs —— 模型路由表「视图→草稿→载荷→保存」全链冒烟。
 *
 * 直跑：node smoke/routes-save.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 *
 * 【t260916-26 修复：真源夹具化】本 smoke 曾直接 buildRoutesView(仓库根) 读
 * 「机器级注册表声明的真源表」+ 用 SANDBAR_PROJECTS_YAML（legacy 单文件 env）
 * 挂临时注册表——两条路在 t260914-05 后都断了：① lane worktree 不在注册表
 * （decl_missing → roles 空 → 草稿访问 crash）；② routes.ts 的注册表解析只认
 * SANDBAR_PROJECTS_DIR / ~/.sandbar/projects（per-key 目录形态），legacy env
 * 已不消费。改为全夹具：临时 per-key 注册表（project.yaml 声明 dirs[0] +
 * paths.model_routes 指向临时表，表内容=仓内兜底表拷贝作种子），A/B 走
 * buildRoutesView 的 projectsDir 注入点，C/D 走 SANDBAR_PROJECTS_DIR——
 * 对机器态零依赖（ui/src/host/routes.ts 反查 readFileSync 列目录缺陷因此也
 * 不再影响本 smoke；该缺陷在 ui/ 插件内、本票写集外，报告另行登记）。
 * 视图解析镜像生产口径（ui/node.ts:211/244）：显式传 projectKey（?project=
 * 同源），不走反查。
 *
 * 覆盖（浏览器半 RoutesTableSection 的纯函数在 src/host/routes-edit.ts，冒烟直测同一代码）：
 *   A. 视图→草稿→载荷 round-trip：draftFromView(buildRoutesView 真源) → draftToPayload
 *      → applyRouteEdits 对真源文本 → changed 应为空（载荷即现状，无扰动）。
 *   B. 编辑语义：改 developer.model / 清空 integration.model → 补丁命中对应键路径，
 *      重解析后值生效；清空后查表向上落 default。
 *   C. 跨插件保存链路：sandbar-admin-ui 宿主 POST /sandbar-admin/api/routes/save
 *      （mock webServer）接收「路由表」分区会发的载荷 → 写声明的 model-routes.yaml
 *      （夹具表）+ 备份 /tmp + 响应 regenerate 提示；保存后 buildRoutesView 查表生效。
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
const REPO = join(HERE, '..', '..', '..', '..') // server/plugins/providers/smoke -> 仓库根

/* ------------------------------------------------ 夹具（每段独立） */

/**
 * 造一套「注册表+项目主目录+路由表」夹具：
 *   <tmp>/projects/smoketest/project.yaml   per-key 注册条目（schema v1，
 *                                           dirs[0]=<tmp>/repo，顶层 paths.model_routes
 *                                           声明指向临时表）
 *   <tmp>/repo/server/model-routes.yaml     表内容=仓内兜底表拷贝（真 YAML 语义种子）
 * 返回 { tmp, root, repo, table }。声明用绝对路径（resolveRoutesFilePath 的
 * 绝对/~/相对三形态里最直白的一种；相对形态会归 join(primaryDir, decl) 同点）。
 */
async function makeFixture() {
  const tmp = await mkdtemp(join(tmpdir(), 'syp-routes-fix-'))
  const root = join(tmp, 'projects')
  const repo = join(tmp, 'repo')
  const table = join(repo, 'server', 'model-routes.yaml')
  await mkdir(join(root, 'smoketest'), { recursive: true })
  await mkdir(join(repo, 'server'), { recursive: true })
  await copyFile(join(REPO, 'server', 'model-routes.yaml'), table)
  const projectYaml = join(root, 'smoketest', 'project.yaml')
  await writeFile(projectYaml, [
    'schema: v1',
    'project:',
    '  - key: smoketest',
    '    name: 冒烟',
    '    dirs:',
    `      - ${repo}`,
    'paths:',
    `  model_routes: ${table}`,
    '',
  ].join('\n'), 'utf8')
  return { tmp, root, repo, table }
}

/* ------------------------------------------------------------ A. round-trip 无扰动 */

section('A 视图→草稿→载荷 round-trip（对真源零扰动）')
{
  const fx = await makeFixture()
  try {
    const view = await buildRoutesView(fx.repo, { projectsDir: fx.root, projectKey: 'smoketest' })
    ok(view.state === 'ok' && view.error === undefined,
       `真源视图可建（state=${view.state}${view.resolution_error ? ' ' + view.resolution_error : ''}）`)
    const draft = draftFromView(view)
    // 期望值从视图推导，不硬编 provider/model——夹具表内容变化不炸冒烟
    const devRow = view.roles.find(rr => rr.role === 'developer')
    ok(devRow !== undefined, '夹具表含 developer 角色（种子=仓内兜底表）')
    ok(draft.roles.developer?.provider === devRow?.effective?.provider,
       '草稿继承 developer 条目值')
    const proofTask = draft.roles['product-operation']?.tasks?.proofread
    ok(proofTask !== undefined && proofTask.model !== '',
       '草稿继承分工 tasks.proofread 条目')
    const payload = draftToPayload(draft)
    ok(Object.keys(payload.roles ?? {}).length >= 3, '载荷含全部角色')
    ok(payload.roles['product-operation'].tasks.proofread.provider === proofTask.provider,
       '载荷含分工条目')
    const text = await readFile(fx.table, 'utf8')
    const r = applyRouteEdits(text, payload)
    ok(r.changed.length === 0, `载荷即现状 → 零变更（${r.changed.join(',')}）`)
  } finally {
    await rm(fx.tmp, { recursive: true, force: true })
  }
}

/* ------------------------------------------------------------ B. 编辑语义 */

section('B 编辑语义：改值 / 清空落兜底')
{
  const fx = await makeFixture()
  try {
    const view = await buildRoutesView(fx.repo, { projectsDir: fx.root, projectKey: 'smoketest' })
    const draft = draftFromView(view)
    draft.roles.developer.model = 'k3-256k' // 用户改 developer 模型
    draft.roles.integration.model = ''      // 用户清空 integration（落 default）
    const payload = draftToPayload(draft)
    ok(payload.roles.developer.model === 'k3-256k' && payload.roles.integration.model === '', '载荷带编辑值（含显式空串）')
    const text = await readFile(fx.table, 'utf8')
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
    ok(via('integration') === `${root.default.provider}/${root.default.model}`, '清空后查表落 default（断言被清空的角色；ops 自有条目，断言它会与 default 解耦）')
  } finally {
    await rm(fx.tmp, { recursive: true, force: true })
  }
}

/* ------------------------------------------------------------ C. 跨插件保存链路 */

section('C 保存链路：providers 载荷 → ui 宿主 POST → 写表+备份+提示')
{
  const fx = await makeFixture()
  try {
    // 多项目化（260823）+ per-key 注册表（t260910-14/t260914-05 后唯一形态）：
    // ui 宿主保存链的 key 解析（project-registry findProject）与表路径解析
    // （routes.ts readDeclaredRoutesPath）都读 SANDBAR_PROJECTS_DIR 根下各
    // project.yaml——该 env 每次调用现读，先设后用（夹具随 tmp 删除即失效）。
    process.env.SANDBAR_PROJECTS_DIR = fx.root
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo: fx.repo })
    const saveRoute = routes.find(x => x.kind === 'exact' && x.path === '/sandbar-admin/api/routes/save')
    const getRoute = routes.find(x => x.kind === 'exact' && x.path === '/sandbar-admin/api/routes')
    ok(saveRoute !== undefined && getRoute !== undefined, 'ui 宿主 routes GET+save 路由都在')

    // 模拟「路由表」分区：真源视图 → 草稿 → 改 developer 模型 → 载荷
    const view = await buildRoutesView(fx.repo, { projectsDir: fx.root, projectKey: 'smoketest' })
    const draft = draftFromView(view)
    draft.roles.developer.model = 'k3-256k'
    const payload = draftToPayload(draft)

    const res = () => ({ status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } })
    const req = (body) => ({
      url: '/sandbar-admin/api/routes/save?project=smoketest', method: 'POST',
      [Symbol.asyncIterator]: async function* () { yield Buffer.from(JSON.stringify(body), 'utf8') },
    })
    const r1 = res()
    await saveRoute.handler(req({ table: payload }), r1)
    ok(r1.status === 200 && r1.body.ok === true, `保存 200 ok${r1.body.ok ? '' : `（${r1.body.error}）`}`)
    ok(r1.body.result.changed.includes('roles/developer/model'), 'changed 含编辑键')
    ok(typeof r1.body.result.backup === 'string' && r1.body.result.backup.startsWith(tmpdir()), '备份落系统临时目录')
    ok((r1.body.result.regenerate ?? '').includes('生效'), '响应含生效话术（运行时查表）')

    const after = await buildRoutesView(fx.repo, { projectsDir: fx.root, projectKey: 'smoketest' })
    ok(after.roles.find(rr => rr.role === 'developer')?.effective?.model === 'k3-256k', '保存后查表生效')

    // 无变更 → written=false
    const r2 = res()
    await saveRoute.handler(req({ table: draftToPayload(draftFromView(after)) }), r2)
    ok(r2.body.ok === true && r2.body.result.written === false, '保存后再次保存同值 → 无变更不写')
  } finally {
    delete process.env.SANDBAR_PROJECTS_DIR
    await rm(fx.tmp, { recursive: true, force: true })
  }
}

/* ------------------------------------------------------------ D. 非法载荷拒绝 */

section('D 非法载荷拒绝（宿主 schema 兜底，不写文件）')
{
  const fx = await makeFixture()
  try {
    process.env.SANDBAR_PROJECTS_DIR = fx.root
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo: fx.repo })
    const saveRoute = routes.find(x => x.kind === 'exact' && x.path === '/sandbar-admin/api/routes/save')
    const res = () => ({ status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } })
    const req = (body) => ({
      url: '/sandbar-admin/api/routes/save?project=smoketest', method: 'POST',
      [Symbol.asyncIterator]: async function* () { yield Buffer.from(JSON.stringify(body), 'utf8') },
    })
    const r = res()
    await saveRoute.handler(req({ table: { roles: { hacker: { provider: 'x', model: 'y' } } } }), r)
    ok(r.body.ok === false && (r.body.error ?? '').includes('不可编辑'), '未登记角色 → 200 ok:false')
    const text = await readFile(fx.table, 'utf8')
    ok(!text.includes('hacker'), '文件未被污染')
  } finally {
    delete process.env.SANDBAR_PROJECTS_DIR
    await rm(fx.tmp, { recursive: true, force: true })
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
