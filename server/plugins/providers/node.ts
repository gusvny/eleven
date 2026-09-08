/**
 * sandbar-providers —— LLM provider 管理与优先级（B 版：手动排序+一键切换）· 宿主半 / node。
 *
 * 职责：在 dsh 自己的 webServer 上挂 /sandbar-providers/api/*，供本插件浏览器半
 * （lib/client.js，设置面板「模型」分区）同源 fetch 使用：
 *
 *   GET  /sandbar-providers/api/state             → 当前快照：4 provider 列表（优先级序）、
 *                                                 当前 agent-default-model、协议白名单、scnet 预置
 *   POST /sandbar-providers/api/add-provider      → 「添加 provider」：baseURL/协议/模型 id 列表/key 环境变量
 *                                                 写 settings.yaml 的 llm-pi-ai.providers
 *   POST /sandbar-providers/api/set-current       → 「设为当前」：写 agent-default-model（provider+model+reasoningEffort?）
 *   POST /sandbar-providers/api/update-note       → 某 provider 的计费档说明（用户可编辑）
 *   POST /sandbar-providers/api/reorder           → 优先级顺序持久化（上下移/拖拽）
 *   POST /sandbar-providers/api/delete-provider   → 从 llm-pi-ai.providers 删除一个已声明 route
 *
 * 安全红线（t260821-08 明令，deepseek-official 教训）：写入 settings.yaml 的 provider
 * **必须先 dry-run 校验「合法可解析」**。本插件不直接改 settings.yaml 文本，而是走
 * dsh 设置 seam 的 `ctx.settings.mutate('llm-pi-ai', …)`——该写路径在持久化之前会先跑
 * llm-pi-ai 适配器注册的 `assertServiceable`（= resolveProfiles：校验协议∈白名单、
 * baseURL 非空且 http(s)、模型 id 非空不重复、手声明 route 必须带 api/baseURL/models），
 * 校验不过即拒绝、不落盘。add-provider 之外再加一道表单预校验（同口径），错误信息更友好。
 * 「deepseek-official」由 dsh-llm-deepseek 适配器拥有，本插件永远拒绝把它写进
 * llm-pi-ai.providers（只读列出、可「设为当前」、不可 add/delete）。
 *
 * 优先级顺序 + 计费说明存独立 JSON（server/plugins/providers/state.json），不进 settings.yaml：
 * 避免给 llm-pi-ai 命名空间塞进不属于它的字段。两者都以 node:fs 读写，无运行时第三方依赖。
 *
 * headless profile 没有 webServer：apply 静默待命（internal/service 事件等不到就不挂路由），
 * 不报错不阻塞。settings 服务由 dsh-base 提供，handler 里按需 `ctx.get('settings')`。
 *
 * 本文件固定落在 <repo>/server/plugins/providers/node.ts 下；无任何机器绝对路径写死。
 */

import { readFile, writeFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'

export const name = 'sandbar-providers'
// webServer 只存在于 web profile；headless 下本插件待机即可，故不走 inject 硬依赖。
export const inject: string[] = []

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))
const STATE_PATH = join(PLUGIN_DIR, 'state.json')

/** llm-pi-ai 适配器可服务的手声明路由协议白名单（与 supportedProtocols() 对齐）。 */
const PROTOCOLS = ['openai-completions', 'openai-responses', 'anthropic-messages']
/** 由 dsh-llm-deepseek（官方 deepseek 适配器）拥有的 route：可读可设当前，绝不进 llm-pi-ai。 */
const EXTERNAL_PROVIDERS = new Set(['deepseek-official'])

/** scnet 预置模板（t260821-11：预填 14 个模型 id，一键添加不用手填。
 * id 用 scnet API 的原始驼峰名——网关只认原始 id，不认小写规范名）。 */
const SCNET_MODELS = [
  'GLM-5.2', 'GLM-5', 'GLM-5.1',
  'MiniMax-M3', 'MiniMax-M2.7', 'MiniMax-M2.5',
  'Kimi-K3', 'Kimi-K2.5', 'Kimi-K2.7-Code', 'Kimi-K2.6',
  'Qwen3.8-Max', // 视觉（image）
  'DeepSeek-V4-Flash-0731', 'DeepSeek-V4-Pro', 'DeepSeek-V4-Flash',
]
const SCNET_PRESET = {
  id: 'scnet',
  displayName: 'SCNet',
  api: 'openai-completions',
  baseURL: 'https://api.scnet.cn/api/llm/v1',
  // 备选 anthropic：https://api.scnet.cn/api/llm/anthropic（仅作注释，不做自动 failover）
  apiKeyEnv: 'SCNET_API_KEY',
  models: SCNET_MODELS,
  description: '深算网络 openai-completions 网关；anthropic 备选 baseURL=https://api.scnet.cn/api/llm/anthropic',
}

/** 优先级顺序 + 计费说明的持久化状态。 */
interface ProviderState {
  priority: string[]
  notes: Record<string, string>
}

const DEFAULT_STATE: ProviderState = {
  priority: ['deepseek-official', 'zai', 'kimi-coding', 'scnet'],
  notes: {},
}

async function loadState(): Promise<ProviderState> {
  try {
    const raw = JSON.parse(await readFile(STATE_PATH, 'utf8'))
    return {
      priority: Array.isArray(raw?.priority) ? raw.priority.filter((x: unknown) => typeof x === 'string') : [...DEFAULT_STATE.priority],
      notes: raw?.notes && typeof raw.notes === 'object' && !Array.isArray(raw.notes) ? raw.notes : {},
    }
  } catch {
    return { priority: [...DEFAULT_STATE.priority], notes: {} }
  }
}

async function saveState(state: ProviderState): Promise<void> {
  await writeFile(STATE_PATH, JSON.stringify(state, null, 2) + '\n', 'utf8')
}

/** 读 POST JSON body（64KB 封顶），非法 JSON 抛错。 */
async function readJsonBody(req: IncomingMessage): Promise<any> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += (chunk as Buffer).length
    if (size > 64 * 1024) throw new Error('body 超过 64KB')
    chunks.push(chunk as Buffer)
  }
  const text = Buffer.concat(chunks).toString('utf8')
  return text === '' ? {} : JSON.parse(text)
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

/** 取 provider 的模型 id 清单（供前端 datalist 下拉）。
 *  优先级：① dsh-llm 运行时注册表 listModels（catalog + settings 手配合并后的真值，
 *  pi-ai 适配器 1660 实现；旧版从 settings JSON 上找 piProvider.getModels 是断的——
 *  settings 值是纯 JSON 没有运行时对象，恒空，260828 修好）；
 *  ② settings JSON 的 models 段（手配 route 如 scnet 直接有）；
 *  ③ 空数组（前端退化为自由文本，原降级契约保留）。 */
async function modelsOf(ctx: any, id: string, prof: any): Promise<string[]> {
  const toIds = (list: any[]): string[] =>
    list.map((m: any) => (typeof m === 'string' ? m : m?.id)).filter((x: unknown) => typeof x === 'string' && x.length > 0)
  try {
    const llm = ctx.get('llm')
    if (llm && typeof llm.listModels === 'function') {
      const ids = toIds(await llm.listModels(id) ?? [])
      if (ids.length > 0) return ids
    }
  } catch { /* provider 未注册/服务不在 → 落 settings 段 */ }
  if (Array.isArray(prof?.models)) return toIds(prof.models)
  return []
}

/** 汇总 provider 列表（优先级序）：llm-pi-ai 已解析路由 + 外部 route + scnet 预置。 */
async function collectProviders(ctx: any, settings: any, state: ProviderState, checkKey: (env: string) => Promise<boolean>): Promise<any[]> {
  const llmPi = settings.get('llm-pi-ai')
  const adModel = settings.get('agent-default-model')
  const piProviders = llmPi?.providers && typeof llmPi.providers === 'object' ? llmPi.providers : {}
  const currentProvider = typeof adModel?.provider === 'string' ? adModel.provider : ''
  const currentModel = typeof adModel?.model === 'string' ? adModel.model : ''

  const byId = new Map<string, any>()
  const keySet = new Map<string, boolean>()
  const envs = new Set<string>()

  const resolveKeyStates = async (): Promise<void> => {
    for (const env of envs) keySet.set(env, await checkKey(env))
  }

  for (const [id, prof] of Object.entries(piProviders)) {
    if (typeof (prof as any)?.apiKeyEnv === 'string') envs.add((prof as any).apiKeyEnv)
  }
  envs.add(SCNET_PRESET.apiKeyEnv)
  await resolveKeyStates()

  for (const [id, prof] of Object.entries(piProviders)) {
    const env = typeof (prof as any)?.apiKeyEnv === 'string' ? (prof as any).apiKeyEnv : null
    byId.set(id, {
      id,
      kind: 'pi-ai',
      displayName: (prof as any)?.displayName || id,
      api: (prof as any)?.api ?? null,
      baseURL: (prof as any)?.baseURL ?? null,
      apiKeyEnv: env,
      keySet: env !== null ? (keySet.get(env) ?? false) : false,
      models: await modelsOf(ctx, id, prof),
      note: state.notes[id] ?? '',
      isCurrent: id === currentProvider,
      currentModel: id === currentProvider ? currentModel : '',
      added: true,
    })
  }

  if (currentProvider && !byId.has(currentProvider)) {
    byId.set(currentProvider, {
      id: currentProvider,
      kind: 'external',
      displayName: currentProvider,
      api: null,
      baseURL: null,
      apiKeyEnv: null,
      keySet: false,
      models: [],
      note: state.notes[currentProvider] ?? '',
      isCurrent: true,
      currentModel,
      added: true,
    })
  }

  if (!byId.has(SCNET_PRESET.id)) {
    byId.set(SCNET_PRESET.id, {
      ...SCNET_PRESET,
      kind: 'preset',
      keySet: keySet.get(SCNET_PRESET.apiKeyEnv) ?? false,
      models: [...SCNET_PRESET.models],
      note: state.notes[SCNET_PRESET.id] ?? '',
      isCurrent: SCNET_PRESET.id === currentProvider,
      currentModel: SCNET_PRESET.id === currentProvider ? currentModel : '',
      added: false,
    })
  }

  const seen = new Set<string>()
  const ordered: string[] = []
  for (const id of state.priority) {
    if (byId.has(id) && !seen.has(id)) { seen.add(id); ordered.push(id) }
  }
  for (const id of [...byId.keys()].sort()) {
    if (!seen.has(id)) ordered.push(id)
  }
  return ordered.map(id => byId.get(id)!)
}

/** add-provider 表单预校验（与 llm-pi-ai assertServiceable 同口径，错误信息更友好）。 */
function validateProviderInput(body: any): { ok: true; id: string; profile: Record<string, unknown> } | { ok: false; error: string } {
  const id = String(body.id ?? '').trim()
  const api = String(body.api ?? '').trim()
  const baseURL = String(body.baseURL ?? '').trim()
  const apiKeyEnv = String(body.apiKeyEnv ?? '').trim()
  const displayName = String(body.displayName ?? '').trim()
  const models = Array.isArray(body.models)
    ? body.models.map((x: unknown) => String(x).trim()).filter((x: string) => x.length > 0)
    : []

  if (!/^[a-z0-9][a-z0-9._-]{0,63}$/i.test(id)) {
    return { ok: false, error: 'provider id 不合法：字母/数字开头，可含 - . _，≤64 字符' }
  }
  if (EXTERNAL_PROVIDERS.has(id)) {
    return { ok: false, error: `provider "${id}" 由 dsh 官方 deepseek 适配器拥有，不可写进 llm-pi-ai.providers（deepseek-official 教训）` }
  }
  if (!PROTOCOLS.includes(api)) {
    return { ok: false, error: `协议 api 必须是 ${PROTOCOLS.join(' / ')} 之一，得到「${api}」` }
  }
  let u: URL
  try {
    u = new URL(baseURL)
  } catch {
    return { ok: false, error: 'baseURL 不是合法 URL' }
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') {
    return { ok: false, error: 'baseURL 协议必须是 http/https' }
  }
  if (!apiKeyEnv) {
    return { ok: false, error: 'key 环境变量 apiKeyEnv 必填（如 SCNET_API_KEY）' }
  }
  if (models.length === 0) {
    return { ok: false, error: '模型 id 列表不能为空（至少一个模型 id，逐行填）' }
  }
  if (new Set(models).size !== models.length) {
    return { ok: false, error: '模型 id 列表有重复' }
  }

  const profile: Record<string, unknown> = { apiKeyEnv, api, baseURL, models: models.map(mid => ({ id: mid })) }
  if (displayName) profile.displayName = displayName
  return { ok: true, id, profile }
}

export function apply(ctx: Context): void {
  /** 请求期取 settings 服务（dsh-base 已提供；到请求时一定就绪）。 */
  function getSettings(): any {
    const s = ctx.get('settings')
    if (s === undefined) throw new Error('settings service 未就绪（headless 无 webServer 不挂路由）')
    return s
  }

/** 请求期取 credentials 服务（dsh-credentials-local 提供：resolve/set/unset，写 $DSH_HOME/.credentials.yaml）。 */
  function getCredentials(): any {
    const c = ctx.get('credentials')
    return c // headless/宿主未提供时为 undefined，调用方自行跳过（key 直填不可用但加 provider 不受影响）
  }

  /** 查一个 apiKeyEnv 是否已有可用 key（不回传值，只回布尔，避免 key 上浏览器）。 */
  async function keyIsSet(envName: string | null): Promise<boolean> {
    if (!envName) return false
    const c = getCredentials()
    if (!c || typeof c.resolve !== 'function') return false
    try {
      const hit = await c.resolve(envName)
      return typeof hit?.value === 'string' && hit.value.length > 0
    } catch { return false }
  }

  /* ------------------------------------------------------------ handlers */

  async function handleState(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const settings = getSettings()
      const state = await loadState()
      const adModel = settings.get('agent-default-model')
      sendJson(res, 200, {
        ok: true,
        result: {
          current: {
            provider: typeof adModel?.provider === 'string' ? adModel.provider : '',
            model: typeof adModel?.model === 'string' ? adModel.model : '',
            reasoningEffort: typeof adModel?.reasoningEffort === 'string' ? adModel.reasoningEffort : '',
          },
          providers: await collectProviders(ctx, settings, state, keyIsSet),
          protocols: PROTOCOLS,
          scnetPreset: SCNET_PRESET,
          settingsPath: settings.documentPath ?? '~/.dsh/settings.yaml',
        },
      })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function handleAdd(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const v = validateProviderInput(body)
    if (!v.ok) { sendJson(res, 400, { ok: false, error: v.error }); return }

    const settings = getSettings()
    const existing = settings.get('llm-pi-ai')?.providers
    if (existing && Object.prototype.hasOwnProperty.call(existing, v.id)) {
      sendJson(res, 409, { ok: false, error: `provider "${v.id}" 已存在于 llm-pi-ai.providers` })
      return
    }
    // t260821-11 ②：key 直填——非空 apiKey 走 dsh credentials seam 写进
    // $DSH_HOME/.credentials.yaml（0600，env 层仍优先），settings.yaml 只落 apiKeyEnv 引用。
    const apiKey = typeof body.apiKey === 'string' ? body.apiKey : ''
    if (apiKey.trim() !== '') {
      const credentials = getCredentials()
      if (!credentials || typeof credentials.set !== 'function') {
        sendJson(res, 400, { ok: false, error: 'credentials 服务不可用，无法直接存 key（可只填 apiKeyEnv 后自行导出环境变量）' })
        return
      }
      try {
        await credentials.set(v.profile.apiKeyEnv as string, apiKey)
      } catch (err) {
        sendJson(res, 400, { ok: false, error: `key 写入 credentials 失败（未改 settings.yaml）：${String((err as any)?.message ?? err)}` })
        return
      }
    }
    try {
      // 关键安全点：走 settings 设置 seam，llm-pi-ai 的 assertServiceable 会在持久化前
      // dry-run 解析整段 providers，坏 provider 直接拒绝、绝不落盘。
      await settings.mutate('llm-pi-ai', [{ op: 'set', path: ['providers', v.id], value: v.profile }])
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `llm-pi-ai 拒绝该 provider（已 dry-run 校验，未写入 settings）：${String((err as any)?.message ?? err)}` })
      return
    }
    const state = await loadState()
    if (!state.priority.includes(v.id)) state.priority.push(v.id)
    if (typeof body.note === 'string' && body.note.trim() !== '') state.notes[v.id] = body.note.trim()
    await saveState(state)
    sendJson(res, 200, { ok: true, result: { added: v.id } })
  }

  async function handleSetCurrent(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const provider = String(body.provider ?? '').trim()
    const model = String(body.model ?? '').trim()
    const re = body.reasoningEffort === undefined || body.reasoningEffort === null || body.reasoningEffort === ''
      ? undefined : String(body.reasoningEffort).trim()
    if (!provider) { sendJson(res, 400, { ok: false, error: '缺少 provider' }); return }
    if (!model) { sendJson(res, 400, { ok: false, error: '缺少 model（请填模型 id）' }); return }

    const section: Record<string, unknown> = { provider, model }
    if (re) section.reasoningEffort = re
    try {
      await getSettings().replace('agent-default-model', section)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `agent-default-model 拒绝该选择：${String((err as any)?.message ?? err)}` })
      return
    }
    sendJson(res, 200, { ok: true, result: { current: { provider, model, reasoningEffort: re ?? '' } } })
  }

  async function handleNote(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const id = String(body.id ?? '').trim()
    if (!id) { sendJson(res, 400, { ok: false, error: '缺少 id' }); return }
    const state = await loadState()
    state.notes[id] = String(body.note ?? '').trim()
    await saveState(state)
    sendJson(res, 200, { ok: true, result: { id, note: state.notes[id] } })
  }

  async function handleReorder(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const order = Array.isArray(body.order) ? body.order.map((x: unknown) => String(x).trim()).filter((x: string) => x.length > 0) : []
    if (order.length === 0 || new Set(order).size !== order.length) {
      sendJson(res, 400, { ok: false, error: 'order 必须是非空、无重复的 provider id 数组' })
      return
    }
    const state = await loadState()
    state.priority = order
    await saveState(state)
    sendJson(res, 200, { ok: true, result: { priority: order } })
  }

  async function handleDelete(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const id = String(body.id ?? '').trim()
    if (!id) { sendJson(res, 400, { ok: false, error: '缺少 id' }); return }
    if (EXTERNAL_PROVIDERS.has(id)) { sendJson(res, 400, { ok: false, error: `provider "${id}" 是官方适配器 route，不可删除` }); return }
    const settings = getSettings()
    const existing = settings.get('llm-pi-ai')?.providers
    if (!existing || !Object.prototype.hasOwnProperty.call(existing, id)) {
      sendJson(res, 409, { ok: false, error: `provider "${id}" 不在 llm-pi-ai.providers` })
      return
    }
    try {
      await settings.mutate('llm-pi-ai', [{ op: 'unset', path: ['providers', id] }])
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `llm-pi-ai 拒绝删除：${String((err as any)?.message ?? err)}` })
      return
    }
    const state = await loadState()
    state.priority = state.priority.filter(x => x !== id)
    delete state.notes[id]
    await saveState(state)
    sendJson(res, 200, { ok: true, result: { deleted: id } })
  }

  /* ------------------------------------------------------------ 挂路由 */

  const attach = (ws: any): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/sandbar-providers/api/state', handler: handleState }),
        ws.register({ kind: 'exact', path: '/sandbar-providers/api/add-provider', handler: handleAdd }),
        ws.register({ kind: 'exact', path: '/sandbar-providers/api/set-current', handler: handleSetCurrent }),
        ws.register({ kind: 'exact', path: '/sandbar-providers/api/update-note', handler: handleNote }),
        ws.register({ kind: 'exact', path: '/sandbar-providers/api/reorder', handler: handleReorder }),
        ws.register({ kind: 'exact', path: '/sandbar-providers/api/delete-provider', handler: handleDelete }),
      ]
      return () => { for (const dispose of disposers) dispose() }
    }, 'sandbar-providers: provider api routes')
    ctx.logger.info('sandbar-providers: provider 管理 API 已挂载 /sandbar-providers/api/*')
  }

  // webServer 可能先已提供（直接取），也可能后到（等 internal/service 事件）；
  // headless 永远等不到——待机即正确行为。
  const existing = ctx.get('webServer')
  if (existing !== undefined) {
    attach(existing)
    return
  }
  const dispose = ctx.on('internal/service', (serviceName: string, value: any) => {
    if (serviceName !== 'webServer') return
    dispose()
    attach(value)
  })
}
