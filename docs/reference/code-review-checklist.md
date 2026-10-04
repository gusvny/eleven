---
title: "Code Review Checklist"
category: reference
tags:
  - code-review
  - review-checklist
  - quality
status: active
updated: 2026-10-04
---

# Code Review Checklist

One page of review criteria. The human reviewer and the review agents read and tick
the same page. Host decision 261004: 「要，收拢成一页（推荐）」.

## 1. Scope

Who uses this page:

| User | Use |
|---|---|
| The human reviewer (merge sign-off) | Tick the rows before a verdict |
| The integration agent | Tick the rows at code review, acceptance walkthrough, and arbitration |
| Lane agents (developer and every lane role) | Self-check the diff before handoff |

When to use it: plan review, code review, acceptance walkthrough, arbitration.

## 2. How to use it

Each row is one question. A row passes when its pass condition holds. Each row names
its source: file plus line. Read the source when a row is not clear.

This page collects rules. It does not replace them. A rule that already has a source
page stays a pointer here; this page does not copy it (one source of truth). No new
rule lives on this page. If a review finds a rule that has no source, register it at
its source first, then add the row here.

Quoted rule text stays in the language of its source file (see
`writing-standard.md` section 6: quoted text stays as it is).

## 3. Rows

### 3.1 Intent and design fit

| # | Question | Pass condition | Source |
|---|---|---|---|
| A1 | Does the diff do what the ticket asks? | The change matches the ticket body; no silent scope growth | Ticket face; this page (host decision 261004) |
| A2 | Does a design document govern this area? | The diff agrees with the design page; a conflict goes back as a finding, not a private fix | `docs/design/` (read-only for lanes) |
| A3 | Did the author write a design document where one is due? | The document passes the design-doc self-check list (9 items, quoted there; tick before human review) | `docs/design/design-doc-writing-guide.md` lines 84–94 |
| A4 | Do the words follow the writing standard? | English artifacts follow the 8 STE rules; Chinese artifacts follow the controlled-Chinese 8; one language per artifact | `docs/reference/writing-standard.md` lines 58–108 (the two checklists and the self-check). Pointer; do not copy here |

### 3.2 Code judgement

| # | Question | Pass condition | Source |
|---|---|---|---|
| B1 | Borrowed or copied implementation: does it list the family? | The author lists the fault modes the source handles and declares, per item, carried or not carried, with a reason | `server/roles/integration.yml` line 82: 「借鉴既有实现：方案/代码声称照搬或参考某个已有实现时，必须列出该实现已处理的」 (section 评审的失败模式纪律, lines 80–94) |
| B2 | Does the code consume external input? | Each input is checked in three states: malformed, missing, late | `server/roles/integration.yml` line 85: 「输入必须检查：凡消费外部输入（LLM 产出物、用户输入、文件、网络数据等），」 |
| B3 | Do spawn, listener, timer, and file descriptor reach a clean end? | Every one of them has a recovery path for every end state: normal, error, timeout, cancel | `server/roles/integration.yml` line 87: 「资源生命周期必须检查回收：凡 spawn/监听/定时器/fd，必问每个终态」 |
| B4 | Is every failure loud? | No silent degrade; an unsupported path does not render and names the degrade path | `server/roles/integration.yml` lines 87–88 (resource end states); `docs/testing-guide.md` lines 330–339 (failure must point at one cause) |
| B5 | Is the error text precise? | The error text names the check that failed; no assertion of "no X" unless X is truly absent | `server/roles/integration.yml` line 89: 「报错必须精确：错误分支文案必须说「哪个检查失败」，不许断言「没有 X」除非真没有」 |
| B6 | Reported symptom: was the whole family swept? | A reported symptom is a family lead; the same-pattern files, same-mechanism faces are swept, each hit is classified, and the list lands in the acceptance report. Fixing only the named spot fails acceptance | `server/roles/integration.yml` line 91: 「实报即全族线索：宿主点名的每个症状只是样本，不是工单范围。凡实报类工单，」 (KB ruling 260907, KI-055) |
| B7 | Dead code, duplication, single source of truth? | No dead code in the diff; no intent-level duplication (same intent already covered is not covered again); one fact has one home — a rule with a source page stays a pointer | `docs/terminology.md` line 49 (意图级重复 / intent-level duplication); `docs/testing-guide.md` line 153 (「Since 260823 the single source of truth for tickets is always the Temporal」) |
| B8 | Do terms match the word table? | No banned jargon (see the banned column of the table); word choice follows the table | `docs/terminology.md` lines 87–95 (禁用对照) and line 122 (the L7 mechanical face). Pointer; the table stays the machine-read source |
| B9 | Does the evidence come from the reader's side? | For every write or delivery face (ledger, receipt, file, cross-process delivery) the evidence is read back through the reader's real path; a writer's `ok` or receipt is not evidence, and the ticket names the face and the command that shows it | `server/roles/integration.yml` line 95: 「读者侧验收：凡写入面/投递面（账本、回执、文件、跨进程投递），验收证据必须从」 |
| B10 | Are paths across a boundary absolute, and are ignored areas probed? | Every path in a cross-process or cross-directory write face and receipt is absolute and starts at the instance root; anything `.gitignore` hides has its own probe — `git status` not seeing it is not proof it is absent | `server/roles/integration.yml` line 99: 「边界上不许相对路径：跨进程/跨目录的写面与回执里的路径必须绝对、且以实例根」; machine face: L19 `integration/lint_tests.py` |

### 3.3 Tests judgement

| # | Question | Pass condition | Source |
|---|---|---|---|
| C1 | Do the assertions land on the end state? | At least one end-state assertion per ticket, on whoever finally consumes the deliverable | `docs/testing-guide.md` lines 277–281 (clause 1) |
| C2 | Is the contract layer covered where a promise exists? | Intermediate faces with a clear contract are asserted in parallel | `docs/testing-guide.md` lines 283–288 (clause 2) |
| C3 | Is each unit test deterministic and isolated? | Results do not depend on run directory, env vars, clock, network, or real data | `docs/testing-guide.md` lines 331–335: 「**Isolation determinism**: results must not depend on the run directory, environment variables,」 |
| C4 | Does any test snapshot real data? | No "exactly N items" assertion; properties, not snapshots | `docs/testing-guide.md` line 336: 「- **No snapshots of real data**: see "test data discipline" above — assert properties, not」; rule text at lines 188–193 |
| C5 | Does one red point at one cause? | Failure messages name the object and the expectation | `docs/testing-guide.md` line 338: 「- **One red points to one cause**: failure messages must name the object and the expectation;」 |
| C6 | Does a new external call site carry a shape assertion? | A mock shape assertion validates the call against the counterpart contract; malformed-input cases ride along | `docs/testing-guide.md` lines 205–215 (KI-046 clause) |
| C7 | How is a red judged and classified? | Read the failure classification protocol: canonical line, three states, fail-closed, main-baseline decision table | `docs/design/failure-classification-protocol-v1.md` (whole page; the contract surface starts at line 33). Pointer; do not copy it here |
| C8 | Does every seam have a case through its outermost real entry? | At least one case per seam runs the real entry (the real activity shell, route, or CLI) with the input production supplies, and asserts an environment-tied outcome (an absolute path under the instance root, never a relative one); injecting that input into a unit case alone does not count | `docs/testing-guide.md` line 341 (clause 10: A seam case must go through the outermost real entry) |

### 3.4 Report quality

| # | Question | Pass condition | Source |
|---|---|---|---|
| D1 | Does the report state what was done and how it was verified? | Each claim has a command or path behind it; an unrun check is declared, not implied green | `docs/testing-guide.md` lines 316–320 (clause 7: sign-off checks the assertion face first) |
| D2 | Does the report name its evidence faces? | End-state evidence, contract evidence, and diagnosis are kept apart | `docs/testing-guide.md` lines 277–292 (clauses 1–3) |
| D3 | Does the report stay in one language, per the language map? | Stage reports and lane handoffs are English, 8 STE rules | `docs/reference/writing-standard.md` lines 46–53 (language map) |

## 4. Authority

- The host order wins. Where this page and a host order disagree, the host order wins
  (same precedence rule as `docs/reference/writing-standard.md` line 149).
- This page adds no machine gate. It collects rows for human and agent review.
- Rows a script already checks: B8 (the banned-jargon lint, L7; machine-read source is
  `docs/terminology.md`), C7 (the integration gate reclassifies failures mechanically),
  and the "no path inside the repo" half of B10 (L19 runtime-state location,
  `integration/lint_tests.py`: a project ledger under a `.sandbar/projects/` tree inside the
  repo, outside the repo's own `.sandbar/` evidence area, is an error).
  Partial face: A4 (the words follow the writing standard) is partly scripted by the
  copy-language gate (L15, `integration/lint_copy_language.py`): it reads added lines
  of a diff and covers CJK text in `server/plugins/*/src/**`, `server/engine/**` and
  two integration face libs. Its boundary is narrow — added lines only, those paths
  only, language only — so style, structure, terminology and every untouched legacy
  line stay human. Other partial face: `docs/scripts/build_index.py` flags missing
  frontmatter and staleness across the doc library, but it does not check the 9-item
  design-doc self-check list.
- Rows that stay human only: A3, B1, B2, B3, B4, B5, B6, B7, B9, B10 (the receipt-path half;
  its "no path inside the repo" half is L19), C1–C6, C8, D1–D3, and the
  part of A4 that L15 does not reach (language outside its paths, style, structure,
  terminology). In particular the design-doc self-check list (row A3) is a human
  judgement; no script ticks it. No script replaces reading the diff.
- The eight rules in `server/roles/integration.yml` (section 评审的失败模式纪律)
  keep their home there. This page points at them; it does not delete or change them.

## 5. Self-check (the rows to tick before a verdict)

1. A1: the diff matches the ticket body.
2. A2: no conflict with a design page, or the conflict is filed.
3. B1: every borrowed implementation lists its fault-mode family.
4. B2: every external input is checked in three states (malformed, missing, late).
5. B3: every spawn, listener, timer, and fd has a recovery path per end state.
6. B5: every error text names the check that failed.
7. B6: the family sweep ran; the hit list is in the acceptance report.
8. B9: the evidence for each write face was read back from the reader's side.
9. B10: boundary paths are absolute; ignored areas have their own probe.
10. C1: at least one assertion lands on the end state.
11. C8: every seam has a case through its outermost real entry.
12. B8/A4: terms and language pass the word table and the writing standard.
13. D1: every claim in the report has evidence; unrun checks are declared.

## Related documents

- [Project Writing Standard](writing-standard.md) — the 8 STE rules and the language map
- [Failure Classification Protocol v1](../design/failure-classification-protocol-v1.md) — red judgement and attribution
- [Design Document Writing Guide](../design/design-doc-writing-guide.md) — design-doc self-check list
- `docs/testing-guide.md` — test layer rules (end state, contract, unit face)
- `docs/terminology.md` — word table and banned-jargon lint
- `server/roles/integration.yml` — section 评审的失败模式纪律 (the eight review rules)
