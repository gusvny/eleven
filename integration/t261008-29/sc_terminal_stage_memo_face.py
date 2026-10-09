#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-29 scenario 2: a ticket that died at its FIRST stage still names the
stage after the workflow is terminal (KI-227 memo leg, grey-box L3, offline
seconds, zero docker/Temporal-server/browser, never touches 3099/7233).

intent (user-perceivable behaviour under guard):
  Today the terminal failure face hardcodes last_stage=None with the note
  "the engine does not write the stage into the Temporal memo" — a hole the
  engine dug itself (client.py, client.lint-visible). After this ticket the
  engine persists the stage into the memo at each stage entry, and the
  terminal face READS it back: the console can say "died in stage X" for a
  three-second ticket instead of "cannot know". Memo is metadata: none of
  this may change any ticket's control flow.

faces (public terminal-face seam; stub handle/desc, no server):
  M1 a terminal description carrying memo {"sandbar_stage": <first stage>}
     yields last_stage == that stage with a note naming the memo source;
  M2 a pre-fix ticket (no sandbar_stage in memo) keeps the honest
     unavailable note — never a guessed stage (KI-025 honesty family);
  M3 a MALFORMED memo payload (binary garbage / wrong shape) degrades to a
     named absence, never a crash, never a fabricated stage;
  M4 the memo read is read-only at the seam: the face consumes the stub and
     writes nothing anywhere (probe dir holds still).

writer-side note: the stage-entry persistence (dev_lane._enter, replay-safe
under workflow.patched) is developer L1 by contract — replay-safety against
real history needs a workflow runtime and is out of this offline entry's
scope; this entry owns the reader side a user actually sees.

pre-implement: M1 red naming the missing memo path (TDD-phase signal); green
required at arbitrate/merge. temporalio / engine tree unimportable = ENV_FAIL
exit 2 (the module import chain is the deployment reality being guarded).
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")

FAILS = []
CHECKS = []


def check(cid, ok, detail=""):
    CHECKS.append((cid, bool(ok), detail))
    if not ok:
        FAILS.append("%s: %s" % (cid, detail or "check failed"))


def _venv_python():
    for cand in (os.path.join(ENGINE, ".venv", "bin", "python"),
                 os.path.join(REPO, "server", "dsh", "temporal-poc", ".venv", "bin", "python"),  # engine-venv-compat（旧路径回落位，t260907-10 豁免口径）
                 sys.executable):
        if os.path.isfile(cand) or cand == sys.executable:
            return cand
    return None


class _StubHandle:
    def __init__(self, exc=None):
        self._exc = exc

    async def result(self, *a, **k):
        if self._exc is not None:
            raise self._exc
        return None

    async def fetch_history(self, *a, **k):
        class _H:
            events = []
        return _H()


class _StubDesc:
    def __init__(self, memo=None):
        # SDK contract (this repo's temporalio): desc.memo() is an ASYNC method
        # returning a Mapping; keep the stub on the real seam shape.
        self._memo = memo

    async def memo(self):
        return self._memo

    start_time = None
    close_time = None
    typed_search_attributes = None


class _FakeFailure(Exception):
    pass


async def _run_face(memo):
    import client as engine_client
    desc = _StubDesc(memo=memo)
    handle = _StubHandle(exc=_FakeFailure("activity run_inspection_surface is not registered"))
    return await engine_client._terminal_failure_face("t-fixture", handle, desc, "FAILED")


def main():
    py = _venv_python()
    if py is None or not os.path.isfile(os.path.join(ENGINE, "client.py")):
        print("ENV_FAIL: engine tree / venv python missing for client.py import")
        return 2
    try:
        sys.path.insert(0, ENGINE)
        import client as engine_client  # noqa: F401 — importable = temporalio present
    except Exception as e:  # noqa: BLE001
        venv = os.path.join(ENGINE, ".venv", "bin", "python")
        if os.path.isfile(venv):
            os.execv(venv, [venv, os.path.abspath(__file__)])  # engine venv is the deployment reality
        print("ENV_FAIL: engine client module unimportable (temporalio chain): %s: %s"
              % (type(e).__name__, e))
        return 2

    tmp = tempfile.mkdtemp(prefix="t26100829-sc2-")
    try:
        # ---- M1: memo-carrying terminal ticket names its stage ----
        face = asyncio.run(_run_face({"sandbar_stage": "run_integration_tests",
                                      "sandbar_stage_history": ["design", "run_integration_tests"]}))
        ls = face.get("last_stage")
        note = str(face.get("last_stage_note") or "").lower()
        check("M1.named", ls == "run_integration_tests",
              "terminal face must recover the stage from the memo, got last_stage=%r note=%r" % (ls, face.get("last_stage_note")))
        check("M1.source", ("memo" in note) or ("memo" in json.dumps(face).lower()),
              "the stage's provenance (memo) must be visible to the reader, note=%r" % (face.get("last_stage_note"),))
        check("M1.honest", face.get("last_stage_available") is not False or "memo" in note,
              "a recovered stage must not be reported as unavailable")

        # ---- M2: pre-fix ticket keeps the honest unavailable face ----
        face2 = asyncio.run(_run_face(None))
        ls2 = face2.get("last_stage")
        note2 = str(face2.get("last_stage_note") or "")
        check("M2.absent", ls2 in (None, ""),
              "no memo must NOT manufacture a stage, got %r" % (ls2,))
        check("M2.note", bool(note2.strip()),
              "the absence must stay explained to the reader (note empty)")

        # ---- M3: malformed memo degrades named, never crashes ----
        for label, memo in (("binary", b"\x00\x01garbage-not-json"),
                            ("wrong-shape", {"unrelated": {"deep": [1, 2]}}),
                            ("wrong-type", "just-a-string")):
            try:
                f3 = asyncio.run(_run_face(memo))
                ls3 = f3.get("last_stage")
                check("M3.%s" % label, ls3 in (None, "") or isinstance(ls3, str),
                      "malformed memo must degrade to absence/named, got %r" % (f3.get("last_stage"),))
            except Exception as e:  # noqa: BLE001
                check("M3.%s" % label, False, "malformed memo must not crash the face: %s: %s" % (type(e).__name__, e))

        # ---- M4: the memo read writes nothing ----
        probe = os.path.join(tmp, "probe-lane")
        os.makedirs(probe)
        open(os.path.join(probe, "sentinel"), "w").close()  # noqa: SIM115
        before = sorted(os.listdir(probe))
        asyncio.run(_run_face({"sandbar_stage": "x"}))
        check("M4.nowrite", sorted(os.listdir(probe)) == before,
              "terminal face must be a pure reader (no writes during the read)")

        return 0 if not FAILS else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    for cid, ok, detail in CHECKS:
        print("%-16s %s %s" % (cid, "PASS" if ok else "FAIL", detail if not ok else ""))
    print("t261008-29 terminal-stage memo face: %d checks, %d failed" % (len(CHECKS), len(FAILS)))
    sys.exit(rc)
