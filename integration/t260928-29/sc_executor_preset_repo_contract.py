#!/usr/bin/env python3
"""执行器身份·preset 仓内真源契约（t260928-29，registry: t260928-29-executor-preset-repo-contract）。

意图（灰盒 L2 级静态契约，ro 池离线秒级，零 docker 零网络）：
方案定盘（t260928-29 create_plan gen1）：执行器 preset 以**仓内新文件**为真源
（server/profile/agent-presets/sandbar-executor/），安装=人手 `cp -R` 进
$DSH_HOME/.agent-presets/（实体复制，软链不被扫描）；`cordis.patch.yml` 的
agent-presets.default **不翻**——翻了会把所有新会话（含全局把关会话）改姓，
违背「按项目来」的设计决定 8。本场景守四条工程承诺：

- A 交付物在位：preset.yml / agent.cordis.yml / README.md 三件在仓、preset 名与
  目录一致（装载面认名）。
- B persona 带通用执行器身份：who（执行器）、NEVER 锚（控制台不重启/不自我扩权/
  不跨项目）与最小权限缺省（零授予只能看和问）在 system-prompt 载体同样在文
  （方案承诺双载体同义，漂移即红）。
- C 无机器绝对路径：preset 文件不得写死 /Users/、/home/ 等机器路径（新项目可
  复制的可复现承诺；KI-073 同族「绝对路径写死」教训）。
- D 加性纪律：cordis.patch.yml 仍指 sandbar-integration，且**不含**
  sandbar-executor——本票对共享挂面文件零编辑的承诺被反停机锁守（260824 事故
  面：default 指到缺席 preset=控制台开不了新会话）。
- E README 安装契约：cp -R 实体复制 + 软链不可用一句 + 跟进票指针
  （workbench 侧按项目自动选 preset 的后续票）在文。

intent 分工：charter 载体归 t260928-29-executor-charter-identity；dsh 侧装载/
roster 行为归 dsh 本体不在本仓断言面。锚语义关键词不锚整句排版。实现未落地段
红属预期（TDD 信号），arbitrate/merge 期必须绿。无 ENV 子用例。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESET_DIR = REPO / "server" / "profile" / "agent-presets" / "sandbar-executor"
PATCH = REPO / "server" / "profile" / "cordis.patch.yml"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def section(t):
    print("\n=== %s ===" % t)


def read(p):
    return p.read_text("utf-8") if p.is_file() else ""


def main():
    section("A 交付物在位")
    pyml = read(PRESET_DIR / "preset.yml")
    cordis = read(PRESET_DIR / "agent.cordis.yml")
    readme = read(PRESET_DIR / "README.md")
    ok(bool(pyml), "A1 preset.yml 在仓")
    ok(bool(cordis), "A2 agent.cordis.yml 在仓")
    ok(bool(readme), "A3 README.md 在仓（安装契约载体）")
    ok(bool(re.search(r"name:\s*['\"]?sandbar-executor", pyml)),
       "A4 preset 名与目录一致（roster 认名前提）")

    section("B persona 通用执行器身份（双载体同义面）")
    body = pyml + cordis
    ok("执行器" in body, "B1 who: 执行器身份在文")
    ok(bool(re.search(r"(控制台|console|3099).{0,24}(重启|停止|占用)|"
                      r"(重启|停止|占用).{0,24}(控制台|console|3099)", body)),
       "B2 NEVER: 不重启/停止/占用控制台")
    ok(bool(re.search(r"不.{0,8}(自行|给自己|自).{0,4}(授权|扩权|加权)|授权只能由|绝不自我扩权", body)),
       "B3 NEVER: 不自我扩权")
    ok("跨项目" in body, "B4 NEVER: 不跨项目动手")
    ok(bool(re.search(r"零授予|没有任何授予|未授予|只能看和问|只(能|可)(看|读).{0,6}问", body)),
       "B5 最小权限缺省: 零授予只能看和问")
    ok(bool(re.search(r"(尚|暂|还|未)不?存在|后续票|(设置页|面板).{0,12}(尚未|落地|后续)", body)),
       "B6 不暗示授予面已存在")

    section("C 无机器绝对路径")
    for label, txt in (("preset.yml", pyml), ("agent.cordis.yml", cordis)):
        ok(not re.search(r"(?m)^.*(/Users/|/home/)", txt), "C1 %s 无机器绝对路径" % label)

    section("D 加性纪律（共享挂面文件零编辑）")
    patch = read(PATCH)
    ok(bool(patch), "D1 cordis.patch.yml 在仓")
    ok(bool(re.search(r"default:\s*['\"]?sandbar-integration", patch)),
       "D2 default 仍指 sandbar-integration")
    ok("sandbar-executor" not in patch,
       "D3 cordis.patch.yml 不含 sandbar-executor（default 不翻、无 roots 新条目）")

    section("E README 安装契约")
    ok("cp -R" in readme or "cp -a" in readme, "E1 实体复制安装指令在文")
    ok("软链" in readme or "symlink" in readme.lower(), "E2 软链不可用说明在文")
    ok(bool(re.search(r"后续|跟进|follow-up", readme, re.I)), "E3 跟进票指针在文")

    print("\nRESULT pass=%d fail=%d" % (PASS, FAIL))
    return EXIT_PASS if FAIL == 0 else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
