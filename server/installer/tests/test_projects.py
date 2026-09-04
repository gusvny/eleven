"""projects 子命令族单测：add 校验闸全枚举 / 文件锚原子写与零残留 / ①b 预布置旅程 /
票计数三态 / list 形状。

外部源桩口径：票计数的 Temporal 依赖用 stub client.py 脚本桩复现（ok/不可达/SDK 缺失/
超时/烂输出五态），不靠真 Temporal；装载器真源 shared.py 按真仓装载（只读）。
注册表全程走 SANDBAR_PROJECTS_DIR 临时目录，不碰生产 ~/.sandbar/projects。
CLI 契约面与 integration/t260904-10 三场景共同冻结（--key/--name/--dir flags 面）。
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_DIR.parents[0]
sys.path.insert(0, str(SERVER_DIR))

from installer import projects as projects_mod  # noqa: E402
from installer.cli import main as cli_main  # noqa: E402
from installer.runtime import InstallPaths  # noqa: E402
from installer.service import FailClosed  # noqa: E402


def _entry_text(key, name, d):
    return ("schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
            % (key, name, d))


def _write_entry(reg, key, name, d):
    d = pathlib.Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (reg / key).mkdir(parents=True, exist_ok=True)
    (reg / key / "project.yaml").write_text(_entry_text(key, name, d), encoding="utf-8")


def _tree_snapshot(root: pathlib.Path):
    """注册表全树字节快照（相对路径+文件字节），零残留断言用（测试侧基线）。"""
    items = []
    if root.is_dir():
        for f in sorted(root.rglob("*")):
            rel = str(f.relative_to(root))
            items.append((rel, f.read_bytes() if f.is_file() else b"<dir>"))
    return items


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="sandbar-ut-proj-"))
        self.reg = self.tmp / "reg"
        self.reg.mkdir()
        (self.reg / ".migrated").write_text("source: ut-fixture\n", encoding="utf-8")
        self.home = self.tmp / "home"
        self.paths = InstallPaths(root=str(REPO_ROOT), home=str(self.home))
        self._env = {}
        self._setenv("SANDBAR_PROJECTS_DIR", str(self.reg))
        self._setenv("SUYOU_PROJECTS_YAML", None)
        self._setenv("SANDBAR_HOME", str(self.home))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _setenv(self, key, value):
        self._env[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def proj_root(self, name="root-a"):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def tree(self):
        return _tree_snapshot(self.reg)

    def add_args(self, key, name, root, as_json=False):
        dirs = root if isinstance(root, list) else [root]
        return SimpleNamespace(key=key, name=name, dir=[str(d) for d in dirs],
                               json=as_json)


class AddSuccess(Base):
    def test_success_roundtrip(self):
        root = self.proj_root()
        rc = projects_mod.cmd_project_add(self.paths, self.add_args("demo", "演示", root))
        self.assertEqual(rc, 0)
        shared = projects_mod._load_shared(self.paths.poc_dir)
        projects, quarantined = shared.load_projects_registry()
        self.assertEqual([p["key"] for p in projects if p["key"] == "demo"], ["demo"])
        self.assertEqual(quarantined, [])
        demo = [p for p in projects if p["key"] == "demo"][0]
        self.assertEqual(demo["name"], "演示")
        self.assertEqual(demo["dirs"], [str(root)])
        # 单根模型：恰一条 dirs；文件可被装载器原样解析（严格子集可往返）
        text = (self.reg / "demo" / "project.yaml").read_text("utf-8")
        parsed = shared.parse_project_file(text, "ut")
        self.assertEqual(parsed["dirs"], [str(root)])

    def test_json_output_machine_judgeable(self):
        lines = []
        rc = projects_mod.cmd_project_add(
            self.paths, self.add_args("demo", "演示", self.proj_root(), as_json=True),
            log=lines.append)
        self.assertEqual(rc, 0)
        payload = json.loads("\n".join(lines))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "add")
        self.assertEqual(payload["project"]["key"], "demo")
        self.assertEqual(payload["credentials"], "fallback")
        codes = sorted(w["code"] for w in payload["warnings"])
        self.assertEqual(codes, ["credentials-fallback", "paths-default",
                                 "verify-yaml-undeclared"])

    def test_credentials_preplaced_journey_contract_1b(self):
        # 契约①b 旅程：目录与 per-key credentials 可先于 add 手工布置 → add 仍成功，
        # 且 credentials 两态报告可辨（在位=绿/fallback 黄，输出与裸目录不同）。
        pre = self.reg / "precred"
        pre.mkdir()
        (pre / "credentials.yaml").write_text("version: 1\nfixture: pre\n", encoding="utf-8")
        bare_lines, pre_lines = [], []
        rc1 = projects_mod.cmd_project_add(
            self.paths, self.add_args("barecred", "裸", self.proj_root("r-bare")),
            log=bare_lines.append)
        rc2 = projects_mod.cmd_project_add(
            self.paths, self.add_args("precred", "预布置", self.proj_root("r-pre")),
            log=pre_lines.append)
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        pre_out = "\n".join(pre_lines)
        self.assertIn("在位", pre_out)
        self.assertIn("credentials", pre_out)
        # JSON 口径同源可判：credentials=present 且无 fallback 黄牌
        (self.reg / "precred2").mkdir()
        (self.reg / "precred2" / "credentials.yaml").write_text("version: 1\n", encoding="utf-8")
        json_lines = []
        rc3 = projects_mod.cmd_project_add(
            self.paths, self.add_args("precred2", "预布置二", self.proj_root("r-pre2"),
                                      as_json=True),
            log=json_lines.append)
        self.assertEqual(rc3, 0)
        payload = json.loads("\n".join(json_lines))
        self.assertEqual(payload["credentials"], "present")
        self.assertNotIn("credentials-fallback", json.dumps(payload))
        self.assertNotEqual("\n".join(bare_lines), pre_out,
                            "credentials 两态输出必须可辨")
        self.assertIn("credentials", "\n".join(bare_lines))

    def test_seed_auto_migration_first_load(self):
        # C1-b：不预置 .migrated，首装载真跑自动播种；既有条目 add 后字节不变。
        fresh = self.tmp / "fresh-reg"
        fresh.mkdir()
        self._setenv("SANDBAR_PROJECTS_DIR", str(fresh))
        shared = projects_mod._load_shared(self.paths.poc_dir)
        seed_keys = set()
        seed = SERVER_DIR / "dsh" / "projects.yaml"
        if seed.is_file():
            seed_keys = {p["key"] for p in
                         shared.parse_legacy_registry_file(seed.read_text("utf-8"), str(seed))}
        self.assertFalse((fresh / ".migrated").is_file())
        before = {k: (fresh / k / "project.yaml") for k in seed_keys}
        rc = projects_mod.cmd_project_add(
            self.paths, self.add_args("demo", "演示", self.proj_root()))
        self.assertEqual(rc, 0)
        self.assertTrue((fresh / ".migrated").is_file())
        for k, f in before.items():
            self.assertTrue(f.is_file(), "播种条目 %s 应在案" % k)
        projects, quarantined = shared.load_projects_registry()
        keys = {p["key"] for p in projects}
        self.assertIn("demo", keys)
        self.assertTrue(seed_keys.issubset(keys), "播种条目不受影响")
        self.assertEqual(quarantined, [])


class AddRejections(Base):
    def setUp(self):
        super().setUp()
        self.root_a = self.proj_root("root-a")
        _write_entry(self.reg, "seed-a", "种子甲", self.root_a)

    def _reject(self, key, name, root, *fragments):
        before = self.tree()
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_add(self.paths, self.add_args(key, name, root))
        for frag in fragments:
            self.assertIn(frag, str(cm.exception))
        self.assertEqual(before, self.tree(), "拒收必须零残留：%s" % key)

    def test_key_shape_whitelist(self):
        root = self.proj_root("r-shape")
        for bad in ("", "Upper", "-lead", "under_score", "a" * 42, "../escape", "空格 key"):
            self._reject(bad, "n", root, "key 不合法")

    def test_key_upper_boundary_accepted(self):
        # 正则上界 41 字符（首字符 + {0,40}）合法收
        rc = projects_mod.cmd_project_add(
            self.paths, self.add_args("a" * 41, "Boundary", self.proj_root("r-bound")))
        self.assertEqual(rc, 0)

    def test_name_gate(self):
        root = self.proj_root("r-name")
        self._reject("new-key", "", root, "name 不能为空")
        self._reject("new-key", "  ", root, "name 不能为空")
        self._reject("new-key", "含#井号", root, "name", "含 #")
        self._reject("new-key", "两\n行", root, "name", "含换行")

    def test_root_gate(self):
        self._reject("new-key", "n", str(self.tmp / "nope"), "不存在")
        self._reject("new-key", "n", "relative/path", "绝对路径")
        plain = self.tmp / "plain.txt"
        plain.write_text("x", encoding="utf-8")
        self._reject("new-key", "n", plain, "不是目录")

    def test_multi_root_semantic_reject(self):
        # 单根模型（决策6）：多目录输入=语义拒收（FailClosed），非 argparse 用法错
        before = self.tree()
        d1, d2 = self.proj_root("m1"), self.proj_root("m2")
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_add(
                self.paths, self.add_args("new-key", "n", [d1, d2]))
        self.assertIn("单根目录模型", str(cm.exception))
        self.assertEqual(before, self.tree())

    def test_key_already_registered_idempotent(self):
        self._reject("seed-a", "改名", self.proj_root("r-other"), "已注册", "幂等")

    def test_key_matches_quarantined_entry(self):
        bad = self.reg / "broken"
        bad.mkdir()
        (bad / "project.yaml").write_text("schema: v1\njunk\n", encoding="utf-8")
        self._reject("broken", "n", self.proj_root("r-broken"), "隔离")

    def test_root_crossing_parent_child_equal(self):
        # 新根=既有根的父目录（tmp 本身）
        self._reject("new-key", "n", self.tmp, "交叉或互为父子")
        # 新根嵌在既有根之下（先真实建出该子目录，过「存在」闸才到交叉闸）
        nested = self.root_a / "sub"
        nested.mkdir()
        self._reject("new-key", "n", nested, "交叉或互为父子")
        # 新根与既有根完全相等（不同 key 同根）→ 文案报两个 key
        before = self.tree()
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_add(
                self.paths, self.add_args("new-key", "n", self.root_a))
        msg = str(cm.exception)
        self.assertIn("seed-a", msg)
        self.assertIn("new-key", msg)
        self.assertEqual(before, self.tree())

    def test_legacy_env_mode_rejected(self):
        legacy = self.tmp / "legacy.yaml"
        legacy.write_text("projects:\n  - key: seed-a\n    name: 种子甲\n    dirs:\n"
                          "      - %s\n" % self.root_a, encoding="utf-8")
        self._setenv("SUYOU_PROJECTS_YAML", str(legacy))
        self._reject("new-key", "n", self.proj_root("r-legacy"), "SUYOU_PROJECTS_YAML")

    def test_preexisting_dir_without_entry_accepted(self):
        # 目录在而无条目（①b 预布置旅程）：add 照常成功——排他锚是 project.yaml 文件
        (self.reg / "prewalk").mkdir()
        rc = projects_mod.cmd_project_add(
            self.paths, self.add_args("prewalk", "预走", self.proj_root("r-prewalk")))
        self.assertEqual(rc, 0)
        self.assertTrue((self.reg / "prewalk" / "project.yaml").is_file())


class AddWriteFailure(Base):
    def test_claim_write_failure_rolls_back_zero_residue(self):
        before = self.tree()
        root = self.proj_root()
        with mock.patch.object(projects_mod.os, "replace",
                               side_effect=OSError(13, "permission denied")):
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_add(self.paths, self.add_args("demo", "演示", root))
        self.assertIn("已回滚", str(cm.exception))
        self.assertEqual(before, self.tree(), "写失败回滚后注册表必须零残留")

    def test_rollback_keeps_preplaced_credentials_dir(self):
        # 回滚只删「本票创建且已空」的目录；①b 预布置目录原样保留
        pre = self.reg / "prewalk"
        pre.mkdir()
        (pre / "credentials.yaml").write_text("keep\n", encoding="utf-8")
        with mock.patch.object(projects_mod.os, "replace",
                               side_effect=OSError(13, "permission denied")):
            with self.assertRaises(FailClosed):
                projects_mod.cmd_project_add(
                    self.paths, self.add_args("prewalk", "预走", self.proj_root("r-pw")))
        self.assertTrue((pre / "credentials.yaml").is_file(), "预布置文件不得被回滚误删")
        self.assertFalse((pre / "project.yaml").exists(), "认领残留必须清掉")

    def test_postcheck_failure_rolls_back(self):
        before = self.tree()
        root = self.proj_root()
        with mock.patch.object(projects_mod, "serialize_project_entry",
                               return_value="schema: v1\njunk\n"):
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_add(self.paths, self.add_args("demo", "演示", root))
        self.assertIn("零残留", str(cm.exception))
        self.assertEqual(before, self.tree())


class TicketCounts(Base):
    def _stub_client(self, behavior):
        """stub client.py 脚本桩：按 behavior 复现票计数外部依赖五态。
        _ticket_counts 只消费 paths.poc_dir → 用 SimpleNamespace 指到桩目录。"""
        poc = self.tmp / "poc-stub"
        poc.mkdir(exist_ok=True)
        if behavior == "ok":
            body = ('import json,sys\nrows=[{"exec_status":"RUNNING"},'
                    '{"exec_status":"RUNNING"},{"exec_status":"COMPLETED"}]\n'
                    'print(json.dumps({"ok":True,"result":{"count":3,"tickets":rows}}))\n')
        elif behavior == "svc-error":
            body = 'import json\nprint(json.dumps({"ok":False,"error":"GRPC: unavailable"}))\n'
        elif behavior == "sdk-missing":
            body = 'import sys\nsys.stderr.write("Traceback\\nModuleNotFoundError: '\
                   "No module named 'temporalio'\\n\")\nsys.exit(1)\n"
        elif behavior == "infra-error":
            body = 'import sys\nsys.stderr.write("gRPC unreachable\\n")\nsys.exit(1)\n'
        elif behavior == "bad-json":
            body = 'print("not json")\n'
        else:
            raise ValueError(behavior)
        (poc / "client.py").write_text(body, encoding="utf-8")
        return SimpleNamespace(poc_dir=str(poc))

    def test_ok_counts_and_archived_from_fs(self):
        (self.reg / "seed-a" / "data" / "tickets" / "t1").mkdir(parents=True)
        (self.reg / "seed-a" / "data" / "tickets" / "t2").mkdir(parents=True)
        paths = self._stub_client("ok")
        counts = projects_mod._ticket_counts(paths, "seed-a", self.reg)
        self.assertEqual(counts, {"state": "ok", "open": 2, "closed": 1, "archived": 2})

    def _state_of(self, behavior):
        paths = self._stub_client(behavior)
        return projects_mod._ticket_counts(paths, "seed-a", self.reg)["state"]

    def test_sdk_missing_distinguishable_from_unreachable(self):
        # KI-039 教训：SDK 缺失 ≠ 服务不可达 ≠ 无数据，三态可辨
        self.assertEqual(self._state_of("sdk-missing"), "sdk-missing")
        self.assertEqual(self._state_of("infra-error"), "unreachable")
        self.assertEqual(self._state_of("svc-error"), "unreachable")
        self.assertEqual(self._state_of("bad-json"), "unreachable")

    def test_timeout_is_reaped_and_reported(self):
        poc = self.tmp / "poc-stub"
        poc.mkdir(exist_ok=True)
        (poc / "client.py").write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
        paths = SimpleNamespace(poc_dir=str(poc))
        with mock.patch.object(projects_mod, "TICKET_QUERY_TIMEOUT_S", 0.3):
            counts = projects_mod._ticket_counts(paths, "seed-a", self.reg)
        self.assertEqual(counts["state"], "unreachable")
        self.assertIn("超时", counts["detail"])


class ListReport(Base):
    def test_list_json_shape_and_quarantine_localization(self):
        _write_entry(self.reg, "seed-a", "种子甲", self.proj_root("root-a"))
        bad = self.reg / "broken"
        bad.mkdir()
        (bad / "project.yaml").write_text("schema: v1\njunk\n", encoding="utf-8")
        lines = []
        with mock.patch.object(projects_mod, "_ticket_counts",
                               return_value={"state": "ok", "open": 1, "closed": 2,
                                             "archived": 3}):
            rc = projects_mod.cmd_project_list(self.paths, mock.Mock(json=True),
                                               log=lines.append)
        self.assertEqual(rc, 0)
        payload = json.loads("\n".join(lines))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "per-key")
        self.assertEqual([p["key"] for p in payload["projects"]], ["seed-a"])
        self.assertEqual(payload["projects"][0]["tickets"],
                         {"open": 1, "closed": 2, "archived": 3})
        self.assertEqual(len(payload["quarantined"]), 1)
        q = payload["quarantined"][0]
        self.assertEqual(q["key"], "broken", "隔离条目 --json 需带 key 字段（deepFind 面）")
        self.assertIn("project.yaml", q["error"], "隔离原因须含 <dir>/project.yaml 定位")

    def test_list_skips_reserved_dirs_without_entry(self):
        _write_entry(self.reg, "seed-a", "种子甲", self.proj_root("root-a"))
        (self.reg / "datadirc").mkdir()  # 保留位目录：无 project.yaml，装载语义=跳过
        lines = []
        with mock.patch.object(projects_mod, "_ticket_counts",
                               return_value={"state": "ok", "open": 0, "closed": 0,
                                             "archived": 0}):
            rc = projects_mod.cmd_project_list(self.paths, mock.Mock(json=True),
                                               log=lines.append)
        self.assertEqual(rc, 0)
        self.assertNotIn("datadirc", "\n".join(lines))

    def test_list_degrades_not_red_when_temporal_down(self):
        _write_entry(self.reg, "seed-a", "种子甲", self.proj_root("root-a"))
        lines = []
        rc = projects_mod.cmd_project_list(self.paths, mock.Mock(json=False),
                                           log=lines.append)
        self.assertEqual(rc, 0, "Temporal 不可达只降级不红")
        out = "\n".join(lines)
        self.assertIn("票计数降级", out)
        self.assertIn("seed-a", out)

    def test_degraded_states_distinguishable_in_output(self):
        # 两态降级输出可辨（不可达 ≠ SDK 缺失，KI-039）
        _write_entry(self.reg, "seed-a", "种子甲", self.proj_root("root-a"))
        out1, out2 = [], []
        with mock.patch.object(projects_mod, "_ticket_counts",
                               return_value={"state": "unreachable", "detail": "GRPC: x"}):
            projects_mod.cmd_project_list(self.paths, mock.Mock(json=False), log=out1.append)
        with mock.patch.object(projects_mod, "_ticket_counts",
                               return_value={"state": "sdk-missing", "detail": "No module"}):
            projects_mod.cmd_project_list(self.paths, mock.Mock(json=False), log=out2.append)
        self.assertIn("unreachable", "\n".join(out1))
        self.assertIn("sdk-missing", "\n".join(out2))
        self.assertNotEqual("\n".join(out1), "\n".join(out2))

    def test_legacy_mode_listed(self):
        legacy = self.tmp / "legacy.yaml"
        legacy.write_text("projects:\n  - key: seed-a\n    name: 种子甲\n    dirs:\n"
                          "      - %s\n" % self.proj_root("root-a"), encoding="utf-8")
        self._setenv("SUYOU_PROJECTS_YAML", str(legacy))
        lines = []
        with mock.patch.object(projects_mod, "_ticket_counts",
                               return_value={"state": "ok", "open": 0, "closed": 0,
                                             "archived": 0}):
            rc = projects_mod.cmd_project_list(self.paths, mock.Mock(json=True),
                                               log=lines.append)
        self.assertEqual(rc, 0)
        payload = json.loads("\n".join(lines))
        self.assertEqual(payload["mode"], "legacy")

    def test_registry_mixed_scene_is_red(self):
        # 混合现场：无 .migrated、盘上条目与种子同 key 但内容不可复现 → 装载器
        # fail-closed（根缺失+种子在位是自动播种，不是红——那是另一条路径）
        shared = projects_mod._load_shared(self.paths.poc_dir)
        mixed = self.tmp / "mixed-reg"
        mixed.mkdir()
        seed = SERVER_DIR / "dsh" / "projects.yaml"
        entry = shared.parse_legacy_registry_file(seed.read_text("utf-8"), str(seed))[0]
        d = mixed / entry["key"]
        d.mkdir()
        (d / "project.yaml").write_text(_entry_text(entry["key"], "被手改的名字",
                                                    entry["dirs"][0]), encoding="utf-8")
        self._setenv("SANDBAR_PROJECTS_DIR", str(mixed))
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_list(self.paths, mock.Mock(json=False))
        self.assertIn("注册表装载失败", str(cm.exception))


class RemoveStub(Base):
    """remove 侧共用脚手架：条目 fixture + stub client.py（票号级 rows）。"""

    def setUp(self):
        super().setUp()
        self.root_a = self.proj_root("root-a")
        (self.root_a / ".lane" / "t260904-01").mkdir(parents=True)
        _write_entry(self.reg, "seed-a", "种子甲", self.root_a)
        # data/：t1=已归档（manifest 在位）、t2=半成品（目录在 manifest 缺）
        tdir = self.reg / "seed-a" / "data" / "tickets" / "t1"
        tdir.mkdir(parents=True)
        (tdir / "archive.json").write_text('{"schema": "v1", "ticket": "t1"}\n',
                                           encoding="utf-8")
        (tdir / "stages").mkdir()
        (tdir / "stages" / "stage_x.json").write_text("{}", encoding="utf-8")
        (self.reg / "seed-a" / "data" / "tickets" / "t2").mkdir(parents=True)
        (self.reg / "seed-a" / "credentials.yaml").write_text("version: 1\n",
                                                              encoding="utf-8")
        # 第二条目 seed-b：默认现场两个项目（最后条目闸单测里再摘掉）
        _write_entry(self.reg, "seed-b", "种子乙", self.proj_root("root-b"))

    _stub_seq = 0

    def _stub_rows(self, rows, ok=True, error=None, exit_zero=True, stderr="",
                   stdout=None):
        """stub client.py：吐票号级 rows（running/completed 混排可控）。
        每次调用独立 poc 目录——同测试内多态注入不得互相覆盖。"""
        RemoveStub._stub_seq += 1
        poc = self.tmp / ("poc-stub-rm-%d" % RemoveStub._stub_seq)
        poc.mkdir()
        # 布桩 poc_dir（方案 R2）：真身 shared.py 复制（装载闸走真语义）+ 假 client.py
        shutil.copy(SERVER_DIR / "dsh" / "temporal-poc" / "shared.py",
                    poc / "shared.py")
        if stdout is None:
            payload = {"ok": ok, "result": {"tickets": rows}}
            if error:
                payload["error"] = error
            stdout = json.dumps(payload)
        body = (
            "import sys\n"
            "sys.stdout.write(%r)\n"
            "sys.stderr.write(%r)\n"
            "sys.exit(%d)\n" % (stdout, stderr, 0 if exit_zero else 1))
        (poc / "client.py").write_text(body, encoding="utf-8")
        return SimpleNamespace(poc_dir=str(poc))

    def _args(self, key="seed-a", as_json=True, dry=False, purge_data=False,
              purge_cred=False, confirm_last=False):
        return SimpleNamespace(key=key, json=as_json, dry_run=dry,
                               purge_data=purge_data, purge_credentials=purge_cred,
                               confirm_last=confirm_last)

    def _cmd(self, paths=None, **kw):
        out = []
        rc = projects_mod.cmd_project_remove(paths or self._stub_rows([]),
                                             self._args(**kw), log=out.append)
        return rc, out


class RemoveLifecycle(RemoveStub):
    def _shared(self):
        return projects_mod._load_shared(self.paths.poc_dir)

    def test_default_remove_retires_keeps_data_and_unlists(self):
        rc, out = self._cmd()
        self.assertEqual(rc, 0)
        payload = json.loads("\n".join(out))
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["report"]["data_kept"])
        self.assertTrue(payload["report"]["credentials_kept"])
        # 退役在位：project.yaml 消失、retired-<ts> 在位（决策2）
        entry_dir = self.reg / "seed-a"
        self.assertFalse((entry_dir / "project.yaml").exists())
        retired = list(entry_dir.glob("project.yaml.retired-*"))
        self.assertEqual(len(retired), 1)
        self.assertEqual(payload["retired_to"], str(retired[0]))
        # data/credentials 字节不动（验收6）
        self.assertTrue((entry_dir / "data" / "tickets" / "t1" / "archive.json").exists())
        self.assertTrue((entry_dir / "credentials.yaml").exists())
        self.assertEqual(payload["report"]["data_bytes"] > 0, True)
        # 泳道清单只报不删（验收10）
        self.assertEqual(payload["report"]["lanes"], ["t260904-01"])
        self.assertTrue((self.root_a / ".lane" / "t260904-01").exists())
        # Python 侧装载器：不再列本 key（可逆摘除=装载器隐身）
        shared = self._shared()
        projects, quarantined = shared.scan_registry(self.reg)
        self.assertNotIn("seed-a", [p["key"] for p in projects],
                         "摘除后装载器不再列本 key（其余条目不受影响）")
        self.assertIn("seed-b", [p["key"] for p in projects])
        self.assertEqual(len(quarantined), 0)

    def test_unarchived_closed_yellow_and_purge_gate(self):
        # prune 现场（C1/R3）：t1 已归档且被 prune（stub 不再返回），t2 目录在
        # manifest 缺 + stub 返回 COMPLETED t2 → 差集含 t2，黄牌亮、purge 拒
        paths = self._stub_rows([{"id": "t2", "exec_status": "COMPLETED"}])
        out = []
        rc = projects_mod.cmd_project_remove(paths, self._args(dry=True),
                                             log=out.append)
        self.assertEqual(rc, 0)
        self.assertIn("t2", "\n".join(out), "dry-run 黄牌列未归档票号")
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(paths, self._args(purge_data=True),
                                            log=lambda *_: None)
        self.assertIn("t2", str(cm.exception))
        self.assertIn("未归档", str(cm.exception))
        self.assertTrue((self.reg / "seed-a" / "data").exists(), "拒 purge 零删除")
        self.assertTrue((self.reg / "seed-a" / "project.yaml").exists(),
                        "purge 闸在退役之前拦下，注册表不动")

    def test_manifest_malformed_is_fail_closed_naming_file(self):
        (self.reg / "seed-a" / "data" / "tickets" / "t2" / "archive.json").write_text(
            "{not json", encoding="utf-8")
        paths = self._stub_rows([])
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(paths, self._args(), log=lambda *_: None)
        self.assertIn("archive.json", str(cm.exception))
        # 缺 schema 行同判（畸形态第二形）
        (self.reg / "seed-a" / "data" / "tickets" / "t2" / "archive.json").write_text(
            '{"ticket": "t2"}', encoding="utf-8")
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(paths, self._args(), log=lambda *_: None)
        self.assertIn("archive.json", str(cm.exception))

    def test_readd_same_key_archive_chain_continuous(self):
        paths = self._stub_rows([])
        rc, _ = self._cmd()
        self.assertEqual(rc, 0)
        shared = self._shared()
        # re-add 同 key：目录在、无 project.yaml=新注册旅程（契约①a-1 再接入）
        add_out = []
        rc2 = projects_mod.cmd_project_add(
            paths, SimpleNamespace(key="seed-a", name="种子甲",
                                   dir=[str(self.root_a)], json=True),
            log=add_out.append)
        self.assertEqual(rc2, 0)
        projects, _q = shared.scan_registry(self.reg)
        self.assertIn("seed-a", [p["key"] for p in projects], "re-add 同 key 再接入成功")
        # 归档链不断：data/tickets 子目录原样（t1+t2），credentials 原样
        self.assertEqual(
            sorted(c.name for c in (self.reg / "seed-a" / "data" / "tickets").iterdir()),
            ["t1", "t2"])
        self.assertTrue((self.reg / "seed-a" / "credentials.yaml").exists())

    def test_running_ticket_rejects_with_ids_and_zero_change(self):
        before = self.tree()
        paths = self._stub_rows([{"id": "t9", "exec_status": "RUNNING"},
                                 {"id": "t8", "exec_status": "COMPLETED"}])
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(paths, self._args(), log=lambda *_: None)
        msg = str(cm.exception)
        self.assertIn("t9", msg, "在飞闸拒摘须报票号（验收5）")
        self.assertIn("在飞", msg)
        self.assertEqual(self.tree(), before, "拒摘零现场变更")

    def test_unreachable_and_sdk_missing_fail_closed(self):
        # remove 语义反转：list 语境=黄牌降级，remove 语境=fail-closed 拒摘无绕过旗
        before = self.tree()
        cases = [
            (self._stub_rows([], ok=False, error="GRPC: unavailable"), "GRPC: unavailable"),
            (self._stub_rows([], exit_zero=False,
                             stderr="ModuleNotFoundError: No module named 'temporalio'"),
             "No module named 'temporalio'"),
            (self._stub_rows([], exit_zero=False, stderr="gRPC unreachable"),
             "gRPC unreachable"),
            (self._stub_rows([], stdout="not json"), "不是合法 JSON"),
        ]
        last = None
        for paths, marker in cases:
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_remove(paths, self._args(),
                                                log=lambda *_: None)
            last = str(cm.exception)
            self.assertIn("拒", last)
            self.assertIn(marker, last, "各态下场可辨（KI-039）")
        self.assertIn("sandbar up", last, "文案含可达性诊断指路（验收7）")
        self.assertEqual(self.tree(), before)

    def test_timeout_is_fail_closed(self):
        poc = self.tmp / "poc-stub-slow"
        poc.mkdir(exist_ok=True)
        shutil.copy(SERVER_DIR / "dsh" / "temporal-poc" / "shared.py", poc / "shared.py")
        (poc / "client.py").write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
        paths = SimpleNamespace(poc_dir=str(poc))
        with mock.patch.object(projects_mod, "TICKET_QUERY_TIMEOUT_S", 0.3):
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_remove(paths, self._args(),
                                                log=lambda *_: None)
        self.assertIn("超时", str(cm.exception))

    def test_purge_flags_combined_delete_both(self):
        # t1 已归档、t2 半成品目录无 manifest 且 stub 台面无此票 → 差集空，闸过
        paths = self._stub_rows([])
        rc, out = self._cmd(purge_data=True, purge_cred=True)
        self.assertEqual(rc, 0)
        payload = json.loads("\n".join(out))
        self.assertFalse((self.reg / "seed-a" / "data").exists())
        self.assertFalse((self.reg / "seed-a" / "credentials.yaml").exists())
        self.assertEqual(payload["purged"], {"data": str(self.reg / "seed-a" / "data"),
                                             "credentials": str(self.reg / "seed-a" / "credentials.yaml")})

    def test_purge_data_keeps_credentials_and_vice_versa(self):
        paths = self._stub_rows([])
        projects_mod.cmd_project_remove(paths, self._args(purge_data=True),
                                        log=lambda *_: None)
        self.assertFalse((self.reg / "seed-a" / "data").exists())
        self.assertTrue((self.reg / "seed-a" / "credentials.yaml").exists(),
                        "--purge-data 不连带 credentials（双旗独立）")

    def test_purge_credentials_only(self):
        # seed-b 已在 fixture 注册：seed-a 摘除仅 purge credentials
        paths = self._stub_rows([])
        rc, out = self._cmd(purge_cred=True)
        self.assertEqual(rc, 0)
        self.assertFalse((self.reg / "seed-a" / "credentials.yaml").exists())
        self.assertTrue((self.reg / "seed-a" / "data").exists(),
                        "--purge-credentials 不连带 data（双旗独立）")

    def test_dry_run_full_gates_zero_change(self):
        before = self.tree()
        paths = self._stub_rows([{"id": "t9", "exec_status": "RUNNING"}])
        with self.assertRaises(FailClosed):
            projects_mod.cmd_project_remove(paths, self._args(dry=True),
                                            log=lambda *_: None)
        self.assertEqual(self.tree(), before, "dry-run 也要过闸（在飞闸拦下）")
        paths2 = self._stub_rows([])
        out = []
        rc = projects_mod.cmd_project_remove(
            paths2, self._args(dry=True, purge_data=True, purge_cred=True),
            log=out.append)
        self.assertEqual(rc, 0)
        self.assertEqual(self.tree(), before, "dry-run 零现场变更（验收8 清单）")
        payload = json.loads("\n".join(out))
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["plan"]["purge"]["data"]["path"],
                         str(self.reg / "seed-a" / "data"))
        self.assertGreater(payload["plan"]["purge"]["data"]["bytes"], 0, "将删清单含字节")
        self.assertGreater(payload["plan"]["purge"]["credentials"]["bytes"], 0)
        self.assertTrue((self.reg / "seed-a" / "project.yaml").exists())

    def test_last_project_gate(self):
        # 摘掉 seed-b 只剩 seed-a → 无旗拒，带旗摘+零条目警告（验收9）
        (self.reg / "seed-b" / "project.yaml").unlink()
        paths = self._stub_rows([])
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(paths, self._args(), log=lambda *_: None)
        self.assertIn("--confirm-last", str(cm.exception))
        self.assertIn("空表", str(cm.exception))
        out = []
        rc = projects_mod.cmd_project_remove(self._stub_rows([]),
                                             self._args(confirm_last=True,
                                                        as_json=False),
                                             log=out.append)
        self.assertEqual(rc, 0)
        self.assertIn("零条目", "\n".join(out))

    def test_legacy_env_rejected_for_remove(self):
        legacy = self.tmp / "legacy.yaml"
        legacy.write_text("projects: []\n", encoding="utf-8")
        self._setenv("SUYOU_PROJECTS_YAML", str(legacy))
        before = self.tree()
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(self._stub_rows([]), self._args(),
                                            log=lambda *_: None)
        self.assertIn("SUYOU_PROJECTS_YAML", str(cm.exception))
        self.assertEqual(self.tree(), before)

    def test_unregistered_and_quarantined_distinguishable(self):
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(self._stub_rows([]),
                                            self._args(key="nobody"),
                                            log=lambda *_: None)
        self.assertIn("未注册", str(cm.exception))
        bad = self.reg / "qbad"
        bad.mkdir()
        (bad / "project.yaml").write_text("schema: v9\njunk\n", encoding="utf-8")
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(self._stub_rows([]),
                                            self._args(key="qbad"),
                                            log=lambda *_: None)
        self.assertIn("隔离", str(cm.exception))
        self.assertIn("project.yaml", str(cm.exception))

    def test_bad_key_shape_rejected_blocks_traversal(self):
        with self.assertRaises(FailClosed):
            projects_mod.cmd_project_remove(self._stub_rows([]),
                                            self._args(key="../escape"),
                                            log=lambda *_: None)

    def test_retired_collision_is_rejected_not_overwritten(self):
        class _FakeTime:
            @staticmethod
            def strftime(_fmt, _t=None):
                return "2026-09-04T00:00:00Z"

            @staticmethod
            def gmtime():
                return 0
        with mock.patch.object(projects_mod, "_time", _FakeTime):
            pre = self.reg / "seed-a" / "project.yaml.retired-2026-09-04T00:00:00Z"
            pre.write_text("旧退役件\n", encoding="utf-8")
            before = self.tree()
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_remove(self._stub_rows([]), self._args(),
                                                log=lambda *_: None)
            self.assertIn("退役文件已存在", str(cm.exception))
            self.assertEqual(self.tree(), before, "碰撞拒收零现场变更")
            self.assertEqual(pre.read_text(encoding="utf-8"), "旧退役件\n")

    def test_rollback_scene_changed_never_overwrites(self):
        # R1-4/C2：自检失败 + 并发 add 已重建 project.yaml → 放弃回滚（红），不覆盖
        paths = self._stub_rows([])
        shared = projects_mod._load_shared(paths.poc_dir)

        real_scan = shared.scan_registry
        state = {"n": 0}

        def _racing_scan(reg_root):
            # 首调=前置装载放行（真语义）；二调=写后自检：模拟并发 add 已重建
            # 条目后自检再红
            state["n"] += 1
            if state["n"] == 1:
                return real_scan(reg_root)
            (self.reg / "seed-a" / "project.yaml").write_text(
                _entry_text("seed-a", "并发重建", self.root_a), encoding="utf-8")
            raise ValueError("注入自检失败")

        with mock.patch.object(shared, "scan_registry", side_effect=_racing_scan):
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_remove(paths, self._args(),
                                                log=lambda *_: None)
        self.assertIn("现场已变", str(cm.exception))
        self.assertEqual(
            (self.reg / "seed-a" / "project.yaml").read_text(encoding="utf-8"),
            _entry_text("seed-a", "并发重建", self.root_a),
            "回滚绝不无条件覆盖他人新条目（C2：不断言 rename 抛错，断言放弃回滚+红）")

    def test_rollback_on_postcheck_failure_restores_entry(self):
        # 自检失败且现场未变 → 回滚改名，条目原样在位（零残留）
        paths = self._stub_rows([])
        shared = projects_mod._load_shared(paths.poc_dir)
        real_scan = shared.scan_registry
        state = {"n": 0}

        def _failing_postcheck(reg_root):
            state["n"] += 1
            if state["n"] == 1:
                return real_scan(reg_root)
            raise ValueError("注入自检失败")

        with mock.patch.object(shared, "scan_registry",
                               side_effect=_failing_postcheck):
            with self.assertRaises(FailClosed) as cm:
                projects_mod.cmd_project_remove(paths, self._args(),
                                                log=lambda *_: None)
        self.assertIn("已回滚", str(cm.exception))
        self.assertTrue((self.reg / "seed-a" / "project.yaml").exists())
        self.assertEqual(list((self.reg / "seed-a").glob("project.yaml.retired-*")), [])

    def test_remove_json_shape_machine_judgeable(self):
        rc, out = self._cmd()
        self.assertEqual(rc, 0)
        payload = json.loads("\n".join(out))
        for field in ("ok", "action", "project", "retired_to", "purged", "report"):
            self.assertIn(field, payload)
        for field in ("lanes", "data_bytes", "credentials_bytes", "data_kept",
                      "credentials_kept", "closed_unarchived", "warnings"):
            self.assertIn(field, payload["report"])
        self.assertEqual(payload["action"], "remove")
        self.assertEqual(payload["project"]["key"], "seed-a")


class RemoveCliWiring(Base):
    def test_remove_flags_accepted_by_cli_semantic_red(self):
        # 旗面被 argparse 接受；坏 key 走语义拒收（exit 1 而非用法错 2）
        rc = cli_main(["--home", "/nonexistent-home-ut", "project", "remove",
                       "--key", "bad key", "--dry-run", "--purge-data",
                       "--purge-credentials", "--confirm-last", "--json"])
        self.assertEqual(rc, 1)


class CliWiring(Base):
    def test_add_via_cli_main_flags(self):
        rc = cli_main(["--home", str(self.home), "project", "add",
                       "--key", "demo", "--name", "演示", "--dir", str(self.proj_root())])
        self.assertEqual(rc, 0)
        self.assertTrue((self.reg / "demo" / "project.yaml").is_file())

    def test_missing_key_is_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            cli_main(["--home", str(self.home), "project", "add", "--name", "n",
                      "--dir", str(self.proj_root())])
        self.assertEqual(cm.exception.code, 2)

    def test_naming_neutrality_guard(self):
        # 硬规则5：新面零 suyou 字样（存量 env 名/存量装载器文件名只引用）
        src = (SERVER_DIR / "installer" / "projects.py").read_text("utf-8")
        for i, line in enumerate(src.split("\n"), 1):
            if "suyou" in line.lower():
                self.assertTrue("SUYOU_PROJECTS_YAML" in line
                                or "suyou-projects.ts" in line,
                                "projects.py:%d 出现未申报的 suyou 标识" % i)


if __name__ == "__main__":
    unittest.main()
