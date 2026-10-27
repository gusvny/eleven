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
                  "activity": "run_integration_tests", "identity": "63268@192.0.2.X"}],
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
  `Verified by worker 63268@192.0.2.X (code stamp agent_activities@2026-09-30T16:43:37;
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


## 11. Answering the executor's request ledger as the steward on duty

The executor files blockers into `~/.sandbar/projects/<key>/requests.jsonl`; the ticket face and the
panel render them as a thread. Two row kinds matter here, and they are **not** interchangeable:

- **`reply` (the sanctioned path).** Write it through the engine's own entry point rather than by
  editing the file:

  ```bash
  PY=server/engine/.venv/bin/python
  "$PY" server/engine/request_thread.py '{"op":"reply","id":"<req-…>","intent":"fact",
    "via":"<who filed it on the decider's behalf>","caller_project":"<key>","text":"…"}'
  ```

  Row shape: `{type:"reply", id:"rpl-…", reply_for:"<req-…>", at, text, by, intent, via?}`. Two
  gates the operator meets, both by design:
  - `caller-undeclared` — pass `caller_project` (or set `SANDBAR_CALLER_PROJECT`); a session with no
    declared project identity is refused rather than guessed.
  - **a project session may ask and add facts, never answer.** `intent` is one of
    `answer` / `fact` / `ask`; a project session is limited to `fact` and `ask`. The decider's word
    arrives as an `answer` (the host answers in the panel, not through this CLI). So a steward
    relaying a *host* decision must either have the host's own words, or post a `fact` reply that
    records the escalation and the disposition, and put the *ticket-side* decision where the ticket
    can see it: a `ruling` on the ticket (`ticket.py op=ruling`, non-empty `note`).
- **`answer` (legacy, still judged).** Rows of `{type:"answer", answer_for, answer, by, at}` were
  appended directly in earlier duty cycles; the thread reader still counts them (an answer row
  moves the head to `answered`), so history stays coherent. Treat it as history, not as the shape
  to reach for: the sanctioned route is the `reply` above plus a `ruling` on the ticket.

**Rules that hold whichever row you write.** One row per fact, append-only, never rewrite the file.
State the disposition, name what the requester must **not** do (retry, rework, or find a way around
a gate), and say who owns the decision. When the request asks for something only the host can give
(a protected path, a widened write set, a design call), the steward's job is: **escalate in the same
breath, record the escalation id on the ticket, and tell the lane to hold** — a lane parked on a
named human decision is cheap; a lane invited to work around one is not.

**A ruling records; a signal moves.** `op=ruling` writes the decision into the ticket's event history —
it does **not** advance or rewind a stage. When the decision is "go back and re-plan" or "re-run the
check", the mechanism is the signal: `rework` (`to_stage=…`, with the named item in the note) or
`retry_qc`. Write the ruling **and** send the signal; a ruling alone leaves a lane that is already
looping exactly where it was (measured: a lane kept cycling implement → tests → acceptance for
several rounds after a ruling that told it to re-plan, and only moved when the `rework` arrived).

**Correction, and then a correction of that correction (261010, t261009-50).** I first wrote here
that "the plan-round union does not work" — that was **wrong**, and the lane proved it: it re-planned
with the two call-site files named, `review_plan` passed, the union admitted them, and the implement
round wrote them (`git diff --stat main...HEAD` in the lane shows `server/engine/activities.py +19`
and `server/engine/workflows.py +26`, including the wiring and its `workflow.patched` guard). The
route works.

What misled me is worth keeping, because it will mislead the next reader the same way:

- **The ticket face's `write_set` field is not rewritten when the union fires.** The union applies to
  the *round's* effective write set, so `op=show` keeps showing the original entries and a face-only
  reading says "the write set did not grow". To see whether the union took effect, read the **lane's
  diff** (`git diff --name-only main...HEAD` inside the lane) and the implement round's own statement
  (it carries a line like "Write-set union … authorized as call-site files"). Never judge the union
  from the stored field.
- **The union keys off the receipt of the *reviewed* plan round.** An older `stage_create_plan_gen*.json`
  (for example a gen-1 receipt from before the plan was re-authored) can still show `files_changed`
  = `plan.md` only. Reading a stale receipt reproduces exactly my mistake.

Two confirmed hazards in the same area:

1. **A plan/design artefact that the ticket's spec asks for must be in the write set.** Measured on
   the same ticket: `integration/<ticket>/plan.md` was rolled back by the settle path gate
   (`.sandbar/quarantine/unauth-create_plan-gen*` carries its diff) because it had no write-set seat,
   and the ticket face does not explain why. Put plan artefacts in the write set when the spec asks
   for one.
   **The same holds for a *code* file, not only plan artefacts (measured 261011, t261011-17).** That
   ticket's spec item 3 asked for a note on the ticket face; the single writer for it is
   `server/engine/dev_lane.py`, but the write set I authored named only `agent_activities.py` + the
   test dirs + `integration/`. The lane edited `dev_lane.py` anyway, the settle path gate rolled the
   edit back, and the lane's own scenario then failed against a tree where the change was absent —
   while the implement statement still said the note was present (`git diff main...HEAD` in the lane
   is the reader that settles it; the statement is not). The rule: **when a spec item names a
   behaviour, put the file that owns that behaviour in the write set** — or have the plan name it as
   a call-site file, which is what admits it to the round's effective write set.
   That rollback is **not** silent: the settle path gate preserves the reverted edit at
   `<lane>/.sandbar/quarantine/<stage>-gen*/manifest.json` with its own diff file. Measured on
   t261011-17: three entries (`unauth-implement-gen0`, `-gen0-2`, `-gen0-3` at 11:54 / 11:56 / 12:15),
   each naming `server/engine/dev_lane.py` with `"action": "reverted"`. So when a statement and
   `git diff` disagree, the third reader is the quarantine manifest — and three entries for the same
   path is the signal that the write set, not the lane, is the thing to fix.
2. **The union is a round-level authorization; the settle judges with the write set it is handed.**
   On this ticket the two files were quarantined once anyway
   (`.sandbar/quarantine/unauth-implement-gen0/server__engine__{activities,workflows}.py.diff`,
   08:17:47, right after the union-bearing round), the round's work was rolled back, and the accept
   loop restarted. Whether that was an ordering race between the write-set refresh and the settle that
   followed it is **not yet proven** — do not treat it as a known mechanism; treat it as a reason to
   check the quarantine directory (`.sandbar/quarantine/unauth-*`) when a lane's work seems to vanish
   between rounds, and to record what you find.

What actually works when the deliverable itself sits outside the frozen write set:

1. **A human widens the write set** for the named files (the host's call — say which files and why on
   the ticket), then the lane does the work itself. This is the smallest change and it stays one
   ticket. Use it when the deliverable IS the out-of-set file (a call site, a wiring point).
2. **A separate ticket owns those files**, and the original ticket's acceptance is re-scoped to point
   at it — the honest version of "hand over to the owning ticket". Do not accept a "handoff patch
   text" left in the lane: the deliverable is then in nobody's hands.
3. **Park the lane while the decision is pending** (`op=pause`): a pause takes effect at the stage
   boundary, releases the concurrency slot, and stops the rounds from burning on a blocker that no
   round can clear. Record the resume condition on the ticket; an unrecorded pause becomes a
   forgotten ticket.

The quarantine-directory reflex above replaces the old wording; nothing else from that paragraph survives.

**A reply does not clear the head — only an `answer`, a `dismiss` or a `state` row does.** The thread reader
(`server/engine/request_thread.py` `head_states`, and the panel's own merge in
`server/plugins/executor-panel/src/host/requests.ts`) derives a request's state as: head starts `open`; an
`answer` row moves it to `answered`; a `dismiss` row to `dismissed`; a `state` row sets what it says. A
`reply` row **only appends to the thread** — it leaves the head `open`, so the panel keeps showing the
request as needing the host's attention. Measured consequence (261010): five requests that had been
answered with sanctioned `reply` rows still counted as open, and the host asked for the ledger to be
cleared. Two ways out, and both are lawful: the host answers in the panel (its own word), or the steward
on duty appends an `answer` row in the host's name under the host's standing order — which is the shape
the earlier duty cycles used and what the ledger's 117 existing answer rows are. When clearing a request,
say what the disposition is, who owns the remaining action, and whether anything is still pending.

**Write the row in the STRICT reader's shape, and verify against the reader the host looks at.** (261010: I
answered six requests by hand and told the host the ledger was clear; the panel still showed six.) The two
readers of `requests.jsonl` disagree on what a valid row is:

- the engine's `request_thread.head_states` only needs an `answer` row's `answer_for` to hit a head;
- the panel's `executor-panel/src/host/requests.ts` (`isAnswerRow`) also requires **`at` to be a number**, and
  its `splitWaiting` deliberately keeps a shape-off row in the "waiting" bucket ("an over-wait beats silencing
  a possibly-open item").

So a hand-written row with `at` as a *string* is counted by the engine and **ignored by the panel** — the engine
says zero pending while the host still sees the items. Recipe for the deputy answer: `{"type":"answer",
"id":"ans-<ms>-<n>","answer_for":"<req-id>","at":<integer ms>,"by":"host（经 integration 值守会话代答；<order>）",
"answer":"…"}`, every field in the strict reader's type; and check the result with the **panel's** split
(waiting = rows whose status is not answered/resolved/dismissed/superseded). Never rewrite a bad row — the
ledger is append-only; land a corrected row (and note the correction inside it), and expect the malformed one
to keep counting in the ledger-health line.

## 12. Who signs the merge gate: the executor first, the steward as the fallback

Host order (261010): *"如果 executor 没有 sign 你再 sign，不然让 executor sign"* — the executor signs its own
ticket's `merge` gate; the steward signs only when the executor has not. This narrows the earlier standing
order ("你可以代签"), which had been read as "the steward signs green merge gates".

The executor holds the grant (`executor-grants.json`, `grants.sign = true`) and is named in the declaration's
`executor_sessions`; the ticket face and `ticket.py op=sign` are the same channel for both roles, so the
grant is the only thing that differs. The steward's own work upstream of that signature is unchanged and is
what makes the executor's signature cheap to give:

1. read the gate receipt for the **current** round (`gate_runs` last `merge_check`, and the timeline's
   `merge_check done` line) — not a stale round's;
2. check the green is against the **current** main (a `main_untouched` + `merge rehearsal` pair from before
   your own last commit to main is stale);
3. put the instruction where the lane reads it — a `ruling` on the ticket names the receipt and says "sign it
   yourself" — and say in the same note what the steward will do if the signature does not appear.

Then wait. The fallback is deliberate, not a race: a lane parked at an unsigned green gate costs one slot and
nothing else, while a steward that pre-empts the executor's signature (measured 261010: `-52` and `-55` were
signed by the steward minutes after their gates went green, before the executor's own round could pick them
up) removes the executor's chance to act on its own ticket and hides whether its sign path works at all.

**When the steward must still sign on sight:** the ticket is blocked on a human gate for other reasons and is
holding a slot while a decision is already in hand (a freeze lifting, a queue head), or the executor has said
in the thread that it cannot sign. Record `who` truthfully either way — the steward's signature carries
"host（经 integration 值守会话代签）", never the host's own name without its word.

### The shared-temp false red at the merge gate: found, cured, and how to recognise the shape again (261010)

**Resolved.** `t261009-60` landed the isolation fix (`a824147a`), so the operational restriction below no longer
applies — the section is kept because the *shape* will come back in other namespaces.

The engine suite had a test asserting **the shared system temp root has no `bundle-freshness-*` leftovers**
(`server/engine/tests/test_t261009_42_bundle_freshness.py::test_rebuild_temp_copy_reaped_on_every_path`,
`KI-01M4J0JGYJWCJ1Z2XD3KW431FV`). Any lane's `merge_check` runs the declared-build-chain freshness check, which
rebuilds the client bundle inside `TemporaryDirectory(prefix="bundle-freshness-")` — **in the shared temp root**
(`tempfile.gettempdir()` = `/var/folders/…/T` on macOS, *not* `/tmp`) for minutes at a time. So while two lanes
sat in `merge_check`, each one's suite run saw the other's live directory and reported a false red.

Measured (261010): `-55` and `-58` entered `merge_check` together at 12:29 → both red at 12:37 (`4561 passed`,
8:44 wall, one failure); `-55` alone at 12:48 → six green checks. Reproduce the mechanism in one command: create
a direct child of `tempfile.gettempdir()` named `bundle-freshness-*` and run that single test — before the fix it
failed in 0.51s; after the fix the whole file is `15 passed / 1.28s` **with the decoy still in place** (steward's
own verification, 13:5x). A decoy placed anywhere else (for example `$(mktemp -d)/bundle-freshness-*` or `/tmp`)
proves nothing, because the glob only looks at the top level of the resolved temp root.

The rules that survive the fix:

1. **A test that asserts "no leftovers" must scope the namespace to its own sandbox** (`monkeypatch` both
   `TMPDIR` and `tempfile.tempdir` — `gettempdir()` memoises its first answer, so the env alone is
   order-dependent — then glob the scoped root). The assertion must keep its teeth: an unreaped dir left by the
   *code under test* still reds. `t261009-60` also swept the class (`integration/t261009-60/sweep.md`).
2. **While such a red is live, serialise `merge_check`**: one lane at that stage at a time, retrying the others
   one at a time instead of firing `retry_qc` at every red in the same minute — that is the difference between a
   coin flip and a pass.
3. Read the red before believing it: if the failure is that one test, the round's other 4500+ cases pass, and the
   test passes alone in the lane and alone on main, it is a namespace collision — not the ticket's fault, and not
   a reason to weaken the gate.
4. Do **not** reach for `integration/known-red-baseline.json` as a stopgap: the roster's quiet rerun builds
   `python3 -m pytest …`, and the lane worker's PATH has no engine venv, so the rerun can only ever be red
   (`KI-01M4J1DZH3QBMR3HV3Q78DVJ9Q`). A row would block exactly as before, while looking like a fix.

**A signal's delivery receipt is not the same as the stage moving (261010, measured twice in one shift).** `rework`
and `retry_qc` return `delivered: true` when the signal reaches the workflow's inbox; the workflow then consumes it
at **its own checkpoint** - which is not "immediately". Two measured shapes:

1. **The ticket is parked at a segment boundary** (`paused` / `paused-waiting`): the signal lands on the ticket's
   timeline as `retry-requested` / a rework entry and the stage does **not** move until a `resume` arrives. Measured
   on t261009-50: `retry_qc` at 10:59 recorded `retry-requested`, the ticket stayed `paused-waiting` for the next
   hour, and a later `resume` consumed the pending rework in the same second (`create_plan rework` →
   `Entered step (attempt 4)`). **A parked ticket needs `resume`, not another signal.**
2. **The ticket is mid-stage with an activity running**: a rework sent to an earlier stage is accepted but sits in
   the inbox until the workflow reaches a boundary it checks - measured on t261009-46 (rework to `implement` sent
   at 16:00 while `run_integration_tests` was running; the ticket then went through `run_integration_tests done` →
   `arbitrate`/`acceptance_walkthrough` → `merge_check` without rewinding, `pending: []` the whole way).

So: **verify a signal by reading the ticket's timeline for the stage entry it should cause** (`Entered step
(attempt N)` on the target stage), never by the `delivered: true` receipt. If the timeline shows no such entry,
the signal is parked, not lost - the cheapest lawful unblock is the one the ticket's state calls for (`resume` for
a parked ticket; wait for the boundary and, if the lane blocks instead, send the signal again then - a rework sent
to a blocked ticket IS consumed).

### A tree-level red is not the ticket's account: read main's own verdict, then sync the lane (261011, twice in one night)

The shape: a lane's `merge_check` reds on `verify_lane code` (or any tree-wide lint/guard leg), the red's *cause*
is a line somebody else committed to `main`, and the ticket is charged for it. Two measured instances in one night:
a banned term in `notes/debts/known-issues.md` (committed `53bd1108`, fixed on `main` one minute later in
`bb0a7bc7` - the lane's base predated the fix, so `t261011-04` inherited the line and red-lit), and the same
mechanism one cycle earlier on `t261009-69` (`KI-01M4JV7JKGK3ATFACYN29JDVKW`).

The disposition, in order - and **never rework the ticket for this**:

1. **Read `main`'s own reading of the same judgement** (run the same lint/verify step on the main tree). If main
   is red, it is a tree-level red: fix it on main (or wait for whoever owns that line), and never send the lane
   looking for a deliverable change.
2. If main is already clean, the lane simply lacks the fix: it is a **sync** problem, not a work problem. Bring
   main in through the engine's own single point - `server/tools/engine_ops.py sync <ticket>` (optionally
   `--dry-run` first). It calls `prepare_conflict_resolution`; **never hand-write a `git merge` in a lane.**
3. Then the mechanical leg the blocked round named: `ruling` on the ticket (say plainly that the red is not the
   ticket's work, and what the lane must NOT do - do not change deliverables for it, do not edit `notes/`, which
   no lane may write) followed by `retry_qc`.
4. Confirm by the timeline (`Entered step (attempt N)` on the stage that blocked), and re-read the lane worker's
   stamp while you are there (`engine_ops workers`): a merge that only touched `notes/` needs no handover.

Why the order matters: a `retry_qc` sent before the sync re-runs the same judgement on the same tree and reds
again (the signal is consumed, the tree is unchanged); a `rework` spends a whole stage cycle to import one line of
somebody else's fix. Both look like diligence and are waste.

### Restarting the console does NOT re-environment an alive central worker (261011, found while wiring the line-round runner)

The central worker (`server/engine/data/worker.pid`, queue `sandbar`) is spawned by the console's supervisor, so it
inherits **the console process's environment**. But the supervisor only spawns when the worker is *not alive*:

```ts
if (!workerAlive()) { spawnWorker() }   // server/plugins/temporal-tools/node.ts, ensureOnce()
```

An alive worker is kept as-is (the generation rule that lets the ticket-worker ensure place a replacement belongs to
the *ticket* workers, not to this one). So: **start the console with a new environment variable and the running
central worker keeps the old one** — the new value only reaches the queue after the worker is handed over.

The sequence that actually takes effect (two steps, two owners):

1. the *host* starts the console with the variable in its environment (`./start-console.sh` prints the line-round
   runner it exports, so the startup log says which value the worker will get);
2. the *steward* hands the worker over — `server/tools/engine_ops.py restart --scope central` (kill only; the
   supervisor respawns it and the tool proves one live poller), then confirms with `engine_ops workers` that the
   new pid's stamp carries the change.

Judging it: the line-round tick names its own state on the operator surface. With no runner declared it reports
`runner_missing`; with a runner declared it produces a delivery-ledger row or a named `could_not_run`. "The console
restarted and nothing changed" is the expected outcome of doing step 1 alone.

### A new lane-flow gate NEVER applies to a ticket already in flight (261011, measured on t261009-80)

The engine gates every new workflow branch behind `workflow.patched(<patch id>)` so old histories replay byte-identically
(KI-061 discipline). The consequence is operational and easy to miss:

> `t261011-10` landed the develop-buffer two-part proof at 11:02 (`DEV_BUFFER_FAST_PROOF_PATCH_ID = "dev-buffer-fast-proof-v1"`,
> inside `if workflow.patched(...) and is_develop_buffer_ticket(...)`). The already-running buffer ticket `t261009-80`
> (history started 02:22) evaluates `patched() = False`, so its round at 11:17:30 ran the **full 581-scenario suite** again
> (`ran 581 / pass 576 / fail 1`) — not the own+fast plan the design requires. Measured, not inferred: the round's receipt
> shows 581 cases while a fresh buffer lane's closing run is the scoped plan (the fast set alone measured 13s).

Rules that follow:

1. **Do not expect a landing in flight to pick up a new proof/flow rule.** An in-flight ticket keeps the old evidence rule
   for its whole life; the only tickets that exercise a new gate are those **created after the change landed** (their history
   records the marker).
2. So "we shipped the flow fix, now the parked ticket will benefit" is false. When a new lane-flow rule matters for a ticket
   that is already running, the choices are: keep rolling the old rule (the lottery), park it, or **open a fresh ticket** to
   exercise the new rule end to end.
3. When you open that fresh ticket, say in its face that it is the **first run on the new gate** — the receipt is the evidence
   the change works (a compared wall clock or case count against the old path is the cheapest proof).
4. The same rule applies in reverse: a fix landed for legacy tickets must not be expected to change anything for a ticket that
   already opted into the new version, and vice versa.
