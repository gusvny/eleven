---
code: concurrency-limit
retired: false
summary: A per-project cap on how many stages run at once, with a queue behind it.
started: 2026-10-04
---

# concurrency-limit

## What it does

One dial per project: 1 to 10 stages running at once, or unlimited, with a queue that says where a ticket waits.

## The problem it solves

Too many parallel stages saturate the machine and the review surface; the number has to be the host's dial rather than whatever the fleet happens to reach.

## Design and rulings

`notes/discussions/261004-concurrency-limit-design.md` (pre-move source; content superseded by the rulings recorded here).

### Slot release ownership (t261027-10, KI-378 ①)

A TERMINAL ticket's slot must come back even when the ending caller cannot write
the projects root (measured: an agent sandbox got `released:false` with a
`PermissionError` on `concurrency-state.json.lock`, and four of five slots on
dengzhufpv stayed held by TERMINATED workflows). Three arms, in order of
guarantee:

1. **Natural completion** — the workflow releases its own slot on the terminal
   path (`concurrency_release` activity, worker-executed). Pre-existing.
2. **Prompt arm (new)** — the `cancel_notice` / `close_out_notice` handlers set
   `_terminal_slot_pending`; the lane's run loop releases at the next async
   boundary behind `TERMINAL_SLOT_PATCH_ID`. Engine-side: the ending caller's
   file access no longer decides whether the slot returns. The caller-side
   release in `client.py` stays as the idempotent backstop.
3. **Guarantee arm (new)** — when a project is saturated (`holders >= limit`)
   and an `acquire` is refused, the worker sweeps the holders: every holder is
   probed (concurrently, one `PROBE_TIMEOUT_S` wall-clock bound, throttled to
   one sweep per `SWEEP_MIN_INTERVAL_S` per process), and only provably-dead
   holders are dropped, under a fresh lock, with revalidation (a holder that
   renewed between snapshot and drop survives). The ledger lock is never held
   across probes.

### The two holder-reclaim judgements (rule 3 refinement)

- **Heartbeat sweep** (`HOLDER_STALE_S`): "this RUNNING holder stopped proving
  it is alive". A human-hold holder has no heartbeat by design, so this sweep
  never judges it at any age — unchanged.
- **Proof-of-death sweep** (`concurrency.sweep`, new): "this workflow is gone
  (Temporal says not_found)". That is a fact about the workflow, not about the
  hold expiring, so it releases a TERMINATED holder parked as human-hold exactly
  like a dead running one. A live human-hold keeps its slot, and so does
  anything the probe cannot judge (fail-closed, unchanged).

### The bounded, named probe (KI-378 ②)

`concurrency.probe_holder_liveness` bounds every probe at `PROBE_TIMEOUT_S` and
names every failure on the receipt (`probe_errors`); only `not_found` is proof
of death. The manual reconcile entry's own probe (server/tools/ticket.py) is
still unbounded — named debt, a follow-up ticket should route it through this
engine probe.
