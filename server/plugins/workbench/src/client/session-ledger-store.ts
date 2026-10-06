/**
 * sandbar-workbench · 会话账册模块级共享 store（t260830-01）。
 *
 * 为什么存在：侧栏 <SessionSection> 与 hero <HeroSessionEntry> 挂在同一个
 * document 里，各自调用 useSessionEntry 时账册曾是实例各自的 useState——
 * hero 新建/切换后侧栏要到下次刷新才可见（工单 t260830-01 根因）。同页
 * 两组件同 document，W3C 口径 storage 事件只触发于同源**其它** document、
 * 同页永不触发，所以跨实例同步走「共享模块级状态 + 订阅」：账册状态收敛
 * 到本模块单例，persist 更新单例并通知全部订阅者，两个视图各自
 * useSyncExternalStore 订阅，同帧（同一通知周期内）重渲染。
 *
 * 账册口径零变化：key 与格式沿用 t260828-02（值见 LEDGER_KEY），读写容错
 * 全部复用 src/shared/sessions.ts 的 parseLedger/serializeLedger，不放宽。
 *
 * 【模块顶层零 IO 约束】本模块顶层不得触碰 localStorage/DOM——smoke
 * （node 裸跑，无 DOM）必须先 stub globalThis.localStorage 再 import 本
 * 模块，顶层一旦有 IO 即静默打断全部 smoke 的 stub 时序。所有 IO 收敛在
 * 函数体内（getLedgerSnapshot / persistLedger）。本模块也不得 import
 * react 或任何 npm 依赖（node_modules 不随仓库安装，smoke 靠 node
 * type-stripping 裸跑）。
 */

import { parseLedger, serializeLedger } from '../shared/sessions.ts'
import type { OpenedEntry } from '../shared/sessions.ts'

/**
 * 会话记账层账册的 localStorage key（t260828-02 定值，t260830-01 起定义
 * 移入本文件；session-entry.tsx re-export 保持对外符号兼容）。
 */
export const LEDGER_KEY = 'sandbar-workbench-opened-sessions-v1'

/** 缓存快照。null = 尚未从 localStorage 惰性读入（非空数组后引用不变）。 */
let current: OpenedEntry[] | null = null

const subscribers = new Set<() => void>()

/** 登记订阅者，返回注销函数（useSyncExternalStore 的 subscribe 协议）。 */
export function subscribeLedger(fn: () => void): () => void {
  subscribers.add(fn)
  return () => { subscribers.delete(fn) }
}

/**
 * 账册快照（useSyncExternalStore 的 getSnapshot）。首次调用惰性读入：
 * localStorage.getItem 抛异常或 payload 畸形一律按 parseLedger 既有容错
 * 剔脏/空册，不抛不崩。之后缓存引用不变，保证快照稳定性（不会触发
 * useSyncExternalStore 无限重渲染）。
 */
export function getLedgerSnapshot(): OpenedEntry[] {
  if (current === null) {
    try {
      current = parseLedger(localStorage.getItem(LEDGER_KEY))
    } catch {
      current = []
    }
  }
  return current
}

/**
 * 落盘 + 广播（useSessionEntry 的 persist 收口到这）：先写 localStorage
 * （写不进只丢持久化——沿用原「本次会话内仍可见」语义，且因为无论如何
 * 都更新单例并通知，两个视图内存态一致、不产生分叉），再更新缓存快照、
 * 逐订阅者通知。单个订阅者回调抛异常被 try/catch 隔离并留痕，不影响
 * 其它订阅者收到本次通知——不隔离则一个视图 throw 会中断循环，恰好
 * 复发本单要修的「常驻入口静默失同步」。
 */
export function persistLedger(entries: OpenedEntry[]): void {
  try {
    localStorage.setItem(LEDGER_KEY, serializeLedger(entries))
  } catch { /* 写不进只丢持久化，本次会话内各实例仍可见 */ }
  current = entries
  for (const fn of [...subscribers]) {
    try {
      fn()
    } catch (err) {
      console.error('[workbench] 会话账册订阅者通知失败（该订阅者本轮跳过，不影响其它订阅者）：', err)
    }
  }
}

/* ---------------- Project-file sync (sessions.json truth, UI-5 t261005-06) ----------------
 * Contract (design 2.2 + plan R4/R5): the truth is <projects_root>/<key>/sessions.json
 * (read/written through the host API); localStorage is demoted to a cache (lossy;
 * rebuilt from the project file). Freshness contract: the client fetches at three
 * moments only - on a project switch (an explicit fetchProjectLedger call), after
 * its own write (inside pushSessionEntry), and on the existing visibility poll
 * (wired by the caller). External file edits are not hot-reloaded (declared
 * behavior, KI-198 family - sessions.json has no runtime consumer, display faces
 * only). Any failure (non-2xx fetch / network error / malformed reply) = the cache
 * stands in; nothing throws. */

/** Session-ledger host API path (verbatim-equal to the path registered in node.ts; KI-042 drift guard). */
export const SESSIONS_API_PATH = '/sandbar-workbench/api/wf/sessions'

/** File entry -> ledger entry field mapping (session_id -> id and friends; the single snake->camel point). */
function fileEntryToOpened(e: {
  session_id: string
  handle?: string
  title?: string
  opened_at?: number
  last_opened_at?: number
  cwd?: string
}): OpenedEntry {
  return {
    id: e.session_id,
    project: '',
    cwd: typeof e.cwd === 'string' ? e.cwd : '',
    lastOpenedAt: typeof e.last_opened_at === 'number' && Number.isFinite(e.last_opened_at) ? e.last_opened_at : 0,
    ...(typeof e.title === 'string' ? { title: e.title } : {}),
    ...(typeof e.handle === 'string' && e.handle !== '' ? { handle: e.handle } : {}),
  }
}

/**
 * Fetch the project session ledger file and refresh the cache from it:
 * GET SESSIONS_API_PATH?project=<key> -> 2xx with a NON-EMPTY entries array ->
 * this project's cached entries are replaced wholesale by the file entries
 * (file-wins) + persist (into the localStorage cache + broadcast). Anything
 * else returns null silently and the cache is untouched (cache fallback, no
 * crash) — INCLUDING a 2xx reply that yields an EMPTY entry list: an empty
 * reply means the file face is absent/unreachable behind the endpoint (the
 * route does not exist yet, a stub answered, or the file is genuinely empty),
 * and the fallback contract is display-what-you-have, never display-nothing —
 * seeded cache entries must survive a missing file face (regression lock:
 * t261005-09's journey seeds only the localStorage cache; the round-8 red
 * was the file-empty win wiping them). Executor projection entries
 * (handle='executor') enter the cache through the same path - the project row
 * and the identity band share one data source.
 */
export async function fetchProjectLedger(project: string): Promise<OpenedEntry[] | null> {
  if (typeof project !== 'string' || project === '') return null
  try {
    const res = await fetch(`${SESSIONS_API_PATH}?project=${encodeURIComponent(project)}`)
    if (!res.ok) return null
    const body = await res.json() as { entries?: unknown }
    if (!Array.isArray(body?.entries)) return null
    const fileEntries = (body.entries as Parameters<typeof fileEntryToOpened>[0][])
      .filter(e => e && typeof e.session_id === 'string' && e.session_id !== '')
      .map(fileEntryToOpened)
      .map(e => ({ ...e, project }))
    // Empty file face = no authoritative data: the cache stands (see doc above).
    if (fileEntries.length === 0) return null
    // file-wins: this project's entries are replaced wholesale; other projects' entries stay as-is.
    const others = getLedgerSnapshot().filter(e => e.project !== project)
    persistLedger([...fileEntries, ...others])
    return fileEntries
  } catch {
    return null
  }
}

/**
 * Register one session into the project file (POST): resolves to the server-
 * assigned handle on success (the short code the identity band and the project
 * row display); throws on any failure (the caller shows an inline notice - a
 * registration failure is never silent, plan step 3 acceptance). A failure does
 * not roll back the local ledger entry (the cache and the file diverge briefly
 * and converge on the next fetch - declared behavior).
 */
export async function pushSessionEntry(entry: {
  id: string
  project: string
  cwd?: string
  title?: string
  lastOpenedAt?: number
}): Promise<string> {
  const res = await fetch(SESSIONS_API_PATH + (entry.project ? `?project=${encodeURIComponent(entry.project)}` : ''), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      session_id: entry.id,
      cwd: entry.cwd,
      ...(entry.title !== undefined ? { title: entry.title } : {}),
      ...(entry.lastOpenedAt !== undefined ? { lastOpenedAt: entry.lastOpenedAt } : {}),
      opened_at: entry.lastOpenedAt,
      last_opened_at: entry.lastOpenedAt,
    }),
  })
  const text = await res.text()
  let body: { ok?: unknown; error?: unknown; handle?: unknown } = {}
  try { body = JSON.parse(text) } catch { /* a non-JSON body counts as malformed and falls through to the throw below */ }
  if (!res.ok || body?.ok !== true) {
    throw new Error(`session ledger register failed (HTTP ${res.status}): ${typeof body?.error === 'string' ? body.error : text.slice(0, 120)}`)
  }
  return typeof body.handle === 'string' ? body.handle : ''
}
