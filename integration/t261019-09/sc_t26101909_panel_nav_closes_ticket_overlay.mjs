#!/usr/bin/env node
/**
 * sc_t26101909_panel_nav_closes_ticket_overlay — panel navigation closes the host
 * ticket dialog (t261019-09, host report 261019, grey-box L3, offline seconds,
 * zero docker/Temporal/browser, never touches 3099/7233).
 *
 * User-perceivable contract: the middle column is the executor panel iframe plus
 * the console's ticket-detail overlay. Today the panel can ask the console to
 * OPEN things (open-ticket, open-face) but there is NO close message, so when the
 * panel switches its own tab or opens a read face, the ticket dialog stays
 * floating over content the user is no longer looking at, and a Settings face
 * mounts UNDER an open dialog. The fix adds ONE panel-to-console message (close
 * the host overlay) and one console-side branch, wired through the host renderer.
 *
 * Anchoring: the faces the user can actually see or receive — the served panel
 * page's outgoing messages (PANEL_HTML, baked at plugin import and the page the
 * console really serves), the message-order contract at the face buttons, the
 * console branch's public effect (dialog closed, and ONLY that), and the pure
 * gate on the new external input. No internal execution order beyond the
 * post-order the user experience itself depends on (close before open-face).
 *
 * Sub-case statuses: every check is PASS/FAIL; missing product sources are
 * ENV_FAIL exit 2; nothing is SKIP. Pre-implement red on E1-E4 is the named TDD
 * signal; green required at the integration gate / merge.
 */
import { readFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

let PASS = 0, FAIL = 0
const ok = (c, label) => { if (c) { PASS++; console.log('  ok  ' + label) } else { FAIL++; console.log('  FAIL ' + label) } }
const section = (t) => console.log('\n' + t)
const die = (why) => { console.error('ENV_FAIL: ' + why); process.exit(2) }

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const read = (p) => { try { return readFileSync(join(repo, p), 'utf8') } catch (e) { die(p + ' unreadable: ' + e.message) } }

const CLOSE_TYPE = 'sandbar-executor-panel:close-overlay'
const panelSrc = read('server/plugins/executor-panel/src/host/panel-page.ts')
const viewSrc = read('server/plugins/workbench/src/client/executor-view.tsx')
const sidebarSrc = read('server/plugins/workbench/src/client/sidebar.tsx')

// ---------- E1: panel navigation (any tab switch) tells the console to close ----------
section('E1 panel navigation posts the close message (the incident: navigation left the dialog up)')
ok(panelSrc.includes(CLOSE_TYPE), 'served panel page knows the close-overlay message type')
// The post must sit inside showTab — the single point every panel content change
// funnels through (tab radios, show-tab/show-epic wayfinding, boot). Anchor on the
// function body, not on line numbers.
const showTabBody = (panelSrc.split(/function showTab\s*\(/)[1] || '').split('\nfunction ')[0]
ok(showTabBody.length > 0 && showTabBody.includes(CLOSE_TYPE), 'the close post lives inside showTab (one choke point for every panel content change)')
// The post is guarded to the embedded case: a standalone panel page (opened
// directly, no console around it) must not post into the void as if a dialog
// existed — the guard is the same window.parent !== window shape the open posts use.
ok(/window\.parent\s*!==?\s*window/.test(showTabBody), 'the close post is guarded to the embedded (in-console) case')

// ---------- E2: a face entry closes FIRST, then opens (no face under a dialog) ----------
section('E2 face entry closes the dialog before opening the face')
const faceIdx = panelSrc.indexOf("'sandbar-executor-panel:open-face'")
ok(faceIdx > 0, 'open-face sender present (pre-existing contract, unchanged)')
// The real order face: within the face-entry click handler, the close post comes
// before the open-face post, so a dialog that was open is gone before the face mounts.
const bindBody = (panelSrc.split(/function bindFaceEntry\s*\(/)[1] || '').split('\n  bindFaceEntry(')[0]
ok(bindBody.includes('postMessage'), 'face-entry click handler posts to the host')
ok(bindBody.includes('CLOSE_OVERLAY_MSG_TYPE') && bindBody.indexOf('CLOSE_OVERLAY_MSG_TYPE') < bindBody.indexOf('OPEN_FACE_MSG_TYPE'), 'the close post precedes the open-face post inside the face-entry handler (constant-name order; the close-then-open resolves to OPEN on the FIFO channel)')

// ---------- E3: the console acts on the close — one branch, wired to the overlay ----------
section('E3 console side: exactly one close branch, and the overlay closer is actually wired')
const branchCount = viewSrc.split('CLOSE_OVERLAY_MSG_TYPE').length - 1
ok(branchCount >= 2, 'executor-view both names and guards the close type (export + decision branch; got ' + branchCount + ' references)')
ok(/closeTicketOverlay\s*&&\s*closeTicketOverlay\s*\(/.test(viewSrc) || /closeTicketOverlay\(\)/.test(viewSrc), 'the close branch calls the overlay close callback (a missing callback stays a no-op, never a crash)')
ok(/closeTicketOverlay\?\s*:\s*\(\)\s*=>\s*void/.test(viewSrc), 'the close callback is an optional ExecutorView prop')
ok(sidebarSrc.includes('closeTicketOverlay'), 'the host renderer actually passes the overlay closer into ExecutorView (without this line the whole fix is a no-op)')

// ---------- E4: the new external input is gated by the pure decision layer ----------
section('E4 close message payload gate (external input: malformed shapes rejected, never throws)')
let gate
try {
  gate = (await import('../../server/plugins/workbench/src/client/face-overlay-model.ts')).closeOverlayFromMessage
} catch (e) {
  die('face-overlay-model.ts unimportable: ' + e.message)
}
if (typeof gate !== 'function') die('closeOverlayFromMessage export missing from face-overlay-model.ts')
ok(gate({ type: CLOSE_TYPE }) === true, 'exact close type accepted')
const rejects = [null, undefined, 42, 'close-overlay', [], {}, { type: 'sandbar-executor-panel:open-face' },
  { type: 'sandbar-executor-panel:close-overlay ', type2: 'x' }, { type: 7 }, { type: null }]
let badReject = 0, threw = false
for (const payload of rejects) {
  try { if (gate(payload) !== true) badReject++ } catch { threw = true }
}
ok(badReject === rejects.length, 'every malformed/foreign payload rejected (' + badReject + '/' + rejects.length + ')')
ok(!threw, 'the gate never throws on malformed input')

console.log('\nPASS=' + PASS + ' FAIL=' + FAIL)
process.exit(FAIL > 0 ? 1 : 0)
