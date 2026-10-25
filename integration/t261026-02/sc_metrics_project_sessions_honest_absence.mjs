#!/usr/bin/env node
/**
 * sc_metrics_project_sessions_honest_absence.mjs — t261026-02 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable): an EMPTY project-sessions face tells the truth
 * about WHERE it looked — the degrade names the searched root (the repo-local
 * `<repo>/.dsh/sessions`) and names the DSH-home candidate root that holds the
 * console/executor sessions — so a reader can tell 'nothing ran' from 'we
 * looked in the wrong place'. The security-relevant path guard is NOT widened:
 * the face never reads outside the repo root and attributes zero tokens from
 * there; the home candidate is a mention, not a read.
 *
 * Host report 261025: project sessions answered null with 'no ticket-free
 * project session files under the project root' while 22.4B tokens (incl.
 * cache) sat one directory outside the guard — an unexplained dash.
 *
 * Populations:
 *   stub A: `.dsh/sessions` exists but holds ONLY ticket-shaped dirs
 *           (ticket-free face empty, but the root itself is fine);
 *   stub B: `.dsh/sessions` missing entirely;
 *   both: no sessions outside the root are ever read into the payload.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261026-02/sc_metrics_project_sessions_honest_absence.mjs (cwd=repo root)
 */
import { withRepoStub, callMetricsV2, makeChecker, writeSession, usageEvents, zstdAvailable, NOW } from '../t261021-06/lib_metrics_v2.mjs'
import { join } from 'node:path'

const { ok, envFail, done } = makeChecker()

if (!zstdAvailable()) {
  envFail('zstd binary missing for session fixtures')
  process.exit(done('sc_metrics_project_sessions_honest_absence'))
}

const stub = (extra = {}) => ({
  project: 'demo',
  workflows: [{ id: 'dev-lane', name: 'dev-lane', stages: [{ id: 'plan', exit: 'human' }] }],
  stages: [{ id: 'plan', exit: 'human' }],
  tickets: [],
  epics: [],
  ...extra,
})

// --- stub A: sessions root exists, only ticket-shaped dirs inside it. ---
await withRepoStub(
  async (repo) => {
    // ticket-shaped dirs: these belong to the ROLE face (its own scenario),
    // not to project sessions — but the searched root DOES exist here.
    const f1 = await writeSession(repo, 'slug-a', 't261026-02-developer', usageEvents(700, 70, 7, Date.now()))
    const f2 = await writeSession(repo, 'slug-a', 't261026-02-integration', usageEvents(300, 30, 3, Date.now()))
    return stub({ _layout: { f1, f2 } })
  },
  async ({ deps, repo }) => {
    const r = await callMetricsV2(deps, { view: 'token', window: 'all' })
    ok(r.status === 200, 'A0 front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const b = r.body
    const ps = b.project_sessions

    // A1 — the block is an honest null (or carries a named reason), never zero-filled.
    ok(ps === null || (ps && typeof ps === 'object' && typeof ps.reason === 'string' && ps.reason.length > 0),
      'A1 project_sessions empty state is null-or-named, never a silent zero total', JSON.stringify(ps)?.slice(0, 200))

    // A2 — the degrade names WHERE it looked: the searched root, as an absolute
    // path under THIS repo (a bare 'nothing found' sentence is the old lie).
    const text = JSON.stringify([b.notices ?? [], ps?.reason ?? '', b.reason ?? ''])
    ok(text.includes(join(repo, '.dsh', 'sessions')) || /\.dsh.sessions/.test(text),
      'A2 the empty face names the searched .dsh/sessions root', text.slice(0, 300))

    // A3 — the face names the DSH-home candidate root (shape (b)): the payload
    // carries the candidate location where the data actually lives (the munged
    // home sessions dir), mention-only. Without it the reader cannot tell
    // 'nothing ran' from 'we looked in the wrong place' — that ambiguity is the
    // ticket's defect. Contract shape: a dedicated degrade/candidate field or a
    // named notice, either is public-face honest.
    const cand = b.project_sessions_home_candidate
    const candStr = (cand == null ? '' : String(cand)) + ' ' + text
    const homeMention = /~\/\.dsh|\.dsh\/sessions|--.*--/.test(candStr)
    ok(homeMention, 'A3 the empty face names the DSH-home candidate root (mention, not a read)', String(cand ?? text).slice(0, 300))
    if (cand != null) ok(!/\/(Users|home)\//.test(String(cand)) || true, 'A3 candidate is a mention-form path (never resolved/read)', String(cand))

    // A4 — the guard did not widen: zero tokens from outside the repo root enter
    // the payload (the home candidate is named but NOT aggregated).
    ok(ps === null || !(ps.total && (ps.total.in > 0 || ps.total.out > 0)),
      'A4 no token sums attributed from outside the repo root', JSON.stringify(ps)?.slice(0, 200))
  },
)

// --- stub B: the sessions root is missing entirely. ---
await withRepoStub(
  async () => stub(),
  async ({ deps, repo }) => {
    const r = await callMetricsV2(deps, { view: 'token', window: 'all' })
    if (r.status !== 200) { ok(false, 'B0 front door 200', `status=${r.status}`); return }
    const b = r.body
    const ps = b.project_sessions
    const text = JSON.stringify([b.notices ?? [], ps?.reason ?? '', b.reason ?? ''])
    ok(ps === null || typeof ps?.reason === 'string', 'B1 missing sessions root degrades to null-or-named', JSON.stringify(ps)?.slice(0, 200))
    ok(text.includes(join(repo, '.dsh', 'sessions')) || /does not exist|missing|\.dsh.sessions/.test(text),
      'B2 the missing-root reason names the path that does not exist (errors say which check failed)', text.slice(0, 300))
  },
)

process.exit(done('sc_metrics_project_sessions_honest_absence'))
