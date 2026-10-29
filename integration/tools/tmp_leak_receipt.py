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

Owner table. 33 of the 56 whitelisted prefixes yield a producer `path[:line]` straight
from the whitelist's own comments (`derive_owners` implements the rule below); the
remaining 23 are listed in `OWNER_OVERRIDES` with a producer or an explicit reason. The
shared prefixes are drift-locked against the engine table
(`server/engine/inspection_lane_watchdog.py::TMP_FIXTURE_OWNERS`) by the battery, and this
module never imports the engine (the sweep must run where the engine cannot).

No filesystem access in the pure faces: `derive_owners` takes source text,
`build_receipt` takes parsed JSON. `load_owners(repo_root)` is the only reader.
"""
from __future__ import annotations

import json
import os
import re

SCHEMA = "tmp-sweep-receipt-v1"

#: Prefixes whose producer lives in another repository. `external` rows carry evidence
#: instead of a path inside this tree (a `~/` path is never resolved here: tests must not
#: read a machine-specific home).
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

#: The 23 prefixes whose whitelist comment does not yield a single producer path. A row
#: with `producer_path` None must carry a `reason`; the table lock enforces that.
OWNER_OVERRIDES = {
    "integ-e2e-fixture-": {
        "producer": "integration/ticket-lifecycle-scenes.mjs e2e fixture family (no single file: "
                    "the .mjs carrier moves with the scene suite)",
        "reason": "comment names a scene suite, not one file",
    },
    "fix10-": {"producer": "integration/t26* .mjs scenario fixtures", "reason": "family comment"},
    "fix14-": {"producer": "integration/t26* .mjs scenario fixtures", "reason": "family comment"},
    "fix17-": {"producer": "integration/t26* .mjs scenario fixtures", "reason": "family comment"},
    "pathgate-": {"producer": "integration/t260911-03 pathgate scenario fixtures",
                  "producer_path": "integration/t260911-03"},
    "t260907-12-ut": {"producer": "server/engine/tests/test_multirepo_anchor.py",
                      "producer_path": "server/engine/tests/test_multirepo_anchor.py"},
    "t26092212-": {"producer": "integration/t260922-12 family (whitelist comment carries no path)",
                   "reason": "family comment"},
    "t260906-": {"producer": "integration/t260906-* family (whitelist comment carries no path)",
                 "reason": "family comment"},
    "lease-ut-": {"producer": "integration/tests/test_stage_lease.py stage-lease unit fixtures",
                  "producer_path": "integration/tests/test_stage_lease.py"},
    "t260904-02-": {"producer": "server/engine/tests/test_t260904_02_registry_anchor.py",
                    "producer_path": "server/engine/tests/test_t260904_02_registry_anchor.py"},
    "t260901-21-": {"producer": "integration/t260901-21 read-side fixtures",
                    "producer_path": "integration/t260901-21"},
    "t02-lane": {"producer": "integration/t260902-02 lane fixtures", "producer_path": "integration/t260902-02"},
    "t26090704-lane": {"producer": "integration/t260907-04 lane fixtures",
                       "producer_path": "integration/t260907-04"},
    "wb-": {"producer": "server/plugins/workbench/tests workbench unit fixtures",
            "producer_path": "server/plugins/workbench/tests"},
    "t260907-12-ch": {"producer": "server/engine/tests/test_multirepo_root_activity.py",
                      "producer_path": "server/engine/tests/test_multirepo_root_activity.py"},
    "sandbar-credentials-": {"producer": "integration/stage_docker.py:1333 credentials copy",
                            "producer_path": "integration/stage_docker.py", "producer_line": 1333},
    "project-content-integ-run-": {"producer": "sister project (project-content) single-flight lock file",
                           "reason": "external producer", "external": True},
    "t260910-10-": {"producer": "integration/t260910-10 docs scenario fixtures",
                    "producer_path": "integration/t260910-10"},
    "t090506-": {"producer": "integration/t260905-06 docs scenario fixtures",
                 "producer_path": "integration/t260905-06"},
    "t26092404-": {"producer": "integration/t260924-04 project-template scenario fixtures",
                   "producer_path": "integration/t260924-04"},
    "t26092523-": {"producer": "integration/t260925-23/tests template pathgate fixtures",
                   "producer_path": "integration/t260925-23/tests"},
    "t260923-": {"producer": "integration/t260923-* family scenario fixtures",
                 "reason": "ticket-namespace family (no stable single path)"},
    "t260925-": {"producer": "integration/t260925-* family scenario fixtures",
                 "reason": "ticket-namespace family (no stable single path)"},
}

#: Producer-derivation rule (verbatim, so the measured counts are reproducible):
#:   1. take the text from `TMP_FIXTURE_PREFIXES = (` up to `BATCH2_MERGED_PREFIXES`;
#:   2. an "entry line" is a line that holds one or more quoted prefix tokens; every
#:      token on it belongs to that entry;
#:   3. the entry comment is the text after `#` on its own line plus the following
#:      pure-comment lines;
#:   4. scan the comment left to right, whitespace/`，`-separated; skip any token that
#:      carries `{`, `}` or `,` (those are brace expansions, not one path — they would
#:      fail the path lock); the first token matching `path.py|mjs|js|ts|sh[:line]` wins.
#: Measured with this rule on the whitelist as landed by t261029-38: 44 entry lines,
#: 56 prefixes, 33 derived, 23 overrides (the table above).
_ENTRY_BLOCK_START = "TMP_FIXTURE_PREFIXES = ("
_ENTRY_BLOCK_END = "BATCH2_MERGED_PREFIXES"
_TOKEN = re.compile(r'"([^"]+)"')
_PRODUCER = re.compile(r'^`?([A-Za-z0-9_./*-]+\.(?:py|mjs|js|ts|sh))(?::(\d+))?')


def derive_owners(src_text, prefixes):
    """Whitelist source text -> {prefix: {producer, producer_path, producer_line}}.

    Implements the rule documented above. Prefixes that yield no producer are simply
    absent; the caller fills them from OWNER_OVERRIDES and the lock refuses a gap.
    """
    try:
        block = src_text[src_text.index(_ENTRY_BLOCK_START):src_text.index(_ENTRY_BLOCK_END)]
    except ValueError:
        return {}
    wanted = set(prefixes)
    entries = []
    cur = None
    for line in block.splitlines():
        toks = [t for t in _TOKEN.findall(line.split("#", 1)[0]) if t in wanted]
        if toks:
            if cur:
                entries.append(cur)
            cur = [toks, line.split("#", 1)[1].strip() if "#" in line else ""]
        elif cur is not None and line.strip().startswith("#"):
            cur[1] += " " + line.strip()[1:]
    if cur:
        entries.append(cur)
    out = {}
    for toks, comment in entries:
        for tok in comment.replace("，", " ").split():
            if "{" in tok or "}" in tok or "," in tok:
                continue
            m = _PRODUCER.match(tok)
            if not m:
                continue
            for p in toks:
                out[p] = {"producer": m.group(1) + (":" + m.group(2) if m.group(2) else ""),
                          "producer_path": m.group(1),
                          "producer_line": int(m.group(2)) if m.group(2) else None,
                          "source": "derived"}
            break
    return out


def load_owners(repo_root, prefixes):
    """Full owner table: derived rows, then overrides, then external rows (repo name last).

    A row is a dict: {repo, producer, producer_path|None, producer_line|None,
    reason|None, external|bool, source: "derived"|"override"|"external"}.
    """
    sweep = os.path.join(repo_root, "integration", "tools", "sweep_tmp_fixtures.py")
    try:
        with open(sweep, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        src = ""
    rows = derive_owners(src, prefixes)
    for p in prefixes:
        if p in rows:
            continue
        base = dict(OWNER_OVERRIDES.get(p) or {})
        ext = EXTERNAL_OWNERS.get(p)
        if ext:
            base.update(ext)
            base["source"] = "external"
        else:
            base.setdefault("source", "override")
        base.setdefault("repo", "sandbar")
        base.setdefault("producer", base.get("producer") or "unknown producer")
        base.setdefault("producer_path", None)
        base.setdefault("producer_line", None)
        base.setdefault("reason", None)
        base.setdefault("external", False)
        rows[p] = base
    for p, row in rows.items():
        row.setdefault("repo", "sandbar")
        row.setdefault("external", bool(EXTERNAL_OWNERS.get(p)))
        row.setdefault("reason", None)
        row.setdefault("producer_path", None)
        row.setdefault("producer_line", None)
        path = row.get("producer_path")
        if not path:
            row["path_ok"] = None
            continue
        # Report a citation that no longer resolves instead of hiding it: the producer
        # may be retired or renamed, and the row then needs a reason (table lock).
        ok = os.path.exists(os.path.join(repo_root, path)) or os.path.exists(path)
        if not ok:
            try:
                import glob as _glob
                ok = bool(_glob.glob(os.path.join(repo_root, path)) or _glob.glob(path))
            except Exception:      # noqa: BLE001 — a glob pattern must never crash the table
                ok = False
        row["path_ok"] = bool(ok)
        if not ok and not row.get("reason"):
            row["reason"] = "cited producer path is not in the tree (retired or renamed)"
    return rows


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
