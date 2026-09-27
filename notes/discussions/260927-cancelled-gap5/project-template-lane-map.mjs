/**
 * tests/project-template-lane-map.mjs —— 项目外置模板的泳道图消费面（t260927 缺口 5）。
 *
 * 缺口（nusuyou 需求书三点九节）：外置模板（`paths.workflow_modules`）的票在控制台里
 * 看不到泳道/段序图——目录面（workflow.py list）只列 dev-lane，票面 topology=None，
 * 前端 `wfById[detail.workflow_id]` 查不到模板，`buildLaneMap` 无从取拓扑。
 *
 * 本 UT 锁「引擎导出的外置模板拓扑 → 渲染器视图模型」这一跳真的通（不锚浏览器）：
 *   A. 真通道取图：临时 per-key 注册根（真声明路径：project.yaml workflow_modules +
 *      真形状模块）+ spawn workflow.py list（引擎 venv 解释器）→ 外置模板行进目录面，
 *      行里 stages 与 topology 齐（段序=声明序、人门 kind 正确、线性链无边悬空）。
 *   B. 渲染器吃得下：同一 topology 喂 buildLaneMap（renderer 唯一入水口）→ 模板 id/
 *      节点序/线性渲染序/段标签全来自该拓扑，零 dev-lane 词泄漏（通用渲染器承诺）。
 *   C. 段状态照常推导：timeline 驱动 vis（running/done）与到站人门 humanGateActive
 *      （kind=human 且 awaiting-human）——「图能画」之外还「画得对」。
 *   D. 缝锁（KI-046 反「缝没接通」）：详情抽屉的拓扑取用面仍是
 *      `detail?.topology ?? selWf?.topology ?? null`（票面优先、模板面兜底、都缺才回落
 *      线性步骤条）——外置票的两条取图路径都在（票面 topology 引擎侧已补，模板面本 UT A 段证）。
 * 全程零 3099/零真 Temporal（TEMPORAL_ADDRESS 指不可达端口）；引擎 venv 缺失=显式
 * 报「没跑」并非零退出，不造假通过。
 */
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildLaneMap } from '../src/client/lane-map-model.ts'

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
if (!existsSync(VENV)) {
  console.error('ENV_FAIL 引擎 venv 缺失（外置模板类面不可加载，本 UT 无 stdlib 替代）')
  process.exit(2)
}

/* 外置模板夹具（内容编撰同形：五段链、两道人门/一段纯脚本闸） */
const TPL_ID = 'ui-probe-flow'
const TPL_SRC = `TEMPLATE_ID = "${TPL_ID}"
TEMPLATE_NAME = "外置探针流"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage


@workflow.defn
class UiProbeFlow(TicketWorkflowBase):
    STAGES = (
        Stage(id="px-brief", name="方案", role="product-operation", next="px-approve",
              parts=("agent",)),
        Stage(id="px-approve", name="立项审（人）", role="product-operation",
              next="px-produce", exit="human", revision_to="px-brief", parts=("human",)),
        Stage(id="px-produce", name="产出", role="product-operation", next="px-qc",
              parts=("agent",)),
        Stage(id="px-qc", name="机器 QC", role="integration", next="px-publish",
              agent=False, revision_to="px-produce", parts=("script",)),
        Stage(id="px-publish", name="发布闸", role="ops", next="", parts=("agent", "script")),
    )
    PATCH_ID = "ui-probe-flow-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "外置探针流"
    TEMPLATE_LANE = "main"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
`
const STAGE_IDS = ['px-brief', 'px-approve', 'px-produce', 'px-qc', 'px-publish']

const tmp = mkdtempSync(join(tmpdir(), 't260927-lanemap-'))
try {
  /* ── 夹具：临时 per-key 注册根 + 真形状外置模板模块 ── */
  const root = join(tmp, 'projects')
  const pd = join(root, 'ui-probe')
  mkdirSync(join(pd, 'mods'), { recursive: true })
  writeFileSync(join(root, '.migrated'), '', 'utf8')   // 拒 legacy 迁移写（夹具只读）
  writeFileSync(join(pd, 'project.yaml'),
    `schema: v1\nproject:\n  - key: ui-probe\n    name: 外置模板 UT 夹具\n    dirs:\n      - ${pd}\n`
    + 'paths:\n  workflow_modules: mods/flow.py\n', 'utf8')
  writeFileSync(join(pd, 'mods', 'flow.py'), TPL_SRC, 'utf8')

  const env = {
    ...process.env,
    SANDBAR_PROJECTS_DIR: root,
    TEMPORAL_ADDRESS: '127.0.0.1:1',      // 不可达端口：连了即红
    PYTHONPYCACHEPREFIX: join(tmp, 'pycache'),
  }
  delete env.SANDBAR_FIXTURE_TEMPLATES

  /* ── A. 真通道：workflow.py list 把外置模板并进目录面（带 stages + topology） ── */
  const p = spawnSync(VENV, [join(repo, 'server/tools/workflow.py'), '{"op":"list"}'],
    { cwd: repo, env, encoding: 'utf8', timeout: 180_000 })
  ok(p.status === 0, `A: workflow.py list 正常退出（exit=${p.status}）`)
  let row = null
  try { row = (JSON.parse(p.stdout).workflows ?? []).find(r => r.id === TPL_ID) ?? null } catch { /* 落下面判红 */ }
  ok(row !== null, `A: 外置模板 ${TPL_ID} 在目录面（stderr 尾=${(p.stderr || '').trim().split('\n').slice(-1)[0] || '空'}）`)
  if (row === null) throw new Error('外置模板未进目录面——渲染器无图可画')
  ok(JSON.stringify(row.stages.map(s => s.id)) === JSON.stringify(STAGE_IDS),
    'A: 行内 stages 段序=模板声明序')
  ok(row.stages.find(s => s.id === 'px-publish').parts.join(',') === 'agent,script',
    'A: 行内 stages 带 parts（执行主体消费面与内置同形）')
  const topo = row.topology
  ok(topo !== null && typeof topo === 'object' && topo.version === 'topology-v1',
    'A: 行带 topology 键（topology-v1 契约）')
  ok(topo.template === TPL_ID && JSON.stringify(topo.nodes.map(n => n.id)) === JSON.stringify(STAGE_IDS),
    'A: 拓扑节点=段全集且同序')
  const kindOf = Object.fromEntries(topo.nodes.map(n => [n.id, n.kind]))
  ok(kindOf['px-approve'] === 'human' && kindOf['px-qc'] === 'gate' && kindOf['px-produce'] === 'agent',
    'A: kind 投影与 STAGES 同口径（人门/脚本闸/agent 三段各归位）')
  const nodeIds = new Set(topo.nodes.map(n => n.id))
  ok(topo.edges.every(([a, b]) => nodeIds.has(a) && nodeIds.has(b)),
    'A: 拓扑边零悬空')
  ok(Array.isArray(topo.groups) && topo.groups.length === 0,
    'A: 线性链无并行组（无组声明即不冒充真并行）')

  /* ── B. 渲染器消费面：buildLaneMap 用该拓扑出图（标签/序全来自拓扑） ── */
  const detail = {
    workflow_id: TPL_ID,
    stage: 'px-produce',
    stage_state: 'running',
    status: 'dispatched',
    timeline: [
      { stage: 'px-brief', state: 'done', at: '2026-09-27T01:00:00', gen: 1 },
      { stage: 'px-approve', state: 'done', at: '2026-09-27T01:05:00', gen: 1 },
      { stage: 'px-produce', state: 'running', at: '2026-09-27T01:06:00', gen: 1 },
    ],
    results: {}, checks: {},
  }
  const model = buildLaneMap(topo, detail)
  ok(model !== null, 'B: 引擎导出的外置拓扑被 buildLaneMap 接受（非 null=泳道图有图可画）')
  if (model === null) throw new Error('渲染器拒收外置模板拓扑——缺口未闭合')
  ok(model.topology.template === TPL_ID, 'B: 模型模板 id 来自拓扑')
  ok(model.items.length === STAGE_IDS.length, 'B: 主道渲染序含全部节点（线性链逐节点）')
  ok(model.nodes['px-qc'].node.label === '机器 QC' && model.nodes['px-approve'].node.label === '立项审（人）',
    'B: 段标签来自模板声明（原样呈现，不另造词）')
  const words = JSON.stringify(model)
  ok(!words.includes('dev-lane') && !words.includes('create_plan') && !words.includes('做方案'),
    'B: 模型面零 dev-lane 业务词泄漏（通用渲染器承诺）')

  /* ── C. 段状态推导：timeline 驱动 + 到站人门可判（画得对） ── */
  ok(model.nodes['px-brief'].vis === 'done' && model.nodes['px-approve'].vis === 'done',
    'C: timeline 完成段推导 done')
  ok(model.nodes['px-produce'].vis === 'running' && model.nodes['px-publish'].vis === 'todo',
    'C: 当前段 running、后续段 todo')
  const awaiting = buildLaneMap(topo, {
    ...detail,
    stage: 'px-approve',
    stage_state: 'awaiting-human',
    status: 'settled',
    timeline: [
      { stage: 'px-brief', state: 'done', at: '2026-09-27T01:00:00', gen: 1 },
      { stage: 'px-approve', state: 'awaiting-human', at: '2026-09-27T01:05:00', gen: 1 },
    ],
  })
  ok(awaiting !== null && awaiting.nodes['px-approve'].vis === 'awaiting-human'
    && awaiting.humanGateActive === 'px-approve',
    'C: 到站人门 humanGateActive 落在 kind=human 节点（人审停位可判）')
  ok(awaiting !== null && awaiting.nodes['px-produce'].vis === 'todo',
    'C: 人门之下的后续段仍是 todo（未越门冒充推进）')

  /* ── D. 缝锁：详情抽屉拓扑取用面（票面优先→模板面兜底→都缺才回落线性） ── */
  const idx = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  ok(/buildLaneMap\(\s*detail\?\.topology\s*\?\?\s*selWf\?\.topology\s*\?\?\s*null/s.test(idx),
    'D: 泳道图拓扑取用面=detail.topology ?? selWf.topology ?? null（外置票两条取图路径都在）')
  const ticketSrc = readFileSync(join(repo, 'server/tools/ticket.py'), 'utf8')
  ok(ticketSrc.includes('_template_topology_fallback('),
    'D: 票面 topology 兜底在位（外置模板票的 detail.topology 非空）')
} finally {
  rmSync(tmp, { recursive: true, force: true })
}

console.log(`\nPROJECT_TEMPLATE_LANE_MAP_TESTS pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
