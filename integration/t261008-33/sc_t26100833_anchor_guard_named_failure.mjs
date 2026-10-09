#!/usr/bin/env node
/**
 * sc_t26100833_anchor_guard_named_failure.mjs — t261008-33, grey-box L3, "ro" pool.
 *
 * User-perceivable face under test (ticket 261008 required outcome 2 + 3 +
 * evidence items "L1 guard", "L3 foreign anchor", "L3 external caller"):
 * a process that lives in a git LINKED WORKTREE (a lane) and resolves a repo
 * anchor OUTSIDE its own tree must fail LOUDLY with the named error
 * SANDBAR_ANCHOR_MISMATCH BEFORE any write, stating both absolute paths and
 * where each came from. A process in a standalone checkout keeps honouring an
 * explicit anchor (the documented escape hatch for unusual layouts). No
 * anchor set = the location-derived normal state, never an error. Resolution
 * ORDER itself is never re-judged here (that is the documented chain, out of
 * scope).
 *
 * Harness: real git fixtures (a seed repo + a genuine linked worktree + two
 * standalone repos), the CURRENT resolver module copied into each fixture
 * tree at its real location (server/plugins/repo-anchor.mjs) so the guard's
 * own-tree detection sees the fixture tree — offline seconds, zero docker/
 * Temporal/3099. The guard judging per-module-location (not cwd) is the
 * declared design; the fixtures place the module where the process "lives".
 * Module/export surface missing = FAIL named (TDD-phase red expected;
 * arbitrate/merge must be green). git missing = ENV_FAIL exit 2.
 *
 * Intent split: env-boundary contract = sc_t26100833_lane_env_anchor_boundary;
 * main-checkout-clean witness = sc_t26100833_main_checkout_witness; guard
 * truth tables in python = developer L1. This entry owns the guard's named
 * verdict contract and the external-caller regression across four tree shapes.
 */
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
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

const tmp = mkdtempSync(join(tmpdir(), 'sandbar-t26100833-guard-'))
process.on('exit', () => {
  try { spawnSync('git', ['worktree', 'prune', '--expire', 'now'], { cwd: join(tmp, 'seed') }) } catch {}
  try { rmSync(tmp, { recursive: true, force: true }) } catch {}
})

// ---- fixtures -------------------------------------------------------------
// seed: a normal repo; laneWT: a REAL linked worktree of it (.git is a gitfile);
// other/other2: standalone checkouts an anchor could wrongly point at.
const seed = join(tmp, 'seed'), lane = join(tmp, 'lane'),
      other = join(tmp, 'other'), other2 = join(tmp, 'other2')
let gitOk = true
try {
  for (const d of [seed, other, other2]) {
    mkdirSync(d, { recursive: true }); git(d, ['init', '-q'])
    git(d, ['config', 'user.email', 't@example.test']); git(d, ['config', 'user.name', 't'])
    writeFileSync(join(d, 'tracked.txt'), `${d}\n`)
    git(d, ['add', '.']); git(d, ['commit', '-qm', 'seed'])
  }
  git(seed, ['worktree', 'add', '-q', lane, '-b', 'lane-wt'])
} catch (e) {
  gitOk = false
  envFail('git-fixtures-buildable', String(e).slice(0, 300))
}

if (gitOk) {
  // Place the CURRENT resolver module where each process "lives".
  const srcMod = join(REPO, 'server', 'plugins', 'repo-anchor.mjs')
  if (!existsSync(srcMod)) {
    judge('anchor-resolver-module-landed', false,
      'server/plugins/repo-anchor.mjs missing: shared resolver not landed — TDD-phase red expected pre-implement', srcMod)
  } else {
    for (const d of [lane, seed]) {
      mkdirSync(join(d, 'server', 'plugins'), { recursive: true })
      cpSync(srcMod, join(d, 'server', 'plugins', 'repo-anchor.mjs'))
    }
    const snap = (d) => git(d, ['status', '--porcelain', '-uno']).trim()
    const probeName = 'anchor_probe.txt'

    // Child: import the resolver from its OWN tree (the process's home tree),
    // resolve via env, run the guard, and only then write a probe file.
    const childCode = `
      const fs = await import('node:fs');
      const path = await import('node:path');
      const { pathToFileURL } = await import('node:url');
      const home = process.env.FIX_HOME;
      const modPath = path.join(home, 'server', 'plugins', 'repo-anchor.mjs');
      let m;
      try { m = await import(pathToFileURL(modPath).href); }
      catch (e) { console.log('VERDICT=' + JSON.stringify({ kind: 'import-error', detail: String(e).slice(0, 300) })); process.exit(0); }
      const resolve = m.resolveRepoAnchor;
      const guard = m.assertAnchorOwnTree;
      if (typeof resolve !== 'function' || typeof guard !== 'function') {
        console.log('VERDICT=' + JSON.stringify({ kind: 'surface-changed', exports: Object.keys(m).join(',') }));
        process.exit(0);
      }
      try {
        const a = resolve(undefined);
        let gErr = null;
        try { guard(a.repo, a.anchorSource); } catch (e) { gErr = e; }
        if (gErr) {
          console.log('VERDICT=' + JSON.stringify({ kind: 'guard', name: gErr.name || '', msg: String(gErr.message || gErr).slice(0, 600) }));
          process.exit(0);
        }
        const probe = path.join(a.repo, process.env.PROBE_NAME);
        fs.writeFileSync(probe, 'probe\\n');
        console.log('VERDICT=' + JSON.stringify({ kind: 'wrote', repo: a.repo, source: a.anchorSource }));
      } catch (e) {
        console.log('VERDICT=' + JSON.stringify({ kind: 'threw', msg: String(e).slice(0, 400) }));
      }
    `
    const writeTmp = join(tmp, 'child.mjs'); writeFileSync(writeTmp, childCode)

    function runLeg(home, anchorEnv) {
      const env = { ...process.env, FIX_HOME: home, PROBE_NAME: probeName }
      delete env.SANDBAR_REPO
      if (anchorEnv !== undefined) env.SANDBAR_REPO = anchorEnv
      return spawnSync(process.execPath, [writeTmp], { cwd: home, env, encoding: 'utf8', timeout: 30000 })
    }
    const verdict = (r) => { try { return JSON.parse((r.stdout || '').split('\n').find(l => l.startsWith('VERDICT=')).slice(8)) } catch { return { kind: 'no-verdict', detail: `${r.stdout} ${r.stderr}`.slice(0, 300) } } }
    const mentions = (msg, ...parts) => parts.every(p => msg.includes(p))

    // Leg A — the incident: lane-resident process, env anchor = another checkout.
    let beforeOther = snap(other)
    let vA = verdict(runLeg(lane, other))
    if (vA.kind === 'import-error' || vA.kind === 'surface-changed') {
      judge('guard-named-mismatch-in-lane', false, `resolver not landed/surface changed: ${JSON.stringify(vA)}`)
    } else {
      judge('guard-named-mismatch-in-lane',
        vA.kind === 'guard' && mentions(vA.msg, 'SANDBAR_ANCHOR_MISMATCH'),
        `verdict=${JSON.stringify(vA).slice(0, 300)}`)
      judge('guard-states-both-roots-and-sources',
        vA.kind === 'guard' && mentions(vA.msg, other, lane, 'SANDBAR_REPO'),
        `msg=${(vA.msg || '').slice(0, 300)}`)
      judge('mismatch-refused-before-write-other-clean',
        vA.kind === 'guard' && !existsSync(join(other, probeName)) && snap(other) === beforeOther,
        `other status delta=${JSON.stringify(snap(other))}`)
      judge('guard-throws-not-warns', vA.kind === 'guard',
        `a warning-return shape (kind=${vA.kind}) is the forbidden silence`)
    }

    // Leg B — lane-resident process, anchor = its own lane root: allowed.
    let vB = verdict(runLeg(lane, lane))
    judge('anchor-equal-lane-root-passes',
      vB.kind === 'wrote' && vB.repo && realpathSync(vB.repo) === realpathSync(lane),
      `verdict=${JSON.stringify(vB).slice(0, 200)}`)
    if (vB.kind === 'wrote') rmSync(join(lane, probeName), { force: true })

    // Leg C — no anchor at all: location-derived normal state, never an error,
    // and it must resolve to the process's own REPO ROOT (the lane), not to a
    // subdirectory of it.
    let vC = verdict(runLeg(lane, undefined))
    judge('no-anchor-is-normal-state',
      vC.kind === 'wrote' && vC.source && /location|derived/i.test(vC.source)
        && realpathSync(vC.repo) === realpathSync(lane),
      `verdict=${JSON.stringify(vC).slice(0, 200)} (location-derived must equal the lane root)`)
    if (vC.kind === 'wrote') rmSync(join(vC.repo, probeName), { force: true })

    // Leg D — external caller regression: standalone checkout honours its env anchor.
    let vD = verdict(runLeg(seed, other2))
    judge('external-caller-anchor-honoured',
      vD.kind === 'wrote' && vD.repo && realpathSync(vD.repo) === realpathSync(other2),
      `verdict=${JSON.stringify(vD).slice(0, 200)}`)
    if (vD.kind === 'wrote') rmSync(join(other2, probeName), { force: true })

    // Hygiene: all fixture trees back to clean after the probes.
    judge('fixture-trees-clean-after-legs',
      !existsSync(join(lane, probeName)) && !existsSync(join(other, probeName))
        && !existsSync(join(other2, probeName)) && snap(seed) === '' && snap(other) === '' && snap(other2) === '',
      `lane=${snap(lane)} seed=${JSON.stringify(snap(seed))} other=${JSON.stringify(snap(other))} other2=${JSON.stringify(snap(other2))}`)
  }
}

console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail}`)
process.exit(envfail ? 2 : failed ? 1 : 0)
