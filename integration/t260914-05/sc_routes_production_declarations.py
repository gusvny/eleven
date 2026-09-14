#!/usr/bin/env python3
"""sc_routes_production_declarations —— 生产两项目声明面照旧生效，引擎仓退出取表来源（t260914-05 验收 5）。

用户场景：本票是「收口清理票」，最容易出的回归是**顺手伤到生产**——机器级真源表
（~/.sandbar/projects/*/model-routes.yaml，红线禁改）或两项目的 paths 声明被误动。
本场景以只读探针钉住生产口径：

  · sandbar / dengzhufpv 两项目的注册条目仍声明 paths.model_routes，且解析 state=ok、
    roles.developer 的 provider/model 非空（验收 5 的机械口径；**只断性质不断具体值**——
    模型是运行时可调项，260910 宿主裁决心智：表值不快照）；
  · 解析路径落在引擎仓之外——「真源在机器级/声明面」的收口不变式；
  · 未登记 key → 三态口径照常（decl_missing、拿不到表、路径不落引擎仓）——引擎仓对
    任何人都不再是取表来源（验收 2 的生产面投影）；
  · 只读承诺：探针前后机器表字节摘要一致（本场景零写）。

intent 去重：t260902-07 表守卫（随本票改写）钉「声明指向的表」的静态性质（L2，单项目、
可换 key）；本条钉**生产注册面的端到端解析拼装**（两项目 + 未登记 key + 只读 pledge），
属验收 5 的系统层证据。环境缺机器注册表/项目条目=ENV_FAIL exit 2（点名），不写 SKIP；
条目在场但声明缺失=产品红（那是契约被破坏，不是环境缺）。

夹具零写；不碰 3099/7233、不删不改机器表；只读仓库。实现段落地前后都应绿
（生产面本票不得变坏）——这条是随票的「不许伤生产」哨兵。
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t05_routes as lib  # noqa: E402

NAME = "sc_routes_production_declarations"
PROD_KEYS = ("sandbar", "dengzhufpv")
LEGACY_REPO_TABLE = lib.REPO / "server" / "model-routes.yaml"


def digest(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def main():
    c = lib.Checks(NAME)
    try:
        shared = lib.import_shared()
    except ImportError as e:
        c.env_fail("引擎 shared 不可导入（venv/PyYAML 缺席）：%s" % e)
        return c.finish()

    import yaml
    from pathlib import Path as _P
    root = _P.home() / ".sandbar" / "projects"
    if not root.is_dir():
        c.env_fail("机器注册表缺席：%s（生产面无从核对；在装有 sandbar 项目注册的机器上跑）" % root)
        return c.finish()

    before = {k: digest(root / k / "model-routes.yaml") for k in PROD_KEYS}
    try:
        for key in PROD_KEYS:
            entry = root / key / "project.yaml"
            if not entry.is_file():
                c.env_fail("项目条目缺席：%s（环境面；本场景只核已在册生产项目）" % entry)
                continue
            c.section("P %s：声明面 → 解析 → developer 角色" % key)
            doc = yaml.safe_load(entry.read_text(encoding="utf-8")) or {}
            declared = (doc.get("paths") or {}).get("model_routes")
            c.ok(isinstance(declared, str) and declared.strip() != "",
                 "P1/%s 注册条目声明 paths.model_routes（实得 %r）" % (key, declared))
            r = shared.resolve_routes_table(key)
            c.ok(r.get("state") == "ok",
                 "P2/%s 解析 state=ok（实得 %r）" % (key, r.get("state")))
            dev = ((r.get("table") or {}).get("roles") or {}).get("developer") or {}
            c.ok(bool(dev.get("provider")) and bool(dev.get("model")),
                 "P3/%s roles.developer 的 provider/model 非空（性质断言不钉值；实得 %r）" % (key, dev))
            rpath = str(r.get("path") or "")
            c.ok(bool(rpath) and not rpath.startswith(str(lib.REPO)),
                 "P4/%s 真源在机器级（解析路径在引擎仓之外；实得 %r）" % (key, rpath))
            c.ok(rpath != str(LEGACY_REPO_TABLE),
                 "P5/%s 取表路径不是仓内旧表（实得 %r）" % (key, rpath))

        c.section("Q 未登记 key 与只读 pledge")
        r_u = shared.resolve_routes_table("t26091405-no-such-project")
        c.ok(r_u.get("state") == "decl_missing",
             "Q1 未登记 key → state=decl_missing 可辨（实得 %r）" % r_u.get("state"))
        c.ok(r_u.get("table") is None,
             "Q2 未登记 key → 拿不到任何表（table=None）")
        c.ok(not str(r_u.get("path") or "").startswith(str(lib.REPO)),
             "Q3 引擎仓不是任何取表来源（未登记 key 的路径不落仓内；实得 %r）"
             % str(r_u.get("path") or ""))
        after = {k: digest(root / k / "model-routes.yaml") for k in PROD_KEYS}
        c.ok(before == after and all(v for v in after.values()),
             "Q4 只读 pledge：机器表字节摘要探针前后一致（零写承诺）")
    except Exception as e:  # noqa: BLE001 — 探针自坏必须响亮，不许绿
        c.ok(False, "探针自坏（不冤产品但不许绿）：%r" % e)

    return c.finish()


if __name__ == "__main__":
    sys.exit(main())
