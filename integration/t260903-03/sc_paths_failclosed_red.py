#!/usr/bin/env python3
"""sc_paths_failclosed_red —— 路径契约化故障面对抗（spawn 缝隙红传导，t260903-03 ①d 三态）。

对抗口径（用户视角：错配置必须得到「红工单 + 点名文件」，绝不静默拿错 persona/模型猜着跑）：
  F1 条目 project.yaml 损坏（存在但解析不了）→ 红，报错点名条目文件——即使现行约定
     位置有同名角色文件，也绝不静默回落（三态总纲：不得按缺失跳过）。
  F2 无表族（t260914-05 兜底分支退役）：model_routes 指向缺失文件（file_missing）/
     未声明（decl_missing）→ spawn 不红、agent 照跑，但**不打模型 patch**（=本轮模型
     来 profile 默认，消费方另点名），且引擎面单点点名留痕（state+路径+指纹）——
     绝不静默取任何仓内表。roles_dir 锚点缺失仍红（roles/persona 契约未放宽，F2b 不变）。
  F3 声明锚点类型错位：model_routes 声明成目录 → bad_content 无表点名；roles_dir
     解析后是文件 → 仍红（F3b 不变）。
  F4 声明值畸形代表例（未知键 / 绝对路径 / .. 穿越形状）→ 红且报错带键名。

夹具全 tmp，env 注入退出还原。依赖 temporalio SDK（venv）——不可用则 ENV_FAIL 环境红退 2
（三态契约 §7.3，绝不放行）。
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


def must_raise(label, frag, **kw):
    """spawn 必须红（抛错）且文案点名 frag；不抛=静默回落=对抗失败。"""
    try:
        fx.spawn(**kw)
    except Exception as e:  # noqa: BLE001——引擎任何异常形态都算红，文案才是断言点
        ok(frag in str(e), label + "（文案点名 %r）" % frag)
        return
    ok(False, label + "——未红（静默回落，三态违反）")


def must_no_table(label, expect_state, **kw):
    """t260914-05 无表子用例：model_routes 非 ok 态 → spawn 不红、不打模型 patch
    （agent 继承 profile 默认，绝不静默取任何仓内表），且引擎面**点名留痕**
    （[model_route] state=<态> + 指纹段）。三态各自可辨（expect_state 由调用方钉）。"""
    with fx.capture_route_warnings() as warns:
        try:
            _cmd, _env, art = fx.spawn(**kw)
        except Exception as e:  # noqa: BLE001
            ok(False, label + "——spawn 红（缺表不应红）：%s" % str(e)[:120])
            return None
    patches = fx.model_patch_files(art)
    ok(not patches, label + "（无表→不打 model patch；实得 %r）" % [p.name for p in patches])
    hits = [w for w in warns
            if "[model_route]" in w and "state=%s" % expect_state in w and "指纹=" in w]
    ok(bool(hits), label + "（引擎面点名 state=%s+指纹；实得 %r）" % (expect_state, warns[:2]))
    return {"state": expect_state, "warns": warns}


def main():
    ws = fx.mk_ws()
    try:
        with fx.Registry() as reg:
            legacy_yml = fx.mk_legacy_roles(ws)  # 现行约定在位——红不靠它兜底

            # F1 条目损坏：坏 YAML；现行约定位置文件在位也必须红（不静默回落）
            reg.write_entry("corrupt", ws_dirs(ws),
                            raw="schema: v1\n\t bad: [unclosed\n")
            must_raise("F1 条目 project.yaml 损坏 → 红",
                       "corrupt/project.yaml", ws=ws, project="corrupt")

            # F2 无表族（t260914-05）：spawn 不红、无模型 patch、引擎面点名（state+指纹）
            reg.write_entry("miss-routes", ws_dirs(ws), paths_lines=[
                ("roles_dir", "ok/roles"),
                ("model_routes", "cfg/absent-routes.yaml"),
            ])
            (ws / "ok" / "roles").mkdir(parents=True)
            (ws / "ok" / "roles" / "reviewer.yml").write_text("persona: x\n", encoding="utf-8")
            states = set()
            r = must_no_table("F2a model_routes 指向缺失文件 → 无表点名（file_missing）",
                              "file_missing", ws=ws, project="miss-routes")
            if r:
                states.add(r["state"])
            reg.write_entry("no-decl", ws_dirs(ws), paths_lines=[("roles_dir", "ok/roles")])
            r = must_no_table("F2c 未声明 paths.model_routes → 无表点名（decl_missing，不回落仓内表）",
                              "decl_missing", ws=ws, project="no-decl")
            if r:
                states.add(r["state"])
            reg.write_entry("miss-roles", ws_dirs(ws), paths_lines=[
                ("roles_dir", "cfg/absent-roles"),
                ("model_routes", "ok/routes.yaml"),
            ])
            fx.write_routes_table(ws / "ok" / "routes.yaml", "prov-ok", "model-ok")
            must_raise("F2b roles_dir 锚点缺失 → 红点名路径（不被软跳过吞掉）",
                       "absent-roles", ws=ws, project="miss-roles")

            # F3 类型错位：表声明成目录（bad_content 无表点名）/ 目录声明成文件（仍红）
            reg.write_entry("type-routes", ws_dirs(ws), paths_lines=[
                ("roles_dir", "ok/roles"),
                ("model_routes", "cfg/dir-as-table"),
            ])
            (ws / "cfg" / "dir-as-table").mkdir(parents=True)
            r = must_no_table("F3a model_routes 解析后是目录 → 坏表族无表点名（bad_content）",
                              "bad_content", ws=ws, project="type-routes")
            if r:
                states.add(r["state"])
            ok(len(states) == 3, "F2/F3 无表三态互异（实得 %s）" % sorted(states))
            reg.write_entry("type-roles", ws_dirs(ws), paths_lines=[
                ("roles_dir", "cfg/file-as-roles"),
                ("model_routes", "ok/routes.yaml"),
            ])
            (ws / "cfg").mkdir(exist_ok=True)
            (ws / "cfg" / "file-as-roles").write_text("not a dir\n", encoding="utf-8")
            must_raise("F3b roles_dir 解析后是文件 → 红",
                       "file-as-roles", ws=ws, project="type-roles")

            # F4 声明值畸形代表例（seam 传导；完整矩阵在组件层 UT）
            for key, lines, frag in [
                ("mal-unknown", [("roles_dir", "ok/roles"), ("model_routes", "ok/routes.yaml"),
                                 ("bogus_key", "x")], "bogus_key"),
                ("mal-abs", [("roles_dir", "/etc"), ("model_routes", "ok/routes.yaml")], "roles_dir"),
                ("mal-dotdot", [("roles_dir", "../escape"), ("model_routes", "ok/routes.yaml")], "roles_dir"),
            ]:
                reg.write_entry(key, ws_dirs(ws), paths_lines=lines)
                must_raise("F4 %s 声明值畸形 → 红且带键名" % key, frag,
                           ws=ws, project=key)
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    print("SC sc_paths_failclosed_red pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
