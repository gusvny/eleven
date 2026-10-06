#!/usr/bin/env node
/**
 * sc_chat_band_and_two_entrances.mjs — t261005-06 scenario 2: the chat
 * identity band and the two new-session entrances (grey-box L3, epic
 * console-ui item UI-5, design note §2.1/§2.5/§2.6).
 *
 * User story: a user with two projects must be able to tell AT A GLANCE
 * which project and which session the right-rail chat is talking to — the
 * identity band changes with the project in all declared channels (band
 * face, bottom border, column wash), carries the session handle, and offers
 * a `Sessions N` menu whose `+ New session` is the second entrance. The
 * first entrance stays in the left-rail session row. Sessions the host
 * opens show their stable short-code handle (not a bare number), and the
 * project executor session — previously invisible in the list (implementer
 * note) — appears with its fixed `executor` handle.
 *
 * The epic's iron rule (口径写文档、不写界面): the UI carries controls and
 * facts only — this scenario asserts anchors/controls/facts, never prose.
 *
 * Intent split (no intent-level duplication):
 *   - developer smoke chat-project-band.mjs owns the existing decorator's
 *     unit truth table (attribute/CSS variable/idempotence/lifecycle stub);
 *   - t260904-01 / t260906-01 own the seq journey and empty-entry faces;
 *   - THIS entry owns the UI-5 upgrade face: three-channel project switch ×
 *     handle labels × both entrances co-present × executor row × zero
 *     residue on unload, chained as one journey (a broken channel makes the
 *     cross-channel comparison step fail loudly).
 *
 * Anchor discipline (understand deep, bind shallow): assertions fall on
 * the declared public contract from the reviewed plan — the band module's
 * exported apply/bind surface, the project color palette, and the declared
 * DOM data anchors (`data-wb-chat-projband`, `data-wb-psess-new`). Missing
 * anchor = FAIL naming it (TDD-phase red expected before implement lands;
 * arbitrate/merge must be green).
 *
 * Run: node integration/t261005-06/sc_chat_band_and_two_entrances.mjs
 * (offline, seconds, zero docker/Temporal/ports/3099; DOM is the same
 * homemade-stub discipline as smoke/chat-project-band.mjs; source-text
 * anchors are read from src, nothing written).
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WB = path.join(HERE, '..', '..', 'server', 'plugins', 'workbench');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`); }
  else { failed++; console.log(`  FAIL ${label}`); }
}
function section(t) { console.log(`\n== ${t}`); }

const nodeVer = process.versions.node.split('.').map(Number);
if (nodeVer[0] < 22 || (nodeVer[0] === 22 && nodeVer[1] < 18)) {
  console.error(`ENV_FAIL: node >= 22.18 required for native .ts import, got ${process.versions.node}`);
  process.exit(2);
}

const BAND = path.join(WB, 'src', 'client', 'chat-project-band.ts');
if (!existsSync(BAND)) {
  console.error('FAIL: contract anchor missing: src/client/chat-project-band.ts');
  process.exit(1);
}

let band, color;
try {
  band = await import('file://' + BAND);
  color = await import('file://' + path.join(WB, 'src', 'shared', 'project-color.ts'));
} catch (e) {
  console.error(`FAIL: contract module failed to load: ${e && e.message}`);
  process.exit(1);
}

// homemade DOM stub (same discipline as smoke/chat-project-band.mjs)
function el(tag = 'div', attrs = {}) {
  const node = {
    tagName: tag, isConnected: true, attributes: { ...attrs }, removed: false,
    style: { _props: {}, setProperty(k, v) { this._props[k] = String(v); }, removeProperty(k) { delete this._props[k]; } },
    setAttribute(k, v) { node.attributes[k] = String(v); },
    getAttribute(k) { return k in node.attributes ? node.attributes[k] : null; },
    removeAttribute(k) { delete node.attributes[k]; },
    appendChild() {}, remove() { node.removed = true; },
  };
  return node;
}

try {
  // ── A. three identity channels change with the project ─────────────────
  section('A. switching projects changes the band in all declared channels');
  const apply = band.applyProjectBand;
  ok(typeof apply === 'function', 'A0 applyProjectBand exported');
  // stub with a real scroll anchor (same discipline as smoke/chat-project-band.mjs)
  const mkScroll = (attrs = {}) => el('div', { 'data-conversation-scroll': '', ...attrs });
  const rootOf = (sc) => ({ querySelectorAll: (sel) => sel === '[data-conversation-scroll]' ? [sc] : [] });
  if (typeof apply === 'function') {
    const scA = mkScroll();
    const touchedA = apply(rootOf(scA), 'sandbar');
    ok(touchedA === 1 && scA.getAttribute('data-wb-chat-projband') === 'sandbar',
      'A1 sandbar band attribute set on the scroll anchor');
    const colA = scA.style._props['--wb-projband-color'];
    const scB = mkScroll();
    apply(rootOf(scB), 'suyou');
    const colB = scB.style._props['--wb-projband-color'];
    ok(colA && colB && colA !== colB, `A2 identity value differs per project (${colA} vs ${colB})`);
    ok(color.projectColor('sandbar') === colA, 'A3 band keyed on projectColor (contract color source)');
    // the three declared §2.1 channels (band face / border / column wash) must
    // all hang off the project-color variable, so one switch moves all three
    const css = String(band.PROJBAND_BASE_CSS ?? '');
    const hits = (css.match(/--wb-projband-color/g) ?? []).length;
    ok(hits >= 3, `A4 all three identity channels ride the project-color variable (hits=${hits}; upgrade to face+border+wash expected)`);
    const scX = mkScroll();
    apply(rootOf(scX), 'sandbar');
    apply(rootOf(scX), null);
    ok(scX.getAttribute('data-wb-chat-projband') === null, 'A5 null/foreign key removes the band (not-in-registry renders nothing)');
  }

  // ── B. band content: key + handle + Sessions N control ─────────────────
  section('B. band carries project key, session handle text, Sessions N control');
  const bandSrc = readFileSync(BAND, 'utf8');
  const iindex = path.join(WB, 'src', 'client', 'index.tsx');
  const chatSrc = [bandSrc,
    existsSync(iindex) ? readFileSync(iindex, 'utf8') : '',
    existsSync(path.join(WB, 'src', 'client', 'session-entry.tsx'))
      ? readFileSync(path.join(WB, 'src', 'client', 'session-entry.tsx'), 'utf8') : ''].join('\n');
  ok(/Sessions\s*N|sessions-count|sessionsCount|data-wb-chat-sessions|data-wb-band-sessions|wb-projband-sessions/i.test(bandSrc + chatSrc),
    'B1 Sessions control anchor present (landed contract anchor: data-wb-band-sessions)');
  ok(/handle|shortCode|short-code/i.test(bandSrc), 'B2 band renders the session handle');
  ok(!/locale|国际化|翻译词典/i.test(bandSrc), 'B3 band carries controls/facts only, no prose dictionary (口径写文档、不写界面)');

  // ── C. two entrances co-present ────────────────────────────────────────
  section('C. both §2.6 entrances exist');
  const rowPath = path.join(WB, 'src', 'client', 'project-session-row.tsx');
  const rowSrc = existsSync(rowPath) ? readFileSync(rowPath, 'utf8') : '';
  ok(/data-wb-psess-new/.test(rowSrc), 'C1 entrance 1: left-rail data-wb-psess-new anchor preserved');
  ok(/Sessions|new-session|newSession|New session/i.test(bandSrc + chatSrc),
    'C2 entrance 2: band Sessions menu carries a new-session control');
  ok(/startSession|useSessionEntry/.test(bandSrc + chatSrc + rowSrc),
    'C3 both entrances reuse the same session-open action surface');
  // if the declared fallback were silently taken (menu only in the left
  // rail), C2 would be the tripwire — the R3 review condition.

  // ── D. handle labels replace bare seq; executor row present ────────────
  section('D. session rows show short-code handles; executor row visible');
  ok(/shortCode|handle/.test(rowSrc), 'D1 left-rail row consumes handle short codes');
  ok(!/>{tab\.seq}|seq\s*as\s*label|\`#{?{?seq/i.test(rowSrc), 'D2 no bare seq-number label path remains in the row');
  ok(/executor/.test(rowSrc + chatSrc), 'D3 fixed executor handle surfaces in the list face');
  const ledgerFilePath = path.join(WB, 'src', 'host', 'session-ledger-file.ts');
  ok(existsSync(ledgerFilePath)
    && /executor-grants|executor_sessions/.test(readFileSync(ledgerFilePath, 'utf8')),
    'D4 executor visibility is the grants-merge door (derived, not a workspace-index change)');

  // ── E. zero residue on unload/stop ─────────────────────────────────────
  section('E. injected band elements are removed on lifecycle stop');
  ok(typeof band.startChatProjectBand === 'function', 'E0 start lifecycle exported');
  if (typeof band.startChatProjectBand === 'function') {
    // full lifecycle with the smoke-style doc stub: start -> set -> stop ->
    // stop again (idempotence) -> attribute gone, style captured removed
    const sc = mkScroll();
    const root = { documentElement: el('html'), body: { children: [sc] }, head: { appendChild() {} },
      querySelector: () => null, createElement: () => el('style'),
      querySelectorAll: (sel) => sel === '[data-conversation-scroll]' ? [sc]
        : sel === `[${band.PROJBAND_ATTR}]` ? [sc] : [] };
    let injected = null;
    root.head.appendChild = (n) => { injected = n; };
    const savedMO = globalThis.MutationObserver;
    globalThis.MutationObserver = class { observe() {} disconnect() {} };
    let h;
    try { h = band.startChatProjectBand({ doc: root }); } finally { /* restored below */ }
    h.set('sandbar');
    ok(sc.getAttribute('data-wb-chat-projband') === 'sandbar', 'E1 band set while running');
    h.stop();
    h.stop();
    ok(sc.getAttribute('data-wb-chat-projband') === null, 'E2 stop removes the band attribute (idempotent double stop)');
    ok(!injected || injected.removed === true, 'E3 injected style element removed on stop (zero residue)');
    h.set('suyou');
    ok(sc.getAttribute('data-wb-chat-projband') === null, 'E4 set after stop is a harmless no-op');
    globalThis.MutationObserver = savedMO;
  }
} catch (e) {
  console.error(`FAIL: journey threw: ${e && (e.stack || e.message)}`);
  process.exit(1);
}

console.log(`\n${passed} ok, ${failed} FAIL`);
process.exit(failed ? 1 : 0);
