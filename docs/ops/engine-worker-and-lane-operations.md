---
title: "Engine worker and lane operations"
category: ops
tags:
  - worker
  - lane
  - integration-gate
  - code-version-attribution
  - gate-coverage
status: active
updated: 2026-09-30
---

# Engine worker and lane operations

> What this document is for: answering "**which worker served this ticket, which code was it
> running, and how far is the lane behind `main`**" without guessing, and knowing which two
> things must both be true before an engine fix can take effect on an in-flight ticket.
> The tool it documents is `server/tools/engine_ops.py` (read-only first).
> What it deliberately does not contain: ticket progress, duty rosters, or hand-over status —
> that lives in Temporal and the ticket faces.

## 1. The worker model: central worker vs lane worker

Two kinds of worker process exist, and a ticket is served by exactly one of them per task queue:

| | central worker | lane (per-ticket) worker |
|---|---|---|
| pidfile | `server/engine/data/worker.pid` | `server/engine/data/worker-<tid>.pid` |
| log | `server/engine/data/worker.log` | `server/engine/data/worker-<tid>.log` |
| queue | the shared queue (`sandbar`) | the ticket's own queue (`sandbar-ticket-<tid>`) |
| started by | the console supervisor (`server/plugins/temporal-tools/node.ts`) at boot and by its keepalive | the console supervisor's per-ticket ensure (a child process of the console, started from the console's own repository) |
| replaced by | killing it: the supervisor's keepalive brings it back within seconds | killing it: the same keepalive brings it back |
| lifetime | long-running; keepalive restarts it if it dies | ends when the ticket's workflow settles (its watcher or the console disposes it) |

Three properties follow, and every operational decision in this document is a consequence of them:

1. **A workflow is executed by whichever process polls its queue and claims the task.** With two
   processes on one queue, the result of a round cannot be attributed to a code version — this is
   not a theoretical risk: it was observed as two "worker started" lines three to five seconds
   apart in `worker.log`, and as a ticket face whose text came from one build while its counts came
   from another.
2. **A worker process loads the engine modules once, at startup.** Editing `server/engine/*.py`
   afterwards changes nothing for a process that is already running — it keeps executing the code
   it imported (the code stamp calls this `stale`).
3. **The lane tree is a snapshot taken when the ticket was created** (a git worktree at
   `.lane/<tid>` with its own checkout). Any file that changed in `main` after that moment is
   absent from the lane until the lane is synced.

## 2. The two conditions for an engine fix to take effect on an in-flight ticket

An engine fix reaches a running ticket only when **both** of these are true, and they are
independent:

| condition | what it fixes | how |
|---|---|---|
| **the lane tree is synced** | the **machine gate**: it runs the project's integration command *inside the lane* (`integration/run_scenarios.py` plus its fixtures, read from `.lane/<tid>`), so a fix that lives only in `main` is not the code the gate executes | `engine_ops.py sync <ticket>` — one merge of `main` into the lane, idempotent, through the engine's single "merge a ref into the lane" implementation (the `prepare_conflict_resolution` activity) |
| **the serving worker process is replaced** | the **workflow and activity code**: the process that serves the ticket keeps the modules it imported at startup | kill the process (`engine_ops.py restart --scope lane:<ticket>`, or `--scope central`) and let the console supervisor's keepalive start a fresh one, then verify exactly one live poller |

Neither condition implies the other. Syncing the lane without replacing the process leaves the
ticket served by old code; replacing the process without syncing the lane leaves the gate
verifying a tree that does not contain the fix. When in doubt, check both with the three routine
checks below.

## 3. Three routine checks before pushing a ticket

Run these before handing work to a ticket (they are cheap and read-only):

```bash
PY=server/engine/.venv/bin/python
"$PY" server/tools/engine_ops.py drift <ticket>   # 1. lane behind main? worker stale? pollers == 1?
"$PY" server/tools/engine_ops.py who <ticket>     # 2. which process served the last gate round
"$PY" server/tools/engine_ops.py workers          # 3. every worker, its tree, its poller count
```

* `drift` exits **1** and names each problem when the lane is missing engine files that landed in
  `main` (code only — documents are listed separately and never raise an alert), when the lane
  worker's code stamp is `stale`, or when the live poller count for the ticket's queue is not
  exactly one. An **unavailable** poller face is itself an alert: "cannot prove exactly one" means
  "do not push".
* `who` reads the workflow's event history: every activity execution carries the `identity` of the
  worker that ran it (`<pid>@<host>`), so the gate rounds can be listed one by one and the serving
  process can be resolved to its tree and code stamp. When Temporal cannot be reached the command
  says so and exits 2 — it never guesses.
* `workers` enumerates every pidfile in the engine's `data/` directory, resolves each live process'
  working tree, and reports the **live** poller count per queue.

**Poller counting rule (do not skip it):** count only pollers whose process is alive. The server
keeps a just-exited worker's entry in its poller history, so counting list entries reports the
worker that was replaced moments ago as a second poller. `engine_ops.py` classifies pollers into
`live` / `stale_history` / `unverifiable` for exactly this reason.

## 4. Restart discipline: kill it, do not start it

- `--old-drain <sec>` (default 90): how long the tool waits for the **old** worker to actually disappear before waiting for the supervisor's replacement. A worker stops gracefully and may keep draining in-flight activities for a while; during that window "new pid already present while the old one still drains" is a **legitimate intermediate state**, named in the result, not a failure.

**The only sanctioned handover is: kill the existing worker and let the console supervisor start
a new one.** Operators and agents do not start workers; `engine_ops.py restart` implements exactly
that and nothing else.

```bash
"$PY" server/tools/engine_ops.py restart --scope lane:t260930-09    # kill, then wait for respawn
"$PY" server/tools/engine_ops.py restart --scope central
```

The command locates the worker through its pidfile, sends `SIGTERM` (graceful), and then waits —
bounded, `--wait` seconds, 60 by default — for all three of:

* the pidfile holds a **different** pid,
* that pid is alive,
* it is the **only live poller** on the queue (when the poller face is reachable).

On success it reports the new pid, its start time and the poller proof. If nothing comes back in
time it fails loudly (`exit 1`) naming the supervisor to check — it never starts a worker itself.
The poller face being *unavailable* is also a failure: "cannot prove exactly one" is not a pass.
`--replace` is now only an alias for this behaviour (the old "stop the old one and start a new one
myself" semantics was removed).

### Why not start it ourselves: the sandbox inheritance incident (t260930-09, 260930)

A worker started from an agent session inherits that session's sandbox (`workspace-write`), and
then **every write outside the workspace fails closed**. The failure surfaces far from the worker,
in the ticket's last step:

```
PermissionError: [Errno 1] Operation not permitted:
'/Users/user/.sandbar/projects/sandbar/data/tickets/t260930-09'
```

That is the archive step of `merge`, which runs in the serving worker. With two such workers
(sandboxed central + sandboxed lane worker), the ticket that had already been signed could not
finish: it sat in `merge/blocked` — fail-closed, so the lane and its branch were preserved rather
than half-merged. The resolution was exactly the discipline above: those two workers were killed
and left to the console supervisor, which started replacements (central `99016`, lane `98999`)
outside the agent session; the ticket was signed again, the archive succeeded, and it closed with
the lane and branch torn down.

Consequences worth remembering:

* "I started a worker to help" is how a ticket ends up unable to archive. Killing is cheap because
  the supervisor restores service within its keepalive interval (5s by default).
* A worker's environment is part of its identity. `server/engine/data/worker*.log` and the
  ownership meta (`<pidfile>.meta`) both name what ran; the ticket face carries
  `worker_identity` and `code_stamp` for the same reason.
* Foreground workers write no pidfile, so nothing can find or replace them; they are for debugging
  on a private queue only.

### What if the supervisor is not running

Then nothing brings the worker back, and `restart` says so: it exits 1 naming the pidfile, the old
pid and the deadline, and tells the operator to check the console session (3099) and the
`temporal-tools` supervisor. That is a genuine incident, not something the tool papers over.

### Verifying the handover took effect

1. `engine_ops.py restart ...` — new pid, alive, exactly one live poller.
2. `engine_ops.py who <ticket>` after the next gate round — the round's activity `identity` should
   be the **new** pid.
3. `engine_ops.py drift <ticket>` — the lane worker is no longer `stale` (assuming the lane tree
   was synced first; see §2).

## 5. Tool reference

```bash
PY=server/engine/.venv/bin/python

# who is working, on which tree, with which code stamp, and how many live pollers per queue
"$PY" server/tools/engine_ops.py workers

# which round was served by which process (per gate round, plus the last 40 activities)
"$PY" server/tools/engine_ops.py who t260930-09
"$PY" server/tools/engine_ops.py who t260930-09 --round 3     # a specific gate round

# pre-push verdict (exit 1 = drift or poller count != 1, with every item named)
"$PY" server/tools/engine_ops.py drift t260930-09

# merge main into the lane once (idempotent; the engine's own merge implementation)
"$PY" server/tools/engine_ops.py sync t260930-09 --dry-run     # show what would come in
"$PY" server/tools/engine_ops.py sync t260930-09               # do it
"$PY" server/tools/engine_ops.py sync t260930-09 --abort       # reset a half-finished merge

# hand a worker over: **kill only** — the console supervisor's keepalive starts the new one
"$PY" server/tools/engine_ops.py restart --scope lane:t260930-09    # --wait N bounds the wait
"$PY" server/tools/engine_ops.py restart --scope central
```

Output is a single line of JSON (`{"ok":…,"result"|"error":…}`), like the rest of the tool family.
Exit codes: `0` normal, `1` alert (drift or poller count), `2` environment face unavailable
(Temporal unreachable, engine venv missing). `--repo <path>` points the tool at another repository
(multi-project operations, or offline fixtures).

Representative output (trimmed):

```json
{"ok": false, "exit": 1,
 "error": "泳道缺 11 个**已落 main 的引擎面文件**（先 sync 再推票）：server/engine/agent_activities.py, …；泳道 worker（pid=63268，起于 2026-09-30T16:09:09）**代码指纹 stale**：agent_activities —— 换进程前它跑的是改动前的码",
 "result": {"ticket": "t260930-09", "verdict": "drift", "behind_commits": 5,
            "lane": {"path": ".lane/t260930-09", "branch": "lane/t260930-09",
                     "source": "ticket snapshot"}}}
```

```json
{"ok": true, "result": {"ticket": "t260930-09", "workflow_type": "LightLaneWorkflow",
 "gate_rounds": [{"round": 5, "at": "2026-09-30T12:21:13",
                  "activity": "run_integration_tests", "identity": "63268@192.0.2.132"}],
 "serving_worker": {"pid": 63268, "alive": true, "tree": "/Users/…/sandbar",
                    "pidfile_state": "live", "registered_for_this_ticket": true,
                    "stamp": {"stale": ["agent_activities"]}}}}
```

## 6. What the lane gate does *not* cover: the pool scope of the round

A green lane round is narrower than it looks, and the difference is deliberate (host ruling
260914, implemented by `verify_lane._integ_pool_exclude`): **every ticket round skips the
declared pools** (today `engine` + `exclusive` — 87 of ~362 entries, the heavy real-chain
scenarios that boot stages and real workers). "Declared = skipped", with no per-ticket
exception: the excluded pools are covered **only by the project-level full runs** (the daily
inspection, a manual full run, or a replay).

What that means when you read a green round:

* the round proves the `ro` / `main` / `browser-free` / `browser` face — including every
  scenario that reads the *engine modules* offline — is green on the lane tree;
* it does **not** prove the real-chain (stage-booting) behaviour. For a ticket whose write set
  is the agent/engine core (say `server/engine/agent_activities.py`), that half rests on the
  developer's L1 plus whatever the gatekeeper runs by hand, and its observation post is the
  daily inspection / the closing full run.

So before signing a core-engine ticket, run the target's own unit surface yourself (and, when
the change is in an agent stage, the engine suite), and say in the sign-off note which half is
proven by this round and which half is not. "The gate is green" must never be read as "the real
chain was exercised".

## 7. Where the same facts appear on the ticket face
The machine gate receipt carries two structured keys and one human line, so nobody has to
remember them:

* `worker_identity` — the serving worker of that round (`<pid>@<host>`, the same string the
  event history records);
* `code_stamp` — that process' code fingerprint, including `stale`;
* the receipt summary ends with one line, for example
  `Verified by worker 63268@192.0.2.132 (code stamp agent_activities@2026-09-30T16:43:37;
  started=2026-09-30T16:09:09; stale=agent_activities)`.

When either value cannot be obtained, the face says so explicitly (`unavailable: <reason>`) — an
unattributable version is itself a fact that must be visible, never a blank.

## 8. The console is a long-lived process too (plugin changes need its restart)

The console (127.0.0.1:3099) is the host's operation surface and it holds the **host-side plugin
code it imported at startup** (`server/plugins/*/node.ts` and their `src/` imports, resolved
through `~/.dsh/profiles/sandbar` → `server/profile`). Merging a plugin fix into `main` therefore
changes a file that a *running* console will not notice: the route keeps answering with the old
logic. This is the same "long-lived process, stale code" class as the lane worker (sections 2 and
4) and as the shared test console, and it has a real cost: on 261001 the executor panel kept
answering the *pre-fix* degradation (`SANDBAR_WORKBENCH_BASE unset`) for a full day after the fix
merged, and the host read that as "the panel still does not work".

How to tell, without restarting anything (all read-only):

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3099/sandbar-executor-panel   # page: 200 = mounted
curl -s 'http://127.0.0.1:3099/sandbar-executor-panel/api/grants?project=sandbar' | python3 -m json.tool
```

A `"degraded": true` whose reason names a **missing config** (`…unset`) is a fingerprint of
pre-t260929-22 code: the current code resolves the base from the request origin and can only
degrade for a **reachability** reason. Compare that against what the code on disk would answer
(the panel's own L1 plus the registered scenario `t260929-22-grants-upstream-400-text` both pass
on the current tree), and if the live answer is older than the tree, the conclusion is
"the console needs a restart", not "the panel is broken".

**Boundary**: restarting 3099 belongs to the host. It is the GUI's own process (and, for an agent
session talking through it, its own connection); the repo rules forbid code, tests and installers
from restarting, stopping or occupying it. An agent's job here is to name the staleness, name the
evidence, and hand the restart over. A *second* console instance is not a workaround either: its
temporal-tools supervisor would manage the same workers.

Before a restart, the lower bound on a console's age can be read off its own routes: a panel route
answering 200 proves the process started after that plugin's mount commit, while a pre-fix answer
from one of its endpoints proves it started before that fix.

## 9. Boundaries

* Default is read-only. The only mutating subcommands are `sync` (one merge of `main` into the
  lane, through the engine's own implementation) and `restart` (which kills a worker — and never
  starts one: starting is the console supervisor's job, see §4).
* `sync` never resolves conflicts on its own: a conflicting lane is reported with the file list,
  and resolution stays with the engine's existing conflict loop (the ticket face's
  `rework(to_stage=implement)`) or a human. `--abort` resets a half-finished merge through the
  engine's settle activity, never by hand.
* The console's port (3099) is the user's operation surface and is never touched.
* Nothing here changes gate criteria, reason codes or attribution rules; the tool reports what the
  engine already decided.

## 10. When a ticket must change a derived or generated path outside its write set

This is the operational recipe for a shape that stopped three tickets in one night (261009/261010,
`t261009-22`, `t261009-35`, `t261008-47`), and it is worth recognising early because no amount of
re-driving the lane can converge.

**The shape.** The merge gate demands a file the write set forbids. Two instances:
a **build output** (`server/plugins/workbench/lib/` must be rebuilt in the same batch as a change
under `server/plugins/workbench/src/client/` — the `bundle_pairs` rule in
`server/merge-checks.yaml`), and a **generated file** (`server/workflows/*.yaml`, output of
`server/engine/gen_workflows_doc.py`, whose change must land in the same commit as the code it was
generated from). In both cases the settle's path gate is right to refuse the derived path — the
ticket's frozen write set does not name it — and the two verdicts are each correct and mutually
unsatisfiable. A `rework` repeats the same work; a `retry_qc` re-measures the same red.

**What does not help.** Rebuilding the output in the lane. The lane can build it and the settle
will still refuse it, so it never enters a commit (`git log -1 -- <out>` keeps naming an older
commit). Do not read the loop as "the settle drops worktree work": measure it with
`git diff --name-only main...HEAD`, which shows the source change and no output change.

**The route that works — widen the write set through the plan, or hand the path to a ticket that
owns it.**
1. **Widen through the plan (the documented mechanism).** The write set is refreshed as a **union**
   after `review_plan` passes, and the added entries come from the `create_plan` receipt's
   `files_changed` (`dev_lane.py::_refresh_write_set_after_plan` → `shared.refresh_write_set`,
   behind `REFRESH_WRITE_SET_PATCH_ID`). So `rework` the ticket to `create_plan` and require the
   new plan to list the derived path **by name** in `files_changed` — an empty or forgetful receipt
   silently no-ops the refresh (the KI-049 shape, which cost three tickets hours), while a listed
   path widens the surface without shrinking the existing entries. Verified end to end on
   261010: the receipt listed both yaml paths and the ticket's `write_set` gained exactly those two
   entries, keeping the original ones.
2. **Hand the path over.** When the derived file is not this ticket's business, a ticket whose own
   write set contains it can act — for generated files, regenerate rather than patch, and keep the
   "generated artefact lands with the source it came from" invariant.
3. **Human routes.** A protected path is a human decision (the `authorize` operation,
   `kind=protected_path`, with `scope` and an `expires` in epoch seconds), and the main-tree route
   stays available for a change that should not go through a lane at all. Note the boundary: the
   authorization face covers **protected paths only** — it does not unlock an ordinary write-set
   violation.

**What to check afterwards.** That the receipt names the path, that the ticket's `write_set` shows
the added entries without losing the old ones, and that the previously red check goes green at the
next merge check.

