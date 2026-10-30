---
code: artifact-face
retired: false
summary: Make what a ticket produces visible while it runs and reviewable at the human gate, with the base capability built once and each project free to ship its own views.
started: 2026-10-30
---

# artifact-face

## What it does

Give every ticket a declared, typed, versioned set of artifacts. Show them while the
ticket runs (progress) and at the human gate (review). Ship one view inventory and one
plugin channel; let every project — sandbar included — add or override views for its own
tickets on top of that base.

## The problem it solves

A running ticket cannot show the host what it is making. The ticket face carries
`artifacts: string[]` (a list of paths, rendered as one semicolon-joined line), plus one
special-cased kind (screenshot evidence) and the stage `report` markdown. Everything else
is invisible.

Three live projects hit this at their human gates (measured 261030):

- modeling (`project-vision` / `part-intake`, five stages, one human gate): the host must
  compare a self-rendered image, a ledger entry (part id / weight / interface) and the
  machine-gate receipt side by side;
- track (`project-vision` / `track-pipeline-v2`, seven stages, one human gate): a per-gate
  reading table, the check images and the generated track file;
- content (`project-content` / `content-studio`, eight stages, two human gates): the plan, the
  finished text, and the QC red items.

The same gap hides progress during a run: the console shows which stage runs and what the
agent says it is doing, but not what it made, not what changed since the last round, and
not what is still missing.

## Design and rulings

Design discussion (working record, Chinese): `notes/discussions/261030-artifact-progress-face-design.md`.

Host rulings, 261030:

1. **The base capability comes first, and it belongs to no project.** Build the base so
   that it works with zero project views. Then sandbar builds its own views and every other
   project builds its own, independently.
2. **Sandbar is a project like any other.** A project may add new views and may override
   the display of a built-in view, for its own tickets. One registry, one format, no
   privileged path.
3. **The frame is not overridable.** The console owns the artifact inventory, the machine
   verdict (gate / QC red-green), the original-bytes link and the source label. A project
   view decides how one artifact is drawn; it never decides whether the artifact is listed
   or whether a red is green.
4. **Retention and cleanup belong to the project too.** Over the per-ticket cap, keep the
   newest rounds and drop the oldest first. Each project declares its own retention policy
   and its own cleanup policy. The console supplies the defaults and keeps an audit ledger;
   nothing is ever removed without a ledger entry; the signed generation is never removed
   automatically; a ticket that never closed keeps its artifacts.

Plugin capability, decided by the fact of what a dsh client plugin is (261030):

- A dsh client plugin is a real package: it declares `dsh.client`, injects the client
  runtime and UI slots, mounts through the console profile, and takes effect on console
  restart. It runs in the console page context, so no iframe can isolate it.
- Therefore a project that needs dsh capability gets **Form B**: a dsh client plugin,
  mounted per project, loaded at console startup, treated as **trusted code** — the same
  stance as project external workflow templates (trusted registrant plus fault
  containment; OS-level isolation is not done and is booked as debt).
- A project that needs no dsh capability gets **Form A**: a sandboxed page bundle inside an
  isolated frame. The console hands it a minimal read-only contract: ticket, artifact,
  round, bytes, theme. No sign authority, no main-page reach.
- A project view that fails to load, throws, or is switched off degrades to the built-in
  view of the same kind, and the frame says so. It never leaves a blank panel.

View kinds. Six built-in views are the console's default registration:
`image`, `text`, `structure`, `diff`, `ledger`, `external`. A kind says what the human does
with the artifact, not what it looks like. Domain identity lives in the artifact `id` and
`title`. An unknown kind degrades to the `external` card. Unknown kinds are recorded and
visible, so the built-in set can grow from evidence instead of guesswork.

## Work breakdown (scope, not tickets)

Base layer — no project coupling:

1. **Artifact declaration.** Structured descriptor replacing bare paths (id, title, kind,
   source, repo, stage, note, open hint, shape hint, optional flag). Old `string[]`
   accepted, kind guessed from the extension, no back-fill.
2. **Inventory and frame.** The console lists declared artifacts with round, size and time;
   renders the machine verdict, the original-bytes link and the source label; handles an
   unknown kind; caps what it opens in the page.
3. **Built-in views.** The six kinds above, plus the degrade card.
4. **Progress face.** Per-stage grouping, latest round, delta against the previous round,
   and the in-progress rule: read-only, partial allowed, labelled as partial, never used
   for a red-green call and never used as the signed version.
5. **Archive and retention.** Pointer instead of copy when the project already owns the
   bytes; per-ticket cap that keeps the newest rounds; project-declared retention and
   cleanup policies; audit ledger per removal; fail-closed when archiving fails.
6. **Plugin channel.** Project registration declares its view plugins; discovery,
   per-project scope, load and degrade. Form A (sandbox page bundle) and Form B (dsh client
   plugin), with the rule that a failing plugin affects only its own project and never the
   built-in views.

Consumers and later layers:

7. **Sandbar's own lanes.** dev-lane, then light-lane, then quickmanual-lane consume the
   base with built-in views only.
8. **Human gate review board.** A lane declares which artifacts sit side by side at the
   gate and what is compared against what; comments land on the gate. This waits until real
   project views exist.

## Non-goals

- No online editor, no 3D viewer, no media player inside these layers. The console provides
  the isolated frame and the channel; what runs inside a frame is the project's business.
- No change to the machine-gate verdict rules and no change to the sign path.
- No artifact content in git or in the page's main DOM.
- No OS-level isolation for Form B plugins this cycle.

## Debts booked with this epic

- Form B needs a console restart to take effect (same as external workflow templates:
  register per project, load at startup, no hot load).
- Form B is trusted code: the frame rules are enforced by review and audit, not by a
  technical boundary.
- Agent session transcripts are the largest current archive cost (sandbar: 1.2G of 1.8G).
  They are outside this epic and need their own retention decision.
