#!/usr/bin/env node
/**
 * registry-loader.mjs —— per-key 项目注册表装载器自测（t260901-14，sandbar M1-1）。
 *
 * 直跑：node integration/t260901-14/registry-loader.mjs（node ≥22.18 原生 type-stripping）。
 * 全部用临时目录 fixture + SANDBAR_PROJECTS_DIR env 隔离，绝不触真实 ~/.sandbar。
 * 覆盖（对照 .suyou/plan-t260901-14.md 用例清单）：
 *   1. 正常多项目扫描 / findProject / primaryDir / 跨项目汇总
 *   2. env 每次调用现读（先 import 后设 env）
 *   3. 跳过：data/ 保留位、无 project.yaml 目录、点开头目录
 *   4. 畸形态逐条 → quarantined（含 <dir>/project.yaml 定位），不炸好条目
 *   5. 版本态：schema 缺失 / schema: v2
 *   6. key 与目录名不等 / 目录名不合法
 *   7. findProject：未知 key=undefined、隔离 key=抛错带原因、形状不合法=undefined
 *   8. 空注册表三分支：根空→迁移 / 全隔离→抛错列原因 / 有标记零条目→抛错
 *   9. 迁移：逐条出仓 + .migrated、幂等零重写、源写坏→抛错、含 # 值拒绝迁移、序列化可往返
 *   9b. 无标记三类现场（修订 v2.1）：崩溃残留→续迁补齐、人工注册表→接受、混合现场→fail-closed
 *  10. legacy env（SUYOU_PROJECTS_YAML）旧单文件模式回归
 */

import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const m = await import('../../../suyou-projects.ts')
const { loadRegistry, loadProjects, findProject, parseProjectYaml, migrateRegistry, PROJECT_KEY_RE } = m

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function throws(fn, label, needle = '') {
  try { fn(); failed++; console.log(`  FAIL ${label}（没抛错）`); return '' }
  catch (e) {
    const msg = String(e instanceof Error ? e.message : e)
    if (needle && !msg.includes(needle)) { failed++; console.log(`  FAIL ${label}（抛错但缺「${needle}」：${msg}）`); return msg }
    passed++; console.log(`  ok ${label}`); return msg
  }
}
function section(t) { console.log(`\n== ${t}`) }

// 每个场景独立 temp 根；legacy env 一律清掉，防外部串扰
delete process.env.SUYOU_PROJECTS_YAML
function freshRoot() {
  const root = mkdtempSync(join(tmpdir(), 'sandbar-reg-'))
  process.env.SANDBAR_PROJECTS_DIR = root
  return root
}
function writeEntry(root, key, text) {
  mkdirSync(join(root, key), { recursive: true })
  writeFileSync(join(root, key, 'project.yaml'), text, 'utf8')
}
const GOOD = (key, name = '名', dirs = ['/p1', '/p2']) =>
  `# 注释\nschema: v1\n\nproject:\n  - key: ${key}\n    name: ${name}\n    dirs:\n${dirs.map(d => `      - ${d}`).join('\n')}\n`

section('1 正常多项目扫描 / 查找 / 主目录 / 汇总')
{
  const root = freshRoot()
  writeEntry(root, 'alpha', GOOD('alpha', '甲', ['/a']))
  writeEntry(root, 'beta', GOOD('beta', '乙', ['/b1', '/b2']))
  const reg = loadRegistry()
  ok(reg.projects.length === 2 && reg.quarantined.length === 0, '两条目全好')
  ok(reg.projects[0].key === 'alpha' && reg.projects[0].name === '甲', 'alpha 解析正确')
  ok(reg.projects[1].dirs.join(',') === '/b1,/b2', 'beta 双目录保序')
  ok(loadProjects().length === 2, 'loadProjects 汇总=2（跨项目扇出读取）')
  const p = findProject('beta')
  ok(p && p.key === 'beta' && m.primaryDir(p) === '/b1', 'findProject + primaryDir=dirs[0]')
}

section('2 env 每次调用现读（先 import 后设 env）')
{
  const r1 = freshRoot()
  writeEntry(r1, 'one', GOOD('one'))
  ok(loadProjects().length === 1 && loadProjects()[0].key === 'one', '第一根生效')
  const r2 = freshRoot()
  writeEntry(r2, 'two', GOOD('two'))
  ok(loadProjects()[0].key === 'two', '换 env 后现读生效（无常量化）')
}

section('3 跳过：data/ 保留位 / 无条目目录 / 点开头目录')
{
  const root = freshRoot()
  mkdirSync(join(root, 'alpha', 'data'), { recursive: true })
  writeEntry(root, 'alpha', GOOD('alpha'))
  mkdirSync(join(root, 'data'), { recursive: true })           // 根级 data/ 保留位
  mkdirSync(join(root, 'scratch'), { recursive: true })        // 无 project.yaml
  mkdirSync(join(root, '.hidden'), { recursive: true })
  writeEntry(root, '.hidden', GOOD('hidden'))
  const reg = loadRegistry()
  ok(reg.projects.length === 1 && reg.projects[0].key === 'alpha', '只装载 alpha，其余跳过')
  ok(reg.quarantined.length === 0, '无隔离')
}

section('4 畸形态逐条 → quarantined（含定位），不炸好条目')
{
  const cases = [
    ['顶层非 project', 'schema: v1\nregistry:\n  - key: bad\n'],
    ['首键非 key', 'schema: v1\nproject:\n  - name: 名\n    dirs:\n      - /p\n'],
    ['key 不合法', 'schema: v1\nproject:\n  - key: Bad Key\n    name: 名\n    dirs:\n      - /p\n'],
    ['缺 name', 'schema: v1\nproject:\n  - key: badx\n    dirs:\n      - /p\n'],
    ['缺 dirs', 'schema: v1\nproject:\n  - key: badx\n    name: 名\n'],
    ['dirs 相对路径', 'schema: v1\nproject:\n  - key: badx\n    name: 名\n    dirs:\n      - rel/p\n'],
    ['dirs 同行给值', 'schema: v1\nproject:\n  - key: badx\n    name: 名\n    dirs: [/p]\n'],
    ['不认的键', 'schema: v1\nproject:\n  - key: badx\n    name: 名\n    bogus: 1\n    dirs:\n      - /p\n'],
    ['断行残缺', 'schema: v1\nproject:\n  - key: badx\n    na'],
  ]
  for (const [label, text] of cases) {
    const root = freshRoot()
    writeEntry(root, 'badx', text)
    writeEntry(root, 'good', GOOD('good'))
    const reg = loadRegistry()
    ok(reg.projects.length === 1 && reg.projects[0].key === 'good', `${label}：好条目不受影响`)
    ok(reg.quarantined.length === 1 && reg.quarantined[0].error.includes(`${join(root, 'badx')}/project.yaml`),
      `${label}：隔离原因含 <dir>/project.yaml 定位`)
  }
  // 纯畸形（无好条目）时 loadRegistry 不抛、loadProjects 抛（见第 8 节）
  const root = freshRoot()
  writeEntry(root, 'badx', 'schema: v1\nproject:\n  - key: badx\n    name: 名\n')
  ok(loadRegistry().quarantined.length === 1, 'loadRegistry 单坏条目不抛（隔离语义）')
}

section('5 版本态')
{
  const root = freshRoot()
  writeEntry(root, 'noversion', 'project:\n  - key: noversion\n    name: 名\n    dirs:\n      - /p\n')
  writeEntry(root, 'future', 'schema: v2\nproject:\n  - key: future\n    name: 名\n    dirs:\n      - /p\n')
  const reg = loadRegistry()
  ok(reg.quarantined.length === 2, '两条全隔离')
  ok(reg.quarantined.some(q => q.dir.endsWith('noversion') && q.error.includes('schema: 缺失')), 'schema 缺失=畸形')
  ok(reg.quarantined.some(q => q.dir.endsWith('future') && q.error.includes('声明 v2，支持集 {v1}')), 'schema v2=版本不支持，报声明与支持集')
}

section('6 key 与目录名不等 / 目录名不合法')
{
  const root = freshRoot()
  writeEntry(root, 'dirname', GOOD('othername'))
  mkdirSync(join(root, 'Bad Key'), { recursive: true })
  writeFileSync(join(root, 'Bad Key', 'project.yaml'), GOOD('badkey'), 'utf8')
  const reg = loadRegistry()
  ok(reg.quarantined.length === 2, '两条全隔离')
  ok(reg.quarantined.some(q => q.error.includes('key 与目录名不等：othername ≠ dirname')), 'key≠目录名 显式报')
  ok(reg.quarantined.some(q => q.error.includes('目录名不合法') && q.error.includes('Bad Key')), '目录名不过白名单显式报')
  ok(!PROJECT_KEY_RE.test('Bad Key'), '白名单拒空格目录名')
}

section('7 findProject：未知/隔离/形状')
{
  const root = freshRoot()
  writeEntry(root, 'good', GOOD('good'))
  writeEntry(root, 'sick', 'schema: v1\nproject:\n  - key: sick\n    name: 名\n')  // 缺 dirs
  ok(findProject('good')?.key === 'good', '好 key 命中')
  ok(findProject('nosuch') === undefined, '真未知 key → undefined（调用方 400）')
  ok(findProject('BAD KEY!') === undefined, '形状不合法 → undefined')
  const msg = throws(() => findProject('sick'), '隔离 key → 抛错', '已隔离')
  ok(msg.includes('sick') && msg.includes('缺 dirs'), '抛错含 key 与隔离原因')
}

section('8 空注册表三分支（全显式，无静默）')
{
  // (a) 根不存在 + 种子在位 → 自动迁移（见第 9 节）；根存在但零条目同样触发迁移
  const root = freshRoot()
  mkdirSync(root, { recursive: true })
  const reg = loadRegistry()  // 空根 → 从仓库种子迁移（种子=server/projects.yaml，含 suyou）
  ok(reg.projects.length >= 1 && reg.projects.some(p => p.key === 'suyou'), '空根→自动迁移出 suyou')
  // (b) 全隔离 → 抛错列原因
  const root2 = freshRoot()
  writeFileSync(join(root2, '.migrated'), 'source: test\n', 'utf8')
  writeEntry(root2, 'sick', 'schema: v1\nproject:\n  - key: sick\n    name: 名\n')
  throws(() => loadProjects(), '全隔离 → loadProjects 抛错', '被隔离')
  try { loadProjects() } catch (e) {
    ok(String(e.message).includes('sick') && String(e.message).includes('缺 dirs'), '抛错列出各条隔离原因')
  }
  // (c) 有标记、零条目 → 抛错
  const root3 = freshRoot()
  writeFileSync(join(root3, '.migrated'), 'source: test\n', 'utf8')
  throws(() => loadProjects(), '零条目 → 抛错', '没有任何项目条目')
}

section('9 迁移：出仓/幂等/坏源/拒 #/往返')
{
  const tmp = mkdtempSync(join(tmpdir(), 'sandbar-seed-'))
  const seed = join(tmp, 'projects.yaml')
  writeFileSync(seed, `projects:\n  - key: one\n    name: 壹\n    dirs:\n      - /d1\n  - key: two\n    name: 贰\n    dirs:\n      - /d2\n      - /d3\n`, 'utf8')
  const root = join(tmp, 'out')
  migrateRegistry(root, seed)
  ok(existsSync(join(root, 'one', 'project.yaml')) && existsSync(join(root, 'two', 'project.yaml')), '逐条出仓')
  ok(existsSync(join(root, '.migrated')), '.migrated 标记已写')
  const back = parseProjectYaml(readFileSync(join(root, 'two', 'project.yaml'), 'utf8'), 'two')
  ok(back.key === 'two' && back.name === '贰' && back.dirs.join(',') === '/d2,/d3', '序列化可往返')
  // 幂等：二次迁移不动已落盘文件
  const before = statSync(join(root, 'one', 'project.yaml')).mtimeMs
  migrateRegistry(root, seed)
  ok(statSync(join(root, 'one', 'project.yaml')).mtimeMs === before, '二次迁移零重写')
  // 坏源 → 抛错（key 重复）
  const badseed = join(tmp, 'bad.yaml')
  writeFileSync(badseed, `projects:\n  - key: x\n    name: 名\n    dirs:\n      - /p\n  - key: x\n    name: 名2\n    dirs:\n      - /q\n`, 'utf8')
  throws(() => migrateRegistry(join(tmp, 'out2'), badseed), '坏源（key 重复）→ 抛错', 'key 重复')
  // 含 # 的 name：严格子集把 # 当注释起点剥掉（解析阶段已不可见），迁移正常进行——
  // 这正是「值不含 #」的来源；serialize 侧的 # 防御分支对解析器不可达，保留防直调。
  const hashseed = join(tmp, 'hash.yaml')
  writeFileSync(hashseed, `projects:\n  - key: h\n    name: 名#注\n    dirs:\n      - /p\n`, 'utf8')
  const hashroot = join(tmp, 'out3')
  migrateRegistry(hashroot, hashseed)
  ok(parseProjectYaml(readFileSync(join(hashroot, 'h', 'project.yaml'), 'utf8'), 'x').name === '名',
    'name 中 # 被严格子集当注释剥掉（迁移不受阻）')
  // 标记在位：即使根里之后只剩坏条目也不再触发迁移分支（走全隔离抛错而非现场判定）
  const marked = freshRoot()
  writeFileSync(join(marked, '.migrated'), 'source: test\n', 'utf8')
  writeEntry(marked, 'sick', 'schema: v1\nproject:\n  - key: sick\n    name: 名\n')
  throws(() => loadProjects(), '有标记+坏条目 → 全隔离抛错（不误判现场）', '被隔离')
}

section('9b 无标记三类现场（修订 v2.1）：续迁 / 人工注册表 / 混合 fail-closed')
{
  // 说明：装载路径的 ensureMigrated 固定用仓库种子（key=suyou）；多 key 续迁场景
  // 用导出的 resumeMigration/expectedEntries 直测，单 key 集成场景走装载路径。
  const tmp = mkdtempSync(join(tmpdir(), 'sandbar-scenes-'))
  const seed = join(tmp, 'projects.yaml')
  const seedText = `projects:\n  - key: one\n    name: 壹\n    dirs:\n      - /d1\n  - key: two\n    name: 贰\n    dirs:\n      - /d2\n`
  writeFileSync(seed, seedText, 'utf8')
  // (a) 崩溃残留（直测续迁件）：迁移后删一条 → 续迁只补缺失、不动已有、补标记
  const resumed = join(tmp, 'resumed')
  migrateRegistry(resumed, seed)
  rmSync(join(resumed, 'two'), { recursive: true })
  rmSync(join(resumed, '.migrated'))
  const before = statSync(join(resumed, 'one', 'project.yaml')).mtimeMs
  const expected = m.expectedEntries(m.parseProjectsYaml(seedText, seed), seed)
  m.resumeMigration(resumed, expected, new Set(['one']))
  ok(existsSync(join(resumed, 'two', 'project.yaml')), '续迁补齐缺失条目')
  ok(parseProjectYaml(readFileSync(join(resumed, 'two', 'project.yaml'), 'utf8'), 'x').key === 'two', '补齐条目内容=种子期望')
  ok(statSync(join(resumed, 'one', 'project.yaml')).mtimeMs === before, '续迁不动已有条目（mtime 不变）')
  ok(existsSync(join(resumed, '.migrated')), '续迁补写 .migrated')
  // (a2) 装载路径集成（仓库种子）：迁移后丢标记 → 自动续迁补标记、条目不重写
  const integ = freshRoot()
  ok(loadProjects().some(p => p.key === 'suyou'), '空根装载触发迁移（集成）')
  const markerPath = join(integ, '.migrated')
  ok(existsSync(markerPath), '迁移写标记（集成）')
  const suyouBefore = statSync(join(integ, 'suyou', 'project.yaml')).mtimeMs
  rmSync(markerPath)
  ok(loadProjects().some(p => p.key === 'suyou'), '丢标记后装载照常（续迁接受）')
  ok(existsSync(markerPath), '续迁补回标记（集成）')
  ok(statSync(join(integ, 'suyou', 'project.yaml')).mtimeMs === suyouBefore, '续迁不重写已有条目（集成）')
  // (b) 纯人工注册表（与种子零交集）→ 接受，无需标记
  const hand = freshRoot()
  writeEntry(hand, 'userreg', GOOD('userreg'))
  ok(loadProjects()[0].key === 'userreg' && !existsSync(join(hand, '.migrated')), '人工注册表接受，不写标记')
  // (c) 混合现场：种子 key（suyou）但字节被人工改过 → fail-closed 抛错
  const mixed = freshRoot()
  mkdirSync(join(mixed, 'suyou'), { recursive: true })
  writeFileSync(join(mixed, 'suyou', 'project.yaml'), GOOD('suyou', '被改过', ['/elsewhere']), 'utf8')
  throws(() => loadProjects(), '混合现场（种子 key 非种子字节）→ fail-closed', '无法判定')
  try { loadProjects() } catch (e) {
    ok(String(e.message).includes('混合现场'), '抛错指明混合现场与处置口径')
  }
  // (d) 混合现场：种子 key + 隔离条目共存 → fail-closed
  const mixed2 = freshRoot()
  mkdirSync(join(mixed2, 'suyou'), { recursive: true })
  writeFileSync(join(mixed2, 'suyou', 'project.yaml'),
    readFileSync(join(integ, 'suyou', 'project.yaml'), 'utf8'), 'utf8')  // 精确种子字节
  writeEntry(mixed2, 'sick', 'schema: v1\nproject:\n  - key: sick\n    name: 名\n')
  throws(() => loadProjects(), '混合现场（种子条目+坏条目）→ fail-closed', '无法判定')
  rmSync(tmp, { recursive: true, force: true })
}

section('10 legacy env（SUYOU_PROJECTS_YAML）旧单文件模式回归')
{
  const tmp = mkdtempSync(join(tmpdir(), 'sandbar-legacy-'))
  const legacy = join(tmp, 'projects.yaml')
  writeFileSync(legacy, `projects:\n  - key: smoketest\n    name: 冒烟\n    dirs:\n      - ${tmp}\n`, 'utf8')
  process.env.SUYOU_PROJECTS_YAML = legacy
  delete process.env.SANDBAR_PROJECTS_DIR
  const reg = loadRegistry()
  ok(reg.projects.length === 1 && reg.projects[0].key === 'smoketest' && reg.projects[0].dirs[0] === tmp, '旧格式单文件解析不变')
  ok(reg.quarantined.length === 0, 'legacy 模式无隔离概念')
  ok(findProject('smoketest')?.name === '冒烟', 'legacy 模式 findProject 正常')
  writeFileSync(legacy, `- key: x\n`, 'utf8')  // 写坏（缺 projects: 根）
  throws(() => loadProjects(), 'legacy 文件写坏 → 抛错', 'projects:')
  delete process.env.SUYOU_PROJECTS_YAML
}

// 清理所有 temp 目录
for (const d of [process.env.SANDBAR_PROJECTS_DIR]) {
  if (d && d.includes('sandbar-')) rmSync(d, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
console.log(`SUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
