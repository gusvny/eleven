---
title: "Project Management UI Design (embedded in the left column)"
category: design
tags:
  - sandbar
  - workbench
  - project management
  - UI
status: active
updated: 2026-09-28
---

# Project Management UI Design (embedded in the left column)

> Delivery document for project-lifecycle ticket ③ (t260904-15); base draft = notes/discussions/260904-project-ui-mock.html
> (mock v5 passed review; final version after the host's revision 11 redrew two icons). Source of truth for the settled stance = notes/epics/project-lifecycle.md
> face D + decision 8 + acceptance 11-14; this document expands the UI face (entries / interaction / degrade / confirmation stance) and does not supersede the epic.

## Problem

Until now, coming in and out of sandbar's project registry (`~/.sandbar/projects/<key>/project.yaml`, contract ①a) was entirely hand-crafted:
onboarding = manually create the directory + hand-write the YAML + manually run the credentials migration; removal = hand-delete
the directory (the in-flight ticket query face dangles; archived data risks evaporating).
Tickets ①② have already consolidated these two operations into the installer CLI (`sandbar project add|remove|list`, fail-closed
pre-validation + in-flight gate + purge dual flags), but the host's operating surface is still the terminal — and the console's left
column already lists project groups from the registry, making it the host's natural operating surface.
What is missing is a UI entry that embeds the CLI capability into the left column, plus three kinds of presentation aligned with
the registry state (quarantined entry, group-header settings entry, onboarding row).
There is also a purely presentational problem: the group header's four view entries are emoji (📋📖🔀🗂️), small and stylistically
inconsistent (host order 260904: do a proper icon set along the way).

## Requirement

1. Exactly three additions to the left column (no standalone page/tab/middle-column view; downgraded by host ruling 260904):
   - **Group-header "Project Settings" entry**: a fifth icon, always visible, in the same row and same style as the four view icons; clicking opens the **project settings modal**
     (read-only: key / display name / root directory + ticket counts [in-flight / completed / archived; when Temporal is unreachable, degrade to a "—" hint, not red] +
     health-check area + a danger area at the bottom, "Remove project…"). This cycle the settings modal is read-only; an editor = Nongoal.
   - **"＋ Onboard project" row**: at the end of the project group list, a boxed ＋ with the same wording as the session area inside a group; the modal form includes a pre-check dry-run,
     and the six classes of rejection error are shown in place (no need to dig through backend logs), while warnings do not block; on success the new project group appears in the left column immediately.
     An empty/fully-quarantined registry still renders this row (the first project onboarding happens precisely on an empty registry).
   - **Quarantine row**: loader-quarantined keys are presented as a red row; clicking opens a modal with the reason (including how to locate `<dir>/project.yaml`
     and how to repair it); while a key is quarantined there is no group header and no settings entry (there is no loaded entry to configure).
2. **All four removal steps happen inside the modal** (entered from the danger area of the settings modal): the in-flight gate result (a refusal reports ticket numbers; when Temporal is
   unreachable the fail-closed wording includes the "run sandbar up first" guidance) → disposition checkboxes (all preserved by default) → the dry-run manifest (what will be deleted / kept) shown first
   → after ticking purge, the key must be typed for a second confirmation; the execution result uses the same stance as the CLI (same source as `--json`).
   Onboarding modal pre-check stance (revised by t260904-15 arbitrate gen1 F1): the CLI `project add` has no `--dry-run` flag
   (adding one = a cross-write-set change, so the ruling item is escalated to host/epic) — the pre-check is downgraded to a **modal-local shape check** (key whitelist regex /
   absolute root path / non-empty; nothing written to disk, no CLI call, and it does not implement the CLI's validation semantics); on confirmation the CLI does the deep validation
   (existence / crossing / duplicate / legacy) and shows the result in place.
3. **One unified icon family** (acceptance 11b): five SVG line icons (ticket list / knowledge base / model routes / epic proposals / project settings),
   one shared spec: viewBox 20×20 · stroke=currentColor · stroke width 1.6 · round caps and joins · fill none · rendered at 18px ·
   hit area 26×26 (radius 6) · three states (idle/hover/active) · identifiable via title+aria-label; settings = sliders (three tracks with offset
   knobs), routes = forking with an arrow (mock v5 revision 11 redraw, final: a spoked gear looked like a sun and a node link looked like share, both avoided).
   The four existing view icons show zero behavior regression after the swap (the ticket list icon's back-to-list linkage semantics stay as before); emoji
   references in render sites and comments are reduced to zero (three files: sidebar/index/epics; index's 🤖⚙️👤 executor badges are outside the icon family and exempt).
4. **Single-source thin shell on the write path** (decision 8): the workbench host write route spawns `sandbar project add|remove --json`
   (the real entry = the repo-root `sandbar` thin shell → installer.cli; zero validation/gate logic on the UI side), and the CLI's rejection error bodies are passed through and shown in place;
   the registry read face goes through the TS loader (GET /wf/projects, whose consumer is the loader itself, preventing two copies from drifting) and is extended with quarantined entries;
   ticket counts are a Temporal query = CLI-only data, so the host read route spawns `sandbar project list --json` to fetch them from a single point
   (the spawn is the same source rather than a second copy, so it does not violate decision 8's registry read-face stance). Write routes do not enter the tool bridge (agents are not a consumer).
5. Zero regression and red lines: the existing group-header four icons / session area / ticket list behave with zero regression; console 3099 is untouched (changes take effect when the host
   chooses to restart the console; staleness banner stance); all tests go through the isolated instance.

## Nongoal

- No project settings editor (rewriting name/paths/roles) — same stance as "real needs such as editing self-declared fields"; this cycle the settings modal is read-only.
- No standalone project management page/tab/middle-column view; no batch operations, drag-and-drop, or cross-machine migration wizard.
- No validation/gate/health-check logic on the UI or route side (thin-shell red line): the six rejection classes, the in-flight gate and the purge precondition gate all live on the CLI side;
  the onboarding pre-check is only a local shape whitelist check (see the revised stance in Requirement 2), not a replica of the CLI's validation semantics.
- The health-check chips are downgraded this cycle to a neutral placeholder saying "health data source not wired up" — CLI list has no health field yet (health warnings are only reported
  once, at add time), and "add a projects[].health field to CLI list --json" is a cross-write-set change that a small ticket will complete after the host/epic rules on it
  (the UI already reserves the render slot, so zero structural change will be needed then). Acceptance item 11 of the epic is delivered with this downgraded stance, which is not a silent deviation.
- The contract schema version is not changed (removal semantics = contract ①a-1, already booked in v1.9).

## Proposal

### Entries and components

| Face | Where it lands | Content |
|---|---|---|
| Icon family | `src/client/project-icons.tsx` | five SVG components + single-source spec constants (viewBox / stroke width) + PROJECT_ICON_SPECS (title=aria-label) |
| Three additions in the left column | `src/client/sidebar.tsx` | the fifth group-header settings entry (data-wb-project-settings-entry), the "＋ Onboard project" row (data-wb-project-add-row), the quarantine red row (data-wb-quarantine-row); data source = projects+quarantined from GET /wf/projects (loadRegistry(), no 500 when empty/fully quarantined) |
| Four modals | `src/client/project-modals.tsx` | settings (read-only + ticket count degrade + health placeholder + danger area) / onboarding (pre-check dry-run + in-place errors) / removal (four-step state machine gate→dispose→dry→confirm→executing) / quarantine details |
| host routes | `node.ts` + `src/host/project-admin.ts` | GET /wf/projects (registry + quarantined entries); GET /wf/projects/detail?key= (ticket counts, spawn CLI list --json); POST /wf/projects/add|remove (write face; the dry_run/purge_data/purge_credentials/confirm_last flags map one-to-one onto the CLI) |

### spawn thin-shell failure-mode stance (runProjectCli; source of truth for the tradeoff = create_plan gen1 R1-①)

repo anchoring = `config?.repo ?? SANDBAR_REPO ?? DEFAULT_REPO` in node.ts, passed in from the same source (cwd=repo, entry=`<repo>/sandbar`,
so that running from another repo cannot hit the wrong registry); timeout 30s (versus the admin CLI's 300s), with the wording naming "CLI execution timed out";
all four terminal states are reclaimed — normal = parse stdout, timeout = SIGTERM + await exit turned into 504, cancellation = AbortSignal turned into 499
(no zombies left in any case, asserted with elapsed time in UT); malformed stdout / over 16MB = turned into 502 with precise wording, never a bare stack throw.
**Non-zero exits are routed by exit code** (settled by arbitrate gen1 F3):
a JSON error body (the FailClosed machine stance) → 409 with the original body passed through; exit 1 with plain-language non-JSON → 409 plus a restatement of the original text (a rejected
user input ≠ an upstream fault; ticket ①'s add rejection currently prints `[红]` plain language, and turning it into JSON is an already-reported cross-ticket contract gap);
exit 2 → 502 "bad parameters" (an argparse usage error = the route's argv assembly does not match the CLI contract, i.e. a bug in the route itself); flag assertions are anchored on the real CLI `--help`
(UT case A0 runs it for real, so a stub cannot pin a wrong argv as the expectation — the arbitrate gen1 UT blind-spot lesson).

### Interaction and confirmation stance

- Modal skeleton = the session-entry confirmation modal precedent: clicking is disabled while in flight (busy disabled, result-driven close), ESC/overlay closes, errors show in place;
  **during execution the modal is locked** (ESC/overlay/✕ all disabled), preventing an abandoned half-done removal from faking completion.
- The removal disposition checkboxes are all unticked by default (default = reversible removal: retire the registry entry only, keep all data); once any purge box is ticked, the confirm button
  requires the key to be typed and matched exactly before it becomes usable; the dry-run manifest is shown before confirmation.
- Semantic anchors: modals are anchored on data-wb-pmod-* (the assertion face for smoke/project-modals.mjs), with zero CSS class-name cross-over with factory styles.

### Icon family color stance

The icon bodies consume currentColor, and the geometric spec (viewBox / stroke width / render size / hit area / corner radius) is unified as this ticket's contract; the three-state colors of the mock
spec card (idle #57606a / hover #0969da+#f0f6ff / active #0969da) were settled for the mock's light-theme context, while the dark-theme sidebar keeps its existing three-state palette
(zero regression on swap takes priority) — if alignment with the light card palette is wanted, handle it in the theming ticket.

### Test and acceptance mapping

- UT: `tests/project-admin.mjs` (spawn four terminal states + malformed input, 17 assertions), `tests/project-routes.mjs` (three-route contract
  + empty registry + quarantined entry, 21 assertions), `tests/project-icons.mjs` (icon family spec + emoji cleared, 29 assertions).
- smoke: `smoke/project-modals.mjs` (four modal semantic anchors + confirmation discipline, 29 assertions).
- Integration: three scenarios under `integration/t260904-15/` (host route contract / three left-column additions + onboarding-and-removal journey / settings face + quarantine + first onboarding on an empty registry),
  registered through run_scenarios.py, contract on the last line of SUMMARY, playwright-core missing = clean SKIP (KI-036 guard).
- The item-by-item correspondence for acceptance 11/11b/12/13/14 is in each scenario's intent field.
