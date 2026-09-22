#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t260922_02_engine_face_dualgen.py —— 0.1.5 会话类型面·engine 体检/统计面
（t260922-02 票面验收①②③④⑤的 engine 侧，灰盒 L3，池=ro）。

intent（用户可感知）：settle note / merge warns 里的 token 统计与会话体检是
「会话档是否被本版本理解」的唯一出口——0.1.5 会话（assistant/attempt、
system/message 等 11 个独有型）必须被认得出（known_types>0、S1 不假报），
usage 拿得到（双代聚合口径不变），词表外类型缺得不静默（未覆盖注记+旗标+
类型级封顶），双代健康会话注记恒空（零噪声守卫），且 0.1.1 现网会话行为
逐字不变（golden 锚：judge 计数/总额/note 全字面）。

与 t260917-05-session-face-loud intent 不同面：彼守「文件名/格式不认识」的
发现面与坏档隔离（S1/S3）；本条守「档能解析、但类型词表两代差异」的识别/
注记面（uncovered 族是本票新契约）。与 developer L1（判据纯函数 UT、内联
行数组夹具）不同层：本条走真 zstd 档 + 真实三层目录树 + _aggregate_lane_usage
聚合整行为（真档解压通路 L1 看不到）。

夹具：lib_t260922_02.build_workspaces 七树（v011=观测型全集/v015=11 独有型
全覆盖/abort=预派发中止形态（review CC1 推荐构成，无 session 头行）/
unknown=注入 v9/whatever/cap=25 个词表外类型/mixed=损坏档+unknown 共存/
both=双代共存）。形状锚=两代 known-event-types.js 底册 + .d.ts（方案 v2 §0.1）。

三态：zstd/temporalio 链缺席=ENV_FAIL exit 2；其余 FAIL exit 1。
直跑：python3 integration/t260922-02/sc_t260922_02_engine_face_dualgen.py
（cwd=仓库根；temporalio 缺席走回落链重执行）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_t260922_02 import (EXIT_ENV, Fail, build_workspaces,  # noqa: E402
                            ensure_engine_python, tmp_root, zstd_available)

ensure_engine_python()  # 需要引擎模块（temporalio 链）——回落链重执行

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server" / "engine"))
import agent_activities  # noqa: E402

TICKET = "t260922-02-itest"


def judge_archive(archive: Path):
    """解压→判据→S1（与聚合面同通路：zstd CLI）。"""
    import subprocess
    p = subprocess.run(["zstd", "-dc", str(archive)], capture_output=True, timeout=30)
    if p.returncode != 0:
        print("ENV_FAIL: zstd 解压夹具失败: %s" % p.stderr[:160])
        sys.exit(EXIT_ENV)
    j = agent_activities._judge_session_lines(p.stdout.decode("utf-8", "replace").split("\n"))
    return j, agent_activities._session_face_s1_text(archive.name, j)


def main() -> int:
    if not zstd_available():
        print("ENV_FAIL: zstd CLI 缺席（会话档解析通路依赖 zstd，环境缺供）")
        return EXIT_ENV
    f = Fail("t260922-02 场景 engine 类型面（双代识别/注记/回归）")
    root = tmp_root("sc-t260922-02-engine-")
    ws = build_workspaces(root)
    arc = {k: Path(v[0]) for k, v in ws.items() if k != "mixed" and k != "both"}

    # ---- 1. 认得出：0.1.5 独有型进词表，中止形态不假 S1 ----
    j15, s1_15 = judge_archive(arc["v015"])
    f.check(j15["parsed"] == 26 and j15["known_types"] == 12,
            "v015 认得出：parsed=26 known=12（6 原集+attempt/system+4 独有型；实得 %s/%s）"
            % (j15["parsed"], j15["known_types"]))
    f.check(j15["usage_records"] == 2 and j15["usage_without_known_keys"] == 0,
            "v015 usage 判据：2 条记录、无已知键全缺（实得 %s/%s）"
            % (j15["usage_records"], j15["usage_without_known_keys"]))
    f.check(s1_15 is None, "v015 不假报 S1「格式不认识」（实得 %r）" % (s1_15,))
    jab, s1_ab = judge_archive(arc["abort"])
    f.check(jab["known_types"] == 2 and s1_ab is None,
            "abort 预派发中止形态（无 session 头行）认得出且不假 S1：known=2（实得 %s/%r）"
            % (jab["known_types"], s1_ab))

    # ---- 2. 拿得到：双代 usage 聚合契约（黄金总额）----
    def agg(kind):
        # ws[kind][0] = <wt>/.dsh/sessions/<slug>/<sub>/<file> → wt 根 = parents[4]
        tokens, note = agent_activities._aggregate_lane_usage(
            Path(ws[kind][0]).parents[4], TICKET)
        return tokens, note

    t011, n011 = agg("v011")
    f.check(n011 == "", "v011 健康档 note 恒空（实得 %r）" % (n011,))
    f.check(t011["in"] == 10 and t011["out"] == 20 and t011["cacheRead"] == 5
            and t011["by_model"] == {"deepseek/m-gold-011": 30},
            "v011 usage 总额逐字（in10/out20/cache5/by_model；实得 %s)" % json.dumps(t011, sort_keys=True))
    tboth, nboth = agg("both")
    f.check(nboth == "" and tboth["in"] == 140 and tboth["out"] == 260
            and tboth["cacheRead"] == 55
            and set(tboth["by_model"]) == {"deepseek/m-gold-011", "deepseek/m-gold-015"},
            "both 双代共存：零注记且双模型总额合并（note=%r tokens=%s）"
            % (nboth, json.dumps(tboth, sort_keys=True)))

    # ---- 3. 缺得不静默：词表外类型 → 未覆盖注记 + 旗标 + 类型级封顶 ----
    ju, s1_u = judge_archive(arc["unknown"])
    f.check(ju.get("uncovered_types") == ["v9/whatever"],
            "unknown 注入词表外类型 → judge.uncovered_types 点名（实得 %r）"
            % (ju.get("uncovered_types"),))
    f.check(s1_u is None, "未覆盖 ≠ 格式不认识：S1 真值表不被触碰（实得 %r）" % (s1_u,))
    tu, nu = agg("unknown")
    f.check("未覆盖" in nu and "v9/whatever" in nu and "疑似更新代" in nu,
            "unknown 聚合 note 人话点名未覆盖类型（实得 %r）" % (nu,))
    f.check(tu.get("uncovered_types") is True, "unknown tokens 旗标 uncovered_types=True")
    f.check(tu["in"] == 130 and tu["out"] == 240 and tu["cacheRead"] == 50,
            "unknown usage 总额不受注记影响（实得 in=%s/out=%s/cache=%s）"
            % (tu["in"], tu["out"], tu["cacheRead"]))
    jc, s1_c = judge_archive(arc["cap"])
    f.check(isinstance(jc.get("uncovered_types"), list) and len(jc["uncovered_types"]) == 25,
            "cap：judge 判据面给全量 25 个词表外类型（实得 %s）"
            % (len(jc["uncovered_types"]) if isinstance(jc.get("uncovered_types"), list) else jc.get("uncovered_types"),))
    tc, nc = agg("cap")
    f.check("等共 25 个" in nc and "v9/t20" in nc and "v9/t21" not in nc,
            "cap：聚合 note 封顶 20 条 + 等共 25 个（不撑爆 settle note）")
    f.check(tc.get("uncovered_types") is True, "cap tokens 旗标 uncovered_types=True")
    tm, nm = agg("mixed")
    f.check("解压失败" in nm and "未覆盖" in nm and "v9/whatever" in nm,
            "mixed：损坏档点名与未覆盖注记共存一 note（多源聚合不互吞；实得 %r）" % (nm,))
    f.check(tm["in"] == 130 and tm["out"] == 240,
            "mixed：总额只来自健康档（实得 in=%s/out=%s）" % (tm["in"], tm["out"]))

    # ---- 4. 0.1.1 逐字回归 golden（改前钉死，任何词表/注记演进不得挪动）----
    j011, s1_011 = judge_archive(arc["v011"])
    golden = {"blank": False, "parsed": 12, "known_types": 6,
              "usage_records": 1, "usage_without_known_keys": 0}
    f.check(all(j011.get(k) == v for k, v in golden.items()) and s1_011 is None
            and j011.get("uncovered_types") == [],
            "0.1.1 golden：judge 全字面（%s；实得 %s）"
            % (json.dumps(golden), json.dumps({k: j011.get(k) for k in golden})))

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (f.passed, len(f.fails)))
    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())
