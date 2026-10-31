#!/usr/bin/env python3
"""t261031-23 (KI-442) — the DECLARED evidence path of this ticket.

The evidence declaration on this ticket was carried over verbatim from the
re-created ticket `t261031-21`, so the gate resolves THIS path as the declared
L1 battery. The assertions live once, in
`test_t261031_23_own_pointed_gate.py` (the ticket's own battery); this module
re-exports its test classes, so the declared path is a real, runnable pytest
target and there is exactly one set of assertions — one proof, one truth.

Offline, no Temporal, no docker, no browser, never touches 3099/7233.
Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261031_21_own_pointed_gate.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_t261031_23_own_pointed_gate import (  # noqa: E402,F401
    TestPointedByMode,
    TestPointedUnion,
    TestReceiptAgreement,
    TestRoundSendsUnion,
    TestUnionSourceLocks,
)
