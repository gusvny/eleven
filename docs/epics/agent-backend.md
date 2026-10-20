---
code: agent-backend
retired: false
summary: Pluggable agent backends: a ticket can run on a different executor than its neighbour, chosen per ticket, two running side by side.
started: 2026-09-13
---

# agent-backend

## What it does

Let a ticket declare which executor runs it (dsh today, another tool tomorrow) and run two of them at the same time.

## The problem it solves

Every ticket today is executed by dsh, so a second executor cannot be tried without replacing the first. The host asked for a choice per ticket, not for a replacement.

## Design and rulings

Host ruling 260913 (no design document yet).
