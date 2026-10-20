---
code: ticket-pause
retired: false
summary: Pause a ticket between stages, honestly.
started: 2026-09-08
---

# ticket-pause

## What it does

Stop a ticket at a stage boundary, name who paused it and why, and let it resume where it stopped.

## The problem it solves

A ticket could not be stopped without killing the work in flight, and a paused ticket was indistinguishable from a stuck one.

## Design and rulings

Host ruling 260908 (pause between stages; the receipt names the holder).
