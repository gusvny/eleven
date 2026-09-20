#!/usr/bin/env python3
"""t260902-07 集成测试 ②：查表函数与钉模型机制的动态行为（需 PyYAML）。

校验对象：server/engine/shared.py

口径（260910 宿主拍板；t260914-05 兜底分支退役）：**路由表运行期可调——谁跑哪个模型
不钉死**；唯一真源=项目声明 paths.model_routes 指向的文件（读写同源），**无表=
table=None + 单点点名（state+路径+指纹），绝不静默回落任何仓内表**。本测试只做
性质断言（夹具自足，畸形输入用桩/固定夹具复现，不靠真外部源）：
- 声明命中（ok 态）：表里每个角色 model_route_for(role, routes_file=…, table=…)
  返回 provider/model 齐备且**与表内容一致**（防「查表函数与真源漂移」）；无 tasks
  段的角色带 kind 与不带 kind 结果一致（分工键不串）；无路径无表 → 拒绝；
- 无表三态（t260914-05 反毒面）：decl_missing（未声明，path=""）/ file_missing
  （声明文件缺失）/ bad_content（内容坏，带字节指纹）三态互异、table 全 None、
  解析层单点 WARNING 点名 state+路径+指纹；**仓内 server/model-routes.yaml 即使
  在位也不被读**（现场 A/B「过期表被静默用错」的机械反证）；
- 声明解析放宽：`~/…` 展开与绝对路径合法、`..` 仍拒（fail-closed）、畸形值不静默猜；
- _pin_default_model：钉用户层、整段替换旧 agent-default-model（含段内注释），
  资源全在临时目录内、测毕清理（生命周期回收）。

历史沿革：快照断言 260910 移除；静默语义 260910-14 三态化重写（KI-030）；260914-05
删除「兜底=仓内表」两条子用例并给无表三态加指纹与反毒断言（KI-091 收口）。
cwd = 泳道根。须用带 PyYAML 的解释器（engine/.venv/bin/python）执行。
"""
import logging
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server" / "engine"))
import shared  # noqa: E402
try:
    import agent_activities  # noqa: E402,F401  （_pin_default_model 在此，依赖 temporalio）
    HAS_AA = True
except ImportError:  # 无 temporalio 的解释器：钉模型用例记 ENV_FAIL（缺 SDK=环境红），其余照跑
    HAS_AA = False

# 夹具自足表：default + 两角色（integration 无 tasks 段=分工键落 role 级的考察面）。
FIXTURE_TABLE = (
    "default:\n  provider: fx-dft\n  model: fx-m0\n"
    "roles:\n"
    "  integration:\n    provider: fx-int\n    model: fx-int-m\n"
    "  developer:\n    provider: fx-dev\n    model: fx-dev-m\n"
)

FAILS = []


def check(cond, msg):
    if cond:
        print("PASS %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL %s" % msg)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


@contextmanager
def _capture_route_warnings():
    """捕获 shared 模块 logger 的告警（解析层单点点名），退出还原。"""
    h = _Capture()
    logger = logging.getLogger(shared.__name__)
    old = logger.level
    logger.addHandler(h)
    logger.setLevel(logging.WARNING)
    try:
        yield h
    finally:
        logger.removeHandler(h)
        logger.setLevel(old)


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

    # ---- 1. 夹具自足：声明命中（ok 态）查表与真源一致（性质断言，不钉角色取值）
    tmp = Path(tempfile.mkdtemp(prefix="t260902-07-itest-main-"))
    try:
        table_path = tmp / "routes.yaml"
        table_path.write_text(FIXTURE_TABLE, "utf-8")
        reg = tmp / "reg"
        _mk_project(reg, "itest", "  model_routes: %s\n" % table_path)
        old = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(reg)
        try:
            resolved = shared.resolve_routes_table("itest")
        finally:
            if old is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old
        check(resolved["state"] == "ok" and Path(resolved["path"]) == table_path
              and resolved["fingerprint"].startswith("sha256:"),
              "声明命中 → ok 态、path=声明文件、指纹=字节摘要（实得 %r/%s）"
              % (resolved["state"], resolved["path"]))
        table = resolved["table"] or {}
        roles = table.get("roles") or {}
        check("integration" in roles, "表中含 integration 角色（不许整段删掉）")
        for role, declared in roles.items():
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 1b. 无表三态（t260914-05 反毒）：table 全 None + 单点点名 + 仓内表在场也不被读
    tmp = Path(tempfile.mkdtemp(prefix="t260902-07-itest-notable-"))
    try:
        bad = tmp / "bad.yaml"
        bad.write_text("roles: [unclosed\n  provider: :::\n", "utf-8")
        absent = tmp / "nope.yaml"

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

        repo_table = ROOT / "server" / "model-routes.yaml"
        if repo_table.is_file():
            check(True, "前提：仓内表在位（(b) 降级口径）——下三条反毒断言在它在场时成立")
        with _capture_route_warnings() as cap:
            rr_decl = resolve_with("")  # 未声明（paths 节无 model_routes 行）
            rr_file = resolve_with("  model_routes: %s\n" % absent)
            rr_bad = resolve_with("  model_routes: %s\n" % bad)
        check(rr_decl["state"] == "decl_missing" and rr_decl["path"] == ""
              and rr_decl["table"] is None and rr_decl["fingerprint"] == "",
              "未声明 → decl_missing：path=\"\" + 无表 + 无指纹（实得 %r/%r）"
              % (rr_decl["state"], rr_decl["path"]))
        check("未声明" in rr_decl["error"] and "docs/model-routes-sample.yaml" in rr_decl["error"],
              "decl_missing error 点名原因+建表指引（%s）" % rr_decl["error"][:60])
        check(rr_file["state"] == "file_missing" and rr_file["table"] is None
              and Path(rr_file["path"]) == absent and rr_file["fingerprint"] == "",
              "声明文件缺失 → file_missing 点名 + 无表（实得 %r，path=%s）"
              % (rr_file["state"], rr_file["path"]))
        check(rr_bad["state"] == "bad_content" and rr_bad["table"] is None
              and rr_bad["fingerprint"].startswith("sha256:"),
              "声明文件内容坏 → bad_content 点名 + 无表 + 带字节指纹（实得 %r/%s）"
              % (rr_bad["state"], rr_bad["fingerprint"]))
        check({rr_decl["state"], rr_file["state"], rr_bad["state"]}
              == {"decl_missing", "file_missing", "bad_content"},
              "无表三态互异（decl_missing/file_missing/bad_content 各自可辨）")
        check(all(rr["table"] is None for rr in (rr_decl, rr_file, rr_bad)),
              "三态一律无表（查表侧回落 profile 默认由消费方点名，禁静默用兜底表）")
        msgs = cap.msgs
        for st, rr in (("decl_missing", rr_decl), ("file_missing", rr_file), ("bad_content", rr_bad)):
            check(any("[model_route]" in m and "state=%s" % st in m and "指纹=" in m for m in msgs),
                  "解析层单点点名含 state=%s + 指纹（捕获 %d 条告警）" % (st, len(msgs)))
        check(not any("兜底" in m for m in msgs), "点名话术无「兜底」语义残留")

    # ---- 2. 解析放宽（~/ 展开、.. 拒、缺字段落 default）+ _pin_default_model
        good = tmp / "routes.yaml"
        good.write_text(FIXTURE_TABLE, "utf-8")
        home = tmp / "home"
        home.mkdir()
        tilde_target = home / "tilde-routes.yaml"
        shutil.copy(good, tilde_target)

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
        # 畸形 YAML 传入 model_route_for（直接路径形态）→ None（warning 留痕由共享 logger 承担）
        r = shared.model_route_for("integration", routes_file=bad)
        check(r is None, "畸形 YAML → model_route_for 返回 None（留痕 warning，不再静默）")
        # 条目缺字段 → 落 default
        partial = tmp / "partial.yaml"
        partial.write_text("default:\n  provider: fx-dft\n  model: fx-m0\n"
                           "roles:\n  integration:\n    provider: fx-int\n", "utf-8")
        r = shared.model_route_for("integration", routes_file=partial)
        check(r == {"provider": "fx-dft", "model": "fx-m0"},
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
