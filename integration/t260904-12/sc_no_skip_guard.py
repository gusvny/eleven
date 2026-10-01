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
    re.compile(r"退役|定稿|[「（(]?闸内无\s*SKIP|旧口径|旧语义|旧词|兼容别名|历史"),   # 退役注记/历史提及
                                        # （「闸内无 SKIP」原形只认 「」 角括号，t260922-02 头注写成全角括号即漏判——260923 放宽到任意括起/裸写）
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
    re.compile(r"skip_settle="),                                        # 引擎 AgentStageArgs 参数名（headless/worker 执行面；
                                        # t260917-08/-04/-14 场景夹具同形）——执行形态开关，非套件状态值
    re.compile(r"ScheduleOverlapPolicy\.SKIP|OverlapPolicy=SKIP"),      # Temporal 调度 API 枚举（t260917-02 资产；服务端
                                        # overlap 语义，非本仓三态词表）
    re.compile(r"num_actions_skipped_overlap|skipped_overlap"),         # Temporal ScheduleInfo 字段名（snake_case 内既有
                                        # skipped\b 不出界——260922 仲裁补）
    re.compile(r"skip_count"),                                          # Temporal deadman 回执键名（t260917-02 资产）
    re.compile(r"skip_archive_no"),                                     # 守望者夹具命令旋钮名（server/plugins/watchdog/harness.mjs:344
                                        # ——造归档跳号用的注入参数，非套件三态状态词；260929 直修 C 实测残留即此一处）
    re.compile(r"SKIP；全部子用例"),                                     # 三态契约句引用（t260921-05 lib 头注；
                                        # 「闸内无 SKIP」退役注记同族）
    # ---- 260923 新增三类（t260904-12 门与后续定稿/资产撞字的清账；每类只锚具体形态，不放松裸词）----
    re.compile(r"verdict\(pass\|fail\|env_fail\|skip\)"),                # 台账 schema 原文：定稿 docs/design/failure-classification-protocol-v1.md
                                        # 「verdict（pass|fail|env_fail|skip）」与引擎 failure_protocol.LEDGER_VERDICTS
                                        # 是同款取值枚举（t260922-12 交付面）；照协议写下的词表不是套件状态值。
                                        # 实盘台账 4673/113/74 行无一 skip 行=该取值声明性存在。
    re.compile(r"env_fail/skip|env_fail_and_skip"),                      # 协议采信边界引用（t260922-12：env_fail 与 skip
                                        # 成对出现在「不采信」负向规则里，含其协议测试名）——负向表述，
                                        # 与既有「不写 SKIP」「闸内无 SKIP」同类。
    re.compile(r"pytest\.mark\.skipif"),                                # pytest 框架 API（环境前提不可测时跳过该用例，
                                        # 如缺 zstd CLI）——与既有 skipTest 同类：框架机制，非三态状态值。
    re.compile(r"skip_when_src_absent"),                                # 被测产品行为名（t260922-12：依赖链在 src 缺席时
                                        # 的取舍＝基线裸态方向，测试名描述产品行为，非套件状态值）。
    re.compile(r"SKIP_DSH_BITS_CHECK|skip_switch"),                      # 产品逃生开关名（安装器版本位检查逃生门：
                                        # env SANDBAR_SKIP_DSH_BITS_CHECK 与测试名 test_skip_switch_*，
                                        # t260923-06 资产）——语义=明知版本位不符仍放行但留痕，非套件跳过状态值。
    re.compile(r"apply_skip_pools"),                                     # 引擎载荷参数名（verify_lane integ 道池排除开关，
                                        # t260913-03 交付、t260924-05 回归棒消费）——排除面开关名，
                                        # 非套件跳过状态值（与 skip_settle=/skipped_budget 同类）。
    # ---- 260928 新增一类（同族清账）：三态契约的**英文负向表述** ----
    # t260928 的票面英文化把新场景头注写成 "Three-exit contract: PASS=0 / FAIL=1 /
    # ENV_FAIL=2 (no SKIP)." —— 与既有「不写 SKIP」「闸内无 SKIP」是同一件事（声明没有
    # 第四态），只是换了语言。只锚**否定式**形态（no/without/never + SKIP、SKIP-free）：
    # 裸词 SKIP 与任何 SKIP 状态值照旧红，T1b 白名单自证同组判据照旧咬得住。
    re.compile(r"\b(?:no|without|never)\s+SKIP\b|SKIP-free", re.I),
    # ---- 260928 第二批同族清账（撞字三类，各只锚具体形态，裸词照旧红）----
    re.compile(r"\bmust\s+skip\b|\bmust not masquerade\b", re.I),        # 英文**行为描述**：新场景头注写
                                        # "a project-scope class … must skip + announce LOUD"（描述产品行为，
                                        # 与既有 skip_when_src_absent 同类，非套件状态值）
    re.compile(r"skip_enabled_gate"),                                   # 产品 API 参数名（事件账 enabled 闸的显式满足开关，
                                        # t260928-13/-20 交付面）——与 apply_skip_pools/skip_settle= 同类
    re.compile(r"/SKIP/\.test\("),                                      # 文档内容断言里的正则字面量（baselines 守「契约文档
                                        # 提到缺失态 SKIP」——读文档文本，非套件产出状态值）
    # ---- 261001 新增一类（同族清账，integration 岗位判词）：中文**否定式**契约声明 ----
    # `integration/engine-ops/sc_engine_ops_offline.py:375` 的
    # "ENV_FAIL: 子用例A 需真 Temporal（…不可达）——该子用例具名不可得（不静默 skip）"：
    # 语义=**声明不静默跳过**（环境不可得即具名 ENV_FAIL），与既有的「不写 SKIP」
    # 「no SKIP / SKIP-free」是同一件事，只差语言与语气。只锚**否定式连写**（不静默/
    # 不悄悄/不许 + skip），裸词 skip 与任何 skip 状态值照旧红——T1b 自证同组照旧咬得住。
    re.compile(r"(?:不静默|不悄悄|不许|不得|不可)[^，。；\n]{0,8}skip", re.I),
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

# ---- T1b 白名单自证（260923 补）：白名单只许放行「注明了的合法残留」，
# 绝不许随条目累积把**裸词**也放过——跑批里真出现静默跳过时，这道门必须还喊得出来。
# 判定式与上面扫描**同一组**（FORBIDDEN/SLOW/ALLOW），不另起一套口径。
def _still_red(line: str) -> bool:
    s = SLOW.sub("", line)
    return bool(FORBIDDEN.search(s)) and not any(a.search(s) for a in ALLOW)


# 合成样本一律 chr() 构词（t260920-03 同款自洁纪律）：本文件虽在 WHITELIST，
# 但 lint 的旧词状态值禁入规则不认白名单——源码字面写死会把 L6 撞红。
_SK, _KP, _SP = chr(115) + chr(107) + chr(105) + chr(112), chr(83) + chr(75) + chr(73) + chr(80), " "
_red_samples = [
    "verdict = '%s' if not tested else 'pass'" % _SK,                       # 状态值当数据写
    "if not env_ok: %s = True  # 静默跳过" % _SK,                             # 静默跳过形状
    "SUMMARY pass=3 %s=1" % _SK,                                            # 旧计数形状
]
_green_samples = [
    "# 闸内无 %s" % _KP,                                                     # 退役注记（角括号形）
    "（闸内无 %s，t260904-12）" % _KP,                                        # 退役注记（全角括号形，260923 起认）
    "pool(...) verdict(pass|fail|env_fail|%s)" % _SK,                       # 协议词表原文
    "@pytest.mark.%sif(not HAS_ZSTD, reason='x')" % _SK,                    # 框架 API
    "def test_dep_links_%s_when_src_absent():" % _SK,                       # 被测产品行为名
]
ok(all(_still_red(s) for s in _red_samples),
   "T1b 白名单自证：裸状态词/静默跳过/旧计数形状仍判红（%d 条合成样本）" % len(_red_samples))
ok(not any(_still_red(s) for s in _green_samples),
   "T1b 白名单自证：注明过的合法残留放行（%d 条合成样本）" % len(_green_samples))

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
