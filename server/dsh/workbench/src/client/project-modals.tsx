/**
 * project-modals.tsx —— 项目生命周期四弹层（project-lifecycle 票③面D，验收 11-13）。
 *
 * 入口（sidebar.tsx 接线）：组头第五枚「项目设置」图标（滑杆）→ ProjectSettingsModal
 * （只读信息 + 票计数 + 体检占位 + danger 区）；danger 区「摘除项目…」→
 * ProjectRemoveModal（四步流）；左栏末尾「＋ 接入项目」行 → ProjectAddModal；
 * 隔离红色行 → QuarantineModal（原因 + <dir>/project.yaml 定位 + 修复指路）。
 *
 * 骨架先例=session-entry 确认弹层（project-session-row.tsx），取舍（create_plan
 * gen1 R1-② 定稿）：在飞禁点带（写按钮 busy disabled，结果驱动关闭——成功才关、
 * 失败停留就地显示）；ESC/遮罩关闭带但**执行中不可关**（防半途弃置假示完成）；
 * 错误就地显示带（验收 12 口径本体）；焦点/aria 基础带。position:fixed 脱离
 * .wb-ticket-list 滚动容器裁剪（session-entry C1 同款理由）。
 *
 * 摘除四步流=显式状态机：gate（在飞闸预检）→ dispose（处置勾选，默认全保留）→
 * dry（摘除清单）→ confirm（purge 勾选后输入 key 二次确认）→ executing → done。
 * 每态迁移由结果驱动；purge 二次确认是弹层职责（路由不重复）。
 *
 * 降级口径：票计数 tickets_state 非 ok → 「—」+提示（不红）；体检 chips 本期降档
 * =「体检数据源未接入」中性提示位（R2b 定稿：CLI list 无体检字段，UI 禁自行实现
 * 体检逻辑——薄壳红线；数据源待宿主/epic 裁定后小票补齐，渲染位已留）。
 *
 * 语义锚（smoke/project-modals.mjs 源文本断言面）：data-wb-pmod-overlay / -close /
 * -settings / -settings-tickets / -settings-health / -remove-danger / -add-row 由
 * sidebar 承担 / data-wb-pmod-add / -add-key / -add-name / -add-dir / -add-pre /
 * -add-submit / -remove-gate / -remove-purge-data / -remove-purge-cred /
 * -remove-dry / -remove-key / -remove-submit / -quarantine-detail。零 CSS 类名
 * 匹配纪律（自有 .wb-pmod-* 前缀，与出厂类名零交叉）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { ProjectEntryLike } from './project-modals-types.ts'
import { DERIVE_TOKENS_CSS } from './theme';

/* ---------------------------------------------------------------- 样式 */

const PMOD_CSS = `${DERIVE_TOKENS_CSS}
.wb-pmod-overlay { position:fixed; inset:0; background:rgba(31,35,40,.35); z-index:200;
  display:flex; align-items:flex-start; justify-content:center; padding-top:8vh; }
.wb-pmod-panel { background:var(--dsw-derive-canvas,#fff); color:var(--dsw-derive-fg,#1f2328); border:1px solid var(--dsw-derive-border,#d0d7de); border-radius:10px;
  width:520px; max-width:94vw; max-height:80vh; overflow-y:auto; box-shadow:0 8px 24px rgba(31,35,40,.18);
  padding:18px 20px; font-size:13px; }
.wb-pmod-panel h3 { margin:0 0 4px; font-size:15px; display:flex; align-items:baseline; gap:10px; }
.wb-pmod-sub { color:var(--dsw-derive-muted,#57606a); font-size:12px; margin:0 0 14px; }
.wb-pmod-x { margin-left:auto; cursor:pointer; color:var(--dsw-derive-muted,#57606a); background:none; border:none; font-size:14px; }
.wb-pmod-field { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.wb-pmod-field label { width:76px; color:var(--dsw-derive-muted,#57606a); text-align:right; flex-shrink:0; }
.wb-pmod-field input { font:inherit; font-size:13px; flex:1; border:1px solid var(--dsw-derive-border,#d0d7de); border-radius:6px; padding:6px 8px; }
.wb-pmod-mono { font-family:ui-monospace,Menlo,monospace; font-size:11.5px; }
.wb-pmod-btn { font:inherit; font-size:13px; border:1px solid var(--dsw-derive-border,#d0d7de); background:var(--dsw-derive-canvas,#fff); color:var(--dsw-derive-fg,#1f2328);
  border-radius:6px; padding:5px 12px; cursor:pointer; }
.wb-pmod-btn:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-pmod-btn:disabled { opacity:.45; cursor:not-allowed; }
.wb-pmod-btn-blue { border-color:var(--dsw-derive-accent-border,#96c8f2); color:var(--dsw-derive-accent,#0969da); background:var(--dsw-derive-accent-bg,#ddf4ff); }
.wb-pmod-btn-danger { border-color:var(--dsw-derive-danger-border,#ff9b9b); color:var(--dsw-derive-danger,#cf222e); background:var(--dsw-derive-danger-bg,#ffebe9); }
.wb-pmod-err { background:var(--dsw-derive-danger-bg,#ffebe9); border:1px solid var(--dsw-derive-danger-border,#ff9b9b); color:var(--dsw-derive-danger,#cf222e); border-radius:6px;
  padding:7px 10px; font-size:12.5px; margin:8px 0; white-space:pre-wrap; }
.wb-pmod-ok { background:var(--dsw-derive-success-bg,#dafbe1); border:1px solid var(--dsw-derive-success-border,#7dd9a0); color:var(--dsw-derive-success,#1a7f37); border-radius:6px;
  padding:7px 10px; font-size:12.5px; margin:8px 0; }
.wb-pmod-warn { background:var(--dsw-derive-warn-bg,#fff8c5); border:1px solid var(--dsw-derive-warn-border,#d4a72c); color:var(--dsw-derive-warn-deep,#7d4e00); border-radius:6px;
  padding:7px 10px; font-size:12.5px; margin:8px 0; }
.wb-pmod-grid { display:grid; grid-template-columns:76px 1fr; row-gap:7px; margin-bottom:6px; }
.wb-pmod-grid .k { color:var(--dsw-derive-muted,#57606a); text-align:right; padding-right:10px; }
.wb-pmod-chip { display:inline-block; font-size:11px; border-radius:10px; padding:1px 8px; margin:1px 4px 1px 0;
  border:1px solid var(--dsw-derive-border,#d0d7de); color:var(--dsw-derive-muted,#57606a); background:var(--dsw-derive-surface,#f6f8fa); white-space:nowrap; }
.wb-pmod-danger { border-top:1px solid var(--dsw-derive-surface-2,#e8ebef); margin-top:14px; padding-top:12px; }
.wb-pmod-check { font-size:13px; line-height:2; }
.wb-pmod-dim { color:var(--dsw-derive-muted,#57606a); font-size:12px; }
`

/* ---------------------------------------------------------------- 公共壳 */

/** 弹层公共壳：遮罩 + ESC 关闭（executing 态不可关——防半途弃置假示完成）。 */
function ModalShell(props: {
  label: string
  locked?: boolean
  onClose: () => void
  children: ReactNode
}) {
  const overlayRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (props.locked) return
    const onKey = (e: KeyboardEvent): void => { if (e.key === 'Escape') props.onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [props.locked, props.onClose])
  return (
    <div
      ref={overlayRef}
      className="wb-pmod-overlay"
      data-wb-pmod-overlay=""
      role="dialog"
      aria-label={props.label}
      onMouseDown={e => { if (!props.locked && e.target === overlayRef.current) props.onClose() }}
    >
      <style>{PMOD_CSS}</style>
      <div className="wb-pmod-panel">
        <button type="button" className="wb-pmod-x" data-wb-pmod-close="" aria-label="关闭弹层"
          disabled={props.locked} onClick={props.onClose}>✕</button>
        {props.children}
      </div>
    </div>
  )
}

/** CLI 调用统一封装：返回 JSON；失败把 HTTP 错误体（error+body）合成人话抛出。 */
async function callProjectApi(url: string, init?: RequestInit): Promise<any> {
  const res = await fetch(url, init)
  let payload: any = null
  try { payload = await res.json() } catch { /* 下方统一报错 */ }
  if (!res.ok || payload?.ok === false) {
    const detail = payload?.error ?? `HTTP ${res.status}`
    const extra = payload?.body?.error ? `\n${payload.body.error}` : ''
    const err = new Error(`${detail}${extra}`)
    ;(err as any).payload = payload
    throw err
  }
  return payload
}

/* ---------------------------------------------------------------- 项目设置 */

/**
 * 项目设置弹层（验收 11）：只读信息 [key/显示名/根目录] + 票计数（Temporal 不可达
 * 降级「—」不红）+ 体检占位（R2b 降档）+ danger 区「摘除项目…」（进入摘除四步流）。
 * 本期只读，编辑器=Nongoal（epic 定稿）。
 */
export function ProjectSettingsModal(props: {
  project: ProjectEntryLike
  onClose: () => void
  onRemove: () => void
}) {
  const { project, onClose, onRemove } = props
  const [detail, setDetail] = useState<any>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const out = await callProjectApi(`/suyou-workbench/api/wf/projects/detail?key=${encodeURIComponent(project.key)}`)
        if (!cancelled) setDetail(out?.result ?? null)
      } catch (err) {
        if (!cancelled) setError(String((err as Error).message))
      }
    })()
    return () => { cancelled = true }
  }, [project.key])
  const t = detail?.tickets
  const degraded = detail != null && detail.tickets_state !== 'ok'
  return (
    <ModalShell label={`项目设置 · ${project.name}`} onClose={onClose}>
      <h3>项目设置 · {project.name} <span className="wb-pmod-mono wb-pmod-dim">{project.key}</span></h3>
      <p className="wb-pmod-sub">注册表条目 · 只读（本期无编辑器）· ~/.sandbar/projects/{project.key}/project.yaml</p>
      <div className="wb-pmod-grid" data-wb-pmod-settings="">
        <span className="k">项目 key</span><span className="wb-pmod-mono">{project.key}</span>
        <span className="k">显示名</span><span>{project.name}</span>
        <span className="k">根目录</span><span className="wb-pmod-mono">{project.primary}</span>
        <span className="k">票计数</span>
        <span data-wb-pmod-settings-tickets="">
          {detail == null
            ? (error ? <span className="wb-pmod-dim">—（{error}）</span> : <span className="wb-pmod-dim">读取中…</span>)
            : degraded
              ? <span className="wb-pmod-dim">—（{detail.tickets_note || 'Temporal 不可达，票计数暂缺'}）</span>
              : <span>在飞 {t?.open ?? 0} · 完结 {t?.closed ?? 0} · 已归档 {t?.archived ?? 0}</span>}
        </span>
        <span className="k">接入体检</span>
        <span data-wb-pmod-settings-health="">
          <span className="wb-pmod-chip">体检数据源未接入（待 CLI list 增补，本弹层只读展示）</span>
        </span>
      </div>
      {error && detail == null && <div className="wb-pmod-err">{error}</div>}
      <div className="wb-pmod-danger">
        <div className="wb-pmod-dim" style={{ marginBottom: 8 }}>危险区——操作走 CLI 单源，与命令行同口径</div>
        <button type="button" className="wb-pmod-btn wb-pmod-btn-danger" data-wb-pmod-remove-danger=""
          onClick={onRemove}>摘除项目…</button>
        <span className="wb-pmod-dim" style={{ marginLeft: 8 }}>默认可逆：退役注册条目，数据全保留</span>
      </div>
    </ModalShell>
  )
}

/* ---------------------------------------------------------------- 接入 */

/**
 * 接入弹层（验收 12）：表单 + 预检 + 拒收就地显示 + 黄牌不阻塞。
 * 预检口径（arbitrate gen1 F1 定稿：CLI `project add` 无 --dry-run 旗，补旗为跨写集
 * 裁定项）——预检降档为**本地形状检查**（key 白名单/根目录绝对路径/非空，不调 CLI、
 * 零落盘），确认时由 CLI 做深度校验（存在性/交叉/重复/legacy）并就地显示；
 * 本地检查=纯形状白名单，不实现 CLI 校验语义（薄壳红线不破）。
 */
export function ProjectAddModal(props: { onClose: () => void; onAdded: () => void }) {
  const { onClose, onAdded } = props
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [dir, setDir] = useState('')
  const [pre, setPre] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  /** 预检（本地形状检查，F1 降档口径）：纯白名单正则/绝对路径/非空，不调 CLI、零落盘。 */
  const localCheck = (): string[] => {
    const problems: string[] = []
    if (!/^[a-z0-9][a-z0-9-]*$/.test(key)) problems.push(`key 形状非法：${key || '（空）'}（白名单=小写字母/数字/连字符，不以连字符开头）`)
    if (!name.trim()) problems.push('显示名不能为空')
    if (!dir.startsWith('/')) problems.push(`根目录必须是绝对路径：${dir || '（空）'}`)
    return problems
  }
  const submit = async (): Promise<void> => {
    setBusy(true)
    setError('')
    try {
      await callProjectApi('/suyou-workbench/api/wf/projects/add', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ key, name, dir }),
      })
      onAdded()
      onClose()
    } catch (err) {
      setError(String((err as Error).message))
      setPre(null)
    } finally {
      setBusy(false)
    }
  }
  /** 预检产物：本地形状问题的提示条（黄牌语义——不阻塞确认，但深度校验仍会拒）。 */
  const warnings: string[] = Array.isArray(pre?.problems) ? pre.problems : []
  return (
    <ModalShell label="接入项目" locked={busy} onClose={onClose}>
      <h3>接入项目</h3>
      <p className="wb-pmod-sub">注册到 ~/.sandbar/projects/&lt;key&gt;/ · 单根模型：多 repo 项目填父目录（票的空间=根下 .lane/）</p>
      <div className="wb-pmod-field"><label>项目 key</label>
        <input className="wb-pmod-mono" data-wb-pmod-add-key="" value={key} onChange={e => setKey(e.target.value)} placeholder="小写字母/数字/连字符" /></div>
      <div className="wb-pmod-field"><label>显示名</label>
        <input data-wb-pmod-add-name="" value={name} onChange={e => setName(e.target.value)} /></div>
      <div className="wb-pmod-field"><label>根目录</label>
        <input className="wb-pmod-mono" data-wb-pmod-add-dir="" value={dir} onChange={e => setDir(e.target.value)} placeholder="/absolute/path" /></div>
      {error && <div className="wb-pmod-err" data-wb-pmod-add-error="">{error}</div>}
      {pre && (
        <div data-wb-pmod-add-pre="">
          <div className="wb-pmod-ok">本地形状检查通过（未落盘）——确认后由 CLI 做深度校验（存在性/交叉/重复/legacy），拒收原因将就地显示。</div>
          {warnings.map((w, i) => (
            <div key={i} className="wb-pmod-warn">⚠ {w}（形状问题不阻塞确认，但 CLI 深度校验仍会拒收）</div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button type="button" className="wb-pmod-btn wb-pmod-btn-blue" data-wb-pmod-add-precheck=""
          disabled={busy || !key || !dir} onClick={() => {
            const problems = localCheck()
            setPre({ problems })
            setError('')
          }}>预检（本地形状检查，不落盘）</button>
        <button type="button" className="wb-pmod-btn" data-wb-pmod-add-submit=""
          disabled={busy || !pre} onClick={() => { void submit() }}>确认接入</button>
      </div>
      <div className="wb-pmod-dim" style={{ marginTop: 8 }}>先预检再接入；拒收原因就地显示，无需翻后端日志。</div>
    </ModalShell>
  )
}

/* ---------------------------------------------------------------- 摘除 */

type RemoveStep = 'gate' | 'dispose' | 'dry' | 'confirm' | 'executing'

/**
 * 摘除弹层（验收 13）四步流：在飞闸预检 → 处置勾选（默认全保留）→ dry-run 清单
 * → purge 二次确认 → 执行（executing 态锁定弹层：ESC/遮罩/✕ 全禁）。
 */
export function ProjectRemoveModal(props: { project: ProjectEntryLike; onClose: () => void; onRemoved: () => void }) {
  const { project, onClose, onRemoved } = props
  const [step, setStep] = useState<RemoveStep>('gate')
  const [gate, setGate] = useState<any>(null)
  const [dry, setDry] = useState<any>(null)
  const [purgeData, setPurgeData] = useState(false)
  const [purgeCred, setPurgeCred] = useState(false)
  const [confirmKey, setConfirmKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const callRemove = useCallback(async (dryRun: boolean): Promise<any> => {
    return callProjectApi('/suyou-workbench/api/wf/projects/remove', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        key: project.key,
        dry_run: dryRun,
        purge_data: purgeData,
        purge_credentials: purgeCred,
        confirm_last: false,
      }),
    })
  }, [project.key, purgeData, purgeCred])

  const precheck = async (): Promise<void> => {
    setBusy(true)
    setError('')
    try {
      const out = await callRemove(true)
      setGate(out?.result ?? out)
      setStep('dispose')
    } catch (err) {
      // 在飞闸拒摘 / Temporal 不可达 fail-closed：拒摘原因就地显示（验收 13）。
      setError(String((err as Error).message))
    } finally {
      setBusy(false)
    }
  }
  const showDry = async (): Promise<void> => {
    setBusy(true)
    setError('')
    try {
      const out = await callRemove(true)
      setDry(out?.result ?? out)
      setStep('confirm')
    } catch (err) {
      setError(String((err as Error).message))
    } finally {
      setBusy(false)
    }
  }
  const execute = async (): Promise<void> => {
    setBusy(true)
    setError('')
    setStep('executing')
    try {
      const out = await callRemove(false)
      setResult(out?.result ?? out)
      onRemoved()
    } catch (err) {
      setError(String((err as Error).message))
      setStep('confirm')
    } finally {
      setBusy(false)
    }
  }
  const purgeNeedsConfirm = purgeData || purgeCred
  return (
    <ModalShell label={`摘除项目 · ${project.key}`} locked={busy || step === 'executing'} onClose={onClose}>
      <h3>摘除项目 · {project.name} <span className="wb-pmod-mono wb-pmod-dim">{project.key}</span></h3>
      <p className="wb-pmod-sub">默认可逆：只退役注册条目，数据全保留；re-add 同 key 即恢复</p>
      <div className="wb-pmod-check">
        <label><input type="checkbox" data-wb-pmod-remove-purge-data="" checked={purgeData}
          onChange={e => setPurgeData(e.target.checked)} />{' '}删数据 data/（归档+metrics，不可逆，需二次确认）</label><br />
        <label><input type="checkbox" data-wb-pmod-remove-purge-cred="" checked={purgeCred}
          onChange={e => setPurgeCred(e.target.checked)} />{' '}删 credentials.yaml</label>
        <div className="wb-pmod-dim">处置默认全保留——不勾任何 purge 即可逆摘除。</div>
      </div>
      {error && <div className="wb-pmod-err" data-wb-pmod-remove-error="">{error}</div>}
      {step === 'gate' && (
        <div data-wb-pmod-remove-gate="">
          <button type="button" className="wb-pmod-btn wb-pmod-btn-blue" data-wb-pmod-remove-precheck=""
            disabled={busy} onClick={() => { void precheck() }}>预检（在飞闸）</button>
          <div className="wb-pmod-dim" style={{ marginTop: 6 }}>
            在飞工单（Temporal 按 ProjectKey 查询）未收口=拒摘并报票号；Temporal 不可达同样拒摘
            （fail-closed 无绕过旗）：先 sandbar up。
          </div>
        </div>
      )}
      {step === 'dispose' && (
        <div data-wb-pmod-remove-dry="">
          <div className="wb-pmod-ok">✓ 预检通过：无在飞工单闸阻（在飞闸结果见 CLI dry-run 口径）。</div>
          <button type="button" className="wb-pmod-btn" disabled={busy} onClick={() => { void showDry() }}>摘除清单（dry-run）</button>
        </div>
      )}
      {step === 'confirm' && (
        <div data-wb-pmod-remove-confirm="">
          {dry && <pre className="wb-pmod-dim wb-pmod-mono" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(dry, null, 2)}</pre>}
          {purgeNeedsConfirm && (
            <div className="wb-pmod-field">
              <label style={{ width: 130 }}>输入 {project.key} 确认</label>
              <input className="wb-pmod-mono" data-wb-pmod-remove-key="" value={confirmKey}
                onChange={e => setConfirmKey(e.target.value)} placeholder={project.key} />
            </div>
          )}
          <button type="button" className="wb-pmod-btn wb-pmod-btn-danger" data-wb-pmod-remove-submit=""
            disabled={busy || (purgeNeedsConfirm && confirmKey !== project.key)}
            onClick={() => { void execute() }}>确认摘除</button>
          <span className="wb-pmod-dim" style={{ marginLeft: 8 }}>执行 sandbar project remove {project.key} --json，结果与 CLI 同口径</span>
        </div>
      )}
      {step === 'executing' && <div className="wb-pmod-warn">执行中…（弹层已锁定）</div>}
      {result && <div className="wb-pmod-ok" data-wb-pmod-remove-result="">摘除完成：{JSON.stringify(result)}</div>}
    </ModalShell>
  )
}

/* ---------------------------------------------------------------- 隔离详情 */

/** 隔离条目弹层（验收 11）：原因含 <dir>/project.yaml 定位 + 修复指路。 */
export function QuarantineModal(props: {
  entry: { key: string; dir: string; error: string }
  onClose: () => void
}) {
  const { entry, onClose } = props
  return (
    <ModalShell label={`隔离条目 · ${entry.key}`} onClose={onClose}>
      <h3>隔离条目 · <span className="wb-pmod-mono">{entry.key}</span></h3>
      <p className="wb-pmod-sub">装载器 fail-closed 隔离，不影响其余项目装载；按 key 查询会显式报隔离原因</p>
      <div className="wb-pmod-err wb-pmod-mono" data-wb-pmod-quarantine-detail="">{entry.error}</div>
      <div className="wb-pmod-dim">
        定位：<span className="wb-pmod-mono">{entry.dir}/project.yaml</span>。
        修复：手工订正该 project.yaml 后自动恢复装载（左栏重新出现项目组）。
        隔离期间无组头无项目设置入口（无装载条目可设置）。
      </div>
    </ModalShell>
  )
}
