"""t260904-02 A 面 UT：项目注册表装载器上收后的锚定与硬闸。

覆盖（承接 t260901-14 registry-loader intent：legacy / per-key / 隔离 / 空 / 未知，
加 KI-032 硬闸三态拒收与「正规入口同源」行为断言）：
- 装载器（shared.load_projects_registry）：per-key 好档 / 单条目畸形隔离 /
  目录名不合法隔离 / 空注册表报错 / legacy env 单文件模式 / SANDBAR_PROJECTS_DIR
  覆盖语义（env 每次现读）；
- lookup_project：命中 / 未知 key / 隔离条目 / key 白名单畸形输入；
- check_paths_under_project：注册目录内放行 / 越界拒收 / 相对路径不拦；
- client.cmd_ticket_start 硬闸（真函数级，stub _connect）：成功子用例 workspace 绝对
  路径锚 project_root（TicketInput 落参断言）；缺 project / 未知 project /
  显式路径越界三态各自可辨拒收。
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （夹具注册表+atexit 回收）

import client  # noqa: E402
import shared  # noqa: E402


def _mk_registry(root, key, name, dirs, bad=False):
    d = Path(root) / key
    d.mkdir(parents=True)
    content = "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n" % (key, name)
    if bad:
        content = "schema: v9\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - /x\n" % (key, name)
    else:
        for p in dirs:
            content += "      - %s\n" % p
    (d / "project.yaml").write_text(content, encoding="utf-8")
    return d


class _Env:
    """env 覆盖上下文（SANDBAR_PROJECTS_DIR / SANDBAR_PROJECTS_YAML）。"""

    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = str(mkdtemp_reclaimed("t260904-02-reg-"))

    def test_per_key_good(self):
        home = os.path.join(self.tmp, "proj-home")
        os.makedirs(home)
        _mk_registry(self.tmp, "alpha", "甲项目", [home])
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            projects, quarantined = shared.load_projects_registry()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["key"], "alpha")
        self.assertEqual(projects[0]["dirs"], [home])
        self.assertEqual(quarantined, [])

    def test_quarantine_malformed_entry(self):
        _mk_registry(self.tmp, "alpha", "甲", ["/x"], bad=True)
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            projects, quarantined = shared.load_projects_registry()
        self.assertEqual(projects, [])
        self.assertEqual(len(quarantined), 1)
        # 隔离原因可定位（schema 版本不支持）
        self.assertIn("schema", quarantined[0]["error"])

    def test_quarantine_bad_dirname(self):
        d = Path(self.tmp) / "Bad_Name"
        d.mkdir(parents=True)
        (d / "project.yaml").write_text("schema: v1\n", encoding="utf-8")
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            _, quarantined = shared.load_projects_registry()
        self.assertEqual(len(quarantined), 1)
        self.assertIn("illegal directory name", quarantined[0]["error"])

    def test_empty_registry_rejected(self):
        root = os.path.join(self.tmp, "empty-root")
        os.makedirs(root)
        # 空根 + 迁移源在场 = 走迁移（合法路径）；fail-closed 报错子用例需要「无迁移源」——
        # monkeypatch 掉 shared.PROJECTS_YAML（真源在 lane 内真实存在，不能动仓文件）。
        real_seed = shared.PROJECTS_YAML
        shared.PROJECTS_YAML = Path(self.tmp) / "no-such-seed.yaml"
        try:
            with _Env(SANDBAR_PROJECTS_DIR=root):
                with self.assertRaises(ValueError) as cm:
                    shared.load_projects_registry()
        finally:
            shared.PROJECTS_YAML = real_seed
        self.assertIn("registry root directory does not exist", str(cm.exception))

    def test_all_quarantined_reports_reasons(self):
        _mk_registry(self.tmp, "alpha", "甲", ["/x"], bad=True)
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            projects, quarantined = shared.load_projects_registry()
            with self.assertRaises(ValueError) as cm:
                shared.assert_registry_nonempty(projects, quarantined)
        self.assertIn("no usable project entries: all 1 were quarantined", str(cm.exception))

    def test_legacy_env_mode(self):
        legacy = os.path.join(self.tmp, "projects.yaml")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("projects:\n  - key: legacy-one\n    name: 旧档\n    dirs:\n      - /tmp/legacy\n")
        with _Env(SANDBAR_PROJECTS_YAML=legacy):
            projects, quarantined = shared.load_projects_registry()
        self.assertEqual(projects[0]["key"], "legacy-one")
        self.assertEqual(quarantined, [])

    def test_env_reread_per_call(self):
        """SANDBAR_PROJECTS_DIR 每次调用现读（先 import 后设 env 不失效）。"""
        a_root = os.path.join(self.tmp, "rega")
        b_root = os.path.join(self.tmp, "regb")
        os.makedirs(os.path.join(a_root, "pa"))
        os.makedirs(os.path.join(b_root, "pb"))
        (Path(a_root) / "pa" / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: pa\n    name: A\n    dirs:\n      - /tmp/a\n", encoding="utf-8")
        (Path(b_root) / "pb" / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: pb\n    name: B\n    dirs:\n      - /tmp/b\n", encoding="utf-8")
        with _Env(SANDBAR_PROJECTS_DIR=a_root):
            self.assertEqual([p["key"] for p in shared.load_projects_registry()[0]], ["pa"])
            os.environ["SANDBAR_PROJECTS_DIR"] = b_root
            self.assertEqual([p["key"] for p in shared.load_projects_registry()[0]], ["pb"])


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = str(mkdtemp_reclaimed("t260904-02-lkp-"))
        self.home = os.path.join(self.tmp, "proj-home")
        os.makedirs(self.home)
        _mk_registry(self.tmp, "bench-anchor", "锚定项目", [self.home])

    def test_hit(self):
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            proj = shared.lookup_project("bench-anchor")
        self.assertEqual(proj["dirs"], [self.home])

    def test_unknown_key(self):
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            with self.assertRaises(ValueError) as cm:
                shared.lookup_project("no-such")
        self.assertIn("unknown project", str(cm.exception))
        self.assertIn("bench-anchor", str(cm.exception))  # 已注册清单指路

    def test_quarantined_key_names_reason(self):
        _mk_registry(self.tmp, "sick", "病", ["/x"], bad=True)
        with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
            with self.assertRaises(ValueError) as cm:
                shared.lookup_project("sick")
        self.assertIn("is quarantined", str(cm.exception))

    def test_malformed_keys(self):
        for bad in ("", "UPPER", "带中文", "a" * 50, "sp ace", None):
            with _Env(SANDBAR_PROJECTS_DIR=self.tmp):
                with self.assertRaises(ValueError) as cm:
                    shared.lookup_project(bad)
            self.assertIn("illegal project", str(cm.exception))


class CheckPathsTest(unittest.TestCase):
    def setUp(self):
        self.proj = {"key": "k", "name": "n", "dirs": ["/repos/alpha", "/repos/alpha-ext"]}

    def test_inside_ok(self):
        shared.check_paths_under_project(self.proj, {"path": "/repos/alpha/.lane/t1"}, "/repos/alpha/.lane/t1")

    def test_second_dir_ok(self):
        shared.check_paths_under_project(self.proj, {"path": "/repos/alpha-ext/ws"}, "")

    def test_foreign_absolute_rejected(self):
        with self.assertRaises(ValueError) as cm:
            shared.check_paths_under_project(self.proj, {"path": "/repos/beta/.lane/t1"}, "")
        self.assertIn("is not inside the registered directories", str(cm.exception))

    def test_prefix_trick_rejected(self):
        # /repos/alpha2 不是 /repos/alpha 子路径（rstrip+sep 语义）
        with self.assertRaises(ValueError):
            shared.check_paths_under_project(self.proj, {"path": "/repos/alpha2/evil"}, "")

    def test_relative_not_intercepted(self):
        shared.check_paths_under_project(self.proj, {"path": ".lane/t1"}, ".lane/t1")


class _FakeHandle:
    def __init__(self):
        self.started = None
        self.id = "fake-wf-id"
        self.result_run_id = "fake-run-id"

    async def start_workflow(self, cls, inp, **kw):
        self.started = (cls, inp, kw)
        return self


class TicketStartGateTest(unittest.TestCase):
    """KI-032 硬闸行为级：真调 client.cmd_ticket_start（stub _connect，
    拒收子用例在 connect 之前就返回，成功子用例断言 TicketInput 落参）。"""

    def setUp(self):
        self.tmp = str(mkdtemp_reclaimed("t260904-02-gate-"))
        self.home = os.path.join(self.tmp, "anchor-home")
        os.makedirs(os.path.join(self.home, ".lane"))
        _mk_registry(os.path.join(self.tmp, "reg"), "bench-anchor", "锚定项目", [self.home])
        self.fake = _FakeHandle()
        self._orig_connect = client._connect

        async def _fake_connect():
            class _C:
                def __init__(self, fake):
                    self._fake = fake

                def start_workflow(self, cls, inp, **kw):
                    async def _aw():
                        return await self._fake.start_workflow(cls, inp, **kw)
                    return _aw()
            return _C(self.fake)

        client._connect = _fake_connect

    def tearDown(self):
        client._connect = self._orig_connect

    def _args(self, **over):
        a = {
            "ticket_id": "t260904-99", "template_id": "dev-lane", "project": "bench-anchor",
            "title": "UT 硬闸", "write_set": ["notes/"], "body": "x",
            # t260925-08 翻严后 ticket-start 过跨项目闸：本用例测锚定语义（非闸），
            # 调用方身份按生产注入链形态声明为同项目（declared 同项目=pass）。
            "caller_project": "bench-anchor",
        }
        a.update(over)
        return a

    def test_success_anchors_absolute(self):
        with _Env(SANDBAR_PROJECTS_DIR=os.path.join(self.tmp, "reg")):
            out = asyncio.run(client.cmd_ticket_start(self._args()))
        self.assertTrue(out.get("ok"), out)
        _, inp, _ = self.fake.started
        ws = inp.workspace
        # macOS 下 /var 是 /private/var 符号链接——锚定用注册目录原文比（引擎不改写）
        home_norm = os.path.normpath(self.home)
        self.assertTrue(os.path.isabs(ws["path"]), "workspace 绝对路径：%r" % ws["path"])
        # epic 验收 1：锚 <项目主目录>/.lane/<工单id>
        self.assertEqual(ws["path"], os.path.join(home_norm, ".lane", "t260904-99"))
        self.assertEqual(inp.worktree, ws["path"])

    def test_missing_project_rejected(self):
        out = asyncio.run(client.cmd_ticket_start(self._args(project="")))
        self.assertFalse(out.get("ok"))
        self.assertIn("requires project", out.get("error", ""))
        self.assertIsNone(self.fake.started)

    def test_unknown_project_rejected_before_connect(self):
        with _Env(SANDBAR_PROJECTS_DIR=os.path.join(self.tmp, "reg")):
            out = asyncio.run(client.cmd_ticket_start(self._args(project="ghost")))
        self.assertFalse(out.get("ok"))
        err = out.get("error", "")
        self.assertIn("not anchored", err)
        self.assertIn("unknown project", err)
        self.assertIsNone(self.fake.started)

    def test_foreign_workspace_rejected(self):
        with _Env(SANDBAR_PROJECTS_DIR=os.path.join(self.tmp, "reg")):
            out = asyncio.run(client.cmd_ticket_start(self._args(
                workspace={"type": "worktree", "path": "/repos/other/.lane/evil"})))
        self.assertFalse(out.get("ok"))
        self.assertIn("is not inside the registered directories", out.get("error", ""))
        self.assertIsNone(self.fake.started)

    def test_explicit_in_project_workspace_ok(self):
        ws_path = os.path.join(self.home, ".lane", "explicit-ws")
        with _Env(SANDBAR_PROJECTS_DIR=os.path.join(self.tmp, "reg")):
            out = asyncio.run(client.cmd_ticket_start(self._args(
                workspace={"type": "worktree", "path": ws_path})))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self.fake.started[1].workspace["path"], ws_path)


if __name__ == "__main__":
    unittest.main()
