/**
 * smoke/ki057-anchors.mjs —— 工单台六面项目感知化的宿主半冒烟（t260907-11 KI-057）。
 *
 * 直跑：node smoke/ki057-anchors.mjs。mock webServer/req/res 驱动 apply()（changes.mjs
 * 同款 harness），临时注册表 fixture（SANDBAR_PROJECTS_DIR）+ 临时双仓布局，零触
 * 真注册表/真引擎；不触 3099/7233。覆盖（对照方案 S3/S4 路由面）：
 *   A. epics 面：?project=fpv 列 fpv 立项单（resolved.source=project）、无参列引擎仓
 *      立项单（回落不变）、未知 key 400、隔离条目 502；
 *   B. sandbar key 等价断言：?project=sandbar 的 resolved.root 与无参回落链 repo 一致；
 *   C. 审批面写路径：POST review ?project=fpv → 落 <fpv仓>/server/dsh/reviews/，GET 回读一致；
 *   D. 证据面：?project=fpv 枚举 fpv 仓归档+泳道截图，无参回落引擎仓。
 */

import { mkdtemp, mkdir, readFile, realpath, writeFile } from 'node:fs/promises'
import { statSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = await mkdtemp(join(tmpdir(), 'wb-ki057-'))
await mkdir(join(tmp, 'engine'), { recursive: true })
await mkdir(join(tmp, 'fpv'), { recursive: true })
const engineRepo = await realpath(join(tmp, 'engine'))
const fpvRepo = await realpath(join(tmp, 'fpv'))
await mkdir(join(engineRepo, 'server', 'dsh'), { recursive: true })
await mkdir(join(engineRepo, 'notes', 'epics'), { recursive: true })
await mkdir(join(fpvRepo, 'notes', 'epics'), { recursive: true })
await writeFile(join(engineRepo, 'notes', 'epics', 'engine-epic.md'), '# 立项单：引擎立项\n\n| 状态 | 进行中 |\n', 'utf8')
await writeFile(join(fpvRepo, 'notes', 'epics', 'fpv-epic.md'), '# 立项单：fpv 立项\n\n| 状态 | 进行中 |\n', 'utf8')

// 注册表 fixture：sandbar（primaryDir=engineRepo）+ fpv（primaryDir=fpvRepo）+ 坏条目
const reg = await mkdtemp(join(tmpdir(), 'wb-ki057-reg-'))
const entry = (key, dir) => `# 注释\nschema: v1\n\nproject:\n  - key: ${key}\n    name: ${key}\n    dirs:\n      - ${dir}\n`
for (const [key, dir] of [['sandbar', engineRepo], ['fpv', fpvRepo]]) {
  await mkdir(join(reg, key), { recursive: true })
  await writeFile(join(reg, key, 'project.yaml'), entry(key, dir), 'utf8')
}
await mkdir(join(reg, 'broken'), { recursive: true })
await writeFile(join(reg, 'broken', 'project.yaml'), 'dirs:\n  - 不是绝对路径\n', 'utf8')
process.env.SANDBAR_PROJECTS_DIR = reg
delete process.env.SANDBAR_PROJECTS_YAML

const routes = []
const ws = { register: (r) => { routes.push(r); return () => {} } }
const ctx = {
  effect: (fn) => { fn() },
  logger: { info() {}, warn() {} },
  get: (k) => (k === 'webServer' ? ws : undefined),
  on: () => () => {},
}
apply(ctx, { repo: engineRepo })

const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b; this.body = b ? JSON.parse(b) : null },
})
const mockReq = (url, method = 'GET', json) => ({
  url, method,
  async *[Symbol.asyncIterator]() { if (json !== undefined) yield Buffer.from(JSON.stringify(json)) },
})
async function call(prefix, url, method = 'GET', json) {
  // exact 优先（epics 列表挂 exact；带子路径时用 prefix）。URL 与 prefix 完全相等（可带 query）。
  const bare = url.split('?')[0]
  const r = routes.find(x => x.kind === 'exact' && x.path === bare) ?? routes.find(x => x.kind === 'prefix' && x.path === prefix)
  const res = mockRes()
  await r.handler(mockReq(url, method, json), res)
  return res
}
const TICKETS = '/sandbar-workbench/api/wf/tickets'
const EPICS = '/sandbar-workbench/api/epics'

section('A epics 面：?project= 解析与显式报错')
{
  let r = await call(EPICS, `${EPICS}?project=fpv`)
  ok(r.status === 200 && r.body.result.epics.some(e => e.code === 'fpv-epic'), '?project=fpv 列 fpv 立项单')
  ok(r.body.resolved?.source === 'project' && r.body.resolved.root === fpvRepo, '响应带 resolved（source=project，root=fpv 主目录）')
  r = await call(EPICS, EPICS)
  ok(r.status === 200 && r.body.result.epics.some(e => e.code === 'engine-epic'), '无参回落引擎仓立项单（行为不变）')
  ok(r.body.resolved?.source === 'default', '无参 resolved.source=default（可观测）')
  r = await call(EPICS, `${EPICS}?project=nope`)
  ok(r.status === 400 && (r.body.error ?? '').includes('未知项目 key'), '未知 key → 400 点名项目键（不静默回落）')
  r = await call(EPICS, `${EPICS}?project=broken`)
  ok(r.status === 502, '隔离条目 → 502（透传注册表错误）')
}

section('B sandbar key 等价断言（注册表条目与回落链不漂移）')
{
  const r = await call(EPICS, `${EPICS}?project=sandbar`)
  ok(r.status === 200 && r.body.resolved?.source === 'project' && r.body.resolved.root === engineRepo,
    '?project=sandbar 的 root === 无参回落 repo（零回归钉）')
}

section('C 审批面写路径随项目根')
{
  const id = 't-ki057-1'
  const round = { base: 'abc', conclude: 'approved', reviewer: 'op-smoke', blocks: [{ block_key: 'k1', summary: 's', type: 'paragraph', status: 'modified' }] }
  let r = await call(TICKETS, `${TICKETS}/${id}/review?project=fpv`, 'POST', round)
  ok(r.status === 200 && r.body.ok === true, 'POST review ?project=fpv → 200')
  const saved = JSON.parse(await readFile(join(fpvRepo, 'server', 'dsh', 'reviews', `${id}.json`), 'utf8'))
  ok(saved.rounds.length === 1 && saved.rounds[0].reviewer === 'op-smoke', '落 <fpv仓>/server/dsh/reviews/<id>.json')
  ok(!exists(engineRepo, 'server/dsh/reviews', `${id}.json`), '引擎仓审批目录未被误写')
  r = await call(TICKETS, `${TICKETS}/${id}/review?project=fpv`)
  ok(r.body.result.rounds.length === 1, 'GET 回读一致')
  r = await call(TICKETS, `${TICKETS}/${id}/review?project=nope`, 'POST', round)
  ok(r.status === 400, 'POST 未知 key → 400（不落盘不回落）')
}

section('D 证据面随项目根')
{
  const id = 't-ki057-2'
  await mkdir(join(fpvRepo, '.suyou', 'evidence', id), { recursive: true })
  await writeFile(join(fpvRepo, '.suyou', 'evidence', id, 'shot.png'), 'png', 'utf8')
  await mkdir(join(fpvRepo, '.worktrees', id, '.suyou', 'screenshots'), { recursive: true })
  await writeFile(join(fpvRepo, '.worktrees', id, '.suyou', 'screenshots', 'live.png'), 'png', 'utf8')
  let r = await call(TICKETS, `${TICKETS}/${id}/evidence?project=fpv`)
  ok(r.status === 200 && r.body.result.files.includes('shot.png') && r.body.result.files.includes('live.png'),
    '?project=fpv 枚举归档+泳道双候选')
  r = await call(TICKETS, `${TICKETS}/t-nothere/evidence?project=fpv`)
  ok(r.status === 200 && r.body.result.files.length === 0, '无证据 → files:[]（枚举语义不变）')
}

function exists(...segs) {
  try { statSync(join(...segs)); return true } catch { return false }
}

console.log(`\nKI057_ANCHORS_SMOKE pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
