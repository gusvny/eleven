#!/usr/bin/env node
/**
 * project-routes.mjs —— 项目生命周期三路由 UT（t260904-15 票③，S2 面）。
 *
 * 直跑：node tests/project-routes.mjs。复用 epics-api.mjs 的 apply()+mock HTTP
 * harness 模式；注册表 fixture 走 SANDBAR_PROJECTS_DIR 指临时目录（带 .migrated
 * 标记免迁移链），CLI 走假 sandbar 脚本（config.python=process.execPath 测试缝），
 * 零触真仓/真注册表/console。覆盖：
 *   A0. 真 CLI 契约锚（UT 盲区教训：旗标断言必须锚真 CLI 契约，
 *       不许 stub 断言把错误 argv 钉成期望）：sandbar project add|remove --help 实跑——
 *       add 无 --dry-run 旗；remove 为 --key 必选旗+三旗在案；
 *   A. GET /wf/projects：projects + quarantined 同响应（隔离条目带 dir/error 定位）；
 *   B. 空/全隔离注册表 → 200 空数组（不再 500——首接发生在空表时）；
 *   C. GET detail：票计数透传 / 降级态透传 / key 形状 400 / 未知 key 404 / POST 405；
 *   D. POST add：args 透传（dry_run:true=422 能力应答，F1）/ 拒收 409 原文透传 / GET 405 / 坏 body 400；
 *   E. POST remove：--key 旗 + dry-run/purge/confirm-last 旗与 CLI 一一对应（F2）。
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply } from './../node.ts'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 假 sandbar：回显 argv（断言旗标一一对应），PROJECT_FAKE_MODE 变体同 project-admin UT。 */
function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo, python: process.execPath })
  const find = (path) => routes.find(r => r.path === path)
  return {
    projects: find('/sandbar-workbench/api/wf/projects'),
    detail: find('/sandbar-workbench/api/wf/projects/detail'),
    add: find('/sandbar-workbench/api/wf/projects/add'),
    remove: find('/sandbar-workbench/api/wf/projects/remove'),
  }
}
const mockRes = () => ({
  status: 0, body: null,
  writeHead(s) { this.status = s },
  end(b) { this.body = b ? JSON.parse(b) : null },
})
const call = async (handler, url, method = 'GET', bodyObj) => {
  const res = mockRes()
  const payload = bodyObj === undefined ? [] : [Buffer.from(JSON.stringify(bodyObj))]
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* payload } }
  await handler.handler(req, res)
  return res
}

function writeFakeCli(repo, listJson) {
  mkdirSync(repo, { recursive: true })
  writeFileSync(join(repo, 'sandbar'), `const mode = process.env.PROJECT_FAKE_MODE ?? 'echo'
if (mode === 'echo') { console.log(JSON.stringify({ ok: true, argv: process.argv.slice(2) })); process.exit(0) }
if (mode === 'list') { console.log(${JSON.stringify(listJson)}); process.exit(0) }
if (mode === 'fail-json') { console.log(JSON.stringify({ ok: false, error: '根目录不存在：/no-such-dir' })); process.exit(1) }
if (mode === 'reject-text') { console.log('[红] key 不合法：Fix_B'); process.exit(1) }
`, 'utf8')
}

const savedEnv = {
  SANDBAR_PROJECTS_DIR: process.env.SANDBAR_PROJECTS_DIR,
  SANDBAR_PROJECTS_YAML: process.env.SANDBAR_PROJECTS_YAML,
}
delete process.env.SANDBAR_PROJECTS_YAML

const LIST_JSON = JSON.stringify({
  ok: true, action: 'list', mode: 'per-key',
  projects: [
    { key: 'alpha', name: '甲', dirs: ['/tmp/alpha'], primary: '/tmp/alpha', tickets: { open: 1, closed: 2, archived: 2 }, tickets_state: 'ok', tickets_note: '' },
    { key: 'beta', name: '乙', dirs: ['/tmp/beta'], primary: '/tmp/beta', tickets: null, tickets_state: 'degraded', tickets_note: 'Temporal 不可达：connection refused' },
  ],
  quarantined: [],
})

try {
  /* -------- A0 真 CLI 契约锚（真跑 --help，防旗标漂移绿到生产） -------- */
  section('A0 真 CLI 契约锚（python3 sandbar project add|remove --help）')
  {
    const { execFileSync } = await import('node:child_process')
    const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')
    const help = (sub) => execFileSync('python3', [join(repoRoot, 'sandbar'), 'project', sub, '--help'], { encoding: 'utf8', cwd: repoRoot })
    const addHelp = help('add')
    ok(addHelp.includes('--key') && addHelp.includes('--name') && addHelp.includes('--dir') && addHelp.includes('--json'), 'add 旗集：--key/--name/--dir/--json')
    ok(!addHelp.includes('--dry-run'), 'add 无 --dry-run 旗（F1 实锚：路由不得拼该旗）')
    const rmHelp = help('remove')
    ok(rmHelp.includes('--key') && rmHelp.includes('--dry-run') && rmHelp.includes('--purge-data') && rmHelp.includes('--purge-credentials') && rmHelp.includes('--confirm-last'), 'remove 旗集：--key 必选旗+四旗在案（F2 实锚）')
  }

  /* -------- A/B 注册表面 -------- */
  section('A GET /wf/projects：projects + quarantined 同响应')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-proutes-'))
    const reg = join(tmp, 'registry')
    mkdirSync(join(reg, 'alpha'), { recursive: true })
    writeFileSync(join(reg, 'alpha', 'project.yaml'), 'schema: v1\nproject:\n  - key: alpha\n    name: 甲\n    dirs:\n      - /tmp/alpha\n', 'utf8')
    mkdirSync(join(reg, 'badschema'), { recursive: true })
    writeFileSync(join(reg, 'badschema', 'project.yaml'), 'schema: v2\nproject:\n  - key: badschema\n    name: 坏\n    dirs:\n      - /tmp/bad\n', 'utf8')
    writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
    process.env.SANDBAR_PROJECTS_DIR = reg
    const repo = join(tmp, 'repo')
    writeFakeCli(repo, LIST_JSON)
    const h = makeHarness(repo)
    const r = await call(h.projects, '/sandbar-workbench/api/wf/projects')
    ok(r.status === 200 && r.body.ok === true, '200 装载成功')
    ok(r.body.result.projects.length === 1 && r.body.result.projects[0].key === 'alpha', '好条目装载')
    const q = r.body.result.quarantined
    ok(Array.isArray(q) && q.length === 1 && q[0].key === 'badschema', '隔离条目同响应（不再拖垮整体）')
    ok(String(q[0].error).includes(join(reg, 'badschema', 'project.yaml')) || String(q[0].dir).includes('badschema'),
      '隔离原因含 <dir>/project.yaml 定位')
    rmSync(tmp, { recursive: true, force: true })
  }

  section('B 空/全隔离注册表 → 200（不再 500，首接发生在空表）')
  {
    const tmp = mkdtempSync(join(tmpdir(), 'wb-proutes-empty-'))
    const reg = join(tmp, 'registry')
    mkdirSync(reg, { recursive: true })
    writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
    process.env.SANDBAR_PROJECTS_DIR = reg
    const repo = join(tmp, 'repo')
    writeFakeCli(repo, LIST_JSON)
    const h = makeHarness(repo)
    const r = await call(h.projects, '/sandbar-workbench/api/wf/projects')
    ok(r.status === 200, '空注册表 → 200（loadRegistry 改造，零分组仍可接首项目）')
    ok(r.body.result.projects.length === 0 && r.body.result.quarantined.length === 0, '双侧空数组')
    rmSync(tmp, { recursive: true, force: true })
  }

  /* -------- C/D/E CLI 面（假 CLI 回显/list/fail） -------- */
  const tmp = mkdtempSync(join(tmpdir(), 'wb-proutes-cli-'))
  process.env.SANDBAR_PROJECTS_DIR = join(tmp, 'unused-registry')
  const repo = join(tmp, 'repo')
  writeFakeCli(repo, LIST_JSON)
  const h = makeHarness(repo)

  section('C GET detail：票计数/降级透传 + 400/404/405')
  {
    process.env.PROJECT_FAKE_MODE = 'list'
    let r = await call(h.detail, '/sandbar-workbench/api/wf/projects/detail?key=alpha')
    ok(r.status === 200 && r.body?.result?.key === 'alpha', `detail → 200（got ${r.status} ${JSON.stringify(r.body).slice(0,120)}）`)
    ok(r.body.result.tickets.open === 1 && r.body.result.tickets.archived === 2 && r.body.result.tickets_state === 'ok', '票计数透传')
    r = await call(h.detail, '/sandbar-workbench/api/wf/projects/detail?key=beta')
    ok(r.status === 200 && r.body.result.tickets_state !== 'ok' && String(r.body.result.tickets_note).includes('connection refused'),
      '降级态原样透传（弹层显「—」不红的源）')
    r = await call(h.detail, '/sandbar-workbench/api/wf/projects/detail?key=ALPHA')
    ok(r.status === 400, 'key 形状不合法 → 400')
    r = await call(h.detail, '/sandbar-workbench/api/wf/projects/detail?key=ghost')
    ok(r.status === 404 && String(r.body.error).includes('ghost'), 'list 无此 key → 404 人话')
    r = await call(h.detail, '/sandbar-workbench/api/wf/projects/detail?key=alpha', 'POST')
    ok(r.status === 405, 'POST detail → 405（只读契约）')
    delete process.env.PROJECT_FAKE_MODE
  }

  section('D POST add：args 透传 / 拒收 409 / GET 405 / 坏 body 400')
  {
    let r = await call(h.add, '/sandbar-workbench/api/wf/projects/add', 'POST',
      { key: 'trip', name: '旅行', dir: '/tmp/trip', dry_run: true })
    ok(r.status === 422, 'add dry_run → 422 能力应答（F1：CLI 无 --dry-run 旗，不 spawn）')
    ok(String(r.body.error).includes('本地形状检查'), '422 文案指路弹层本地预检')
    r = await call(h.add, '/sandbar-workbench/api/wf/projects/add', 'POST',
      { key: 'trip', name: '旅行', dir: '/tmp/trip' })
    ok(r.status === 200 && r.body.result.argv.join(' ') === 'project add --key trip --name 旅行 --dir /tmp/trip --json',
      'args 与真 CLI 契约一致（A0 锚：无 --dry-run）')
    process.env.PROJECT_FAKE_MODE = 'reject-text'
    r = await call(h.add, '/sandbar-workbench/api/wf/projects/add', 'POST',
      { key: 'trip', name: '旅行', dir: '/tmp/trip' })
    ok(r.status === 409 && String(r.body.error).includes('[红] key 不合法'), 'CLI 拒收（人话）→ 409 原文透传（F3：非 502）')
    process.env.PROJECT_FAKE_MODE = 'fail-json'
    r = await call(h.add, '/sandbar-workbench/api/wf/projects/add', 'POST',
      { key: 'trip', name: '旅行', dir: '/tmp/trip' })
    ok(r.status === 409 && String(r.body.error).includes('根目录不存在'), 'CLI 拒收（JSON 体）→ 409 错误体透传（就地显示源）')
    delete process.env.PROJECT_FAKE_MODE
    r = await call(h.add, '/sandbar-workbench/api/wf/projects/add', 'GET')
    ok(r.status === 405, 'GET 写路由 → 405')
    const res = mockRes()
    const req = { url: '/x', method: 'POST', async *[Symbol.asyncIterator]() { yield Buffer.from('not json') } }
    await h.add.handler(req, res)
    ok(res.status === 400, '坏 body → 400')
  }

  section('E POST remove：purge/confirm 旗一一对应')
  {
    let r = await call(h.remove, '/sandbar-workbench/api/wf/projects/remove', 'POST',
      { key: 'alpha', dry_run: true, purge_data: true, purge_credentials: true, confirm_last: true })
    ok(r.status === 200, 'remove dry-run → 200')
    ok(r.body.result.argv.join(' ') === 'project remove --key alpha --json --dry-run --purge-data --purge-credentials --confirm-last',
      '旗标与 CLI 一一对应（F2：--key 必选旗；在飞闸/purge 前置闸全在 CLI 侧）')
    r = await call(h.remove, '/sandbar-workbench/api/wf/projects/remove', 'POST', { key: 'alpha' })
    ok(r.body.result.argv.join(' ') === 'project remove --key alpha --json', '默认全保留（零旗=可逆摘除）')
    rmSync(tmp, { recursive: true, force: true })
  }
} finally {
  if (savedEnv.SANDBAR_PROJECTS_DIR === undefined) delete process.env.SANDBAR_PROJECTS_DIR
  else process.env.SANDBAR_PROJECTS_DIR = savedEnv.SANDBAR_PROJECTS_DIR
  if (savedEnv.SANDBAR_PROJECTS_YAML === undefined) delete process.env.SANDBAR_PROJECTS_YAML
  else process.env.SANDBAR_PROJECTS_YAML = savedEnv.SANDBAR_PROJECTS_YAML
}

console.log(`\nPROJECT_ROUTES_TESTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
