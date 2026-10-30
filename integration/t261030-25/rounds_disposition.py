#!/usr/bin/env python3
"""Disposition of fabricated round directories (t261030-25, KI-429).

A ``run-*`` directory under a project's ``data/develop/rounds/`` is FABRICATED
when every revision its ``face.json`` cites is not a commit object in the repo
the round claims to judge. Two modes:

- ``--manifest``: read-only. Capture each fabricated directory (id, revisions,
  face.json, suite.log) into a JSON manifest and print the classification.
- ``--apply --manifest FILE``: delete exactly the directories the manifest
  names, then re-check that nothing fabricated is left. The manifest is the
  evidence; the live face stops carrying a green round nobody ran (the face's
  own rolling retention prunes by age, so deleting a fabricated round is what
  retention would have done — only now the reason is recorded).

The delivery ledger is NOT touched here: its rows are append-only facts, and a
correction is another row (the freeze this incident opened was released with a
named ``freeze_change`` row at seq 801). Only the face artifacts move.

Usage:
  python3 integration/t261030-25/rounds_disposition.py --manifest OUT.json
  python3 integration/t261030-25/rounds_disposition.py --apply --manifest OUT.json
"""

import argparse
import json
import subprocess
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib_real_root_watch as watch  # noqa: E402


def is_commit(repo_path, revision):
    try:
        p = subprocess.run(["git", "-C", str(repo_path), "cat-file", "-e",
                            "%s^{commit}" % revision],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def rounds_dir(project_key, root=None):
    base = pathlib.Path(root) if root else watch.project_dir(project_key)
    return base / "data" / "develop" / "rounds"


def classify(project_key, repo_path, root=None):
    """Return (fabricated, real, other) listings for one project's face."""
    out = {"fabricated": [], "real": [], "pointer": []}
    rdir = rounds_dir(project_key, root)
    if not rdir.is_dir():
        return out
    for entry in sorted(rdir.iterdir()):
        if not entry.is_dir() or not entry.name.startswith("run-"):
            out["pointer"].append(entry.name)
            continue
        face_path = entry / "face.json"
        try:
            face = json.loads(face_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            face = {}
        revisions = face.get("revision") if isinstance(face, dict) else {}
        pairs = list(revisions.items()) if isinstance(revisions, dict) else []
        reach = [(repo, rev, is_commit(repo_path, rev)) for repo, rev in pairs]
        record = {"run_id": entry.name, "path": str(entry),
                  "revisions": [{"repo": r, "revision": v, "reachable": ok}
                                for r, v, ok in reach],
                  "face": face}
        try:
            record["suite_log"] = (entry / "suite.log").read_text(
                encoding="utf-8")
        except OSError:
            record["suite_log"] = None
        if any(not ok for _r, _v, ok in reach) or not reach:
            out["fabricated"].append(record)
        else:
            out["real"].append(record)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="sandbar")
    ap.add_argument("--repo", default="", help="the repo the revisions claim")
    ap.add_argument("--root", default="", help="watch a substituted project dir")
    ap.add_argument("--manifest", default="")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    repo_path = args.repo or str(pathlib.Path(__file__).resolve().parents[2])
    state = classify(args.project, repo_path, root=args.root or None)
    for bucket in ("fabricated", "real", "pointer"):
        print("%s: %d" % (bucket, len(state[bucket])), file=sys.stderr)
    for rec in state["fabricated"]:
        print("  FABRICATED %s revisions=%r"
              % (rec["run_id"],
                 [(r["repo"], r["revision"][:10]) for r in rec["revisions"]]),
              file=sys.stderr)
    for rec in state["real"]:
        print("  REAL %s revisions=%r"
              % (rec["run_id"],
                 [(r["repo"], r["revision"][:10]) for r in rec["revisions"]]),
              file=sys.stderr)
    if not args.apply:
        payload = {"project": args.project, "repo": repo_path, "state": state}
        if args.manifest:
            pathlib.Path(args.manifest).write_text(
                json.dumps(payload, indent=1) + "\n", encoding="utf-8")
            print("manifest written: %s" % args.manifest, file=sys.stderr)
        return 0
    if not args.manifest:
        ap.error("--apply needs the manifest it is executing")
    payload = json.loads(pathlib.Path(args.manifest).read_text(
        encoding="utf-8"))
    removed = []
    for rec in payload["state"]["fabricated"]:
        target = pathlib.Path(rec["path"])
        if not target.exists():
            continue  # already pruned by a later round's retention
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()
        removed.append(rec["run_id"])
        print("removed %s" % rec["run_id"], file=sys.stderr)
    after = classify(args.project, repo_path, root=args.root or None)
    print("remaining fabricated: %d" % len(after["fabricated"]), file=sys.stderr)
    print(json.dumps({"removed": removed,
                      "remaining_fabricated": [r["run_id"] for r in
                                               after["fabricated"]]},
                     indent=1))
    return 0 if not after["fabricated"] else 1


if __name__ == "__main__":
    sys.exit(main())
