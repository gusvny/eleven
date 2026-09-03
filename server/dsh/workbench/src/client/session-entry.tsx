/**
 * suyou-workbench · 顶部会话入口（session-entry t260831-02 第三轮）。
 *
 * 本文件是会话入口唯一的逻辑实现点：
 *
 *   - useSessionEntry()：账册（localStorage）读写 + handleNew/handleOpen +
 *     切换行推导，全部复用 src/shared/sessions.ts 纯函数（记账层语义零改动，
 *     t260828-02 口径原样保留）；
 *   - FACTORY_NEW_LABELS：出厂「⊕ New Session」钮的语义锚——aria-label 全集
 *     （dsh-client-ui-sidebar 的 locale 字典只有 zh/en 两份，实查于平台包；
 *     若 dsh 新增语言字典，锚集合在此补）。sidebar.tsx 的注入 effect 用它在
 *     SidebarRoot 直接子 button 上找到出厂钮并整行原地替换（隐藏出厂 + 我们的
 *     入口渲染在侧栏顶部同一视觉位置）；找不到锚时软退化：出厂钮照常显示、
 *     我们的入口仍在侧栏顶部，功能不丢，console.warn 留痕。
 *   - <SessionTopEntry>：紧凑一行入口——「+ 新建会话」+ 最近会话切换（≤5，
 *     会话跟项目走）。与已退场的 SessionSection（t260825-02 左栏会话区，本票
 *     整块移除）和 HeroSessionEntry（t260829-06 hero 槽版，本票随 hero 接管
 *     拆除退场）消费同一个 useSessionEntry 同一账册，只有渲染层不同。
 *     带 data-wb-* 断言锚（UI 验收 DOM 断言用）：data-wb-session-entry（根）、
 *     data-wb-session-new（新建钮）、data-wb-session-row[data-active]（切换行）、
 *     data-wb-session-close（关闭钮）、data-wb-session-rename（改名输入）、
 *     data-wb-session-reopen（↺ 恢复菜单钮，菜单项 data-wb-session-restore）。
 *
 * t260831-06 tab 交互三修（停原地/重命名/关闭）：
 *   - 停原地：handleOpen 不再 touchEntry——lastOpenedAt 只在登记路径写（新建/
 *     blank 自愈换绑/↺ 恢复，时间单调递增=登记顺序），点 tab 不再重排，「点谁
 *     谁置顶」就此消除。排序实现保留 lastOpenedAt 降序（smoke/hero.mjs 既有
 *     断言兼容，该文件不在本单写集）。
 *   - 重命名：tab 双击进行内编辑，落账册 title 字段（renameEntry + persist），
 *     空名=恢复默认显示；localStorage 持久化，刷新后保留。
 *   - 关闭：行尾 ×（hover 才显，不占常驻宽度）→ removeEntry 剔账册 + 条目移入
 *     「最近关闭」列表（localStorage 第二键，惰性读写，cap 10）→ tab 消失；
 *     sessions 服务若有 close API 则尽力调用（现无——会话数据不删，仅剔入口，
 *     无不可恢复损失，故不做确认弹窗，规格「无未发送内容时直接关」）。
 *     重新打开走行尾 ↺ 菜单：touchEntry 重登账册 + openSession 统一链，title
 *     随条目带回（改名→关闭→重开链自定义名不丢）。主账册登记只有新建登记、
 *     blank 自愈换绑、↺ 恢复三条显式路径，无 current 自动登记 effect——关闭
 *     当前活跃会话的终态：tab 消失、current 不变（会话仍在运行），不会复活，
 *     可从 ↺ 菜单找回。
 *   - 竞态取舍：双击会先触发两次 click——onClick 里 editingId 命中即 return，
 *     编辑态不触发 open；Esc 先置 cancelRef 再 blur，onBlur 提交前查该 ref，
 *     取消不落账（每次进编辑前重置）。
 *
 * 故障模式取舍（t260831-04 gen2 修订；逐项「带/不带」理由见工单方案与实现报告）：
 *   - 新建走 ctx.workspaces.startSession（工厂同款）；workspaces 服务缺失：
 *     行内可见错误 + console.error，按钮不复位为假成功；
 *   - 工作区按项目主目录匹配（workspaceForDir：精确→前缀→realtime 归一），
 *     找不到且 projectDir 有值 → workspaces.create（host 幂等：已注册同目录
 *     返回既存工作区）；create 失败：行内提示，不落账不静默；
 *   - startSession 后 current 10s 未落定：行内提示 + warn；工作区已连接，
 *     可从列表进入；
 *   - 切换路径 sessions.open(id) 失败（throw，gen10 勘误：未列出 id 是 throw
 *     不是静默 no-op）：console.error 留痕 + 行内错误提示，账册条目保留
 *     （超时≠磁盘清理，自动 removeEntry 已删——t260831-02 的超时剔账正是
 *     「切回内容丢失」成因之一）；账册中 blank 会话条目（自铸 chat- 残留）
 *     走 startSession 换绑自愈——blank 零内容，无损失；
 *   - open 已调用但 list.current 未指向目标：warn 留痕（激活未生效线索）；
 *   - localStorage 读失败/坏 JSON：parseLedger 容错剔脏；写失败：丢持久化但
 *     本次会话内 state 仍可见（同一 hook 无第二份实现）；
 *   - 工单会话（ticket- 前缀）：isGlobalSessionId 在 touchEntry 里挡在账册外，
 *     顶部入口与账册同函数同口径，天然不混入（smoke/sessions.mjs 有断言）。
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type { ObservableSnapshot, SessionListState } from '@deepseek-ai/dsh-client-runtime/client'
// 「会话」记账层纯函数（t260828-02 项目归属+只列 UI 主动打开；smoke/sessions.mjs 直测）。
// t260831-06：removeEntry 的显式调用点=tab 关闭钮（剔账不删数据）；renameEntry=
// tab 重命名落账。借鉴模式取舍：非数组容错/未知 id 无害/不改入参/坏 JSON 不抛
// 全部沿用（取舍清单见工单实现报告）。
import {
  touchEntry,
  removeEntry,
  renameEntry,
  parseLedger,
  serializeLedger,
  pickSwitchTargets,
} from '../shared/sessions.ts'
import type { OpenedEntry } from '../shared/sessions.ts'
// 账册模块级共享 store：同页跨实例同步。persist 落盘 + 广播收口于此。
import {
  LEDGER_KEY,
  subscribeLedger,
  getLedgerSnapshot,
  persistLedger,
} from './session-ledger-store.ts'

export { LEDGER_KEY }

/**
 * 出厂「⊕ New Session」钮的语义锚（aria-label 全集）：dsh-client-ui-sidebar 的
 * `session.new.label` 词条，zh=新建会话 / en=New session（实查平台包 locale 字典，
 * 全包仅此两份）。侧栏注入 effect 以「SidebarRoot 直接子 button 且 aria-label
 * 命中本集合」定位出厂钮——零 CSS 类名匹配（t260828-06 死因不复犯）。
 * smoke/hero.mjs 对本集合有存在性断言（新增语言字典时提醒补锚）。
 */
export const FACTORY_NEW_LABELS: readonly string[] = ['新建会话', 'New session']

/* ── 「最近关闭」列表（t260831-06）：tab × 之后条目的去处，↺ 菜单的重开数据源。
 * session-ledger-store.ts 不在本单写集、其订阅机制不可复用，故此处走**惰性读写**
 * localStorage（菜单/关闭动作是离散交互，无常驻跨实例同步需求），坏 JSON 由
 * parseLedger 同款容错兜底。cap 10，同 id 重关重提头，超出淘汰最旧。 */
export const CLOSED_LEDGER_KEY = 'suyou.workbench.closedSessions'
const CLOSED_LEDGER_CAP = 10

/** 读「最近关闭」列表（localStorage → OpenedEntry[]；坏数据 parseLedger 容错）。 */
function readClosedLedger(): OpenedEntry[] {
  try {
    return parseLedger(window.localStorage.getItem(CLOSED_LEDGER_KEY))
  } catch {
    return []
  }
}

/** 写回「最近关闭」列表（写失败丢持久化但不抛——同账册 persist 取舍口径）。 */
function writeClosedLedger(entries: OpenedEntry[]): void {
  try {
    window.localStorage.setItem(CLOSED_LEDGER_KEY, serializeLedger(entries.slice(0, CLOSED_LEDGER_CAP)))
  } catch { /* 写失败：丢持久化，本次会话内 state 仍可见 */ }
}

/** 条目移入「最近关闭」（同 id 去重重提头 + cap 截断），返回新列表。 */
function pushClosedLedger(prev: OpenedEntry[], entry: OpenedEntry): OpenedEntry[] {
  const out = [entry, ...prev.filter(e => e && e.id !== entry.id)]
  return out.slice(0, CLOSED_LEDGER_CAP)
}

/** sessions 服务面（ctx.sessions 的子集；结构类型可测裸对象）。 */
export interface SessionsFace {
  open(id: string): void
  scope(id: string): any
  refresh?(): Promise<unknown>
  /** 关闭会话（可选；运行时现未提供——提供则关闭钮尽力调用，失败仅 warn）。 */
  close?(id: string): void
  list: ObservableSnapshot<SessionListState>
}

/**
 * workspaces 服务面（ctx.workspaces 的子集；IWorkspaces 公开契约的结构投影）。
 * t260831-04 gen2 取证实锤：WorkspaceBrowserInjected.open/startSession 是
 * ui-workspace 的**注册者私有注入**，slot owner props（wide/expandSidebar）里
 * 拿不到——gen0 之前代码里「slotOpen 优先」的分支恒走 sessions.open 兜底。
 * 新建的工厂同款语义在公开面 ctx.workspaces.startSession：绑工作区 + 复用
 * blank 会话 + 正确打开（staging）。
 */
export interface WorkspacesFace {
  list: ObservableSnapshot<{ items: readonly { workspaceId: string; path: string }[] }>
  startSession(workspaceId?: string): void
  create(input: { path: string }): Promise<{ workspaceId: string }>
}

/** host 侧 create 的 session 经 list 流同步到 client 有延迟——轮询等 scope 可解析（≤ms 毫秒）。
 *  ⚠️ 勘误（t260831-02 gen8）：sessions 服务头注明 scope 是「首次 open 才惰性铸造」——
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
 * 等 id 进入客户端会话列表。勘误链（t260831-02 gen10 审读订正）：open(id) 对未
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
  /** 客户端 workspaces 服务（index.tsx 的 ctx.workspaces；新建走工厂同款语义）。 */
  workspaces?: WorkspacesFace
  /** 槽注入的打开动作（WorkspaceBrowserInjected.open；由侧栏槽注入）。 */
  slotOpen?: (sessionId: string) => void
  /** 列表归属与新建落点的项目 key（空=未选项目：列表空，多项目时 + 弹项目选单）。 */
  projectKey: string
  /** 该项目主目录（注册表 primary；新建落点的工作区按它匹配/创建）。 */
  projectDir?: string
  /** 注册表项目清单（sidebar 的 /wf/projects）：多项目未选时 + 按钮弹选单选项目新建
   *  （t260903 切换夜：console 自 sandbar 起、双项目注册表下按钮曾静默禁用）。 */
  projects?: readonly { key: string; name: string; primary: string }[]
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
 * 那会把旧会话误记进账册（gen2 自测探针实锤过的 bug）。
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

/**
 * 会话入口共享 hook：账册状态 + 切换行 + 新建/打开动作。
 * <SessionTopEntry> 渲染它的返回值。
 */
export function useSessionEntry({ sessions, workspaces, slotOpen, projectKey, projectDir }: SessionEntryOptions) {
  const list = sessions.list
  const subscribe = useCallback((fn: () => void) => list.subscribe(fn), [list])
  const getSnapshot = useCallback(() => list.getSnapshot(), [list])
  const listState = useSyncExternalStore(subscribe, getSnapshot)
  // 账册：模块级共享 store——挂载时（首次 getSnapshot）从 localStorage 惰性读入
  // （坏数据 parseLedger 容错为空册）；persist 统一「更新单例 + 落盘 + 通知订阅者」。
  const ledger = useSyncExternalStore(subscribeLedger, getLedgerSnapshot)
  const persist = useCallback((entries: OpenedEntry[]) => {
    persistLedger(entries)
  }, [])
  const targets = useMemo(() => pickSwitchTargets(ledger, {
    project: projectKey,
    current: listState?.current,
    byId: listState?.byId,
  }), [ledger, projectKey, listState])
  const [creating, setCreating] = useState(false)
  /** 行内可见错误/提示（t260831-04）：open 链失败不再只打 console——用户在
   *  界面上能看见「为什么没切过去」。下一次动作或 8s 后自动清除（timer 有
   *  cleanup，见下方 effect，全终态回收）。 */
  const [entryNotice, setEntryNotice] = useState('')

  // 通知自动清除：8s 后回落，组件卸载/新通知到来前清 timer。
  useEffect(() => {
    if (!entryNotice) return
    const t = setTimeout(() => setEntryNotice(''), 8000)
    return () => clearTimeout(t)
  }, [entryNotice])

  /**
   * 打开一个已入账册的会话（t260831-04 收口：handleOpen/handleNew 共用，
   * 时序唯一实现）：refresh → waitForListed（轮询 200ms，≤10s）→
   * slotOpen || sessions.open → open 后读 list.current 自检。
   * - 超时：账册条目保留 + 行内提示，返回 false（t260831-02 的自动
   *   removeEntry 已删——超时只说明 wire 同步慢，误删=「切回丢内容」成因）；
   * - open throw（未列出 id，gen10 勘误）：console.error + 行内提示，返回 false；
   * - 成功但 current 未跟上：warn 留痕（激活未生效线索），仍返回 true——
   *   open 调用本身已生效，下一步激活是平台层时序，不在本插件能强制的面内。
   */
  const openSession = useCallback(async (id: string): Promise<boolean> => {
    setEntryNotice('')
    const listed = await waitForListed(sessions, id, 10000)
    if (!listed) {
      console.warn('[workbench] 打开会话：会话未进客户端列表（wire 同步慢或会话已被磁盘清理；账册条目保留，可稍后重试）：', id)
      setEntryNotice('会话打开超时：列表同步未完成，条目已保留，可重试')
      return false
    }
    try {
      if (slotOpen) slotOpen(id)
      else sessions.open(id)
    } catch (err) {
      console.error('[workbench] 打开会话失败：', id, err)
      setEntryNotice('会话打开失败（详情见控制台）')
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
  }, [sessions, slotOpen])

  // 切换（t260831-06：不再 touchEntry 重排——点 tab 停在原地，顺序=登记顺序），
  // 直接走 openSession 统一链。超时不剔账（见 openSession 注释）。
  // blank 自愈（t260831-04 gen2）：账册里的 blank 会话（gen1 前宿主端自铸的
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
        workspaces.startSession(ws.workspaceId)
        const staged = await waitForStaged(sessions, prev, 10000)
        if (staged && staged !== id) {
          persist(touchEntry(removeEntry(ledger, id), {
            id: staged,
            project: entry.project,
            cwd: entry.cwd,
            title: entry.title,
            lastOpenedAt: Date.now(),
          }))
        }
        return
      }
    }
    await openSession(id)
  }, [openSession, workspaces, sessions, ledger, persist, projectKey])

  // 新建（t260831-04 gen2 重写）：不再走宿主端 global-session/open 自铸会话
  // （自铸会话不绑工作区 → 平台语义「hero ⟺ blank」下永远停在 hero、内容被
  // 发到别处——仲裁 S2/S3 失败的根因）。改走 ctx.workspaces.startSession——
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
      setEntryNotice('新建会话失败：workspaces 服务不可用')
      console.error('[workbench] 新建会话失败：ctx.workspaces 未注入（index.tsx inject 列表缺 workspaces）')
      return
    }
    setCreating(true)
    setEntryNotice('')
    try {
      let ws = workspaceForDir(workspaces.list.getSnapshot()?.items ?? [], pd ?? '')
      if (!ws && pd) {
        ws = await workspaces.create({ path: pd }).then(w => ({ ...w, path: pd })).catch((err: unknown) => {
          console.error('[workbench] 新建会话失败：工作区创建失败：', pd, err)
          setEntryNotice('新建会话失败：工作区创建失败（详情见控制台）')
          return undefined
        })
      }
      if (!ws) {
        console.error('[workbench] 新建会话失败：项目无对应工作区且无法创建：', pk, pd)
        setEntryNotice('新建会话失败：项目主目录未注册为工作区')
        return
      }
      workspaces.startSession(ws.workspaceId)
      const prev = (() => { try { return (sessions.list.getSnapshot()?.current as string | undefined) ?? null } catch { return null } })()
      const staged = await waitForStaged(sessions, prev, 10000)
      if (!staged) {
        console.warn('[workbench] 新建会话：staging 未落定（current 未更新）；工作区已连接，可从列表进入：', ws.workspaceId)
        setEntryNotice('会话打开超时：列表同步未完成，可重试')
        return
      }
      persist(touchEntry(ledger, {
        id: staged,
        project: pk,
        cwd: pd ?? '',
        lastOpenedAt: Date.now(),
      }))
    } catch (err) {
      console.error('[workbench] 新建会话请求异常：', err)
      setEntryNotice('新建会话失败：请求异常（详情见控制台）')
    } finally {
      setCreating(false)
    }
  }, [workspaces, sessions, projectKey, projectDir, creating, ledger, persist])

  /* ── tab 关闭 / 重开（t260831-06）──
   * 关闭=removeEntry 剔账册（tab 消失）+ 条目移入「最近关闭」列表 + 尽力调
   * sessions.close?（运行时现无——会话数据不删，仅剔入口，无不可恢复损失，
   * 故不做确认弹窗）。重开=↺ 菜单 touchEntry 重登（title 随条目带回，头插=
   * 登记顺序最新）+ openSession 统一链 + 从「最近关闭」移除。 */
  const [closedList, setClosedList] = useState<OpenedEntry[]>(() => readClosedLedger())

  const handleClose = useCallback((id: string) => {
    const entry = ledger.find(e => e.id === id)
    persist(removeEntry(ledger, id))
    if (entry) {
      // push 后立即落盘（t260831-06 验收打回归因：漏这行是双故障——刷新丢「最近
      // 关闭」列表；且 ↺ effect 从空 localStorage 读回 [] → wrap 自卸载，菜单
      // 永远打不开，重开必经路径必挂）
      const next = pushClosedLedger(readClosedLedger(), entry)
      writeClosedLedger(next)
      setClosedList(next)
    }
    if (typeof sessions.close === 'function') {
      try { sessions.close(id) } catch (err) {
        console.warn('[workbench] 关闭会话：sessions.close 调用失败（入口已剔除，会话数据不受影响）：', id, err)
      }
    }
  }, [ledger, persist, sessions])

  const handleReopen = useCallback(async (id: string) => {
    const entry = closedList.find(e => e.id === id)
    if (!entry) return
    writeClosedLedger(closedList.filter(e => e.id !== id))
    setClosedList(closedList.filter(e => e.id !== id))
    persist(touchEntry(ledger, {
      id: entry.id,
      project: entry.project || projectKey,
      cwd: entry.cwd,
      title: entry.title,
      lastOpenedAt: Date.now(),
    }))
    await openSession(entry.id)
  }, [closedList, ledger, persist, projectKey, openSession])

  // 从 localStorage 刷新，但与内存态**合并而非裸覆盖**（防同类自毁：若磁盘读回
  // 空而内存仍有——如写失败丢持久化——不把 ↺ 钮连带菜单整个卸掉；磁盘序优先，
  // 内存独有的条目追加在后）。
  const refreshClosedList = useCallback(() => setClosedList(prev => {
    const disk = readClosedLedger()
    const ids = new Set(disk.map(e => e.id))
    return [...disk, ...prev.filter(e => !ids.has(e.id))].slice(0, CLOSED_LEDGER_CAP)
  }), [])

  return { ledger, targets, creating, entryNotice, handleNew, handleOpen, handleClose, handleReopen, closedList, refreshClosedList, listState }
}

/**
 * 顶部紧凑一行会话入口（t260831-02 建；t260831-06 tab 三修：div 行 + 双击改名
 * + hover 关闭钮 + ↺ 恢复菜单）。由 sidebar.tsx 挂在 .wb-sb-left 顶部——
 * 视觉位置=deepseek logo 正下方，即出厂「⊕ New Session」行被注入 effect 隐藏后
 * 让出的原位（整行原地替换）。新建落点=当前视图项目；未选时单项目注册表兜底，
 * 多项目未选禁用并提示（不造隐形缺省）。
 * 渲染类名 .wb-sessTop-* 全部 wb- 前缀，与出厂类名零交叉。
 * 本组件新增样式随组件注入 <style>（sidebar.tsx 不在本单写集，故新样式收在本
 * 文件）。
 */
const SESSION_ENTRY_STYLES = `
.wb-sessTop-tab { display:inline-flex; align-items:center; gap:2px; min-width:0; }
.wb-sessTop-close { flex:none; opacity:0; font:inherit; font-size:10px; line-height:1;
  padding:1px 3px; border:none; border-radius:3px; background:none; color:#f87171;
  cursor:pointer; }
.wb-sessTop-tab:hover .wb-sessTop-close, .wb-sessTop-close:focus-visible { opacity:1; }
.wb-sessTop-close:hover { background:rgba(248,113,113,0.18); }
.wb-sessTop-rename { font:inherit; font-size:11.5px; width:110px; padding:1px 4px;
  border-radius:3px; border:1px solid rgba(124,58,237,0.6);
  background:rgba(0,0,0,0.3); color:var(--dsw-alias-label-primary,#e0e0e0); outline:none; }
.wb-sessTop-reopen-wrap { position:relative; flex:none; }
.wb-sessTop-reopen { font:inherit; font-size:11px; padding:1px 5px; border-radius:4px;
  border:1px solid rgba(255,255,255,0.18); background:none;
  color:var(--dsw-alias-label-secondary,#b8b8c8); cursor:pointer; }
.wb-sessTop-reopen:hover { background:rgba(255,255,255,0.08);
  color:var(--dsw-alias-label-primary,#e0e0e0); }
.wb-sessTop-menu { position:absolute; top:100%; right:0; margin-top:4px; z-index:30;
  min-width:150px; max-height:220px; overflow-y:auto; padding:4px; border-radius:6px;
  background:#1e1e24; border:1px solid rgba(255,255,255,0.15);
  box-shadow:0 4px 16px rgba(0,0,0,0.5); }
.wb-sessTop-menu button { display:block; width:100%; text-align:left; font:inherit;
  font-size:11.5px; padding:4px 8px; border:none; border-radius:4px; background:none;
  color:var(--dsw-alias-label-primary,#d0d0d8); cursor:pointer; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.wb-sessTop-menu button:hover { background:rgba(255,255,255,0.08); }
`

/**
 * tab 行内组件（t260831-06）：div[role=button]（button 嵌 button 非法 HTML，
 * 行内要容纳改名 input 与关闭钮）；data-wb-session-row 锚名保留（smoke/hero.mjs
 * 源文本断言）。单击/Enter/Space=open（编辑态除外）；双击=改名；×=关闭。
 */
function SessionTab({ target, editing, draftTitle, onOpen, onClose, onEditStart, onDraftChange, onEditDone, onEditCancel }: {
  target: { id: string; title: string; cwd: string; active: boolean }
  editing: boolean
  draftTitle: string
  onOpen: () => void
  onClose: () => void
  onEditStart: () => void
  onDraftChange: (v: string) => void
  onEditDone: () => void
  onEditCancel: () => void
}) {
  const cancelRef = useRef(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    if (editing) {
      cancelRef.current = false
      inputRef.current?.select()
    }
  }, [editing])
  if (editing) {
    return (
      <span className="wb-sessTop-tab" data-wb-session-row="" data-active={target.active} data-editing="true">
        <input
          ref={inputRef}
          className="wb-sessTop-rename"
          data-wb-session-rename=""
          value={draftTitle}
          autoFocus
          onClick={e => e.stopPropagation()}
          onChange={e => onDraftChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault()
              inputRef.current?.blur() // blur 统一走提交路径
            } else if (e.key === 'Escape') {
              // 先置取消标记再 blur：onBlur 提交前查该 ref，取消不落账
              cancelRef.current = true
              inputRef.current?.blur()
            }
          }}
          onBlur={() => {
            if (cancelRef.current) { cancelRef.current = false; onEditCancel() }
            else onEditDone()
          }}
        />
      </span>
    )
  }
  return (
    <div
      className="wb-sessTop-row wb-sessTop-tab"
      data-wb-session-row=""
      data-active={target.active}
      role="button"
      tabIndex={0}
      title={`${target.title}\n${target.id}${target.cwd ? `\n${target.cwd}` : ''}`}
      onClick={onOpen}
      onDoubleClick={onEditStart}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() }
      }}
    >
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{target.title}</span>
      <button
        type="button"
        className="wb-sessTop-close"
        data-wb-session-close=""
        title="关闭该会话入口（不删除会话内容，可从 ↺ 重新打开）"
        aria-label={`关闭会话入口 ${target.title}`}
        onClick={e => { e.stopPropagation(); onClose() }}
      >×</button>
    </div>
  )
}

export function SessionTopEntry({ sessions, workspaces, slotOpen, projectKey, projectDir, projects }: SessionEntryOptions) {
  const {
    ledger, targets, creating, entryNotice, handleNew, handleOpen, handleClose, handleReopen,
    closedList, refreshClosedList,
  } = useSessionEntry({ sessions, workspaces, slotOpen, projectKey, projectDir })
  const persist = useCallback((entries: OpenedEntry[]) => persistLedger(entries), [])

  // 重命名编辑态：editingId + 草稿；cancelRef 在 SessionTab 内（Esc 时序见该组件注释）。
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  const startEdit = useCallback((t: { id: string; title: string }) => {
    setEditingId(t.id)
    setDraftTitle(t.title)
  }, [])

  const commitEdit = useCallback((id: string) => {
    persist(renameEntry(ledger, id, draftTitle))
    setEditingId(null)
  }, [ledger, draftTitle, persist])

  const cancelEdit = useCallback(() => setEditingId(null), [])

  // ↺ 恢复菜单：打开时惰性刷新「最近关闭」列表；点外/Escape 收起（listener 有
  // cleanup，全终态回收）。
  const [reopenOpen, setReopenOpen] = useState(false)
  const reopenWrapRef = useRef<HTMLDivElement | null>(null)
  const projectClosed = useMemo(
    () => closedList.filter(e => e && e.project === projectKey),
    [closedList, projectKey],
  )
  useEffect(() => {
    if (!reopenOpen) return
    refreshClosedList()
    const onDocDown = (e: globalThis.MouseEvent) => {
      if (reopenWrapRef.current && !reopenWrapRef.current.contains(e.target as Node)) setReopenOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setReopenOpen(false) }
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [reopenOpen, refreshClosedList])

  // 项目选单（t260903 切换夜）：多项目注册表 + 未选项目时，+ 按钮不再禁用，
  // 点开弹注册表项目选单——选中的项目主目录即新建落点（未注册工作区自动 create，
  // 与点票后新建同一链）。点外/Escape 收起（与 ↺ 菜单同模式）。
  const pickerChoices = !projectKey && (projects?.length ?? 0) > 0 ? projects! : null
  const [projOpen, setProjOpen] = useState(false)
  const projWrapRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!projOpen) return
    const onDocDown = (e: globalThis.MouseEvent) => {
      if (projWrapRef.current && !projWrapRef.current.contains(e.target as Node)) setProjOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setProjOpen(false) }
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [projOpen])

  const newDisabled = creating || (!projectKey && !pickerChoices)
  return (
    <div className="wb-sessTop" data-wb-session-entry="">
      <style>{SESSION_ENTRY_STYLES}</style>
      {/* 行首：新建（紧凑按钮）；其后：会话切换行（≤5，项目归属，active 高亮，登记顺序）。
          多项目未选：+ 变选单触发器（t260903 切换夜，选项目即落点）。 */}
      <div className="wb-sessTop-reopen-wrap" ref={projWrapRef}>
        <button
          type="button"
          className={`wb-sessTop-new ${newDisabled ? 'disabled' : ''}`}
          data-wb-session-new=""
          disabled={newDisabled}
          title={projectKey ? '新建会话（落在当前项目主目录）' : pickerChoices ? '新建会话（选择项目主目录）' : '先在左侧点选一个项目'}
          onClick={() => { if (pickerChoices) setProjOpen(v => !v); else handleNew() }}
        >{creating ? '新建中…' : '+ 新建会话'}</button>
        {projOpen && pickerChoices && (
          <div className="wb-sessTop-menu" role="menu" style={{ left: 0, right: 'auto' }}>
            {pickerChoices.map(p => (
              <button
                key={p.key}
                type="button"
                role="menuitem"
                data-wb-session-project-pick=""
                title={p.primary}
                onClick={() => { setProjOpen(false); handleNew({ key: p.key, dir: p.primary }) }}
              >{p.name || p.key}　<span style={{ opacity: 0.55 }}>{p.key}</span></button>
            ))}
          </div>
        )}
      </div>
      <div className="wb-sessTop-rows">
        {targets.length === 0 ? (
          <span className="wb-sessTop-empty">{projectKey ? '暂无最近会话' : '先点选一个项目'}</span>
        ) : targets.map(t => (
          <SessionTab
            key={t.id}
            target={t}
            editing={editingId === t.id}
            draftTitle={draftTitle}
            onOpen={() => { if (editingId === null) handleOpen(t.id) }}
            onClose={() => { if (editingId === null) handleClose(t.id) }}
            onEditStart={() => startEdit(t)}
            onDraftChange={setDraftTitle}
            onEditDone={() => { if (editingId === t.id) commitEdit(t.id) }}
            onEditCancel={cancelEdit}
          />
        ))}
      </div>
      {/* ↺ 恢复菜单（t260831-06）：「最近关闭」非空时显示，重开=重登账册+打开 */}
      {projectKey && projectClosed.length > 0 && (
        <div className="wb-sessTop-reopen-wrap" ref={reopenWrapRef}>
          <button
            type="button"
            className="wb-sessTop-reopen"
            data-wb-session-reopen=""
            aria-haspopup="menu"
            aria-expanded={reopenOpen}
            title={`重新打开最近关闭的会话入口（${projectClosed.length} 个）`}
            onClick={() => setReopenOpen(v => !v)}
          >↺ {projectClosed.length}</button>
          {reopenOpen && (
            <div className="wb-sessTop-menu" role="menu">
              {projectClosed.map(e => (
                <button
                  key={e.id}
                  type="button"
                  role="menuitem"
                  data-wb-session-restore=""
                  title={e.id}
                  onClick={() => { setReopenOpen(false); handleReopen(e.id) }}
                >{e.title || e.id}</button>
              ))}
            </div>
          )}
        </div>
      )}
      {/* 打开/新建失败（超时/throw/服务端报错）的行内可见反馈：不挡入口行布局，
          出现时独占一行，8s 自动清除（timer 有 cleanup）。 */}
      {entryNotice !== '' && (
        <span className="wb-sessTop-notice" data-wb-session-notice="" role="status">{entryNotice}</span>
      )}
    </div>
  )
}
