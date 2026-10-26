/**
 * tests/t261026-05-declared-roots.mjs — Rule 5 (metrics-token-face-delta.md,
 * host ruling 261025 option u): the project-sessions and per-role readers walk
 * TWO declared roots — the repo `.dsh/sessions` and the DSH session home for
 * the project — read-only, slug-bounded, refusal vocabulary verbatim.
 *
 * Direct run: node server/plugins/workbench/tests/t261026-05-declared-roots.mjs
 * (node ≥22.18 native type-stripping). Fully hermetic: SANDBAR_DSH_HOME points
 * the home helper at a temp dir, so the real ~/.dsh is never touched.
 */
import { mkdirSync, writeFileSync, rmSync, readdirSync, symlinkSync, existsSync, chmodSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { freshDir, ok as libOk, dumpFails } from './lib.mjs'

const __isMain = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(process.argv[1]).href
function ok(cond, label, detail = '') { libOk(label, cond, detail) }

const { resolveProjectSessionFiles, resolveTicketRoleSessionFiles, dshSessionHomeRoot } = await import(
  new URL('./../src/host/agent-usage.ts', import.meta.url).pathname)

const SESSION_FILE = 'session.jsonl.zstd' // name-level discovery only; content never parsed here

function makeSessionDir(base, ...segs) {
  const dir = join(base, ...segs)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, SESSION_FILE), '{}\n') // junk content: the resolver reads names only
  return dir
}

function slugOf(repo) {
  return '--' + repo.split('/').filter(Boolean).join('-') + '--'
}

async function runAll() {
  const oldHome = process.env.SANDBAR_DSH_HOME
  const home = freshDir('dsh-home-')
  process.env.SANDBAR_DSH_HOME = home
  try {
    const repo = freshDir('roots-repo-')
    const slug = slugOf(repo)
    const repoSess = join(repo, '.dsh', 'sessions')
    const homeSess = join(home, '.dsh', 'sessions', slug)

    ok(dshSessionHomeRoot('/a/b') === join(home, '.dsh', 'sessions', '--a-b--'),
      'home helper munges the repo path the dsh way', dshSessionHomeRoot('/a/b'))

    // A. repo-local only
    makeSessionDir(repoSess, 'executor', 'global')
    let ref = await resolveProjectSessionFiles(repo, [])
    ok(ref.paths.length === 1 && ref.buckets.executor?.length === 1, 'A: repo-local project session found', JSON.stringify(ref))
    ok(Array.isArray(ref.searchedRoots) && ref.searchedRoots.length === 2 && ref.searchedRoots[0] === repoSess && ref.searchedRoots[1] === homeSess,
      'A: both declared roots named, repo first', JSON.stringify(ref.searchedRoots))

    // B. home only — the real home layout: session dirs sit DIRECTLY under the
    // project slug dir (one level; gen1 arbitration), no slug level below it.
    rmSync(repoSess, { recursive: true, force: true })
    makeSessionDir(homeSess, 'cron-1')
    ref = await resolveProjectSessionFiles(repo, [])
    ok(ref.paths.length === 1 && ref.buckets['cron-1']?.length === 1, 'B: DSH-home project session found at the one-level layout (the (u) widening)', JSON.stringify(ref))
    ok(ref.paths[0].startsWith(homeSess), 'B: the path lives under the home slug dir', ref.paths[0])

    // C. both roots at once
    makeSessionDir(repoSess, 'executor', 'global')
    ref = await resolveProjectSessionFiles(repo, [])
    ok(ref.paths.length === 2, 'C: both roots walked, paths unioned', JSON.stringify(ref.paths))

    // D. ticket-shaped dirs stay out of project sessions (both roots)
    makeSessionDir(repoSess, 'executor', 't261026-01-developer')
    makeSessionDir(homeSess, 't261026-02-integration')
    const refD = await resolveProjectSessionFiles(repo, [])
    ok(refD.paths.length === 2 && !JSON.stringify(refD.buckets).includes('t261026'),
      'D: ticket-shaped session dirs excluded from project sessions', JSON.stringify(refD.buckets))

    // E. symlink INSIDE the slug dir pointing at ANOTHER project's slug dir under
    //    the same home: refused BY NAME, path-scoped — the escaped content is
    //    never read while an honest sibling keeps counting (gen1 gate, E3).
    const sneakyDir = makeSessionDir(join(home, '.dsh', 'sessions'), '--other-proj--', 'sneaky-session')
    writeFileSync(join(sneakyDir, SESSION_FILE), '{"x":1}\n')
    symlinkSync(sneakyDir, join(homeSess, 'evil'), 'dir')
    const refE = await resolveProjectSessionFiles(repo, [])
    ok(refE.refused !== true && /session path outside the workspace root \(refused to read\)/.test(refE.reason ?? ''),
      'E: cross-project home symlink refused with the verbatim refusal, path-scoped', refE.reason ?? '')
    ok(!JSON.stringify(refE.buckets).includes('sneaky'), 'E: the escaped content is never aggregated', JSON.stringify(refE.buckets))
    ok(Object.keys(refE.buckets).length >= 1, 'E: the honest sibling keeps counting next to the refusal', JSON.stringify(Object.keys(refE.buckets)))
    rmSync(join(homeSess, 'evil'), { force: true })
    rmSync(join(home, '.dsh', 'sessions', '--other-proj--'), { recursive: true, force: true })

    // F. per-role reader: home ticket-shaped dirs are found, role parsed, skips named
    makeSessionDir(homeSess, 't261026-05-developer')
    makeSessionDir(homeSess, 't1-2x-old') // ticket-shaped, no parseable role
    const rr = await resolveTicketRoleSessionFiles(repo)
    ok(rr.refused !== true && rr.roles.developer?.tickets.includes('t261026-05'),
      'F: per-role discovery reads the home root (developer face)', JSON.stringify(rr.roles))
    ok(rr.skips.some((s) => s.includes('t1-2x-old')), 'F: role-less ticket-shaped dir is a named skip', JSON.stringify(rr.skips))
    ok(Array.isArray(rr.searchedRoots) && rr.searchedRoots.length === 2, 'F: role discovery names both roots', JSON.stringify(rr.searchedRoots))

    // G. read-only: no file is created, moved or deleted under either root
    const snap = (d) => { const out = []; const walk = (p) => { for (const e of readdirSync(p, { withFileTypes: true })) { out.push(join(p, e.name)); if (e.isDirectory()) walk(join(p, e.name)) } }; try { walk(d) } catch { } return out.sort() }
    const before = [...snap(repoSess), ...snap(homeSess)]
    await resolveProjectSessionFiles(repo, [])
    await resolveTicketRoleSessionFiles(repo)
    ok(JSON.stringify(before) === JSON.stringify([...snap(repoSess), ...snap(homeSess)]),
      'G: discovery is read-only (no create/move/delete under either root)')

    // H. home missing: named degrade, never a throw; empty message names both roots
    process.env.SANDBAR_DSH_HOME = freshDir('dsh-missing-')
    rmSync(repoSess, { recursive: true, force: true })
    const refH = await resolveProjectSessionFiles(repo, [])
    ok(refH.paths.length === 0 && /dsh home: sessions directory does not exist/.test(refH.reason ?? ''),
      'H: missing home root degrades with a named reason', refH.reason ?? '')
    ok((refH.reason ?? '').includes(repoSess) && (refH.reason ?? '').includes(join(process.env.SANDBAR_DSH_HOME, '.dsh', 'sessions', slug)),
      'H: the empty reason names BOTH searched roots', refH.reason ?? '')
    process.env.SANDBAR_DSH_HOME = home

    // J. gen1-arbitration layout legs (mirroring the gate scenario's shapes):
    const repoJ = freshDir('roots-repo-j-')
    const homeJ = freshDir('dsh-home-j-')
    process.env.SANDBAR_DSH_HOME = homeJ
    const slugJ = slugOf(repoJ)
    const repoSessJ = join(repoJ, '.dsh', 'sessions')
    const homeSessJ = join(homeJ, '.dsh', 'sessions', slugJ)
    // J1 shallow repo tree: sessions/<dir>/file counts (over-deep demand = the
    // empty-room defect the other way around).
    makeSessionDir(repoSessJ, 'projB')
    const refJ1 = await resolveProjectSessionFiles(repoJ, [])
    ok(refJ1.paths.length === 1 && refJ1.buckets.projB?.length === 1, 'J1: a shallow repo tree (sessions/<dir>/file) counts', JSON.stringify(refJ1))
    // J2 home two names: slug/<uuid>/file counts; a sibling project slug is never entered.
    makeSessionDir(homeSessJ, 'projA')
    const refJ2 = await resolveProjectSessionFiles(repoJ, [])
    ok(refJ2.paths.length === 2, 'J2: repo shallow + home one-level both count', JSON.stringify(refJ2.paths))
    // J3 non-canonical session file names: newest mtime wins, stale sibling never counts.
    const multi = join(homeSessJ, 'projmulti')
    mkdirSync(multi, { recursive: true })
    writeFileSync(join(multi, 'older-session.jsonl.zstd'), '{}\n')
    writeFileSync(join(multi, 'newer-session.jsonl.zstd'), '{}\n')
    const { utimesSync } = await import('node:fs')
    utimesSync(join(multi, 'newer-session.jsonl.zstd'), new Date(), new Date(Date.now() + 10_000))
    const refJ3 = await resolveTicketRoleSessionFiles(repoJ)
    void refJ3
    const refJ3p = await resolveProjectSessionFiles(repoJ, [])
    const multiPaths = refJ3p.buckets.projmulti ?? []
    ok(multiPaths.length === 1 && multiPaths[0].endsWith('newer-session.jsonl.zstd'),
      'J3: one newest *.jsonl.zstd per session dir (non-canonical names included)', JSON.stringify(multiPaths))
    // J4 unreadable session dir degrades with a named reason, never throws.
    const locked = join(homeSessJ, 'locked')
    mkdirSync(locked, { recursive: true })
    writeFileSync(join(locked, SESSION_FILE), '{}\n')
    chmodSync(locked, 0o000)
    const refJ4 = await resolveProjectSessionFiles(repoJ, [])
    chmodSync(locked, 0o755)
    ok(refJ4.refused !== true && /session dir locked unreadable/.test(refJ4.reason ?? ''),
      'J4: an unreadable session dir is a NAMED degrade, never a silent skip', refJ4.reason ?? '')
    process.env.SANDBAR_DSH_HOME = home
    void existsSync
  } finally {
    if (oldHome === undefined) delete process.env.SANDBAR_DSH_HOME
    else process.env.SANDBAR_DSH_HOME = oldHome
  }
  console.log('t261026-05-declared-roots done')
  dumpFails()
  if (!__isMain) console.log('(imported as a module)')
}

if (__isMain) await runAll()
else console.log('t261026-05-declared-roots: imported as a module; battery skipped')
