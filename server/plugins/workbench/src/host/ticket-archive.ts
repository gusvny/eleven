/**
 * ticket-archive.ts — legacy-row backfill from the on-disk ticket archive
 * (t261026-01).
 *
 * DEFECT: the engine's minimal-row projection (server/engine/client.py, the
 * no-snapshot branch) drops `workflow`/`created`/`updated`/`lane_version` for
 * tickets whose Temporal snapshot is unavailable — which is every archived
 * (pre-develop-buffer, legacy-v1) ticket. The data is NOT lost: the landing
 * store `<root>/<key>/data/tickets/<id>/archive.json` carries
 * `meta.created`, `meta.workflow_id`, `meta.updated` and (legacy-era only)
 * `meta.lane_version`. The metrics KPI population filters rows to the selected
 * template BEFORE windowing, so those empty rows never enter any KPI and the
 * face counts 43 tickets where the store holds 422.
 *
 * This module is the read side only: it never writes the store, never invents a
 * value (an empty `workflow_id` in the archive stays empty — the chain really
 * is unknown), and never throws into the caller's face. Backfill decisions key
 * ONLY off the row field being empty; `lane_version` is written back only when
 * the archive carries a non-empty string and the row's value is empty (recent
 * archives carry it as null/absent — it is never an input to any decision).
 *
 * Caching (pattern: `readLineFace` in node.ts, 15s TTL + single-flight):
 * - `/wf/tickets` is polled every 10s, so the store read sits behind a 15s TTL
 *   cache with a single-flight promise map keyed by the store dir. Archives are
 *   written once at ticket close (append-only), so a ≤15s-late backfill delays
 *   a row field, never corrupts it; TTL-bounded staleness is the named
 *   invalidation policy (no mtime watch — append-only writes make it
 *   unnecessary complexity).
 * - A failed store listing (missing root, unreadable dir) is NEVER cached: the
 *   cache entry is dropped so the next poll retries. Per-file parse failures
 *   ARE cached WITH the result, as a named `unreadable` id list (a visible,
 *   counted degrade beats a silent re-read flip-flop).
 * - Memory bound: the cache holds ONE index object per store dir, replaced
 *   wholesale on each refresh — the map never grows across refreshes; each
 *   index is bounded by the store's own directory listing (small objects).
 */

import { existsSync } from 'node:fs'
import { readdir, readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** The row-relevant fields of one archived ticket (verbatim store data). */
export interface ArchiveRowMeta {
  /** epoch seconds (store shape); null when absent/malformed. */
  created: number | null
  /** `meta.workflow_id`; '' when absent/empty — never guessed. */
  workflow: string
  /** `meta.lane_version`; '' when absent/None (recent archives carry it as null). */
  laneVersion: string
  /** epoch seconds (store shape); null when absent/malformed. */
  updated: number | null
}

export interface ArchiveIndex {
  metas: Map<string, ArchiveRowMeta>
  /** ids whose archive.json exists but could not be parsed — named, counted, never silent. */
  unreadable: string[]
}

export interface ArchiveRead {
  index: ArchiveIndex | null
  /** '' on success; a named reason when the read is disabled/failed. */
  reason: string
}

/** Store dir resolution. Root chain mirrors the metrics-cache convention
 *  (`SANDBAR_PROJECTS_DIR` ?? `~/.sandbar/projects`), headed by a dedicated test
 *  override. Not carried from `resolveMetricsCacheDir`: the settle-dir split and
 *  the legacy `SANDBAR_PROJECTS_YAML` disable — both are metrics-cache-specific;
 *  the ticket store exists regardless of registry mode. */
export function resolveTicketsDir(projectKey: string): { dir: string; enabled: boolean; reason?: string } {
  const root = process.env.SANDBAR_TICKETS_DIR ?? process.env.SANDBAR_PROJECTS_DIR
    ?? join(homedir(), '.sandbar', 'projects')
  const dir = join(root, projectKey, 'data', 'tickets')
  if (!existsSync(dir)) {
    return { dir, enabled: false, reason: `ticket store dir missing: ${dir}` }
  }
  return { dir, enabled: true }
}

const TTL_MS = 15_000
type CacheEntry = { at: number; promise: Promise<ArchiveRead> }
const cache = new Map<string, CacheEntry>()

function finiteEpoch(x: unknown): number | null {
  if (typeof x === 'number' && Number.isFinite(x) && x > 0) return x
  return null
}

async function readIndexDir(dir: string): Promise<ArchiveRead> {
  let ids: string[]
  try {
    ids = (await readdir(dir)).filter((f) => !f.startsWith('.'))
  } catch (err) {
    // Hard listing failure: resolved uncached (readArchiveIndex drops the entry).
    return { index: null, reason: `ticket store unreadable: ${dir}: ${String(err instanceof Error ? err.message : err)}` }
  }
  const metas = new Map<string, ArchiveRowMeta>()
  const unreadable: string[] = []
  for (const id of ids) {
    let doc: any
    try {
      doc = JSON.parse(await readFile(join(dir, id, 'archive.json'), 'utf8'))
    } catch {
      unreadable.push(id)   // missing or malformed archive: named absence, never a throw
      continue
    }
    const meta = (doc && typeof doc === 'object' && doc.meta && typeof doc.meta === 'object') ? doc.meta : {}
    const wf = meta.workflow_id
    const lv = meta.lane_version
    metas.set(id, {
      created: finiteEpoch(meta.created),
      workflow: typeof wf === 'string' ? wf : '',
      laneVersion: typeof lv === 'string' ? lv : '',
      updated: finiteEpoch(meta.updated),
    })
  }
  return { index: { metas, unreadable }, reason: '' }
}

/** Read the project's ticket-store index (TTL-cached, single-flight). Never
 *  throws; a disabled/failed read comes back as `{index: null, reason}` and is
 *  not cached past itself. */
export async function readArchiveIndex(projectKey: string): Promise<ArchiveRead> {
  const d = resolveTicketsDir(projectKey)
  if (!d.enabled) return { index: null, reason: d.reason ?? 'ticket store disabled' }
  const key = d.dir
  const hit = cache.get(key)
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise
  const entry: CacheEntry = { at: Date.now(), promise: readIndexDir(key) }
  cache.set(key, entry)
  const r = await entry.promise
  if (r.index === null) cache.delete(key)   // a failed listing is never cached as good
  return r
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** Engine row shape for `updated` ('%m-%d %H:%M', local time of the reader). */
function formatUpdated(epochSec: number): string {
  const d = new Date(epochSec * 1000)
  return `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** Fill a row's EMPTY fields from one archive meta (verbatim data; nothing is
 *  invented — an empty archive field leaves the row field empty). Returns true
 *  when at least one field was filled. Existing row keys only: no new
 *  top-level row keys (engine row-keyset-parity contracts stay intact). */
export function backfillRowFromArchive(row: any, meta: ArchiveRowMeta): boolean {
  if (!row || typeof row !== 'object' || !meta || typeof meta !== 'object') return false
  let filled = false
  if ((row.workflow === undefined || row.workflow === null || row.workflow === '') && meta.workflow !== '') {
    row.workflow = meta.workflow
    filled = true
  }
  if ((row.created === undefined || row.created === null) && meta.created !== null) {
    row.created = meta.created
    filled = true
  }
  if ((row.lane_version === undefined || row.lane_version === null || row.lane_version === '') && meta.laneVersion !== '') {
    row.lane_version = meta.laneVersion
    filled = true
  }
  if ((row.updated_ts === undefined || row.updated_ts === null || row.updated_ts === 0) && meta.updated !== null) {
    row.updated_ts = meta.updated
    row.updated = formatUpdated(meta.updated)
    filled = true
  }
  return filled
}

/** Backfill a row batch from the index; returns the number of rows changed. */
export function backfillRowsFromArchive(rows: any[], index: ArchiveIndex): number {
  let n = 0
  for (const row of rows) {
    const meta = index.metas.get(String(row?.id ?? ''))
    if (meta && backfillRowFromArchive(row, meta)) n++
  }
  return n
}

/** Test-only cache reset (a test process may outlive a TTL). */
export function resetArchiveCacheForTests(): void {
  cache.clear()
}
