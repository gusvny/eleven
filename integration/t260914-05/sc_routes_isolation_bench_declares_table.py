#!/usr/bin/env python3
"""sc_routes_isolation_bench_declares_table —— 隔离测试台自声明路由表（t260914-05 验收 3 的根因回归网）。

用户场景（现场 B，260914 dengzhufpv 容器化首验）：隔离注册表没有 paths.model_routes 声明 →
兜底读仓内旧表 → 真 agent 段撞 429 → 容器化 A 子用例 A4–A7 全 N/A，**85 断言全绿也没拦住**——
因为旧链路把「静默用错」藏在 N/A 后面。本场景以零模型成本把现场 B 钉死：隔离台（e2e 夹具）
生成的项目条目必须**自己声明**路由表，且声明指向的表：

  · 存在、可解析、implement 段角色（developer）条目齐全（provider/model 非空）——
    「先做 4 再删表」顺序的机械判据：删表之后隔离环境必须仍有表可用，不许从「静默用错」
    变成「无表」；
  · 解析路径落在夹具根内——隔离台与生产同源口径（声明面取表），引擎仓不再是任何取表来源；
  · provider 在本机供应面上有名（settings.yaml 或出厂适配器）——防「表里写了个容器没配的
    provider」再撞 401/不存在（review R4 面）。

intent 去重：t260913-04 五条场景锁容器执行面（接线/镜像/生命周期/多仓/负锁），A 子用例判据钉在
该票设计段结果文件、由驱动脚本承担——**没有任何条目守夹具注册表的声明面**；本条补这个面。
与 t260910-14-routes-truth-fallback 不同面：彼锁引擎读面语义，本条锁测试台夹具的自声明契约。

实现：直调 integration/t260913-04/run_real_ticket_e2e.py 的 build_project（夹具构造唯一入口，
模块级无副作用，import 安全），在 tmp 生成真 git 仓+注册表后断言。git 缺席=夹具自坏子用例响亮。
夹具全 tmp，零真环境写、零 3099/7233、零 docker、零模型成本；不写 SKIP。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t05_routes as lib  # noqa: E402

NAME = "sc_routes_isolation_bench_declares_table"
E2E = lib.REPO / "integration" / "t260913-04" / "run_real_ticket_e2e.py"
BUILTIN_PROVIDERS = ("deepseek-official",)   # 出厂适配器：不进 settings.yaml 也算供应面在册


def load_harness():
    spec = importlib.util.spec_from_file_location("t26091304_e2e_harness", E2E)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    c = lib.Checks(NAME)
    try:
        import yaml  # noqa: F401
        shared = lib.import_shared()
        mod = load_harness()
    except ImportError as e:
        c.env_fail("依赖缺席（PyYAML / 引擎 shared / e2e 夹具模块）：%s" % e)
        return c.finish()

    tmp = Path(tempfile.mkdtemp(prefix="t26091405-e2e-"))
    try:
        proj, regroot = mod.build_project(tmp)
        entry_file = regroot / mod.PROJ / "project.yaml"
        c.section("G1 隔离台自声明（现场 B 的负锁）")
        doc = yaml.safe_load(entry_file.read_text(encoding="utf-8")) or {}
        paths = doc.get("paths") or {}
        declared = paths.get("model_routes")
        c.ok(isinstance(declared, str) and declared.strip() != "",
             "G1 隔离台条目自声明 paths.model_routes（现场 B 根因；实得 %r）" % (declared,))

        c.section("G2 声明表可用：存在、可解析、implement 角色条目齐全（先做 4 再删表的判据）")
        tpath = Path(os.path.expanduser(str(declared))) if declared else None
        c.ok(bool(tpath) and tpath.is_file(), "G2a 声明路径指向在场的表文件（%s）" % tpath)
        table = {}
        if bool(tpath) and tpath.is_file():
            table = yaml.safe_load(tpath.read_text(encoding="utf-8")) or {}
        dev = ((table.get("roles") or {}).get("developer") or {})
        c.ok(bool(dev.get("provider")) and bool(dev.get("model")),
             "G2b roles.developer 的 provider/model 非空（implement 段真 agent 依赖；实得 %r）" % (dev,))

        c.section("G3 与生产同源：解析走声明面，路径落夹具根内（引擎仓退场）")
        # 夹具注入：解析必须对着本夹具注册表（否则打到真注册表=夹具 bug，不是被测行为）
        old_reg = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(regroot)
        try:
            r = shared.resolve_routes_table(mod.PROJ)
        finally:
            if old_reg is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old_reg
        c.ok(r.get("state") == "ok", "G3a 隔离台解析 state=ok（实得 %r）" % r.get("state"))
        rpath = str(r.get("path") or "")
        c.ok(rpath == str(tpath), "G3b 解析路径=声明指向文件（实得 %r）" % rpath)
        c.ok(bool(rpath) and rpath.startswith(str(regroot)),
             "G3c 解析路径落在夹具根内（绝不落引擎仓；实得 %r）" % rpath)

        c.section("G4 供应面对齐：表里的 provider 本机配得上（R4 面）")
        if not dev.get("provider"):
            c.ok(False, "G4 跳过判定前置缺席（G2b 未过，不再叠加断言）")
        else:
            settings = Path.home() / ".dsh" / "settings.yaml"
            if not settings.is_file():
                c.env_fail("供应面缺席：%s 不存在——provider 对齐无从判定（点名补齐后重跑）" % settings)
            else:
                known = dev["provider"] in settings.read_text(encoding="utf-8") \
                    or dev["provider"] in BUILTIN_PROVIDERS
                c.ok(known,
                     "G4 provider=%s 在供应面（settings.yaml 或出厂适配器）有名" % dev["provider"])

        c.section("G5 隔离性：夹具根是 tmp，不指机器注册表/仓库")
        c.ok(str(regroot).startswith(str(tmp)) and not str(regroot).startswith(str(Path.home())),
             "G5a 注册表根在 tmp 内（不碰机器注册表；%s）" % regroot)
        c.ok(not str(regroot).startswith(str(lib.REPO)),
             "G5b 注册表根不在引擎仓内")
    except Exception as e:  # noqa: BLE001 — 夹具自坏必须响亮（环境/脚本问题不冤产品，但也不许绿）
        c.ok(False, "夹具自坏（git/路径/脚本问题，不冤产品但不许绿）：%r" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return c.finish()


if __name__ == "__main__":
    sys.exit(main())
