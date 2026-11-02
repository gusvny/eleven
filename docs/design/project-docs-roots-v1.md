---
title: Per-Project Documentation Roots v1 (one or many, per repository; the index kept outside the repository)
category: design
tags:
  - docs roots
  - documentation
  - knowledge base
  - multi-repository
  - judged surface
status: active
updated: 2026-11-03
related:
  - mode: practice reference
    target: design-doc-writing-guide.md
    note: the four-section admission standard this document was written to
  - mode: context
    target: knowledge-base-design.md
    note: what a documentation root holds, and what the machine index is
  - mode: dependency
    target: sandbar-project-onboarding-contract-v1.md
    note: where a project's declaration and its data directory outside the repository are defined
  - mode: dependency
    target: develop-buffer-v1.md
    note: the judged-surface exclusion is what the certification uses to reuse a test baseline; this document changes what that exclusion is keyed on
  - mode: context
    target: ticket-workflow-console-design.md
    note: the project registry and the console surfaces that read a project
---

# Per-Project Documentation Roots v1 (one or many, per repository; the index kept outside the repository)

> Audience: whoever onboards a project, whoever maintains the console's documents view, and whoever
> maintains the gates that read documentation.
> This document states **what the rule is and why**; the mechanics belong to the implementation tickets.

## Problem

**One sentence:** the place where a project keeps its documents is fixed to one directory name in
six separate readers, so a project whose documents live anywhere else cannot be onboarded without
five of those readers staying silently wrong.

**Background knowledge (what an outsider needs first):**

- A **documentation root** is a directory inside a project's repository that holds the project's
  finalized documents.
- The **machine index** is a structured list of those documents — where each one is, and its title,
  category, tags and status. The console and the knowledge feature read the index instead of walking
  the tree on every request. Today the index is generated into the repository, next to the documents,
  and committed with them.
- Six **consumers** read "where the documents are", and each one decides it on its own: the console's
  documents view, the knowledge feature, the inspection side's mechanical document checks, the index
  builder, the certification's baseline decision, and the lint and scenario rules that speak about
  document paths.
- A project may hold more than one repository. Today's consumers assume one repository and one
  directory directly under it.
- The **judged surface** is the set of files whose change means "a test baseline built on an older
  revision cannot be reused". That suite is expensive, so a revision that leaves the judged surface
  unchanged reuses the previous baseline. Prose that no test reads is excluded from that surface, so
  that editing a document does not pay for a full rebuild.

**Evidence — six hard-coded calibers (measured 2026-11-03, this repository):**

1. **The console's documents view.** Its two scope names are fixed to the documentation directory and
   the notes directory (`server/plugins/workbench/src/host/docs.ts:29`). A project that keeps documents
   elsewhere has no way to appear in the view.
2. **The knowledge feature.** It fixes the project's primary repository plus the documentation
   directory, and inside that directory it fixes the machine index, the index build script and the
   review store (`server/plugins/knowledge/node.ts:190`, `:207`, `:347`).
3. **The inspection side, in two constants.** The mechanical document checks fix the documentation
   root and the consistency checks that walk it against the index
   (`server/engine/inspection_doc_mech.py:135`), and the declaration reader fixes a default root
   (`server/engine/inspection_decl.py:124`).
4. **The certification's judged surface.** The certification excludes content from the judged surface
   by a fixed list of **directory names** — the documentation directory, the notes directory and the
   engine's workspace (`server/engine/develop_certify.py:1333`).
5. **Lint and scenario rules.** Several rules key on the documentation directory as a path prefix
   (`integration/sc_check_inspection_produce_chain.py:63`, `server/engine/agent_activities.py:9920`).
6. **The index builder.** It scans four fixed category subdirectories under the documentation root —
   design, content, ops and reference (`docs/scripts/build_index.py:4`, `:26`) — and the inspection
   side's document checks use the same four category names (`server/engine/inspection_doc_mech.py:140`).
   A moved root makes the builder scan nothing and report an empty library, so the project looks like
   it has no documents at all.

**Why one setting would leave five calibers wrong:**

- The six readers are independent. None of them asks another one where the documents are. One new
  setting would be read by the reader that was changed, and ignored by the other five.
- The five failures are silent, and they do not look alike. The view lists no documents. The knowledge
  feature answers that the project has no documents. The mechanical checks go green because they walk
  a directory that holds nothing. The index builder reports an empty library. The certification
  quietly changes what it judges.
- This is not hypothetical. One of the six already carries its own root setting: the inspection side
  lets one kind of inspection instance name its documentation root, and that setting has never moved
  the other five. A knob of exactly the kind we would add already exists, in one consumer, and the
  other five still hard-code the name.
- The calibers also do not agree in kind. Some name the directory. One names the directory and three
  items inside it. One treats the directory as a path prefix. One excludes the directory by name. One
  enumerates four fixed subdirectory names under it. One value cannot satisfy all of those shapes
  unless a single place resolves it for all of them.

**Why the judged-surface caliber is the dangerous one:**

- The other five fail visibly in the end: somebody looks for a document and does not find it. The
  judged surface fails silently, in both directions.
- **First direction, cost.** A root that moves away from the excluded name is no longer excluded.
  Document-only edits then count as a change to the judged surface, so every prose edit forces a full
  baseline rebuild. Nothing is wrong with the documents, and nothing says why the suite got slow again.
- **Second direction, false green.** The exclusion is a list of names, so it can also exclude a
  directory that is *not* documentation in a new layout. A wrong exclusion is a hole: the suite becomes
  green about content it never looked at. This is why each entry in that list carries a reason today.
- Both directions have one cause. The exclusion is keyed on a directory **name**, while the truth is a
  declared **path**. Names and paths can disagree, and the disagreement has no error path.
- **Multi-repository projects cannot be expressed at all.** A project whose documents live in two
  repositories, or in two places inside one repository, has no way to say so, and no way to see both in
  one view. Its second root is simply invisible.

## Requirement

**Goals (verifiable):**

1. A project can declare **zero, one or many** documentation roots. Each entry names one repository of
   the project and one path inside that repository. One entry is the ordinary case; several entries
   cover a project whose documents live in more than one repository, or in more than one place inside
   one repository.
2. **Every consumer follows the declaration.** For a project that declares a non-default root, all six
   calibers read that root: the documents view, the knowledge feature, the mechanical document checks,
   the index builder, the certification's judged surface, and the lint and scenario rules. Verified by a
   project with one non-default root and a project with two roots, and by the absence of any consumer
   that reaches a documentation directory by name on its own.
3. **No declaration means today's behaviour, byte for byte.** A project that declares no documentation
   roots and that has a documentation directory at its repository root has that directory as its
   **implied default root**: the documents view, the machine index and the gates behave exactly as they
   do today, and nothing about that project changes.
4. **Every configuration lands in one of three states, and none of them is silent.**
   - No declaration, documentation directory present → **served** at the implied default root: the view
     shows the documents, each one naming the root it came from.
   - No declaration, no documentation directory → **refused by name**: the consumer says the
     documentation root is absent and names what it looked for.
   - Declared and present → **served**; declared, present and holding no documents → **present but
     empty**, and the view says so and names the root it searched; declared and absent, or present and
     unreadable → **refused by name**, naming the declaration that produced it and the path that was
     looked for.
   A project that has documents is never shown as empty. A project that has none is never shown as
   silently empty either. The two cases stay distinguishable to a reader. No consumer falls back to a
   default directory, and none renders an empty view for a missing root.
5. **The machine index is a derived artefact, and it lives outside the repository.** It is produced from
   the documents alone; rebuilding it from unchanged documents gives the same result; deleting it loses
   no information; its home is the project's own data directory, outside every repository of the
   project; a copy of it inside a repository is never read as the truth.
6. **The index is rebuilt on the inspection's schedule, never on the read path.** The documentation
   inspection is what rebuilds it, in its own periodic pass; opening the documents view never triggers a
   rebuild and never waits for one. A reader can always tell which of three index states it is looking
   at: **absent** (never built yet), **stale** (a rebuild is due — the view says so, gives the time of
   the last build, and never presents that content as current), and **rebuild failed** (named, with the
   reason, and the old index is never served as if it were fresh). An operator may ask for an immediate
   rebuild; that is an explicit act, never the default path.
7. **A moved root never silently changes what the judged surface excludes.** The exclusion is computed
   from the resolved roots. A move either keeps the judged set's meaning — documentation content stays
   not-judged, everything else stays judged — or it stops with a named refusal. No consumer adds a
   directory name to the exclusion list to make a move work.
8. **Multi-repository projects work with one root or with many.** There is one documents view per
   project, showing the merged set of its roots. Every document keeps a stable identity that includes
   its repository and its root, so two roots that hold the same relative path do not shadow each other;
   such a collision is named, never silently dropped.
9. **A refusal is actionable without reading code.** It names the project, the declaration behind it
   (when there is one), and the path that was looked for.
10. **The declaration is the only place where a documentation location is declared.** No engine path, no
   scenario rule and no console default carries a project-specific location.
11. **Adding a consumer must not add a caliber.** A new consumer asks the same resolution step; a
    consumer that finds the root by directory name is a defect, even when the name happens to be right.
12. **Optional LLM-facing projections are derived artefacts too, and they are a per-project choice.**
    For a project that wants its documentation readable by an LLM without going through the console, the
    same scan may also emit an entry list sized for an LLM and a full-text variant, beside the index and
    from the same documents. They follow the same rules as the index: derived, rebuildable, never the
    truth. Whether such a projection is committed to a repository is declared by the project together
    with its roots. It is never an engine default, and a project that declares nothing gets none.

**Stakeholders and what they care about most:**

- **Host** — onboarding an existing project without moving its documents, and no project-specific
  hard-coding inside the engine.
- **Project owner** — one place to declare where the documents live, and one view that shows which roots
  are in effect.
- **Reader** — never an empty screen that is really a missing directory.
- **Integration and the gates** — the judged surface keeps its meaning after a move, and no false-green
  hole opens in it.
- **Agent** — documents usable as context, and an explicit refusal instead of a silently empty index.

**Upfront constraints (must not be broken):**

- No existing project changes behaviour or layout. The change is **additive**: a project with a
  documentation directory at its repository root behaves as it does today, declared or not.
- Documents stay plain text files inside their repository. No format change, no move of content.
- The index is never a truth source: every gate that reads it today must work when it is absent or
  freshly rebuilt.
- A declared root is a path inside its own repository and cannot leave it: relative, no parent
  segments, no absolute path. This lexical discipline already exists for the one root setting that is
  deployed, and it is kept.
- The engine stays project-agnostic: it reads declarations and never project names.
- The notes knowledge base keeps its current behaviour this round.
- A refusal never degrades into an empty answer, and no consumer keeps a silent fallback to the default
  name.
- The documentation inspection is the only automatic writer of derived documentation artefacts. A reader
  never writes one, and no gate depends on a derived artefact being present.

## Nongoal

- **Not bringing the notes knowledge base into the declaration this round.** Observations keep their
  current location and their current readers. They join in a later round, after the documents case has
  proven the shape; declaring them now would mean designing both rules before either has been used.
- **Not migrating existing documents.** No file moves, no rewrites, no forced reorganisation of any
  project's document tree. A project that is happy with its current directory keeps it.
- **Not a new document format.** The same plain text pages with the same frontmatter. The index is
  derived; the documents are not restructured to suit it.
- **Not cross-project document search.** One view per project over its own roots. Searching across
  projects is a different feature with different permissions, and it is not this one.
- **Not moving the documents out of the repository.** Only the index moves out. The documents stay
  versioned together with the code they describe.
- **Not turning the documents view into an editor.** It stays read-only this round.
- **Not removing the judged-surface exclusion, and not judging prose.** The exclusion keeps its reason;
  only the key it uses changes.
- **Not a general multi-repository rework of the console.** This document covers the documentation root
  only. Other surfaces that assume one repository are separate work.
- **Not a per-consumer setting.** Six settings that must agree is the shape this document removes, not
  the shape it introduces.
- **Not rebuilding the index on the read path this round.** A read that silently refreshes state looks
  convenient and costs predictability, failure handling and a write in every reader. Freshness belongs
  to the inspection pass, or to an explicit operator rebuild.
- **Not deciding for a project whether an LLM-facing projection is committed.** That is declared with
  the roots, per project. The engine has no opinion and no default.

## Proposal

### High level: one declared fact, one resolution, every consumer through it

The project's declaration gains a list of documentation roots. An absent or empty list means "no
declaration". Each entry names one repository of the project and one path inside that repository.

One resolution step turns that declaration into the set of roots in effect for a project, and every
consumer asks that step. The resolution is the only place that knows the rules — the implied default,
the three states, the refusal wording, the ordering of roots. Consumers never derive a root from a
directory name again.

Why a resolution step and not a shared setting: a shared setting already exists in one consumer, and it
never moved the other five. What is missing is a single place all six pass through, because that is
also the only place where the default-off promise, the three states and the judged-surface rule can be
guaranteed **once** instead of six times.

**How each consumer reaches it:**

- The documents view resolves the project's roots when it renders, and shows one merged view.
- The knowledge feature resolves them for listing, opening and reviewing a document.
- The mechanical document checks resolve them per project, so the index consistency walk follows the
  declared places.
- The index builder resolves them before it walks the categories, so it scans the declared places and
  the four category names under them, never four directories under a guessed root.
- The certification resolves them to compute the judged surface.
- Lint and scenario rules either resolve them, or speak of "the declared root" instead of a literal
  name.

### The three states, as one rule

- **No declaration, documentation directory present** → the implied default root. Today's behaviour,
  byte for byte. The system must not report this project as having declared anything.
- **No declaration, no documentation directory** → a **named refusal**. The consumer says the
  documentation root is absent and names what it looked for. It never renders an empty view as though
  the project simply had no documents, and it never falls back to another directory.
- **Declared, absent or unreadable** → a **named refusal** that names the declaration and the missing
  path.

A declaration that is malformed or unreadable is refused the same way. The whole point of the rule is
that a reader can tell "no documents" from "documents not found".

### The derived index: produced from the documents, kept outside the repository

- The index is produced from the documents, per project, and its home is the project's own data
  directory, outside every repository. It is rebuildable at any time from the documents alone.
- **When it is produced: the documentation inspection.** The periodic inspection pass rebuilds it, in
  the pass that already reads the documents. No read path rebuilds it: opening the documents view never
  starts a rebuild and never waits for one. The reason is that a read must stay cheap and predictable,
  and a read that silently repairs state is a read that can fail for reasons the reader did not ask
  about.
- **An operator may ask for a rebuild now.** That is an explicit act with its own record. It is not the
  default path, and it does not make the read path responsible for freshness.
- **Three index states, and the view says which one it is in:**
  - **absent** — never built yet;
  - **stale** — a rebuild is due; the view says it is stale, gives the time of the last build, and never
    presents that content as current;
  - **rebuild failed** — named, with the reason, and the previous index is never served as if it were
    fresh.
- It is never a truth source. A gate that requires the committed index, or a check that compares the
  index with itself, would put a derived artefact back into the truth path, which is the defect this
  rule removes.
- **The same scan may emit LLM-facing projections beside the index.** Where a project wants its
  documentation readable by an LLM without going through the console, the scan can also produce an entry
  list sized for an LLM and a full-text variant. These are derived artefacts of the same family, with the
  same rules: produced from the documents, rebuildable, never the truth. Whether such a projection is
  committed to a repository is a per-project choice declared together with the roots. It is never an
  engine default, and a project that declares nothing gets none.
- What it buys: a project can keep documents in any directory without the index contradicting it;
  document edits stop touching a generated file, so a repository diff stays human; a project that does
  not want generated files in its repository still gets a view; a reader sees a rebuilt index without
  the read paying for it; and losing the data directory costs a rebuild, never content.
- What it costs: freshness is as good as the last inspection pass, so a document edit is visible in the
  index only after the next pass or an operator rebuild — which is why the view must say "stale, last
  built at ..." instead of quietly showing older content as current.

### The judged surface follows the declaration, never a name

- The judged surface is the whole tree **minus the resolved documentation roots**, plus the entries that
  already carry their own reason.
- A project without a declaration keeps exactly today's exclusion, which is the implied default root.
- Because a root is a path inside its repository, the exclusion is expressible as a path — exactly and
  only.
- The exclusion may cover documentation and must never cover code. A declaration that would exclude a
  path the suite reads is **refused by name**, not excluded: a wrong exclusion is a false-green hole.

### What a reviewer sees

- The documents view names the roots in effect for the project — which repository, which path — and the
  state it is in: served, present but empty, or refused. A refusal appears in place of a listing, with
  the declaration behind it and the path it looked for.
- The project's declaration is visible where the project itself is declared, so a reviewer can compare
  what was declared with what the view actually used.
- The documents view says which index state it is in: absent, stale with the time of the last build, or
  rebuild failed with its reason. A stale index is labelled, never passed off as current.
- The certification's report names the judged surface it used, so a reviewer can see whether a
  documentation root was excluded or not.

### Reconciliation rules a reader must not get wrong

1. **The declaration says where, not what.** It names places, never documents. An existing but empty
   root is a finding about content, not a refusal about configuration.
2. **The default is implied, never written.** A project with a documentation directory and no
   declaration has the default root in effect. Nothing rewrites the project's declaration to say so, and
   nothing reports it as declared.
3. **Refusal and emptiness are different answers.** There are three states and no fourth. Mapping a
   refusal onto an empty view is the failure this change exists to remove.
4. **The index is a cache; the documents are the content.** Any rule that makes the index part of the
   truth is wrong, however convenient it looks.
5. **The inspection rebuilds the index; a reader never does.** "The view would be fresher if the read
   rebuilt it" is not a reason. A read that repairs state fails for reasons the reader never asked
   about.
6. **Stale is a state to display, not a licence to show.** A stale index is shown as stale with the time
   of the last build. It is never mixed into the view as though it were current, and an index that could
   not be rebuilt is a named failure with its reason — not an empty library, and not silently the old
   one.
7. **A projection is derived and optional.** An LLM-facing entry list or full-text variant is produced
   the same way the index is, and it never becomes a second truth. A project that declares nothing gets
   none, and no engine default commits one to a repository.
8. **The judged surface is keyed on resolved paths, never names.** If somebody has to add a directory
   name to make a move work, the move is wrong, not the list.
9. **Identity includes the root.** Two roots may hold the same relative path. Both documents exist, and
   the view names which root each one came from.
10. **The notes knowledge base is outside the declaration this round.** A declaration covers
    documentation roots only; a reader must not read it as covering observations, and the notes behaviour
    must stay exactly as it is.
11. **One consumer, one resolution.** A consumer that reaches a documentation directory by name is a
    defect even when the name is currently correct, because the next project is where it breaks.

### How this ties back

This proposal addresses the **Problem** by removing the single hard-coded name from all six calibers
and replacing it with one declared fact and one resolution step, and by moving the derived index out of
the repository so that a project's document layout stops being entangled with a generated artefact. It
makes the silent multi-caliber failure impossible, because a consumer can no longer have its own answer,
and it makes the judged surface key on declared paths, which is the only way the cost direction and the
false-green direction of that failure both close.

It satisfies the **Requirement** as follows: goals 1 and 10 by the declaration being the only place a
location is declared, and by admitting zero, one or many entries that each name a repository and a path;
goal 2 by every consumer, including the index builder, passing through the one resolution; goal 3 by the
implied default root keeping today's behaviour byte for byte for a project with a documentation
directory and no declaration; goal 4 by the three distinguishable states — served at the implied
default, present but empty, and refused by name — with refusals that name the project, the declaration
and the path looked for, and with no fallback to a default directory; goal 5 by the index being derived,
out of the repository and rebuildable from the documents alone; goal 6 by the index being rebuilt by the
documentation inspection rather than on the read path, with the three index states a reader can tell
apart and an operator rebuild that is explicit rather than default; goal 7 by the judged surface being
computed from resolved roots, so a move either keeps its meaning or stops with a named refusal; goal 8 by
one merged view over roots whose identity includes repository and root; goal 9 by the refusal naming what
was looked for; goal 11 by making a new consumer ask the same resolution rather than add a seventh
caliber; and goal 12 by making any LLM-facing projection a derived artefact of the same family, emitted
only where a project declares it.

It avoids the **Nongoal** items by not touching the notes knowledge base this round, not migrating any
existing document, not changing the document format, not adding cross-project search, not moving
documents out of their repositories, not turning the view into an editor, not removing the judged-surface
exclusion or judging prose, not reworking the console's other single-repository assumptions, not
introducing six settings that must agree, not rebuilding the index on the read path, and not deciding
for a project whether an LLM-facing projection is committed.

## Related documents

- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document
  follows.
- [Knowledge Base Design](knowledge-base-design.md) — what a documentation root holds, the human index
  and the machine index, and where this document sits in the document-first workflow.
- [Sandbar Project Onboarding Contract v1](sandbar-project-onboarding-contract-v1.md) — the project
  declaration, its repositories, and the per-project data directory outside the repository.
- [Develop Buffer v1](develop-buffer-v1.md) — the certification that reuses a test baseline, and
  therefore the owner of the judged surface this document re-keys.
- [Ticket Workflow Console Design](ticket-workflow-console-design.md) — the project registry and the
  console surfaces that read a project.
