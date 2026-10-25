/**
 * certification-queue — the round-queue request record face (t261025-12,
 * ruling §5 "the recorded request must name who asked and when").
 *
 * The queue route (api.ts is the HTTP shell) queues the next certification
 * round through the ENGINE'S OWN seam — the `line-round-force` marker the
 * scan tick consumes (develop_certify FORCE_MARKER_NAME; the same marker the
 * ops face drops). This module owns the panel-side ACCOUNT of that act:
 *
 *   <projects_root>/<key>/certification/queue-records.jsonl
 *
 * one attributed row per queuing act (at, by='host' — named by the credential,
 * by_claimed + writer_mismatch when a caller claims otherwise, project,
 * marker path). Borrowed-surface dispositions (the inspection-triggers
 * pattern, each carried deliberately):
 *  - idempotency is the MARKER's existence, not the record's: the marker
 *    write uses exclusive create ('wx'), so two concurrent clicks race on
 *    the filesystem and the loser reads already_queued — two clicks cannot
 *    queue two rounds.
 *  - append is a whole-file rewrite tmp->rename (never a torn line); read
 *    counts malformed rows instead of silently dropping them.
 *  - the marker's path comes from the adapter's queue-state receipt (the
 *    engine's own path rule) — this module never re-derives it.
 */

import { join } from 'node:path'
import * as fs from 'node:fs'
import { concurrencyProjectsRoot } from './concurrency.ts'

/** The queue-request record file (beside the project's ledger, in the
 *  project's own account directory — same family as the trigger records). */
export function certQueueRecordsPath(env: NodeJS.ProcessEnv, key: string): string {
  return join(concurrencyProjectsRoot(env), key, 'certification', 'queue-records.jsonl')
}

/** Display cap, declared once (t261004-14 discipline): never an inlined number. */
export const CERT_QUEUE_RECORDS_CAP = 20

export interface CertQueueIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
  /** Whole-file atomic rewrite (tmp->rename inside; injectable for tests). */
  writeFileAtomic(file: string, content: string): void
  /** Exclusive marker create ('wx'): succeeds once, refuses with
   *  reason='already_queued' when the marker exists. Injectable for tests. */
  writeMarkerExclusive(file: string, content: string): void
  mkdirSync(dir: string): void
}

export const fsCertQueueIo: CertQueueIo = {
  existsSync: (f) => fs.existsSync(f),
  readFileSync: (f) => fs.readFileSync(f, 'utf-8'),
  writeFileAtomic: (file, content) => {
    fs.mkdirSync(join(file, '..'), { recursive: true })
    const tmp = `${file}.tmp-${process.pid}-${Date.now()}`
    fs.writeFileSync(tmp, content)
    try {
      fs.renameSync(tmp, file)
    } catch (err) {
      try { fs.unlinkSync(tmp) } catch { /* never mask the original error */ }
      throw err
    }
  },
  writeMarkerExclusive: (file, content) => {
    fs.mkdirSync(join(file, '..'), { recursive: true })
    // 'wx' = atomic exclusive create: the idempotency race is settled by the
    // filesystem, not by a check-then-write window.
    fs.writeFileSync(file, content, { flag: 'wx' })
  },
  mkdirSync: (dir) => fs.mkdirSync(dir, { recursive: true }),
}

export type CertQueueRecordsRead =
  | { ok: true; source: string; rows: Array<Record<string, unknown>>; malformed_rows: number }
  | { ok: false; source: string; reason: string }

export function readCertQueueRecords(io: CertQueueIo, env: NodeJS.ProcessEnv, key: string): CertQueueRecordsRead {
  const file = certQueueRecordsPath(env, key)
  if (!io.existsSync(file)) {
    return { ok: false, source: file, reason: 'the project has no queue-request record file yet' }
  }
  let raw = ''
  try {
    raw = io.readFileSync(file)
  } catch (e) {
    return { ok: false, source: file, reason: 'queue-request records unreadable: ' + (e instanceof Error ? e.message : String(e)) }
  }
  const rows: Array<Record<string, unknown>> = []
  let malformed = 0
  for (const ln of raw.split('\n')) {
    const s = ln.trim()
    if (!s) continue
    try {
      const obj = JSON.parse(s)
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) rows.push(obj as Record<string, unknown>)
      else malformed++
    } catch {
      malformed++
    }
  }
  rows.sort((a, b) => String(b.at ?? '').localeCompare(String(a.at ?? '')))
  return { ok: true, source: file, rows: rows.slice(0, CERT_QUEUE_RECORDS_CAP), malformed_rows: malformed }
}

export function appendCertQueueRecord(io: CertQueueIo, env: NodeJS.ProcessEnv, key: string, record: Record<string, unknown>): { ok: true; file: string } | { ok: false; error: string } {
  const file = certQueueRecordsPath(env, key)
  let prior = ''
  try {
    if (io.existsSync(file)) prior = io.readFileSync(file)
    if (prior && !prior.endsWith('\n')) prior += '\n'
  } catch (e) {
    return { ok: false, error: 'queue-record read failed before append: ' + (e instanceof Error ? e.message : String(e)) }
  }
  const line = JSON.stringify(record, (_, v) => typeof v === 'bigint' ? String(v) : v)
  try {
    io.writeFileAtomic(file, prior + line + '\n')
  } catch (e) {
    return { ok: false, error: 'queue-record append failed: ' + (e instanceof Error ? e.message : String(e)) }
  }
  return { ok: true, file }
}
