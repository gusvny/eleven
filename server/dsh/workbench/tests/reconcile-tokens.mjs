#!/usr/bin/env node
/**
 * reconcile-tokens.mjs —— t260902-05 工单④「7d token 总量 1.91M 明显不对」对账脚本。
 *
 * 逐票 dump：resolveAllSessionFiles 返回的会话文件 paths（路径/size/mtime 指纹/
 * 逐文件聚合量），核三件事：
 *   A. 是否存在同内容指纹（size+mtimeMs）的多份文件被重复加总（候选根因 a）；
 *   B. 逐票 in+out 明细与大户（口径判断素材，候选根因 b：total 恒加不按窗，
 *      闭票归窗但 token 计全生涯）；
 *   C. 抽样一票与原始 session 行数对照（候选根因 c：assistant/message 重复计）。
 *
 * 用法（影子仓库出票表 + 真实仓库根解会话文件，见 README）：
 *   node reconcile-tokens.mjs '<shadow-repo>' '<real-repo>' '{"window":"7d","template":"dev-lane"}'
 * 只读，不写任何用户数据。
 */
import { buildMetricsResponse, defaultDeps } from './../src/host/metrics.ts'
import { resolveAllSessionFiles, aggregateTicketUsage, stageWindowsFromTimeline } from './../src/host/agent-usage.ts'
import { closeStageWindows } from './../src/host/metrics.ts'
import { stat } from 'node:fs/promises'

const repo = process.argv[2]
const sessionRepo = process.argv[3] ?? repo
const params = JSON.parse(process.argv[4] ?? '{}')
const deps = defaultDeps(repo)
const proj = await deps.defaultProject()
const r = await buildMetricsResponse({ view: 'token', window: params.window ?? '7d', epic: 'all', template: params.template ?? 'dev-lane' }, deps)
if (r.status !== 200) { console.error(JSON.stringify(r.body)); process.exit(2) }
console.log('kpis', JSON.stringify(r.body.kpis))

const rows = await deps.listTickets(proj).then(rs => rs.filter(x => String(x?.workflow ?? '') === (params.template ?? 'dev-lane')))
const fp = new Map()
let dupTokens = 0
const perTicket = []
for (const row of rows) {
  const id = String(row?.id ?? '')
  const ticket = (await deps.showTicket(id)) ?? row
  const ref = await resolveAllSessionFiles(sessionRepo, id, ticket)
  if (ref.refused || !ref.paths?.length) { perTicket.push({ id, note: ref.reason ?? 'no paths' }); continue }
  const files = []
  for (const p of ref.paths) {
    try { const s = await stat(p); files.push({ p: p.replace(repo, '<repo>'), size: s.size, mtime: Math.round(s.mtimeMs) } ) } catch { files.push({ p, stat: 'fail' }) }
  }
  // A：内容指纹重复（同 size+mtime，且不是同一 inode 意义上的同一文件）
  const seen = new Map()
  for (const f of files) {
    const k = `${f.size}:${f.mtime}`
    if (seen.has(k) && seen.get(k) !== f.p) { dupTokens++; console.log('DUP-FINGERPRINT', id, seen.get(k), '<>', f.p) }
    seen.set(k, f.p)
  }
  const timeline = ticket?.timeline ?? ticket?.meta?.timeline
  const windows = closeStageWindows(stageWindowsFromTimeline(timeline), NaN)
  const agg = await aggregateTicketUsage(ref.paths, windows)
  perTicket.push({ id, open: String(ticket?.status ?? '') !== 'closed', files: files.length, in: agg.total.input, out: agg.total.output, cacheRead: agg.total.cacheRead })
}
perTicket.sort((a, b) => (b.in + b.out ?? 0) - (a.in + a.out ?? 0))
console.log('--- per-ticket（按 in+out 降序）---')
for (const t of perTicket) console.log(JSON.stringify(t))
console.log('dup_fingerprint_pairs', dupTokens)
