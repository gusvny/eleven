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


def review_ledger_path(project_key: Any,
                       override: Any = None) -> Tuple[Optional[Path], str]:
    """Ledger path, three priorities: override (caller args) >
    `SANDBAR_REVIEW_LEDGER_DIR` > `<SANDBAR_PROJECTS_DIR or ~/.sandbar/
    projects>/<key>/inspection/reviewed.jsonl`.

    Never raises: underivable (bad key, home expansion failure with no
    override) = (None, reason note) — the caller degrades to "everything
    unreviewed" plus the named note (observable, not silent, not fatal)."""
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
            return None, "review ledger override path unusable (%s: %s)" % (
                type(e).__name__, e)
    ok, reason = validate_path_component(project_key)
    if not ok:
        return None, "review ledger path not derived (project_key %r: %s)" % (
            project_key, reason)
    root_env = os.environ.get(PROJECTS_ROOT_ENV) or ""
    try:
        root = Path(root_env.strip()).expanduser() if root_env.strip() \
            else (Path.home() / ".sandbar" / "projects")
    except (OSError, RuntimeError) as e:
        return None, "projects root not derivable (%s: %s)" % (type(e).__name__, e)
    return root / str(project_key).strip() / "inspection" / "reviewed.jsonl", ""


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
