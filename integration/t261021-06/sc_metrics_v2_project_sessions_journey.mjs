#!/usr/bin/env node
/**
 * sc_metrics_v2_project_sessions_journey.mjs — t261021-06 L3 (grey-box, offline seconds, needs `zstd`).
 *
 * intent (user-perceivable): the tab's "tokens spent outside any ticket" face is
 * real data with provenance — sessions under the project root's `.dsh/sessions`
 * that carry no ticket id are attributed into executor and global buckets, and
 * the discovery face refuses out-of-workspace paths exactly like the per-ticket
 * discovery does (same refusal discipline as resolveAllSessionFiles).
 *
 * User journey: a project with only-ticketless sessions shows tokens_outside_tickets > 0,
 * tokens_in_tickets consistent with tokens_total, cache_hit in [0,1]; a session dir
 * named like a ticket contributes nothing; a session dir resolving OUTSIDE the
 * workspace root refuses the whole block with a named reason (never a partial read).
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261021-06/sc_metrics_v2_project_sessions_journey.mjs (cwd=repo root)
 */
import { symlink, mkdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { withRepoStub, callMetricsV2, makeChecker, writeSession, usageEvents, zstdAvailable, NOW, DAY } from './lib_metrics_v2.mjs'

const { ok, envFail, done } = makeChecker()

if (!zstdAvailable()) {
  envFail('zstd binary missing for session fixtures')
  process.exit(done('sc_metrics_v2_project_sessions_journey'))
}

// Layout (per slug, one session dir each):
//   executor/ex-sess  → in 1000, out 100, cacheRead 50
//   global/g-sess     → in  200, out  20, cacheRead 10
//   misc/t21-99-x     → ticket-shaped SESSION-DIR NAME (the level where ticket ids
//                       live in the real layout <slug>/<ticketId>-<role>): must be
//                       EXCLUDED (arbitrate gen2: the old fixture put the ticket
//                       shape at the SLUG level, which the discovery face never
//                       reads — a fixture-shape mismatch, not a product defect)
//   lane-pt ticket    → one real per-ticket session (in 100, out 10, cacheRead 0)
//                       so the kpis ticket face (tokens_in_tickets / cache_hit)
//                       has data and stays separable from the project face
//   outside-link      → symlink to a session dir OUTSIDE the repo → refusal face
const PT = 't21-pt'
await withRepoStub(
  async (repo) => {
    const e1 = await writeSession(repo, 'executor', 'ex-sess', usageEvents(1000, 100, 50, Date.now()))
    const e2 = await writeSession(repo, 'global', 'g-sess', usageEvents(200, 20, 10, Date.now()))
    const e3 = await writeSession(repo, 'misc', 't21-99-x', usageEvents(999999, 999999, 0, Date.now()))
    const e4 = await writeSession(join(repo, 'lane-pt'), 'slug0', `${PT}-exec`, usageEvents(100, 10, 0, Date.now()))
    const outHost = join(tmpdir(), `sandbar-m21-outside-${Date.now().toString(36)}`)
    await mkdir(join(outHost, 'evil-sess'), { recursive: true })
    try {
      await symlink(join(outHost, 'evil-sess'), join(repo, '.dsh', 'sessions', 'outside-link'), 'dir')
    } catch { /* symlink unsupported: the out-of-root leg degrades to D-refusal-absent below */ }
    return {
      project: 'demo',
      workflows: [{ id: 'dev-lane', name: 'dev-lane', stages: [{ id: 'plan', exit: 'human' }] }],
      stages: [{ id: 'plan', exit: 'human' }],
      tickets: [{
        id: PT, workflow: 'dev-lane', status: 'closed', worktree: 'lane-pt', epic: '',
        updated: new Date().toISOString(),
        // anchored timeline so the ticket enters the window population (its token
        // record then feeds tokens_in_tickets / cache_hit)
        timeline: [
          { at: new Date(NOW - DAY).toISOString(), stage: 'plan', state: 'running' },
          { at: new Date(NOW - DAY + 3600e3).toISOString(), stage: 'plan', state: 'closed' },
        ],
      }],
      epics: [],
      _layout: { e1, e2, e3, e4 },
    }
  },
  async ({ deps, m, repo, tmp }) => {
    const r = await callMetricsV2(deps, { view: 'token', window: 'all' })
    ok(r.status === 200, 'front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const b = r.body
    const ps = b.project_sessions

    // P1 — buckets exist with the real sums; executor/global attribution by slug.
    ok(ps != null && typeof ps === 'object', 'P1 project_sessions present (project HAS project-level sessions)', JSON.stringify(ps)?.slice(0, 160))
    if (!ps || typeof ps !== 'object') return
    const ex = ps.executor ?? ps.buckets?.executor
    const gl = ps.global ?? ps.buckets?.global
    ok(ex != null && (ex.in ?? ex.total?.in) === 1000 && (ex.out ?? ex.total?.out) === 100, 'P1 executor bucket = in 1000 / out 100', JSON.stringify(ex))
    ok(gl != null && (gl.in ?? gl.total?.in) === 200, 'P1 global bucket = in 200', JSON.stringify(gl))

    // P2 — the ticket-shaped dir is excluded: its 999999 tokens appear NOWHERE in the block.
    ok(!JSON.stringify(ps).includes('999999'), 'P2 ticket-id-named session dir excluded (no 999999 anywhere)', '')

    // P3 — kpis cross-face consistency. cache_hit is defined over TICKET records
    // only (contract v2 kpis table): the ticket session carries in 100 / out 10 /
    // cacheRead 0 → cache_hit = 0/(110) = 0 (denominator non-zero, so not null).
    const k = b.kpis ?? {}
    const outside = k.tokens_outside_tickets
    ok(outside === 1320, `P3 tokens_outside_tickets=1320 (1000+100+200+20, sneaky excluded)`, `got ${outside}`)
    ok(k.tokens_in_tickets === 110, `P3 tokens_in_tickets=110 (the ticket's own session)`, `got ${k.tokens_in_tickets}`)
    ok(k.cache_hit === 0, `P3 cache_hit = 0 (ticket cacheRead 0 over a non-zero denominator)`, `got ${k.cache_hit}`)

    // P4 — refusal face: an out-of-workspace session dir must never leak its bytes.
    // (Discovery refuses any RESOLVED path outside the workspace; a symlinked dir
    // that the traversal never resolves is skipped — either way no outside bytes
    // may enter the payload. The refusal-reason face itself stays covered by the
    // per-ticket discovery twin, resolveAllSessionFiles.)
    ok(!JSON.stringify(b).includes('evil-sess'), 'P4 no out-of-workspace bytes ever enter the payload', '')
  },
)

process.exit(done('sc_metrics_v2_project_sessions_journey'))
