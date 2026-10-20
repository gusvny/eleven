---
code: develop-buffer
retired: false
summary: The delivery line: land a ticket on develop-buffer, certify the revision, promote it to main.
started: 2026-10-09
---

# develop-buffer

## What it does

A buffer line between lanes and main: a lane proves only its own ticket, content lands on develop-buffer, the full suite runs per line and period, and a green certification is promoted to main by a human signature.

## The problem it solves

Every ticket ran the full suite (~35 minutes), so the fleet jammed on testing and one red stopped everyone.

## Design and rulings

`docs/design/develop-buffer-v1.md`, `docs/design/project-fact-ledgers-v1.md`, `docs/design/ticket-relations-v1.md`, `docs/reference/ledger-record-models-v1.md`.
