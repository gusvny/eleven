/**
 * smoke/routes.mjs —— sandbar-admin-ui M12「模型路由」的宿主半冒烟。
 *
 * 直跑：node smoke/routes.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. parseRoutesYaml（src/host/routes.ts）：最小 YAML 子集解析（default/roles/tasks
 *      结构）；非法行/缩进/键重复/带引号值 → RoutesParseError 带行号（不静默丢）。
 *   B. effectiveRoute：查表链路 tasks.<kind> → roles.<role> → default；条目缺
 *      provider/model → 告警并向上落；全落空 → null。
 *   D. buildRoutesView 读「声明指向的表」（夹具注册表+自写夹具表，性质断言）：
 *      state=ok 读写同源、查表链/分工序/只读口径、常量面；声明文件缺失=file_missing
 *      点名+引导态（t260914-05：不回落任何仓内表）。
 *   E. /sandbar-admin/api/routes 路由（node.ts apply + mock webServer/req/res）：
 *      声明命中 → 200 路由表透传；未声明 → 200 ok+decl_missing 引导态，**仓内形状的
 *      表在场也不被读**（反毒断言）；routes/init 退役不再注册。
 *   H. 保存端点：声明命中正常保存（备份/生效话术）；未声明 → 显式拒写+建表指引
 *      （t260914-05：不代写仓内文件）。
 */

import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import {
  KINDS, PROVIDER_FAMILY, ROLES,
  RoutesParseError, applyRouteEdits, buildRoutesView, effectiveRoute,
  parseRoutesYaml, validateRouteTable,
} from '../src/host/routes.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ------------------------------------------------------------ A. parseRoutesYaml */

section('A parseRoutesYaml 严格最小子集解析')
{
  const yaml = `# 表头注释
default:
  provider: kimi-coding
  model: k3
roles:
  developer:         # 行尾注释
    provider: kimi-coding
    model: k3
    tasks:
      proofread:
        provider: zai
        model: glm-5.2
`
  const root = parseRoutesYaml(yaml)
  ok(root.default.provider === 'kimi-coding' && root.default.model === 'k3', 'default 条目解析')
  ok(root.roles.developer.provider === 'kimi-coding', 'roles.<role> 解析')
  ok(root.roles.developer.tasks.proofread.model === 'glm-5.2', 'tasks.<kind> 嵌套解析')
  ok(Object.keys(root).join(',') === 'default,roles', '顶层键序')

  const err = (text, label) => {
    try { parseRoutesYaml(text); ok(false, label + '（未抛错）') }
    catch (e) { ok(e instanceof RoutesParseError, label + '（RoutesParseError）') }
  }
  // 标量父键不压栈 → 更深子键按 gen.py 同款栈语义附着到外层容器（与 gen.py 行为一致，不报错）
  const lenient = parseRoutesYaml('roles:\n  developer: x\n    provider: y\n')
  ok(lenient.roles.developer === 'x' && lenient.roles.provider === 'y', '标量后的更深子键附着外层（gen.py 同款栈语义）')
  err('roles:\n   developer: x\n', '3 空格缩进 → 报错')
  err('a: "quoted"\n', '带引号值 → 报错')
  err('roles:\n  developer: x\n  developer: y\n', '键重复 → 报错')
  err('这是不认识的行\n', '非 key: 行 → 报错')
  err('a: 1\tb\n', '含 tab → 报错')
  // 行号信息
  try { parseRoutesYaml('a: 1\nb:\n  c: 2\n  d:\n    e: 3\n   f: 4\n') }
  catch (e) { ok(/:\d+/.test(e.message) && e.message.includes('缩进非法'), '错误消息带行号') }
}

/* ------------------------------------------------------------ B. effectiveRoute */

section('B effectiveRoute 查表链路')
{
  const root = parseRoutesYaml(`default:
  provider: dft
  model: m0
roles:
  alpha:
    provider: a
    model: ma
    tasks:
      proofread:
        provider: p
        model: mp
  beta:
    tasks:
      qa:
        provider: q
        model: mq
  gamma:
    provider: g
`)
  let w = []
  const r1 = effectiveRoute(root, 'alpha', 'proofread', w)
  ok(r1?.provider === 'p' && r1?.model === 'mp' && r1?.via === 'roles.alpha.tasks.proofread', 'task 级命中')
  const r2 = effectiveRoute(root, 'alpha', undefined, w)
  ok(r2?.provider === 'a' && r2?.via === 'roles.alpha', 'role 级命中')
  const r3 = effectiveRoute(root, 'beta', undefined, w)
  ok(r3?.provider === 'dft' && r3?.via === 'default', '无 role 条目落 default')
  const r4 = effectiveRoute(root, 'nope', undefined, w)
  ok(r4?.provider === 'dft' && r4?.via === 'default', '未知角色落 default')
  w = []
  const r5 = effectiveRoute(root, 'gamma', undefined, w)
  ok(r5?.provider === 'dft' && w.some(x => x.includes('缺 provider/model')), 'gamma 缺 model → 告警 + 落 default')
  w = []
  const r6 = effectiveRoute(root, 'beta', 'analyst', w)
  ok(r6?.provider === 'dft' && r6?.via === 'default', 'task 缺条目落 default')
}

/* ------------------------------------------------------------ D. 视图读声明表（性质断言） */

const FIXTURE_TABLE = [
  '# 夹具表（t260914-05：真源=声明 paths.model_routes 指向的文件）',
  'default:',
  '  provider: fx-dft',
  '  model: fx-m0',
  'roles:',
  '  integration:',
  '    provider: fx-int',
  '    model: fx-mi',
  '  developer:',
  '    provider: fx-dev',
  '    model: fx-md',
  '  product-operation:',
  '    provider: fx-po',
  '    model: fx-mp',
  '    tasks:',
  '      proofread:',
  '        provider: fx-pr',
  '        model: fx-mpr',
  '      qa:',
  '        provider: fx-qa',
  '        model: fx-mqa',
  '      analyst:',
  '        provider: fx-an',
  '        model: fx-man',
  '',
].join('\n')

async function fixtureRegistry(tmp, entries) {
  const reg = join(tmp, 'reg')
  for (const [key, body] of Object.entries(entries)) {
    await mkdir(join(reg, key), { recursive: true })
    await writeFile(join(reg, key, 'project.yaml'), body, 'utf8')
  }
  return reg
}

const entryYaml = (key, repoDir, declaredPath) => `schema: v1\n`
  + (declaredPath ? `paths:\n  model_routes: ${declaredPath}\n` : '')
  + `project:\n  - key: ${key}\n    name: ${key.toUpperCase()}\n    dirs:\n      - ${repoDir}\n`

section('D buildRoutesView 读「声明指向的表」（夹具自足，性质断言不钉生产值）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syadm-routes-view-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(repo, { recursive: true })
    const tablePath = join(tmp, 'declared', 'routes.yaml')
    await mkdir(dirname(tablePath), { recursive: true })
    await writeFile(tablePath, FIXTURE_TABLE, 'utf8')
    const reg = await fixtureRegistry(tmp, { fxdemo: entryYaml('fxdemo', repo, tablePath) })

    const view = await buildRoutesView(repo, { projectsDir: reg, projectKey: 'fxdemo' })
    ok(view.error === undefined, '视图组装无 error')
    ok(view.state === 'ok' && view.declared === tablePath && view.routes_file === tablePath,
      'state=ok 且读写同源（路径=声明文件）')
    ok(view.default?.provider === 'fx-dft' && view.default?.via === 'default', 'default 条目来自声明表')
    ok(view.roles.length === 3, '三角色齐全')
    ok(view.roles.map(r => r.role).join(',') === 'integration,developer,product-operation',
      '角色顺序 = ROLES 常量顺序')
    const dev = view.roles.find(r => r.role === 'developer')
    ok(dev?.effective?.provider === 'fx-dev' && dev?.effective?.via === 'roles.developer', 'developer 落角色条目')
    const integ = view.roles.find(r => r.role === 'integration')
    ok(integ?.effective?.provider === 'fx-int' && integ?.effective?.via === 'roles.integration', 'integration 落角色条目')
    const po = view.roles.find(r => r.role === 'product-operation')
    ok(po?.tasks.length === 3 && po?.tasks.map(t => t.kind).join(',') === 'proofread,qa,analyst',
      'product-operation 分工序 = KINDS 常量序')
    const proofread = po?.tasks.find(t => t.kind === 'proofread')
    ok(proofread?.effective?.provider === 'fx-pr'
      && proofread?.effective?.via === 'roles.product-operation.tasks.proofread', '审校分工查 task 级')
    ok(proofread?.readonly === true, '审校分工只读')
    ok(PROVIDER_FAMILY['kimi-coding'] === '生成家' && PROVIDER_FAMILY.zai === '审校家', '家映射常量')
    ok(KINDS.proofread.display === '审校' && ROLES.developer.display === '开发', '显示名常量')

    // 声明文件缺失 → file_missing 点名 + 引导态（不回落任何仓内表，t260914-05）
    await rm(tablePath)
    const v2 = await buildRoutesView(repo, { projectsDir: reg, projectKey: 'fxdemo' })
    ok(v2.state === 'file_missing' && v2.uninitialized === true && v2.default === null,
      '声明文件缺失 → file_missing 引导态（无表）')
    ok(String(v2.resolution_error).includes('文件缺失') && String(v2.resolution_error).includes(tablePath),
      'file_missing 点名声明路径')
    ok(!String(v2.resolution_error).includes('兜底'), '无「兜底」语义残留')
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

/* ------------------------------------------------------------ E. 路由 */

section('E /sandbar-admin/api/routes 路由（mock webServer + per-key 注册表）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syadm-routes-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server'), { recursive: true })
    // 反毒夹具：仓内形状的表在场，但项目未声明——证明「在场也不被读」（t260914-05 毒面反证）
    await writeFile(join(repo, 'server', 'model-routes.yaml'),
      'default:\n  provider: stale-zai\n  model: stale-m\nroles: {}\n', 'utf8')

    const tablePath = join(tmp, 'declared', 'routes.yaml')
    await mkdir(dirname(tablePath), { recursive: true })
    await writeFile(tablePath, FIXTURE_TABLE, 'utf8')
    const reg = await fixtureRegistry(tmp, {
      demo: entryYaml('demo', repo, tablePath),
      stale: entryYaml('stale', repo, null),
    })
    process.env.SANDBAR_PROJECTS_DIR = reg

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const route = routes.find(x => x.kind === 'exact' && x.path === '/sandbar-admin/api/routes')
    ok(route !== undefined, 'routes exact 路由已挂')

    const res = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    const callGet = async (key) => {
      const r = { status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } }
      await route.handler({ url: '/sandbar-admin/api/routes?project=' + key, method: 'GET' }, r)
      return r
    }

    // 声明命中（ok）：读声明表并透传
    const r1 = await callGet('demo')
    ok(r1.status === 200 && r1.body.ok === true, 'GET 200（声明命中）')
    ok(r1.body.result.state === 'ok' && r1.body.result.routes_file === tablePath,
      '读写同源：routes_file=声明文件')
    ok(r1.body.result.default.provider === 'fx-dft', 'default 透传（来自声明表）')
    ok(r1.body.result.roles.length === 3, '路由表 3 角色')

    // 未声明（反毒）：decl_missing 引导态，仓内形状的表在场也不被读
    const r2 = await callGet('stale')
    ok(r2.status === 200 && r2.body.ok === true, 'GET 200（未声明=引导态不红）')
    ok(r2.body.result.state === 'decl_missing' && r2.body.result.declared === null,
      'decl_missing 分态可辨')
    ok(r2.body.result.uninitialized === true && r2.body.result.default === null,
      '无表引导态（不渲染旧表）')
    ok(r2.body.result.routes_file === '', 'routes_file 空（不再指仓内表）')
    const err2 = String(r2.body.result.resolution_error ?? '')
    ok(err2.includes('未声明') && err2.includes('docs/model-routes-sample.yaml'),
      'resolution_error 点名+建表指引')
    ok(!err2.includes('兜底'), '无「兜底」语义残留')
    ok(!JSON.stringify(r2.body.result).includes('stale-zai'), '仓内表内容未被透出（在场也不被读）')

    // t260910-14 退役断言：routes/init 引导动作已随 init 退役删除（宿主拍板：
    // 新项目按 docs 样例人工填表），路由不再注册。
    ok(routes.find(x => x.path === '/sandbar-admin/api/routes/init') === undefined,
      'routes/init 路由已退役（不再注册）')
  } finally {
    delete process.env.SANDBAR_PROJECTS_DIR
    await rm(tmp, { recursive: true, force: true })
  }
}

/* ------------------------------------------------------------ F. validateRouteTable（M13） */

section('F validateRouteTable 保存载荷 schema')
{
  const good = {
    default: { provider: 'kimi-coding', model: 'k3' },
    roles: {
      integration: { provider: 'zai', model: 'glm-5.2' },
      developer: { provider: 'kimi-coding', model: 'k3' },
      'product-operation': {
        provider: 'kimi-coding', model: 'k3',
        tasks: { proofread: { provider: 'zai', model: 'glm-5.2' }, qa: { provider: 'zai', model: 'glm-5.2' } },
      },
    },
  }
  ok(validateRouteTable(good).ok === true, '合法载荷通过')
  ok(validateRouteTable({ default: { provider: 'kimi-coding' } }).ok === true, '只带 provider 也合法（部分更新）')
  ok(validateRouteTable({}).ok === true, '空载荷合法（无变更）')

  const bad = (t, label) => {
    const r = validateRouteTable(t)
    ok(r.ok === false && (r.error ?? '').length > 0, `${label} 被拒（${r.error?.slice(0, 40)}…）`)
  }
  bad({ roles: { hacker: { model: 'x' } } }, '未登记角色')
  bad({ roles: { developer: { tasks: { deepscan: { model: 'x' } } } } }, '未登记分工 kind')
  bad({ roles: { developer: { foo: 'x' } } }, '角色条目未知键')
  bad({ default: { provider: 'has space' } }, '值含空格')
  bad({ default: { provider: '"quoted"' } }, '值带引号')
  bad({ default: { provider: 42 } }, '值非字符串')
  bad({ top: {} }, '未知顶层键')
  bad({ default: 'x' }, '条目非对象')
  ok(validateRouteTable([]).ok === false, '数组拒绝')
}

/* ------------------------------------------------------------ G. applyRouteEdits（M13） */

section('G applyRouteEdits 外科补丁（保留注释/键序/表头）')
{
  const yaml = `# ═ 表头注释（必须原样保留）
default:
  provider: kimi-coding
  model: k3
roles:
  developer:         # 行尾注释-角色
    provider: kimi-coding
    model: k3        # 行尾注释-模型
  integration:
    provider: zai
    model: glm-5.2
  artist:
    provider: kimi-coding
`
  // 改值：行尾注释保留
  let r = applyRouteEdits(yaml, { roles: { developer: { model: 'k3-256k' } } })
  ok(r.changed.join(',') === 'roles/developer/model', '只改目标键')
  const patched = r.text.split('\n')
  ok(patched.some(l => l.includes('model: k3-256k') && l.includes('# 行尾注释-模型')), '改值保留行尾注释')
  ok(patched[0] === '# ═ 表头注释（必须原样保留）', '表头原样保留')
  ok(parseRoutesYaml(r.text).roles.developer.model === 'k3-256k', '改后重新解析生效')

  // 空值 → 删键（查表向上落兜底）
  r = applyRouteEdits(yaml, { roles: { developer: { model: '' } } })
  ok(r.changed.join(',') === 'roles/developer/model', '空值=删键')
  ok(!r.text.includes('k3        # 行尾注释-模型'), 'model 行已删除')
  ok(parseRoutesYaml(r.text).roles.developer.model === undefined, '删后解析无 model')

  // 缺键 → 按父键缩进插入（product-operation 无 model 行的 fixture 场景改用 developer 已测，跳过）

  // 无变更 → changed 空
  r = applyRouteEdits(yaml, { roles: { developer: { model: 'k3' } } })
  ok(r.changed.length === 0, '值与现状一致 → 无变更')

  // 多键同改（default + role + task；含 tasks 的 yaml）
  const yaml2 = `default:
  provider: kimi-coding
  model: k3
roles:
  developer:
    provider: kimi-coding
    model: k3
  product-operation:
    provider: kimi-coding
    model: k3
    tasks:
      proofread:
        provider: zai
        model: glm-5.2
`
  r = applyRouteEdits(yaml2, {
    default: { model: 'k3-256k' },
    roles: { developer: { provider: 'zai' }, 'product-operation': { tasks: { proofread: { provider: 'scnet' } } } },
  })
  ok(r.changed.length === 3 && r.changed.includes('default/model')
    && r.changed.includes('roles/developer/provider')
    && r.changed.includes('roles/product-operation/tasks/proofread/provider'), '多键 diff 全命中')

  // 空载荷 → 无变更
  r = applyRouteEdits(yaml2, {})
  ok(r.changed.length === 0, '空载荷无变更')

  // 非法：父键是标量 → 插入报错
  try {
    applyRouteEdits('roles:\n  developer: kimi-coding\n', { roles: { developer: { model: 'k3' } } })
    ok(false, '标量父键插入未报错')
  } catch (e) { ok(e instanceof RoutesParseError, '标量父键插入 → RoutesParseError') }

  // 非法载荷 → 抛 RoutesParseError
  try {
    applyRouteEdits(yaml, { roles: { hacker: { model: 'x' } } })
    ok(false, '非法载荷未抛')
  } catch (e) { ok(e instanceof RoutesParseError && (e.message ?? '').includes('保存载荷非法'), '非法载荷 → RoutesParseError') }
}

/* ------------------------------------------------------------ H. 保存端点（M13） */

section('H POST /sandbar-admin/api/routes/save（mock webServer + 临时 repo）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syadm-routes-save-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server'), { recursive: true })
    const routesFile = join(repo, 'server', 'model-routes.yaml')
    // t260914-05：自写夹具表（不再拷贝仓内表当夹具——真源=声明指向文件，夹具自足）
    await writeFile(routesFile, FIXTURE_TABLE, 'utf8')

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const route = routes.find(x => x.kind === 'exact' && x.path === '/sandbar-admin/api/routes/save')
    ok(route !== undefined, 'save exact 路由已挂')

    // 注册表夹具（t260910-14 同源化）：per-key 注册表 + 声明 paths.model_routes 指向
    // 临时表——保存落点=声明指向文件（真源）；nodecl 条目不声明（拒写子用例用）。
    const reg = await fixtureRegistry(tmp, {
      demo: entryYaml('demo', repo, routesFile),
      nodecl: entryYaml('nodecl', join(tmp, 'repo2'), null),
    })
    process.env.SANDBAR_PROJECTS_DIR = reg

    const res = () => ({ status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } })
    const call = async (body, key = 'demo') => {
      const r = res()
      const req = {
        url: '/sandbar-admin/api/routes/save?project=' + key,
        method: 'POST',
        [Symbol.asyncIterator]: async function* () { yield Buffer.from(JSON.stringify(body ?? {}), 'utf8') },
      }
      await route.handler(req, r)
      return r
    }

    // 成功保存：改 developer.model + integration 不变
    const r1 = await call({ table: {
      default: { provider: 'kimi-coding', model: 'k3' },
      roles: {
        integration: { provider: 'zai', model: 'glm-5.2' },
        developer: { provider: 'kimi-coding', model: 'k3-256k' },
        'product-operation': {
          provider: 'kimi-coding', model: 'k3',
          tasks: { proofread: { provider: 'zai', model: 'glm-5.2' }, qa: { provider: 'zai', model: 'glm-5.2' }, analyst: { provider: 'zai', model: 'glm-5.2' } },
        },
      },
    } })
    ok(r1.status === 200 && r1.body.ok === true, '保存 200 ok')
    ok(r1.body.result.written === true, 'written=true')
    ok(r1.body.result.changed.includes('roles/developer/model'),
      `changed 含 developer.model（${r1.body.result.changed.join(',')}）`)
    ok(typeof r1.body.result.backup === 'string' && r1.body.result.backup.includes('suyou-model-routes-'), '备份落 /tmp/suyou-model-routes-*')
    ok((r1.body.result.regenerate ?? '').includes('生效'), '响应带生效话术（运行时查表）')
    const savedText = await readFile(routesFile, 'utf8')
    ok(savedText.includes('k3-256k') && savedText.includes('  developer:') && savedText.includes('roles:'), '文件已写 + 结构保留')
    const view = await buildRoutesView(repo, { projectKey: 'demo' })
    ok(view.roles.find(rr => rr.role === 'developer')?.effective?.model === 'k3-256k', '保存后查表生效')

    // 无变更 → written=false 不写
    const r2 = await call({ table: {
      default: { provider: 'kimi-coding', model: 'k3' },
      roles: { developer: { provider: 'kimi-coding', model: 'k3-256k' } },
    } })
    ok(r2.body.ok === true && r2.body.result.written === false, '无变更不写文件')

    // 非法载荷 → 200 ok:false（不抛）
    const r3 = await call({ table: { roles: { hacker: { model: 'x' } } } })
    ok(r3.body.ok === false && (r3.body.error ?? '').includes('不可编辑'), '非法载荷 → 200 ok:false')

    // 缺 table → 400
    const r4 = await call({})
    ok(r4.status === 400, '缺 table → 400')

    // t260914-05：未声明项目保存 → 200 ok:false 显式拒写+建表指引（不代写仓内文件）
    const r5 = await call({ table: { default: { provider: 'x', model: 'y' } } }, 'nodecl')
    ok(r5.status === 200 && r5.body.ok === false,
      '未声明保存 → 200 ok:false（显式拒写，无 result 键）')
    ok(String(r5.body.error).includes('无落点可写')
      && String(r5.body.error).includes('docs/model-routes-sample.yaml'),
      '拒写文案点名原因+建表指引')
  } finally {
    delete process.env.SANDBAR_PROJECTS_DIR
    await rm(tmp, { recursive: true, force: true })
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
