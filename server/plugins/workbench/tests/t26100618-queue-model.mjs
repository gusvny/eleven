// t261006-18 CL-3 左栏工单顺序：queue-model 纯函数层 UT（真值表 + 畸形输入面）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
// 畸形输入纪律：消费外部数据（host 读脸 JSON），缺/畸形用例内联桩复现，不靠真外部源。
import assert from 'node:assert/strict'
import {
  parseConcFace, concFaceFromReply, orderKindOf, moveTicket, reorderMoveTo, permutationOf,
  stageDotsLit, faceCounts, STAGE_DOTS_TOTAL,
} from '../src/client/queue-model.ts'

let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${name}`) }

const FACE = {
  holders: [{ ticket: 't1', reason: 'running' }, { ticket: 't2', reason: 'human-hold' }],
  queue: [{ ticket: 't3', position: 1 }, { ticket: 't4', position: 2 }, { ticket: 't5', position: 3 }],
}

/* ------------------------------------------------ 读脸解析（畸形=具名 null，绝不编造顺序） */

ok('读脸解析：holders+queue 正常投影（queue 提 id，持额提 reason）', () => {
  const f = parseConcFace(FACE)
  assert.deepEqual(f, { holderReason: { t1: 'running', t2: 'human-hold' }, queue: ['t3', 't4', 't5'] })
})

ok('读脸解析：queue 条目纯 id 串也认（引擎回执两种形状兼容）', () => {
  assert.deepEqual(parseConcFace({ queue: ['a', 'b'] })?.queue, ['a', 'b'])
})

ok('读脸解析：空脸/缺 holders 键合法（新项目未记账=空脸非畸形）', () => {
  assert.deepEqual(parseConcFace({}), { holderReason: {}, queue: [] })
})

ok('读脸解析：非对象/数组/null → null', () => {
  assert.equal(parseConcFace(null), null)
  assert.equal(parseConcFace('x'), null)
  assert.equal(parseConcFace([]), null)
  assert.equal(parseConcFace(42), null)
})

ok('读脸解析：holders/queue 非数组 → null', () => {
  assert.equal(parseConcFace({ holders: 'x' }), null)
  assert.equal(parseConcFace({ queue: {} }), null)
})

ok('读脸解析：条目缺 ticket/空 id → null（不渲染半残假顺序）', () => {
  assert.equal(parseConcFace({ queue: [{ position: 1 }] }), null)
  assert.equal(parseConcFace({ queue: [{ ticket: '' }] }), null)
  assert.equal(parseConcFace({ holders: [{ reason: 'running' }] }), null)
})

ok('读脸解析：queue 重复 id → null（歧义顺序宁缺毋滥）', () => {
  assert.equal(parseConcFace({ queue: [{ ticket: 'a' }, { ticket: 'a' }] }), null)
})

/* ------------------------------------------------ 行分类（face 投影，行自身不判） */

ok('行分类：queued/atwork/hold/paused 各归位', () => {
  const f = parseConcFace(FACE)
  assert.equal(orderKindOf('t3', f), 'queued')
  assert.equal(orderKindOf('t1', f), 'atwork')
  assert.equal(orderKindOf('t2', f), 'hold')
  assert.equal(orderKindOf('t9', f, true), 'paused')
  assert.equal(orderKindOf('t9', f, false), undefined)
  assert.equal(orderKindOf('t9', f), undefined)
})

ok('行分类：脸 null（失败/畸形降级）→ 全 undefined（零顺序标记，不本地补算）', () => {
  for (const id of ['t1', 't3', 't9']) assert.equal(orderKindOf(id, null, true), undefined)
})

/* ------------------------------------------------ 移动（±1 与拖到指定行） */

ok('moveTicket：±1 交换；到队首/队尾越界 → null', () => {
  const q = ['a', 'b', 'c']
  assert.deepEqual(moveTicket(q, 'b', -1), ['b', 'a', 'c'])
  assert.deepEqual(moveTicket(q, 'b', 1), ['a', 'c', 'b'])
  assert.equal(moveTicket(q, 'a', -1), null)
  assert.equal(moveTicket(q, 'c', 1), null)
})

ok('moveTicket：id 不在队列/非法方向 → null（排队行之外零移动）', () => {
  assert.equal(moveTicket(['a'], 'x', -1), null)
  assert.equal(moveTicket(['a'], 'a', 0), null)
  assert.equal(moveTicket(['a'], 'a', 2), null)
})

ok('reorderMoveTo：拖 A 落 B 位；同位/缺席 → null', () => {
  assert.deepEqual(reorderMoveTo(['a', 'b', 'c'], 'a', 'c'), ['b', 'c', 'a'])
  assert.deepEqual(reorderMoveTo(['a', 'b', 'c'], 'c', 'a'), ['c', 'a', 'b'])
  assert.equal(reorderMoveTo(['a', 'b'], 'a', 'a'), null)
  assert.equal(reorderMoveTo(['a', 'b'], 'x', 'a'), null)
})

ok('moveTicket/reorderMoveTo 不改入参（零本地顺序状态的前半：纯函数）', () => {
  const q = ['a', 'b', 'c']
  moveTicket(q, 'a', 1); reorderMoveTo(q, 'a', 'c')
  assert.deepEqual(q, ['a', 'b', 'c'])
})

/* ------------------------------------------------ 排列守卫（POST body 前的客户端镜像闸） */

ok('permutationOf：同元素异序=排列（含恒等序）；形状合法即原样返回', () => {
  assert.deepEqual(permutationOf(['a', 'b', 'c'], ['c', 'a', 'b']), ['c', 'a', 'b'])
  assert.deepEqual(permutationOf(['a', 'b'], ['a', 'b']), ['a', 'b'])
})

ok('permutationOf：丢票/添票/重复/非串 → null（引擎 reorder 同判的客户端镜像）', () => {
  assert.equal(permutationOf(['a', 'b', 'c'], ['a', 'b']), null)
  assert.equal(permutationOf(['a', 'b'], ['a', 'b', 'c']), null)
  assert.equal(permutationOf(['a', 'b'], ['a', 'a']), null)
  assert.equal(permutationOf(['a'], [1]), null)
  assert.equal(permutationOf(['a'], 'a'), null)
})

/* ------------------------------------------------ 十段进展点（§7.2 默认 dots） */

ok('stageDotsLit：0 基段序 → 亮到当前段；封顶 10；未知段=0', () => {
  assert.equal(stageDotsLit(0), 1)
  assert.equal(stageDotsLit(3), 4)
  assert.equal(stageDotsLit(9), 10)
  assert.equal(stageDotsLit(11), STAGE_DOTS_TOTAL)
  assert.equal(stageDotsLit(-1), 0)
  assert.equal(stageDotsLit(1.5), 0)
  assert.equal(stageDotsLit(Number.NaN), 0)
})

ok('stageDotsLit：收口票全亮（closed=true 压过段序）', () => {
  assert.equal(stageDotsLit(0, true), 10)
  assert.equal(stageDotsLit(-1, true), 10)
})

/* ------------------------------------------------ 回执解包（两种合法形状 + 拒收） */

ok('concFaceFromReply：host 包裹 {ok:true,result} 与裸 read_state 都解出；其余=null', () => {
  assert.deepEqual(concFaceFromReply({ ok: true, result: FACE }), FACE)
  assert.deepEqual(concFaceFromReply(FACE), FACE)
  assert.equal(concFaceFromReply({ ok: false, error: 'x' }), null)
  assert.equal(concFaceFromReply({ ok: true }), null) // ok 壳无 result：不猜脸
  assert.equal(concFaceFromReply(null), null)
  assert.equal(concFaceFromReply('x'), null)
})

/* ------------------------------------------------ 项目行两个数（只报数不写句子） */

ok('faceCounts：atWork=holders 数、waiting=queue 数；脸 null=双 0 不乱报', () => {
  const f = parseConcFace(FACE)
  assert.deepEqual(faceCounts(f), { atWork: 2, waiting: 3 })
  assert.deepEqual(faceCounts(null), { atWork: 0, waiting: 0 })
})

console.log(`t26100618-queue-model ran=${n} pass=${n} fail=0`)
