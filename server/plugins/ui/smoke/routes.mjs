/**
 * smoke/routes.mjs —— sandbar-admin-ui M12「模型路由」的宿主半冒烟。
 *
 * 直跑：node smoke/routes.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. parseRoutesYaml（src/host/routes.ts）：最小 YAML 子集解析（default/roles/tasks
 *      结构）；非法行/缩进/键重复/带引号值 → RoutesParseError 带行号（不静默丢）。
 *   B. effectiveRoute：查表链路 tasks.<kind> → roles.<role> → default；条目缺
 *      provider/model → 告警并向上落；全落空 → null。
 *   D. buildRoutesView 对真源（model-routes.yaml + suyou-integration preset）钉当前值：
 *      默认 kimi-coding/k3、integration=zai/glm-5.2、product-operation 分工=zai/glm-5.2、
 *      8 个 dispatch 实例（5 默认 + 3 分工）、只读口径——防 gen.py/路由表漂移。
 *   E. /suyou-admin/api/routes 路由（node.ts apply + mock webServer/req/res）：
 *      临时 repo 布局 → 200 路由表+实例；路由表缺失 → 200 ok+uninitialized 引导态
 *      （t260906-01）；POST /routes/init 从引擎默认表生成（已存在拒收、建父目录）。
 */

import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
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

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = join(HERE, '..', '..', '..', '..') // server/plugins/ui/smoke -> 仓库根

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

/* ------------------------------------------------------------ D. 真源钉值 */

section('D buildRoutesView 对真源钉当前值（防路由表漂移）')
{
  const view = await buildRoutesView(REPO)
  ok(view.error === undefined, '真源视图组装无 error')
  ok(view.default?.provider === 'zai' && view.default?.model === 'glm-5.3-flash' && view.default?.via === 'default',
    'default = zai/glm-5.3-flash（260902 配额急救修正后的表值）')
  ok(view.roles.length === 3, '三角色齐全')
  ok(view.roles.map(r => r.role).join(',') === 'integration,developer,product-operation',
    '角色顺序 = ROLES 常量顺序')
  const dev = view.roles.find(r => r.role === 'developer')
  ok(dev?.effective?.provider === 'zai' && dev?.effective?.via === 'roles.developer', 'developer 落角色条目 zai')
  const integ = view.roles.find(r => r.role === 'integration')
  ok(integ?.effective?.provider === 'zai-coding-cn' && integ?.effective?.via === 'roles.integration', 'integration = zai-coding-cn（第二账号）')
  const po = view.roles.find(r => r.role === 'product-operation')
  ok(po?.tasks.length === 3, 'product-operation 三个分工')
  ok(po?.tasks.map(t => t.kind).join(',') === 'proofread,qa,analyst', '分工序 = KINDS 常量序')
  const proofread = po?.tasks.find(t => t.kind === 'proofread')
  ok(proofread?.effective?.provider === 'zai' && proofread?.effective?.model === 'glm-5.2'
    && proofread?.effective?.via === 'roles.product-operation.tasks.proofread', '审校分工 = zai/glm-5.2')
  ok(proofread?.readonly === true, '审校分工只读')
  ok(PROVIDER_FAMILY['kimi-coding'] === '生成家' && PROVIDER_FAMILY.zai === '审校家', '家映射常量')
  ok(KINDS.proofread.display === '审校' && ROLES.developer.display === '开发', '显示名常量')
}

/* ------------------------------------------------------------ E. 路由 */

section('E /suyou-admin/api/routes 路由（mock webServer）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syadm-routes-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server'), { recursive: true })
    await copyFile(join(REPO, 'server', 'model-routes.yaml'), join(repo, 'server', 'model-routes.yaml'))

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const route = routes.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes')
    ok(route !== undefined, 'routes exact 路由已挂')

    // 注册表夹具（SUYOU_PROJECTS_YAML legacy 单文件模式，loadRegistry 每次现读 env）：
    // projOf 需要已注册项目；三个 key 各指一个主目录（有表 / 无表 / 深层无父目录）。
    // 先 import 后设 env 依赖此口径。
    const fixtureReg = join(tmp, 'projects.yaml')
    await writeFile(fixtureReg,
      `projects:\n  - key: demo\n    name: Demo\n    dirs:\n      - ${repo}`
      + `\n  - key: empty\n    name: Empty\n    dirs:\n      - ${join(tmp, 'repo-empty')}`
      + `\n  - key: deep\n    name: Deep\n    dirs:\n      - ${join(tmp, 'repo-empty2')}\n`, 'utf8')
    process.env.SUYOU_PROJECTS_YAML = fixtureReg

    const res = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    await route.handler({ url: '/suyou-admin/api/routes?project=demo', method: 'GET' }, res)
    ok(res.status === 200 && res.body.ok === true, 'GET 200')
    ok(res.body.result.roles.length === 3, '路由表 3 角色')
    ok(res.body.result.default.provider === 'zai', 'default 透传')

    // 路由表缺失 → 200 ok + uninitialized 引导态（不抛错不红）
    const routes2 = []
    const ws2 = { register: (r) => { routes2.push(r); return () => {} } }
    const ctx2 = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws2 : undefined),
      on: () => () => {},
    }
    await mkdir(join(tmp, 'repo-empty', 'server'), { recursive: true })
    apply(ctx2, { repo: join(tmp, 'repo-empty') })
    const route2 = routes2.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes')
    const res2 = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    await route2.handler({ url: '/suyou-admin/api/routes?project=empty', method: 'GET' }, res2)
    // t260906-01：表缺失=未初始化引导态（非错误）——uninitialized:true + 模板来源
    ok(res2.status === 200 && res2.body.ok === true
      && res2.body.result.uninitialized === true
      && typeof res2.body.result.template_source === 'string'
      && res2.body.result.template_source.includes('model-routes.yaml'),
      '路由表缺失 → 200 ok + uninitialized 引导态（不抛错不红）')

    // t260906-01 init 端点：无表 → 从引擎默认表生成；已有表 → 拒收（零覆盖）
    const initRoute = routes2.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes/init')
    ok(initRoute !== undefined, 'routes/init exact 路由已挂')
    const res3 = { status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } }
    await initRoute.handler({ url: '/suyou-admin/api/routes/init?project=empty', method: 'POST' }, res3)
    ok(res3.status === 200 && res3.body.ok === true && res3.body.result.routes_file.includes('model-routes.yaml'),
      'init POST（无表）→ 200 ok，默认表已生成')
    const initedText = await readFile(join(tmp, 'repo-empty', 'server', 'model-routes.yaml'), 'utf8')
    const engineText = await readFile(join(REPO, 'server', 'model-routes.yaml'), 'utf8')
    ok(initedText === engineText, '生成的表=引擎仓真源逐字节一致（同源模板）')
    const res4 = { status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } }
    await initRoute.handler({ url: '/suyou-admin/api/routes/init?project=empty', method: 'POST' }, res4)
    ok(res4.status === 200 && res4.body.ok === false && (res4.body.error ?? '').includes('已存在'),
      'init 对已存在表 → 200 ok:false（零覆盖拒收）')
    // 深层父目录：init 建父目录（repo-empty2 完全无 server 层级）
    const res5 = { status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } }
    const req5 = { url: '/suyou-admin/api/routes/init?project=deep', method: 'POST', [Symbol.asyncIterator]: async function* () { yield Buffer.from('{}', 'utf8') } }
    apply(ctx2, { repo: join(tmp, 'repo-empty2') })
    const initRoute2 = routes2.filter(x => x.path === '/suyou-admin/api/routes/init').pop()
    await initRoute2.handler(req5, res5)
    ok(res5.status === 200 && res5.body.ok === true
      && (await readFile(join(tmp, 'repo-empty2', 'server', 'model-routes.yaml'), 'utf8')) === engineText,
      'init 对深层缺失父目录 → mkdir 递归后生成')
    const res6 = { status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } }
    await initRoute2.handler({ url: '/suyou-admin/api/routes/init?project=deep', method: 'GET' }, res6)
    ok(res6.status === 405, 'init GET → 405')
  } finally {
    delete process.env.SUYOU_PROJECTS_YAML
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

section('H POST /suyou-admin/api/routes/save（mock webServer + 临时 repo）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'syadm-routes-save-'))
  try {
    const repo = join(tmp, 'repo')
    await mkdir(join(repo, 'server'), { recursive: true })
    await copyFile(join(REPO, 'server', 'model-routes.yaml'), join(repo, 'server', 'model-routes.yaml'))
    const routesFile = join(repo, 'server', 'model-routes.yaml')

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const route = routes.find(x => x.kind === 'exact' && x.path === '/suyou-admin/api/routes/save')
    ok(route !== undefined, 'save exact 路由已挂')

    // 注册表夹具（同 E 段口径）：projOf 需要已注册项目，主目录=临时 repo。
    const fixtureReg = join(tmp, 'projects.yaml')
    await writeFile(fixtureReg, `projects:\n  - key: demo\n    name: Demo\n    dirs:\n      - ${repo}\n`, 'utf8')
    process.env.SUYOU_PROJECTS_YAML = fixtureReg

    const res = () => ({ status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } })
    const call = async (body) => {
      const r = res()
      const req = {
        url: '/suyou-admin/api/routes/save?project=demo',
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
    const view = await buildRoutesView(repo)
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
  } finally {
    delete process.env.SUYOU_PROJECTS_YAML

    await rm(tmp, { recursive: true, force: true })
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
