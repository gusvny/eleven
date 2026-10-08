"""t261008-25 KI-223 Step 1: the exhaustive status-to-surface map.

Pins (plan Step 1 + review conditions):
- exhaustiveness: `_STATUS_SURFACE_MAP` keys must equal the full Temporal
  WorkflowExecutionStatus name set — a future terminal class landing outside every
  collection pass turns this red (the KI-223 root cause, made structurally impossible);
- the terminal-archive eligibility set is derived from the map, never a second list;
- CONTINUED_AS_NEW must NOT carry the terminal_archive face (KI-025: not terminal);
- no rogue query literal: every `ExecutionStatus="<NAME>"` literal in client.py must
  name a status present in the map (a face silently widened/narrowed by a raw literal
  turns red), and each filtered face's query literal must exist.

Source-text anchor per review condition 4: the mechanical `# face=<id>` comments keep
the grep-style check simple.
"""
import re
from pathlib import Path

import client

REPO = Path(__file__).resolve().parents[3]
CLIENT_SRC = (REPO / "server" / "engine" / "client.py").read_text(encoding="utf-8")

# The full set of ExecutionStatus names Temporal's WorkflowExecutionStatus can report
# (hardcoded here on purpose: a new name appearing in the engine but missing from the
# map is exactly the failure mode this pin exists to catch).
TEMPORAL_EXECUTION_STATUSES = {
    "COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT",
    "CONTINUED_AS_NEW", "RUNNING",
}

FILTERED_FACES = ("archive_cleanup", "running", "cancel_audit")


def test_map_exhaustive_over_temporal_statuses():
    assert set(client._STATUS_SURFACE_MAP) == TEMPORAL_EXECUTION_STATUSES


def test_every_status_carries_the_board_face():
    for status, faces in client._STATUS_SURFACE_MAP.items():
        assert "board" in faces, status


def test_terminal_archive_eligible_derived_from_map():
    # FAILED + TERMINATED + CANCELED + TIMED_OUT = terminal-but-not-COMPLETED, and the
    # set must be a derivation, not an independent literal list.
    assert client._ARCHIVE_TERMINAL_ELIGIBLE == {"FAILED", "TERMINATED", "CANCELED",
                                                 "TIMED_OUT"}
    assert all("terminal_archive" in client._STATUS_SURFACE_MAP[s]
               for s in client._ARCHIVE_TERMINAL_ELIGIBLE)


def test_continued_as_new_never_reaches_the_terminal_archive_exit():
    # KI-025 pin: the watcher-generation handover is not terminal, so the named exit
    # must refuse it by construction.
    assert "terminal_archive" not in client._STATUS_SURFACE_MAP["CONTINUED_AS_NEW"]
    assert "CONTINUED_AS_NEW" not in client._ARCHIVE_TERMINAL_ELIGIBLE


def test_completed_is_not_terminal_archive_eligible():
    # The exit must not become a side door for completed tickets.
    assert "COMPLETED" not in client._ARCHIVE_TERMINAL_ELIGIBLE


def test_no_rogue_execution_status_literal():
    # Every raw query literal in client.py must name a status the map knows (the
    # query-predicate capitalization is Temporal's "Completed"/"Running"/"Terminated"
    # spelling — matched case-insensitively against the UPPER map keys); a literal
    # for an unmapped status = a collection face the map does not declare = red.
    literals = set(re.findall(r'ExecutionStatus="([A-Za-z_]+)"', CLIENT_SRC))
    unmapped = {lit for lit in literals if lit.upper() not in client._STATUS_SURFACE_MAP}
    assert not unmapped, unmapped


def test_each_filtered_face_has_its_query_literal():
    expected = {"archive_cleanup": "Completed", "running": "Running",
                "cancel_audit": "Terminated"}
    for face, literal in expected.items():
        marker = "# face=%s per _STATUS_SURFACE_MAP" % face
        assert marker in CLIENT_SRC, face
        # the mechanical comment is immediately followed by the face's query literal
        tail = CLIENT_SRC.split(marker, 1)[1][:400]
        assert 'ExecutionStatus="%s"' % literal in tail, face
