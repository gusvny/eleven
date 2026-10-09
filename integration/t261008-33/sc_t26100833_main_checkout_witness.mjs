#!/usr/bin/env node
/**
 * sc_t26100833_main_checkout_witness.mjs — t261008-33, grey-box L3, "ro" pool.
 *
 * User-perceivable face under test (ticket 261008 required outcome 4 + evidence
 * item "L3: the scenario that writes evidence leaves the main checkout clean"):
 * the 261008 incident class, replayed as an assertion. A lane-resident writer
 * whose environment carries the MAIN checkout as its repo anchor (the shape
 * every engine-spawned child lived in before this ticket) must not modify the
 * main checkout's working tree — the writer either fails with the named guard
 * or lands its evidence inside its own lane. The main checkout is judged from
 * the READER side: `git status --porcelain` in the real checkout this scenario
 * runs against, derived via `git rev-parse` (never from SANDBAR_REPO, which
 * the fix withdraws from lane children).
 *
 * Judgement is DELTA-based on purpose: the main checkout is a shared tree, so
 * the assertion is "no NEW dirt appeared while the lane writer ran", with any
 * pre-existing dirt reported verbatim in the evidence line (the gate's
 * main_untouched check owns the absolute-clean judgement; this entry owns the
 * causal witness that lane writes cannot be the dirt).
 *
 * Harness: real git fixtures (a seed repo, a genuine linked worktree as the
 * lane) built entirely inside a tmp dir — the real main checkout is touched
 * READ-ONLY (status only). The current resolver module is copied into the lane
 * at its real location. Anti-proof leg proves the harness detects
 * contamination when no guard exists (non-vacuity, t261008-04 lesson).
 * Offline seconds, zero docker/Temporal/3099. Module missing = FAIL named
 * (TDD-phase red expected; arbitrate/merge must be green). git missing =
 * ENV_FAIL exit 2.
 *
 * Intent split: guard verdict contract = sc_t26100833_anchor_guard_named_failure;
 * env-boundary contract = sc_t26100833_lane_env_anchor_boundary; the gate's
 * main_untouched absolute check = existing merge_check face (not re-judged).
 * This entry uniquely owns the incident-class reader-side witness.
 */
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { emitCase } from '../lib_result.mjs'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = realpathSync(join(HERE, '..', '..'))

let passed = 0, failed = 0, envfail = 0
function judge(name, ok, reason = '', evidence = '') {
  if (ok) passed++; else failed++
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
  emitCase({ name, suite: 't261008-33', status: ok ? 'pass' : 'fail',
    cause: ok ? 'self' : 'unknown', reason: ok ? '' : reason, evidence: evidence || reason })
}
function envFail(name, reason) {
  envfail++
  console.log(`[ENV_FAIL] ${name} — ${reason}`)
  emitCase({ name, suite: 't261008-33', status: 'not-checked', cause: 'external', reason, evidence: reason })
}
function git(cwd, args) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`git ${args.join(' ')} failed: ${r.stderr}`)
  return r.stdout
}

// Main checkout this gate runs against: read-only witness target.
let mainCheckout
try {
  const commonDir = git(REPO, ['rev-parse', '--path-format=absolute', '--git-common-dir']).trim()
  mainCheckout = realpathSync(join(commonDir, '..'))
} catch (e) {
  envFail('main-checkout-derivable', String(e).slice(0, 200))
}
const gitPresent = spawnSync('git', ['--version']).status === 0

if (mainCheckout && gitPresent) {
  const porcelainMain = () => git(mainCheckout, ['status', '--porcelain']).trim()
  const beforeLines = porcelainMain().split('\n').filter(Boolean)
  if (beforeLines.length) console.log(`[NOTE] main checkout carries pre-existing dirt (${beforeLines.length} lines); judgement is delta-based`)

  const tmp = mkdtempSync(join(tmpdir(), 'sandbar-t26100833-witness-'))
  process.on('exit', () => {
    try { spawnSync('git', ['worktree', 'prune', '--expire', 'now'], { cwd: join(tmp, 'seed') }) } catch {}
    try { rmSync(tmp, { recursive: true, force: true }) } catch {}
  })

  // Fixture: seed repo + a genuine linked worktree (the lane shape).
  const seed = join(tmp, 'seed'), lane = join(tmp, 'lane')
  let built = true
  try {
    for (const d of [seed]) {
      mkdirSync(d, { recursive: true }); git(d, ['init', '-q'])
      git(d, ['config', 'user.email', 't@example.test']); git(d, ['config', 'user.name', 't'])
      writeFileSync(join(d, 'tracked.txt'), 'seed\n'); git(d, ['add', '.']); git(d, ['commit', '-qm', 'seed'])
    }
    git(seed, ['worktree', 'add', '-q', lane, '-b', 'lane-wt'])
  } catch (e) { built = false; envFail('lane-fixture-buildable', String(e).slice(0, 200)) }

  if (built) {
    const srcMod = join(REPO, 'server', 'plugins', 'repo-anchor.mjs')
    if (!existsSync(srcMod)) {
      judge('resolver-landed-for-witness', false,
        'server/plugins/repo-anchor.mjs missing: not landed — TDD-phase red expected pre-implement', srcMod)
    } else {
      mkdirSync(join(lane, 'server', 'plugins'), { recursive: true })
      cpSync(srcMod, join(lane, 'server', 'plugins', 'repo-anchor.mjs'))

      // The "evidence writer": the shape the browser-pool scenario ran with —
      // resolve the anchor from env, guard, then write an evidence file.
      const childCode = `
        const fs = await import('node:fs');
        const path = await import('node:path');
        const { pathToFileURL } = await import('node:url');
        const home = process.env.FIX_HOME;
        let m;
        try { m = await import(pathToFileURL(path.join(home, 'server', 'plugins', 'repo-anchor.mjs')).href); }
        catch (e) { console.log('VERDICT=' + JSON.stringify({ kind: 'import-error', detail: String(e).slice(0, 200) })); process.exit(0); }
        if (typeof m.resolveRepoAnchor !== 'function' || typeof m.assertAnchorOwnTree !== 'function') {
          console.log('VERDICT=' + JSON.stringify({ kind: 'surface-changed', exports: Object.keys(m).join(',') })); process.exit(0);
        }
        try {
          const a = m.resolveRepoAnchor(undefined);
          try { m.assertAnchorOwnTree(a.repo, a.anchorSource); }
          catch (e) { console.log('VERDICT=' + JSON.stringify({ kind: 'guard', msg: String(e.message || e).slice(0, 400) })); process.exit(0); }
          const out = path.join(a.repo, 'integration', 't261008-33', 'shots');
          fs.mkdirSync(out, { recursive: true });
          fs.writeFileSync(path.join(out, 'witness-probe.png'), 'png-bytes');
          console.log('VERDICT=' + JSON.stringify({ kind: 'wrote', repo: a.repo }));
        } catch (e) { console.log('VERDICT=' + JSON.stringify({ kind: 'threw', msg: String(e).slice(0, 300) })); }
      `
      const childPath = join(tmp, 'writer.mjs'); writeFileSync(childPath, childCode)
      const runWriter = (anchorEnv) => {
        const env = { ...process.env, FIX_HOME: lane }
        delete env.SANDBAR_REPO
        if (anchorEnv !== undefined) env.SANDBAR_REPO = anchorEnv
        return spawnSync(process.execPath, [childPath], { cwd: lane, env, encoding: 'utf8', timeout: 30000 })
      }
      const verdict = (r) => {
        try { return JSON.parse((r.stdout || '').split('\n').find(l => l.startsWith('VERDICT=')).slice(8)) }
        catch { return { kind: 'no-verdict', detail: `${r.stdout} ${r.stderr}`.slice(0, 200) } }
      }
      const mainShots = join(mainCheckout, 'integration', 't261008-33', 'shots')
      const mainShotsBefore = existsSync(mainShots) ? readdirSync(mainShots).sort().join(',') : ''

      // Leg 1 — the incident shape: lane writer, env anchor = the REAL main checkout.
      let v1 = verdict(runWriter(mainCheckout))
      if (v1.kind === 'import-error' || v1.kind === 'surface-changed') {
        judge('incident-shape-refused-at-main', false, `resolver not landed: ${JSON.stringify(v1)}`)
      } else if (v1.kind === 'threw' && /EPERM|EACCES/.test(v1.msg || '')) {
        // The OS denied the cross-checkout write before the guard could judge
        // (sandboxed host). The face could not be exercised here: honest env red.
        envFail('incident-shape-refused-at-main',
          `write into the main checkout was OS-denied before the guard judged; guard face unexercisable in this sandbox: ${v1.msg.slice(0, 200)}`)
      } else {
        judge('incident-shape-refused-at-main',
          v1.kind === 'guard' && String(v1.msg).includes('SANDBAR_ANCHOR_MISMATCH')
            || (v1.kind === 'wrote' && realpathSync(v1.repo) === realpathSync(lane)),
          `verdict=${JSON.stringify(v1).slice(0, 250)}`)
      }
      let after1 = porcelainMain()
      let after1Set = new Set(after1.split('\n').filter(Boolean))
      let newDirt1 = [...after1Set].filter(l => !beforeLines.includes(l))
      judge('main-checkout-clean-after-incident-shape', newDirt1.length === 0,
        `new dirt=${JSON.stringify(newDirt1)}`, `porcelain delta empty; pre-existing=${beforeLines.length} lines`)
      judge('main-shots-dir-untouched-by-incident-shape',
        (existsSync(mainShots) ? readdirSync(mainShots).sort().join(',') : '') === mainShotsBefore,
        `shots listing changed during this run (judgement is the listing DELTA; pre-existing residue at run start: ${mainShotsBefore || 'none'} — residue from a pre-fix run is reported for separate cleanup, never judged here)`)

      // Leg 2 — the fixed shape: env anchor = the lane root; evidence lands in the lane.
      let v2 = verdict(runWriter(lane))
      judge('lane-anchored-write-lands-evidence-in-lane',
        v2.kind === 'wrote' && existsSync(join(lane, 'integration', 't261008-33', 'shots', 'witness-probe.png')),
        `verdict=${JSON.stringify(v2).slice(0, 200)}`)
      let after2 = porcelainMain()
      let newDirt2 = after2.split('\n').filter(Boolean).filter(l => !beforeLines.includes(l))
      judge('main-checkout-still-clean-after-lane-write', newDirt2.length === 0,
        `new dirt=${JSON.stringify(newDirt2)}`)

      // Anti-proof (non-vacuity): a guard-less writer in a standalone-shaped
      // tree DOES land its probe at the anchor — the harness above would have
      // seen it. Build a standalone copy of the module and point it at `seed`.
      const standalone = join(tmp, 'standalone')
      mkdirSync(join(standalone, 'server', 'plugins'), { recursive: true })
      cpSync(srcMod, join(standalone, 'server', 'plugins', 'repo-anchor.mjs'))
      const env = { ...process.env, FIX_HOME: standalone, SANDBAR_REPO: seed }
      let v3 = verdict(spawnSync(process.execPath, [childPath], { cwd: standalone, env, encoding: 'utf8', timeout: 30000 }))
      judge('harness-detects-contamination-anti-proof',
        v3.kind === 'wrote' && existsSync(join(seed, 'integration', 't261008-33', 'shots', 'witness-probe.png')),
        `a silent no-op harness (verdict=${JSON.stringify(v3).slice(0, 120)}) would pass even with the defect present`)

      // Hygiene: probe cleaned from the lane fixture.
      rmSync(join(lane, 'integration'), { recursive: true, force: true })
    }
  }
}

console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail}`)
process.exit(envfail ? 2 : failed ? 1 : 0)
