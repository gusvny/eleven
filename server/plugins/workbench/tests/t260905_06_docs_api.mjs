// t260905-06 「文档」宿主半 UT（src/host/docs.ts：枚举/读取真值表 + 畸形输入矩阵）。
// fixture=mkdtemp 临时目录自搭，不依赖真仓 docs/notes 内容；exit 0 = 过。
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { listDocs, readDoc, DOC_MAX_CHARS } from '../src/host/docs.ts'

let seq = 0
function fresh() { return mkdtempSync(join(tmpdir(), 't0606-docs-') + String(++seq)) }

const cases = []
function test(name, fn) { cases.push([name, fn]) }

/* ------------------------------------------------ listDocs（目录树） */

test('listDocs：动态分组 + frontmatter 标题 + skipped 可见（C2/C3）', async () => {
  const root = fresh()
  mkdirSync(join(root, 'design'), { recursive: true })
  writeFileSync(join(root, 'README.md'), '# 总目录\n')
  writeFileSync(join(root, 'design', '夹具甲篇.md'), '---\ntitle: 定稿甲\n---\n正文甲\n')
  writeFileSync(join(root, 'design', '带 空格.md'), 'x\n')
  writeFileSync(join(root, 'design', '笔记.txt'), 'x\n')
  const t = await listDocs(root, 'docs')
  assert.equal(t.empty, false)
  assert.deepEqual(t.groups.map((g) => g.dir), ['', 'design'])
  assert.equal(t.groups[0].files[0].title, 'README') // 无 frontmatter 回落文件名
  assert.equal(t.groups[1].files[0].title, '定稿甲')
  assert.deepEqual(t.skipped.map((s) => s.path), ['design/带 空格.md', 'design/笔记.txt'])
  assert.match(t.skipped[0].reason, /空格/)
  assert.match(t.skipped[1].reason, /仅 \.md/)
})

test('listDocs：目录缺席 → empty+reason 点名真没有（KI-025 口径；措辞=项目根 t260910-10）', async () => {
  const t = await listDocs(join(fresh(), '不存在的目录'), 'notes')
  assert.equal(t.empty, true)
  assert.match(t.reason, /目录不存在/)
  assert.match(t.reason, /项目根=/)
  assert.doesNotMatch(t.reason, /仓根/) // KI-070 后 root=项目锚解析的项目根，措辞不误导诊断（C7）
  assert.deepEqual(t.groups, [])
  assert.deepEqual(t.skipped, [])
})

test('listDocs：嵌套子目录动态聚合，label=最后一段（C2 不写死名单）', async () => {
  const root = fresh()
  mkdirSync(join(root, 'a', 'b'), { recursive: true })
  writeFileSync(join(root, 'a', 'b', 'deep.md'), '---\ntitle: 深篇\n---\n')
  const t = await listDocs(root, 'docs')
  assert.equal(t.groups[0].dir, 'a/b')
  assert.equal(t.groups[0].label, 'b')
  assert.equal(t.groups[0].files[0].title, '深篇')
})

/* ------------------------------------------------ readDoc（按篇读取） */

test('readDoc：合法篇返回 title/meta/body，正文剥 frontmatter', async () => {
  const root = fresh()
  mkdirSync(join(root, '设计'), { recursive: true })
  writeFileSync(join(root, '设计', '夹具篇.md'), '---\ntitle: 夹具题\nstatus: active\n---\n\n# 正文标题\n\n```js\ncode()\n```\n')
  const r = await readDoc(root, '设计/夹具篇.md')
  assert.equal(r.empty, false)
  assert.equal(r.title, '夹具题')
  assert.equal(r.meta.status, 'active')
  assert.ok(r.body.startsWith('# 正文标题'))
  assert.ok(r.body.includes('```js'))
})

test('readDoc 畸形矩阵：穿路径/绝对/反斜杠/%编码/空串/空格/非md 逐检查精确报错', async () => {
  const root = fresh()
  mkdirSync(join(root, 'secret'), { recursive: true })
  writeFileSync(join(root, 'secret', 'x.md'), '机密')
  for (const [bad, hint] of [
    ['../secret/x.md', '\\.\\.'],
    ['..%2Fsecret%2Fx.md', '%'],
    ['/etc/passwd.md', '绝对路径'],
    ['a\\b.md', '反斜杠'],
    ['', '缺失'],
    ['good name.md', '段字符'],
    ['x.txt', '不合法'],
  ]) {
    const r = await readDoc(root, bad)
    assert.equal(r.empty, true, JSON.stringify(bad))
    assert.match(r.reason, new RegExp(hint), JSON.stringify(bad))
  }
  // 白名单允许但真没有 → 「文件不存在」（不许谎报，KI-025）
  assert.match((await readDoc(root, '没有这篇.md')).reason, /文件不存在/)
})

test('readDoc：大小上限拒绝（reason 点名超限）；上限内正常读', async () => {
  const root = fresh()
  writeFileSync(join(root, 'big.md'), 'x'.repeat(DOC_MAX_CHARS + 1))
  const r = await readDoc(root, 'big.md')
  assert.equal(r.empty, true)
  assert.match(r.reason, /超过大小上限/)
  writeFileSync(join(root, 'ok.md'), 'y'.repeat(DOC_MAX_CHARS))
  assert.equal((await readDoc(root, 'ok.md')).empty, false)
})

test('readDoc：根内符号链接不拦（只读面，非本票威胁模型）；.. 段穿出必挡', async () => {
  const root = fresh()
  const outside = fresh()
  writeFileSync(join(outside, 'target.md'), '外泄')
  try { symlinkSync(join(outside, 'target.md'), join(root, 'link.md')) } catch { /* 平台无权限=该腿退化为只验穿路径 */ }
  assert.equal((await listDocs(root, 'docs')).empty, false)
  const r = await readDoc(root, '../' + outside.split('/').pop() + '/target.md')
  assert.equal(r.empty, true)
  assert.match(r.reason, /\.\./)
})

/* ------------------------------------------------ 顺序执行 */

for (const [name, fn] of cases) {
  try {
    await fn()
    console.log(`  ok ${cases.indexOf([name, fn]) + 1 || ''} - ${name}`)
  } catch (e) {
    console.error(`FAIL - ${name}`)
    throw e
  }
}
console.log(`DOCS_HOST_TESTS ran=${cases.length} pass=${cases.length} fail=0`)
