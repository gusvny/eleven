#!/usr/bin/env python3
"""t260910-11 场景①：声明 v2——实例改名去后缀 + face 字段退役（灰盒 L2，纯离线）。

依据三支：①工单验收「改名与新声明可解析且旧声明拒收点名」——用户可感知面=交付
inspection.yaml 的实例名变为 integration-tests/docs-sync（票号形如
inspection-integration-tests-<日期>）、声明回执不再含 face 键；含 face: 的旧形态
声明被解析面拒收且报错点名字段名（报错精确纪律：拒绝理由必须说「哪个字段不合法」，
不许笼统「声明不可用」）。②兼容红线（工单②）：workflow 输入结构
InspectionPeriodicInput 保留 face 默认值防历史重放解码报错——该面是数据类契约，
归 developer L1 重放锁单测（方案①已列），本场景不越层复写。③交付契约：解析器
合法字段表白名单语义（未知字段拒收）是既有 decl 门行为（t260905-03-decl-gate 守
「谁能跑/谁被拒」的门面），本条守「字段表翻转后新旧声明的命运」= schema 演进契约，
intent 不同面。

三态：全部腿纯标准库离线（decl 解析零网络零依赖），闸内即验，无 ENV 支路。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                + "/t260905-03")
import lib_inspection as lib  # noqa: E402

REPO = lib.REPO
# t260916-02 声明落位迁移A：交付声明从 server/engine/ 迁本仓根（口径④），
# 本场景守「交付面可解析」随之重指向新落位（断言不变）。
DELIVERED_YAML = os.path.join(REPO, "inspection.yaml")

# 旧形态声明样本：与新表唯一差异=实例带 face 行（1:1 复刻工单②点名的合法字段表七键原表）
OLD_FORM_DECL = """schema: v1
instances:
  - id: legacy-face
    face: test
    enabled: true
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

# 合并语义（t260910-11 × t260910-09）：本票改名的两个实例 + main 带入的两个占位实例
# （占位 id 保留 t260910-09 原名，面由 id 承载——声明 face 字段已除名）
# t260915-18 验收走查修正：腿A 原为 ids 与 NEW_IDS 的**集合相等**断言，把
# 「声明清单永不增长」冻进了改名契约——stage-capacity 占位实例（enabled=false）
# 一加入即红（260915 机械轮实爆，归属=本场景断言超出场景 intent）。改名契约的
# 本意是「新名在案、旧形态拒收」（见文件头 intent），故收紧为子集断言：四个
# 改名实例必须全部在案（改名复辟/实例被删仍红），新增实例不再误伤；旧形态
# 拒收仍由腿C 封口。依据=docs/testing-guide.md 测试数据纪律：新增一条真实
# 数据（声明一项实例）不应让任何测试变红。
NEW_IDS = {"integration-tests", "docs-sync", "mechanism-face", "simplify-face"}


def main() -> int:
    failures = []
    workdir = None

    # ── 腿A：交付 inspection.yaml 解析为 v2——实例名已去后缀、回执零 face 键 ──
    # t260916-02 迁移A：decl 聚合时代「交付声明解析」显式指交付文件（仓根），
    # 腿语义不变（守交付面内容形状，解析面另由 t260916-02-decl-gate-aggregate 守）。
    proc, parsed = lib.run_trigger(["decl", "--decl-path", DELIVERED_YAML])
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        failures.append("腿A 交付声明解析失败（新声明必须可解析）：%r | stderr=%s"
                        % ((parsed or (proc.stdout or "")[:160]), (proc.stderr or "")[:200]))
    else:
        result = parsed.get("result") or {}
        ids = {str(i.get("id") or "") for i in (result.get("instances") or [])}
        if not NEW_IDS.issubset(ids):
            failures.append("腿A 改名实例未在案（须全部含 %s）：%s"
                            % (sorted(NEW_IDS), sorted(ids)))
        if '"face"' in json.dumps(parsed, ensure_ascii=False):
            failures.append("腿A decl 回执仍含 face 键（字段未退役）：%r"
                            % json.dumps(parsed, ensure_ascii=False)[:300])

    # ── 腿B：交付 yaml 文本零 face: 行（工单②点名「inspection.yaml 删 face 行」）──
    try:
        with open(DELIVERED_YAML, "r", encoding="utf-8") as f:
            yaml_text = f.read()
    except OSError as e:
        failures.append("腿B 交付 inspection.yaml 不可读：%s" % e)
        yaml_text = ""
    for ln in yaml_text.splitlines():
        stripped = ln.strip()
        if stripped.startswith("face:") or stripped == "face:":
            failures.append("腿B 交付声明仍含 face 行：%r" % ln)
            break

    # ── 腿C：旧形态声明（含 face:）拒收且报错点名 face（旧声明拒收点名）──
    workdir = os.path.join(lib.TP_DIR, "out", "t260910-11-decl-fixture-%05d" % os.getpid())
    os.makedirs(workdir, exist_ok=True)
    old_yaml = os.path.join(workdir, "old_form.yaml")
    with open(old_yaml, "w", encoding="utf-8") as f:
        f.write(OLD_FORM_DECL)
    proc, parsed = lib.run_trigger(["decl", "--decl-path", old_yaml])
    if not isinstance(parsed, dict):
        failures.append("腿C 旧形态声明回执非单行 JSON：%r | stderr=%s"
                        % ((proc.stdout or "")[:160], (proc.stderr or "")[:160]))
    elif parsed.get("ok") is not False:
        failures.append("腿C 含 face: 的旧形态声明被放行（字段表未翻转）：%r" % parsed)
    else:
        err = str(parsed.get("error") or "")
        if "face" not in err:
            failures.append("腿C 拒绝理由未点名 face 字段（报错必须精确）：%r" % err[:240])

    if workdir:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 交付声明 v2（integration-tests/docs-sync、回执与 yaml 零 face）；"
          "旧形态声明拒收且点名 face 字段", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
