// t260908-01 段间暂停 UI 纯函数层 UT（pauseOpOf/pausedBadgeText 真值表 + 行卡/host 源码锁）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。零网络/零 console。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pauseOpOf, pausedBadgeText } from '../src/client/ticket-list-model.ts'

const repo = resolveRepo()
function resolveRepo() {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
}
let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${name}`) }

/* ------------------------------------------------ pauseOpOf 真值表（含畸形行） */

ok('pauseOpOf：未暂停→pause / 已暂停→resume', () => {
  assert.equal(pauseOpOf(false), 'pause')
  assert.equal(pauseOpOf(true), 'resume')
})

ok('pauseOpOf：畸形输入不 throw 且按真值性归位（undefined→pause、真值→resume）', () => {
  assert.equal(pauseOpOf(undefined), 'pause')
  assert.equal(pauseOpOf(null), 'pause')
  assert.equal(pauseOpOf(''), 'pause')
  assert.equal(pauseOpOf(1), 'resume')
  assert.equal(pauseOpOf('true'), 'resume')
})

/* ------------------------------------------------ pausedBadgeText 二态文案
   t261011-19：徽标图标化后，行面只留 ⏸ 单字形；二态文案只活在 title/aria。
   断言改钉「锚点 + 词语义」不钉逐字 copy（宿主令：never the copy）——
   两相位可辨、未知相位兜底到 pending 语义、词带 ⏸ 字形。 */

ok('pausedBadgeText：两相位语义可辨，未知/畸形相位兜底到 pending 语义', () => {
  const gate = pausedBadgeText('at_gate')
  const pending = pausedBadgeText('pending')
  assert.notEqual(gate, pending, '两相位文案可辨（不钉逐字 copy）')
  assert.equal(pausedBadgeText(undefined), pending, '未知相位兜底=保守 pending 语义')
  assert.equal(pausedBadgeText('some_future_phase'), pending)
  assert.equal(pausedBadgeText(''), pending)
  assert.ok(gate.startsWith('⏸') && pending.startsWith('⏸'), '词带暂停字形（icon 同源）')
})

/* ------------------------------------------------ 源码锁（防消费面漂移） */

ok('行卡源码锁：暂停徽标 data 锚点 + pause/resume 操作位 + busy 纪律', () => {
  const card = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
  assert.ok(card.includes("data-paused=\"1\""), '徽标 data-paused 锚点')
  assert.ok(card.includes("data-paused-phase="), '徽标 data-paused-phase 锚点')
  // t261011-19：compact 行面只留 ⏸ 字形；词走 aria-label/title，不逐字钉 copy。
  const compactIcon = card.slice(card.indexOf('const pauseIcon'), card.indexOf('const ctlSpan'))
  assert.ok(compactIcon.includes("role=\"img\""), 'compact 暂停徽标 role=img')
  assert.ok(compactIcon.includes('aria-label={pausedBadgeText(t.paused_phase)}'), '词进 aria-label')
  assert.ok(compactIcon.includes("'Halted at the stage gate") || compactIcon.includes('title={t.paused_phase'),
    'title 承载二态语境')
  assert.ok(compactIcon.includes('⏸'), '行面字形=⏸')
  assert.ok(!/\n\s*Paused at the stage gate'?\s*\}/.test(compactIcon) || !compactIcon.includes('>\n            ⏸ Paused'),
    '行面不渲染整句 copy')
  assert.ok(card.includes("'pause' | 'resume'"), 'CardOp 键集含 pause/resume')
  assert.ok(card.includes("ops.includes('pause')") && card.includes("ops.includes('resume')"),
    'pause/resume 操作位渲染分支')
  // busy 连点防线（同族纪律）：两钮均 disabled={busy}
  const pauseBtn = card.slice(card.indexOf("ops.includes('pause')"))
  const resumeBtn = card.slice(card.indexOf("ops.includes('resume')"))
  assert.ok(pauseBtn.includes('disabled={busy}') && resumeBtn.includes('disabled={busy}'),
    'pause/resume 钮 busy 禁用')
})

ok('index.tsx 源码锁：availableOps 走 pauseOpOf 纯函数层 + 行卡装配 onPause/onResume', () => {
  const idx = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  assert.ok(idx.includes('v2ops.push(pauseOpOf(t.paused))'), 'availableOps 消费 pauseOpOf')
  // t261005-10 (UI-2)：操作位随行卡迁入详情 More 区——装配点改锁详情面。
  assert.ok(idx.includes("doOp(detail.id, 'pause',") && idx.includes("doOp(detail.id, 'resume',"),
    '详情 More 区装配 pause/resume 走 doOp 既有写通路')
})

ok('node.ts 源码锁：OPS 白名单含 pause/resume + 走 runPocCli 信号通道（不造旁路）', () => {
  const host = readFileSync(join(repo, 'server/plugins/workbench/node.ts'), 'utf8')
  assert.ok(host.includes("'pause', 'resume'"), 'OPS 白名单含 pause/resume')
  assert.ok(host.includes("op === 'pause' || op === 'resume'"), 'pause/resume 分发分支')
  const branch = host.slice(host.indexOf("op === 'pause' || op === 'resume'"))
  assert.ok(branch.includes('runPocCli'), '分支走 runPocCli 直调 engine client.py（sign/retry-qc 同族）')
})

console.log(`TICKET_PAUSE_UI ran=${n} fail=0`)
