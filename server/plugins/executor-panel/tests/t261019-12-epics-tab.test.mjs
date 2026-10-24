/**
 * t261019-12: the Epics tab is the host-approved mock (out/mocks/epics-tab-261019.html)
 * over the moved docs/epics registry with the single retired boolean.
 *
 * Contract pinned here (source-text + fixture-corpus legs, the house style of
 * t261019-05-docs-envelope.test.mjs — the page is ES5-flavoured inline JS, so the
 * assertions read the served source):
 *   - the badge is the retired boolean ONLY ('online' / 'retired'), fail-closed on
 *     a defective registry row;
 *   - the summary is the only document prose on the surface (no title/status/note,
 *     no notes/epics path anywhere in the page);
 *   - the merged list sorts newest-activity-first; a row expands IN PLACE (no
 *     separate detail page) to started date, the three counts, the document link,
 *     the newest five tickets and a 'Show N more' fold;
 *   - the workbench API half (node.ts) serves code+retired+summary+started from
 *     docs/epics, fails closed on a malformed doc, names a missing registry dir,
 *     and its close/status write routes are dead; both parsers consume the SAME
 *     fixture corpus as the engine pytest (no drift on what counts as fail-closed).
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const REPO = join(fileURLToPath(import.meta.url), '..', '..', '..', '..', '..')
const PAGE = readFileSync(join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts'), 'utf8')
const NODE = readFileSync(join(REPO, 'server/plugins/workbench/node.ts'), 'utf8')
const CORPUS_DIR = join(REPO, 'server/engine/tests/fixtures/epic_registry_t261019')

let fails = 0
const ok = (cond, name, detail = '') => {
  if (cond) { console.log('ok   ' + name); return }
  fails += 1; console.log('FAIL ' + name + (detail ? ' — ' + detail : ''))
}

// ---- the page: badge = the retired boolean, fail-closed ----
ok(/e\.retired===false && !e\.defect/.test(PAGE), 'badge reads retired===false (and only a non-defective row) as online')
ok(PAGE.includes('>online</span>') && PAGE.includes('>retired</span>'), 'the two badge words are online/retired (no status vocabulary)')
ok(PAGE.includes('Defective registry entry'), 'a defective registry row renders the named defect face, fail-closed')

// ---- the page: summary is the only prose ----
ok(PAGE.includes("typeof e.summary==='string'"), 'the summary comes from the front-matter summary field')
// t261024-21: locate the Epics-tab renderer by its tab wiring, not by the first
// name match of 'function renderEpics' — a same-name twin declared later used to
// shadow it, and a first-match slice happily measured the WRONG function.
const EPIC_BLOCK = (() => {
  const body = PAGE.indexOf("var list=el('epicsList')")
  if (body < 0) return ''
  const head = PAGE.lastIndexOf('function ', body)
  return PAGE.slice(head, PAGE.indexOf('function openTicketInHost'))
})()
ok(EPIC_BLOCK.includes("el('epicsList')"), 'the slice anchors on the Epics-tab renderer (tab wiring, not the first name match)')
ok(!/e\.title|meta\.status|meta\.note|\.status\|\|/.test(EPIC_BLOCK), 'the old title/status/note face is gone from the epic renderers')
ok(!PAGE.includes('notes/epics'), 'no notes/epics path remains in the page')
ok(PAGE.includes('docs/epics/'), 'the document link names docs/epics/')

// ---- the page: the approved mock layout ----
ok(/epicLastActivity\(epicCodeOf\(b\)\)-epicLastActivity\(epicCodeOf\(a\)\)/.test(PAGE), 'the merged list sorts newest-activity-first')
ok(PAGE.includes('newest activity first'), 'the bar names the sort like the mock')
ok(/Math\.min\(5,\s*rows\.length\)/.test(PAGE), 'exactly the newest five tickets before the fold')
ok(PAGE.includes("Show '+(rows.length-shown)+' more tickets"), "the 'Show N more' fold is present")
ok(PAGE.includes('in flight <b>') && PAGE.includes('waiting on you <b>') && PAGE.includes('landed today <b>'), 'the three expanded counts render with the mock wording')
ok(PAGE.includes('started <b>'), 'the expanded face carries the started date')
ok(!PAGE.includes('renderEpicDetail'), 'no separate detail page (the row IS the epic)')
ok(/state\.epicOpen\s*=\s*state\.epicOpen===n\.dataset\.epicHead\s*\?\s*''/.test(PAGE), 'a head click expands the row in place (toggle, no navigation)')

// ---- the workbench API half (node.ts) ----
ok(/anchorEnv\(anchor,\s*'SANDBAR_EPICS_DIR'\)/.test(NODE) && /return env \?\? join\(anchor\.root,\s*'docs',\s*'epics'\)/.test(NODE),
   'node.ts resolves docs/epics (env override wins; no notes/epics fallback)')
ok(NODE.includes('epic registry directory not found'), 'a missing registry dir is a named error, never an empty 200')
ok(/retired:\s*true,\s*summary:\s*''/.test(NODE), 'a malformed doc fails closed to a defect row (retired:true)')
ok(NODE.includes('must be exactly') && /retired/.test(NODE), 'a non-boolean retired value is named, not accepted')
ok(/import \{ isEvidenceFileName \} from '\.\/src\/host\/epics\.ts'/.test(NODE), 'only the evidence whitelist is imported from the retired epics.ts module')
ok(/const EPIC_CODE_RE = \/\^\[a-z0-9\]\[a-z0-9-\]\{0,40\}\$\//.test(NODE),
   'EPIC_CODE_RE is DEFINED in node.ts (self-contained mirror — a use without a definition was the gate round-1 ReferenceError)')
ok(NODE.includes("parts[1] === 'close' || parts[1] === 'status'") && NODE.includes('410'), 'the close/status write routes answer a named dead 4xx')
ok(/path:\s*`docs\/epics\/\$\{code\}\.md`/.test(NODE), 'the detail face names the docs/epics path')
const LIVE_NODE = NODE.split('\n').filter((l) => !(l.includes('notes/epics') && l.includes('t261019-12'))).join('\n')
ok(!/notes\/epics/.test(LIVE_NODE), 'no live notes/epics reference remains in node.ts (retirement notes aside)')

// ---- one shared fixture corpus (both parsers, no drift) ----
const online = readFileSync(join(CORPUS_DIR, 'online.md'), 'utf8')
const malformed = readFileSync(join(CORPUS_DIR, 'malformed.md'), 'utf8')
ok(online.startsWith('---\ncode: epic-online\nretired: false\n'), 'corpus online doc carries healthy front-matter')
ok(!malformed.includes('---'), 'corpus malformed doc has no front-matter block (the fail-closed leg)')
ok(NODE.includes('epic_registry_t261019') || readFileSync(join(REPO, 'server/engine/tests/test_t261019_12_epic_registry.py'), 'utf8').includes('epic_registry_t261019'),
   'the corpus is declared next to the engine test that pins the python parser')

console.log(fails === 0 ? 'done 1' : 'done 0')
process.exit(fails === 0 ? 0 : 1)
