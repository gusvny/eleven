---
title: sandbar distribution form v1
category: design
tags: [distribution, installer, docker, design]
status: draft
updated: 2026-09-28
---

# sandbar distribution form v1 (proposal draft, pending host final review)

> **Status**: proposal draft. Design finalization belongs to the host — this document lays the option out clearly and
> lists the points of disagreement explicitly as "pending host decision"; it does not finalize on the host's behalf.
> The host's 260907 decisions are already written into this document as fixed: **no npm package; mac first for the initial
> release (Linux to follow, Windows later with no commitment); keys belong to the user and do not go into the package**.
> Three specific names (the distribution env knobs, the compose project name, the uninstall subcommand) are marked
> "naming pending host review".
>
> The host's supplemental decisions of 260907 (v2–v6) are likewise fixed here: **the recipient's perspective** is the
> primary acceptance perspective (v2); the target naming table and migration order form a chapter (v3/v4); persona
> de-projectization (v5); final directory structure plus the four delivery decisions (v6) — see §Recipient perspective,
> §Target naming table, §Generic persona library, and §Directory structure and release manifest respectively.
>
> Path-writing convention: this document cites in-repo artifacts by their **current path** (before migration completes it
> is the source of truth), and the target name for each is in §Target naming table — the two sets of names can be compared
> side by side, and the old paths lapse naturally once migration finishes.

## Problem

**In one sentence**: today sandbar can only be picked up by "someone who can open a terminal, understands the red lines, and clones the repo to bring the stack up by hand"; to hand it to two new audiences — contributors (who can run the repo but do not want to recite a set of passed-down steps) and end users (who just want to use it without understanding the stack) — there is no written distribution path at all.

**Background**: one sandbar stack = the dsh console (3099, forever the user's operating surface) + the Temporal engine (7233 gRPC / 8233 Web UI) + the ticket worker + the agent runtime surface. The production port red lines (3099/7233 must not be touched) and the docker-isolated test bench topology are in [testing-guide](../testing-guide.md); for engine mechanics see the [engine mechanism master document](deepseek_harness_and_temporal_based_multi-agent_mechanism.md).

**Evidence**: onboarding newcomers rests entirely on word of mouth (clone → create venv → start-console.sh → start temporal → start worker → open the console), and the repo has no install documentation and no install.sh; the only docker bench that is written down is the **test bench** (3199/17233, see testing-guide), which is not a distribution form meant for outsiders. The result: every new contributor costs a veteran half an hour of hand-holding, and the end-user form simply does not exist.

## Requirement

**Goals (verifiable)**:

- R1 **Form one (repo + init script, developer/contributor tier)**: `install.sh` is written down as a behavioral contract (see Proposal §Form one), and each of the seven specs defines plain-language behavior for all three input states "missing / conflicting / malformed", with the malformed state always raising an explicit error and never degrading silently.
- R2 **Form two (whole stack in containers, end-user tier)**: a three-service topology (console as the only external port 3099 + engine = temporal + worker + agent running inside containers); a host port-occupancy pre-check before up, reporting an error instead of fighting for an occupied port; data lands in named volumes so upgrades do not lose it; **no equivalent of `down -v` is offered** (deleting data must go through an explicit uninstall plus confirmation).
- R3 **The fresh-home acceptance scenario is written down**: a brand-new home directory → bring the stack up → all three probes green → open a real ticket from the console → land a result, with no manual intervention throughout; every step has an expected output and a location where a failure is reported; the macOS case comes first.
- R4 **A structure diagram of the shared init source of truth**: both forms share the same stack-assembly logic, and reading the diagram alone conveys the single-source-of-truth relationships.
- R5 Version and compatibility surfaces follow the existing criteria (clause ⑧ of the [onboarding contract v1](sandbar-project-onboarding-contract-v1.md): VERSION as a single source, the dsh version range, the compatibility matrix) rather than inventing a second set.
- R6 **The recipient's perspective (host instruction v2)**: the fresh-home script stars **the recipient's own project** (start from an empty registry → guide the registration of the recipient's project → open tickets on it → land through the seven stages), with "sandbar as a project" absent throughout; the distribution includes an example-project sample (both a teaching sandbox and an acceptance fixture); the three self-references have a removal checklist (see §Recipient perspective).
- R7 **Naming and structure finalized (host instructions v3–v6)**: the target naming table plus the layered migration order form a chapter (final review = the host's own read-through); the server/ directory structure is finalized per v6; the four delivery decisions (release manifest / prebuild / single instance / engine data volume) are locked; persona de-projectization (v5).

**Stakeholders**: the host (finalization and the three pending decisions); contributors (form-one users, who want fewer steps to remember and self-rescue when things go wrong); end users (form-two users, who want a one-command stack and no data loss); integration (acceptance-scenario design, which needs the distribution and the test bench to share a source and be parameterizable).

**Prerequisites** (host decisions + repo discipline, each written down as fixed):

1. No npm package (host decision 260907).
2. Initial-release support = **mac first** (the fresh-home acceptance scenario does the macOS case first), Linux to follow, Windows later (WSL2/NTFS corner cases recorded, not committed).
3. Keys = **the user's, never in the package**: no install/distribution artifact generates, moves, or prints user keys.
4. Migrating the existing `SANDBAR_*` env and the `/suyou-workbench/` prefix = **release-blocking debt** (see Proposal §Release-blocking debt), handled by a dedicated migration ticket.
5. console (3099) is forever the user's operating surface: every install path **only probes and only warns**, and must not spawn/start/kill/restart 3099 (CLAUDE.md hard rule 1; the existing installer follows the same discipline).
6. All new naming uses sandbar or a neutral name, adding no new naming that carries the word suyou (CLAUDE.md hard rule 5).
7. Accidental production connection is fail-closed: a worker without an engine address prefix defaults to connecting to **production** 7233/default (testing-guide states plainly that this "amounts to an incident on the scale of touching 3099"), so every engine-address default in the distribution form must avoid pointing at the production surface.

## Nongoal

- **npm package**: the host decided against it; no argument, no interface reserved.
- **Windows/WSL2/NTFS support**: not committed this cycle; NTFS permission bits and path-case corner cases are recorded in §Cost accounting.
- **Key management**: no generation, movement, or custody of user keys; the key surface only probes whether something is corrupted.
- **Executing the existing naming migration**: the target naming table and migration order form a chapter here (§Target naming table), but the migration actions follow only a dedicated migration ticket (each step its own ticket and its own gate); this document does not execute them.
- **Finalizing the installer.cli container backend interface**: this document declares only "a new one is needed" and the acceptance direction; the interface is left to the implementation ticket.
- **Absorbing the installer domain design surface**: the full design documentation of the existing installer (init/up/down/status/doctor/upgrade) is not expanded here (whether to absorb it is §Pending host decisions item 3).
- **Delivering the Linux fresh-home case**: written down as a follow-up item; that case is not done this cycle.
- **Going back and changing the test bench**: docker bench no. 19 (the test-bench compose surface, today `server/docker-compose.test.yml` + `integration/stage_docker.py`) is reused read-only for its mechanism, and test-bench behavior is not changed for the sake of the distribution (moving the directory to `server/sandbar/` per the naming table belongs to the migration ticket, not to the distribution changing the test bench).

## Proposal

### High level

Two distribution tiers sharing **one and the same stack-assembly source of truth**:

- **Form ① repo + init script (developer/contributor tier)**: after `git clone`, run `install.sh` — a thin bootstrap that does the one-time landing (plain-language pre-checks, venv, home-directory wiring, .env template, three probes), after which day-to-day lifecycle is handed to the existing installer `./sandbar init/up/down/status/doctor/upgrade`.
- **Form ② whole stack in containers (end-user tier)**: one command brings up a three-service container stack (console / engine / agent), data lands in named volumes, and replacing containers on upgrade loses no data; the user is not required to understand python, venv, or the red lines.

**Structure diagram of the shared init source of truth (R4)**:

```
                    repository (the single source of truth for stack assembly)
                                        │
        ┌───────────────────────────────┼──────────────────────────────┐
        ▼                               ▼                              ▼
   install.sh                     installer.cli               container entrypoint
  (thin bootstrap,             (day-to-day lifecycle)         (runs inside form ②)
   one-shot)                 init/up/down/status/         reuses install.sh's stack-
   pre-checks/venv/              doctor/upgrade             assembly steps + in-
   wiring/.env/three probes                                   container probes
        │                               ▲                              │
        │  form ① host runs direct      │  form ② reuse in-container   │
        └──────── hand off after install ┘ ◀────────────────────────────┘
```

Key trade-off: **do not build a second or third stack-assembly entry point**. install.sh and the entrypoint are only two entry shells over "the same stack-assembly logic"; for lifecycle (start/stop/status/health check/upgrade) the only source of truth is `installer.cli`. For form ②, installer.cli currently has no container backend for the engine lifecycle; this document lists that as a to-do for the implementation ticket (see §Pending host decisions item 2), and the interface is not fixed here.

### Form one: repo + init script (developer/contributor tier)

#### install.sh behavioral contract (R1)

The specs stop at the **behavioral-contract level**: what plain-language message each check prints when it fails, and what the fix is; the full script and the complete command-line inventory are not included. All seven items share one iron rule: **missing = create it, conflicting = warn only without overwriting, malformed = explicit red plus a pointer to the fix, never degrade silently** (precedents: notes/debts/known-issues.md KI-030, where a rotten config silently fell back to defaults, and KI-039, where a missing dependency was silently swallowed by fault tolerance).

| # | Item | Missing → create | Conflicting → warn only, no overwrite | Malformed → explicit red |
|---|---|---|---|---|
| 1 | **Idempotent pre-check**: git present, python3 version adequate, (container mode) docker present, **3099/7233/8233 occupancy check** | git/python3 missing → print a one-line install hint (e.g. `brew install git`) and stop without going further | port occupied → plain-language error with a pointer: 3099 occupied = "the console belongs to the user's operating surface; a stack may already be running, please confirm manually (`./sandbar status`)"; 7233 occupied = "an engine is already running, verify with `./sandbar status` first". **Do not seize, do not displace, do not kill any process** | python3 present but too old / not executable → red text naming the version and the install hint |
| 2 | **venv**: created from a pinned requirements file, with a health check after install | no venv → create it and install dependencies | venv exists but its dependency fingerprint does not match requirements → print the difference and the rebuild command, and **do not rebuild silently** (a rebuild means loss, KI-039) | half-broken venv (broken python / failed imports) → red plus a rebuild instruction, no silent overwrite |
| 3 | **Home-directory wiring**: wiring files such as profiles/settings | write only when missing | existing file with different contents → print the differing path, warn only, do not overwrite | existing file truncated / bad format → red plus a pointer (a rotten config silently falling back to defaults = an incident on the KI-030 scale) |
| 4 | **git identity and key surface** | user.name/user.email missing → print a one-line `git config` hint | identity already present → skip | corrupted key surface → explicit red. **The script never generates, moves, or prints keys** (prerequisite 3) |
| 5 | **.env template**: write `.env` (mode 600, not in git), **explicitly pinning the engine address and namespace defaults, never defaulting to production 7233/default** (prerequisite 7; key names per §Target naming table, with `SANDBAR_*` as the final name and `SANDBAR_*` as the transitional compatibility alias) | missing → write the template (every line commented in plain language) | .env exists → only add missing keys, do not overwrite existing values | corrupted .env contents → red text naming the bad line plus the fix |
| 6 | **Closing self-check, three probes** (each probe one green line / one red line with the fix): ① key venv dependencies importable; ② console probe — TCP connect to 3099 to judge presence, **probe only, never start**; ③ engine probe — connect to the engine address and namespace pinned in .env | — | — | any probe red → overall non-zero exit, and the red line is the entry point for troubleshooting |
| 7 | **Print the plain-language next steps**: after install, print "what to do next" (`./sandbar init` → `./sandbar up` → open console 3099 → which docs to read) | — | — | — |

Re-running after a half-finished install: install.sh is idempotent — it walks the three states of the table above item by item until green, with no need to delete the directory and start over.

#### Division of labor with the existing installer (single source of truth, no fork)

- `install.sh` = **the first-landing scaffold** (green once, then it exits the picture);
- `./sandbar` (thin shell → `installer.cli`) = **the single entry point for day-to-day lifecycle**: init/up/down/status/doctor/upgrade; its remit (engine 7233/8233 + worker) and the "probe 3099, warn only" discipline carry over;
- starting and stopping the console (3099) = the user's operating surface (repo-root start-console.sh / stop-console.sh), which both forms only probe and reference, never replace.

### Form two: whole stack in containers (end-user tier)

#### Three-service topology (R2)

```
 host user ── 3099 (only external port) ──▶ ┌────────────────┐
                                            │ console cont.  │  dsh console
                                            └───────┬────────┘
                                   compose network │ (no host port mapping)
                     ┌─────────────────────────────┼───────────────────────────┐
                     ▼                             ▼                           ▼
             ┌────────────────┐            ┌────────────────┐        ┌────────────────┐
             │ engine cont.   │            │ agent cont.    │        │ project dir    │
             │ temporal:7233  │◀──────────▶│ agent runtime  │        │ bind mount     │
             │ + worker       │            └────────────────┘        │ (same path)    │
             └───────┬────────┘                                     └────────────────┘
                     ▼
             named volume (engine/console data, survives upgrade)
```

Why it is safe: inside the container the engine address points at the compose network `temporal:7233` with an independent namespace — the network topology naturally separates it from the host production surface (7233/3099), so there is no path by which "forgetting the prefix connects you to production"; the only port mapped on the host side is 3099.

#### Trade-off checklist for docker bench no. 19's parts (the boundary of same-source parameterization)

The distribution and the test bench are **same-source** = the same compose parameterization surface and the same image set; but the test bench's safety design runs **opposite** to the distribution's needs in several places, addressed item by item (precedents: the trade-off checklist in the integration/stage_docker.py file header, and the installer handover trade-off table):

| # | Bench no. 19 mechanism | Distribution position | Rationale |
|---|---|---|---|
| 1 | `SANDBAR_TEST_*` parameter knob naming domain | **Take the mechanism, not the names**: the distribution uses its own neutral knobs (`SANDBAR_DIST_*`, naming pending host review), with a same-source mapping table from distribution knobs to test-bench knobs | The test-bench naming domain does not enter the end-user surface (CLAUDE.md hard rule 5) |
| 2 | Hard exclusion of the forbidden port set {3099,3199,7233,8233,17233,18233} | **Defined in reverse**: 3099 is a legitimate external port for the distribution; but up still probes host occupancy of 3099/7233/8233 and reports a plain-language error instead of fighting for an occupied port (same semantics as the form-one pre-check) | The test bench guards against accidentally connecting to production, the distribution guards against accidentally displacing production — same source, opposite directions, each fail-closed |
| 3 | `down -v` zero residue (wipes data volumes too) | **Not carried over**: data volumes are the source of truth for user data, and the distribution **never offers an equivalent of down -v**; uninstall = an explicit uninstall subcommand (naming pending host review) plus a two-step confirmation (first list what will be deleted, then delete); upgrade = volumes retained, containers/images replaced | Copying the teardown semantics verbatim = deleting user data |
| 4 | Tier flock + port ranges (parallel instances do not collide) | **Not carried over**: the distribution is single-instance; the lock degrades into "already running → up is an idempotent reuse plus a plain-language notice", the default port tier is fixed, and a conflict is an error rather than a silent tier shift | Multiple instances = a source of user confusion; single instance plus idempotence is enough |
| 5 | Three-state exit codes 0/2/3/64 (ok / ENV_FAIL / environment conflict / malformed input) plus "the message names what is missing" | **Carried over**: the distribution's up and three probes use the same semantics | The criteria are proven, and users can branch on them in scripts |
| 6 | Health wait with a timeout carrying the tail of `docker compose logs` | **Carried over, with one difference**: on timeout, after printing the logs tail, **preserve the scene** instead of tearing the stack down automatically | The test bench prefers "clean up then exit" for CI; distribution users need the scene for troubleshooting |
| 7 | `-p` compose project name isolation | **Carried over with a fixed value** (e.g. `sandbar-dist`, naming pending host review): up/down hit precisely their own stack and do not damage other compose stacks on the host | The minimum isolation under a fixed single instance |
| 8 | Full terminal-state collection on SIGINT/SIGTERM | **Adapted**: Ctrl-C on a foreground up only stops following, it does not delete volumes; the discipline "the signal path must reach a terminal state" carries over | The full-terminal-state collection red line is unchanged; the semantics change for the distribution |

#### Solutions to the four hard problems

1. **Bind-mount the project directory at the same path**: the user's project directory is mounted into the container at the **same absolute path as on the host** (e.g. `~/Documents/foo` → the same path inside the container). Reason: profiles and the ticket surface record projects by absolute path, so mounting at a different path = landing-path drift. On mac, Docker Desktop requires the user to authorize directory sharing once, and the install flow points this step out explicitly.
2. **git identity and keys go through .env, not into the image**: zero identity and zero keys inside the image (so it is distributable); git identity, key-surface references, and the engine address/namespace are all injected at runtime via .env. The image can be public, `.env` stays on the host, and it enters neither git nor the image layers.
3. **Named volumes preserve data across upgrades**: the engine's on-disk data and the console's data all land in named volumes; an upgrade = new images and new containers, with the volumes untouched. **Deleting data has exactly one route: explicit uninstall plus two-step confirmation** (trade-off table #3).
4. **init reused as the entrypoint (single source of truth)**: the container entrypoint reuses the same stack-assembly steps of install.sh (the container case: pre-check → wiring → three probes → hand off to lifecycle), rather than building a third stack-assembly logic (see the structure diagram).

#### Cost accounting

- **uid mapping**: mac — the container reads and writes the bind mount through Docker Desktop file sharing and file ownership is mapped automatically to the host user, painlessly; Linux — the container's root writing to a host bind mount leaves root-owned files behind, so the follow-up case needs the container process to run as the host uid (or an equivalent mapping), and this is the main work item of the Linux case.
- **Ownership acceptance criterion**: after the container finishes a ticket, the ownership of newly landed files in the project directory = the host user (immediately true for the macOS case).
- **User restart habits**: after rebooting the machine or Docker Desktop, `up -d` restores everything (the data is in the volumes); stopping the stack day to day = down (volumes kept); **there is no scenario in which the user needs to kill containers by hand** — the docs and CLI messages steer toward the three verbs "down/upgrade/uninstall" and do not teach kill.
- **Windows/WSL2 corner cases (recorded, not committed)**: NTFS has no POSIX permission bits, and crossing /home with a bind mount raises performance and ownership issues; the later case will assess these separately.

### Recipient perspective and self-reference removal (host instructions v2/v5)

**The primary acceptance perspective = the recipient**: "we deliver sandbar for others to use, and their project will not contain a project called sandbar." Several parts of the current stack assume sandbar itself as the project (model routes, roles persona, self-check scenarios, documentation), and all of them must be dismantled in the delivered state:

| # | Self-reference | Current state (development) | After removal (delivered) |
|---|---|---|---|
| 1 | Engine-level model routing/roles | Model routes and roles persona use files inside the sandbar project as the only/preferred path | **Engine-level defaults plus user keys are promoted to first-class citizens**; project-level overrides = an optional advanced path; the fallback that resolves via the home directory is retained but is no longer the only path |
| 2 | persona project pointing | Wording such as "you are a developer on the suyou project" hardcodes the project name | **De-projectized**: roles/ is a cross-project asset, and the persona wording is **parameterized** (`{{project}}` injected by the engine when it dispatches work, per the ticket's project) or loses its project pointer — the name is not swapped to sandbar (host instruction v5); engine-level roles = generic personas (default), and project-specific personas go through the project-level override contract (`paths.roles_dir`) |
| 3 | Release self-check | Reuses the 156 integration scenarios that run on sandbar itself | **An independent small scenario family** (the recipient script, see §fresh-home scenario spec), maintained separately from the development-repo scenario family |
| 4 | Documentation layering | The engine manual and the project docs are mixed in the repo's docs/ | **The engine manual ships with the package** (README/install guide/first-run guidance go into the distribution); project docs belong to the project |

**example-project sample**: the distribution includes a sample project directory — the first-run guidance registers it → a teaching ticket runs through all seven stages. Both a teaching sandbox and an acceptance fixture, two uses in one; the recipient then registers their own real project, and the sample can be deleted or kept.

### Directory structure and release manifest (host instruction v6, structure decision "the directory is fine")

**Final server/ directory structure** (server flattened):

| Target directory | Contents | Note |
|---|---|---|
| `server/engine/` | the former `server/engine/` (bin/temporal + data/ as the engine's private base) | The engine is properly named (v4 revision: heavy reliance on Temporal is a fact settled by the design, so the directory name reflects it honestly, and only the poc experimental tail is dropped) |
| `server/plugins/` | the former 11 dsh plugin directories | Package names follow the naming table suyou-* → sandbar-* |
| `server/tools/` + `server/ui-check/` | tool family + UI check | tools stays put, ui-check moves up one level |
| `server/profile/` + `server/profile-headless/` | profile presets | names unchanged |
| `server/roles/` + `server/model-routes.yaml` | cross-project generic persona library + routing table | projects may override (see self-reference removal #2) |

**init walkthrough flow diagram** (at install time the walkthrough follows this order; the directory and the deliverables interlock):

```
install.sh / entrypoint
   │ 1 pre-check (git/python3/docker/port occupancy)
   ▼
2 lay down the package (per the release manifest; engine/data/ left empty, not packaged)
   ▼
3 home-directory wiring (profiles/settings/.env; ~/.dsh/profiles symlink per the naming table)
   ▼
4 venv (form one) or in-image dependencies (form two)
   ▼
5 three probes → hand off to installer.cli lifecycle
   ▼
6 first-run guidance: register example-project → teaching ticket seven stages → register the recipient's own project
```

**The four delivery decisions (locked)**:

1. **Release manifest**: in the package = code + `bin/temporal` + **prebuilt plugin bundles**; out = `engine/data/`, `.lane/`, `.venv`, `node_modules`;
2. **Reap the prebuild dividend**: the recipient needs no frontend build chain (node exists only to run dsh; installing a build toolchain is not required);
3. **Machine-level global names** (`~/.dsh/profiles/sandbar` + `~/.sandbar/projects/`) **v1 = single-instance assumption**: multi-instance conflicts are handled explicitly (a name collision is an error with a pointer), and true multi-instance coexistence is left to a later version;
4. **`engine/data/` stays gitignored**: in container form the entire directory is mounted as a named volume, and the mount point goes into the compose spec (interlocking with hard problem #3).

### Target naming table and migration order (host instructions v3/v4, final naming review = the host's own read-through)

| Target | Current state | Note |
|---|---|---|
| `server/engine/` (v4 revision) | `server/engine/` | The engine is properly named, dropping the poc experimental name |
| `server/sandbar/` | `server/` | Shedding the host shell's surname; note that the external symlink under `~/.dsh/profiles/` must be re-pointed in step, plus the console restart boundary |
| Plugin packages `sandbar-*` | `suyou-*` (including 61 occurrences of the `/suyou-workbench/` route prefix; both halves move in the same ticket) | |
| Queue `sandbar` | `suyou-poc` | The worker uses two queues during the transition |
| `SANDBAR_*` env (transitional compatibility alias `SANDBAR_*`) | `SANDBAR_*` | The lane's `.suyou/` → `.sandbar/` changes in the same batch |
| roles persona `{{project}}` parameterization | wording hardcodes "the suyou project" | v5 revision: drop the name, do not swap it |

**Migration order**: env → package name/routes → queues → the engine directory (a surface of 128 file paths) → the server directory (last). All complete before distribution v1 ships; **each step its own ticket and its own gate**, with acceptance = the corresponding scenario family re-run green.



### fresh-home scenario spec (R3/R6, macOS case first, recipient perspective)

**Protagonist = the recipient**: the script stars the recipient's own project throughout, with example-project serving only as first-run teaching; "sandbar as a project" is absent.

**Definition of the initial state**: a brand-new mac (or a clean `HOME` used to simulate one), with only git and Docker Desktop installed, no manual python configuration, and no clone history; the project registry is empty.

| Step | Action | Expected output (green) | Where a plain-language failure message appears |
|---|---|---|---|
| 1 | **Bring up the stack**: form two = run install.sh (container mode) → `up -d`; form one = clone → install.sh → `./sandbar init` → `./sandbar up` | Green lines from each pre-check item; three containers (form two) or engine + worker (form one) come up; three probes all green at the end plus the next-steps list | One plain-language line per failed item (with a pointer to the fix), and the red line is the troubleshooting entry point; form two's up timeout carries the compose logs tail and preserves the scene |
| 2 | **Three probes**: venv dependencies importable / console probe (3099, probe only) / engine probe (pinned address) | three green lines | Red = an overall non-zero exit pointing at the corresponding fix |
| 3 | **First-run guidance**: the console shows an empty registry → follow the guidance to register the example-project sample | the sample project enters the registry; the guidance points next at the teaching ticket | the guidance panel reports the reason registration failed |
| 4 | **Teaching ticket**: open a teaching ticket on example-project and run it through the seven stages to landing | the ticket runs fully automatically from open to landing and the result is queryable — the teaching sandbox and acceptance fixture in one | the console panel reports the worker offline / the engine unreachable |
| 5 | **The recipient's real business**: register the recipient's own project (bind-mounted at the same path, see hard problem #1) and open a real ticket on it that lands | the ticket lands; the ownership of new files in the project directory = the recipient user | — |

**Three-state injection case criteria** (for acceptance/test design; an implementation that consumes external input must carry malformed-state cases; this section is also the seed list for the **independent small scenario family of the release self-check** — it does not reuse the development repo's 156 cases, see self-reference removal #3):

- Missing: no docker → the pre-check names in plain language "install Docker Desktop + authorize directory sharing";
- Conflicting: 3099 already occupied by the development stack → the pre-check errors out with a pointer (the human chooses between the two) and does not seize the port;
- Malformed: a bad .env → red text naming the bad line; a half-broken venv (form one) → red plus a rebuild instruction; re-running a half-finished install → idempotently reaches green.

The Linux case = the same scenario re-run on Linux (with ownership mapping as the changed focus); the Windows case is not committed (see Nongoal).

### Release-blocking debt (host-decided debt, handled by dedicated migration tickets)

This must be cleared before distribution form v1 (or shipped as explicit host-acknowledged debt): every row of **§Target naming table and migration order** (env → package name/routes → queues → engine directory → server directory, each step its own ticket and its own gate); the naming of this document's distribution knobs / compose project name / uninstall subcommand is finalized together with the naming table (currently held by the "naming pending host review" placeholder).

### Pending host decisions

1. **3099 as the only external port vs an existing stack on the same machine**: running the development-stack console (3099) and the distribution stack on one machine is bound to collide on the port, and "console as the only external port 3099" contradicts "the distribution can shift port tiers". Proposal: before up, the distribution pre-checks and, finding 3099 occupied, errors out and guides the user to choose between the two (without changing the port automatically) — pending the host's decision on same-machine coexistence semantics.
2. **installer.cli container backend**: whether form two's engine lifecycle is absorbed into installer.cli (proposed yes, delivered as an implementation ticket), to avoid a second parallel entry point.
3. **Absorbing the installer domain design surface**: docs currently has no finalized installer document; whether this document expands to cover it or a separate ticket writes one is pending the host's decision.

### Acceptance criteria

- The document passes the host's review (this is a proposal draft);
- The fresh-home scenario spec (bring up the stack → three probes → open a ticket → land, fully automatic) is written down with every step verifiable, and the three-state injection case criteria are complete;
- The structure diagram of the shared init source of truth for both forms is clear (reading the diagram alone conveys the single-source-of-truth relationships).

**Callback**: this option addresses the Problem's "no written distribution path" directly with two forms plus one source of truth (the contributor tier becomes writable and self-installable, and the end-user tier exists for the first time); it satisfies R1–R7 item by item (the seven-item three-state contract / topology and port discipline / the mac fresh-home recipient perspective / the structure diagram / carrying over contract clause ⑧ / self-reference removal + example-project / the naming table + finalized structure + four delivery decisions); Nongoal keeps the npm package, Windows, keys, migration execution, and the installer interface finalization all outside the scope, so the scope does not creep.

## Related documents

- Dependencies: [test environment isolation guide](../testing-guide.md) (port red lines, test-bench topology); the engine mechanism master document (`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`); [sandbar project onboarding contract v1](sandbar-project-onboarding-contract-v1.md) (clause ⑧ version/compatibility matrix)
- Standards basis: [design doc writing guide](design-doc-writing-guide.md)
- In-repo artifacts (not docs; current path → target name in §Target naming table): `install.sh` (form one, pending implementation ticket), the repo-root `sandbar` (installer.cli), the test-bench compose surface (today `server/docker-compose.test.yml` → target `server/sandbar/` domain) + `integration/stage_docker.py` (bench no. 19), `server/probes/` (compatibility probes), roles/model-routes (today `server/roles`, `server/model-routes.yaml` → target `server/roles/`, `server/model-routes.yaml`, the cross-project generic persona library)
