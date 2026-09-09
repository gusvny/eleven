/**
 * sandbar-workbench · 「最近关闭」列表模块级共享 store（t260904-01 D1 修复，
 * session-entry 第 3 面①验收走查打回项）。
 *
 * 为什么存在：D1 回归——t260904-01 双实例拆分（顶部行 +
 * sidebar 项目行各持一个 useSessionEntry）前，closedList 是 hook 实例各自的
 * useState，单实例时代够用；拆分后项目行（二号实例）handleClose 只写
 * localStorage + 自身 state，顶部行（一号实例）的 ↺ 钮渲染条件
 * `closedRecent.length > 0` 挂在自身挂载时快照上——boot 后首关场景 ↺ 钮
 * 不出现，「打开菜单时刷新」的惰性刷新救不了「钮未渲染」的空态死锁（用户
 * 须刷新页面才能找回恢复入口，验收标准 4「可从恢复路径找回」断裂）。
 *
 * 修复=账册主 store（session-ledger-store.ts）同款模式：状态收敛到本模块
 * 单例，persist 更新单例并通知全部订阅者，两实例各自 useSyncExternalStore
 * 订阅、同一通知周期内重渲染——任意实例关闭/重开，另一实例的 ↺ 钮与菜单
 * 即时可见。同页 storage 事件不触发的口径同主 store 头注（W3C：仅同源其它
 * document），跨实例同步只能走共享状态。
 *
 * IO 容错（对齐 session-ledger-store / 原 readClosedLedger 取舍）：
 * - 【模块顶层零 IO】顶层不碰 localStorage/DOM（smoke node 裸跑先 stub 再
 *   import 的时序约束），全部 IO 收敛在函数体内；不 import react/npm 依赖。
 * - 读：localStorage.getItem 抛异常或坏 JSON → parseLedger 容错空表，不抛不崩。
 * - 写：写失败丢持久化但**仍更新内存单例并通知**（本次会话内各实例一致，
 *   不产生分叉——「写失败丢持久化」语义与主 store 一致）。
 * - 单订阅者回调抛异常被隔离并留痕，不中断其余订阅者（主 store 同款）。
 *
 * cap 10、同 id 重关重提头、超出淘汰最旧——语义沿用 t260831-06 原口径，
 * 本模块只改「状态归属」（实例 state → 共享单例），不改任何业务规则。
 */

import { parseLedger, serializeLedger } from '../shared/sessions.ts'
import type { OpenedEntry } from '../shared/sessions.ts'

/** 「最近关闭」列表的 localStorage key（t260831-06 定值，D1 修复起定义随
 * IO 迁入本文件；session-entry.tsx re-export 保持对外符号兼容；260908 终切
 * 改 sandbar 前缀，旧 key 读入时一次性迁移——KI-058 状态层清单规则）。 */
export const CLOSED_LEDGER_KEY = 'sandbar.workbench.closedSessions'
const LEGACY_CLOSED_LEDGER_KEY = 'suyou.workbench.closedSessions'

/** 列表上限（沿用 t260831-06：cap 10，防无限增长）。 */
export const CLOSED_LEDGER_CAP = 10

/** 缓存快照。null = 尚未从 localStorage 惰性读入。 */
let current: OpenedEntry[] | null = null

const subscribers = new Set<() => void>()

/** 登记订阅者，返回注销函数（useSyncExternalStore 的 subscribe 协议）。 */
export function subscribeClosed(fn: () => void): () => void {
  subscribers.add(fn)
  return () => { subscribers.delete(fn) }
}

/**
 * 列表快照（useSyncExternalStore 的 getSnapshot）。首次调用惰性读入
 * localStorage（抛异常/坏 JSON → parseLedger 容错空表）；之后缓存引用不变，
 * 保证快照稳定性（不触发无限重渲染）。
 */
export function getClosedSnapshot(): OpenedEntry[] {
  if (current === null) {
    try {
      let raw = localStorage.getItem(CLOSED_LEDGER_KEY)
      if (raw === null) {
        // 一次性迁移：旧 key 数据搬新 key 后删旧（KI-058：localStorage 改名不迁移=入口隐形）
        const legacy = localStorage.getItem(LEGACY_CLOSED_LEDGER_KEY)
        if (legacy !== null) {
          localStorage.setItem(CLOSED_LEDGER_KEY, legacy)
          localStorage.removeItem(LEGACY_CLOSED_LEDGER_KEY)
          raw = legacy
        }
      }
      current = parseLedger(raw)
    } catch {
      current = []
    }
  }
  return current
}

/**
 * 落盘 + 广播：先写 localStorage（cap 截断后写，写失败只丢持久化），再更新
 * 内存单例（同样 cap 收敛，防越界增长）并逐订阅者通知——任意实例调用，全部
 * 实例同帧看到（D1 修复核心）。
 */
export function persistClosed(entries: OpenedEntry[]): void {
  const capped = (Array.isArray(entries) ? entries : []).slice(0, CLOSED_LEDGER_CAP)
  try {
    localStorage.setItem(CLOSED_LEDGER_KEY, serializeLedger(capped))
  } catch { /* 写失败：丢持久化，本次会话内各实例仍一致可见 */ }
  current = capped
  for (const fn of [...subscribers]) {
    try {
      fn()
    } catch (err) {
      console.error('[workbench] 最近关闭列表订阅者通知失败（该订阅者本轮跳过，不影响其它订阅者）：', err)
    }
  }
}
