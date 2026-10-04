/**
 * recent-actions.test.mjs —— 「最近动作」读源 UT（t261003-10 换源重写；gen5 按
 * rework 裁定改层：授权键与 caller_project 在 **summary 解析后对象顶层**）。
 * 夹具纪律：**真行逐字拷贝**——admin-log-real-current.jsonl（真行旧形状）与
 * admin-log-real-grant-rows.jsonl（真行带 summary 顶层授权键，摘自主仓
 * server/admin.log.20261003）皆零改动拷贝；畸形输入全桩化，零真外部源依赖。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import { readRecentActions, parseAdminLine, adminLogFile, fsActionsIo, TAIL_BYTES } from '../src/host/recent-actions.ts'

const here = dirname(fileURLToPath(import.meta.url))
const realLines = readFileSync(join(here, 'fixtures', 'admin-log-real-current.jsonl'), 'utf8')
const grantRows = readFileSync(join(here, 'fixtures', 'admin-log-real-grant-rows.jsonl'), 'utf8').trim().split('\n')

let n = 0
const dirs = []

function memIo(files) {
  return {
    files,
    existsSync: (f) => f in files,
    readFileSync: (f) => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f] },
  }
}
function envFor(file) { return { HOME: '/nonexistent-home', SANDBAR_ADMIN_LOG: file } }

// ---- 单行判定（真行）----
{
  const v = parseAdminLine(realLines.split('\n')[0], 'sandbar') // 真 sign 行（无授权键=旧窗口行）
  assert(v.kind === 'missing_auth', 'real old-shape sign row → missing_auth (no grant key anywhere in the row)')
  const bad = parseAdminLine('this line is not json')
  assert(bad.kind === 'malformed', 'non-JSON line → malformed')
  assert(parseAdminLine('[1,2,3]').kind === 'malformed', 'JSON array line → malformed')
  assert(parseAdminLine('42').kind === 'malformed', 'JSON scalar line → malformed')
  assert(parseAdminLine('   ').kind === 'other', 'blank line → other (not counted)')
  n += 5
}

// ---- 真授权行（summary 顶层键）：动作行全语义 ----
{
  const g0 = JSON.parse(grantRows[0]) // sub=ticket, grant op=sign, caller=sandbar, t261002-14
  const v = parseAdminLine(JSON.stringify(g0), 'sandbar')
  assert(v.kind === 'action', 'real grant row → action')
  assert(v.row.action === 'Sign' && v.row.permission === 'sign', 'action=Sign permission=sign (op vocabulary, recorded not invented)')
  assert(v.row.ticket === 't261002-14', 'ticket parsed from summary.result.ticket_id')
  assert(v.row.at === g0.ts * 1000, 'at = ts*1000 (epoch s → ms)')
  assert(v.row.result === 'ok', 'result reflects the audit ok flag')
  const g1 = JSON.parse(grantRows[1]) // sub=ticket-start, op=open-ticket, t261003-04
  const v1 = parseAdminLine(JSON.stringify(g1), 'sandbar')
  assert(v1.kind === 'action' && v1.row.action === 'Open ticket' && v1.row.permission === 'open-ticket' && v1.row.ticket === 't261003-04',
    'real ticket-start row → Open ticket / open-ticket / id from summary (generic sub does not win)')
  // caller_project 过滤读 summary 顶层：别的项目的授权行 → other
  const gX = JSON.parse(grantRows[0]); const sdX = JSON.parse(gX.summary); sdX.caller_project = 'other-project'; gX.summary = JSON.stringify(sdX); delete gX.caller_project
  assert(parseAdminLine(JSON.stringify(gX), 'sandbar').kind === 'other', 'summary-level caller_project of another project → other (filter reads the right level)')
  // summary 缺 caller_project → 行级兜底
  const gL = JSON.parse(grantRows[0]); const sdL = JSON.parse(gL.summary); delete sdL.caller_project; gL.summary = JSON.stringify(sdL); gL.caller_project = 'other-project'
  assert(parseAdminLine(JSON.stringify(gL), 'sandbar').kind === 'other', 'line-level caller_project fallback still filters')
  // 行级授权键兜底（非 summary 层）也认
  const lineLevel = parseAdminLine(JSON.stringify({ sub: 'ticket', ok: true, executor_grant_op: 'send-back', summary: '{"ok":true,"result":{"ticket_id":"t9"}}' }), 'sandbar')
  assert(lineLevel.kind === 'action' && lineLevel.row.action === 'Send back' && lineLevel.row.permission === 'send-back', 'line-level grant key fallback → Send back')
  // unknown sub AND unknown op → unmapped（计数，不编造）
  const unknownBoth = parseAdminLine(JSON.stringify({ sub: 'ticket.teleport', executor_grant_op: 'teleport', summary: '{}' }))
  assert(unknownBoth.kind === 'unmapped' && unknownBoth.permission === 'teleport', 'unknown sub AND unknown op → unmapped (counted, not invented)')
  n += 9
}

// ---- 读面：真行旧形状 → 显式降级，绝不空表冒充 ----
{
  const file = '/nonexistent/admin.log'
  const r1 = readRecentActions(memIo({}), envFor(file), 'sandbar')
  assert(r1.ok === false && r1.reason.includes(file), 'absent source → ok:false naming the resolved path')
  const errIo = { existsSync: () => true, readFileSync: () => { throw new Error('EACCES') } }
  const r2 = readRecentActions(errIo, envFor(file), 'sandbar')
  assert(r2.ok === false && r2.reason.includes('unreadable') && r2.reason.includes('EACCES'), 'unreadable source → ok:false naming the reason')
  const r3 = readRecentActions(memIo({ [file]: realLines }), envFor(file), 'sandbar')
  assert(r3.ok === false && r3.reason.includes('none of them records which permission authorized it'),
    'real old-shape rows → degraded card naming the missing per-row authorization')
  const readOnlyRows = realLines.split('\n').filter((l) => l.includes('ticket-list') || l.includes('ticket-query')).join('\n') + '\n'
  const r4 = readRecentActions(memIo({ [file]: readOnlyRows }), envFor(file), 'sandbar')
  assert(r4.ok === false && r4.reason.includes('no gated executor actions'), 'read-only rows only → explicit no-gated-actions degradation')
  n += 4
}

// ---- 读面：真授权行 → 动作行出列，坏行计数，排序，max 截断 ----
{
  const file = '/nonexistent/admin.log'
  const lines = [
    ...grantRows,
    'garbage line',
    JSON.stringify({ sub: 'ticket.teleport', executor_grant_op: 'teleport', caller_project: 'sandbar', summary: '{}' }),
    realLines.split('\n')[0], // 真行旧形状 → missing_auth
    '',
  ]
  const io = memIo({ [file]: lines.join('\n') + '\n' })
  const r = readRecentActions(io, envFor(file), 'sandbar')
  assert(r.ok === true, 'real grant rows → ok:true with rows')
  assert(r.actions.length === 3, 'the three permission-bearing rows shown')
  assert(r.actions.every((a) => a.permission !== ''), 'every shown row names its permission')
  assert(r.actions[0].ticket === 't261003-05' && r.actions[2].ticket === 't261002-14', 'newest first (real ts ordering)')
  assert(r.malformed_rows === 1 && r.unmapped_rows === 1 && r.missing_authorization_rows === 1, 'bad/unknown/missing-auth all counted, none silent')
  const rMax = readRecentActions(io, envFor(file), 'sandbar', 1)
  assert(rMax.ok === true && rMax.actions.length === 1, 'max truncation works')
  n += 6
}

// ---- 项目过滤：别的项目（summary 层 caller_project）绝不混入 ----
{
  const file = '/nonexistent/admin.log'
  const g0 = JSON.parse(grantRows[0]); const sd = JSON.parse(g0.summary); sd.caller_project = 'other-project'; g0.summary = JSON.stringify(sd); delete g0.caller_project
  const io = memIo({ [file]: JSON.stringify(g0) + '\n' + grantRows[0] + '\n' })
  const r = readRecentActions(io, envFor(file), 'sandbar')
  assert(r.ok === true && r.actions.length === 1 && r.actions[0].ticket === 't261002-14', 'foreign-project gated row excluded, own row kept')
  n += 1
}

// ---- 尾读窗口（fs 版真文件）：fd 收口 + 残首行丢弃 ----
{
  const dir = freshDir()
  dirs.push(dir)
  const file = join(dir, 'admin.log')
  const pad = 'x'.repeat(200) + '\n'
  writeFileSync(file, pad.repeat(TAIL_BYTES / 200) + grantRows[0] + '\n')
  const r = readRecentActions(fsActionsIo, envFor(file), 'sandbar')
  assert(r.ok === true && r.actions.length === 1 && r.actions[0].permission === 'sign', 'tail read over real fs file parses the trailing real grant row (window fits)')
  const ioSmall = {
    existsSync: fsActionsIo.existsSync,
    readFileSync: fsActionsIo.readFileSync,
    readTail: (f, b) => fsActionsIo.readTail(f, 120),
  }
  const r2 = readRecentActions(ioSmall, envFor(file), 'sandbar')
  assert(r2.ok === false && !r2.reason.includes('unreadable'), 'partial first line dropped by tail read (no crash, no miscount)')
  n += 2
}

// ---- adminLogFile 路径解析 ----
{
  assert(adminLogFile({ SANDBAR_ADMIN_LOG: '/tmp/x.log' }) === '/tmp/x.log', 'env override wins (engine-audit.py same key)')
  const fallback = adminLogFile({})
  assert(fallback.endsWith('/server/admin.log'), 'module-relative fallback resolves to <repo>/server/admin.log (got ' + fallback + ')')
  n += 2
}

cleanup(dirs)
done(n)
