---
title: "Right Column Session Entry and New Session hero Customization"
category: design
tags:
  - dsh
  - ticket console
  - session
status: draft
updated: 2026-09-28
---

# Right Column Session Entry and New Session hero Customization (epic)

> Opened 2026-08-25. Origin: the user's three questions in a row — after a refresh the sessions
> in the right-column chat are lost and cannot be found again; does clicking a ticket create a
> pile of sessions and leak resources; the New Session button at the top is rather large, can it
> be customized. This document is the sediment of the problem and the proposal; implementation
> goes through tickets. Related: [[ticket-workflow-console-design]] (source of the three-column
> sidebar layout). Origin epic: session-entry (decision rationale in notes/epics/session-entry.md)

## 1. Problem

**One sentence**: sessions in the right-column chat are "one-shot" — the moment the page is refreshed, the current
session disappears from view and no UI entry can get back to it; at the same time, the factory New Session landing
page (hero) you land on when there is no session is to be replaced wholesale — what the user actually needs is only
this: under the current project, open a session in one click, and switch quickly among the few sessions they have
opened themselves.

**Background knowledge** (what someone who was not involved needs to know):

- The three-column layout of the dsh console was remodeled by the ticket console plugin: left column = ticket console sidebar,
  middle column = three views, right column = chat. The left-column slot was originally dsh's factory "workspace browser"
  (a session list grouped by workspace, with search and a new-session button), and the ticket console sidebar pushed it out
  through the plugin-slot priority mechanism — and in doing so it also pushed out **the only ready-made session recovery entry**.
- Sessions in dsh come in two kinds: **ticket sessions** (opened by clicking a ticket, id fixed as `ticket-<ticket id>`,
  one per ticket, reused, not one per click — verified: no leak); **project sessions**
  (free chat the user opens on the UI, owned by the project — a new one lands in the project's main directory).
  This document deals only with the latter. It **follows the project**; it is not a global resource pool.
- The session itself lives on the server's disk, so a refresh loses no data; what is lost is the "entry".
- With no session (or when a session did not come back), the right column lands on a landing page (hero): a big title +
  a big input card + workspace/preset selectors, filling the whole column. Stance (revised by t260829-06; the original sentence
  "this factory form is to be replaced, not coexisted with" was proven unattainable by t260828-06→t260829-01):
  every takeover-able slot on the hero is replaced by a plugin slot, while the big title and the big input card, the two
  slot-less elements, are allowed to coexist until dsh provides a takeover surface for them.

**Evidence**:

- Measured: after a refresh the right column returns to a blank landing page, the left-column ticket console has no session list, and free sessions cannot be reached again.
- dsh itself does record the current session in browser local storage, but refresh recovery depends on the session list syncing back first; when the timing is off it falls back to blank — so it cannot be relied on.
- Quite a few sessions are stored on disk (historical leftovers, sessions created by other means), but existing ≠ what should be shown —
  only sessions the user opened on the UI are "the user's sessions", and only those belong in the switch list.

## 2. Requirement

**Goals (verifiable)**:

1. After refreshing the page, with no memorization at all, one can get from a persistent entry back to any session one has opened.
2. Creating a session is a one-click action, and the new session lands in the current project's main directory.
3. The session switch entry is scoped to the current project, lists only what the user opened on the UI, holds no more than 5, and highlights the currently active one.
4. The factory New Session landing page at the top is **slot-replaced** (stance revised by t260829-06; the original text
   "replaced wholesale — the big-title big-card form no longer appears" was proven unattainable, see §1 and the appendix):
   all three takeover-able slots on the hero (workspace selector, preset selector, brand mark) are taken over by this plugin
   preempting them by priority, and the workspace slot renders this plugin's compact session entry; the big title / big input
   card are allowed to coexist until dsh provides a takeover-able slot (t260828-06's style-suppression direction has been
   falsified and is prohibited).
5. Ticket session entry (revised 260904 as t260903-07 landed; the original "clicking a ticket opens a session with context,
   behavior unchanged" has been overturned): clicking a ticket **no longer switches the right-hand chat** — the right side is
   always a single global session whose context does not move; clicking a ticket only opens the ticket detail drawer in the
   middle column (the three entries — left-column ticket row / epic-proposal related row / metrics drill-down — behave
   identically). The client-side linkage entry for per-ticket sessions has been retired (`openTicketSessionFlow` deleted;
   the client has no caller of `ticket-session/open`).
6. All changes stay closed inside the ticket console plugin; no file in the dsh installation tree is modified.

**Stakeholders**:

- User (the host): what they want is "a few sessions, switch at a glance", not a full session manager.
- Ticket system (revised 260904): the right side is always a single global session, and the ticket side goes only through the middle-column detail drawer — the boundary between ticket sessions and the global session is guaranteed by "separate entries" (the original linkage form, "the boundary is not muddled", went offline with t260903-07).
- Future dsh upgrades: when the customization breaks it must soft-degrade (styles bounce back, functionality does not crash).

**Upfront constraints**: do not touch the dsh core (use only the plugin mechanism); restarting the console (3099) is done by the user;
deliver the verify_lane code four-piece set.

## 3. Nongoal

- No full session list / search / archive — do not bring the whole capability set of the factory workspace browser back.
- The semantics and data of ticket sessions are unchanged (still true after t260903-07): the server-side `ticket-session/open` route and `ticketContext` are kept, existing `ticket-*` session data is not deleted at all, and find-or-create is unchanged — what went offline is only the client-side linkage layer "clicking a ticket triggers it".
- No session delete/cleanup UI this cycle (session count is maintained by hand; the magnitude is nothing to worry about).
- No cross-project session migration, no grouping by workspace (project ownership = cwd stance, not a grouping browser).

## 4. Proposal

**High level**: two customization faces, both inside the ticket console plugin.

1. **Add a "Sessions" section to the sidebar (persistent entry, solves recovery)**: a small block outside the ticket section in the left column —
   a new-session button + switch buttons for the current project's recently opened sessions (cap 5, active highlighted).
   The data is **not** a filter over the client's full session list — disk leftovers (historical, created by other means) never
   enter the list; the list = sessions the user opened through the UI, **book-kept by the plugin itself** (per-project ledger,
   MRU order), and clicking opens one in the right column. This is the main entry: persistent, still there after a refresh,
   curing "cannot get back" at the root.
2. **Slot-replace the top New Session (hero)** (revised by t260829-06): all three takeover-able plugin slots of the factory hero
   (workspace selector, preset selector, brand mark) are taken over by this plugin using the same priority-preemption mechanism as
   the left column: the workspace slot renders the compact session entry (new-session button + the same group of project-session
   switch buttons, reusing the sidebar ledger hook), and the preset/brand slots are left empty. **No CSS suppression of any
   factory element** (suffix-substring class-name suppression has been falsified, see the appendix) — the big title / big input
   card coexist, which is a declared item of the revised stance; a session created by the first message sent from the factory big
   card still does not enter the ledger (a coexistence leftover, not a silent degrade, stated explicitly here).

**Key tradeoffs**:

- Put the entry in two places (persistent in the sidebar + hero replaced with the same button group) rather than changing the hero only — because the hero appears only when there is no session, and changing the hero alone cannot solve "switch while a session exists" or "recover after a refresh".
- Sessions follow the project: both the list and new-session creation belong to the current project (cwd = project main directory), consistent with the sidebar's existing "per-row project routing"; no global session pool.
- List = actively opened (plugin bookkeeping) rather than a full enumeration — only what the user opened counts as "the user's sessions";
  disk leftovers, ticket sessions and subagent sessions never enter. The ledger converges naturally by MRU, and no
  pin/pin-to-top concept is introduced.
- Hero slot replacement does no style suppression of any factory element (settled by t260829-06; the original direction
  "style suppression via semantic anchors" has been falsified — t260828-06's suffix-substring rule hit the factory chat's only
  entry by mistake, and the cross section cannot converge; annotated in the appendix). Soft-degrade model (source: the
  t260828-06 hero-version implementation, not the left-column precedent — the left column registers without try/catch):
  slot contract changes → register throws, the plugin catches it → factory elements bounce back, functionality does not crash.
- After the preset/brand slots are left empty, the factory preset-selection capability is removed from the hero — this is a
  **functional loss** (not a coexistence leftover), which the user confirmed as acceptable at human review of this revision.

**Risks and mitigations**:

- Slot takeover depends on dsh's slot structure being stable: an upgrade may break it → soft degrade is acceptable, and on
  failure it bounces back to the factory form (put the try/catch inside the slots.inject callback body — when the slot is not
  declared, the inject callback runs lazily inside the declaring party's register(), so a catch wrapped outside inject() never
  sees it; see the @deepseek-ai/dsh-client-runtime slots.d.ts inject contract).
- A blank session that never sent a message is hidden by dsh's list semantics: accept that semantics
  (a blank session is not worth keeping), or do not persist the session at creation and wait for the first message —
  to be decided at implementation time.
- Where the "actively opened" bookkeeping lives (a host-side file or client storage) must survive refresh/restart —
  to be decided at implementation time; the ledger is a precondition for this design to hold, not an option.

**Tie-back**: the persistent sidebar session section (project ownership + actively-opened ledger) → satisfies goals 1/2/3;
hero three-slot replacement → satisfies goal 4 (revised stance); both faces touch only the plugin → satisfies goal 6;
the ticket-session path is untouched → satisfies goal 5 and avoids the Nongoal overreach items.

## Appendix: Key verification record (implementation tickets can cite directly, no need to re-check)

> This appendix is the code-investigation conclusion of 2026-08-25, a "you will get it wrong if you do not write it down" detail.
> From t260829-06 on, each item carries a validity tag: [valid] cite as usual; [falsified] no longer citable.

- [valid] Hard evidence that ticket sessions do not leak: the host side creates/finds a session by `ticket-<ticket id>` and reuses an existing one;
  there are 8 on disk now, and the whole session directory is 90M (the bulk being historical sessions).
- [valid] Left-column preemption precedent: the ticket console pushed the factory browser out of the sidebar slot with priority=-10
  ("the lowest-priority one renders" for a single slot); the hero's three slots are single slots too, so the same mechanism can take them over.
- [valid] Three takeover-able hero slots: workspace selector, preset selector, brand mark.
- [falsified, t260828-06→t260829-01] Style anchors: it is true that the session root element has a `data-phase="hero"`
  semantic attribute, but the **normative statement** "style class-name semantic suffixes are stable across builds, so write style
  selectors by suffix-substring matching" is void, **and any further style suppression of factory elements is prohibited**: it was
  measured that `[class$="hero"]` sets display:none on the factory chat's only entry (the big input card, whose variant class is
  `<hash>_hero`); contains matches such as `[class*="workspace"]`/`[class*="headline"]` have an extremely large cross section with
  the full set of factory component class names and cannot converge in that direction. Hero replacement always goes through slot
  replacement only.
- [valid] dsh has browser-local persistence of the "current session" (store name dsh.conversation.chat),
  but recovery has a timing race, so it cannot serve as a recovery path — only as an optimization.
- [valid] A blank session is shown as only the currently selected one in the factory list logic.
- [valid] Creating a new session: when the client capability is insufficient, add a host-side endpoint modeled on "open/find a ticket session"
  but without the ticket prefix and without injecting ticket context (already landed: global-session/open).
- [obsolete (no longer holds from t260828-02), kept for reference] The data source of the sidebar "Sessions" section =
  ctx.sessions.list filtered (full-enumeration stance) — the current implementation is a plugin-built ledger
  (localStorage MRU, listing only UI-opened sessions); this item only documents the fact that ctx.sessions.list carries no
  "was it opened on the UI" information, and that fact is still valid.
