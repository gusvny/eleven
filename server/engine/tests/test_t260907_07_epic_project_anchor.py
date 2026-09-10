"""t260907-07 UT：立项单校验项目感知化（CLI×工单台锚点一致，GAP-B 修复）。

覆盖（方案 gen1/gen2 验收口径）：
- resolve_epics_dir 三级解析：项目锚（两项目同名/异名立项单各取各的）/
  env SANDBAR_EPICS_DIR 现读优先（自测语义不变）/ 空 project 引擎锚兜底 /
  未知 project fail-closed / env 空串回落 / env 指不存在目录不预检；
- validate_epic_code 加参：项目锚通过/拒绝、报错文案含实际查询目录（诊断
  信息=项目主目录而非引擎锚）、缺省 None 保持 legacy 行为、畸形输入
  （路径穿越/空串放行/目录为空）；
- client.cmd_ticket_start 项目感知开票（真函数级，stub _connect）：外部项目
  epic 在其主目录 → 校验通过（TicketInput 落参断言）；引擎项目行为不变；
- （t260910-14 退役注记：原 prepare_epic_next 项目感知段随功能整链退役删除。）
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import client  # noqa: E402
import shared  # noqa: E402


def _mk_registry(root, key, name, dirs):
    d = Path(root) / key
    d.mkdir(parents=True)
    content = "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n" % (key, name)
    for p in dirs:
        content += "      - %s\n" % p
    (d / "project.yaml").write_text(content, encoding="utf-8")
    return d


class _Env:
    """env 覆盖上下文（SANDBAR_PROJECTS_DIR / SANDBAR_EPICS_DIR）。"""

    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


import os  # noqa: E402  （_Env 依赖，置后导入保持 defs 上方无副作用）


class ResolveEpicsDirTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        # ambient 隔离（t260908-01 实证）：resolve_epics_dir 设计上 env
        # SANDBAR_EPICS_DIR 现读优先——桩脑工单泳道里 merge_check 的 pytest 会
        # 继承 worker 的测试台 env，ambient 值压过本类自建项目锚造成假红。
        # 专项测「env 现读优先」的用例经 _Env 自行注入，不受影响。
        self._saved_epics_env = os.environ.get("SANDBAR_EPICS_DIR")
        os.environ.pop("SANDBAR_EPICS_DIR", None)
        self.root = Path(tempfile.mkdtemp(prefix="t260907-07-reg-"))
        # 两项目夹具：engine 桶 + external 桶，各自主目录下 notes/epics 放
        # 同名（gap-b.md）+ 异名（各自独有）立项单——被测的是解析代码路径，
        # 主目录均指临时目录，不碰 worktree 根（方案 C3 夹具卫生）。
        self.engine_root = self.root / "engine-main"
        self.external_root = self.root / "external-main"
        _mk_registry(self.root, "engine", "引擎项目", [str(self.engine_root)])
        _mk_registry(self.root, "external", "外部项目", [str(self.external_root)])
        for base, own in ((self.engine_root, "engine-only"), (self.external_root, "external-only")):
            epics = base / "notes" / "epics"
            epics.mkdir(parents=True)
            (epics / "gap-b.md").write_text("# 立项单：gap-b\n", encoding="utf-8")
            (epics / (own + ".md")).write_text("# 立项单：%s\n" % own, encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
        if self._saved_epics_env is None:
            os.environ.pop("SANDBAR_EPICS_DIR", None)
        else:
            os.environ["SANDBAR_EPICS_DIR"] = self._saved_epics_env

    def test_project_anchor_per_project(self):
        """两项目同名/异名立项单各取各的（验收①②的解析层）。"""
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root)):
            self.assertEqual(shared.resolve_epics_dir("external"),
                             self.external_root / "notes" / "epics")
            self.assertEqual(shared.resolve_epics_dir("engine"),
                             self.engine_root / "notes" / "epics")
            # 同名立项单：external 桶存在、engine 桶也存在——校验各自通过且各读各文件
            self.assertEqual(shared.validate_epic_code(
                "gap-b", shared.resolve_epics_dir("external")), "gap-b")
            self.assertEqual(shared.validate_epic_code(
                "gap-b", shared.resolve_epics_dir("engine")), "gap-b")
            # 异名：各自独有代号只在各自桶里放行
            self.assertEqual(shared.validate_epic_code(
                "external-only", shared.resolve_epics_dir("external")), "external-only")
            with self.assertRaises(ValueError):
                shared.validate_epic_code("external-only", shared.resolve_epics_dir("engine"))

    def test_env_override_selftest_semantics(self):
        """env SANDBAR_EPICS_DIR 现读优先——自测语义不变（先 import 后设 env 也生效）。"""
        import tempfile
        env_dir = Path(tempfile.mkdtemp(prefix="t260907-07-env-"))
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=str(env_dir)):
            self.assertEqual(shared.resolve_epics_dir("external"), env_dir)
            self.assertEqual(shared.resolve_epics_dir(""), env_dir)
        # env 空串 → 回落项目锚（照搬取舍①）
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=""):
            self.assertEqual(shared.resolve_epics_dir("external"),
                             self.external_root / "notes" / "epics")

    def test_empty_project_engine_anchor_fallback(self):
        """空 project → 引擎锚兜底（生产不可达路径，仅夹具/兼容用——方案 N2 措辞）。"""
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=None):
            self.assertEqual(shared.resolve_epics_dir(""), shared.EPICS_DIR)
            self.assertEqual(shared.resolve_epics_dir(None), shared.EPICS_DIR)

    def test_unknown_project_fail_closed(self):
        """未知 key / 隔离条目 → ValueError（fail-closed，不静默退引擎仓）。"""
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=None):
            with self.assertRaises(ValueError):
                shared.resolve_epics_dir("no-such")

    def test_env_missing_dir_not_prechecked(self):
        """env 指向不存在目录 → 不预检照返回（报错由调用侧文案兜住，取舍③）。"""
        with _Env(SANDBAR_EPICS_DIR="/nonexistent/t260907-07/epics"):
            self.assertEqual(shared.resolve_epics_dir("external"),
                             Path("/nonexistent/t260907-07/epics"))


class ValidateEpicCodeProjectAwareTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="t260907-07-val-"))
        self.external_root = self.root / "ext"
        epics = self.external_root / "notes" / "epics"
        epics.mkdir(parents=True)
        (epics / "gap-b.md").write_text("# 立项单：gap-b\n", encoding="utf-8")
        _mk_registry(self.root, "external", "外部项目", [str(self.external_root)])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_error_message_carries_actual_dir(self):
        """报错文案含实际查询目录=项目主目录 notes/epics（C7 诊断信息断言）。"""
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=None):
            with self.assertRaises(ValueError) as cm:
                shared.validate_epic_code("nope", shared.resolve_epics_dir("external"))
            msg = str(cm.exception)
            self.assertIn(str(self.external_root / "notes" / "epics"), msg)
            self.assertNotIn(str(shared.EPICS_DIR), msg)

    def test_env_missing_dir_error_bubbles_with_dir(self):
        """env 指不存在目录 → 档案不存在报错且文案带该目录（C2-③ 显式用例）。"""
        with _Env(SANDBAR_EPICS_DIR="/nonexistent/t260907-07/epics"):
            with self.assertRaises(ValueError) as cm:
                shared.validate_epic_code("gap-b", shared.resolve_epics_dir("external"))
            self.assertIn("/nonexistent/t260907-07/epics", str(cm.exception))

    def test_default_none_keeps_legacy(self):
        """缺省 epics_dir=None = legacy 引擎锚行为不变（零回归面）。"""
        with _Env(SANDBAR_EPICS_DIR=None):
            # 引擎锚下 gap-b 通常不存在：只断言「不抛非 ValueError 异常」+ 文案锚引擎仓
            try:
                shared.validate_epic_code("t260907-nope")
                self.fail("expected ValueError")
            except ValueError as e:
                self.assertIn(str(shared.EPICS_DIR), str(e))
            # 空串放行与形状拒收（畸形输入用例）
            self.assertEqual(shared.validate_epic_code(""), "")
            self.assertEqual(shared.validate_epic_code(None), "")
            with self.assertRaises(ValueError):
                shared.validate_epic_code("../../etc/passwd")
            with self.assertRaises(ValueError):
                shared.validate_epic_code("../escape")


class CmdTicketStartProjectAwareTest(unittest.TestCase):
    """开票路径真函数级断言（stub _connect 不起 Temporal）。"""

    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="t260907-07-cli-"))
        self.engine_root = self.root / "engine-main"
        self.external_root = self.root / "external-main"
        _mk_registry(self.root, "engine", "引擎项目", [str(self.engine_root)])
        _mk_registry(self.root, "external", "外部项目", [str(self.external_root)])
        (self.external_root / "notes" / "epics").mkdir(parents=True)
        (self.external_root / "notes" / "epics" / "gap-b.md").write_text(
            "# 立项单：gap-b\n", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _start(self, project, epic):
        return asyncio.run(client.cmd_ticket_start({
            "template_id": "dev-lane", "ticket_id": "t260907-07-t1",
            "project": project, "epic": epic,
            "lane": "dir", "title": "x",
            "write_set": ["notes/x.md"],
        }))

    def test_external_epic_in_own_root_passes(self):
        """验收①：外部项目立项单在其自己根下 → CLI 开票关联成功。"""
        orig_connect = client._connect
        orig_env = os.environ.get("SANDBAR_EPICS_DIR")
        os.environ.pop("SANDBAR_EPICS_DIR", None)

        class _FakeClose:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        captured = {}

        class _FakeStub:
            async def start_workflow(self, wf, arg, *a, **kw):
                captured["input"] = arg
                return type("R", (), {"result": lambda s: None, "id": "w1",
                                      "result_run_id": "run-1"})()

        async def _connect():
            return _FakeStub()

        client._connect = _connect
        try:
            with _Env(SANDBAR_PROJECTS_DIR=str(self.root)):
                r = self._start("external", "gap-b")
        finally:
            client._connect = orig_connect
            if orig_env is None:
                os.environ.pop("SANDBAR_EPICS_DIR", None)
            else:
                os.environ["SANDBAR_EPICS_DIR"] = orig_env
        self.assertTrue(r.get("ok"), r)
        inp = captured.get("input")
        self.assertIsNotNone(inp)
        self.assertEqual(getattr(inp, "epic", ""), "gap-b")
        self.assertEqual(getattr(inp, "project", ""), "external")

    def test_external_epic_missing_in_engine_anchor_rejected_no_more(self):
        """改造核心：立项单只在外部项目根下、project=external → 不再被引擎锚拒收。

        （镜像断言：同一 epic 对未知 project 在 resolve 层 fail-closed，由
        ResolveEpicsDirTest.test_unknown_project_fail_closed 覆盖。）"""
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=None):
            # 直接驱动校验对（client 层同参），不依赖 _connect stub 细节
            epic = shared.validate_epic_code("gap-b", shared.resolve_epics_dir("external"))
            self.assertEqual(epic, "gap-b")

    def test_engine_anchor_epic_only_in_engine_still_works(self):
        """验收②：引擎项目行为不变——engine 主目录下的立项单照常关联。"""
        (self.engine_root / "notes" / "epics").mkdir(parents=True)
        (self.engine_root / "notes" / "epics" / "engine-only.md").write_text(
            "# 立项单：engine-only\n", encoding="utf-8")
        with _Env(SANDBAR_PROJECTS_DIR=str(self.root), SANDBAR_EPICS_DIR=None):
            self.assertEqual(
                shared.validate_epic_code("engine-only", shared.resolve_epics_dir("engine")),
                "engine-only")
            # external 项目读不到 engine 桶的异名（隔离不串桶）
            with self.assertRaises(ValueError):
                shared.validate_epic_code("engine-only", shared.resolve_epics_dir("external"))


# t260910-14 退役注记：原 EpicNextPrepProjectAwareTest（prepare_epic_next 读段
# 项目感知）随 suggest_next 整链退役删除。

if __name__ == "__main__":
    unittest.main()
