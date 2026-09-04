/**
 * suyou-workbench · 项目内会话区（session-entry 第 3 面①，R1–R6）。
 *
 * 口径真源 notes/epics/session-entry.md（R1–R6 + 拍板 1/2/3）：
 *   - R1 位置：左栏项目组头之下、工单列表之上，一横排；随项目组折叠整体隐藏
 *     （挂载点在 sidebar.tsx 的 !collapsed 分支内，折叠=整组收起同隐）。
 *   - R2 形态：正方形「+」钮 + 正方形数字 tab（编号=项目内登记顺序 seq，关闭
 *     不回收，序列可有洞）；数量不限（无 limit），超宽 flex-wrap 换行不横滚。
 *   - R3 新建：onNew → useSessionEntry 的 handleNew({key,dir}) 工厂同款链
 *     （绑工作区+复用 blank+正确打开），落点=本组项目主目录。
 *   - R4 切换：点 tab → handleOpen 统一链（平台单 current 语义）。
 *   - R5 关闭：关闭钮 → 轻量确认弹层（插件内，不用原生 confirm），文案含编号
 *     与标题、明示「仅关闭入口不删内容」；确认走既有 handleClose（剔入口+入
 *     最近关闭，不删会话数据）；取消不动。
 *   - R6 高亮：active = id === current（与顶部行同源；current 全局唯一 → 至多
 *     一个 tab 高亮；current 为工单/未入账会话时全不亮）。
 *
 * 数据：账册按 project 过滤消费（pickProjectTabs 纯函数，shared/sessions.ts）；
 * 本组件零 IO、零出厂 DOM 接触——动作全部由 sidebar.tsx 的 useSessionEntry
 * 二号实例注入（账册=模块级共享 store，两实例同帧一致）。
 *
 * 确认弹层定位（review C1 修订；旧恢复菜单已随票② R8 退役，定位模式沿革记此）：
 * 旧恢复菜单挂在 .wb-sb-left（无滚动祖先，absolute 自由溢出）；本行挂在 .wb-ticket-list 内
 * （overflow-y:auto 滚动容器——CSS 一轴 auto 另一轴计算为 auto，absolute 弹层
 * 会被裁剪）。故弹层走 position:fixed 脱离滚动容器裁剪 + 视口钳制（左右不出界、
 * 底部放不下向上翻），列表滚动时经 capture scroll 监听跟随锚重摆。点外/Esc
 * 收起（document listener，effect cleanup 全终态回收——正常收起/卸载/换确认
 * 目标三条路径都摘干净）。
 *
 * 语义锚（smoke/project-sessions.mjs 源文本断言面）：data-wb-psess-row（根）、
 * data-wb-psess-new（+ 钮）、data-wb-psess-tab[data-active]（tab）、
 * data-wb-psess-close（tab 关闭钮）、data-wb-psess-confirm（确认弹层）、
 * data-wb-psess-confirm-ok / -confirm-cancel（确认/取消）、
 * data-wb-psess-notice（行内失败提示）。零 CSS 类名匹配纪律（自有 .wb-psess-*
 * 前缀，与出厂类名零交叉）。
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { pickProjectTabs } from '../shared/sessions.ts'
import type { OpenedEntry, TitleRowLike } from '../shared/sessions.ts'
// 项目色（票② R7）：确定性色板 + hex→rgba 展开（hover 淡底，避免 color-mix 赌注）。
import { projectColor } from '../shared/project-color.ts'
import { hexToRgba } from './chat-project-band.ts'

/** 项目内会话区行 props（动作由 sidebar 的 useSessionEntry 二号实例注入）。 */
export interface ProjectSessionRowProps {
  /** 本组项目 key（账册过滤键）。 */
  projectKey: string
  /** 项目显示名（弹层/提示文案用）。 */
  projectName: string
  /** 该项目主目录（+ 钮 tooltip 展示落点；新建动作由父级闭包绑定）。 */
  projectDir: string
  /** 账册快照（模块级共享 store 的引用；缺 seq 条目经挂载 effect 已迁移）。 */
  ledger: OpenedEntry[]
  /** 右栏当前会话 id（ctx.sessions.list.current；高亮源）。 */
  current?: string
  /** 会话标题表（ctx.sessions.list.byId；title 三级兜底中间层）。 */
  byId?: Record<string, TitleRowLike | undefined>
  /** 新建进行中（+ 钮防双击）。 */
  creating: boolean
  /** 行内失败提示（hook 的 entryNotice）。 */
  notice: string
  /** 提示归属项目（非本项目不显示，避免 N 个项目组重复同一条全局噪音）。 */
  noticeProject?: string
  /** 新建（handleNew({key,dir})，落点=本组项目主目录）。 */
  onNew: () => void
  /** 切换（handleOpen 统一链）。 */
  onOpen: (id: string) => void
  /** 关闭（确认后调用；handleClose=剔入口+入最近关闭，不删数据）。 */
  onClose: (id: string) => void
}

/* 自有样式（随组件 <style> 注入；.wb-psess-* 前缀与出厂类名零交叉）。
 * 正方形：+ 钮与 tab 显式 box-sizing:border-box + 24×24 基准（shell 无全局
 * border-box 重置，content-box 下 padding/border 会外扩成 28×24——隔离台
 * DOM 断言实锤后修正）；两位数以上数字可读优先微加宽（min-width 允许内容
 * 撑开，拍板验收口径「正方形小块」以单数字位为基准形态）。关闭钮 hover 才显
 * （absolute 右上角，不占常驻宽度）。换行：行容器 flex-wrap:wrap，无
 * overflow-x（不横滚，拍板 2）。 */
const PSESS_STYLES = `
.wb-psess { display:flex; flex-wrap:wrap; align-items:center; gap:4px;
  padding:4px 8px 4px 20px; border-bottom:1px solid rgba(255,255,255,0.04); }
/* 项目色（票② R7 拍板 5）：色源=--wb-psess-color（根节点 inline 注入，
 * 值=projectColor(projectKey) 确定性色板）；淡底由 JS 用同色 16% 透明展开。 */
.wb-psess-new { box-sizing:border-box; width:24px; height:24px; flex:none;
  display:flex; align-items:center; justify-content:center; font:inherit;
  font-size:13px; line-height:1; padding:0; border-radius:4px;
  border:1px solid var(--wb-psess-color, rgba(255,255,255,0.25)); background:none;
  color:var(--wb-psess-color, var(--dsw-alias-label-primary,#e0e0e0)); cursor:pointer; }
.wb-psess-new:hover:not(:disabled) { background:var(--wb-psess-hover, rgba(255,255,255,0.1)); }
.wb-psess-new:disabled { opacity:0.4; cursor:default; }
.wb-psess-tab { box-sizing:border-box; position:relative; min-width:24px;
  height:24px; flex:none; display:inline-flex; align-items:center;
  justify-content:center; padding:0 3px; border-radius:4px;
  border:1px solid transparent; background:none;
  color:var(--dsw-alias-label-secondary,#b8b8c8); font:inherit; font-size:11.5px;
  cursor:pointer; }
.wb-psess-tab:hover { background:rgba(255,255,255,0.08);
  color:var(--dsw-alias-label-primary,#e0e0e0); }
.wb-psess-tab.active { background:var(--wb-psess-hover, rgba(255,255,255,0.10));
  border-color:var(--wb-psess-color, rgba(255,255,255,0.4));
  color:var(--wb-psess-color, var(--dsw-alias-label-primary,#e0e0e0)); }
.wb-psess-num { line-height:1; font-family:var(--ds-font-family-code,monospace); }
.wb-psess-close { position:absolute; top:-5px; right:-5px; width:12px; height:12px;
  display:flex; align-items:center; justify-content:center; padding:0; font:inherit;
  font-size:9px; line-height:1; border:none; border-radius:3px; background:none;
  color:#f87171; cursor:pointer; opacity:0; }
.wb-psess-tab:hover .wb-psess-close, .wb-psess-close:focus-visible { opacity:1; }
.wb-psess-close:hover { background:rgba(248,113,113,0.18); }
.wb-psess-notice { flex-basis:100%; font-size:10.5px; color:#f59e0b; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.wb-psess-confirm { position:fixed; z-index:97; min-width:200px; max-width:280px;
  padding:8px 10px; border-radius:8px; background:#1e1e24;
  border:1px solid rgba(255,255,255,0.15); box-shadow:0 8px 24px rgba(0,0,0,0.5);
  display:flex; flex-direction:column; gap:5px; }
.wb-psess-confirm-t { font-size:12px; font-weight:600; }
.wb-psess-confirm-d { font-size:11px; color:#b8b8c8; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.wb-psess-confirm-m { font-size:10.5px; color:#8c959f; }
.wb-psess-confirm-btns { display:flex; gap:6px; justify-content:flex-end; }
.wb-psess-confirm-btns button { font:inherit; font-size:11px; padding:2px 10px;
  border-radius:4px; cursor:pointer; border:1px solid rgba(255,255,255,0.2);
  background:none; color:var(--dsw-alias-label-primary,#e0e0e0); }
.wb-psess-confirm-btns button:hover { background:rgba(255,255,255,0.08); }
.wb-psess-confirm-btns .wb-psess-confirm-ok { border-color:rgba(248,113,113,0.6);
  color:#f87171; }
.wb-psess-confirm-btns .wb-psess-confirm-ok:hover { background:rgba(248,113,113,0.15); }
`

/**
 * 一横排项目会话区：+ 钮 + 数字 tab 行 +（有确认目标时）确认弹层 + 行内提示。
 * 纯展示/交互组件，状态只有 confirmId（哪个 tab 在等确认）。
 */
export function ProjectSessionRow(props: ProjectSessionRowProps) {
  const {
    projectKey, projectName, projectDir, ledger, current, byId,
    creating, notice, noticeProject, onNew, onOpen, onClose,
  } = props
  const tabs = useMemo(
    () => pickProjectTabs(ledger, { project: projectKey, current, byId }),
    [ledger, projectKey, current, byId],
  )

  /* ── 确认弹层（R5）：confirmId=等确认的 tab；弹层 position:fixed（见文件头注）── */
  const [confirmId, setConfirmId] = useState<string | null>(null)
  /** 正在确认的 tab 锚（ref 回调按 confirmId 条件挂到对应 tab 上）。 */
  const tabRef = useRef<HTMLDivElement | null>(null)
  const popRef = useRef<HTMLDivElement | null>(null)

  /** 摆位：锚矩形 → 视口钳制（左右不出界）+ 底部放不下向上翻。 */
  const place = useCallback(() => {
    const pop = popRef.current
    const anchor = tabRef.current
    if (!pop || !anchor) return
    const r = anchor.getBoundingClientRect()
    const w = pop.offsetWidth
    const h = pop.offsetHeight
    const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8))
    const below = r.bottom + 4
    const top = below + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 4) : below
    pop.style.left = `${left}px`
    pop.style.top = `${top}px`
  }, [])

  // 弹层刚挂载时先量尺寸再摆位（layout 阶段，避免闪现在默认位置）。
  useLayoutEffect(() => {
    if (confirmId !== null) place()
  }, [confirmId, place, tabs])

  // 点外/Esc 收起 + 列表滚动跟随（capture：滚动容器是 .wb-ticket-list 非
  // document）。listener 全终态回收：确认提交/取消/点外/Esc/组件卸载都走
  // setConfirmId(null) 或卸载 cleanup，本 effect return 统一摘干净。
  useEffect(() => {
    if (confirmId === null) return
    const onDocDown = (e: globalThis.MouseEvent) => {
      const t = e.target as Node | null
      if (t && (popRef.current?.contains(t) || tabRef.current?.contains(t))) return
      setConfirmId(null)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setConfirmId(null) }
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('keydown', onKey)
    document.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('mousedown', onDocDown)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('scroll', place, true)
    }
  }, [confirmId, place])

  const confirmTab = confirmId === null ? null : tabs.find(t => t.id === confirmId) ?? null
  // 行内提示只显示本项目归属的（无归属信息时照常显示，保守不静默）。
  const showNotice = notice !== '' && (noticeProject === undefined || noticeProject === projectKey)

  // 项目色（票② R7）：色值与 16% 透明淡底由根节点 CSS 变量下发（激活 tab /
  // + 钮边框文字 / hover 底色统一消费；色板=projectColor 确定性，同 key 恒同色）。
  const color = projectColor(projectKey)
  const colorVars = {
    '--wb-psess-color': color,
    '--wb-psess-hover': hexToRgba(color, 0.16),
  } as CSSProperties

  return (
    <div className="wb-psess" data-wb-psess-row="" style={colorVars}>
      <style>{PSESS_STYLES}</style>
      <button
        type="button"
        className="wb-psess-new"
        data-wb-psess-new=""
        disabled={creating}
        title={`新建 ${projectName} 会话（主目录${projectDir ? `：${projectDir}` : ''}）`}
        aria-label={`新建 ${projectName} 会话`}
        onClick={onNew}
      >+</button>
      {tabs.map(t => (
        <div
          key={t.id}
          ref={confirmId === t.id ? tabRef : undefined}
          className={`wb-psess-tab ${t.active ? 'active' : ''}`}
          data-wb-psess-tab=""
          data-active={t.active}
          role="button"
          tabIndex={0}
          title={`${projectName} 会话 ${t.seq}：${t.title}\n${t.id}`}
          onClick={() => { setConfirmId(null); onOpen(t.id) }}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setConfirmId(null)
              onOpen(t.id)
            }
          }}
        >
          <span className="wb-psess-num">{t.seq}</span>
          <button
            type="button"
            className="wb-psess-close"
            data-wb-psess-close=""
            title="关闭该会话入口（需确认；不删除会话内容）"
            aria-label={`关闭会话入口 ${t.seq}`}
            onClick={e => { e.stopPropagation(); setConfirmId(t.id) }}
          >×</button>
        </div>
      ))}
      {confirmTab && (
        <div
          className="wb-psess-confirm"
          data-wb-psess-confirm=""
          role="dialog"
          aria-label="关闭会话入口确认"
          ref={popRef}
        >
          <div className="wb-psess-confirm-t">关闭会话 {confirmTab.seq}？</div>
          <div className="wb-psess-confirm-d" title={confirmTab.title}>{confirmTab.title}</div>
          <div className="wb-psess-confirm-m">仅关闭入口，不删除会话内容。</div>
          <div className="wb-psess-confirm-btns">
            <button
              type="button"
              className="wb-psess-confirm-cancel"
              data-wb-psess-confirm-cancel=""
              onClick={() => setConfirmId(null)}
            >取消</button>
            <button
              type="button"
              className="wb-psess-confirm-ok"
              data-wb-psess-confirm-ok=""
              onClick={() => { setConfirmId(null); onClose(confirmTab.id) }}
            >关闭</button>
          </div>
        </div>
      )}
      {showNotice && (
        <span className="wb-psess-notice" data-wb-psess-notice="" role="status">{notice}</span>
      )}
    </div>
  )
}
