#!/usr/bin/env python3
"""sc_routes_fingerprint_diagnostics —— 告警里的「内容指纹」必须真能标识读到的字节（t260914-05 验收 1）。

用户场景：路由表在「声明缺失 / 文件缺失 / 内容坏」时引擎要点名告警，且告警必须带**表路径与
内容指纹**（票面验收 1「可机械断言」）。指纹的价值＝运维能回答「当时生效的是哪一版表」——
KI-091 的放大器正是「告警只说非 ok，人无法判断读到了哪份内容」。所以指纹若满足以下任一条，
验收 1 就形同虚设，本场景把它当产品红：

  · 常量/固定值（不随文件内容变）→ 两条不同表给出同一「指纹」＝撒谎；
  · 进程相关值（hash()/id()/时间戳）→ 同一文件两次解析、两个进程各说各话；
  · 日志与返回值不一致 → 告警里报的指纹对不上解析面拿到的，诊断被引向错误方向；
  · 坏表（字节可读、解析失败）不给指纹 → 恰恰是最需要指纹定位坏版本的现场；
  · 无字节可读（声明缺失/文件缺失）却给出「像模像样」的指纹 → 冒充存在。

断言全部走性质口径（内容敏感、稳定、跨进程一致、日志与返回值一致），**不锚摘要算法**——
sha256 前 12 位是实现选择，不是票面承诺；换算法不该打破本场景。

intent 去重：t260910-14-routes-truth-fallback / t260902-07 守卫（随本票改写）钉「三态可辨 +
告警含指纹」的**在场性**；本条钉指纹的**诊断效力**（内容敏感/跨进程稳定/日志一致/坏表可定位），
属既有场景不覆盖的新面。与 developer L1（pytest 的 fingerprint 形状断言）不同层：本条含跨进程
子进程命令与日志比对子用例。

夹具全 tmp（SANDBAR_PROJECTS_DIR 注入，退出还原）；只读仓库、零真环境写、零 3099/7233。
PyYAML 缺席=ENV_FAIL exit 2（点名），不写 SKIP。实现段落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t05_routes as lib  # noqa: E402

NAME = "sc_routes_fingerprint_diagnostics"


def _resolve_in_subprocess(project_key, reg_root):
    """跨进程子用例：子进程（引擎 venv python）解析同一夹具注册表，返回 dict。"""
    script = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "import shared;"
        "r=shared.resolve_routes_table(%r);"
        "print(json.dumps({'state': r.get('state'), 'fp': r.get('fingerprint'), 'path': str(r.get('path'))}))"
        % (str(lib.POC), project_key)
    )
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(reg_root)
    p = subprocess.run([lib.engine_python(), "-c", script], capture_output=True,
                       text=True, cwd=str(lib.REPO), env=env, timeout=120)
    if p.returncode != 0:
        return None, (p.stderr or "")[-200:]
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]), ""
    except Exception as e:  # noqa: BLE001
        return None, "子进程输出不可解析：%r（%s）" % (p.stdout[-120:], e)


def main():
    c = lib.Checks(NAME)
    try:
        shared = lib.import_shared()
    except ImportError as e:
        c.env_fail("引擎 shared 不可导入（venv/PyYAML 缺席）：%s" % e)
        return c.finish()

    try:
        with lib.Registry() as reg:
            # 好表 v1（哨兵 A）
            t = reg.root / "proj" / "model-routes.yaml"
            lib.write_table(t, "sentinel-prov", "sentinel-model", role="developer")
            reg.entry("proj", [str(reg.root / "proj")], paths_lines=[("model_routes", str(t))])

            c.section("F1/F2 指纹的内容敏感性与稳定性（同文件同值、换内容变值）")
            r1 = shared.resolve_routes_table("proj")
            r2 = shared.resolve_routes_table("proj")
            fp1, fp2 = r1.get("fingerprint"), r2.get("fingerprint")
            c.ok(isinstance(fp1, str) and len(fp1) > 0,
                 "F1a 可读文件给出非空指纹（实得 %r）" % (fp1,))
            c.ok(fp1 == fp2,
                 "F1b 同一未变更文件两次解析指纹稳定（%r vs %r）" % (fp1, fp2))
            lib.write_table(t, "sentinel-prov", "sentinel-model-v2", role="developer")
            r3 = shared.resolve_routes_table("proj")
            c.ok(r3.get("fingerprint") != fp1,
                 "F2 文件内容换一版 → 指纹必须变（%r vs %r）" % (r3.get("fingerprint"), fp1))

            c.section("F3 跨进程一致（挡进程相关指纹：hash()/id()/时间戳）")
            # 基准=父进程对「当前文件内容」的新解析（F2 刚改写过文件，不能用改写前的旧值）
            fp_cur = shared.resolve_routes_table("proj").get("fingerprint")
            sub, sub_err = _resolve_in_subprocess("proj", reg.root)
            if sub is None:
                c.ok(False, "F3 跨进程子用例自坏（脚本/环境问题，不冤产品）：%s" % sub_err)
            else:
                c.ok(sub.get("state") == "ok" and sub.get("fp") == fp_cur,
                     "F3 子进程与父进程解析同一份字节指纹一致（子=%r 父=%r）" % (sub.get("fp"), fp_cur))

            c.section("F4 坏表（字节可读、解析失败）：指纹必须仍给且能区分版本")
            bad = reg.root / "bad" / "model-routes.yaml"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("roles: [unclosed\n  provider: :::\n", encoding="utf-8")
            reg.entry("bad", [str(reg.root / "proj")], paths_lines=[("model_routes", str(bad))])
            r_bad = shared.resolve_routes_table("bad")
            fp_bad = r_bad.get("fingerprint")
            c.ok(r_bad.get("state") == "bad_content",
                 "F4a 内容坏 → state=bad_content（实得 %r）" % r_bad.get("state"))
            c.ok(isinstance(fp_bad, str) and len(fp_bad) > 0,
                 "F4b 坏表字节可读 → 指纹非空（能定位坏版本；实得 %r）" % (fp_bad,))
            c.ok(fp_bad != fp1,
                 "F4c 坏表指纹与好版本不同（%r vs %r）" % (fp_bad, fp1))

            c.section("F5 无字节两态：不许拿常量冒充指纹")
            reg.entry("undecl", [str(reg.root / "proj")])
            r_und = shared.resolve_routes_table("undecl")
            reg.entry("miss", [str(reg.root / "proj")], paths_lines=[("model_routes", str(reg.root / "nope.yaml"))])
            r_miss = shared.resolve_routes_table("miss")
            c.ok(r_und.get("state") == "decl_missing" and r_miss.get("state") == "file_missing",
                 "F5a 两无字节态可辨（%r / %r）" % (r_und.get("state"), r_miss.get("state")))
            on_disk_fps = {fp1, r3.get("fingerprint"), fp_bad}
            c.ok(r_und.get("fingerprint") not in on_disk_fps,
                 "F5b decl_missing 指纹不得与任何在场文件的指纹相同（实得 %r）" % (r_und.get("fingerprint"),))
            c.ok(r_miss.get("fingerprint") not in on_disk_fps,
                 "F5c file_missing 指纹不得与任何在场文件的指纹相同（实得 %r）" % (r_miss.get("fingerprint"),))

            c.section("F6 日志不撒谎：告警里的指纹＝返回值指纹；无字节态告警仍点名路径")
            (_r, txt_bad) = lib.capture(lambda: shared.resolve_routes_table("bad"))
            c.ok(str(fp_bad) in txt_bad,
                 "F6a bad_content 告警文本含返回值指纹（%r）" % fp_bad)
            (_r, txt_miss) = lib.capture(lambda: shared.resolve_routes_table("miss"))
            c.ok(str(reg.root / "nope.yaml") in txt_miss,
                 "F6b file_missing 告警点名声明路径")
            (_r, txt_und) = lib.capture(lambda: shared.resolve_routes_table("undecl"))
            c.ok(("undecl" in txt_und) or ("model-routes.yaml" in txt_und),
                 "F6c decl_missing 告警点名可定位（项目 key 或目标表路径）")
    except Exception as e:  # noqa: BLE001 — 夹具自坏必须响亮（环境/脚本问题不冤产品，但也不许绿）
        c.ok(False, "夹具自坏（不冤产品但不许绿）：%r" % e)

    return c.finish()


if __name__ == "__main__":
    sys.exit(main())
