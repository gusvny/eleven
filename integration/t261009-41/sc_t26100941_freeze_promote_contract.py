"""sc_t26100941_freeze_promote_contract.py — t261009-41, grey-box L2, offline.

The engine projection contract the Certification tab renders (dispatch rules
2/5): a red round freezes the line against NEW landings but never takes the
already-certified part hostage (develop-buffer design goal 8, t261009-21).
Anchored on the public projections (freeze_state / may_land /
ticket_wait_state / ticket_outcome), never on internal helpers, so a
contract-preserving refactor of the engine must not break this.

Intent split (no duplication): the landing journey over real repos belongs
to t261009-18-landing-journey; run-record identity/counts belong to
t261009-11-run-record-contract; the hatch store belongs to t261009-13; the
node face of the tab model belongs to the sibling seam scenario
sc_t26100941_certification_face_seam.mjs. This entry owns ONLY the
projection truth table: promote-lives-through-freeze, the boundary between
certified and waiting, and the named refusal matrix.

Engine module unimportable = ENV_FAIL exit 2. Pre-implement tree: this face
is engine-side and already landed (t261009-21), so it must be GREEN now.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE = os.path.join(ROOT, "server", "engine")


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def main():
    py = None
    for cand in ("server/engine/.venv/bin/python", sys.executable):
        p = os.path.join(ROOT, cand)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            py = p
            break
        if cand is sys.executable:
            py = cand
    probe = subprocess.run(
        [py, "-c", "import develop_certify, develop_promote"],
        cwd=ENGINE, capture_output=True, text=True)
    if probe.returncode != 0:
        env_fail("engine projections unimportable: %s" % probe.stderr.strip()[-300:])
    code = subprocess.run(
        [py, "-c", PROBE, ROOT],
        capture_output=True, text=True, cwd=ENGINE)
    sys.stdout.write(code.stdout)
    sys.stderr.write(code.stderr[-800:])
    if code.returncode == 2:
        env_fail("probe reported environment failure")
    if code.returncode != 0:
        fail("projection contract probe failed (see stdout above)")


PROBE = r"""
import json, sys
root = sys.argv[1]
sys.path.insert(0, root + "/server/engine")
import develop_certify as dc
import develop_promote as dp

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))

LINE = "dev/main"
T_CERT = "t-cert"
T_WAIT = "t-wait"

landing = lambda t, at, seq: {"kind": "landing", "id": "ldg-" + t, "ticket": t,
                         "line": LINE, "repos": [{"repo": "r", "revision": "rev-" + t}],
                         "at": at, "seq": seq}
green_cert = {"kind": "certification", "id": "cert-green", "line": LINE,
              "run": "run-G", "booked_red": "0", "judged_by": "host", "at": 2000,
              "seq": 3, "repos": [{"repo": "r", "revision": "rev-t-cert"}]}
red_cert = {"kind": "certification", "id": "cert-red", "line": LINE,
            "run": "run-R", "booked_red": "1", "judged_by": "host", "at": 3000,
            "seq": 4, "repos": [{"repo": "r", "revision": "rev-t-wait"}]}
freeze = {"kind": "freeze", "id": "frz-1", "line": LINE,
          "cause": "cert-red", "at": 3100, "seq": 5}
attrib = {"kind": "freeze_change", "freeze": "frz-1", "change": "attribution",
          "by": "host", "reason": "implicates t-wait content", "value": T_WAIT,
          "at": 3200, "line": LINE, "seq": 6}

rows = [landing(T_CERT, 1000, 1), landing(T_WAIT, 1500, 2),
        green_cert, red_cert, freeze, attrib]
promotions = []  # nothing promoted yet

is_green = lambda rid: {"run-G": True, "run-R": False}.get(rid)

# F1 promote lives through freeze: the ticket certified BEFORE the red round
# still reads certified_by from the records — the freeze never touches it.
# main@4373682 moved promotions into the one delivery seq space (t261009-29):
# ticket_outcome(rows, ticket, is_green, ticket_record) — no second file.
out = dp.ticket_outcome(rows, T_CERT, is_green=is_green)
check("F1 certified_by survives freeze", out.get("certified_by") == "cert-green")
check("F1b landed_at is the landing's revisions",
      out.get("landed_at") == landing(T_CERT, 1000, 1)["repos"])

# F2 the frozen line refuses NEW landings by kind, keeps the exempt fix kind.
st = dc.freeze_state(rows, LINE)
check("F2 frozen", st["frozen"] is True)
check("F2b cause names the red cert", st["cause"] == "cert-red")
check("F2c culprit named from attribution", st["culprit"] == T_WAIT)
check("F2d ordinary landing refused while frozen",
      dc.may_land(rows, LINE, "chore") is False)
# t261009-63: the exemption is derived from a current `repairs` relation
# naming the repaired landing — kind-only self-declaration is refused by name.
def _raised41(fn):
    try:
        fn()
        return ""
    except dc.CertifyError as e:
        return str(e)
check("F2e0 kind-only fix refused BY NAME on a frozen line (no relation)",
      "freeze_repair_relation_missing" in _raised41(
          lambda: dc.may_land(rows, LINE, "fix")))
rel41 = {"id": "rel-fix41", "from": "t-fixer", "to": T_CERT,
         "kind": dc.REL_KIND_REPAIRS, "recorded_by": "host",
         "reason": "repairs the landing the red implicated",
         "evidence": {"what": "ticket", "ref": T_CERT},
         "at": 1791510000000}
check("F2e fix kind still lands through the repairs relation (goal 8)",
      dc.may_land(rows + [rel41], LINE, "fix", "t-fixer", rel41) is True)
try:
    undecl = None
    dc.may_land(rows, LINE, "fxi")
except dc.CertifyError as e:
    undecl = str(e)
check("F2f undeclared kind refused BY NAME, never read as the freeze",
      undecl is not None and "undeclared" in undecl)

# F3 the certified/waiting boundary comes from the records' order.
# t261011-23 arbitrate iteration: coverage is now GREEN-RANGE membership
# (prev_cert.seq < landing.seq <= cert.seq, one rule, two faces), so the
# t-wait landing (seq 2) sits inside cert-green's range (0 < 2 <= 3) and
# reads certified — the fixture's t-wait did NOT land after the red round,
# so the old F3b check name did not match its own fixture. The intent
# (a landing after the red round is not silently certified) moves to a
# landing that actually lands after cert-red (seq > 4).
cov = dc.ticket_wait_state(rows, LINE, landing(T_CERT, 1000, 1), is_green, 9999)
w = dc.ticket_wait_state(rows, LINE, landing(T_WAIT, 1500, 2), is_green, 9999)
check("F3 covered landing is certified with covered_by",
      cov["state"] == "certified" and cov.get("covered_by") == "cert-green")
check("F3b landing inside the green round's range is certified (range rule, t261011-23)",
      w["state"] == "certified" and w.get("covered_by") == "cert-green")
after_red = {"kind": "landing", "id": "ldg-t-after", "ticket": "t-after",
             "line": LINE, "repos": [{"repo": "r", "revision": "rev-t-after"}],
             "at": 3500, "seq": 7}
wa = dc.ticket_wait_state(rows, LINE, after_red, is_green, 9999)
check("F3c landing after the red round is NOT silently certified",
      wa["state"] in ("waiting", "red_implicated"))

# F4 named refusals on malformed input (loud, never guessed).
def raises(fn):
    try:
        fn()
        return None
    except dc.CertifyError as e:
        return str(e)
check("F4a not-a-landing refused", raises(
    lambda: dc.ticket_wait_state(rows, LINE, {"kind": "certification"}, is_green, 1)) is not None)
check("F4b landing not on the line refused", raises(
    lambda: dc.ticket_wait_state(rows, "dev/other", landing(T_WAIT, 1500, 2), is_green, 1)) is not None)
check("F4c non-ms now refused", raises(
    lambda: dc.ticket_wait_state(rows, LINE, landing(T_WAIT, 1500, 2), is_green, "now")) is not None)
check("F4d silent None run reader refused once a cert exists", raises(
    lambda: dc.ticket_wait_state(rows, LINE, landing(T_WAIT, 1500, 2), None, 1)) is not None)

# F5 an honest 'could not run' is not a red: no freeze opens from it.
check("F5 could-not-run never freezes", dc.should_freeze("") is False)
check("F5b content-attributed red freezes", dc.should_freeze("t-wait") is True)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print("%s %s" % ("ok " if ok else "RED", n))
print(json.dumps({"total": len(checks), "failed": bad}))
sys.exit(1 if bad else 0)
"""

if __name__ == "__main__":
    main()
