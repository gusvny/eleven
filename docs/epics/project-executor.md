---
code: project-executor
retired: false
summary: One resident executor session per project: it signs, fixes stuck tickets and only calls you when it truly cannot continue.
started: 2026-09-27
---

# project-executor

## What it does

A per-project session that watches the queue, signs what is mechanical, repairs what is stuck and escalates only judgement calls.

## The problem it solves

The host is the bottleneck on every small decision, and a stuck ticket waits for a person who is not watching.

## Design and rulings

`notes/discussions/260927-project-executor-design.md` (pre-move source).
