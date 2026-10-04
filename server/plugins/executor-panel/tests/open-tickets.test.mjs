/**
 * open-tickets.test.mjs —— t261004-19「Open tickets in these epics」面板半边 UT。
 *
 * 覆盖：
 *  - 声明镜像校验：open_ticket_epics / open_ticket_cap 接受与畸形具名拒收（含
 *    非数组 / 非串项 / 坏代号 / 超上限 / 坏 cap——外部输入纪律：桩直灌）；
 *  - 保存搬运：epic 清单随保存落盘；下次保存不带=继承不静默抹掉；审计行带 epic；
 *  - epic 列表读面：SANDBAR_EPICS_DIR 锚列全部 epic（code + 状态行原文 + authorized），
 *    目录缺席=空数组不报错；坏目录锚=ok:false 点名原因（显式降级，不渲染空表冒充）；
 *  - C3 fail-soft：epicFromGrantSource 认 allowed 行的 grant_source 形状、refused
 *    行的 reason 点名；旧行/缺形状/垃圾输入返回 '' 不抛；parseActionLine 对无
 *    grant_source 的旧行照常出 action 行（epic 不设键，行不吞）。
 * 零真实 ~/.sandbar、零 3099。
 */
import { assert, done, freshDir, cleanup, fakeClock } from './lib.mjs'
import { validateDeclaration, saveGrantsDecl, declarationPath, auditPath, readDeclaration } from '../src/host/executor-grants.ts'
import { listOpenTicketEpics } from '../src/host/open-tickets.ts'
import { epicFromGrantSource, parseActionLine } from '../src/host/recent-actions.ts'
import { mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'

const wd = freshDir(), epicsDir = freshDir()
const env = { HOME: '/nonexistent-home', SANDBAR_PROJECTS_DIR: wd, SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: wd, SANDBAR_EPICS_DIR: epicsDir }
const clock = fakeClock()
let n = 0
try {
  // ---- 声明镜像校验 ----
  {
    const [ok, err] = validateDeclaration({ version: 1, grants: {}, open_ticket_epics: ['proj-exec', 'ki-x'], open_ticket_cap: 5 })
    assert(!err && ok.open_ticket_epics.join(',') === 'proj-exec,ki-x' && ok.open_ticket_cap === 5, `accept new keys (${++n})`)
    const [dd] = validateDeclaration({ version: 1, grants: {}, open_ticket_epics: ['a', 'a', ' b '] })
    assert(dd.open_ticket_epics.join(',') === 'a,b', `dedupe + trim (${++n})`)
    const [d1] = validateDeclaration({ version: 1, grants: {} })
    assert(d1.open_ticket_epics.length === 0 && d1.open_ticket_cap === 3, `defaults (${++n})`)
    const bads = [
      [{ version: 1, grants: {}, open_ticket_epics: 'nope' }, 'array'],
      [{ version: 1, grants: {}, open_ticket_epics: [1] }, 'string items'],
      [{ version: 1, grants: {}, open_ticket_epics: [''] }, 'empty item'],
      [{ version: 1, grants: {}, open_ticket_epics: ['BAD_CODE'] }, 'code shape'],
      [{ version: 1, grants: {}, open_ticket_cap: 0 }, 'cap zero'],
      [{ version: 1, grants: {}, open_ticket_cap: true }, 'cap bool'],
      [{ version: 1, grants: {}, open_ticket_cap: 1.5 }, 'cap float'],
      [{ version: 1, grants: {}, open_ticket_cap: '3' }, 'cap string'],
    ]
    for (const [doc, label] of bads) {
      const [, e] = validateDeclaration(doc)
      assert(typeof e === 'string' && e.length > 0, `malformed refused, named: ${label} (${++n})`)
    }
    const longList = Array.from({ length: 65 }, (_, i) => 'e' + i)
    const [, e64] = validateDeclaration({ version: 1, grants: {}, open_ticket_epics: longList })
    assert(e64 && e64.includes('open_ticket_epics'), `list cap named (${++n})`)
  }

  // ---- 保存搬运 + 审计 ----
  {
    const r = saveGrantsDecl('sandbar', { grants: { 'open-ticket': true }, open_ticket_epics: ['proj-exec'], open_ticket_cap: 7 }, 'host', env, clock.now())
    assert(r.saved === true && r.resolved.open_ticket_epics.join(',') === 'proj-exec' && r.resolved.open_ticket_cap === 7, `save carries (${++n})`)
    const onDisk = JSON.parse(readFileSync(declarationPath('sandbar', env), 'utf8'))
    assert(onDisk.open_ticket_epics.join(',') === 'proj-exec' && onDisk.open_ticket_cap === 7, `file shape (${++n})`)
    const r2 = saveGrantsDecl('sandbar', { grants: { sign: true } }, 'host', env, clock.now())
    assert(r2.saved === true && r2.resolved.open_ticket_epics.join(',') === 'proj-exec', `inherit on partial save (${++n})`)
    const rows = readFileSync(auditPath('sandbar', env), 'utf8').trim().split('\n').map((l) => JSON.parse(l))
    assert(rows.every((row) => Array.isArray(row.open_ticket_epics)), `audit rows carry epic list (${++n})`)
  }

  // ---- epic 列表读面 ----
  {
    mkdirSync(join(epicsDir, 'x'), { recursive: true })
    writeFileSync(join(epicsDir, 'proj-exec.md'), '# 立项单\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `proj-exec` |\n| 状态 | 草稿（设计稿已成） |\n', 'utf8')
    writeFileSync(join(epicsDir, 'ghost.md'), '# 立项单：ghost\n\nno status table here\n', 'utf8')
    writeFileSync(join(epicsDir, 'not-an-epic.txt'), 'skip me\n', 'utf8')
    saveGrantsDecl('p1', { grants: {}, open_ticket_epics: ['proj-exec'] }, 'host', env, clock.now())
    const r = listOpenTicketEpics('p1', env)
    assert(r.ok === true && r.epics.length === 2, `lists all epics (${++n})`)
    const pe = r.epics.find((e) => e.code === 'proj-exec')
    const gh = r.epics.find((e) => e.code === 'ghost')
    assert(pe.status === '草稿（设计稿已成）', `status line as written (${++n})`)
    assert(pe.authorized === true && gh.authorized === false, `authorized flag (${++n})`)
    assert(gh.status === '', `missing status line = empty string (${++n})`)

    const empty = freshDir()
    const r2 = listOpenTicketEpics('p1', { ...env, SANDBAR_EPICS_DIR: empty })
    assert(r2.ok === true && r2.epics.length === 0, `absent dir = empty list, not error (${++n})`)
    cleanup([empty])

    const r3 = listOpenTicketEpics('p1', { ...env, SANDBAR_EPICS_DIR: '' }) // 无锚 → 注册表（假 HOME）→ 显式降级
    if (r3.ok === false) assert(typeof r3.reason === 'string' && r3.reason.length > 0, `degraded carries reason (${++n})`)
    else assert(Array.isArray(r3.epics), `registry fallback answered (${++n})`)
  }

  // ---- C3 fail-soft：epic 解析 ----
  {
    assert(epicFromGrantSource('open_ticket_epics.proj-exec @ /x/executor-grants.json', '') === 'proj-exec', `grant_source shape (${++n})`)
    assert(epicFromGrantSource('', 'refused: epic other-epic is not on the list') === 'other-epic', `reason fallback (${++n})`)
    assert(epicFromGrantSource('', 'open_ticket_epics entry epic ghost has no epic file') === 'ghost', `reason fallback 2 (${++n})`)
    assert(epicFromGrantSource('', 'no epic mentioned here') === '', `english prose not mistaken (${++n})`)
    assert(epicFromGrantSource('', '') === '', `empty inputs (${++n})`)
    assert(epicFromGrantSource('grants.sign @ /x', 'no epic mentioned') === '', `legacy row (${++n})`)
    assert(epicFromGrantSource(null, undefined) === '', `garbage inputs (${++n})`)

    const legacy = JSON.stringify({ v: 1, at: 1, op: 'sign', ticket: 't1', grant: 'sign', grant_source: 'grants.sign @ /f', session: 's', channel: 'cwd', decision: 'allowed', idem: 'i1' })
    const v1 = parseActionLine(legacy)
    assert(v1.kind === 'action' && v1.row.epic === undefined, `legacy row renders without epic (${++n})`)
    const withEpic = JSON.stringify({ v: 1, at: 2, op: 'ticket-start', ticket: 't2', grant: 'open-ticket', grant_source: 'open_ticket_epics.proj-exec @ /f', session: 's', channel: 'cwd', decision: 'allowed', idem: 'i2' })
    const v2 = parseActionLine(withEpic)
    assert(v2.kind === 'action' && v2.row.epic === 'proj-exec', `allowed row carries epic (${++n})`)
    const refused = JSON.stringify({ v: 1, at: 3, op: 'ticket-start', ticket: 't3', grant: '', grant_source: '', session: 's', channel: 'cwd', decision: 'refused', reason: 'refused: epic epic-b is not on the list', idem: 'i3' })
    const v3 = parseActionLine(refused)
    assert(v3.kind === 'action' && v3.row.epic === 'epic-b' && v3.row.reason.includes('epic-b'), `refused row carries epic (${++n})`)
  }
} finally {
  try { cleanup([wd]) } catch { /* tmp cleanup best effort */ }
  try { cleanup([epicsDir]) } catch { /* tmp cleanup best effort */ }
  try { rmSync('/nonexistent-home', { recursive: true, force: true }) } catch { /* never created */ }
}
done(n)
