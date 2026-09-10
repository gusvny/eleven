#!/usr/bin/env python3
"""t260902-07 集成测试 ②：查表函数与钉模型机制的动态行为（需 PyYAML）。

校验对象：server/engine/shared.py

口径（260910 宿主拍板 + 260910 夜宿主风险令）：**路由表运行期可调——谁跑哪个模型
不钉死**；真源=项目声明 paths.model_routes 指向的文件（读写同源），读侧分层兜底=
仓内 server/model-routes.yaml（迁移窗口期不断供）。本测试只做性质断言：
- resolve_routes_table 三态点名：声明缺失 / 文件缺失 / 内容坏分别可辨（state 命名
  恒不因兜底成功而洗白——禁静默，KI-030 收窄：旧「except: return None」语义废除）；
- 表里每个角色：model_route_for(role, routes_file=…, table=…) 返回 provider/model
  齐备，且**与表内容一致**（防「查表函数与真源漂移」这类真错误）；
- `integration` 角色必须在表里（不许整段删掉）；
- 无 tasks 段的角色：带 kind 与不带 kind 的查表结果一致（分工键不串）；
- 声明解析放宽：`~/…` 展开与绝对路径合法、`..` 仍拒、相对语义不变（畸形输入用例，
  桩/固定夹具，不靠真外部源）；
- _pin_default_model：钉用户层、整段替换旧 agent-default-model（含段内注释），
  资源全在临时目录内、测毕清理（生命周期回收）。

历史沿革：本测试原先钉死 integration=kimi-coding/k3 等角色取值（260907 口径），
260910 宿主裁定后快照断言移除；260910 头注钉的「表 YAML 非法 → 返回 None（不抛
异常）」静默语义随 t260910-14 三态化**重写**（KI-030 条目自记的同步义务）。
cwd = 泳道根。须用带 PyYAML 的解释器（engine/.venv/bin/python）执行。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server" / "engine"))
import shared  # noqa: E402
try:
    import agent_activities  # noqa: E402,F401  （_pin_default_model 在此，依赖 temporalio）
    HAS_AA = True
except ImportError:  # 无 temporalio 的解释器：钉模型用例记 ENV_FAIL（缺 SDK=环境红），其余照跑
    HAS_AA = False

FAILS = []


def check(cond, msg):
    if cond:
        print("PASS %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL %s" % msg)


def _mk_project(root, key, body):
    d = Path(root) / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.yaml").write_text(
        "schema: v1\npaths:\n%sproject:\n  - key: %s\n    name: itest\n    dirs:\n      - %s\n"
        % (body, key, root), "utf-8")
    return d


def main():
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("ENV_FAIL: 需要 PyYAML：请用 server/engine/.venv/bin/python 执行")
        return 2

    # ---- 1. 现表（仓内兜底表；声明缺失态点名）查表与真源一致（性质断言，不钉角色取值）
    resolved = shared.resolve_routes_table("")
    check(resolved["state"] == "decl_missing",
          "空 project → 声明缺失态点名 decl_missing（实得 %r）" % resolved["state"])
    check(resolved["declared"] is None and "兜底" in resolved["error"],
          "decl_missing 态 error 点名兜底（留痕不静默：%s）" % resolved["error"][:60])
    check(isinstance(resolved["table"], dict) and (resolved["table"].get("roles") or {}),
          "兜底腿拿到仓内表（roles 非空）")
    table = resolved["table"] or {}
    roles = table.get("roles") or {}
    check("integration" in roles, "表中含 integration 角色（不许整段删掉）")
    for role, declared in roles.items():
        if role == "product-operation":
            continue  # 其 tasks 子表由分工键性质覆盖
        declared = declared if isinstance(declared, dict) else {}
        got = shared.model_route_for(role, table=table, routes_file=resolved["path"])
        check(isinstance(got, dict) and bool(got.get("provider")) and bool(got.get("model")),
              "model_route_for(%s) 返回 provider/model 齐备（实得 %r）" % (role, got))
        check(got == {"provider": declared.get("provider"), "model": declared.get("model")},
              "model_route_for(%s) 与表内容一致（表=%r 实得=%r）"
              % (role, {"provider": declared.get("provider"),
                        "model": declared.get("model")}, got))

    default_declared = table.get("default") or {}
    r = shared.model_route_for("integration", "proofread", table=table,
                               routes_file=resolved["path"])
    check(r == {"provider": roles.get("integration", {}).get("provider")
                or default_declared.get("provider"),
                "model": roles.get("integration", {}).get("model")
                or default_declared.get("model")},
          "integration 无 tasks 段 → 分工键落 role 级（实得 %r）" % r)

    try:
        shared.model_route_for("integration")
        check(False, "model_route_for 无路径无表 → 拒绝（单点化，不隐式回落常量）")
    except ValueError:
        check(True, "model_route_for 无路径无表 → 拒绝（单点化，不隐式回落常量）")

    # ---- 2. 三态 + 解析放宽（夹具注册表，全在临时目录内；畸形输入桩复现，不靠外部源）
    tmp = Path(tempfile.mkdtemp(prefix="t260902-07-itest-"))
    try:
        good = tmp / "routes.yaml"
        good.write_text("default:\n  provider: zai-coding-cn\n  model: glm-5.3-flash\n"
                        "roles:\n  integration:\n    provider: zai-coding-cn\n"
                        "    model: glm-5.3-flash\n", "utf-8")
        home = tmp / "home"
        home.mkdir()
        tilde_target = home / "tilde-routes.yaml"
        shutil.copy(good, tilde_target)

        def resolve_with(decl_body):
            reg = tmp / ("reg-" + str(abs(hash(decl_body)) % 10**8))
            _mk_project(reg, "itest", decl_body)
            old = os.environ.get("SANDBAR_PROJECTS_DIR")
            os.environ["SANDBAR_PROJECTS_DIR"] = str(reg)
            try:
                return shared.resolve_routes_table("itest")
            finally:
                if old is None:
                    os.environ.pop("SANDBAR_PROJECTS_DIR", None)
                else:
                    os.environ["SANDBAR_PROJECTS_DIR"] = old

        # ok：声明指向文件（绝对路径形态）存在且可解析 → 真源生效
        rr = resolve_with("  model_routes: %s\n" % good)
        check(rr["state"] == "ok" and Path(rr["path"]) == good and rr["declared"] == good,
              "声明指向文件（绝对路径）→ ok 态、path=声明文件（实得 %r/%s）" % (rr["state"], rr["path"]))
        # ~ 展开：声明 ~/… 落到展开后的文件（夹具家目录经 HOME 注入）
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        try:
            rr = resolve_with("  model_routes: ~/tilde-routes.yaml\n")
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
        check(rr["state"] == "ok" and Path(rr["path"]) == tilde_target,
              "声明 ~/… → 展开后命中（实得 %r/%s）" % (rr["state"], rr["path"]))
        # .. 逃逸仍拒（ProjectPathsError fail-closed）
        try:
            resolve_with("  model_routes: ../escape.yaml\n")
            check(False, "声明 .. 逃逸 → ProjectPathsError（机器级放宽不免除越界闸）")
        except shared.ProjectPathsError:
            check(True, "声明 .. 逃逸 → ProjectPathsError（机器级放宽不免除越界闸）")
        # file_missing：声明存在、文件缺失 → 兜底接管读（仓内表），点名 file_missing
        rr = resolve_with("  model_routes: %s\n" % (tmp / "nope.yaml"))
        check(rr["state"] == "file_missing" and rr["table"] is not None
              and Path(rr["path"]) == shared.MODEL_ROUTES_FILE,
              "声明文件缺失 → file_missing 点名 + 兜底=仓内表（实得 %r，path=%s）"
              % (rr["state"], rr["path"]))
        # bad_content：声明文件不可解析 → bad_content 点名 + 兜底
        bad = tmp / "bad.yaml"
        bad.write_text("roles: [unclosed\n  provider: :::\n", "utf-8")
        rr = resolve_with("  model_routes: %s\n" % bad)
        check(rr["state"] == "bad_content" and rr["table"] is not None,
              "声明文件内容坏 → bad_content 点名 + 兜底接管（实得 %r）" % rr["state"])
        # 畸形 YAML 传入 model_route_for（直接路径形态）→ None（warning 留痕由共享 logger 承担）
        r = shared.model_route_for("integration", routes_file=bad)
        check(r is None, "畸形 YAML → model_route_for 返回 None（留痕 warning，不再静默）")
        # 条目缺字段 → 落 default
        partial = tmp / "partial.yaml"
        partial.write_text("default:\n  provider: zai\n  model: glm-5.3-flash\n"
                           "roles:\n  integration:\n    provider: zai-coding-cn\n", "utf-8")
        r = shared.model_route_for("integration", routes_file=partial)
        check(r == {"provider": "zai", "model": "glm-5.3-flash"},
              "条目缺 model → 落 default（实得 %r）" % r)

        # 3. _pin_default_model：整段替换旧 agent-default-model（含注释），其余内容不动
        if not HAS_AA:
            print("ENV_FAIL: _pin_default_model 用例：本解释器无 temporalio"
                  "（请用 server/engine/.venv/bin/python 复跑）")
        else:
            dst = tmp / "dsh"
            dst.mkdir()
            (dst / "settings.yaml").write_text(
                "providers:\n  zai-coding-cn:\n    apiKeyEnv: X\n"
                "agent-default-model:\n  # 旧注释行\n  provider: kimi-coding\n  model: k3\n"
                "other-key: keep\n", "utf-8")
            agent_activities._pin_default_model(dst, {"provider": "zai-coding-cn", "model": "glm-5.3-flash"})
            out = (dst / "settings.yaml").read_text("utf-8")
            check("provider: kimi-coding" not in out.split("other-key")[0].split("agent-default-model:")[-1]
                  if "agent-default-model:" in out else False,
                  "旧 agent-default-model 段（含注释）被整段摘除")
            check("agent-default-model:\n  provider: zai-coding-cn\n  model: glm-5.3-flash\n" in out,
                  "新路由钉进用户层 agent-default-model 段")
            check("other-key: keep" in out and "apiKeyEnv: X" in out,
                  "settings 其余段不受影响")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not HAS_AA:  # 缺 temporalio SDK=环境红（env_fail 优先级高于产品红）
        return 2
    if FAILS:
        print("\n%d 项失败" % len(FAILS))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
