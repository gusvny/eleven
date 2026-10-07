/**
 * smoke/session-charter.mjs — smoke for the session-charter render pure functions + wiring anchors (t260904-07).
 *
 * Run: node smoke/session-charter.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers:
 *   A. renderSessionCharter: all four placeholders replaced (including placeholder-like text
 *      inside comments and sections, R4 unified rendering), multiple occurrences, unknown
 *      placeholders untouched, non-string input tolerated, missing vars entries tolerated.
 *   B. splitProjectSections: generic-section / per-section split, key trimming, duplicate
 *      sections, no sections, malformed input.
 *   C. composeSessionCharter: rendering the real charter file (section hit / miss),
 *      missing file / empty / non-string falls back to the fallback template (no-5xx
 *      semantics), empty render result falls back, empty key, duplicate sections take the first.
 *   D. Source-text assertions: the node.ts route registration (SESSION_CHARTER_PATH same-source
 *      constant, R7 anti-drift), the session-entry injection guards (blank judgment / exactly
 *      one prompt call site / TOCTOU re-check / local try-catch), the charter file content
 *      anchors (the two host disciplines / in-case authorization = none / two sections /
 *      four placeholders).
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  SESSION_CHARTER_PATH,
  CHARTER_MARKER,
  splitProjectSections,
  renderSessionCharter,
  composeSessionCharter,
  stripLeadingComment,
  charterTitleLine,
  composeCharterInjection,
  DEFAULT_CHARTER_TEMPLATE,
} from '../src/host/session-charter.ts'

const here = dirname(fileURLToPath(import.meta.url))
// cwd compatibility: works both from the repo root (the run_tests convention) and from the
// workbench directory directly. here=<repo>/server/plugins/workbench/smoke -> four levels up = repo root.
const repoRoot = join(here, '..', '..', '..', '..')
const charterFilePath = join(repoRoot, 'server', 'session_charter.md')
const nodeTsPath = join(repoRoot, 'server', 'plugins', 'workbench', 'node.ts')
const entryTsxPath = join(repoRoot, 'server', 'plugins', 'workbench', 'src', 'client', 'session-entry.tsx')

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

// The real charter file (the rendering input of section C / the content anchor of section D, same source).
const real = readFileSync(charterFilePath, 'utf8')
// Source with comment lines stripped (counting assertions like "exactly once" only look at code, not the header).
const entryCode = readFileSync(entryTsxPath, 'utf8')
  .split('\n')
  .filter(l => { const t = l.trim(); return !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('//') })
  .join('\n')

const VARS = { projectKey: 'sandbar', projectName: 'sandbar 引擎', primaryDir: '/repo/sandbar', engineRoot: '/repo' }

section('A renderSessionCharter 占位符渲染')
{
  const out = renderSessionCharter('k={{project_key}} n={{project_name}} d={{primary_dir}} e={{engine_root}}', VARS)
  ok(out === 'k=sandbar n=sandbar 引擎 d=/repo/sandbar e=/repo', '四占位符全量替换')
  const multi = renderSessionCharter('{{project_key}}-{{project_key}}', VARS)
  ok(multi === 'sandbar-sandbar', '同占位符多次出现全替换')
  const keep = renderSessionCharter('{{unknown}} {{ project_key }}', VARS)
  ok(keep === '{{unknown}} {{ project_key }}', '未知/异形占位符原样不动')
  ok(renderSessionCharter(null, VARS) === '', 'raw 非字符串容错为空串')
  const partial = renderSessionCharter('k={{project_key}}/{{project_name}}', { projectKey: 'x' })
  ok(partial === 'k=x/', 'vars 缺项容错为空串')
  ok(renderSessionCharter('n={{project_name}}', { ...VARS, projectName: undefined }) === 'n=', 'vars 值 undefined 容错')
}

section('B splitProjectSections 分段解析')
{
  const raw = '# 通用\n通用正文\n## project:a\nA1\n## project:b\nB1\n'
  const r = splitProjectSections(raw)
  ok(r.general === '# 通用\n通用正文', '通用段=首个分段标题前全文')
  ok(r.sections.length === 2 && r.sections[0].key === 'a' && r.sections[1].key === 'b', '两分段 key 解析')
  ok(r.sections[0].body.startsWith('## project:a'), '分段 body 含标题行（原文追加语义）')
  const dup = splitProjectSections('g\n## project:a\n第一份\n## project:a\n第二份\n')
  ok(dup.sections.length === 2 && dup.sections[0].body.includes('第一份'), '重复分段都解析（合并侧取首个）')
  const none = splitProjectSections('没有分段')
  ok(none.sections.length === 0 && none.general === '没有分段', '无分段 → sections 空 general=原文')
  const empty = splitProjectSections(null)
  ok(empty.general === '' && empty.sections.length === 0, 'null 容错为空产物')
  const spaced = splitProjectSections('g\n  ## project:c\nC\n')
  ok(spaced.sections.length === 1 && spaced.sections[0].key === 'c', '标题行缩进/空格容错')
}

section('C composeSessionCharter 组装与回落')
{
  const sandbar = composeSessionCharter(real, 'sandbar', VARS)
  ok(sandbar.includes('「sandbar 引擎」的项目会话（key=sandbar，主目录=/repo/sandbar）'), '通用模板占位符现填')
  ok(sandbar.includes('## project:sandbar') && sandbar.includes('引擎真源在本仓'), '命中 sandbar 分段原文追加')
  ok(!sandbar.includes('## project:suyou'), '未命中分段不出现（suyou 段不追加）')
  ok(!sandbar.includes('{{'), '注释与分段内占位符统一渲染净尽（R4）')
  const suyou = composeSessionCharter(real, 'suyou', VARS)
  ok(suyou.includes('## project:suyou') && suyou.includes('引擎操作一律用 /repo'), 'suyou 分段命中且段内 engine_root 渲染')
  ok(!suyou.includes('## project:sandbar'), 'suyou 组装不出现 sandbar 段')
  const unknown = composeSessionCharter(real, 'nosuch', VARS)
  ok(unknown.includes('「sandbar 引擎」的项目会话') && !unknown.includes('引擎真源在本仓') && !unknown.includes('本项目仓已冻结'), '未注册 key → 只回通用段（分段正文不出现）')
  const fallback1 = composeSessionCharter('', 'sandbar', VARS)
  const fallback2 = composeSessionCharter(null, 'sandbar', VARS)
  const fallback3 = composeSessionCharter('   \n  ', 'sandbar', VARS)
  for (const [i, out] of [fallback1, fallback2, fallback3].entries()) {
    ok(out.includes('内置兜底版') && out.includes('key=sandbar') && !out.includes('{{'), `缺文件/空/空白回落兜底模板且渲染（用例 ${i + 1}）`)
  }
  const emptyRender = composeSessionCharter('{{project_name}}', 'sandbar', { projectKey: 'sandbar', projectName: '', primaryDir: '', engineRoot: '' })
  ok(emptyRender.includes('内置兜底版'), '渲染结果整体空白 → 回落兜底模板')
  ok(!composeSessionCharter(real, '', VARS).includes('引擎真源在本仓'), '空 key → 不命中任何分段')
  ok(!composeSessionCharter(real, undefined, VARS).includes('本项目仓已冻结'), 'key 非字符串容错 → 只回通用段')
  const dup = composeSessionCharter('g\n## project:d\n第一份独有\n## project:d\n第二份独有\n', 'd', VARS)
  ok(dup.includes('第一份独有') && !dup.includes('第二份独有'), '重复分段取首个')
  // t261008-01：文件头注释不进注入文本（只摘首部闭合块；正文/分段原样）。
  ok(!composeSessionCharter(real, 'sandbar', VARS).includes('session_charter.md ——'), '文件头注释被摘除，不进注入文本')
  const withComment = composeSessionCharter('<!-- doc -->\n正文A\n## project:x\nX\n', 'x', VARS)
  ok(withComment.startsWith('正文A') && withComment.includes('## project:x'), '前置注释摘除后正文/分段原样保留')
  ok(composeSessionCharter('<!-- 未闭合\n正文B\n', 'x', VARS).includes('<!-- 未闭合'), '未闭合注释原样保留（不吞文件）')
  ok(composeSessionCharter('正文C\n<!-- 尾部注释 -->\n', 'x', VARS).startsWith('正文C'), '非首部注释不动（只摘首部）')
  ok(DEFAULT_CHARTER_TEMPLATE.includes('内置兜底版') && composeSessionCharter('', 'k', VARS).includes('内置兜底版'), '兜底模板不受摘注释影响')
}

section('D 源文本断言（接线锚 + R7 路径同源）')
{
  ok(SESSION_CHARTER_PATH === '/sandbar-workbench/api/session-charter', '常量值正确（注册与 fetch 共用同源）')
  const nodeTs = readFileSync(nodeTsPath, 'utf8')
  ok(nodeTs.includes(`path: SESSION_CHARTER_PATH, handler: handleSessionCharter`), 'node.ts 路由注册用同源常量（R7/KI-042 防漂移）')
  ok(nodeTs.includes("readFile(join(repo, 'server', 'session_charter.md'), 'utf8')"), '端点每次请求现读 charter 文件')
  ok(nodeTs.includes("composeSessionCharter(raw, project, {"), '端点渲染走纯函数模块')
  ok(nodeTs.includes(`sendJson(res, 400, { ok: false, error: 'session-charter 缺 project query`), 'project query 缺失/空串=400')
  ok(nodeTs.includes('projectName, kind'), '端点响应带 projectName 字段（t261008-01：客户端拼人读标题行）')
  const entry = readFileSync(entryTsxPath, 'utf8')
  ok(entry.includes("import { SESSION_CHARTER_PATH, composeCharterInjection } from '../host/session-charter.ts'"), '客户端同源常量/组装函数导入（R7 防漂移，t261008-01）')
  ok(entry.includes('`${SESSION_CHARTER_PATH}?project='), 'fetch URL 由同源常量派生')
  ok(entry.includes('byId[id]?.blank === true'), '注入守卫 1：blank 位判定')
  ok((entryCode.match(/session\.prompt\(/g) ?? []).length === 1, '恰一次：prompt 调用点（剥注释后）唯一')
  ok(entry.includes("composeCharterInjection(displayProjectName, projectKey, charter)"), '注入文本经 composeCharterInjection 拼装（首行=人读标题，t261008-01）')
  ok(entry.includes("typeof projectName === 'string' && projectName.trim() !== '' ? projectName : projectKey"), 'projectName 畸形/缺失回落 projectKey')
  ok(nodeTs.includes("kind: 'charter'"), '端点响应 kind=charter 字段（t260905-04 引擎打标引擎半）')
  ok(entry.includes('if (!result?.ok)'), 'prompt 业务失败不 throw 只返 RpcResult——result.ok 显式检查（KI-046：07 票 R3 兜底失效根因）')
  ok((entry.match(/isBlankSession\(sessions, staged\)/g) ?? []).length === 2, '守卫 1 + TOCTOU 复核（R5）两次 blank 判定')
  ok(entry.includes('await injectSessionCharter(sessions, staged, pk, notify)'), 'handleNew 尾段接入注入（登记后恰一次）')
  ok(entry.includes("notify('Session charter injection failed (see the console for details); the session was created normally', projectKey)"), '失败就地消化+行内提示不冒泡（R3；文案英文=261004 控制台 UI 文案口径，本断言随票面文案纪律更新）')
  ok(entry.includes("typeof charter !== 'string' || charter.trim() === ''"), '响应体 charter 畸形不注入（R2）')
  ok(entry.includes('响应非 JSON'), '响应非 JSON 畸形用例（R2）')
  const charter = real
  ok(charter.includes('<!-- session_charter.md'), '顶部注释在文（真源附录逐字）')
  ok(charter.includes('stripLeadingComment') && charter.includes('composeCharterInjection'), '文件头注释写明摘除/标题行机制（t261008-01）')
  ok(charter.includes('落盘纪律：草稿攒批'), '宿主纪律①：notes 落盘攒批在文')
  ok(charter.includes('但动手前先告知用户'), '宿主纪律②：点名修复可进 lane 先告知在文')
  // 261004 起在案授权=executor-grants.json 文件面（不再是「无」字面量）——断言随真源口径更新。
  ok(charter.includes('## 当前在案授权') && charter.includes('executor-grants.json'), '在案授权段=grants 文件面口径（261004）')
  ok(charter.includes('## project:sandbar') && charter.includes('## project:suyou'), '两个项目分段在文')
  for (const p of ['{{project_key}}', '{{project_name}}', '{{primary_dir}}', '{{engine_root}}']) {
    ok(charter.includes(p), `占位符 ${p} 在文`)
  }
  ok(DEFAULT_CHARTER_TEMPLATE.includes('{{project_key}}') && DEFAULT_CHARTER_TEMPLATE.includes('内置兜底版'), '兜底模板常量在库')
}

section('E 注入拼装（t261008-01：首行人读标题行 + 标记第 2 行）')
{
  const inj = composeCharterInjection('sandbar 引擎', 'sandbar', '正文一\n正文二')
  const lines = inj.split('\n')
  ok(lines[0] === 'Project session — sandbar 引擎 (sandbar)', '首行=人读标题行（点名项目）')
  ok(lines[1] === CHARTER_MARKER, '第 2 行=机读标记（不再占首行）')
  ok(inj.endsWith('正文一\n正文二'), 'charter 正文原样在后')
  ok(!lines[0].startsWith('<!--'), '首行不再是 HTML 注释（平台标题取首行）')
  ok(composeCharterInjection('', 'sandbar', 'x').split('\n')[0] === 'Project session — sandbar', 'name 空 → 回落 key（同值不重复括注）')
  ok(composeCharterInjection('   ', '', 'x').split('\n')[0] === 'Project session — project', 'name/key 全空 → 固定 label')
  ok(composeCharterInjection('n', 'n', 'x').split('\n')[0] === 'Project session — n', 'name=key 不重复括注')
  ok(composeCharterInjection(null, undefined, 'x').split('\n')[0] === 'Project session — project', '非字符串入参容错')
  ok(composeCharterInjection('n', 'k', 42).endsWith('\n'), 'charter 非字符串容错为空串（不抛）')
  // stripLeadingComment 直测（矩阵：有/无/未闭合/非首部/非字符串）。
  ok(stripLeadingComment('<!-- a -->\nB') === 'B', '闭合首部注释整块摘除')
  ok(stripLeadingComment('  <!-- a -->\r\nB') === 'B', '缩进注释摘除（前导空白保留语义等价）')
  ok(stripLeadingComment('B\n<!-- t -->') === 'B\n<!-- t -->', '无首部注释 → no-op')
  ok(stripLeadingComment('<!-- 未闭合') === '<!-- 未闭合', '未闭合 → 原样返回')
  ok(stripLeadingComment(42) === 42, '非字符串原样返回')
  // 标题行独立直测。
  ok(charterTitleLine('N', 'K') === 'Project session — N (K)', 'charterTitleLine 基形')
  ok(typeof charterTitleLine(undefined, undefined) === 'string', '畸形入参不抛')
}

console.log(`\nsession-charter smoke: passed=${passed} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
