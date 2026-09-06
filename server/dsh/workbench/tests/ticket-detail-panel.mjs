/**
 * tests/ticket-detail-panel.mjs —— 工单详情面板与首句标题纯函数（t260905-07）。
 *
 * 直跑：node server/dsh/workbench/tests/ticket-detail-panel.mjs
 * 覆盖：
 *   A. firstSentenceOf（ticket-list-model.ts）：首句裁剪口径（句读/无句读/markdown
 *      剥头/超长截断/空正文/畸形不抛）——列表 enrichment 与详情头部共用的单一事实。
 *   B. ticketDisplayTitle：展示选择 title → title_or_first → id（裸编号=最后兜底）。
 *   C. deriveTitleOrFirst（src/host/enrich.ts，host enrichment 口径，review 附条件3）：
 *      title 非空跳过裁剪；show 失败/body 非字符串/裁不出 → 字段缺省。
 *   D. snapshotDigest：阶段时间线（**KI-019 乱序呈现口径：按 at 升序归位、缺 at
 *      沉底带 untime 标注**——乱序注入用例钉死）、最近交接尾 5、门与签字记录合并
 *      降序、工作流快照要点；畸形输入（timeline 非数组/条目畸形/全空/非对象）不抛。
 * 全程纯函数直跑，不碰 3099、不起 console。
 */

import { firstSentenceOf, ticketDisplayTitle, snapshotDigest } from './../src/client/ticket-list-model.ts'
import { deriveTitleOrFirst } from './../src/host/enrich.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ── A. firstSentenceOf ─────────────────────────────────────── */
ok(firstSentenceOf('做什么：①工单详情。②横幅。后续') === '做什么：①工单详情。',
  'A: 首句在句号处截断')
ok(firstSentenceOf('没有句读的一整行') === '没有句读的一整行', 'A: 无句读取整行')
ok(firstSentenceOf('英文? yes! done') === '英文?', 'A: 半角句读同样截断')
ok(firstSentenceOf('## 标题行\n正文第二行。别的') === '标题行', 'A: markdown 剥头（#/空格）')
ok(firstSentenceOf('> 引用行。后续') === '引用行。', 'A: markdown 剥头（>）')
ok(firstSentenceOf('- 列表项！后续') === '列表项！', 'A: markdown 剥头（-）')
{
  const long = '一'.repeat(60) + '。后续'
  const got = firstSentenceOf(long)
  ok(got !== null && [...got].length === 49 && got.endsWith('…'), 'A: 超长截断 48 字+省略号')
}
ok(firstSentenceOf('   \n\n  \n') === null, 'A: 全空白正文 → null（字段缺省，不造脏数据）')
ok(firstSentenceOf('###\n---\n') === null, 'A: 全是标记行 → null')
ok(firstSentenceOf(undefined) === null && firstSentenceOf(null) === null
  && firstSentenceOf(42) === null && firstSentenceOf({}) === null,
  'A: 畸形输入（缺失/数字/对象）→ null 不抛')
ok(firstSentenceOf('没有句读的一整行超长' + '一'.repeat(60)) === null || true, 'A: 边界不抛')

/* ── B. ticketDisplayTitle ──────────────────────────────────── */
ok(ticketDisplayTitle({ id: 't260903-10', title: '有标题' }) === '有标题', 'B: title 优先')
ok(ticketDisplayTitle({ id: 't260903-10', title: '   ', title_or_first: '首句话。后续' }) === '首句话。后续',
  'B: title 空白 → title_or_first（t260903-10 裸编号现场根治面）')
ok(ticketDisplayTitle({ id: 't260903-10' }) === 't260903-10', 'B: 两字段全缺 → 裸编号（最后兜底）')
ok(ticketDisplayTitle({ id: 't260903-10', title: '', title_or_first: '  ' }) === 't260903-10',
  'B: title_or_first 空白 → 裸编号（不显空白）')

/* ── C. deriveTitleOrFirst（host enrichment 口径） ──────────── */
ok(deriveTitleOrFirst({ id: 'x', title: '有标题' }, { body: '正文。' }) === undefined,
  'C: title 非空 → 跳过裁剪（字段不下发，review 附条件3 钉死口径）')
ok(deriveTitleOrFirst({ id: 'x', title: '' }, { body: '无标题票正文首句。后续' }) === '无标题票正文首句。',
  'C: title 空 → 从 show body 裁首句下发')
ok(deriveTitleOrFirst({ id: 'x' }, { body: '缺 title 字段也裁。' }) === '缺 title 字段也裁。',
  'C: title 缺省 → 裁首句')
ok(deriveTitleOrFirst({ id: 'x', title: '' }, undefined) === undefined, 'C: show 失败（undefined）→ 字段缺省')
ok(deriveTitleOrFirst({ id: 'x', title: '' }, null) === undefined, 'C: show null → 字段缺省')
ok(deriveTitleOrFirst({ id: 'x', title: '' }, { body: 42 }) === undefined, 'C: body 非字符串 → 字段缺省')
ok(deriveTitleOrFirst({ id: 'x', title: '' }, { body: '   ' }) === undefined, 'C: body 全空白裁不出 → 字段缺省')
ok(deriveTitleOrFirst(null, { body: 'x' }) === undefined, 'C: row 畸形 → 字段缺省不抛')

/* ── D. snapshotDigest ─────────────────────────────────────── */

// KI-019 乱序注入用例：乱序到达的时间线被按 at 归位；缺 at 条目沉底带标注。
{
  const d = snapshotDigest({
    id: 't1', status: 'running', stage: 's2', stage_state: 'running', revision_count: 2,
    timeline: [
      { stage: 's3', state: 'running', at: 300 },
      { stage: 's1', state: 'done', at: 100 },
      { stage: 's2', state: 'running', at: 200 },
      { stage: 'sX', state: 'running' },            // 缺 at → 沉底 untime
      { stage: 'sY', state: 'blocked', at: 'not-a-number' }, // at 畸形 → 沉底 untime
      'junk',                                        // 条目畸形 → 跳过
    ],
  })
  ok(d.timeline.length === 5, 'D: 乱序注入——合法条目全保留（畸形条目剔除）')
  ok(d.timeline[0].stage === 's1' && d.timeline[1].stage === 's2' && d.timeline[2].stage === 's3',
    'D: KI-019 呈现口径——乱序到达按 at 升序归位（钉死排序，非原样呈现）')
  ok(d.timeline[3].untime === true && d.timeline[4].untime === true
    && d.timeline[3].at === null && d.timeline[4].at === null,
    'D: 缺 at/畸形 at 条目沉底并带 untime 标注（失真面显性化，不静默混排）')
  ok(d.workflow.id === 't1' && d.workflow.stage === 's2' && d.workflow.revisions === 2,
    'D: 工作流快照要点字段面（id/当前段/修订）')
}

// 最近交接：尾部 5 条、顺序从新到旧。
{
  const handoffs = Array.from({ length: 8 }, (_, i) => ({ from: `a${i}`, to: `a${i + 1}`, at: `t${i}` }))
  const d = snapshotDigest({ handoffs })
  ok(d.handoffs.length === 5, 'D: 最近交接裁尾 5 条')
  ok(d.handoffs[0].from === 'a7' && d.handoffs[4].from === 'a3',
    'D: 最近交接最近在前（尾部从新到旧）')
}

// 门与签字记录合并、按时间降序、畸形条目跳过。
{
  const d = snapshotDigest({
    gate_runs: [
      { stage: 'gate1', kind: 'script', status: 'green', at: '100' },
      { stage: 'gate2', kind: 'script', status: 'red', at: '300' },
      'junk',
    ],
    signatures: {
      create: { who: 'host', decision: 'approve', note: '立项签', at: '200' },
      merge: { who: 'integration', decision: 'approve', note: '收口签', at: 'junk' },
      bad: 42,
    },
  })
  ok(d.gates.length === 4, 'D: 门与签字记录合并（畸形条目剔除）')
  ok(d.gates[0].stage === 'gate2' && d.gates[1].stage === 'create' && d.gates[2].stage === 'gate1',
    'D: 记录按 at 降序（最近在前），at 畸形沉底')
  ok(d.gates[1].kind === 'signature' && d.gates[0].kind === 'gate',
    'D: 门/签字 kind 保留（UI 按 kind 区分徽标）')
  ok(d.gates[3].stage === 'merge' && d.gates[3].at === 'junk', 'D: at 非数值串原样保留且沉底（不猜不丢）')
}

// 畸形输入全家族不抛 + 空形状。
{
  const empties = [undefined, null, 42, 'str', {}, [], { timeline: 'x' }, { timeline: [null, 1, {}] },
    { handoffs: 'x' }, { gate_runs: 'x' }, { signatures: [] }, { signatures: { s: 1 } }]
  let threw = false
  let allEmpty = true
  for (const e of empties) {
    try {
      const d = snapshotDigest(e)
      if (!Array.isArray(d.timeline) || !Array.isArray(d.handoffs) || !Array.isArray(d.gates)
        || typeof d.workflow !== 'object') allEmpty = false
    } catch { threw = true }
  }
  ok(!threw && allEmpty, 'D: 畸形输入全家族不抛、空形状兜底')
}

console.log(`\nSUMMARY pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
