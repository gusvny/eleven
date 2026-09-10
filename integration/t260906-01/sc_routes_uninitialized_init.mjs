// sc_routes_uninitialized_init.mjs — t260906-01 场景③：路由无表引导态 + init 退役终态。
//
// intent（t260910-14 退役收口后的重写版；原「一键初始化」动作随宿主拍板整体退役）：
//   A. 无声明项目 → 分层兜底（宿主风险令 260910）：视图/API 出**仓内兜底表**内容
//      （default 可解析）且分态可辨（state=decl_missing 留痕不洗白）、routes_file=兜底
//      仓内表路径（真源锚）、不再有「未初始化红错」旧态；template_source 字段退场
//      （init 动作退役，新项目按 docs 样例人工填表+落声明）。
//   B. init 端点退场：POST /sandbar-admin/api/routes/init 不再挂载（零写动作=零覆盖面）。
//   C. 已有项目自有表但未声明 → 自有表不被读也不被改（state=decl_missing、读兜底表、
//      文件字节不变——「已有表拒收零覆盖」意图在 init 退役后由「零写动作」天然承担）。
//   D. 声明指向畸形表 → 编辑视图诚实暴露解析失败（不静默换表展示；读侧运行时兜底
//      归引擎面 t260903-03/t260910-14-S1 钉，本条锁编辑面）。
// 台别：API 面（mock webServer 手法同 server/plugins/ui/smoke/routes.mjs，无浏览器，
// 进程内 apply 不起监听、零 3099 接触）；wire 口径=project 走 ?project= 查询参。
// 实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { tmpRoot, makeChecks, writeProjectEntry } from '../t260904-14/lib_fix14.mjs';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const REPO_ROOT = path.resolve(HERE, '..', '..');
const c = makeChecks('t260906-01 路由无表引导态+init 退役终态');
delete process.env.SANDBAR_PROJECTS_YAML;

const ENGINE_TABLE = path.join(REPO_ROOT, 'server', 'model-routes.yaml');
const { buildRoutesView, repoRoutesFallbackPath } = await import(
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
  const lines = ['schema: v1', 'project:', `  - key: ${key}`, `    name: ${key}`, '  dirs:'.replace('  dirs:', '    dirs:'),
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

// ---- A：无声明=分层兜底出仓内表 + 分态留痕（视图半 + API 半双面）----
const emptyRepo = await mktempRepo('t260906-noroutes-')
writeProjectEntry(regRoot, 'rtk', 'RT', [emptyRepo]) // 已注册项目、未声明 paths.model_routes
{
  c.check('前提：仓内兜底表在位（宿主令①零断供的本票前提）', existsSync(ENGINE_TABLE), ENGINE_TABLE)
  const v = await buildRoutesView(emptyRepo, { projectsDir: regRoot, projectKey: 'rtk' })
  c.check('无声明视图：state=decl_missing 留痕（不再 uninitialized 红错）',
    v.state === 'decl_missing' && v.declared == null && v.uninitialized === undefined,
    JSON.stringify({ s: v.state, d: v.declared, u: v.uninitialized }))
  c.check('视图出兜底表内容（default 可解析）', v.default !== null,
    JSON.stringify(v.default))
  c.check('routes_file=兜底仓内表（真源锚；template_source 退场）',
    v.routes_file === repoRoutesFallbackPath() && v.template_source === undefined,
    JSON.stringify({ rf: v.routes_file, ts: v.template_source }))

  const find = mountRoutes(emptyRepo)
  const r = await call(find('/sandbar-admin/api/routes').handler, projUrl('rtk'))
  c.check('API 无声明=200 ok:true + state=decl_missing 透传 + 兜底表出内容',
    r.status === 200 && r.body.ok === true && r.body.result?.state === 'decl_missing'
      && r.body.result?.default !== null && r.body.result?.uninitialized === undefined,
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
  c.check('未声明的自有表不被读（读兜底仓内表、state=decl_missing）',
    v.state === 'decl_missing' && v.default !== null
      && v.default.provider !== 'mine',
    JSON.stringify({ s: v.state, d: v.default }))
  c.check('自有表字节零变更（init 退役=零写动作）', readFileSync(p, 'utf8') === own, 'table touched')
}

// ---- D：声明指向畸形表 → 编辑视图诚实暴露解析失败（不静默换表展示）----
{
  const repo3 = await mktempRepo('t260906-badtable-')
  writeEntry('badk', [repo3], [['model_routes', 'bad-table.yaml']])
  writeFileSync(path.join(repo3, 'bad-table.yaml'), 'default:\n  - broken\nroles: [\n')
  const vBad = await buildRoutesView(repo3, { projectsDir: regRoot, projectKey: 'badk' })
  c.check('声明畸形表=视图解析失败点名（无 uninitialized 引导态）',
    typeof vBad.error === 'string' && vBad.error.includes('解析失败')
      && vBad.uninitialized === undefined,
    JSON.stringify({ e: vBad.error, u: vBad.uninitialized, s: vBad.state }))
}

c.finish();
