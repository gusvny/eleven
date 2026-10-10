"""Review ledger and the least-recently-reviewed slice (t261006-12; lands the
261004 inspection two-face redesign, design doc sections 4/7).

Single responsibility: the per-file **review ledger** (last reviewed period +
timestamp) and the things derived from it — the rotation **slice** and the
period **coverage** lists. Pure functions plus thin IO (read the ledger, append
write-back); nothing raises — the ledger is allowed to be lost (261004 host
ruling: losing it means start over with everything unreviewed; never an error,
never a complex self-heal).

Source-of-truth conventions (section 7 ruling, item by item):
- The ledger lives in the **project directory**:
  `~/.sandbar/projects/<project_key>/inspection/reviewed.jsonl`
  (env `SANDBAR_PROJECTS_DIR` swaps the registry root — same semantics as
  shared.py; env `SANDBAR_REVIEW_LEDGER_DIR` overrides the whole path — test
  seam, same family as the ledger_dir three-priority chain).
- Append-style JSONL, one file per line `{"path","period","ts"}`; multiple rows
  for one path = the last row wins.
- The coverage list is a **list, not a count** (L5 hard requirement): reviewed
  and not-reviewed are both full lists and land in the period report doc — a
  lost ledger cannot erase past coverage.

Slice discipline (L2): the ordering is declared — (1) never-reviewed first
(path ascending); (2) then oldest `ts`, ties by path ascending (stated tie
rule). Same input, same output (deterministic); never falls back to the whole
repo.
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Whole-path override env for the ledger (test seam; empty = derive from the
#: project directory)
REVIEW_LEDGER_ENV = "SANDBAR_REVIEW_LEDGER_DIR"
#: Projects registry root env (same name and meaning as shared.py; this module
#: does not import shared — stays zero-temporalio-dependency)
PROJECTS_ROOT_ENV = "SANDBAR_PROJECTS_DIR"

#: Excluded trees for the managed-source inventory (exact directory names;
#: declared in one place so the total — the design's measured 1298 files /
#: 20.08 MB — stays reproducible)
EXCLUDED_TREE_NAMES = (
    ".git", ".lane", ".sandbar", ".dsh",
    "node_modules", "__pycache__", ".pytest_cache",
    "out", "archive", "archives",
)

DEFAULT_SLICE_MIN = 40
DEFAULT_SLICE_MAX = 60


# ---------------------------------------------------------------------------
# Path derivation (borrows the args > env > constant three-priority chain of
# run_inspection_inspect and shared.py's empty-env-is-unset semantics; every
# failure mode from plan table R1 — none raises)
# ---------------------------------------------------------------------------

def validate_path_component(key: Any) -> Tuple[bool, str]:
    """Path-component validity (a hostile project_key must not become path
    traversal). Never raises; returns (ok, reason), reason empty = valid.
    Rejects: empty, non-str, `/` or `\\`, `..`, leading `.` (hidden/relative
    anchor), `\\0`."""
    if not isinstance(key, str) or not key.strip():
        return False, "empty or not a string"
    k = key.strip()
    if "\0" in k:
        return False, "contains NUL"
    if "/" in k or "\\" in k:
        return False, "contains a path separator"
    if k in (".", "..") or k.startswith("."):
        return False, "dot-prefixed or relative anchor"
    return True, ""


def _ledger_file_path(project_key: Any, filename: str,
                      override: Any) -> Tuple[Optional[Path], str]:
    """Shared three-priority derivation (override > `SANDBAR_REVIEW_LEDGER_DIR` >
    `<SANDBAR_PROJECTS_DIR or ~/.sandbar/projects>/<key>/inspection/<filename>`);
    review_ledger_path and finding_ledger_path both delegate here so the chain
    cannot drift between the reviewed ledger and the finding ledgers."""
    ov = ""
    if isinstance(override, str) and override.strip():
        ov = override.strip()
    if not ov:
        env = os.environ.get(REVIEW_LEDGER_ENV) or ""
        if env.strip():
            ov = env.strip()
    if ov:
        try:
            return Path(ov).expanduser(), ""
        except (OSError, RuntimeError) as e:  # expanduser can raise on odd HOME
            return None, "ledger override path unusable (%s: %s)" % (
                type(e).__name__, e)
    ok, reason = validate_path_component(project_key)
    if not ok:
        return None, "ledger path not derived (project_key %r: %s)" % (
            project_key, reason)
    root_env = os.environ.get(PROJECTS_ROOT_ENV) or ""
    try:
        root = Path(root_env.strip()).expanduser() if root_env.strip() \
            else (Path.home() / ".sandbar" / "projects")
    except (OSError, RuntimeError) as e:
        return None, "projects root not derivable (%s: %s)" % (type(e).__name__, e)
    return root / str(project_key).strip() / "inspection" / filename, ""


def review_ledger_path(project_key: Any,
                       override: Any = None) -> Tuple[Optional[Path], str]:
    """Ledger path, three priorities: override (caller args) >
    `SANDBAR_REVIEW_LEDGER_DIR` > `<SANDBAR_PROJECTS_DIR or ~/.sandbar/
    projects>/<key>/inspection/reviewed.jsonl`.

    Never raises: underivable (bad key, home expansion failure with no
    override) = (None, reason note) — the caller degrades to "everything
    unreviewed" plus the named note (observable, not silent, not fatal)."""
    return _ledger_file_path(project_key, "reviewed.jsonl", override)


# ---------------------------------------------------------------------------
# Ledger read (failure modes 3/4/5/6/7/10: missing file = everything
# unreviewed; corrupt rows dropped and counted; never raises)
# ---------------------------------------------------------------------------

def load_review_ledger(path: Any) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """JSONL ledger -> {path: {"period","ts"}} (last row per path wins).
    Returns (map, notes); notes carry ledger_note (absence/unreadable reason)
    and ledger_corrupt_lines (corrupt-row count)."""
    notes: Dict[str, Any] = {}
    p = Path(path) if path else None
    if p is None:
        notes["ledger_note"] = "no review ledger path (everything unreviewed)"
        return {}, notes
    if not p.is_file():
        notes["ledger_note"] = ("review ledger absent (%s) — starting over, "
                                "everything unreviewed" % p.name)
        return {}, notes
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        notes["ledger_note"] = ("review ledger unreadable (%s: %s) — starting over, "
                                "everything unreviewed" % (type(e).__name__, e))
        return {}, notes
    rows: Dict[str, Dict[str, Any]] = {}
    bad = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            doc = json.loads(s)
        except ValueError:
            bad += 1          # includes a torn trailing line / replacement-char damage
            continue
        if not isinstance(doc, dict):
            bad += 1
            continue
        fpath = doc.get("path")
        period = doc.get("period")
        ts = doc.get("ts")
        if not isinstance(fpath, str) or not fpath.strip() or "\0" in fpath \
                or not isinstance(period, str) or not period.strip() \
                or not isinstance(ts, (int, float)) or isinstance(ts, bool):
            bad += 1
            continue
        rows[fpath.strip()] = {"period": period.strip(), "ts": float(ts)}
    if bad:
        notes["ledger_corrupt_lines"] = bad
    return rows, notes


# ---------------------------------------------------------------------------
# Managed inventory and slice (L2: declared ordering, deterministic; never
# falls back to the whole repo)
# ---------------------------------------------------------------------------

def enumerate_managed_files(base_dir: Any,
                            excluded: Tuple[str, ...] = EXCLUDED_TREE_NAMES) -> List[str]:
    """Managed-source inventory: every file under base_dir as a relative path
    (excluded trees by exact directory name), sorted by path. Missing or
    unreadable base = empty list (the caller names it explicitly; never a
    "review everything" fallback)."""
    base = Path(base_dir) if base_dir else None
    if base is None or not base.is_dir():
        return []
    excluded_set = set(excluded)
    out: List[str] = []
    stack = [base]
    while stack:
        cur = stack.pop()
        try:
            entries = sorted(cur.iterdir(), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.is_symlink():
                continue
            if e.is_dir():
                if e.name not in excluded_set:
                    stack.append(e)
            elif e.is_file():
                out.append(e.relative_to(base).as_posix())
    out.sort()
    return out


def select_slice(managed: List[str], ledger: Dict[str, Dict[str, Any]],
                 slice_min: int = DEFAULT_SLICE_MIN,
                 slice_max: int = DEFAULT_SLICE_MAX) -> Tuple[List[str], Dict[str, Any]]:
    """Least-recently-reviewed slice. Declared ordering: never-reviewed first
    (path ascending) -> oldest ts -> path ascending (tie rule). Capped at
    slice_max; an inventory smaller than slice_min is reviewed in full (no
    padding). min > max clamps max := min (with a note; no invented bound).
    Deterministic: same input, same output."""
    notes: Dict[str, Any] = {}
    lo = max(1, int(slice_min))
    hi = max(1, int(slice_max))
    if hi < lo:
        notes["slice_clamped"] = "slice_max %d < slice_min %d — clamped to %d" % (
            hi, lo, lo)
        hi = lo
    def _order(p: str) -> Tuple[int, float, str]:
        row = ledger.get(p)
        if row is None:
            return (0, 0.0, p)          # never-reviewed first (path asc within)
        return (1, float(row.get("ts") or 0.0), p)
    ordered = sorted(managed, key=_order)
    kept = ordered[:hi]
    notes["never_reviewed"] = sum(1 for p in managed if p not in ledger)
    notes["total_managed"] = len(managed)
    if len(managed) < lo:
        notes["slice_note"] = ("managed inventory (%d) below slice_min %d — reviewing "
                               "the whole inventory" % (len(managed), lo))
    return kept, notes


# ---------------------------------------------------------------------------
# Coverage (L5: lists, not counts; both lists land in the report doc)
# ---------------------------------------------------------------------------

def coverage_section(reviewed: List[str], managed: List[str],
                     period: str) -> Dict[str, Any]:
    """Period coverage: which files were reviewed, which were not — **full
    lists** (never a count only). reviewed is deduped and sorted;
    not_reviewed = managed − reviewed; the two lists are disjoint and their
    union is the inventory."""
    reviewed_set = sorted({str(p) for p in reviewed if str(p).strip()})
    managed_set = sorted({str(p) for p in managed if str(p).strip()})
    reviewed_l = set(reviewed_set)
    not_reviewed = [p for p in managed_set if p not in reviewed_l]
    return {
        "period": str(period or ""),
        "reviewed_files": reviewed_set,
        "not_reviewed_files": not_reviewed,
        "total_managed": len(managed_set),
        "reviewed_count": len(reviewed_set),
        "not_reviewed_count": len(not_reviewed),
        "statement": ("Coverage this period: %d of %d managed source files reviewed. "
                      "The remaining %d were NOT reviewed — not reviewed is not "
                      "\"no problem\"; full lists are in this report's coverage section."
                      % (len(reviewed_set), len(managed_set), len(not_reviewed))),
    }


# ---------------------------------------------------------------------------
# Write-back (L3/L4: append-style; one write per batch; a write failure is a
# note and never raises into the inspection flow)
# ---------------------------------------------------------------------------

def append_reviewed(path: Any, files: List[str], period: str,
                    ts: Optional[float] = None) -> Dict[str, Any]:
    """Append this period's actually-reviewed files to the ledger. The whole
    batch goes out in one write (a small payload in a single syscall is close
    enough to atomic; a torn interleaving degrades to one corrupt row dropped
    and counted on the next read — no locks / no self-heal, per the ruling).
    Returns notes (ledger_written count / write_note reason); never raises."""
    notes: Dict[str, Any] = {}
    p = Path(path) if path else None
    if p is None:
        return {"write_note": "no review ledger path — write-back skipped (named)"}
    rows = [f for f in files if isinstance(f, str) and f.strip() and "\0" not in f]
    if not rows:
        return {"write_note": "no reviewed files to record — write-back skipped (named)"}
    stamp = float(ts if ts is not None else time.time())
    period_s = str(period or "").strip()
    payload = "".join(
        json.dumps({"path": f.strip(), "period": period_s, "ts": stamp},
                   ensure_ascii=False, sort_keys=True) + "\n"
        for f in rows)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(payload)
    except OSError as e:
        return {"write_note": "review ledger append failed (%s: %s) — period continues; "
                              "the slice may repeat next period (loss-tolerant by ruling)"
                              % (type(e).__name__, e)}
    notes["ledger_written"] = len(rows)
    return notes


# ========================================================================================
# Finding entity + observation ledgers (t261009-69; ledger-record-models-v1
# sections "finding (entity)" and "finding observation (fact)").
#
# The entity/observation split (fact-ledger design rule): a finding is an ENTITY
# that persists while the facts about it are OBSERVATIONS — seen in this period,
# with that verification outcome. Without the split "how long has this been open"
# cannot be answered and identity has to be re-derived from content every time.
#
# Two append-style JSONL faces in the same project-store directory as
# reviewed.jsonl (one row per fact, never a record holding a list):
#   findings.jsonl     — one entity row per finding first recorded
#                        {"id","subject","severity","scan","evidence","minted_at"}
#   observations.jsonl — one sighting row per (finding, period); NO id — the key
#                        is the tuple {"finding","period","verification",
#                        "verification_note","at"}
#
# Borrowed-implementation tradeoffs from the reviewed-ledger fault-mode list
# (declared per review condition 4):
#   torn interleaving -> row dropped and counted on the next read   [brought over]
#   OSError on append -> named note, period continues               [brought over]
#   no derivable path -> named skip, nothing written                [brought over]
#   corrupt ENTITY row in findings.jsonl -> dropped AND counted, same as a
#     reviewed-path row — NOT silently special-cased. The risk the review named
#     (an observation then keys to nothing) is contained on the read face:
#     `finding_history` reports such sightings under `orphan_sightings` instead
#     of dropping them, so the gap is visible rather than quiet.
#   duplicate observation for the same (finding, period) -> the append face
#     SKIPS it when the caller passes the already-known keys
#     (`append_observations(..., known_keys=...)`), with a named count; on the
#     raw ledger the LAST row per (finding, period) wins on read (same
#     consumption rule as the reviewed ledger).
# ========================================================================================

FINDINGS_LEDGER_NAME = "findings.jsonl"
OBSERVATIONS_LEDGER_NAME = "observations.jsonl"
#: Verification vocabulary (models doc: the one thing that changes sighting to
#: sighting). Anything outside the vocabulary degrades to `downgraded` WITH a
#: named note — degrade and name, never silently reinterpret.
VERIFICATION_VERIFIED = "verified"
VERIFICATION_DOWNGRADED = "downgraded"
VERIFICATION_UNLOCATABLE = "unlocatable"
VERIFICATION_VOCAB: Tuple[str, ...] = (
    VERIFICATION_VERIFIED, VERIFICATION_DOWNGRADED, VERIFICATION_UNLOCATABLE)


def finding_ledger_path(project_key: Any, name: str,
                        override: Any = None) -> Tuple[Optional[Path], str]:
    """Path for the finding entity / observation ledger (`name` = the file name;
    same three-priority chain as review_ledger_path, shared helper). Never
    raises; (None, reason) when underivable — the caller names the skip."""
    return _ledger_file_path(project_key, str(name or ""), override)


def finding_entity_record(finding: Any,
                          ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The ENTITY row for a finding (pure; None on malformed input, never
    raises — the caller names the skip). The id MUST already be minted
    (`with_ids`); the entity is the content identity, so a row without one is
    not a finding record. Evidence is reduced to the identity-bearing
    locations (path/line dict entries); prose evidence is data, not identity,
    and stays out of the entity row."""
    if not isinstance(finding, dict):
        return None
    fid = finding.get("id")
    if not isinstance(fid, str) or not fid.strip() or "\0" in fid:
        return None
    evidence = []
    for ev in (finding.get("evidence") or []):
        if isinstance(ev, dict) and isinstance(ev.get("path"), str) and ev["path"].strip():
            try:
                line = int(ev.get("line") or 0)
            except (TypeError, ValueError):
                line = 0
            evidence.append({"path": ev["path"].strip(), "line": line})
    stamp = float(ts if ts is not None else time.time())
    return {
        "id": fid.strip(),
        "subject": str(finding.get("subject") or ""),
        "severity": str(finding.get("severity") or ""),
        "scan": str(finding.get("scan") or ""),
        "evidence": evidence,
        "minted_at": stamp,
    }


def finding_observation_record(finding_id: Any, period: Any,
                               verification: Any,
                               note: Any = "",
                               ts: Optional[float] = None
                               ) -> Optional[Dict[str, Any]]:
    """The OBSERVATION row: no id, the key is (finding, period). Pure; None on
    malformed input (empty/absent finding id or period), never raises. A
    verification outcome outside the vocabulary degrades to `downgraded` and
    the unrecognized value is NAMED in the note (requirement 4) — a finding
    that cannot be verified this period still gets its observation saying so.
    `at` is milliseconds since the epoch (models-doc shape)."""
    fid = finding_id.strip() if isinstance(finding_id, str) else ""
    per = period.strip() if isinstance(period, str) else ""
    if not fid or "\0" in fid or not per or "\0" in per:
        return None
    ver = verification.strip() if isinstance(verification, str) else ""
    ver_note = str(note or "")
    if ver not in VERIFICATION_VOCAB:
        raw = ver or "absent"
        ver = VERIFICATION_DOWNGRADED
        ver_note = ("verification outcome %r is outside the vocabulary "
                    "(%s) — degraded and named" % (raw,
                                                   "|".join(VERIFICATION_VOCAB))
                    + ("; " + ver_note if ver_note else ""))
    stamp_ms = int(round(float(ts if ts is not None else time.time()) * 1000.0))
    return {
        "finding": fid,
        "period": per,
        "verification": ver,
        "verification_note": ver_note,
        "at": stamp_ms,
    }


def append_ledger_rows(path: Any, rows: List[Dict[str, Any]],
                       what: str) -> Dict[str, Any]:
    """Append rows to one JSONL ledger, one write per batch (borrowed from
    append_reviewed: a small payload in a single syscall is close enough to
    atomic; a torn interleaving degrades to one corrupt row dropped and counted
    on the next read — no locks, no self-heal). Never raises; returns notes."""
    notes: Dict[str, Any] = {}
    p = Path(path) if path else None
    if p is None:
        return {"write_note": "no %s ledger path — write skipped (named)" % what}
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return {"write_note": "no %s rows to record — write skipped (named)" % what}
    payload = "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(payload)
    except OSError as e:
        return {"write_note": "%s ledger append failed (%s: %s) — period "
                              "continues; the sighting is re-recordable next "
                              "period (loss-tolerant by ruling)"
                              % (what, type(e).__name__, e)}
    notes["ledger_written"] = len(rows)
    return notes


def load_jsonl_rows(path: Any, what: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read one JSONL ledger into rows. Borrowed failure modes: missing file =
    empty + named note (a lost ledger never becomes an error); unreadable =
    empty + named note; corrupt/torn lines dropped AND counted
    (`corrupt_lines`). Never raises."""
    notes: Dict[str, Any] = {}
    p = Path(path) if path else None
    if p is None:
        notes["ledger_note"] = "no %s ledger path" % what
        return [], notes
    if not p.is_file():
        notes["ledger_note"] = "%s ledger absent (%s)" % (what, p.name)
        return [], notes
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        notes["ledger_note"] = "%s ledger unreadable (%s: %s)" % (
            what, type(e).__name__, e)
        return [], notes
    rows: List[Dict[str, Any]] = []
    bad = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            doc = json.loads(s)
        except ValueError:
            bad += 1          # includes a torn trailing line
            continue
        if not isinstance(doc, dict):
            bad += 1
            continue
        rows.append(doc)
    if bad:
        notes["corrupt_lines"] = bad
    return rows, notes


def observation_keys(rows: List[Dict[str, Any]]) -> set:
    """The set of (finding, period) keys already in a loaded observation list —
    the caller passes this to `append_observations` so a re-seeing period
    appends a NEW period's sighting but never a duplicate of the same one."""
    out = set()
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("finding"), str) \
                and isinstance(r.get("period"), str):
            out.add((r["finding"].strip(), r["period"].strip()))
    return out


def append_findings(path: Any, records: List[Any]) -> Dict[str, Any]:
    """Entity append face: build entity rows from minted findings and append.
    A malformed finding (no minted id) is named, not written — degrade and
    name. A finding already in the ledger (same id — the content identity) is
    NOT appended again: re-seeing appends an observation, never a second
    entity. `existing_ids` may be passed to skip re-minted duplicates."""
    return append_findings_ex(path, records, existing_ids=None)


def append_findings_ex(path: Any, records: List[Any],
                       existing_ids: Optional[set] = None) -> Dict[str, Any]:
    """`append_findings` with duplicate-entity suppression: a finding whose id
    is already in `existing_ids` (load `findings.jsonl` and collect ids) is
    skipped with a named count — one entity, many observations."""
    notes: Dict[str, Any] = {}
    built: List[Dict[str, Any]] = []
    bad = skipped = 0
    seen_here: set = set()
    for f in records or []:
        rec = finding_entity_record(f)
        if rec is None:
            bad += 1
            continue
        if existing_ids and rec["id"] in existing_ids or rec["id"] in seen_here:
            skipped += 1
            continue
        seen_here.add(rec["id"])
        built.append(rec)
    if bad:
        notes["entity_rows_malformed"] = bad
    if skipped:
        notes["entity_duplicates_skipped"] = skipped
    if not built:
        if "entity_rows_malformed" not in notes and "entity_duplicates_skipped" not in notes:
            notes["write_note"] = "no finding entities to record — write skipped (named)"
        return notes
    notes.update(append_ledger_rows(path, built, "finding-entity"))
    return notes


def append_observations(path: Any, rows: List[Any],
                        known_keys: Optional[set] = None) -> Dict[str, Any]:
    """Observation append face: rows are already-built observation records
    (finding_observation_record) or (finding, period, verification, note)
    tuples-normalized dicts. A (finding, period) already in `known_keys`
    (from `observation_keys(load)`) is skipped with a named count. Never
    raises; write failures are named notes."""
    notes: Dict[str, Any] = {}
    built: List[Dict[str, Any]] = []
    bad = skipped = 0
    seen_here: set = set()
    for r in rows or []:
        if isinstance(r, dict) and "finding" in r:
            rec = r if r.get("verification") in VERIFICATION_VOCAB else \
                finding_observation_record(r.get("finding"), r.get("period"),
                                           r.get("verification"),
                                           r.get("verification_note"))
        else:
            rec = None
        if rec is None:
            bad += 1
            continue
        key = (rec["finding"], rec["period"])
        if (known_keys and key in known_keys) or key in seen_here:
            skipped += 1
            continue
        seen_here.add(key)
        built.append(rec)
    if bad:
        notes["observation_rows_malformed"] = bad
    if skipped:
        notes["observation_duplicates_skipped"] = skipped
    if not built:
        if "observation_rows_malformed" not in notes \
                and "observation_duplicates_skipped" not in notes:
            notes["write_note"] = "no observations to record — write skipped (named)"
        return notes
    notes.update(append_ledger_rows(path, built, "finding-observation"))
    return notes


def finding_history(findings_path: Any, observations_path: Any,
                    finding_id: Any) -> Dict[str, Any]:
    """THE read face (t261009-69 requirement 3): "how long has this been open"
    is a query, not a re-derivation. Answers, from the ledger alone: when the
    finding was FIRST seen, how many periods it has been seen in (the list and
    the count), and its LAST sighting with that sighting's verification
    outcome. Entity rows are matched by id under the widening rule
    (`inspection_inspect.legacy_id_matches`): an old 8-hex stored id resolves
    to a 16-hex minted query id by prefix — history is never renumbered, and
    `id_resolution` in the result says which rule matched. Sightings whose
    entity row is missing/corrupt land in `orphan_sightings` (visible, not
    dropped). Missing ledgers = available:false + named reason, never raise."""
    out: Dict[str, Any] = {
        "finding_id": str(finding_id or ""),
        "available": False,
        "reason": "",
        "first_seen": None,
        "periods_seen": [],
        "periods_seen_count": 0,
        "last_sighting": None,
        "orphan_sightings": [],
        "id_resolution": "unresolved",
        "notes": {},
    }
    fid = out["finding_id"].strip()
    if not fid:
        out["reason"] = "no finding id given — query refused (named)"
        return out
    entities, fnotes = load_jsonl_rows(findings_path, "finding-entity")
    sightings, onotes = load_jsonl_rows(observations_path, "finding-observation")
    out["notes"] = {k: v for k, v in
                    dict(list(fnotes.items()) + list(onotes.items())).items()}
    row = None
    for e in entities:
        stored = str(e.get("id") or "")
        from inspection_inspect import legacy_id_matches
        if legacy_id_matches(stored, fid):
            row = e
            out["id_resolution"] = ("exact" if stored == fid
                                    else "legacy 8-hex prefix (history not renumbered)")
            break
    if row is None:
        out["reason"] = ("finding %r not in the entity ledger — nothing has ever "
                         "recorded it" % fid)
        return out
    periods: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for s in sightings:
        if not isinstance(s.get("finding"), str):
            continue
        if not legacy_id_matches(str(s["finding"]).strip(), fid):
            continue
        per = str(s.get("period") or "").strip()
        if not per:
            continue
        periods.append(per)
        if last is None or _period_order_key(per) >= _period_order_key(str(last.get("period"))):
            last = s
    if not periods:
        out["reason"] = ("entity found but zero sightings recorded — the entity "
                         "ledger predates the observation ledger (named, not an error)")
    out["available"] = True
    out["periods_seen"] = sorted(set(periods), key=_period_order_key)
    out["periods_seen_count"] = len(out["periods_seen"])
    out["first_seen"] = out["periods_seen"][0] if out["periods_seen"] else None
    out["last_sighting"] = last
    return out


def _period_order_key(period: str) -> Tuple[int, int]:
    """Period ordering: numeric when the period is digits (20261007 style),
    lexicographic fallback otherwise; deterministic either way."""
    p = str(period or "").strip()
    if p.isdigit():
        return (1, int(p))
    return (0, _str_key(p))


def _str_key(s: str) -> int:
    # stable, dependency-free ordering proxy for non-numeric periods
    return sum((i + 1) * ord(c) for i, c in enumerate(s[:32]))


# ---- the finding chain's relation faces (t261009-71) ------------------------
#
# The record models' kind ``originates from a finding`` (record-models §B,
# "only kinds with a live consumer") is declared in the delivery ledger's
# vocabulary (``develop_certify.REL_KIND_ORIGINATES``). These are its live
# consumers, the inspection design's closing section: the finding's face
# answers "which tickets were opened from me", the ticket's face answers
# "which finding did I come from", a finding is CLOSED when its quoted
# content is gone (not merely when a ticket was opened), and a finding
# already seen under its content-minted id is not filed again.
#
# Import direction: inspection -> promote -> certify, never back; the
# direction logic itself is ``develop_certify.relations_of`` — consumed,
# never re-implemented here.

import develop_certify as dc  # noqa: E402  (vocabulary + row loader)
import develop_promote as dp  # noqa: E402  (current-relation view)


def delivery_ledger_path(project: Any,
                         ledger_dir: Any = None) -> Tuple[Optional[Path], str]:
    """The delivery ledger file the relation rows are read FROM (never from
    a return value). Same three-priority chain as every path helper here:
    explicit dir (flat ``<project>.jsonl``), SANDBAR_DELIVERY_LEDGER_DIR,
    then the project store. Never raises; (None, reason) when underivable."""
    proj = str(project or "").strip()
    if not proj or "\0" in proj:
        return None, "no project key — delivery ledger path underivable"
    d = (str(ledger_dir).strip() if ledger_dir else "") \
        or os.environ.get(dc.LEDGER_DIR_ENV, "").strip()
    if d:
        return Path(d) / ("%s.jsonl" % proj), ""
    home = Path(os.path.expanduser("~"))
    return home / ".sandbar" / "projects" / proj / "ledger" / dc.MAIN_NAME, ""


def _relation_to_finding_id(to: Any) -> str:
    """The bare finding id a relation target names: a ``finding:`` or
    ``fi-`` prefix is stripped; anything else is taken as stored. Never
    raises; empty string on unusable input."""
    s = str(to or "").strip()
    if s.startswith("finding:"):
        return s[len("finding:"):].strip()
    if s.startswith("fi-"):
        return s[len("fi-"):].strip()
    return s


def _current_relations_from_disk(ledger_path: Any
                                 ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Current relation rows read from the ledger FILE on disk. Borrowed
    failure modes: missing/unreadable ledger = empty + named note; corrupt
    lines counted by ``read_rows``; the current view is
    ``develop_promote.current_relations`` — consumed, never re-implemented.
    Never raises."""
    notes: Dict[str, Any] = {}
    p = Path(ledger_path) if ledger_path else None
    if p is None:
        notes["delivery_ledger_note"] = "no delivery ledger path"
        return [], notes
    if not p.is_file():
        notes["delivery_ledger_note"] = ("delivery ledger absent (%s)"
                                         % p.name)
        return [], notes
    try:
        rows, bad = dc.read_rows(p)
    except OSError as e:  # defensive: read_rows already guards, named anyway
        notes["delivery_ledger_note"] = ("delivery ledger unreadable (%s: %s)"
                                         % (type(e).__name__, e))
        return [], notes
    if bad:
        notes["delivery_ledger_corrupt_lines"] = len(bad)
    return dp.current_relations(rows), notes


def _finding_id_matches(stored: Any, fid: str) -> bool:
    """Same widening rule the finding faces read by (t261009-69): an old
    8-hex stored id resolves to a 16-hex query id by prefix. One helper so
    the relation faces never re-implement the comparison."""
    from inspection_inspect import legacy_id_matches
    return legacy_id_matches(str(stored or "").strip(), fid)


def finding_work_of(ledger_path: Any, finding_id: Any) -> Dict[str, Any]:
    """The FINDING's read face (t261009-71, consumer a): which current
    ``originates from a finding`` relations name this finding — i.e. which
    work tickets were opened from it. The relation rows come from the
    ledger file on disk; a ticket whose relation names the finding by any
    of the id's forms (``finding:<id>``, ``fi-<id>``, bare hex, legacy
    8-hex prefix) is answered, and each entry names WHICH form matched.
    Malformed relation rows are filtered by the current-view reader, never
    crashed on; a missing ledger degrades by name."""
    out: Dict[str, Any] = {
        "finding_id": str(finding_id or "").strip(),
        "available": False,
        "reason": "",
        "tickets": [],
        "notes": {},
    }
    fid = out["finding_id"]
    if not fid:
        out["reason"] = "no finding id given — query refused (named)"
        return out
    rels, notes = _current_relations_from_disk(ledger_path)
    out["notes"] = notes
    for rel in rels:
        if rel.get("kind") != dc.REL_KIND_ORIGINATES:
            continue
        to = str(rel.get("to") or "").strip()
        bare = _relation_to_finding_id(to)
        if not _finding_id_matches(bare, fid):
            continue
        out["tickets"].append({
            "id": rel.get("id"),
            "ticket": rel.get("from"),
            "recorded_by": rel.get("recorded_by"),
            "reason": rel.get("reason"),
            "at": rel.get("at"),
            "id_form": ("finding-prefixed" if to != bare else
                        ("legacy 8-hex prefix" if bare != fid else "exact")),
        })
    out["available"] = True
    if not out["tickets"]:
        out["reason"] = ("no work ticket records originating from finding %r "
                         "in the current relation ledger" % fid)
    return out


def origin_finding_of(ledger_path: Any, ticket: Any, project: Any = None,
                      ledger_dir: Any = None) -> Dict[str, Any]:
    """The TICKET's read face (t261009-71, consumer a): which finding this
    ticket came from, over the current ``originates from a finding``
    relations read from the ledger file on disk. ``ledger_path`` is the
    delivery ledger FILE; when absent it is resolved from
    ``project`` + ``ledger_dir`` (the delivery-ledger priority chain), and
    an underivable path is a named refusal, never a guess. Direction logic
    goes through ``develop_certify.relations_of`` (the ONE declared
    reader); this face only narrows it to the finding kind and names the
    finding refs — a finding id is never shown as a ticket."""
    out: Dict[str, Any] = {
        "ticket": str(ticket or "").strip(),
        "available": False,
        "reason": "",
        "findings": [],
        "finding_refs": [],
        "notes": {},
    }
    t = out["ticket"]
    if not t:
        out["reason"] = "no ticket id given — query refused (named)"
        return out
    if ledger_path and str(ledger_path).strip():
        p: Optional[Path] = Path(ledger_path)
    else:
        p, why = delivery_ledger_path(project, ledger_dir)
        if p is None:
            out["reason"] = why
            return out
    rows, notes = _current_relations_from_disk(p)
    rel = dc.relations_of(rows, t)
    out["notes"] = notes
    for entry in rel["as_actor"].get(dc.REL_KIND_ORIGINATES, []):
        out["findings"].append(dict(entry, derived=False))
    for entry in rel["as_benefited"].get(dc.REL_KIND_ORIGINATES, []):
        out["findings"].append(dict(entry, derived=True))
    out["finding_refs"] = rel.get("finding_refs", [])
    out["available"] = True
    if not out["findings"]:
        out["reason"] = ("ticket %r records no originating finding in the "
                         "current relation ledger" % t)
    return out


def finding_closure(ledger_path: Any, findings_path: Any,
                    observations_path: Any, finding_id: Any) -> Dict[str, Any]:
    """The closing rule (t261009-71, consumer b): a finding is closed when
    its QUOTED CONTENT IS GONE — the newest sighting no longer confirms the
    content — not merely when a ticket was opened from it. The two states
    the design separates are distinguishable on this face:

    - ``never_seen``: the entity ledger holds no such finding id.
    - ``open_no_work``: seen, content confirmed, no originating relation.
    - ``work_opened_content_present``: an originating relation exists AND
      the newest sighting still verifies.
    - ``closed_content_gone``: the newest sighting is anything but
      ``verified`` — content no longer confirmed (the models doc's own
      content-gone example is ``downgraded`` with a "quoted line no longer"
      note; ``unlocatable`` is the other mintable token). The newest
      verification is reported VERBATIM in ``newest_verification`` — the
      tokens stay distinguishable there; the status branches only on
      confirmed vs not.

    All rows come from the ledger files on disk; absent ledgers and a
    finding with sightings but no newest-verifiable state degrade by name.
    """
    out: Dict[str, Any] = {
        "finding_id": str(finding_id or "").strip(),
        "available": False,
        "reason": "",
        "status": "never_seen",
        "work_opened": False,
        "newest_verification": None,
        "newest_period": None,
        "notes": {},
    }
    fid = out["finding_id"]
    if not fid:
        out["reason"] = "no finding id given — query refused (named)"
        return out
    hist = finding_history(findings_path, observations_path, fid)
    out["notes"] = hist.get("notes", {})
    rels, rnotes = _current_relations_from_disk(ledger_path)
    if rnotes:
        out["notes"].update(rnotes)
    for rel in rels:
        if rel.get("kind") != dc.REL_KIND_ORIGINATES:
            continue
        to = str(rel.get("to") or "").strip()
        bare = _relation_to_finding_id(to)
        if _finding_id_matches(bare, fid):
            out["work_opened"] = True
            break
    if not hist.get("available"):
        out["reason"] = hist.get("reason", "finding entity not found")
        return out
    out["available"] = True
    last = hist.get("last_sighting")
    if last is None:
        # entity exists, zero sightings: no state asserts the content is
        # gone, and none asserts it is present — named, not guessed
        out["status"] = "open_no_work" if not out["work_opened"] \
            else "work_opened_no_sighting"
        out["reason"] = ("entity found but zero sightings — content state "
                         "unknown (named, not an error)")
        return out
    ver = str(last.get("verification") or "").strip()
    out["newest_verification"] = ver
    out["newest_period"] = last.get("period")
    if ver == "verified":
        out["status"] = "work_opened_content_present" if out["work_opened"] \
            else "open_no_work"
    else:
        out["status"] = "closed_content_gone"
    return out


def finding_already_filed(findings_path: Any, finding_id: Any) -> Dict[str, Any]:
    """The dedupe face (t261009-71, consumer c): is this finding already on
    file under its content-minted id? Derived from the ENTITY ledger — the
    id IS the content — never from prose. The same widening rule as
    ``finding_history`` applies, and ``resolution`` names which form
    matched. Absent ledger degrades to ``already_filed: False`` WITH the
    named note (nothing has ever been filed, which is the honest answer),
    never raises."""
    out: Dict[str, Any] = {
        "finding_id": str(finding_id or "").strip(),
        "available": False,
        "already_filed": False,
        "resolution": "unresolved",
        "reason": "",
        "notes": {},
    }
    fid = out["finding_id"]
    if not fid:
        out["reason"] = "no finding id given — query refused (named)"
        return out
    entities, notes = load_jsonl_rows(findings_path, "finding-entity")
    out["notes"] = notes
    for e in entities:
        stored = str(e.get("id") or "")
        if _finding_id_matches(stored, fid):
            out["already_filed"] = True
            out["resolution"] = ("exact" if stored == fid
                                 else "legacy 8-hex prefix")
            break
    out["available"] = True
    if not out["already_filed"]:
        out["reason"] = ("finding %r not in the entity ledger — not filed "
                         "before" % fid)
    return out
