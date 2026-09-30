---
title: "Engine worker and lane operations"
category: ops
tags:
  - worker
  - lane
  - integration-gate
  - code-version-attribution
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
| started by | the console supervisor (`server/plugins/temporal-tools/node.ts`) at boot and by its keepalive; or an operator via `worker.py --daemon` | the console supervisor's per-ticket ensure (a child process of the console); or the engine-side helper `server/engine/ticket_worker.py` |
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
| **the serving worker process is replaced** | the **workflow and activity code**: the process that serves the ticket keeps the modules it imported at startup | `engine_ops.py restart --scope lane:<ticket> --replace` (or `--scope central`), then verify exactly one live poller |

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

## 4. Restart discipline

* A daemon start **refuses** to run when the pidfile names a live process (named error, exit code
  2). This is deliberate: a second process on the same queue is the failure mode this whole
  document is about.
* `--replace` is the explicit takeover: the old worker is asked to stop (`SIGTERM`, graceful), the
  new start waits a bounded time for it to exit, and then takes the slot. A timeout is an error —
  the path never KILLs silently, because cutting an in-flight agent activity in half leaves the
  ticket carrying the damage.
* A stale or malformed pidfile is taken over normally, with a log line saying so.
* Foreground runs write no pidfile and therefore cannot be guarded. They are for debugging; one
  that lands on a shared queue while a daemon worker is alive prints a loud warning naming the
  process it would be doubling.
* **After any restart, verify exactly one live poller before pushing a ticket.**

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

# replace a worker process (guarded; --replace is required when one is alive)
"$PY" server/tools/engine_ops.py restart --scope lane:t260930-09 --replace
"$PY" server/tools/engine_ops.py restart --scope central --replace
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

## 6. Where the same facts appear on the ticket face

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

## 7. Boundaries

* Default is read-only. The only mutating subcommands are `sync` (one merge of `main` into the
  lane, through the engine's own implementation) and `restart` (through the engine's own spawn
  face and startup guard).
* `sync` never resolves conflicts on its own: a conflicting lane is reported with the file list,
  and resolution stays with the engine's existing conflict loop (the ticket face's
  `rework(to_stage=implement)`) or a human. `--abort` resets a half-finished merge through the
  engine's settle activity, never by hand.
* The console's port (3099) is the user's operation surface and is never touched.
* Nothing here changes gate criteria, reason codes or attribution rules; the tool reports what the
  engine already decided.
