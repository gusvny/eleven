/**
 * sc_t261026_05_session_home_two_roots.mjs — the Rule 5 two-declared-roots
 * read face (t261026-05, host report 261026 item 3; design
 * docs/design/metrics-token-face-delta.md Rule 5, host ruling option (u)).
 *
 * User-facing rule under test: the project-sessions and tokens-by-role faces
 * answer "no project-level sessions" today because they search ONLY
 * <repo>/.dsh/sessions, while the real work lives in the DSH session home
 * (<home>/.dsh/sessions/<project slug>/ — 91 files for this project, 62 in
 * the window). The host ruled the read face MAY read the DSH home, read-only:
 * exactly two declared roots, refusal vocabulary unchanged, bounded to the
 * project's own slug with the existing file cap, and BOTH roots named on the
 * face so "nothing ran" stays distinguishable from "we looked in the wrong
 * place".
 *
 * Grey-box L3 over the REAL buildMetricsResponse (the composed face a user's
 * tab reads) with a fixture DSH home built under an overridden $HOME (the
 * declared home root is derived from the repo path exactly as the face's own
 * home-candidate line munges it). Offline seconds, zero docker/Temporal-
 * server/browser, never touches 3099/7233, never touches the real ~/.dsh.
 *
 * Legs:
 *  A  home-only sessions ARE counted: project_sessions non-null, both roots
 *     named on the face (the singular searched line stays for old readers);
 *  B  both roots contribute to one total (repo file + home file summed);
 *  C  slug bound: another project's slug dir under the same home is never
 *     read (a big decoy there changes nothing);
 *  D  read-only, proven: the file set + mtimes under BOTH roots are
 *     byte-identical before and after the read;
 *  E  refusal discipline: a symlink inside the slug dir escaping to another
 *     project's home slug dir is refused by name, never read, never thrown;
 *  F  one newest session file per session directory (an older file's tokens
 *     never double-count beside the newest);
 *  G  an unreadable slug dir degrades with a named reason, never throws;
 *  H  the per-role face grows: t<id>-developer sessions in the home land in
 *     role_aggregate (the measured "developer 1 ticket" defect retired).
 *
 * Pre-implement tree red = the named TDD signal; green required at the
 * integration gate/merge. zstd missing = ENV_FAIL exit 2.
 */
import { mkdirSync, writeFileSync, rmSync, readdirSync, statSync, symlinkSync, chmodSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'
import {
  freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents,
  ok as libOk, summary,
} from '../../server/plugins/workbench/tests/lib.mjs'

const __isMain = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(process.argv[1]).href

function ok(cond, label, detail = '') { libOk(label, cond, detail) }
function section(t) { console.log(`\n== ${t}`) }

const TMP_DIRS = []
function keep(d) { TMP_DIRS.push(d); return d }
process.on('exit', () => { for (const d of TMP_DIRS) { try { rmSync(d, { recursive: true, force: true }) } catch { /* best effort */ } } })

function putSessionAs(sessDir, fileName, events) {
  mkdirSync(sessDir, { recursive: true })
  const raw = join(sessDir, 'raw-' + fileName)
  writeFileSync(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n')
  execFileSync('zstd', ['-f', '-q', raw, '-o', join(sessDir, fileName)])
  rmSync(raw)
}

function putSession(sessDir, events) { putSessionAs(sessDir, 'session.jsonl.zstd', events) }

/** The declared slug munging (the face's own home-candidate rule). */
function homeSlug(repoPath) {
  return '--' + repoPath.split('/').filter(Boolean).join('-') + '--'
}

function snapshot(dir) {
  const out = {}
  function walk(d) {
    let entries = []
    try { entries = readdirSync(d, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const p = join(d, e.name)
      if (e.isDirectory()) walk(p)
      else if (e.isFile()) { try { out[p] = statSync(p).mtimeMs } catch { /* skip */ } }
    }
  }
  walk(dir)
  return out
}

function sameSnap(a, b) {
  const ka = Object.keys(a); const kb = Object.keys(b)
  if (ka.length !== kb.length) return false
  return ka.every((k) => b[k] === a[k])
}

function ticketRow(id, closedAt) {
  return {
    id, project: 'demo', epic: 'metrics', title: id, workflow: 'dev-lane',
    stage: 'implement', stage_state: 'closed', status: 'closed', role: 'developer',
    created: new Date(closedAt - 86400e3).toISOString(), updated: new Date(closedAt).toISOString(),
    updated_ts: Math.round(closedAt / 1000), worktree: `.worktrees/${id}`,
  }
}

async function runTokenView(stubPath, repo, home, projectsRoot, withRole = true) {
  const old = {}
  const keys = ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR',
    'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR', 'HOME', 'SANDBAR_DSH_HOME']
  for (const k of keys) { old[k] = process.env[k]; delete process.env[k] }
  process.env.SANDBAR_METRICS_STUB = stubPath
  process.env.SANDBAR_METRICS_DIR = projectsRoot
  process.env.SANDBAR_PROJECTS_DIR = projectsRoot
  if (home !== null) { process.env.HOME = home; process.env.SANDBAR_DSH_HOME = home }
  try {
    const m = await loadMetrics()
    const deps = m.defaultDeps(repo, () => NOW)
    const params = { view: 'token', window: '30d', epic: 'all', template: 'dev-lane', mode: 'full' }
    return await m.buildMetricsResponse(params, deps)
  } finally {
    for (const k of keys) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

/** usage events with a distinctive total so fixtures are tellable apart. */
function events(totalIn) {
  return [
    { type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 },
    { type: 'assistant/message', data: { usage: { inputTokens: totalIn, outputTokens: 10, cacheReadTokens: 5 } }, time: 2 },
  ]
}

async function runAll() {
  section('0. environment gates')
  let hasZstd = true
  try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }) } catch { hasZstd = false }
  if (!hasZstd) {
    console.log('ENV_FAIL: zstd CLI missing — session fixtures cannot be built; honest red, not a silent skip')
    process.exit(2)
  }
  ok(hasZstd, 'zstd present, fixtures buildable')

  const CLOSED = Date.parse('2026-08-30T06:00:00Z')
  const ID = 't261026-05'

  // ---- A. home-only sessions ARE counted and both roots are named ----
  section('A. home-only sessions counted; both roots named on the face')
  const repoA = keep(freshDir('t05r-repo-'))       // NO repo-local sessions at all
  const homeA = keep(freshDir('t05r-home-'))
  const projectsA = keep(freshDir('t05r-projects-'))
  const slugA = homeSlug(repoA)
  putSession(join(homeA, '.dsh', 'sessions', slugA, 'projA'), events(5000))
  const stubA = writeStub(keep(freshDir('t05r-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  const bodyA = ((await runTokenView(stubA, repoA, homeA, projectsA)).body) ?? {}
  const ps = bodyA?.project_sessions ?? null
  ok(ps !== null && ps !== undefined,
    'A1 home-only sessions count: project_sessions is NOT null (the empty-room defect retired)',
    JSON.stringify(bodyA?.project_sessions_degrade ?? bodyA?.project_sessions)?.slice(0, 220))
  const psText = JSON.stringify(bodyA?.project_sessions ?? '') + JSON.stringify(bodyA?.project_sessions_degrade ?? '')
  ok(psText.includes(join(repoA, '.dsh', 'sessions')) && psText.includes(join(homeA, '.dsh', 'sessions', slugA)),
    'A2 the face names BOTH searched roots (the reader can tell where it looked)',
    psText.slice(0, 300))
  ok(psText.includes(join(repoA, '.dsh', 'sessions')),
    'A3 the singular searched line survives for old readers', '')
  if (ps && typeof ps === 'object') {
    const total = JSON.stringify(ps)
    ok(total.includes('5000'),
      'A4 the home session tokens land in the block (5000 in from the fixture)', total.slice(0, 220))
  }

  // ---- B. both roots contribute to one total ----
  section('B. repo root and home root summed')
  const repoB = keep(freshDir('t05b-repo-'))
  const homeB = keep(freshDir('t05b-home-'))
  const projectsB = keep(freshDir('t05b-projects-'))
  putSession(join(repoB, '.dsh', 'sessions', 'projB'), events(111))
  putSession(join(homeB, '.dsh', 'sessions', homeSlug(repoB), 'projB2'), events(222))
  const stubB = writeStub(keep(freshDir('t05b-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  const bodyB = ((await runTokenView(stubB, repoB, homeB, projectsB)).body) ?? {}
  const psTextB = JSON.stringify(bodyB?.project_sessions ?? '')
  ok(psTextB.includes('111') && psTextB.includes('222'),
    'B1 both roots contribute to the same block (333 in, not max-of-roots)', psTextB.slice(0, 260))

  // ---- C. slug bound: another project's home slug dir is never read ----
  section('C. slug bound inside the home')
  const repoC = keep(freshDir('t05c-repo-'))
  const homeC = keep(freshDir('t05c-home-'))
  const projectsC = keep(freshDir('t05c-projects-'))
  putSession(join(homeC, '.dsh', 'sessions', homeSlug(repoC), 'mine'), events(300))
  putSession(join(homeC, '.dsh', 'sessions', homeSlug('/some/other/project'), 'decoy'), events(999999))
  const stubC = writeStub(keep(freshDir('t05c-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  const bodyC = ((await runTokenView(stubC, repoC, homeC, projectsC)).body) ?? {}
  const psTextC = JSON.stringify(bodyC?.project_sessions ?? '')
  ok(psTextC.includes('300') && !psTextC.includes('999999'),
    'C1 the neighbour project slug under the same home is never read', psTextC.slice(0, 260))

  // ---- D. read-only, proven from the filesystem ----
  section('D. read-only: both roots untouched by the read')
  const repoD = keep(freshDir('t05d-repo-'))
  const homeD = keep(freshDir('t05d-home-'))
  const projectsD = keep(freshDir('t05d-projects-'))
  mkdirSync(join(repoD, '.dsh', 'sessions', 'rsl'), { recursive: true })
  putSession(join(repoD, '.dsh', 'sessions', 'rsl', 's1'), events(50))
  putSession(join(homeD, '.dsh', 'sessions', homeSlug(repoD), 'hsl'), events(60))
  const before = { repo: snapshot(join(repoD, '.dsh', 'sessions')), home: snapshot(join(homeD, '.dsh', 'sessions')) }
  const stubD = writeStub(keep(freshDir('t05d-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  await runTokenView(stubD, repoD, homeD, projectsD)
  const after = { repo: snapshot(join(repoD, '.dsh', 'sessions')), home: snapshot(join(homeD, '.dsh', 'sessions')) }
  ok(sameSnap(before.repo, after.repo) && sameSnap(before.home, after.home),
    'D1 the read created, moved or touched NOTHING under either root (reader-side mtime+set proof)',
    JSON.stringify({ before, after }).slice(0, 300))

  // ---- E. symlink escape refused by name ----
  section('E. refusal discipline inside the home root')
  const repoE = keep(freshDir('t05e-repo-'))
  const homeE = keep(freshDir('t05e-home-'))
  const projectsE = keep(freshDir('t05e-projects-'))
  const outside = keep(freshDir('t05e-outside-'))
  putSession(join(outside, 'escaped', 'sessdir'), events(888888))
  putSession(join(homeE, '.dsh', 'sessions', homeSlug(repoE), 'honest'), events(70))
  try {
    symlinkSync(join(outside, 'escaped'), join(homeE, '.dsh', 'sessions', homeSlug(repoE), 'link'))
  } catch { /* some filesystems refuse symlinks; the leg then has nothing to bite */ }
  const stubE = writeStub(keep(freshDir('t05e-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  let bodyE = null
  try {
    bodyE = ((await runTokenView(stubE, repoE, homeE, projectsE)).body) ?? {}
  } catch (err) {
    bodyE = null
    ok(false, 'E0 the read never throws on a symlink escape', String(err?.message ?? err))
  }
  if (bodyE !== null) {
    const allTextE = JSON.stringify(bodyE)
    ok(!allTextE.includes('888888'),
      'E1 the symlink-escaped content is never aggregated', '')
    ok(/refus|outside|escape|symlink/i.test(allTextE),
      'E2 the escape carries a named refusal (vocabulary present on the face)', allTextE.slice(0, 300))
    ok(JSON.stringify(bodyE?.project_sessions ?? '').includes('70'),
      'E3 the honest sibling session still counts next to the refused one', '')
  }

  // ---- F. one newest session file per session directory ----
  section('F. newest-file-per-dir bound')
  const repoF = keep(freshDir('t05f-repo-'))
  const homeF = keep(freshDir('t05f-home-'))
  const projectsF = keep(freshDir('t05f-projects-'))
  const dirF = join(homeF, '.dsh', 'sessions', homeSlug(repoF), 'projmulti')
  putSessionAs(dirF, 'older-session.jsonl.zstd', events(1000))   // stale sibling
  // bump the newest file's mtime clearly above the stale one
  const newer = join(dirF, 'newer-session.jsonl.zstd')
  putSessionAs(dirF, 'newer-session.jsonl.zstd', events(4000))
  const stOld = statSync(join(dirF, 'older-session.jsonl.zstd'))
  const stNew = statSync(newer)
  if (stNew.mtimeMs <= stOld.mtimeMs) {
    const { utimesSync } = await import('node:fs')
    // mtime is in MILLISECONDS — the earlier seconds-based arithmetic set the
    // "newer" fixture to 1970 and flipped the newest-file leg into a false red.
    utimesSync(newer, stNew.atime, new Date(stOld.mtimeMs + 10_000))
  }
  const stubF = writeStub(keep(freshDir('t05f-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  const bodyF = ((await runTokenView(stubF, repoF, homeF, projectsF)).body) ?? {}
  const psTextF = JSON.stringify(bodyF?.project_sessions ?? '')
  ok(psTextF.includes('4000') && !psTextF.includes('1000'),
    'F1 only the newest session file per directory counts (no double-count of the stale sibling)',
    psTextF.slice(0, 260))

  // ---- G. unreadable slug dir degrades named, never throws ----
  section('G. unreadable slug dir degrades named')
  if (typeof process.getuid === 'function' && process.getuid() === 0) {
    console.log('  N/A G1 unreadable-dir refusal needs a non-root process (root reads through 000 modes)')
  } else {
    const repoG = keep(freshDir('t05g-repo-'))
    const homeG = keep(freshDir('t05g-home-'))
    const projectsG = keep(freshDir('t05g-projects-'))
    const locked = join(homeG, '.dsh', 'sessions', homeSlug(repoG), 'locked')
    putSession(locked, events(90))
    chmodSync(locked, 0o000)
    const stubG = writeStub(keep(freshDir('t05g-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
    let bodyG = null
    try { bodyG = ((await runTokenView(stubG, repoG, homeG, projectsG)).body) ?? {} } catch (err) {
      ok(false, 'G1 an unreadable slug dir never throws the read', String(err?.message ?? err))
    }
    chmodSync(locked, 0o755)
    if (bodyG !== null) {
      ok(/reason|unread|denied/i.test(JSON.stringify(bodyG)),
        'G2 the unreadable dir degrades with a named reason on the face', JSON.stringify(bodyG).slice(0, 240))
    }
  }

  // ---- H. the per-role face grows from the home root ----
  section('H. role_aggregate reads the home root')
  const repoH = keep(freshDir('t05h-repo-'))
  const homeH = keep(freshDir('t05h-home-'))
  const projectsH = keep(freshDir('t05h-projects-'))
  putSession(join(homeH, '.dsh', 'sessions', homeSlug(repoH), `${ID}-developer`), events(700))
  putSession(join(homeH, '.dsh', 'sessions', homeSlug(repoH), `${ID}-reviewer`), events(800))
  const stubH = writeStub(keep(freshDir('t05h-stub-')), baseStub({ tickets: [ticketRow(ID, CLOSED)] }))
  const bodyH = ((await runTokenView(stubH, repoH, homeH, projectsH)).body) ?? {}
  const roles = bodyH?.role_aggregate?.roles ?? {}
  const raText = JSON.stringify(bodyH?.role_aggregate ?? {})
  ok(Object.keys(roles).length > 0 && raText.includes('700'),
    'H1 developer sessions in the HOME root land in role_aggregate (the 1-ticket defect retired)',
    raText.slice(0, 300))
  ok(!/no sessions in window/i.test(raText),
    'H2 a home with sessions never answers "no sessions in window"', raText.slice(0, 200))
  const rootsH = raText
  ok(rootsH.includes(join(repoH, '.dsh', 'sessions')) && rootsH.includes(join(homeH, '.dsh', 'sessions', homeSlug(repoH))),
    'H3 the role face also names both searched roots', '')

  const green = summary('sc_t261026_05_session_home_two_roots')
  process.exit(green ? 0 : 1)
}

if (__isMain) {
  await runAll()
} else {
  console.log('sc_t261026_05_session_home_two_roots: imported as a module; battery skipped')
}
