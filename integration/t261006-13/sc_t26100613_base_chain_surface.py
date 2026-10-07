#!/usr/bin/env python3
"""sc_t26100613_base_chain_surface.py — shared base-point chain + coverage self-check
(t261006-13, B1/B2/B3; offline source locks + pure-function replay, stdlib only,
sc_check_inspection_produce_chain pattern).

Locked faces (grey-box L3 — public behaviour of the inspection period pipeline):
  B2 the base chain never self-seeds the current HEAD: the inspect activity carries no
     self-seed branch, and the prev-base fallback is lane base_ref -> suite base_ref ->
     the PREVIOUS REPORT's base_head only. HEAD may appear solely as the diff ENDPOINT.
  B1 one surface computation per period: a single module computes the period surface and
     both faces consume it; consumers fail closed on a base-sha mismatch and compute the
     same pure functions themselves when the shared file is absent (review cond. 1).
  B3 coverage self-check: an uncomputable surface fails the period loudly (the old
     scope_collapse med-finding silent path is gone); a genuinely small surface prints a
     front-page little-to-review block WITH the thresholds used (review cond. 3).
  Input robustness: malformed `git diff --name-status` lines are skipped and counted,
     never fatal.

Pre-implement = FAIL naming the missing module/branch (TDD-phase red expected); must be
green at arbitrate/merge. Missing engine module import = FAIL (named), not ENV_FAIL —
the modules are stdlib-pure by contract. Never touches 3099/7233, zero docker/Temporal.

Run directly: python3 integration/t261006-13/sc_t26100613_base_chain_surface.py (cwd=repo root).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))
sys.path.insert(0, str(ROOT / "integration"))

from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600)
ok, na, finish, env_fail = _ck.ok, _ck.na, _ck.finish, _ck.env_fail
NAME = "t261006-13-base-chain-surface"

ACT_SRC = (ROOT / "server/engine/agent_activities.py").read_text("utf-8")
FLOW_SRC = (ROOT / "server/engine/inspection_flow.py").read_text("utf-8")
INSPECT_SRC = (ROOT / "server/engine/inspection_inspect.py").read_text("utf-8")

SURFACE = None
try:
    import inspection_surface as surface_mod  # noqa: E402
    SURFACE = surface_mod
except Exception as e:  # pre-implement: module not landed yet
    print("FAIL named: server/engine/inspection_surface.py missing or not importable "
          "(t261006-13 B1 single surface module): %s: %s" % (type(e).__name__, e))

# ---------- B2: the base chain is real, never self-seeded ----------
print("\nB2 base chain (never self-seed HEAD as a previous base)")
SURFACE_SRC = ""
_SURF_PATH = ROOT / "server/engine/inspection_surface.py"
if _SURF_PATH.exists():
    SURFACE_SRC = _SURF_PATH.read_text("utf-8")
ok("base_source_this" not in ACT_SRC and "取当前 HEAD" not in ACT_SRC,
   "self-seed branch deleted from the inspect activity (no base_source_this key, no HEAD-seed message)")
ok("inspection_surface" in ACT_SRC,
   "inspect activity consumes the shared surface module (per-face recompute removed)")
if SURFACE is not None:
    ok(hasattr(SURFACE, "resolve_prev_base") and hasattr(SURFACE, "resolve_this_base")
       and hasattr(SURFACE, "compute_surface") and hasattr(SURFACE, "coverage_verdict"),
       "surface module exposes the declared pure functions "
       "(resolve_prev_base/resolve_this_base/compute_surface/coverage_verdict)")
    def _as_result(r):
        # grey-box: accept either a dict or a (base, meta) tuple — the contract is the
        # base VALUE and the unavailable verdict, not the container shape
        if isinstance(r, dict):
            return r
        if isinstance(r, (tuple, list)) and r:
            meta = dict(r[1]) if len(r) > 1 and isinstance(r[1], dict) else {}
            meta.setdefault("base", r[0])
            return meta
        return {"base": r}

    no_base = _as_result(SURFACE.resolve_prev_base({}))
    ok(no_base.get("base") in ("", None)
       and (no_base.get("verdict") == "unavailable"
            or no_base.get("base_source") == "unavailable"
            or no_base.get("status") == "unavailable"),
       "no base anywhere resolves to unavailable — resolve_prev_base never invents HEAD")
    # fallback chain: lane -> suite -> prev REPORT base_head; nothing else, never HEAD.
    doc = {"scan_meta": {"inspect": {"base_head": "deadbeef"}}}
    ok(_as_result(SURFACE.resolve_prev_base(doc)).get("base") == "deadbeef",
       "prev REPORT's base_head is the final fallback (B2: fall back to the previous report)")
    doc2 = {"lane": {"base_ref": "aa11bb22"}, "suite": {"base_ref": "cc33dd44"}}
    ok(_as_result(SURFACE.resolve_prev_base(doc2)).get("base") == "aa11bb22",
       "lane base_ref wins over suite base_ref (3-level chain preserved)")
    ok(_as_result(SURFACE.resolve_this_base("ee55ff66")).get("base") == "ee55ff66",
       "resolve_this_base returns the diff endpoint (current base_head is legitimate AS ENDPOINT)")
    tb = _as_result(SURFACE.resolve_this_base(""))
    ok(tb.get("verdict") == "unavailable" or tb.get("status") == "unavailable"
       or not tb.get("base"),
       "this-base empty resolves unavailable — no hidden HEAD seeding at the endpoint either")
else:
    ok(False, "surface module present (blocks all replay rows this section)")
    na("replay: resolve_prev_base/resolve_this_base truth table (module missing)")

# ---------- B1: one shared computation, consumed fail-closed ----------
print("\nB1 shared surface (one computation per period, consumers fail closed)")
ok("surface-" in ACT_SRC or "surface_%s" in ACT_SRC or "surface-" in FLOW_SRC
   or "surface_" in FLOW_SRC,
   "period surface is persisted/keys by period (surface-<period>) so the second face reads it")
ok("mismatch" in FLOW_SRC.lower() or "mismatch" in ACT_SRC.lower()
   or "stale" in FLOW_SRC.lower(),
   "consumer names stale/mismatched surface shas (fail-closed on mismatch)")
ok("unavailable" in FLOW_SRC and ("blocked" in FLOW_SRC or "_blocked" in FLOW_SRC),
   "uncomputable surface blocks the inspect stage with the reason (B3 loud fail, not a note)")

# ---------- B3: coverage self-check ----------
print("\nB3 coverage self-check (small surface stated, collapse not silent)")
ok("scope_collapse_findings" not in INSPECT_SRC
   or "little-to-review" in FLOW_SRC or "little_to_review" in FLOW_SRC,
   "old silent collapse path superseded by an explicit coverage verdict on the front page")
ok("little-to-review" in FLOW_SRC or "little_to_review" in FLOW_SRC,
   "little-to-review verdict exists and reaches the report front page")
ok("threshold" in FLOW_SRC.lower(),
   "front-page coverage block names the thresholds used (review cond. 3: a named bar, not hidden)")

if SURFACE is not None and hasattr(SURFACE, "compute_surface"):
    good = ("M\tserver/engine/a.py\nA\tintegration/x/sc_new_case.py\n"
            "M\tserver/engine/b.py\nR100\told.py\tnew.py")
    s = _as_result(SURFACE.compute_surface("p1", "p2", good))
    flat = str(s)
    ok("server/engine/a.py" in flat and "integration/x/sc_new_case.py" in flat,
       "compute_surface splits changed files by face (integration/ vs server/)")
    ns = s.get("new_scenarios") or s.get("new_scenarios_count") or 0
    try:
        ns_ok = int(ns) >= 1
    except (TypeError, ValueError):
        ns_ok = False
    ok(ns_ok or "sc_new_case" in flat,
       "new scenario files are counted for the coverage verdict")
    malformed = "GARBAGE LINE WITHOUT TABS\nM\tserver/engine/ok.py\n\n??\tuntracked-ish"
    try:
        s2 = _as_result(SURFACE.compute_surface("p1", "p2", malformed))
        raised = False
    except Exception:
        s2 = {}
        raised = True
    ok(not raised,
       "malformed name-status lines never raise (skip + count, B-side robustness)")
    ok("server/engine/ok.py" in str(s2),
       "well-formed lines survive alongside malformed ones")
    s3 = _as_result(SURFACE.compute_surface("p1", "p2", "M\tserver/engine/only.py"))
    v = None
    if hasattr(SURFACE, "coverage_verdict"):
        try:
            v = SURFACE.coverage_verdict(s3, {"min_surface_files": 8,
                                              "min_new_scenarios": 1})
        except TypeError:
            v = SURFACE.coverage_verdict(s3)
    v_str = str(v)
    ok("little-to-review" in v_str,
       "1-file surface under threshold -> little-to-review (stated, never silent no-problem)")
else:
    na("replay: compute_surface/coverage_verdict truth table (module missing)")

print()
finish(NAME)
