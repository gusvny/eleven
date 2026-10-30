#!/usr/bin/env python3
"""L1: the round's live state is keyed by run id and bound to its owner
(t261030-19, KI-421).

Measured 2026-10-29/30: the tick was killed, its runner (spawned in its own
session) kept running and kept writing the counts of a round that no longer
existed; when the scheduler later started a round, BOTH wrote
``<develop>/rounds/current.json`` and its ``revision`` flapped between two
trees (8d38ece0 vs 99c65939). A reader was then misled about which tree was
being judged.

The rules pinned here, by construction with real processes:

- A writer whose OWNER (the tick that spawned it) is gone writes nothing
  more: it lands ONE terminal receipt naming ``owner_gone:<pid>`` and then
  every further publish is a no-op (no counts, no pointer refresh).
- A live round's pointer is never overwritten by a later round; the pointer
  is keyed by run id, so a round keeps its own pointer across the relabel to
  the ledger run id and retires exactly that pointer when it finishes.
- A pointer whose round died is taken over by the next round AND the takeover
  is written into the new round's face (``pointer_takeover`` names the dead
  run id and the revision a reader was seeing), so "a round is running now"
  and "the last round died" never read the same.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEG = HERE.parent
sys.path.insert(0, str(INTEG))

import lib_round_face as L  # noqa: E402


#: A real round process: publishes its live face with its own revision and
#: then holds (or, in ``loop`` mode, keeps publishing like a watcher tick).
ROUND_CHILD = r'''
import json
import os
import sys
import time

integ, dev, run_id, revision, report = sys.argv[1:6]
mode = sys.argv[6] if len(sys.argv) > 6 else "hold"
sys.path.insert(0, integ)
import lib_round_face as L

owner = os.environ.get("CHILD_OWNER_PID", "").strip()
owner_pid = int(owner) if owner.isdigit() else None
writer = L.FaceWriter(dev, run_id, "develop-buffer",
                      {"sandbar": revision}, owner_pid=owner_pid)
writer.start()
with open(report, "w", encoding="utf-8") as fh:
    json.dump({"pid": os.getpid(), "run_id": run_id}, fh)
if mode == "hold":
    # A fixture round's LIFETIME: the test itself kills this process.
    # SANCTIONED-WAIT: lifetime, not an awaited bound.
    time.sleep(600)
else:
    stamps = []
    for _ in range(40):
        writer.merge_progress(L.snapshot_progress("PASS [sc_1] (0.1s)"))
        writer.publish()
        face = os.path.join(dev, "rounds", run_id, "face.json")
        try:
            stamps.append(os.stat(face).st_mtime_ns)
        except OSError:
            stamps.append(None)
        time.sleep(0.05)
    with open(report + ".stamps", "w", encoding="utf-8") as fh:
        json.dump(stamps, fh)
'''


# ---- helpers ---------------------------------------------------------------

def write_child(tmp_path):
    p = tmp_path / "round_child.py"
    p.write_text(ROUND_CHILD, encoding="utf-8")
    return p


def spawn_child(script, dev, run_id, revision, report, mode, owner_pid=None):
    env = dict(os.environ)
    if owner_pid is not None:
        env["CHILD_OWNER_PID"] = str(owner_pid)
    return subprocess.Popen(
        [sys.executable, str(script), str(INTEG), str(dev), run_id,
         revision, str(report), mode],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def wait_for(path, budget_s=30.0):
    deadline = time.time() + budget_s
    while time.time() < deadline:
        if Path(path).exists():
            return True
        time.sleep(0.02)
    return False


def kill_hard(proc):
    if proc.poll() is None:
        os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=20)


def dead(pid, budget_s=15.0):
    deadline = time.time() + budget_s
    while time.time() < deadline:
        if not L._pid_alive(pid):
            return True
        time.sleep(0.02)
    return not L._pid_alive(pid)


def pointer(dev):
    p = Path(dev) / "rounds" / L.CURRENT_NAME
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---- a live round's face is never overwritten, and the takeover is named ---

def test_live_round_pointer_is_never_overwritten_and_dies_named(tmp_path):
    dev = tmp_path / "develop"
    script = write_child(tmp_path)
    report = tmp_path / "round-a.json"
    live = spawn_child(script, dev, "round-20261030T000000Z", "revA",
                       report, "hold")
    try:
        assert wait_for(report), "the first round never published its face"
        first = pointer(dev)
        assert first is not None
        assert first["run_id"] == "round-20261030T000000Z"
        assert first["revision"] == {"sandbar": "revA"}
        assert first["state"] == "running"

        # a LATER round (live owner, live writer) must not overwrite it
        later = L.FaceWriter(dev, "round-20261030T000100Z", "develop-buffer",
                             {"sandbar": "revB"}, owner_pid=os.getpid())
        later.start()
        later.merge_progress(L.snapshot_progress("PASS [sc_1] (0.1s)"))
        later.publish()
        for _ in range(3):
            now = pointer(dev)
            assert now["run_id"] == "round-20261030T000000Z"
            assert now["revision"] == {"sandbar": "revA"}
            assert now["counts"]["ran"] == 0, "a stranger's counts, not ours"
            time.sleep(0.05)
    finally:
        kill_hard(live)
    assert dead(json.loads(Path(report).read_text())["pid"])

    # the first round is dead: the later round takes the pointer over and SAYS
    # SO (the dead run id and the revision a reader was seeing)
    later.publish()
    now = pointer(dev)
    assert now["run_id"] == "round-20261030T000100Z"
    assert now["revision"] == {"sandbar": "revB"}
    takeover = now["pointer_takeover"]
    assert takeover["run_id"] == "round-20261030T000000Z"
    assert takeover["revision"] == {"sandbar": "revA"}
    assert takeover["reason"] == "owner_gone"

    # and it retires exactly its OWN pointer when it finishes
    later.finish("done", "green", None)
    assert pointer(dev) is None


def test_relabelled_round_retires_its_own_pointer(tmp_path):
    """The measured stale-pointer hole: the writer renamed the evidence dir and
    the face's run id but not its own id, so its guarded finish never
    recognised the pointer and left it on disk for ever."""
    dev = tmp_path / "develop"
    writer = L.FaceWriter(dev, "round-20261030T010000Z", "develop-buffer",
                          {"sandbar": "revC"}, owner_pid=os.getpid())
    writer.start()
    assert pointer(dev)["run_id"] == "round-20261030T010000Z"
    writer.set_run_id("run-01M4SXHB0000000000000000")
    writer.publish()
    assert pointer(dev)["run_id"] == "run-01M4SXHB0000000000000000"
    writer.finish("done", "green", None)
    assert pointer(dev) is None, "the adopted id must still retire its pointer"


def test_writer_whose_owner_is_gone_stops_writing(tmp_path):
    """The killed tick's runner: it must land ONE named receipt and then write
    nothing at all — no counts, no pointer refresh, no flapping."""
    dev = tmp_path / "develop"
    script = write_child(tmp_path)
    # The owner fixture's LIFETIME: the test kills it.
    # SANCTIONED-WAIT: lifetime, not an awaited bound.
    owner_cmd = "import time; time.sleep(120)"
    owner = subprocess.Popen([sys.executable, "-c", owner_cmd])
    report = tmp_path / "round-gone.json"
    child = spawn_child(script, dev, "round-20261030T020000Z", "revD",
                        report, "loop", owner_pid=owner.pid)
    try:
        assert wait_for(report), "the round never published its face"
        assert pointer(dev)["run_id"] == "round-20261030T020000Z"
        os.kill(owner.pid, signal.SIGKILL)
        owner.wait(timeout=20)
        assert dead(owner.pid)
        assert wait_for(Path(str(report) + ".stamps"), 40), \
            "the round never finished its publish loop"
        child.wait(timeout=20)
        assert child.returncode == 0, child.stderr.read()[-400:]
    finally:
        for proc in (child, owner):
            if proc.poll() is None:
                kill_hard(proc)

    face = json.loads((dev / "rounds" / "round-20261030T020000Z"
                       / L.FACE_NAME).read_text(encoding="utf-8"))
    assert face["state"] == "failed"
    assert face["outcome"]["reason"] == "owner_gone:%d" % owner.pid
    assert face["owner_gone"]["pid"] == owner.pid
    assert pointer(dev) is None, "a dead round must not leave a live pointer"

    stamps = [s for s in json.loads(
        Path(str(report) + ".stamps").read_text()) if s is not None]
    assert stamps, "the halted round never wrote its receipt"
    assert len(set(stamps)) == 1, \
        "every publish after the halt must be a no-op (no rewriting)"
