---
title: "Ticket Workflow Console Design v0.3"
category: design
tags:
  - ticket
  - workflow
  - collaboration
status: deprecated
updated: 2026-09-28
---

> **Note 2026-08-23**: this document is an archived design from the M1 era. The
> `server/tickets/<id>.json/md` projection scheme described in it has been superseded — the
> source of truth for a ticket is always the Temporal workflow (v2 templates as code,
> ticket-start/list/query), and the projection directory plus the ticket_migrate/import-migrate
> tools have been deleted; project separation goes through the ProjectKey search attribute
> + the `server/projects.yaml` registry. The operating surface (op list, state machine,
> UI matrix) still follows this document.

# Ticket Workflow Console Design v0.3

> 2026-08-20 inception (user: "this is too primitive right now — build a UI that lists the
> session's current tickets programmatically; behind a ticket there is actually a workflow, and
> different kinds of work have different flows, possibly with several agents handing off to
> each other").
> Not dependent on the dsh admin shell — three independent layers (data/engine/UI); the carrier
> decision is recorded in §6/§7.
> v0.2 (2026-08-20): added §8–§13 (template catalog / API contract / UI spec / migration /
> linkage / implementation waves), distilled from this wave's actual run.
> v0.3 (2026-08-20): disposition of the qa review (pipeline/output/wf_design_qa_260820/README.md,
> 2 blocker + 13 major + 17 minor) —
> added the "epic proposal (human only)" stage (A4.1 blocker), resolved the final-review→publish
> action-matrix deadlock (A3.2 blocker), extended the allowlist with hot-update data keys (A1.1),
> moved visual authority to the steward (A1.4), worktree base ref / entry snapshot (A2.1/A2.2),
> stage_state writer contract (A3.1), acceptor ≠ executor (A5.1), fanout shard aggregation (A5.2),
> final review reads proposal §6 mechanically (A5.3), revision counter (A4.2), etc.; the complete
> disposition is in §14.

## 1. Problem

Current state: a ticket = `server/tickets/<id>.md` (```json block + body), its state lives in file
fields that get edited by hand, and the flow lives in people's heads; different kinds of work have
different flows (content production / code lane / proofreading / regression / cleanup), and
multi-agent handoff relies entirely on the steward dispatching agents one by one. The result:
handoff state is unclear (this wave was called out by the user: Hou Hanshu was closed but final
review was never signed, and the two-track bookkeeping caused a misreading), and there is no way
to see at a glance "all current tickets, how far each one has got, who is working on it, and where
it is stuck".

## 2. Goals

1. **Programmatic console**: one command / one page lists all the session's current tickets
   (status/stage/role/progress).
2. **A ticket carries a workflow**: a workflow template defines the stage chain; different flows
   use different templates, and a ticket only fills in instance data.
3. **Multi-agent handoff**: a stage = role + acceptance checklist + artifacts; after advance, the
   dispatch instruction for the next handoff is generated automatically (it can fan out to several
   agents, and the merge point is passed only once all of them have settled).
4. **UI actions**: see progress, advance a stage, dispatch the next handoff, tick acceptance,
   rework, mark as waiting on the user.

## 3. Data model

```
Workflow (template, server/workflows/<id>.yaml, read-only)
  id, name, description
  stages[]:
    - id
      role          # editor/developer/proofreader/qa/analyst/ops/artist/dispatcher
      name, description
      acceptance[]  # acceptance checklist (pre-written; the agent self-checks when settling, steward/qa re-check)
      fanout        # 0/1: whether it can fan out to several agents (e.g. content batches, multi-object review)
      next          # the next stage id on normal advancement (none = terminal state)
      exit          # optional: exit condition before the terminal state (e.g. human final review)

Ticket (source of truth = structured, server/tickets/<id>.json; md is downgraded to an export/render layer)
  id, title, workflow_id, role
  status: dispatched → settled → verified → closed / rework (keeps the existing state machine)
  stage: current stage id (index into workflow.stages)
  stage_state: running | awaiting | awaiting-human | blocked
  log[]:   {ts, status|stage, note}      # status stream (already present today)
  handoffs[]: {stage, agent_id, summary, artifacts[]}   # handoff record: who did it, what was handed over
  acceptance: [] # current-stage acceptance ticks {item, done, by}
  pending[]:     # pending items (leftover issues; not force-changed back to the assignee — aligned with the current discipline)
  worktree:      # the persistent lane bound to the ticket (mandatory for code-type worktree workflows)
                 # created once and reused across agent sessions: if this run's agent dies, the next one
                 # still uses the same worktree and all intermediate artifacts/branch changes are still there
                 # (260820 evidence: the mastery-m0/instr-audio lanes were reused losslessly after a restart)
```

- Compatibility: existing md tickets are imported once into json (import script); md can keep being
  generated by the engine as a human-readable snapshot; all new reads and writes go through json.
- Proposal linkage: the stages of a content-type workflow map directly onto the proposal state
  machine (proposal→epic proposal→processing→machine QC→AI review⇄revision ≤2→final review→publish),
  with the final-review stage's exit = human.

## 4. Engine (server/tools/)

- `workflow.py` (new tool): `workflow list/show` — template directory scanning with
  self-registration (hot-plugged the same way as tools_registry).
- `ticket.py` extensions:
  - `list {status?, workflow?, role?}` — returns structured data (including stage progress),
    no longer just summary lines.
  - `create {workflow, ...}` — attach a template; initial stage = stages[0].
  - `advance {id, note?}` — the current stage's acceptance passes → write handoff → advance along
    the template's next; if exit = human before the terminal state, stage_state = awaiting-human
    (the UI marks it "waiting for your signature").
  - `dispatch-next {id}` — the steward clicks a button: generate a dispatch instruction from the
    next stage's role (role spec path + handoff artifact paths + acceptance checklist) and return a
    prompt that can be pasted into dispatch_<role>.
  - `rework {id, note}` — rework (back to the previous stage or to dispatched).
- The state machine is unchanged (dispatched→settled→verified→closed/rework); stage_state is the
  progress dimension, and the two are orthogonal: closed only means "merged in", whereas
  awaiting-human means stuck on a human's final review — the "Hou Hanshu is closed but the final
  review was never signed" misreading from the last wave is now shown directly on the console as a
  stage/exit label instead of relying on a note.

## 5. UI (ticket workflow console, in the form of a dsh plugin — the user decided: make it a dsh plugin, independent of the existing admin shell)

The plugin package follows the same scheme as the existing server/plugins/ui/ (node.ts host
registration + frontend bundle), but with a name of its own (e.g. suyou-workbench) and without
piggybacking on sandbar-admin-ui; it is loaded through the profile's plugin config line.
The page is a single page with three zones:

1. **Console zone**: ticket cards/table — id | workflow | stage progress bar (the stage chain with
   the current position highlighted) | current role | status colors (running green / awaiting
   yellow / awaiting-human blue / blocked red / done gray).
2. **Detail zone**: lane diagram (stages laid out horizontally, arrows = next, the current stage
   highlighted, fanout drawn as branches) + acceptance checklist ticks + handoff timeline
   (who → handed over what) + log stream + pending items.
3. **Action zone**: advance / dispatch the next handoff (dispatch-next generates the instruction) /
   rework / mark as waiting (awaiting-human) — only the actions available for the current state
   are shown.

Backend API: a unified plugin prefix — `GET /suyou-workbench/api/wf/tickets` (console),
`GET /suyou-workbench/api/wf/tickets/<id>` (detail),
`POST /suyou-workbench/api/wf/tickets/<id>/advance|dispatch-next|rework` (actions, which write an
admin.log audit record).
Auth: reuses loopback + the layered admin token (the same as the current serve.py); hardening comes
at deployment time.

## 6. Landing waves

| Wave | Content | Acceptance |
|---|---|---|
| M1 data + engine | 5 workflow templates (content production / code lane / proofreading / regression / cleanup) + ticket migration to json + workflow.py + ticket.py extensions (list/advance/dispatch-next) + **worktree bound to the ticket** (code-type templates require the persistent lane .worktrees/t<id>, and the dispatch instruction pins a "reuse the lane" clause) | all 10 existing tickets import with zero loss; structured list output |
| M2 UI | **the dsh plugin suyou-workbench**: three-zone console page + API | the console lists all current tickets and can advance one of them all the way through |
| M3 integration | dispatch-next wired to dispatch_<role> (one-click prompt generation), proposal state-machine linkage, full migration of historical tickets, CLAUDE.md ledger entries |

## 7. Decision points (decided 2026-08-20)

1. **Storage**: source of truth = JSON, md downgraded to an export. ✅
2. **UI carrier**: make it a dsh plugin (a name of its own, without piggybacking on the admin
   shell). ✅
3. **Handoff automation**: semi-automatic (the steward clicks "dispatch the next handoff" to
   generate the instruction, then launches the agent). ✅
4. **Lane persistence** (added by the user): every task should have its own worktree; even if the
   agent on that worktree fails this run, the next run still uses the same worktree and the changes
   are still there — the ticket↔worktree binding goes into the data model (§3) and the dispatch
   instruction (§4, the dispatch-next pinned clause). ✅

## 8. Workflow template catalog (6 in the first version, all distilled from this wave's actual runs)

> **260904 host order (retirement note)**: this section is the first-version design draft (templates
> were hot-plugged yaml back then). The current regime is "templates as code" (source of truth = the
> workflow classes under `engine/`, with yaml as a generated snapshot), and
> **the content-pipeline / proofread / regression / cleanup templates are retired**; of the ticket
> templates only **dev-lane** remains (the non-ticket inspection dispatcher-scan is not part of the
> ticket template surface and is kept); independent regression after a ticket has merged in
> (regression) is now carried out either by integration running it directly on the main side or by
> opening a dev-lane. The yaml below is the historical design as originally written, kept for
> context; it no longer reflects the current state.

Templates live in `server/workflows/<id>.yaml` (hot-plugged the same way as tools_registry: drop in
a file and it is live).

```yaml
# Template 1: content-pipeline content production (proposal-based, mapping the pipeline/proposals state machine)
id: content-pipeline
name: content production
lane: main           # the main-tree data track (books/json/wiki hot-update layer), no worktree created
stages:
  - id: propose
    role: editor
    name: proposal
    acceptance: ["the proposal file lands in pipeline/proposals/<id>.md", "status=proposal, machine QC checklist enumerated"]
    next: approve
  - id: approve
    role: dispatcher
    name: epic proposal
    exit: human       # "the epic proposal is human-only" is a non-delegable red line (QA A4.1): the proposal header status=proposal→epic proposal is changed by a human
    acceptance: ["proposal header status=epic proposal (changed by a human)"]
    next: process
  - id: process
    role: editor
    name: processing
    acceptance: ["back up to /tmp/ before touching data (QA A4.4)", "the four-artifact set / source-expansion artifacts are in place", "lint_residue zero residue", "zero banned-word hits"]
    next: machine-qc
  - id: machine-qc
    role: editor
    name: machine QC
    acceptance: ["every script in the machine QC checklist of proposal §3 is green (QA A4.3; cite the proposal rather than keeping a separate checklist)"]
    next: ai-review
  - id: ai-review
    role: proofreader
    name: AI review (cross-model)
    fanout: 1         # can fan out to several reviewing agents; acceptance is sharded per agent, and the merge point is passed only when every shard is fully ticked (QA A5.2)
    revision_to: process  # the rework target follows stage semantics (QA A4.2): review revisions go back to processing, not mechanically to the previous stage
    acceptance: ["report = severity + location + iron-rule clause", "revision_count ≤ 2 (over the limit, rework with to_stage=approve, back to the epic proposal)"]
    next: final-review
  - id: final-review
    role: dispatcher
    name: final review
    exit: human       # exit condition: only a human can sign (proposal §6)
    acceptance: ["proposal §6 final-review signature (read mechanically from the proposal file, QA A5.3)"]
    next: publish
  - id: publish
    role: dispatcher
    name: publish gate
    acceptance: ["the publish chain reruns fully green (verify_lane content track)", "build_shelf final assembly + books.json book-set format validation (mid-state detection, QA A4.5)"]
```

```yaml
# Template 2: code-lane code lane (worktree persistence)
id: code-lane
name: code lane
lane: worktree       # the lane .worktrees/t<short-slug> must be created and reused across sessions (if the agent dies, the changes are still there)
stages:
  - id: develop
    role: developer
    name: development
    acceptance: ["inside the write-set allowlist (including hot-update data keys, QA A1.1 wording)", "back up app/public/data/*.json first / keep it reconcilable", "tsc --noEmit fully green", "every change point has its matching smoke test/probe passing (add one if there is none, QA A1.5)"]
    next: verify
  - id: verify
    role: dispatcher
    name: steward acceptance
    acceptance: ["verify_lane green light (must be rerun once merge conflicts are resolved, QA A1.2)", "qa diff review passes (intent matches / no scope creep / nothing unrelated smuggled in, QA A1.3)", "conflicts are coordinated by the steward and resolved with the original author's judgment (QA A2.4)"]
    next: visual
  - id: visual
    role: dispatcher
    name: SHOTDEBUG visual verification   # authority split (QA A1.4): build/screenshot/revert belong to the steward; qa produces the checkpoint checklist and judges the screenshots
    acceptance: ["every pre-written screenshot checkpoint from qa passes (written into the instance checklist at create time, QA A1.6)", "revert injection + clean rebuild (executed by the steward)"]
    next: close
  - id: close
    role: dispatcher
    name: merge in
    acceptance: ["commit recorded", "CLAUDE.md ledger entry", "lane cleanup: delete the branch + tear down the worktree after close (kept for reuse while active, including rework, QA A2.5/A1.7)"]
```

```yaml
# Template 3: proofread review (independent cross-check, see v0.1's five-layer anti-hallucination scheme)
id: proofread
name: proofreading
lane: main
stages:
  - id: review
    role: proofreader
    name: review
    fanout: 1
    acceptance: ["read-only, no changes to business files", "the report contains severity/location/iron-rule clause"]
    next: report
  - id: report
    role: dispatcher
    name: triage
    acceptance: ["blocker/major→open a rework ticket (back to content-pipeline process or code-lane develop)", "minor→attach to pending"]
```

```yaml
# Template 4: regression acceptance (wave merge-in)
id: regression
name: regression acceptance
lane: main
stages:
  - id: regress
    role: qa
    name: independent regression
    acceptance: ["verify_lane all green", "the full smoke suite rerun independently", "diff re-checked against the write-set allowlist"]
    next: report
  - id: report
    role: dispatcher
    name: conclusion
    acceptance: ["list every red item with its ku/file + reason"]
```

```yaml
# Template 5: cleanup data cleanup (provenance repair)
id: cleanup
name: data cleanup
lane: main
stages:
  - id: clean
    role: editor
    name: cleaning
    acceptance: ["clean_inline extensions do not break the existing order", "the backup lands in /tmp first", "lint zero residue"]
    next: rederive
  - id: rederive
    role: editor
    name: re-derivation (fill in notation / re-scrape / rerun generators)
    acceptance: ["QC fully green", "all other artifacts byte-for-byte undisturbed"]
```

```yaml
# Template 6: building the workflow itself (this design lands through it)
id: build-workbench
name: platform construction
lane: worktree
stages:   # expanded into the same stage list as code-lane (QA B5: do not use shorthand, which is invalid YAML)
  - { id: develop, role: developer, name: development, next: verify }
  - { id: verify,  role: dispatcher, name: steward acceptance, next: visual }
  - { id: visual,  role: dispatcher, name: SHOTDEBUG, next: close }
  - { id: close,   role: dispatcher, name: merge in }
```

## 9. Engine API contract (server/tools/, hot-plugged)

```
workflow list                          → [{id, name, stages:[{id,role,name,next,exit,fanout,revision_to}]}]
workflow show {id}                     → the full template text

ticket list {status?, workflow?, role?, stage_state?}
    → {count, tickets:[{id, title, workflow, stage, stage_state, status, role,
                        updated, handoff_count, pending_count, worktree, proposal_id}]}
ticket show {id}                       → full text (including handoffs/acceptance/pending/log)
ticket create {workflow, title, body?, proposal_id?}
    → automatically stage=stages[0].id; code-lane registers a worktree (short slug: t<prefix>-<alias>, QA A2.3)
      + base ref = main-tree HEAD (QA A2.1) + initial stage_state=awaiting (QA A3.1)
    → the instance acceptance = a copy of the template checklist, editable per ticket (QA A5.5)
ticket accept {id, item, done, by, evidence?}
    → by is injected from the caller's identity and may not be self-filled; evidence = raw script output / artifact path (QA A5.4)
ticket advance {id, note}
    → validate: every acceptance item is ticked ∧ the by of every done ≠ the current stage role (QA A5.1)
    → fanout stage: every shard fully ticked (QA A5.2); a second call on the same stage errors out (idempotent, QA A5.5)
    → exit=human and reaching final-review/publish: read the proposal §6 signature mechanically (date + conclusion, QA A5.3)
    → hard validation of revision_count (QA A4.2)
    → write handoff → stage=next → stage_state = exit==='human' ? 'awaiting-human' : 'awaiting'
ticket dispatch-next {id}
    → generate the dispatch instruction (JSON): {role, prompt:[role spec path, handoff artifact path list, acceptance checklist,
       worktree clause (code-lane must contain "reuse .worktrees/<slug>, do not recreate; before starting, report a git status
        snapshot to the steward + fetch main and rebase onto the latest, QA A2.2/A2.1"), ticket id, commit-in-small-steps clause]}
    → also sets stage_state=running (QA A3.1)
ticket rework {id, to_stage?, note}
    → the default target follows stage semantics: ai-review→revision_to=process (QA A4.2), everything else back to the previous stage
    → status=rework, stage=to_stage, stage_state=awaiting (QA A3.4)
ticket import-migrate {dir?}           → one-off: md→json (import all existing tickets; the count is whatever it is at implementation time, QA B1)
```

**stage_state writer contract** (QA A3.1, hard-coded to prevent drift):
create→awaiting; dispatch-next→running; the agent settles (ticket update settled)→awaiting (steward acceptance window);
blocked is set explicitly by an agent/the steward (with a reason attached, only allowed while status∈{dispatched,settled,rework}, QA A3.5);
rework→awaiting; advance→awaiting / awaiting-human.

**Invariants** (validated on the engine side, QA A3.3/A3.5/A3.6):
- `status=closed ⇒ stage_state≠awaiting-human` (the human gate is cleared before close; migration leftovers are
  history display only, with a one-way exit = rework back to final-review→signature→advance→publish)
- awaiting-human is only allowed on a stage with exit=human; blocked is only allowed on an active stage.

The state machine (status) is unchanged; `stage_state` is the progress dimension (§3). The combination of the two
drives the UI action matrix (§10).

## 10. UI spec (the dsh plugin suyou-workbench)

**Plugin wiring** (a name of its own, without piggybacking on the admin shell):
- `server/plugins/workbench/`: node.ts (host registration, the same `webServer.register` pattern as
  sandbar-admin-ui, mounting the same-origin `/suyou-workbench/api/*`) + src/ (the three-zone frontend
  page) + tsdown.config.ts (lib/client.js bundle).
- Loaded through a profile plugin line; audit goes to admin.log (reusing the run-id mechanism).

**Three zones on the page**:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ Console: ticket card grid                                                               │
│  [content] Hou Hanshu L0  ▓▓▓▓▓▓░░░░ final review(awaiting-human)                       │
│  [code]    songs-wiring   ▓▓▓▓▓▓▓▓▓▓ merge in(done)                                     │
│  [review]  proofread      ▓▓▓▓░░░░░░ triage(awaiting)                                   │
│  Filters: status▾ workflow▾ role▾                                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ Detail drawer (click a card to expand)                                                  │
│  Lane diagram: proposal→processing→QC→review→[final review●]→publish (fanout=review⊕⊕)  │
│  Acceptance checklist: ☑☑☑  Handoff timeline: editor→proofreader→(you)                  │
│  pending: 3 items   worktree: .worktrees/t<id>                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**Status palette**: running green (an agent is working on it) / awaiting yellow (waiting for the steward to dispatch) /
awaiting-human blue (waiting for your signature) / blocked red (stuck, with a reason attached) / done gray. The
"Hou Hanshu-style misreading" of closed+awaiting-human is now shown directly on the card as the
"final review(awaiting-human)" label instead of relying on a note.

**Action button matrix** (only available actions are shown, by status×stage_state; QA A3.2 resolves the deadlock and A3.4 adds the rework row):

| status \ stage_state | running | awaiting | awaiting-human | blocked |
|---|---|---|---|---|
| dispatched | — | dispatch next / rework | — | retry / rework |
| settled | — | acceptance(accept)+advance | **final review signature→acceptance+advance** (QA A3.2) | rework |
| verified | — | dispatch next | **final review signature→advance** (QA A3.2) | — |
| rework | — | dispatch next (by the rolled-back stage's role) / rework | — | retry |
| closed | view | view | history display: view (one-way exit = rework back to final-review, sign→advance→publish, QA A3.3) | — |

## 11. Migration (md→json)

- One-off script `server/tools/ticket_migrate.py`: reads the ```json block of `server/tickets/*.md` →
  converts it into `server/tickets/<id>.json` (fields mapped directly + log kept as-is + handoffs
  backfilled from the log summaries).
- Example mapping for the 12 existing tickets: t260820-mastery-m0 → code-lane (stage=develop already done),
  t260820-hanshu-l0 → content-pipeline (stage=final-review, stage_state=awaiting-human),
  t260820-後漢書-proofread-返工 → content-pipeline (reworking at stage=process)... all of them can be classified.
- md is kept as an export snapshot (refreshed after every engine write), so the human-readable path is never broken.

## 12. Linkage

- **Proposal state machine ↔ stage**: content-pipeline's propose/**approve**/process/machine-qc/ai-review/final-review/publish
  maps one-to-one onto the pipeline/proposals README state machine (7 states, 7 stages, QA A4.1); when advancing to final-review,
  the UI explicitly prompts "go and sign proposal §6"; once signed, advance→publish triggers the publish chain
  (build_shelf etc., executed by the steward); a Ticket carries `proposal_id` (QA A4.6), and advancing to
  final-review/publish reads the proposal header status and §6 mechanically.
- **dispatch-next ↔ dispatch_<role>**: the generated instruction is exactly the prompt triad of dispatch_<role>
  (role spec + ticket + acceptance), which the steward copies and uses as is (semi-automatic); in M3 this can become a
  one-click UI call to dispatch_<role>.

## 13. Implementation waves (refined)

| Wave | Task | Acceptance |
|---|---|---|
| M1a | 6 workflow template yaml files (per v0.3, including the approve stage) + ticket_migrate.py (import all existing tickets; the count is whatever it is at implementation time) | zero-loss import; structured ticket list output |
| M1b | workflow.py + ticket.py extensions (accept/advance/dispatch-next/rework) + the stage_state writer contract + invariants (closed⇒¬awaiting-human etc.) + add dispatcher to the role enum (QA B3) | use 1 real ticket to run advance+dispatch-next end to end |
| M2 | the suyou-workbench plugin: three-zone page + /suyou-workbench/api/wf/* + action matrix (including the awaiting-human advance and the rework row) | the console lists all tickets; advance one of them through a full loop |
| M3 | dispatch-next one-click call to dispatch_<role>; proposal linkage (proposal_id + mechanical §6 read); CLAUDE.md ledger entries | end to end: ticket creation→handoff→final review→publish all completed on the console |

## 14. qa review disposition record (v0.3, corresponding to pipeline/output/wf_design_qa_260820/README.md)

| QA item | Disposition |
|---|---|
| A3.2 blocker final-review→publish matrix deadlock | §10 matrix settled/verified×awaiting-human gains "final review signature→advance(advance)" ✅ |
| A4.1 blocker missing human gate for the epic proposal | template 1 gains an approve(exit=human) stage; §12 changed to 7 states, 7 stages ✅ |
| A1.1 allowlist inconsistent in three places | template 2 develop acceptance extended with "including hot-update data keys"; the verify_lane allowlist extended with {app/public/data/*.json} (M1 companion) ✅ |
| A1.2 rerun verify_lane after merge | template 2 verify acceptance changed to "must be rerun once merge conflicts are resolved" ✅ |
| A1.3 qa diff review has no landing point | template 2 verify acceptance adds "qa diff review passes" ✅ |
| A1.4 visual overrides the qa red line | the visual stage role changed to dispatcher (qa produces checkpoints + judges; the build belongs to the steward) ✅ |
| A2.1 worktree base ref missing | create registers base ref = main-tree HEAD; the dispatch-next clause adds fetch+rebase ✅ |
| A2.2 no snapshot at the agent-fail entry point | the dispatch-next clause adds "before starting, report a git status snapshot to the steward" ✅ |
| A3.1 stage_state writer undefined | §9 adds the writer contract (create→awaiting etc.) ✅ |
| A3.3 closed+awaiting-human self-contradictory | §9 invariant status=closed⇒stage_state≠awaiting-human; migration leftovers have a one-way exit ✅ |
| A3.4 matrix missing the rework row | §10 adds the rework row; §9 rework semantics (status=rework/stage/awaiting) ✅ |
| A4.2 revision ≤ 2 has no counter / reworks to the wrong stage | Ticket gains revision_count; ai-review pairs with revision_to=process; over the limit goes back to approve ✅ |
| A5.1 acceptor = executor | advance validates done.by ≠ the current stage role; accept by is identity-injected and may not be self-filled ✅ |
| A5.2 fanout aggregation undefined | fanout acceptance is sharded per agent, and the merge point is passed only when every shard is fully ticked ✅ |
| A5.3 no mechanical check on the final-review signature | advance reads proposal §6 mechanically (date + conclusion) before letting it through ✅ |
| A2.3/A2.5/A1.7 lane naming and cleanup | short slug naming; cleaned up at close, kept while active ✅ |
| A4.3/A4.4/A4.5/A4.6 proposal-side details | cite the proposal §3 checklist / backup clause / publish refinement / proposal_id ✅ |
| A1.5/A1.6/A3.5/A3.6/A5.4/A5.5/B1–B5 | the corresponding places were changed (smoke wording / instance checklist / invariant / transition table / evidence / idempotence / number drift / stale example / role enum / API path / template 6 expanded) ✅ |

## Related documents

- Platform Architecture Design (./平台架构设计.md) — §13 editing workflow; this document is its implementation. (Note: that document is not in this repository.)
- [admin-dsh application plan](../ops/admin-dsh-application-plan.md) (practice reference: dsh as the carrier)
- [Knowledge Base Design](./knowledge-base-design.md) (practice reference: block diff review)
- [Multi-role collaboration agent mechanism based on DeepSeek Harness and Temporal](./deepseek_harness_and_temporal_based_multi-agent_mechanism.md) (the overall outline: this document is the refined implementation of its R1/R5/R6)
