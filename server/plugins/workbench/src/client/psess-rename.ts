/**
 * sandbar-workbench · project-session tab rename: click arbitration and commit
 * decision (t261031-33, R1/R3). Pure functions, zero IO, zero DOM, no React
 * import - node runs this file directly (smoke and the L1 battery do).
 *
 * Why a state machine instead of inline handlers: a browser fires click, click,
 * dblclick for one double click. R1 forbids two switches, and a switch plus a
 * detached editor. So the tab's click does NOT switch at once - it arms a
 * pending switch for RENAME_CLICK_WINDOW_MS. The pair's second click arrives
 * inside that window and cancels it, so a double click performs ZERO switches
 * and ONE editor open; a single click performs exactly ONE switch when its
 * timer fires. The timer itself is host IO (window.setTimeout in
 * project-session-row.tsx); every decision below is pure and testable.
 *
 * States:
 *   pending - tab id whose switch is armed (null = none);
 *   editing - tab id whose inline name editor is open (null = none).
 *
 * Transitions (see tabClickStep):
 *   click(id)          edit open on id -> drop the armed switch, nothing else
 *                                      (a click inside the editor is the
 *                                      editor's own business);
 *                      otherwise       -> arm the switch for id (latest click
 *                                      wins; the host clears the old timer);
 *   dblclick(id)       edit open on id -> no-op (a double click in the input is
 *                                      word selection, never a re-open that
 *                                      would reset the typed draft);
 *                      otherwise       -> cancel the armed switch, open the
 *                                      editor;
 *   switch-due(id)     pending === id  -> exactly one switch to id;
 *                      otherwise       -> stale timer, no-op;
 *   close-editor       -> editor closed, nothing armed.
 */

import { tabLabelOf } from '../shared/sessions.ts'

/** Window a single click waits for a possible second click (ms). 250 ms sits
 *  inside the ~500 ms browser double-click interval, so a normal double click
 *  always lands while the switch is still armed. */
export const RENAME_CLICK_WINDOW_MS = 250

/** Arbitration state (two ids or null; no other dimensions). */
export interface TabClickState {
  /** Tab id whose switch is armed, or null. */
  pending: string | null
  /** Tab id whose inline name editor is open, or null. */
  editing: string | null
}

/** One input to the machine. */
export type TabClickEvent =
  | { type: 'click'; id: string }
  | { type: 'dblclick'; id: string }
  | { type: 'switch-due'; id: string }
  | { type: 'close-editor' }

/** One step: the next state plus the at-most-one side effect it asks for. */
export interface TabClickStep {
  state: TabClickState
  /** Session to open now (exactly one per step at most); null = no switch. */
  switchTo: string | null
  /** Tab whose editor opens now; null = none. */
  openEditor: string | null
}

/** Fresh state: nothing armed, no editor. */
export function initialTabClickState(): TabClickState {
  return { pending: null, editing: null }
}

/** Malformed events and malformed ids are no-ops (never a guessed switch). */
function noop(state: TabClickState): TabClickStep {
  return { state, switchTo: null, openEditor: null }
}

/** Apply one event. Pure: the input state object is never mutated. */
export function tabClickStep(state: TabClickState | undefined, event: TabClickEvent | undefined): TabClickStep {
  const cur: TabClickState = state && typeof state === 'object'
    ? { pending: typeof state.pending === 'string' ? state.pending : null, editing: typeof state.editing === 'string' ? state.editing : null }
    : initialTabClickState()
  const type = event && typeof event === 'object' ? event.type : undefined
  const id = event && typeof event === 'object' && 'id' in event ? (event as { id?: unknown }).id : undefined
  const validId = typeof id === 'string' && id !== ''
  switch (type) {
    case 'click': {
      if (!validId) return noop(cur)
      // A click on the tab whose editor is open: the second click of the pair
      // that opened it, or a click inside the input. Nothing gets armed.
      if (cur.editing === id) return { state: { pending: null, editing: cur.editing }, switchTo: null, openEditor: null }
      return { state: { pending: id as string, editing: cur.editing }, switchTo: null, openEditor: null }
    }
    case 'dblclick': {
      if (!validId) return noop(cur)
      // Word selection inside the open editor must not reset the draft.
      if (cur.editing === id) return noop(cur)
      // The pair cancels the armed switch: a double click never switches.
      return { state: { pending: null, editing: id as string }, switchTo: null, openEditor: id as string }
    }
    case 'switch-due': {
      if (!validId) return noop(cur)
      if (cur.pending === null || cur.pending !== id) return noop(cur)
      return { state: { pending: null, editing: cur.editing }, switchTo: id as string, openEditor: null }
    }
    case 'close-editor':
      return { state: { pending: null, editing: null }, switchTo: null, openEditor: null }
    default:
      return noop(cur)
  }
}

/**
 * Text the inline editor opens with (R1: "prefilled with the current name"):
 * the set custom name, else the label the tab shows today (the handle short
 * code). Same rule as the rendered label, so the user edits what they see.
 */
export function renameDraftOf(customTitle: unknown, handleLabel: unknown): string {
  return tabLabelOf(customTitle, handleLabel)
}

/** What a commit writes. */
export type RenameCommit =
  /** Nothing to write: the trimmed draft equals the prefill, so no ledger write. */
  | { kind: 'none' }
  /** Write this name through setEntryTitle. '' clears the custom title (R3). */
  | { kind: 'set'; name: string }

/**
 * Decide a commit (Enter, or blur - the row commits on blur so a click
 * elsewhere never silently drops a typed name; Esc is the cancel path).
 * An unchanged draft writes nothing, so a bare double click followed by a blur
 * cannot turn the handle label into a stored name. A trimmed-empty draft
 * returns name '' = clear.
 */
export function renameCommitOf(draft: unknown, prefill: unknown): RenameCommit {
  const d = typeof draft === 'string' ? draft.trim() : ''
  const p = typeof prefill === 'string' ? prefill.trim() : ''
  if (d === p) return { kind: 'none' }
  return { kind: 'set', name: d }
}
