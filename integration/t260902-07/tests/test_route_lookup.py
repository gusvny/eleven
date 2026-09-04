#!/usr/bin/env python3
"""t260902-07 集成测试 ②：查表函数与钉模型机制的动态行为（需 PyYAML）。

校验对象：server/dsh/temporal-poc/shared.py
- model_route_for("integration") 返回 zai-coding-cn/glm-5.3-flash，其余角色无回归
- 畸形/缺失输入三态：表 YAML 非法 → 返回 None（不抛异常、不落 patch）；
  角色无条目 → 落 default；条目缺字段 → 落 default
- _pin_default_model：钉用户层、整段替换旧 agent-default-model（含段内注释），
  资源全在临时目录内、测毕清理（生命周期回收）
cwd = 泳道根。须用带 PyYAML 的解释器（temporal-poc/.venv/bin/python）执行。
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server" / "dsh" / "temporal-poc"))
import shared  # noqa: E402
try:
    import agent_activities  # noqa: E402,F401  （_pin_default_model 在此，依赖 temporalio）
    HAS_AA = True
except ImportError:  # 无 temporalio 的解释器：跳过钉模型用例，其余照跑（不冒充通过）
    HAS_AA = False

FAILS = []


def check(cond, msg):
    if cond:
        print("PASS %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL %s" % msg)


def main():
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("SKIP 需要 PyYAML：请用 server/dsh/temporal-poc/.venv/bin/python 执行")
        return 0

    # 1. 查表：新值 + 无回归
    r = shared.model_route_for("integration")
    check(r == {"provider": "zai-coding-cn", "model": "glm-5.3-flash"},
          "model_route_for(integration) = %r" % r)
    expect = {"default": ("zai", "glm-5.3-flash"), "developer": ("zai", "glm-5.3-flash"),
              "ops": ("kimi-coding", "k3"), "artist": ("kimi-coding", "k3"),
              "product-operation": ("zai", "glm-5.3-flash")}
    for role, (p, m) in expect.items():
        r = shared.model_route_for(role)
        check(r == {"provider": p, "model": m},
              "无回归 model_route_for(%s) = %s/%s（实得 %r）" % (role, p, m, r))

    # 2. 分工键不串：integration 无 tasks 段，proofread 分工仍落 role 级
    r = shared.model_route_for("integration", "proofread")
    check(r == {"provider": "zai-coding-cn", "model": "glm-5.3-flash"},
          "integration+proofread 分工落 role 级新值（实得 %r）" % r)

    # 3. 畸形输入：表 YAML 非法 → 优雅返回 None
    tmp = Path(tempfile.mkdtemp(prefix="t260902-07-itest-"))
    try:
        bad = tmp / "bad.yaml"
        bad.write_text("roles: [unclosed\n  provider: :::\n", "utf-8")
        orig = shared.MODEL_ROUTES_FILE
        try:
            shared.MODEL_ROUTES_FILE = bad
            r = shared.model_route_for("integration")
            check(r is None, "畸形 YAML → model_route_for 返回 None（实得 %r）" % r)
            # 缺失输入：文件不存在 → None
            shared.MODEL_ROUTES_FILE = tmp / "nope.yaml"
            r = shared.model_route_for("integration")
            check(r is None, "表文件缺失 → 返回 None（实得 %r）" % r)
            # 条目缺字段 → 落 default
            partial = tmp / "partial.yaml"
            partial.write_text("default:\n  provider: zai\n  model: glm-5.3-flash\n"
                               "roles:\n  integration:\n    provider: zai-coding-cn\n", "utf-8")
            shared.MODEL_ROUTES_FILE = partial
            r = shared.model_route_for("integration")
            check(r == {"provider": "zai", "model": "glm-5.3-flash"},
                  "条目缺 model → 落 default（实得 %r）" % r)
        finally:
            shared.MODEL_ROUTES_FILE = orig

        # 4. _pin_default_model：整段替换旧 agent-default-model（含注释），其余内容不动
        if not HAS_AA:
            print("SKIP _pin_default_model 用例：本解释器无 temporalio"
                  "（请用 server/dsh/temporal-poc/.venv/bin/python 复跑）")
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

    if FAILS:
        print("\n%d 项失败" % len(FAILS))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
