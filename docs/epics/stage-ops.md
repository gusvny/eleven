---
code: stage-ops
retired: false
summary: Stage leases and test benches: one owner per bench, no orphans left behind.
started: 2026-09-20
---

# stage-ops

## What it does

A lease per test bench with an owner, a heartbeat and a sweep, so a dead holder is reclaimed and a live one is never stolen.

## The problem it solves

Parallel runs collided on shared benches, and killed runs left containers and lease files behind.

## Design and rulings

`docs/design/develop-buffer-v1.md` (bench and stage rules).
