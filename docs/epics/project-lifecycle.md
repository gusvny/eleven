---
code: project-lifecycle
retired: false
summary: Project lifecycle: add, quarantine and remove a project without corrupting the registry.
started: 2026-09-04
---

# project-lifecycle

## What it does

Explicit add / quarantine / remove paths with a dry-run precheck, so one bad project never poisons the loader for the others.

## The problem it solves

A broken project entry used to take the whole registry down, and a removal could leave loaders pointing at a missing directory.

## Design and rulings

`docs/design/project-fact-ledgers-v1.md` (project facts), registry contract in `docs/reference/`.
