"""zombies 单测（t260904-02）：census 解析畸形面、判定谓词红绿、三档输入、live 扫描失败红。"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_DIR))

from installer import zombies  # noqa: E402


def _census(entries):
    return json.dumps(entries)


class ParseCensusTest(unittest.TestCase):
    """census 解析：合法面 + 畸形面（消费外部输入必带畸形用例）。"""

    def test_ok_shape(self):
        es = zombies.parse_census(_census([
            {"pid": 1, "command": "node x.js", "cwd": "/a"},
            {"pid": 999999, "command": "python3 y.py", "cwd": "/b/c"},
        ]))
        self.assertEqual(len(es), 2)
        self.assertEqual(es[0]["pid"], 1)

    def test_object_contract_shape(self):
        # 集成场景契约形态（sc_doctor_zombie 写档口径）：{"processes": [...]}
        es = zombies.parse_census(json.dumps({"processes": [
            {"pid": 410242, "command": "node", "cwd": "/old/server/dsh/temporal-poc"},
        ]}))
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0]["pid"], 410242)

    def test_object_shape_bad_processes(self):
        # 对象形态但 processes 非数组=畸形（不静默按空表绿）
        for bad in ({"processes": {"pid": 1}}, {}, {"procs": []}):
            with self.assertRaises(ValueError):
                zombies.parse_census(json.dumps(bad))

    def test_bad_json(self):
        with self.assertRaises(ValueError):
            zombies.parse_census("{not json")

    def test_not_array(self):
        with self.assertRaises(ValueError):
            zombies.parse_census(json.dumps({"pid": 1}))

    def test_element_not_object(self):
        with self.assertRaises(ValueError):
            zombies.parse_census(_census(["node"]))

    def test_missing_keys(self):
        for bad in ({"pid": 1, "command": "node"},           # 缺 cwd
                    {"pid": 1, "cwd": "/a"},                 # 缺 command
                    {"command": "node", "cwd": "/a"}):       # 缺 pid
            with self.assertRaises(ValueError):
                zombies.parse_census(_census([bad]))

    def test_wrong_types(self):
        for bad in ({"pid": "1", "command": "node", "cwd": "/a"},        # pid 字符串
                    {"pid": 1.5, "command": "node", "cwd": "/a"},        # pid 浮点
                    {"pid": True, "command": "node", "cwd": "/a"},       # pid bool（int 子类）
                    {"pid": 0, "command": "node", "cwd": "/a"},          # 非正 pid
                    {"pid": -3, "command": "node", "cwd": "/a"},
                    {"pid": 1, "command": 42, "cwd": "/a"},              # command 非串
                    {"pid": 1, "command": "  ", "cwd": "/a"},            # command 空白
                    {"pid": 1, "command": "node", "cwd": ""}):           # cwd 空
            with self.assertRaises(ValueError):
                zombies.parse_census(_census([bad]))


class JudgeTest(unittest.TestCase):
    """判定谓词：当前仓绿 / 本仓 worktree 家族绿 / 异仓 poc 红（字符串+无归属）/
    异仓 git 根红（真目录）/ 非引擎命令不误伤 / 非引擎地界不误伤。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sandbar-ut-zombies-")
        self.engine_root = os.path.join(self.tmp, "cur-engine")
        os.makedirs(os.path.join(self.engine_root, "server", "dsh", "temporal-poc"))
        os.makedirs(os.path.join(self.engine_root, ".git"))  # git 归属根（否则家族判不了）

    def test_current_repo_procs_green(self):
        entries = [
            {"pid": 1, "command": "node /x/main.js", "cwd": self.engine_root},
            {"pid": 2, "command": "python3 worker.py", "cwd": os.path.join(self.engine_root, "server", "dsh", "temporal-poc")},
            {"pid": 3, "command": "node agent.js", "cwd": os.path.join(self.engine_root, "server", "dsh")},  # 深层 cwd
        ]
        self.assertEqual(zombies.judge_zombies(entries, self.engine_root), [])

    def test_sibling_worktree_family_green(self):
        """本仓 worktree 家族（主树 console / 兄弟泳道 agent）不红——真机实扫常驻，
        误报会让 doctor 永远红（实现期真机实锤：333 进程 3 个 node 在家族内）。"""
        main = os.path.join(self.tmp, "main-repo")
        os.makedirs(os.path.join(main, ".git", "worktrees", "w1"))
        os.makedirs(os.path.join(main, "server", "dsh", "temporal-poc"))
        lane = os.path.join(main, "w1")
        os.makedirs(os.path.join(lane, "server", "dsh", "temporal-poc"))
        with open(os.path.join(lane, ".git"), "w", encoding="utf-8") as f:
            f.write("gitdir: %s\n" % os.path.join(main, ".git", "worktrees", "w1"))
        # 从主仓视角：兄弟 worktree 进程绿；主仓自身进程绿
        entries = [
            {"pid": 5, "command": "node console.js", "cwd": main},
            {"pid": 6, "command": "node agent.js", "cwd": os.path.join(lane, "server", "dsh", "temporal-poc")},
        ]
        self.assertEqual(zombies.judge_zombies(entries, main), [])
        # 从 worktree 视角：主仓进程同样绿（家族对称）
        self.assertEqual(zombies.judge_zombies(entries, lane), [])

    def test_foreign_poc_marker_red(self):
        # 谓词 A：fixture 路径无需存在（字符串判据——场景注入面），无 git 归属=保守红
        entries = [{"pid": 424242, "command": "node headless", "cwd": "/old/frozen-suyou/server/dsh/temporal-poc"}]
        hits = zombies.judge_zombies(entries, self.engine_root)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["pid"], 424242)

    def test_foreign_git_repo_red(self):
        # 异仓 git 根（冻结旧仓形态：独立 .git + poc 目录）
        other = os.path.join(self.tmp, "other-engine")
        os.makedirs(os.path.join(other, ".git"))
        os.makedirs(os.path.join(other, "server", "dsh", "temporal-poc"))
        entries = [{"pid": 7, "command": "python3 worker.py", "cwd": other}]
        self.assertEqual(len(zombies.judge_zombies(entries, self.engine_root)), 1)
        # cwd 在异仓 poc 子目录同样红（260904 实案形态：headless cwd=suyou poc）
        entries[0]["cwd"] = os.path.join(other, "server", "dsh", "temporal-poc")
        self.assertEqual(len(zombies.judge_zombies(entries, self.engine_root)), 1)

    def test_non_engine_command_ignored(self):
        entries = [{"pid": 8, "command": "/usr/sbin/route monitor", "cwd": "/old/frozen-suyou/server/dsh/temporal-poc"}]
        self.assertEqual(zombies.judge_zombies(entries, self.engine_root), [])

    def test_non_engine_cwd_ignored(self):
        entries = [{"pid": 9, "command": "node /x/main.js", "cwd": "/Users/whoever/work"}]
        self.assertEqual(zombies.judge_zombies(entries, self.engine_root), [])

    def test_python3_variants_counted(self):
        for cmd in ("python worker.py", "python3 worker.py", "Python worker.py", "/usr/bin/python3.9 worker.py"):
            hits = zombies.judge_zombies(
                [{"pid": 10, "command": cmd, "cwd": "/old/x/server/dsh/temporal-poc"}], self.engine_root)
            self.assertEqual(len(hits), 1, cmd)


class ProbeTest(unittest.TestCase):
    """三档输入：缺省样本档（绿且文案自辨）/ census 注入红绿 / 注入文件不可读红。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sandbar-ut-zombies-p-")
        self.engine_root = os.path.join(self.tmp, "cur-engine")
        os.makedirs(os.path.join(self.engine_root, "server", "dsh", "temporal-poc"))
        os.makedirs(os.path.join(self.engine_root, ".git"))  # git 归属根（家族判定前提）

    def _write(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_default_sample_green_self_identified(self):
        ok, detail = zombies.probe(engine_root=self.engine_root)
        self.assertTrue(ok)
        # review C2：缺省档绿行必须自辨「未扫真机」，防误读为「无僵尸」。
        self.assertIn("内嵌干净样本", detail)
        self.assertIn("未扫真机", detail)
        self.assertIn("--live", detail)

    def test_census_bad_red_names_pid(self):
        p = self._write("bad.json", _census(
            [{"pid": 424242, "command": "node headless", "cwd": "/old/frozen/server/dsh/temporal-poc"}]))
        ok, detail = zombies.probe(engine_root=self.engine_root, census_path=p)
        self.assertFalse(ok)
        self.assertIn("424242", detail)
        self.assertIn("/old/frozen/server/dsh/temporal-poc", detail)

    def test_census_good_green(self):
        p = self._write("good.json", _census(
            [{"pid": 1, "command": "node main.js", "cwd": self.engine_root},
             {"pid": 2, "command": "node main.js", "cwd": "/unrelated"}]))
        ok, detail = zombies.probe(engine_root=self.engine_root, census_path=p)
        self.assertTrue(ok)
        self.assertIn("census 注入档", detail)

    def test_census_malformed_red(self):
        p = self._write("malformed.json", "{oops")
        ok, detail = zombies.probe(engine_root=self.engine_root, census_path=p)
        self.assertFalse(ok)
        self.assertIn("畸形", detail)

    def test_census_unreadable_red(self):
        ok, detail = zombies.probe(engine_root=self.engine_root,
                                   census_path=os.path.join(self.tmp, "nope.json"))
        self.assertFalse(ok)
        self.assertIn("不可读", detail)


class ScanLiveTest(unittest.TestCase):
    """live 扫描：lsof 缺失=显式红（fail-closed 不假绿）；lsof 块格式解析。
    （真机 live 绿已由实现期冒烟自证：lane/主仓双视角 0 僵尸——本类只钉故障面。）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sandbar-ut-zombies-s-")
        self.engine_root = os.path.join(self.tmp, "cur-engine")
        os.makedirs(os.path.join(self.engine_root, "server", "dsh", "temporal-poc"))
        os.makedirs(os.path.join(self.engine_root, ".git"))

    def test_lsof_missing_red(self):
        real_run = zombies.subprocess.run

        def _no_lsof(cmd, *a, **k):
            if cmd and cmd[0] == "lsof":
                raise FileNotFoundError("lsof")
            return real_run(cmd, *a, **k)

        zombies.subprocess.run = _no_lsof
        try:
            entries, err = zombies.scan_live()
            self.assertEqual(entries, [])
            self.assertIn("lsof", err)
            # probe 也必须在补丁窗口内调（restore 后再调会真扫机器）
            ok, detail = zombies.probe(live=True, engine_root=self.engine_root)
        finally:
            zombies.subprocess.run = real_run
        self.assertFalse(ok)
        self.assertIn("fail-closed", detail)

    def test_parse_lsof_blocks(self):
        # lsof -F pnc -d cwd 实测块格式：p<pid>/c<command>/fcwd/n<cwd>（见 spike）
        sample = ("p167\nloginwindow\n".replace("loginwindow", "cloginwindow")
                  + "fcwd\nn/\n"
                  + "p8114\ncnode\nfcwd\nn/Users/x/old/server/dsh/temporal-poc\n")
        real_run = zombies.subprocess.run

        class R:
            returncode = 0
            stdout = sample
            stderr = ""

        def _fake(cmd, *a, **k):
            return R()

        zombies.subprocess.run = _fake
        try:
            entries, err = zombies.scan_live()
        finally:
            zombies.subprocess.run = real_run
        self.assertEqual(err, "")
        self.assertEqual(len(entries), 2)
        node_entries = [e for e in entries if e["command"] == "node"]
        self.assertEqual(len(node_entries), 1)
        self.assertEqual(node_entries[0]["cwd"], "/Users/x/old/server/dsh/temporal-poc")


if __name__ == "__main__":
    unittest.main()
