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


class RemovePlaceholder(Base):
    def test_remove_is_ticket2_placeholder(self):
        with self.assertRaises(FailClosed) as cm:
            projects_mod.cmd_project_remove(self.paths, mock.Mock(json=False))
        self.assertIn("remove", str(cm.exception))
        self.assertIn("票②", str(cm.exception))
        rc = cli_main(["--home", str(self.home), "project", "remove", "--key", "seed-a"])
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
