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
 *
 * 会话 id 寻址口径（t260922-06 源码实证）：0.1.1 与 0.1.5 无漂移——自定义 id 原生
 * 全链路有效（目录名=encodeSegment(id)、头记录 id=自定义 id、resume 按该 id 全项目
 * 扫描寻址），单点真源=自定义 id 本身，无需映射表。0.1.5 真正的接缝是形状面：
 * `Session.events` 快照数组被移除（stock 0.1.5 改走 eventAt(SessionSeq(seq)) 半开
 * 区间），旧实现在 0.1.5 下每次 spawn 收尾抛 `events is not iterable`。本实现按
 * 会话形状双轨（v3=eventAt / legacy=events 数组），形状违约一律响亮点名不裸崩；
 * 聚合逻辑拆在同目录 summarize.js（零依赖纯函数，node --test 可测）。
 *
 * 兜底触发判据（review gen1 意见4，不临场裁量）：若 live dsh 加载本插件报
 * ERR_MODULE_NOT_FOUND 且路径指向 ./summarize.js，才触发内联回退（备选 B：
 * summarize.js 内容并回本文件、损失纯函数可测性）；其余导入面失败一律按接缝
 * 漂移上报，不自行改道。
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
// SessionSeq 仅 0.1.5+ 存在（0.1.1 无此导出 → undefined；只在 v3 事件读取面需要，
// 0.1.1 必走 legacy 路径，不受影响）。SessionSeq 校验异常按 stock 语义原样透传。
const { SessionId, SessionSeq } = await import(_req.resolve('@deepseek-ai/dsh-session'))
const { default: z } = await import(_req.resolve('@deepseek-ai/schemastery'))
// 会话事件读取/聚合纯函数层 + stderr 词汇表（现行文案逐字锚）。显式 URL 动态导入，
// 绕开 TS loader 相对导入别名面；sibling 随泳道内物化 copytree 一并随行。
const { summarizeSession, messages } = await import(
  new URL('./summarize.js', import.meta.url).href)

export const name = 'headless-resume'
export const inject = ['agentDefaultModel', 'agents', 'sessions'] as const

export const Config = z.object({ task: z.string().required() })

/** 测试可替换的输出流（与 stock internals 同制式）。 */
export const internals = {
  stdout: process.stdout,
  stderr: process.stderr,
}

/** 汇报意外故障并请求失败退出（词汇单点=messages.fail，golden 锚在 summarize.test.mjs）。 */
function fail(io: any, error: unknown) {
  io.stderr.write(messages.fail(error instanceof Error ? error.message : String(error)))
  io.exit(1)
}

/**
 * agents.resume / agents.create 返回形状守卫（t260922-06 验收②）：
 * 形状漂移（含 null/undefined 两态）一律响亮点名拒绝，不裸崩、不静默。
 * 覆盖全部四处调用点：resume ×1（同 id 恢复）+ create ×3（同 id 回落新建 /
 * 全新 id 兜底 / 无 resumeId 一次性）。
 */
function requireAgent(returned: any, op: 'resume' | 'create'): any {
  if (returned == null || returned.agent == null) {
    throw new Error(messages.agentReturnShape(op))
  }
  return returned.agent
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
  // 每一处 agents.resume/create 都过形状守卫（漂移=响亮点名后仍走既有回落链，流程不死）。
  const resumeId = (process.env.DSH_HEADLESS_SESSION ?? '').trim()
  let agent: any
  if (resumeId !== '') {
    try {
      agent = requireAgent(
        await agents.resume({ resumeSessionId: SessionId(resumeId), agentOptions, setup }),
        'resume')
      io.stderr.write(messages.resumed(resumeId))
    } catch (err) {
      io.stderr.write(
        messages.resumeFailedFallbackCreate(
          resumeId, err instanceof Error ? err.message : String(err)))
      try {
        agent = requireAgent(await agents.create({
          sessionId: SessionId(resumeId),
          meta: { cwd: process.cwd() },
          agentOptions,
          setup,
        }), 'create')
      } catch (err2) {
        // 同 id 新建也失败 = 会话存储层损坏（t260829-06：agent 被杀于写入中留 zstd
        // 撕裂帧，resume 与同 id create 都撞死）。换全新会话 id 保流程不死；
        // 上下文丢失如实大声说，不静默。
        io.stderr.write(
          messages.sameIdCreateFailedFresh(
            err2 instanceof Error ? err2.message : String(err2)))
        agent = requireAgent(await agents.create({
          sessionId: SessionId(`session-${randomUUID()}`),
          meta: { cwd: process.cwd() },
          agentOptions,
          setup,
        }), 'create')
      }
    }
  } else {
    agent = requireAgent(await agents.create({
      sessionId: SessionId(`session-${randomUUID()}`),
      meta: { cwd: process.cwd() },
      agentOptions,
      setup,
    }), 'create')
  }

  await agent.whenIdle()
  const firstSeq = agent.session.seq
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: task }],
    source: { kind: 'user' },
  }))
  await agent.whenIdle()
  await sessions.flush(agent.session)
  // 会话事件读取面（t260922-06 验收②）：双形状（v3=eventAt 半开区间 / 0.1.1=events
  // 数组）自动判定，形状违约响亮点名（ShapeError），经 fail() 单点落 `dsh: …` exit 1，
  // 绝不再现 `events is not iterable` 裸崩。取舍清单见 summarize.js 头注。
  const outcome = summarizeSession(agent.session, firstSeq, SessionSeq)
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
