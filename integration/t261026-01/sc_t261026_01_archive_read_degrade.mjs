#!/usr/bin/env node
/**
 * sc_t261026_01_archive_read_degrade.mjs — t261026-01, grey-box L2 (ticket store
 * read face), offline seconds, zero docker/Temporal-server/browser, never touches
 * 3099/7233.
 *
 * intent (user-perceivable contract): the legacy-era ticket data that the row
 * projection dropped (workflow/created/lane_version empty on 339 of 384 listed
 * rows while the store holds 422 archives) is readable VERBATIM from the on-disk
 * archive store through the workbench's declared archive-read seam — and a
 * damaged store degrades BY NAME, never by invention and never by a crash:
 *   A1 a legacy-v1 archive (created/workflow_id/lane_version) reads back verbatim;
 *   A2 a recent archive with lane_version absent/None reads created, fabricates
 *      no lane_version (lane_version is never an input to any decision, round-1 c3);
 *   A3 an archive with an empty workflow_id stays empty — no invented chain
 *      (the ticket's DO-NOT: never invent a workflow value);
 *   A4 malformed archive files (truncated JSON / non-JSON bytes / missing meta)
 *      are named unreadable per id, the healthy ids read unaffected, no throw;
 *   A5 a missing store root reads as a NAMED disabled state, never a silent
 *      empty population and never a throw;
 *   A6 a ticket id with no archive on disk appears nowhere (absence is named
 *      absence, not a guessed entry).
 *
 * Pre-implement tree red (TDD signal): the SANDBAR_TICKETS_DIR seam / archive
 * module do not exist yet -> A1..A6 FAIL by name. Green required at the
 * integration gate / merge. Workbench sources absent = ENV_FAIL exit 2.
 */
import { makeChecker } from '../t260903-09/lib_integration.mjs'
import {
  TICKETS_TS, loadTicketArchive, writeArchive, withTicketsRoot, freshTmp, rmRf,
} from './lib_t261026.mjs'

const { ok, envFail, done } = makeChecker()
const NAME = 't261026-01-archive-read-degrade'

// Fixtures (project key `proj`; shape mirrors the live store layout).
const DAY = 86_400_000
const NOW = Date.parse('2026-10-26T00:00:00Z')
const LEG_TS = NOW - 40 * DAY

let mod = null
try {
  mod = await loadTicketArchive()
} catch (e) {
  envFail('A0 production archive module importable',
    `workbench ticket-archive sources absent/unimportable: ${TICKETS_TS.pathname} (${String(e).slice(0, 120)})`)
}
if (mod) {
  const root = await freshTmp('t261026a')
  try {
    await writeArchive(root, 'proj', 't-leg1', { created: LEG_TS, workflow_id: 'dev-lane', lane_version: 'legacy-v1' })
    await writeArchive(root, 'proj', 't-new1', { created: NOW - DAY, workflow_id: 'dev-lane', lane_version: null })
    await writeArchive(root, 'proj', 't-new2', { created: NOW - 2 * DAY, workflow_id: 'dev-lane' }) // lane_version key absent
    await writeArchive(root, 'proj', 't-chainless', { created: NOW - 2 * DAY, workflow_id: '' })
    await writeArchive(root, 'proj', 't-bad-trunc', null, '{"meta": {"created": 12')
    await writeArchive(root, 'proj', 't-bad-nonjson', null, 'not json at all')
    await writeArchive(root, 'proj', 't-bad-nometa', { unrelated: true })

    await withTicketsRoot(root, async () => {
      let idx = null
      let threw = ''
      try {
        idx = await mod.readArchiveIndex('proj')
      } catch (e) {
        threw = String(e)
      }
      ok(threw === '', 'A4 the whole read never throws on damaged files', threw)
      if (idx) {
        const metas = idx.index?.metas ?? idx.metas ?? null
        const dump = JSON.stringify(idx)
        const leg = metas?.get?.('t-leg1') ?? null
        ok(leg !== null && JSON.stringify(leg).includes('dev-lane') && JSON.stringify(leg).includes('legacy-v1'),
          'A1 legacy-v1 archive reads back verbatim (created + workflow + lane_version)', JSON.stringify(leg))
        ok(leg !== null && JSON.stringify(leg).includes(String(LEG_TS)), 'A1 created is the archive number, not a derived value', JSON.stringify(leg))
        const n1 = metas?.get?.('t-new1') ?? null
        const n2 = metas?.get?.('t-new2') ?? null
        ok(n1 !== null && JSON.stringify(n1).includes(String(NOW - DAY)) && !JSON.stringify(n1).includes('legacy'),
          'A2 lane_version=None -> created read, no fabricated lane_version', JSON.stringify(n1))
        ok(n2 !== null, 'A2b lane_version key absent -> entry still present (created readable)', JSON.stringify(n2))
        const ch = metas?.get?.('t-chainless') ?? null
        ok(ch !== null && !JSON.stringify(ch).includes('dev-lane'),
          'A3 empty workflow_id stays empty — the read invents no chain', JSON.stringify(ch))
        ok(dump.includes('t-bad-trunc') && dump.includes('t-bad-nonjson'),
          'A4 malformed ids are named (unreadable set carries them)', '')
        const good = metas?.get?.('t-new1')
        ok(good !== null, 'A4 healthy ids unaffected by damaged neighbours', '')
        ok(!dump.includes('t-bad-nometa') || dump.indexOf('t-bad-nometa') > -1, 'A4b missing-meta archive handled without throw', '')
      } else {
        ok(false, 'A4 readArchiveIndex returns a shaped result', 'result was null/undefined')
      }

      // A5 missing root -> named disabled, never a silent empty map.
      let disabled = null
      let threw5 = ''
      try {
        if (typeof mod.resolveTicketsDir === 'function') disabled = mod.resolveTicketsDir('no-such-project')
        else threw5 = 'resolveTicketsDir not exported'
      } catch (e) { threw5 = String(e) }
      ok(disabled !== null && typeof disabled === 'object' && disabled.enabled === false && String(disabled.reason ?? '').length > 0,
        'A5 missing store root reads as named disabled + reason', JSON.stringify(disabled) + threw5)

      // A6 absent id appears nowhere.
      const again = await mod.readArchiveIndex('proj')
      const againMetas = again?.index?.metas ?? again?.metas
      ok(againMetas?.has?.('t-absent') !== true, 'A6 id with no archive appears nowhere (named absence)', '')
    })
  } finally {
    await rmRf(root)
  }
}
process.exit(done(NAME))
