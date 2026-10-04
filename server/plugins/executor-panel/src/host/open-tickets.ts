/**
 * open-tickets.ts — the t261004-19 "Open tickets in these epics" read face
 * (host-only).
 *
 * What it is: the read half of the new Grants-page section — it lists EVERY epic in
 * notes/epics/*.md (code + the status line as written + whether it is on the
 * declaration's open_ticket_epics list today); the write half (the per-epic switches)
 * goes through the existing audited saveGrantsDecl path (this module never writes).
 *
 * The judgment reads the declaration, not the epic prose (the epic file format is
 * unchanged and stays prose for people) — the engine judgment lives in
 * server/engine/executor_grants.py; this module only answers "what does the panel
 * show".
 *
 * Directory anchor (same chain as the engine's shared.resolve_epics_dir): env
 * SANDBAR_EPICS_DIR wins, else the project registry entry's primary directory
 * (server/project-registry.ts dirs[0]) / notes/epics. An unreadable registry / an
 * entry without a primary directory = an explicit degraded object (reason named),
 * never rendered as a fake "no epics".
 */

import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { findProject, primaryDir } from '../../../../project-registry.ts'
import { readDeclaration } from './executor-grants.ts'

export interface OpenTicketEpicRow {
  code: string
  /** The status line as written (the value of the field table's status row, verbatim; '' when the row is missing). */
  status: string
  /** Whether it is authorized right now (on the declaration's open_ticket_epics list). */
  authorized: boolean
}

export type OpenTicketEpicsRead =
  | { ok: true; dir: string; epics: OpenTicketEpicRow[] }
  | { ok: false; reason: string }

/** The verbatim value of a field in the field table (| field | value |); '' when the row is missing (tolerant, never refuses). */
function statusLineOf(markdown: string): string {
  // The field-table key is Chinese in the epic files by design (data, not copy), so
  // the key is spelled with unicode escapes here to keep this source ASCII.
  const m = /^\|\s*\u72b6\u6001\s*\|\s*([^|]*?)\s*\|/m.exec(markdown)
  return m ? m[1] : ''
}

/** Resolve the epic directory (same chain as the engine's shared.resolve_epics_dir; unresolvable = explicit degradation). */
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
  return { ok: true, dir: join(root, 'notes', 'epics') }
}

/** List the epic rows (read-only; a missing/empty directory = an empty array, not an error; a single unreadable file is skipped and never drags the whole list down). */
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
  for (const name of names) {
    let markdown = ''
    try {
      markdown = readFileSync(join(anchor.dir, name), 'utf8')
    } catch {
      continue // a single unreadable file is skipped (same discipline as workbench listEpics)
    }
    const code = name.replace(/\.md$/, '')
    epics.push({ code, status: statusLineOf(markdown), authorized: authorized.has(code) })
  }
  return { ok: true, dir: anchor.dir, epics }
}
