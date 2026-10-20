#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261019-12 — the epic registry lives in docs/epics with ONE enforced boolean.

Grey-box L3 (integration-owned), ticket t261019-12, authority
docs/design/epic-registry-v1.md (4561583e): retired is the only state —
false accepts tickets, true refuses them BY NAME at the single validation
point; the store is docs/epics and notes/epics is a corpse, never a
fallback. The REAL server/engine/shared.py public faces
(resolve_epics_dir / validate_epic_code) over fixture directories.
Offline seconds, zero docker/Temporal/browser, never touches 3099/7233.

User-perceivable contract under test:
  A THE REFUSAL — a retired:true epic refuses a new ticket at
    validate_epic_code: ValueError naming the epic code, the FILE IT READ
    (absolute, under the resolved dir) and `retired: true`, in the same
    voice as the unknown-code refusal. A greyed-out row without this
    refusal is a comment, not a rule.
  B FAIL-CLOSED — malformed input never reads as "accepting": a document
    with no front-matter, an empty file, a non-boolean retired (yes/no/
    True/1), or a truncated block is refused with a NAMED reason. Only the
    literal `retired: false` accepts.
  C ACCEPTANCE + UNKNOWN-VOICE REGRESSION — retired:false accepts; an
    empty code passes (tickets without an epic); an unknown code still
    refuses naming the queried directory and the existing codes (the old
    voice must not degrade).
  D THE HARD CUT — the default resolution is <root>/docs/epics at BOTH
    anchor levels (engine default and project-home step); a missing
    docs/epics is a named error, and a same-named file in notes/epics does
    NOT satisfy the check (the silent second source must not resurrect).
  E THE VISIBLE OVERRIDE — SANDBAR_EPICS_DIR still wins when set: an
    explicit operator override is a face, not a fallback, and stays
    observable.

Intent split (no intent-level duplication): the front-matter parser unit
matrix and the refusal-message copy details belong to developer L1
(server/engine/tests); the /api/epics route face and the dead close/status
routes belong to sc_t26101912_epics_api_store_move; the Epics tab render
belongs to the executor-panel tests. This entry owns the enforcement
journey on the real validation point and the store-move resolution face.

Pre-implement tree: A/B/D/E red = the named TDD signal; green required at
the integration gate / merge. shared.py unimportable = ENV_FAIL exit 2.
Scenario contract: PASS/FAIL/ENV_FAIL only — no SKIP.
"""

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

import shared  # noqa: E402

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


def doc(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def fm(code, retired=None, started="2026-10-19"):
    lines = ["---", f"code: {code}"]
    if retired is not None:
        lines.append(f"retired: {retired}")
    lines.append(f"started: {started}")
    lines.append("summary: One English sentence.")
    lines += ["---", "", f"# {code}", "", "Intent and problem.", ""]
    return "\n".join(lines)


def refused(fn):
    """Run fn, return the ValueError message or None."""
    try:
        fn()
        return None
    except ValueError as e:
        return str(e)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="integ-t26101912-"))
    saved_env = os.environ.pop("SANDBAR_EPICS_DIR", None)
    try:
        base = tmp / "repo"
        good = fm("live-epic", retired="false")
        dead = fm("dead-epic", retired="true")

        # ---------------------------------------------------------- A. the refusal
        print("== A retired:true refuses a new ticket, naming the file it read")
        docs = base / "docs" / "epics"
        doc(docs / "live-epic.md", good)
        doc(docs / "dead-epic.md", dead)
        d = docs  # the fixture dir, passed explicitly (project-aware callers do the same)
        msg = refused(lambda: shared.validate_epic_code("dead-epic", d))
        ok(msg is not None, "retired:true -> refused, not accepted")
        ok(bool(msg) and "dead-epic" in msg, "refusal names the epic code")
        ok(bool(msg) and "retired: true" in msg, "refusal carries the retired: true fact")
        ok(bool(msg) and str(docs / "dead-epic.md") in msg,
           "refusal names the file it read (absolute, under the resolved dir)")
        unknown = refused(lambda: shared.validate_epic_code("no-such-epic", d))
        ok(bool(unknown) and "no-such-epic" in unknown and str(d) in unknown,
           "same voice as the unknown-code refusal (code + directory named)")
        # the refusal reaches a caller even when the UI face is gone: the error
        # type is ValueError, the engine's epic funnel already propagates it
        ok(isinstance(shared.validate_epic_code("live-epic", d), str),
           "retired:false epic still validates to itself")

        # ---------------------------------------------------------- B. fail-closed
        print("== B malformed front-matter is retired-by-defect, never accepting")
        for i, body in enumerate([
            "# no front matter at all\n",                # missing block
            "",                                          # empty file
            "---\ncode: x\nretired: yes\n---\n",         # non-boolean (yes)
            "---\ncode: x\nretired: True\n---\n",        # non-literal (True)
            "---\ncode: x\nretired: 1\n---\n",           # non-boolean (1)
            "---\ncode: x\nretired:\n---\n",             # empty value
            "---\ncode: x\nretired: false\n",            # truncated block
        ]):
            p = docs / f"defect-{i}.md"
            doc(p, body)
            m = refused(lambda pp=p: shared.validate_epic_code(pp.stem, d))
            ok(m is not None, f"malformed doc {i} -> refused (fail-closed)")
            ok(bool(m) and p.name in m, f"malformed doc {i} refusal names the file")

        # ------------------------------------------- C. acceptance + unknown voice
        print("== C retired:false accepts; empty code passes; unknown voice intact")
        ok(shared.validate_epic_code("live-epic", d) == "live-epic",
           "retired:false accepts the ticket")
        ok(shared.validate_epic_code("", d) == "", "empty code passes (no epic is legal)")
        shape = refused(lambda: shared.validate_epic_code("BAD_SHAPE", d))
        ok(bool(shape) and "illegal epic code shape" in shape,
           "shape rejection voice unchanged")

        # ------------------------------------------------------- D. the hard cut
        print("== D the store is docs/epics; notes/epics is not a fallback")
        ok(shared.resolve_epics_dir("").name == "epics"
           and shared.resolve_epics_dir("").parent.name == "docs",
           "engine anchor resolves to <root>/docs/epics")
        proj = tmp / "projhome"
        # project-home step: an unknown key is a named fail-closed refusal; a
        # registered key resolves under that project's home with the tail
        # docs/epics — never notes/epics
        m4 = refused(lambda: shared.resolve_epics_dir("no-such-proj-key"))
        ok(bool(m4) and "no-such-proj-key" in m4,
           "unknown project key -> named refusal (fail-closed resolution)")
        resolved = shared.resolve_epics_dir("sandbar")
        ok(resolved.name == "epics" and resolved.parent.name == "docs",
           "project-step resolution ends in docs/epics, never notes/epics")
        # missing docs/epics is a named error, not an empty success
        empty_root = tmp / "empty"
        (empty_root / "docs").mkdir(parents=True)
        # validate against a dir that does not exist
        m2 = refused(lambda: shared.validate_epic_code("any-code", empty_root / "docs" / "epics"))
        ok(m2 is not None and "any-code" in m2,
           "missing docs/epics -> named refusal, never a silent accept")
        # the corpse must not resurrect: same-named live doc in notes/epics only
        corpse_root = tmp / "corpse"
        doc(corpse_root / "notes" / "epics" / "ghost.md", good)
        m3 = refused(lambda: shared.validate_epic_code(
            "ghost", corpse_root / "docs" / "epics"))
        ok(m3 is not None, "a live doc under notes/epics does NOT satisfy the check")

        # --------------------------------------------------- E. the visible override
        print("== E SANDBAR_EPICS_DIR override stays visible, not a fallback")
        override = tmp / "override-epics"
        doc(override / "ov-epic.md", good)
        os.environ["SANDBAR_EPICS_DIR"] = str(override)
        ok(str(shared.resolve_epics_dir("")) == str(override),
           "env override wins when explicitly set")
        ok(shared.validate_epic_code("ov-epic",
                                     shared.resolve_epics_dir("")) == "ov-epic",
           "override dir serves validation when set")
        os.environ.pop("SANDBAR_EPICS_DIR", None)
        ok(str(shared.resolve_epics_dir("")) != str(override),
           "unsetting the env returns to the docs/epics anchor")

    except Exception:
        traceback.print_exc()
        print(f"PASS={PASS} FAIL={FAIL} (exception -> FAIL)")
        return 1
    finally:
        if saved_env is not None:
            os.environ["SANDBAR_EPICS_DIR"] = saved_env
        else:
            os.environ.pop("SANDBAR_EPICS_DIR", None)
        # L8 tmp hygiene: every exit path reclaims the fixture dir (t261019-24 lane
        # round: the mkdtemp call site above had no reclaim verb on the synced file).
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
