#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_epic_anchor_two_projects.py — 立项目录锚项目感知×env 自测语义（t260907-07，GAP-B）。

intent（用户可感知行为，验收①②的校验面+工单正文 env 口径）：项目把立项单放自己
主目录 notes/epics/ 时，CLI 开票校验（validate_epic_code×resolve_epics_dir）取
**该项目**的立项单——外部项目不再误报「立项代号不存在」、引擎桶项目行为不变；
env SUYOU_EPICS_DIR 覆盖保持「自测指向」语义（两项目同指 env 目录、优先于项目锚、
空串回落项目锚）；未知项目 key fail-closed（不静默退引擎仓）；env 指不存在目录
报错可辨不崩（文案含「目录为空或不存在」）。

与 developer L1（单测含畸形输入细目）intent 不同面：本场景守双项目同名/异名立项单
的「取各项目」行为与 env 覆盖优先级——工单正文验收夹具形态的直译。
Hermetic：tmp per-key 注册表+tmp 立项目录，shared.py stdlib-only 直驱，零网络零 docker。
Run: python3 integration/t260907-07/sc_epic_anchor_two_projects.py（cwd=仓库根）
三态：末行 SUMMARY pass=X fail=Y env_fail=Z na=W；exit 0=PASS / 1=FAIL / 2=ENV_FAIL。
"""
import os
import pathlib
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "server", "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import epic_fixture as fx  # noqa: E402
import shared  # noqa: E402

passed, failed, env_failed = 0, 0, 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label, flush=True)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, " — " + str(detail)[:200] if detail else ""), flush=True)
    return cond


def main():
    print("== t260907-07 ①立项目录锚项目感知（双项目同名/异名 + env 自测语义）")
    if not hasattr(shared, "resolve_epics_dir"):
        print("  FAIL resolve_epics_dir 未落地（实现未合入，TDD 预期红）", flush=True)
        print("SUMMARY pass=0 fail=1 env_fail=0 na=0", flush=True)
        return 1
    eng_name, ext_name = "engine", "external"
    # 负例代号：任何桶都不存在的档案（跨项目拒绝腿用引擎桶异名，另配全缺失档）
    with fx.RegistryEnv() as reg:
        eng = fx.make_project(reg.root, eng_name)
        ext = fx.make_project(reg.root, ext_name)
        fx.write_epic(eng, "gap-b")
        fx.write_epic(ext, "gap-b")
        fx.write_epic(eng, "engine-only")
        fx.write_epic(ext, "external-only")
        eng_epics = str(eng / "notes" / "epics")
        ext_epics = str(ext / "notes" / "epics")

        def resolve(key):
            return shared.resolve_epics_dir(key)

        # ---- A 解析各取各的（项目主目录 notes/epics，非引擎仓） ----
        check(resolve(eng_name) == pathlib.Path(eng_epics),
              "A1 engine 锚自己主目录 notes/epics", resolve(eng_name))
        check(resolve(ext_name) == pathlib.Path(ext_epics),
              "A2 external 锚自己主目录 notes/epics", resolve(ext_name))
        check(resolve(eng_name) != resolve(ext_name), "A3 两桶锚点互异（不串桶）")

        # ---- B 同名立项单：各自通过（验收①②） ----
        check(shared.validate_epic_code("gap-b", resolve(eng_name)) == "gap-b",
              "B1 engine 同名 gap-b 通过")
        check(shared.validate_epic_code("gap-b", resolve(ext_name)) == "gap-b",
              "B2 external 同名 gap-b 通过（改造前误报「立项代号不存在」的面）")

        # ---- C 异名：自项目通过、跨项目拒绝且文案带该项目实际查询目录 ----
        check(shared.validate_epic_code("engine-only", resolve(eng_name)) == "engine-only",
              "C1 engine 异名自桶通过")
        check(shared.validate_epic_code("external-only", resolve(ext_name)) == "external-only",
              "C2 external 异名自桶通过")
        try:
            shared.validate_epic_code("engine-only", resolve(ext_name))
            cross_ok, msg = False, "未拒收"
        except ValueError as e:
            msg = str(e)
            cross_ok = ("立项代号不存在" in msg and ext_epics in msg and eng_epics not in msg)
        check(cross_ok, "C3 engine 异名对 external 拒收且文案带 external 实际目录（诊断信息）", msg)

        # ---- D 未知项目 fail-closed（不静默退引擎仓） ----
        try:
            resolve("no-such-project")
            unk_ok, unk_msg = False, "未拒收"
        except ValueError as e:
            unk_ok, unk_msg = True, str(e)
        check(unk_ok and "no-such-project" in unk_msg,
              "D 未知项目 key 拒收（fail-closed，不静默兜底）", unk_msg)

        # ---- E env 覆盖自测语义：两项目同指 env 目录、优先于项目锚 ----
        env_root = tempfile.mkdtemp(prefix="t26090707-epics-env-")
        env_dir = os.path.join(env_root, "notes", "epics")
        os.makedirs(env_dir)
        with open(os.path.join(env_dir, "env-only.md"), "w") as f:
            f.write("# env-only\n")
        os.environ["SUYOU_EPICS_DIR"] = env_dir
        try:
            check(resolve(eng_name) == pathlib.Path(env_dir)
                  and resolve(ext_name) == pathlib.Path(env_dir),
                  "E1 env 覆盖：两项目同指 env 目录（优先于项目锚）")
            check(shared.validate_epic_code("env-only", resolve(eng_name)) == "env-only",
                  "E2 env 桶档案经项目锚校验通过（env 现读生效）")
        finally:
            os.environ.pop("SUYOU_EPICS_DIR", None)

        # ---- F env 空串：回落项目锚（不落空路径） ----
        os.environ["SUYOU_EPICS_DIR"] = ""
        try:
            check(resolve(eng_name) == pathlib.Path(eng_epics),
                  "F env 空串回落项目锚（不取空串当目录）")
        finally:
            os.environ.pop("SUYOU_EPICS_DIR", None)

        # ---- G env 指不存在目录：报错可辨不崩 ----
        os.environ["SUYOU_EPICS_DIR"] = os.path.join(env_root, "not-exist")
        try:
            shared.validate_epic_code("gap-b", resolve(eng_name))
            g_ok, g_msg = False, "未拒收"
        except ValueError as e:
            g_msg = str(e)
            g_ok = "目录为空或不存在" in g_msg
        finally:
            os.environ.pop("SUYOU_EPICS_DIR", None)
        check(g_ok, "G env 指不存在目录：报错含「目录为空或不存在」", g_msg)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
