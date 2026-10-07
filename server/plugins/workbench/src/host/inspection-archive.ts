/**
 * inspection-archive — read-only model + reader for the inspection period archive
 * (t261006-15, plan D1/D2).
 *
 * Computation core of GET /sandbar-workbench/api/wf/inspection-archive?project=<key>.
 * Why the latest-scan endpoint is not enough (P5 record): scan-report serves only the
 * newest dispatcher scan report (server/engine/out/scan/<date>.json) — no period list,
 * no per-instance reports, no missing/merge semantics. The inspection period archive is
 * a different source: out/inspection/inspection-<instance>-<period>.json, written by
 * engine inspection_flow.write_inspection_report_impl.
 *
 * Period order and merge semantics (261004 host rulings §8-1 / §7, verbatim):
 *  - Period order is EXPLICITLY newest first: a numeric descending compare on the
 *    YYYYMMDD key — never a data source iteration order (the mock shipped the bug where
 *    numeric-looking object keys enumerate ascending in JS, putting the oldest first).
 *  - Which periods exist is decided by the archive: only archived periods become items;
 *    no date arithmetic, no placeholder generation.
 *  - "Adjacent means consecutive": merging is judged by adjacency in this declared
 *    sorted sequence only — consecutive report-less periods merge into one item (span +
 *    count label, per-period causes kept inside); report-less periods separated by a
 *    period WITH a report stay separate. A calendar gap alone creates neither an item
 *    nor a merge.
 *  - A single report-less period stays its own item, explicitly "not available" — never
 *    a silent blank.
 *
 * Failure face (fail-closed, after scan-report.ts / inspection-report.ts precedents):
 *  - absent directory -> ok:false + human reason (no inspection has run; not a 5xx);
 *  - filename whitelist inspection-<instance>-<YYYYMMDD>.json (instance shape = the
 *    project key whitelist family);
 *  - a file over 256 KB is not parsed (truncated text can break mid-JSON); the slot
 *    carries a per-file reason; parse failure same — the file contributes "present but
 *    unreadable" to the period list, never report content;
 *  - whitelist-external files are counted (hidden), never read.
 * Resource terminal state: pure readdir/readFile/stat, no handles, no timers; every
 * path terminates naturally.
 */

import { readdir, readFile, stat } from 'node:fs/promises'
import { join } from 'node:path'

/** Period key shape (YYYYMMDD; same shape as the engine period_key). */
export const PERIOD_RE = /^\d{8}$/
/** Archive filename whitelist: inspection-<instance>-<YYYYMMDD>.json. */
export const ARCHIVE_FILE_RE = /^inspection-([a-z0-9][a-z0-9-]{0,40})-(\d{8})\.json$/
/** Per-report byte cap: an over-cap file is not JSON.parsed. */
export const ARCHIVE_MAX_BYTES = 256 * 1024

export interface ArchiveEntry {
  instance: string
  period: string
  file: string
}

/** One instance report inside one period: ok = parsed report; fail = human reason. */
export type ReportSlot =
  | { ok: true; file: string; report: unknown }
  | { ok: false; file: string; reason: string }

export interface PeriodEntry {
  period: string
  reports: Record<string, ReportSlot>
  /** At least one report in this period read out (drives no-report merging). */
  any_report: boolean
}

/** An item of the browser's period row: a normal period / a merged no-report run. */
export type ArchiveItem =
  | { kind: 'period'; period: string; any_report: boolean }
  | { kind: 'no-report-run'; label: string; count: number; periods: PeriodEntry[] }

export type ArchiveRead =
  | {
      ok: true
      dir: string
      instances: string[]
      periods: PeriodEntry[]
      items: ArchiveItem[]
      /** Whitelist-matched files that could not be read/parsed (visible, never silent). */
      unreadable_files: number
      /** Whitelist-external files counted, never read. */
      hidden_files: number
      reason: ''
    }
  | { ok: false; dir: string; reason: string }

/** Explicit descending numeric sort of YYYYMMDD keys. Single point for the ordering
 *  discipline — callers must not sort on their own. */
export function sortPeriodsDesc(periods: string[]): string[] {
  return [...periods].sort((a, b) => Number(b) - Number(a))
}

/**
 * Merge semantics (pure function, unit-tested directly): input is a sequence ALREADY
 * sorted by the explicit descending order; output is the period-row items — consecutive
 * any_report=false entries merge into one no-report-run (label `<newest>–<oldest> · N
 * without a report`; per-period data stays in periods). A single no-report period keeps
 * its own item (callers render the single form when count === 1).
 */
export function buildArchiveItems(periods: PeriodEntry[]): ArchiveItem[] {
  const items: ArchiveItem[] = []
  let run: PeriodEntry[] = []
  const flush = () => {
    if (run.length === 0) return
    items.push({
      kind: 'no-report-run',
      label: run.length === 1
        ? `${run[0].period} · (no report)`
        : `${run[0].period}–${run[run.length - 1].period} · ${run.length} without a report`,
      count: run.length,
      periods: run,
    })
    run = []
  }
  for (const p of periods) {
    if (p.any_report) {
      flush()
      items.push({ kind: 'period', period: p.period, any_report: true })
    } else {
      run.push(p)
    }
  }
  flush()
  return items
}

/**
 * Archive reader: readdir -> whitelist -> try-read+parse per file (over-cap / bad JSON
 * = a fail-closed slot reason) -> period entries -> explicit descending order -> merge.
 * An absent directory = ok:false (nothing has run yet).
 */
export async function readInspectionArchive(dir: string): Promise<ArchiveRead> {
  let names: string[]
  try {
    names = await readdir(dir)
  } catch {
    return { ok: false, dir, reason: 'inspection archive directory does not exist (no inspection has run for this project yet)' }
  }
  const entries: ArchiveEntry[] = []
  let hidden = 0
  for (const n of names) {
    const m = ARCHIVE_FILE_RE.exec(n)
    if (!m) { hidden += 1; continue }
    entries.push({ instance: m[1], period: m[2], file: join(dir, n) })
  }
  if (entries.length === 0) {
    return { ok: false, dir, reason: 'no inspection report in the archive (whitelist inspection-<instance>-<YYYYMMDD>.json matched nothing)' }
  }

  const instances = [...new Set(entries.map((e) => e.instance))].sort()
  const byPeriod = new Map<string, Record<string, ReportSlot>>()
  let unreadable = 0
  for (const e of entries) {
    const slot: ReportSlot = { ok: false, file: e.file, reason: '' }
    try {
      const st = await stat(e.file)
      if (st.size > ARCHIVE_MAX_BYTES) {
        slot.reason = `report file is ${st.size} bytes (over the ${ARCHIVE_MAX_BYTES} read cap) — not parsed`
      } else {
        slot.report = JSON.parse(await readFile(e.file, 'utf8'))
        slot.ok = true
      }
    } catch (err) {
      slot.reason = `report file unreadable or not JSON: ${err instanceof Error ? err.message : String(err)}`
    }
    if (!slot.ok) unreadable += 1
    const rec = byPeriod.get(e.period) ?? {}
    // Same instance + same period should not collide (the writer overwrites by name);
    // if it ever does, the later read wins and the slot stays single.
    rec[e.instance] = slot
    byPeriod.set(e.period, rec)
  }

  const periods: PeriodEntry[] = sortPeriodsDesc([...byPeriod.keys()]).map((p) => {
    const reports = byPeriod.get(p) as Record<string, ReportSlot>
    const anyReport = Object.values(reports).some((s) => s.ok)
    return { period: p, reports, any_report: anyReport }
  })
  return {
    ok: true, dir, instances, periods, items: buildArchiveItems(periods),
    unreadable_files: unreadable, hidden_files: hidden, reason: '',
  }
}

/** Single period+instance report fetch (a period-row click drills into one card):
 *  both parts whitelisted before readFile; fail-closed. */
export async function readPeriodReport(
  dir: string, instance: string, period: string,
): Promise<{ ok: true; file: string; report: unknown } | { ok: false; reason: string }> {
  if (!PERIOD_RE.test(period)) {
    return { ok: false, reason: `period shape is invalid: '${period}' (need YYYYMMDD)` }
  }
  if (!ARCHIVE_FILE_RE.test(`inspection-${instance}-${period}.json`)) {
    return { ok: false, reason: `instance shape is invalid: '${instance}'` }
  }
  const file = join(dir, `inspection-${instance}-${period}.json`)
  try {
    const st = await stat(file)
    if (st.size > ARCHIVE_MAX_BYTES) {
      return { ok: false, reason: `report file is ${st.size} bytes (over the ${ARCHIVE_MAX_BYTES} read cap) — not parsed` }
    }
    return { ok: true, file, report: JSON.parse(await readFile(file, 'utf8')) }
  } catch (err) {
    return { ok: false, reason: `report not available for this period: ${err instanceof Error ? err.message : String(err)}` }
  }
}
