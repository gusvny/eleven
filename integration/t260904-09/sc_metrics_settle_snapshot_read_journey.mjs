#!/usr/bin/env node
/**
 * sc_metrics_settle_snapshot_read_journey.mjs —— t260904-09 metrics 读侧 L3 旅程场景（灰盒）。
 *
 * intent（用户可感知）：工单收口后，面板的交付/token 数字来自 settle 时刻冻结的
 * 快照（不再随后读侧实现/泳道拆除而抖动）；无快照的存量票，归档口径只认 message
 * 以票号开头的 squash 收口提交（他账剔除）；「未交付（在制）」与「不可算（数据
 * 缺失）」两语义在 donut 里不混；快照文件畸形时不炸面板。
 *
 * 断言面（锚 /metrics 响应契约：图表数值、reason、donut 分桶；不绑记录内部字段）：
 *  R0 夹具自检：stub 冷跑出响应（夹具纪律=让实现自己写缓存，再篡改）。
 *  R1 快照优先级（默认根链 cacheRoot/demo/data/settle）：有快照的票交付=快照值
 *     （101+9）、token=快照值（500+120）——对照组：该票无 git 提交，快照不生效即不可算。
 *  R2 归档口径收窄（真 git fixture 仓）：票号前缀 squash 提交 +12 与引用性提及
 *     他账 +50 并存 → 面板交付=12（非 62），reason 标归档口径。
 *  R3 口径变更可达性（05 锚同构，KI 上报面）：篡改存量缓存为 v1 宽口径 →
 *     重开面板重算回收窄值（source_version 失配=整条作废重算，宽口径不永续）。
 *  R4 donut 四桶：有变更/已收口·零变更/未交付（在制）/不可算（数据缺失）互斥
 *     且 Σ=票数；零变更已闭票不落「不可算」。
 *  R5 快照畸形：坏 JSON 快照 → 面板不炸、该票走回落口径并留人话 reason。
 *  R6 SANDBAR_SETTLE_SNAPSHOT_DIR 覆盖根：env 指向的替代目录被读侧消费。
 *
 * 与既有资产 intent 区别：t260904-04-stale-cache-heal-journey 守「失败维/open 陈旧
 * 自愈」两拍旅程；t260903-13-metrics-golden-freeze 守响应形状冻结；workbench/tests
 * delivery-recovery（L1）守记录内部机制；本场景守「settle 快照成为数字真源」的
 * 消费契约与口径收窄/四桶语义。
 * 预期状态：实现段落地前 R1~R6 红属预期（TDD 信号），R0 绿（夹具自检）；
 * arbitrate/merge 期必须全绿。
 * Run: node integration/t260904-09/sc_metrics_settle_snapshot_read_journey.mjs（cwd=仓库根）
 */
import { writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import {
  NOW, WORKFLOWS, ticketRow, withStub, callMetrics, findCacheFile, findSpecs,
  gitInit, commitFile, git, freshTmp, rmRf, makeChecker,
} from '../t260903-09/lib_integration.mjs'

const { ok, done } = makeChecker()

/** 快照文件（跨组件公开契约形状，写侧由 sc_settle_snapshot_write_journey 守真）。 */
function snapshotJson(id, { add = 0, del = 0, zero = false, tokens = null } = {}) {
  return JSON.stringify({
    schema_version: 'v1',
    ticket_id: id,
    project_key: 'demo',
    squash_commit: zero ? 'aaaa111' : 'bbb2222',
    settled_at: new Date(NOW).toISOString(),
    tokens: tokens ?? { in: 0, out: 0, cacheRead: 0, by_stage: {}, by_model: {}, by_stage_available: false, tokens_zero: zero },
    delivery: { base: 'ccc3333', add, del, commits: zero ? 0 : 1, squash_commit: zero ? 'aaaa111' : 'bbb2222', zero_change: zero },
  })
}

async function putSnapshot(root, id, opts) {
  const dir = join(root, 'demo', 'data', 'settle')
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, `${id}.json`), snapshotJson(id, opts), 'utf8')
}

/** delivery 视图 Top 票里某票的 add+del 值（无则 undefined）。 */
function topDeliveryValue(resp, id) {
  const body = resp?.body ?? resp
  const specs = findSpecs(body, 'Top 票变更量')
  for (const s of specs) {
    const i = (s.categories ?? []).indexOf(id)
    if (i >= 0) return s.series?.[0]?.data?.[i]
  }
  return undefined
}

/** token 视图 Top 票里某票的 in+out 值（无则 undefined）。 */
function topTokenValue(resp, id) {
  const body = resp?.body ?? resp
  const specs = findSpecs(body, 'Top 票 token 消耗')
  for (const s of specs) {
    const i = (s.categories ?? []).indexOf(id)
    if (i >= 0) return s.series?.[0]?.data?.[i]
  }
  return undefined
}

function reasonSegment(resp, id) {
  const body = resp?.body ?? resp
  return String(body?.reason ?? '').split('；').find((s) => s.startsWith(`${id}: `)) ?? ''
}

async function withEnv(key, value, fn) {
  const saved = process.env[key]
  if (value === undefined) delete process.env[key]
  else process.env[key] = value
  try { return await fn() } finally {
    if (saved === undefined) delete process.env[key]
    else process.env[key] = saved
  }
}

async function main() {
  // R0 夹具自检（无快照世界，现算通路仍自洽）
  await withStub({ tickets: [ticketRow('t260904-09r0', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 })], workflows: WORKFLOWS, deliveries: {} }, async (ctx) => {
    const resp = await callMetrics(ctx.deps, { view: 'delivery' })
    const body = resp?.body ?? resp
    ok(body && body.kpis && typeof body.reason === 'string', 'R0 夹具自检：冷跑出响应', JSON.stringify(body?.kpis ?? body)?.slice(0, 120))
  })

  // R1 快照优先级（默认根链）
  await withStub({ tickets: [ticketRow('t260904-09r1', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 })], workflows: WORKFLOWS, deliveries: {} }, async (ctx) => {
    await putSnapshot(ctx.cacheRoot, 't260904-09r1', { add: 101, del: 9, tokens: { in: 500, out: 120, cacheRead: 30, by_stage: {}, by_model: { 'prov/m': 620 }, by_stage_available: false, tokens_zero: false } })
    const dv = await callMetrics(ctx.deps, { view: 'delivery' })
    ok(topDeliveryValue(dv, 't260904-09r1') === 110, 'R1 交付=快照值（101+9；该票无 git 提交，快照不生效即不可算）', `top=${topDeliveryValue(dv, 't260904-09r1')}`)
    const tv = await callMetrics(ctx.deps, { view: 'token' })
    ok(topTokenValue(tv, 't260904-09r1') === 620, 'R1 token=快照值（500+120）', `top=${topTokenValue(tv, 't260904-09r1')}`)
  })

  // R2+R3 归档收窄与口径变更可达性（真 git fixture 仓）
  const repo = await freshTmp('t260904-09-repo')
  try {
    await gitInit(repo)
    await commitFile(repo, 'base.txt', 1, 'init', 'base')
    await commitFile(repo, 'code.txt', 12, 't260904-09ra squash 收口（一单一提交）', 'code')   // 真身 +12
    await commitFile(repo, 'notes.txt', 50, `讨论档（引用 t260904-09ra 教训）`, 'note')          // 他账 +50（message 引用性提及，票号不居首）
    await withStub({ tickets: [ticketRow('t260904-09ra', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 })], workflows: WORKFLOWS, deliveries: {} }, async (ctx) => {
      ctx.deps.git = (cwd, args) => git(repo, args)   // git 真源指向 fixture 仓（rows 仍走 stub）
      const dv = await callMetrics(ctx.deps, { view: 'delivery' })
      ok(topDeliveryValue(dv, 't260904-09ra') === 12, 'R2 归档收窄：只认票号前缀 squash（12 非 62）', `top=${topDeliveryValue(dv, 't260904-09ra')}`)
      const seg = reasonSegment(dv, 't260904-09ra')
      ok(seg.includes('归档'), 'R2 reason 标归档口径', seg.slice(0, 120))

      // R3 口径变更可达性：存量缓存钉在宽口径（v1）→ 重开面板必须重算回收窄值
      const cacheFile = await findCacheFile(ctx.cacheRoot, 't260904-09ra')
      ok(!!cacheFile, 'R3 前置：冷跑已落盘缓存')
      if (cacheFile) {
        const rec = JSON.parse(await (await import('node:fs/promises')).readFile(cacheFile, 'utf8'))
        rec.source_version = 'v1'
        rec.delivery = { ...rec.delivery, add: 50, del: 0, commits: 2 }
        await writeFile(cacheFile, JSON.stringify(rec), 'utf8')
        const dv2 = await callMetrics(ctx.deps, { view: 'delivery' })
        ok(topDeliveryValue(dv2, 't260904-09ra') === 12, 'R3 v1 宽口径存量被重算治愈（05 锚同构：宽口径不永续）', `top=${topDeliveryValue(dv2, 't260904-09ra')}`)
      }
    })
  } finally {
    await rmRf(repo)
  }

  // R4 donut 四桶（互斥且 Σ=票数；零变更已闭票不落「不可算」）
  await withStub({
    tickets: [
      ticketRow('t260904-09rc', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 }),              // 有变更（真 git squash +2）
      ticketRow('t260904-09rz', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 }),              // 已收口·零变更（快照 zero_change）
      ticketRow('t260904-09ro', { createdAt: NOW - 3600e3, closedAt: null }),                    // 未交付（在制）
      ticketRow('t260904-09rn', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 }),              // 不可算（数据缺失）
    ],
    workflows: WORKFLOWS, deliveries: {},
  }, async (ctx) => {
    const repo2 = await freshTmp('t260904-09-repo2')
    try {
      await gitInit(repo2)
      await commitFile(repo2, 'b.txt', 1, 'init', 'b')
      await commitFile(repo2, 'c.txt', 2, 't260904-09rc squash 收口（一单一提交）', 'c')
      ctx.deps.git = (cwd, args) => git(repo2, args)
      await putSnapshot(ctx.cacheRoot, 't260904-09rz', { zero: true })
      const dv = await callMetrics(ctx.deps, { view: 'delivery' })
      const specs = findSpecs(dv, '有无代码变更')
      ok(specs.length > 0, 'R4 donut 在场')
      const s = specs[0]
      const cats = s?.categories ?? []
      const data = s?.series?.[0]?.data ?? []
      const sum = data.reduce((a, b) => a + (b ?? 0), 0)
      ok(cats.length === 4 && sum === 4, 'R4 四桶互斥且 Σ=票数', `cats=${JSON.stringify(cats)} data=${JSON.stringify(data)}`)
      const pick = (kw) => { const i = cats.findIndex((c) => String(c).includes(kw)); return i >= 0 ? data[i] : undefined }
      ok(pick('零变更') === 1, 'R4 已收口·零变更桶恰 1（零变更闭票不落不可算）', `pick=${pick('零变更')}`)
      ok(pick('不可算') === 1, 'R4 不可算（数据缺失）桶恰 1', `pick=${pick('不可算')}`)
      ok(pick('在制') === 1, 'R4 未交付（在制）桶恰 1', `pick=${pick('在制')}`)
      ok(pick('有变更') === 1, 'R4 有变更桶恰 1', `pick=${pick('有变更')}`)
    } finally {
      await rmRf(repo2)
    }
  })

  // R5 快照畸形降级
  await withStub({ tickets: [ticketRow('t260904-09rb', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 })], workflows: WORKFLOWS, deliveries: {} }, async (ctx) => {
    const dir = join(ctx.cacheRoot, 'demo', 'data', 'settle')
    await mkdir(dir, { recursive: true })
    await writeFile(join(dir, 't260904-09rb.json'), '{oops not json', 'utf8')
    const dv = await callMetrics(ctx.deps, { view: 'delivery' })
    ok(dv && (dv.body ?? dv).kpis, 'R5 坏 JSON 快照不炸面板')
    const seg = reasonSegment(dv, 't260904-09rb')
    ok(seg !== '', 'R5 坏快照票留人话 reason（回落口径/不可算，不静默）', seg.slice(0, 120))
    ok(topDeliveryValue(dv, 't260904-09rb') === undefined, 'R5 坏快照不当真源（数字不出现）', `top=${topDeliveryValue(dv, 't260904-09rb')}`)
  })

  // R6 SANDBAR_SETTLE_SNAPSHOT_DIR 覆盖根
  const alt = await freshTmp('t260904-09-alt')
  try {
    await withStub({ tickets: [ticketRow('t260904-09rv', { createdAt: NOW - 3600e3, closedAt: NOW - 60e3 })], workflows: WORKFLOWS, deliveries: {} }, async (ctx) => {
      // 方案意见 6 钉死语义：env 替换项目根整体 → 快照在 <env>/<key>/data/settle/。
      const dir = join(alt, 'demo', 'data', 'settle')
      await mkdir(dir, { recursive: true })
      await writeFile(join(dir, 't260904-09rv.json'), snapshotJson('t260904-09rv', { add: 7, del: 1 }), 'utf8')
      await withEnv('SANDBAR_SETTLE_SNAPSHOT_DIR', alt, async () => {
        const dv = await callMetrics(ctx.deps, { view: 'delivery' })
        ok(topDeliveryValue(dv, 't260904-09rv') === 8, 'R6 env 覆盖根被消费（7+1）', `top=${topDeliveryValue(dv, 't260904-09rv')}`)
      })
    })
  } finally {
    await rmRf(alt)
  }

  process.exit(done())
}

main().catch((e) => {
  console.error('FAIL 场景异常：', e?.stack ?? e)
  console.log('SUMMARY pass=0 skip=0 fail=1')
  process.exit(1)
})
