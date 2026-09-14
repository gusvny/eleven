// KI-048（t260911-05）详情「人话状态卡」UT：视图模型真值表（动态，node 26
// type-stripping 真跑 status-card.ts）+ 渲染/CSS 源级守卫（三产物同源，锁
// 「改 src 忘重建 lib」——spec-card-ui.mjs 同族）。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildStatusCard, STATUS_CARD_FILES_CAP, STATUS_CARD_LOG_TAIL } from '../src/host/status-card.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
})()

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---- A. 视图模型真值表（四件：主文案/文件点名/下一步/日志折叠） ---- */
section('A. 视图模型真值表')
{
  const detail = {
    stage_state: 'blocked',
    blocked_reason: 'merge 未收口（dirty/main_dirty）： 合并收口被 main 工作区未提交改动挡住'
      + '（git 本地改动保护，非冲突；主树现场未动）：main 工作区有未提交改动（git 本地改动保护，'
      + '非冲突）——挡事文件：server/model-routes.yaml｜处理：提交或暂存（git stash）这些改动，'
      + '或在票面说明后发 retry_qc 重验；引擎绝不自动 stash/自动提交',
    meta: { blocked_detail: { reason_code: 'main_dirty', files: ['server/model-routes.yaml'], next_action: '提交或暂存后发 retry_qc' } },
    timeline: [
      { at: '2026-09-11T10:00:00Z', stage: 'merge', state: 'blocked', reason: 'merge 未收口' },
      { at: '2026-09-11T10:01:00Z', stage: 'merge', state: 'running', reason: '重验' },
    ],
  }
  const card = buildStatusCard(detail)
  ok(card !== null, 'blocked+结构化面 → 卡渲染')
  ok(card.severity === 'red', 'blocked 态=红调')
  ok(card.headline.includes('uncommitted changes') && card.headline.includes('not a conflict'), '主文案走词条表（出了什么/非冲突）')
  ok(card.files.length === 1 && card.files[0] === 'server/model-routes.yaml', '文件点名取结构化 files')
  ok(card.next.includes('retry_qc') || card.next.includes('retry-qc'), '下一步取结构化 next_action（谁做什么）')
  ok(card.rawLog.length === 2 && card.rawLog[0].includes('merge/blocked'), '原始日志折叠=timeline 格式化行')
}
{
  // 结构化面缺席：从 blocked_reason 文本抽路径 token 兜底
  const detail = {
    stage_state: 'blocked',
    blocked_reason: 'merge 未收口：挡事文件：docs/guide.md、server/x.ts｜处理：提交或暂存',
  }
  const card = buildStatusCard(detail)
  ok(card !== null, '仅 blocked_reason 也出卡（降级不空转）')
  ok(card.files.includes('docs/guide.md') && card.files.includes('server/x.ts'), '文件点名从文本抽路径 token')
  ok(card.headline === detail.blocked_reason, '主文案回落 blocked_reason 原文')
  ok(card.severity === 'red', 'blocked 态=红调')
}
{
  // awaiting-human（黄调）：merge blocked 恢复后仍挂 detail 的中间态
  const detail = {
    stage_state: 'awaiting-human',
    blocked_reason: 'merge 未收口（dirty/main_dirty）： 挡事文件：a/b.txt',
    meta: { blocked_detail: { reason_code: 'main_dirty', files: ['a/b.txt'], next_action: '处置后 retry_qc' } },
  }
  const card = buildStatusCard(detail)
  ok(card !== null && card.severity === 'amber', '非 blocked 但有受阻面 → 黄调卡')
}
{
  // 老票零侵入：非受阻 + 无结构化面 + 无文案 → null
  ok(buildStatusCard({ stage_state: 'running', timeline: [] }) === null, '干净老票整卡不渲染')
  ok(buildStatusCard(null) === null, 'null detail 不崩，返回 null')
  ok(buildStatusCard('nonsense') === null, '非对象 detail 软降级')
  ok(buildStatusCard({}) === null, '空对象 detail → null')
}
{
  // 畸形输入族：字段类型错 / 列表混入非串 / timeline 条目畸形 / 超长截断
  const detail = {
    stage_state: 'blocked',
    blocked_reason: 123, // 非串
    meta: { blocked_detail: { reason_code: 42, files: ['ok.txt', 7, null, ''], next_action: { x: 1 } } },
    timeline: [null, 'junk', { at: 't', stage: 's', state: 'blocked', reason: 'r' }, 42],
  }
  const card = buildStatusCard(detail)
  ok(card !== null, '畸形字段不抛，卡仍出')
  ok(card.files.length === 1 && card.files[0] === 'ok.txt', 'files 混入非串被滤')
  ok(card.rawLog.length === 1 && card.rawLog[0].includes('s/blocked'), 'timeline 畸形条目逐条跳过')
  ok(typeof card.next === 'string' && card.next.length > 0, '下一步缺省话术兜底（宁显话术不显空白）')
  ok(typeof card.headline === 'string' && card.headline.length > 0, 'reason 码非串视为缺席，主文案走兜底链不空')
}
{
  // 封顶：文件 20 上限 + 溢出计数；日志尾窗
  const files = Array.from({ length: 30 }, (_, i) => `f${i}.txt`)
  const card = buildStatusCard({
    stage_state: 'blocked',
    meta: { blocked_detail: { reason_code: 'main_dirty', files, next_action: '' } },
    timeline: Array.from({ length: 30 }, (_, i) => ({ at: `t${i}`, stage: 's', state: 'x', reason: 'r' })),
  })
  ok(card.files.length === STATUS_CARD_FILES_CAP && card.filesMore === 10, `文件封顶 ${STATUS_CARD_FILES_CAP} + 溢出计数`)
  ok(card.rawLog.length === STATUS_CARD_LOG_TAIL, `日志折叠=尾部 ${STATUS_CARD_LOG_TAIL} 条`)
}

/* ---- B. 渲染/CSS 源级守卫（三产物同源锁） ---- */
section('B. 渲染分支 + CSS 守卫（src 与 lib 产物同源）')
const src = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
const libJs = readFileSync(join(repo, 'server/plugins/workbench/lib/client.js'), 'utf8')
const libCjs = readFileSync(join(repo, 'server/plugins/workbench/lib/client.cjs'), 'utf8')
for (const [name, art] of [['src', src], ['lib/client.js', libJs], ['lib/client.cjs', libCjs]]) {
  ok(art.includes('wb-status-card'), `${name}: 卡类名 wb-status-card 在场`)
  ok(art.includes('Raw engine log'), `${name}: 原始日志折叠 summary（固定元素英文）在场`)
  ok(art.includes('Next:'), `${name}: 下一步安排行（Next:）在场`)
  ok(art.includes('sc-file'), `${name}: 文件点名 chip 类名在场`)
}
ok(src.includes('buildStatusCard(detail)'), 'src: 视图模型经 buildStatusCard 纯函数派生（非内联翻译）')
ok(src.includes("data-testid=\"status-card\""), 'src: DOM 断言锚点 data-testid=status-card 在场')
ok(src.includes('.wb-status-card .sc-raw'), 'src: 折叠区样式（details.sc-raw）在场')
ok(src.includes('blocked_detail?: { reason_code?: string; files?: string[]; next_action?: string }'),
  'src: TicketDetail.meta.blocked_detail 类型声明在场')

console.log(`\nSTATUS_CARD_TESTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
