#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_test_ns_consistency.py — 测试台命名空间一致性看守（t260917-07 验收③）。

intent（用户可感知契约）：「台面 compose 声明的测试台命名空间」与「起台入口回落、
baselines 断言、资产字面量、文档表述」不可静默漂移。t260917-07 实锤的半截迁移
（d342b46 终切改了 compose 缺省未触 stage_docker 回落；t260917-02 改 lib 未同步看守）
让一仓出现两个现役台名（stage_docker 台=suyou-test / 裸 compose 台=sandbar-test），
套件「台面供给红/环境红」即此。同类漂移已两起在案，本守钉死。

与同族看守的分工（review 意见④，不重复设防）：
  - t260907-04/sc_naming_grep_assert = **全树旧 suyou 标识零容忍**：注释/文案/任意
    上下文归它（marker + 豁免册白名单），扫 server/engine + server/tools + integration；
  - 本守 = **台面契约值一致性**：只锚定「测试台命名空间」这一个值——compose 缺省插值、
    stage_docker 回落、baselines TEST_NS 三处锚 + integration 树内带引号的旧名字面量
    （消费面）+ 两篇测试文档的旧名表述。注释里的裸旧名（非引号非赋值形态）归
    t260907-04，本守不设防。

故障模式取舍清单（参考 sc_naming_grep_assert 逐项裁定，review 意见④）：
  - 自证红绿（合成样本注入即红/干净样本即绿）：**带过来**——看守必须自证「漂移必红」，
    否则断言恒真≠守卫（KI-051 反面）；
  - 单 marker（行内 naming-compat 标记）即可豁免：**不带**——一个注释标记就能洗白
    任意新字面量，恰是旧名漂移存活至今的通道；本守改**双锁**：行含 marker 且
    (rel, 出现数) 锚在 ALLOW 册（file → 最大出现数 → 逐条理由），缺一即红；
  - 全树扫描 + TEXT_EXT 多扩展名：**不带**——本守契约面只有测试台命名空间一个值，
    integration/ 的 .py/.mjs 引号字面量已覆盖全部消费面；docs 只看旧名子串
    （表述同步面，带 marker 的历史叙述可豁免）；server/ 的声明面由锚定断言覆盖；
  - 锚点解析 fail-closed：**新增**——compose/stage_docker/baselines 的锚缺失、
    数量≠预期、值不可解析一律红。找不到锚=绿正是本票要钉死的静默漂移反面
    （KI-051「守卫锚×改名脱钩」同族）；未来锚点数量变化必须连看守一起改，
    改声明不破看守即红。

Hermetic：只读扫描 + tmp 合成样本自证，零网络零舞台；cwd=仓库根；秒级。
**实现落地前红属预期（TDD 信号）：baselines 收口随人审放行或 main 侧直修，
落定前 c 条红=如实漂移记账；arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)

OLD_NAME = "suyou-test"
COMPOSE_REL = os.path.join("server", "docker-compose.test.yml")
STAGE_REL = os.path.join("integration", "stage_docker.py")
BASELINE_REL = os.path.join("integration", "baselines", "ticket-lifecycle-scenes.mjs")
DOC_RELS = (os.path.join("docs", "testing-guide.md"),
            os.path.join("integration", "README.md"))

# 锚数量预期（fail-closed：增删锚点必须连本守一起改，否则红）
EXPECT_COMPOSE_ANCHORS = 2    # compose：command --namespace + dsh environment 各 1
EXPECT_STAGE_FALLBACKS = 2    # stage_docker：compose_env + adopt_live_residue 各 1
EXPECT_BASELINE_ANCHORS = 1   # baselines：TEST_NS 恰 1 处

COMPOSE_ANCHOR_RE = re.compile(r"\$\{SANDBAR_TEST_NAMESPACE:-([^}]*)\}")
STAGE_FALLBACK_RE = re.compile(r'opts\.get\("namespace"\)\s+or\s+"([^"]*)"')
BASELINE_TEST_NS_RE = re.compile(r"export const TEST_NS = '([^']*)'")
LITERAL_RE = re.compile(r"['\"]%s['\"]" % OLD_NAME)

SKIP_DIRS = {"node_modules", "__pycache__", ".git", "out", "data"}

# 双锁豁免册（终态口径）：rel → (最大允许引号旧名字面量数, 理由)。
# 行内必须同时带 naming-compat 标记——单 marker 曾是漂移存活通道，双锁缺一即红。
ALLOW = {
    "integration/t260907-04/sc_naming_grep_assert.py": (
        1, "看守自身 OLD_RE 匹配表：旧名即被测对象（t260907-04 命名看守契约内容）"),
}
SELF = "integration/t260917-07/sc_test_ns_consistency.py"


def extract_compose_defaults(text):
    return COMPOSE_ANCHOR_RE.findall(text)


def extract_stage_fallbacks(text):
    return STAGE_FALLBACK_RE.findall(text)


def extract_baseline_ns(text):
    return BASELINE_TEST_NS_RE.findall(text)


def check_contract(compose_text, stage_text, baseline_text):
    """四层锚定断言（纯函数，供真树与合成样本共用）。返回 (failures, contract)。"""
    failures = []
    # a) compose 声明面：缺省插值恰 N 处、值相等且非空 → 契约值 C
    vals = extract_compose_defaults(compose_text)
    if len(vals) != EXPECT_COMPOSE_ANCHORS:
        failures.append(
            "compose 锚数量=%d ≠ %d（SANDBAR_TEST_NAMESPACE 缺省插值缺锚/变形/增删——"
            "找不到锚=绿正是静默漂移反面，fail-closed）" % (len(vals), EXPECT_COMPOSE_ANCHORS))
        return failures, None
    contract = vals[0]
    if not contract:
        failures.append("compose 契约值为空串（缺省插值不可为空）")
    if any(v != contract for v in vals):
        failures.append("compose 两处缺省插值互异：%r（声明面自漂移）" % vals)
    # b) 起台入口回落 == C
    fb = extract_stage_fallbacks(stage_text)
    if len(fb) != EXPECT_STAGE_FALLBACKS:
        failures.append("stage_docker 回落锚数量=%d ≠ %d（回落点增删未同步看守，fail-closed）"
                        % (len(fb), EXPECT_STAGE_FALLBACKS))
    else:
        bad = [v for v in fb if v != contract]
        if bad:
            failures.append("stage_docker 回落 %r ≠ 契约值 %r（起台入口显式覆盖 compose 声明"
                            "=本票事故真源形态）" % (fb, contract))
    # c) baselines TEST_NS == C（保护文件只读断言；收口前红=TDD 信号窗口）
    ns = extract_baseline_ns(baseline_text)
    if len(ns) != EXPECT_BASELINE_ANCHORS:
        failures.append("baselines TEST_NS 锚数量=%d ≠ %d（fail-closed）"
                        % (len(ns), EXPECT_BASELINE_ANCHORS))
    elif ns[0] != contract:
        failures.append("baselines TEST_NS=%r ≠ 契约值 %r（保护文件收口：authorize 放行"
                        "本票改或 main 侧直修——t260917-07 S3，patch 随交付；落定前此红"
                        "=TDD 信号窗口，merge 期必须绿）" % (ns[0], contract))
    return failures, contract


def literal_line_verdict(rel, line, file_total=None):
    """行级双锁判定：引号旧名字面量须 marker+在册，且**文件级**出现总数≤册上限。
    登记语义是 file→最大出现数——若按行计数，「多行×1 处」可绕开数量锁（洗白通道），
    故文件总数由 scan_literals 预计算传入；file_total=None 退化为按本行计数
    （自证样本单行形态）。返回 (ok, reason)。"""
    n = len(LITERAL_RE.findall(line))
    if not n:
        return True, ""
    marked = "naming-compat" in line
    allow = ALLOW.get(rel)
    cap = allow[0] if allow else None
    total = file_total if file_total is not None else n
    if marked and cap is not None and total <= cap:
        return True, ""
    return False, "marker=%s inbook=%s 文件计数=%d 册上限=%s（%s）" % (
        marked, allow is not None, total, cap,
        allow[1] if allow else "未入 ALLOW 册")


def scan_literals(integ_dir):
    """integration 树 .py/.mjs 引号旧名字面量扫描，返回 [(rel, lineno, line, reason)]。

    看守自身文件（SELF）豁免：本文件的自证红绿夹具以旧名字面量为被测对象内容
    （t260907-04 同款先例：`rel in (SELF, UT)` 豁免）——扫描根恒为 integration/，
    绝不出界扫 server/（server/ 声明面由锚定断言覆盖，消费面资产全在 integration/）。"""
    hits = []
    for dirpath, dirnames, filenames in os.walk(integ_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith((".py", ".mjs")):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, REPO)
            if rel == SELF:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            total = sum(len(LITERAL_RE.findall(ln)) for ln in lines)
            if not total:
                continue
            for i, line in enumerate(lines, 1):
                ok, reason = literal_line_verdict(rel, line, file_total=total)
                if not ok:
                    hits.append((rel, i, line.strip()[:100], reason))
    return hits


def scan_docs():
    """测试文档表述同步面：旧名子串仅可在带 naming-compat 标记的行出现。"""
    bad = []
    for rel in DOC_RELS:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            bad.append((rel, 0, "<文件缺失（fail-closed）>"))
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError) as e:
            bad.append((rel, 0, "<不可读：%s>" % e))
            continue
        for i, line in enumerate(lines, 1):
            if OLD_NAME in line and "naming-compat" not in line:
                bad.append((rel, i, line.strip()[:100]))
    return bad


def selftest():
    """合成样本自证红绿（review 意见③④：漂移必红/锚缺失必红/锚数异常必红）。"""
    f = []
    good_compose = ("- ${SANDBAR_TEST_NAMESPACE:-sandbar-test}\n"
                    "  X: ${SANDBAR_TEST_NAMESPACE:-sandbar-test}\n")
    good_stage = ('a = opts.get("namespace") or "sandbar-test"\n'
                  'b = opts.get("namespace") or "sandbar-test"\n')
    good_base = "export const TEST_NS = 'sandbar-test'\n"
    # 干净样本 → 绿，契约值正确
    fl, c = check_contract(good_compose, good_stage, good_base)
    if fl:
        f.append("自证：干净样本应绿，实际红 %r" % fl)
    if c != "sandbar-test":
        f.append("自证：契约值提取错 %r" % c)
    # compose 缺省漂移 → 红
    fl, _ = check_contract(good_compose.replace("sandbar-test", "suyou-test"),
                           good_stage, good_base)
    if not fl:
        f.append("自证：compose 缺省漂移样本未红")
    # 锚缺失（只 1 处）→ 红（vacuous pass 禁止）
    fl, _ = check_contract("- ${SANDBAR_TEST_NAMESPACE:-sandbar-test}\n", good_stage, good_base)
    if not fl:
        f.append("自证：compose 锚缺失样本未红")
    # 锚数量异常（3 处）→ 红
    fl, _ = check_contract(good_compose + "  Y: ${SANDBAR_TEST_NAMESPACE:-sandbar-test}\n",
                           good_stage, good_base)
    if not fl:
        f.append("自证：compose 锚数量≠2 样本未红")
    # stage_docker 回落漂移（仅 1 处改旧名）→ 红
    drifted_stage = good_stage.replace(
        'b = opts.get("namespace") or "sandbar-test"',
        'b = opts.get("namespace") or "suyou-test"')
    fl, _ = check_contract(good_compose, drifted_stage, good_base)
    if not fl:
        f.append("自证：stage_docker 回落漂移样本未红")
    # baselines TEST_NS 漂移 → 红
    fl, _ = check_contract(good_compose, good_stage, "export const TEST_NS = 'drift-ns'\n")
    if not fl:
        f.append("自证：baselines TEST_NS 漂移样本未红")
    # 扫描器语义：引号旧名必命中、新名不命中
    if not LITERAL_RE.search("x = 'suyou-test'"):
        f.append("自证：字面量扫描器漏报旧名")
    if LITERAL_RE.search("x = 'sandbar-test'"):
        f.append("自证：字面量扫描器误报新名")
    if LITERAL_RE.search("// suyou-test 注释形态不带引号"):
        f.append("自证：扫描器误伤无引号注释（该面归 t260907-04）")
    # 双锁判定：marker+在册+文件计数≤上限=绿；去 marker=红；超上限（单行/多行累计）=红；未入册=红
    inbook = "integration/t260907-04/sc_naming_grep_assert.py"
    ok, _ = literal_line_verdict(inbook, 'x = "suyou-test"  # naming-compat')
    if not ok:
        f.append("自证：在册+marker 行应豁免，实际红")
    ok, _ = literal_line_verdict(inbook, 'x = "suyou-test"')
    if ok:
        f.append("自证：在册但无 marker 行应红（双锁），实际绿")
    ok, _ = literal_line_verdict(inbook, '"suyou-test" "suyou-test"  # naming-compat')
    if ok:
        f.append("自证：单行超册上限应红，实际绿")
    ok, _ = literal_line_verdict(inbook, 'y = "suyou-test"  # naming-compat', file_total=2)
    if ok:
        f.append("自证：多行×1 处累计超册应红（按行计数的洗白通道已封），实际绿")
    ok, _ = literal_line_verdict("integration/other.py", "x = 'suyou-test'  // naming-compat")
    if ok:
        f.append("自证：未入册文件行应红（单 marker 不得洗白），实际绿")
    return f


def main():
    failures = []
    print("== t260917-07 测试台命名空间一致性看守（契约真源=server/docker-compose.test.yml）")

    def read(rel):
        with open(os.path.join(REPO, rel), "r", encoding="utf-8") as f:
            return f.read()

    # 真树四层锚定
    try:
        fl, contract = check_contract(read(COMPOSE_REL), read(STAGE_REL), read(BASELINE_REL))
        failures += fl
        print("  契约值 C=%r（compose 恰 %d 锚）" % (contract, EXPECT_COMPOSE_ANCHORS))
    except (OSError, UnicodeDecodeError) as e:
        failures.append("锚文件不可读（fail-closed）：%s" % e)
    # 引号字面量双锁扫描（根=integration 树，绝不出界）
    for rel, i, line, reason in scan_literals(INTEG):
        failures.append("引号旧名字面量 %s:%d 双锁不过（%s）：%s" % (rel, i, reason, line))
    # 文档表述面
    for rel, i, line in scan_docs():
        failures.append("测试文档旧名表述未同步 %s:%d：%s" % (rel, i, line))
    # 合成样本自证（看守自身红绿语义）
    st_failures = selftest()
    failures += st_failures

    if failures:
        for msg in failures:
            print("  FAIL %s" % msg)
        print("\nSUMMARY pass=%d fail=%d（漂移零容忍；fail 条目即漂移清单）"
              % (0, len(failures)))
        return 1
    print("  ok 契约值三层锚定一致（compose 缺省=stage_docker 回落=baselines TEST_NS）")
    print("  ok integration 树引号旧名字面量双锁零违例（ALLOW 册 %d 条）" % len(ALLOW))
    print("  ok 测试文档（testing-guide / README）旧名表述零残留")
    print("  ok 合成样本自证红绿全过（干净/漂移/锚缺失/锚数异常/双锁语义/扫描器不误伤注释）")
    print("\nSUMMARY pass=4 fail=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
