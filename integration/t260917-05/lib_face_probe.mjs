/**
 * lib_face_probe.mjs —— t260917-05 场景的 TS 半直调缝（review 意见7 钉死机制）。
 *
 * 机制：node >= 22.18 原生 type-stripping 直跑 .ts 模块导出（与 workbench smoke
 * 同范式，smoke/agent-usage.mjs:4）。本文件把三个被测导出包成 CLI：
 *   node lib_face_probe.mjs resolveAll '{"repo":…,"ticketId":…,"ticket":{…}}'
 *   node lib_face_probe.mjs resolveOne '{"repo":…,"ticketId":…,"ticket":{…}}'
 *   node lib_face_probe.mjs aggregate  '{"paths":[…],"windows":[…]}'
 * 输出：单行 JSON {"ok":true,"result":…} 或 {"ok":false,"error":"…"}（exit 0/1）。
 * zstd 缺席 → ENV_FAIL 点名（exit 2；家族先例 sc_torn_session_quarantine.py:58-60）。
 * 会话桩全部由场景临时目录固定文件提供，不依赖任何真实外部会话数据。
 */
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { resolveAllSessionFiles, aggregateTicketUsage } from '../../server/plugins/workbench/src/host/agent-usage.ts'
import { resolveSessionFile } from '../../server/plugins/workbench/src/host/agent-live.ts'

const execFileP = promisify(execFile)

async function main() {
  const [action, argRaw] = process.argv.slice(2)
  try {
    await execFileP('zstd', ['--version'])
  } catch {
    console.log(JSON.stringify({ ok: false, error: 'ENV_FAIL: zstd CLI 缺席（会话解析面依赖 zstd，环境缺供）' }))
    process.exit(2)
  }
  let arg
  try { arg = JSON.parse(argRaw ?? '{}') } catch (e) {
    console.log(JSON.stringify({ ok: false, error: `参数不是合法 JSON: ${e.message}` }))
    process.exit(1)
  }
  let result
  if (action === 'resolveAll') {
    result = await resolveAllSessionFiles(arg.repo, arg.ticketId, arg.ticket ?? null, arg.extraRoots ?? [])
  } else if (action === 'resolveOne') {
    result = await resolveSessionFile(arg.repo, arg.ticketId, arg.ticket ?? null, arg.extraRoots ?? [])
  } else if (action === 'aggregate') {
    result = await aggregateTicketUsage(arg.paths, arg.windows ?? [])
  } else {
    console.log(JSON.stringify({ ok: false, error: `未知 action: ${action}` }))
    process.exit(1)
  }
  console.log(JSON.stringify({ ok: true, result }))
}

main().catch(e => {
  console.log(JSON.stringify({ ok: false, error: String((e && e.message) || e) }))
  process.exit(1)
})
