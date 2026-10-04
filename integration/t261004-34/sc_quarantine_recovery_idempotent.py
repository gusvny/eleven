#!/usr/bin/env python3
"""t261004-34 scenario C: the quarantine recovery must be idempotent.

Executor request -0004: the t261004-25 recovery marks only the batch it
consumed, so a path quarantined N times comes back from the next unmarked
batch on every settle (observed restore -> lane deletes -> it is back on
t261004-18). A deliberate removal must stay removed, and a second settle must
not restore the path again.

Grey-box L3, offline, seconds; reuses the t260916-19 real-git lane fixture via
the t261004-25 shared lib (same mechanism, same tmp-repo discipline, shared
helpers are sanctioned). Requires the engine modules; unavailable = ENV_FAIL
exit 2 (no fake red, no fake green).

Cases (the recovery contract this ticket owns):
- C1 two historical batches carrying the SAME test-face path: one settle
     restores the file once and marks the path across BOTH manifests (the
     per-batch blindness dies); red before the fix (only gen0 got marked);
- C2 a second settle performs NO restore: no recovery claim in the receipt,
     manifest recovered-flags unchanged (idempotence face; red before the fix);
- C3 the lane deliberately deletes the restored file, then settles again:
     the removal is respected, the file stays gone (red before the fix);
- C4 a NEW quarantine batch for the same path arriving after the deliberate
     removal is a new human face, not an automatic restore: the file stays
     gone and the receipt names the skip.

Run: PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3;
     "$PY" -B integration/t261004-34/sc_quarantine_recovery_idempotent.py
     (cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2.
Red before implement lands is the expected TDD signal.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
for p in (os.path.join(os.path.dirname(HERE), "t261004-25"),):
    if p not in sys.path:
        sys.path.insert(0, p)
from lib_t26100425 import (  # noqa: E402
    check, engine_modules, env_fail, mk_lane, quarantine_root, rmtree, settle,
    summary,
)
from pathlib import Path

TID = "t261004-34"
LOST_REL = "server/engine/tests/test_t261004_34_lost_probe.py"
LOST_BODY = "# t261004-34: quarantined five times, must not resurrect\n"


def craft_batch(lane, shared, name, items, files):
    """Craft one historical quarantine batch (same shape as the producer)."""
    qroot = quarantine_root(lane, shared)
    batch = qroot / name
    batch.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = batch / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for it in items:
        if it.get("archive") and not it["archive"].startswith("."):
            it["archive"] = str((batch / it["archive"]).relative_to(Path(lane)))
    (batch / "manifest.json").write_text(
        json.dumps({"ticket_stage": "implement", "gen": 0,
                    "ts": int(time.time() * 1000), "items": items},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return batch


def manifest_items(batch):
    man = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    return [(it.get("path"), bool(it.get("recovered"))) for it in man["items"]]


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("engine modules unavailable (%s) - direct settle has no "
                 "stdlib substitute for these cases" % why)
    shared, aa = mods
    arch_rel = LOST_REL

    def two_batches(lane):
        b0 = craft_batch(lane, shared, "unauth-implement-gen0",
                         [{"path": LOST_REL, "xy": "??", "action": "moved",
                           "archive": arch_rel, "ts": 1}],
                         {arch_rel: LOST_BODY})
        b1 = craft_batch(lane, shared, "unauth-implement-gen1",
                         [{"path": LOST_REL, "xy": "??", "action": "moved",
                           "archive": arch_rel, "ts": 2}],
                         {arch_rel: LOST_BODY})
        return b0, b1

    print("== C1 one settle restores once and marks BOTH historical batches")
    tmp, mainrepo, lane, fork = mk_lane("t26100434-c1-")
    b0, b1 = two_batches(lane)
    r1 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/"])
    restored = Path(lane) / LOST_REL
    note1 = r1.note or ""
    check("C1a file restored once with content intact",
          restored.is_file()
          and restored.read_text(encoding="utf-8") == LOST_BODY,
          "exists=%s" % restored.is_file())
    marks = manifest_items(b0) + manifest_items(b1)
    check("C1b path marked recovered across BOTH batches",
          all(rec for _, rec in marks), "marks=%r" % (marks,))
    check("C1c receipt names the recovery with the path", LOST_REL in note1,
          "note=%r" % note1[:300])

    print("== C2 second settle restores nothing (idempotence)")
    flags_before = manifest_items(b0) + manifest_items(b1)
    r2 = settle(shared, aa, lane, TID, "implement", 2, fork,
                write_set=["docs/"])
    note2 = r2.note or ""
    check("C2a settle completes without error", r2.error in (None, ""),
          "error=%r" % r2.error)
    check("C2b receipt names a recovery hold for the path, not a recovery",
          LOST_REL in note2 and "recovery" in note2.lower()
          and "restored" not in note2.lower(),
          "note=%r" % note2[:300])
    check("C2c manifest recovered-flags unchanged",
          flags_before == manifest_items(b0) + manifest_items(b1), "")
    rmtree(tmp)

    print("== C3 deliberate removal is respected by the next settle")
    tmp, mainrepo, lane, fork = mk_lane("t26100434-c3-")
    b0, b1 = two_batches(lane)
    settle(shared, aa, lane, TID, "implement", 1, fork, write_set=["docs/"])
    if not (Path(lane) / LOST_REL).exists():
        check("C3 precheck: first settle restored the file", False,
              "recovery did not fire; cannot exercise the removal face")
    else:
        (Path(lane) / LOST_REL).unlink()
        r3 = settle(shared, aa, lane, TID, "implement", 2, fork,
                    write_set=["docs/"])
        note3 = r3.note or ""
        check("C3a file stays deleted after the next settle",
              not (Path(lane) / LOST_REL).exists(),
              "note=%r" % note3[:300])
        check("C3b receipt names the non-restore instead of staying silent",
              LOST_REL in note3 or "recover" in note3.lower(),
              "note=%r" % note3[:300])

        print("== C4 a new quarantine batch after removal is a new human face")
        craft_batch(lane, shared, "unauth-implement-gen2",
                    [{"path": LOST_REL, "xy": "??", "action": "moved",
                      "archive": arch_rel, "ts": 3}],
                    {arch_rel: LOST_BODY})
        r4 = settle(shared, aa, lane, TID, "implement", 3, fork,
                    write_set=["docs/"])
        note4 = r4.note or ""
        check("C4a deliberate removal still respected (no auto-restore)",
              not (Path(lane) / LOST_REL).exists(),
              "note=%r" % note4[:300])
        check("C4b receipt names the skip (visible, not silent)",
              LOST_REL in note4 or "recover" in note4.lower(),
              "note=%r" % note4[:300])
    rmtree(tmp)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
