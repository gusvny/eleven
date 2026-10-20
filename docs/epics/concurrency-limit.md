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
