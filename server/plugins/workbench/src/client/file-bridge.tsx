/**
 * file-bridge.tsx — the right-column tab body that hands a file to the middle
 * column and gets out of the way (t261102-09).
 *
 * Life of one click on a file link in the chat:
 *   1. the chat calls `ctx.sidebarRight.openResource(address)`, which reveals the
 *      column and opens a tab of the extension-band type this plugin registers;
 *   2. this body reads its own tab (address, line, revision) and forwards the file
 *      to the middle column through `file-open-request.ts`;
 *   3. it closes its own tab, and collapses the column again when it is still
 *      expanded with no tab left. `openResource` revealed the column, so leaving it
 *      open here is exactly the "expanded and empty" refusal the ticket names.
 *
 * Shape: the seat renders this component as a normal React element and hands the
 * injected hooks in as props named `use<Name>`. The body is kept as ONE component on
 * purpose — the tab-info hook then has exactly one call site per render (`readTabInfo`,
 * a stable site whichever branch it comes from) and every refusal lives in the same
 * file. Nested components would render fine here; a shallow test renderer is the only
 * thing that would not see through them, and that is a harness property, not a rule of
 * the seat.
 *
 * Refusals kept by this file:
 *   - an address the grammar rejects does NOT throw in the slot: the claim rule
 *     (`claimsTextFile`) already leaves such addresses to the builtin preview, and a
 *     RESTORED tab that still carries one renders a named banner instead;
 *   - a missing injected hook, a throwing tab-info read, a throwing close or a
 *     throwing collapse never escapes the slot: each renders a banner or logs one line.
 */

import { useEffect } from 'react'
import {
  fileTitleOf,
  lineOfParams,
  parseFileAddress,
  type SidebarColumnFace,
  type TabInfoHook,
  type TabInfoLike,
} from './file-pane-model.ts'
import { requestFileOpen } from './file-open-request.ts'

/** Reads one dsh service through `ctx.get` (the repo's probe idiom). */
export type GetService = (id: string) => unknown

export interface FileBridgeProps {
  /** Injected by the slot framework (pass-through of the seat's own tab-info hook). */
  useTabInfo?: TabInfoHook
}

/**
 * The service probe, bound once at plugin apply time.
 *
 * Why a binding and not a prop: the seat passes ONLY the injected hooks as props, so
 * the plugin's own `ctx.get` handle has nowhere to travel. One binding per page
 * evaluation, set from `apply(ctx)`.
 */
let serviceProbe: GetService | undefined

/**
 * Bind the plugin's service probe for the bridge body.
 * @param get - the `ctx.get` handle bound to the client context.
 */
export function bindBridgeService(get: GetService | undefined): void {
  serviceProbe = get
}

/** Empty tab info: what a missing or throwing hook is read as. */
const EMPTY_TAB_INFO: TabInfoLike = {}

/**
 * Read the tab info, or an empty record when the hook cannot answer.
 *
 * One call site for every branch, so the hook order never changes between renders.
 * @param hook - the injected tab-info hook (untrusted: it arrives as a slot prop).
 * @returns the tab information, or an empty record.
 */
function readTabInfo(hook: TabInfoHook | undefined): TabInfoLike {
  if (typeof hook !== 'function') return EMPTY_TAB_INFO
  try {
    return hook() ?? EMPTY_TAB_INFO
  } catch (err) {
    console.warn('[workbench] file bridge: reading its tab failed:', err)
    return EMPTY_TAB_INFO
  }
}

/**
 * The tab body registered under `sidebar.right.pane.tab`.
 * @param props - the slot props (the injected tab-info hook among them).
 * @returns the forwarding body, or a named banner when the tab cannot be read.
 */
export function FileBridgeBody(props: FileBridgeProps) {
  const info = readTabInfo(props.useTabInfo)
  const tab = info.tab
  const address = typeof tab?.contentId === 'string' ? tab.contentId : ''
  const revision = typeof tab?.navigation?.revision === 'number' ? tab.navigation.revision : 0
  const tabId = tab === undefined ? '' : String(tab.id ?? '')
  const parsed = parseFileAddress(address)
  const line = lineOfParams(tab?.navigation?.params)

  useEffect(() => {
    if (parsed === null) return
    requestFileOpen({
      address,
      scope: parsed.scope,
      sessionId: parsed.sessionId,
      path: parsed.path,
      line,
    })
    try {
      tab?.actions?.close?.()
    } catch (err) {
      // The forward already happened; a failed close must not undo it.
      console.warn('[workbench] file bridge: closing its tab failed:', err)
    }
    try {
      const right = serviceProbe?.('sidebarRight') as SidebarColumnFace | undefined
      // `active()` is also undefined when no seat is mounted, so the expanded term
      // is required: without it this would EXPAND an empty column.
      if (right !== undefined && right !== null && typeof right.isExpanded === 'function'
        && right.isExpanded() === true && right.active() === undefined) {
        right.toggleExpanded()
      }
    } catch (err) {
      console.warn('[workbench] file bridge: collapsing the column failed:', err)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabId, address, revision])

  // Both refusals are inline because they are two short, self-contained lines and this
  // keeps every refusal of the body in one place. (An earlier note here claimed the seat
  // renders only one level and a helper component would never draw — that was measured on
  // a shallow test renderer, not on the platform: the seat renders nested components
  // normally.)
  if (typeof props.useTabInfo !== 'function') {
    return (
      <div className="wb-file-bridge wb-file-bridge-refused" data-file-bridge-refused=""
        data-file-bridge-address="" role="alert">
        Cannot read this tab: the tab-info hook is missing.
      </div>
    )
  }
  if (parsed === null) {
    return (
      <div className="wb-file-bridge wb-file-bridge-refused" data-file-bridge-refused=""
        data-file-bridge-address={address} role="alert">
        Cannot open this tab: the address cannot be parsed ({address || '(empty)'}).
      </div>
    )
  }
  return (
    <div className="wb-file-bridge" data-file-bridge={address} role="status">
      Opening {fileTitleOf(address)} in the middle column…
    </div>
  )
}
