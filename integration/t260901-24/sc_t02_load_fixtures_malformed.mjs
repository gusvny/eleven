/**
 * t02-load-fixtures-malformed —— t260901-24「capture-lane 状态注入」畸形输入面基线。
 *
 * 直跑：node integration/t260901-24/t02-load-fixtures-malformed.mjs（cwd=泳道根）。
 *
 * 黑盒契约（第 2 稿方案 loadFixtures 校验清单）：capture.mjs 导出纯函数
 * loadFixtures(dir)，消费外部输入（fixture 文件），任一畸形必须**人话拒因抛错，
 * 不静默降级**——静默降级=伪造「渲染正常」，正是本票根治的病。覆盖矩阵：
 *   缺目录 / 坏 JSON / 缺 _fixture 标记 / 缺必需键 / 软链文件 / 越出路径 → 拒跑；
 *   完整桩目录 → 通过。
 *
 * 全部用 os tmpdir 桩目录，不碰仓库与真数据。
 */

import { mkdtempSync, symlinkSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const CAPTURE = join(REPO, 'server', 'dsh', 'ui-check', 'capture.mjs')

let passed = 0, failed = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('被测模块解析：capture.mjs 导出 loadFixtures')
let loadFixtures = null
try {
  const mod = await import(pathToFileURL(CAPTURE).href + '?t=' + Date.now())
  loadFixtures = mod.loadFixtures
} catch { /* 入口守卫应保证 import 无副作用；import 失败也算未实现 */ }
if (typeof loadFixtures !== 'function') {
  console.log('  FAIL capture.mjs 未导出 loadFixtures（t260901-24 implement 段应导出该纯函数）')
  console.log(`\nSUMMARY pass=0 fail=1 env_fail=0 na=0`)
  process.exit(1)
}
ok(true, 'loadFixtures 已导出（基线可黑盒 import，入口守卫生效）')

/** 最小完整桩：五文件全齐、形状对、全带 _fixture。 */
const stubDetailB = {
  id: 'T-FIX-B', status: 'dispatched', stage: 'implement', stage_state: 'running',
  timeline: [
    { at: '2026-09-01T00:00:00', stage: 'create_plan', state: 'running' },
    { at: '2026-09-01T00:01:00', stage: 'implement', state: 'running' },
    { at: '2026-09-01T00:02:00', stage: 'design_integration_tests', state: 'running' },
  ],
  results: { create_plan: { status: 'ok', gen: 0 } }, checks: {},
}
const stubList = {
  _fixture: true,
  tickets: [
    { id: 'T-FIX-A', status: 'dispatched', stage: 'merge', stage_state: 'awaiting-human',
      workflow: 'dev-lane', role: 'integration', worktree: '/tmp/wa' },
    { id: 'T-FIX-B', status: 'dispatched', stage: 'implement', stage_state: 'running',
      workflow: 'dev-lane', role: 'developer', worktree: '/tmp/wb' },
  ],
}
function writeStub(dir, overrides = {}) {
  mkdirSync(dir, { recursive: true })
  const put = (name, obj) => writeFileSync(join(dir, name), JSON.stringify(obj))
  put('tickets-list.json', overrides.list ?? stubList)
  put('ticket-show-T-FIX-A.json', overrides.showA ?? {
    _fixture: true, id: 'T-FIX-A', status: 'dispatched', stage: 'merge', stage_state: 'awaiting-human',
    timeline: [{ at: '2026-09-01T00:00:00', stage: 'merge', state: 'awaiting-human' }],
    results: { create_plan: { status: 'ok', gen: 0 } }, checks: {},
  })
  put('ticket-show-T-FIX-B.json', overrides.showB ?? { _fixture: true, ...stubDetailB })
  put('workflows.json', overrides.workflows ?? {
    _fixture: true, workflows: [{ id: 'dev-lane', order: ['create_plan', 'implement',
      'design_integration_tests', 'merge'] }],
  })
  put('ticket-diff-T-FIX-A.json', overrides.diff ?? { _fixture: true, diff: '+hello' })
}

/** 统一 await + 捕获（loadFixtures 可能为 async；同步/异步抛错都算拒跑）。 */
async function tryLoad(dir) {
  try { return { out: await loadFixtures(dir) } } catch (e) { return { threw: e } }
}

section('畸形输入矩阵（各自人话拒因，不静默降级）')
const tmp = mkdtempSync(join(tmpdir(), 't260901-24-t02-'))
try {
  // F1 缺目录
  let r = await tryLoad(join(tmp, 'no-such-dir'))
  ok(r.threw !== undefined, 'F1 缺目录 → 抛错拒跑')
  // F2 坏 JSON
  const d2 = join(tmp, 'bad-json'); writeStub(d2)
  writeFileSync(join(d2, 'ticket-show-T-FIX-B.json'), '{not json')
  r = await tryLoad(d2)
  ok(r.threw !== undefined && /ticket-show-T-FIX-B/.test(String(r.threw?.message)),
    `F2 坏 JSON → 抛错且拒因含文件名（实际：${firstLine(r.threw)}）`)
  // F3 缺 _fixture 标记
  const d3 = join(tmp, 'no-mark'); writeStub(d3)
  patchJson(d3, 'tickets-list.json', (j) => { delete j._fixture; return j })
  r = await tryLoad(d3)
  ok(r.threw !== undefined && /tickets-list/.test(String(r.threw?.message)),
    `F3 缺 _fixture 标记 → 抛错且含文件名（实际：${firstLine(r.threw)}）`)
  // F4 缺必需键（票缺 id）
  const d4 = join(tmp, 'no-id'); writeStub(d4)
  patchJson(d4, 'tickets-list.json', (j) => { delete j.tickets[0].id; return j })
  r = await tryLoad(d4)
  ok(r.threw !== undefined, `F4 票缺必需键 id → 抛错拒跑（实际：${firstLine(r.threw)}）`)
  // F5 软链 fixture 文件（实体性校验，镜像 preset 先例）
  const d5 = join(tmp, 'symlink'); writeStub(d5)
  rmSync(join(d5, 'workflows.json'))
  symlinkSync(join(d5, 'tickets-list.json'), join(d5, 'workflows.json'))
  r = await tryLoad(d5)
  ok(r.threw !== undefined, `F5 软链 fixture 文件 → 抛错拒跑（实际：${firstLine(r.threw)}）`)
  // F6 空目录（必需文件缺）
  const d6 = join(tmp, 'empty'); mkdirSync(d6, { recursive: true })
  r = await tryLoad(d6)
  ok(r.threw !== undefined, 'F6 空目录（缺必需文件）→ 抛错拒跑')
  // F7 拒因是人话不是堆栈：非空 message
  ok(r.threw !== undefined && String(r.threw?.message || '').trim().length > 0,
    'F7 拒因为人话消息（非空 message）')
} finally {
  rmSync(tmp, { recursive: true, force: true })
}

section('完整桩 → 通过')
const dOk = join(tmpdir(), 't260901-24-t02-ok-' + process.pid)
try {
  writeStub(dOk)
  const r = await tryLoad(dOk)
  ok(r.threw === undefined && r.out != null,
    `完整桩目录 loadFixtures 通过（异常：${firstLine(r.threw)}）`)
  ok(r.out != null && typeof r.out === 'object', '返回结构化结果（供 installFixtureRoutes 消费）')
} finally {
  rmSync(dOk, { recursive: true, force: true })
}

function firstLine(e) {
  return e ? String(e?.message || e).split('\n')[0].slice(0, 120) : '（未抛）'
}
function patchJson(dir, name, fn) {
  const p = join(dir, name)
  writeFileSync(p, JSON.stringify(fn(JSON.parse(readText(p)))))
}
import { readFileSync as readText } from 'node:fs'

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
if (failed > 0) { console.log('FAILURES:\n  - ' + failures.join('\n  - ')); process.exit(1) }
