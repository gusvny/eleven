#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-20 集成场景（离线半）：巡检声明的项目身份门（fail-closed 契约面）。

intent（登记于 run_scenarios.py，名 t260915-20-decl-project-identity）：
  实例级 project_key 成为巡检声明的身份字段后，声明门（inspection_trigger.py decl
  子命令，纯 stdlib 解析面）的用户可感知契约：
  ① 启用实例缺 project_key → 拒收，且回执 error 点名实例 id 与「project_key／项目
    身份」事由（fail-closed：无项目身份的巡检=无主票，绝不静默回落引擎仓）；
  ② enabled=false 占位实例缺 project_key → 同样拒收（身份不是调度细节，占位豁免
    惯例——如 schedule.source/n 只在 enabled 必填——不适用于身份字段）；
  ③ project_key 形状畸形（大写/下划线，出实例 id 词法白名单）→ 拒收点名实例；
  ④ 正形声明（两启用实例各带身份）→ 过门，schedule_specs 面实例身份各归各位
    （instance_project_key 与 instance_id 一一同位）；
  ⑤ 实例级身份与 schedule 级计数源两键并存（race-first 计数实例）→ 过门，且
    specs 里 project_key==计数源值、instance_project_key==身份值——两字段作用域
    不同不串键（260915 review R2「身份/计数源串键」教训的离线见证）。

分工（防 intent 级重复）：
  · t260905-03-decl-gate 守声明门**通用**行为（畸形声明/未接线 kind/占位与未知实
    例拒绝/enabled 放行回执带票号）——其夹具不含 project_key 字段；本条只守**新
    身份字段**的门行为，与彼四类拒绝腿互不覆盖；
  · 真链路半张（t260915-20-project-identity-realchain，exclusive）守 SA 盖章／
    项目板行可见／扫对仓／调度 update 重铸——身份进起票面之后的行为；本条止于
    解析门；
  · developer L1（server/engine/tests decl 解析真值表）不同层。

三态：PASS exit 0 / FAIL exit 1（产品红，缺什么点名什么）/ ENV_FAIL exit 2。
纯 stdlib 离线（decl 子命令零网络零三方依赖），不存在环境红面——实现未落地=
产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  python3 integration/t260915-20/sc_inspection_decl_project_identity.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))   # integration/<票>/ → 仓根
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))

from lib_inspection import die_fail, last_json, run_trigger  # noqa: E402

# 身份事由锚（KI-051 教训：锚语义不锚字面——字段名或事由词二居其一即算点名）。
IDENTITY_TOKENS = ("project_key", "项目身份")

STATS = {"pass": 0, "fail": 0}
FAILS = []


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


def decl_text(instances_yaml: str) -> str:
    return "schema: v1\ninstances:\n%s" % instances_yaml


def run_decl(path):
    """decl 子命令（离线校验面）→ (proc, parsed)。"""
    return run_trigger(["decl", "--decl-path", path])


def err_text(parsed, raw):
    p = parsed if isinstance(parsed, dict) else {}
    return str(p.get("error") or "") or (raw or "")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sandbar-t26091520-decl-")

    # ---- 腿①：启用实例缺 project_key → 拒收点名实例与身份事由 ----
    d1 = os.path.join(tmp, "d1.yaml")
    with open(d1, "w", encoding="utf-8") as f:
        f.write(decl_text(
            "  - id: nopk-inst\n"
            "    enabled: true\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 7 * * *\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n"))
    proc, parsed = run_decl(d1)
    err = err_text(parsed, proc.stdout)
    check("D1 启用实例缺身份拒收",
          parsed is not None and parsed.get("ok") is not True
          and "nopk-inst" in err and any(t in err for t in IDENTITY_TOKENS),
          "ok=%r error=%r" % ((parsed or {}).get("ok"), err[:200]))

    # ---- 腿②：enabled=false 占位实例缺 project_key → 同样拒收（身份不豁免） ----
    d2 = os.path.join(tmp, "d2.yaml")
    with open(d2, "w", encoding="utf-8") as f:
        f.write(decl_text(
            "  - id: nopk-placeholder\n"
            "    enabled: false\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 7 * * 1\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n"))
    proc, parsed = run_decl(d2)
    err = err_text(parsed, proc.stdout)
    check("D2 占位实例缺身份同样拒收",
          parsed is not None and parsed.get("ok") is not True
          and "nopk-placeholder" in err and any(t in err for t in IDENTITY_TOKENS),
          "ok=%r error=%r" % ((parsed or {}).get("ok"), err[:200]))

    # ---- 腿③：project_key 形状畸形 → 拒收点名实例 ----
    d3 = os.path.join(tmp, "d3.yaml")
    with open(d3, "w", encoding="utf-8") as f:
        f.write(decl_text(
            "  - id: badshape-inst\n"
            "    enabled: true\n"
            "    project_key: Bad_Key\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 7 * * *\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n"))
    proc, parsed = run_decl(d3)
    err = err_text(parsed, proc.stdout)
    check("D3 身份形状畸形拒收点名",
          parsed is not None and parsed.get("ok") is not True
          and "badshape-inst" in err and any(t in err for t in IDENTITY_TOKENS),
          "ok=%r error=%r" % ((parsed or {}).get("ok"), err[:200]))

    # ---- 腿④：正形双实例 → 过门，specs 面身份各归各位 ----
    key_a, key_b = "declkey-a", "declkey-b"
    d4 = os.path.join(tmp, "d4.yaml")
    with open(d4, "w", encoding="utf-8") as f:
        f.write(decl_text(
            "  - id: ok-inst-a\n"
            "    enabled: true\n"
            "    project_key: %s\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 7 * * *\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n"
            "  - id: ok-inst-b\n"
            "    enabled: true\n"
            "    project_key: %s\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 8 * * 1\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n" % (key_a, key_b)))
    proc, parsed = run_decl(d4)
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    specs = (res or {}).get("schedule_specs") if isinstance(res, dict) else None
    spec_by_id = {str(s.get("instance_id")): s for s in specs} if isinstance(specs, list) else {}
    sa = spec_by_id.get("ok-inst-a") or {}
    sb = spec_by_id.get("ok-inst-b") or {}
    check("D4a 正形声明过门",
          parsed is not None and parsed.get("ok") is True,
          "ok=%r error=%r" % ((parsed or {}).get("ok"), err_text(parsed, proc.stdout)[:200]))
    check("D4b specs 面身份各归各位",
          str(sa.get("instance_project_key") or "") == key_a
          and str(sb.get("instance_project_key") or "") == key_b,
          "a=%r b=%r" % (sa.get("instance_project_key"), sb.get("instance_project_key")))

    # ---- 腿⑤：实例身份 × 计数源两键并存（race-first）→ 不串键 ----
    count_src = "countsrc-a"
    d5 = os.path.join(tmp, "d5.yaml")
    with open(d5, "w", encoding="utf-8") as f:
        f.write(decl_text(
            "  - id: race-inst\n"
            "    enabled: true\n"
            "    project_key: %s\n"
            "    schedule:\n"
            "      kind: race-first\n"
            "      cron: 0 9 * * 1\n"
            "      n: 20\n"
            "      source: archive-dir\n"
            "      project_key: %s\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n" % (key_a, count_src)))
    proc, parsed = run_decl(d5)
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    specs = (res or {}).get("schedule_specs") if isinstance(res, dict) else None
    s5 = next((s for s in specs if str(s.get("instance_id")) == "race-inst"), {}) \
        if isinstance(specs, list) else {}
    check("D5 两键并存不串键（身份=身份、计数源=计数源）",
          parsed is not None and parsed.get("ok") is True
          and str(s5.get("instance_project_key") or "") == key_a
          and str(s5.get("project_key") or "") == count_src,
          "ok=%r instance_project_key=%r project_key=%r"
          % ((parsed or {}).get("ok"), s5.get("instance_project_key"),
             s5.get("project_key")))

    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (STATS["pass"], STATS["fail"], 0, 0), flush=True)
    if FAILS:
        print("FAIL_REASON: %s" % "；".join(FAILS), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001——意外异常=产品红点名，不静默不假绿
        die_fail("场景异常退出：%s: %s" % (type(e).__name__, e))
