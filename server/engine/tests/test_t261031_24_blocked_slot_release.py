#!/usr/bin/env python3
"""t261031-26 - the DECLARED evidence path of this ticket.

The `_24_` in this file name is the ticket's CREATION-TIME evidence declaration,
carried verbatim from the create payload. That is a slip in the payload, not a
second ticket: `t261031-24` is not a ticket of this project. The integration gate
resolves the DECLARED path, so this module exists to make that path resolve to
the real proof.

The assertions live ONCE, in `test_t261031_26_blocked_slot_release.py` (this
ticket's own L1 battery). This module re-exports that battery's test functions
and its `proj` fixture - one proof, one truth: no second implementation, no
duplicated assertion, nothing weakened.

Offline: no Temporal, no docker, no browser, never touches 3099/7233 or the real
projects root (the ledger is driven through a temporary SANDBAR_PROJECTS_DIR).
Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261031_24_blocked_slot_release.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_t261031_26_blocked_slot_release import (  # noqa: E402,F401
    proj,
    test_a_blocked_stage_releases_its_slot_with_its_own_cause,
    test_the_parked_release_is_named_on_the_ticket_face,
    test_a_park_that_held_nothing_says_so_instead_of_claiming_a_release,
    test_leaving_the_park_reacquires_through_the_fifo_queue,
    test_the_ticket_face_names_the_end_of_the_parked_wait,
    test_every_wake_reason_goes_through_the_ordinary_gate,
    test_unknown_liveness_still_keeps_the_slot,
    test_a_blocked_and_released_ticket_is_not_a_zombie,
    test_the_limit_counts_only_holders_that_can_progress,
    test_a_merge_claim_consumes_no_work_slot,
    test_a_signed_merge_reaches_the_merge_step_without_a_work_slot,
    test_the_merge_wait_face_stays_truthful_across_the_claim,
    test_a_stale_merge_claim_is_reclaimed_and_named,
    test_a_blocked_history_recorded_before_the_marker_still_renews,
    test_a_merge_history_recorded_before_the_claim_marker_still_acquires,
    test_a_pre_cl1_history_schedules_no_concurrency_command,
    test_the_new_markers_are_single_sourced_and_guarded,
    test_the_blocked_wait_cause_is_its_own_word,
)
