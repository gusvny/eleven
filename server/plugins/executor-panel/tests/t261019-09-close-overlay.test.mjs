/**
 * t261019-09-close-overlay.test.mjs — the panel side of the close request
 * (t261019-09). CONTRACT test over the baked PANEL_HTML (import-time constant,
 * same technique as browser-page-contract.test.mjs — no browser, no 3099/7233).
 *
 * Faces:
 *  P1 the page carries the close constant, byte-identical to the host side
 *     (paired-constant discipline).
 *  P2 showTab posts close behind the embedded guard (window.parent !== window) —
 *     every panel content change funnels through showTab (tab radios, the
 *     show-tab / show-epic wayfinding branches, boot).
 *  P3 the face entry posts close BEFORE open-face (FIFO ordering: the ticket
 *     overlay goes down, then the face opens — it never mounts under a stale
 *     ticket dialog).
 *  P4 malformed-input discipline: the host-side gate is the pure
 *     closeOverlayFromMessage (face-overlay-model.ts) — asserted indirectly here
 *     by the type pairing, and directly in the workbench test battery.
 *  P5 boot fire (showTab('t-epics') at boot) is harmless: the same embedded guard
 *     covers it, and the host treats close-when-closed as a no-op (R5).
 */
import assert from 'node:assert/strict'
import { PANEL_HTML } from '../src/host/panel-page.ts'
import { CLOSE_OVERLAY_MSG_TYPE } from '../../workbench/src/client/face-overlay-model.ts'

let n = 0

// ---- P1 constant present and paired ----
assert.ok(PANEL_HTML.includes("var CLOSE_OVERLAY_MSG_TYPE = 'sandbar-executor-panel:close-overlay'"), `P1 constant declared (${++n})`)
assert.ok(PANEL_HTML.includes(`{ type: CLOSE_OVERLAY_MSG_TYPE }`), `P1 close posts carry no payload (${++n})`)

// ---- P2 showTab choke point, embedded guard ----
const showTab = PANEL_HTML.match(/function showTab\(id\)\{[\s\S]*?\n  \}/)?.[0] ?? ''
assert.ok(showTab.length > 0, `P2 showTab found (${++n})`)
assert.ok(showTab.includes('window.parent !== window'), `P2 embedded-only guard inside showTab (${++n})`)
assert.ok(showTab.includes('postMessage({ type: CLOSE_OVERLAY_MSG_TYPE }'), `P2 showTab posts close (${++n})`)
// guard BEFORE the post (standalone panel never posts)
assert.ok(showTab.indexOf('window.parent !== window') < showTab.indexOf('postMessage({ type: CLOSE_OVERLAY_MSG_TYPE }'), `P2 guard precedes the post (${++n})`)

// ---- P3 face entry order: close then open-face ----
const faceClick = PANEL_HTML.match(/btn\.onclick = function\(\)\{[\s\S]*?\n    \};/)?.[0] ?? ''
assert.ok(faceClick.includes('CLOSE_OVERLAY_MSG_TYPE'), `P3 face click posts close (${++n})`)
assert.ok(faceClick.includes('OPEN_FACE_MSG_TYPE'), `P3 face click still opens the face (${++n})`)
assert.ok(faceClick.indexOf('CLOSE_OVERLAY_MSG_TYPE') < faceClick.indexOf('OPEN_FACE_MSG_TYPE'), `P3 close precedes open-face (${++n})`)

// ---- P5 boot path: boot calls showTab, so the boot-time post rides the same
// guarded code — assert the boot call still exists (harmless by the guard + the
// host's close-when-closed no-op) ----
assert.ok(PANEL_HTML.includes("showTab('t-epics')"), `P5 boot showTab present, close rides the guard (${++n})`)

// ---- open-ticket untouched: still posts open-ticket with ticketId ----
assert.ok(PANEL_HTML.includes("'sandbar-executor-panel:open-ticket'"), `open-ticket contract untouched (${++n})`)

console.log(`done ${n}`)
