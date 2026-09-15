/**
 * tests/workflow-list-topology.mjs —— 模板拓扑导出通道 UT（t260915-05 ④）。
 *
 * 直跑：node server/plugins/workbench/tests/workflow-list-topology.mjs
 * 覆盖：
 *   A. workflow.py list additive topology 键：dev-lane 行带拓扑契约（version/nodes/
 *      edges/groups 结构完整、边引用合法、kind 词表、人门在场、组员连续），且既有
 *      线性 stages 链原样保留（additive 不改老消费面）。
 *   B. 未声明模板 → topology=null（显式缺省，渲染器回落线性，不猜拓扑）。
 *   C. fixture-two-step（另一模板）拓扑导出可达——渲染器通用性对拍的数据面真源。
 *   D. 投影缝源码锁（KI-046 反「缝没接通」）：ticket.py _v2_query 投影白名单带
 *      'topology'——快照新键不被白名单截掉（引擎缝由 integration 池场景真锁）。
 * 全程零 3099/零真 Temporal：只 spawn python3 跑只读 CLI。
 */
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
})()

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const VENV = join(repo, 'server/engine/.venv/bin/python')
const PY = existsSync(VENV) ? VENV : 'python3'

function runJson(args) {
  const p = spawnSync(PY, args, { cwd: repo, encoding: 'utf8', timeout: 60_000 })
  if (p.status !== 0) throw new Error(`python3 ${args.join(' ')} exit=${p.status}: ${p.stderr.slice(0, 400)}`)
  return JSON.parse(p.stdout)
}

/* ── A. workflow.py list 拓扑键 ── */
{
  const out = runJson([join(repo, 'server/tools/workflow.py')])
  const rows = out.workflows ?? []
  const dev = rows.find(r => r.id === 'dev-lane')
  ok(dev !== undefined, 'A: dev-lane 模板在 list（yaml 参考快照）')
  ok(Array.isArray(dev.stages) && dev.stages.length > 0 && dev.stages[0].next !== undefined,
    'A: 既有线性 stages 链原样保留（additive 不改老面）')
  const t = dev.topology
  ok(t !== null && typeof t === 'object', 'A: list 行带 topology 键（additive）')
  ok(t.version === 'topology-v1' && t.template === 'dev-lane', 'A: 契约版本/模板 id')
  ok(Array.isArray(t.nodes) && t.nodes.length === dev.stages.length,
    'A: 拓扑节点集=STAGES 全集（节点数一致）')
  const ids = new Set(t.nodes.map(n => n.id))
  ok(dev.stages.every(s => ids.has(s.id)), 'A: 拓扑节点 id 与 stages 链同词表')
  ok(t.nodes.every(n => ['agent', 'gate', 'human'].includes(n.kind)), 'A: kind 三值词表')
  ok(t.nodes.some(n => n.kind === 'human'), 'A: 人门标记在场')
  ok(Array.isArray(t.edges) && t.edges.every(([a, b]) => ids.has(a) && ids.has(b)), 'A: 边引用全部合法（无悬空）')
  ok(Array.isArray(t.groups) && t.groups.length === 2, 'A: 并行分叉两组（真拓扑，KI-019）')
  const membersOk = t.groups.every(g => g.members.length >= 2 && g.members.every(m => ids.has(m)))
  ok(membersOk, 'A: 组员全部在节点表')
  // 组员在节点声明序中连续（fork-join 语义）
  const order = t.nodes.map(n => n.id)
  const contiguous = t.groups.every(g => {
    const idx = g.members.map(m => order.indexOf(m))
    return idx.every((v, i) => i === 0 || v === idx[i - 1] + 1)
  })
  ok(contiguous, 'A: 组员在节点序中连续')
}

/* ── B. 未声明模板 → 显式 null ── */
{
  const out = runJson(['-c', 'import sys,json;sys.path.insert(0,"server/engine");import template_topology as tt;print(json.dumps(tt.export_template_topology("no-such-template")))'])
  ok(out === null, 'B: 未声明模板导出=null（不猜拓扑）')
}
/* ── C. fixture-two-step 拓扑可达（另一模板=通用性对拍数据面） ── */
{
  const t = runJson(['-c', 'import sys,json;sys.path.insert(0,"server/engine");import template_topology as tt;print(json.dumps(tt.export_template_topology("fixture-two-step")))'])
  ok(t !== null && t.template === 'fixture-two-step', 'C: fixture-two-step 拓扑导出可达')
  ok(t.nodes.length === 2 && t.edges.length === 1 && t.groups.length === 0, 'C: 线性两段（无组）')
  ok(t.nodes[0].label === '夹具段一', 'C: 标签来自拓扑声明')
}

/* ── D. 投影缝源码锁 ── */
{
  const { readFileSync } = await import('node:fs')
  const src = readFileSync(join(repo, 'server/tools/ticket.py'), 'utf8')
  ok(/for k in \((?:[^)]*)'topology'\)/.test(src.replace(/\n\s+/g, ' ')),
    'D: ticket.py _v2_query 投影白名单带 topology（缝不截新键）')
  const wl = src.match(/for k in \(([^)]+)\)/)
  ok(wl !== null && wl[1].includes("'gate_runs'") && wl[1].includes("'gens'"),
    'D: 白名单既有键未被动（gens/gate_runs 原样）')
}

console.log(`\nWORKFLOW_LIST_TOPOLOGY_TESTS pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
