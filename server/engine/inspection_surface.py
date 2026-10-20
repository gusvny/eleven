#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Period change surface: ONE computation per inspection period, shared by all faces.

Ticket t261006-13 (design source: the 261004 inspection redesign note, section 2
"the shared first step" and section 5 "the four shared disciplines"):

- B1 shared base computation: the period surface = prev period's base point → this
  period's base point, split by face. Both faces consume this single computation.
- B2 the base must be real: fall back to the previous REPORT's recorded base point;
  NEVER self-seed the current HEAD as a previous-period base (self-seeding erases the
  diff and turns the period into a no-op). Using the current HEAD as THIS period's diff
  *endpoint* is legitimate and is never recorded as a future prev-base.
- B3 coverage self-check: a too-small surface is stated on the front page
  ("little to review"); a missing/uncomputable surface is `unavailable` and the period
  must fail loudly — it is a defect of the period, not a finding-free result.
- B4 cross-face dedupe: a finding the owner face already reported (same content-hash id)
  is suppressed in the non-owner face with the reporting faces recorded. Identity is the
  minted content hash (rule + subject family, stable under whitespace/wording drift),
  so distinct findings that merely share a subject survive.
- B5 machine noise is not findings: sweep truncation and unreadable-ticket lists become
  counted machine notes, not line-enumerated findings repeated every period.

stdlib-only, fail-closed / fail-named (no silent degradation), pure functions except the
two explicitly IO-marked helpers (surface file load).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Face split (B1): changed files are attributed to the face that owns them.
# ---------------------------------------------------------------------------
#: path prefix → face name. First matching prefix wins; anything else is "other".
FACE_BY_PREFIX: Tuple[Tuple[str, str], ...] = (
    ("integration/", "test"),
    ("server/", "simplify"),
)

#: surface dict schema marker (forward-compat: consumers reject unknown schema fail-closed)
SURFACE_SCHEMA = 1

# ---------------------------------------------------------------------------
# Coverage thresholds (B3). Review condition 3: the defaults are named here, are
# overridable per instance via the `surface_thresholds` declaration key, and the
# front-page block always prints the thresholds actually used.
# ---------------------------------------------------------------------------
DEFAULT_MIN_SURFACE_FILES = 8
DEFAULT_MIN_NEW_SCENARIOS = 1

#: scenario file naming (integration scenarios register as sc_*.py|.mjs)
SCENARIO_PREFIX = "sc_"

#: shared public scan → default owner instance (design §5 discipline 2: the public
#: lane/watchdog scan lands in ONE declared place; other faces keep a reference line).
#: The engine default keeps behaviour deterministic without editing the root
#: inspection.yaml (outside this ticket's write set); the declaration may override.
DEFAULT_SHARED_SCAN_OWNER = "integration-tests"

#: public scans a declaration may route to an owner face (fail-closed vocabulary).
SHARED_SCAN_NAMES = ("lane-watchdog",)

#: coverage threshold keys a declaration may set (fail-closed vocabulary).
SURFACE_THRESHOLD_KEYS = ("min_surface_files", "min_new_scenarios")


def split_face(path: str) -> str:
    """Changed file path → owning face ("test" | "simplify" | "other"). Pure."""
    p = str(path or "").replace("\\", "/").lstrip("./")
    for prefix, face in FACE_BY_PREFIX:
        if p.startswith(prefix):
            return face
    return "other"


def resolve_prev_base(prev_doc: Any) -> Dict[str, Any]:
    """Previous period's REAL base point, three-level fallback (B2; borrowed from the
    260929 contract-A chain, moved out of the inspect activity so every face resolves the
    same way):

      1. prev_doc["lane"]["base_ref"]      (suite period lane base)
      2. prev_doc["suite"]["base_ref"]     (suite receipt base)
      3. prev_doc["scan_meta"]["inspect"]["base_head"]  (the PREVIOUS REPORT's endpoint)

    There is NO fourth level. In particular this resolver never returns a self-seeded
    HEAD: no usable level → {"verdict": "unavailable"} and the period fails loudly
    (B3), never a seeded no-op diff.
    Returns {"base", "base_source", "verdict"}; verdict "ok" | "unavailable".
    Malformed containers are tolerated (unavailable — the caller names the gap)."""
    if isinstance(prev_doc, dict):
        for key, source in (("lane", "prev lane.base_ref"),
                            ("suite", "prev suite.base_ref")):
            d = prev_doc.get(key)
            if isinstance(d, dict):
                ref = d.get("base_ref")
                if isinstance(ref, str) and ref.strip():  # non-string is unusable (fail-closed)
                    return {"base": ref.strip(), "base_source": source, "verdict": "ok"}
        sm = prev_doc.get("scan_meta")
        ins = sm.get("inspect") if isinstance(sm, dict) else None
        if isinstance(ins, dict):
            ref = ins.get("base_head")
            if isinstance(ref, str) and ref.strip():
                return {"base": ref.strip(),
                        "base_source": "prev scan_meta.inspect.base_head",
                        "verdict": "ok"}
    return {"base": "", "base_source": "unavailable", "verdict": "unavailable"}


# ---------------------------------------------------------------------------
# Declared bootstrap base (t261018-12): the lawful restart for a dead prev-base
# chain. DESIGN RULING (recorded on ticket t261018-12): B2 forbids SELF-seeding
# — the engine picking the current HEAD as its own previous base, which erases
# the diff. It does NOT forbid an OPERATOR-DECLARED base: a human writes
# surface-bootstrap-<instance_id>.json (schema below) naming a real past commit;
# the activity uses it as prev_base ONLY when the report chain is unavailable,
# records the fact in the surface, and the next period inherits a real base
# through the normal report chain. There is NO second fallback and NO HEAD
# seeding: absent file → the period still fails loudly (unchanged); malformed
# or unresolvable bootstrap → unavailable naming the defect (fail-closed).
# ---------------------------------------------------------------------------

#: schema marker for the bootstrap file (consumers reject foreign schemas)
BOOTSTRAP_SCHEMA = 1


def bootstrap_file_name(instance_id: str) -> str:
    """Bootstrap file for one instance. Pure. The instance id must be a plain
    basename (no separators) — defense in depth against a path-shaped id ever
    reaching a filename."""
    iid = str(instance_id or "")
    if not iid or "/" in iid or "\\" in iid or iid in (".", ".."):
        raise ValueError("invalid instance id (bootstrap filename): %r" % iid)
    return "surface-bootstrap-%s.json" % iid


def parse_bootstrap_base(raw: Any) -> Dict[str, Any]:
    """Validate the CONTENT of a bootstrap file (pure; the file read and the
    repo existence check are the caller's job).

    Returns {"base": <sha>, "verdict": "ok"} or
    {"base": "", "verdict": "unavailable", "reason": <named defect>}.

    Policy: `base_ref` must be the FULL 40-hex commit sha. No prefixes (an
    abbreviated sha is ambiguous by design; a ref name would drift). The pure
    side checks syntax only — the caller must additionally confirm the commit
    exists in the reviewed repo (`git rev-parse --verify <sha>^{commit}`) before
    the base flows into a diff."""
    if not isinstance(raw, dict):
        return {"base": "", "verdict": "unavailable",
                "reason": "bootstrap content is not an object (%s)" % type(raw).__name__}
    if raw.get("schema") != BOOTSTRAP_SCHEMA:
        return {"base": "", "verdict": "unavailable",
                "reason": "bootstrap schema %r is not %r" % (raw.get("schema"), BOOTSTRAP_SCHEMA)}
    ref = raw.get("base_ref")
    if not isinstance(ref, str) or not ref.strip():
        return {"base": "", "verdict": "unavailable",
                "reason": "bootstrap base_ref missing/not a string (%r)" % (ref,)}
    ref = ref.strip()
    if len(ref) != 40 or any(c not in "0123456789abcdef" for c in ref.lower()):
        return {"base": "", "verdict": "unavailable",
                "reason": "bootstrap base_ref %r is not a full 40-hex commit sha "
                          "(full sha required, no prefixes/refs)" % ref[:12]}
    base: Dict[str, Any] = {"base": ref.lower(), "verdict": "ok"}
    reason = raw.get("reason")
    if isinstance(reason, str) and reason.strip():
        base["reason"] = reason.strip()[:200]
    return base


def load_declared_bootstrap(ledger_dir: Any, instance_id: str, base_dir: Any
                            ) -> Dict[str, Any]:
    """Read + validate + EXISTENCE-CHECK the instance's declared bootstrap base
    (t261018-12; IO + git — the second explicitly IO-marked helper in this module).

    Returns one of:
      {"state": "absent"}                      — no bootstrap file (the period keeps
                                                 its original unavailable reason)
      {"state": "defective", "reason": ...}    — present but unreadable / malformed /
                                                 wrong schema / bad sha syntax /
                                                 UNRESOLVABLE in the reviewed repo —
                                                 named, never silently ignored
      {"state": "ok", "base": <40-hex sha>, "reason": ...?}
                                                 — a real commit in the reviewed repo

    The `git rev-parse --verify <sha>^{commit}` check is the boundary the pure
    validator (parse_bootstrap_base) cannot cross: a syntactically valid but
    nonexistent (typo / GC'd / foreign) sha must never flow into a diff. Never
    raises."""
    try:
        fname = bootstrap_file_name(instance_id)
    except ValueError as e:
        return {"state": "defective", "reason": "bootstrap file name refused: %s" % e}
    p = Path(str(ledger_dir or "")) / fname
    if not p.is_file():
        return {"state": "absent"}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"state": "defective",
                "reason": "%s unreadable (%s: %s)" % (fname, type(e).__name__, e)}
    res = parse_bootstrap_base(raw)
    if res.get("verdict") != "ok":
        return {"state": "defective", "reason": "%s: %s" % (fname, res.get("reason"))}
    sha = str(res["base"])
    try:
        proc = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "--verify", "--quiet",
             "%s^{commit}" % sha],
            timeout=30, capture_output=True, text=True, check=False)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {"state": "defective",
                "reason": "%s: existence check not runnable (%s: %s)"
                          % (fname, type(e).__name__, e)}
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return {"state": "defective",
                "reason": ("%s: base_ref %s does not resolve to a commit in the "
                           "reviewed repo (typo, GC'd or foreign sha)" % (fname, sha[:12]))}
    out: Dict[str, Any] = {"state": "ok", "base": sha}
    if res.get("reason"):
        out["reason"] = str(res["reason"])
    return out


def resolve_this_base(base_head: Any) -> Dict[str, Any]:
    """This period's diff ENDPOINT (pure). A non-empty base_head (the suite lane's
    base_ref) is the legitimate endpoint. An empty one is `unavailable` — there is NO
    hidden HEAD seeding here either (B2): the caller may resolve HEAD itself for the
    endpoint, but that value must stay an endpoint and is never recorded as a future
    prev-base."""
    ref = str(base_head or "").strip()
    if ref:
        return {"base": ref, "verdict": "ok"}
    return {"base": "", "verdict": "unavailable"}


def compute_surface(prev_base: str, this_base: str, name_status_text: str,
                    thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Parsed `git diff --name-status` text → the period surface dict (pure; B1).

    Malformed lines are skipped AND counted (never fatal); an empty diff with both bases
    present is a legitimate empty surface (verdict `little-to-review`), while a missing
    base produces `unavailable` with a reason (B3 loud-fail is decided by the caller on
    that verdict, not by an exception). `changed_files` maps face → path list so the
    report can say which face owns which file."""
    from inspection_inspect import parse_name_status
    rows, meta = parse_name_status(name_status_text)
    faces = {"test": 0, "simplify": 0, "other": 0}
    changed_files: Dict[str, List[str]] = {"test": [], "simplify": [], "other": []}
    scenarios = 0
    for row in rows:
        path = row.split("\t", 1)[1] if "\t" in row else row
        face = split_face(path)
        faces[face] = faces.get(face, 0) + 1
        changed_files[face].append(path)
        if face == "test" and Path(path).name.startswith(SCENARIO_PREFIX):
            scenarios += 1
    surface: Dict[str, Any] = {
        "schema": SURFACE_SCHEMA,
        "prev_base": str(prev_base or ""),
        "this_base": str(this_base or ""),
        "rows": rows,
        "changed_files": changed_files,
        "faces": faces,
        "new_scenarios": scenarios,
        "malformed_lines": int(meta.get("diff_malformed_lines") or 0),
    }
    surface["verdict"] = coverage_verdict(surface, thresholds)
    surface["coverage"] = coverage_meta(len(rows), scenarios, thresholds)
    return surface


def surface_unavailable(reason: str,
                        prev_base: str = "", this_base: str = "") -> Dict[str, Any]:
    """The `unavailable` surface (B3): the diff could not be made. The workflow must
    block the period on this verdict — it is a defect, not a finding-free result."""
    return {
        "schema": SURFACE_SCHEMA,
        "prev_base": str(prev_base or ""), "this_base": str(this_base or ""),
        "rows": [], "faces": {"test": 0, "simplify": 0, "other": 0},
        "new_scenarios": 0, "malformed_lines": 0,
        "verdict": "unavailable", "reason": str(reason or "")[:400],
        "coverage": coverage_meta(0, 0, 0),
    }


def normalize_thresholds(raw: Any) -> Dict[str, int]:
    """Threshold values → validated ints with engine defaults for missing keys.
    Declaration-side parsing already fail-closes on garbage; this side additionally
    tolerates None/{} (all defaults) and clamps negatives to the default."""
    out = {"min_surface_files": DEFAULT_MIN_SURFACE_FILES,
           "min_new_scenarios": DEFAULT_MIN_NEW_SCENARIOS}
    if isinstance(raw, dict):
        for key in list(out):
            try:
                val = int(str(raw.get(key, "")).strip() or out[key])
                if val >= 0:
                    out[key] = val
            except (TypeError, ValueError):
                pass  # declaration parser rejects garbage; here keep the default
    return out


def coverage_meta(files: int, scenarios: int,
                  thresholds: Any = None) -> Dict[str, Any]:
    """Front-page coverage block: the counts AND the named thresholds (review
    condition 3 — "little" is only judgeable against a stated bar)."""
    th = normalize_thresholds(thresholds)
    return {"surface_files": int(files), "new_scenarios": int(scenarios),
            "thresholds": th}


def coverage_verdict(surface: Any, thresholds: Any = None) -> str:
    """B3 verdict (pure): "unavailable" | "little-to-review" | "normal". Rule: the
    surface is `little-to-review` when the changed file count is under the stated
    threshold AND there are no new scenarios at all — either signal alone keeps
    `normal` so a legitimately code-light but test-rich period is not dimmed.
    `unavailable` surfaces (missing/uncomputable base) pass through unchanged: the
    caller must fail the period loudly on them. Use coverage_meta() for the counts +
    the named thresholds that must accompany the verdict on the front page."""
    if not isinstance(surface, dict) or surface.get("verdict") == "unavailable":
        return "unavailable"
    th = normalize_thresholds(thresholds)
    files = sum(int(v) for v in (surface.get("faces") or {}).values()) \
        if surface.get("faces") else len(surface.get("rows") or [])
    scenarios = int(surface.get("new_scenarios") or 0)
    return ("little-to-review"
            if files < th["min_surface_files"] and scenarios < th["min_new_scenarios"]
            else "normal")


# ---------------------------------------------------------------------------
# Shared surface file (B1): one computation per period on disk, keyed by base shas.
# ---------------------------------------------------------------------------

def surface_file_name(period: str) -> str:
    return "surface-%s.json" % str(period or "")


def load_shared_surface(ledger_dir: Any, period: str,
                        prev_base: str, this_base: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Read the period's shared surface file (IO; the ONLY non-pure helper here).

    Three states, all named (review condition 1):
      - file present AND both base shas match → (surface, "shared")
      - file present but bases differ (stale) → (None, named mismatch note) — the
        consumer computes its own from the same pure functions; never trust a surface
        computed between different points.
      - file absent → (None, "absent") — the consumer computes its own and (the
        activity shell) writes it; absence is NOT a blocked period (no liveness
        dependency between two independently scheduled faces).
    Any read/parse failure → (None, named note); never raises."""
    p = Path(str(ledger_dir or "")) / surface_file_name(period) if str(ledger_dir or "") else None
    if p is None:
        return None, "no ledger dir given — computing locally"
    if not p.is_file():
        return None, "shared surface file absent (%s) — computing locally" % p.name
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, "shared surface file unreadable (%s: %s) — computing locally" % (
            type(e).__name__, e)
    if not isinstance(data, dict) or data.get("schema") != SURFACE_SCHEMA:
        return None, "shared surface file has a foreign schema — computing locally"
    if str(data.get("prev_base") or "") != str(prev_base or "") or \
       str(data.get("this_base") or "") != str(this_base or ""):
        return None, ("shared surface file is for other base points (%s..%s, ours %s..%s) "
                      "— computing locally" % (str(data.get("prev_base"))[:7],
                                               str(data.get("this_base"))[:7],
                                               str(prev_base)[:7], str(this_base)[:7]))
    return data, "shared"


# ---------------------------------------------------------------------------
# B4 cross-face dedupe: identity = minted content-hash id (design §5.1: rule+object,
# never wording). mint_finding_id normalizes whitespace and sorts evidence, so the id
# is stable under wording drift; distinct findings sharing a subject keep distinct ids
# (why + evidence are part of the hash).
# ---------------------------------------------------------------------------

def apply_cross_face_dedupe(findings: Any, owner_doc: Any,
                            owner_instance: str, self_instance: str
                            ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Suppress findings the owner face already reported this period (pure).

    A suppressed finding KEEPS its place in the list (visible, never silently dropped)
    with verified="suppressed" (the existing single-value contract) plus a
    `cross_face_dedup` block naming `into` (owner instance) and `faces` (both
    reporters). Distinct findings that merely share a subject are untouched: their
    content-hash ids differ. Owner doc absent/malformed → fail-open with a named note
    (the non-owner keeps its findings; the gap is visible in the returned meta)."""
    if not isinstance(findings, list):
        return [], {"cross_face_note": "findings input malformed — nothing deduped"}
    meta: Dict[str, Any] = {}
    owner_ids: Optional[set] = None
    if isinstance(owner_doc, dict) and isinstance(owner_doc.get("findings"), list):
        owner_ids = {str(f.get("id")) for f in owner_doc["findings"]
                     if isinstance(f, dict) and f.get("id")}
    if owner_ids is None:
        meta["cross_face_note"] = (
            "owner period doc for %s unreadable/absent — cross-face dedupe not applied, "
            "findings kept (fail-open, named)" % str(owner_instance or "?"))
        return findings, meta
    deduped = 0
    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "")
        if fid and fid in owner_ids:
            f["verified"] = "suppressed"
            f["reported_by"] = [str(owner_instance), str(self_instance)]
            f["cross_face_dedup"] = {"into": str(owner_instance),
                                     "faces": [str(owner_instance), str(self_instance)]}
            deduped += 1
    meta["cross_face_deduped"] = deduped
    return findings, meta
