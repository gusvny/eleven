---
title: Project Lifecycle Runbook (add/list/remove)
category: ops
tags:
  - sandbar
  - installer
  - project registry
  - ops
status: active
updated: 2026-09-28
---

# Project Lifecycle Runbook (add/list/remove)

> Source of truth for the epic = `notes/epics/project-lifecycle.md` (ticket ① = t260904-10: `sandbar project
> add|list`; ticket ② = t260904-14: reversible removal via `sandbar project remove`). Source of truth for the contract =
> `docs/design/sandbar-project-onboarding-contract-v1.md` ①a/①b/②a. Source of truth for loading =
> `server/engine/shared.py` (Python) and `server/project-registry.ts` (TS,
> consumer of the workbench API) — both sides use the same registry with isomorphic semantics.

## Command face

```bash
# Register a new project (fail-closed validation + atomic write + onboarding health report)
sandbar project add --key <key> --name <display-name> --dir <absolute-project-root> [--json]

# List all registry and quarantined entries + ticket counts (degrade with a hint when Temporal is unreachable; the command does not go red)
sandbar project list [--json]

# Remove a project (reversible: project.yaml is retired by rename; no data is deleted by default)
sandbar project remove --key <key> [--json]
sandbar project remove --key <key> --dry-run     # full gate rehearsal: prints only the rename/delete manifest, zero on-site change
sandbar project remove --key <key> --purge-data          # delete <key>/data/ after removal (only once the gate passes)
sandbar project remove --key <key> --purge-credentials   # delete credentials.yaml after removal (independent flag)
sandbar project remove --key <key> --confirm-last        # mandatory when removing the last registered project
```

Exit codes: `0` = green; `1` = red (semantic rejection, the FailClosed channel); `2` = usage error (the argparse face).
`--json` makes all three commands machine-decidable; the UI (ticket ③) and scripts share the same stance.

## Where the registry lives

- Per-key directory mode (current): `~/.sandbar/projects/<key>/project.yaml`; the environment variable
  `SANDBAR_PROJECTS_DIR` can point at another root (test/multi-machine scenarios).
- Legacy single-file mode (read-only compatibility): when the environment variable `SANDBAR_PROJECTS_YAML` is present, the runtime reads the old
  single file. **In this mode `project add` / `project remove` are rejected** — writes go into per-key directories that the runtime
  cannot read (a silent no-op; for remove it means "a fake successful removal"), and the tool prefers refusing over creating a split brain.
  Remove that env var and retry.
- The first time add/list runs against a non-existent registry root, the loader auto-seeds existing entries from the migration seed
  `server/projects.yaml` and drops a `.migrated` marker — this is the loader's current semantics, which the tool neither bypasses nor second-guesses.

## add: pre-validation checklist (any failure = rejection, zero registry residue)

| # | Gate | Rejection condition | Distinguishing wording |
|---|---|---|---|
| a | key whitelist | fails `^[a-z0-9][a-z0-9-]{0,40}$` (lowercase letters/digits/hyphens, starting with a lowercase letter or digit, upper bound of 41 characters) | "invalid key" |
| b | single-root model | `--dir` given zero times or several times (multiple directories = ambiguous ownership; for multi-repo projects, use the parent directory as the root) | "single-root directory model" |
| c | key not registered | already registered (including a quarantined entry of the same name) → **an idempotent re-run gives the same verdict** (same exit, same wording) and never rewrites | "already registered", "idempotent" |
| d | roots do not cross | equal to an existing project root / nested as parent-child / crossing paths → report **both keys** | "crossing or parent-child" |
| e | not legacy | `SANDBAR_PROJECTS_YAML` is present | names the env var and points the way |
| f | load first | the pre-load runs the loader's full semantics (auto-seed / on-site determination / fail-closed on a mixed site); a failed load = red | "registry load failed" |
| g | scalar values | name non-empty, leading/trailing whitespace is trimmed; name and root directory contain no `#` and no newline (on write they would be stripped as a comment by the loader or would break the structure) | names `name`/`root_dir` |

The write is atomic: first an `O_CREAT|O_EXCL` exclusive claim on `<root>/<key>/project.yaml` (two concurrent adds for the same
key give exactly one success and one rejection, the loser reporting an idempotent rejection, with no silent overwrite), then tmp+rename to land the content,
and finally a post-write self-check (parseable by the loader + zero quarantined entries across the whole table). Any failing step rolls back and cleans up, leaving no
half-built entry in the registry.

**The directory may already exist**: the `<registry root>/<key>/` directory and `credentials.yaml` may be placed by hand before add
(contract ①b user journey); the exclusive anchor is the project.yaml file rather than the directory.

## add: onboarding health report (warnings only hint, do not write on your behalf, do not block; exit 0)

| Class | When present/declared | When missing/undeclared |
|---|---|---|
| verify.yaml | — (the carrying location is chosen by the project registration itself, contract ②a; `.sandbar/` is not a mandatory path, and the tool does not guess paths) | warning "verify.yaml location not declared": if the first dev-lane ticket needs integration tests and the project has not provided them itself, it will go red on the integration lane |
| credentials | green line "per-key credentials.yaml present" | warning "falling back to the dsh platform file" (`DSH_HOME/.credentials.yaml` → `~/.dsh/.credentials.yaml`, the ①b deprecation-window stance). **add does not copy it for you** (ruled 260904) |
| paths | — (this tool does not produce a paths section) | warning "paths section not declared": roles_dir/model_routes fall back per the current convention |

The tool writes no file in the project repo on your behalf — project policy is the project's own business (contract: mechanism in the IDE, policy in the project).

## remove: the four-step gate order (contract ①a-1; any failure = exit 1, zero on-site change)

| # | Gate | Rejection condition | Distinguishing wording |
|---|---|---|---|
| 0 | mode gate | `SANDBAR_PROJECTS_YAML` is present (a retire/purge writing into a per-key directory = a fake successful removal the runtime cannot read) | names the legacy env var |
| 1 | load/key gate | registry load fails; key not registered (reported distinctly from a quarantined entry of the same name, including how to locate `<dir>/project.yaml`); invalid key | "not registered", "quarantined" |
| 2 | last-entry gate | removing the last registered project without `--confirm-last` (the zero-entry warning = naming the loader's empty-table error semantics) | "--confirm-last", "empty table" |
| 3 | in-flight gate | a Temporal query by ProjectKey returns non-empty RUNNING tickets → **refuse the removal and report each ticket number**; Temporal unreachable / SDK missing / channel returning corrupt JSON → **fail-closed refusal with no bypass flag** (ruled 260904: to remove, run `sandbar up` first; if the engine is truly dead, take the manual path and read the red-line section first) | the ticket number list; the two states "unreachable" and "sdk-missing" are distinguishable (KI-039) |

All four gates passed → **retirement by rename**: `<root>/<key>/project.yaml` is atomically renamed within the same directory to
`project.yaml.retired-<UTC>` (no data is deleted; the loader already skips subdirectories without project.yaml
= the entry goes invisible immediately; **reversible**: rename it back and the entry returns). If a retired file already exists in the same directory (a same-second collision) = rejected
and named for manual handling. After the rename a post-write self-check runs (the load no longer lists this key, the whole table shows zero change); if the self-check fails, the rename is rolled back;
if project.yaml is found in place again before the rollback (a concurrent add rebuilt it) → abandon the rollback and report "the on-site state has changed, please re-run",
never overwriting someone else's new entry.

**Removal report**: a byte-count ledger of data/ (archives + metrics) and credentials.yaml, a warning for the closed-but-unarchived difference set
(listing ticket numbers), the lane list of every ticket under the project root's `.lane/` (**report only, never delete**; points to teardown/manual cleanup),
and the zero-entry warning when the last project is removed. `--json` shares the same stance as the human-readable output.

**The three data-disposition states are explicitly separated** (the audit source of truth never evaporates):

- Default: the bytes of `data/` and `credentials.yaml` **are not touched**.
- `--purge-data`: gated first on "all closed are archived" — the unarchived difference set = the set of Temporal COMPLETED ticket ids
  − the set already archived on fs (**the decision anchor = the three states of `<id>/archive.json`**: present and containing `schema: v1` = archived;
  directory present but manifest missing = unarchived, enters the difference set; a malformed manifest = an immediate fail-closed naming of
  `<id>/archive.json`, never silently sided with or silently regenerated). A non-empty difference set = rejection listing the ticket numbers; only once the gate passes is `data/` deleted.
- `--purge-credentials`: an independent flag that deletes only `credentials.yaml`; may be combined with `--purge-data`.
- `--dry-run`: all gates still run, while retirement/deletion are not executed, and the rename/delete manifest is printed (paths + bytes + ticket counts),
  with the registry root byte-for-byte unchanged.

**Re-onboarding (re-add)**: after removal, re-running `project add` with the same key restores the registration; the `data/tickets/`
archive chain stays continuous (the default removal never touched the data at all).

## list: report stance

- All registry entries are listed (key / display name / root directory / ticket counts: in-flight, completed, archived).
- All quarantined entries are listed, with the reason containing the `<dir>/project.yaml` location literal (a broken file can be found right away).
- Retained directories without project.yaml (such as `data/`) are not listed (load semantics = skip).
- Ticket counts come from a subprocess querying Temporal (`client.py ticket-list` by ProjectKey). **The two degrade states are
  distinguishable and neither goes red** (exit 0): the service being unreachable (connection failure/timeout/abnormal output) and the temporalio SDK
  being missing — a missing dependency is not swallowed as "no data" (the KI-039 lesson), nor is it conflated with unreachability.
  To query real tickets, start the server with `sandbar up` first and retry.
- `--json`: `{projects:[{key,name,dirs,tickets,tickets_state,tickets_note}],
  quarantined:[{key,dir,error}], mode}`, the same columns and shape as the human-readable output.

## Failure stances

- **Concurrent double add for the same key**: exactly one success and one rejection; the winner's entry is self-consistent in name/dirs; the loser reloads and reports an idempotent
  rejection. Different keys never collide concurrently (each writes its own directory). add is defined as a single-host operating-surface command and needs
  no distributed lock.
- **Write failure** (disk full / permissions and so on): reports "rolled back (zero registry residue)"; empty directories that were created are cleaned up
  along with it, while a directory where credentials were pre-placed is kept as is.
- **Mixed on-site state** (the registry root has content but no `.migrated` marker, and it is partly related to the seed in a way that cannot be reproduced):
  the loader fails closed, and a human handles it per the error (add the marker / clear the directory and re-migrate / remove the migration source — pick one); the tool
  does not guess.
- **Deleting a `<key>/` directory by hand is still forbidden**: once remove has landed, doing so is a **bypass** — the archives (`data/tickets/`,
  the audit source of truth) evaporate with the directory, and it also bypasses the in-flight gate and the purge gate. Removal always goes through `sandbar project remove`;
  an emergency manual removal when Temporal is truly dead requires first confirming there are no in-flight tickets and taking responsibility for the gates (red-line section).
- **remove rollback with a changed on-site state**: the post-write self-check fails and project.yaml is in place again (a concurrent add rebuilt it) →
  abandon the rollback and report "the on-site state has changed, please re-run" — the new entry is not overwritten; the retired file is still there, and after checking by hand
  you can re-run remove or rename it back to restore.

## Red lines

- The console (3099) always belongs to the user's operating surface; this command family has zero contact with it.
- The registry is **read**-open (list/lookup); **writes** (add/remove/purge) go only through this installer CLI
  (the host's operating surface) and do not enter the tool bridge — dirs are the rule body of the ticket-anchoring gate, and the party judged by a gate must not rewrite its own boundary.
- The audit source of truth never evaporates: deleting by hand a key directory that contains `data/` is a permanent no-go area (no path outside remove's purge semantics
  may delete archives); `--purge-data` only acts when the unarchived difference set of all closed tickets is empty.

## Historical notes

- 2026-09-04 (ticket ① of t260904-10): first version of this runbook, covering add/list; the remove chapter was added along with ticket ②.
- 2026-09-04 (ticket ② of t260904-14): the remove chapter landed (four-step gate order / retirement by rename / purge dual flags + dry-run /
  last-entry confirmation / legacy mode gate / re-add); the "remove is always red" section was retired. For the contract stance see
  `docs/design/sandbar-project-onboarding-contract-v1.md` ①a-1 (v1.9).
