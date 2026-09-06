// t260905-06 「文档」视图纯函数层 UT（docs-model.ts 真值表 + 畸形输入矩阵）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  isSafeDocRel, isDocsScope, parseFrontmatter, buildDocTree, docTitleOf, DOCS_SCOPES,
} from '../src/shared/docs-model.ts'

let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${n} - ${name}`) }

/* ------------------------------------------------ 路径白名单（穿路径 fail-closed） */

ok('白名单：合法相对路径（含中文/子目录/下划线）放行', () => {
  assert.equal(isSafeDocRel('design/xx.md'), true)
  assert.equal(isSafeDocRel('设计文档/工单工作流台设计.md'), true)
  assert.equal(isSafeDocRel('README.md'), true)
  assert.equal(isSafeDocRel('a/b_c/d-1.md'), true)
})

ok('白名单：穿路径/绝对路径/反斜杠/URL 编码残留全拒（畸形矩阵）', () => {
  assert.equal(isSafeDocRel('../secrets.md'), false)
  assert.equal(isSafeDocRel('design/../../etc/passwd.md'), false)
  assert.equal(isSafeDocRel('/etc/passwd.md'), false)
  assert.equal(isSafeDocRel('design\\x.md'), false)
  assert.equal(isSafeDocRel('%2e%2e/x.md'), false)
  assert.equal(isSafeDocRel('design/%2f.md'), false)
})

ok('白名单：空格/全角符号/非 md/空串/非字符串拒（C3 拒收面）', () => {
  assert.equal(isSafeDocRel('my doc.md'), false)
  assert.equal(isSafeDocRel('全角名Ａ.md'), false)
  assert.equal(isSafeDocRel('design/xx.txt'), false)
  assert.equal(isSafeDocRel(''), false)
  assert.equal(isSafeDocRel(undefined), false)
  assert.equal(isSafeDocRel(123), false)
  assert.equal(isSafeDocRel(null), false)
})

ok('scope 词表：docs|notes 在册，其余拒', () => {
  assert.deepEqual([...DOCS_SCOPES], ['docs', 'notes'])
  assert.equal(isDocsScope('docs'), true)
  assert.equal(isDocsScope('notes'), true)
  assert.equal(isDocsScope('app'), false)
  assert.equal(isDocsScope(undefined), false)
})

/* ------------------------------------------------ frontmatter（畸形定值分支） */

ok('frontmatter：合法块解析出 title/status/updated，正文剥离', () => {
  const src = '---\ntitle: 测试篇\nstatus: active\nupdated: 2026-09-05\n---\n\n# 正文\n\n段落'
  const p = parseFrontmatter(src)
  assert.equal(p.hasFrontmatter, true)
  assert.equal(p.meta.title, '测试篇')
  assert.equal(p.meta.status, 'active')
  assert.equal(p.body.startsWith('# 正文'), true)
})

ok('frontmatter：无块 → 原文返回不吞内容', () => {
  const src = '# 直接正文\n没有 frontmatter'
  const p = parseFrontmatter(src)
  assert.equal(p.hasFrontmatter, false)
  assert.equal(p.body, src)
})

ok('frontmatter 畸形矩阵：缺闭合符/空文件/嵌套线/非字符串均定值不 throw', () => {
  const unclosed = parseFrontmatter('---\ntitle: 没闭合\n正文被当原文')
  assert.equal(unclosed.hasFrontmatter, false)
  assert.equal(unclosed.body.startsWith('---'), true) // 正文不丢
  const empty = parseFrontmatter('')
  assert.deepEqual(empty, { meta: {}, body: '', hasFrontmatter: false })
  const nested = parseFrontmatter('---\ntitle: a\n---\n---\ntitle: b\n---\n后文')
  assert.equal(nested.meta.title, 'a')
  assert.equal(nested.hasFrontmatter, true)
  assert.deepEqual(parseFrontmatter(undefined), { meta: {}, body: '', hasFrontmatter: false })
  assert.deepEqual(parseFrontmatter(42), { meta: {}, body: '', hasFrontmatter: false })
})

/* ------------------------------------------------ 目录树（C2 动态聚合） */

ok('buildDocTree：按实际子目录聚合，根级组单列「总目录」且恒在最前', () => {
  const tree = buildDocTree([
    { rel: 'design/b.md', title: '乙' },
    { rel: 'README.md' },
    { rel: 'design/a.md' },
    { rel: 'ops/x.md' },
  ])
  assert.deepEqual(tree.map((g) => g.dir), ['', 'design', 'ops'])
  assert.equal(tree[0].label, '总目录')
  assert.equal(tree[0].files.length, 1)
  // 组内字典序
  assert.deepEqual(tree[1].files.map((f) => f.rel), ['design/a.md', 'design/b.md'])
  // 子目录 label=最后一段（嵌套目录也成立）
  const nested = buildDocTree([{ rel: 'a/b/c.md' }])
  assert.equal(nested[0].label, 'b')
})

ok('buildDocTree：title 缺省回落 rel；白名单非法条目不进组', () => {
  const tree = buildDocTree([{ rel: 'x.md' }, { rel: '../bad.md' }, { rel: 'good.md', title: '好' }])
  assert.deepEqual(tree.map((g) => g.dir), [''])
  assert.deepEqual(tree[0].files, [{ rel: 'good.md', title: '好' }, { rel: 'x.md', title: 'x.md' }])
  assert.deepEqual(buildDocTree([]), [])
})

ok('docTitleOf：frontmatter title 优先，回落文件名去扩展名', () => {
  assert.equal(docTitleOf({ title: '定稿题' }, 'design/x.md'), '定稿题')
  assert.equal(docTitleOf({}, 'design/工单工作流台设计.md'), '工单工作流台设计')
  assert.equal(docTitleOf({ title: '' }, 'a/b.md'), 'b')
})

console.log(`DOCS_MODEL_TESTS ran=${n} pass=${n} fail=0`)
