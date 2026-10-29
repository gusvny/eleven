#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tmp_leak_receipt — attribution and receipt assembly for the tmp-fixture sweep (t261029-38).

Why this module exists. The sweep tool answers "what can be deleted". The daily cadence
needs two more things: a **count delta** (did the backlog shrink or grow since the last
tick) and an **owner** for each family (which repo mints it), so the next occurrence
points at a person instead of a number. Both are pure functions over the sweep's JSON, so
they can be exercised without a clock, a root or a process table.

Sections of a receipt, in reader order:
  1. the one-line header (mode, root, backlog, delta, top leaker, cross-repo family);
  2. window, round shape, flags, tool revision;
  3. counts and the sweep's own summary line;
  4. count delta against the previous receipt (baseline with a named reason when the
     root or the mode changed, because macOS gives a new $TMPDIR per boot and a report
     run must never be compared with an apply run);
  5. top leaker families (prefix, count, oldest age, repo, producer);
  6. foreign and sister-repo families (counted, never swept — the project-vision part-intake
     note lives here, by name);
  7. excluded families (Chrome, macOS, dsh, BSD mktemp, editor/docker sockets);
  8. uncovered families (owner unknown, never guessed);
  9. capacity arithmetic (entries and bytes against the measured inflow) and notes.

Owner table. One row per family on the sweep's delete surface, read from the ONE family
declaration (`integration/tools/tmp_fixture_families.json`, t261029-81) that the sweeper
deletes from and the alarm face counts. Each row carries the declaration's `project` (the
repo), its `producer` (the evidence: a path that resolves in this tree, a named producer,
or nothing at all - rendered as `owner=unknown`, never guessed) and its `reason`. There is
no second copy of that evidence here: a hand-kept override table is exactly the structure
that drifts away from the surface it describes. The battery drift-locks the surface and
the evidence against the engine's own mirror read
(`server/engine/inspection_lane_watchdog.py::TMP_FIXTURE_OWNERS`), and this module never
imports the engine (the sweep must run where the engine cannot).

No filesystem access in the pure faces: `build_receipt` takes parsed JSON.
`load_owners(repo_root)` is the only reader.
"""
from __future__ import annotations

import json
import os
import re

SCHEMA = "tmp-sweep-receipt-v1"

#: The projects whose families this repo's temp root can carry without this repo being
#: able to fix them. A declaration record whose `project` is not ours must name one of
#: these: a fourth project would otherwise appear in the owner table silently, and the
#: next occurrence would point at nobody. This is a list of PROJECTS, never of families -
#: the families themselves live in the one declaration.
SIBLING_PROJECTS = ("project-content", "project-vision")

#: External evidence cited on the receipt: a producer we can name but not resolve. A `~/`
#: path is never resolved here (tests must not read a machine-specific home), so these
#: rows carry the citation instead of `producer_path`. The battery cross-locks this table
#: against the declaration: every prefix cited here must still be on the swept surface,
#: otherwise the receipt would stop counting a family it claims to know about.
EXTERNAL_OWNERS = {
    "project-content-integ-run-": {
        "repo": "project-content",
        "producer": "~/Documents/project-content/integration/run_scenarios.py:182 (same runner, sister project; "
                    "this repo cannot fix it)",
        "external": True,
        "reason": "sister-project producer: the lock cannot resolve a path outside this tree",
    },
}

#: The cross-repo leaker (ticket deliverable 3). Counted every tick, never swept: the fix
#: belongs to a ticket in that project. Numbers are the ticket's own record (1,295 runs,
#: about 130 MB per run, about 200 GB left) plus this repo's plan-time measurement.
FOREIGN_MINT = {
    "t26101406-gate-": {
        "repo": "project-vision",
        "file": "integration/sc_fpv_part_intake_gate.py",
        "line": 122,
    },
    "t26101406-refs-": {
        "repo": "project-vision",
        "file": "integration/sc_fpv_part_intake_refs_rule.py",
        "line": 71,
    },
    "t26101406-absent-": {
        "repo": "project-vision",
        "file": "integration/sc_fpv_part_intake_gate.py",
        "line": 339,
    },
    "t26101409-lane-gate-": {
        "repo": "project-vision",
        "file": "integration/sc_fpv_part_intake_lane_gate.py",
        "line": 110,
    },
    "t26101409-absent-": {
        "repo": "project-vision",
        "file": "integration/sc_fpv_part_intake_lane_gate.py",
        "line": 249,
    },
}

#: One sentence a reader can quote, kept in the receipt notes (deliverable 3, by name).
CROSS_REPO_NOTE = (
    "cross-repo leaker, recorded not fixed: the project-vision part-intake scenarios "
    "(integration/sc_fpv_part_intake_gate.py, integration/sc_fpv_part_intake_lane_gate.py, "
    "integration/sc_fpv_part_intake_refs_rule.py) copy two full repos into a fresh temp dir "
    "per run (about 130 MB) and never reclaim; 1,295 recorded runs left about 200 GB. "
    "This repo counts the family and never sweeps it; the fix belongs to a ticket in "
    "that project."
)

#: Owner labels for the families the sweep excludes by policy (counted, never swept).
EXCLUDED_OWNERS = {
    "com.google.Chrome.": "Google Chrome (profile temp dirs)",
    "com.apple.": "macOS system services",
    "BlobRegistryFiles": "other tooling (BlobRegistryFiles)",
    "playwright": "Playwright browser profiles",
    "TemporaryItems": "macOS/other tooling (TemporaryItems)",
    "TemporaryDirectory.": "other tooling (TemporaryDirectory.)",
    "vscode-git-": "VS Code git sockets",
    "docker_cli_": "docker CLI sockets",
    "dsh-subprocess-": "dsh runtime (agent subprocess spill dirs)",
    "dsh-spill-": "dsh runtime (spill dirs)",
    "tmp": "BSD mktemp default template",
}

#: The ONE family declaration the owner table is read from (t261029-81). The sweeper
#: deletes exactly the families this file declares and the alarm face counts exactly the
#: same ones, so this is also the surface the receipt attributes - prefix, project, producer
#: and reason arrive as data. A record's fields: prefix / kind / project / reason / producer
#: / measured / added_by.
OWNER_TABLE_FILENAME = "tmp_fixture_families.json"
OWNER_TABLE_RELPATH = os.path.join("integration", "tools", OWNER_TABLE_FILENAME)

#: Projects that mean "this repository owns the family". An empty or explicitly unknown
#: `project` is this repo's own namespace too: the sweeper reclaims it, so the row must name
#: this repo and say that the owner is unknown - it may never be attributed to a sibling.
OWN_PROJECTS = ("", "unknown", "sandbar")

#: Evidence classes of one owner row.
SOURCE_DERIVED = "derived"      # the producer names a path that resolves in this tree
SOURCE_OVERRIDE = "override"    # the producer is stated by name, or not recorded at all
SOURCE_EXTERNAL = "external"    # the producer lives in another project
SOURCE_UNKNOWN = "unknown"      # no row at all: the prefix is not on the declared surface

#: What a row says when the declaration records no producer (the census left several
#: families without an owner). Rendered as owner=unknown; never guessed.
UNKNOWN_PRODUCER = "unknown (the declaration records no producer)"

#: A producer citation inside the declaration's `producer` field: a repository-relative
#: `path` with a language suffix, optionally `:line`. Braces (`{a,b}.py`), shell globs and
#: family sentences yield no single path and stay a named producer (see the rule below).
_PRODUCER = re.compile(r"([A-Za-z0-9_./*-]+\.(?:py|mjs|js|ts|sh))(?::(\d+))?")


def declaration_path(repo_root):
    """The declaration file for a repository root (the sweeper's own directory)."""
    return os.path.join(str(repo_root), OWNER_TABLE_RELPATH)


def load_declaration(repo_root):
    """Read the family declaration -> (records, status).

    `records` are the raw dict records, in attribution order. `status` is
    `{"path", "status": "loaded"|"absent"|"malformed", "detail"}` - the same vocabulary the
    sweeper and the alarm face use, so one reader can compare all three.
    Structural rules match theirs: the document holds a `families` list, every record is an
    object with a non-empty `prefix`, and the strings are stripped. A duplicate prefix is
    malformed: two rows for one family would attribute an occurrence twice.
    """
    path = declaration_path(repo_root)
    out = {"path": path, "status": "absent", "detail": ""}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        out["detail"] = "the declaration file is absent"
        return [], out
    except OSError as exc:
        out["status"] = "malformed"
        out["detail"] = "cannot read the declaration: %s: %s" % (type(exc).__name__, exc)
        return [], out
    try:
        data = json.loads(raw)
    except ValueError as exc:
        out["status"] = "malformed"
        out["detail"] = "the declaration is not valid JSON: %s" % exc
        return [], out
    listed = data.get("families") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        out["status"] = "malformed"
        out["detail"] = "the declaration carries no `families` list"
        return [], out
    records, problems, seen = [], [], set()
    for i, rec in enumerate(listed):
        if not isinstance(rec, dict):
            problems.append("family #%d is not an object" % i)
            continue
        row = {k: str(rec.get(k) or "").strip() for k in
               ("prefix", "kind", "project", "reason", "producer", "measured", "added_by")}
        if not row["prefix"]:
            problems.append("family #%d has no prefix" % i)
            continue
        if row["prefix"] in seen:
            problems.append("%s: declared twice" % row["prefix"])
            continue
        seen.add(row["prefix"])
        records.append(row)
    if problems:
        out["status"] = "malformed"
        out["detail"] = "; ".join(problems[:8])
        return records, out
    out["status"] = "loaded"
    return records, out


def _resolves(repo_root, candidate):
    """Does a produced `path` (or glob) exist in this tree?"""
    try:
        if os.path.exists(os.path.join(str(repo_root), candidate)):
            return True
        import glob as _glob
        return bool(_glob.glob(os.path.join(str(repo_root), candidate)))
    except OSError:
        return False


def declared_path(repo_root, producer):
    """First producer path cited by the record that resolves in this tree -> (path, line).

    Returns `(None, None)` when the record states its producer by name (a family sentence, a
    brace list, a ticket namespace) or records no producer at all. A cited path that does not
    resolve is not an owner we can point at, so it stays a named producer rather than
    becoming a dead `producer_path` in the receipt.
    """
    for m in _PRODUCER.finditer(producer or ""):
        candidate = m.group(1)
        if _resolves(repo_root, candidate):
            return candidate, int(m.group(2)) if m.group(2) else None
    return None, None


def owner_row(repo_root, record, status=None):
    """One owner row from one declaration record (or an explicit unknown row).

    A row is a dict: `{repo, producer, producer_path|None, producer_line|None, reason|None,
    external, source, path_ok, declared_project, owner_recorded}`.

    - `repo` is the record's `project`; an empty/unknown project means this repo (the sweeper
      reclaims it) and keeps `declared_project="unknown"` for the reader.
    - `source` is `external` for a sibling project, `derived` when the producer path resolves
      in this tree, and `override` otherwise (evidence stated by name, or not recorded).
    - `producer_path` is only a path that exists here: a citation outside this tree (a `~/`
      path, another project's file) stays evidence text, never a resolvable path.
    """
    status = status or {"status": "loaded", "detail": ""}
    if record is None:
        reason = "the declaration names no record for this prefix"
        if status.get("status") != "loaded":
            reason = "the declaration could not be read: %s" % (
                status.get("detail") or status.get("status"))
        return {"repo": "unknown", "producer": UNKNOWN_PRODUCER, "producer_path": None,
                "producer_line": None, "reason": reason, "external": False,
                "source": SOURCE_UNKNOWN, "path_ok": None, "declared_project": "",
                "owner_recorded": False}
    project = record.get("project") or ""
    own = project in OWN_PROJECTS
    repo = "sandbar" if own else project
    producer = (record.get("producer") or "").strip()
    reason = (record.get("reason") or "").strip() or None
    if not own:
        return {"repo": repo, "producer": producer or UNKNOWN_PRODUCER,
                "producer_path": None, "producer_line": None, "reason": reason,
                "external": True, "source": SOURCE_EXTERNAL, "path_ok": None,
                "declared_project": project, "owner_recorded": bool(producer)}
    path, line = declared_path(repo_root, producer) if producer else (None, None)
    if path:
        return {"repo": repo, "producer": producer, "producer_path": path,
                "producer_line": line, "reason": reason, "external": False,
                "source": SOURCE_DERIVED, "path_ok": True, "declared_project": project,
                "owner_recorded": True}
    # No fabricated reason: a record with no path and no reason is a declaration defect, and
    # the receipt says so by leaving `reason` None. The battery names the prefix.
    return {"repo": repo, "producer": producer or UNKNOWN_PRODUCER, "producer_path": None,
            "producer_line": None, "reason": reason, "external": False,
            "source": SOURCE_OVERRIDE, "path_ok": None, "declared_project": project,
            "owner_recorded": bool(producer)}


def load_owners(repo_root, prefixes):
    """The owner table for `prefixes`, read from the one declaration -> {prefix: row}.

    A prefix with no record still gets a row: `owner=unknown` with a named reason, because a
    family the sweeper reclaims without an owner must be visible, not absent. The declaration
    status is not swallowed either - `load_owners_status` returns it next to the rows.
    """
    rows, _status = load_owners_status(repo_root, prefixes)
    return rows


def load_owners_status(repo_root, prefixes):
    """`(rows, status)` - the owner table plus the declaration status it was read from."""
    records, status = load_declaration(repo_root)
    by_prefix = {r["prefix"]: r for r in records}
    rows = {p: owner_row(repo_root, by_prefix.get(p), status) for p in prefixes}
    return rows, status


def owner_of(prefix, owners):
    """One owner row, or an explicit unknown row (never a guess)."""
    row = owners.get(prefix)
    if row:
        return dict(row)
    return {"repo": "unknown", "producer": "unknown (prefix not in the whitelist)",
            "producer_path": None, "producer_line": None, "reason": "not whitelisted",
            "external": False, "source": "unknown"}


#: Grouping key for entries outside the whitelist: strip one trailing mkdtemp random
#: token, keep the rest. Handles `<ticket>-<token>`, `<name>-<token>`, `name_token` and
#: dotted names; malformed names (spaces, newlines, undecodable bytes) fall back to the
#: first whitespace-separated word so nothing crashes and nothing is silently merged.
_TRAILING_TOKEN = re.compile(r"[-_]?[a-z0-9]{4,}$", re.IGNORECASE)


def family_key(name):
    """Deterministic family key for an entry name outside the whitelist."""
    text = name if isinstance(name, str) else str(name)
    first = text.split()[0] if text.split() else text
    key = _TRAILING_TOKEN.sub("", first)
    if not key:
        key = first
    return key


def uncovered_families(names, top=5):
    """Group names outside the whitelist -> top rows [{family, count}] (count desc, name asc)."""
    counts = {}
    for n in names:
        try:
            k = family_key(n)
        except Exception:            # noqa: BLE001 — a name must never crash a receipt
            k = "undecodable"
        counts[k] = counts.get(k, 0) + 1
    rows = [{"family": k, "count": c} for k, c in counts.items() if c]
    rows.sort(key=lambda r: (-r["count"], r["family"]))
    return rows[:top]


def attribute_rows(per_prefix_rows, live_per_prefix, owners):
    """Sweep per-prefix rows -> attributed leaker rows (count desc, then prefix asc).

    Zero-count rows are dropped: the sweep prints all 56 prefixes today, and a receipt
    that lists 56 rows buries the owner the reader came for.
    """
    out = []
    for r in per_prefix_rows or ():
        prefix = r.get("prefix")
        if not prefix:
            continue
        stale = int(r.get("count") or 0)
        live = int((live_per_prefix or {}).get(prefix) or 0)
        total = stale + live
        if total <= 0:
            continue
        row = owner_of(prefix, owners)
        out.append({"prefix": prefix, "count": total, "stale": stale, "live": live,
                    "oldest_h": round(float(r.get("oldest_h") or 0.0), 2),
                    "est_bytes": int(r.get("est_bytes") or 0),
                    "repo": row["repo"], "producer": row["producer"],
                    "producer_path": row.get("producer_path"),
                    "producer_line": row.get("producer_line"),
                    "owner_source": row.get("source")})
    out.sort(key=lambda r: (-r["count"], r["prefix"]))
    return out


def delta_block(previous, mode, root, per_prefix_counts, entries, whitelisted_total,
                now_epoch=None):
    """Count delta against the previous receipt, with a named baseline reason.

    Comparison requires the same realpath root AND the same mode: macOS hands out a new
    $TMPDIR per boot, and a report run must never be compared with an apply run.
    """
    block = {"basis": "baseline", "reason": "no_previous", "previous_receipt_path": None,
             "entries": None, "whitelisted": None, "per_prefix": [], "gap_s": None,
             "growth": False}
    if not isinstance(previous, dict):
        return block
    block["previous_receipt_path"] = previous.get("receipt_path")
    if previous.get("_unreadable"):
        block["reason"] = "unreadable_previous"
        return block
    if previous.get("mode") != mode:
        block["reason"] = "mode_changed"
        return block
    prev_root = previous.get("root")
    if prev_root and prev_root != root:
        block["reason"] = "root_changed"
        return block
    prev_counts = (previous.get("counts") or {})
    prev_entries = prev_counts.get("entries")
    prev_wl = prev_counts.get("whitelisted_total")
    if not isinstance(prev_entries, (int, float)) or not isinstance(prev_wl, (int, float)):
        block["reason"] = "previous_incomplete"
        return block
    block["basis"] = "previous"
    block["reason"] = None
    block["entries"] = {"prev": int(prev_entries), "now": int(entries),
                        "delta": int(entries) - int(prev_entries)}
    block["whitelisted"] = {"prev": int(prev_wl), "now": int(whitelisted_total),
                            "delta": int(whitelisted_total) - int(prev_wl)}
    prev_pp = previous.get("per_prefix_counts") or {}
    rows = []
    for prefix, now in sorted((per_prefix_counts or {}).items()):
        before = int(prev_pp.get(prefix) or 0)
        if before == now and not before:
            continue
        rows.append({"prefix": prefix, "prev": before, "now": int(now),
                     "delta": int(now) - before})
    block["per_prefix"] = rows
    block["growth"] = block["whitelisted"]["delta"] > 0
    prev_ended = previous.get("ended_utc_epoch")
    if isinstance(prev_ended, (int, float)) and isinstance(now_epoch, (int, float)):
        gap = float(now_epoch) - float(prev_ended)
        block["gap_s"] = round(gap, 1) if gap > 0 else None
    return block


def capacity_block(mode, counts, freed_est_bytes, duration_s, delta, whitelisted_bytes_now):
    """Capacity against the measured inflow (apply mode only for the deficit verdict).

    Basis (deliberate): entries are whitelisted candidates only, bytes come from the
    whitelist size estimate. The whole-backlog average (about 2.14 MB/entry on this host)
    is dominated by foreign fpv dirs this ticket must not delete, so it would overstate
    the drain rate by an order of magnitude.
    """
    swept = int(counts.get("swept") or 0)
    cap_entries_s = (swept / duration_s) if duration_s and swept else 0.0
    cap_bytes_s = (float(freed_est_bytes) / duration_s) if duration_s and freed_est_bytes else 0.0
    inflow_entries_s = None
    wl_delta = (delta.get("whitelisted") or {}).get("delta")
    gap = delta.get("gap_s")
    if isinstance(wl_delta, (int, float)) and isinstance(gap, (int, float)) and gap > 0:
        inflow_entries_s = max(0.0, float(wl_delta) / float(gap))
    backlog = int(counts.get("candidates_total") or 0)
    projected = None
    if cap_entries_s > 0 and (inflow_entries_s or 0) < cap_entries_s and backlog:
        net = cap_entries_s - (inflow_entries_s or 0.0)
        projected = round(backlog / net / 86400.0, 2) if net > 0 else None
    deficit = bool(mode == "apply" and backlog > 1000 and inflow_entries_s is not None
                   and cap_entries_s < inflow_entries_s)
    return {"capacity_entries_per_s": round(cap_entries_s, 1),
            "capacity_bytes_per_s": int(cap_bytes_s),
            "inflow_entries_per_s": round(inflow_entries_s, 3) if inflow_entries_s is not None else None,
            "backlog_candidates": backlog,
            "projected_days_to_clear": projected,
            "deficit": deficit,
            "basis": "whitelisted candidates only; bytes are the whitelist estimate",
            "note": ("deficit: capacity is below the observed inflow; the backlog is still "
                     "growing" if deficit else None)}


def foreign_rows(foreign_sweep_json):
    """Per-mint family rows from the count-only sweep of the foreign prefix set."""
    rows = []
    per_prefix = (foreign_sweep_json or {}).get("per_prefix") or []
    live = (foreign_sweep_json or {}).get("live_per_prefix") or {}
    for r in per_prefix:
        mint = FOREIGN_MINT.get(r.get("prefix"))
        if not mint:
            continue
        count = int(r.get("count") or 0) + int(live.get(r.get("prefix")) or 0)
        if count <= 0:
            continue
        rows.append({"prefix": r.get("prefix"), "count": count,
                     "oldest_h": round(float(r.get("oldest_h") or 0.0), 2),
                     "est_bytes": int(r.get("est_bytes") or 0),
                     "repo": mint["repo"], "file": mint["file"], "line": mint["line"]})
    rows.sort(key=lambda r: (-r["count"], r["prefix"]))
    return rows


def excluded_rows(excluded_by_prefix):
    """Excluded families with counts and owner labels (never swept, always visible)."""
    rows = []
    for prefix, count in (excluded_by_prefix or {}).items():
        if not count:
            continue
        rows.append({"prefix": prefix, "count": int(count),
                     "owner": EXCLUDED_OWNERS.get(prefix, "unknown (excluded by policy)")})
    rows.sort(key=lambda r: (-r["count"], r["prefix"]))
    return rows


def build_receipt(*, sweep_json, foreign_json, previous, owners, ctx):
    """Assemble one receipt dict from the two sweep runs plus the run context.

    `ctx` carries the run facts: mode, round_shape, round_depth, root, state_dir,
    receipt_path, started/ended (UTC + epoch), max_age_h, limit, budget_s,
    budget_source, flags, tool_rev, status, degraded, notes.
    """
    counts_in = sweep_json or {}
    per_prefix = counts_in.get("per_prefix") or []
    per_prefix_counts = {}
    for r in per_prefix:
        p = r.get("prefix")
        if p:
            per_prefix_counts[p] = int(r.get("count") or 0) + int(
                (counts_in.get("live_per_prefix") or {}).get(p) or 0)
    whitelisted_total = sum(per_prefix_counts.values())
    counts = {"entries": int(counts_in.get("entries") or 0),
              "whitelisted_total": whitelisted_total,
              "stale": int(counts_in.get("swept") or 0) if ctx.get("mode") == "apply" else
                       int(counts_in.get("candidates_total") or 0),
              "candidates_total": int(counts_in.get("candidates_total") or 0),
              "live": int(counts_in.get("kept_live") or 0),
              "untouched": int(counts_in.get("untouched") or 0),
              "excluded": sum(int(v or 0) for v in (counts_in.get("excluded_by_prefix") or {}).values()),
              "swept": (int(counts_in.get("swept") or 0)
                        if ctx.get("mode") == "apply" else 0),
              "would_sweep": (int(counts_in.get("swept") or 0)
                              if ctx.get("mode") != "apply" else 0),
              "processed": int(counts_in.get("processed") or 0),
              "remaining": int(counts_in.get("remaining") or 0),
              "failed": int(counts_in.get("failed") or 0),
              "failed_named": list(counts_in.get("failed_named") or [])[:20],
              "partial": bool(counts_in.get("partial")),
              "kept_live": int(counts_in.get("kept_live") or 0),
              "holders_kept": int(counts_in.get("holders_kept") or 0),
              "holders_named": list(counts_in.get("holders_named") or [])[:20],
              "carriers_kept": int(counts_in.get("carriers_kept") or 0),
              "carriers_named": list(counts_in.get("carriers_named") or [])[:20],
              "locks_kept": int(counts_in.get("locks_kept") or 0),
              "locks_named": list(counts_in.get("locks_kept_named") or [])[:20]}
    delta = delta_block(previous, ctx.get("mode"), ctx.get("root"), per_prefix_counts,
                        counts["entries"], whitelisted_total,
                        now_epoch=ctx.get("started_utc_epoch"))
    top = attribute_rows(per_prefix, counts_in.get("live_per_prefix"), owners)[:5]
    duration = float(ctx.get("duration_s") or 0.0)
    capacity = capacity_block(ctx.get("mode"), counts, counts_in.get("freed_est_bytes"),
                              duration, delta, whitelisted_bytes_now=None)
    receipt = {
        "schema": SCHEMA,
        "status": ctx.get("status") or "ok",
        "mode": ctx.get("mode"),
        "round_shape": ctx.get("round_shape"),
        "round_depth": ctx.get("round_depth"),
        "root": ctx.get("root"),
        "state_dir": ctx.get("state_dir"),
        "receipt_path": ctx.get("receipt_path"),
        "previous_receipt_path": delta.get("previous_receipt_path"),
        "started_utc": ctx.get("started_utc"), "ended_utc": ctx.get("ended_utc"),
        "started_utc_epoch": ctx.get("started_utc_epoch"),
        "ended_utc_epoch": ctx.get("ended_utc_epoch"),
        "duration_s": round(duration, 2),
        "max_age_h": ctx.get("max_age_h"), "limit": ctx.get("limit"),
        "budget_s": ctx.get("budget_s"), "budget_source": ctx.get("budget_source"),
        "flags": ctx.get("flags") or {},
        "tool_rev": ctx.get("tool_rev") or {},
        "counts": counts,
        # Top-level mirrors of the counters a receipt reader quotes without walking the
        # nested block (the cadence scenario and the delivery report both read these).
        "swept": counts["swept"],
        "swept_this_tick": counts["swept"],
        "would_sweep": counts["would_sweep"],
        "candidates_total": counts["candidates_total"],
        "sweep_summary": counts_in.get("summary"),
        "freed_est_bytes": int(counts_in.get("freed_est_bytes") or 0),
        "estimate": True,
        "probe": counts_in.get("probe") or {},
        "degraded": bool(counts_in.get("degraded") or ctx.get("degraded")),
        "degraded_reason": counts_in.get("degraded_reason") or ctx.get("degraded_reason"),
        "delta": delta,
        "per_prefix_counts": per_prefix_counts,
        "top_leakers": top,
        "foreign": {"prefixes": sorted(FOREIGN_MINT),
                    "rows": foreign_rows(foreign_json),
                    "note": CROSS_REPO_NOTE},
        "excluded": excluded_rows(counts_in.get("excluded_by_prefix")),
        "uncovered": [dict(r, owner="unknown (not whitelisted; may be a new producer in "
                                     "this repo or another repo's fixtures)")
                      for r in uncovered_families(
                          (sweep_json or {}).get("untouched_names") or [])],
        "capacity": capacity,
        "notes": list(ctx.get("notes") or []),
    }
    receipt["header"] = header_line(receipt)
    return receipt


def header_line(receipt):
    """One line a person can read without opening the file (deliverable 2 and 3)."""
    counts = receipt.get("counts") or {}
    delta = receipt.get("delta") or {}
    wl = (delta.get("whitelisted") or {})
    d = wl.get("delta")
    delta_txt = ("Δ%+d" % d) if isinstance(d, int) else "baseline"
    top = (receipt.get("top_leakers") or [None])[0]
    if top:
        top_txt = "%s %d × %s:%s" % (top["prefix"], top["count"], top["repo"],
                                     top.get("producer") or "unknown")
    else:
        top_txt = "none"
    foreign = receipt.get("foreign") or {}
    f_rows = foreign.get("rows") or []
    if f_rows:
        f_count = sum(r["count"] for r in f_rows)
        f_size = sum(r["est_bytes"] for r in f_rows)
        foreign_txt = "%s %d dirs ≈%s (counted, never swept)" % (
            ",".join(sorted({r["repo"] for r in f_rows})), f_count, human(f_size))
    else:
        foreign_txt = "none counted"
    return ("TMP-SWEEP TICK %s mode=%s root=%s receipts=%s backlog=%d (%s) | top leaker: %s | "
            "cross-repo: %s"
            % (receipt.get("status"), receipt.get("mode"), receipt.get("root"),
               receipt.get("state_dir"), int(counts.get("candidates_total") or 0),
               delta_txt, top_txt, foreign_txt))


def human(n):
    """Bytes -> human (B/K/M/G/T, one decimal)."""
    v = float(n or 0)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if v < 1024 or unit == "P":
            return ("%dB" % int(v)) if unit == "B" else ("%.1f%s" % (v, unit))
        v /= 1024.0
    return "%.1fP" % v


def render_markdown(receipt):
    """Human receipt: header first, then the sections a reader walks in order."""
    c = receipt.get("counts") or {}
    d = receipt.get("delta") or {}
    lines = ["# " + receipt.get("header", "TMP-SWEEP receipt"), ""]
    lines.append("- receipt: `%s`" % receipt.get("receipt_path"))
    lines.append("- previous: `%s`" % (receipt.get("previous_receipt_path") or "none"))
    lines.append("- window: %s → %s (%.1fs)" % (receipt.get("started_utc"),
                                                receipt.get("ended_utc"),
                                                float(receipt.get("duration_s") or 0.0)))
    lines.append("- shape: %s depth=%s | mode=%s | age gate %sh | limit=%s | budget=%ss (%s)"
                 % (receipt.get("round_shape"), receipt.get("round_depth"), receipt.get("mode"),
                    receipt.get("max_age_h"), receipt.get("limit"), receipt.get("budget_s"),
                    receipt.get("budget_source")))
    rev = receipt.get("tool_rev") or {}
    lines.append("- tool: head=%s sweep_sha=%s" % (rev.get("head") or "unknown",
                                                   rev.get("sweep_sha") or "unknown"))
    probe = receipt.get("probe") or {}
    if probe:
        lines.append("- probe: rows=%s cwd=%s fd=%s in_root=%s matched_pids=%s degraded=%s"
                     % (probe.get("rows"), probe.get("cwd_rows"), probe.get("fd_rows"),
                        probe.get("in_root_rows"), probe.get("matched_pids"),
                        probe.get("degraded")))
    lines += ["", "## Counts", ""]
    lines.append("entries %d | whitelisted %d | candidates %d | swept %d | would sweep %d | "
                 "kept live %d | holders kept %d | carriers kept %d | locks kept %d | failed %d | "
                 "untouched %d | excluded %d"
                 % (c.get("entries", 0), c.get("whitelisted_total", 0),
                    c.get("candidates_total", 0), c.get("swept", 0), c.get("would_sweep", 0),
                    c.get("kept_live", 0),
                    c.get("holders_kept", 0), c.get("carriers_kept", 0), c.get("locks_kept", 0),
                    c.get("failed", 0), c.get("untouched", 0), c.get("excluded", 0)))
    if c.get("partial"):
        lines.append("")
        lines.append("**PARTIAL**: swept %d of %d candidates; %d left for the next tick."
                     % (c.get("swept", 0), c.get("candidates_total", 0), c.get("remaining", 0)))
    kept_named = (c.get("holders_named") or []) + (c.get("carriers_named") or []) + \
                 (c.get("locks_named") or [])
    if kept_named:
        lines.append("")
        lines.append("kept and named (a live holder, a carrier cwd or an flocked lock):")
        for n in kept_named[:20]:
            lines.append("- " + str(n))
    if c.get("failed_named"):
        lines.append("")
        lines.append("failed (named): " + "; ".join(c["failed_named"]))
    lines += ["", "## Count delta", ""]
    if d.get("basis") == "previous":
        e = d.get("entries") or {}
        w = d.get("whitelisted") or {}
        lines.append("entries %d → %d (%+d) | whitelisted %d → %d (%+d)%s"
                     % (e.get("prev", 0), e.get("now", 0), e.get("delta", 0),
                        w.get("prev", 0), w.get("now", 0), w.get("delta", 0),
                        "  **growth**" if d.get("growth") else ""))
        rows = d.get("per_prefix") or []
        if rows:
            lines.append("")
            lines.append("| prefix | prev | now | delta |")
            lines.append("|---|---|---|---|")
            for r in rows[:15]:
                lines.append("| `%s` | %d | %d | %+d |" % (r["prefix"], r["prev"], r["now"], r["delta"]))
    else:
        lines.append("baseline (%s) — no comparison with a previous receipt" % d.get("reason"))
    lines += ["", "## Top leaker families (swept families; count, repo, producer)", ""]
    if receipt.get("top_leakers"):
        lines.append("| prefix | count | oldest | repo | producer |")
        lines.append("|---|---|---|---|---|")
        for r in receipt["top_leakers"]:
            lines.append("| `%s` | %d | %.1fh | %s | %s |"
                         % (r["prefix"], r["count"], r["oldest_h"], r["repo"], r["producer"]))
    else:
        lines.append("none")
    lines += ["", "## Foreign / sister families (counted, never swept)", ""]
    f = receipt.get("foreign") or {}
    if f.get("rows"):
        lines.append("| prefix | count | oldest | est | repo | minted at |")
        lines.append("|---|---|---|---|---|---|")
        for r in f["rows"]:
            lines.append("| `%s` | %d | %.1fh | ≈%s | %s | %s:%s |"
                         % (r["prefix"], r["count"], r["oldest_h"], human(r["est_bytes"]),
                            r["repo"], r["file"], r["line"]))
    else:
        lines.append("none counted this tick")
    lines.append("")
    lines.append(f.get("note") or "")
    lines += ["", "## Excluded families (policy: never swept)", ""]
    if receipt.get("excluded"):
        for r in receipt["excluded"]:
            lines.append("- `%s` %d — %s" % (r["prefix"], r["count"], r["owner"]))
    else:
        lines.append("none")
    lines += ["", "## Uncovered families (not whitelisted; owner unknown)", ""]
    if receipt.get("uncovered"):
        for r in receipt["uncovered"]:
            lines.append("- `%s` %d — %s" % (r["family"], r["count"], r["owner"]))
    else:
        lines.append("none")
    cap = receipt.get("capacity") or {}
    lines += ["", "## Capacity", ""]
    lines.append("capacity %.1f entries/s | inflow %s entries/s | backlog %d | projected %s days"
                 % (cap.get("capacity_entries_per_s") or 0.0,
                    cap.get("inflow_entries_per_s"), cap.get("backlog_candidates") or 0,
                    cap.get("projected_days_to_clear")))
    lines.append("basis: %s" % cap.get("basis"))
    if cap.get("note"):
        lines.append("")
        lines.append("**%s**" % cap["note"])
    if receipt.get("notes"):
        lines += ["", "## Notes", ""]
        for n in receipt["notes"]:
            lines.append("- " + str(n))
    return "\n".join(lines) + "\n"


def dumps(receipt):
    """Stable JSON text for the receipt file."""
    return json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
