/**
 * sandbar-workbench · platform banner-row hide decorator (t261007-07; the last
 * open item of the 261004 topbar-banner design note).
 *
 * Visual: hide the platform's own left-column banner row (brand mark + name +
 * fold toggle) so the console opens with our own brand row (t261005-09, 26px,
 * `[data-wb-brand-row]`) as the first row. The platform banner is a **sibling
 * flex child** of SidebarRoot (not a layer our chrome paints on), so per
 * design-note §2 this is HIDE, not COVER: display:none lets the regionArea move
 * up, a blank strip is impossible, and the guard path's worst case is the
 * platform row simply remaining visible (the degradation the design note
 * allows) — never a partial hide. The fold button goes away with the row (host
 * ruling 260924: the separator drag already changes the width, clampWidth
 * 264–420). This build has no theme button in the row at all (the theme control
 * lives in the settings panel, dsh-client-ui-settings-general, footArea), so
 * "both buttons stay gone" holds. document.title is platform-owned and this
 * module never touches it (design note §2).
 *
 * ── Anchor (named constants + provenance, discipline ①) ──
 * Anchor = the fold toggle's aria-label set (zh/en locale dicts, read in the
 * installed tree @deepseek-ai/dsh-client-ui-sidebar/lib/client.js lines 312–313
 * (zh) and 320–321 (en); across the platform only the fold toggle uses these
 * keys — the brand button and the new-session button both use
 * session.new.label, same file — so neither can be mistaken for the anchor).
 * A new platform locale dict = add here; drift = guard warn.
 * Root landmark = our own brand row `[data-wb-brand-row]` (rendered by
 * sidebar.tsx).
 *
 * ── Row resolution (review C1: never a blind parentElement) ──
 * The toggle renders inside a platform Tooltip wrapper; whether that wrapper
 * produces a real DOM element cannot be verified from the minified sources
 * (dsh-client-ui-primitives has no installed directory and a whole-tree grep
 * finds no `function Tooltip` symbol — inlined and renamed). Resolution is
 * therefore: **walk up from the toggle collecting ancestors until (excluding)
 * the first ancestor that contains our brand row (= the platform SidebarRoot);
 * tag every collected element**:
 *   - flat DOM (no wrapper): chain = [logoRow], the whole row is hidden;
 *   - Tooltip renders a wrapper: chain = [wrapper, logoRow], the full chain is
 *     hidden — never a partial hide;
 *   - landmark not found (our brand row unmounted / unexpected structure) or
 *     the walk exceeds the cap → guard path: hide nothing and log one explicit
 *     line (see below). The platform banner staying visible beats any risk of
 *     a half-hidden state.
 *
 * ── Guard (discipline ②): anchor absent = hide nothing + exactly one
 * console.warn naming the missing anchor; at most one warn per start (repeated
 * scans never spam); a successful hide logs nothing extra.
 *
 * ── Render mechanism (mirrors chat-project-band.ts; zero childList intrusion
 * into React-managed containers): set only a self-owned attribute
 * `data-wb-platform-banner-hidden` on platform elements; the visual lives in
 * one self-owned <style> injected into head (attribute selector, display:none).
 * On plugin unload the style and every self-set attribute are removed and the
 * factory tree is restored.
 *
 * ── Fault-mode tradeoff list (chat-project-tag.ts lines 13–25 form; review
 * condition C2) — borrowed from the chat-project-band.ts shape (attr + head
 * style + MutationObserver + cleanup), carried / not carried item by item:
 * 1. ✅ Late platform mount: a body-subtree childList MutationObserver re-scans
 *    — once React builds the row, the next callback hides it (same as band;
 *    the observer stays connected, anchor disappear/reappear does not blind it).
 * 2. ✅ Double injection / repeated scans: idempotent — same-value attribute
 *    writes and same-text style writes are skipped; re-renders and observer
 *    callbacks do not churn.
 * 3. ✅ Node rebuild: childList rescan re-tags (band C4: never disconnect the
 *    observer, so a hero↔chat-style switch does not leave it permanently blind).
 * 4. ✅ Full-terminal-state cleanup: stop() is idempotent = disconnect the
 *    observer + remove the head style + remove only the attributes this
 *    decorator set (tracked per element, never a global sweep) + the guard
 *    warn stays on the record; normal / error / timeout / unload all funnel
 *    into the same stop().
 * 5. ✅ Malformed / missing aria-label: querySelectorAll + getAttribute are
 *    fault-tolerant; odd nodes are skipped without throwing (malformed-input
 *    case, stub-reproduced, no real platform dependency).
 * 6. ✅ Anchor semantics (module-specific): multiple anchors all hidden
 *    together; a failed resolution hides nothing — never half-hidden.
 *    MAX_WALK bounds the upward walk so an unexpected structure can never hide
 *    half the page (safe-side failure = the platform row stays).
 * 7. ✅ Guard is not noisy: at most one warn per start (declared: the first
 *    unresolved scan logs, a later success does not log a "recovered" line —
 *    one console line is enough, no state-machine narration).
 * 8. ❌ No document.title writes (design note §2: never fight the platform for
 *    the same field).
 * 9. ❌ No collapsed-mode special case: the narrow rail renders the same row as
 *    a 36px platform mark and it is hidden too — declared behavior (our plugin
 *    owns the whole column; the platform mark has no place left to live).
 * 10. ❌ No body-level overlay / scroll listeners (band's UI-5 face only; this
 *     module has no interactive face, pure display:none, nothing to pin).
 */

/** The fold toggle's aria-label set (provenance in the module header; zh + en dicts). */
export const PLATFORM_FOLD_LABELS: readonly string[] = [
  // copy-lang-allow:data — detection anchor, not copy: the platform's own zh
  // locale string must stay byte-exact to match (provenance in the header).
  // copy-lang-allow:data
  '收起侧边栏',
  // copy-lang-allow:data — detection anchor, not copy (see above).
  // copy-lang-allow:data
  '打开侧边栏',
  'Collapse sidebar',
  'Open sidebar',
]

/** Our own brand row's self-set attribute selector (rendered by sidebar.tsx; the SidebarRoot landmark). */
export const BRAND_ROW_SELECTOR = '[data-wb-brand-row]'

/** Self-owned hidden-attribute name (set on platform elements to hide). */
export const BANNER_ATTR = 'data-wb-platform-banner-hidden'

/** Self-owned style element selector (in head, outside the React tree). */
export const BANNER_STYLE_SELECTOR = 'style[data-wb-platform-banner-style]'

/** The injected hide CSS (attribute selector only, zero class/hash dependence). */
export const BANNER_CSS = `[${BANNER_ATTR}] { display: none !important; }
`

/** Walk depth cap (safe side: exceeded = guard, never hide upward past the root). */
export const MAX_WALK = 12

/** Guard warn lines (each names the missing anchor by its literal labels; at most one per start). */
// copy-lang-allow:data — the zh label literals below are detection-anchor text,
// not copy: the guard line must name the anchor byte-exactly (scenario C2).
// copy-lang-allow:data
const GUARD_NO_ANCHOR = '[workbench] platform banner: fold-toggle anchor ("Collapse sidebar" / "Open sidebar" / "收起侧边栏" / "打开侧边栏") not found; nothing hidden'
const GUARD_NO_ROOT = '[workbench] platform banner: fold-toggle found but the sidebar root (an ancestor containing [data-wb-brand-row]) could not be resolved; nothing hidden'

/**
 * Row resolution (pure DOM logic, stub-tested): the elements to tag this round,
 * or null = guard (anchor missing or root unresolved — hide nothing).
 */
export function resolveBannerTargets(root: ParentNode): Element[] | null {
  let buttons: Element[]
  try {
    buttons = Array.from(root.querySelectorAll('button'))
  } catch {
    return null
  }
  const toggles = buttons.filter(b => {
    try {
      const label = b.getAttribute('aria-label')
      return typeof label === 'string' && PLATFORM_FOLD_LABELS.includes(label)
    } catch {
      return false
    }
  })
  if (toggles.length === 0) return null

  const targets: Element[] = []
  for (const toggle of toggles) {
    // Walk up from the toggle: collect ancestors until (excluding) the first
    // one containing our brand row (= the platform SidebarRoot).
    let node: Element | null = null
    try {
      node = toggle.parentElement
    } catch {
      return null
    }
    const chain: Element[] = []
    let resolved = false
    for (let depth = 0; node !== null && depth < MAX_WALK; depth++) {
      let hasBrandRow = false
      try {
        hasBrandRow = node.querySelector(BRAND_ROW_SELECTOR) !== null
      } catch {
        return null
      }
      if (hasBrandRow) {
        resolved = true
        break
      }
      chain.push(node)
      node = node.parentElement
    }
    if (!resolved) return null // walked out / cap hit without the landmark: guard, never a partial hide
    for (const el of chain) if (!targets.includes(el)) targets.push(el)
  }
  return targets
}

/** Set/clear the attribute (idempotent). targets=null or empty = clear everything we set (the guard hides nothing). */
export function applyBannerHidden(root: ParentNode, targets: Element[] | null): number {
  let touched = 0
  let styled: Element[]
  try {
    styled = Array.from(root.querySelectorAll(`[${BANNER_ATTR}]`))
  } catch {
    return 0
  }
  const wanted = new Set(targets ?? [])
  for (const el of styled) {
    if (!wanted.has(el)) {
      try {
        el.removeAttribute(BANNER_ATTR)
        touched++
      } catch { /* platform node not writable: retry next callback, never throw */ }
    }
  }
  if (targets === null) return touched
  for (const el of targets) {
    try {
      if (el.getAttribute(BANNER_ATTR) === null) {
        el.setAttribute(BANNER_ATTR, '')
        touched++
      }
    } catch { /* same: skip unwritable nodes, never throw */ }
  }
  return touched
}

export interface PlatformBannerHandle {
  /** Full-terminal-state cleanup (fault-mode item 4 checklist). Idempotent. */
  stop(): void
}

/** useEffect-shaped entry (F1 guard, same as chat-project-band): returns the cleanup itself. */
export function startPlatformBannerHideEffect(opts: { doc?: Document } = {}): () => void {
  const h = startPlatformBannerHide(opts)
  return () => h.stop()
}

/**
 * Start the decorator: head style + first scan + a body-subtree childList
 * Observer that rescans on platform rebuilds. Guard: a scan that cannot hide
 * anything (anchor missing or the root unresolved) hides nothing and warns
 * exactly once per start (no spam across repeated scans). stop() is mandatory
 * on unload.
 */
export function startPlatformBannerHide(opts: { doc?: Document } = {}): PlatformBannerHandle {
  const doc = opts.doc ?? (typeof document !== 'undefined' ? document : null)
  if (!doc || doc.documentElement === null || typeof doc.createElement !== 'function') {
    console.warn('[workbench] platform banner decorator has no document to attach to; soft-degrade, nothing hidden')
    return { stop() {} }
  }

  let stopped = false
  let warned = false
  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => { if (!stopped) scan() })
    : null

  function scan(): void {
    if (stopped) return
    let targets: Element[] | null
    try {
      targets = resolveBannerTargets(doc)
    } catch {
      targets = null
    }
    try {
      applyBannerHidden(doc, targets)
    } catch { /* attribute-surface errors never escape the decorator */ }
    if (targets === null && !warned) {
      // Guard: exactly one line naming the missing anchor (fold toggle missing
      // vs root landmark unresolved — name the finer cause of the two).
      warned = true
      const hasToggle = PLATFORM_FOLD_LABELS.some(label => {
        try {
          const bs = Array.from(doc.querySelectorAll('button'))
          return bs.some(b => b.getAttribute('aria-label') === label)
        } catch {
          return false
        }
      })
      console.warn(hasToggle ? GUARD_NO_ROOT : GUARD_NO_ANCHOR)
    }
  }

  // -- Own style in head (same-value writes skipped; query surfaces may throw on odd stubs) --
  let style = null
  try {
    style = doc.querySelector(BANNER_STYLE_SELECTOR)
  } catch {
    style = null
  }
  if (!style) {
    style = doc.createElement('style')
    try {
      style.setAttribute('data-wb-platform-banner-style', '')
      style.textContent = BANNER_CSS
      doc.head.appendChild(style)
    } catch {
      console.warn('[workbench] platform banner decorator cannot inject its style; nothing hidden')
      return { stop() {} }
    }
  }

  scan()
  try {
    observer?.observe(doc.body, { childList: true, subtree: true })
  } catch {
    console.warn('[workbench] platform banner decorator cannot observe the DOM; platform rebuilds will not re-hide')
  }

  return {
    stop() {
      if (stopped) return
      stopped = true
      try {
        observer?.disconnect()
      } catch { /* already disconnected */ }
      try {
        // Remove only the attributes this decorator set (scan and tagging share
        // the same surface; never a global sweep).
        const styled = doc.querySelectorAll(`[${BANNER_ATTR}]`)
        for (const el of Array.from(styled)) el.removeAttribute(BANNER_ATTR)
      } catch { /* best-effort teardown */ }
      try {
        style?.remove()
      } catch { /* best-effort teardown */ }
    },
  }
}
