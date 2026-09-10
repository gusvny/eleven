#!/usr/bin/env python3
"""sc_paths_failclosed_red —— 路径契约化故障面对抗（spawn 缝隙红传导，t260903-03 ①d 三态）。

对抗口径（用户视角：错配置必须得到「红工单 + 点名文件」，绝不静默拿错 persona/模型猜着跑）：
  F1 条目 project.yaml 损坏（存在但解析不了）→ 红，报错点名条目文件——即使现行约定
     位置有同名角色文件、回落表也在位，也绝不静默回落（三态总纲：不得按缺失跳过）。
  F2 声明锚点缺失（model_routes）→ **分层兜底**（宿主风险令 260910 夜，KI-030 收窄
     为分态留痕）：spawn 不再红、agent 照跑，但生效模型必须真来自仓内兜底表
     （model_patch 在场且=兜底表解析值——若静默回落 profile 默认则 patch 不存在，
     本腿即红）；分态点名留痕（state+path+error）由读面层守卫钉（t260910-14 S1）。
     roles_dir 锚点缺失仍红（roles/persona 契约未放宽，F2b 不变）。
  F3 声明锚点类型错位：model_routes 声明成目录 → 同 F2 兜底语义（不可解析=坏表族，
     兜底生效不静默）；roles_dir 解析后是文件 → 仍红（F3b 不变）。
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


def must_fallback(label, expected, **kw):
    """宿主令①分层兜底腿：model_routes 非 ok 态不红，agent 拿**仓内兜底表**模型
    （model_patch 在场且值=兜底表解析）；若静默回落 profile 默认（patch 不存在）
    或拿错值 = 对抗失败。分态点名留痕（state+path+error）由读面层守卫钉（S1 场景）。"""
    try:
        _cmd, _env, art = fx.spawn(**kw)
    except Exception as e:  # noqa: BLE001
        ok(False, label + "——spawn 红（兜底未生效）：%s" % str(e)[:120])
        return
    txt = fx.model_patch_text(art)
    got = {}
    for ln in txt.splitlines():
        s = ln.strip()
        for k in ("provider", "model"):
            if s.startswith(k + ":"):
                got[k] = s.split(":", 1)[1].strip()
    ok(bool(txt) and got.get("provider") == expected[0] and got.get("model") == expected[1],
       label + "（patch 值=%s 期望=%s）" % (got, expected))


def main():
    ws = fx.mk_ws()
    try:
        with fx.Registry() as reg:
            legacy_yml = fx.mk_legacy_roles(ws)  # 现行约定在位——红不靠它兜底
            legacy_table = ws / "legacy-table.yaml"
            fx.write_routes_table(legacy_table, "prov-legacy", "model-legacy")

            # F1 条目损坏：坏 YAML；现行约定位置文件与回落表全在位也必须红
            with fx.PatchedRoutesFile(legacy_table):
                reg.write_entry("corrupt", ws_dirs(ws),
                                raw="schema: v1\n\t bad: [unclosed\n")
                must_raise("F1 条目 project.yaml 损坏 → 红",
                           "corrupt/project.yaml", ws=ws, project="corrupt")

            # F2 锚点缺失：声明了但解析后不存在（两个键各一例）
            reg.write_entry("miss-routes", ws_dirs(ws), paths_lines=[
                ("roles_dir", "ok/roles"),
                ("model_routes", "cfg/absent-routes.yaml"),
            ])
            (ws / "ok" / "roles").mkdir(parents=True)
            (ws / "ok" / "roles" / "reviewer.yml").write_text("persona: x\n", encoding="utf-8")
            # 期望值=同一公开单点解析面对兜底（仓内）表的产出——机器无关（不钉具体模型名）：
            # 建无 paths 声明的探针条目 → resolve_routes_table 走 decl_missing 兜底 → 同表同值
            reg.write_entry("fb-probe", ws_dirs(ws))
            _res = fx.import_shared().resolve_routes_table("fb-probe")
            _route = fx.import_shared().model_route_for(fx.ROLE, "", table=_res["table"],
                                                        routes_file=_res["path"])
            _exp = (_route["provider"], _route["model"]) if _route else ("", "")
            must_fallback("F2a model_routes 锚点缺失 → 分层兜底生效（非静默 profile 默认）",
                          _exp, ws=ws, project="miss-routes")
            reg.write_entry("miss-roles", ws_dirs(ws), paths_lines=[
                ("roles_dir", "cfg/absent-roles"),
                ("model_routes", "ok/routes.yaml"),
            ])
            fx.write_routes_table(ws / "ok" / "routes.yaml", "prov-ok", "model-ok")
            must_raise("F2b roles_dir 锚点缺失 → 红点名路径（不被软跳过吞掉）",
                       "absent-roles", ws=ws, project="miss-roles")

            # F3 类型错位：表声明成目录 / 目录声明成文件
            reg.write_entry("type-routes", ws_dirs(ws), paths_lines=[
                ("roles_dir", "ok/roles"),
                ("model_routes", "cfg/dir-as-table"),
            ])
            (ws / "cfg" / "dir-as-table").mkdir(parents=True)
            must_fallback("F3a model_routes 解析后是目录 → 坏表族兜底生效（非静默）",
                          _exp, ws=ws, project="type-routes")
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
