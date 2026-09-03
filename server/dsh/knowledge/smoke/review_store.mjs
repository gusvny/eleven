#!/usr/bin/env node
/**
 * review_store.mjs —— server/dsh/knowledge/review_store.py 的冒烟（node 直跑，零依赖）。
 *
 * 用法：node smoke/review_store.mjs   （在 server/dsh/knowledge/ 下跑；或任意 cwd）
 *
 * 做法：mkdtemp 临时假仓库（docs/ + server/），SUYOU_REPO 指过去，spawn python3
 * review_store.py 各子命令，断言落盘格式与 node 侧 review-store.ts 同制式：
 *   docs/reviews/<path,/→__>.json  { path, rounds:[{base,ts,reviewer,conclude,blocks[]}] }
 * 全程不碰真 docs/。退出码 0=全绿。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, existsSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const CLI = join(HERE, '..', 'review_store.py')
const REPO = mkdtempSync(join(tmpdir(), 'suyou-review-store-'))
mkdirSync(join(REPO, 'docs'), { recursive: true })
mkdirSync(join(REPO, 'server'), { recursive: true })

let pass = 0, fail = 0
function check(name, cond, detail = '') {
  if (cond) { pass++; console.log('  ✓ ' + name) }
  else { fail++; console.log('  ✗ ' + name + (detail ? ' — ' + detail : '')) }
}
function run(args) {
  try {
    const out = execFileSync('python3', [CLI, ...args], {
      env: { ...process.env, SUYOU_REPO: REPO }, encoding: 'utf8',
    })
    return JSON.parse(out)
  } catch (e) {
    // 业务拒绝走 exit 1 + stdout JSON
    const out = (e.stdout || '').trim()
    if (out) { try { return JSON.parse(out) } catch { /* fallthrough */ } }
    return { ok: false, error: 'spawn 失败: ' + String(e.message || e).slice(0, 200) }
  }
}

// ---- 1) save 正常落盘（制式与 review-store.ts 同款）----
const saveArgs = {
  path: 'design/测试文档.md', base: 'HEAD', conclude: 'changes-requested',
  reviewer: 'proofreader', ticket: 't260821-m45-demo', stage: 'ai-review',
  blocks: [
    { block_key: 'h2:1:ab12', summary: '§1 标题', type: 'heading', status: 'modified',
      decision: 'reject', comment: '标题与正文不符' },
    { block_key: 'p:4:cd34', summary: '第 4 段', type: 'paragraph', status: 'added',
      decision: 'approve' },
    { block_key: 'doc:whole', summary: '整篇', type: 'doc', status: 'modified',
      decision: 'reject', comment: '结构需重排' },
  ],
}
let r = run(['save', JSON.stringify(saveArgs)])
check('save ok + run_id', r.ok === true && typeof r.result?.run_id === 'string' && r.result.run_id.length === 12)
check('save rounds=1', r.result?.rounds === 1)
const fp = join(REPO, 'docs', 'reviews', 'design__测试文档.md.json')
check('落盘文件名 / → __', existsSync(fp))
const disk = JSON.parse(readFileSync(fp, 'utf8'))
check('落盘制式 {path,rounds[]}', disk.path === 'design/测试文档.md' && Array.isArray(disk.rounds))
const rd = disk.rounds[0]
check('round 五键齐全', rd.base === 'HEAD' && typeof rd.ts === 'number'
  && rd.reviewer === 'proofreader' && rd.conclude === 'changes-requested'
  && rd.blocks.length === 3)
check('round 扩展键 ticket/stage 透传', rd.ticket === 't260821-m45-demo' && rd.stage === 'ai-review')
check('block 键形（block_key/summary/type/status/decision/comment）',
  rd.blocks[0].block_key === 'h2:1:ab12' && rd.blocks[0].decision === 'reject'
  && rd.blocks[0].comment === '标题与正文不符'
  && rd.blocks[1].decision === 'approve' && rd.blocks[1].comment === undefined)

// ---- 2) save 追加第二轮 ----
r = run(['save', JSON.stringify({ path: 'design/测试文档.md', conclude: 'in-progress', blocks: [] })])
check('save 追加第二轮（reviewer 缺省 agent）', r.ok && r.result.rounds === 2 && r.result.round.reviewer === 'agent')

// ---- 3) 白名单与校验 ----
r = run(['save', JSON.stringify({ path: '../escape.md', conclude: 'approved', blocks: [] })])
check('穿路径拒绝', r.ok === false && /path 不合法/.test(r.error || ''))
r = run(['save', JSON.stringify({ path: 'design/x.md', conclude: 'nope', blocks: [] })])
check('conclude 非法拒绝', r.ok === false && /conclude/.test(r.error || ''))
r = run(['save', JSON.stringify({ path: 'design/x.md', conclude: 'approved', blocks: [{ summary: '缺 key' }] })])
check('block 缺 block_key 拒绝', r.ok === false && /block_key/.test(r.error || ''))
r = run(['save', JSON.stringify({ path: 'design/x.md', base: '$(rm -rf /)', conclude: 'approved', blocks: [] })])
check('base 注入字符拒绝', r.ok === false && /base 不合法/.test(r.error || ''))

// ---- 4) show ----
r = run(['show', 'design/测试文档.md'])
check('show 读回 2 轮', r.ok && r.result.rounds.length === 2)
r = run(['show', 'design/不存在.md'])
check('show 不存在 → 空 rounds（非错误）', r.ok && r.result.rounds.length === 0)

// ---- 5) rework 一键复制指令 ----
r = run(['rework', 'design/测试文档.md'])
check('rework 取最后 changes-requested 轮（跳过第 2 轮 in-progress）',
  r.ok && r.result.round === 1 && r.result.rejects === 2)
const ins = r.result?.instruction || ''
check('指令含 reject 块明细', ins.includes('h2:1:ab12') && ins.includes('标题与正文不符'))
check('指令含存档路径', ins.includes('docs/reviews/design__测试文档.md.json'))
check('指令含一键复制 ticket rework 调用（ticket 取自轮次记录）',
  ins.includes('admin.py call ticket rework') && ins.includes('t260821-m45-demo'))

// ---- 6) admin.log 审计同形 ----
const log = readFileSync(join(REPO, 'server', 'admin.log'), 'utf8').trim().split('\n').map(JSON.parse)
check('审计 JSONL 同形（run_id/actor/name/ok）',
  log.length >= 5 && log.every(x => x.actor === 'knowledge-review' && x.name === 'review.save'
    && typeof x.run_id === 'string' && typeof x.ok === 'boolean'))
check('审计失败也留痕（path 不合法那条 ok=false）', log.some(x => x.ok === false))

console.log(`\n冒烟汇总：${pass + fail} 项，红 ${fail} 项（临时仓库 ${REPO}，可删）`)
process.exit(fail ? 1 : 0)
