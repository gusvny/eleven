# t261009-79 — Integration test design (REPAIR: lane map renders wrong in three named ways)

Stage: design_integration_tests (integration). English per host order 260925.

## Verdict on scenario set: ZERO new scenarios (with justification)

All three named reds already have owning L3 scenarios, registered in
`integration/run_scenarios.py`:

| Named red | Owning scenario | Face |
|---|---|---|
| P7 tinted=0 / P9 clocks | `t261009-53-lane-map-slim-pipe` | P7 state-by-fill (done 22% tint, current solid); P9 header elapsed/now-at + axis clocks |
| T5 diamond glyph | `t261009-22-lane-map-mock-chrome` | T5 vector diamond glyph (closed multi-segment svg path, anchor semantics) |
| T2b dashed boxes=0 | `t261008-23-lane-map-v5-proportional` | T2 dashed parallel window box spanning both tracks |

Creating a fourth "combined lane-map faces" scenario would be an intent-level
duplicate: each face already has exactly one owner, the intent-split notes in
the registry already partition the lane-map surface, and the ticket's
requirement (4) — "the three faces re-checked together in one run" — is met by
the integration gate run, which executes all three scenarios in one suite pass.
The repair therefore moves the scenarios' PROBES and FIXTURES (developer
implement stage, plan items 1-4), not the scenario inventory.

## Design basis (three-source discipline, exhausted)

1. **Original user_request / acceptance wording**: the ticket names P7, P9,
   T5, T2b "quoted verdict by verdict" in a real browser run — each named face
   maps 1:1 to an existing sub-assertion in the owning scenario above. No
   face in the ticket lacks an owner.
2. **Known-issue list (`notes/debts/known-issues.md`)**, entries this ticket's
   changes touch:
   - KI-051 (guard anchor x implementation drift): the T2b/T5 probe moves are
     anchor-semantic repairs under exactly this KI — the v5 probe anchored the
     RETIRED block renderer's CSS borders; T5's 60-char slice is an
     implementation-anchored truncation. The scenarios must anchor the mock's
     SVG semantics (`stroke-dasharray` rect; closed fold regex over the full
     attribute), not retired DOM shapes or arbitrary slice windows.
   - KI-01M4JJWGWZQPNWSM0QT4X8F94A (env_fail streak let an unverified UI
     landing through): this ticket's acceptance receipt MUST be a real
     browser pass on the fixed harness (t261009-72 in main) — an env_fail
     receipt does NOT close this ticket's named faces.
   - KI-01M4HR0ECTNFS4RWSQ8M0GE17J (write-set shape vs bundle build chain):
     this ticket touches `server/plugins/workbench/src/client/` (coordinate
     rounding) — the implement stage must keep the declared bundle pair's src
     prefix aligned with the write set so rebuilt `lib/client.{js,cjs}` get
     legal identity. Recorded as a handover risk, not a scenario.
   - No NEW failure mode is discovered in this design pass; nothing to report
     to the KI register.
3. **Component contract (user-perceivable behaviour, mock 261004 as spec)**:
   state is expressed by fill (tint vs solid); parallel windows are dashed
   SVG boxes spanning both tracks; the human gate is a closed four-fold
   diamond; the time axis shows start/end clocks and the header elapsed/now-at.
   Assertions stay on SVG primitive geometry / user-visible text with
   tolerance — never class names, never literal coordinates (KI-051 writing
   rule).

## Failure surfaces the design already pins (via existing scenarios, unchanged ownership)

- Malformed input: t261009-22 fixture carries a corrupt non-ISO `at` and a
  corrupt non-string stage entry (T9: no `undefined` leak, zero pageerror);
  the developer UT adds an empty-timeline no-throw case.
- Stale-time boundary: the slim-pipe scenario moves to a live `now` anchor
  (`start: Date.now() - 40*60e3`) — P3d (label overlap) must hold at BOTH
  fixture-time and real-now (developer UT locks both).
- Regression coupling: coordinate rounding changes every numeric attribute in
  the map DOM; the gate rerun re-checks all three scenarios in one pass so a
  fix for one face cannot silently break another (ticket requirement 4).
- Family sweep (review_plan condition 1): `fixtureTimeline`/`lib_fix23`
  consumers are exactly three scenarios — `t261009-53-lane-map-slim-pipe`,
  `t261009-22-lane-map-mock-chrome`,
  `t261009-68-lane-map-mount-receipt` (grep evidence below). All three are in
  the gate run; the done-mark fixture change and live-start change must leave
  t261009-68's mount faces (M1-M4, C) unaffected — that scenario asserts
  mount/crash faces only, but its receipt is the cross-check that the fixture
  change did not break the detail drawer journey.

## How this ticket's faces are verified (the deciding receipt)

- Gate rerun (engine integration stage, on the fixed harness with t261009-72
  in main): all three scenarios pass, and the arbitrate/merge receipt quotes
  P7 and P9, T5, T2b verdict-by-verdict — not just "scenario green".
- Targeted re-run of any single red during investigation stays inside the
  forensic discipline: `python3 integration/run_scenarios.py --only <name>`
  with the gate's own `--exclude-pools engine,exclusive` scope; a full-suite
  re-run only when the whole suite is red.
- No integration entry is executed in developer stages (host order 260921);
  this design stage likewise ran only the static lint.

## Deliberately NOT designed here

- No snapshot pin on rounded coordinate values (rot-by-design; assertions keep
  tolerance and shape semantics).
- No new scenario for "fixture must express narrated state with engine-shaped
  marks" — that is a fixture-construction discipline inside the existing
  scenarios plus a developer UT lock, not a separate user-facing behaviour;
  revisit as an inspection/lint item only if a second fixture drifts the same
  way (KI-pattern candidate, watch item).
