// sc_refusal_copy_anchor_contract.mjs — the workbench agent faces' out-of-root
// refusal contract and its copy-anchor rot tripwire (ticket t261009-10).

// Run: node integration/t261009-10/sc_refusal_copy_anchor_contract.mjs (cwd = repo
// root), or via the SCENARIOS registry entry in integration/run_scenarios.py.

// Grey-box L2, offline seconds, zero docker/Temporal/browser, never touches 3099.
// Fault being guarded (t261009-01 -> t261009-10 split): production
// resolveAgentBaseDir migrated its out-of-root refusal copy from Chinese
// (「越界」) to English ("ticket worktree outside the registered roots
// (refused to read): ...") but the workbench smoke faces kept pinning the old
// Chinese anchor, so the smoke went red (50 passed / 1 failed) and — because
// smoke is agent-run only and verify.yaml has no smoke reference (KI-047
// observation) — the engine gate never saw the red. This scenario owns:
//
//   C  contract face — the refusal itself, judged on the shared stable anchor
//      "refused to read" (the same substring the smoke faces pin), across the
//      three trigger shapes: worktree ".." escape, default extraRoots miss,
//      and an absolute path outside every registered root. Plus the negative
//      regression: an in-root worktree still resolves untouched.
//   M  malformed input — a null ticket and an empty worktree never throw and
//      never produce a base; the caller always gets a shaped result.
//   R  anchor-rot tripwire — the test faces must not re-pin the dead Chinese
//      anchor against the English copy, and the production source must still
//      carry the anchor the smoke pins. This is what puts the smoke-only red
//      inside the engine gate (KI-047: smoke redness alone is invisible to it).
//
// Pre-fix tree: R red is the expected TDD signal (the four smoke anchors are
// still Chinese); green required at the integration gate / merge.
// node missing / production TS unimportable = ENV_FAIL exit 2.

import { readFile } from 'node:fs/promises'

let pass = 0, fail = 0, envFail = 0

function ok(cond, label) {
  if (cond) { pass++; console.log('  ok   ' + label) }
  else { fail++; console.log('  FAIL ' + label) }
}

function envFailExit(msg) {
  envFail++
  console.log('ENV_FAIL: ' + msg)
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
  process.exit(2)
}

const REPO = new URL('../../', import.meta.url).pathname.replace(/\/$/, '')
const ANCHOR = 'refused to read'

let resolveAgentBaseDir
try {
  ;({ resolveAgentBaseDir } = await import(
    new URL('../../server/plugins/workbench/src/host/agent-logs.ts', import.meta.url)))
} catch (err) {
  envFailExit('workbench production module unimportable (node >= 22.18 with native type-stripping required): ' + (err?.message ?? err))
}
ok(typeof resolveAgentBaseDir === 'function', 'production resolveAgentBaseDir importable')

// ---- C. refusal contract, three trigger shapes, one shared stable anchor ----
{
  const repo = REPO
  const rEsc = resolveAgentBaseDir(repo, 't-sc', { worktree: '..' })
  ok(rEsc.base === '' && (rEsc.reason ?? '').includes(ANCHOR),
    `worktree=".." escape -> refused, reason carries the stable anchor (${ANCHOR})`)

  const rNo = resolveAgentBaseDir(repo, 't-sc', { worktree: '/otherproj/.lane/t-sc' })
  ok(rNo.base === '' && (rNo.reason ?? '').includes(ANCHOR),
    'default extraRoots: out-of-root worktree refused with the same anchor')

  const rEvil = resolveAgentBaseDir(repo, 't-sc', { worktree: '/etc' }, ['/otherproj'])
  ok(rEvil.base === '' && (rEvil.reason ?? '').includes(ANCHOR),
    'extraRoots miss: absolute path outside every registered root refused with the same anchor')

  // negative regression: the refusal must not leak into the legal path
  const { mkdtemp, mkdir, writeFile, rm } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const tmp = await mkdtemp(join(tmpdir(), 'sc-t261009-10-'))
  try {
    const wt = join(tmp, 'wt')
    await mkdir(wt, { recursive: true })
    await writeFile(join(wt, 'marker.txt'), 'x')
    // tmp is outside the repo, so register it as the ticket's own extra root
    // (the cross-project allowance, t260903-11) — the hit path must stay clean.
    const rOk = resolveAgentBaseDir(repo, 't-sc', { worktree: wt }, [tmp])
    ok(rOk.base === join(wt, '.sandbar') && rOk.reason === undefined,
      'registered-root worktree still resolves to <wt>/.sandbar with no refusal')
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

// ---- M. malformed input: shaped result, never a throw ----
{
  let threw = null, rNull = null
  try { rNull = resolveAgentBaseDir(REPO, 't-sc', null) } catch (e) { threw = e }
  ok(threw === null && rNull && typeof rNull === 'object',
    'null ticket -> shaped result, no throw (fallback face)')
  let rEmpty = null
  try { rEmpty = resolveAgentBaseDir(REPO, 't-sc', { worktree: '' }) } catch (e) { threw = e }
  ok(threw === null && rEmpty && typeof rEmpty === 'object',
    'empty worktree -> shaped result, no throw')
}

// ---- R. anchor-rot tripwire (the ticket's own fault mode, gate-visible per KI-047) ----
{
  let prodSrc = null
  try {
    prodSrc = await readFile(new URL('../../server/plugins/workbench/src/host/agent-logs.ts', import.meta.url), 'utf8')
  } catch (err) {
    envFailExit('production source unreadable: ' + (err?.message ?? err))
  }
  ok(prodSrc.includes(ANCHOR),
    `production refusal copy still carries the anchor the smoke pins (${ANCHOR}) — copy migration without anchor re-pin turns this red`)

  const faces = [
    'server/plugins/workbench/smoke/agent-live.mjs',
    'server/plugins/workbench/smoke/agent-usage.mjs',
    'server/plugins/workbench/smoke/agent-logs.mjs',
  ]
  for (const f of faces) {
    let src = null
    try {
      src = await readFile(new URL('../../' + f, import.meta.url), 'utf8')
    } catch (err) {
      envFailExit('smoke face unreadable: ' + f)
    }
    const stale = src.split('\n')
      .map((line, i) => [i + 1, line])
      .filter(([, line]) => line.includes("includes('越界')"))
    ok(stale.length === 0,
      f + ' pins no dead Chinese anchor against the English refusal copy' +
      (stale.length ? ' — stale at line(s) ' + stale.map(([n]) => n).join(',') : ''))
  }
}

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
process.exit(fail > 0 ? 1 : 0)
