---
title: "Sandbar project onboarding contract v1"
category: design
tags:
  - sandbar
  - contract
  - onboarding
  - schema-version
status: active
updated: 2026-09-28
---

<!-- Truth-source declaration (host ruling 260904): this file IS the contract truth source — documents
     under the sandbar repo are governed by this repo. The same path in the suyou repo (v1.7, the
     original from the t260903-08 period) is downgraded to a historical frozen artifact: kept for
     sedimentation reference only, never evolving, and no process may treat it as a modification
     target. Consumers: the sandbar installer `sandbar upgrade` / `sandbar doctor` (M2-C code ticket
     t260903-10).
     Since the M2 migration into sandbar this file evolves in this repo: from v2.0 it carries the
     no-SKIP integration gate of t260904-12 (②a supply declaration, ②b-1 three-state protocol,
     ②b-2 env_fail field).
     Note: this English version is the sandbar-side translation, and the Chinese text of this contract
     still lives in the suyou repo (see the truth-source declaration above for the governing copy). -->

# Sandbar project onboarding contract v1

> sandbar is an "IDE" — a multi-project ticket engine that installs on its own and upgrades on its
> own. A project onboards by registering with the IDE; upgrading the IDE affects neither the
> development nor the use of any project. This document defines **the entire contact surface (the
> contract) through which a project onboards the IDE**: five items are promoted to official status,
> each with a schema version number and closing semantics. Everything beyond those five items is
> sandbar internal implementation, may change at any time, and carries no stable promise.
> The structural skeleton of the contract is in this document; the field-level definitions of the
> various declaration files are added once the configuration tickets land, and field details are not
> part of this contract text.

## Problem

### What is wrong today

1. The engine lives inside the project repo (`server/`): the engine reads the project, and the
   project carries the engine. The IDE's own upgrades are coupled dead to the development and use of
   the project — upgrading the IDE means touching the project repo, and upgrading the project means
   following the engine.
2. The contract is not written down: there is no contract file under `docs/`, no `verify.yaml`, no
   `.sandbar/` workspace declaration. The later "in-place inversion" and "physical relocation"
   tickets have no prior basis — nobody knows which files the engine should read a project through,
   or what a project should provide.
3. Project-specific policy checks (for example, "if src changed, the bundle must be rebuilt") have no
   stable home: they are either hard-coded into the engine (which does not hold for another project)
   or scattered around and held together by discipline alone.

### Background

- **The sandbar epic proposal**: turn the whole ticket-driven development apparatus into an
  independent, general-purpose IDE; the key move is to **invert the dependency direction** — today
  the engine reads the project, while the target shape is a project registering with the IDE, with
  not a single line of engine code left in the project repo. The route is "contractize → in-place
  inversion → physical relocation", and the order cannot be reversed.
- **Separation of mechanism and policy**: the engine provides only the mechanism (run the
  integration tests the project declares, judge red or green), while the check content comes from
  the project (policy). `server/merge-checks.yaml` is the pioneer sample that already proves this
  route: policy is externalized into the project repo, the engine reads the file, and with no file
  the policy takes no effect.
- **schema version**: each contract surface declares a version number. Versioning is the
  precondition for decoupled upgrades — when the IDE upgrades it must know which syntax version the
  project declares, and when the project upgrades an old IDE must either recognize that version or
  explicitly refuse it.

### Evidence

- The M0 commitments and acceptance criterion 4 of the sandbar epic proposal (five promoted items +
  schema version numbers + missing file = closing semantics + context composition order).
- The current state of the repo: no contract file under `docs/`, no `verify.yaml`, no `.sandbar/`
  workspace declaration; `merge-checks.yaml` is the only externalized-policy sample that has landed.

## Requirement

Each of the following is verifiable and is an acceptance criterion of this document:

1. The contract promotes exactly five items, no more and no less: ① project registration and
   directory model; ② policy configuration and integration test declaration; ③ role persona
   override; ④ epic proposal content location; ⑤ tool bridge protocol. Each item carries a schema
   version number.
2. The closing semantics of each item covers three states with explicit criteria:
   - **missing**: the file does not exist, or it exists without that declaration = that gate closes,
     and the engine must not carry built-in default project policy;
   - **malformed**: the file exists but cannot be parsed, or its structure is invalid = fail-closed,
     with an explicit error naming which file and which check failed; it must not be silently
     treated as "no declaration";
   - **version unknown or higher than the engine supports** = fail-closed, with an error stating the
     version the project declares and the version range the engine currently supports.
3. The docs context composition order is written down: the docs of the repo the agent is in ⊕
   project-level docs; IDE docs do not enter project ticket context.
4. It states explicitly which surfaces are the stable contract (the five items) and which are
   sandbar internal implementation (the six template subclasses, the plugin API, the `.suyou`
   internal layout); internal implementation may change at any time.
5. There is a contract change record mechanism: every contract change is recorded, appended inside
   the document.
6. The upgrade decoupling mechanism is written down: semver + keeping the old reading for the first
   N versions of a deprecation + a compatibility matrix. The compatibility matrix promises only the
   mechanism (the definition of axes and cells, and the rule of appending with versions); it does
   not pre-fill cells beyond v1.
7. "The contract surface is the upgrade burden, and promotion waits for a real demand from a third
   project" is written down: surfaces beyond the five items do not enter the contract until a real
   project need appears.

## Nongoal

- **No engine/configuration implementation**: the verify.yaml parser, the persona merge code, and the
  three-state verdict implementation are all work for later configuration tickets; this contract
  defines only "what it is and why".
- **No full field-level schema definition**: this document writes the structural skeleton and the
  semantics of each item; field-level definitions land with the configuration tickets and are not
  part of this contract text.
- **No upstreaming into dsh, and no changes to the six template subclasses or the plugin API**: they
  belong to the internal implementation surface and may change at any time.
- **No pre-filling of compatibility matrix cells**: v1 has exactly one verified cell (schema v1 ×
  the current IDE version); empty cells are left for real verification results and must not be read
  as promises of support.
- **No definition of the details of policy isolation between projects**: the concrete implementation
  of "registering a project does not trigger other projects' policies" is internal implementation;
  the contract only guarantees that the contact surface is stable.

## Proposal

### High level

The contract = the entire contact surface for a project registering with the IDE. When the project
changes, all it needs to provide is the five declarations and the files carrying them; all the IDE
must guarantee is the reading semantics of those five (including three-state closing). Everything
else — how templates are implemented, what the plugin API looks like, how the `.suyou` directory is
laid out internally — is inside sandbar; projects neither touch it nor should depend on it.

```
Project repo                          sandbar (IDE)
┌──────────────────────────┐          ┌────────────────────────────────┐
│ Project registration and │ ───────▶ │ ① registration: single/multi-   │
│   directory model        │          │   repo, three-level docs        │
│   (registration decl.)   │          │ ② policy: verify.yaml           │
│ .sandbar/                │ ───────▶ │   (integration test decl.)      │
│   verify.yaml            │          │   merge-checks.yaml             │
│   merge-checks.yaml      │          │   (extension checks)            │
│   persona override       │ ───────▶ │ ③ persona three-layer merge     │
│ Epic proposal content    │ ───────▶ │ ④ epic proposal location        │
│ Tool bridge entry decl.  │ ───────▶ │ ⑤ tool bridge invocation        │
└──────────────────────────┘          └────────────────────────────────┘
        Beyond those five ⇄ IDE internals: no contact either way
```

Trade-off: deliberate restraint. The contract surface is the upgrade burden — every item promoted
means the IDE carries one more compatibility obligation whenever it bumps a version. So v1 promotes
only the five items the epic explicitly needs: better to keep internal implementation flexible than
to lock down something that will change as a promise.

### Closing semantics: the three-state overview

The closing semantics of each of the five items is uniformly judged by three states, and the engine
implementation must not deviate:

| State | Criterion | Engine behavior |
| --- | --- | --- |
| missing | The file does not exist, or it exists without that declaration | That gate closes: nothing is executed, no error is raised, the remaining gates continue. The engine must not carry a default policy built in for any project. |
| malformed | The file exists but cannot be parsed, or its structure is invalid | fail-closed: an explicit error naming which file and which check failed; the corresponding gate of that ticket turns red, and it must not be silently skipped as "missing". |
| version unsupported | The declared schema version is unknown, or higher than the engine supports | fail-closed: the error states the version the project declares and the version range the engine supports; no guessing at interpretation. |

The "missing" state is not a degradation path but the intent of the declaration: the project says
explicitly "this gate does not apply". Malformed and version-unsupported mean the project spoke but
the IDE cannot understand it — in that case it is better to refuse to run than to run on a guess.
The current "no such file = no extension checks" semantics of `merge-checks.yaml` is exactly the
missing state, and this contract brings it into the three-state frame with unchanged behavior.

### ① Project registration and directory model (schema: v1)

**What it is**: a project declares its own directory structure when registering with the IDE. Two
key points:

- **A project = a directory**. A single-repo project is one repo directory; a multi-repo project
  uses a parent directory as the project directory, with each repo as a subdirectory. Tickets and
  lanes land in some repo; the epic proposal and project-level policy hang on the project directory.
- **Three-level docs hierarchy declaration**: a project declares its own docs levels — IDE docs
  (sandbar's own documentation, serving sandbar development only), project-level docs (under the
  project directory, shared across repos), and repo-level docs (under each repo subdirectory). The
  location of each level is declared at registration.

**Why it is stable**: this is the anchor of the dependency-direction inversion. "A project registers
with the IDE" holds only if the IDE can mechanically know which directory is which project, which
repo belongs to which project, and at which levels the docs live. If the directory model is
unstable, the inversion has nowhere to land.

**Closing semantics** (per the three-state overview): the IDE does not serve an unregistered project
(the boundary case of the missing state — the registration declaration itself is the precondition
for onboarding); a malformed registration declaration or an unsupported version = fail-closed.

#### ①a per-key directory model and loading semantics (schema v1, landed with the out-of-repo ticket t260901-14)

This section is the carrier-level truth source of ①. Shape of the registry after it moved out of the
repo (sandbar M1-1): **one project, one directory**, with the machine-level root directory
`~/.sandbar/projects/` (the env `SANDBAR_PROJECTS_DIR` may override it), the registry entry = a
`project.yaml` inside the directory, and loading = scanning the project.yaml of each project
subdirectory under the root directory. Entry file format (a strict minimal YAML subset):

```
schema: v1            # required; missing = malformed, non-v1 = version unsupported (the error states the declaration and the supported set)
project:
  - key: <key>        # must be exactly equal to the containing directory name; both the directory name and the key pass the key whitelist
    name: <name>
    dirs:
      - /abs/path     # the first one = the main directory
```

Loading semantics (the engine must not deviate):

- **Per-entry isolation**: one `project.yaml` that is malformed or of an unsupported version = that
  project is isolated fail-closed (the error contains the `<dir>/project.yaml` locator), without
  affecting the loading of other entries; a lookup by an isolated key = an explicit error (not
  silently treated as unknown). If the root directory exists but has zero entries, or all entries are
  isolated, raise an error listing the reasons.
- **Directory conventions**: registry entries live under `projects/<key>/`; `projects/<key>/data/` is
  the reserved slot for engine data (migrated in M1-3; the metrics cache will land in
  `data/metrics/` later, with a uniform path convention, and this ticket writes nothing to disk); the
  reserved credentials slot lands in M1-2 (see ①b). Subdirectories without a `project.yaml`
  (including `data/`) are skipped at load time.
- **Migration**: automatic migration from the old single-file registry, where the skip criterion
  honors only a `.migrated` marker in the root directory. When the marker is absent and the root has
  content, three categories apply: on-disk entries that are all exact byte subsets of the
  migration-source entries = crash residue, so finish the migration and write the marker; zero
  intersection with the migration source = a hand-made registry, accept it; partially related but not
  reproducible = a mixed site, fail-closed and raise for manual handling. Never skip silently.
- **legacy compatibility**: when the env `SANDBAR_PROJECTS_YAML` points at a single file in the old
  format, load it in the old format (behavior identical to before the move out of the repo), which
  takes priority over per-key directory mode.

#### ①a-1 Removal / re-onboarding / data disposal three states (schema v1, landed with project-lifecycle epic proposal ② t260904-14)

This section defines the **removal semantics** of a registry entry (tool = `sandbar project remove`,
an installer CLI write surface). Removal = **retiring the entry, not deleting the directory**:
`<key>/project.yaml` is atomically renamed (os.replace) to `project.yaml.retired-<UTC ISO8601>` in
the same directory and stays under `<key>/` — the existing ①a semantics "subdirectories without a
`project.yaml` are skipped at load time" makes the retired entry invisible to the loader immediately,
with **zero schema change and full reversibility** (renaming the file back restores the entry;
re-onboarding = re-running `sandbar project add` with the same key, and the `data/tickets/` archive
chain stays continuous). Retired files do not participate in loading, and the loader is unaware of
multiple retired files in the same directory.

Gate order of the removal command (the engine and the tool must not deviate; any failure = fail-closed
refusal to remove, with zero site changes):

1. **Mode gate**: in legacy single-file mode (with `SANDBAR_PROJECTS_YAML` in place) it **refuses** —
   retirement/purge writes the per-key directory, which the runtime cannot read = a fake successful
   removal (same cause and same shape as `add`).
2. **In-flight gate**: Temporal is queried for running tickets by `ProjectKey`; non-empty = refuse the
   removal and report each ticket number; Temporal unreachable (including a missing SDK) = fail-closed
   refusal, **no bypass flag** (start the server first if you want to remove).
3. **Last-entry gate**: removing the last registry entry = a zero-entry warning (naming the loader's
   empty-table error semantics, ①a loading semantics) + an explicit confirmation flag; a missing flag
   means refusal.
4. **closed all-archived gate (purge precondition)**: before `--purge-data`, compute the "unarchived
   difference set" = the set of Temporal COMPLETED ticket ids − the set already archived on fs. The
   fs-side anchor = **the `<id>/archive.json` three states (the same closing semantics as ①c)**: the
   manifest is in place and parseable (including `schema: v1`) = archived; missing = unarchived (it
   enters the difference set, the yellow card lists ticket ids and purge is refused — the directory
   existing ≠ archived, and a half-finished archive must not be released to purge); malformed =
   fail-closed, red-naming `<id>/archive.json` (no silent side assignment, no silent re-production). A
   non-empty difference set = purge refused with the ticket ids listed. The TERMINATED
   (cleanup/revocation) family does not enter the difference set (ticket-list does not surface it, and
   the archive object = completed tickets).

**Explicit separation of the three data disposal states**: by default removal deletes no data —
`data/` (archive + metrics) and `credentials.yaml` are untouched byte for byte, and the removal report
accounts for byte counts item by item; only the explicit flags `--purge-data` /
`--purge-credentials` delete, and the two flags are independent and combinable; `--dry-run` rehearses
all gates without writing to disk (it prints what would be renamed/deleted: path + bytes + ticket
counts). The removal report includes the per-ticket lane list under the project root `.lane/` —
**reported only, never deleted** (lane = the space of tickets; it points to teardown/manual cleanup).
The audit truth source does not evaporate: no path may silently delete an archive.

**Single root directory criterion** (written into the tool surface): one project has exactly one root
directory, and the tool writes exactly one `dirs` entry (the schema v1 list shape is compatible;
multiple directory input = semantic refusal); multiple `dirs` entries = a legacy shape: loading
tolerates it (the first = the main directory, semantics unchanged) and the tool never produces it. A
multi-repo project = the parent directory as the root.

### ①b per-key credentials.yaml (landed with the out-of-repo ticket t260901-21)

This section is the carrier-level truth source of project credentials. The credentials truth source
moves into the project directory:
`<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/credentials.yaml`. File format = the current
`~/.dsh/.credentials.yaml` as-is — its `version` and other fields are self-managed by the dsh
credentials seam and are kept unchanged; the sandbar side adds **no** schema declaration field
(credential content does not participate in IDE upgrade decoupling; the path convention is what
belongs to this contract surface).

Read-side parsing semantics (the engine and project tools must not deviate; the Python and JS sides
are isomorphic):

1. **per-key first**: the project key passes the key whitelist (same as ①a) and
   `<root>/<key>/credentials.yaml` is a file → use it;
2. **legacy fallback** (deprecation window): on a per-key miss, fall back to the old global
   `$DSH_HOME/.credentials.yaml` → `$HOME/.dsh/.credentials.yaml`; a hit through the fallback means the
   project credentials have not been migrated and requires a visible notice log;
3. **neither present** = the project has no credentials, and the read side copies nothing (it does not
   silently create default credentials); existing error semantics (such as headless agent
   MISSING_CREDENTIAL) are unchanged.

Three-state criteria: **missing** = a per-key miss, after which fallback/no-credentials follows the
declaration, and the engine must not build in guessing logic beyond the default credential path;
**malformed** (unparseable content) = fail-closed, reported by the dsh credentials seam — the read
side only resolves paths and copies, it does not re-implement the parser; **unreadable**
(permission/owner) = fail-closed, and the copy error must contain the source path, never silently
swallowed. The engine's credential read location is unchanged (`$DSH_HOME/.credentials.yaml`); what
the out-of-repo change moves is only the **copy source** — zero downtime: without migrating the file
it still runs as usual (the fallback is the pre-M1-2 behavior).

Migration steps (documented on the write side; the write-side seam lives in the dsh-credentials-local
plugin layer, and its direct write to the per-key path is a later ticket, so this section establishes
the manual steps first):

```
mkdir -p ~/.sandbar/projects/<key>/
install -m 0600 ~/.dsh/.credentials.yaml ~/.sandbar/projects/<key>/credentials.yaml
```

The original `~/.dsh/.credentials.yaml` is kept until the legacy fallback is deleted, so that the
migration window cannot cut off supply.

### ①c per-key engine data directory data/tickets/ (landed with the out-of-repo ticket t260902-02)

This section is the carrier-level truth source for archiving completed ticket data (the body of
sandbar key decision 3). The archive truth source moves out of the repo into the machine-level
per-key data directory:

```
<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/data/tickets/<ticket_id>/
├── archive.json          # manifest (schema v1, skeleton below)
├── stages/               # .suyou/stage_*.json (stage results / settlement reports)
├── screenshots/          # .suyou/screenshots/**/*.png (UI evidence, relative hierarchy preserved)
└── sessions/             # <worktree>/.dsh/sessions/<repo-slug>/* (session on-disk event files)
```

**Why it is stable**: the root causes are "stage reports of completed tickets are lost when the lane
is torn down" + "Temporal has no upper bound on retention" (measured 2026-09-01: 31MB / 40 tickets).
The archive is IDE data, and the audit truth source belongs to the machine-level IDE data directory;
the project repo (including lane worktrees and the main tree's `.suyou/`) keeps only disposable cache
(treated like node_modules). The dev-lane wrap-up (merge-in) order is thereby fixed as three stages:
`merge` (accounting only) → `archive_ticket` (out of the repo, fail-closed) → `teardown_lane` (tear
the lane down) — a successful archive is the precondition for tearing down the lane "without losing
reports".

**archive.json manifest skeleton** (schema v1; field details are sandbar internal implementation and
do not enter the contract):

```json
{"schema": "v1", "ticket_id": "<id>", "legacy": false, "archived_at": "<ISO>",
 "meta": {…}, "files": [{"src": "…", "dst": "…", "bytes": 0}],
 "absent": [], "excluded_rules": [], "reason": "…"}
```

The archiving criteria (three families): stage result files, UI screenshots, and session on-disk
data. The **exclusion** criteria (recorded in `excluded_rules`, not archived): agent spawn runtime
logs, model/resume patches, profile mirrors, and **any `.credentials.yaml` (credentials never enter
the archive)**. Files are copied byte for byte (corrupt JSON is archived as-is; archiving does not
parse content, and the consumer judges malformed content when reading); a missing session directory =
soft handling (the manifest records it in `absent`, the same existing degradation criterion as the
usage endpoint).

`legacy: true` semantics: honest accounting of the backlog — for historical tickets where "the lane
was already torn down before archiving and the stage reports are unrecoverable", `ticket
archive-legacy` writes a manifest with an empty file list + an explicit `reason`, and **fabricates
and back-fills nothing**; `ticket prune` needs the `--allow-legacy` double flag to delete a legacy
ticket.

**Closing semantics** (per the three-state overview):

| State | Criterion | Engine behavior |
| --- | --- | --- |
| missing | `<key>/data/tickets/<id>/archive.json` does not exist | The ticket is "unarchived": prune refuses to delete (Temporal history is retained; history does not evaporate) |
| malformed | The manifest cannot be parsed / it lacks `schema: v1` | fail-closed: prune counts it as a failure and it is handled manually; when archive_ticket sees an existing malformed manifest it **does not silently re-produce it** (re-production destroys evidence) and raises it to a blocked lane without tearing the lane down |
| copy failure | The target is not writable / IO failure | fail-closed: archive_ticket raises → the ticket is blocked and the lane is kept |

### ①d project.yaml paths section: in-project path declaration (schema v1, t260903-03 landed with the engine consumption point)

This section is the carrier-level declaration of in-project paths: the engine must no longer assume
"some fixed path inside the project" (the precondition of sandbar M2 physical relocation — after the
split, the engine and the project are no longer in the same repo). A project declares an optional
`paths` section at the top level of its registry entry
`<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/project.yaml`, and the engine takes values through
the registry. There are two consumption points today: ① the role preset patch and the role
description directory (at spawn time `<lane>/server/roles/<role>.yml`; the role_doc assembled by the
prompt comes from the same source); ② the model routes table (the runtime lookup file). Declaration
shape (the same tradition as the strict minimal YAML subset of ①a):

```
schema: v1
project:
  - key: <key>
    name: <name>
    dirs:
      - /abs/path
paths:                     # optional whole section; missing = everything falls back to the current convention
  roles_dir: server/roles                   # role directory, relative to the project root
  model_routes: server/model-routes.yaml    # model routes table file, relative to the project root
  workflow_modules: mods/a.py,mods/b.py     # project-external workflow template module list (t260924-04), relative to the project root, separated by `,`
```

**schema stays v1**: purely additive optional fields, and old entries (without a paths section) parse
with unchanged behavior. It cites the ②a v1.5 ruling: errata and increments do not bump the schema
version and trigger no semver bump obligation.

**Resolution basis**: `project root` = the registry entry's `dirs[0]` (the main directory).
`roles_dir` must be a non-empty relative path (empty after strip = malformed, and so is a
whitespace-only value); absolute paths are forbidden, `..` escapes are forbidden, and `~` and
non-scalar forms (`{}`/`[]`) are forbidden; it is resolved relative to the **spawn cwd (the lane
worktree)** — preserving the semantics "the copy inside the worktree = the ticket snapshot". Since
t260910-14 `model_routes` is **relaxed to a machine-level form**: the relative-path semantics are
unchanged (resolved relative to the project main directory dirs[0], keeping the runtime truth source
with the main repo), and `~/…` (expanded to the current user's home; the suggested default is
`~/.sandbar/projects/<key>/model-routes.yaml`) and absolute paths (including Windows drive letters)
are also allowed; after expansion, `..` escapes and empty/non-scalar values are still forbidden, and a
quoted scalar is judged the same way after the quotes are stripped (the same verdict as the TS
parser; the consistency guard = the t260910-14 parity scenario).

**`inspection_decl` (t260916-02 increment, pointing to where the inspection declaration lands)**: the
same machine-level relaxation as `model_routes` (relative = joined to the project main directory
dirs[0], `~/…` expansion, and absolute paths are all allowed), but the **fallback semantics are
deliberately not copied** — an absent inspection declaration = "this project has no inspection
surface" (absent response semantics; it does not masquerade as an error and never borrows another
project's declaration); a bad shape / unreadable / `..` escape / pointing at something that does not
exist = a project-level error explicitly naming the declaration path (fail-closed; silently turning
off the inspection surface is forbidden). Without a declared `inspection_decl` → the default location
is `<project root>/inspection.yaml` (a single file, version-controlled in git; no multi-file
directory). The engine's in-repo declaration has been retired (t260916-02 migration delivery body):
the engine side keeps only the mechanism + the `docs/inspection-sample.yaml` sample template, and
sample instances enter no aggregation. Aggregation (board whitelist / missed-run check / schedule-up)
traverses registered

**`workflow_modules` (t260924-04 increment, the registration point for project-external workflow
templates)**: a `,`-separated module list, where each item is a `.py` module path relative to the
project main directory `dirs[0]` (**relative only** — `~/` and absolute forms are not allowed,
deliberately inconsistent with the machine-level relaxation of `model_routes`: template code lives in
the project repo and evolves with it, with no need for machine-level pointing). Each item is
validated as in ①d (empty item / absolute / `..` escape / non-scalar each turn red and name the Nth
item); a declaration that is present but whose anchor is missing / whose module fails to load / whose
template shape is malformed / whose template id collides / whose patch identifier collides with an
engine surface → **template-level isolation and refusal** (fail-closed, structurally naming "which
check failed + both sides of the collision"; a bad template is not registered, does not drag down
other modules of the same project or other projects, and ticket creation and resumption fail-closed).
Not declaring it = the four categories fall back, with zero behavior change. The interface shape, the
clean-module constraint, the deterministic encoding rules, and the evolution discipline (new template
ids coexist / the `workflow.patched()` patch identifier carries a `<project key>-` prefix) are in
[project-external workflow template loader v1](project-external-workflow-template-loader-v1.md).
projects read their own declarations; a cross-project duplicate instance id = an identity-ambiguity
configuration accident, removed from the aggregation whitelist with both places named (multiple hits
on the trigger surface raise the same error, and the two paths have one consistent criterion).

**Reader parsing subset (hand-written on the engine side, stdlib-only, the same criterion as the ①a
loader: values contain no `#`, and a trailing `#` starts truncation)**: the top level recognizes only
the three keys `schema:`, `project:`, `paths:`; `schema` must exist and be `v1` (missing = malformed,
non-v1 = version unsupported); inside the paths section only the three keys `roles_dir`,
`model_routes`, `inspection_decl` are recognized, and unknown keys, a section that is not a mapping,
non-scalar key values, and deeper nesting are all malformed. The entry field shape inside the
`project:` section is the ①a loader's business — the reader takes only the first `dirs` item as the
resolution basis and does not re-verify the full entry shape (the loader has already fail-closed the
same file at ticket creation/registration time; the two layers of readers do not duplicate each
other's duties).

**Four-state verdict (the engine reader must not deviate)**:

| State | Criterion | Engine behavior |
| --- | --- | --- |
| fallback | no paths section / a key missing inside the section / the entry file does not exist / the project key is empty, fails the whitelist, or the project is unregistered | That item falls back to the current convention (`server/roles`, `server/model-routes.yaml`), byte-for-byte identical to before the move out of the repo. suyou declares no paths, zero change and zero regression |
| malformed (declared value) | the declared value is not relative / `..` escape / empty or whitespace-only / non-scalar / the paths section is not a mapping / unknown key | fail-closed: an explicit error containing the entry file path and the key name, no silent filtering (the same outline as ②c) |
| malformed (entry file) | project.yaml exists but its top-level shape cannot be parsed (unknown top-level key, schema missing or not v1, non-UTF-8) | fail-closed: the error names `<key>/project.yaml` and the reason, with **no fallback and no silence** — during spawn stages the only reader of this file is this reader, and skipping it as "missing" is exactly the run-on-a-guess the three-state overview forbids |
| declared anchor missing / misplaced | after resolution `roles_dir` does not exist or is not a directory | fail-closed red: the error names the resolved absolute path |
| `model_routes` declared-surface defect (changed to soft fallback by t260910-14) | the declaration points at a missing file (file_missing) or unparseable content (bad_content); not declared (decl_missing) | layered read-side fallback (host risk order 260910): if the in-repo `server/model-routes.yaml` exists it takes over **reading** (the write surface/UI still points at the declared path), and it **must be named and logged** (state+path+reason; silent fallback to the profile default is forbidden); if the fallback is also missing → the lookup falls back to the profile default, likewise logged. The truth source = the file the declaration points at (the engine reads it, the UI reads and writes the same source; python `resolve_routes_table` × TS `resolveRoutesFilePath` judge identically) |

**Anchor vs content**: fail-closed covers only the declared anchor itself, not the content semantics
of the declared object. Two boundary rulings are written down with this section: ① a declared
`roles_dir` where a specific role's yml/md is missing = the existing soft skip is kept (a missing
patch degrades to the default persona, contract ③ "add only, never change"); ② a declared
`model_routes` table that exists but has no entry for a role = the lookup function returning empty is
kept (the agent uses the profile default model). Same outline (revised by t260910-14): the **content**
of a declared `model_routes` table being unparseable no longer silently inherits the lookup tolerance
— it is upgraded to a named bad_content state (per-state logging, KI-030 narrowed): after the log/UI
names state+path+reason, the read side falls back to the in-repo table or to the profile default (the
agent can still run, never silently). The four states of this section cover only declared values and
anchors; a table with no entry for a role still keeps the lookup function returning empty (the
default model).

**Transitional state**: the current registry loader (`server/tools/ticket.py` entry parsing
whitelists only `schema:` and `project:` at the top level; `server/project-registry.ts` is isomorphic)
refuses a top-level `paths:` section under the rule "only two keys at the top level" — until the
relaxation ticket lands, any project declaring paths is isolated per-entry by ①a (fail-closed and
visible, not silent). **The semantics of this section take effect only once the loader-relaxation
ticket lands**; suyou declares no paths and is unaffected. The engine-side consumption points (spawn
taking the role directory and routes table path, prompt assembling role_doc) already take values per
this section, and the fallback state matches the current convention.

### ② Policy configuration and integration test declaration (schema: v1)

**What it is**: a project declares two kinds of policy files in its workspace (the conventional
directory `.sandbar/`):

- **verify.yaml — the integration test declaration**: the entry command, red/green criteria, and
  timeout of the integration tests. The integration stage of dev-lane is pure mechanism: it runs the
  integration tests the project declares and judges red/green by the declared criteria, with no
  project-specific judgment smuggled in by the engine. sandbar tests its own install/wiring/upgrade,
  suyou tests its own four-piece suite; neither smuggles in the other, and each project brings its
  own content.
- **merge-checks.yaml — extension checks**: project-specific extensions of the merge check gate (the
  current `server/merge-checks.yaml` is an instance of this sample: if the src prefix changed while
  the out prefix did not, it is red). Format constraint: the minimal YAML subset that the engine's
  built-in parser understands, with bare tokens for all values.

**Why it is stable**: this is where "separation of mechanism and policy" lands, and it is the final
answer to the problem that "checks are project-relative". If check content were written into the
engine, it would not hold for another project; only when declarations enter the contract can the
engine genuinely achieve zero project-specific logic. Schema versioning lets the engine know which
syntax version to read by when it upgrades.

**Closing semantics** (per the three-state overview, with the t260903-01 erratum aligned to the
engine): the whole verify.yaml file missing = **two paths**: ① the code lane closes per the project
declaration (green items visible, not silent); ② the integration lane **fails closed with an error**
— the integration lane has no "missing = closed" state, and any invocation of the lane is judged (see
②b). The old criterion "with no integration tests to run, the integration stage uses the existing
no-op criterion" is void (after the engine was thinned to a shell, missing means err, not no-op).
merge-checks.yaml missing = no extension checks, consistent with current behavior (the missing
state); a malformed file or an unsupported version = fail-closed, with the error naming the file and
the check item.

### ②a verify.yaml field-level definition (schema v1 truth source; landed t260901-08, rewritten per the implementation by t260903-01)

This section is the field-level truth source of ②. The declared value `v1` ↔ the engine's reading
`'v1'` (exact string comparison), supported set = {"v1"}. The carrier location is chosen by the
project's own registration (suyou registers at the repo root `verify.yaml`; the `.sandbar/` of the
contract examples is not a mandatory path).

**schema stays v1 ruling** (v1.5): the v1.1 version of this section carried a five-type keyed field
table (the retired distorted keys: `checks.shotdebug.file`/`checks.deps_dir`/`checks.tsc.cwd`/
`checks.smoke.dir` and `integration.entry`/`integration.red_green.*`) — the engine **never
implemented** that shape, so it was documentation running ahead of the implementation. The current
engine reading has been list-command style from the start (see the table below). This rewrite takes
the implementation as the truth source; it is an erratum rather than a broken published syntax, so
the schema version is not bumped and no semver bump obligation is triggered.

| Field | Type | Semantics | When the key is missing |
| --- | --- | --- | --- |
| `schema` | bare token, supported set {v1} | syntax version declaration | malformed (the version is the precondition for onboarding; no guessing) |
| `lanes.code.write_allow` | non-empty prefix/path list (block list or inline `[...]`) | the coarse criterion for the code lane's write-set whitelist; when the merge gate passes a ticket's write_set it judges per ticket, and this criterion covers manual invocation. The `.suyou/` and `.dsh/` engine runtime directories are never judged | malformed (declaring the code lane means declaring the write-set boundary; no guessing) |
| `lanes.code.checks` | non-empty list `[{id, cmd, cwd?, timeout?}]` (**list-command style**, no type vocabulary) | code lane command checks: `id` = human-readable name; `cmd` is executed via `/bin/sh -c`, and a non-zero exit = red; `cwd` is relative to the declaration root (default `.`); `timeout` is in seconds (default 600). All entries run in parallel | that item closes (the whole key may be omitted; present but structurally invalid = malformed) |
| `integration.cmd` | non-empty string (one command) | the only declaration of the integration lane: the engine runs it with `/bin/sh -c`, cwd = the declaration root; the red/green criterion = exit code + the ②b three-line protocol parse; the overall timeout env is `SANDBAR_INTEG_BATCH_TIMEOUT_SEC` (default 5400) | the whole integration stage missing = the integration lane fails closed (②b: this lane has no "missing = closed" state); the stage present but `cmd` missing or empty = malformed fail-closed |
| `integration.supply` | optional list `[{need, cmd, cwd?, timeout?}]` (the t260904-12 supply declaration system, final draft §7.4) | integration test environment supply: `need` = human-readable gap name; `cmd` = one **idempotent assembly command** that the engine runs before integration.cmd (implemented since v2.1), where failure/timeout = explicitly red and names the need (no silent continuation); `cwd` is relative to the declaration root (default `.`); `timeout` is in seconds (default 900) | **key missing = zero declarations is legally empty** (a project without supply needs simply does not declare it; a precheck failure inside a scenario naturally surfaces as ENV_FAIL, ②b-1) |
| `ui_evidence` | optional mapping `{dirs, supply?}` (the t260904-18 KI-050 declaration system; `dirs` = a non-empty list of strings, the UI screenshot evidence directories (repo-relative prefixes); `supply` = **a reserved field, not consumed by this version of the engine**, and declaring it is not a guarantee of screenshot supply) | the directory criterion for UI screenshot evidence at the merge gate: merge_check 3.6 and ui_changed_paths judge a UI ticket by "actual diff paths × dirs" and look for screenshot evidence under `.suyou/screenshots/`; it replaces the old engine-side `UI_WRITE_PREFIXES` five-path hard-coding (that constant survives only as a compatibility fallback for old-ticket replay/frozen branches and is no longer the live-path truth source) | **key missing = the screenshot evidence item is absent per the project declaration**: merge_check 3.6 emits that item green + a visible note (not SKIP, not fake green; the behavior stays visible); `ui_evidence` present but with an illegal shape (not a mapping / dirs missing or not a non-empty string list) = malformed fail-closed red (intercepted at both verify_lane `_validate_cfg` and merge_check 3.6; malformed ≠ default) |

Any unknown key (top level / `lanes` / `lanes.code` / within a checks entry, including the old
five-type keyed form) = malformed fail-closed, with no silent filtering. `ui_evidence` is a legal
top-level key added by t260904-18 (the engine-side whitelist and the `_validate_cfg` shape validation
landed in the same ticket), and the unknown-key discipline still applies to keys other than it.

Missing-state mapping (the criterion after the erratum, to prevent misreading): **the whole
verify.yaml file missing = ① the code lane closes per the project declaration (t260901-08 extension;
green items visible, not silent) + ② the integration lane fails closed with an error (t260903-01
erratum; see ②b)**. The former is the intent of the declaration, the latter is the semantics of the
engine's "any invocation of the lane is judged"; neither is a degradation path, and the engine must
not fall back to any built-in default policy on that basis.

### ②b Output contract = the entire programmable contact surface of the verify lane for the onboarder (entered into the contract in v1.5)

#### ②b-1 The integration lane's "output contract three lines" (a character-level sub-contract of integration.cmd)

The scenario executor (the project-side implementation of integration.cmd) outputs per the
**three-state protocol** (t260904-12 no-SKIP-ization inside the gate; final draft =
notes/discussions/260904-charter-injection-invalid-payload.md §7.3: at scenario level there is only
PASS / FAIL / ENV_FAIL, and the "clean SKIP for a missing environment (exit 0)" semantics is
retired):

1. `PASS [scenario name]` —— one scenario is green;
2. `FAIL [scenario name] exit=<code>` —— one scenario is **product-red**; the **four-space indented
   line** after it is that scenario's output tail (the engine collects it line by line, truncated to
   4000 characters);
3. `ENV_FAIL [scenario name] exit=2` —— one scenario is **environment-red** (nothing was verified and
   the cause is attributed to the environment: missing dependency / isolation bench / credentials /
   playwright, etc.; what is missing is written in its indented output tail), with the line-leading
   word `ENV_FAIL` and the mandatory `exit=2`; a format mismatch (a missing `exit=`, or an unknown
   leading-word combination) follows the FAIL line's malformed convention and counts as name=the
   whole line, exit=-1 —— malformed output is not silently swallowed;
4. the last line `SCENARIOS ran=N pass=N fail=N env_fail=N na=N` —— the summary line, whose five
   counts enter the contract literally; `na` is the scenario-level placeholder for the sub-case-level
   N/A state (N/A is already folded into pass/fail inside a scenario and is always 0 at the executor
   level); **the bidirectional net criterion: ran=pass+fail+env_fail must hold, and any inconsistency
   = the summary lies and counts as product red exit 1** (the executor self-checks; engine-side
   reading and checking land with the B-part ticket, and until then the engine carries the red
   semantics via "a non-zero exit is never green").

Sub-case-level semantics inside a scenario (the project-side convention of the executor's criteria):
N/A is given only to sub-cases conditioned on **system state** (not on the test environment); a
missing environment is always ENV_FAIL; **a scenario whose sub-cases are all N/A = product red**
(nothing verifiable = a scenario design/coverage problem; fix the scenario, not the environment).

Red/green criteria (mechanically executed by the engine, zero project policy):

- **green = the executor exit code is 0 and the parsed fail=0 and env_fail=0 and the summary and
  details are bidirectionally net**.
- A non-zero exit is never green: rc=1 (product red) goes to rework; rc=2 (environment red) goes to
  supply repair —— engine-side env/product attribution routing is mechanized with the B-part ticket
  (verify_lane env_fail counting), and before that attribution is done manually in arbitration; no
  result line at all (ran=0) with rc≠0 = the **err state** (neither red nor green): the executor
  produced no result, which is a fault of the test lane itself and is raised to arbitration.
- **zero-scenario green**: ran=0 and rc=0 = green (ran=0, pass=0, fail=0, env_fail=0). The engine
  **does not enforce** the stdout protocol —— without the protocol you get zero-scenario green, and
  this is a fact the engine does not verify (a risk surface); an onboarder's self-check must include
  at least one guaranteed-red scenario. **The integration lane has no "missing = closed" state like
  the code lane (see ②a); to express "this lane has nothing to do", declare one always-succeeding
  empty command (such as `cmd: true`) and get zero-scenario green —— that is the only closing idiom
  of this lane.**
- **err semantics**: err non-null ⇒ green is always false and ran/pass/fail/env_fail are meaningless.
  "The verification itself did not run" (verify.yaml missing/malformed, cmd missing or empty, overall
  executor timeout, zero results) and "it ran but scenarios are red" are two kinds of results, and
  consumers route test-lane faults versus scenario reds accordingly.

#### ②b-2 verify_lane per-lane return shape (JSON API)

- **content/code lane**: `{lane, green, red_count, checks:[{check, level,
  items:[{detail}], note?}]}`, level ∈ {red, green}, red_count = the sum of the red items' items.
- **integ lane**: `{lane, green, ran, pass, fail, env_fail, scenarios:[{name, exit,
  output_tail}], err}` (v1.8 adds `env_fail`; until the B-part ticket lands the engine does not yet
  produce that key, and consumers read it as a field that may be absent); every failure path returns
  `{lane, green:false, err}` —— there is no red_count/checks, and consumers must not read integ in the
  content shape.
- These two shapes = the entire programmable contact surface of the verify lane for the onboarder:
  the merge gate, the workflow verify step, and the workbench UI all consume that shape, and **must
  not bypass it to read verify.yaml and re-judge on their own**.

### ②c Handwritten parser grammar subset = the writable domain

verify.yaml is read by an engine-internal handwritten parser (stdlib-only, bare python3 without
pyyaml). **The project's writable domain = the shapes expressible in the subset below; writing YAML
outside the subset is refused (malformed fail-closed), and the engine does not parse leniently.**

Supported syntax forms (one positive example each, pinned by tests):

- two-space indented nested mappings; tabs expand to two spaces;
- bare-token scalars and quoted scalars;
- `- ` string lists (block lists) and inline flow lists `[a, b]`;
- `- k: v` list-of-mappings (checks entries), where later, more deeply indented lines merge into that
  entry;
- comments: a line-leading `#` is skipped; only ` #` inside a value (a space before the `#`) truncates
  —— values where the `#` is glued on, such as `url#anchor`, are not damaged.

fail-closed declaration: unknown lines, unknown keys, and incomplete structures all raise an error
and turn red, with **no silent filtering** —— verify.yaml is the lane's own declaration, and an
incomplete one is fail-closed under the "malformed" state of the three-state overview.

### ②d Thin-shell execution topology = single tool source

- Both the code lane's checks and integration.cmd are executed by the engine via `/bin/sh -c`: cwd
  takes the declared value (relative to the **declaration root** = the directory containing
  verify.yaml; the main tree's is the repo root, and inside a lane it is the worktree root), timeout
  takes the declared value, and they run in parallel (independent child processes, with the process
  killed on timeout to reclaim the terminal state).
- The project-side entry is a **thin shell**: all project tool logic is gathered in a single-source
  executor inside the project repo (the suyou instance = the repo-root verify.yaml pointing at
  `integration/run_scenarios.py`; the SCENARIOS triple, the `sc_` prefix iron rule, and pool
  scheduling are project-internal conventions that do not enter the contract).
- The engine has zero project policy: it embeds no project tooling and has no perception of the
  concept of a "scenario"; it only runs the declared commands, judges red/green per ②b, and passes
  through the output tail. Execution and parsing exist exactly once under the sun, in the engine ——
  upper layers only place orders and translate JSON.

### ②e Three levels of reuse + rule of three

Reuse has three levels:

- **level one = engine mechanism**: common across projects, belonging to sandbar (running and judging
  the verify lane, the three-state verdict, the thin-shell execution topology —— that is, the
  chapters of this contract);
- **level two = the project repo's shared layer**: modules/fixtures shared by multiple scenarios
  inside a project (the suyou instance = shared code under `integration/` without the `sc_` prefix);
- **level three = scenario-private**: carried by the `sc_`-prefixed scenario file itself, never lent
  out.

The abstraction threshold = **rule of three**: only when the same shape repeats for the third time
does it sink down and rise one level; prefer repetition to premature abstraction. Promoting a
level-one item is additionally constrained by the general principle of "a real demand from a third
project" (see the promotion-principle section).

### ③ Role persona override (schema: v1)

**What it is**: a project may declare role persona overrides in its workspace, layered on top of
sandbar's built-in role skeletons. The merge is three layers: built-in role skeleton (process /
discipline / output format, following sandbar) ⊕ workspace persona override (business context,
brought by the project) ⊕ machine-level default. Overrides add business context only; they do not
change the skeleton's process and discipline.

**Why it is stable**: the role skeleton changes with sandbar upgrades (an internal implementation
surface), but "the project wants to give its own business context" is a real demand of every project,
and the shape of that need is stable —— it is one override declaration. Promoting it means that when
an IDE upgrade swaps the skeleton, the project only needs to keep its override file.

**Closing semantics** (per the three-state overview): no override = pure skeleton (the missing state,
which is also the state of most projects); a malformed override declaration or an unsupported version
= fail-closed —— better to refuse to run than to silently retreat to the pure skeleton, because that
retreat means the business context the project claims is quietly dropped.

### ④ Epic proposal content location (schema: v1)

**What it is**: the content of the epic proposal (epic) hangs under the project directory, at a
location declared by the project's registration, with no hard-coded path for any project. sandbar
finds the epic proposal content through the registration declaration, carrying the full lifecycle of
"epic = goal + acceptance criteria + key decisions + archived snapshot".

**Why it is stable**: the epic proposal is the semantic unit above tickets, and the link between a
ticket and an epic relies on a machine-checkable epic code (see the mechanism document "epic proposal
and ticket association"). The existence of the code is strongly checked by file existence, so "where
the epic proposal is" must be a contract question rather than a convention.

**Closing semantics** (per the three-state overview): a project with no epic proposal = that
dimension's functionality closes (tickets still run, without the epic dimension); a malformed epic
proposal content location declaration or an unsupported version = fail-closed.

### ⑤ Tool bridge protocol (schema: v1)

**What it is**: the project's own management/operations tools (the admin-script kind) are exposed to
agents through a declaration. The protocol = entry declaration (where the tool is, how to invoke it)
+ invocation convention (input/output shape). The tool content is the project's own, and the IDE does
not prescribe what project tools do.

**Why it is stable**: while executing tickets, agents often need to trigger project-specific
mechanical actions (create a ticket, check status, trigger a release). This contact surface is a real
need of every project; promoting "how to expose it" leaves the tool's own implementation in the
project's hands, unaffected by IDE upgrades.

**Closing semantics** (per the three-state overview): no declaration = no tool bridge available; a
malformed declaration or an unsupported version = fail-closed, with the error naming which entry
declaration failed.

### ⑧ dsh platform compatibility range and mandatory upgrade checks (schema: v1, t260903-08 landed with the contract)

> This section is the truth source of sandbar's compatibility promise toward the **dsh platform
> layer** (the clause carrying key decision 4, "zero dsh patches, follow the version upstream"), and
> it belongs to sandbar's self-declared surface rather than the project declaration surface ——
> projects do not write it, but project availability is constrained by it. Consumers: the sandbar
> installer (`sandbar upgrade`) and the compatibility matrix probe set (`sandbar doctor`).

**⑧-1 Compatibility range declaration**: sandbar's compatibility surface with `@deepseek-ai/dsh` uses
**an enumeration of verified points** as its criterion and writes no mathematical range —— every
verified point must be backed by green probe evidence. Verified points: `0.1.1-rc.2` (the only data
point, 2026-09-03). Extension rule: a new dsh version is appended to this list only after sandbar's
probe set is all green; a version not listed = not verified (not unsupported, but without evidence).

**⑧-2 Mandatory upgrade checks** (truth source = the summary section of
`notes/debts/sandbar-m0-dsh-touchpoints.md`, promoted with this section; re-scan each item on a dsh
upgrade, and any mismatch = no range extension):

1. **settings/resolve layering order** (touchpoints A3): a change in the composition order of the GUI
   default model stage and the declaration-layer patch would silently invalidate the "routing takes
   priority over the GUI" semantics;
2. **headless runner assembly and startup hooks** (A4/A5): a change to any of the stock runner's
   cordis id, the `inject:[headlessStartup]` injection point, and the `DSH_HEADLESS_SESSION`
   convention invalidates the session-continuation patch (manifesting as a silent loss of session
   continuation, not a hard failure);
3. **dsh home layout and session storage format** (B1/C1/C2): a change to any of the directory layout
   and file names of profiles/credentials/settings, the session on-disk path, the compression format
   (zstd line-based event stream), and the event fields (`data.usage`,
   `request/context|header`) affects the spawn copy chain and the workbench observation surface;
4. **headless SIGTERM semantics** (D1): a change to the assumption of "intact session file + no
   orphans" after terminate manifests as a red "agent exited without writing the result file"
   (explicitly observable, not silent).

**⑧-3 Compatibility matrix mechanism**: a matrix row = **sandbar version × dsh verified point ×
project schema version**, appended one row at a time as probes run green (append style, landing in
`~/.sandbar/compat-matrix.json`, whose schema is maintained by the sandbar repo); an empty matrix
cell = unverified, not a promise of support.

**⑧-4 Version self-report criterion**: the engine snapshot self-reports `sandbar_version` (semver,
read from the sandbar repo root VERSION, from `0.1.0` onward); the historical snapshot's
`temporal_engine_version` integer key is **kept as-is, not migrated, and no historical semver mapping
is fabricated** (the engine of the v2 era never existed as semver, so mapping after the fact would be
fabricating history); a consumer that meets an unknown int displays it as-is per the historical
criterion, and one that meets a malformed `sandbar_version` (not semver) = fail-closed red. The two
keys coexist, and the legacy int key is not retired.

**⑧-5 Upgrade execution order**: the release path for a new dsh version = the probe set all green →
append to the ⑧-1 list → sandbar releases → projects follow; extending the range by skipping probes
is forbidden (the mechanization of key decision 4).

### docs context composition order

The knowledge base is a first-class component of the IDE, and the three docs levels = three levels
of working context. The context composition when an agent works:

- **Take "the docs of the repo it is in ⊕ project-level docs"**: repo-level docs are the main body of
  the working context, project-level docs provide context shared across repos, and the two are
  composed.
- **IDE docs do not enter project ticket context**: IDE docs serve sandbar's own development only.
  The exception is not a channel but an identity —— when dogfooding, sandbar's own repo is registered
  as a project, and IDE docs enter the context with the identity of "that project's project-level /
  repo-level docs", going through the normal post-registration composition rather than a bypass.

The composition order is independent of the three states: a missing docs level simply means that
level of context does not exist (no docs directory means none), and there is no "malformed docs
fail-closed" verdict —— docs are natural-language documents that do not use schema versions, and when
their structure is invalid the knowledge base component handles it by its own criterion.

### Stable contract surface vs internal implementation surface

| Surface | Content | Promise |
| --- | --- | --- |
| Stable contract | the five items: registration and directory model, policy and integration test declaration, persona override, epic proposal location, tool bridge protocol | follows semver; changes go through the change record; a deprecation keeps the old reading for the first N versions |
| Internal implementation | the six template subclasses, the plugin API, the `.suyou` internal layout, and everything else | changes at any time, and projects must not depend on it; it does not enter the contract |

Promotion principle: **wait for a real demand from a third project**. Only when an internal
implementation surface is genuinely needed by two or more projects is its promotion into the contract
evaluated; promotion means carrying the upgrade burden, so prefer slow to excessive.

### Upgrade decoupling and compatibility matrix

Upgrade decoupling of the contract surface relies on mechanisms, not on discipline:

- **semver**: sandbar releases by semantic versioning, and contract-surface changes show up in the
  version number.
- **keep the old reading for the first N versions of a deprecation**: when a contract item is
  deprecated, the old reading is kept for N versions, giving projects an explicit migration window.
- **compatibility matrix**: axes = the schema version the project declares × the IDE version (the dsh
  version axis is carried by sandbar's declared compatibility range with dsh, see the mechanism
  document; from v1.7 it is refined into three axes —— the IDE version axis = the composite of the
  sandbar version + the dsh range, see ⑧-3). The matrix promises only the mechanism —— the definition
  of axes and cells and the rule of appending as versions are verified; an empty cell does not mean
  "supported", only "unverified", and v1 has exactly one verified cell: schema v1 × the current IDE
  version.

### Contract change record mechanism

At the end of this document an append-style "change log" table is maintained (version / date / change
/ affected surface). Every contract change —— a newly promoted surface, a schema version bump, a
revision of closing semantics —— must land one record; the record shares the same truth source (git)
with the contract body and does not depend on any execution engine. A promotion (an internal
implementation surface becoming official) also goes through a record, annotated with the project need
that drove it.

### Tying back

- Solves Problem 1 (the engine lives in the project repo, coupled dead): the five items define the
  entire contact surface after the inversion, and the project repo no longer carries the engine.
- Solves Problem 2 (the contract is unwritten and later tickets have no prior basis): the five items,
  the schema versions, and the three-state closing semantics are all written down, and the in-place
  inversion and physical relocation tickets have a citable contract.
- Solves Problem 3 (project policy has no stable home): the policy configuration and integration test
  declaration are promoted (Requirement 1, 2), and the separation of mechanism and policy lands in
  verifiable clauses.
- Satisfies Requirement 3 (context composition order), 4 (stable/internal boundary), 5 (change
  record), 6 (semver/deprecation/compatibility matrix mechanism), and 7 (promotion principle), each
  with its own section.
- The implementation details, field-level definitions, and matrix empty cells delimited by Nongoal are
  all left to later tickets; this document does not touch them.

### Change log

| Version | Date | Change | Affected surface |
| --- | --- | --- | --- |
| v1 | 2026-08-31 | First written version: five promoted surfaces (schema v1), three-state closing semantics, context composition order, the stable-surface/internal-implementation boundary, the upgrade decoupling mechanism, the promotion principle | All five items; the citation basis for later configuration/inversion/relocation tickets |
| v1.1 | 2026-09-01 | t260901-08 configuration ticket landed: the verify.yaml field-level definition written down (new §②a: lanes.code.write_allow/checks, integration.entry/red_green); the carrier location is left to the project's own registration (suyou = repo root, not .sandbar/); missing-state mapping extended —— with verify.yaml missing, besides the integration stage having no tests to run, the code lane also closes per the declaration (green visible, not silent) | ②/②a; verify_lane code lane |
| v1.2 | 2026-09-01 | t260901-14 out-of-repo ticket landed: the registry truth source moved out of the repo to the machine-level per-key directory `~/.sandbar/projects/<key>/project.yaml` (new §①a: entry format, per-entry isolation three states, directory/data/metrics path conventions, the .migrated migration criterion and the handling of the three site categories, legacy env compatibility); credentials and engine data only establish path conventions without touching content (migrated in M1-2/M1-3) | ①/①a; registry loader (isomorphic on the TS/Python sides) |
| v1.3 | 2026-09-01 | t260901-21 credentials out-of-repo ticket landed: the credentials truth source moved into `<root>/<key>/credentials.yaml` (new §①b: two-level read-side resolution = per-key first + legacy deprecation-window fallback, three-state criteria, zero-downtime semantics separating the copy source from the read location, manual migration steps); the engine's credential read location and the dsh credentials seam are unchanged | ①/①b; read-side copy points (agent_activities.py, ui-check) |
| v1.4 | 2026-09-02 | t260902-02 engine data out-of-repo ticket landed: the archive truth source of completed tickets moved out of the repo to the per-key data directory `<root>/<key>/data/tickets/<id>/` (new §①c: the three archiving families/exclusion criteria, the archive.json manifest skeleton, legacy honest-accounting semantics, three-state closing semantics); the dev-lane wrap-up (merge-in) is fixed as three stages merge→archive→teardown (a fail-closed archive is the precondition for tearing down the lane); Temporal's return to the running state = `ticket prune` actively cleaning up the workflow history of closed and archived tickets (dry-run by default, legacy double flag) | ①/①c; dev-lane three-stage wrap-up, archive_ticket/teardown_lane activity, client.py ticket-prune/ticket-archive-legacy |
| v1.5 | 2026-09-03 | t260903-01 declaration-system alignment: ②a rewritten per the engine implementation into v2 list-command style (`checks=[{id,cmd,cwd?,timeout?}]`, `integration.cmd`; the v1.1 five-type field table was documentation distortion —— the engine never implemented it, and the erratum does not bump the schema version, with the ruling entered alongside ②a); ② missing-state erratum (the integration lane fails closed, and the "no-op criterion" is void); new ②b output contract (three-line protocol + per-lane return shapes + err semantics + the zero-scenario-green closing idiom), ②c handwritten parser grammar subset = the writable domain, ②d thin-shell execution topology = single tool source, ②e three levels of reuse + rule of three | ②/②a/②b/②c/②d/②e; verify_lane code/integ lanes |
| v1.6 | 2026-09-03 | t260903-03 path contractization landed: new ①d —— the optional top-level `paths` section of project.yaml declares in-project paths (`roles_dir` role directory resolved relative to the spawn cwd lane snapshot, `model_routes` routes table resolved relative to the main directory), and engine spawn taking the role directory/routes table plus the prompt's role_doc assembly now take values through the declaration; four-state verdict (the four fallback categories with zero regression / malformed declared value / malformed entry file / declared anchor missing or misplaced = fail-closed red naming the file), the anchor vs content boundary (per-role missing soft skip, table content corruption inherits lookup tolerance), transitional state (the current loader's top-level whitelist does not yet allow paths, so declaring it means being isolated by ①a —— ①d takes effect only once the relaxation ticket lands); schema stays v1 (additive optional fields) | ①/①d; the two agent_activities spawn consumption points, shared.py prompt assembly and model routes lookup; registry loader (TS/Python) pending the relaxation ticket |
| v1.7 | 2026-09-03 | t260903-08 dsh compatibility range written down: new ⑧ —— the dsh platform compatibility range declaration (verified-point enumeration, the current only point = 0.1.1-rc.2, extension requiring green probes before appending), the four mandatory upgrade checks promoted (touchpoints summary section A3/A4+A5/B1+C1+C2/D1), the three-axis compatibility matrix mechanism (sandbar version × dsh verified point × project schema version, append style), the engine version self-report criterion (`sandbar_version` semver from 0.1.0; the historical `temporal_engine_version` int kept as-is with no mapping fabricated, malformed fail-closed), the upgrade execution order (probes green → extend the range → release → projects follow); the two-axis wording of the "upgrade decoupling and compatibility matrix" section is complemented with the v1.7 three-axis link (the IDE axis = the sandbar+dsh composite). The installer/probe/VERSION code surface is taken up by the sandbar repo M2-C code tickets (handoff note notes/debts/sandbar-m2-c-installer-handoff.md) | ⑧ (new); the "upgrade decoupling and compatibility matrix" section; consumers = the installer upgrade/doctor probe set (code ticket pending) |
| v2.0 | 2026-09-04 | t260904-12 no-SKIP-ization of the integration gate (the merge point of the version number was postponed from v1.8: the main-side v1.8 truth-source promotion / v1.9 removal surface had already occupied it) (final draft = notes/discussions/260904-charter-injection-invalid-payload.md §7.3/§7.4): ②b-1 three-line protocol raised to a three-state protocol —— scenario-level PASS/FAIL/ENV_FAIL, the character-level format of the `ENV_FAIL [scenario name] exit=2` line (malformed follows the FAIL convention, name = the whole line, exit=-1), the summary line's five counts `SCENARIOS ran=N pass=N fail=N env_fail=N na=N` entering the contract literally + the bidirectional net criterion (lying = product red), the green criterion adding env_fail=0, exit codes splitting into 0/1/2 (product red takes priority; all sub-cases N/A = product red, and N/A is given only to system-state-conditioned sub-cases); the ②a integration stage gains the `supply` supply declaration (`[{need,cmd,cwd?,timeout?}]`, idempotent assembly commands run before cmd, failure = red naming the need, key missing = zero declarations is legally empty); the ②b-2 integ shape gains `env_fail` (may be absent before the B-part ticket lands). Same family KI-036/044/046; the engine-side env/product attribution mechanization and supply execution = the B-part ticket (verify_lane/repo-root verify.yaml, pending the host's expanded set) | ②a/②b-1/②b-2; the integration executor and scenario set, the engine verify_lane (B part) |
| v2.1 | 2026-09-04 | t260904-12 part B landed: the verify_lane integ lane implements three-state parsing (the ENV_FAIL line / the env_fail count entering the return shape, the green criterion including env_fail=0, malformed following the FAIL convention) and supply assembly execution (before cmd, with failure/timeout = red naming the need); ②b-2 env_fail becomes "always present"; the basis for moving the ticket-lifecycle scenario out of the set = final draft §7.3 "what cannot truly run inside the gate (red-line no-go areas / destructive) does not enter the gate list" (the worker mechanical step always triggers the anti-recursion guardrail = a design-time environment red, with PASS unreachable inside the gate; real coverage is taken up by the main repo's manual list; the second reversal of the criterion, with the basis chain in integration/README known limitations) | ②a/②b-2; verify_lane integ lane, repo-root verify.yaml, integration scenario list |
| v1.8 | 2026-09-04 | Truth-source promotion (host ruling 260904): this file is upgraded from "a read-only same-source copy of suyou repo v1.7" to the contract truth source, and the header declaration is rewritten; the same-named file on the suyou side is downgraded to a historical frozen artifact (no longer evolving, not a modification target). Zero semantic change to the body; the ①a supplement (removal/re-onboarding, single-root-directory tool criterion) lands with project-lifecycle epic ticket ②, recorded in a separate row at that time | Document governance surface; consumer guidance (upgrade/doctor take this copy as authoritative) |
| v1.9 | 2026-09-04 | t260904-14 removal surface landed: new ①a-1 —— removal/re-onboarding/data disposal three states written down (entry retirement = atomic rename of project.yaml to retired-<UTC ISO8601>, zero schema change and reversible; re-onboarding = re-add with the same key, archive chain continuous; mode gate [legacy refusal]/in-flight gate [unreachable fail-closed, no bypass flag]/last-entry confirmation gate/closed all-archived gate [purge precondition: the unarchived difference set = the Temporal COMPLETED ticket id set − the fs archive.json three-state verdict set, malformed manifest = fail-closed naming the file]; purge double flags explicitly separated, dry-run rehearsing all gates, the removal report only reporting the project-root .lane/ lanes without deleting them); the single-root-directory criterion written into the tool surface (the tool writes exactly one dirs entry; multiple entries = a legacy shape tolerated at load and never produced by the tool) | ①/①a; the installer project remove subcommand, consumers of the removal report (ops runbook / future UI surface) |
| v2.2 | 2026-09-04 | t260904-18 three gates landed: ②a adds the legal top-level key `ui_evidence` (optional mapping `{dirs, supply?}`; missing = the screenshot evidence item absent per the project declaration, green + a visible note; malformed = fail-closed red naming the field; supply is a reserved field not consumed by this version of the engine) —— the merge gate's UI screenshot evidence directory becomes a project declaration, retiring the engine-side `UI_WRITE_PREFIXES` five-path hard-coding from its live-path identity (only a compatibility fallback for old-ticket replay/frozen branches remains); same family: the background-file gate at ticket creation (ticket refs must already be committed and in a clean HEAD state, otherwise refused with naming) and the create_plan receipt files_changed empty-array/malformed visible red (KI-049), which belong to the engine mechanism surface and do not enter this contract's field table | ②a; verify_lane `_validate_cfg`, merge_check 3.6, ui_changed_paths, repo-root verify.yaml |
| v2.3 | 2026-09-07 | t260907-10 directory refactor (host order v6 final) changed the path anchor semantics: the ①d `paths` section fallback convention's old anchors `server/dsh/roles`, `server/dsh/model-routes.yaml` are **retired**, and the new fallback anchors = `server/roles`, `server/model-routes.yaml` (the engine repo's server/dsh wrapper layer exits and the five layers are flattened and moved up; the engine body = temporal-poc → `server/engine`); projects without an explicit `paths` declaration keep the same fallback semantics (only the fallback target changes to the new anchor); projects with an explicit declaration of the old anchor turn fail-closed red naming the anchor per ①d; the venv location fallback chain = the new path `server/engine/.venv` first, with one round of compatibility for the old path `server/dsh/temporal-poc/.venv` (a single path once the removal ticket lands); the old anchor wording in this document survives only in this change-log row (a historical fact, not a live pointer) | ①d/fallback convention; the two agent_activities spawn consumption points, shared.py DEFAULT_ROLES_DIR/MODEL_ROUTES_REL, installer, repo-root verify.yaml (expanded-permission surface) |
| v2.4 | 2026-09-10 | t260910-14 model routes table moved out of git (truth source = the file the project declaration points at): the ①d `model_routes` declared value is relaxed —— the relative-to-main-directory semantics are unchanged, while `~/` expansion (suggested default `~/.sandbar/projects/<key>/model-routes.yaml`) and absolute path forms are added, with `..` escapes/empty values/non-scalars still fail-closed and a quoted scalar judged the same after the quotes are stripped; the missing-table semantics change from "anchor missing = fail-closed red" to a **per-state soft fallback** —— the three states decl_missing/file_missing/bad_content are named and logged (silent fallback to the profile default forbidden, KI-030 narrowed), and the read-side layered fallback = the in-repo `server/model-routes.yaml` (host risk order 260910: no supply break during the migration window, so the in-repo table is kept by this ticket and its deletion is deferred to another ticket); the engine lookup (`resolve_routes_table` three-state discrimination) and the UI read/write (TS `resolveRoutesFilePath`) share one source and one verdict (consistency guard = the t260910-14 parity scenario); the init guidance is retired (new projects fill the table manually per the docs sample). | ①d; shared.py routes stage/the agent_activities spawn consumption point, ui routes.ts (view/save/init retired), the two guard items of t260902-07, sc_paths_contract_doc_guard G6 updated in step with the new semantics |
| v2.5 | 2026-09-16 | t260916-02 inspection declaration relocation A: the ①d `paths` section gains the `inspection_decl` pointing key (the same machine-level relaxation as model_routes: relative joined to the main directory / ~/ expansion / absolute; lexical validation from the same source), with **fallback semantics deliberately not copied** —— an absent declaration = this project has no inspection surface (absent, borrowing neither another project's nor the engine sample), and a bad shape/missing anchor = a project-level error naming it (silence forbidden); the inspection declaration defaults to the single file `<project root>/inspection.yaml` (no directory), and the engine repo's `server/engine/inspection.yaml` is retired and deleted (the engine = mechanism + the docs/inspection-sample.yaml sample); aggregation (board whitelist/missed-run check/schedule-up) changes to traversing registered projects and reading each declaration, where a cross-project duplicate instance id = ambiguity removed with both places named; inspection ticket ids uniformly take the ticket-number form `t<YYMMDD>-<NN>` through the existing allocation, and "one ticket per period" is explicitly deduplicated by (instance, period number) (SA InspectionInstance/InspectionPeriod + atomic pointer three states), with the instance/period number never reverse-derived from the ticket number (read from the ticket face/SA) | ①/①d; shared.py project_paths, inspection_decl.py, inspection_ticketing.py (new), inspection_trigger.py, the two client.py board sub-cases, docs/inspection-sample.yaml, repo-root inspection.yaml |

> 来源立项：sandbar

## Related documents

- [DeepSeek Harness and Temporal based multi-agent mechanism](../design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md) —— the mechanism truth source; the five-layer architecture and the dependency-direction inversion are in its dedicated section
- [Design doc writing guide](../design/design-doc-writing-guide.md) —— the structural basis of this document
- epic proposal `notes/epics/sandbar.md` —— the source of "contract v1 (deliberate restraint)" and key decisions 4/5/6/7
