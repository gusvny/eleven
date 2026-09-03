/**
 * dsh-headless-resume —— 支持会话延续的 headless one-shot runner（dsh-headless 的平替）。
 *
 * 与 stock headless-runner 的唯一差别在 agent 获取方式：
 *   - 环境变量 DSH_HEADLESS_SESSION 置了会话 id → create-or-resume：
 *     agents.resume 恢复该会话（session 文件在 $DSH_HOME/sessions 下），
 *     恢复失败（会话不存在/损坏）则回落 agents.create 同 id 新建——不硬失败；
 *   - 未置 → 与 stock 行为一致（随机新会话，一次性）。
 * 其余（任务来源 headlessStartup、followup → whenIdle → flush → 打印 → 退出）逐行对齐
 * stock，行为无漂移。
 *
 * 用途：编排系统（如 Temporal 工单流）按确定性 session id 让同一角色的多次派活
 * 延续同一会话（写方案的人就是实现的人，打回意见在自己的会话里收到接着改），
 * 调用方只管设置 DSH_HEADLESS_SESSION=<id>，本插件无任何项目耦合。
 *
 * 挂载方式（patch 文件，不走 profile 主层——只对显式 --patch 的 spawn 生效）：
 *   - id: headless-runner
 *     disabled: true
 *   - insert:
 *       - id: headless-resume
 *         name: '<node.ts 的绝对路径>'   ← bare 包名解析到 dsh bin 根、相对名解析到
 *         inject: [headlessStartup]       profile 目录（实测），只有绝对路径不依赖
 *         config:                         安装位置；调用方 spawn 时生成一次性 patch
 *           task: !!js ctx.headlessStartup.task
 *   （模板见同目录 cordis.patch.yml）
 *
 * dsh 内部包（dsh-agent/dsh-llm/dsh-session/schemastery）经 createRequire(argv[1])
 * 解析——argv[1] 即 dsh 启动脚本，解析根=dsh 安装树，插件目录无需 node_modules。
 */

import { randomUUID } from 'node:crypto'
import { realpathSync } from 'node:fs'
import { createRequire } from 'node:module'
import type { Context } from '@deepseek-ai/cordis'

// argv[1]=dsh 启动脚本（可能是软链，如 /opt/homebrew/bin/dsh）——取 realpath 再
// createRequire，解析根=dsh 安装树（@deepseek-ai/* 在 dsh 自己的 node_modules 里）。
const _argv1 = process.argv[1] ? realpathSync(process.argv[1]) : import.meta.url
const _req = createRequire(_argv1)
const { installModelSelection } = await import(_req.resolve('@deepseek-ai/dsh-agent'))
const { createUserMessage } = await import(_req.resolve('@deepseek-ai/dsh-llm'))
const { SessionId } = await import(_req.resolve('@deepseek-ai/dsh-session'))
const { default: z } = await import(_req.resolve('@deepseek-ai/schemastery'))

export const name = 'headless-resume'
export const inject = ['agentDefaultModel', 'agents', 'sessions'] as const

export const Config = z.object({ task: z.string().required() })

/** 测试可替换的输出流（与 stock internals 同制式）。 */
export const internals = {
  stdout: process.stdout,
  stderr: process.stderr,
}

/** 汇总本轮产出（firstSeq 之后的 turn）：最终 assistant 文本 + turn 结局。 */
function summarize(events: any[], firstSeq: number) {
  let started = false
  let text = ''
  let reason: any
  for (const event of events) {
    if (event.seq < firstSeq) continue
    if (event.type === 'turn/start') {
      started = true
      continue
    }
    if (!started) continue
    if (event.type === 'assistant/message') {
      const joined = event.data.message.content
        .filter((block: any) => block.type === 'text')
        .map((block: any) => block.text)
        .join('')
      if (joined !== '') text = joined
    }
    if (event.type === 'turn/end') reason = event.data.reason
  }
  return { text, reason }
}

/** 汇报意外故障并请求失败退出。 */
function fail(io: any, error: unknown) {
  io.stderr.write(`dsh: ${error instanceof Error ? error.message : String(error)}\n`)
  io.exit(1)
}

async function run(ctx: Context, task: string, io: any) {
  await (ctx.get('loader') as any)?.await()
  const agents = ctx.get('agents') as any
  const defaultModel = ctx.get('agentDefaultModel') as any
  const sessions = ctx.get('sessions') as any
  if (agents === undefined || defaultModel === undefined || sessions === undefined) return
  const selection = defaultModel.currentSelection()
  const agentOptions = { provider: selection.provider, model: selection.model }
  const setup = (agentCtx: Context) => {
    installModelSelection(agentCtx, { current: selection, assembled: undefined })
  }

  // create-or-resume：DSH_HEADLESS_SESSION 置了 → 优先恢复同 id 会话；失败回落新建。
  const resumeId = (process.env.DSH_HEADLESS_SESSION ?? '').trim()
  let agent: any
  if (resumeId !== '') {
    try {
      agent = (await agents.resume({ resumeSessionId: SessionId(resumeId), agentOptions, setup })).agent
      io.stderr.write(`dsh-headless-resume: 已恢复会话 ${resumeId}\n`)
    } catch (err) {
      io.stderr.write(
        `dsh-headless-resume: 恢复会话 ${resumeId} 失败（回落新建同 id 会话）：` +
        `${err instanceof Error ? err.message : String(err)}\n`)
      try {
        agent = (await agents.create({
          sessionId: SessionId(resumeId),
          meta: { cwd: process.cwd() },
          agentOptions,
          setup,
        })).agent
      } catch (err2) {
        // 同 id 新建也失败 = 会话存储层损坏（t260829-06：agent 被杀于写入中留 zstd
        // 撕裂帧，resume 与同 id create 都撞死）。换全新会话 id 保流程不死；
        // 上下文丢失如实大声说，不静默。
        io.stderr.write(
          `dsh-headless-resume: 同 id 新建仍失败（${err2 instanceof Error ? err2.message : String(err2)}）` +
          `——会话存储疑似损坏，改用全新会话 id（上下文不可恢复，工单侧应检疫坏文件）\n`)
        agent = (await agents.create({
          sessionId: SessionId(`session-${randomUUID()}`),
          meta: { cwd: process.cwd() },
          agentOptions,
          setup,
        })).agent
      }
    }
  } else {
    agent = (await agents.create({
      sessionId: SessionId(`session-${randomUUID()}`),
      meta: { cwd: process.cwd() },
      agentOptions,
      setup,
    })).agent
  }

  await agent.whenIdle()
  const firstSeq = agent.session.seq
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: task }],
    source: { kind: 'user' },
  }))
  await agent.whenIdle()
  await sessions.flush(agent.session)
  const outcome = summarize(agent.session.events, firstSeq)
  io.stdout.write(outcome.text + '\n')
  if (outcome.reason?.kind === 'error') {
    io.stderr.write(`dsh: ${outcome.reason.error.code}: ${outcome.reason.error.message}\n`)
  }
  io.exit(outcome.reason?.kind === 'completed' ? 0 : 1)
}

export function apply(ctx: Context, config: { task: string }): void {
  const exit = ctx.get('appExit') as any
  if (exit === undefined) {
    throw new Error('headless-resume: the launcher must provide ctx.appExit before the tree mounts')
  }
  const io = { stdout: internals.stdout, stderr: internals.stderr, exit }
  run(ctx, config.task, io).catch((error) => { fail(io, error) })
}
