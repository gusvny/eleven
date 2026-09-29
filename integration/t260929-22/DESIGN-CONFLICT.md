# DESIGN CONFLICT — t260929-22 GAP A: the entry vs the 180px rail (host decision required)

Written by developer, implement gen4, per the gen3 arbitration's explicit
instruction ("escalate to the host rather than bounce a fourth guess"). No
fourth geometry guess is shipped in this round; the tree stays at gen3
(developer's own scenario green, the two foreign scenarios red as attributed).

## The arithmetic (why this is not an implementation-skill problem)

Group-head row inside a 180px rail: inner width 164px (8+8 padding).
Fixed prefix: caret 10 + gaps + color dot 8 ≈ 28–36px. Frozen icon cluster:
5 × 26px hit area + gaps = 138px. 28 + 138 = 166 > 164 — **five 26px icons plus
even a caret leave ~0px for the project name**. The 260927 design ("the project
name row IS the executor entry", name readable, one row per project) and the
260823 ruling ("five view icons, permanently visible, on every project row")
cannot both hold inside the 180px rail. Three rework generations each proved
one leg of this by single-variable A/B at the gate:

| gen | change | own scenario | foreign A/B result |
|---|---|---|---|
| gen1 | entry zone + icons 26→20px | — | t260904-17 FAIL (icons are a frozen contract) |
| gen2 | icons restored 26×26, rail 180→320px | — | t260904-17 + t260915-09 FAIL (rail width is a frozen geometry) |
| gen3 | rail/icons restored; icon strip hover-revealed below the row (absolute) | PASS | t260904-17 + t260915-09 FAIL (constraint (c): no absolute layer over sibling hit-testing) |

A fourth shape exists on paper only if one more thing gives. The candidates,
with their price:

1. **260927 wins (name = entry)** — then clicking a project name navigates the
   center column to the executor panel. t260904-17's fixture flow clicks the
   project name expecting to stay on the board; that scenario needs a
   scenario-side update (its click assumption is pre-entry-era), owned by
   integration with the host's sign-off. Icons: still cannot stay permanently
   visible in 180px → the 260823 visibility ruling must be relaxed (hover
   reveal, or icons move to a group-level affordance).
2. **260823 wins (five icons always visible on the row)** — then there is no
   room for a name-width entry; the executor entry needs a different host-approved
   shape (e.g. a dedicated per-row executor glyph = a deviation from the
   260927 "no separate entry affordance" wording, re-ruled by the host).
3. **The rail widens** — needs a dsh-shell-side layout decision (the shell's
   resize-handle geometry broke at 320px), outside this ticket's write set.

## What is NOT in conflict (already green, undisputed since gen1)

- GAP B: grants upstream producer (origin-derived same-origin base) — scenario
  `t260929-22-grants-upstream-400-text` 8/8, L1 10/10.
- GAP C: named-check 400 text (`project-key.ts` single source, four api.ts
  sites + requests/settings family) — scenario C1–C5, L1 12/12.
- The Executor/Chat switcher and the ExecutorView center-column face (E1–E5 of
  `t260929-22-executor-entry-console` PASS on the gen3 tree).

## Ask

Host picks 1, 2 or 3 (or rules a new shape). Developer implements the chosen
leg in one rework round; the two foreign scenarios get re-attributed
per the host's ruling instead of per geometry guess.
