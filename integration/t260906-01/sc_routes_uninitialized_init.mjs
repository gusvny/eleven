// sc_routes_uninitialized_init.mjs — t260906-01 场景③：路由无表引导态 + 一键初始化。
//
// intent（用户可感知行为，工单验收「路由视图引导态可一键初始化」、方案 D 段契约）：
//   A. 无表项目路由视图=「未初始化」引导态（uninitialized+template_source），红错退役——
//      运行时本就回落默认模型，无表≠故障；
//   B. 畸形表（不可解析）= 仍走解析失败红错（三态：畸形 fail-closed，不降级为引导态）；
//   C. POST /suyou-admin/api/routes/init 对无表项目=建父目录 + 原子写引擎真源表
//      （写入后与引擎仓表逐字节一致——同源模板不造两份）；
//   D. init 对已有表=拒收零覆盖（放一张用户自有表再 init，断言内容不被覆盖）；
//   E. init 后 GET 视图=出表（uninitialized 消失、default 可解析）。
//
// 台别：API 面（mock webServer 手法同 server/dsh/ui/smoke/routes.mjs E 段，无浏览器，
// 进程内 apply 不起监听、零 3099 接触）；wire 口径=project 走 ?project= 查询参
// （与同族 GET /api/routes 一致）。实现落地前本场景红属预期（TDD 信号），
// arbitrate/merge 期必须绿。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { tmpRoot, makeChecks, writeProjectEntry } from '../t260904-14/lib_fix14.mjs';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const REPO_ROOT = path.resolve(HERE, '..', '..');
const c = makeChecks('t260906-01 路由无表引导态+一键初始化');
delete process.env.SANDBAR_PROJECTS_YAML;

const ENGINE_TABLE = path.join(REPO_ROOT, 'server', 'dsh', 'model-routes.yaml');
const { buildRoutesView } = await import(
  pathToFileURL(path.join(REPO_ROOT, 'server', 'dsh', 'ui', 'src', 'host', 'routes.ts')).href);
const { apply } = await import(
  pathToFileURL(path.join(REPO_ROOT, 'server', 'dsh', 'ui', 'node.ts')).href);

const mktempRepo = async (prefix) => await mkdtemp(path.join(tmpdir(), prefix));

// 项目解析缝：?project= 是注册表 key（findProject，非裸路径）——write 端点只服务
// 已注册项目（未注册=未知项目拒收，fail-closed）。fixture：隔离注册表根 + 条目。
const regRoot = tmpRoot('t260906-reg-');
mkdirSync(regRoot, { recursive: true });
writeFileSync(path.join(regRoot, '.migrated'), 'source: fixture\n');
process.env.SANDBAR_PROJECTS_DIR = regRoot;

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

const projUrl = (key) => '/suyou-admin/api/routes?project=' + encodeURIComponent(key)
const initUrl = (key) => '/suyou-admin/api/routes/init?project=' + encodeURIComponent(key)

// ---- A：无表=引导态非红错（视图半 + API 半双面；repo 连 server/dsh/ 都没有）----
const emptyRepo = await mktempRepo('t260906-noroutes-')
writeProjectEntry(regRoot, 'rtk', 'RT', [emptyRepo]) // 已注册项目、主目录无表（引导态旅程主体）
{
  const v = await buildRoutesView(emptyRepo)
  c.check('无表视图 uninitialized=true（非 error）',
    v.uninitialized === true && v.error === undefined,
    JSON.stringify({ u: v.uninitialized, e: v.error }))
  c.check('引导态含模板来源路径（template_source）',
    typeof v.template_source === 'string' && v.template_source.includes('model-routes.yaml'),
    JSON.stringify(v.template_source))

  const find = mountRoutes(emptyRepo)
  const r = await call(find('/suyou-admin/api/routes').handler, projUrl('rtk'))
  c.check('API 无表=200 ok:true + uninitialized 透传（不再 ok:false 红错）',
    r.status === 200 && r.body.ok === true && r.body.result?.uninitialized === true,
    JSON.stringify(r.body).slice(0, 300))
}

// ---- C + E：init 一键建表（父目录缺失代建+同源模板字节一致+无 tmp 泄漏）→ 视图出表 ----
{
  const find = mountRoutes(emptyRepo)
  const init = find('/suyou-admin/api/routes/init')
  c.check('init 端点已挂（POST /suyou-admin/api/routes/init）', init !== undefined)

  // 未注册项目=拒收（write 端点 fail-closed，不认裸路径）
  const rBad = await call(init.handler, initUrl('nosuchk'), 'POST')
  c.check('init 对未注册项目=拒收（ok:false 未知项目）',
    rBad.body?.ok === false && rBad.body.error.includes('未知项目'),
    JSON.stringify(rBad.body).slice(0, 200))

  const r = await call(init.handler, initUrl('rtk'), 'POST')
  c.check('init 成功 ok:true + routes_file 回执',
    r.status === 200 && r.body.ok === true && typeof r.body.result?.routes_file === 'string',
    JSON.stringify(r.body).slice(0, 300))
  const target = path.join(emptyRepo, 'server', 'dsh', 'model-routes.yaml')
  c.check('表已落盘（父目录 server/dsh/ 由 init 代建）', existsSync(target), target)
  c.check('写入与引擎仓真源逐字节一致（同源模板）',
    existsSync(target) && readFileSync(target).equals(readFileSync(ENGINE_TABLE)),
    'init copy != engine source')
  c.check('无 .tmp 写泄漏（原子写口径）',
    !existsSync(target + '.tmp') && !existsSync(target + '.scaffold-tmp'), 'tmp leak')

  const r2 = await call(find('/suyou-admin/api/routes').handler, projUrl('rtk'))
  c.check('init 后视图出表（uninitialized 消失、default 可解析）',
    r2.status === 200 && r2.body.ok === true && r2.body.result?.uninitialized === undefined
      && r2.body.result?.default !== null,
    JSON.stringify(r2.body ?? {}).slice(0, 300))
}

// ---- D + B：init 对已有表=拒收零覆盖；畸形表=解析失败红错不降级 ----
{
  const repo2 = await mktempRepo('t260906-hastable-')
  mkdirSync(path.join(repo2, 'server', 'dsh'), { recursive: true })
  writeProjectEntry(regRoot, 'hask', 'Hask', [repo2]) // 已注册、主目录自带自有表
  const p = path.join(repo2, 'server', 'dsh', 'model-routes.yaml')
  const own = '# my own table\ndefault:\n  provider: mine\n  model: m1\n'
  writeFileSync(p, own) // 用户自有表（故意非引擎表内容）

  const find = mountRoutes(repo2)
  const r = await call(find('/suyou-admin/api/routes/init').handler, initUrl('hask'), 'POST')
  c.check('init 对已有表=拒收（ok:false）', r.body?.ok === false, JSON.stringify(r.body).slice(0, 300))
  c.check('已有表内容零覆盖（不被引擎表冲掉）', readFileSync(p, 'utf8') === own, 'table overwritten')

  writeFileSync(p, 'default:\n  - broken\nroles: [\n') // 打成畸形
  const vBad = await buildRoutesView(repo2)
  c.check('畸形表=解析失败红错（无 uninitialized 引导态）',
    typeof vBad.error === 'string' && vBad.error.includes('解析失败')
      && vBad.uninitialized === undefined,
    JSON.stringify({ e: vBad.error, u: vBad.uninitialized }))
}

c.finish();
