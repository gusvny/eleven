/**
 * smoke/projects.mjs —— 项目注册表解析器纯函数冒烟。
 *
 * 直跑：node smoke/projects.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖 project-registry.ts parseProjectsYaml：
 *   A. 标准单项目（含注释/空行）→ key/name/dirs 解析正确。
 *   B. 多项目 + 多目录（1:N）→ 顺序与归属正确。
 *   C. 写坏的形状一律抛错：缺 projects: 根 / dirs 相对路径 / 缺 name / 缺 dirs / key 重复 /
 *      key 形状不合法 / 不认的键 / dirs 同行给值。
 *   D. PROJECT_KEY_RE 边界。
 */

import { parseProjectsYaml, PROJECT_KEY_RE } from '../../../project-registry.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function throws(text, label) {
  try { parseProjectsYaml(text); failed++; console.log(`  FAIL ${label}（没抛错）`) }
  catch { passed++; console.log(`  ok ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('A 标准单项目')
{
  const r = parseProjectsYaml(`
# 顶部注释
projects:
  - key: suyou
    name: 溯游
    dirs:
      - /Users/user/Documents/sandbar   # 行尾注释
`)
  ok(r.length === 1 && r[0].key === 'suyou' && r[0].name === '溯游'
    && r[0].dirs.length === 1 && r[0].dirs[0] === '/Users/user/Documents/sandbar', '单项目解析正确')
}

section('B 多项目 + 多目录（1:N）')
{
  const r = parseProjectsYaml(`projects:
  - key: suyou
    name: 溯游
    dirs:
      - /Users/user/Documents/sandbar
      - /Users/user/Documents/sandbar-mirror
  - key: misc
    name: 杂项
    dirs:
      - /tmp/misc
`)
  ok(r.length === 2, '两个项目')
  ok(r[0].dirs.length === 2 && r[0].dirs[1] === '/Users/user/Documents/sandbar-mirror', 'suyou 双目录保序')
  ok(r[1].key === 'misc' && r[1].dirs[0] === '/tmp/misc', '第二项目正确')
}

section('C 坏形状一律抛错')
{
  throws(`- key: x`, '缺 projects: 根')
  throws(`projects:\n  - key: x\n    name: 名\n    dirs:\n      - rel/path`, 'dirs 相对路径')
  throws(`projects:\n  - key: x\n    dirs:\n      - /p`, '缺 name')
  throws(`projects:\n  - key: x\n    name: 名`, '缺 dirs')
  throws(`projects:\n  - key: x\n    name: 名\n    dirs:\n      - /p\n  - key: x\n    name: 名2\n    dirs:\n      - /q`, 'key 重复')
  throws(`projects:\n  - key: Suyou\n    name: 名\n    dirs:\n      - /p`, 'key 大写不合法')
  throws(`projects:\n  - key: x\n    name: 名\n    bogus: 1\n    dirs:\n      - /p`, '不认的键')
  throws(`projects:\n  - key: x\n    name: 名\n    dirs: [/p]`, 'dirs 同行给值')
  throws(`projects:\n  - name: 名\n    dirs:\n      - /p`, '条目首键不是 key')
}

section('D PROJECT_KEY_RE 边界')
{
  ok(PROJECT_KEY_RE.test('suyou'), '常规 key')
  ok(PROJECT_KEY_RE.test('a'), '单字符')
  ok(!PROJECT_KEY_RE.test(''), '空串')
  ok(!PROJECT_KEY_RE.test('-ab'), '中划线开头')
  ok(!PROJECT_KEY_RE.test('a b'), '含空格')
  ok(!PROJECT_KEY_RE.test('a/b'), '含斜杠（防穿路径）')
  ok(!PROJECT_KEY_RE.test('项目'), '中文不收（SA Keyword 值保持 ASCII）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
