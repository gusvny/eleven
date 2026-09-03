/**
 * suyou-providers —— LLM provider 管理与优先级 · 浏览器半（会话主视图「模型」页签版）。
 *
 * 槽位契约（t260821-11 ①：从 settings 分区迁来，制式照抄 workbench）：向会话视图环
 * `conversation.view` 注册一个页签（id 'suyou-providers'，标签「模型」，order 15，
 * 与 chat(0)/trajectory(10)/工单台(20) 平级），用户在主会话视图顶部页签切换即见。
 * 配套注册 `conversationViews.register`（target 'suyou-providers'）：本视图数据来自
 * /suyou-providers/api/* 而非会话事件，builder 为空实现，仅为满足 per-session 契约。
 *
 * 功能（t260821-08 B 版 + t260821-11 ②③ + M13 路由表）：
 *   ① 列出 provider（deepseek-official/kimi-coding/zai/scnet…）+ 上下移/拖拽排序；
 *   ② 每个 provider 计费档说明可编辑；
 *   ③ 「设为当前」一键写 agent-default-model（provider+model，可带 reasoningEffort）；
 *   ④ 「添加 provider」表单（baseURL/协议/模型 id 列表/key 环境变量 + **key 直填**）：
 *      key 直填走宿主半 credentials seam 写 $DSH_HOME/.credentials.yaml，settings.yaml
 *      仍只落 apiKeyEnv 引用，写 settings 仍走 assertServiceable dry-run 校验；
 *   ⑤ scnet 预置一键填表并**预填 14 个模型 id**（glm/minimax/kimi/qwen/deepseek 系）；
 *   ⑥ 「路由表」分区（M13，t260822-m13-model-routes-edit）：展示 model-routes.yaml
 *      真源路由表（default/五角色/分工 tasks）+ provider 下拉/模型下拉编辑（换 provider
 *      即刷新该家已注册模型清单，260828）+
 *      保存（POST /suyou-admin/api/routes/save，宿主在 suyou-admin-ui 插件，写前备份
 *      /tmp；保存即生效——运行时查表，下一个工单 agent spawn 用新表）。
 * 所有写操作走宿主半（../node.ts）挂在 dsh webServer 上的 /suyou-providers/api/*；
 * 路由表读写走 suyou-admin-ui 的 /suyou-admin/api/routes（同源，M13① 保留的 API）。
 */

import { useEffect, useMemo, useState } from 'react'
import type { ClientContext, ConversationViewDefinition } from '@deepseek-ai/dsh-client-runtime/client'
// 空具名 type import：把 dsh-client-ui-conversation 的 SlotMap 扩展（conversation.view 槽声明）
// 带进 tsc 检查环境；纯类型副作用，构建时被剥离，不进 bundle。
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'

export const name = 'suyou-providers/client'
export const inject = ['slots', 'conversationViews']

/* ---------------------------------------------------------------- 样式 */

const CSS = `
.syp-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:#f6f8fa;color:#1f2328;min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:16px;font-size:13px;line-height:1.55}
.syp-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid #d0d7de;padding-bottom:12px}
.syp-title{font-size:20px;font-weight:600;color:#1f2328}
.syp-sub{font-size:12px;color:#57606a}
.syp-banner{display:flex;align-items:center;gap:10px;border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:10px 14px;flex-wrap:wrap}
.syp-banner-k{color:#57606a}
.syp-banner-v{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-err{background:#ffebe9;border:1px solid #ff9b9b;color:#cf222e;border-radius:6px;padding:8px 12px;font-size:12px;white-space:pre-wrap}
.syp-ok{background:#dafbe1;border:1px solid #7dd9a0;color:#116329;border-radius:6px;padding:8px 12px;font-size:12px}
.syp-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.syp-btn{font:inherit;font-size:12px;padding:4px 12px;border-radius:6px;cursor:pointer;border:1px solid #d0d7de;background:#fff;color:#1f2328;transition:background .12s}
.syp-btn:hover{background:#f6f8fa}
.syp-btn:disabled{opacity:.45;cursor:default}
.syp-btn-primary{border-color:#0969da;background:#0969da;color:#fff;font-weight:600}
.syp-btn-primary:hover{background:#0857b6}
.syp-btn-danger{border-color:#ff9b9b;color:#cf222e;background:#ffebe9}
.syp-btn-green{border-color:#7dd9a0;color:#1a7f37;background:#dafbe1}
.syp-icon-btn{font:inherit;font-size:13px;padding:2px 8px;border-radius:6px;cursor:pointer;border:1px solid #d0d7de;background:#fff;color:#57606a}
.syp-icon-btn:hover{background:#f6f8fa}
.syp-icon-btn:disabled{opacity:.35;cursor:default}
.syp-list{display:flex;flex-direction:column;gap:8px}
.syp-row{display:flex;align-items:flex-start;gap:10px;border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:10px 12px;transition:box-shadow .12s}
.syp-row[data-current=true]{border-color:#0969da;box-shadow:inset 3px 0 0 #0969da;background:#f0f6ff}
.syp-row[data-drag=true]{opacity:.5;border-style:dashed}
.syp-row-grip{cursor:grab;color:#8c959f;user-select:none;font-size:16px;line-height:1;padding:4px 2px}
.syp-row-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}
.syp-row-line1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.syp-row-name{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:500}
.syp-badge[data-kind=external]{background:#fff8c5;color:#7d4e00}
.syp-badge[data-kind=pi-ai]{background:#dafbe1;color:#116329}
.syp-badge[data-kind=preset]{background:#ddf4ff;color:#0550ae}
.syp-badge[data-cur=true]{background:#0969da;color:#fff}
.syp-row-line2{display:flex;gap:8px 16px;flex-wrap:wrap;font-size:11px;color:#57606a}
.syp-kv{display:inline-flex;gap:4px}
.syp-kv b{color:#8c959f;font-weight:500}
.syp-row-line3{display:flex;align-items:center;gap:8px}
.syp-note-label{font-size:11px;color:#8c959f;white-space:nowrap}
.syp-note-input{font:inherit;font-size:12px;flex:1;border:1px solid #d0d7de;border-radius:6px;padding:4px 8px;color:#1f2328;background:#fff}
.syp-note-input:focus{outline:none;border-color:#0969da}
.syp-row-ops{display:flex;flex-direction:column;gap:6px;align-items:flex-end;flex:none}
.syp-row-ops .syp-btn{white-space:nowrap}
.syp-form{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.syp-form-title{font-size:14px;font-weight:600;color:#1f2328}
.syp-field{display:flex;flex-direction:column;gap:4px}
.syp-field label{font-size:12px;color:#57606a}
.syp-field input,.syp-field select,.syp-field textarea{font:inherit;font-size:12px;border:1px solid #d0d7de;border-radius:6px;padding:6px 10px;color:#1f2328;background:#fff}
.syp-field input:focus,.syp-field select:focus,.syp-field textarea:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.syp-field textarea{min-height:72px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-hint{font-size:11px;color:#8c959f}
.syp-modal{position:fixed;inset:0;background:rgba(31,35,40,.5);z-index:99;display:flex;align-items:center;justify-content:center;padding:24px}
.syp-modal-box{background:#fff;border:1px solid #d0d7de;border-radius:10px;box-shadow:0 8px 32px rgba(31,35,40,.2);max-width:520px;width:100%;display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.syp-modal-title{font-size:15px;font-weight:600;color:#1f2328}
.syp-empty{font-size:12px;color:#57606a;padding:12px 0}
/* ── M13 路由表（syp-route-*）── */
.syp-route-card{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:14px 16px;
  display:flex;flex-direction:column;gap:10px}
.syp-route-title{font-size:14px;font-weight:600;color:#1f2328;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.syp-route-note{font-size:11px;color:#57606a;line-height:1.7}
.syp-route-redline{font-size:11px;color:#7d4e00;background:#fff8c5;border:1px solid #d4a72c;
  border-radius:6px;padding:6px 10px;line-height:1.7}
.syp-route-gen{font-size:12px;color:#116329;background:#dafbe1;border:1px solid #7dd9a0;
  border-radius:6px;padding:8px 12px;line-height:1.7;white-space:pre-wrap}
.syp-route-tbl{border:1px solid #eaeef2;border-radius:6px;overflow:hidden}
.syp-route-row{display:grid;grid-template-columns:170px minmax(140px,1fr) minmax(140px,1fr) auto;
  gap:8px;align-items:center;padding:6px 10px;border-bottom:1px solid #eaeef2}
.syp-route-row:last-child{border-bottom:none}
.syp-route-row[data-head=true]{background:#f6f8fa;font-size:11px;color:#8c959f;padding-top:5px;padding-bottom:5px}
.syp-route-row[data-task=true]{padding-left:26px;background:#fbfcfe}
.syp-route-label{font-size:12px;font-weight:600;color:#1f2328;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.syp-route-kind{font-size:11px;font-weight:400;color:#8c959f}
.syp-route-cell{display:flex;flex-direction:column;gap:2px;min-width:0}
.syp-route-cell select,.syp-route-cell input{font:inherit;font-size:12px;border:1px solid #d0d7de;
  border-radius:6px;padding:4px 8px;color:#1f2328;background:#fff;width:100%;box-sizing:border-box}
.syp-route-cell select:focus,.syp-route-cell input:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.syp-route-cell-hint{font-size:10px;color:#8c959f}
.syp-route-cell-warn{font-size:10px;color:#b45309;display:block}
.syp-route-eff{font-size:11px;color:#57606a;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.syp-route-via{font-size:10px;color:#8c959f;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-route-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.syp-route-warn{font-size:11px;color:#9a6700;background:#fff8c5;border-radius:6px;padding:6px 10px;
  margin:0;white-space:pre-wrap;line-height:1.6}
`

const CSS_TAG_ID = 'suyou-providers/ProvidersSection.css'
if (typeof document !== 'undefined'
  && document.querySelector('style[data-plugin-css=' + JSON.stringify(CSS_TAG_ID) + ']') === null) {
  const tag = document.createElement('style')
  tag.dataset.plugin = 'suyou-providers'
  tag.dataset.pluginCss = CSS_TAG_ID
  tag.textContent = CSS
  document.head.appendChild(tag)
}

/* -------------------------------------------------------------- 数据通道 */

const API = '/suyou-providers/api'

interface ProviderRow {
  id: string
  kind: 'pi-ai' | 'external' | 'preset'
  displayName: string
  api: string | null
  baseURL: string | null
  apiKeyEnv: string | null
  keySet?: boolean
  models: string[]
  note: string
  isCurrent: boolean
  currentModel: string
  added: boolean
  description?: string
}

interface StateData {
  current: { provider: string; model: string; reasoningEffort: string }
  providers: ProviderRow[]
  protocols: string[]
  scnetPreset: { id: string; displayName: string; api: string; baseURL: string; apiKeyEnv: string; models?: string[]; description: string }
  settingsPath: string
}

/** 多项目化（260823）：路由表两条 URL（/suyou-admin/api/routes*，按项目主目录解析
 *  model-routes.yaml）统一拼 ?project=；provider 管理（/suyou-providers/api/*）是
 *  dsh 全局设施，不分流。
 *  260826 修：project 从模块级持有量改为纯函数入参——旧写法靠 ProvidersSection 的
 *  effect 落值，但 React 挂载时子组件 effect 先于父组件执行，RoutesTableSection
 *  首次 load 永远拿到空 project → 宿主 400「缺 project 参数」。prop 渲染期即有值，
 *  不依赖 effect 顺序。 */
function routesUrl(path: string, projectKey: string): string {
  if (!projectKey) return path
  return path + (path.includes('?') ? '&' : '?') + 'project=' + encodeURIComponent(projectKey)
}

async function apiGet(path: string): Promise<any> {
  const res = await fetch(path)
  return res.json()
}

async function apiPost(path: string, body: unknown): Promise<any> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  return res.json()
}

/* -------------------------------------------------------------- 分区本体 */

const KIND_LABEL: Record<string, string> = {
  'pi-ai': 'llm-pi-ai 路由',
  external: '官方 deepseek 适配器',
  preset: '预置（未添加）',
}

/** 「手填…」select 选项哨兵值：与真实模型 id 冲突面极小（模型 id 不会长这样）。 */
const HAND_OPT = '__hand__'

/**
 * 模型 id 单元。provider 有已注册清单 → 渲染真 <select>（整单随 provider 刷新）；
 * 清单为空或选了「手填…」→ 自由输入 + datalist 兜底（catalog 滞后的新模型仍可手输）。
 *
 * 为什么不用 datalist 当主下拉：datalist 的候选会被输入框现值过滤（框里留着上一家的
 * 模型 id 时，下拉看起来永远是空的/旧的），WebKit 还常不随重渲染刷新候选——260828
 * 反馈「选了 provider 模型列表不刷新」的根因。真 select 没有这两毛病。
 * 调用方用 key={provider id} 挂载：换 provider 即重挂，手填态自动退回下拉。
 */
function ModelIdCell({ pid, models, value, onChange, listId }: {
  pid: string
  models: string[]
  value: string
  onChange: (v: string) => void
  listId: string
}) {
  const [hand, setHand] = useState(false)
  if (hand || models.length === 0) {
    return (
      <>
        <input value={value} list={models.length > 0 ? listId : undefined}
          placeholder="模型 id（手填）" onChange={e => onChange(e.target.value)} />
        {models.length > 0 && <datalist id={listId}>{models.map(m => <option key={m} value={m} />)}</datalist>}
        {models.length > 0 && (
          <button type="button" className="syp-btn" onClick={() => setHand(false)}>回 {pid} 清单下拉</button>
        )}
      </>
    )
  }
  const known = models.includes(value)
  return (
    <select value={known ? value : HAND_OPT} onChange={e => {
      if (e.target.value === HAND_OPT) { setHand(true); return }
      onChange(e.target.value)
    }}>
      {!known && <option value={value}>{value === '' ? '（未设）' : `${value}（未注册）`}</option>}
      {models.map(m => <option key={m} value={m}>{m}</option>)}
      <option value={HAND_OPT}>（手填…）</option>
    </select>
  )
}

export function ProvidersSection({ projectKey }: { projectKey?: string }) {
  const [data, setData] = useState<StateData | undefined>(undefined)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [dragId, setDragId] = useState<string | null>(null)
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({})

  // add-provider 表单
  const [fId, setFId] = useState('')
  const [fDisplay, setFDisplay] = useState('')
  const [fApi, setFApi] = useState('openai-completions')
  const [fBase, setFBase] = useState('')
  const [fKeyEnv, setFKeyEnv] = useState('')
  const [fApiKey, setFApiKey] = useState('')
  const [fModels, setFModels] = useState('')
  const [fNote, setFNote] = useState('')

  // 设为当前
  const [curId, setCurId] = useState<string | null>(null)
  const [curModel, setCurModel] = useState('')
  const [curRe, setCurRe] = useState('')

  async function reload(): Promise<void> {
    try {
      const d = await apiGet(`${API}/state`)
      if (d?.ok !== true) throw new Error(d?.error ?? '加载失败')
      setData(d.result as StateData)
      setError('')
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    }
  }

  useEffect(() => { void reload() }, [])

  async function post(path: string, body: unknown, okMsg: string): Promise<boolean> {
    setBusy(true)
    setMsg('')
    try {
      const r = await apiPost(path, body)
      if (r?.ok !== true) {
        setMsg(`失败：${r?.error ?? '未知错误'}`)
        return false
      }
      setMsg(okMsg)
      await reload()
      return true
    } catch (err) {
      setMsg(`请求失败：${String(err instanceof Error ? err.message : err)}`)
      return false
    } finally {
      setBusy(false)
    }
  }

  function fillScnet(): void {
    const p = data?.scnetPreset
    if (!p) return
    setFId(p.id)
    setFDisplay(p.displayName)
    setFApi(p.api)
    setFBase(p.baseURL)
    setFKeyEnv(p.apiKeyEnv)
    setFApiKey('')
    setFModels(Array.isArray(p.models) ? p.models.join('\n') : '')
    setFNote('')
  }

  async function submitAdd(): Promise<void> {
    const models = fModels.split(/[\n,]+/).map(s => s.trim()).filter(Boolean)
    const ok = await post(`${API}/add-provider`, {
      id: fId, displayName: fDisplay, api: fApi, baseURL: fBase, apiKeyEnv: fKeyEnv, apiKey: fApiKey, models, note: fNote,
    }, `已添加 provider「${fId.trim()}」到 llm-pi-ai.providers${fApiKey.trim() !== '' ? `，key 已存入 ${fKeyEnv.trim()}` : ''}`)
    if (ok) {
      setShowForm(false)
      setFId(''); setFDisplay(''); setFApi('openai-completions'); setFBase(''); setFKeyEnv(''); setFApiKey(''); setFModels(''); setFNote('')
    }
  }

  function openSetCurrent(p: ProviderRow): void {
    setCurId(p.id)
    setCurModel(p.isCurrent ? p.currentModel : (p.models[0] ?? ''))
    setCurRe(p.isCurrent ? (data?.current.reasoningEffort ?? '') : '')
  }

  async function submitSetCurrent(): Promise<void> {
    if (!curId) return
    const ok = await post(`${API}/set-current`, { provider: curId, model: curModel, reasoningEffort: curRe },
      `已把 agent-default-model 切到 ${curId} / ${curModel.trim()}`)
    if (ok) setCurId(null)
  }

  async function saveNote(p: ProviderRow): Promise<void> {
    const note = (noteDraft[p.id] ?? p.note) as string
    await post(`${API}/update-note`, { id: p.id, note }, `已保存「${p.id}」计费说明`)
  }

  async function reorder(order: string[]): Promise<void> {
    setBusy(true)
    setMsg('')
    try {
      const r = await apiPost(`${API}/reorder`, { order })
      if (r?.ok !== true) { setMsg(`失败：${r?.error ?? '未知错误'}`); return }
      setMsg('优先级已保存')
      await reload()
    } catch (err) {
      setMsg(`请求失败：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setBusy(false)
    }
  }

  function move(id: string, delta: number): void {
    const list = data?.providers.map(p => p.id) ?? []
    const i = list.indexOf(id)
    const j = i + delta
    if (i < 0 || j < 0 || j >= list.length) return
    const next = [...list]
    const tmp = next[i]; next[i] = next[j]; next[j] = tmp
    void reorder(next)
  }

  function onDrop(id: string): void {
    const list = data?.providers.map(p => p.id) ?? []
    const from = dragId
    const to = id
    setDragId(null)
    if (!from || from === to) return
    const next = list.filter(x => x !== from)
    const idx = next.indexOf(to)
    next.splice(idx, 0, from)
    void reorder(next)
  }

  const rows = data?.providers ?? []
  const modelListForCurrent = useMemo(() => (curId ? (rows.find(p => p.id === curId)?.models ?? []) : []), [curId, rows])

  return (
    <div className="syp-root">
      <div className="syp-head">
        <span className="syp-title">模 型</span>
        <span className="syp-sub">LLM provider 管理与优先级（手动排序 + 一键切换）· 写 {data?.settingsPath ?? 'settings.yaml'}</span>
      </div>

      {data && (
        <div className="syp-banner">
          <span className="syp-banner-k">当前 agent-default-model：</span>
          <span className="syp-banner-v">{data.current.provider} / {data.current.model}</span>
          {data.current.reasoningEffort && <span className="syp-badge" data-cur={true}>{data.current.reasoningEffort}</span>}
        </div>
      )}

      {error !== '' && <div className="syp-err">{error}{'\n'}（模型管理 API 未挂载？headless profile 无 webServer。）</div>}
      {msg !== '' && (msg.startsWith('失败') || msg.startsWith('请求失败')
        ? <div className="syp-err">{msg}</div> : <div className="syp-ok">{msg}</div>)}

      <div className="syp-actions">
        <button className="syp-btn" disabled={busy} onClick={() => { void reload() }}>刷 新</button>
        <button className="syp-btn syp-btn-primary" onClick={() => setShowForm(v => !v)}>
          {showForm ? '收起添加表单' : '+ 添加 provider'}
        </button>
      </div>

      {showForm && (
        <div className="syp-form">
          <div className="syp-form-title">添加 provider（写 settings.yaml 的 llm-pi-ai.providers；坏 provider 会被 dry-run 拒绝，绝不落盘）</div>
          <div className="syp-actions">
            <button className="syp-btn" onClick={fillScnet} title={data?.scnetPreset?.description}>scnet 预置一键填表</button>
            <span className="syp-hint">{data?.scnetPreset?.description ?? ''}</span>
          </div>
          <div className="syp-field">
            <label>provider id（route key，如 scnet / my-gateway）</label>
            <input value={fId} onChange={e => setFId(e.target.value)} placeholder="scnet" />
          </div>
          <div className="syp-field">
            <label>显示名（可选）</label>
            <input value={fDisplay} onChange={e => setFDisplay(e.target.value)} placeholder="SCNet" />
          </div>
          <div className="syp-field">
            <label>协议 api</label>
            <select value={fApi} onChange={e => setFApi(e.target.value)}>
              {(data?.protocols ?? ['openai-completions', 'openai-responses', 'anthropic-messages']).map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="syp-field">
            <label>baseURL</label>
            <input value={fBase} onChange={e => setFBase(e.target.value)} placeholder="https://api.scnet.cn/api/llm/v1" />
          </div>
          <div className="syp-field">
            <label>key 环境变量 apiKeyEnv（key 直填时即存入该名下）</label>
            <input value={fKeyEnv} onChange={e => setFKeyEnv(e.target.value)} placeholder="SCNET_API_KEY" />
          </div>
          <div className="syp-field">
            <label>API key 直填（可选；留空则只登记 apiKeyEnv，不写任何 key）</label>
            <input type="password" value={fApiKey} onChange={e => setFApiKey(e.target.value)} autoComplete="off"
              placeholder="sk-…（存入 $DSH_HOME/.credentials.yaml，0600）" />
          </div>
          <div className="syp-field">
            <label>模型 id 列表（每行一个；scnet 预置会预填 14 个模型 id，可增删）</label>
            <textarea value={fModels} onChange={e => setFModels(e.target.value)} placeholder={'GLM-5.2\nGLM-5\n…'} />
          </div>
          <div className="syp-field">
            <label>计费档说明（可选）</label>
            <input value={fNote} onChange={e => setFNote(e.target.value)} placeholder="如：¥0.001/1K tokens" />
          </div>
          <div className="syp-actions">
            <button className="syp-btn syp-btn-green" disabled={busy} onClick={() => { void submitAdd() }}>添 加</button>
          </div>
        </div>
      )}

      <div className="syp-list">
        {rows.map((p, i) => (
          <div key={p.id} className="syp-row" data-current={p.isCurrent} data-drag={dragId === p.id}
            draggable={!busy}
            onDragStart={() => setDragId(p.id)}
            onDragOver={e => e.preventDefault()}
            onDrop={e => { e.preventDefault(); onDrop(p.id) }}
            onDragEnd={() => setDragId(null)}>
            <span className="syp-row-grip" title="拖拽排序">⠿</span>
            <div className="syp-row-main">
              <div className="syp-row-line1">
                <span className="syp-row-name">{p.id}</span>
                {p.displayName && p.displayName !== p.id && <span className="syp-sub">{p.displayName}</span>}
                <span className="syp-badge" data-kind={p.kind}>{KIND_LABEL[p.kind] ?? p.kind}</span>
                {p.isCurrent && <span className="syp-badge" data-cur={true}>当前</span>}
              </div>
              <div className="syp-row-line2">
                {p.api && <span className="syp-kv"><b>协议</b>{p.api}</span>}
                {p.baseURL && <span className="syp-kv"><b>baseURL</b>{p.baseURL}</span>}
                {p.apiKeyEnv && (
                  <span className="syp-kv"><b>key</b>{p.apiKeyEnv}{p.keySet === true ? '（已存）' : p.keySet === false ? '（未存）' : ''}</span>
                )}
                <span className="syp-kv"><b>模型</b>{p.models.length > 0 ? `${p.models.length} 个` : '—'}</span>
                {p.description && <span className="syp-kv"><b>备注</b>{p.description}</span>}
              </div>
              <div className="syp-row-line3">
                <span className="syp-note-label">计费说明</span>
                <input className="syp-note-input" value={noteDraft[p.id] ?? p.note}
                  placeholder="（可编辑，如计费档位/价格）"
                  onChange={e => setNoteDraft(v => ({ ...v, [p.id]: e.target.value }))} />
                <button className="syp-btn" disabled={busy} onClick={() => { void saveNote(p) }}>保存说明</button>
              </div>
            </div>
            <div className="syp-row-ops">
              <div className="syp-actions">
                <button className="syp-icon-btn" disabled={busy || i === 0} title="上移" onClick={() => move(p.id, -1)}>↑</button>
                <button className="syp-icon-btn" disabled={busy || i === rows.length - 1} title="下移" onClick={() => move(p.id, 1)}>↓</button>
              </div>
              <button className="syp-btn syp-btn-primary" disabled={busy} onClick={() => openSetCurrent(p)}>设为当前</button>
              {p.kind === 'preset' && (
                <button className="syp-btn syp-btn-green" disabled={busy} onClick={() => { fillScnet(); setShowForm(true) }}>添加</button>
              )}
              {p.kind === 'pi-ai' && (
                <button className="syp-btn syp-btn-danger" disabled={busy}
                  onClick={() => { if (window.confirm(`删除 provider「${p.id}」（从 llm-pi-ai.providers 移除）？`)) void post(`${API}/delete-provider`, { id: p.id }, `已删除「${p.id}」`) }}>
                  删除
                </button>
              )}
            </div>
          </div>
        ))}
        {rows.length === 0 && <div className="syp-empty">没有 provider（加载中或 API 未挂载）。</div>}
      </div>

      <RoutesTableSection providers={rows} projectKey={projectKey} />

      {curId !== null && (
        <div className="syp-modal">
          <div className="syp-modal-box">
            <div className="syp-modal-title">设为当前 — {curId}</div>
            <div className="syp-field">
              <label>模型 id（{modelListForCurrent.length > 0 ? `${modelListForCurrent.length} 个已注册模型下拉可选，新模型选「手填…」` : '手填模型 id'}）</label>
              <ModelIdCell key={curId} pid={curId} models={modelListForCurrent} value={curModel}
                onChange={setCurModel} listId="syp-model-list" />
            </div>
            <div className="syp-field">
              <label>reasoningEffort（可选，留空则省略；仅当目标适配器支持时有效）</label>
              <input value={curRe} onChange={e => setCurRe(e.target.value)} placeholder="low / medium / high" />
            </div>
            <div className="syp-actions">
              <button className="syp-btn syp-btn-primary" disabled={busy || !curModel.trim()} onClick={() => { void submitSetCurrent() }}>确认切换</button>
              <button className="syp-btn" disabled={busy} onClick={() => setCurId(null)}>取 消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ 路由表（M13） */

// 纯函数与类型（视图→草稿→保存载荷）在 src/host/routes-edit.ts，浏览器半与冒烟共用。
import {
  draftFromView, draftToPayload,
  type RouteDraft, type RouteEff, type RoutesViewResp,
} from '../host/routes-edit.ts'

/** 「路由表」分区：展示当前路由表（只读真源）+ 编辑 provider/model + 保存
 *  （保存即生效——运行时查表，下一个工单 agent spawn 用新表）。providers 列表
 *  （含模型 id）来自本插件 /state，供下拉用。 */
function RoutesTableSection({ providers, projectKey }: { providers: ProviderRow[]; projectKey?: string }) {
  const [view, setView] = useState<RoutesViewResp | undefined>(undefined)
  const [draft, setDraft] = useState<RouteDraft | undefined>(undefined)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [saved, setSaved] = useState(false)

  async function load(): Promise<void> {
    setError('')
    try {
      const data = await apiGet(routesUrl('/suyou-admin/api/routes', projectKey ?? ''))
      if (data?.ok !== true) throw new Error(data?.error ?? '模型路由读取失败')
      const v = data.result as RoutesViewResp
      setView(v)
      setDraft(draftFromView(v))
      setSaved(false)
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    }
  }

  // 切项目重载（project 直接走 prop——不依赖模块持有量，effect 顺序无关）。
  useEffect(() => {
    setView(undefined)
    setDraft(undefined)
    setError('')
    if (projectKey) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectKey])

  function setRoleField(rid: string, field: 'provider' | 'model', value: string): void {
    setDraft(d => d === undefined ? d : { ...d, roles: { ...d.roles, [rid]: { ...d.roles[rid], [field]: value } } })
  }
  function setTaskField(rid: string, kind: string, field: 'provider' | 'model', value: string): void {
    setDraft(d => d === undefined ? d : {
      ...d,
      roles: {
        ...d.roles,
        [rid]: { ...d.roles[rid], tasks: { ...d.roles[rid].tasks, [kind]: { ...d.roles[rid].tasks[kind], [field]: value } } },
      },
    })
  }

  async function save(): Promise<void> {
    if (draft === undefined) return
    const confirmed = window.confirm(
      '保存将改写 server/dsh/model-routes.yaml（真源，写前备份 /tmp）。\n' +
      '保存即生效：路由表是运行时查表，下一个工单 agent spawn 时就按新表走，无需任何生成/重启步骤。\n' +
      '确认保存路由表？')
    if (!confirmed) return
    setBusy(true)
    setMsg('')
    setSaved(false)
    try {
      const r = await apiPost(routesUrl('/suyou-admin/api/routes/save', projectKey ?? ''), { table: draftToPayload(draft) })
      if (r?.ok !== true) {
        setMsg(`保存失败：${r?.error ?? '未知错误'}`)
        return
      }
      const res = r.result ?? {}
      setMsg(res.changed?.length > 0
        ? `已保存 ${res.changed.length} 处变更（${res.changed.join('、')}）到 ${res.routes_file}`
        : '路由表无变更（未写文件）')
      setSaved(true)
      await load()
    } catch (err) {
      setMsg(`请求失败：${String(err instanceof Error ? err.message : err)}`)
    } finally {
      setBusy(false)
    }
  }

  if (!projectKey) {
    return (
      <div className="syp-route-card">
        <div className="syp-route-title">路 由 表</div>
        <div className="syp-sub">从左侧项目行点 🔀 图标打开该项目的模型路由。</div>
      </div>
    )
  }

  if (error !== '') {
    return (
      <div className="syp-route-card">
        <div className="syp-route-title">路 由 表</div>
        <div className="syp-err">{error}{'\n'}（/suyou-admin/api/routes 返回错误——按上面文案排查：缺参/未知项目=调用问题；表缺失/解析失败=该项目主目录的 model-routes.yaml 问题。）</div>
      </div>
    )
  }
  if (view === undefined || draft === undefined) {
    return (
      <div className="syp-route-card">
        <div className="syp-route-title">路 由 表</div>
        <div className="syp-empty">加载路由表…</div>
      </div>
    )
  }

  const modelsOf = (pid: string): string[] => providers.find(p => p.id === pid)?.models ?? []
  /** 换 provider 时对齐 model：切到「继承/不设」清空；原 model 不在新家清单 → 取新家
   *  首个已注册模型（都没有则清空）。避免留下「A 家 provider + B 家 model」的错配，也
   *  让模型下拉随 provider 切换即见新家清单。 */
  function snapModel(curModel: string, newPid: string): string {
    if (newPid === '') return ''
    const ms = modelsOf(newPid)
    if (ms.includes(curModel)) return curModel
    return ms[0] ?? ''
  }
  /** 未注册提示：值非空、该家有已知清单、值不在清单 → 提示（不硬拦——catalog 滞后的
   *  新模型仍需手输入口，但把「模型 ref 不许发明」红线摆到眼前，260826 zai/k3 教训）。 */
  const UnregHint = ({ pid, model }: { pid: string; model: string }) => {
    const ms = modelsOf(pid)
    if (model === '' || ms.length === 0 || ms.includes(model)) return null
    return <span className="syp-route-cell-warn">⚠ 不在 {pid} 已注册清单（{ms.length} 个），保存前确认已实测</span>
  }
  const effOf = (eff: RouteEff | null): string => eff !== null ? `${eff.provider}/${eff.model}` : '未设（继承 profile 默认）'

  return (
    <div className="syp-route-card">
      <div className="syp-route-title">
        路 由 表
        <span className="syp-hint">真源 {view.routes_file} · 工单 agent 用哪个模型（运行时查表，下次 spawn 生效）</span>
      </div>

      <div className="syp-route-redline">
        改表红线：保存直接改写 model-routes.yaml（写前备份 /tmp）；模型 ref 不许发明——只用下方
        provider 下拉里实证存在的 provider 及其模型 id。保存后<strong>下一个工单 agent 启动即生效</strong>，无需任何生成/重启步骤。
      </div>

      {view.warnings.length > 0 && <pre className="syp-route-warn">{view.warnings.join('\n')}</pre>}

      {saved && (
        <div className="syp-route-gen">
          ✅ 路由表已写入 {view.routes_file}。下一个工单 agent 启动即按新表路由（运行时查表，无需任何生成/重启步骤）。
        </div>
      )}

      <div className="syp-route-tbl">
        <div className="syp-route-row" data-head={true}>
          <span>条目</span><span>provider</span><span>model</span><span>当前查表结果</span>
        </div>

        {/* default 兜底 */}
        <div className="syp-route-row">
          <span className="syp-route-label">default <span className="syp-route-kind">兜底</span></span>
          <span className="syp-route-cell">
            <select value={draft.default.provider}
              onChange={e => setDraft(d => {
                if (d === undefined) return d
                const provider = e.target.value
                return { ...d, default: { provider, model: snapModel(d.default.model, provider) } }
              })}>
              <option value="">（不设 → 全部不烘焙）</option>
              {providers.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
            </select>
          </span>
          <span className="syp-route-cell">
            <ModelIdCell key={draft.default.provider} pid={draft.default.provider || '（未设 provider）'}
              models={modelsOf(draft.default.provider)} value={draft.default.model}
              onChange={v => setDraft(d => d === undefined ? d : { ...d, default: { ...d.default, model: v } })}
              listId="syp-ml-default" />
            <UnregHint pid={draft.default.provider} model={draft.default.model} />
          </span>
          <span className="syp-route-cell">
            <span className="syp-route-eff">{effOf(view.default)}</span>
            {view.default !== null && <span className="syp-route-via">via {view.default.via}</span>}
          </span>
        </div>

        {/* 五角色（含分工 tasks） */}
        {view.roles.map(role => (
          <div key={role.role}>
            <div className="syp-route-row">
              <span className="syp-route-label">{role.display} <span className="syp-route-kind">{role.role}</span></span>
              <span className="syp-route-cell">
                <select value={draft.roles[role.role].provider}
                  onChange={e => setDraft(d => {
                    if (d === undefined) return d
                    const provider = e.target.value
                    const r = d.roles[role.role]
                    return { ...d, roles: { ...d.roles, [role.role]: { ...r, provider, model: snapModel(r.model, provider) } } }
                  })}>
                  <option value="">（继承 default）</option>
                  {providers.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
                </select>
              </span>
              <span className="syp-route-cell">
                <ModelIdCell key={draft.roles[role.role].provider} pid={draft.roles[role.role].provider || '（未设 provider）'}
                  models={modelsOf(draft.roles[role.role].provider)} value={draft.roles[role.role].model}
                  onChange={v => setRoleField(role.role, 'model', v)}
                  listId={`syp-ml-${role.role}`} />
                <UnregHint pid={draft.roles[role.role].provider} model={draft.roles[role.role].model} />
                {modelsOf(draft.roles[role.role].provider).length > 0 && (
                  <span className="syp-route-cell-hint">已注册 {modelsOf(draft.roles[role.role].provider).length} 个模型，下拉直选</span>
                )}
              </span>
              <span className="syp-route-cell">
                <span className="syp-route-eff">{effOf(role.effective)}</span>
                {role.effective !== null && <span className="syp-route-via">via {role.effective.via}</span>}
              </span>
            </div>
            {role.tasks.map(task => (
              <div className="syp-route-row" data-task={true} key={task.kind}>
                <span className="syp-route-label">{task.display}分工 <span className="syp-route-kind">{task.kind}</span></span>
                <span className="syp-route-cell">
                  <select value={draft.roles[role.role].tasks[task.kind].provider}
                    onChange={e => setDraft(d => {
                      if (d === undefined) return d
                      const provider = e.target.value
                      const t = d.roles[role.role].tasks[task.kind]
                      const tasks = { ...d.roles[role.role].tasks, [task.kind]: { ...t, provider, model: snapModel(t.model, provider) } }
                      const r = d.roles[role.role]
                      return { ...d, roles: { ...d.roles, [role.role]: { ...r, tasks } } }
                    })}>
                    <option value="">（继承 default）</option>
                    {providers.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
                  </select>
                </span>
                <span className="syp-route-cell">
                  <ModelIdCell key={`${draft.roles[role.role].provider}-${task.kind}`} pid={draft.roles[role.role].tasks[task.kind].provider || '（未设 provider）'}
                    models={modelsOf(draft.roles[role.role].tasks[task.kind].provider)} value={draft.roles[role.role].tasks[task.kind].model}
                    onChange={v => setTaskField(role.role, task.kind, 'model', v)}
                    listId={`syp-ml-${role.role}-${task.kind}`} />
                  <UnregHint pid={draft.roles[role.role].tasks[task.kind].provider} model={draft.roles[role.role].tasks[task.kind].model} />
                </span>
                <span className="syp-route-cell">
                  <span className="syp-route-eff">{effOf(task.effective)}</span>
                  {task.effective !== null && <span className="syp-route-via">via {task.effective.via}</span>}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {msg !== '' && (msg.startsWith('保存失败') || msg.startsWith('请求失败')
        ? <div className="syp-err">{msg}</div> : <div className="syp-ok">{msg}</div>)}

      <div className="syp-route-actions">
        <button className="syp-btn syp-btn-primary" disabled={busy} onClick={() => { void save() }}>
          {busy ? '保存中…' : '保存路由表'}
        </button>
        <button className="syp-btn" disabled={busy} onClick={() => { void load() }}>放弃修改（重新加载）</button>
        <span className="syp-hint">查表规则：(role, task_kind) → tasks.&lt;kind&gt; → roles.&lt;role&gt; → default；条目留空即向上落兜底。</span>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- 注册 */

/**
 * 260823 起「模型」UI 不再占 chat 顶部页签——移到工单台侧栏中栏，
 * 由 suyou-workbench 的侧栏直接 import ProvidersSection 渲染（用户拍板：chat 页签只留 chat/trajectory）。
 * apply 保留为空操作（宿主装载契约要求导出）。
 */
export function apply(_ctx: ClientContext): void {
  /* 无注册：视图经 suyou-workbench 侧栏中栏承载 */
}
