#!/usr/bin/env python3
"""regen_coverage_rows.py — re-capture the real coverage archive rows.

Ticket t261026-11. The checked-in fixtures/coverage-real.json must be a
capture of the archive's own reading, not an invented view model. When a live
project store is reachable (this lane's sandbox has none), this script
re-captures:

  1. rows   — the archive record rows the coverage reader consumes
             (<projects>/<key>/data/coverage/**, the recordsToAttempts
             contract: {instance, period, reason?, spawn?{ticket_id,error?}}).
  2. periods — the per-period per-instance report slots the panel's archive
             read hands buildCoverage ({period, reports:{<inst>:{ok,report}}}).

Run on a machine with the store:
  SANDBAR_PROJECTS_DIR=<root> SANDBAR_PROJECT_KEY=<key> \
    python3 integration/t261026-11/fixtures/regen_coverage_rows.py

It reads only; it overwrites the fixture in place and prints the capture
provenance (root, key, row count) on stdout.
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    root = os.environ.get("SANDBAR_PROJECTS_DIR")
    key = os.environ.get("SANDBAR_PROJECT_KEY")
    if not root or not key:
        print("need SANDBAR_PROJECTS_DIR and SANDBAR_PROJECT_KEY", file=sys.stderr)
        return 2
    cov_dir = Path(root) / key / "data" / "coverage"
    if not cov_dir.is_dir():
        print(f"no coverage archive at {cov_dir}", file=sys.stderr)
        return 2
    rows = []
    periods = {}
    for p in sorted(cov_dir.rglob("*.json")):
        try:
            docs = json.loads(p.read_text())
        except Exception as e:
            print(f"skip unreadable {p}: {e}", file=sys.stderr)
            continue
        for d in docs if isinstance(docs, list) else [docs]:
            if isinstance(d, dict) and d.get("period") and (d.get("instance") or d.get("instance_id")):
                rows.append(d)
    if not rows:
        print("no record rows captured", file=sys.stderr)
        return 2
    instances = sorted({(r.get("instance") or r.get("instance_id")) for r in rows})
    fixture = {
        "_provenance": f"captured from {cov_dir} (key={key}); see fixtures/README.md",
        "instances": instances,
        "rows": rows,
        # periods: real report slots come from the archive read; the capture
        # above keeps rows only — re-run the panel's own reader (t261009-49
        # engine face) to fill periods, or ship rows-only and let the
        # scenario build periods from the ok-slots the reader produced.
        "periods": [],
    }
    out = Path(__file__).with_name("coverage-real.json")
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=1))
    print(f"captured rows={len(rows)} instances={instances} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
