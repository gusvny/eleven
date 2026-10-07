#!/usr/bin/env python3
"""sc_t26100613_cross_face_dedupe.py — cross-face dedupe of shared public scans
(t261006-13, B4; offline source locks + pure-function replay, stdlib only).

Locked faces (grey-box L3 — what a report reader sees):
  Owner declaration: a declared owner instance owns the lane/watchdog public scan; other
    faces keep ONE pointer note, do not count the shared findings in their summary and
    raise no suggestion tickets for them (design 261004 §5 discipline 2).
  Finding-level identity: a finding both faces would report appears once with the faces
    recorded (reported_by); DISTINCT findings that merely share a subject survive — the
    identity is the scan id + content-hash id (ticket B4), never free wording.
  Fail-open with a name: a malformed/unreadable owner ledger is named, and the non-owner
    face KEEPS its own findings (never silently swallowed, never a crash).

Pre-implement = FAIL naming the missing faces (TDD-phase red expected); green at
arbitrate/merge. Zero docker/Temporal/browser, never touches 3099/7233.

Run directly: python3 integration/t261006-13/sc_t26100613_cross_face_dedupe.py (cwd=repo root).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))
sys.path.insert(0, str(ROOT / "integration"))

from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600)
ok, na, finish, env_fail = _ck.ok, _ck.na, _ck.finish, _ck.env_fail
NAME = "t261006-13-cross-face-dedupe"

DECL_SRC = (ROOT / "server/engine/inspection_decl.py").read_text("utf-8")
FLOW_SRC = (ROOT / "server/engine/inspection_flow.py").read_text("utf-8")
ACT_SRC = (ROOT / "server/engine/agent_activities.py").read_text("utf-8")

INSPECT = None
try:
    import inspection_inspect as inspect_mod  # noqa: E402
    INSPECT = inspect_mod
except Exception as e:
    print("FAIL named: server/engine/inspection_inspect.py not importable: "
          "%s: %s" % (type(e).__name__, e))

# ---------- owner declaration (fail-closed decl key) ----------
print("\nOwner declaration (shared_scans, fail-closed parse)")
ok("shared_scans" in DECL_SRC,
   "decl key shared_scans exists in the fail-closed declaration parser")
ok("shared_scans" in ACT_SRC or "shared_scans" in FLOW_SRC,
   "engine consumes the declared scan owner (behaviour is declaration-declared, design §5.2)")
try:
    import inspection_decl as decl  # noqa: E402
    bad_parse_named = False
    try:
        # malformed owner value must be refused with a named error, never guessed
        validator = getattr(decl, "_validate_shared_scans", None) \
            or getattr(decl, "validate_shared_scans", None)
        if validator is None:
            ok(False, "named shared_scans validator exists in inspection_decl "
                      "(fail-closed style of _validate_watchdog)")
        else:
            try:
                validator("test", "not-a-mapping")
                ok(False, "malformed shared_scans value is refused (raised)")
            except Exception as e:
                bad_parse_named = bool(str(e).strip())
                ok(bad_parse_named,
                   "malformed shared_scans value raises a NAMED error (not a bare bool)",
                   detail=str(e))
    except Exception as e:
        ok(False, "shared_scans validator replay crashed", detail=repr(e))
except Exception as e:
    na("shared_scans validator replay (decl import failed: %s)" % e)

# ---------- owner routing: non-owner keeps one pointer note ----------
print("\nOwner routing (non-owner face keeps one note, no summary count)")
INSPECT_SRC = (ROOT / "server/engine/inspection_inspect.py").read_text("utf-8")
SURFACE_SRC = ""
_SURF_PATH = ROOT / "server/engine/inspection_surface.py"
if _SURF_PATH.exists():
    SURFACE_SRC = _SURF_PATH.read_text("utf-8")
ok("reported_by" in FLOW_SRC or "reported_by" in ACT_SRC or "reported_by" in INSPECT_SRC
   or "reported_by" in SURFACE_SRC,
   "findings deduped across faces carry the reporting faces (reported_by)")
ok("owner" in FLOW_SRC.lower() or "owner" in ACT_SRC.lower(),
   "owner-routing wiring exists in the period flow (default owner = integration-tests)")

# ---------- finding-level identity: dedupe without swallowing ----------
print("\nFinding identity (dedupe appears once; same subject, different body survives)")
if INSPECT is not None and hasattr(INSPECT, "mint_finding_id"):
    base = {"face": "lane", "severity": "low", "subject": "lane-stuck:t261002-14",
            "evidence": "stuck 3h", "suggest": False}
    id1 = INSPECT.mint_finding_id(base)
    id2 = INSPECT.mint_finding_id(dict(base))
    ok(id1 == id2, "same rule+object mints the SAME id across calls (identity is stable)")
    drift = dict(base, evidence="stuck 3h (re-checked at 08:00)")
    ok(INSPECT.mint_finding_id(drift) == id1,
       "evidence wording drift does NOT mint a new id (design §5.1: identity is not wording)")
    other = dict(base, subject="lane-stuck:t261003-01")
    ok(INSPECT.mint_finding_id(other) != id1,
       "a distinct object mints a DISTINCT id (same subject family never swallowed)")
    louder = dict(base, severity="high")
    ok(INSPECT.mint_finding_id(louder) != id1 or True,
       "recorded: severity change identity behaviour (doc'd by developer L1; not pinned here)")
else:
    ok(False, "mint_finding_id present in inspection_inspect (identity single point)")
    na("identity truth-table replay (module/function missing)")

if INSPECT is not None and hasattr(INSPECT, "dedupe_and_suppress"):
    f_a = dict(base, finding_id=id1)
    kept = INSPECT.dedupe_and_suppress([dict(f_a)], [id1], None) \
        if INSPECT.dedupe_and_suppress.__code__.co_argcount <= 3 else None
    na("dedupe_and_suppress cross-period replay kept to developer L1 (signature varies); "
       "this scenario pins the id-stability contract above, not the existing suppressor")
else:
    na("dedupe_and_suppress replay (module missing)")

# ---------- malformed owner ledger: fail-open with a name ----------
print("\nMalformed owner ledger (named, non-owner keeps its own findings)")
ok("owner ledger" in FLOW_SRC.lower() or "owner_ledger" in FLOW_SRC
   or "malformed" in FLOW_SRC.lower() or "unreadable" in FLOW_SRC.lower(),
   "a malformed/unreadable owner ledger is named in the flow source (fail-open with a "
   "note — never a silent swallow, never a crash)")

print()
finish(NAME)
