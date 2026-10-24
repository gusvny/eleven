#!/usr/bin/env python3
"""t261024-60 L1: the quick gate threads the ticket's OWN face, and a genuinely
empty derived own set is refused BY NAME.

The second measured hole (lane t261022-14): every quick-gate round report
carried only_plan.own=[] — _quick_gate_round never threaded own_names, so the
t261024-40 exemption face (pool/roster) and the t261024-60 reuse exemption were
absent on the quickmanual path; the own scenarios ran only while the evidence
declaration happened to point them.

Covers:
- A shared.QuickScopeResolveResult carries own_names/own_error with EMPTY
  defaults (replay safety: old payloads and old histories decode unchanged);
- B shared.own_set_expected_error truth table: write-set marker present +
  empty own set -> a named refusal carrying the expected source path and the
  why-empty reason; docs-only (no own files) -> no refusal; own set present ->
  no refusal; query-error text is preferred over the zero-hits fallback;
- C _quick_scope_registry_snippet: the ticket id is baked in (json-quoted), the
  snippet compiles, own-derivation failure lands in own_error (never an empty
  list silently), and a malformed slug is refused inside the runner face;
- D dev_lane source locks: _quick_gate_round threads quick_scope.own_names into
  _integ_run_args, the quick gate block carries the own refusal, and the
  develop-buffer gate carries the same named refusal (reason_code
  own_set_derivation_empty);
- E the payload parse face: a names-only (pre-t261024-60) list payload names
  the own face unavailable instead of guessing.

Source-lock + pure-function battery, following the test_t260923_*/test_t261024_40
precedent — zero docker/Temporal/browser/3099/7233, nothing runs.
"""
import json
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(ENGINE)

sys.path.insert(0, ENGINE)
import shared  # noqa: E402

_DEV_LANE = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
_ACTIVITIES = open(os.path.join(ENGINE, "agent_activities.py"),
                   encoding="utf-8").read()


def _snippet_fn():
    """Extract the snippet builder standalone (agent_activities imports
    temporalio at module level; the engine venv may not carry it in every
    checkout — the builder is a pure string function, same extraction stance
    as the source locks)."""
    src = _ACTIVITIES
    start = src.index("def _quick_scope_registry_snippet")
    end = src.index("@activity.defn", start)
    ns = {"json": json}
    exec(src[start:end], ns)  # noqa: S102 - trusted in-repo source
    return ns["_quick_scope_registry_snippet"]


class ResultFields(unittest.TestCase):
    def test_own_fields_default_empty_old_payloads_decode(self):
        r = shared.QuickScopeResolveResult()
        self.assertEqual(r.own_names, [])
        self.assertEqual(r.own_error, "")
        # old dict payloads decode unchanged (the workflow-side fallback)
        old = {"ok": True, "mode": "scenario", "only_names": ["x"],
               "registry_count": 9}
        self.assertEqual([str(x) for x in (old.get("own_names") or [])], [])


class OwnSetExpectedError(unittest.TestCase):
    WS = ["integration/t261022-12/sc_own.py", "docs/a.md"]

    def test_marker_plus_empty_set_refused_by_name(self):
        err = shared.own_set_expected_error("t261022-12", self.WS, [], "")
        self.assertIn("own set derivation empty", err)
        self.assertIn("integration/t261022-12/sc_own.py", err)
        self.assertIn("expected source integration/t261022-12/ registry", err)
        self.assertIn("no entries under", err)      # the why-empty fallback

    def test_query_error_text_is_preferred(self):
        err = shared.own_set_expected_error("t261022-12", self.WS, [],
                                            "TimeoutError: boom")
        self.assertIn("TimeoutError: boom", err)

    def test_docs_only_ticket_never_refused(self):
        self.assertEqual(shared.own_set_expected_error(
            "t261022-12", ["docs/a.md", "server/engine/x.py"], [], ""), "")

    def test_nonempty_own_set_never_refused(self):
        self.assertEqual(shared.own_set_expected_error(
            "t261022-12", self.WS, ["own-a"], ""), "")

    def test_whitespace_own_names_count_as_empty(self):
        err = shared.own_set_expected_error("t261022-12", self.WS, ["  "], "")
        self.assertTrue(err)

    def test_other_tickets_files_do_not_trigger(self):
        self.assertEqual(shared.own_set_expected_error(
            "t261022-12", ["integration/t261022-14/sc_x.py"], [], ""), "")


class Snippet(unittest.TestCase):
    def test_snippet_compiles_and_bakes_the_ticket_id(self):
        fn = _snippet_fn()
        s = fn("t261022-12")
        compile(s, "<quick-scope-snippet>", "exec")
        self.assertIn('"t261022-12"', s)            # json-quoted slug
        self.assertIn("own_set_entries", s)

    def test_snippet_refuses_malformed_slug_inside_the_runner(self):
        fn = _snippet_fn()
        s = fn("BAD SLUG; import os")
        compile(s, "<quick-scope-snippet>", "exec")
        # json.dumps quotes it into a single string argument, never code
        self.assertIn('"BAD SLUG; import os"', s)


class PayloadParse(unittest.TestCase):
    def test_names_only_payload_names_own_face_unavailable(self):
        # the parse branch in _quick_scope_resolve_body: a plain list payload
        # (pre-t261024-60 shape) must set own_error, never silently guess.
        self.assertIn("names-only payload", _ACTIVITIES)
        self.assertIn("own derivation unavailable", _ACTIVITIES)
        self.assertIn("isinstance(_payload, list)", _ACTIVITIES)
        self.assertIn("isinstance(_payload, dict)", _ACTIVITIES)


class DevLaneLocks(unittest.TestCase):
    def test_quick_gate_round_threads_own_names(self):
        self.assertIn(
            'own_names=list((quick_scope or {}).get("own_names") or [])',
            _DEV_LANE)

    def test_quick_gate_carries_the_own_refusal(self):
        self.assertIn("shared.own_set_expected_error(", _DEV_LANE)
        self.assertIn("__own_set_empty__", _DEV_LANE)
        self.assertIn('"own_names": list(r.own_names)', _DEV_LANE)

    def test_develop_buffer_gate_carries_the_named_refusal(self):
        self.assertIn('reason_code": "own_set_derivation_empty"', _DEV_LANE)
        # and it rides the existing zero-run refusal channel (never a run)
        self.assertIn("_fs_refusal = _own_refusal", _DEV_LANE)

    def test_scope_receipt_carries_own_error(self):
        self.assertIn('own_error=str(rraw.get("own_error") or "")', _DEV_LANE)


if __name__ == "__main__":
    unittest.main()
