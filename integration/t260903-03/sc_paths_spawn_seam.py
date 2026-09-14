#!/usr/bin/env python3
"""sc_paths_spawn_seam —— 路径契约化端到端（spawn 缝隙，t260903-03 ①d 用户旅程）。

黑盒口径（从引擎 spawn 唯一准备入口进，观测产物 = cmd 的 --patch 链与 patch 文件内容，
即「这个 agent 拿到哪份 persona、哪个模型」的用户可感知结果）：
  A 声明命中：项目在注册条目声明 paths 后，spawn 用声明值——角色 patch 指声明目录
    （而不是现行约定目录，即使两者同时存在），模型来自声明表（roles 契约不变）。
  B 未声明（t260914-05 兜底腿退役）：无 paths 节 / 条目不存在 / key 为空 / key 非法
    （含穿越形状）多态，角色 patch 仍走现行约定（roles 语义不变），模型面**无表**：
    不打 model patch（=本轮模型来 profile 默认）且引擎面点名 state=decl_missing——
    绝不静默取任何仓内表。
  C 软语义（锚点在、内容缺）：声明目录里没有该角色的 preset 文件 → 不红、不打角色
    patch（默认 persona）；声明表里查不到该角色且无 default → 不红、不打模型 patch
    （默认模型）。

夹具全 tmp（注册表 env 注入、告警捕获退出还原），不写仓内、不碰 3099。
依赖：temporalio SDK（venv）——不可用则 ENV_FAIL 环境红退 2（三态契约 §7.3，绝不放行）。
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
    print("ENV_FAIL: temporalio SDK 不可用（%s）" % e)
    sys.exit(2)


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
            fx.write_routes_table(ws / "cfg" / "routes.yaml",
                                  "prov-declared", "model-declared")
            reg.write_entry("alpha", ws_dirs(ws), paths_lines=[
                ("roles_dir", "cfg/roles"),
                ("model_routes", "cfg/routes.yaml"),
            ])
            cmd, _env, art = fx.spawn(ws, project="alpha")
            ok(any(p == str(declared_role_yml) for p in fx.patch_paths(cmd)),
               "A1 角色 patch 指声明目录（非现行约定）")
            ok(not fx.patches_ending(cmd, str(legacy_yml)),
               "A2 现行约定位置的同名文件未被采用")
            ok("provider: prov-declared" in fx.model_patch_text(art),
               "A3 模型来自声明表（provider/model）")
            shutil.rmtree(ws / "cfg")
            shutil.rmtree(ws / "server")

        # ---- B 未声明=无表（t260914-05）：roles 走现行约定，模型面无表+点名 ----
        legacy_yml = fx.mk_legacy_roles(ws)

        def b_leg(label, project, tag):
            """公共断言：角色 patch 走现行约定（roles 语义不变）+ 模型面无表（不打
            model patch）+ 引擎面点名 state=decl_missing（禁静默回落仓内表）。"""
            with fx.capture_route_warnings() as warns:
                cmd, _env, art = fx.spawn(ws, project=project, tag=tag)
            ok(fx.patches_ending(cmd, str(legacy_yml)), label + "角色 patch 走现行约定")
            ok(not fx.model_patch_files(art),
               label + "模型面无表：不打 model patch（禁静默回落）")
            ok(any("[model_route]" in w and "state=decl_missing" in w for w in warns),
               label + "引擎面点名 state=decl_missing")

        with fx.Registry() as reg:
            reg.write_entry("beta", ws_dirs(ws))  # b1 无 paths 节
            b_leg("B1 无 paths 节 → ", "beta", "b1")
            b_leg("B2 条目文件不存在 → ", "ghost", "b2")
            b_leg("B3 key 为空 → ", "", "b3")
            b_leg("B4 key 穿越形状 → ", "../evil", "b4")
            b_leg("B4' key 白名单外 → ", "BAD_KEY", "b4b")

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

    print("SC sc_paths_spawn_seam pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
