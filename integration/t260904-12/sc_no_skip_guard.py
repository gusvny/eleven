#!/usr/bin/env python3
"""SKIP 语义清零防复辟守卫（t260904-12，KI-036/046 同族回归）。

intent：「干净 SKIP（exit 0）」穿闸是 KI-046 实锤的闸穿透根源。本场景守迁移
后的存量面：integration/ 树（基建白名单外）SKIP/skip 字样零残留（含运行时
模板串形态——状态值旧词本身被禁（本行提及属退役注记），源码 grep 字面才能覆盖）；README 执行
契约段三态明文且无 skip-exit0 指引；lint_tests.py 全绿且防回潮规则在位。

白名单口径（gen2 方案 R5 三重清零）：执行器 run_scenarios.py（三态行为已由
t260904-12-executor-three-state 单独钉死）、共享助手 lib_env.py（退役语义
注记）、lint_tests.py（防回潮规则自身须提及禁词）三件基建豁免；其余任何
.py/.mjs 命中即红并点名文件与行。skip_slow（code 道 checks 合法机制名）不属
本守卫语义，剔除后不计。

本场景零环境依赖、秒级。
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
SELF = Path(__file__).resolve()
WHITELIST = {SELF, INTEG / "run_scenarios.py", INTEG / "lib_env.py", INTEG / "lint_tests.py",
             INTEG / "bench.py"}  # bench.py=自检工具变更记录表（历史叙述）

RETIRED_NOTE = re.compile("退役")

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


FORBIDDEN = re.compile(r"SKIP|skip")
SLOW = re.compile(r"skip[_-]slow")
# 合法残留类别（逐类注明，白名单从严——新增类别须在结算 evidence 说明）：
ALLOW = [
    re.compile(r"退役|定稿|「闸内无 SKIP」|旧口径|旧语义|旧词|兼容别名|历史"),   # 退役注记/历史提及
    re.compile(r"skipped_legacy|skipped_not_archived|skipped\b|skip-counted|skip count"),  # 被测产品回执字段/检查名
    re.compile(r"skip1\b|waitProjectRowOrSkip"),                       # 兼容别名/共享助手名（内部已是 env_fail 语义）
    re.compile(r"skipped AND counted|skip count 2"),                    # cache_probe 被测产品行为描述
    re.compile(r"无凭据"),                                              # metrics 契约产品域软降级语义（宿主裁定不属闸语义）
    re.compile(r"不再有 skip|skip 计数"),                                # 退役注记变体
    re.compile(r"(?<![A-Za-z0-9])skips(?:ing)?(?![A-Za-z0-9])"),       # skip_slow 产品特性的动词谓语（非状态词）；边界用字母数字负向断言而非 \b——snake_case 里 _skips_ 的 \b 失效，会把「滑档」谓语（test_external_band_lock_skips_band）误判成状态词（t260904-19 gen10 实锤）
    re.compile(r"SKIP→exit 0→闸计过"),                                  # 本票守卫场景对穿透机制的历史引用
    re.compile(r"不写\s*SKIP"),                                          # 否定式契约声明（t260912 lib
                                        # 头注「缺失=ENV_FAIL exit 2，不写 SKIP」——
                                        # 三态契约的负向表述，与「闸内无 SKIP」退役注记同族）
    re.compile(r"SKIP_DIRS"),                                           # 目录排除表常量名（非测试状态词）
    re.compile(r"skipTest"),                                            # unittest 内建 API（环境前提不可测时跳过单用例），非三态状态词
    re.compile(r"skipped_budget"),                                      # 被测产品回执字段名（t260912-02 stage_docker sweep 报告
                                        # 的预算跳过清单键；acceptance 走查脚本读它=产品域，非套件状态值）
]

hits = []
for f in sorted(INTEG.rglob("*")):
    if f.suffix not in (".py", ".mjs") or f in WHITELIST or f.is_dir():
        continue
    try:
        text = f.read_text()
    except UnicodeDecodeError:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        stripped = SLOW.sub("", line)
        if FORBIDDEN.search(stripped) and not any(a.search(stripped) for a in ALLOW):
            hits.append("%s:%d: %s" % (f.relative_to(REPO), i, line.strip()[:100]))

ok(not hits, "T1 integration/ 树（基建白名单外）SKIP 语义零残留")
if hits:
    for h in hits[:20]:
        print("    残留: " + h)
    if len(hits) > 20:
        print("    …共 %d 处" % len(hits))

# ---- README 执行契约段：三态明文 + 无 skip-exit0 指引 ----
readme = (INTEG / "README.md").read_text()
ok(all(RETIRED_NOTE.search(l) for l in readme.splitlines()
       if re.search(r"干净 SKIP|clean SKIP", l)),
   "T2 README 旧词只准出现在退役注记行（非指引残留）")
ok(not re.search(r"SUMMARY pass=\S* skip=|skip=\d", readme),  # 旧词，退役注记
   "T3 README 无旧词计数形状（SUMMARY 新形状无该计数）")  # 退役
ok("ENV_FAIL" in readme and ("exit 2" in readme or "退出码" in readme),
   "T4 README 执行契约段三态/ENV_FAIL 明文在场")

# ---- lint 全绿 + 防回潮规则在位（锚真实形态） ----
p = subprocess.run([sys.executable, str(INTEG / "lint_tests.py")],
                   capture_output=True, text=True)
ok(p.returncode == 0 and "0 error" in (p.stdout + p.stderr),
   "T5 integration/lint_tests.py 全绿（迁移后树不被 lint 误伤）")
lint_src = (INTEG / "lint_tests.py").read_text()
ok(re.search(r"\]skip\[", lint_src) is not None,  # 旧词退役注记（锚 lint 真实形态：字符类禁入规则）
   "T6 lint 防回潮规则在位：旧词状态值禁入规则（锚真实形态非字面）")
ok("env_fail" in lint_src,
   "T7 lint 防回潮规则在位：SUMMARY/env_fail 形状规则在场")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
