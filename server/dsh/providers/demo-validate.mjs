/**
 * suyou-providers —— 添加 provider 前 dry-run 校验演示（t260821-08 安全红线）。
 *
 * 证明：写 settings.yaml 之前，能拒绝「不可解析」的 provider，绝不复现
 * 「deepseek-official 误塞 llm-pi-ai 导致整段失败」的坑。
 *
 * 做法：直接用真实 @deepseek-ai/dsh-llm-pi-ai 模块的 Config（schemastery schema，
 * 与设置 seam 写 llm-pi-ai 命名空间时跑的是同一份）+ supportedProtocols()，
 * 再叠一层与 resolveProfiles 同口径的服务性门（手声明 route 必须带
 * api/baseURL/models，模型 id 非空不重复）。
 *
 * 运行：node server/dsh/providers/demo-validate.mjs
 * （无机器绝对路径：经 $DSH_HOME 或 ~/.dsh 解析 dsh 已装模块。）
 */

import { homedir } from 'node:os'
import { join } from 'node:path'

const dshHome = process.env.DSH_HOME || join(homedir(), '.dsh')
const llmPi = join(dshHome, 'profiles', 'node_modules', '@deepseek-ai', 'dsh-llm-pi-ai', 'lib', 'index.js')

const { Config, supportedProtocols } = await import(llmPi)
const protocols = supportedProtocols()

/** 与 resolveProfiles 同口径的服务性门（schema 之外、跨字段约束）。 */
function serviceable(providers) {
  if (Array.isArray(providers)) throw new Error('providers 必须是 dict（route key → profile），不是数组')
  for (const [provider, source] of Object.entries(providers ?? {})) {
    if (provider.length === 0) throw new Error('provider 名不能为空')
    if (provider === 'deepseek-official') throw new Error('deepseek-official 由 dsh-llm-deepseek 拥有，禁止写进 llm-pi-ai.providers')
    if (source.api !== undefined && !protocols.includes(source.api)) throw new Error(`协议 "${source.api}" 不在白名单 ${protocols.join('/')}`)
    if (source.api === undefined) throw new Error('缺协议 api（手声明 route 必须命名协议）')
    if (source.baseURL === undefined) throw new Error('缺 baseURL')
    if (source.baseURL.length === 0) throw new Error('baseURL 为空')
    const models = source.models ?? []
    if (models.length === 0) throw new Error('模型 id 列表为空')
    const seen = new Set()
    for (const m of models) {
      if (!m?.id || m.id.length === 0) throw new Error('有模型缺 id')
      if (seen.has(m.id)) throw new Error(`模型 id "${m.id}" 重复`)
      seen.add(m.id)
    }
  }
  return true
}

const CASES = [
  {
    name: 'GOOD scnet 预置（openai-completions + baseURL + 模型 id 齐全）',
    want: 'pass',
    providers: {
      scnet: { apiKeyEnv: 'SCNET_API_KEY', api: 'openai-completions', baseURL: 'https://api.scnet.cn/api/llm/v1', models: [{ id: 'scnet-chat' }, { id: 'scnet-reasoner' }] },
    },
  },
  {
    name: 'BAD 协议不在白名单（api: websocket）',
    want: 'reject',
    providers: { bad1: { apiKeyEnv: 'X', api: 'websocket', baseURL: 'https://x.example/v1', models: [{ id: 'm' }] } },
  },
  {
    name: 'BAD 缺 baseURL（手声明 route）',
    want: 'reject',
    providers: { bad2: { apiKeyEnv: 'X', api: 'openai-completions', models: [{ id: 'm' }] } },
  },
  {
    name: 'BAD 模型 id 列表为空',
    want: 'reject',
    providers: { bad3: { apiKeyEnv: 'X', api: 'openai-completions', baseURL: 'https://x.example/v1', models: [] } },
  },
  {
    name: 'BAD 模型 id 重复',
    want: 'reject',
    providers: { bad4: { apiKeyEnv: 'X', api: 'openai-completions', baseURL: 'https://x.example/v1', models: [{ id: 'm' }, { id: 'm' }] } },
  },
  {
    name: 'BAD deepseek-official 误塞 llm-pi-ai（官方 deepseek 适配器 route）',
    want: 'reject',
    providers: { 'deepseek-official': { apiKeyEnv: 'DEEPSEEK_API_KEY' } },
  },
]

let failures = 0
for (const c of CASES) {
  let configOk = true
  let configErr = ''
  let svcOk = true
  let svcErr = ''
  try {
    Config({ providers: c.providers })
  } catch (e) {
    configOk = false
    configErr = String(e?.message ?? e).slice(0, 140)
  }
  try {
    serviceable(c.providers)
  } catch (e) {
    svcOk = false
    svcErr = String(e?.message ?? e).slice(0, 140)
  }
  const overallPass = configOk && svcOk
  const expected = c.want === 'pass'
  const verdict = overallPass === expected ? 'OK' : 'FAIL'
  if (verdict === 'FAIL') failures++
  console.log(`[${verdict}] ${c.name}`)
  console.log(`     Config schema     : ${configOk ? 'PASS' : `REJECT — ${configErr}`}`)
  console.log(`     serviceable 门    : ${svcOk ? 'PASS' : `REJECT — ${svcErr}`}`)
}

console.log(`\n协议白名单 = ${protocols.join(' / ')}`)
console.log(`结果：${CASES.length - failures}/${CASES.length} 例符合预期（GOOD 全 PASS、BAD 至少被一道门 REJECT）`)
process.exitCode = failures === 0 ? 0 : 1
