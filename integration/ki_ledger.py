#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ki_ledger.py — the machine-readable mirror of the KI ledger (261020).

Why this exists: `notes/debts/known-issues.md` holds 294 answers in prose, and
every consumer that needs one of them greps a 6000-line Chinese document. During
the 261019 night that cost time on every fault: "is this already known?", "is it
fixed?", "which ticket fixed it?" were all manual reads, and two of tonight's
faults were re-discovered as if they were new.

The prose stays the SOURCE (host rule: notes/ is a knowledge ledger a person
writes). This tool derives a JSONL mirror from it and fails when the mirror and
the prose drift, so:
  * a machine can ask "open KIs" without parsing prose;
  * a human edit cannot silently disagrees with what tools read;
  * the ids stay single-sourced (the prose), never a second hand-kept list.

Two shapes live in the prose and both are read:
  * table rows `| KI-<n> | title | severity | status | locator |` (the older
    entries). Status: open / fixed / wontfix / obsolete.
  * `## KI-<id>` sections (the newer ULID entries). Status is derived from the
    section's own trailing marker: 未修 => open, 已修/已直修/已修好 => fixed,
    otherwise the section keeps the status it declares (default open), and the
    entry says which parts were derived so nothing is invented silently.

Usage:
    python3 integration/ki_ledger.py --check      # exit 1 on drift (CI face)
    python3 integration/ki_ledger.py --write      # regenerate the mirror
    python3 integration/ki_ledger.py --status open   # list ids by status
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: 261020 (host order): the ledger lives in the project store, OUTSIDE git; the
#: repository keeps only a pointer file plus pinned entries. Store wins when both
#: exist, because the store is the ledger a person writes.
STORE_DIR = Path.home() / ".sandbar" / "projects" / "sandbar" / "kb"
STORE_PROSE = STORE_DIR / "known-issues.md"
STORE_MIRROR = STORE_DIR / "known-issues.jsonl"
REPO_PROSE = REPO / "notes" / "debts" / "known-issues.md"
#: the store prose is optional now (jsonl-only store); when it is absent the
#: check validates the mirror instead of comparing two files.
PROSE = STORE_PROSE if STORE_PROSE.is_file() else REPO_PROSE
#: the MIRROR is the store ledger whenever the store has one (jsonl-only store is
#: the default now); the repo sibling is only a fallback for a checkout with no store
MIRROR = STORE_MIRROR if STORE_MIRROR.is_file() else REPO_PROSE.with_suffix(".jsonl")

ID_RE = re.compile(r"KI-[0-9A-Z]{2,}")
TABLE_ROW_RE = re.compile(r"^\|\s*(KI-[0-9A-Z]+)\s*\|(.*)$")
SECTION_RE = re.compile(r"^##\s+(KI-[0-9A-Z]+)\s*(.*)$")
STATUS_WORDS = {
    "open": "open",
    "未修": "open",
    "fixed": "fixed",
    "已修": "fixed",
    "已直修": "fixed",
    "已修好": "fixed",
    "wontfix": "wontfix",
    "obsolete": "obsolete",
    "退役": "obsolete",
}


def _status_of(text):
    """The first status word this text declares, or '' (pure, never guessed)."""
    low = str(text or "").lower()
    best = ("", -1)
    for word, status in STATUS_WORDS.items():
        i = low.find(word.lower())
        if i >= 0 and (best[1] < 0 or i < best[1]):
            best = (status, i)
    return best[0]


def parse(text):
    """Parse the prose into records, keyed by id (pure function).

    Returns {"rows": {id: record}, "problems": [str]} — problems are the shapes
    this reader cannot trust (a table row with too few columns, a duplicate id
    with two different titles), and are reported rather than dropped."""
    rows = {}
    problems = []
    in_table = False
    body_of = {}
    current = None
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        m = SECTION_RE.match(line)
        if m:
            current = m.group(1)
            body_of.setdefault(current, [])
            kid, rest = m.group(1), m.group(2)
            status = _status_of(rest)
            rec = rows.setdefault(kid, {"id": kid, "sources": []})
            rec["sources"].append("section")
            rec.setdefault("line", lineno)
            if not rec.get("title"):
                # the section header is prose: strip the markdown bold and cut at
                # the first parenthetical (the parenthetical holds provenance, not
                # the finding) so a reader gets the claim, not the whole paragraph.
                t = " ".join(rest.replace("**", "").split())
                for sep in ("（", "("):
                    if sep in t:
                        t = t.split(sep, 1)[0]
                rec["title"] = t.strip()[:160]
            if status:
                rec["status"] = status
                rec.setdefault("status_from", "section")
            continue
        if current is not None and raw.strip():
            body_of[current].append(raw.rstrip())
            continue
        if line.startswith("|") and "KI-" in line:
            m = TABLE_ROW_RE.match(line)
            if not m:
                in_table = True
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                problems.append("line %d: table row has %d columns" % (lineno, len(cells)))
                continue
            kid = cells[0]
            title, severity, status, locator = cells[1], cells[2], cells[3], \
                (cells[4] if len(cells) > 4 else "")
            rec = rows.setdefault(kid, {"id": kid, "sources": []})
            rec["sources"].append("table")
            rec["title"] = rec.get("title") or title
            rec.setdefault("severity", severity)
            rec.setdefault("locator", locator)
            st = _status_of(status)
            if st and "status" not in rec:
                rec["status"] = st
                rec["status_from"] = "table"
            rec.setdefault("line", lineno)
            in_table = True
    for kid, rec in rows.items():
        body = "\n".join(body_of.get(kid, [])).strip()
        if body:
            rec["body"] = body
    for rec in rows.values():
        rec.setdefault("status", "open")
        rec.setdefault("status_from", "default")
        rec["sources"] = sorted(set(rec["sources"]))
        rec["title"] = " ".join(str(rec.get("title") or "").split())
    return {"rows": rows, "problems": problems}


def render(parsed):
    """The mirror's bytes: one JSON object per line, ids sorted (stable diffs)."""
    out = []
    for kid in sorted(parsed["rows"]):
        out.append(json.dumps(parsed["rows"][kid], ensure_ascii=False, sort_keys=True))
    return "\n".join(out) + ("\n" if out else "")


def drift(parsed, mirror_text):
    """Problems between the prose and the mirror (pure). Empty list = in sync."""
    problems = list(parsed["problems"])
    have = {}
    for lineno, line in enumerate(str(mirror_text or "").splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except ValueError as e:
            problems.append("mirror line %d is not JSON: %s" % (lineno, e))
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            problems.append("mirror line %d has no id" % lineno)
            continue
        have[rec["id"]] = rec
    prose_ids, mirror_ids = set(parsed["rows"]), set(have)
    for kid in sorted(prose_ids - mirror_ids):
        problems.append("%s is in the prose but not in the mirror (run --write)" % kid)
    for kid in sorted(mirror_ids - prose_ids):
        problems.append("%s is in the mirror but the prose no longer has it" % kid)
    for kid in sorted(prose_ids & mirror_ids):
        a, b = parsed["rows"][kid], have[kid]
        if a.get("status") != b.get("status"):
            problems.append("%s status drift: prose=%r mirror=%r"
                            % (kid, a.get("status"), b.get("status")))
        if " ".join(str(a.get("title") or "").split()) != " ".join(str(b.get("title") or "").split()):
            problems.append("%s title drift: prose changed, mirror is stale" % kid)
    return problems


def render_md(records):
    """A human-readable view of the mirror (261020). The md is a RENDERING now —
    the store keeps one jsonl; this prints the same text on demand so nobody has
    to read escaped JSON strings to understand a fault."""
    out = ["# Known issues (rendered from the store mirror)", ""]
    for rec in sorted(records, key=lambda r: (r.get("id") or "")):
        title = rec.get("title") or ""
        out.append("## %s %s" % (rec.get("id"), title))
        meta = ["status=%s" % rec.get("status", "open")]
        if rec.get("severity"):
            meta.append("severity=%s" % rec["severity"])
        if rec.get("locator"):
            meta.append("locator=%s" % rec["locator"])
        out.append("_" + " · ".join(meta) + "_")
        if rec.get("body"):
            out.append("")
            out.append(rec["body"])
        out.append("")
    return "\n".join(out) + "\n"


def load_mirror(path):
    """Read the store ledger; every malformed line is named (never skipped)."""
    recs, problems = [], []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return [], ["cannot read %s: %s" % (path, e)]
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except ValueError as e:
            problems.append("line %d is not JSON: %s" % (lineno, e))
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            problems.append("line %d has no id" % lineno)
            continue
        recs.append(rec)
    return recs, problems


def append_record(path, rec):
    """Append ONE record (a person never hand-edits JSON). Refuses a duplicate id."""
    recs, problems = load_mirror(path)
    if problems:
        return "refused: the ledger has %d malformed line(s): %s" % (len(problems), problems[0])
    if any(r.get("id") == rec.get("id") for r in recs):
        return "refused: %s is already in the ledger (an id is never reused)" % rec.get("id")
    with open(str(path), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return ""


def set_status(path, kid, status):
    """Rewrite one record's status in place (whole-file rewrite, stable order)."""
    recs, problems = load_mirror(path)
    if problems:
        return "refused: the ledger has %d malformed line(s): %s" % (len(problems), problems[0])
    hit = [r for r in recs if r.get("id") == kid]
    if not hit:
        return "refused: %s is not in the ledger" % kid
    if status not in set(STATUS_WORDS.values()):
        return "refused: status must be one of %s" % sorted(set(STATUS_WORDS.values()))
    hit[0]["status"] = status
    Path(path).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in recs) + "\n",
        encoding="utf-8")
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="KI store ledger (jsonl), with a prose bridge")
    ap.add_argument("--check", action="store_true", help="fail when the ledger is unsound or drifts from prose")
    ap.add_argument("--write", action="store_true", help="regenerate the jsonl from a prose ledger")
    ap.add_argument("--render", action="store_true", help="print the human-readable view")
    ap.add_argument("--status", default="", help="list ids whose status is this value")
    ap.add_argument("--set-status", nargs=2, metavar=("ID", "STATUS"), help="set one record's status")
    ap.add_argument("--add-json", default="", help="append one record given as JSON")
    ap.add_argument("--prose", default="", help="an explicit prose ledger to read (bridge mode)")
    ap.add_argument("--mirror", default=str(STORE_MIRROR), help="the jsonl ledger")
    args = ap.parse_args(argv)

    mirror_path = Path(args.mirror)
    prose_path = Path(args.prose) if args.prose else STORE_PROSE
    legacy = prose_path.is_file()

    if args.write:
        if not legacy:
            print("refused: --write needs a prose ledger to derive from (%s is absent)" % prose_path)
            return 2
        parsed = parse(prose_path.read_text(encoding="utf-8"))
        mirror_path.write_text(render(parsed), encoding="utf-8")
        print("wrote %d records to %s" % (len(parsed["rows"]), mirror_path))
        for p in parsed["problems"]:
            print("PROBLEM %s" % p)
        return 0

    if args.add_json:
        try:
            rec = json.loads(args.add_json)
        except ValueError as e:
            print("refused: --add-json is not JSON: %s" % e)
            return 2
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            print("refused: the record needs an id")
            return 2
        err = append_record(mirror_path, rec)
        print("refused: %s" % err if err else "appended %s" % rec["id"])
        return 1 if err else 0

    if args.set_status:
        kid, status = args.set_status
        err = set_status(mirror_path, kid, status)
        print("refused: %s" % err if err else "status of %s set to %s" % (kid, status))
        return 1 if err else 0

    recs, problems = load_mirror(mirror_path)

    if args.render:
        for p in problems:
            print("PROBLEM %s" % p)
        sys.stdout.write(render_md(recs))
        return 0 if not problems else 1

    if args.status:
        ids = sorted(r["id"] for r in recs if r.get("status") == args.status)
        print(json.dumps({"status": args.status, "count": len(ids), "ids": ids},
                         ensure_ascii=False))
        return 0

    # --check: soundness of the ledger itself, plus prose agreement when a prose
    # ledger still exists (the bridge mode a migration uses).
    seen = set()
    for r in recs:
        kid = r.get("id")
        if kid in seen:
            problems.append("%s appears twice (an id is never reused)" % kid)
        seen.add(kid)
        if r.get("status") not in set(STATUS_WORDS.values()):
            problems.append("%s has an unknown status %r" % (kid, r.get("status")))
    if not recs:
        problems.append("the ledger holds no records: %s" % mirror_path)
    if legacy:
        parsed = parse(prose_path.read_text(encoding="utf-8"))
        problems.extend(x for x in drift(parsed, mirror_path.read_text(encoding="utf-8"))
                        if x not in problems)
    if problems:
        for p in problems[:40]:
            print("DRIFT %s" % p)
        print("ki ledger: %d problem(s)" % len(problems))
        return 1
    print("ki ledger clean: %d records%s"
          % (len(recs), " (prose bridge agrees)" if legacy else " (jsonl-only store)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
