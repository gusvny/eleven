---
title: "Project Writing Standard (80% ASD-STE100 and controlled Chinese)"
category: reference
tags:
  - writing-standard
  - asd-ste100
  - controlled-chinese
  - style
status: active
updated: 2026-10-04
---

# Project Writing Standard (80% ASD-STE100 and controlled Chinese)

> **Language note**: this document is written in English on purpose. Since 260928 the
> `docs/` library is English-only, with one deliberate exception: `docs/terminology.md`,
> the machine-read source of the banned-jargon lint (L7). This document is the second
> deliberate exception in part: its framing is English, but each checklist below is
> quoted in the language it governs, because the Chinese checklist is itself a
> demonstration of the controlled-Chinese rules it states. Translating it into English
> would destroy the thing it defines.

This standard promotes the writing rules that previously lived only in the executor
preset and in `notes/discussions/261003-executor-panel-redesign.md` (section 4) to the
whole project (host order 261004). It defines how every writing agent in this project
writes English artifacts (80% of ASD-STE100) and Chinese artifacts (a controlled
Chinese with the same structure).

## 1. Scope

Every writing agent follows this standard. This includes:

| Role / artifact producer | Governed artifacts |
|---|---|
| Lane agents (developer, integration, and every other lane role) | Ticket faces, stage reports, lane handoff and report artifacts, chat replies |
| The project executor | Panel strings, alert texts, ledger and settings copy, console UI copy |
| Document authors | New documents in `notes/` (Chinese), in `docs/` (English), and code comments (English) |
| The host and every human reviewer | Reviews text against this standard before sign-off |

The standard governs prose. It does not govern code, data formats, or identifiers.

## 2. Language map

One artifact is written in one language. Never mix two languages inside one artifact.

| Artifact | Language |
|---|---|
| Ticket faces (title, spec, body, deliverables, acceptance, rework reasons, sign-offs, verdicts) | English (host order 260924) |
| Console UI copy (labels, stage names, status and enum tags) | English; data stays in its own language (host order 260925) |
| Code comments | English (ASD-STE100, 80 percent) — host order 261004 retires CLAUDE.md rule 3 (modern Chinese); existing Chinese comments stay as they are until touched |
| Knowledge-base documents in `notes/` | Chinese; new text follows the controlled-Chinese checklist in section 3.2 |
| Documents in the `docs/` library | English, except `docs/terminology.md` (Chinese by design) and this document's quoted Chinese checklist |
| Chat replies to the host | Plain Chinese |

`docs/terminology.md` stays the source of truth for Chinese word choice; this
standard says how to build sentences, not which terms to use.

## 3. The two checklists

The sixteen rules below are quoted verbatim from their source
(`notes/discussions/261003-executor-panel-redesign.md` section 4, host order 261004).
Do not reword them.

### 3.1 English artifacts (ASD-STE100, 80 percent)

1. Short sentences: descriptions of at most about 25 words; one idea per sentence.
2. Active voice and present tense; use the imperative for what the reader must do.
3. One word, one meaning. Fix the terms: ticket / executor / permission / session / stage / gate / merge / alert / watchdog.
4. No jargon, metaphor or abbreviation; no contractions (write do not, will not).
5. Noun clusters of at most three words.
6. Introduce labels and numbers with a colon (Ticket:, Request id:, Default action:).
7. Write states as complete sentences (Self-lock cleared.).
8. Every panel string (Grants, Settings, Ledger, Alerts included) follows this checklist with no exception.

### 3.2 Chinese artifacts (controlled Chinese)

1. 一句一个意思；陈述句不超过约 25 字，超了就写成两句。
2. 主动语态、现在时；要人做的事用命令句。
3. 一个词一个意思：按 `docs/terminology.md` 用词表（中文为主，在册术语可留英文原词）；
   同一个东西全文不许换叫法。
4. 不用行话、隐喻、四字格堆砌、生造缩写。
5. 名词串不超过三段，超了要拆成短句或用标点断开。
6. 数字与标识用冒号引出（票号：t261003-10；已等：12 分钟）。
7. 状态写成完整句（执行器停摆。不是停摆中）。
8. 不用双重否定、不堆被动、不填空词（进行/相关/处理/情况 能删就删）；不写自我辩白的长句。

## 4. Self-check before you submit text

Run this list on every artifact before you deliver it:

1. Split check: does every sentence carry one idea, and stay near 25 words (English)
   or 25 characters (Chinese)? Split the long ones.
2. Voice check: is the sentence active and in the present tense? Do instructions use
   the imperative?
3. Term check: does each thing keep one name? Do fixed terms match
   `docs/terminology.md`?
4. Plainness check: no jargon, no metaphor, no abbreviation, no contraction, no
   invented acronym, no pile of four-character idioms (Chinese).
5. Noun-cluster check: no noun cluster longer than three words. Split or punctuate.
6. Label check: do numbers and identifiers come after a colon?
7. State check: does every state read as a complete sentence?
8. Filler check (Chinese): remove 双重否定, 被动堆叠, and the empty words
   进行/相关/处理/情况 where you can remove them.
9. Language check: does the artifact stay in one language? Does it use the language
   the map in section 2 gives for that artifact (code comments: English; `notes/`
   documents: Chinese)?
10. Exemption check: quoted code, identifiers, tool output, and legal text stay as
    they are; do not "fix" them.

## 5. Samples (before / after)

These pairs come from real artifacts in this repository. Sources are named.

### 5.1 English samples

Source: `notes/discussions/261003-executor-panel-redesign.md` section 4.1.

| Before | After | Broken rule |
|---|---|---|
| Anything to add before I open this ticket? | Do you have more instructions before the executor opens this ticket? | Rule 3: the fixed term `executor` was missing |
| Grant executor permissions? | Which permissions do you give to the executor? | Rule 2: the reader could not tell who acts |
| stall — t261002-10 idle 16m | Ticket t261002-10 did not move for 16 minutes. | Rules 4 and 7: jargon word and a state without a sentence |

### 5.2 Chinese samples

Source: `notes/discussions/261003-executor-panel-redesign.md` section 4.2.

| 改前 | 改后 | 违反条目 |
|---|---|---|
| 该票当前处于因主同步同批文件反复冲突而转人工处置的阻塞状态 | 票卡住了：合并 main 时同一个文件反复冲突，已经交给人工。 | 第 1、5、8 条：长句、名词串、空词 |
| 执行器尚未被唤醒，故未能对阻塞做出响应 | 没人叫它，所以它不知道票卡住了。 | 第 2、8 条：被动堆叠、双重否定式表达 |
| 请在上述选项中择一以完成授权范围的配置 | 选一个授权范围。 | 第 1、8 条：长句、填空词 |

## 6. Enforcement and precedence

This standard has one machine face of its own, and it keeps the older ones:

- The copy-language gate (L15, `integration/lint_copy_language.py`, wired into
  `integration/lint_tests.py`) reads the added lines of a diff and fails a new or
  touched line that carries CJK text inside its declared scope:
  `server/plugins/*/src/**`, `server/engine/**`, and two integration face libs. It
  covers code comments too, because section 2 puts them in the English column. A
  reviewer-visible exemption marker (`copy-lang-allow:<id>`) is the declared way out.
- The banned-jargon lint (L7) keeps its gate role; its machine-read source is
  `docs/terminology.md`.
- `docs/terminology.md` keeps its role as the word-choice table.

A reviewer (human or agent in a review seat) must reject text that breaks these
rules, and must name the broken rule in the rejection. A rejection without a rule
number is not a valid rejection under this standard.

Exempt from the rules: quoted code, identifiers, tool output, and legal text. Copy
them as they are.

Precedence: where this standard and a host order disagree, the host order wins.
Where this standard and a machine gate disagree, the machine gate wins for its own
scope; fix the text so both pass.
