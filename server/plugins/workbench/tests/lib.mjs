/**
 * lib.mjs —— t260901-20 metrics M1a 测试集公共件（fixture / 桩 / 断言助手）。
 *
 * 全部 fixture 落 mkdtemp 临时目录，零真实 ~/.sandbar / admin.py / git 触碰：
 * 数据真源走 SANDBAR_METRICS_STUB 缝（metrics.ts 文件头），缓存走 SANDBAR_METRICS_DIR。
 * zstd fixture 用系统 zstd 命令现场压缩（缺命令由调用方 SKIP）。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const HERE = new URL('.', import.meta.url).pathname
export const WB = new URL('./..', import.meta.url).pathname

let seq = 0
export function freshDir(prefix = 'm20-') {
  return mkdtempSync(join(tmpdir(), prefix + String(++seq) + '-'))
}

/** 模板链（plan → review(human) → implement），engine_version 的真源。 */
export const STAGES = [
  { id: 'plan', role: 'planner', exit: 'agent' },
  { id: 'review', role: 'reviewer', exit: 'human' },
  { id: 'implement', role: 'developer', exit: 'agent' },
]

export function baseStub(overrides = {}) {
  return {
    project: 'demo',
    epics: ['metrics'],
    workflows: [{ id: 'dev-lane', name: 'dev-lane', lane: 'lane', stages: STAGES }],
    tickets: [],
    deliveries: {},
    ...overrides,
  }
}

export function writeStub(dir, stub) {
  const p = join(dir, 'stub.json')
  writeFileSync(p, JSON.stringify(stub))
  return p
}

/** 标准时钟（固定值——双前门/重算两边同刻可比）。 */
export const NOW = Date.parse('2026-09-01T00:30:00Z')

export async function loadMetrics() {
  return import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)
}

export function gitStubMap(pairs) {
  // pairs: [[argsString, stdout]]
  return Object.fromEntries(pairs)
}

/** 造一份会话 jsonl 并压成 session.jsonl.zstd；返回 {ok, reason}。 */
export function makeSession(dir, ticketId, role, events) {
  try {
    const sess = join(dir, `.dsh`, 'sessions', 'slug0', `${ticketId}-${role}`)
    mkdirSync(sess, { recursive: true })
    const jsonl = events.map((e) => JSON.stringify(e)).join('\n') + '\n'
    const raw = join(dir, 'raw.jsonl')
    writeFileSync(raw, jsonl)
    execFileSync('zstd', ['-f', '-q', raw, '-o', join(sess, 'session.jsonl.zstd')])
    rmSync(raw)
    return { ok: true }
  } catch (err) {
    return { ok: false, reason: String(err?.message ?? err) }
  }
}

export function usageEvents(opts = {}) {
  // 最小 usage 事件序列：模型归因 + message usage + chunk 镜像（不应翻倍）
  const ev = []
  ev.push({ type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: opts.t1 ?? 1 })
  ev.push({ type: 'assistant/message', data: { usage: { inputTokens: 100, outputTokens: 10, cacheReadTokens: 5 } }, time: opts.t2 ?? 2 })
  ev.push({ type: 'assistant/chunk', data: { chunk: { type: 'usage', inputTokens: 100, outputTokens: 10, cacheReadTokens: 5 } }, time: (opts.t2 ?? 2) + 0.5 })
  return ev
}

export function worktreeTimeline(t0) {
  return [
    { at: new Date(t0).toISOString(), stage: 'plan', state: 'running' },
    { at: new Date(t0 + 3600e3).toISOString(), stage: 'review', state: 'running' },
    { at: new Date(t0 + 2 * 3600e3).toISOString(), stage: 'implement', state: 'running' },
  ]
}

export function closedTicket(id, stub, opts = {}) {
  const t0 = opts.t0 ?? Date.parse('2026-08-29T01:00:00Z')
  const closedAt = opts.closedAt ?? Date.parse('2026-08-30T06:00:00Z')
  return {
    id, project: stub.project, epic: opts.epic ?? 'metrics', title: id, workflow: 'dev-lane',
    stage: 'implement', stage_state: 'closed', status: 'closed', role: 'developer',
    updated: new Date(closedAt).toISOString(), worktree: `.worktrees/${id}`,
    timeline: [...worktreeTimeline(t0), { at: new Date(closedAt).toISOString(), stage: 'implement', state: 'closed' }],
    ...opts.extra,
  }
}

let pass = 0
let fail = 0
let skip = 0
const fails = []
export function ok(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  ok ${name}`) } else { fail++; fails.push(name); console.log(`  FAIL ${name}${detail ? ' — ' + detail : ''}`) }
}
export function skipCase(name, reason) {
  skip++; console.log(`  SKIP ${name} — ${reason}`)
}
export function summary(name) {
  console.log(`SUMMARY pass=${pass} skip=${skip} fail=${fail}`)
  return fail === 0
}
export function dumpFails() {
  return fails
}
