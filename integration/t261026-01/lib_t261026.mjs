/**
 * lib_t261026.mjs — t261026-01 shared fixtures (non sc_ prefix = shared code,
 * not registered, per the run_scenarios.py naming iron rule).
 *
 * Seam discipline (grey-box: anchor to declared public seams, not internals):
 * - archive store seam: SANDBAR_TICKETS_DIR (the ticket's declared test override)
 *   + the on-disk shape <root>/<projectKey>/data/tickets/<id>/archive.json with
 *   meta.created / meta.workflow_id / meta.lane_version — the same ground truth
 *   the live store holds (measured 261025: 422 archives, 293 within 31d).
 * - metrics seam: the shared t260903-09/lib_integration.mjs stub
 *   (SANDBAR_METRICS_STUB / SANDBAR_METRICS_DIR / buildMetricsResponse front door).
 */
import { mkdir, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { freshTmp, rmRf } from '../t260903-09/lib_integration.mjs'

export const TICKETS_TS = new URL('../../server/plugins/workbench/src/host/ticket-archive.ts', import.meta.url)

let ticketsMod = null
export async function loadTicketArchive() {
  if (ticketsMod === null) ticketsMod = await import(TICKETS_TS.href)
  return ticketsMod
}

export { freshTmp, rmRf }

/** Write one archive.json; pass raw (string) for a malformed file body. */
export async function writeArchive(root, projectKey, ticketId, meta, raw) {
  const dir = join(root, projectKey, 'data', 'tickets', ticketId)
  await mkdir(dir, { recursive: true })
  const body = raw ?? JSON.stringify({ id: ticketId, meta })
  await writeFile(join(dir, 'archive.json'), body, 'utf8')
}

/** Scoped env wrapper: SANDBAR_TICKETS_DIR set for fn only, restored after. */
export async function withTicketsRoot(root, fn) {
  const saved = process.env.SANDBAR_TICKETS_DIR
  process.env.SANDBAR_TICKETS_DIR = root
  try {
    return await fn()
  } finally {
    if (saved === undefined) delete process.env.SANDBAR_TICKETS_DIR
    else process.env.SANDBAR_TICKETS_DIR = saved
  }
}
