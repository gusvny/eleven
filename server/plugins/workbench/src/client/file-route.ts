/**
 * file-route.ts — the one path the guarded file read is served on (t261102-09).
 *
 * Why this module exists: the middle-column pane fetches a route that the node
 * half registers. Two literals in two halves drift, and the drift is invisible
 * to a source lock that checks each half on its own (the "dead button" shape).
 * Both halves import this constant instead. The module has NO imports, so it is
 * safe for the browser bundle and for the node half alike; a source lock pins
 * the zero-import rule.
 *
 * Precedent: `src/client/session-entry.tsx` reads `SESSION_CHARTER_PATH` from a
 * shared module for the same reason.
 */

/** Path of the guarded file-read route (node.ts registers it; the pane calls it). */
export const FILE_READ_PATH = '/sandbar-workbench/api/wf/file'
