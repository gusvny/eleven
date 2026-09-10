// t260910-10 「文档」视图客户端纯函数层 UT（docs-view-model.ts 真值表 + 畸形输入矩阵）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
// 被测=mock v1 UI 拆出的可判定逻辑：Search 过滤 / On this page 大纲提取 /
// Verified 占位判定 / Path chip / Project 选择器选项（synthesized 缺省项）。
import assert from 'node:assert/strict'
import {
  filterGroups, outlineFromHtml, verifiedChipValue, chipPath, projectOptions, HEADING_ID_PREFIX,
} from '../src/client/docs-view-model.ts'

let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${n} - ${name}`) }

const TREE = [
  { dir: '', label: 'root', files: [{ rel: 'README.md', title: 'Index' }, { rel: 'handbook.md', title: 'Handbook' }] },
  { dir: 'design', label: 'design', files: [{ rel: 'design/台面.md', title: '工单工作流台设计' }] },
]

/* ------------------------------------------------ Search 过滤 */

ok('filterGroups：title/rel 双字段子串命中（大小写不敏感），空组隐藏', () => {
  const r = filterGroups(TREE, 'hand')
  assert.deepEqual(r.map((g) => g.dir), [''])
  assert.deepEqual(r[0].files, [{ rel: 'handbook.md', title: 'Handbook' }])
  const zh = filterGroups(TREE, '台面') // rel 命中
  assert.equal(zh[0].files[0].rel, 'design/台面.md')
  const title = filterGroups(TREE, '工作流') // title 命中
  assert.equal(title[0].files[0].title, '工单工作流台设计')
  assert.equal(filterGroups(TREE, 'HANDBOOK').length, 1) // 大小写不敏感
})

ok('filterGroups：空串/纯空白/非字符串 query → 原树返回（不误伤）', () => {
  assert.deepEqual(filterGroups(TREE, ''), TREE)
  assert.deepEqual(filterGroups(TREE, '   '), TREE)
  assert.deepEqual(filterGroups(TREE, undefined), TREE)
  assert.deepEqual(filterGroups(TREE, 42), TREE)
})

ok('filterGroups：畸形树定值不炸（非数组/组缺 files/files 缺字段）', () => {
  assert.deepEqual(filterGroups(null, 'x'), [])
  assert.deepEqual(filterGroups('nope', 'x'), [])
  assert.deepEqual(filterGroups([{ dir: 'a', files: undefined }, { dir: 'b', files: [{ rel: 'x.md', title: 'X' }] }], 'x'),
    [{ dir: 'b', files: [{ rel: 'x.md', title: 'X' }] }])
  assert.deepEqual(filterGroups([{ dir: 'a', files: [{ title: '只有 title' }] }], '只有'), [{ dir: 'a', files: [{ title: '只有 title' }] }])
})

ok('filterGroups：全不命中 → 空数组（搜索无结果的合法终态）', () => {
  assert.deepEqual(filterGroups(TREE, '不存在的关键字'), [])
})

/* ------------------------------------------------ On this page 大纲提取 */

ok('outlineFromHtml：h2/h3 按 DOM 顺序提取，id=前缀+序号（与渲染后 DOM 赋 id 同序）', () => {
  const html = '<h2>快速上手</h2><p>第一段。</p><h3>前置条件</h3><p>第二段。</p><h2>常见问题</h2>'
  assert.deepEqual(outlineFromHtml(html), [
    { level: 2, text: '快速上手', id: `${HEADING_ID_PREFIX}0` },
    { level: 3, text: '前置条件', id: `${HEADING_ID_PREFIX}1` },
    { level: 2, text: '常见问题', id: `${HEADING_ID_PREFIX}2` },
  ])
})

ok('outlineFromHtml：h4/h1 不入大纲；标题内富文本剥标签+实体解码；空文本跳过', () => {
  const html = '<h1>篇名</h1><h2><em>强调</em> &amp; <code>代码</code></h2><h4>太深</h4><h3></h3><h3>   </h3><h2>尾题</h2>'
  assert.deepEqual(outlineFromHtml(html), [
    { level: 2, text: '强调 & 代码', id: `${HEADING_ID_PREFIX}0` },
    { level: 2, text: '尾题', id: `${HEADING_ID_PREFIX}1` },
  ])
})

ok('outlineFromHtml：畸形输入定值（非字符串/空串/无标题/未闭合标签不吞后续）', () => {
  assert.deepEqual(outlineFromHtml(''), [])
  assert.deepEqual(outlineFromHtml(undefined), [])
  assert.deepEqual(outlineFromHtml(42), [])
  assert.deepEqual(outlineFromHtml('<p>没有标题的正文</p>'), [])
  // 未闭合 h2 后的 h3 仍可提取（正则逐对匹配，不因一处畸形丢全纲）
  const partial = outlineFromHtml('<h2>未闭合<h3>后续</h3>')
  assert.equal(partial.some((e) => e.text === '后续'), true)
})

/* ------------------------------------------------ Verified chip 占位 */

ok('verifiedChipValue：真值透传；缺失/空/空白/非对象显式 pending 占位（不留假日期）', () => {
  assert.equal(verifiedChipValue({ verified: '2026-09-10' }), '2026-09-10')
  assert.equal(verifiedChipValue({ verified: '2026-08-01T02:03:04Z' }), '2026-08-01T02:03:04Z')
  assert.equal(verifiedChipValue({}), 'pending')
  assert.equal(verifiedChipValue({ verified: '' }), 'pending')
  assert.equal(verifiedChipValue({ verified: '   ' }), 'pending')
  assert.equal(verifiedChipValue(undefined), 'pending')
  assert.equal(verifiedChipValue(null), 'pending')
  assert.equal(verifiedChipValue('not-an-object'), 'pending')
  assert.equal(verifiedChipValue({ verified: 42 }), 'pending') // 非字符串=数据未就绪，不 String() 造值
})

/* ------------------------------------------------ Path chip */

ok('chipPath：scope 前缀 + rel 拼展示串', () => {
  assert.equal(chipPath('docs', 'design/x.md'), 'docs/design/x.md')
  assert.equal(chipPath('notes', 'README.md'), 'notes/README.md')
})

/* ------------------------------------------------ Project 选择器选项 */

ok('projectOptions：synthesized 缺省项恒在首（不依赖 registry 有 sandbar 条目，N4）', () => {
  const opts = projectOptions([{ key: 'docp', name: '文档夹具' }])
  assert.deepEqual(opts, [
    { key: '', label: 'sandbar / default' },
    { key: 'docp', label: '文档夹具 / docp' },
  ])
})

ok('projectOptions：name 缺省=重复回落 key；畸形条目跳过；非数组只有缺省项', () => {
  assert.deepEqual(projectOptions([{ key: 'k1' }, { key: 'k2', name: 'k2' }, { key: '', name: 'x' }, null, {}]), [
    { key: '', label: 'sandbar / default' },
    { key: 'k1', label: 'k1' },
    { key: 'k2', label: 'k2' },
  ])
  assert.deepEqual(projectOptions(undefined), [{ key: '', label: 'sandbar / default' }])
  assert.deepEqual(projectOptions('bad'), [{ key: '', label: 'sandbar / default' }])
})

console.log(`DOCS_VIEW_MODEL_TESTS ran=${n} pass=${n} fail=0`)
