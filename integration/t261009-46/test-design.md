# t261009-46 — L3 test design (integration)

Registry entries (pool `ro`, `integration/run_scenarios.py`):

1. `t261009-46-optin-landing-journey` — `sc_optin_landing_journey.py`
   Faces: A version-name refusal matrix (unknown / non-str / whitespace /
   wrong-case refused with the value named; absent shape `None`/`""` resolves
   to legacy per the declared absence rule, never migrated); B opt-in landing
   end to end (proven sha lands on the line as one merge commit, main does not
   move, exactly one delivery-ledger landing row read back from the FILE with
   head == the reader-side line head, receipt revisions match); C the PROVEN
   revision lands, not the drifted tip (clean tree pins, line content is the
   proven content, merge parent is the proven sha, checkout left pinned);
   D dirty drifted checkout refuses via the receipt (`ok=False` + named
   pin/proven error), zero ledger rows, line branch never created, lane HEAD
   untouched.
2. `t261009-46-legacy-path-untouched` — `sc_legacy_path_untouched.py`
   Faces: A legacy resolution creates nothing (no develop dir, no delivery
   ledger); B one-way dependency for the wired tree (importing
   `agent_activities` leaves the new surface unimported — its only reference
   is the lazy import inside `land_to_line`; develop_line/develop_certify/
   develop_promote carry no import of dev_lane/workflows_v2); C an old-path
   settle through `_settle_merge_core` (the single implementation, merge
   staged as the join close-out does) advances main by exactly one
   first-parent merge commit and writes nothing into the store outside the
   repo; D `workflows_v2.py` names no new surface.

Failure surfaces covered: malformed/absent opt-in input; drifted vs proven
revision (wrong-tip delivery, the t261009-18 handover hole); unpinnable
checkout; silent default at intake; silent migration of legacy tickets; new
surface reaching back into the running flow; second store write home.

Intent-level non-duplication: the landing act's own guarantees (linear
history, one-per-ticket, conflict rollback, serialization) stay owned by the
t261009-18 entries; certification/round/freeze/outcome faces stay owned by
t261009-30/41. This pair owns only the opt-in wiring journey and the wired
coexistence face.

Known reds NOT owned here (developer implement stage, in flight at design
time): `L15` CJK copy in new dev_lane.py lines; `L16` missing anchor for
`server/engine/tests/test_t261009_46_lane_version_optin.py`; `L2` pytest
collection path error in that test; the t261009-18 `sc_old_flow_inert_face.py`
face B (textual grep on dev_lane.py) needs its planned re-statement —
dev_lane now imports develop_line at module level (declared inert, gated at
the version predicate).
