#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_waiting_harness — t261004-08 scenarios' shared driver (grey-box L2/L3).

Reuse of the t260928-28 seam (Harness, one JSON command per line over
stdin/stdout, drives the real Watchdog with injected clock / in-memory
ledgers / stub faces; zero docker, zero console 3099, zero engine 7233).
This ticket adds two seam commands to that contract. These are TEST SEAMS,
not product behavior — the only thing the developer must land in
`server/plugins/watchdog/harness.mjs`:

  - requests_seed {rows:[RequestRow...]} | {unreadable:true, reason}
      Seed (replace) the executor-panel REQUEST LEDGER at the harness's
      isolated panel-dir seam with real RequestRow shapes
      (executor-panel/src/host/requests.ts: id/kind/question/detail/
      raised_by/status/at). `unreadable` = the ledger read throws, for
      fail-loud injection. The panel ledger IS the real pendingProvider
      source (t260929-08); there is no separate in-memory pending stub for
      this ticket's face.
  - requests_rows {}
      Reply with the rows as the panel's readRequests normalizes them
      (answered rows joined). Scenarios assert on this, never on file bytes.
  - session_stat_set {running:bool, updatedAtMs:number} | {missing:true}
      Stub the session snapshot face (list-derived): running + updatedAt
      for the declared executor session, or `missing` = the host list
      returned nothing (runningOf() === null injection, review C3).
  - session_text_set {text:string} | {malformed:true} | {absent:true}
      Stub the recent-round-text face (follow/page adapter output): the
      executor session's most recent assistant round text, or `malformed`
      = the transcript read produces garbage (fail-loud injection), or
      `absent` = no text source.

Config keys this ticket adds (flow through fixture_config overrides):
  waiting_minutes (self_lock escalation threshold)
  prose_backstop {enabled, idle_minutes}

Status faces under contract (additive; existing keys never change meaning):
  waiting_on_host {state:'clear'|'waiting'|'unknown', asks, sinceMs, reason}
  self_lock (gains pre-threshold state 'waiting')
  prose_backstop {state:'off'|'idle'|'filed'|'covered'|'unknown', ...}
New alert rules: prose_ask_filed, prose_backstop_unknown.

Three-state contract: node absent = ENV_FAIL exit 2; seam command or
implementation not landed = FAIL exit 1 with the gap named (TDD red is the
expected signal now; must be green at arbitrate/merge).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "t260928-28"))
from lib_watchdog_harness import Harness as _BaseHarness  # noqa: E402,F401
from lib_watchdog_harness import ledger_row, ok  # noqa: E402,F401

EXEC_SESSION = "executor-p1"


class WaitingHarness(_BaseHarness):
    """t261004-08 fixture: panel-ledger pending source + snapshot/text stubs."""

    def fixture_config(self, project, overrides=None):
        cfg = super().fixture_config(project)
        cfg["waiting_minutes"] = 5
        cfg["prose_backstop"] = {"enabled": True, "idle_minutes": 10}
        if overrides:
            for k, v in overrides.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        return cfg

    # ---- fixture helpers ----
    def seed_requests(self, rows, project="p1"):
        return self.cmd("requests_seed", project=project, rows=rows)

    def seed_requests_unreadable(self, project="p1", reason="panel ledger io down"):
        return self.cmd("requests_seed", project=project, unreadable=True, reason=reason)

    def request_rows(self, project="p1"):
        return self.cmd("requests_rows", project=project)

    def answer_row(self, req_id, at_ms=0):
        """Panel answer-row shape (t260929-03 R2: answering APPENDS an answer row;
        a request row never carries answered state itself)."""
        return {"type": "answer", "answer_for": req_id, "at": at_ms,
                "answer": "yes", "by": "host"}

    def set_session(self, running=False, updated_at_ms=None):
        return self.cmd("session_stat_set", running=running,
                        updatedAtMs=updated_at_ms, missing=updated_at_ms is None)

    def session_missing(self):
        return self.cmd("session_stat_set", missing=True)

    def set_round_text(self, text):
        return self.cmd("session_text_set", text=text)

    def round_text_malformed(self):
        return self.cmd("session_text_set", malformed=True)

    def round_text_absent(self):
        return self.cmd("session_text_set", absent=True)


def request_row(req_id, raised_by, status="waiting", question="may I restart the worker?",
                kind="question", at_ms=None):
    """Real panel RequestRow shape (executor-panel/src/host/requests.ts contract)."""
    return {
        "type": "request", "id": req_id, "kind": kind, "question": question,
        "detail": "", "default_action": "", "expires_at": None,
        "raised_by": raised_by, "status": status,
        "at": at_ms if at_ms is not None else 0,
    }
