#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261027_26_cap_exit_contract.py -- t261027-26 (KI-382), L2 contract.

The acceptance send-back cap is a dead end today: the blocked face names no way
out, and no authorization kind can lift it (AUTH_KINDS = protected_path |
arbitration_verdict, measured on t261026-18 with a green machine gate and
walkthrough reports that named no failed acceptance item). The approved plan
(create_plan rev 1, review_plan verdict=conditional) gives the operator an
explicit cap lift carried by `op=ruling`, published on the blocked face.

This entry owns the OPERATOR ROUND TRIP that no single-component test can
express - the face hands a person a complete, truthful, usable exit, and every
name on that face exists on the receiving side:

  A  THE PUBLISHED EXIT IS HONEST: the prefix of the blocked text is byte
     identical to today's sentence (operator habits, existing assertions and
     the KI-061 startswith contract keep matching); every `op=<name>` the text
     names exists in the human CLI (server/tools/ticket.py) - no invented
     exit; the text states that a ruling alone does not wake the stop and
     names retry_qc; the stated lifetime equals the engine's own constant and
     the lift is stated single use.
  B  THE CITATION IS THE REPORT'S REAL NAME: the token printed on the face is
     exactly the walkthrough report file name the operator can open
     (stage_acceptance_walkthrough_gen<N>.json), and the parser accepts the
     printed form and a bare generation number while refusing another stage's
     file and garbage - a face that prints a token the intake cannot accept is
     the dead end again with extra steps.
  C  THE EXIT IS HUMAN-ONLY AND DOES NOT DRIFT FROM AUTHORIZE: the shared
     identity guard refuses agent role names and the -agent display family with
     a named reason and accepts a human identity; the authorize channel still
     refuses an agent who through the SAME guard (no second source of truth, no
     regression of the t260912-03 contract).
  D  THE STOP STAYS A PERSON'S STOP: the published text classifies as a
     judgement stop, so an executor lift (`lift_stop`) cannot clear it - a
     named human exit must not quietly become a machine exit.
  E  THE LIFT IS READABLE ON THE FACE THE OPERATOR LOOKS AT: `ticket show`
     projects the timeline and the refusal ledger (ticket.py `_v2_query`), so
     the armed/used lift and its refusals are readable without internal state;
     the text says the lift is recorded on the ticket face.

Intent split (no intent-level duplication): the lift grammar's own truth table,
the expiry/single-use live filter, the intake write/refuse matrix and the
engine branch wiring belong to developer L1
(server/engine/tests/test_t261027_26_acceptance_cap_lift.py, T1/T2/T5/T9);
the arbitration sibling's block-text contract belongs to the t260917-09 family;
the stop-tier classifier's marker corpus belongs to t261019-26. THIS entry
uniquely owns the operator round trip across the published face, the CLI op
vocabulary, the report-file name, the shared identity guard and the detail-face
projection.

Grey-box: the REAL published producer (shared.acceptance_cap_blocked_text, the
face the engine blocks with), the REAL report-name derivation
(shared.result_file_for), the REAL classifier (shared.classify_stop_tier), the
REAL identity guard behind both intake channels, and the REAL CLI/detail-face
sources are read; no assertion anchors on a helper's private shape. Offline
seconds, pure stdlib + the engine modules, zero docker/Temporal-server/browser,
never touches 3099/7233.

Pre-implementation tree: red by name (the named TDD signal - the exit producer
does not exist yet); green required at the integration gate / merge.
engine modules unimportable = ENV_FAIL exit 2.
"""
import os
import re
import subprocess
import sys

REPO_RC = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
if REPO_RC.returncode != 0 or not REPO_RC.stdout.strip():
    print("ENV_FAIL t261027-26-acceptance-cap-exit-contract: repo root unresolved")
    sys.exit(2)
REPO = REPO_RC.stdout.strip()
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, ENGINE)

PASS = 0
FAILS = []
ENVS = []


def check(name, cond, why=""):
    global PASS
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def env_fail(name, why):
    ENVS.append(name)
    print("ENV_FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, len(FAILS), len(ENVS)))
    if FAILS:
        print("FAIL t261027-26-acceptance-cap-exit-contract (%d): %s"
              % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    if ENVS:
        print("ENV_FAIL t261027-26-acceptance-cap-exit-contract: %s" % "; ".join(ENVS))
        sys.exit(2)
    print("PASS t261027-26-acceptance-cap-exit-contract")
    sys.exit(0)


try:
    import shared
except Exception as e:  # noqa: BLE001 - engine tree unavailable is an environment fact
    env_fail("engine-modules", "shared.py unimportable: %s: %s" % (type(e).__name__, e))
    summary()

producer = getattr(shared, "acceptance_cap_blocked_text", None)
if not callable(producer):
    check("A0 the exit producer is on the shared face",
          False,
          "shared.acceptance_cap_blocked_text missing - the blocked face has no "
          "named exit to publish (the approved plan's deliverable 2)")
    summary()

# ---------------------------------------------------------------------------
# A - the published exit is honest
# ---------------------------------------------------------------------------
GEN_CITED = 3
token = None
token_builder = getattr(shared, "acceptance_report_token", None)
if callable(token_builder):
    token = token_builder("acceptance_walkthrough", GEN_CITED)
else:
    token = "stage_acceptance_walkthrough_gen%d.json" % GEN_CITED

TEXT = producer(MAX_GEN_ROUNDS := 3, shared.MAX_ACCEPTANCE_ROUNDS, token)

check("A1 the published prefix is byte identical to today's blocked sentence",
      TEXT.startswith("acceptance walkthrough send-back 3 rounds over limit (cap 2)"),
      "text=%r" % TEXT[:120])

OPS_IN_TEXT = sorted(set(re.findall(r"op=([a-z_]+)", TEXT)))
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")
try:
    CLI_SRC = open(TICKET_PY, encoding="utf-8").read()
except OSError as e:
    CLI_SRC = ""
    env_fail("cli-source", "cannot read %s: %s" % (TICKET_PY, e))

KNOWN_OPS = set(re.findall(r"op\s*[=:]\s*'([a-z_]+)'", CLI_SRC)) | set(
    re.findall(r"'([a-z_]+)'", CLI_SRC.split("ops", 1)[1][:2000])) \
    if "ops" in CLI_SRC else set(re.findall(r"op\s*[=:]\s*'([a-z_]+)'", CLI_SRC))

check("A2 the text names the lift, the rework and the pause exits",
      {"ruling", "rework", "pause"}.issubset(set(OPS_IN_TEXT)),
      "ops in text=%r" % (OPS_IN_TEXT,))
check("A3 no invented exit: every op the face names exists in the human CLI",
      bool(OPS_IN_TEXT) and all(("'%s'" % op) in CLI_SRC for op in OPS_IN_TEXT),
      "ops=%r missing from server/tools/ticket.py" % (
          [op for op in OPS_IN_TEXT if ("'%s'" % op) not in CLI_SRC],))

low = TEXT.lower()
check("A4 the text states that the ruling alone does not wake the stop",
      any(m in low for m in ("no wake-up", "no wakeup", "does not wake",
                             "sends no wake")),
      "no wake-up honesty sentence found; text=%r" % TEXT[-400:])
check("A5 the text names retry_qc as the wake action",
      "retry_qc" in TEXT, "retry_qc missing from the face")

TTL = getattr(shared, "ACCEPTANCE_CAP_LIFT_TTL_SEC", None)
check("A6 the stated lifetime equals the engine's own TTL constant",
      isinstance(TTL, int) and TTL > 0 and
      ("%d h" % (TTL // 3600) in TEXT or "%d hours" % (TTL // 3600) in TEXT),
      "TTL=%r text=%r" % (TTL, TEXT[-160:]))
check("A7 the text says a lift is single use",
      "single use" in low, "the face must not promise a permanent bypass")

# ---------------------------------------------------------------------------
# B - the citation is the report file's real name
# ---------------------------------------------------------------------------
check("B1 the token the face prints is a walkthrough report file name",
      bool(re.search(r"stage_acceptance_walkthrough_gen\d+\.json", token or "")),
      "token=%r" % (token,))

try:
    real = os.path.basename(shared.result_file_for(
        "t000000-00", "acceptance_walkthrough", GEN_CITED, None))
except Exception as e:  # noqa: BLE001
    real = ""
    env_fail("result-file", "result_file_for failed: %s: %s" % (type(e).__name__, e))

check("B2 the printed token is the report file the operator can actually open",
      real == token, "printed=%r real=%r" % (token, real))

parser = getattr(shared, "parse_acceptance_report_token", None)
if callable(parser):
    check("B3 the printed token round-trips through the reader",
          parser(token) == GEN_CITED, "parser(%r)=%r" % (token, parser(token)))
    check("B4 a bare generation number is accepted",
          parser(str(GEN_CITED)) == GEN_CITED, "bare gen refused: %r" % (parser(str(GEN_CITED)),))
    check("B5 another stage's report is refused (a stale citation cannot lift)",
          parser("stage_merge_check_gen3.json") in (None, ""),
          "parser accepted a foreign stage file")
    check("B6 garbage never raises and is not a generation",
          parser("not-a-report") in (None, "")
          and parser("") in (None, "")
          and parser("stage_acceptance_walkthrough_gen_x.json") in (None, ""),
          "garbage parsed as a generation")
else:
    check("B3 the citation reader is on the shared face", False,
          "shared.parse_acceptance_report_token missing")

# ---------------------------------------------------------------------------
# C - human-only, one identity guard, authorize not regressed
# ---------------------------------------------------------------------------
guard = getattr(shared, "identity_refusal", None)
roles = sorted(getattr(shared, "AUTHZ_AGENT_ROLE_NAMES", ()) or ())
if callable(guard):
    agent_refusals = [guard(r) for r in roles] + [guard("ops-agent"), guard("  Developer ")]
    check("C1 every agent identity is refused by name",
          all(isinstance(x, str) and x.strip() for x in agent_refusals),
          "agent identities accepted: %r"
          % [r for r, x in zip(roles + ["ops-agent", "  Developer "], agent_refusals)
             if not (isinstance(x, str) and x.strip())])
    human = guard("host")
    check("C2 a human identity passes the guard", isinstance(human, str) and not human.strip(),
          "human identity refused: %r" % (human,))
    check("C3 a missing identity is refused",
          isinstance(guard(""), str) and bool(guard("").strip()),
          "blank who accepted")
else:
    check("C1 the shared identity guard is on the face", False,
          "shared.identity_refusal missing (the mirror's anti-self-sign mode "
          "must be one source for authorize and the cap lift)")

try:
    import authz_gates

    class _Auth(object):
        kind = "arbitration_verdict"
        who = roles[0] if roles else "developer"
        reason = "probe"
        scope = ["t000000-00"]
        expires = 9999999999

    err = authz_gates.validate_authorization(_Auth(), 1000, "t000000-00")
    check("C4 authorize still refuses an agent who through the same guard "
          "(no second source of truth, t260912-03 contract intact)",
          "self-authorize" in (err or ""), "err=%r" % (err,))
except Exception as e:  # noqa: BLE001
    env_fail("authz-gates", "authz_gates unavailable: %s: %s" % (type(e).__name__, e))

# ---------------------------------------------------------------------------
# D - the stop stays a person's stop
# ---------------------------------------------------------------------------
tier, _kind = shared.classify_stop_tier(TEXT)
check("D1 the cap stop classifies as judgement (an executor lift cannot clear it)",
      tier == shared.STOP_TIER_JUDGEMENT, "tier=%r" % (tier,))

# ---------------------------------------------------------------------------
# A8 - the printed line must survive how an operator pastes it (F-family)
# The face prints the lift grammar; chat clients and markdown render it with
# decoration. A paste that neither arms a lift nor is refused BY NAME is a
# silent no-op: the operator believes the exit is armed, retry_qc re-runs the
# walkthrough, and the ticket stops at the same sentence (the KI-382 feeling
# again). Direction-agnostic: arming OR a named refusal both satisfy it.
# ---------------------------------------------------------------------------
try:
    import shared as _shared

    _paste_shapes = [
        ("bold", "**lift=acceptance_cap report=%s reason=ok**" % token),
        ("italic", "*lift=acceptance_cap report=%s reason=ok*" % token),
        ("underscore", "_lift=acceptance_cap report=%s reason=ok_" % token),
        ("table-cell", "| lift=acceptance_cap report=%s reason=ok |" % token),
        ("bullet", "- lift=acceptance_cap report=%s reason=ok" % token),
        ("numbered", "1. lift=acceptance_cap report=%s reason=ok" % token),
        ("blockquote", "> lift=acceptance_cap report=%s reason=ok" % token),
        ("backticked", "`lift=acceptance_cap report=%s reason=ok`" % token),
        ("indented", "    lift=acceptance_cap report=%s reason=ok" % token),
    ]
    _silent = []
    for _name, _note in _paste_shapes:
        _rec, _err = _shared.acceptance_cap_lift(_note, "host", token)
        if not _rec and not (isinstance(_err, str) and _err.strip()):
            _silent.append(_name)
    check("A8 a pasted lift line either arms the lift or is refused by name "
          "(never a silent no-op)",
          not _silent, "silent no-ops: %r" % (_silent,))
except Exception as e:  # noqa: BLE001
    check("A8 a pasted lift line either arms the lift or is refused by name",
          False, "probe failed: %s: %s" % (type(e).__name__, e))

# ---------------------------------------------------------------------------
# E - the lift is readable on the face the operator looks at
# ---------------------------------------------------------------------------
q_at = CLI_SRC.find("def _v2_query")
projection = CLI_SRC[q_at:q_at + 4000] if q_at != -1 else ""
check("E1 the detail face projects the timeline (armed/used lift entries are "
      "readable with ticket show)",
      "'timeline'" in projection or '"timeline"' in projection,
      "ticket.py::_v2_query does not project timeline")
check("E2 the detail face projects the refusal ledger (a refused lift is named "
      "to the operator)",
      "'refused'" in projection or '"refused"' in projection,
      "ticket.py::_v2_query does not project refused")
check("E3 the face tells the operator the lift is recorded there",
      "recorded on the ticket face" in low or "on the ticket face" in low,
      "the exit sentence does not say where the record lands")

summary()
