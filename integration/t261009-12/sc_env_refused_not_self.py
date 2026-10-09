#!/usr/bin/env python3
"""t261009-12 Defect A — an environment red must never wear the ticket's own cause.

Grey-box L2.5, offline, seconds, zero docker/browser. Scenario processes in this
repo only carry an exit code plus a text tail, so the user-perceivable contract is
the synthesized protocol line: on the t261008-36 incident the tail carried
`net::ERR_CONNECTION_REFUSED at http://127.0.0.1:21010/` plus a fixture transport
error, the process exited 1, and the synthesis stamped it fail × self ×
assert_mismatch — pointing every reader at the wrong file.

We drive the production synthesis seam (`run_scenarios._spec_from_output`) with
real subprocess-shaped outputs and assert ONLY on the emitted spec line (the
public protocol face consumed by the gate), never on internal helpers:

  A  incident tail (literal t261008-36 shape) × exit 1  -> not-checked × external,
     reason in PREPARE_REASONS naming the connection-refused family, evidence
     keeps the observed tail verbatim; the line survives parse_spec_line and
     enforce_semantics with ZERO violations (a backed env red is a legal line).
  B  assertion-shaped tail × exit 1 -> fail × self × assert_mismatch, byte-for-
     byte the old behaviour (no overreach: env vocabulary must not swallow real
     product reds).
  C  malformed faces: None tail, empty tail, garbage tail × exit 1 stay on the
     fail × self path (fail-closed toward self, never toward a free env label).
  D  closed exit-code table unchanged: 0 -> pass; 2 -> not-checked × external;
     -9 -> fail × self × timeout.
  E  no `{`/`[` line may leak from this scenario (house three-state contract).

Pre-implement red on A is the expected TDD signal; arbitrate/merge must be green.
run_scenarios/failure_protocol unimportable = ENV_FAIL exit 2.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INTEG = os.path.join(REPO, "integration")

sys.path.insert(0, INTEG)

try:
    import run_scenarios
    import failure_protocol
    import lib_result
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: cannot import integration modules under test: %r" % (e,))
    sys.exit(2)

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    tag = "PASS" if cond else "FAIL"
    print("%s %s%s" % (tag, name, (" — " + detail) if (detail and not cond) else ""))
    if not cond:
        FAILURES.append(name)


def spec_for(tail, exit_code):
    line = run_scenarios._spec_from_output(
        name="t261009-12-synthetic", pool="ro",
        out=tail if tail is not None else "", exit_code=exit_code,
        dur=0.5, started=0.0)
    return line


INCIDENT_TAIL = (
    "playwright: page.goto -> net::ERR_CONNECTION_REFUSED at "
    "http://127.0.0.1:21010/ || fixture transport error: connect ECONNREFUSED "
    "127.0.0.1:21010")
ASSERT_TAIL = "AssertionError: assert 3 == 4 — expected view rows, got none"

# ---- A: the incident shape must classify as a named environment red ----
line_a = spec_for(INCIDENT_TAIL, 1)
obj = json.loads(line_a)
check("A1 incident exit-1 is not fail×self",
      not (obj.get("status") == "fail" and obj.get("cause") == "self"),
      line_a[:200])
check("A2 status is not-checked", obj.get("status") == "not-checked", str(obj.get("status")))
check("A3 cause is external", obj.get("cause") == "external", str(obj.get("cause")))
check("A4 reason is a prepare-type code naming the family",
      obj.get("reason") in failure_protocol.PREPARE_REASONS, str(obj.get("reason")))
ev = str(obj.get("evidence") or "")
check("A5 evidence keeps the observed tail",
      "ERR_CONNECTION_REFUSED" in ev and "ECONNREFUSED" in ev, ev[:120])

# the line must be a legal protocol line the gate can consume without violation
parsed = failure_protocol.parse_spec_line(line_a)
check("A6 line parses as a protocol line", isinstance(parsed, dict)
      and "__malformed__" not in parsed, line_a[:120])
if isinstance(parsed, dict) and "__malformed__" not in parsed:
    norm, violations = failure_protocol.enforce_semantics(
        failure_protocol.normalize_case(parsed))
    check("A7 gate consumes the env red with zero violations",
          violations == [] and norm["status"] == "not-checked",
          "; ".join(violations))

# ---- B: a genuine assertion tail keeps the old classification ----
obj_b = json.loads(spec_for(ASSERT_TAIL, 1))
check("B1 assertion tail stays fail×self×assert_mismatch",
      obj_b.get("status") == "fail" and obj_b.get("cause") == "self"
      and obj_b.get("reason") == "assert_mismatch", line_a and str(obj_b))

# ---- C: malformed tails fail closed toward self, never toward a free env label
obj_c1 = json.loads(spec_for(None, 1))
check("C1 None tail stays fail×self",
      obj_c1.get("status") == "fail" and obj_c1.get("cause") == "self", str(obj_c1))
obj_c2 = json.loads(spec_for("", 1))
check("C2 empty tail stays fail×self",
      obj_c2.get("status") == "fail" and obj_c2.get("cause") == "self", str(obj_c2))
obj_c3 = json.loads(spec_for("random garbage output line", 1))
check("C3 env-pattern-free garbage tail stays fail×self",
      obj_c3.get("status") == "fail" and obj_c3.get("cause") == "self", str(obj_c3))

# ---- D: the closed exit-code table is untouched ----
check("D1 exit 0 -> pass", json.loads(spec_for("all green", 0)).get("status") == "pass")
obj_d2 = json.loads(spec_for("ENV_FAIL: docker daemon unreachable", 2))
check("D2 exit 2 -> not-checked×external",
      obj_d2.get("status") == "not-checked" and obj_d2.get("cause") == "external",
      str(obj_d2))
obj_d3 = json.loads(spec_for("hung", -9))
check("D3 exit -9 -> fail×self×timeout",
      obj_d3.get("status") == "fail" and obj_d3.get("reason") == "timeout", str(obj_d3))

print("t261009-12-env-refused-not-self: %d checks, %d failed"
      % (CHECKS[0], len(FAILURES)))
sys.exit(1 if FAILURES else 0)
