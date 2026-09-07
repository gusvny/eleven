/**
 * smoke/session-charter.mjs —— session-charter 渲染纯函数 + 接线锚冒烟（t260904-07）。
 *
 * 直跑：node smoke/session-charter.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. renderSessionCharter：四占位符全量替换（含注释/分段内字样，R4 统一渲染）、
 *      多次出现、未知占位符不动、非字符串容错、vars 缺项容错。
 *   B. splitProjectSections：通用段/分段切分、key trim、重复分段、无分段、畸形输入。
 *   C. composeSessionCharter：真实 charter 文件渲染（分段命中/未命中）、
 *      缺文件/空/非字符串回落兜底模板（不 5xx 语义）、渲染结果空回落、空 key、
 *      重复分段取首个。
 *   D. 源文本断言：node.ts 路由注册（SESSION_CHARTER_PATH 同源常量，R7 防漂移）、
 *      session-entry 注入守卫（blank 判定/恰一次 prompt 调用点/TOCTOU 复核/就地
 *      try-catch）、charter 文件内容锚（两条宿主纪律/在案授权=无/两分段/四占位符）。
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  SESSION_CHARTER_PATH,
  splitProjectSections,
  renderSessionCharter,
  composeSessionCharter,
  DEFAULT_CHARTER_TEMPLATE,
} from '../src/host/session-charter.ts'

const here = dirname(fileURLToPath(import.meta.url))
// cwd 兼容：仓库根（run_tests 约定）或 workbench 目录直跑都能定位真源文件。
// here=<repo>/server/dsh/workbench/smoke → 上四级=仓库根。
const repoRoot = join(here, '..', '..', '..', '..')
const charterFilePath = join(repoRoot, 'server', 'dsh', 'session_charter.md')
const nodeTsPath = join(repoRoot, 'server', 'dsh', 'workbench', 'node.ts')
const entryTsxPath = join(repoRoot, 'server', 'dsh', 'workbench', 'src', 'client', 'session-entry.tsx')

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

// 真源 charter 文件（C 段渲染输入 / D 段内容锚同源）。
const real = readFileSync(charterFilePath, 'utf8')
// 剥注释行后的源码（恰一次计数等源断言只看代码，不看头注）。
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
}

section('D 源文本断言（接线锚 + R7 路径同源）')
{
  ok(SESSION_CHARTER_PATH === '/sandbar-workbench/api/session-charter', '常量值正确（注册与 fetch 共用同源）')
  const nodeTs = readFileSync(nodeTsPath, 'utf8')
  ok(nodeTs.includes(`path: SESSION_CHARTER_PATH, handler: handleSessionCharter`), 'node.ts 路由注册用同源常量（R7/KI-042 防漂移）')
  ok(nodeTs.includes("readFile(join(repo, 'server', 'dsh', 'session_charter.md'), 'utf8')"), '端点每次请求现读 charter 文件')
  ok(nodeTs.includes("composeSessionCharter(raw, project, {"), '端点渲染走纯函数模块')
  ok(nodeTs.includes(`sendJson(res, 400, { ok: false, error: 'session-charter 缺 project query`), 'project query 缺失/空串=400')
  const entry = readFileSync(entryTsxPath, 'utf8')
  ok(entry.includes("import { SESSION_CHARTER_PATH, CHARTER_MARKER } from '../host/session-charter.ts'"), '客户端同源常量导入（R7 + CHARTER_MARKER，t260905-04）')
  ok(entry.includes('`${SESSION_CHARTER_PATH}?project='), 'fetch URL 由同源常量派生')
  ok(entry.includes('byId[id]?.blank === true'), '注入守卫 1：blank 位判定')
  ok((entryCode.match(/session\.prompt\(/g) ?? []).length === 1, '恰一次：prompt 调用点（剥注释后）唯一')
  ok(entry.includes("await session.prompt([{ type: 'text', text: `${CHARTER_MARKER}\\n${charter}` }], 'queue')"), 'prompt 分片数组载荷（marker 前缀，t260905-04）+queue 模式（KI-046：平台 wire 契约 PromptContentPart[]，裸字符串即 invalid payload）')
  ok(nodeTs.includes("kind: 'charter'"), '端点响应 kind=charter 字段（t260905-04 引擎打标引擎半）')
  ok(entry.includes('if (!result?.ok)'), 'prompt 业务失败不 throw 只返 RpcResult——result.ok 显式检查（KI-046：07 票 R3 兜底失效根因）')
  ok((entry.match(/isBlankSession\(sessions, staged\)/g) ?? []).length === 2, '守卫 1 + TOCTOU 复核（R5）两次 blank 判定')
  ok(entry.includes('await injectSessionCharter(sessions, staged, pk, notify)'), 'handleNew 尾段接入注入（登记后恰一次）')
  ok(entry.includes("notify('会话开局提示注入失败（详情见控制台），会话已正常创建', projectKey)"), '失败就地消化+行内提示不冒泡（R3）')
  ok(entry.includes("typeof charter !== 'string' || charter.trim() === ''"), '响应体 charter 畸形不注入（R2）')
  ok(entry.includes('响应非 JSON'), '响应非 JSON 畸形用例（R2）')
  const charter = real
  ok(charter.includes('<!-- session_charter.md'), '顶部注释在文（真源附录逐字）')
  ok(charter.includes('落盘纪律：草稿攒批'), '宿主纪律①：notes 落盘攒批在文')
  ok(charter.includes('但动手前先告知用户'), '宿主纪律②：点名修复可进 lane 先告知在文')
  ok(/## 当前在案授权\n无/.test(charter), '当前在案授权=无')
  ok(charter.includes('## project:sandbar') && charter.includes('## project:suyou'), '两个项目分段在文')
  for (const p of ['{{project_key}}', '{{project_name}}', '{{primary_dir}}', '{{engine_root}}']) {
    ok(charter.includes(p), `占位符 ${p} 在文`)
  }
  ok(DEFAULT_CHARTER_TEMPLATE.includes('{{project_key}}') && DEFAULT_CHARTER_TEMPLATE.includes('内置兜底版'), '兜底模板常量在库')
}

console.log(`\nsession-charter smoke: passed=${passed} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
