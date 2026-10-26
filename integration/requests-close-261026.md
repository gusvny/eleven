# Requests closable by evidence — 261026

Source: `~/.sandbar/projects/sandbar/requests.jsonl` (append-only ledger).
Rule: a head is closable when EVERY ticket id its text mentions is already archived in
`data/tickets/` (the archive is written at close). Each row names the head, its kind, the
tickets it cites and the question text, so a reader can check the claim row by row.

Condition to attach (engine vocabulary, `op=condition`): `{"kind":"ticket_closed","ticket":"<id>"}`.
The sweep then closes the head with the observed ticket status as its evidence.

| # | request id | kind | cited tickets (all archived) | question |
|---|---|---|---|---|
| 1 | `req-1792467684317-0001` | blocker | t261019-44 | main mid-edit: L16 red blocks 44. Commit the anchors row? |
| 2 | `req-1792469138561-0001` | blocker | t261019-45 | 45 stops on an identical face. Rule it clear, then I retry? |
| 3 | `req-1792471571045-0001` | blocker | t261019-45 | 45 stopped again; the stamp fix is silent. Which exit? |
| 4 | `req-1792476275984-0001` | blocker | t261009-30, t261019-41, t261019-44, t261019-45 | Two landings wait on a line round. Kick one? |
| 5 | `req-1792477537895-0001` | blocker | t261019-32 | 32: annex request_thread.py, and is red 2 a caliber gap? |
| 6 | `req-1792483832108-0001` | finding | t261019-32 | Gate receipt counts 8 over the list, every round. Why? |
| 7 | `req-1792590209058-0001` | blocker | t261021-08, t261021-10, t261021-12 | Your uncommitted main edit blocks all merges. Commit it? |
| 8 | `req-1792590477108-0001` | blocker | t261021-06 | t261021-06: bundle delete cannot land. Delete it at merge? |
| 9 | `req-1792592130018-0001` | blocker | t261021-06, t261021-08 | Line fix on main needs a console restart. Restart it? |
| 10 | `req-1792595358469-0001` | blocker | t261021-06 | Correction: the console restart is unproven. Line stalls. |
| 11 | `req-1792627960807-0001` | blocker | t260911-02, t260913-02, t261021-06 | Line is red: sandbar-test namespace is missing. Create it? |
| 12 | `req-1792629392611-0001` | blocker | t260910-04, t261021-15 | 091a8d1d left 3 lint errors on main. Fix them? |
| 13 | `req-1792632081153-0001` | blocker | t260904-10, t260904-15, t260904-19, t260905-03, t260910-06, t260910-11, t260911-02, t260913-02, t260913-05, t260915-08, t260915-20, t260916-02, t260916-22, t260916-26, t260917-02, t260925-21, t260929-07, t261003-13, t261006-12, t261008-02, t261008-24 | Line round: 20 env-fails, 8 real fails, cut at 15 min. |
| 14 | `req-1792660628380-0001` | blocker | t260904-15 | Main has committed conflict markers. Clean them? |
| 15 | `req-1792663295914-0001` | blocker | t261022-14 | The red-line refusal names the wrong command. Fix? |
| 16 | `req-1792677704968-0001` | blocker | t261009-16 | The fast-set red is a false positive in the check. |
| 17 | `req-1792736065567-0001` | blocker | t260904-15, t261021-07, t261021-10, t261021-12, t261021-13 | Main's marker lines now block the merge queue. Delete them? |
| 18 | `req-1792738158759-0001` | blocker | t261021-07, t261021-08, t261021-12, t261021-15, t261022-09, t261022-14 | Load-only self-check reds bounce tickets. Change the rule? |
| 19 | `req-1792738832690-0001` | blocker | t261022-14 | The test bed is down again. Bring it up? |
| 20 | `req-1792740019114-0001` | blocker | t261021-14 | t261021-14 hit the arbitration cap. Authorize it? |
| 21 | `req-1792740618080-0001` | blocker | t260913-03, t261009-01, t261021-06, t261021-11, t261021-15 | The line red implicates landings. Open a fix ticket? |
| 22 | `req-1792741336055-0001` | blocker | t261021-14, t261022-12 | A second ticket hit the same cap. Authorize both? |
| 23 | `req-1792742121127-0001` | blocker | t261021-06, t261021-07, t261021-10, t261021-11, t261021-13, t261021-15, t261022-09, t261022-12, t261022-14 | Union rule and L16 dead-anchor rule collide. Rule? |
| 24 | `req-1792743573833-0001` | blocker | t261021-10, t261021-13, t261022-14 | ran=0 cannot certify green, so the ticket cycles. Rule? |
| 25 | `req-1792744412716-0001` | blocker | t261021-15 | Plan lists no files, so the write set cannot widen. Rule? |
| 26 | `req-1792749871475-0001` | blocker | t261021-07, t261021-15 | Host load 178 stalled the engine. Shed load? |
| 27 | `req-1792753824304-0001` | blocker | t261021-11, t261022-09, t261022-14 | Lane reds need booking; baseline is protected. Who edits? |
| 28 | `req-1792765239596-0001` | blocker | t261021-07, t261021-12 | Landing proof needs a full round. Lanes run targeted ones. |
| 29 | `req-1792767548725-0001` | blocker | t261021-07, t261021-10, t261021-12, t261021-13, t261021-14, t261021-15 | Landing remedy needs git merge. Lane agents cannot merge. |
| 30 | `req-1792785176733-0001` | question | t261021-10 | Anti-churn stop blocks a green ticket. Rule it? |
| 31 | `req-1792786173254-0001` | question | t261021-11, t261021-12, t261022-12 | Lanes merge main, fixes land on develop. Promote? |
| 32 | `req-1792790478489-0001` | question | t261021-12, t261021-14, t261021-15, t261022-12, t261024-01 | Fix ticket waits for a session. Who works it? |
| 33 | `req-1792792867792-0001` | question | t261021-12, t261021-14, t261021-15, t261022-12 | Force one line round now? Proof says green. |
| 34 | `req-1792796967140-0001` | question | t260907-04, t261003-13, t261006-12, t261008-02, t261024-01 | Five UI journeys always ENV_FAIL. Green is unreachable. |
| 35 | `req-1792798911372-0001` | question | t261022-14 | Main itself fails lint L7. Every lane inherits it. |
| 36 | `req-1792808345281-0001` | question | t260915-20, t260916-02, t260916-22, t261021-14 | Line worktree is dirty. No lane can land. |
| 37 | `req-1792809842246-0001` | question | t260916-22, t261021-14, t261021-15 | Book row points at a missing commit. Lanes cannot land. |
| 38 | `req-1792840612443-0001` | question | t261022-14 | KI-350 anchor refresh misses a lane; the gate then runs 0 |
| 39 | `req-1792857851419-0001` | question | t261022-12, t261022-14 | A green gate round passes but the face does not move |
| 40 | `req-1792897024876-0001` | finding | t260915-08, t261024-16, t261025-08 | Line round is green but no certificate covers the landing |
| 41 | `req-1792898730355-0001` | question | t261021-11, t261022-09, t261022-12 | t261022-12 hit the arbitration cap. Authorize it? |
| 42 | `req-1792899733814-0001` | finding | t261022-12 | Your rerun cannot clear the arbitration cap |
| 43 | `req-1792900450933-0001` | question | t261022-12 | t261022-12 hit the anti-churn stop. Ruling? |
| 44 | `req-1792901615063-0001` | blocker | t260915-08, t261022-14, t261024-16 | The develop line is frozen. No landing can proceed. |
| 45 | `req-1792904340332-0001` | blocker | t261009-16, t261011-11, t261018-01, t261022-09, t261022-14 | Fast-set tests are red. The landing certificate is red. |
| 46 | `req-1792935243452-0001` | blocker | t261014-04, t261025-11 | Lane branch and lane worktree diverged. Which one wins? |
| 47 | `req-1792936318415-0001` | blocker | t261025-11 | t261025-11 closed as landed. The line never got it. |
| 48 | `req-1792939272341-0001` | question | t261025-13 | t261025-13 needs a write-set ruling, or a second ticket |
| 49 | `req-1792943689176-0001` | blocker | t261025-12 | The same freeze now blocks a landable ticket |
| 50 | `req-1792944284918-0001` | question | t261025-13 | The engine stopped it twice. Which option do you take? |
| 51 | `req-1792944821053-0001` | blocker | t261025-13 | The write-set widening did not take. Plan list is empty |
| 52 | `req-1792948541461-0001` | blocker | t261025-14 | The new freeze has a victim: t261025-14 is stopped |
| 53 | `req-1792950291458-0001` | blocker | t261025-12, t261025-13, t261025-14, t261026-01, t261026-03 | One freeze now holds five finished tickets |
| 54 | `req-1792951437704-0001` | blocker | t261025-13, t261026-02 | Golden re-record has no lawful path for an agent |
| 55 | `req-1792952331153-0001` | blocker | t261025-11, t261025-12, t261025-14 | Second false green, two tickets at once |
| 56 | `req-1792952750901-0001` | blocker | t261025-13 | t261025-13 carries work no stage will accept |
| 57 | `req-1792953648755-0001` | blocker | t261025-13 | Your implement order will hit the same gate again |
| 58 | `req-1792954668329-0001` | blocker | t261025-13, t261025-14 | A landed fixture blocks t261025-13 arbitration |
| 59 | `req-1792955989461-0001` | blocker | t261014-04, t261025-13 | Detached lane again. The two sides are identical |
| 60 | `req-1792957125839-0001` | blocker | t261025-13 | The lane will not merge the line, whatever I ask |
| 61 | `req-1792958798423-0001` | question | t261025-13, t261025-14 | Authorize would move it, but it still cannot land |
| 62 | `req-1792960605272-0001` | finding | t261025-13 | Your rerun on t261025-13 cannot clear the cap |
| 63 | `req-1792962119392-0001` | blocker | t261025-13, t261025-14, t261026-02 | The same instruction fails here for a measured reason |
| 64 | `req-1792966609317-0001` | blocker | t261021-07, t261025-13 | The close names one revision, the landing names an older one |
| 65 | `req-1792972555648-0001` | finding | t261009-13, t261021-07 | Env reds are listed as high and want ten fix tickets |

Total: 65 heads. Generated 2026-10-26T08:54:22+08:00.
