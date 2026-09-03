/* ------------------------------------------------- shell Settings 行锚定（纯逻辑，node 可直测）——metrics-anchor.ts */

/** shell Settings 钮锚定词（aria-label/title/text 全对，大小写不敏感）。 */
const SETTINGS_ANCHOR_RE = /(^|\b)settings(\b|$)|设置/i
/** 工单台自有子树标记（sidebar.tsx 侧栏根类名）——锚定负向排除用（打回 2 案1）。 */
const OWN_SUBTREE_MARKER = 'wb-sb'

function isSettingsButton(el: Element): boolean {
  return SETTINGS_ANCHOR_RE.test(el.getAttribute('aria-label') ?? '')
    || SETTINGS_ANCHOR_RE.test(el.getAttribute('title') ?? '')
    || SETTINGS_ANCHOR_RE.test(el.textContent ?? '')
}

/**
 * 从侧栏根向上找 **shell 的** Settings 钮（上溯 ≤10 层，同 useHideFactoryNewSession
 * 半径）。锚定负向排除（t260902-05 验收打回 2 案1，实拍证伪了上一版）：命中钮必须
 * **不在侧栏包子树内**——工单台自有 ⚙（title=设置，.wb-sb-foot 内）会被「设置」
 * 锚词误伤，而 shell 底栏结构性处于侧栏包根之外。双保险：root.contains 命中即排除
 * + closest('.wb-sb-foot') 排除，把自有元素全部挡在外面。
 */
export function findSettingsRow(root: HTMLElement): { row: HTMLElement; settings: HTMLButtonElement } | null {
  for (let e: HTMLElement | null = root.parentElement, i = 0; e && i < 10; i++, e = e.parentElement) {
    const hit = Array.from(e.querySelectorAll('button')).find(b =>
      isSettingsButton(b)
      && !root.contains(b)
      && b.closest(`.${OWN_SUBTREE_MARKER}, .${OWN_SUBTREE_MARKER}-foot`) === null)
    if (hit && hit.parentElement) return { row: hit.parentElement, settings: hit }
  }
  return null
}

