#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_loss_check — prove that a conflict resolution kept both sides' work.

Why this exists (ticket t261013-06, review comment C3): a merge resolution can
silently drop one side's lines. Every container check still passes then: the
lane contains the line, the landing merges cleanly, and no marker remains. The
loss shows up later as a red certification on a frozen line, and the remedy is
another fix ticket.

What it measures, per conflicted file, at line level:

  1. lines that ``ours`` added since the merge base but that ``theirs`` lacks;
  2. lines that ``theirs`` added since the merge base but that ``ours`` lacks;
  3. after a merge: lines either side added that the result lacks;
  4. after a merge: lines either side deleted that the other side or the
     result still carries (a review row, never a failure by itself).

Two modes:

  ``--classify``  before the merge, name the lossless resolution per file:
                  ``theirs-verbatim``, ``ours-verbatim`` or ``combine``, each
                  with the command that applies it;
  default         after the merge, report the result's losses. A line whose
                  only difference is a leading or trailing delimiter run is
                  named ``delimiter-only`` and never counts as a loss
                  (review condition 2: a comma must not read as a lost line).
                  A hand-authored resolution diverges on purpose sometimes, so
                  ``--declared FILE`` accepts rows with a reason each. Anything
                  undeclared stays red, and an entry that matches no row is
                  reported as stale and fails the check, so the declaration can
                  never rot into a blanket exemption.

The loss mode checks a SETTLED result: both named sides must be ancestors of
``--result``. An unmerged result (the plain lane tip) reads as a loss list in
every file, and that false red cost a round (t261013-06 arbitration finding 2),
so it is refused by name instead. ``--allow-unmerged-result`` is the explicit
way to check a hand-built resolution that is not a merge commit.

Exit codes: 0 = no unexplained loss, 1 = a loss or marker residue was found,
2 = the arguments, the repository or the result's state are unusable (fail
closed, never clean).

Read-only: it runs ``git show``, ``git merge-base`` and ``git merge-tree``.
It never writes the repository, the index or the worktree.
"""
import argparse
import collections
import difflib
import json
import re
import subprocess
import sys

GIT_TIMEOUT_S = 120

#: The merge-tree block headers that mean "both sides touched this file": the
#: conflict candidate set. The one-sided headers ("added in remote", "changed in
#: local" and friends) need no resolution decision, and counting them inflated
#: this list to 18 files against 15 real conflicts (measured 261013).
CONFLICT_HEADERS = (
    "added in both",
    "changed in both",
    "removed in both",
)

#: Conflict marker shapes. A committed marker is always a failure.
MARKER_PREFIXES = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

#: Characters that carry no meaning for the delimiter-only comparison.
_LEAD_DELIMS = "([{,:;'\""
_TAIL_DELIMS = ")]},;:'\""


class CheckError(Exception):
    """The check could not run. Always a named reason, never a guessed result."""


def _git(args, repo):
    try:
        proc = subprocess.run(["git"] + list(args), cwd=str(repo),
                              capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, errors="replace")
    except OSError as exc:
        raise CheckError("git unusable: %s" % exc)
    except subprocess.TimeoutExpired:
        raise CheckError("git timed out after %ds: git %s" % (GIT_TIMEOUT_S, " ".join(args)))
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def merge_base(repo, ours, theirs):
    rc, out, err = _git(["merge-base", ours, theirs], repo)
    sha = out.strip().splitlines()[0].strip() if out.strip() else ""
    if rc != 0 or not sha:
        raise CheckError("merge-base %s %s failed (fail closed, never a guessed base): %s"
                         % (ours, theirs, (err or out).strip()[-200:]))
    return sha


def resolved_sha(repo, rev):
    rc, out, err = _git(["rev-parse", "--verify", "%s^{commit}" % rev], repo)
    sha = out.strip().splitlines()[0].strip() if out.strip() else ""
    if rc != 0 or not sha:
        raise CheckError("revision %r is not a commit (fail closed): %s"
                         % (rev, (err or out).strip()[-200:]))
    return sha


def is_ancestor(repo, rev, of_rev):
    rc, _out, _err = _git(["merge-base", "--is-ancestor", rev, of_rev], repo)
    if rc == 0:
        return True
    if rc == 1:
        return False
    raise CheckError("merge-base --is-ancestor %s %s failed (fail closed)" % (rev, of_rev))


def require_settled_result(repo, ours, theirs, result):
    """Refuse a result that did not absorb the two named sides.

    A settled merge commit has both sides as ancestors. A plain lane tip has
    neither, and every line of the other side then reads as lost — the false
    red of t261013-06 arbitration finding 2. Returns the missing side names.
    """
    missing = [name for name, rev in (("ours", ours), ("theirs", theirs))
               if not is_ancestor(repo, rev, result)]
    return missing


def show_lines(repo, rev, path):
    """The file's lines at ``rev``, or None when the path does not exist there."""
    rc, out, err = _git(["show", "%s:%s" % (rev, path)], repo)
    if rc != 0:
        text = (err or out)
        if "does not exist" in text or "exists on disk, but not in" in text \
                or "unknown revision" in text or "Path '" in text:
            return None
        raise CheckError("git show %s:%s failed: %s" % (rev, path, text.strip()[-200:]))
    return out.splitlines()


def staged_conflicts(repo):
    """The paths a LIVE merge left unmerged (``git ls-files -u``), or [].

    This is the authoritative set once a scene exists. The merge-tree forecast
    is the pre-merge prediction and disagrees with the real merge: measured
    t261013-06, the forecast named 15 files while the merge left 11 unmerged and
    auto-merged 4 (t261013-06 arbitration finding B). Resolving from the forecast
    alone would chase files that are not conflicts and leave real conflicts
    unchased (t260904-12 wording guard: the retired wording named the same
    hazard with a banned state word; the hazard sentence stays, the word does
    not).
    """
    rc, out, err = _git(["ls-files", "-u"], repo)
    if rc != 0:
        raise CheckError("git ls-files -u failed (fail closed): %s" % (err or out).strip()[-200:])
    paths = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] and parts[1] not in paths:
            paths.append(parts[1])
    return sorted(paths)


def conflict_files(repo, base, ours, theirs):
    """The files the merge of ``ours`` and ``theirs`` conflicts on.

    Read from ``git merge-tree <base> <ours> <theirs>`` — the same read-only
    forecast the plan used. Only the "both sides touched it" blocks count: a
    one-sided change needs no resolution decision. A failed merge-tree is never
    read as "no conflicts"."""
    rc, out, err = _git(["merge-tree", base, ours, theirs], repo)
    if rc != 0:
        raise CheckError("merge-tree %s %s %s failed (fail closed): %s"
                         % (base, ours, theirs, (err or out).strip()[-200:]))
    files, in_block = [], False
    for line in out.splitlines():
        if line.strip() in CONFLICT_HEADERS:
            in_block = True
            continue
        if line.strip().endswith((" in both", " in remote", " in local")):
            in_block = False            # another section starts: leave this block
            continue
        if not in_block:
            continue
        parts = line.split()
        if len(parts) >= 4 and parts[0] in ("our", "their", "base"):
            files.append(parts[3])
            in_block = False
    seen, ordered = set(), []
    for path in files:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def added_lines(base_lines, side_lines):
    """The lines ``side_lines`` adds or rewrites, with their line numbers."""
    if side_lines is None:
        return []
    if base_lines is None:
        # The file is new on this side: every line is an addition.
        return [(i + 1, text) for i, text in enumerate(side_lines)]
    matcher = difflib.SequenceMatcher(a=base_lines, b=side_lines, autojunk=False)
    out = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            out.extend((j + 1, side_lines[j]) for j in range(j1, j2))
    return out


def deleted_lines(base_lines, side_lines):
    """The lines ``side_lines`` removes or rewrites away, with base line numbers."""
    if base_lines is None:
        return []
    if side_lines is None:
        return [(i + 1, text) for i, text in enumerate(base_lines)]
    matcher = difflib.SequenceMatcher(a=base_lines, b=side_lines, autojunk=False)
    out = []
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            out.extend((i + 1, base_lines[i]) for i in range(i1, i2))
    return out


def _without_delims(line):
    stripped = line.strip()
    start, end = 0, len(stripped)
    while start < end and stripped[start] in _LEAD_DELIMS:
        start += 1
    while end > start and stripped[end - 1] in _TAIL_DELIMS:
        end -= 1
    return stripped[start:end]


def classify_missing(line, result_lines, result_counter):
    """How ``line`` is missing from the result, or None when it is present.

    ``missing``  the line's text is absent in any form;
    ``delimiter-only``  the result carries the same line with a different
    leading or trailing delimiter run, so the difference is punctuation only.
    """
    if result_counter[line] > 0:
        return None
    target = _without_delims(line)
    if target:
        for other in result_lines:
            if other != line and _without_delims(other) == target:
                return "delimiter-only"
    return "missing"


def marker_lines(lines):
    """The conflict-marker lines a committed result must never carry."""
    out = []
    for number, text in enumerate(lines or [], start=1):
        stripped = text.strip()
        if stripped.startswith(MARKER_PREFIXES):
            out.append((number, text))
    return out


def symbols_at(repo, rev, path, pattern):
    """The symbols ``pattern`` finds in ``path`` at ``rev`` (an empty set when the
    file does not exist there). The pattern's first group wins when it has one."""
    lines = show_lines(repo, rev, path)
    if lines is None:
        return set()
    out = set()
    for match in pattern.finditer("\n".join(lines)):
        value = match.group(1) if match.groups() else match.group(0)
        if value:
            out.add(value)
    return out


def symbol_loss(repo, ours, theirs, result, path, pattern):
    """Symbols from either side that the result lost.

    A merged file can lose a whole family of names while every line-level check
    looks reasonable: the registry case (t261013-06 arbitration — the scenario
    registry where the line carries names main does not, so a one-sided
    resolution drops them silently). The check is semantic and side-symmetric:
    every symbol either side carries must survive in the result.
    """
    our_syms = symbols_at(repo, ours, path, pattern)
    their_syms = symbols_at(repo, theirs, path, pattern)
    result_syms = symbols_at(repo, result, path, pattern)
    missing = []
    for symbol in sorted((our_syms | their_syms) - result_syms):
        on = [side for side, syms in (("ours", our_syms), ("theirs", their_syms))
              if symbol in syms]
        missing.append({"symbol": symbol, "on": on})
    return {
        "file": path,
        "ours": len(our_syms),
        "theirs": len(their_syms),
        "result": len(result_syms),
        "missing": missing,
    }


def classify_file(repo, base, ours, theirs, path):
    base_lines = show_lines(repo, base, path)
    our_lines = show_lines(repo, ours, path)
    their_lines = show_lines(repo, theirs, path)
    if our_lines is None and their_lines is None:
        raise CheckError("%s exists on neither side (malformed conflict set)" % path)
    our_added = added_lines(base_lines, our_lines)
    their_added = added_lines(base_lines, their_lines)
    our_counter = collections.Counter(our_lines or [])
    their_counter = collections.Counter(their_lines or [])
    our_missing = []
    for number, text in our_added:
        kind = classify_missing(text, their_lines or [], their_counter)
        if kind:
            our_missing.append({"line": number, "text": text, "kind": kind})
    their_missing = []
    for number, text in their_added:
        kind = classify_missing(text, our_lines or [], our_counter)
        if kind:
            their_missing.append({"line": number, "text": text, "kind": kind})
    our_lost = [row for row in our_missing if row["kind"] == "missing"]
    their_lost = [row for row in their_missing if row["kind"] == "missing"]
    if not our_lost:
        resolution = "theirs-verbatim"       # theirs already carries every ours line
    elif not their_lost:
        resolution = "ours-verbatim"         # ours already carries every theirs line
    else:
        resolution = "combine"
    return {
        "file": path,
        "ours_added": len(our_added),
        "theirs_added": len(their_added),
        "ours_missing_from_theirs": our_missing,
        "theirs_missing_from_ours": their_missing,
        "ours_deleted_kept_by_theirs": _kept(deleted_lines(base_lines, our_lines),
                                             their_counter),
        "theirs_deleted_kept_by_ours": _kept(deleted_lines(base_lines, their_lines),
                                             our_counter),
        "lossless_resolution": resolution,
    }


def _kept(deletions, other_counter):
    return [{"text": text} for _number, text in deletions if other_counter[text] > 0]


def resolution_command(row, ours_sha, theirs_sha):
    """The paste-ready way to apply a verbatim resolution.

    A shell redirect writes the worktree file and nothing else, so it works
    where a ``git checkout <rev> -- <path>`` cannot (that one writes the index).
    A ``combine`` file has no single source, so it returns "".
    """
    kind = row["lossless_resolution"]
    if kind == "theirs-verbatim":
        return "git show %s:%s > %s" % (theirs_sha, row["file"], row["file"])
    if kind == "ours-verbatim":
        return "git show %s:%s > %s" % (ours_sha, row["file"], row["file"])
    return ""


def loss_file(repo, base, ours, theirs, result, path):
    our_lines = show_lines(repo, ours, path)
    their_lines = show_lines(repo, theirs, path)
    result_lines = show_lines(repo, result, path)
    base_lines = show_lines(repo, base, path)
    if result_lines is None:
        result_counter = collections.Counter()
    else:
        result_counter = collections.Counter(result_lines)
    rows = []
    for side, side_lines, side_added in (
            ("ours", our_lines, added_lines(base_lines, our_lines)),
            ("theirs", their_lines, added_lines(base_lines, their_lines))):
        for number, text in side_added:
            kind = classify_missing(text, result_lines or [], result_counter)
            if kind:
                rows.append({"side": side, "line": number, "text": text, "kind": kind})
    markers = marker_lines(result_lines)
    unexplained = [row for row in rows if row["kind"] == "missing"]
    return {
        "file": path,
        "missing": rows,
        "unexplained": unexplained,
        "markers": [{"line": n, "text": t} for n, t in markers],
        "result_present": result_lines is not None,
    }


def _print_table(rows, columns, stream):
    if not rows:
        return
    widths = [len(name) for name in columns]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    stream.write("  ".join(name.ljust(widths[i]) for i, name in enumerate(columns)) + "\n")
    for row in rows:
        stream.write("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + "\n")


def load_declarations(path):
    """Parse a declared-deviation file. Returns (entries, error).

    A hand-authored resolution legitimately diverges from both sides: a
    superseded implementation, a comment that was rewritten, a rolled-back
    behaviour. Without a declaration those rows read exactly like a silent loss
    (t261013-06 arbitration pass 4, finding D). Every entry must name a file, a
    non-empty reason, and exactly one of ``text`` (a line) or ``symbol``; a
    malformed entry is a named refusal, never ignored. Nothing is accepted
    silently: an entry that matches no row is reported as stale.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        return None, "declared_unreadable: %s: %s" % (type(exc).__name__, exc)
    if isinstance(raw, dict):
        raw = raw.get("deviations")
    if not isinstance(raw, list) or not raw:
        return None, "declared_not_a_non_empty_list"
    entries = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            return None, "declared_entry_not_an_object:%d" % index
        path_in = entry.get("file")
        why = entry.get("why")
        why = why.strip() if isinstance(why, str) else ""
        text = entry.get("text")
        symbol = entry.get("symbol")
        has_text = isinstance(text, str) and text != ""
        has_symbol = isinstance(symbol, str) and symbol != ""
        if not isinstance(path_in, str) or not path_in.strip():
            return None, "declared_entry_missing_file:%d" % index
        if not why:
            return None, "declared_entry_missing_reason:%d" % index
        if has_text == has_symbol:
            return None, "declared_entry_needs_exactly_one_of_text_symbol:%d" % index
        entries.append({"file": path_in, "why": why, "text": text, "symbol": symbol,
                        "used": 0})
    return entries, ""


def apply_declarations(entries, rows, key, match_text):
    """Split ``rows`` into (accepted, undeclared) using the declarations.

    ``match_text`` is a callable returning (file, needle) for a row; ``key``
    names the field the needle must match (``text`` or ``symbol``).
    """
    accepted, undeclared = [], []
    for row in rows:
        file_name, needle = match_text(row)
        hit = None
        for entry in entries or []:
            if entry["file"] != file_name:
                continue
            if needle and entry[key] == needle:
                hit = entry
                break
        if hit is None:
            undeclared.append(row)
        else:
            hit["used"] += 1
            item = dict(row)
            item["declared_why"] = hit["why"]
            accepted.append(item)
    return accepted, undeclared


def build_parser():
    parser = argparse.ArgumentParser(
        description="Prove that a merge resolution kept both sides' work "
                    "(t261013-06 review C3). Read-only.")
    parser.add_argument("--repo", default=".", help="repository or worktree root (default: cwd)")
    parser.add_argument("--base", default="", help="merge base (default: git merge-base ours theirs)")
    parser.add_argument("--ours", required=True, help="the revision merged INTO (the line)")
    parser.add_argument("--theirs", required=True, help="the revision merged (the lane candidate)")
    parser.add_argument("--result", default="HEAD",
                        help="the settled revision to check (default: HEAD; loss mode only)")
    parser.add_argument("--classify", action="store_true",
                        help="name the lossless resolution per file instead of checking a result")
    parser.add_argument("--files", nargs="*", default=None,
                        help="check these paths instead of the merge-tree conflict set")
    parser.add_argument("--allow-unmerged-result", action="store_true",
                        help="loss mode: check a hand-built resolution that is not a merge "
                             "commit (both named sides are normally required as ancestors of "
                             "the result)")
    parser.add_argument("--symbol-file", default="",
                        help="loss mode: also check that every symbol either side carries in this "
                             "path survives (the registry case); use with --symbol-regex")
    parser.add_argument("--symbol-regex", default="",
                        help="the symbol pattern for --symbol-file (group 1 wins when present)")
    parser.add_argument("--declared", default="",
                        help="loss mode: a JSON file of accepted deviations "
                             "([{file, why, text|symbol}]), each with a reason; anything "
                             "undeclared stays red and an unused entry is reported as stale")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    symbol_block = None
    declarations = None
    try:
        base = args.base.strip() or merge_base(args.repo, args.ours, args.theirs)
        if args.files:
            files, source = list(args.files), "declared"
        else:
            files = staged_conflicts(args.repo)
            source = "live-merge" if files else "forecast"
            if not files:
                files = conflict_files(args.repo, base, args.ours, args.theirs)
        if not files:
            raise CheckError("no conflicted file to check (an empty set is never a pass here)")
        if bool(args.symbol_file) != bool(args.symbol_regex):
            raise CheckError("symbol_check_incomplete: --symbol-file and --symbol-regex go together")
        pattern = None
        if args.symbol_regex:
            try:
                pattern = re.compile(args.symbol_regex)
            except re.error as exc:
                raise CheckError("symbol_regex_invalid: %s (%s)" % (args.symbol_regex, exc))
        settled_missing = []
        if args.classify:
            report = [classify_file(args.repo, base, args.ours, args.theirs, path)
                      for path in files]
        else:
            if not args.allow_unmerged_result:
                settled_missing = require_settled_result(args.repo, args.ours, args.theirs,
                                                         args.result)
                if settled_missing:
                    raise CheckError(
                        "result_not_settled: %s does not contain %s — this check belongs after "
                        "the merge and its settle, not before (a plain lane tip reads as a loss "
                        "list in every file). Use --allow-unmerged-result only for a hand-built "
                        "resolution that is not a merge commit."
                        % (args.result, "/".join(settled_missing)))
            report = [loss_file(args.repo, base, args.ours, args.theirs, args.result, path)
                      for path in files]
            if pattern is not None:
                symbol_block = symbol_loss(args.repo, args.ours, args.theirs, args.result,
                                           args.symbol_file, pattern)
        if args.declared:
            declarations, derror = load_declarations(args.declared)
            if derror:
                raise CheckError("%s (--declared %s)" % (derror, args.declared))
        if declarations:
            for row in report:
                accepted, undeclared = apply_declarations(
                    declarations, row["unexplained"], "text",
                    lambda r, f=row["file"]: (f, r["text"]))
                row["declared"] = accepted
                row["unexplained"] = undeclared
            if symbol_block is not None:
                accepted, undeclared = apply_declarations(
                    declarations, symbol_block["missing"], "symbol",
                    lambda r, f=symbol_block["file"]: (f, r["symbol"]))
                symbol_block["declared"] = accepted
                symbol_block["missing"] = undeclared
    except CheckError as exc:
        payload = {"ok": False, "exit": 2, "error": str(exc), "base": args.base,
                   "ours": args.ours, "theirs": args.theirs}
        print(json.dumps(payload, ensure_ascii=False) if args.json
              else "merge_loss_check: %s" % exc, file=sys.stdout)
        return 2

    if args.classify:
        ours_sha = resolved_sha(args.repo, args.ours)
        theirs_sha = resolved_sha(args.repo, args.theirs)
        for row in report:
            row["resolution_command"] = resolution_command(row, ours_sha, theirs_sha)
        classes = collections.Counter(row["lossless_resolution"] for row in report)
        unexplained = [row for row in report
                       if any(m["kind"] == "missing" for m in row["ours_missing_from_theirs"])
                       and any(m["kind"] == "missing" for m in row["theirs_missing_from_ours"])]
        payload = {"ok": True, "exit": 0, "base": base, "ours": args.ours,
                   "theirs": args.theirs, "ours_sha": ours_sha, "theirs_sha": theirs_sha,
                   "mode": "classify", "conflict_source": source, "files": report,
                   "classes": dict(classes), "needs_combine": [row["file"] for row in unexplained]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
            return 0
        print("merge_loss_check: classify, base=%s ours=%s theirs=%s, %d files (conflict set: %s)"
              % (base[:12], args.ours, args.theirs, len(report), source))
        _print_table([[row["file"], row["ours_added"], row["theirs_added"],
                       len(row["ours_missing_from_theirs"]), len(row["theirs_missing_from_ours"]),
                       row["lossless_resolution"]] for row in report],
                     ["file", "ours+", "theirs+", "oursMissing", "theirsMissing", "resolution"],
                     sys.stdout)
        print("classes=%s" % dict(classes))
        for row in report:
            for side, key in (("ours", "ours_missing_from_theirs"),
                              ("theirs", "theirs_missing_from_ours")):
                for miss in row[key]:
                    print("  %s %s:%s %s  %s" % (row["file"], side, miss["line"], miss["kind"],
                                                 miss["text"][:100]))
        print("resolution commands (verbatim files; a combine file keeps both sides by hand):")
        for row in report:
            if row["resolution_command"]:
                print("  " + row["resolution_command"])
            else:
                print("  # %s: combine by hand, keep both sides' lines (see the lists above)"
                      % row["file"])
        return 0

    failures = [row for row in report if row["unexplained"] or row["markers"]]
    symbol_missing = list((symbol_block or {}).get("missing") or [])
    declared_rows = [item for row in report for item in row.get("declared") or []]
    declared_rows += list((symbol_block or {}).get("declared") or [])
    stale = [{"file": e["file"], "why": e["why"],
              "text": e["text"], "symbol": e["symbol"]}
             for e in (declarations or []) if e["used"] == 0]
    payload = {"ok": not (failures or symbol_missing or stale),
               "exit": 1 if (failures or symbol_missing or stale) else 0,
               "base": base, "ours": args.ours, "theirs": args.theirs, "result": args.result,
               "settled": not settled_missing, "mode": "loss", "conflict_source": source,
               "files": report, "failed_files": [row["file"] for row in failures],
               "declared_count": len(declared_rows), "stale_declarations": stale}
    if declarations is not None:
        payload["declared_file"] = args.declared
    if symbol_block is not None:
        payload["symbol_check"] = symbol_block
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return payload["exit"]
    print("merge_loss_check: result=%s base=%s ours=%s theirs=%s, %d files checked "
          "(conflict set: %s)"
          % (args.result, base[:12], args.ours, args.theirs, len(report), source))
    _print_table([[row["file"], len(row["unexplained"]), len(row.get("declared") or []),
                   len([m for m in row["missing"] if m["kind"] == "delimiter-only"]),
                   len(row["markers"]), row["result_present"]] for row in report],
                 ["file", "unexplained", "declared", "delimiterOnly", "markers", "inResult"],
                 sys.stdout)
    for row in report:
        for miss in row["missing"]:
            print("  %s %s:%s %s  %s" % (row["file"], miss["side"], miss["line"], miss["kind"],
                                         miss["text"][:100]))
        for mark in row["markers"]:
            print("  %s result:%s marker residue  %s" % (row["file"], mark["line"],
                                                         mark["text"][:100]))
    if declared_rows:
        print("declared deviations accepted: %d" % len(declared_rows))
        for item in declared_rows[:20]:
            print("  %s: %s" % (item.get("file"), item.get("declared_why", "")[:110]))
        if len(declared_rows) > 20:
            print("  ... (%d more; the JSON output carries them all)" % (len(declared_rows) - 20))
    if stale:
        print("STALE declarations (matched no row — they accept nothing): %d" % len(stale))
        for entry in stale:
            print("  %s: %s" % (entry["file"], (entry["text"] or entry["symbol"] or "")[:100]))
    if symbol_block is not None:
        print("symbol check: file=%s ours=%d theirs=%d result=%d missing=%d"
              % (symbol_block["file"], symbol_block["ours"], symbol_block["theirs"],
                 symbol_block["result"], len(symbol_block["missing"])))
        for miss in symbol_block["missing"]:
            print("  %s symbol missing from the result (on %s): %s"
                  % (symbol_block["file"], "+".join(miss["on"]), miss["symbol"]))
    if failures:
        print("FAIL: %d file(s) with an undeclared loss or marker residue" % len(failures))
        return 1
    if symbol_missing:
        print("FAIL: %d symbol(s) carried by one side are missing from the result"
              % len(symbol_missing))
        return 1
    if stale:
        print("FAIL: %d declared deviation(s) matched no row — a stale declaration accepts "
              "nothing and must be removed" % len(stale))
        return 1
    print("PASS: every added line of both sides survives in the result, or is a declared deviation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
