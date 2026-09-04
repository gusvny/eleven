#!/usr/bin/env python3
"""sc_paths_spawn_seam —— 路径契约化端到端（spawn 缝隙，t260903-03 ①d 用户旅程）。

黑盒口径（从引擎 spawn 唯一准备入口进，观测产物 = cmd 的 --patch 链与 patch 文件内容，
即「这个 agent 拿到哪份 persona、哪个模型」的用户可感知结果）：
  A 声明命中：项目在注册条目声明 paths 后，spawn 用声明值——角色 patch 指声明目录
    （而不是现行约定目录，即使两者同时存在），模型来自声明表（而不是回落常量表）。
  B 未声明回落：无 paths 节 / 条目不存在 / key 为空 / key 非法（含穿越形状）四态，
    spawn 与现行约定等价——角色 patch 指 server/dsh/roles，模型读回落常量单源。
  C 软语义（锚点在、内容缺）：声明目录里没有该角色的 preset 文件 → 不红、不打角色
    patch（默认 persona）；声明表里查不到该角色且无 default → 不红、不打模型 patch
    （默认模型）。

夹具全 tmp（注册表 env 注入、回落常量进程内替换，退出还原），不写仓内、不碰 3099。
依赖：temporalio SDK（venv）——不可用则干净 SKIP（exit 0，integration/README 既有口径）。
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths_fixture as fx  # noqa: E402

pass_n = 0
fail_n = 0
failures = []


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  PASS %s" % label)
    else:
        fail_n += 1
        failures.append(label)
        print("  FAIL %s" % label)


try:
    fx.import_engine()
except ImportError as e:
    print("SKIP temporalio SDK 不可用（%s）" % e)
    sys.exit(0)


def ws_dirs(ws):
    return [str(ws)]


def main():
    ws = fx.mk_ws()
    try:
        # ---- A 声明命中：声明值赢过现行约定 ----
        with fx.Registry() as reg:
            declared_roles = ws / "cfg" / "roles"
            declared_roles.mkdir(parents=True)
            declared_role_yml = declared_roles / "reviewer.yml"
            declared_role_yml.write_text("persona: declared-roles-marker\n", encoding="utf-8")
            legacy_yml = fx.mk_legacy_roles(ws)  # 现行约定位置也放一份——证明声明优先
            declared_table = fx.write_routes_table(ws / "cfg" / "routes.yaml",
                                                   "prov-declared", "model-declared")
            reg.write_entry("alpha", ws_dirs(ws), paths_lines=[
                ("roles_dir", "cfg/roles"),
                ("model_routes", "cfg/routes.yaml"),
            ])
            with fx.PatchedRoutesFile(ws / "legacy-table.yaml"):
                fx.write_routes_table(ws / "legacy-table.yaml", "prov-legacy", "model-legacy")
                cmd, _env, art = fx.spawn(ws, project="alpha")
            ok(any(p == str(declared_role_yml) for p in fx.patch_paths(cmd)),
               "A1 角色 patch 指声明目录（非现行约定）")
            ok(not fx.patches_ending(cmd, str(legacy_yml)),
               "A2 现行约定位置的同名文件未被采用")
            ok("provider: prov-declared" in fx.model_patch_text(art),
               "A3 模型来自声明表（provider/model）")
            shutil.rmtree(ws / "cfg")
            shutil.rmtree(ws / "server")

        # ---- B 未声明回落：与现行约定等价（四态）----
        legacy_yml = fx.mk_legacy_roles(ws)
        with fx.Registry() as reg:
            reg.write_entry("beta", ws_dirs(ws))  # b1 无 paths 节
            with fx.PatchedRoutesFile(ws / "legacy-table.yaml"):
                fx.write_routes_table(ws / "legacy-table.yaml", "prov-legacy", "model-legacy")
                cmd, _env, art = fx.spawn(ws, project="beta")
                ok(fx.patches_ending(cmd, str(legacy_yml)), "B1 无 paths 节 → 角色 patch 走现行约定")
                ok("provider: prov-legacy" in fx.model_patch_text(art),
                   "B1 模型走回落常量单源")
                cmd2, _e2, _a2 = fx.spawn(ws, project="ghost", tag="b2")  # b2 条目不存在
                ok(fx.patches_ending(cmd2, str(legacy_yml)), "B2 条目文件不存在 → 回落现行约定")
                cmd3, _e3, _a3 = fx.spawn(ws, project="", tag="b3")  # b3 key 空
                ok(fx.patches_ending(cmd3, str(legacy_yml)), "B3 key 为空 → 回落现行约定")
                cmd4, _e4, _a4 = fx.spawn(ws, project="../evil", tag="b4")  # b4 key 穿越形状
                ok(fx.patches_ending(cmd4, str(legacy_yml)), "B4 key 穿越形状 → 回落且不越界读")
                cmd5, _e5, _a5 = fx.spawn(ws, project="BAD_KEY", tag="b4b")  # b4' key 白名单外
                ok(fx.patches_ending(cmd5, str(legacy_yml)), "B4' key 白名单外 → 回落现行约定")

        # ---- C 软语义：锚点在、内容缺 → 不红、不打对应 patch ----
        with fx.Registry() as reg:
            declared_roles = ws / "cfg2" / "roles"
            declared_roles.mkdir(parents=True)  # 锚点在，但 reviewer.yml 不存在；legacy 也不存在
            empty_table = fx.write_empty_routes_table(ws / "cfg2" / "routes.yaml")
            reg.write_entry("gamma", ws_dirs(ws), paths_lines=[
                ("roles_dir", "cfg2/roles"),
                ("model_routes", "cfg2/routes.yaml"),
            ])
            cmd, _env, art = fx.spawn(ws, project="gamma")
            ok(not fx.patches_ending(cmd, "reviewer.yml"),
               "C1 角色 preset 缺 → 不打角色 patch（默认 persona，不红）")
            ok(not fx.model_patch_files(art),
               "C2 声明表查不到该角色且无 default → 不打模型 patch（默认模型，不红）")
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    print("SC sc_paths_spawn_seam pass=%d fail=%d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
