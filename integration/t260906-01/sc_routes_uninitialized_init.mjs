// sc_routes_uninitialized_init.mjs — t260906-01 场景③：路由无表引导态 + init 退役终态。
//
// intent（t260914-05 兜底腿退役后的重写版；t260910-14 已退役 init 动作）：
//   A. 无声明项目 → 无表引导态：视图/API state=decl_missing、uninitialized=true、
//      default=null、routes_file=""（无落点），resolution_error 点名「未声明」+建表
//      模板指引；**反毒断言**：仓内 server/model-routes.yaml 即使仍在位也不被读、
//      内容不被透出（「表在场但过期被静默用错」= 本票要杀的毒面）。
//   B. init 端点退场：POST /sandbar-admin/api/routes/init 不再挂载（零写动作=零覆盖面）。
//   C. 已有项目自有表但未声明 → 自有表不被读也不被改（state=decl_missing、无表、
//      文件字节不变——「已有表拒收零覆盖」意图在 init 退役后由「零写动作」天然承担）。
//   D. 声明指向畸形表 → 编辑视图诚实暴露解析失败并给 state=bad_content + 内容指纹
//      （t260914-05 补齐与引擎 resolve_routes_table 的 parity；读侧运行时行为归引擎面
//      t260903-03/t260910-14-S1 钉，本条锁编辑面）。
// 台别：API 面（mock webServer 手法同 server/plugins/ui/smoke/routes.mjs，无浏览器，
// 进程内 apply 不起监听、零 3099 接触）；wire 口径=project 走 ?project= 查询参。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { tmpRoot, makeChecks, writeProjectEntry } from '../t260904-14/lib_fix14.mjs';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const REPO_ROOT = path.resolve(HERE, '..', '..');
const c = makeChecks('t260906-01 路由无表引导态+init 退役终态（t260914-05 兜底退役版）');
delete process.env.SANDBAR_PROJECTS_YAML;

const ENGINE_TABLE = path.join(REPO_ROOT, 'server', 'model-routes.yaml');
const { buildRoutesView } = await import(
  pathToFileURL(path.join(REPO_ROOT, 'server', 'plugins', 'ui', 'src', 'host', 'routes.ts')).href);
const { apply } = await import(
  pathToFileURL(path.join(REPO_ROOT, 'server', 'plugins', 'ui', 'node.ts')).href);

const mktempRepo = async (prefix) => await mkdtemp(path.join(tmpdir(), prefix));

// 项目解析缝：?project= 是注册表 key（findProject，非裸路径）——fixture：隔离注册表根 + 条目。
const regRoot = tmpRoot('t260906-reg-');
mkdirSync(regRoot, { recursive: true });
writeFileSync(path.join(regRoot, '.migrated'), 'source: fixture\n');
process.env.SANDBAR_PROJECTS_DIR = regRoot;

/** 手写条目（带可选 paths 节——真源=声明指向文件的声明面桩）。 */
function writeEntry(key, dirs, pathsLines) {
  const d = path.join(regRoot, key);
  mkdirSync(d, { recursive: true });
  const lines = ['schema: v1', 'project:', `  - key: ${key}`, `    name: ${key}`, '    dirs:',
    ...dirs.map((x) => `      - ${x}`)];
  if (pathsLines) lines.push('paths:', ...pathsLines.map(([k, v]) => `  ${k}: ${v}`));
  writeFileSync(path.join(d, 'project.yaml'), lines.join('\n') + '\n');
}

/** mock webServer 手法（ui smoke E 段同款）：捕获 register 的路由表，进程内调 handler。 */
function mountRoutes(repo) {
  const routes = [];
  const ws = { register: (r) => { routes.push(r); return () => {} } };
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  return (p) => routes.find((x) => x.kind === 'exact' && x.path === p)
}

async function call(handler, url, method = 'GET') {
  const res = {
    status: 0, body: null,
    writeHead(s) { this.status = s },
    end(b) { this.body = b ? JSON.parse(b) : null },
  }
  await handler({ url, method }, res)
  return res
}

const projUrl = (key) => '/sandbar-admin/api/routes?project=' + encodeURIComponent(key)
const initUrl = (key) => '/sandbar-admin/api/routes/init?project=' + encodeURIComponent(key)

// ---- A：无声明=无表引导态 + 反毒（仓内表在场也不被读；视图半 + API 半双面）----
const emptyRepo = await mktempRepo('t260906-noroutes-')
writeProjectEntry(regRoot, 'rtk', 'RT', [emptyRepo]) // 已注册项目、未声明 paths.model_routes
{
  c.check('前提：仓内表仍在位（(b) 降级口径；下两条证它在场也不被读）',
    existsSync(ENGINE_TABLE), ENGINE_TABLE)
  const v = await buildRoutesView(emptyRepo, { projectsDir: regRoot, projectKey: 'rtk' })
  c.check('无声明视图：state=decl_missing + uninitialized 引导态 + default=null',
    v.state === 'decl_missing' && v.declared == null && v.uninitialized === true
      && v.default === null,
    JSON.stringify({ s: v.state, d: v.declared, u: v.uninitialized, dft: v.default }))
  c.check('routes_file=""（无落点，不再指任何仓内表）',
    v.routes_file === '' && v.template_source === undefined,
    JSON.stringify({ rf: v.routes_file, ts: v.template_source }))
  const err = String(v.resolution_error ?? '')
  c.check('resolution_error 点名未声明+建表模板指引（禁静默）',
    err.includes('未声明') && err.includes('docs/model-routes-sample.yaml') && !err.includes('兜底'),
    err.slice(0, 200))

  const find = mountRoutes(emptyRepo)
  const r = await call(find('/sandbar-admin/api/routes').handler, projUrl('rtk'))
  c.check('API 无声明=200 ok:true + state=decl_missing 透传 + 引导态（无表内容）',
    r.status === 200 && r.body.ok === true && r.body.result?.state === 'decl_missing'
      && r.body.result?.default === null && r.body.result?.uninitialized === true,
    JSON.stringify(r.body).slice(0, 260))
  c.check('API 反毒：仓内表路径与内容均不透出',
    !JSON.stringify(r.body).includes('server/model-routes.yaml')
      && !JSON.stringify(r.body).includes('glm'),
    JSON.stringify(r.body).slice(0, 260))
}

// ---- B：init 端点退役（动作退场=零写动作）----
{
  const find = mountRoutes(emptyRepo)
  c.check('init 端点退场（POST /sandbar-admin/api/routes/init 不再挂载）',
    find('/sandbar-admin/api/routes/init') === undefined)
}

// ---- C：已有项目自有表但未声明 → 不被读也不被改（零写动作天然承担零覆盖）----
{
  const repo2 = await mktempRepo('t260906-hastable-')
  mkdirSync(path.join(repo2, 'server'), { recursive: true })
  writeProjectEntry(regRoot, 'hask', 'Hask', [repo2])
  const p = path.join(repo2, 'server', 'model-routes.yaml')
  const own = '# my own table\ndefault:\n  provider: mine\n  model: m1\n'
  writeFileSync(p, own)

  const v = await buildRoutesView(repo2, { projectsDir: regRoot, projectKey: 'hask' })
  c.check('未声明的自有表不被读（无表引导态，default=null）',
    v.state === 'decl_missing' && v.default === null && v.routes_file === '',
    JSON.stringify({ s: v.state, d: v.default, rf: v.routes_file }))
  c.check('自有表字节零变更（init 退役=零写动作）', readFileSync(p, 'utf8') === own, 'table touched')
}

// ---- D：声明指向畸形表 → 解析失败点名 + state=bad_content + 内容指纹（parity 补齐）----
{
  const repo3 = await mktempRepo('t260906-badtable-')
  writeEntry('badk', [repo3], [['model_routes', 'bad-table.yaml']])
  writeFileSync(path.join(repo3, 'bad-table.yaml'), 'default:\n  - broken\nroles: [\n')
  const vBad = await buildRoutesView(repo3, { projectsDir: regRoot, projectKey: 'badk' })
  c.check('声明畸形表=视图解析失败点名（无 uninitialized 引导态）',
    typeof vBad.error === 'string' && vBad.error.includes('解析失败')
      && vBad.uninitialized === undefined,
    JSON.stringify({ e: vBad.error, u: vBad.uninitialized, s: vBad.state }))
  c.check('state=bad_content 分态可辨 + 内容指纹进人话串（sha256:12hex）',
    vBad.state === 'bad_content'
      && /指纹=sha256:[0-9a-f]{12}/.test(String(vBad.error))
      && /指纹=sha256:[0-9a-f]{12}/.test(String(vBad.resolution_error)),
    JSON.stringify({ s: vBad.state, e: vBad.error, re: vBad.resolution_error }))
}

// ---- D2：声明指向「可解析但非映射」表（标量/列表）→ 同 bad_content（260915 P5：py/TS 同判）----
// py 侧此形曾判 ok 而消费方 AttributeError（t260914-05 走查 P5，已收紧）；UI 半行式解析器
// 一直拒收此形。本腿把 UI 判定钉住，与引擎 UT（test_non_mapping_table_is_bad_content）互为两岸。
{
  const repo4 = await mktempRepo('t260906-nonmap-')
  writeEntry('nonmapk', [repo4], [['model_routes', 'scalar-table.yaml']])
  writeFileSync(path.join(repo4, 'scalar-table.yaml'), 'just-a-scalar\n')
  const v1 = await buildRoutesView(repo4, { projectsDir: regRoot, projectKey: 'nonmapk' })
  c.check('标量表=bad_content + 指纹（与引擎同判，非 ok 放行）',
    v1.state === 'bad_content' && /指纹=sha256:[0-9a-f]{12}/.test(String(v1.error)),
    JSON.stringify({ s: v1.state, e: v1.error }))
  writeFileSync(path.join(repo4, 'scalar-table.yaml'), '- a\n- b\n')
  const v2 = await buildRoutesView(repo4, { projectsDir: regRoot, projectKey: 'nonmapk' })
  c.check('列表形表=同判 bad_content（指纹随字节变）',
    v2.state === 'bad_content' && v2.error !== v1.error,
    JSON.stringify({ s: v2.state, e: v2.error }))
}

// ---- D3：形状坏表（roles/条目/tasks 值非映射）→ 与引擎同判 bad_content（260915 gen2）----
// 引擎侧此形曾 state=ok 而消费方 AttributeError（260915 独立探针，已收口）；UI 半 asMap
// 曾静默吞非映射值→视图对坏表出「默认路由」假象。本腿钉住 TS 判定（引擎 UT
// test_shape_broken_table_is_bad_content 互为两岸）。
{
  const repo5 = await mktempRepo('t260906-shapebad-')
  writeEntry('shapebadk', [repo5], [['model_routes', 'shape-bad.yaml']])
  writeFileSync(path.join(repo5, 'shape-bad.yaml'), 'roles: just-a-string\n')
  const v3 = await buildRoutesView(repo5, { projectsDir: regRoot, projectKey: 'shapebadk' })
  c.check('roles 段非映射=bad_content + 指纹（引擎/TS 同判，不静默出默认路由）',
    v3.state === 'bad_content' && v3.default == null
      && /指纹=sha256:[0-9a-f]{12}/.test(String(v3.error)),
    JSON.stringify({ s: v3.state, e: v3.error }))
  writeFileSync(path.join(repo5, 'shape-bad.yaml'), 'roles:\n  developer:\n    tasks: not-a-map\n')
  const v4 = await buildRoutesView(repo5, { projectsDir: regRoot, projectKey: 'shapebadk' })
  c.check('tasks 值非映射=同判 bad_content（点名 roles.developer.tasks）',
    v4.state === 'bad_content' && String(v4.error).includes('roles.developer.tasks'),
    JSON.stringify({ s: v4.state, e: v4.error }))
}

c.finish();
