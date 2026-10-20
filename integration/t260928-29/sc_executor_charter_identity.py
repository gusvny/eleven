#!/usr/bin/env python3
"""执行器身份·charter 分段身份面（t260829-29 → t260928-29，registry: t260928-29-executor-charter-identity）。

意图（灰盒 L2 级静态契约，ro 池离线秒级，零 docker 零网络）：
设计稿决定 8（notes/discussions/260927-project-executor-design.md L482-484/L575）＝每个项目
一份执行器人设 + 一段 charter。本票把 sandbar 的执行器身份块落进
server/session_charter.md 的 `## project:sandbar` 分段（唯一已到达每个新建项目会话的
通道）。用户可感知承诺与故障面：

- A 身份在文：sandbar 分段带执行器身份——who（本项目常驻执行器、站用户一侧）、
  MAY 面（代签/打回/开票/暂停恢复/取消）、NEVER 面（不自扩权/不动控制台/不跨项目/
  不替用户拍板/不手工维护进度表/主树直修需当面授权锚）、最小权限缺省（零授予＝只能
  看和问）且**不暗示授予面已存在**（面板/设置页属后续票，落地前无任何授予来源）。
- B 未声明项目零行为变化（源头面）：通用模板段**不得**混入执行器身份标记——未声明
  项目的回落文本保持今天的通用形态；身份只经项目分段送达。（端点活体层面的
  「未命中项目只回通用段」归 t260904-07-charter-endpoint-live，本条不重复。）
- C 双分段共存：sandbar 与 suyou 分段都在（跨项目隔离面，别的项目内容不进本票）。

intent 分工（防 intent 级重复）：t260904-07 三条守「交付物在位/端点活体/注入一次」
的结构与接线契约；本条只守**本票新增内容**——身份语义在 sandbar 分段在文、通用段
不回潮。锚语义关键词组（每组任一别名命中即过），不锚整句排版。实现未落地段红属
预期（TDD 信号），arbitrate/merge 期必须绿。无 ENV 子用例（受控资产静态读，资产
缺席=产品红非环境红）。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
CHARTER = REPO / "server" / "session_charter.md"

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


def section(title):
    print("\n=== %s ===" % title)


def split_sections(text):
    """(generic_template, {key: section_body}) — 与端点 splitProjectSections 同语义。"""
    parts = re.split(r"(?m)^(## project:([A-Za-z0-9_-]+))\s*$", text)
    generic = parts[0]
    secs = {}
    for i in range(1, len(parts), 3):
        secs[parts[i + 1]] = parts[i + 2]
    return generic, secs


# 语义锚组：每组给若干可接受的措辞别名，组内任一命中=该承诺在文。
GROUPS = [
    ("who: 本项目常驻执行器/站用户一侧/非泳道角色",
     [r"执行器"]),
    ("MAY: 代签", [r"代签"]),
    ("MAY: 打回", [r"打回"]),
    ("MAY: 开票", [r"开票"]),
    ("MAY: 暂停/恢复", [r"暂停", r"恢复"]),
    ("MAY: 取消", [r"取消"]),
    ("NEVER: 不自授权/不扩权",
     [r"不.{0,8}(自行|给自己|自).{0,4}(授权|扩权|加权)", r"授权只能由", r"绝不自我扩权"]),
    ("NEVER: 不重启/停止/占用控制台",
     [r"(控制台|console|3099).{0,24}(重启|停止|占用)",
      r"(重启|停止|占用).{0,24}(控制台|console|3099)"]),
    ("NEVER: 不跨项目动手",
     [r"跨项目"]),
    ("NEVER: 不替用户拍板设计问题",
     [r"(拍板|做主|定夺)", r"设计.{0,12}(属于|归).{0,6}用户", r"不.{0,8}替用户.{0,8}(决定|拍板)"]),
    ("NEVER: 不手工维护进度表",
     [r"(手工|手动).{0,10}维护.{0,10}(进度|台账|清单)", r"进度(表|记录)"]),
    ("NEVER: 主树直修须当面授权锚",
     [r"主树.{0,10}直修", r"直修.{0,20}(授权|锚)", r"当面.{0,10}(授权|原话|commit)"]),
    ("默认最小权限: 零授予只能看和问",
     [r"零授予", r"没有任何授予", r"未授予", r"无授权.{0,20}(只|仅)", r"只能看和问", r"只(能|可)(看|读).{0,6}问"]),
    ("授予面尚不存在（不暗示已有权限来源）",
     [r"(尚|暂|还|未)不?存在", r"后续票", r"(设置页|面板).{0,12}(尚未|落地|后续)", r"授予.{0,12}(尚未|后续|面板)"]),
]


def main():
    text = CHARTER.read_text("utf-8") if CHARTER.is_file() else ""
    generic, secs = split_sections(text)

    section("A sandbar 分段执行器身份在文")
    sand = secs.get("sandbar", "")
    ok(bool(sand.strip()), "A0 ## project:sandbar 分段存在且非空")
    for name, alts in GROUPS:
        ok(any(re.search(p, sand) for p in alts), "A %s" % name)

    section("B 通用模板不混入执行器身份（未声明项目零变化·源头面）")
    ok("执行器" not in generic, "B1 通用模板无执行器身份标记")
    ok(bool(re.search(r"\{\{project_key\}\}.*\{\{engine_root\}\}", generic, re.S)),
       "B2 通用模板占位符仍在（回落渲染前提，t260904-07 同源前提面）")

    section("C 双分段共存")
    ok("suyou" in secs, "C1 ## project:suyou 分段仍在")
    ok(set(secs) <= {"sandbar", "suyou"}, "C2 未新增其他项目分段（本票范围外）")

    print("\nRESULT pass=%d fail=%d" % (PASS, FAIL))
    return EXIT_PASS if FAIL == 0 else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
