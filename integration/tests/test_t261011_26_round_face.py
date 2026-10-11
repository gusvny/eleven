#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-26 L1 unit battery: the line round's live face and retained
evidence (developer stage).

Covers, over temp dirs only (offline seconds, zero docker/Temporal/port/
console, never touches 3099):

- snapshot_progress: the parser truth table pinned to the suite's ACTUAL
  vocabulary (PASS/FAIL/ENV_FAIL result blocks, pool banners, the pool-
  exclusion summary, INTEG_SUMMARY) + malformed-input matrix (garbled
  lines, torn JSON, empty input, re-parse idempotence — snapshot, not
  deltas);
- atomic_write_json: a failed replace leaves the previous face intact;
- FaceWriter lifecycle: start writes current.json, finish writes the
  terminal face.json and retires the pointer RUN-ID-GUARDED (review
  condition 1: a second, newer round's pointer is never deleted);
- retention prune: keeps the newest FACE_RETAIN_ROUNDS run dirs, never
  deletes the dir named by the live pointer;
- resolve_develop_dir: override wins; scan finds the declaring project;
  no match / torn declaration / unreadable root = named degrade (None);
  multiple declaring projects = sorted-first wins, named on stderr;
- end-to-end over the REAL runner (subprocess stub suite, SANDBAR_* env
  pins): the face is visible DURING the run, terminal done/green,
  done/red, and failed+named-reason (could-not-run) outcomes.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "integration"

sys.path.insert(0, str(INTEG))
import lib_round_face as lrf  # noqa: E402
import line_round_runner as runner  # noqa: E402


class SnapshotProgress(unittest.TestCase):
    def test_pass_fail_envfail_blocks(self):
        text = "\n".join([
            "PASS [sc_a] (1.2s)",
            "FAIL [sc_b] exit=1 (0.5s)",
            "  tail line ignored",
            "ENV_FAIL [sc_c] exit=2 (0.1s)",
        ])
        s = lrf.snapshot_progress(text)
        self.assertEqual(s["counts"], {"ran": 3, "pass": 1, "fail": 1,
                                       "env_fail": 1})
        self.assertEqual(s["last_scenario"],
                         {"name": "sc_c", "verdict": "ENV_FAIL"})

    def test_pool_banners_and_exclusion_summary(self):
        text = "\n".join([
            "  点名 [sc_a]（池=engine）",
            "  跳过 [sc_b]（池=browser）",
            "本轮跳过池=engine,browser（少 3 条）",
        ])
        s = lrf.snapshot_progress(text)
        self.assertEqual(s["pool"], "browser")
        self.assertEqual(s["counts"]["ran"], 0)

    def test_summary_end_mark(self):
        self.assertTrue(lrf.snapshot_progress(
            'INTEG_SUMMARY {"ran": 1}')["summary_seen"])
        self.assertFalse(lrf.snapshot_progress("PASS [x] (1s)")["summary_seen"])

    def test_malformed_input_ignored_never_raises(self):
        for junk in ("", None, "\x00\x01", "PASS [", "FAIL", "（池=）",
                     "PASS [ok] (1s)\n\x00torn", "INTEG_SUMMARY not-json"):
            s = lrf.snapshot_progress(junk)  # must not raise
            self.assertIsInstance(s["counts"]["ran"], int)

    def test_snapshot_idempotent_not_delta(self):
        one = lrf.snapshot_progress("PASS [x] (1s)")
        again = lrf.snapshot_progress("PASS [x] (1s)\nPASS [x] (1s)")
        self.assertEqual(one["counts"]["ran"], 1)
        self.assertEqual(again["counts"]["ran"], 2)  # grown file, fresh parse


class AtomicWrite(unittest.TestCase):
    def test_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.json"
            lrf.atomic_write_json(p, {"a": 1})
            lrf.atomic_write_json(p, {"a": 2})
            self.assertEqual(json.loads(p.read_text())["a"], 2)
            self.assertEqual(list(Path(tmp).iterdir()), [p])  # no tmp residue

    def test_failed_write_leaves_previous_face(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.json"
            lrf.atomic_write_json(p, {"a": 1})
            real_replace = os.replace

            def boom(src, dst):
                raise OSError("disk full")

            os.replace = boom
            try:
                with self.assertRaises(OSError):
                    lrf.atomic_write_json(p, {"a": 2})
            finally:
                os.replace = real_replace
            self.assertEqual(json.loads(p.read_text())["a"], 1)


class FaceWriterLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev = Path(self.tmp.name) / "develop"
        self.w = lrf.FaceWriter(self.dev, "round-1", "l1", {"r": "rev1"})
        self.w.start()

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_writes_live_pointer(self):
        cur = self.dev / "rounds" / "current.json"
        obj = json.loads(cur.read_text())
        self.assertEqual(obj["run_id"], "round-1")
        self.assertEqual(obj["state"], "running")
        self.assertEqual(obj["counts"]["ran"], 0)

    def test_finish_terminal_record_and_retire(self):
        self.w.finish("done", "green", None)
        self.assertFalse((self.dev / "rounds" / "current.json").exists())
        face = json.loads(
            (self.dev / "rounds" / "round-1" / "face.json").read_text())
        self.assertEqual(face["state"], "done")
        self.assertEqual(face["outcome"], {"verdict": "green", "reason": ""})

    def test_finish_failed_carries_reason(self):
        self.w.finish("failed", None, "could_not_run:runner_timeout:30s")
        face = json.loads(
            (self.dev / "rounds" / "round-1" / "face.json").read_text())
        self.assertEqual(face["outcome"]["reason"],
                         "could_not_run:runner_timeout:30s")

    def test_finish_never_deletes_newer_round_pointer(self):
        # review condition 1 + arbitration 261011 r1: a second round CANNOT
        # steal the live pointer (publish declines, named) — so the first
        # round's guarded finish retires exactly its own pointer, and the
        # second round's decline leaves the first's face intact until then
        newer = lrf.FaceWriter(self.dev, "round-2", "l1", {"r": "rev2"})
        newer.start()
        cur = self.dev / "rounds" / "current.json"
        self.assertEqual(json.loads(cur.read_text())["run_id"], "round-1")
        self.w.finish("failed", None, "late")
        self.assertFalse(cur.exists())  # w retired its OWN pointer
        # with the pointer free, the second round may now publish
        newer.publish()
        self.assertEqual(json.loads(cur.read_text())["run_id"], "round-2")

    def test_publish_never_steals_foreign_pointer(self):
        # arbitration 261011 round 1, leg C1: a round starting while ANOTHER
        # round's pointer is live must not overwrite it (its own guarded
        # finish would then delete the stranger's face)
        cur = self.dev / "rounds" / "current.json"
        cur.write_text(json.dumps(
            {"run_id": "round-stranger", "state": "running"}))
        (self.dev / "rounds" / "round-stranger").mkdir()
        late = lrf.FaceWriter(self.dev, "round-late", "l1", {"r": "rev"})
        late.start()
        self.assertEqual(json.loads(cur.read_text())["run_id"],
                         "round-stranger")  # pointer NOT stolen at publish
        late.merge_progress(lrf.snapshot_progress("PASS [x] (1s)"))
        late.publish()  # watcher tick: still must not steal
        self.assertEqual(json.loads(cur.read_text())["run_id"],
                         "round-stranger")
        late.finish("done", "green", None)
        self.assertEqual(json.loads(cur.read_text())["run_id"],
                         "round-stranger")  # and NOT deleted at finish
        # this round's terminal record still lands, run-id-keyed
        face = json.loads(
            (self.dev / "rounds" / "round-late" / "face.json").read_text())
        self.assertEqual(face["state"], "done")

    def test_retain_log_copies_suite_log(self):
        log = Path(self.tmp.name) / "suite.log"
        log.write_text("PASS [x] (1s)\n")
        self.w.retain_log(log)
        kept = self.dev / "rounds" / "round-1" / "suite.log"
        self.assertEqual(kept.read_text(), "PASS [x] (1s)\n")

    def test_prune_keeps_newest_and_live(self):
        # names chosen so "round-1" is the lexically NEWEST (real ids are
        # timestamps, so newest = greatest name); the live pointer names an
        # OLD dir, which must survive the prune anyway
        for i in range(lrf.FACE_RETAIN_ROUNDS + 3):
            (self.dev / "rounds" / ("q-old-%02d" % i)).mkdir()
        (self.dev / "rounds" / "q-old-00" / "x").write_text("keep-alive")
        live = lrf.FaceWriter(self.dev, "q-old-00", "l", {})
        (self.dev / "rounds" / "current.json").write_text(
            json.dumps({"run_id": "q-old-00"}))
        live.start()  # triggers prune
        names = {d.name for d in (self.dev / "rounds").iterdir()}
        self.assertIn("q-old-00", names)      # live pointer's dir survives
        self.assertIn("round-1", names)       # newest survives
        self.assertNotIn("q-old-02", names)   # oldest pruned
        self.assertLessEqual(
            len([n for n in names if n != "current.json"]),
            lrf.FACE_RETAIN_ROUNDS + 1)


DECL = [{"version": 1, "line_id": "l1", "scope": "", "owner": "",
         "repositories": [{"name": "sandbar", "branch": "line/l1"}],
         "extra_scenarios": []}]


class ResolveDevelopDir(unittest.TestCase):
    def test_override_wins(self):
        env = {lrf.FACE_DIR_ENV: "/tmp/face-override"}
        d, line = lrf.resolve_develop_dir(["any"], env)
        self.assertEqual((str(d), line), ("/tmp/face-override", None))

    def test_scan_finds_declaring_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p1" / "data" / "develop"
            proj.mkdir(parents=True)
            (proj / "lines.json").write_text(json.dumps(DECL))
            d, line = lrf.resolve_develop_dir(["sandbar"],
                                              {lrf.PROJECTS_DIR_ENV: tmp})
            self.assertEqual(d, proj)
            self.assertEqual(line, "l1")

    def test_no_match_named_degrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = sys.stderr
            import io
            buf = io.StringIO()
            sys.stderr = buf
            try:
                d, line = lrf.resolve_develop_dir(
                    ["nope"], {lrf.PROJECTS_DIR_ENV: tmp})
            finally:
                sys.stderr = err
            self.assertIsNone(d)
            self.assertIn("degrade", buf.getvalue())

    def test_torn_declaration_skipped_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p1" / "data" / "develop"
            proj.mkdir(parents=True)
            (proj / "lines.json").write_text("{torn")
            import io
            err, buf = sys.stderr, io.StringIO()
            sys.stderr = buf
            try:
                d, _ = lrf.resolve_develop_dir(["sandbar"],
                                               {lrf.PROJECTS_DIR_ENV: tmp})
            finally:
                sys.stderr = err
            self.assertIsNone(d)
            self.assertIn("unreadable", buf.getvalue())

    def test_multiple_projects_first_sorted_wins_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("pa", "pb"):
                proj = Path(tmp) / name / "data" / "develop"
                proj.mkdir(parents=True)
                (proj / "lines.json").write_text(json.dumps(DECL))
            import io
            err, buf = sys.stderr, io.StringIO()
            sys.stderr = buf
            try:
                d, line = lrf.resolve_develop_dir(["sandbar"],
                                                  {lrf.PROJECTS_DIR_ENV: tmp})
            finally:
                sys.stderr = err
            self.assertEqual(d, Path(tmp) / "pa" / "data" / "develop")
            self.assertIn("2 projects", buf.getvalue())

    def test_unreadable_root_named_degrade(self):
        import io
        err, buf = sys.stderr, io.StringIO()
        sys.stderr = buf
        try:
            d, _ = lrf.resolve_develop_dir(
                ["x"], {lrf.PROJECTS_DIR_ENV: "/nonexistent-zz-root"})
        finally:
            sys.stderr = err
        self.assertIsNone(d)
        self.assertIn("degrade", buf.getvalue())


class StubTree(unittest.TestCase):
    """A tiny git fixture whose HEAD carries integration/run_scenarios.py —
    the runner can clone it and run the STUB suite command inside."""

    def make_repo(self):
        import shutil
        import subprocess as sp
        src = Path(self.tmp.name) / "src"
        (src / "integration").mkdir(parents=True)
        (src / "integration" / "run_scenarios.py").write_text("# stub\n")
        # the stub suite writes a REAL run record through the clone's own
        # ledger store — so the clone carries it (committed files only)
        shutil.copyfile(INTEG / "scenario_ledger.py",
                        src / "integration" / "scenario_ledger.py")
        (src / "server" / "engine").mkdir(parents=True)
        shutil.copyfile(ROOT / "server" / "engine" / "failure_protocol.py",
                        src / "server" / "engine" / "failure_protocol.py")
        for argv in (["git", "init", "-q", str(src)],
                     ["git", "-C", str(src), "add", "-A"],
                     ["git", "-C", str(src), "commit", "-qm", "t"]):
            sp.run(argv, check=True, capture_output=True)
        return src

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = self.make_repo()
        self.run_root = Path(self.tmp.name) / "run"
        self.face_dir = Path(self.tmp.name) / "develop"
        self.decl_dir = self.face_dir  # resolution override target

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, extra=None):
        rev = subprocess.run(["git", "-C", str(self.src), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        env = dict(os.environ)
        env.update({
            runner.CANDIDATES_ENV: json.dumps(
                [{"repo": "src", "revision": rev}]),
            runner.RUN_ROOT_ENV: str(self.run_root),
            "SANDBAR_LINE_ROUND_REPO_PATH_SRC": str(self.src),
            runner.SUITE_CMD_ENV: "%s %s" % (sys.executable, self.stub_path),
            lrf.FACE_DIR_ENV: str(self.face_dir),
        })
        env.update(extra or {})
        return env

    def run_runner(self, extra=None):
        # wait bound injectable (L25): seconds in practice, generous cap only
        cap = float(os.environ.get("T26101126_RUNNER_TIMEOUT_S", "120"))
        return subprocess.run(
            [sys.executable, str(INTEG / "line_round_runner.py")],
            env=self.env(extra), capture_output=True, text=True, timeout=cap)

    def rounds(self):
        return self.face_dir / "rounds"


class RoundFaceEndToEnd(StubTree):
    """The stub suite writes a REAL run record (rows + validated header via
    the clone's own scenario_ledger — the same store the real suite writes),
    so the runner's read-back relay fires and the round can complete."""

    STUB = (
        "import hashlib, json, os, subprocess, sys, time\n"
        "cwd = os.getcwd()\n"
        "sys.path.insert(0, os.path.join(cwd, 'integration'))\n"
        "import scenario_ledger as sl\n"
        "time.sleep(float(os.environ.get('STUB_SLEEP', '0')))\n"
        "verdicts = json.loads(os.environ.get('STUB_VERDICTS',\n"
        "                                     '[\"pass\", \"pass\"]'))\n"
        "rev = subprocess.run(['git', '-C', cwd, 'rev-parse', 'HEAD'],\n"
        "                     capture_output=True, text=True).stdout.strip()\n"
        "rid = sl.mint_run_id()\n"
        "fp_sha = hashlib.sha256(b'stub').hexdigest()\n"
        "now = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())\n"
        "rows = [{'ts': now, 'commit': rev, 'env_fp': fp_sha,\n"
        "         'conc_width': 1, 'pool': 'ro', 'scenario': 'sc_%d' % i,\n"
        "         'verdict': v, 'wall_s': 0.1,\n"
        "         'source': 'lane:line-round', 'ticket': '', 'run': rid}\n"
        "        for i, v in enumerate(verdicts)]\n"
        "r = sl.append_records(rows)\n"
        "assert r['written'] == len(rows), r\n"
        "counts = {'ran': len(rows), 'passed': verdicts.count('pass'),\n"
        "          'failed': verdicts.count('fail'),\n"
        "          'env_failed': verdicts.count('env_fail')}\n"
        "hdr = {'v': sl.RUN_HEADER_V, 'id': rid,\n"
        "       'repos': [{'repo': 'src', 'revision': rev}],\n"
        "       'suite': 'full', 'source': 'lane:line-round',\n"
        "       'env_fp': fp_sha, 'conc_width': 1, 'pool': 'ro',\n"
        "       'started_at': int(time.time() * 1000), 'duration_s': 0.1,\n"
        "       'cases': counts, 'verdict': sl.run_verdict(counts)}\n"
        "r = sl.append_run_header(hdr)\n"
        "assert r['written'] == 1, r\n"
        "for i, v in enumerate(verdicts):\n"
        "    fmt = {'pass': 'PASS [sc_%d] (0.1s)',\n"
        "           'fail': 'FAIL [sc_%d] exit=1 (0.1s)',\n"
        "           'env_fail': 'ENV_FAIL [sc_%d] exit=2 (0.1s)'}[v]\n"
        "    print(fmt % i, flush=True)\n"
        "print('INTEG_SUMMARY %s' % json.dumps({'ran': len(rows),\n"
        "      'run_id': rid}), flush=True)\n")

    def write_stub(self):
        self.stub_path = Path(self.tmp.name) / "stub_suite.py"
        self.stub_path.write_text(self.STUB)

    def test_face_visible_during_run_then_done_green(self):
        self.write_stub()
        proc = subprocess.Popen(
            [sys.executable, str(INTEG / "line_round_runner.py")],
            env=self.env({"STUB_SLEEP": "4"}), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        # mid-run: the live pointer must exist and say running
        cur = self.rounds() / "current.json"
        seen_running = False
        deadline = time.time() + 20
        while time.time() < deadline and proc.poll() is None:
            if cur.exists():
                obj = json.loads(cur.read_text())
                if obj.get("state") == "running":
                    seen_running = True
                    self.assertTrue(obj["run_id"].startswith("round-"))
                    break
            time.sleep(0.2)
        # wait bound injectable (L25): seconds in practice, generous cap only
        out, err = proc.communicate(
            timeout=float(os.environ.get("T26101126_RUNNER_TIMEOUT_S", "120")))
        self.assertEqual(proc.returncode, 0, err[-400:])
        self.assertTrue(seen_running, "live face never seen during the run")
        self.assertFalse(cur.exists())  # absence = idle after the round
        run_id = json.loads(out)["id"]  # relabelled to the ledger run id
        run_dir = self.rounds() / run_id
        face = json.loads((run_dir / "face.json").read_text())
        self.assertEqual(face["state"], "done")
        self.assertEqual(face["run_id"], run_id)
        self.assertEqual(face["outcome"]["verdict"], "green")
        self.assertEqual(face["counts"]["ran"], 2)
        self.assertTrue((run_dir / "suite.log").exists(), "log not retained")

    def test_completed_red_is_done_red(self):
        self.write_stub()
        proc = self.run_runner({"STUB_VERDICTS": '["pass", "fail"]'})
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        out = json.loads(proc.stdout)
        face = json.loads((self.rounds() / out["id"] / "face.json")
                          .read_text())
        self.assertEqual(face["outcome"]["verdict"], "red")

    def test_missing_summary_is_failed_named(self):
        # a stub that writes NO INTEG_SUMMARY and exits nonzero: the runner's
        # could-not-run path must land on the face as failed + named reason
        self.stub_path = Path(self.tmp.name) / "stub_suite.py"
        self.stub_path.write_text("import sys; sys.exit(3)\n")
        proc = self.run_runner()
        self.assertNotEqual(proc.returncode, 0)
        faces = list(self.rounds().glob("*/face.json"))
        self.assertEqual(len(faces), 1)
        face = json.loads(faces[0].read_text())
        self.assertEqual(face["state"], "failed")
        self.assertIn("suite_rc_3", face["outcome"]["reason"])
        self.assertIn("could_not_run", proc.stderr)

    def test_unresolvable_face_dir_degrades_honest(self):
        self.write_stub()
        proc = self.run_runner({lrf.FACE_DIR_ENV: "",
                                "STUB_VERDICTS": '["pass"]'})
        # no face dir resolved -> the round runs exactly as before; the
        # point: no traceback, no half-written face anywhere
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
