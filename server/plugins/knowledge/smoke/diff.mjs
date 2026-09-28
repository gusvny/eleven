/**
 * smoke/diff.mjs —— sandbar-knowledge block diff / review 持久化 / 端点行为冒烟。
 *
 * 直跑：node smoke/diff.mjs（node ≥22.18 原生 type-stripping，直接 import .ts，
 * 无需编译）。覆盖：
 *   A. 纯函数（src/shared/blocks.ts）：
 *      1 无变化→全部未变  2 改一段→单块修改  3 标题改字→修改非删增
 *      4 列表项增删  5 表格行修改（其他行/表头未变）  6 新增块  7 key 跨插入稳定
 *   B. review 存读 round-trip（src/shared/review-store.ts，临时目录注入）
 *   C. 端点行为（node.ts apply + mock webServer/req/res + 临时 git 仓库）：
 *      /diff 未改文档 changed=false、base 坏字符 400、base 坏 ref 400、path 穿路径 404、
 *      base 下无文件 hasBase=false 全新增；/review GET 空→POST 存→GET 读回、
 *      坏 path 404、坏 conclude 400、GET 打 save 405；admin.log 审计留痕。
 */

import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { diffBlocks, parseBlocks } from '../src/shared/blocks.ts'
import { appendReviewRound, loadReview, reviewFilePath } from '../src/shared/review-store.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------------------------------------------------------- A. 纯函数 */

const DOC1 = `---
title: 测试文档
---

# 总标题

第一段正文，讲一件事。

## 小节甲

- 列表项一
- 列表项二

| 列A | 列B |
|---|---|
| a1 | b1 |
| a2 | b2 |

\`\`\`js
const x = 1
\`\`\`

## 小节乙

结尾段落。
`

section('A1 无变化 → 全部未变')
{
  const blocks = diffBlocks(DOC1, DOC1)
  ok(blocks.length > 0, `切出 ${blocks.length} 块`)
  ok(blocks.every(b => b.status === 'unchanged'), '全部 unchanged')
  ok(blocks.some(b => b.type === 'frontmatter'), 'frontmatter 独立块')
  ok(blocks.filter(b => b.type === 'list-item').length === 2, '列表项逐条独立块')
  ok(blocks.filter(b => b.type === 'table-row').length === 2, '表格数据行逐行独立块')
  ok(blocks.some(b => b.type === 'table-head'), '表头独立块')
  ok(blocks.some(b => b.type === 'code'), '围栏代码块整块')
}

section('A2 改一段 → 单块修改')
{
  const doc2 = DOC1.replace('第一段正文，讲一件事。', '第一段正文，讲一件更大的事。')
  const blocks = diffBlocks(DOC1, doc2)
  const mod = blocks.filter(b => b.status === 'modified')
  ok(mod.length === 1, `恰好 1 块修改（实际 ${mod.length}）`)
  ok(mod[0].type === 'paragraph', '改的是段落块')
  ok(Array.isArray(mod[0].ops) && mod[0].ops.some(o => o.k !== 'ctx'), '修改块带行级 ops')
  ok(blocks.filter(b => b.status === 'unchanged').every(b => b.ops === undefined), '未变块不带 ops（降噪）')
}

section('A3 标题改字 → 修改非删增')
{
  const doc2 = DOC1.replace('## 小节甲', '## 小节甲（修订）')
  const blocks = diffBlocks(DOC1, doc2)
  const heads = blocks.filter(b => b.type === 'heading')
  const mod = heads.filter(b => b.status === 'modified')
  ok(mod.length === 1, `标题对齐成 1 块修改（实际 modified=${mod.length}）`)
  ok(!heads.some(b => b.status === 'added' || b.status === 'removed'), '标题没有删+增')
  ok(mod[0].level === 2, '标题块带级别 H2')
}

section('A4 列表项增删')
{
  const doc2 = DOC1.replace('- 列表项二\n', '- 列表项二\n- 列表项三\n').replace('- 列表项一', '- 列表项一改')
  const blocks = diffBlocks(DOC1, doc2)
  const items = blocks.filter(b => b.type === 'list-item')
  ok(items.filter(b => b.status === 'added').length === 1, '新增 1 个列表项')
  ok(items.filter(b => b.status === 'modified').length === 1, '改 1 个列表项')
  ok(items.filter(b => b.status === 'unchanged').length === 1, '其余列表项未变')
  const doc3 = DOC1.replace('- 列表项二\n', '')
  const b3 = diffBlocks(DOC1, doc3).filter(b => b.type === 'list-item')
  ok(b3.filter(b => b.status === 'removed').length === 1, '删除 1 个列表项')
}

section('A5 表格行修改')
{
  const doc2 = DOC1.replace('| a2 | b2 |', '| a2 | b2改 |')
  const blocks = diffBlocks(DOC1, doc2)
  const rows = blocks.filter(b => b.type === 'table-row')
  ok(rows.filter(b => b.status === 'modified').length === 1, '恰好 1 数据行修改')
  ok(rows.filter(b => b.status === 'unchanged').length === 1, '另 1 数据行未变')
  ok(blocks.find(b => b.type === 'table-head')?.status === 'unchanged', '表头未变')
  const mod = rows.find(b => b.status === 'modified')
  ok(mod.oldText?.includes('b2') && mod.newText?.includes('b2改'), '修改行带新旧文本（供单元格级对齐）')
}

section('A6 新增块 / 删除块')
{
  const doc2 = DOC1 + '\n## 小节丙\n\n全新段落。\n'
  const blocks = diffBlocks(DOC1, doc2)
  const added = blocks.filter(b => b.status === 'added')
  ok(added.length === 2, `新增 2 块（标题+段落，实际 ${added.length}）`)
  ok(blocks.filter(b => b.status === 'removed').length === 0, '无删除')
  const b2 = diffBlocks(doc2, DOC1)
  ok(b2.filter(b => b.status === 'removed').length === 2, '反向=删除 2 块')
}

section('A7 稳定 key 跨插入不变')
{
  const doc2 = DOC1.replace('第一段正文，讲一件事。', '插入的新段落。\n\n第一段正文，讲一件事。')
  const k1 = parseBlocks(DOC1).map(b => b.key)
  const b2 = diffBlocks(DOC1, doc2)
  const unchanged = b2.filter(b => b.status === 'unchanged').map(b => b.key)
  ok(unchanged.every(k => k1.includes(k)), '未变块 key 与旧文档一致（内容哈希稳定）')
  ok(new Set(k1).size === k1.length, '同文档内 key 唯一')
}

/* ---------------------------------------------------------------- B. review 存读 round-trip */

section('B review 存读 round-trip（临时目录）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'kb-review-'))
  try {
    const docsDir = join(tmp, 'docs')
    const p = 'design/knowledge-base-design.md'
    ok(reviewFilePath(docsDir, p).endsWith(join('docs', 'reviews', 'design__knowledge-base-design.md.json')), '文件名 / → __ 映射')
    const empty = await loadReview(docsDir, p)
    ok(empty.rounds.length === 0, '未存过 → 空 rounds（非错误）')
    await appendReviewRound(docsDir, p, {
      base: 'HEAD', ts: 1787300000, reviewer: 'user', conclude: 'in-progress',
      blocks: [{ block_key: 'paragraph:abc123', summary: '第一段', type: 'paragraph', status: 'modified', decision: 'reject', comment: '这里要改' }],
    })
    await appendReviewRound(docsDir, p, {
      base: 'HEAD', ts: 1787300100, reviewer: 'user', conclude: 'approved', blocks: [],
    })
    const back = await loadReview(docsDir, p)
    ok(back.rounds.length === 2, '两轮都存读回')
    ok(back.rounds[0].blocks[0].block_key === 'paragraph:abc123' && back.rounds[0].blocks[0].comment === '这里要改', '块意见逐字段 round-trip')
    ok(back.rounds[1].conclude === 'approved', '整篇结论 round-trip')
    const raw = JSON.parse(await readFile(reviewFilePath(docsDir, p), 'utf8'))
    ok(raw.path === p && Array.isArray(raw.rounds), '落盘结构 {path, rounds[]}')
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

/* ---------------------------------------------------------------- C. 端点行为 */

section('C 端点行为（mock webServer + 临时 git 仓库）')
{
  const tmp = await mkdtemp(join(tmpdir(), 'kb-api-'))
  try {
    const docsDir = join(tmp, 'docs')
    await mkdir(join(docsDir, 'design'), { recursive: true })
    await mkdir(join(tmp, 'server'), { recursive: true })
    const docPath = join(docsDir, 'design', 'x.md')
    await writeFile(docPath, DOC1, 'utf8')
    const tmpReal = await realpath(tmp)
    const git = (args) => execFileSync('git', args, { cwd: tmpReal, stdio: ['ignore', 'pipe', 'pipe'] })
    git(['init', '-q'])
    git(['add', 'docs/design/x.md'])
    git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'init'])

    // mock ctx/webServer
    const routes = new Map()
    const ws = { register: ({ path, handler }) => { routes.set(path, handler); return () => routes.delete(path) } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo: tmpReal })
    // 多项目化（260823）后宿主路由必传 project 且经注册表解析主目录——
    // 临时注册表（SANDBAR_PROJECTS_YAML）指向本临时 repo，与 providers/routes-save 同款。
    const registry = join(tmp, 'projects.yaml')
    await writeFile(registry, `projects:\n  - key: smoketest\n    name: 冒烟\n    dirs:\n      - ${tmpReal}\n`, 'utf8')
    process.env.SANDBAR_PROJECTS_YAML = registry
    ok(routes.has('/sandbar-knowledge/api/diff'), '路由 /diff 已挂')
    ok(routes.has('/sandbar-knowledge/api/review'), '路由 /review 已挂')
    ok(routes.has('/sandbar-knowledge/api/review/save'), '路由 /review/save 已挂')

    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET', json) => ({
      url, method,
      async *[Symbol.asyncIterator]() { if (json !== undefined) yield Buffer.from(JSON.stringify(json)) },
    })
    const call = async (route, url, method, json) => {
      const res = mockRes()
      await routes.get(route)(mockReq(url, method, json), res)
      return res
    }

    // /diff：未改文档 → changed=false 且全部未变（基线 bug 验收）
    let r = await call('/sandbar-knowledge/api/diff', '/sandbar-knowledge/api/diff?project=smoketest&path=design/x.md&base=HEAD')
    ok(r.status === 200 && r.body.ok === true, 'GET /diff 200')
    ok(r.body.result.hasBase === true, 'hasBase=true（base 取到了）')
    ok(r.body.result.changed === false, '未改文档 changed=false')
    ok(r.body.result.blocks.every(b => b.status === 'unchanged'), '未改文档全部块未变')

    // 改一段 → changed=true
    await writeFile(docPath, DOC1.replace('第一段正文，讲一件事。', '第一段正文，讲一件更大的事。'), 'utf8')
    r = await call('/sandbar-knowledge/api/diff', '/sandbar-knowledge/api/diff?project=smoketest&path=design/x.md&base=HEAD')
    ok(r.body.result.changed === true, '改动后 changed=true')
    ok(r.body.result.blocks.filter(b => b.status === 'modified').length === 1, '单块修改')

    // 边界：path 穿路径 / base 坏字符 / base 坏 ref / 文档不存在
    r = await call('/sandbar-knowledge/api/diff', '/sandbar-knowledge/api/diff?project=smoketest&path=../CLAUDE.md&base=HEAD')
    ok(r.status === 404, 'path 越白名单 → 404')
    r = await call('/sandbar-knowledge/api/diff', `/sandbar-knowledge/api/diff?project=smoketest&path=design/x.md&base=${encodeURIComponent('HEAD; rm -rf')}`)
    ok(r.status === 400, 'base 坏字符 → 400')
    r = await call('/sandbar-knowledge/api/diff', '/sandbar-knowledge/api/diff?project=smoketest&path=design/x.md&base=deadbeef')
    ok(r.status === 400, 'base 坏 ref → 400')
    r = await call('/sandbar-knowledge/api/diff', '/sandbar-knowledge/api/diff?project=smoketest&path=design/none.md&base=HEAD')
    ok(r.status === 404, '文档不存在 → 404')
    // base 下无此文件（工作区有）→ hasBase=false 全新增
    await writeFile(join(docsDir, 'design', 'new.md'), '# 新文档\n\n内容。\n', 'utf8')
    r = await call('/sandbar-knowledge/api/diff', '/sandbar-knowledge/api/diff?project=smoketest&path=design/new.md&base=HEAD')
    ok(r.status === 200 && r.body.result.hasBase === false, 'base 下无文件 hasBase=false')
    ok(r.body.result.blocks.every(b => b.status === 'added'), '整篇按新增处理')

    // /review：空 → 存 → 读回
    r = await call('/sandbar-knowledge/api/review', '/sandbar-knowledge/api/review?project=smoketest&path=design/x.md')
    ok(r.status === 200 && r.body.result.rounds.length === 0, 'GET /review 空 rounds')
    r = await call('/sandbar-knowledge/api/review/save', '/sandbar-knowledge/api/review/save?project=smoketest', 'POST', {
      path: 'design/x.md', base: 'HEAD', conclude: 'changes-requested',
      blocks: [{ block_key: 'paragraph:xyz', summary: '第一段', type: 'paragraph', status: 'modified', decision: 'reject', comment: '重写' }],
    })
    ok(r.status === 200 && r.body.ok === true && typeof r.body.run_id === 'string' && r.body.run_id !== '', 'POST /review/save 200 + run-id')
    const saved = JSON.parse(await readFile(join(docsDir, 'reviews', 'design__x.md.json'), 'utf8'))
    ok(saved.rounds.length === 1 && saved.rounds[0].conclude === 'changes-requested', '落盘 docs/reviews/design__x.md.json')
    ok(saved.rounds[0].reviewer === 'user', 'reviewer 缺省 user')
    r = await call('/sandbar-knowledge/api/review', '/sandbar-knowledge/api/review?project=smoketest&path=design/x.md')
    ok(r.body.result.rounds.length === 1 && r.body.result.rounds[0].blocks[0].comment === '重写', 'GET /review 读回')

    // 审计：admin.log 留痕（run-id 对账）
    const log = await readFile(join(tmp, 'server', 'admin.log'), 'utf8')
    const recs = log.trim().split('\n').map(l => JSON.parse(l))
    ok(recs.some(rec => rec.name === 'review.save' && rec.ok === true && rec.actor === 'sandbar-knowledge'), 'admin.log 审计留痕')

    // 边界：坏 path / 坏 conclude / GET 打 save / 坏 JSON
    r = await call('/sandbar-knowledge/api/review/save', '/sandbar-knowledge/api/review/save?project=smoketest', 'POST', { path: '../x.md', base: 'HEAD', conclude: 'approved', blocks: [] })
    ok(r.status === 404, 'save 坏 path → 404')
    r = await call('/sandbar-knowledge/api/review/save', '/sandbar-knowledge/api/review/save?project=smoketest', 'POST', { path: 'design/x.md', base: 'HEAD', conclude: 'whatever', blocks: [] })
    ok(r.status === 400, 'save 坏 conclude → 400')
    r = await call('/sandbar-knowledge/api/review/save', '/sandbar-knowledge/api/review/save', 'GET')
    ok(r.status === 405, 'GET 打 save → 405')
    r = await call('/sandbar-knowledge/api/review', '/sandbar-knowledge/api/review?project=smoketest&path=../etc/passwd')
    ok(r.status === 404, 'review 坏 path → 404')
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
