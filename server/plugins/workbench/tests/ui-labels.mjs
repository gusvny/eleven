/**
 * Baseline: 控制台 UI 英文文案唯一映射表（t260925-18，CLAUDE.md 规则 6 补充令）。
 *
 * Intent:
 *   界面文案一律英文、数据不译；英文标签以引擎既有英文标识为真源
 *   （stage id / stage_state / status / 模板 id），经 ui-labels.ts 单表映射。
 *   本测试锁三层行为契约：
 *     A. 引擎既有标识 → 英文（映射存在、不造新词）；
 *     B. 未知值回落原始标识（永不空白、永不中文）——引擎加新段/新态时 UI
 *        显示原 id，等映射表补条目，不做静默降级；
 *     C. 畸形输入（null/undefined/非字符串/空白串）不抛、回落安全值。
 *   附带锁 spec 卡 markdown 渲染的安全口径（renderMarkdown 转义先行：
 *   无活跃注入标签、危险 URL 拒绝），防 spec 卡退回裸文本/裸 HTML 注入面。
 *   Pure node 直跑——无服务器、无浏览器，随处可跑（含引擎机械 integration 步）。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  labelOf, stageLabel, stateLabel, statusLabel, workflowLabel, stageDisplayLabel,
  STAGE_LABEL, STATE_LABEL,
} from '../src/client/ui-labels.ts'
import { renderMarkdown } from '../../knowledge/src/client/markdown.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ---- A. 引擎既有标识 → 英文 ---- */
ok(stageLabel('create_plan') === 'Create Plan', 'stage create_plan → Create Plan')
ok(stageLabel('review_plan') === 'Review Plan', 'stage review_plan → Review Plan')
ok(stageLabel('merge') === 'Merge (Human Review)', 'stage merge → Merge (Human Review)')
ok(stageLabel('close') === 'Close', 'inspection stage close → Close')
ok(stateLabel('running') === 'In Progress', 'stage_state running → In Progress')
ok(stateLabel('awaiting-human') === 'Awaiting Approval', 'stage_state awaiting-human → Awaiting Approval')
ok(stateLabel('blocked') === 'Blocked', 'stage_state blocked → Blocked')
ok(statusLabel('dispatched') === 'Dispatched', 'status dispatched → Dispatched')
ok(workflowLabel('dev-lane') === 'Dev Lane', 'workflow dev-lane → Dev Lane')
ok(Object.keys(STAGE_LABEL).length >= 15, 'stage 表覆盖引擎全段词表（≥15 条）')

/* ---- B. 未知值回落原始标识（永不空白、永不中文） ---- */
ok(stageLabel('brand_new_stage') === 'brand_new_stage', '未知 stage id 回落原 id')
ok(stateLabel('weird_state') === 'weird_state', '未知 stage_state 回落原值')
ok(stageLabel('做方案') === '做方案', '中文输入原样回落（数据不译口径）')
ok(labelOf({}, 'anything') === 'anything', '空表回落原标识')

/* ---- C. 畸形输入（消费外部快照，不可信） ---- */
ok(stageLabel(null) === '', 'null → 空串不抛')
ok(stageLabel(undefined) === '', 'undefined → 空串不抛')
ok(stageLabel(42) === '', '数字 → 空串不抛')
ok(stageLabel('   ') === '', '空白串 → 空串不抛（视同未知，不显空白徽标由渲染层守卫）')
ok(stageDisplayLabel('create_plan', '做方案') === 'Create Plan', 'stageDisplayLabel：映射命中取英文')
ok(stageDisplayLabel('unknown_st', '做方案') === 'unknown_st', 'stageDisplayLabel：未知 id 回落原 id（不回落中文 label）')
ok(stageDisplayLabel('', '做方案') === '做方案', 'stageDisplayLabel：id 缺失才以引擎名兜底（有总比空白好）')
ok(stageDisplayLabel(undefined, undefined) === '', 'stageDisplayLabel：全缺省 → 空串不抛')

/* ---- D. STATE_LABEL 旧消费点兼容：表键仍是引擎标识、值全英文 ---- */
for (const [k, v] of Object.entries(STATE_LABEL)) {
  ok(/^[A-Za-z ()-]+$/.test(v), `STATE_LABEL[${k}] 值全英文 ASCII：${v}`)
}

/* ---- E. spec 卡 markdown 安全渲染（渲染器=knowledge renderMarkdown，转义先行） ---- */
const md = renderMarkdown('# Title\n\n- item\n\n`code`\n\n```bash\nls\n```\n')
ok(md.includes('<h1>'), 'markdown: 标题渲染为 h1')
ok(md.includes('<li>'), 'markdown: 列表渲染为 li')
ok(md.includes('<code>'), 'markdown: 行内码/代码块渲染')
ok(/class="[^"]*md-copy/.test(md), 'markdown: 代码块带复制按钮（页面委托承接）')

// 畸形/恶意输入：先转义后拼 HTML，无活跃注入面
ok(!/<script>/.test(renderMarkdown('<script>alert(1)</script>')), 'markdown: <script> 被转义不成为活跃标签')
ok(!/<img /.test(renderMarkdown('<img src=x onerror=alert(1)>')), 'markdown: 裸 HTML img 被转义为字面文本（onerror 不存活）')
ok(!/href="javascript:/i.test(renderMarkdown('[x](javascript:alert(1))')), 'markdown: javascript: URL 拒绝')
ok(!/src="data:/i.test(renderMarkdown('![x](data:text/html;base64,AAA)')), 'markdown: data: URL 拒绝')
// null/undefined/空串由 src 渲染守卫 `detail.spec && (` 拦截（整卡不渲染），渲染器只收真串。

/* ---- F. 三产物同源锁：映射表与 spec markdown 已进 bundle（改 src 忘重建=红） ---- */
const REPO = process.cwd()
// knowledge 渲染器自带中文按钮文案在显示层英文化（knowledge 源不在写集，字符串级后处理）
{
  const idxSrc = readFileSync(join(REPO, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  ok(idxSrc.includes("'>复制</button>', '>Copy</button>'"), 'src: spec 卡复制按钮文案显示层英文化（specMarkdownHtml 后处理）')
}
for (const name of ['client.js', 'client.cjs']) {
  const art = readFileSync(join(REPO, 'server', 'plugins', 'workbench', 'lib', name), 'utf8')
  ok(art.includes('Execution spec'), `${name}: spec 卡英文标题在场（bundle 已重建）`)
  ok(art.includes('renderMarkdown') || art.includes('md-copy'), `${name}: markdown 渲染器在场`)
  ok(art.includes('Awaiting Approval'), `${name}: STATE 映射英文字面在场`)
  ok(!art.includes('执行规格（spec）'), `${name}: 旧中文 spec 标题已退役`)
}

console.log(`\nui-labels: pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
