#!/usr/bin/env python3
"""全量不变式注入面（t260925-04，registry: t260925-04-full-run-invariants）。

意图（灰盒 L3，ro 池，畸形/边界输入注入，秒级零 docker，developer 对抗面）：
本票把定点复跑口径换成「实际改动文件」后，**放行与覆盖的既有承诺不许被稀释**。
本场景对决策契约（shared.targeted_rerun_plan 新签名）注入畸形/边界外部输入，
钉死四条不变式（fail-closed 与首轮/覆盖语义锚定行为承诺，不锚实现）：

- A 畸形清单恒全量：changed_files 传 None / 非序列（int/str/dict）/ 含非字符串
  元素 / 含空白元素 → 全量（空定点面），绝不因解析崩溃走窄判或抛异常逃逸
  （**注意：畸形元素两子用例按方案口径应为 fail-closed 恒全量，现实现「跳过畸形元素
  照旧 localized」与票面规格漂移——本场景故意保持红作为对抗信号，归因见结果
  文件，不随实现放宽断言**）；
- B error 非空恒全量：错误优先级契约在 changed_files_blast_radius 的
  diff_error 形参上（决策点入口由 dev_lane 以「error 非空→传空清单」承接）——
  diff_error 任一非空串 → shared；空清单（=不可得形态）→ 全量，绝不因
  「看起来没改」收窄；
- C 首轮恒全量：清单全非共享 + first_run=True → 仍全量（首轮全跑承诺不因新
  口径松动）；
- D 覆盖不减：定点面输出恒为上轮红名名单的**去重保序子集**，绝不发明注册表
  外名字、绝不因新口径扩面/缩面；红名名单畸形（非序列/含 None/合成条目 __）
  时清洗语义与旧签名逐字一致。

intent 分工：sc_t260925_04_file_blast_radius 守真仓上的 happy-path 组件链
（localized/shared/fail-closed 三态），本条只守**不变式注入面**——同一决策点的
对抗输入形态，developer L1 真值矩阵之外的用户级对抗复核（互为冗余防御，
intent 同源但注入维度不同：真 git 子进程形态 vs 纯边界值形态）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。无 ENV 子用例。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

ENGINE_WRITE_SET = ["server/engine/", "integration/", "verify.yaml"]
LOCAL_FILES = ["app/feature.py", "tickets/t260925-04/note.md"]
REDS = ["sc_red_a", "sc_red_b", "sc_red_c"]


def main():
    import shared  # noqa: E402

    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：%s" % detail) if detail else ""))

    _UNSET = object()

    def plan(changed=_UNSET, first_run=False, reds=REDS,
             write_set=ENGINE_WRITE_SET):
        kwargs = {"first_run": first_run}
        if changed is not _UNSET:
            kwargs["changed_files"] = changed
        try:
            return shared.targeted_rerun_plan(write_set, reds, **kwargs)
        except Exception as e:  # 契约：畸形输入不抛，fail-closed 返回空
            return ("RAISED", "%s: %s" % (type(e).__name__, e))

    # ---- A 畸形清单恒全量 ----
    for label, bad in [
        ("None", None),
        ("int", 7),
        ("裸字符串", "app/feature.py"),
        ("dict", {"app/feature.py": 1}),
        ("含非字符串元素", ["app/feature.py", 3, None]),
        ("含空白元素", ["app/feature.py", "   "]),
        ("空清单", []),
    ]:
        got = plan(changed=bad)
        check("A 畸形清单（%s）→ 恒全量且不抛" % label,
              got == [], "got=%r" % (got,))

    # ---- B error 非空恒全量（错误优先级契约=changed_files_blast_radius.diff_error；
    # 决策点以空清单承接不可得形态）----
    for label, err in [("非空串", "git diff 失败 rc=128"),
                       ("空白串", "   ")]:
        radius = shared.changed_files_blast_radius(LOCAL_FILES, diff_error=err)
        check("B diff_error %s → shared（计算面报错绝不放窄）" % label,
              radius == "shared", "radius=%r" % (radius,))
    got = plan(changed=[])
    check("B2 空清单（=清单不可得的决策点承接形态）→ 恒全量",
          got == [], "got=%r" % (got,))

    # ---- C 首轮恒全量 ----
    got = plan(changed=LOCAL_FILES, first_run=True)
    check("C 清单全非共享 + first_run → 仍全量", got == [], "got=%r" % (got,))

    # ---- D 覆盖不减：定点面=红名去重保序子集 ----
    got = plan(changed=LOCAL_FILES, reds=["sc_b", "sc_a", "sc_b", "__syn", "", None])
    check("D1 定点面=红名清洗去重保序子集（__合成/空/非串剔除）",
          got == ["sc_b", "sc_a"], "got=%r" % (got,))
    got = plan(changed=LOCAL_FILES, reds=None)
    check("D2 红名名单畸形（None）→ 全量不抛", got == [], "got=%r" % (got,))
    got = plan(changed=LOCAL_FILES, reds=42)
    check("D3 红名名单畸形（int）→ 全量不抛", got == [], "got=%r" % (got,))
    check("D4 合法清单+合法红名 → 定点面非空（新口径真解禁，不是恒全量换皮）",
          plan(changed=LOCAL_FILES) == REDS)

    n_fail = legs.count(False)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (len(legs) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
