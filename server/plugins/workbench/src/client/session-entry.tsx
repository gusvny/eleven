/**
 * sandbar-workbench · 会话动作层唯一样态（session-entry t260831-02 → 票② t260904-05 R8 退役收口）。
 *
 * R8 顶部行退役后，本文件**不再有任何渲染面**——只保留 useSessionEntry()
 * 动作层（账册读写 + handleNew/handleOpen/handleClose），供项目行
 * （project-session-row.tsx）消费；账册/闭账/编号计数器全部复用
 * src/shared/sessions.ts 纯函数（记账层语义零改动）。随顶部行一并退役
 * （拍板 2/3/4，notes/epics/session-entry.md 票②拍板）：
 *   - ↺「最近关闭」恢复菜单（handleReopen）——不迁移；闭账数据保留，
 *     仅作 nextProjectSeq 防撞号域（BO-1），无 UI 消费面；
 *   - tab 双击重命名（重命名纯函数随 shared/sessions.ts 一并退役）；
 *   - 顶部行组件/SessionTab/SESSION_ENTRY_STYLES 与
 *     顶部行家族 data-wb-* 断言锚（无残留消费方，smoke/hero.mjs 有
 *     「不在场」反转断言看守）。
 *
 *   - FACTORY_NEW_LABELS：出厂「⊕ New Session」钮的语义锚——aria-label 全集
 *     （dsh-client-ui-sidebar 的 locale 字典只有 zh/en 两份，实查于平台包；
 *     若 dsh 新增语言字典，锚集合在此补）。sidebar.tsx 的注入 effect 用它
 *     找到出厂钮并隐藏——**职责=压制全局新建入口**（拍板 1：移除注入=出厂
 *     全局钮回到左栏顶部，落点=平台当前工作区非项目归属，与「入口长在项目上」
 *     直接冲突）；找不到锚时软退化：出厂钮照常显示，console.warn 留痕。
 *
 * 关闭语义（t260831-06 口径沿用）：tab × 确认弹层后 handleClose =
 * removeEntry 剔账册 + 条目移入「最近关闭」（cap 10）+ 尽力调 sessions.close?；
 * 会话数据不删，仅剔入口。主账册登记只有新建登记、blank 自愈换绑两条显式路径
 * （↺ 恢复已随顶部行退役），无 current 自动登记 effect——关闭当前活跃会话的
 * 终态：tab 消失、current 不变（会话仍在运行），不会复活。
 *
 * 故障模式取舍（票 t260831-04）：
 *   - 新建走 services 的 startSession（工厂同款）；服务缺失：行内可见错误 +
 *     console.error，按钮不复位为假成功。**260923 起统一经 resolveStartSession
 *     取用**：0.1.5 该 API 在 ctx.uiWorkspace、0.1.1 在 ctx.workspaces（混版
 *     直呼旧面＝TypeError「workspaces.startSession is not a function」，实弹过）；
 *   - 工作区按项目主目录匹配（workspaceForDir：精确→前缀→realtime 归一），
 *     找不到且 projectDir 有值 → workspaces.create（host 幂等：已注册同目录
 *     返回既存工作区）；create 失败：行内提示，不落账不静默；
 *   - startSession 后 current 10s 未落定：行内提示 + warn；工作区已连接，
 *     可从列表进入；
 *   - 切换路径 sessions.open(id) 失败（throw：未列出 id 是 throw
 *     不是静默 no-op）：console.error 留痕 + 行内错误提示，账册条目保留
 *     （超时≠磁盘清理，自动 removeEntry 已删——t260831-02 的超时剔账正是
 *     「切回内容丢失」成因之一）；账册中 blank 会话条目（自铸 chat- 残留）
 *     走 startSession 换绑自愈——blank 零内容，无损失；
 *   - open 已调用但 list.current 未指向目标：warn 留痕（激活未生效线索）；
 *   - localStorage 读失败/坏 JSON：parseLedger 容错剔脏；写失败：丢持久化但
 *     本次会话内 state 仍可见（同一 hook 无第二份实现）；
 *   - 工单会话（ticket- 前缀）：isGlobalSessionId 在 touchEntry 里挡在账册外，
 *     顶部入口与账册同函数同口径，天然不混入（smoke/sessions.mjs 有断言）。
 *
 * 第 3 面①（t260904-01，项目内会话区）：handleNew 在登记时分配项目内序号 seq
 * （拍板 1「不回收」：每项目计数器续号，见 SEQ_COUNTER_KEY），blank 换绑带原号；
 * 项目行消费同一账册（模块级共享 store）与同一组动作。行内通知带归属项目
 * （noticeProject）：项目行只显示自己项目的失败提示。BO-1：nextProjectSeq
 * 兜底号域纳入「最近关闭」，计数器丢失时不再重发已关最大号。
 */

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import type { ISession, ObservableSnapshot, SessionListState } from '@deepseek-ai/dsh-client-runtime/client'
// ISession（t260904-11，KI-046 any 面收窄）：sessionOf 的返回类型直接钉平台对外
// 契约——ISession.prompt 的签名（content: PromptContentPart[], mode, RpcResult 返回）
// 即平台边界契约，tsc 从此对本文件的 prompt 调用形状负责（裸字符串传参编译期即红）。
// 「会话」记账层纯函数（t260828-02 项目归属+只列 UI 主动打开；smoke/sessions.mjs 直测）。
// removeEntry 的显式调用点=tab 关闭钮（剔账不删数据）。借鉴模式取舍：非数组容错/
// 未知 id 无害/不改入参/坏 JSON 不抛全部沿用（取舍清单见工单实现报告）。
// （重命名/切换行推导纯函数已随 R8 顶部行退役，t260904-05。）
import {
  touchEntry,
  removeEntry,
  backfillProjectSeqs,
  nextProjectSeq,
} from '../shared/sessions.ts'
import type { OpenedEntry } from '../shared/sessions.ts'
// 账册模块级共享 store：同页跨实例同步。persist 落盘 + 广播收口于此。
import {
  LEDGER_KEY,
  subscribeLedger,
  getLedgerSnapshot,
  persistLedger,
} from './session-ledger-store.ts'
// 「最近关闭」列表共享 store：模块级单例（t260904-01 D1 修复）。↺ 恢复菜单已
// 随 R8 顶部行退役（无 UI 消费面）；closed 数据保留，仅作 nextProjectSeq 防撞
// 号域（BO-1）参与续号计算——handleNew 读 getClosedSnapshot()。
import {
  CLOSED_LEDGER_KEY,
  CLOSED_LEDGER_CAP,
  subscribeClosed,
  getClosedSnapshot,
  persistClosed,
} from './closed-ledger-store.ts'
// session-charter 端点路径常量（t260904-07）：与 node.ts 路由注册同源派生
// （方案 R7 防 KI-042 路径漂移）；被引模块零 node 依赖，浏览器包安全（review C1）。
import { SESSION_CHARTER_PATH, CHARTER_MARKER } from '../host/session-charter.ts'
// 「新建会话」启动面的双版兼容解析（260923）：0.1.1 在 ctx.workspaces 上、
// 0.1.5 起迁到 ctx.uiWorkspace（workspaces 变纯控制器）——严禁直呼旧面。
import { resolveStartSession } from '../shared/workspaces-compat.ts'

export { LEDGER_KEY, CLOSED_LEDGER_KEY }

/**
 * 出厂「⊕ New Session」钮的语义锚（aria-label 全集）：dsh-client-ui-sidebar 的
 * `session.new.label` 词条，zh=新建会话 / en=New session（实查平台包 locale 字典，
 * 全包仅此两份）。侧栏注入 effect 以「SidebarRoot 直接子 button 且 aria-label
 * 命中本集合」定位出厂钮——零 CSS 类名匹配（t260828-06 死因不复犯）。
 * smoke/hero.mjs 对本集合有存在性断言（新增语言字典时提醒补锚）。
 */
export const FACTORY_NEW_LABELS: readonly string[] = ['新建会话', 'New session']

/* ── 「最近关闭」列表（t260831-06 建）：tab × 之后条目的去处，↺ 菜单的重开
 * 数据源。t260904-01 D1 修复：IO 与状态归属迁入 closed-ledger-store.ts 模块级
 * 共享 store（坏 JSON 容错/写失败丢持久化/cap 10/同 id 重关重提头——取舍清单
 * 见该文件头注）；本文件只留纯函数 pushClosedLedger。 */
/** 条目移入「最近关闭」（同 id 去重重提头 + cap 截断），返回新列表。 */
function pushClosedLedger(prev: OpenedEntry[], entry: OpenedEntry): OpenedEntry[] {
  const out = [entry, ...prev.filter(e => e && e.id !== entry.id)]
  return out.slice(0, CLOSED_LEDGER_CAP)
}

/* ── 项目内会话编号计数器（第 3 面①，拍板 1「不回收」）──
 * 形态：localStorage 单键存 {[projectKey]: 该项目历史最大已用 seq}；handleNew
 * 登记时 nextProjectSeq = max(计数器, 账册内该项目现存最大 seq) + 1，**先写计数器
 * 再落账**。故障模式取舍（对齐 closed-ledger-store.ts 头注清单，逐项带/不带理由）：
 *   - 读容错（带）：坏 JSON/非对象/数组/键值畸形 → 该项目按 0 处理，等价计数器
 *     丢失；nextProjectSeq 以账册现存最大 seq 兜底——只可能跳号，不可能重号
 *     （编号语义=稳定身份而非稠密序列，拍板 1，跳号无害）。
 *   - 写容错（带）：写失败丢持久化不抛（同账册 persist 取舍——本次会话内计算
 *     仍正确，localStorage 不可写的环境本就丢一切持久化）。
 *   - 原子性（声明不做）：计数器与账册两键非原子；中断窗口=号被跳过、不会重号
 *     （先写计数器：中断后计数器已前进，重试取新号；账册先写才会重号，故此序）。
 *   - 跨实例同步（声明不做）：消费点只有 handleNew 登记这一个离散动作，两个
 *     useSessionEntry 实例的登记尾段都是同步代码（JS 单线程不交错），无同帧
 *     并发读写需求——不入 session-ledger-store 共享 store（review C3 取舍：
 *     计数器读→写→persist 在同一同步段完成，同号窗口就此闭合）。
 * 惰性读写（同 CLOSED_LEDGER 模式），无模块顶层 IO。 */
export const SEQ_COUNTER_KEY = 'sandbar-workbench-project-seq-v1'

/** 读项目编号计数器（localStorage → {[project]: 最大已用 seq}；坏数据容错为空表）。 */
function readSeqCounters(): Record<string, number> {
  try {
    const raw = window.localStorage.getItem(SEQ_COUNTER_KEY)
    if (!raw) return {}
    const data: unknown = JSON.parse(raw)
    if (typeof data !== 'object' || data === null || Array.isArray(data)) return {}
    const out: Record<string, number> = {}
    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      if (typeof k !== 'string' || k === '') continue
      if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) continue
      out[k] = v
    }
    return out
  } catch {
    return {}
  }
}

/** 写回项目编号计数器（写失败丢持久化但不抛——取舍见上方清单）。 */
function writeSeqCounters(map: Record<string, number>): void {
  try {
    window.localStorage.setItem(SEQ_COUNTER_KEY, JSON.stringify(map))
  } catch { /* 写失败：丢持久化，本次会话内续号计算仍正确 */ }
}

/** sessions 服务面（ctx.sessions 的子集；结构类型可测裸对象）。 */
export interface SessionsFace {
  open(id: string): void
  scope(id: string): any
  /** 会话域 actx → Session 对象（t260904-07 charter 注入用；可选：运行时面缺失则注入失败就地留痕）。
   *  返回类型钉平台 ISession（t260904-11 KI-046 any 面收窄：签名由平台 d.ts 校验，不再 any 抹平）。 */
  sessionOf?(actx: any): ISession
  refresh?(): Promise<unknown>
  /** 关闭会话（可选；运行时现未提供——提供则关闭钮尽力调用，失败仅 warn）。 */
  close?(id: string): void
  list: ObservableSnapshot<SessionListState>
}

/**
 * workspaces 服务面（ctx.workspaces 的子集；IWorkspaces 公开契约的结构投影）。
 * t260831-04 取证实锤：WorkspaceBrowserInjected.open/startSession 是
 * ui-workspace 的**注册者私有注入**，slot owner props（wide/expandSidebar）里
 * 拿不到——旧代码里「slotOpen 优先」的分支恒走 sessions.open 兜底。
 * 新建的工厂同款语义在**公开服务**的 startSession：绑工作区 + 复用
 * blank 会话 + 正确打开（staging）。
 *
 * ⚠️ 260923 勘误（升级 0.1.5 后「新建会话」全项目报 TypeError 的事故）：
 *   0.1.1 时代该 API 在 `ctx.workspaces` 上；**0.1.5 起它随 UI 工作区服务迁到
 *   `ctx.uiWorkspace`**（dsh-client-ui-workspace，`super(ctx,"uiWorkspace")`），
 *   而 `ctx.workspaces` 变成纯控制器 dsh-api-workspace-controller（整包无此方法）。
 *   故本接口的 startSession 标为可选：实际取用一律走 `resolveStartSession`
 *   （shared/workspaces-compat.ts；双版容错 + 精确报错），**严禁再直呼
 *   `workspaces.startSession(...)`**（有静态看守）。
 */
export interface WorkspacesFace {
  list: ObservableSnapshot<{ items: readonly { workspaceId: string; path: string }[] }>
  startSession?(workspaceId?: string): void
  create(input: { path: string }): Promise<{ workspaceId: string }>
}

/** host 侧 create 的 session 经 list 流同步到 client 有延迟——轮询等 scope 可解析（≤ms 毫秒）。
 *  ⚠️ 勘误（票 t260831-02）：sessions 服务头注明 scope 是「首次 open 才惰性铸造」——
 *  open 之前等 scope 永远超时，本函数对打开路径没有前置价值，保留只为 sidebar.tsx
 *  工单点击路径的既有调用（ticket 会话由同链路 open，行为不变）。
 *  打开路径的正确前置=waitForListed（等 id 进客户端 list，见下）。 */
export async function waitForScope(sessions: SessionsFace, id: string, ms = 4000): Promise<any> {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try {
      const s = sessions.scope(id)
      if (s) return s
    } catch { /* 未同步 */ }
    await new Promise(r => setTimeout(r, 250))
  }
  return null
}

/**
 * 等 id 进入客户端会话列表。勘误后口径（票 t260831-02）：open(id) 对未
 * 列出 id 是 **throw**（manager.select: 'sessions.select: unknown session …'），
 * 不是静默 no-op；scope 的惰性铸造时机是「first resolution」而非「first open」。
 * 等 listed 的价值=把「未列出即 throw」挡在调用前、并把等不到的场景转成明确报错，
 * 而不是依赖 catch——保留本前置，语义按订正后口径理解。
 */
export async function waitForListed(sessions: SessionsFace, id: string, ms = 10000): Promise<boolean> {
  const listed = (): boolean => {
    try {
      // byId 键是 branded SessionId，字符串 id 用 in 判存在（绕开 TS7053 索引噪音）
      const byId = (sessions.list.getSnapshot()?.byId ?? {}) as Record<string, unknown>
      return id in byId
    } catch { return false }
  }
  const t0 = Date.now()
  while (!listed() && Date.now() - t0 < ms) {
    try { await sessions.refresh?.() } catch { /* 拉取失败继续轮询 */ }
    await new Promise(r => setTimeout(r, 200))
  }
  return listed()
}

/** useSessionEntry 的入参。 */
interface SessionEntryOptions {
  /** 客户端 sessions 服务（index.tsx 的 ctx.sessions）。 */
  sessions: SessionsFace
  /** 客户端 workspaces 服务（index.tsx 的 ctx.workspaces；0.1.5 起＝纯控制器）。 */
  workspaces?: WorkspacesFace
  /** 客户端 uiWorkspace 服务（index.tsx 的 ctx.uiWorkspace；**0.1.5 起** startSession 在这上面）。
   *  可选：0.1.1 没有该服务，缺失时自动回落 workspaces（见 resolveStartSession）。 */
  uiWorkspace?: WorkspacesFace
  /** 槽注入的打开动作（WorkspaceBrowserInjected.open；由侧栏槽注入）。 */
  slotOpen?: (sessionId: string) => void
  /** 列表归属与新建落点的项目 key（空=未选项目：列表空，多项目时 + 弹项目选单）。 */
  projectKey: string
  /** 该项目主目录（注册表 primary；新建落点的工作区按它匹配/创建）。 */
  projectDir?: string
}

/**
 * 按 cwd 匹配工作区：先精确 path，再目录前缀（工作区是项目目录或其祖先/后代
 * 场景都容——平台 realpath canon 对我们的注册表 path 可能带 /private 前缀等）。
 * 找不到返回 undefined，调用方决定是否 create。
 */
function workspaceForDir(items: readonly { workspaceId: string; path: string }[], dir: string): { workspaceId: string; path: string } | undefined {
  if (!dir) return undefined
  return items.find(w => w.path === dir)
    ?? items.find(w => dir.startsWith(w.path + '/') || w.path.startsWith(dir + '/'))
    ?? items.find(w => w.path.replace(/^\/private/, '') === dir.replace(/^\/private/, ''))
}

/**
 * 等 staging 落定：startSession 之后等 list.current **离开 prev**（新开/换绑）。
 * 超时未变 = startSession 复用了 prev 指向的 blank 会话（工厂语义：blank 复用，
 * current 合法地不动），此时返回 prev 作为 staged 会话（prev 为 null 则 null）。
 * ⚠️ 不能「等 current 非 null」——点击前 current 就非空（正在看的会话），
 * 那会把旧会话误记进账册（自测探针实锤过的 bug）。
 */
async function waitForStaged(sessions: SessionsFace, prev: string | null | undefined, ms = 10000): Promise<string | null> {
  const read = (): string | null => {
    try { return (sessions.list.getSnapshot()?.current as string | undefined) ?? null } catch { return null }
  }
  const t0 = Date.now()
  let cur = read()
  while ((cur === null || cur === prev) && Date.now() - t0 < ms) {
    try { await sessions.refresh?.() } catch { /* 拉取失败继续轮询 */ }
    await new Promise(r => setTimeout(r, 200))
    cur = read()
  }
  return cur ?? prev ?? null
}

/** 读会话 blank 位（平台语义：新会话零内容=blank）。快照读失败一律视为非
 *  blank——注入宁可不发，不误注入到读不出状态的会话上。 */
function isBlankSession(sessions: SessionsFace, id: string): boolean {
  try {
    const byId = (sessions.list.getSnapshot()?.byId ?? {}) as Record<string, { blank?: boolean }>
    return byId[id]?.blank === true
  } catch { return false }
}

/**
 * 会话开局 charter 注入（t260904-07）：blank 新会话恰一次注入项目 charter
 * （GET /sandbar-workbench/api/session-charter?project=<key> 现读现渲染）→
 * sessions.scope(staged) → sessions.sessionOf(actx) → session.prompt([文本分片],
 * 'queue')（平台首条消息正路：blank→engaging，触发一轮 agent 回复=预期
 * kick-off）。借鉴取舍清单（t260831-08 ⑥ 口径，方案 R1 八项逐项声明）：
 *   1. 恢复/切换路径不注入——带：仅 handleNew 单路径调用本函数；
 *   2. 非 blank 二次注入污染——带：blank 守卫（发过首条即非 blank）；
 *   3. staged 未落定即注入——带：handleNew 已 waitForStaged+null 提前 return；
 *   4. 「本项目行」归属——由构造保证（startSession 绑项目工作区+账册同帧
 *      project=pk），不设运行时守卫（冗余）；
 *   5. 服务端建会话半——不带：本链路走客户端工厂链，服务端只出只读端点；
 *   6. 旧 API conversation.send——不带：改 session.prompt('queue')；
 *   7. waitForStaged 超时复用 blank prev——在守卫域内：blank===true 时注入
 *      命中复用会话=预期（工厂语义），非 blank 被守卫挡掉；
 *   8. 注入失败不回滚——本方案定死：就地捕获+行内提示，会话创建与注入解耦。
 *  勘误（t260904-11，KI-046）：「失败」现含两条路——①throw（fetch/解析/传输层）；
 *  ②prompt 返回 RpcResult{ok:false}（平台业务失败不 throw）——②原实现漏检，
 *  错误只经 toast 直达用户、console 零留痕；现统一转①走下方 catch 就地消化。
 * 报错精确纪律（R3，KI-018/025 谎报同族）：全链路 try/catch 就地消化，绝不
 * 冒泡 handleNew 外层 catch（外层文案=「新建会话失败」，而此刻会话已创建）。
 * TOCTOU 复核（R5）：prompt 前一刻用最新快照复核 blank 位，网络往返期间用户
 * 抢先发首条则静默跳过（console.info 留痕——用户已接管对话，提示是噪音）。
 */
export async function injectSessionCharter(sessions: SessionsFace, staged: string, projectKey: string, notify: (text: string, project?: string) => void): Promise<void> {
  // 截图台豁免（capture 族）：capture.mjs 经 addInitScript 预置 localStorage
  // 门旗。隔离台没有真 agent 会话，charter prompt 永远挂在 machineBusy，
  // composer 恒 readOnly，种子消息写不进去、chat 态视图开不出——台内造数
  // 语义下跳过注入，改由种子消息自己驱动 active（与注入落地前同权）。
  try {
    if (globalThis.localStorage?.getItem('sandbar-ui-capture-skip-charter') === '1') return
  } catch { /* localStorage 不可达（SSR 等）→ 不豁免 */ }
  if (!isBlankSession(sessions, staged)) return
  try {
    const res = await fetch(`${SESSION_CHARTER_PATH}?project=${encodeURIComponent(projectKey)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const text = await res.text()
    let body: unknown
    try { body = JSON.parse(text) } catch { throw new Error(`响应非 JSON：${text.slice(0, 80)}`) }
    const charter = (body as { charter?: unknown } | null | undefined)?.charter
    if (typeof charter !== 'string' || charter.trim() === '') throw new Error('charter 字段缺失或非字符串（响应体畸形）')
    if (!isBlankSession(sessions, staged)) {
      console.info('[workbench] charter 注入跳过：会话已非 blank（用户已抢先发首条）：', staged)
      return
    }
    if (typeof sessions.sessionOf !== 'function') throw new Error('ctx.sessions.sessionOf 未注入（运行时面缺失）')
    const session = sessions.sessionOf(sessions.scope(staged))
    // 载荷形状（t260904-11，KI-046 根因修复）：平台 wire 契约要求 content 为
    // PromptContentPart 分片数组（apiproxy sessionPromptRequestSchema zod 判收），
    // 裸字符串即报 invalid payload for session prompt。且 prompt 的**业务失败不
    // throw 只返回 RpcResult**（ok:false，同时镜像进 snapshot.promptError）——
    // 原 R3「就地 catch 兜底」假设失败会 throw，07 票因此静默失效；此处显式
    // 检查 result.ok，失败转 throw 落入下方 catch 的就地消化路径（R3 语义不变）。
    // 注入文本首行拼机读标记（t260905-04）：渲染端 context-fold 折叠件据此把
    // 本条消息收成「已注入项目背景」小条（标记常量与端点同源，R7 防漂移）；
    // 畸形 charter 已在上方守卫挡掉，标记拼装只对已验证的字符串生效。
    const result = await session.prompt([{ type: 'text', text: `${CHARTER_MARKER}\n${charter}` }], 'queue')
    if (!result?.ok) {
      const detail = result && !result.ok ? `${result.error.code} ${result.error.message}` : '空结果（未返回 RpcResult）'
      throw new Error(`charter prompt 被平台拒收：${detail}`)
    }
  } catch (err) {
    console.error('[workbench] 会话开局 charter 注入失败（会话创建不受影响）：', staged, err)
    notify('会话开局提示注入失败（详情见控制台），会话已正常创建', projectKey)
  }
}

/**
 * 会话入口共享 hook（动作层）：账册状态 + 新建/打开/关闭动作，渲染面=项目行。
 */
export function useSessionEntry({ sessions, workspaces, uiWorkspace, slotOpen, projectKey, projectDir }: SessionEntryOptions) {
  const list = sessions.list
  const subscribe = useCallback((fn: () => void) => list.subscribe(fn), [list])
  const getSnapshot = useCallback(() => list.getSnapshot(), [list])
  const listState = useSyncExternalStore(subscribe, getSnapshot)
  /** 「绑工作区 + 复用 blank + 正确打开」的启动动作（双版容错，260923）：
   *  优先 0.1.5 的 ctx.uiWorkspace，回落 0.1.1 的 ctx.workspaces；两者都没有时
   *  resolveStartSession 抛精确错误（被外层 catch 打进控制台，不再甩裸 TypeError）。 */
  const startWorkspaceSession = useCallback(
    (workspaceId?: string) => resolveStartSession([uiWorkspace, workspaces])(workspaceId),
    [uiWorkspace, workspaces],
  )
  // 账册：模块级共享 store——挂载时（首次 getSnapshot）从 localStorage 惰性读入
  // （坏数据 parseLedger 容错为空册）；persist 统一「更新单例 + 落盘 + 通知订阅者」。
  const ledger = useSyncExternalStore(subscribeLedger, getLedgerSnapshot)
  const persist = useCallback((entries: OpenedEntry[]) => {
    persistLedger(entries)
  }, [])
  const [creating, setCreating] = useState(false)
  /** 行内可见错误/提示（t260831-04）：open 链失败不再只打 console——用户在
   *  界面上能看见「为什么没切过去」。下一次动作或 8s 后自动清除（timer 有
   *  cleanup，见下方 effect，全终态回收）。 */
  const [entryNotice, setEntryNotice] = useState('')
  /** 通知归属项目（第 3 面①）：项目行据此只显示自己项目的提示（N 个项目组
   *  不重复同一条全局噪音）；undefined=无归属信息（顶部行不区分照常全显）。 */
  const [noticeProject, setNoticeProject] = useState<string | undefined>(undefined)

  /** 通知统一入口：text='' 清空（连带清归属）。 */
  const notify = useCallback((text: string, project?: string) => {
    setEntryNotice(text)
    setNoticeProject(text === '' ? undefined : project)
  }, [])

  // 通知自动清除：8s 后回落，组件卸载/新通知到来前清 timer。
  useEffect(() => {
    if (!entryNotice) return
    const t = setTimeout(() => notify(''), 8000)
    return () => clearTimeout(t)
  }, [entryNotice, notify])

  /**
   * 打开一个已入账册的会话（t260831-04 收口：handleOpen/handleNew 共用，
   * 时序唯一实现）：refresh → waitForListed（轮询 200ms，≤10s）→
   * slotOpen || sessions.open → open 后读 list.current 自检。
   * - 超时：账册条目保留 + 行内提示，返回 false（t260831-02 的自动
   *   removeEntry 已删——超时只说明 wire 同步慢，误删=「切回丢内容」成因）；
   * - open throw（未列出 id）：console.error + 行内提示，返回 false；
   * - 成功但 current 未跟上：warn 留痕（激活未生效线索），仍返回 true——
   *   open 调用本身已生效，下一步激活是平台层时序，不在本插件能强制的面内。
   */
  const openSession = useCallback(async (id: string, projectHint?: string): Promise<boolean> => {
    notify('', undefined)
    const listed = await waitForListed(sessions, id, 10000)
    if (!listed) {
      console.warn('[workbench] 打开会话：会话未进客户端列表（wire 同步慢或会话已被磁盘清理；账册条目保留，可稍后重试）：', id)
      notify('会话打开超时：列表同步未完成，条目已保留，可重试', projectHint)
      return false
    }
    try {
      if (slotOpen) slotOpen(id)
      else sessions.open(id)
    } catch (err) {
      console.error('[workbench] 打开会话失败：', id, err)
      notify('会话打开失败（详情见控制台）', projectHint)
      return false
    }
    // open 生效性自检：留一拍让 select/通知走完，再读 current 比对。
    await new Promise(r => setTimeout(r, 250))
    let cur: unknown
    try { cur = sessions.list.getSnapshot()?.current } catch { cur = '<unreadable>' }
    if (cur !== id) {
      console.warn('[workbench] open 已调用但 list.current 未指向目标（激活可能未生效，右栏或仍驻留 hero）：', id, 'current=', String(cur))
    }
    return true
  }, [sessions, slotOpen, notify])

  // 切换（t260831-06：不再 touchEntry 重排——点 tab 停在原地，顺序=登记顺序），
  // 直接走 openSession 统一链。超时不剔账（见 openSession 注释）。
  // blank 自愈（票 t260831-04）：账册里的 blank 会话（早期宿主端自铸的
  // chat- 条目——没绑工作区，永远不会被 staging 之外的路径写入内容，平台
  // 语义「hero ⟺ 当前会话 blank」决定点它只会看到 hero+工作区选择器）改走
  // startSession(工作区)——blank 会话零内容，换绑新 id 无内容损失，账册同步
  // 换到新 id（这是显式语义路径，不是误删；换绑登记带原 title 不丢改名）。
  const handleOpen = useCallback(async (id: string) => {
    const entry = ledger.find(e => e.id === id)
    const byId = (() => { try { return sessions.list.getSnapshot()?.byId ?? {} } catch { return {} } })()
    const row = (byId as Record<string, { blank?: boolean }>)[id]
    if (row?.blank === true && workspaces && entry?.cwd) {
      const ws = workspaceForDir(workspaces.list.getSnapshot()?.items ?? [], entry.cwd)
        ?? await workspaces.create({ path: entry.cwd }).catch((err: unknown) => {
          console.warn('[workbench] blank 会话自愈：工作区创建失败，退回普通打开：', entry.cwd, err)
          return undefined
        })
      if (ws) {
        const prev = (() => { try { return (sessions.list.getSnapshot()?.current as string | undefined) ?? null } catch { return null } })()
        startWorkspaceSession(ws.workspaceId)
        const staged = await waitForStaged(sessions, prev, 10000)
        if (staged && staged !== id) {
          persist(touchEntry(removeEntry(ledger, id), {
            id: staged,
            project: entry.project,
            cwd: entry.cwd,
            title: entry.title,
            // 原号带回（第 3 面① 拍板 1：换绑=同一逻辑 tab 换会话壳，编号=稳定身份不重排）
            seq: entry.seq,
            lastOpenedAt: Date.now(),
          }))
        }
        return
      }
    }
    await openSession(id, entry?.project)
  }, [openSession, workspaces, sessions, ledger, persist, projectKey, startWorkspaceSession])

  // 新建（票 t260831-04 重写）：不再走宿主端 global-session/open 自铸会话
  // （自铸会话不绑工作区 → 平台语义「hero ⟺ blank」下永远停在 hero、内容被
  // 发到别处——仲裁 S2/S3 失败的根因）。改走 startWorkspaceSession
  // （双版容错：0.1.5 的 ctx.uiWorkspace 优先，回落 0.1.1 的 ctx.workspaces）——
  // 与出厂 New Session 完全同款：绑当前项目工作区、复用既有 blank 会话
  // （不再累积空会话）、正确打开。staged 的会话 id 落账册（打开链路失败也
  // 不丢入口——记账层的意义）。行内可见错误态同前。
  // target：多项目未选时由项目选单显式传入（t260903 切换夜）；缺省回落当前
  // viewProject 语义（单项目兜底/点票后）——两条路同一创建链。
  const handleNew = useCallback(async (target?: { key: string; dir: string }) => {
    const pk = target?.key ?? projectKey
    const pd = target?.dir ?? projectDir
    if (!pk || creating) return
    if (!workspaces) {
      notify('新建会话失败：workspaces 服务不可用', pk)
      console.error('[workbench] 新建会话失败：ctx.workspaces 未注入（index.tsx inject 列表缺 workspaces）')
      return
    }
    setCreating(true)
    notify('', undefined)
    try {
      let ws = workspaceForDir(workspaces.list.getSnapshot()?.items ?? [], pd ?? '')
      if (!ws && pd) {
        ws = await workspaces.create({ path: pd }).then(w => ({ ...w, path: pd })).catch((err: unknown) => {
          console.error('[workbench] 新建会话失败：工作区创建失败：', pd, err)
          notify('新建会话失败：工作区创建失败（详情见控制台）', pk)
          return undefined
        })
      }
      if (!ws) {
        console.error('[workbench] 新建会话失败：项目无对应工作区且无法创建：', pk, pd)
        notify('新建会话失败：项目主目录未注册为工作区', pk)
        return
      }
      startWorkspaceSession(ws.workspaceId)
      const prev = (() => { try { return (sessions.list.getSnapshot()?.current as string | undefined) ?? null } catch { return null } })()
      const staged = await waitForStaged(sessions, prev, 10000)
      if (!staged) {
        console.warn('[workbench] 新建会话：staging 未落定（current 未更新）；工作区已连接，可从列表进入：', ws.workspaceId)
        notify('会话打开超时：列表同步未完成，可重试', pk)
        return
      }
      // 编号分配（第 3 面①，拍板 1「不回收」）：
      // - C4 自愈：先纯计算补齐账册缺号存量（backfillProjectSeqs），随本次登记
      //   一并 persist（挂载 effect 之外的兜底，防两路竞态留缺号条目）；
      // - 续号：nextProjectSeq = max(计数器, 项目内现存最大 seq) + 1；**先写计数器
      //   再落账**（中断=跳号不重号，取舍见 SEQ_COUNTER_KEY 头注）；
      // - C3 并发同号窗口闭合：计数器读→写→persist 在同一同步段（上方 await 已
      //   结束，JS 单线程下两个 handleNew 尾段不交错）；ledger 取
      //   getLedgerSnapshot() 最新快照而非闭包值——顶部行/项目行两实例同帧
      //   各自完成登记时，闭包值会读到旧册。
      const latest = getLedgerSnapshot()
      const base = backfillProjectSeqs(latest)
      const counters = readSeqCounters()
      // BO-1 修复（验收走查边界观察）：兜底号域纳入「最近关闭」——计数器丢失时
      // 关掉的最大号（如 30）不再被重发，杜绝「重开撞号破坏稳定身份」。
      const seq = nextProjectSeq(base, pk, counters[pk], getClosedSnapshot())
      writeSeqCounters({ ...counters, [pk]: seq })
      persist(touchEntry(base, {
        id: staged,
        project: pk,
        cwd: pd ?? '',
        lastOpenedAt: Date.now(),
        seq,
      }))
      // 会话开局 charter 注入（t260904-07）：登记完成后，仅当 staged 是 blank
      // 新会话时恰一次注入（守卫与失败路径全在 injectSessionCharter 内就地
      // 消化：blank 判定 + prompt 前 TOCTOU 复核 + 不冒泡外层 catch 不回滚
      // 创建；handleOpen/自愈换绑等恢复/切换路径不接本注入）。
      await injectSessionCharter(sessions, staged, pk, notify)
    } catch (err) {
      console.error('[workbench] 新建会话请求异常：', err)
      notify('新建会话失败：请求异常（详情见控制台）', pk)
    } finally {
      setCreating(false)
    }
  }, [workspaces, sessions, projectKey, projectDir, creating, persist, notify, startWorkspaceSession])

  /* ── tab 关闭（t260831-06；t260904-01 D1 修复：closed 状态迁共享 store）──
   * 关闭=removeEntry 剔账册（tab 消失）+ 条目移入「最近关闭」列表 + 尽力调
   * sessions.close?（运行时现无——会话数据不删，仅剔入口，无不可恢复损失，
   * 确认弹窗由项目行承担，R5）。重开（↺）已随 R8 顶部行退役——closed 只出
   * 不进，数据保留作 BO-1 号域。 */
  const closedList = useSyncExternalStore(subscribeClosed, getClosedSnapshot)

  const handleClose = useCallback((id: string) => {
    const entry = ledger.find(e => e.id === id)
    persist(removeEntry(ledger, id))
    if (entry) {
      // push 后立即 persistClosed（落盘+更新单例+广播——t260831-06 打回的
      // 「漏写盘」双故障由 store 收口，D1 的「不通知对端」同在此修）
      persistClosed(pushClosedLedger(getClosedSnapshot(), entry))
    }
    if (typeof sessions.close === 'function') {
      try { sessions.close(id) } catch (err) {
        console.warn('[workbench] 关闭会话：sessions.close 调用失败（入口已剔除，会话数据不受影响）：', id, err)
      }
    }
  }, [ledger, persist, sessions])

  // handleReopen（↺ 恢复）已随 R8 顶部行退役（拍板 2）：closed 只出不进，
  // 数据保留作 BO-1 号域。persistClosed 仍被 handleClose 使用。

  return { ledger, creating, entryNotice, noticeProject, handleNew, handleOpen, handleClose, closedList, listState }
}
