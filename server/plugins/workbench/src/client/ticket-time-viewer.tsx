/**
 * ticket-time-viewer.tsx —— 「本票时刻 · 只读」文件查看器弹层（t260915-17，
 * 260904 详情 mock 标注 D 落地；查看器样张=notes-ui mock 屏②「UI 内查看器（只读）」）。
 *
 * 数据源=宿主半 GET /sandbar-workbench/api/wf/tickets/<id>/file?path=&mode=
 * （node.ts handleTicketTimeFile；settle=收口版 / base=开票基点版 / current=当前版）。
 *
 * 版面（mock D 原话）：顶部横幅「🕰 本票时刻 · 只读」+版本副文案（ref 短哈希+来源标签）
 * +「跳到当前版」小链——点击切 current 口径重取内容且横幅消失（横幅消失=切到当前版的
 * 可见信号，验收口径①）。渲染：.md 走 knowledge renderMarkdown（docs.tsx 同款复用，
 * 转义先行/危险 URL 拒绝随 import 带入），其余文件等宽纯文本。只读刚性：本组件源码
 * 层面不引入任何编辑/保存控件（无 input/textarea/contentEditable/保存钮），集成场景
 * 源码锁直断（sc_ticket_time_file）。
 *
 * 故障模式取舍清单（review C6，对照先例逐项声明带/不带）：
 *   - EvidenceLightbox 的 document 级 keydown + isEditableTarget guard：**带**（详情
 *     抽屉含输入件，Esc 关闭复用同款 guard 防误关；isEditableTarget 在 index.tsx 不
 *     导出且 import 会成环，此处本地复刻同款 8 行并注释互指）。
 *   - EvidenceLightbox 的 evidenceNav 越界兜底：**不带**——查看器单文件无左右导航，
 *     无越界面可兜。
 *   - 单图加载失败占位：**带**（同语义=人话 reason 面板/加载失败条，不拖垮抽屉）。
 *   - handleDocsDoc 的 200+{empty,reason} 人话降级：**带**（同风格——fail-closed 的
 *     reason 面板走正常响应渲染，不 500）。
 *   - t01 临时真 git 仓 fixture 手法：**带**（tests/t260915-17-ticket-time-file.mjs
 *     同款 mkdtemp+rmSync+git timeout）。
 *
 * 资源终态：in-flight fetch 由 AbortController 收口（mode/path/卸载任一变化即 abort
 * 前次）；document keydown 挂载/卸载成对（useEffect cleanup 单点回收）；无定时器/
 * 轮询/长驻句柄，正常、报错、取消三路径都落定。
 */
import { useEffect, useRef, useState } from 'react'
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import {
  buildTicketTimeBanner, isTicketTimeMode,
  type TicketTimeMode,
} from '../shared/ticket-time-model.ts'

const API_PREFIX = '/sandbar-workbench/api/wf/tickets'

/** 契约锚（集成场景/UT 断言用；不可移除/改名）。 */
export const TICKET_TIME_VIEWER_TESTID = 'ticket-time-viewer'
export const TICKET_TIME_BANNER_TESTID = 'ticket-time-banner'
export const TICKET_TIME_FAIL_TESTID = 'ticket-time-fail'
export const TICKET_TIME_JUMP_TESTID = 'ticket-time-jump-current'

interface FileResult {
  ok?: boolean
  reason?: string
  content?: string
  path?: string
  mode?: string
  refShort?: string
  refSource?: string
  truncated?: boolean
}

/** 与 index.tsx isEditableTarget 同款（C6：复用语义、本地复刻防 import 环）。 */
function isEditableTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT'
    || t.isContentEditable
}

export interface TicketTimeViewerProps {
  ticketId: string
  path: string
  /** 打开时的时刻口径（状态卡/diff 行=settle；背景引用=base；「跳到当前版」后内部切 current）。 */
  initialMode: TicketTimeMode
  onClose: () => void
}

export function TicketTimeViewer({ ticketId, path, initialMode, onClose }: TicketTimeViewerProps) {
  const [mode, setMode] = useState<TicketTimeMode>(initialMode)
  const [data, setData] = useState<FileResult | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  // 拉取：mode/path/ticket 任一变化即重取并 abort 前次（资源终态单点）。
  useEffect(() => {
    const ac = new AbortController()
    abortRef.current?.abort()
    abortRef.current = ac
    setData(null)
    setLoadErr('')
    fetch(`${API_PREFIX}/${encodeURIComponent(ticketId)}/file?path=${encodeURIComponent(path)}&mode=${mode}`, { signal: ac.signal })
      .then((r) => r.json())
      .then((d) => { if (!ac.signal.aborted) setData((d?.result ?? null) as FileResult | null) })
      .catch((err) => {
        if (ac.signal.aborted) return
        setLoadErr(String(err instanceof Error ? err.message : err))
      })
    return () => { ac.abort() }
  }, [ticketId, path, mode])
  useEffect(() => () => { abortRef.current?.abort() }, [])

  // Esc 关闭（editable guard 防「输入框打字误关」；挂 document 级——fixed 遮罩同灯箱理由）。
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isEditableTarget(e.target)) { e.preventDefault(); onClose() }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  // 畸形响应软降级（消费外部输入纪律）：result 非对象/mode 畸形一律按「读取失败」面板。
  const resOk = data?.ok === true
    && typeof data.content === 'string'
    && isTicketTimeMode(data.mode)
  const banner = resOk && data !== null
    ? buildTicketTimeBanner(mode, (data.refSource as never) ?? 'base-ref', data.refShort)
    : null
  const isMd = /\.md$/i.test(path)

  return (
    <div
      className="wb-ttv-mask"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="wb-ttv" data-testid={TICKET_TIME_VIEWER_TESTID} role="dialog" aria-label={`本票时刻只读查看 ${path}`}>
        <div className="wb-ttv-head">
          <code className="wb-ttv-path">{path}</code>
          <button className="wb-ttv-close" aria-label="关闭查看器" onClick={onClose}>✕</button>
        </div>
        {banner !== null && (
          <div className="wb-ttv-banner" data-testid={TICKET_TIME_BANNER_TESTID}>
            <span className="wb-ttv-banner-text">{banner.text}</span>
            <span className="wb-ttv-banner-ver">{banner.version}</span>
            {banner.canJumpCurrent && (
              <button
                className="wb-ttv-jump"
                data-testid={TICKET_TIME_JUMP_TESTID}
                onClick={() => setMode('current')}
              >跳到当前版</button>
            )}
          </div>
        )}
        {loadErr !== '' && <div className="wb-ttv-fail" data-testid={TICKET_TIME_FAIL_TESTID}>读取失败：{loadErr}</div>}
        {loadErr === '' && data === null && <div className="wb-ttv-loading">读取中…</div>}
        {loadErr === '' && data !== null && data.ok === false && (
          <div className="wb-ttv-fail" data-testid={TICKET_TIME_FAIL_TESTID}>
            <div className="wb-ttv-fail-ttl">拿不到本票时刻的这个版本</div>
            {data.reason ?? '原因未知'}
          </div>
        )}
        {loadErr === '' && resOk && (
          isMd
            ? <div className="wb-ttv-body wb-doc-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(String(data?.content ?? '')) }} />
            : <pre className="wb-ttv-body wb-ttv-code">{data?.content}{data?.truncated === true ? '\n\n（内容超封顶已截断——此处不是完整文件，完整内容走 git show）' : ''}</pre>
        )}
        {loadErr === '' && resOk && data?.truncated === true && isMd && (
          <div className="wb-ttv-trunc">内容超封顶已截断——此处不是完整文件，完整内容走 git show。</div>
        )}
      </div>
    </div>
  )
}
