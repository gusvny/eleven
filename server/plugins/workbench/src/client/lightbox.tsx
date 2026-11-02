/**
 * lightbox.tsx — the shared overlay (epic artifact-face, slice 3, ticket t261030-36).
 *
 * Extracted from `index.tsx`, where it served the screenshot-evidence list only. The
 * artifact image view uses the SAME component, so both faces keep the same guards:
 *   - Esc closes (any focus);
 *   - the arrow keys page only when the focus is outside an editable control, so typing
 *     in an input does not page the overlay;
 *   - a click on the backdrop closes, a click on the image does not;
 *   - the `keydown` listener and the broken-image state are reclaimed on unmount.
 *
 * The component is a projection: the caller owns the item list and the open index.
 */
import { useEffect, useState } from 'react'
import { LIGHTBOX_KEYS } from './lightbox-model.ts'

export interface LightboxItem {
  /** File name or artifact title, shown in the bar. */
  name: string
  /** The served URL (same origin, read-only route). */
  src: string
  /** Alt text. Falls back to `name`. */
  alt?: string
}

/** True when the event target is an editable control (typing moves the caret, not the page). */
export function isEditableTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT'
    || t.isContentEditable
}

export function Lightbox({ items, index, onClose, onNav, kindLabel }: {
  items: LightboxItem[]
  index: number
  onClose: () => void
  onNav: (items: LightboxItem[], index: number, delta: number) => void
  /** Word used in the load-failure line ("Image" / "Screenshot"). */
  kindLabel?: string
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === LIGHTBOX_KEYS.close) { e.preventDefault(); onClose() }
      else if (e.key === LIGHTBOX_KEYS.prev && !isEditableTarget(e.target)) {
        e.preventDefault(); onNav(items, index, -1)
      } else if (e.key === LIGHTBOX_KEYS.next && !isEditableTarget(e.target)) {
        e.preventDefault(); onNav(items, index, 1)
      }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [items, index, onClose, onNav])
  const f = items[index] ?? items[0]
  const [broken, setBroken] = useState(false)
  // A new item may load: the old failure does not follow it.
  useEffect(() => { setBroken(false) }, [f?.src])
  if (!f) return null
  const word = kindLabel ?? 'Image'
  return (
    <div className="wb-lb" onClick={onClose} data-testid="lightbox">
      {items.length > 1 && (
        <button type="button" className="wb-lb-nav" aria-label="Previous"
          onClick={(e) => { e.stopPropagation(); onNav(items, index, -1) }}>‹</button>
      )}
      {broken
        ? <div className="wb-lb-miss">{word} failed to load: {f.name}</div>
        : (
            <img
              className="wb-lb-img"
              alt={f.alt ?? f.name}
              src={f.src}
              onClick={(e) => e.stopPropagation()}
              onError={() => setBroken(true)}
            />
          )}
      {items.length > 1 && (
        <button type="button" className="wb-lb-nav" aria-label="Next"
          onClick={(e) => { e.stopPropagation(); onNav(items, index, 1) }}>›</button>
      )}
      <div className="wb-lb-bar" onClick={(e) => e.stopPropagation()}>
        <span>{items.length > 0 ? `${index + 1} / ${items.length}` : '0 / 0'}</span>
        <span className="wb-lb-name">{f.name}</span>
        <button type="button" className="wb-lb-close" onClick={onClose}>Close (Esc)</button>
      </div>
    </div>
  )
}
