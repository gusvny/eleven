#!/usr/bin/env python3
"""t01 —— shared 归档路径纯函数（M1-3 契约 ①c 的路径承载级真源）。

覆盖：PROJECT_KEY_RE 上移 shared 且 agent_activities 旧名 re-export 同对象；
perkey_projects_root env 三分支（绝对路径尊重 / 空串回落 / 相对路径回落）；
ticket_data_dir 白名单防穿越（project_key 与 ticket_id 双双硬校验）；
ARCHIVE_* 入档/排除口径常量在场且非空。

全 stdlib + temporalio 桩（只挡 agent_activities 的模块级依赖，不碰被测函数）。
跑法：python3 integration/t260902-02/t01_archive_paths.py（cwd=泳道根）
"""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parents[1]))
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （集成侧回收 helper：注册表+atexit，t261002-13）

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "engine"

# ---- temporalio 桩（同 t260901-21 i01 口径）----
_tmod = types.ModuleType("temporalio")
_amod = types.ModuleType("temporalio.activity")


class _ActivityStub:
    logger = logging.getLogger("temporalio-stub-t01")

    def defn(self, fn=None, **kw):
        return (lambda f: f) if fn is None else fn

    def heartbeat(self, *a, **kw):
        pass


_amod.activity = _ActivityStub()
_tmod.activity = _ActivityStub()
sys.modules.setdefault("temporalio", _tmod)
sys.modules.setdefault("temporalio.activity", _amod)
sys.path.insert(0, str(POC))

import shared  # noqa: E402
import agent_activities as aa  # noqa: E402

PASS = FAIL = ENV_FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def main():
    # 1) PROJECT_KEY_RE 真源在 shared，agent_activities re-export 同对象
    ok(shared.PROJECT_KEY_RE is aa.PROJECT_KEY_RE,
       "PROJECT_KEY_RE 真源=shared，agent_activities 旧名同对象")

    # 2) perkey_projects_root env 三分支
    saved = os.environ.get("SANDBAR_PROJECTS_DIR")
    tmp = str(mkdtemp_reclaimed("t01-"))
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = tmp
        ok(str(shared.perkey_projects_root()) == tmp, "env 绝对路径被尊重")
        os.environ["SANDBAR_PROJECTS_DIR"] = ""
        ok(str(shared.perkey_projects_root()).endswith("/.sandbar/projects"),
           "env 空串=未设置回落默认根（不猜空串根目录）")
        os.environ["SANDBAR_PROJECTS_DIR"] = "relative/path"
        ok(str(shared.perkey_projects_root()).endswith("/.sandbar/projects"),
           "env 相对路径=未设置回落默认根（显式拒绝不猜）")
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        ok(str(shared.perkey_projects_root()).endswith("/.sandbar/projects"),
           "env 未设置回落默认根")
    finally:
        if saved is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = saved

    # 3) ticket_data_dir 白名单（project_key / ticket_id 双双硬校验，防 ../ 穿越）
    os.environ["SANDBAR_PROJECTS_DIR"] = tmp
    try:
        d = shared.ticket_data_dir("suyou", "t260902-02")
        ok(str(d) == os.path.join(tmp, "suyou", "data", "tickets", "t260902-02"),
           "合法 key+id 拼出 data/tickets/<id>/")
        for bad_key, bad_id, label in [
                ("../evil", "t1", "project_key 含 ../ 被拒"),
                ("suyou", "../evil", "ticket_id 含 ../ 被拒"),
                ("-bad", "t1", "project_key - 开头被拒"),
                ("suyou", "", "ticket_id 空串被拒"),
                ("Suyou", "t1", "project_key 大写被拒（白名单小写）"),
                ("suyou", "x" * 42, "ticket_id 超长（>41）被拒"),
                ("a/b", "t1", "project_key 含斜杠被拒")]:
            try:
                shared.ticket_data_dir(bad_key, bad_id)
                ok(False, label)
            except ValueError:
                ok(True, label)
    finally:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)

    # 4) ARCHIVE_* 口径常量在场且非空
    for name in ("ARCHIVE_INCLUDE_STAGE_GLOB", "ARCHIVE_INCLUDE_SHOTS_GLOB",
                 "ARCHIVE_INCLUDE_SESSIONS_DIR", "ARCHIVE_EXCLUDED_RULES"):
        val = getattr(shared, name, None)
        ok(bool(val), "%s 常量在场且非空" % name)
    ok(any("credentials" in r for r in shared.ARCHIVE_EXCLUDED_RULES),
       "排除口径含凭据绝不入档")

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, ENV_FAIL, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
