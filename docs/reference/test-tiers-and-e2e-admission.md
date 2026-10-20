---
title: "Test Tiers and the End-to-End Admission Rule"
category: reference
tags:
  - testing
  - end-to-end
  - cost
  - policy
  - tiers
status: active
updated: 2026-10-04
---

# Test Tiers and the End-to-End Admission Rule

> Source: host order 261004. The host asked for one page that says what must be an
> end-to-end case and what must not, so that the suite does not grow for no reason.
> The host also asked the inspection to check this page's rules.
> The Chinese draft is `notes/discussions/261004-test-tiers-and-e2e-admission-draft.md`.

## Why this page exists

One field was dropped while the panel saved a declaration. Nothing failed loudly. The
save answered success.

A static parity check and a contract case of about 0.07 seconds can catch that shape. An
end-to-end case cannot add anything: the fault sat between two adjacent code layers, not
in the assembled system.

The suite is expensive. Of 494 registered scenarios, 95 (19 percent) are expensive: 60
run in the `engine` pool, 24 are `exclusive`, and 11 need a browser. One full suite round
takes 8 to 12 minutes.

So this page states the tiers, the admission rule, the budget, and the checks.

## The four tiers

| Tier | Who delivers | Shape | Unit cost |
|---|---|---|---|
| L0 static | any role | lint, parity checks, source locks, anchor manifest | milliseconds (whole repo about 15 seconds) |
| L1 unit | developer, with the ticket | pure functions and module batteries (pytest, node) | milliseconds |
| L2 component contract | integration role | gray-box assertions on one component's contract: offline, no browser, no test stage | milliseconds to seconds |
| L3 system case (end-to-end) | integration role | one journey or one injected fault on the assembled system | 0.5 to 12 minutes per case; 8 to 12 minutes for the suite |

## When an end-to-end case is allowed

All six items must hold.

1. **A cross-component seam.** No single component's contract can express the property.
   Example: "the host answers a request and the executor wakes".
2. **Or a fault that only the assembled system can reach.** Examples: the test stage fails
   to assemble, a torn mount, a session restored from a broken record, a lock or port
   fight.
3. **Or the user journey itself** — the steps a person performs, in order.
4. **The cheaper tiers cannot do it.** A property that a static check or a millisecond
   contract case can catch must not become an end-to-end case.
5. **It is worth paying on every merge.** It guards a real regression class, not a single
   event.
6. **It is named.** The intent states why L1 and L2 cannot carry it, which pool (cost
   tier) it runs in, and its anchor (the L16 manifest already requires the anchor).

## What must never be an end-to-end case

1. **Field, validation, parsing, or round-trip properties.** They belong to L1 or L2. The
   dropped field named above is this class.
2. **UI rendering, order, copy, or formatting.** They belong to an L2 contract that does
   not open a browser. Use a browser only when the property itself is browser behavior:
   scroll position, real layout, a real click.
3. **Anything a static check can express**: key sets, path shapes, terminology, the
   presence of an anchor.
4. **A repeat of a lower tier's intent.** The intent-level duplication rule already
   forbids this.
5. **A re-run of what a lower tier already asserts**, done to make coverage look better.
6. **A one-off bug pinned by an expensive case.** Pin it in the cheap tier instead.

## Budget

1. **At most one new end-to-end case per ticket.** A second one must say why it cannot
   merge into the first, or why it cannot move to a cheaper tier.
2. **Prefer parameterizing an existing case** over registering a new one. This also avoids
   one more conflict at the shared registry.
3. **An expensive pool needs a net-add reason.** The expensive pools are `engine`,
   `browser`, and `exclusive`. Without a reason, move the case to a cheaper pool.
4. **Watch the trend.** When one suite round passes a threshold (10 minutes for now), or
   when the number of expensive cases grows, the inspection report must say so. It must
   not stay silent.

## Enforcement

Three places carry these rules. All three are needed.

1. **Static, on every merge.** The lint battery requires a tier-justification marker and a
   cost tier in the intent of every scenario that uses an expensive pool. A missing marker
   is red and names the scenario.
2. **The review checklist.** `docs/reference/code-review-checklist.md` carries one row: a
   new expensive case states its tier reason and its cost tier.
3. **The inspection.** Each period reports three things:
   - A. demotion candidates: new or changed cases that are offline, deterministic, and
     cross no seam, so a cheaper tier can carry them;
   - B. the trend: one suite round's wall time and the number of expensive cases;
   - C. repeats: new cases whose intent a lower tier already covers.

## Existing cases

The 95 expensive cases stay as they are for now. The inspection reports demotion
candidates first. A real cleanup is its own ticket, never a side task.

## Related documents

- [Writing standard](writing-standard.md) - the language rules this page follows.
- [Code review checklist](code-review-checklist.md) - the review rows, including the
  tier row this page requires.
- [Design document writing guide](../design/design-doc-writing-guide.md) - the four-section
  shape for design pages.
- [Testing guide](../testing-guide.md) - the isolated test environment and its red lines.
