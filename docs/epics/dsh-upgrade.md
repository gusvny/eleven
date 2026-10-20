---
code: dsh-upgrade
retired: false
summary: Upgrade the dsh runtime through a process, never a drop-in swap.
started: 2026-09-16
---

# dsh-upgrade

## What it does

A staged upgrade of the runtime every ticket's agent runs on, with a rehearsal and a rollback.

## The problem it solves

Every ticket's agent depends on dsh; an upgrade that disturbs production or cannot be reverted is unacceptable.

## Design and rulings

Host ruling 260916 ('an upgrade needs a process; it must not disturb production and must be reversible').
