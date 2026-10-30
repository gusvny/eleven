/**
 * open-tickets.ts — the t261004-19 "Open tickets in these epics" read face
 * (host-only).
 *
 * What it is: the read half of the Grants-page section — it lists every epic in the
 * epic registry (code + status line + whether it is on the declaration's
 * open_ticket_epics list today); the write half (the per-epic switches) goes through
 * the existing audited saveGrantsDecl path (this module never writes).
 *
 * The judgment reads the declaration, not the epic prose — the engine judgment lives in
 * server/engine/executor_grants.py; this module only answers "what does the panel
 * show".
 *
 * Directory anchor (t261030-30: one rule with the engine's shared.resolve_epics_dir and
 * with project-anchor.ts anchorEpicsDir): env SANDBAR_EPICS_DIR when it is set and
 * non-empty, else the project registry entry's primary directory
 * (server/project-registry.ts dirs[0]) / docs/epics. The store moved from notes/epics to
 * docs/epics in t261019-12 (hard cut) — this face never falls back to notes/epics.
 * An unreadable registry / an entry without a primary directory = an explicit degraded
 * object (reason named), never rendered as a fake "no epics".
 *
 * Row model (t261030-30): one row shape for every console epic reader —
 * src/host/epics.ts epicRecord (front-matter code / retired / summary, with the legacy
 * field table as a fallback). A row whose record cannot be read carries a named reason
 * and a non-empty status, so it never renders as a healthy row with a blank status.
 */

import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { findProject, primaryDir } from '../../../../project-registry.ts'
import { EPIC_CODE_RE, epicRecord } from '../../../workbench/src/host/epics.ts'
import { readDeclaration } from './executor-grants.ts'

export interface OpenTicketEpicRow {
  code: string
  /** The status line of the row. Never empty: 'open' / 'retired' from the front-matter,
   *  the legacy field-table value, or 'unknown' when nothing readable exists. */
  status: string
  /** The front-matter summary ('' when absent). */
  summary: string
  /** true/false from the front-matter; null when the code has no readable record. */
  retired: boolean | null
  /** Whether it is authorized right now (on the declaration's open_ticket_epics list). */
  authorized: boolean
  /** Whether the registry holds a document for this code. */
  in_registry: boolean
  /** Named reason when the row is not a healthy registry record ('' when healthy). */
  reason: string
}

export type OpenTicketEpicsRead =
  | { ok: true; dir: string; epics: OpenTicketEpicRow[] }
  | { ok: false; reason: string }

/** Resolve the epic directory (the engine rule: env when set and non-empty, else the
 *  project root's docs/epics; unresolvable = explicit degradation). */
export function resolveOpenTicketEpicsDir(key: string, env: NodeJS.ProcessEnv = process.env):
  { ok: true; dir: string } | { ok: false; reason: string } {
  // Double env read: when the caller's env object (the face api/harness builds
  // explicitly) lacks the key, fall back to process.env (production node.ts passes
  // process.env; the harness builds a narrow env without the epic key — the double
  // read keeps the SANDBAR_EPICS_DIR priority identical on both faces, so the
  // injection-face shape cannot silently break it).
  const envDir = env.SANDBAR_EPICS_DIR ?? process.env.SANDBAR_EPICS_DIR
  if (typeof envDir === 'string' && envDir.trim() !== '') return { ok: true, dir: envDir }
  const k = String(key ?? '').trim()
  if (!k) return { ok: false, reason: 'no project key — the epics directory cannot be resolved' }
  let p
  try {
    p = findProject(k)
  } catch (e) {
    return { ok: false, reason: 'the project registry entry cannot be loaded: ' + (e instanceof Error ? e.message : String(e)) }
  }
  if (p === undefined) return { ok: false, reason: `unknown project key '${k}' (not in projects.yaml) — no epic list can be read` }
  const root = primaryDir(p)
  if (typeof root !== 'string' || root === '') {
    return { ok: false, reason: `project '${k}' has no primary directory in the registry — no epic list can be read` }
  }
  return { ok: true, dir: join(root, 'docs', 'epics') }
}

/**
 * List the epic rows (read-only). A missing/empty directory answers an empty array,
 * not an error; a single unreadable file is skipped and never drags the whole list
 * down.
 *
 * A code that is authorized on the declaration but has no document in the registry is
 * still a row (t261030-30, A4): the panel renders it with its switch on, so the next
 * save keeps the authorization instead of silently dropping it.
 */
export function listOpenTicketEpics(key: string, env: NodeJS.ProcessEnv = process.env): OpenTicketEpicsRead {
  const anchor = resolveOpenTicketEpicsDir(key, env)
  if (!anchor.ok) return anchor
  let names: string[] = []
  try {
    names = readdirSync(anchor.dir).filter((n) => n.endsWith('.md')).sort()
  } catch {
    return { ok: true, dir: anchor.dir, epics: [] } // directory absent = this project has no epic yet
  }
  const decl = readDeclaration(key, env)
  const authorized = new Set<string>(decl.ok ? (decl.declaration?.open_ticket_epics ?? []) : [])
  const epics: OpenTicketEpicRow[] = []
  const seen = new Set<string>()
  for (const name of names) {
    const code = name.replace(/\.md$/, '')
    // A name that is not a legal code shape is not a row: the engine refuses that
    // shape, so listing it as an epic would claim a code no ticket can use.
    if (!EPIC_CODE_RE.test(code)) continue
    let markdown = ''
    try {
      markdown = readFileSync(join(anchor.dir, name), 'utf8')
    } catch {
      continue // a single unreadable file is skipped (same discipline as listEpics)
    }
    const rec = epicRecord(code, markdown)
    seen.add(code)
    epics.push({
      code,
      status: rec.status,
      summary: rec.summary,
      retired: rec.retired,
      authorized: authorized.has(code),
      in_registry: true,
      reason: rec.defect ?? '',
    })
  }
  for (const code of [...authorized].sort()) {
    if (seen.has(code) || !EPIC_CODE_RE.test(code)) continue
    epics.push({
      code,
      status: 'unknown',
      summary: '',
      retired: null,
      authorized: true,
      in_registry: false,
      reason: `authorized, but ${join(anchor.dir, code + '.md')} does not exist — the engine refuses this code`,
    })
  }
  epics.sort((a, b) => (a.code < b.code ? -1 : a.code > b.code ? 1 : 0))
  return { ok: true, dir: anchor.dir, epics }
}
