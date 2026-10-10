#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_intake_optin_journey.py -- t261009-76 L3 journey: the develop-buffer
opt-in is reachable from the REAL intake (grey-box L3, offline seconds,
stdlib only, zero docker/Temporal/browser, never touches 3099/7233; the
intake refusal gate runs BEFORE the Temporal connect, so the whole face is
observable in a plain process — an offline run is itself the evidence that
no workflow start is needed to be refused).

intent: this entry owns the intake seam the ticket names — ticket t261009-76
spec (1)(2)(3). KI-01M4HBC9ANXZXQRDQR54Z9C0MZ instance four: a mechanism
landed, no call site owned it — the intake built a plain TicketInput, so
`getattr(inp, "lane_version", "")` was always "" in production and every
ticket silently routed legacy.
  A  a create payload naming lane_version="develop-buffer-v1" plus a DECLARED
     line validates at intake and is carried into an input the workflow reads
     as opted in: the intake returns the CANONICAL version and the declared
     line id (single truth = fixture lines.json), and applying the opt-in to a
     real base TicketInput yields the opted-in subclass carrying both fields —
     the exact two intake calls the real ticket-start makes, never a
     hand-invented payload.
  B  refusals are BY NAME at intake, before the workflow starts: unknown
     version (value named + registry listed), malformed versions (whitespace /
     underscore / uppercase / non-string — refused as malformed, never
     stringified), develop-buffer with an empty develop_line_id, an undeclared
     line id (message names the id AND the declared list read back from the
     fixture lines.json — no duplicated truth), legacy-v1 carrying a line id,
     and the fields on a non-dev-lane template.
  C  absence stays legacy: a payload with neither field validates clean with
     EMPTY fields and applying the opt-in returns the SAME plain TicketInput
     object unchanged (exact legacy type, no lane attributes); the engine
     getattr default stays the in-flight replay guard — no silent migration.

Intent split (no duplication): the version-name truth tables and the landing
act belong to the t261009-46 entries (they pin develop_line.parse_lane_version
and land_to_line directly); this entry owns only the INTAKE seam — what the
real create payload turns into, and what it is refused by. The ticket-face
(declared schema / list rows) belongs to t261009-76-intake-optin-face.

Surfaces anchored: the client intake's opt-in capabilities discovered by
contract name (the validator returning (ok, lane_version, develop_line_id,
err) and the carrier applying it to the input) — a contract-preserving
refactor must stay green; a missing capability is a named FAIL (the expected
TDD signal before implement); green required at the integration gate / merge.
Engine tree or git missing = ENV_FAIL exit 2.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True)
if REPO.returncode != 0 or not REPO.stdout.strip():
    print("ENV_FAIL: git repo root unresolved (git missing or not a repo)")
    sys.exit(2)
ROOT = REPO.stdout.strip()
ENGINE = os.path.join(ROOT, "server", "engine")
if not os.path.isdir(ENGINE):
    print("ENV_FAIL: engine tree missing: %s" % ENGINE)
    sys.exit(2)
sys.path.insert(0, ENGINE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


DEV_BUFFER = "develop-buffer-v1"
LEGACY = "legacy-v1"
LINE_A = "line-a"
LINE_B = "line-b"

with tempfile.TemporaryDirectory(prefix="t26100976-intake-") as tmp:
    # Fixture project store: the admin-written declaration is the single truth.
    dev_dir = os.path.join(tmp, "proj-a", "data", "develop")
    os.makedirs(dev_dir)
    decl = [
        {"line_id": LINE_A, "scope": "fix", "owner": "qa",
         "repositories": [{"name": "sandbar", "branch": "lane/line-a"}]},
        {"line_id": LINE_B, "scope": "fix", "owner": "qa",
         "repositories": [{"name": "sandbar", "branch": "lane/line-b"}]},
    ]
    with open(os.path.join(dev_dir, "lines.json"), "w", encoding="utf-8") as f:
        json.dump(decl, f)
    os.environ["SANDBAR_PROJECTS_DIR"] = tmp
    PROJ = "proj-a"

    import client  # noqa: E402  (engine intake module, the production seam)
    import develop_line as dl  # noqa: E402
    from shared import TicketInput  # noqa: E402

    # -- contract-name discovery of the intake's opt-in capabilities ---------
    cands = [n for n in sorted(dir(client))
             if "optin" in n.lower() or "opt_in" in n.lower()]
    validator = carrier = None
    for n in cands:
        obj = getattr(client, n)
        if not callable(obj):
            continue
        try:
            out = obj({"lane_version": DEV_BUFFER, "develop_line_id": LINE_A},
                      template_id="dev-lane", project_key=PROJ)
        except TypeError:
            continue  # different arity → the carrier, judged below
        if isinstance(out, tuple) and len(out) == 4 and isinstance(out[0], bool):
            validator = obj
    for n in cands:
        obj = getattr(client, n)
        if obj is validator or not callable(obj):
            continue
        carrier = obj
    if validator is None:
        check("A1.intake-seam-present", False,
              "no intake opt-in validator capability found on the client module "
              "(TDD signal pre-implement); candidates=%r" % cands)
        print("INTEG_RESULT pass=%d fail=%d" % (passed, failed))
        sys.exit(1)
    check("A1.intake-seam-present", True)

    def intake(args, template_id="dev-lane"):
        """Drive the real intake validator; returns (ok, lane_version, line_id, err)."""
        return validator(args, template_id=template_id, project_key=PROJ)

    def carried(lane_version, develop_line_id, base=None):
        """Apply the opt-in to a real base input (the intake's carrier step)."""
        if carrier is None:
            return None
        if base is None:
            base = TicketInput(ticket_id="t26100976-fixture", template_id="dev-lane")
        return carrier(base, lane_version, develop_line_id)

    # ---- A: opt-in carried through the real intake path ----
    ok, lv, dlid, err = intake({"lane_version": DEV_BUFFER, "develop_line_id": LINE_A})
    check("A2.optin-accepted", ok, "intake refused a lawful opt-in: %r" % err)
    check("A3.version-canonical-develop-buffer",
          lv == DEV_BUFFER and dl.parse_lane_version(lv) == DEV_BUFFER,
          "lane_version=%r" % lv)
    check("A4.declared-line-carried",
          dlid == LINE_A and dl.load_line(PROJ, LINE_A) is not None,
          "develop_line_id=%r" % dlid)
    inp = carried(lv, dlid)
    check("A5.input-reads-opted-in",
          inp is not None and type(inp).__name__ != "TicketInput"
          and str(getattr(inp, "lane_version", "")) == DEV_BUFFER
          and str(getattr(inp, "develop_line_id", "")) == LINE_A,
          "carrier=%r input=%r" % (carrier, inp))

    ok2, lv2, _, err2 = intake({"lane_version": LEGACY})
    check("A6.explicit-legacy-is-lawful", ok2 and lv2 == LEGACY,
          "ok=%r lv=%r err=%r" % (ok2, lv2, err2))

    # ---- B: named refusals at intake (offline process = before the start) ----
    def refused(tag, args, needles, template_id="dev-lane"):
        okr, _, _, errr = intake(args, template_id=template_id)
        ok = (not okr) and all(n in errr for n in needles)
        check(tag, ok, "ok=%r err=%r needles=%r" % (okr, errr, needles))

    refused("B1.unknown-version-names-registry",
            {"lane_version": "develop-buffer-v2"}, ["develop-buffer-v2", LEGACY, DEV_BUFFER])
    refused("B2.whitespace-malformed",
            {"lane_version": " " + DEV_BUFFER}, ["malformed"])
    refused("B3.underscore-malformed",
            {"lane_version": "develop_buffer_v1"}, ["malformed"])
    refused("B4.uppercase-malformed",
            {"lane_version": "Develop-Buffer-V1"}, ["malformed"])
    refused("B5.non-string-malformed-not-stringified",
            {"lane_version": ["develop-buffer-v1"]}, ["malformed"])
    refused("B6.develop-buffer-requires-line",
            {"lane_version": DEV_BUFFER}, ["develop_line_id"])
    refused("B7.undeclared-line-names-id-and-list",
            {"lane_version": DEV_BUFFER, "develop_line_id": "line-zzz"},
            ["line-zzz", LINE_A, LINE_B])
    refused("B8.legacy-with-line-refused",
            {"lane_version": LEGACY, "develop_line_id": LINE_A},
            [LINE_A, "develop_line_id", DEV_BUFFER])
    refused("B9.foreign-template-refused",
            {"lane_version": DEV_BUFFER, "develop_line_id": LINE_A},
            ["dev-lane", "template"], template_id="light-lane")

    # ---- C: absence stays legacy, no silent migration ----
    okc, lvc, dlidc, errc = intake({})
    check("C1.absence-legacy-empty-fields", okc and lvc == "" and dlidc == "" and errc == "",
          "ok=%r lv=%r dlid=%r err=%r" % (okc, lvc, dlidc, errc))
    base = TicketInput(ticket_id="t26100976-fixture", template_id="dev-lane")
    out = carried(lvc, dlidc, base=base) if carrier is not None else None
    check("C2.absence-plain-ticketinput-unchanged",
          out is base and type(out).__name__ == "TicketInput",
          "the carrier must return the SAME plain input object unchanged")
    check("C3.getattr-replay-default",
          getattr(out, "lane_version", "") == "",
          "an older-history replay resolves through the getattr default")

print("INTEG_RESULT pass=%d fail=%d" % (passed, failed))
sys.exit(1 if failed else 0)
