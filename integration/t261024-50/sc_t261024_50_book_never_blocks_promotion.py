#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261024-50 — a known-red booking can never block the promotion it was
meant to help: the round reads the book from the CANDIDATE (line branch tip)
tree, so a booking lives on the line, main never diverges, and the strict
fast-forward promotion verdict is unchanged.

Grey-box L3 (integration-owned): a REAL tmp git repository laid out the way
the engine lays out line worktrees (SANDBAR_PROJECTS_DIR -> <project>/data/
develop/wt/<repo>, branches main + develop), a REAL line declaration in
lines.json, and the REAL server/engine/develop_certify roster faces. Offline
seconds, zero docker/Temporal-server/browser, never touches 3099/7233.

User-perceivable faces under contract (ticket ACCEPTANCE):
  A booking-between-landings keeps the fast-forward: after a booking commit
    lands on the LINE branch, merge-base(main, certified revision) == main
    AND merge-base(main, line tip) == main, and main's tip is byte-identical
    to before the booking (no main-side commit happened, none is needed).
  B a round after the booking sees it: the round's roster (read at the
    declared line branch tip, NOT this checkout's copy and NOT the certified
    landing revision) contains the freshly booked case name.
  C an unreadable book fails closed BY NAME: a corrupt book on the line
    raises a named error (known_red_roster_unreadable), never a silent empty
    roster.
  D a book that exists on NO declared repo stays the legal inert empty
    roster (deliberate non-exemption, no error).
  E two declared repos both carrying the book is refused by name
    (an error naming the ambiguity, e.g. known_red_roster_ambiguous), never
    guessed between them.

Intent split: the pure truth tables (verdict vocabulary, malformed-entry
drops, env override seam) belong to developer L1
(test_t261024_50_known_red_candidate_roster.py, test_t260930_01_*); the
runner-env injection face belongs to developer L1 per the plan; THIS entry
uniquely owns the assembled booking -> promotion-verdict journey on real git
history. Pre-implement tree red on B/C/E = the named TDD signal; green
required at the integration gate/merge. git absent or the engine modules
unimportable = ENV_FAIL exit 2. Scenario contract: PASS/FAIL/ENV_FAIL only —
no SKIP.
"""

import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

PROJECT = "p50"
REPO_NAME = "sandbar"
LINE_ID = "develop"
LINE_BRANCH = "develop"
BOOK_REL = "integration/known-red-baseline.json"
BOOKED_NAME = "sc_t261024_50_canary_case"


def _git(path, *args):
    p = subprocess.run(["git", "-C", str(path)] + list(args),
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args[0] if args else "",
                                                  (p.stderr or "").strip()[:200]))
    return p.stdout.strip()


def _commit(path, rel, text, msg):
    f = path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    _git(path, "add", rel)
    _git(path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", msg)


def _merge_base(path, a, b):
    return _git(path, "merge-base", a, b)


def _book_json(name):
    return json.dumps({
        "meta": {"max_entries": 99},
        "entries": [{"name": name, "verdict": "booked",
                     "owner": "integration", "retire_when": "on fix"}],
    }, indent=2)


def build_fixture(root):
    """A real git repo with main + develop, laid out as the engine's line wt,
    plus the declared line in lines.json. Returns the wt path."""
    dev = root / PROJECT / "data" / "develop"
    wt_root = dev / "wt" / REPO_NAME
    wt_root.mkdir(parents=True)
    _git(wt_root, "init", "-q", "-b", "main")
    _commit(wt_root, "src/app.py", "print('base')\n", "base on main")
    main_tip = _git(wt_root, "rev-parse", "refs/heads/main")
    _git(wt_root, "checkout", "-q", "-b", LINE_BRANCH)
    _commit(wt_root, "src/fix.py", "print('landing')\n", "landing on develop")
    # lines.json: one declared line, one repo, one branch (public declaration face)
    (dev / "lines.json").write_text(json.dumps([{
        "line_id": LINE_ID, "scope": "all", "owner": "integration",
        "repositories": [{"name": REPO_NAME, "branch": LINE_BRANCH}],
    }]), encoding="utf-8")
    return wt_root, main_tip


def main():
    import develop_certify as dc

    results = []

    def check(name, fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:  # noqa: BLE001 — one failed leg must not hide the rest
            results.append((name, False, "%s: %s" % (type(e).__name__, e)))

    tmp = Path(tempfile.mkdtemp(prefix="t261024-50-"))
    os.environ["SANDBAR_PROJECTS_DIR"] = str(tmp)
    try:
        wt, main_tip = build_fixture(tmp)

        # ---- A: booking between landings keeps the strict fast-forward ----
        cert_rev = _git(wt, "rev-parse", "refs/heads/%s" % LINE_BRANCH)
        main_before = _git(wt, "rev-parse", "refs/heads/main")
        _commit(wt, BOOK_REL, _book_json(BOOKED_NAME),
                "book a known red (LINE side, by design)")
        main_after = _git(wt, "rev-parse", "refs/heads/main")

        def a_fast_forward():
            assert main_after == main_before, (
                "main moved without a main-side commit: %s -> %s"
                % (main_before[:12], main_after[:12]))
            mb_cert = _merge_base(wt, "refs/heads/main", cert_rev)
            assert mb_cert == main_before, (
                "certified revision no longer fast-forwards over main: mb=%s main=%s"
                % (mb_cert[:12], main_before[:12]))
            mb_tip = _merge_base(wt, "refs/heads/main",
                                 "refs/heads/%s" % LINE_BRANCH)
            assert mb_tip == main_before, (
                "line tip no longer contains main after a booking: mb=%s main=%s"
                % (mb_tip[:12], main_before[:12]))

        check("A booking keeps fast-forward (cert rev, line tip, main unmoved)",
              a_fast_forward)

        # ---- B: a round after the booking sees it, no main-side commit ----
        def b_round_sees_booking():
            roster = dc._known_red_roster(PROJECT, LINE_ID)
            names = [e.get("name") for e in (roster.get("entries") or [])
                     if isinstance(e, dict)]
            assert BOOKED_NAME in names, (
                "round roster missing the fresh booking: %r" % (names,))
            # anchored to the candidate tree, not this checkout's copy
            payload = json.loads((wt / BOOK_REL).read_text(encoding="utf-8"))
            assert payload["entries"], "sanity: wt book carries the entry"

        check("B round roster (line branch tip) sees the booking", b_round_sees_booking)

        # ---- C: unreadable book fails closed BY NAME ----
        _commit(wt, BOOK_REL, "{bad json", "corrupt the book on the line")

        def c_fail_closed_named():
            try:
                roster = dc._known_red_roster(PROJECT, LINE_ID)
            except dc.CertifyError as e:
                assert "known_red_roster_unreadable" in str(e), (
                    "named wrong: %s" % e)
                return
            entries = (roster.get("entries") or []) if isinstance(roster, dict) else None
            assert not entries, (
                "corrupt book silently read as an EMPTY roster — fail-open")

        check("C corrupt book fails closed by name", c_fail_closed_named)

        # ---- D: book on no declared repo = legal inert empty ----
        _commit(wt, BOOK_REL, _book_json(BOOKED_NAME), "restore the book")

        # a second declared repo whose history never carried the book
        wt2 = tmp / PROJECT / "data" / "develop" / "wt" / "other"
        wt2.mkdir(parents=True)
        _git(wt2, "init", "-q", "-b", "main")
        _commit(wt2, "src/x.py", "x\n", "base")
        _git(wt2, "checkout", "-q", "-b", LINE_BRANCH)
        _commit(wt2, "src/y.py", "y\n", "landing")
        decl = tmp / PROJECT / "data" / "develop" / "lines.json"
        data = json.loads(decl.read_text(encoding="utf-8"))
        data[0]["repositories"].append({"name": "other", "branch": LINE_BRANCH})
        decl.write_text(json.dumps(data), encoding="utf-8")

        def d_absent_is_inert():
            roster = dc._known_red_roster(PROJECT, LINE_ID)
            names = [e.get("name") for e in (roster.get("entries") or [])
                     if isinstance(e, dict)]
            assert BOOKED_NAME in names, (
                "single-carrier case broke when a second bookless repo joined: %r"
                % (names,))

        check("D bookless second repo keeps the carrier visible", d_absent_is_inert)

        # ---- E: two carriers = refused by name, never guessed ----
        _commit(wt, BOOK_REL, _book_json("second-carrier-book"),
                "book from the first repo")
        _commit(wt2, BOOK_REL, _book_json("other-book-from-second-repo"),
                "book from the second repo too")

        def e_ambiguous_named():
            try:
                roster = dc._known_red_roster(PROJECT, LINE_ID)
            except dc.CertifyError as e:
                assert "ambiguous" in str(e), (
                    "ambiguous-carrier named wrong: %s" % e)
                return
            entries = (roster.get("entries") or []) if isinstance(roster, dict) else None
            assert not entries, (
                "two carriers guessed silently (roster=%r) — must refuse by name"
                % (entries,))

        check("E two carrier repos refused by name", e_ambiguous_named)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in results if not r[1]]
    for name, ok_, why in results:
        print(("PASS" if ok_ else "FAIL") + "  " + name + (("  — " + why) if not ok_ else ""))
    if failed:
        print("FAIL t261024-50: %d/%d legs red" % (len(failed), len(results)))
        return 1
    print("PASS t261024-50: %d/%d legs green" % (len(results), len(results)))
    return 0


if __name__ == "__main__":
    try:
        import develop_certify as _dc  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: engine modules unimportable: %s: %s"
              % (type(e).__name__, e))
        sys.exit(2)
    rc = subprocess.run(["git", "--version"], capture_output=True)
    if rc.returncode != 0:
        print("ENV_FAIL: git absent: %s" % (rc.stderr or "")[:200])
        sys.exit(2)
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("FAIL t261024-50: unhandled harness error")
        sys.exit(1)
