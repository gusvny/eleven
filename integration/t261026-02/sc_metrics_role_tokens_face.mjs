#!/usr/bin/env node
/**
 * sc_metrics_role_tokens_face.mjs — t261026-02 L3 (grey-box, offline seconds, needs `zstd`).
 *
 * intent (user-perceivable): the Metrics tab's "Tokens by role" rows are REAL
 * per-role data — fresh tokens, cache and ticket coverage aggregated from the
 * `<ticket>-<role>` session directories that already live under the project
 * root's `.dsh/sessions` tree — and a role nobody ran under reads as an empty
 * role ('no sessions in window'), never as 'no per-role face'.
 *
 * Host report 261025: developer/integration/executor all showed a dash with no
 * per-role face, by construction (the rows were hardcoded and never read the
 * payload). The data was always on disk; this scenario proves the face reads it.
 *
 * Fixture (one stub repo, real session files on disk, all inside the root):
 *   slug-a/t261026-02-developer       → in 1000 out 100 cache 50
 *   slug-b/t261026-02-developer       → in  200 out  20 cache  5   (same ticket+role, 2nd slug)
 *   slug-b/t261026-02-integration     → in  500 out  50 cache  0
 *   slug-c/t261026-03-reviewer        → in   10 out   1 cache  0   (role beyond the fixed three, kept verbatim)
 *   slug-a/t261026-04-scanner         → garbage session file (unreadable degrade, siblings survive)
 *   slug-a/t261026-99x                → ticket-shaped dir name with NO parseable role (skipped AND named)
 * The 'executor' role has NO directory at all → absent from the roles map, the
 * face the tab must render as 'no sessions in window' (never 'no per-role face').
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261026-02/sc_metrics_role_tokens_face.mjs (cwd=repo root)
 */
import { withRepoStub, callMetricsV2, makeChecker, writeSession, writeGarbageSession, usageEvents, zstdAvailable, NOW } from '../t261021-06/lib_metrics_v2.mjs'

const { ok, envFail, done } = makeChecker()

if (!zstdAvailable()) {
  envFail('zstd binary missing for session fixtures')
  process.exit(done('sc_metrics_role_tokens_face'))
}

await withRepoStub(
  async (repo) => {
    const f1 = await writeSession(repo, 'slug-a', 't261026-02-developer', usageEvents(1000, 100, 50, Date.now()))
    const f2 = await writeSession(repo, 'slug-b', 't261026-02-developer', usageEvents(200, 20, 5, Date.now()))
    const f3 = await writeSession(repo, 'slug-b', 't261026-02-integration', usageEvents(500, 50, 0, Date.now()))
    const f4 = await writeSession(repo, 'slug-c', 't261026-03-reviewer', usageEvents(10, 1, 0, Date.now()))
    await writeGarbageSession(repo, 'slug-a', 't261026-04-scanner')
    await writeGarbageSession(repo, 'slug-a', 't261026-99x')
    return {
      project: 'demo',
      workflows: [{ id: 'dev-lane', name: 'dev-lane', stages: [{ id: 'plan', exit: 'human' }] }],
      stages: [{ id: 'plan', exit: 'human' }],
      tickets: [],
      epics: [],
      _layout: { f1, f2, f3, f4 },
    }
  },
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'token', window: 'all' })
    ok(r.status === 200, 'R0 front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const b = r.body
    const ra = b.role_aggregate

    // R1 — the face exists at all: an additive top-level role block is on the response.
    ok(ra != null && typeof ra === 'object', 'R1 role aggregate block present (no face was shipped at all before this ticket)', JSON.stringify(ra)?.slice(0, 200))
    if (!ra || typeof ra !== 'object') return
    const roles = ra.roles && typeof ra.roles === 'object' ? ra.roles : null
    ok(roles != null, 'R1 roles map present', JSON.stringify(Object.keys(ra)))

    // R2 — developer: fresh-token sums over BOTH its session dirs; ticket coverage counts distinct tickets (1), files 2.
    const dev = roles?.developer
    ok(dev != null && typeof dev === 'object', 'R2 developer role present', JSON.stringify(dev))
    if (dev && typeof dev === 'object') {
      ok((dev.in ?? dev.input) === 1200, 'R2 developer fresh input = 1000+200 (chunk mirror never double-counted)', JSON.stringify(dev))
      ok((dev.out ?? dev.output) === 120, 'R2 developer fresh output = 100+20', JSON.stringify(dev))
      ok(dev.cache_read === 55, 'R2 developer cache_read = 50+5', JSON.stringify(dev))
      ok(dev.tickets === 1, 'R2 developer ticket coverage counts DISTINCT tickets (two dirs, one ticket id)', JSON.stringify(dev))
      ok(dev.files === 2, 'R2 developer file count = 2 session dirs', JSON.stringify(dev))
    }

    // R3 — integration: exact sums, its own bucket, never blended into developer.
    const integ = roles?.integration
    ok(integ != null && (integ.in ?? integ.input) === 500 && integ.out === 50 && integ.cache_read === 0,
      'R3 integration role exact sums, its own bucket', JSON.stringify(integ))

    // R4 — a role beyond the fixed three is kept verbatim, not dropped, not invented.
    const rev = roles?.reviewer
    ok(rev != null && (rev.in ?? rev.input) === 10, 'R4 role reviewer (ran on disk) kept verbatim with its sums', JSON.stringify(rev))

    // R5 — the empty role: executor ran NOWHERE on disk, so the roles map must
    // not invent it (absent, or present only as a zero-coverage declaration) —
    // the tab then says 'no sessions in window', never 'no per-role face', and
    // never fabricates tokens for a role nobody ran under.
    const exec = roles?.executor
    ok(exec === undefined || exec === null || ((exec.files ?? 0) === 0 && !(exec.in > 0 || exec.out > 0)),
      'R5 executor (no session dirs on disk) is absent or zero-declared, never invented', JSON.stringify(exec))

    // R6 — a ticket-shaped dir name with NO parseable role contributes nothing
    // to any role AND is named (skipped-and-named, never silently swallowed).
    const text = JSON.stringify(b)
    ok(!roles || (Object.keys(roles).every((k) => !/99x/.test(k)) && (roles.reviewer?.in ?? roles.reviewer?.input) === 10), 'R6 junk ticket-shaped dir contributes no sums and no role key', JSON.stringify(Object.keys(roles ?? {})))
    ok(/99x|no parseable role/.test(text), 'R6 the skipped dir is NAMED in the payload (reason/notice)', 'no mention of the skipped dir')

    // R7 — one garbage session file degrades with a named reason; the good roles survive intact.
    const scan = roles?.scanner
    ok(/scanner|t261026-04-scanner/.test(String(ra.reason ?? '')) || (scan && typeof scan.reason === 'string' && scan.reason.length > 0),
      'R7 the unreadable session file is named (per-file reason, never swallowed)', String(ra.reason ?? '').slice(0, 300))
    ok(scan && (scan.in ?? 0) === 0 && (scan.out ?? 0) === 0, 'R7 the unreadable file contributes no fabricated sums', JSON.stringify(scan))
    const devAfter = roles?.developer
    ok(devAfter && (devAfter.in ?? devAfter.input) === 1200, 'R7 garbage file did not destroy the developer totals', JSON.stringify(devAfter))

    // R8 — the block total equals the sum of its roles (fresh in+out; cache separate).
    let tin = 0, tout = 0, tcache = 0
    for (const v of Object.values(roles ?? {})) {
      tin += v?.in ?? 0; tout += v?.out ?? 0; tcache += v?.cache_read ?? 0
    }
    const tot = ra.total && typeof ra.total === 'object' ? ra.total : null
    if (tot) {
      ok((tot.in ?? 0) === tin && (tot.out ?? 0) === tout && (tot.cache_read ?? 0) === tcache,
        'R8 block total = sum of roles', JSON.stringify({ tot, tin, tout, tcache }))
    } else {
      ok(false, 'R8 block carries a total', 'role_aggregate.total missing')
    }
  },
)

process.exit(done('sc_metrics_role_tokens_face'))
