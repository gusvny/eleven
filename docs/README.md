---
title: "docs index"
category: reference
tags:
  - index
  - knowledge-base
status: active
updated: 2026-09-28
---

# docs index

> **260904 migration note**: this library was migrated from the suyou repository into sandbar
> (host order). What moved is the **engine / plugin / infrastructure domain** documentation — the
> admission rule is in the graduation policy of `notes/README.md` (anything a new agent needs to
> read in order to change sandbar code belongs in this library).
> **Product / content / project domain** documents (HLD, platform architecture, library, game
> incentives, construction, mastery model, reading annotations, agent persona, ancient-text
> pipeline, reference research) stay in the frozen suyou repository as historical reference
> (read-only, never written back).
> The machine index has been regenerated (`docs/index.json`, 18 documents as of 260928);
> **since 260928 the whole library is written in English** (host order) except `terminology.md`.
>
> History: 2026-08-21 the docs library was restructured as a knowledge base (four categories +
> frontmatter + index.json + consumption by the suyou-knowledge plugin); this page is the
> human-readable catalogue, the machine-readable one is `docs/index.json`, and the directory
> structure and migration mapping are in `design/knowledge-base-design.md` (§2 / §6).

## design (design — what the engine/plugins look like, and why)

| File | Content |
|---|---|
| `design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md` | **Engine mechanism master document**: the DSH+Temporal multi-agent ticket engine (first-read reference for engine/plugin domain tickets) |
| `design/ticket-workflow-console-design.md` | Ticket workflow console design (multi-role collaboration infrastructure) |
| `design/sidebar-session-entry-and-hero-design.md` | workbench right-column session entry and hero customization (appendix carries the 【valid】/【disproven】 anchor conclusions) |
| `design/metrics-api-contract-v1.md` | workbench metrics API contract |
| `design/metrics-panel-ui-plan.md` | metrics panel UI plan |
| `design/knowledge-base-design.md` | Knowledge base design (final): four categories, markdown rules, UI, migration mapping |
| `design/dsh-seam-requirements-v1.md` | dsh plugin seam requirements (plugin family contract) |
| `design/chore-lane-ticket-template-design.md` | chore-lane chore ticket template (draft, awaiting host sign-off) |
| `design/failure-classification-protocol-v1.md` | Failure classification protocol v1 and mechanical attribution: one-line JSON canonical line + three-state tightening + gate main-baseline difference decision table (t260910-13) + result ledger and baseline-tree dependency guidance (t260922-12, re-ruled into the registry on 260922) |
| `design/design-doc-writing-guide.md` | Design document writing standard |
| `design/sandbar-project-onboarding-contract-v1.md` | sandbar project onboarding contract v1 (key table / handover faces / append-style change log) |
| `design/project-external-workflow-template-loader-v1.md` | Project external workflow template loader v1 (t260924-04: register-then-load / per-template isolated rejection / evolution discipline / determinism rules) |
| `design/devlane-lite-v1.md` | Lightweight dev lane: effort proportional to risk (three profiles, round economy, proportional gate, scoped execution environments) — **draft, awaiting host decision** |

## ops (operations — build / deploy / monitor)

| File | Content |
|---|---|
| `ops/admin-dsh-application-plan.md` | admin × DeepSeek Harness (dsh) application plan |
| `ops/project-lifecycle-runbook.md` | Project lifecycle operations runbook |
| `ops/engine-worker-and-lane-operations.md` | Engine worker and lane operations: central vs lane worker, the two conditions for an engine fix to reach an in-flight ticket, the three pre-push checks, restart discipline, what a green lane round does and does not cover (pool scope), and `server/tools/engine_ops.py` |

## Root level (cross-cutting standards)

| File | Content |
|---|---|
| `terminology.md` | Project terminology table (maintained by the integration role, additions/removals go through human review; migrated whole from suyou, with a few project-domain entries still to be cleaned up). **Chinese by design** — it is the machine-read source of truth for the banned-jargon lint gate |
| `writing-standard.md` | Project writing standard (t261004-04): the 80% ASD-STE100 checklist for English artifacts and the matching controlled-Chinese checklist, promoted project-wide from the executor preset (source: 261003 executor panel redesign §4). Scope, language map, self-check list, before/after samples, enforcement — adds no machine gate; L7 and the terminology table stay the mechanical faces. Framing in English; the Chinese checklist is quoted in Chinese by design (second deliberate language exception after `terminology.md`) |
| `reference/test-tiers-and-e2e-admission.md` | Test tiers and the end-to-end admission rule (host order 261004): the four tiers, the six conditions a new end-to-end case must meet, the six shapes that must never be end-to-end, the budget (at most one per ticket, expensive pools need a reason, trend watch), and the three enforcement places (lint marker, review row, inspection items). Written because a dropped field was caught by neither tier and the suite is expensive: 95 of 494 cases are expensive and one round takes 8 to 12 minutes |
| `reference/code-review-checklist.md` | Code review checklist (t261004-15): one page of review rows shared by the human reviewer and the review agents — intent/design fit, code judgement, tests judgement, report quality. Every row quotes its rule verbatim and cites file plus line; rules with a source page stay pointers. Adds no machine gate; the host order wins |
| `reference/ledger-record-models-v1.md` | Ledger record models v1 (t261009-26): what each ledger stores and how — the naming table that keeps *line* apart from *branch* and *main*, id minting, the conventions every record obeys, then the records themselves: the line declaration (the one record that is a file a person writes, with its named errors and what a line is not), the landing, the certification, the run, the freeze episode, the promotion, the withdrawal rule, the ticket outcome, the relation and fault-knowledge families, and the inspection and fleet records. Section A's records are labelled built or proposed from the modules that hold them; the open contradictions found between this document and the code are named at the end rather than silently settled |
| `testing-guide.md` | Test environment isolation guide (3099/7233 red lines, Docker isolated test environment) |

## Maintenance conventions

- Every document carries YAML frontmatter: `title` (the first `#` heading) / `category` (design|content|ops|reference) / `tags` / `status` (active|draft|deprecated) / `updated` (date of the last substantive change).
- Adding a document: put it in the matching category directory + add frontmatter, then run `python3 docs/scripts/build_index.py` to refresh `docs/index.json`.
- Related documents **link to each other** (relative paths; three relations: depends-on/depended-on-by, supersedes/superseded-by, practical reference — see `design/knowledge-base-design.md` §3.2).
- The repository-root `CLAUDE.md` is the master handover entry point and this directory is its detailed knowledge base; process discussions and epic proposals live in `notes/` (division of labour and graduation policy in `notes/README.md`).
