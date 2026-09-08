#!/usr/bin/env python3
"""sc_merge_checks_pairs.py — merge-checks.yaml 护栏配置与仓实况对齐（t260903-12）。

intent（守护的用户可感知契约）：本仓 bundle 构建链（workbench src/client/ → lib/）
必须真实处于 merge_check 3.5 节 bundle 新鲜度护栏覆盖之下。故障面：配置文件缺失、
形状写坏（护栏启动即抛错）、或 src/out 前缀与仓内真实路径不齐——前两者引擎侧
fail-closed 可见，第三种是静默失效（3.5 节判定「src 前缀无改动 → continue 降噪」，
路径写错 = 前缀永不命中 = 护栏形同虚设，恰是 t260827-02「假上线」教训的死灰复燃形态）。
本场景独立守护该对齐，与引擎解析/判定逻辑互不替代。

步骤：
  1. server/merge-checks.yaml 在场（缺失=红：护栏未启用）；
  2. 解析出至少一对 bundle_pairs，形状=引擎 3.5 节契约（顶格 bundle_pairs: +
     缩进「- src: X」/「out: Y」成对、值裸 token、其余缩进行=坏行）；坏行=红；
  3. 恰含本票声明对 (server/plugins/workbench/src/client/, server/plugins/workbench/lib/)；
  4. 每对 src/out 前缀均为仓内真实目录（isdir）——防路径写错的静默失效。

Hermetic：纯文件读，零端口零网络，不碰 3099。cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0。
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join("server", "merge-checks.yaml")
DECLARED_PAIR = ("server/plugins/workbench/src/client/", "server/plugins/workbench/lib/")

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)
    return cond


def parse_bundle_pairs(text):
    """最小解析，行为契约=agent_activities._parse_bundle_pairs（3.5 节文档化形状）：
    只认顶格 bundle_pairs: 下缩进的「- src: X」+「out: Y」成对条目，值裸 token；
    其余缩进行=坏行（引擎侧 raise，这里返回 (None, 坏行) 由断言红）。"""
    pairs, cur, in_section, bad = [], None, False, None
    for raw in text.splitlines():
        ln = raw.replace("\t", "  ").rstrip()
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if not ln.startswith(" "):
            in_section = (s == "bundle_pairs:")
            cur = None
            continue
        if not in_section:
            continue
        if s.startswith("- src:"):
            cur = {"src": s[len("- src:"):].strip(), "out": ""}
            pairs.append(cur)
        elif s.startswith("out:") and cur is not None:
            cur["out"] = s[len("out:"):].strip()
        else:
            bad = s
    complete = [(p["src"], p["out"]) for p in pairs if p["src"] and p["out"]]
    return complete, bad


def main():
    print("== 1. 配置在场（护栏启用前提）")
    path = os.path.join(REPO, CFG)
    if not check(os.path.isfile(path), "%s 存在（缺失=bundle 新鲜度护栏未启用）" % CFG):
        return finish()
    with open(path, encoding="utf-8") as f:
        text = f.read()

    print("== 2. 形状可解析（引擎遇坏行 fail-closed，护栏死）")
    pairs, bad = parse_bundle_pairs(text)
    check(bad is None, "无坏缩进行（契约：只认 - src:/out: 成对，实得坏行=%r）" % bad)
    check(len(pairs) > 0, "解析出至少一对 bundle_pairs（实得 %d 对）" % len(pairs))

    print("== 3. 本票声明对登记在案")
    check(DECLARED_PAIR in pairs,
          "含声明对 %s → %s（解析全对=%s）" % (DECLARED_PAIR[0], DECLARED_PAIR[1], pairs))

    print("== 4. 前缀与仓实况对齐（防路径写错静默失效）")
    for src, out in pairs:
        for prefix in (src, out):
            check(os.path.isdir(os.path.join(REPO, prefix)),
                  "前缀是仓内真实目录：%s" % prefix)
    return finish()


def finish():
    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
