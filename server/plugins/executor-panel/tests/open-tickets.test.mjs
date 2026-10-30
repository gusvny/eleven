/**
 * open-tickets.test.mjs —— t261004-19「Open tickets in these epics」面板半边 UT。
 *
 * 覆盖：
 *  - 声明镜像校验：open_ticket_epics / open_ticket_cap 接受与畸形具名拒收（含
 *    非数组 / 非串项 / 坏代号 / 超上限 / 坏 cap——外部输入纪律：桩直灌）；
 *  - 保存搬运：epic 清单随保存落盘；下次保存不带=继承不静默抹掉；审计行带 epic；
 *  - 锚（t261030-30 A1/A3）：缺省锚 = <项目根>/docs/epics（none notes/epics
 *    fallback）；新加一份 docs/epics/*.md 就出现在列表；列表代号集 = 引擎
 *    shared.validate_epic_code 放行的代号集（真引擎对真 fixture 比对）；
 *  - 行模型（t261030-30 A2）：行读 front-matter（code/retired/summary）；无
 *    front-matter 的档回落旧字段表格；不可读档带点名原因、status 恒非空
 *    （绝不渲染成健康的空状态行）；
 *  - 授权不静默丢失（t261030-30 A4）：已授权但无档的代号仍成一行（开关在），
 *    往返保存后仍授权；页面在位面不可读时不提交 epic 清单（保留盘上授权）；
 *  - C3 fail-soft：epicFromGrantSource 认 allowed 行的 grant_source 形状、refused
 *    行的 reason 点名；旧行/缺形状/垃圾输入返回 '' 不抛；parseActionLine 对无
 *    grant_source 的旧行照常出 action 行（epic 不设键，行不吞）。
 * 零真实 ~/.sandbar、零 3099。
 */
import { assert, done, freshDir, cleanup, fakeClock } from './lib.mjs'
import { validateDeclaration, saveGrantsDecl, declarationPath, auditPath, readDeclaration } from '../src/host/executor-grants.ts'
import { listOpenTicketEpics, resolveOpenTicketEpicsDir } from '../src/host/open-tickets.ts'
import { epicFromGrantSource, parseActionLine } from '../src/host/recent-actions.ts'
import { grantsSaveBody, epicsToPost } from '../src/host/page-logic.ts'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Ask the real engine (server/engine/shared.py validate_epic_code) which codes it
 * accepts for one directory. Returns null when the engine interpreter is missing — the
 * caller then names the skip; it never fakes a pass.
 */
function engineAccepted(epicsDir, codes, repo) {
  const py = join(repo, 'server/engine/.venv/bin/python')
  if (!existsSync(py)) return null
  const script = [
    'import json, sys, pathlib',
    'sys.path.insert(0, sys.argv[2])',
    'import shared',
    'out = {}',
    'd = pathlib.Path(sys.argv[1])',
    'for c in json.loads(sys.argv[3]):',
    '    try:',
    '        shared.validate_epic_code(c, d)',
    '        out[c] = True',
    '    except ValueError:',
    '        out[c] = False',
    'print(json.dumps(out))',
  ].join('\n')
  const out = execFileSync(py, ['-c', script, epicsDir, join(repo, 'server/engine'), JSON.stringify(codes)], { encoding: 'utf8' })
  return JSON.parse(out)
}

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

  // ---- 行模型（t261030-30 A2）：front-matter 优先，旧字段表格只做回落 ----
  const fmDoc = (code, opts = {}) => {
    const retired = opts.retired ?? 'false'
    const summary = opts.summary ?? `Summary of ${code}.`
    return `---\ncode: ${code}\nretired: ${retired}\nsummary: ${summary}\nstarted: 2026-10-30\n---\n\n# ${code}\n\nbody\n`
  }
  const LEGACY_DOC = '# 立项单\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `old-epic` |\n| 状态 | 草稿（设计稿已成） |\n'
  {
    mkdirSync(join(epicsDir, 'x'), { recursive: true }) // a directory entry is not a row
    writeFileSync(join(epicsDir, 'proj-exec.md'), fmDoc('proj-exec', { summary: 'Do the thing.' }), 'utf8')
    writeFileSync(join(epicsDir, 'retired-epic.md'), fmDoc('retired-epic', { retired: 'true' }), 'utf8')
    writeFileSync(join(epicsDir, 'old-epic.md'), LEGACY_DOC, 'utf8')
    writeFileSync(join(epicsDir, 'no-record.md'), '# nothing here\n', 'utf8')
    writeFileSync(join(epicsDir, 'bad-retired.md'), '---\ncode: bad-retired\nretired: yes\n---\n', 'utf8')
    writeFileSync(join(epicsDir, 'Bad_Code.md'), fmDoc('Bad_Code'), 'utf8') // illegal shape: the engine refuses it
    writeFileSync(join(epicsDir, 'not-an-epic.txt'), 'skip me\n', 'utf8')
    saveGrantsDecl('p1', { grants: {}, open_ticket_epics: ['proj-exec'] }, 'host', env, clock.now())
    const r = listOpenTicketEpics('p1', env)
    assert(r.ok === true, `A2 list answers ok (${++n})`)
    const codes = r.epics.map((e) => e.code)
    assert(JSON.stringify(codes) === JSON.stringify(['bad-retired', 'no-record', 'old-epic', 'proj-exec', 'retired-epic']),
      `A2 only legal code shapes are rows, sorted: ${codes.join(',')} (${++n})`)
    const by = Object.fromEntries(r.epics.map((e) => [e.code, e]))
    assert(by['proj-exec'].status === 'open' && by['proj-exec'].retired === false
      && by['proj-exec'].summary === 'Do the thing.' && by['proj-exec'].reason === ''
      && by['proj-exec'].in_registry === true, `A2 front-matter row (status/retired/summary) (${++n})`)
    assert(by['retired-epic'].status === 'retired' && by['retired-epic'].retired === true,
      `A2 retired: true reads as retired (${++n})`)
    assert(by['old-epic'].status === '草稿（设计稿已成）' && by['old-epic'].reason.includes('no front-matter block')
      && by['old-epic'].retired === true,
      `A2 legacy table is the fallback for a document without front-matter, and the row fails closed (${++n})`)
    assert(by['no-record'].status === 'unknown' && by['no-record'].reason !== '' && by['no-record'].retired === true,
      `A2 a document with no readable record degrades with a named reason (${++n})`)
    assert(by['bad-retired'].reason.includes("'retired'") && by['bad-retired'].retired === true,
      `A2 a malformed retired value names the failed field and fails closed (${++n})`)
    assert(r.epics.every((e) => typeof e.status === 'string' && e.status !== ''),
      `A2 no row carries a blank status (${++n})`)
    assert(by['proj-exec'].authorized === true && by['retired-epic'].authorized === false, `A2 authorized flag (${++n})`)

    const empty = freshDir()
    const r2 = listOpenTicketEpics('p1', { ...env, SANDBAR_EPICS_DIR: empty })
    assert(r2.ok === true && r2.epics.every((e) => e.in_registry === false),
      `absent dir = no registry rows, not an error (${++n})`)
    assert(r2.epics.length === 1 && r2.epics[0].code === 'proj-exec' && r2.epics[0].authorized === true,
      `absent dir keeps the already-authorized code as a row (${++n})`)
    cleanup([empty])

    const r3 = listOpenTicketEpics('p1', { ...env, SANDBAR_EPICS_DIR: '', SANDBAR_PROJECTS_DIR: freshDir() })
    assert(r3.ok === false && typeof r3.reason === 'string' && r3.reason !== '',
      `an unresolvable anchor degrades with a named reason (${++n})`)
  }

  // ---- 锚（t261030-30 A1/A3）：缺省 = <项目根>/docs/epics，新档自动上台面 ----
  const repo = join(dirname(fileURLToPath(import.meta.url)), '../../../..')
  const docProject = freshDir('t30-docproj-')
  const docRegistry = freshDir('t30-registry-')
  const docRoot = join(docProject, 'primary')
  const envDocs = { HOME: '/nonexistent-home', SANDBAR_PROJECTS_DIR: docRegistry, SANDBAR_WATCHDOG_DIR: docProject, SANDBAR_PANEL_DIR: docProject }
  {
    // A per-key registry entry (schema v1 + the migration marker, which the loader
    // demands before it trusts a populated root).
    mkdirSync(join(docRegistry, 'docproj'), { recursive: true })
    writeFileSync(join(docRegistry, 'docproj', 'project.yaml'),
      `schema: v1\nproject:\n  - key: docproj\n    name: docproj\n    dirs:\n      - ${docRoot}\n`, 'utf8')
    writeFileSync(join(docRegistry, '.migrated'), 'source: test-fixture\n', 'utf8')
    mkdirSync(join(docRoot, 'docs', 'epics'), { recursive: true })
    mkdirSync(join(docRoot, 'notes', 'epics'), { recursive: true })
    writeFileSync(join(docRoot, 'docs', 'epics', 'artifact-face.md'), fmDoc('artifact-face'), 'utf8')
    writeFileSync(join(docRoot, 'docs', 'epics', 'retired-epic.md'), fmDoc('retired-epic', { retired: 'true' }), 'utf8')
    // A document in the retired notes/epics store must never reach the panel.
    writeFileSync(join(docRoot, 'notes', 'epics', 'notes-only.md'), fmDoc('notes-only'), 'utf8')

    const savedEnvDir = process.env.SANDBAR_EPICS_DIR
    const savedProjectsYaml = process.env.SANDBAR_PROJECTS_YAML
    const savedProjectsDir = process.env.SANDBAR_PROJECTS_DIR
    // The project registry loader reads process.env (the face injects only the epic and
    // grants keys), so the fixture registry must ride the process env here as well.
    delete process.env.SANDBAR_EPICS_DIR
    delete process.env.SANDBAR_PROJECTS_YAML
    process.env.SANDBAR_PROJECTS_DIR = docRegistry
    try {
      // A3: the default anchor is the project root's docs/epics.
      const anchor = resolveOpenTicketEpicsDir('docproj', envDocs)
      assert(anchor.ok === true && anchor.dir === join(docRoot, 'docs', 'epics'),
        `A3 default anchor = <project root>/docs/epics (${++n})`)
      const r = listOpenTicketEpics('docproj', envDocs)
      assert(r.ok === true, `A3 the doc registry answers (${++n})`)
      const before = r.epics.map((e) => e.code)
      assert(JSON.stringify(before) === JSON.stringify(['artifact-face', 'retired-epic']),
        `A3 rows come from docs/epics only: ${before.join(',')} (${++n})`)
      assert(!before.includes('notes-only'), `A1 no notes/epics fallback in the console path (${++n})`)

      // A3 guard: a new document appears with no code change.
      writeFileSync(join(docRoot, 'docs', 'epics', 'fresh-epic.md'), fmDoc('fresh-epic'), 'utf8')
      const after = listOpenTicketEpics('docproj', envDocs)
      assert(after.ok === true && after.epics.some((e) => e.code === 'fresh-epic'),
        `A3 a new docs/epics/*.md shows up in the panel epic list with no code change (${++n})`)

      // A3 parity: the listed codes the panel treats as open == the codes the engine
      // accepts (real engine, real fixture). A missing interpreter is a named skip,
      // never a silent pass.
      const allCodes = ['artifact-face', 'retired-epic', 'fresh-epic']
      const openCodes = after.epics.filter((e) => e.retired === false).map((e) => e.code)
      const engineVerdict = engineAccepted(join(docRoot, 'docs', 'epics'), allCodes, repo)
      if (engineVerdict === null) {
        console.log('  skip engine parity — the engine interpreter is missing (server/engine/.venv/bin/python)')
      } else {
        const accepted = allCodes.filter((c) => engineVerdict[c] === true)
        assert(JSON.stringify(openCodes) === JSON.stringify(accepted),
          `A3 listed open codes == the codes the engine accepts [${openCodes.join(',')}] vs [${accepted.join(',')}] (${++n})`)
      }

      // A4: an authorized code without a document keeps its switch and survives a save.
      saveGrantsDecl('docproj', { grants: {}, open_ticket_epics: ['artifact-face', 'ghost-epic'] }, 'host', envDocs, clock.now())
      const withGhost = listOpenTicketEpics('docproj', envDocs)
      const ghost = withGhost.epics.find((e) => e.code === 'ghost-epic')
      assert(ghost !== undefined && ghost.authorized === true && ghost.in_registry === false
        && ghost.status !== '' && ghost.reason.includes('ghost-epic.md'),
        `A4 an authorized code with no document is still a row with a named reason (${++n})`)
      const posted = withGhost.epics.filter((e) => e.authorized === true).map((e) => e.code)
      assert(JSON.stringify(posted) === JSON.stringify(['artifact-face', 'ghost-epic']),
        `A4 the rendered switches post every authorized code (${++n})`)
      saveGrantsDecl('docproj', { grants: {}, open_ticket_epics: posted }, 'host', envDocs, clock.now())
      const back = readDeclaration('docproj', envDocs)
      assert(back.ok === true
        && JSON.stringify(back.declaration.open_ticket_epics) === JSON.stringify(['artifact-face', 'ghost-epic']),
        `A4 round trip keeps an authorized epic that has no document (${++n})`)
      // A save with no epic key inherits the on-disk list (the degraded-read path).
      saveGrantsDecl('docproj', { grants: { sign: true } }, 'host', envDocs, clock.now())
      const inherited = readDeclaration('docproj', envDocs)
      assert(inherited.ok === true
        && JSON.stringify(inherited.declaration.open_ticket_epics) === JSON.stringify(['artifact-face', 'ghost-epic']),
        `A4 a save that omits the epic list keeps the authorization (${++n})`)
      // The page wiring: it renders one switch per row, and its save body is the
      // tested builder (asserted below by source parity) — never a hand-rolled body.
      const pageSrc = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/panel-page.ts'), 'utf8')
      assert(pageSrc.includes("data-epic=\"'+esc(e.code)+'\"") && pageSrc.includes('epicRowLine(e)'),
        `A4 the page renders a switch and a non-blank status line per row (${++n})`)
    } finally {
      if (savedEnvDir !== undefined) process.env.SANDBAR_EPICS_DIR = savedEnvDir
      if (savedProjectsYaml === undefined) delete process.env.SANDBAR_PROJECTS_YAML
      else process.env.SANDBAR_PROJECTS_YAML = savedProjectsYaml
      if (savedProjectsDir === undefined) delete process.env.SANDBAR_PROJECTS_DIR
      else process.env.SANDBAR_PROJECTS_DIR = savedProjectsDir
      cleanup([docProject, docRegistry])
    }
  }

  // ---- t261030-41: the audited save payload is the WHOLE declaration ----
  // The regression this guards: the save posted only the permission switches, so the
  // epic list that authorizes the open-ticket row silently dropped out of the payload
  // and the writer had to guess whether the list was cleared or merely not sent.
  // Asserting "a save happened" cannot see that, so the assertions below pin the
  // PAYLOAD: it carries the epic list AND the surviving grants, and the epic key is
  // present even when the list is empty (present-empty = cleared on purpose; absent =
  // the field was dropped).
  {
    const payload = grantsSaveBody({
      grants: { 'open-ticket': true, sign: true },
      session: ' exec-1 ',
      epics: ['engine-hardening', 'localization'],
    })
    assert(Object.hasOwn(payload, 'open_ticket_epics'),
      `the save payload carries the open_ticket_epics key (${++n})`)
    assert(Array.isArray(payload.open_ticket_epics)
      && payload.open_ticket_epics.join(',') === 'engine-hardening,localization',
      `the save payload carries the whole epic list the switches selected: ${JSON.stringify(payload.open_ticket_epics)} (${++n})`)
    assert(payload.grants['open-ticket'] === true && payload.grants.sign === true,
      `the save payload keeps the existing grants: ${JSON.stringify(payload.grants)} (${++n})`)
    assert(JSON.stringify(payload.executor_sessions) === JSON.stringify(['exec-1']),
      `the save payload carries the trimmed session (${++n})`)

    const empty = grantsSaveBody({ grants: {}, epics: [] })
    assert(Object.hasOwn(empty, 'open_ticket_epics') && empty.open_ticket_epics.length === 0
      && Object.keys(empty.grants).length === 0 && !('executor_sessions' in empty),
      `an empty save still carries the epic key and no session key (${++n})`)
    // Only ON switches travel: an off switch is an absent op, never an explicit false.
    const off = grantsSaveBody({ grants: { sign: true, 'open-ticket': false }, epics: ['proj-exec'] })
    assert(JSON.stringify(off.grants) === JSON.stringify({ sign: true }),
      `only on-switches travel: ${JSON.stringify(off.grants)} (${++n})`)
    // Malformed input never throws and never drops the key (external-input discipline).
    for (const bad of [undefined, null, {}, { grants: null, epics: 'nope' }, { grants: {}, session: 5, epics: [1, null] }]) {
      const b = grantsSaveBody(bad)
      assert(Object.hasOwn(b, 'open_ticket_epics') && Array.isArray(b.open_ticket_epics)
        && b.grants !== null && typeof b.grants === 'object' && !('executor_sessions' in b),
        `malformed input still yields a whole payload: ${JSON.stringify(bad)} (${++n})`)
    }

    // The epic list the save carries: a readable face posts the switches; a read that
    // failed posts the list already on disk instead of an empty one that erases it.
    assert(JSON.stringify(epicsToPost(['engine-hardening', 'localization'], true, ['proj-exec']))
      === JSON.stringify(['engine-hardening', 'localization']),
      `readable face: the switches are what the save posts (${++n})`)
    assert(JSON.stringify(epicsToPost([], false, ['artifact-face', 'ghost-epic']))
      === JSON.stringify(['artifact-face', 'ghost-epic']),
      `failed read: the on-disk list is posted, never [] (${++n})`)
    assert(JSON.stringify(epicsToPost(null, false, ['proj-exec', 'proj-exec', 7, '']))
      === JSON.stringify(['proj-exec']),
      `failed read: a malformed declaration degrades to its readable codes (${++n})`)
    assert(JSON.stringify(epicsToPost(undefined, false, null)) === JSON.stringify([]),
      `failed read with no declaration posts an empty list, never a throw (${++n})`)

    // End to end over the two halves: the payload the page would post for the
    // scenario's face (both epics on) lands on disk with the grants intact.
    const roundTrip = grantsSaveBody({
      grants: { sign: true, 'open-ticket': true },
      epics: epicsToPost(['engine-hardening', 'localization'], true, []),
    })
    const saved = saveGrantsDecl('t261030-41-payload', roundTrip, 'host', env, clock.now())
    const onDisk = saved.saved === true ? JSON.parse(readFileSync(declarationPath('t261030-41-payload', env), 'utf8')) : null
    assert(saved.saved === true
      && JSON.stringify(onDisk.open_ticket_epics) === JSON.stringify(['engine-hardening', 'localization'])
      && onDisk.grants.sign === true && onDisk.grants['open-ticket'] === true,
      `the posted payload reaches the declaration file with the epic list and the grants (${++n})`)

    // The served page runs the SAME source these assertions drive (String(fn) embed),
    // so this test cannot stay green while the page posts something else.
    assert(PANEL_PAGE_HTML.includes(String(grantsSaveBody)),
      `the served page embeds the tested save-body builder (${++n})`)
    assert(PANEL_PAGE_HTML.includes(String(epicsToPost)),
      `the served page embeds the tested epic-list source (${++n})`)
    const pageSrc = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/panel-page.ts'), 'utf8')
    assert(/var built = grantsSaveBody\(\{/.test(pageSrc) && pageSrc.includes('epics: openEpicsToPost()'),
      `the panel save builds its body with the builder and the epic source (${++n})`)
    assert(/\{ grants: built\.grants, executor_sessions: built\.executor_sessions, open_ticket_epics: built\.open_ticket_epics \}/.test(pageSrc),
      `the posted body names the whole declaration, epic list included (${++n})`)
    assert(!/body\.open_ticket_epics\s*=/.test(pageSrc),
      `the panel never sets the epic key outside the builder (the shape that lost it) (${++n})`)
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
