/**
 * ui-labels —— 控制台 UI 英文文案唯一映射表（t260925-18，CLAUDE.md 规则 6 补充令）。
 *
 * 口径（宿主令 260925）：
 *  - 界面文案一律英文；数据不译（票面正文/交接报告/台账保持原语言）。
 *  - 英文标签以**引擎既有英文标识**为真源（stage id / stage_state / status /
 *    workflow 模板 id），由本表统一映射；不另造词、不逐页各译。
 *  - 未知值回落原始标识本身（永不空白、永不中文）——engine 加新段/新态时
 *    UI 显示原 id，等待本表补条目，不做静默降级。
 *
 * 纯函数层：无 DOM / 无 IO，node 直跑可测（tests/ui-labels.mjs）。
 */

/** 查表回落：表内无此键 → 返回原始标识（trim 后空白串也视为未知）。 */
export function labelOf(table: Record<string, string>, id: unknown): string {
  if (typeof id !== 'string') return ''
  const key = id.trim()
  if (key === '') return ''
  return table[key] ?? key
}

/** 阶段 id → 英文段名（真源：dev_lane.py / inspection_flow.py Stage(id=…)）。 */
const STAGE_TABLE: Record<string, string> = {
  // dev-lane（server/engine/dev_lane.py STAGES）
  create_plan: 'Create Plan',
  review_plan: 'Review Plan',
  implement: 'Implement',
  design_integration_tests: 'Design Integration Tests',
  ui_evidence: 'UI Evidence',
  run_integration_tests: 'Run Integration Tests',
  arbitrate: 'Arbitrate',
  acceptance_walkthrough: 'Acceptance Walkthrough',
  merge_check: 'Merge Check',
  merge: 'Merge (Human Review)',
  // inspection-lite（server/engine/inspection_flow.py STAGES）
  setup: 'Setup',
  suite: 'Suite',
  inspect: 'Inspect',
  produce: 'Produce',
  selfcheck: 'Self-check',
  report: 'Report',
  close: 'Close',
}

/** 阶段态 stage_state → 英文（真源：base.py stage_state 写入点）。 */
const STATE_TABLE: Record<string, string> = {
  running: 'In Progress',
  awaiting: 'Awaiting Dispatch',
  'awaiting-human': 'Awaiting Approval',
  blocked: 'Blocked',
  rework: 'Rework',
  done: 'Done',
  closed: 'Done',
}

/** 台面 status → 英文（真源：引擎 status 词表）。 */
const STATUS_TABLE: Record<string, string> = {
  dispatched: 'Dispatched',
  settled: 'Settled',
  running: 'Running',
  closed: 'Closed',
  paused: 'Paused',
}

/** 工作流模板 id → 英文名（真源：模板注册 id；模板 name 字段是中文数据，不译不显）。 */
const WORKFLOW_TABLE: Record<string, string> = {
  'dev-lane': 'Dev Lane',
  'inspection-lite': 'Inspection',
  'chore-lane': 'Chore Lane',
}

export const STAGE_LABEL: Record<string, string> = STAGE_TABLE
export const STATE_LABEL: Record<string, string> = STATE_TABLE
export const STATUS_LABEL: Record<string, string> = STATUS_TABLE
export const WORKFLOW_LABEL: Record<string, string> = WORKFLOW_TABLE

export function stageLabel(id: unknown): string { return labelOf(STAGE_TABLE, id) }
export function stateLabel(id: unknown): string { return labelOf(STATE_TABLE, id) }
export function statusLabel(id: unknown): string { return labelOf(STATUS_TABLE, id) }
export function workflowLabel(id: unknown): string { return labelOf(WORKFLOW_TABLE, id) }

/** 段名优先级：拓扑/模板节点自带英文时数据侧已可用；此处只认 id 映射（显示层覆盖，
 *  不改引擎数据——review 260925 裁定：引擎中文 label 数据不动，仅显示层按 id 覆盖）。 */
export function stageDisplayLabel(stageId: unknown, engineName?: unknown): string {
  const mapped = stageLabel(stageId)
  if (mapped !== '' && mapped !== stageId) return mapped
  // 未知 id：回落原始标识；id 缺失时允许用引擎名兜底（有总比空白好，仍非自造词）。
  if (mapped === '' && typeof engineName === 'string' && engineName.trim() !== '') return engineName
  return mapped
}
