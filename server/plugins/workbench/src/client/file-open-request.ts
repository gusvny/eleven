/**
 * file-open-request.ts — the one-slot hand-off from the chat's file tab to the
 * middle column (t261102-09).
 *
 * Why a module store and not a prop: the bridge body lives in dsh's right-column
 * slot tree, the pane lives in the workbench's middle column. They share no React
 * parent, so the request crosses a module boundary. Rules kept here:
 *
 *   - ONE slot, never a stack. A second click replaces the first, and the same
 *     address keeps one entry and only updates its line and revision — which is
 *     what makes "click the same file twice" reuse one middle view.
 *   - The published anchor. The holder lives on `globalThis` under
 *     `Symbol.for('sandbar.workbench.fileOpen.v1')` and IS the store API object
 *     (request / read / subscribe / close), for two reasons: a plugin re-register
 *     re-evaluates the client bundle and would wipe a bare module-level value
 *     (same reason `dismiss-pending-store.ts` anchors its state), and a second
 *     reader of the same page can find the store by that symbol without importing
 *     this module. Nothing is persisted; a page reload starts empty.
 *
 * A request stays readable until it is consumed or replaced. The middle column may
 * be unmounted (narrow shell, no project selected); the request waits there instead
 * of dropping, and opens when the column returns.
 *
 * No React import, no IO, and a snapshot that changes only on a real change, so
 * `useSyncExternalStore` can read it directly.
 */

import type { FileAddress } from './file-pane-model.ts'

/** One forwarded file, as the pane consumes it. */
export interface FileOpenRequest {
  /** The address the tab carried (also the reuse key). */
  address: string
  scope: FileAddress['scope']
  /** Empty for the absolute scope. */
  sessionId: string
  /** Absolute, or relative to the session workspace root. */
  path: string
  /** 1-based line to reveal, 0 for none. */
  line: number
  /** Bumped on every navigation of the same address. */
  revision: number
  /** Bumped for every accepted request; orders two different files. */
  seq: number
}

/** What a caller hands over: the address, the session it came from, and the line. */
export interface FileOpenIntent {
  address: string
  /** Optional; derived from the address when absent (session id present = session scope). */
  scope?: FileAddress['scope']
  sessionId?: string
  path: string
  line?: number
}

/** The published store surface (anchored on globalThis; also exported as functions). */
export interface FileOpenStore {
  requestFileOpen(intent: FileOpenIntent): FileOpenRequest
  readFileOpenRequest(): FileOpenRequest | null
  subscribeFileOpen(listener: () => void): () => void
  closeFileOpen(): void
}

interface StoreState {
  current: FileOpenRequest | null
  seq: number
  revision: number
  listeners: Set<() => void>
}

const HOLDER_KEY = Symbol.for('sandbar.workbench.fileOpen.v1')

function createStore(): FileOpenStore {
  const state: StoreState = { current: null, seq: 0, revision: 0, listeners: new Set() }

  const changed = (): void => {
    for (const listener of [...state.listeners]) {
      try {
        listener()
      } catch {
        // One broken subscriber does not stop the others.
      }
    }
  }

  const requestFileOpen = (intent: FileOpenIntent): FileOpenRequest => {
    const sessionId = typeof intent.sessionId === 'string' ? intent.sessionId : ''
    const scope: FileAddress['scope'] = intent.scope === 'session' || intent.scope === 'absolute'
      ? intent.scope
      : (sessionId !== '' ? 'session' : 'absolute')
    const line = typeof intent.line === 'number' && Number.isFinite(intent.line) && intent.line >= 1
      ? Math.floor(intent.line)
      : 0
    const address = typeof intent.address === 'string' ? intent.address : ''
    const held = state.current
    state.revision += 1
    if (held !== null && held.address === address) {
      // Same file: one view, a new line target. `revision` tells the pane to
      // re-scroll instead of remounting.
      const next: FileOpenRequest = { ...held, line, revision: state.revision }
      state.current = next
      changed()
      return next
    }
    state.seq += 1
    const next: FileOpenRequest = {
      address,
      scope,
      sessionId,
      path: typeof intent.path === 'string' ? intent.path : '',
      line,
      revision: state.revision,
      seq: state.seq,
    }
    state.current = next
    changed()
    return next
  }

  return {
    requestFileOpen,
    readFileOpenRequest: () => state.current,
    subscribeFileOpen: (listener: () => void) => {
      state.listeners.add(listener)
      return () => {
        state.listeners.delete(listener)
      }
    },
    closeFileOpen: () => {
      if (state.current === null) return
      state.current = null
      changed()
    },
  }
}

/** The published store; created once per page evaluation and anchored on globalThis. */
function anchor(): FileOpenStore {
  const slot = globalThis as unknown as Record<symbol, FileOpenStore | undefined>
  const held = slot[HOLDER_KEY]
  if (held !== undefined && typeof held.readFileOpenRequest === 'function') return held
  const created = createStore()
  slot[HOLDER_KEY] = created
  return created
}

/**
 * Hand one file to the middle column.
 * @param intent - the address, the session it came from, and the line.
 * @returns the request now in the slot.
 */
export function requestFileOpen(intent: FileOpenIntent): FileOpenRequest {
  return anchor().requestFileOpen(intent)
}

/** The request on show, or null. Reference-stable between changes. */
export function readFileOpenRequest(): FileOpenRequest | null {
  return anchor().readFileOpenRequest()
}

/**
 * Observe request changes.
 * @param listener - a synchronous callback.
 * @returns the unsubscribe callback.
 */
export function subscribeFileOpen(listener: () => void): () => void {
  return anchor().subscribeFileOpen(listener)
}

/** Close the pane: the slot empties and the middle column shows what was under it. */
export function closeFileOpen(): void {
  anchor().closeFileOpen()
}
