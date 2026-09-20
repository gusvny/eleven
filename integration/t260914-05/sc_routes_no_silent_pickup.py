#!/usr/bin/env python3
"""sc_routes_no_silent_pickup —— 兜底表退役后的取表来源封闭性与消费方可见性（t260914-05 验收 1/2）。

用户场景（260914 两个现场 A/B 的回归网）：工单 agent 用哪个模型，只能来自「项目声明
paths.model_routes 指向的表」。判据一句话：**表存在但内容过期，比表缺失更毒**——缺失会点名，
过期会被静默捡起用错（现场 A：声明读不到 → 静默兜底读仓内旧表 developer=zai → 429，
报错文案把人引向「额度用尽」；现场 B：隔离注册表无声明 → 同一条兜底分支 → 真 agent 段全 N/A）。

本场景以用户视角（「我的 agent 会被钉到哪个模型」）钉三件事：

  A. 声明面好时照旧——声明指向的表内容原样生效。**不许为「防过期」引入任何内容新鲜度判定**
     （查表语义零改动＝本票红线；这条同时是夹具自证：证明断言真在观测 spawn 行为）。
  B. 未声明 / 声明面坏的项目，agent 绝不被钉到任何「没人声明的表」：①引擎仓内那份旧表、
     ②项目主目录里恰好同名的旧表；且「本轮模型来自 profile 默认」必须点名可见（禁静默回落）。
  C. 项目间不串——一个项目的表不得影响另一个项目的 spawn。

intent 去重（与既有场景不同面）：t260910-14-routes-truth-fallback 锁「真源随声明走 + 分层兜底
留痕」的拼装行为（随本票改口径）；t260903-03-paths-failclosed-red 锁路径锚点红传导与 roles 面；
本条锁**兜底退役后的取表来源封闭性 + 消费方点名可见性**，对抗面是「项目本地同名旧表诱饵」与
「跨项目串扰」两个既有场景不碰的面。与 developer L1（server/engine/tests 的 pytest，夹具级
形状与告警捕获）不同层：本条走真 spawn 缝隙、真注册表注入、真消费方日志。

夹具全 tmp（SANDBAR_PROJECTS_DIR 注入，退出还原）；只读仓库、零真环境写、零 3099/7233。
temporalio/PyYAML 缺席=ENV_FAIL exit 2（点名），不写 SKIP。实现段落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t05_routes as lib  # noqa: E402

NAME = "sc_routes_no_silent_pickup"
# 「表无命中」现场的点名容差词表（措辞自由，只要人能看出「本轮用了默认模型/没命中」）。
NOHIT_TOKENS = ("无命中", "未命中", "没有命中", "找不到", "profile", "默认模型", "继承默认")


def main():
    c = lib.Checks(NAME)
    try:
        shared = lib.import_shared()
    except ImportError as e:
        c.env_fail("引擎 shared 不可导入（venv/PyYAML 缺席）：%s" % e)
        return c.finish()
    try:
        lib.import_engine()
    except ImportError as e:
        c.env_fail("agent_activities 不可导入（temporalio 缺席，无法观测 spawn 缝隙）：%s" % e)
        return c.finish()

    ws_good = lib.mk_ws()
    ws_poison = lib.mk_ws()
    try:
        with lib.Registry() as reg:
            # ---------------- A. 绿锚：声明面好 → 表内容原样生效（红线：不许加新鲜度判定）----------------
            c.section("A 声明面好：哨兵表原样生效（夹具自证 + 查表语义零改动锚）")
            good_table = reg.root / "good" / "model-routes.yaml"
            lib.write_table(good_table, "sentinel-prov", "sentinel-model", role="developer")
            reg.entry("good", [str(ws_good)], paths_lines=[("model_routes", str(good_table))])
            r_good = shared.resolve_routes_table("good")
            c.ok(r_good.get("state") == "ok",
                 "A1 声明指向存在表 → state=ok（实得 %r）" % r_good.get("state"))
            c.ok(str(r_good.get("path")) == str(good_table),
                 "A2 path=声明指向文件（实得 %r）" % r_good.get("path"))
            role_dev = ((r_good.get("table") or {}).get("roles") or {}).get("developer") or {}
            c.ok(role_dev.get("provider") == "sentinel-prov" and role_dev.get("model") == "sentinel-model",
                 "A3 声明表内容原样生效（不看内容新旧、不做新鲜度判定＝查表语义零改动）")
            cmd_g, _env_g, art_g = lib.spawn(ws_good, project="good", role="developer", tag="good")
            txt_g = lib.model_patch_text(art_g)
            c.ok("sentinel-prov" in txt_g and "sentinel-model" in txt_g,
                 "A4 spawn 真被钉到声明表哨兵值（夹具自证：断言确实在观测 spawn 缝隙）")

            # ---------------- B. 未声明 + 主目录同名旧表诱饵：不得被捡 ----------------
            c.section("B 未声明项目（主目录里放着同名过期表）：不得静默捡起")
            decoy = ws_poison / "server" / "model-routes.yaml"
            lib.write_table(decoy, "decoy-prov", "decoy-model", role="developer")
            reg.entry("poison", [str(ws_poison)])
            r_p = shared.resolve_routes_table("poison")
            c.ok(r_p.get("state") == "decl_missing",
                 "B1 未声明 → state=decl_missing 可辨（实得 %r）" % r_p.get("state"))
            c.ok(r_p.get("table") is None,
                 "B2 未声明 → 拿不到任何表（table=None；退役前会静默拿到仓内旧表）")
            p_path = str(r_p.get("path") or "")
            c.ok(not p_path.startswith(str(lib.REPO)),
                 "B3 解析路径不得落在引擎仓内（实得 %r）" % p_path)
            c.ok(p_path != str(decoy),
                 "B4 也不得捡项目主目录里的同名旧表（实得 %r）" % p_path)
            (cmd_p, _e_p, art_p), txt_p = lib.capture(
                lambda: lib.spawn(ws_poison, project="poison", role="developer", tag="poison"))
            c.ok(not lib.model_patch_files(art_p),
                 "B5 未声明 → spawn 不产出模型 patch（没人声明的表不许替 agent 挑模型）")
            joined = " ".join(lib.patch_paths(cmd_p))
            c.ok(("decoy-prov" not in joined) and ("sentinel-prov" not in joined),
                 "B6 cmd 里不出现任何未声明表的模型值（诱饵与他项目哨兵都不许）")
            c.ok("decl_missing" in txt_p,
                 "B7 该现场日志点名 state（禁静默；尾 160：%r）" % txt_p.strip()[-160:])
            c.ok(("poison" in txt_p) or ("model-routes.yaml" in txt_p),
                 "B8 点名可定位（含项目 key 或目标表路径）")

            # ---------------- C. 声明面坏两态：不得回落引擎仓旧表 ----------------
            c.section("C 声明面坏（文件缺失 / 内容坏）：不得回落引擎仓旧表")
            missing = reg.root / "nope-routes.yaml"
            # 夹具 key 必须过 PROJECT_KEY_RE 白名单（^[a-z0-9][a-z0-9-]{0,40}$，下划线非法），
            # 否则 project_paths 按未注册处理——那是夹具 bug，不是被测行为。
            reg.entry("decl-missing", [str(ws_good)], paths_lines=[("model_routes", str(missing))])
            r_m = shared.resolve_routes_table("decl-missing")
            c.ok(r_m.get("state") == "file_missing",
                 "C1 声明文件缺失 → state=file_missing 可辨（实得 %r）" % r_m.get("state"))
            c.ok(r_m.get("table") is None,
                 "C2 声明文件缺失 → 不得回落引擎仓旧表（table=None）")
            bad = reg.root / "bad" / "model-routes.yaml"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("roles: [unclosed\n  provider: :::\n", encoding="utf-8")
            reg.entry("bad-content", [str(ws_good)], paths_lines=[("model_routes", str(bad))])
            r_b = shared.resolve_routes_table("bad-content")
            c.ok(r_b.get("state") == "bad_content",
                 "C3 内容坏 → state=bad_content 可辨（实得 %r）" % r_b.get("state"))
            c.ok(r_b.get("table") is None,
                 "C4 内容坏 → 不得回落引擎仓旧表（table=None）")
            for key, tag in (("decl-missing", "bm"), ("bad-content", "bc")):
                (_cmd, _env, art_x), txt_x = lib.capture(
                    lambda k=key, t=tag: lib.spawn(ws_good, project=k, role="developer", tag=t))
                declared = str(missing) if key == "decl-missing" else str(bad)
                c.ok(not lib.model_patch_files(art_x),
                     "C5/%s 坏声明面 → 不产出模型 patch" % tag)
                c.ok(declared in txt_x,
                     "C6/%s 告警点名声明路径（%s）" % (tag, declared))

            # ---------------- D. 表在场但角色无命中：同样点名可见、与无表可辨 ----------------
            c.section("D 表在场但该角色无条目：回落 profile 默认必须同样可见")
            nohit_table = reg.root / "nohit" / "model-routes.yaml"
            lib.write_table(nohit_table, "other-prov", "other-model", role="other-role", default=False)
            reg.entry("nohit", [str(ws_good)], paths_lines=[("model_routes", str(nohit_table))])
            r_n = shared.resolve_routes_table("nohit")
            c.ok(r_n.get("state") == "ok", "D1 表在场且可解析 → state=ok（实得 %r）" % r_n.get("state"))
            role = "role-without-entry"
            (_cmd_n, _env_n, art_n), txt_n = lib.capture(
                lambda: lib.spawn(ws_good, project="nohit", role=role, tag="nohit"))
            c.ok(not lib.model_patch_files(art_n),
                 "D2 表无该角色条目（且无 default）→ 不产出模型 patch（继承 profile 默认）")
            c.ok((role in txt_n) or any(t in txt_n for t in NOHIT_TOKENS),
                 "D3 该现场也点名可见（禁静默回落 profile 默认；尾 160：%r）" % txt_n.strip()[-160:])
            c.ok(txt_n != txt_p,
                 "D4 两因（无表 / 表在场无命中）在日志里可辨（文本必须不同）")
    finally:
        import shutil
        shutil.rmtree(ws_good, ignore_errors=True)
        shutil.rmtree(ws_poison, ignore_errors=True)

    return c.finish()


if __name__ == "__main__":
    sys.exit(main())
