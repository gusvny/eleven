/**
 * lib_metrics_v2.mjs — shared fixtures for the t261021-06 Metrics API v2 scenarios.
 * Shared helper code (non-sc_ prefix: registered nowhere, lint-exempt by design).
 *
 * Reuse discipline: the population/stub/cache helpers come from t260903-09's
 * lib_integration.mjs (front-door seam `buildMetricsResponse`, deterministic NOW,
 * three-state checker). This file adds only what the v2 faces need:
 *   - a stub wrapper whose repo is a real writable tmp directory (the v2 ticket
 *     needs real session files on disk; the old stub repo path `/stub-repo` is not
 *     writable), with ticket rows pointing at lane dirs inside that repo;
 *   - zstd session-file writers for the per-ticket and the project-level
 *     `.dsh/sessions` trees (same two-generation file names the product reads);
 *   - a response-tree walker for the "no money" guard.
 * All fixtures live under the ticket's tmp/ dir inside the workspace; nothing
 * touches port 3099, Docker, Temporal, or a browser.
 */
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadMetrics, freshTmp, rmRf, makeChecker, NOW, DAY, iso } from '../t260903-09/lib_integration.mjs'

export { loadMetrics, freshTmp, rmRf, makeChecker, NOW, DAY, iso }

const HERE = fileURLToPath(new URL('.', import.meta.url))

/** Minimal usage-event sequence (same shape the per-ticket tests use): model attribution + one message usage; the chunk mirror must NOT be counted. */
export function usageEvents(input, output, cacheRead, timeMs) {
  return [
    { type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 },
    { type: 'assistant/message', data: { usage: { inputTokens: input, outputTokens: output, cacheReadTokens: cacheRead } }, time: timeMs },
    { type: 'assistant/chunk', data: { chunk: { type: 'usage', inputTokens: input, outputTokens: output, cacheReadTokens: cacheRead } }, time: timeMs + 0.5 },
  ]
}

/** Write one session file (zstd-compressed jsonl, old-generation name) under <wsRoot>/.dsh/sessions/<slug>/<dir>/. Returns {ok, reason}. */
export async function writeSession(wsRoot, slug, dirName, events) {
  const sess = join(wsRoot, '.dsh', 'sessions', slug, dirName)
  await mkdir(sess, { recursive: true })
  const raw = join(sess, 'raw.jsonl')
  await writeFile(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n', 'utf8')
  try {
    execFileSync('zstd', ['-f', '-q', raw, '-o', join(sess, 'session.jsonl.zstd')], { stdio: 'pipe' })
  } catch (err) {
    await rm(raw, { force: true })
    return { ok: false, reason: `zstd unavailable: ${String(err?.message ?? err)}` }
  }
  await rm(raw, { force: true })
  return { ok: true }
}

/** Write a raw (garbage) file where a session file is expected — the unreadable-file degrade face. */
export async function writeGarbageSession(wsRoot, slug, dirName) {
  const sess = join(wsRoot, '.dsh', 'sessions', slug, dirName)
  await mkdir(sess, { recursive: true })
  await writeFile(join(sess, 'session.jsonl.zstd'), Buffer.from('this is not zstd\n'), 'utf8')
}

/**
 * Stub wrapper with a REAL writable repo root. `layout` builds the on-disk faces
 * (lane sessions / project sessions) and receives the repo root; it returns the
 * stub object (ticket rows may carry worktree paths relative to that root).
 */
export async function withRepoStub(layout, fn) {
  const tmp = await freshTmp('m21')
  const repo = join(tmp, 'repo')
  await mkdir(repo, { recursive: true })
  const stub = await layout(repo)
  const stubPath = join(tmp, 'stub.json')
  await writeFile(stubPath, JSON.stringify(stub), 'utf8')
  const cacheRoot = join(tmp, 'cache')
  const saved = { STUB: process.env.SANDBAR_METRICS_STUB, DIR: process.env.SANDBAR_METRICS_DIR }
  process.env.SANDBAR_METRICS_STUB = stubPath
  process.env.SANDBAR_METRICS_DIR = cacheRoot
  try {
    const m = await loadMetrics()
    const deps = m.defaultDeps(repo, () => NOW)
    return await fn({ deps, repo, cacheRoot, tmp, m })
  } finally {
    if (saved.STUB === undefined) delete process.env.SANDBAR_METRICS_STUB
    else process.env.SANDBAR_METRICS_STUB = saved.STUB
    if (saved.DIR === undefined) delete process.env.SANDBAR_METRICS_DIR
    else process.env.SANDBAR_METRICS_DIR = saved.DIR
    await rmRf(tmp)
  }
}

/** Call the front door (same seam the HTTP route and the CLI both serve). */
export async function callMetricsV2(deps, query) {
  const m = await loadMetrics()
  return m.buildMetricsResponse({ project: 'demo', window: '7d', ...query }, deps)
}

/** Ticket row with a lane worktree inside the stub repo (sessions resolve under <repo>/<lane>/.dsh/sessions).
 *  `workflow` overrides the chain — without it a hotfix fixture ticket silently stays dev-lane and the
 *  chain-mixing assertions test a mixed fixture (this fix has been reverted by the settle repeatedly;
 *  a copy now rides in rework_gen2_bundle for loss-proof re-application). `updated` must be an ISO
 *  STRING — the row parser (isoMs) is string-typed; a numeric ms parses to NaN and the last_activity
 *  face degrades for the wrong reason. */
export function laneTicket(id, lane, { createdAt, closedAt, timeline, epic, updated, workflow, extra = {} } = {}) {
  return {
    id,
    workflow: workflow ?? 'dev-lane',
    status: closedAt != null ? 'closed' : 'running',
    worktree: lane,
    epic: epic ?? '',
    updated: updated ?? (closedAt ?? createdAt ?? NOW),
    timeline: timeline ?? [],
    ...extra,
  }
}

/** Depth-first key inventory of a JSON tree (for the no-money guard). */
export function allKeys(node, out = []) {
  if (Array.isArray(node)) { for (const n of node) allKeys(n, out); return out }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) { out.push(k); allKeys(v, out) }
  }
  return out
}

/** Common workflow/stage tables: dev-lane carries a human-exit stage (plan) for the human_wait face. */
export const WF_STAGES = [
  { id: 'plan', exit: 'human' },
  { id: 'code', exit: 'agent' },
  { id: 'review', exit: 'human' },
]
export const WF_DEV = { id: 'dev-lane', name: 'dev-lane', stages: WF_STAGES }
export const WF_HOTFIX = { id: 'hotfix', name: 'hotfix', stages: [{ id: 'plan', exit: 'human' }, { id: 'code', exit: 'agent' }] }

/** Does the environment carry the zstd binary the session fixtures need? */
export function zstdAvailable() {
  return existsSync('/opt/homebrew/bin/zstd') || existsSync('/usr/bin/zstd') || existsSync('/usr/local/bin/zstd')
}
export { HERE }
