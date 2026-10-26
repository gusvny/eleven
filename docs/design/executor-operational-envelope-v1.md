# The executor's operational envelope v1 — run watch, stop tiers, request audience

Status: design (host-ruled 261019). Implementation is separate tickets.

## The model the host asked for

One **executor session per project** is the only long-lived operational actor: it signs what is
mechanical, repairs what is stuck, lands and promotes, and watches the runs. Every other session is
**opened for a purpose and closed**: design work, an ad-hoc investigation, a one-off repair. A person
is called only for judgement — a design decision, a ruling on intent, or a claim the records cannot
settle.

Today this fails in three observable ways:

1. **Nobody owns the runs.** A red certification freezes the line and nothing acts on it; a round
   that stops running is only noticed by whoever happens to look. Measured 261018–19: both freezes
   of the night were raised and cleared by hand by integration, hours apart.
2. **The executor cannot lift a stop it could prove is over.** Every stop is presented as
   "route to a human", including stops whose evidence says the condition has ended (an environment
   face that no longer counts as content guilt, a freeze whose releasing green certification exists).
   The executor's only move is to file a request and wait.
3. **Requests go to a person by default.** A request is the executor's (or a working session's)
   question. Most of them are answerable by the records; only judgement questions need the host.
   Without an audience and a closing condition they pile up (measured: 37 open in four days).

## 1. Run watch (the executor owns the run face)

Once per tick the executor reads the delivery ledger for its line and takes exactly one of:

* **Green certification** — nothing to do; the artifacts stay as they are.
* **Red certification whose new-regression set is environment-only** — the run is not content guilt.
  The executor records the closure through the engine's own releasing rule (the first green
  certification after the red releases the freeze episode) only when such a green exists; otherwise
  it opens a fix ticket naming the environment face and the evidence line. It never edits a
  certification and never closes a freeze over a content red.
* **Red certification with content regressions** — open (or reuse) a fix ticket against the line,
  naming the regressing cases and the run id. Do not re-run for a new answer; the range only grows.
* **No round for N hours while landings are pending** — file a request of class `run-stalled`
  (audience: host) naming the last round id, its verdict and the pending range.
* **A round that ended without a row** (could-not-run) — name it on the face and retry once; a second
  silent end is a `run-silent` request, never a silent accept.

The watch is read-only over the ledger and the rounds directory; it writes only: fix tickets,
closure rows (through the engine's writer), and requests. Every action carries the row id it acted on.

## 2. Stop tiers (what the executor may lift, and what only a person may)

| Tier | Shape | Who lifts it |
| --- | --- | --- |
| **Evidence stop** | the stop's own reason is a condition the records can disprove: an environment face (bench unreachable), a freeze whose releasing green cert exists, a landing refused only because main moved | the executor, by citing the row id, through the engine's writer |
| **Mechanical stop** | a front-door refusal that a rework or a retry_qc can clear (path gate, gate round, missing write-set entry) | the executor, by sending the signal with a written reason |
| **Judgement stop** | the stop asks for a decision the records cannot settle: two consecutive identical measurement faces, a design conflict, an arbitration verdict of tests-fault that keeps returning | a person (the host), or a session the host has told to rule in writing |

An evidence stop lifted without a cited row id is a defect, not a shortcut: the record must let a
reader check the claim. A judgement stop lifted by the executor is a defect of the same severity as
lifting a human gate.

## 3. Request audience and closing

A request carries `audience` (`host` | `executor` | `any`) and, when the records can settle it,
`resolves_when` (the delivery-ledger condition). The sweep closes a request when its condition holds,
naming the observed row; the executor answers the ones addressed to it with evidence; the host keeps
the judgement questions. A request without a condition and without an audience stays a human item.

## 3b. The executor closes what the records settle (host order 261026)

A request that the records have already answered must not wait for a person. The host put it plainly:
the executor should close the ones it can close. Two mechanisms, and the second is where the work is:

* **Declared conditions (built, was broken).** A head may carry `resolves_when`; the sweep evaluates it
  against the delivery ledger once per watch cycle. Measured 261026: the sweep could close nothing
  because its ticket reader pointed at a path that no longer exists (65 heads skipped, receipt still
  `ok:true`). Fixed under t261026-06, with the missing reader made a named receipt error.
* **Class conditions (the gap).** After the sweep worked, 49 heads stayed open and NOT ONE of them
  carried a condition — because nobody declared what would close them. Every request class the
  executor files must therefore declare its own closing condition when it is filed, from a table the
  design keeps:

  | Class | Closes when |
  |---|---|
  | run-silent | any certification row exists on that line after the head (the silence ended) |
  | run-stalled | a round row exists after the head |
  | blocker (ticket-shaped) | the ticket it names is closed, or its landing exists |
  | finding | never auto-closed: a finding is a claim, and a claim needs a human accept or a fix ticket |
  | question | only a person answers a question; the executor may close it when a later record answers it in substance, naming that record |

  A class missing from this table is a design gap to be fixed here, not a puzzle handed to the host.

* **Resolve with evidence.** For a head whose subject has ended but no condition was declared, the doer
  resolves with evidence naming the row that ended it. The engine refuses a *project* session (a worker
  cannot close its own question) and refuses dismissal to everyone but the host's panel — so the
  executor session is the actor that closes these, and its evidence must name the row.

## 4. What integration stops doing

Integration keeps: design documents, the adversarial test estate (L2/L3), audits, the known-issue
ledger, freeze and roster bookkeeping, and rulings when the host delegates one. Integration no longer
drives the routine loop (promoting every landing, retrying every stuck ticket). If integration finds
itself doing a routine action, that is a missing executor capability and belongs in a ticket, not in
a habit.

## 5. The panel's two controls (host ruling 261025, option c)

The executor panel is the host's own surface. A click there is the host's act, not an agent's, so
the panel may carry the two controls the certification tab used to only name as absent — and the
rule that decides their honesty is the same rule that retired the "auto rounds" switch: no control
without a handler, and no handler that only explains why it does nothing.

**Trigger a round.** The panel may request the next certification round. It does not run the round
inside the request: a round owns the line for tens of minutes and belongs to the scheduler, so the
request only queues it, says that it is queued, and shows what the queue is waiting on (a round
already in flight, a held guard, a missing runner). A queued request that the host cannot watch is
not a feature, so the same face must show the resulting round the moment the scheduler picks it up.

**Sign a promotion.** The panel may perform the signed promotion act, because the person clicking it
is the person the act needs. Two obligations follow:

* The recorded row names the human identity that signed, and the panel never invents one — it asks,
  or reads a declared operator for the project, and shows the value before the act.
* The engine's own refusal vocabulary is the answer the panel shows, verbatim: an agent role name
  stays refused no matter which surface sent it, and a line that cannot be fast-forwarded, a
  missing green certification or a frozen line read as themselves, never as a generic failure.

**Why this is not the executor doing the host's job.** The executor's bounds (section 2) are about
what an agent may lift on its own; these two controls are the human gate's own front door, rendered
where the human already is. An agent reaching them is the same defect as an agent signing its own
role name, and the engine's identity rules already refuse it.

**What the face must show after either act.** The act's own record (the queued request, or the
promotion row with its signer and the revisions it moved), read back from the ledger — never the
panel's optimistic guess.

## Out of scope

Per-project permissions, the panel's rendering, and the model behind the executor session.
