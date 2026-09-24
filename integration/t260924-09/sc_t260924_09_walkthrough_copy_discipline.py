#!/usr/bin/env python3
"""派活文案·取证纪律声明面（t260924-09，registry: t260924-09-walkthrough-copy-discipline）。

意图（灰盒 L1 级静态契约，ro 池离线秒级，零网络零 docker）：
工单必做①「走查与仲裁的派活文案明确写死」——文案就是本票的用户可感知交付物
（agent 段行为由派活文案引导；t260924-04 实证纯文案挡不住全量滥用，但护栏之外
文案仍必须说对话：文案缺声明=「机械判了文案没说」的单边态，t260921-04 对称
纪律）。断言四处派活声明面（真源文件静态读，锚语义标记不锚 prompt 键名与整句
排版）：

- 走查段与仲裁段两处派活 prompt（dev_lane.py）各含一段「取证纪律」声明，且每段
  声明窗口内四要素齐备：
  ①「闸回执即全量证据」（闸回执就是全量证据，不许再跑全量自证）；
  ②定点复现入口 `--only`（复现单条红=定点）；
  ③闸口径 `--exclude-pools engine,exclusive`（必做③口径一致；engine 归 pytest）；
  ④每段非定点全套次数上限（「1 趟」——与机械护栏同口径）；
- integration 角色 persona（roles/integration.yml）同样四要素；
- 一致性副锁：机械护栏面（agent_activities）闸口径字面与文案同源——漂移即红。

intent 分工：机械行为面归 suite-guard-receipt（真缝回执契约）与 developer L1
分类纯函数真值表——本条只守声明面齐备与口径字面一致，不测行为。
被扫文件缺席=产品红（受控资产面）；无 ENV 子用例。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE_LIT = "engine,exclusive"          # 闸口径字面（verify.yaml exclude_pools 同源）
MARK = "取证纪律"                       # 声明块锚（语义标记，不锚键名/排版）
WIN = 700                              # 声明块语义窗口（声明段为紧凑块）


def main():
    dev_p = REPO / "server/engine/dev_lane.py"
    yml_p = REPO / "server/roles/integration.yml"
    aa_p = REPO / "server/engine/agent_activities.py"
    for p in (dev_p, yml_p, aa_p):
        if not p.is_file():
            print("FAIL [文件面] %s 缺席（受控资产缺失）" % p)
            sys.exit(EXIT_FAIL)
    dev = dev_p.read_text("utf-8")
    persona = yml_p.read_text("utf-8")
    aa = aa_p.read_text("utf-8")

    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：" + detail) if detail and not ok else ""))

    def four_elements(label, blob):
        check("%s：①含「闸回执」即全量证据声明" % label, "闸回执" in blob)
        check("%s：②含定点入口 --only" % label, "--only" in blob)
        check("%s：③含闸口径 %s" % (label, GATE_LIT), GATE_LIT in blob)
        check("%s：④含每段非定点全套次数上限（1 趟）" % label,
              bool(re.search(r"1\s*趟", blob)))

    # 走查 + 仲裁：dev_lane 内取证纪律声明块至少两处，逐处四要素
    idx = [m.start() for m in re.finditer(MARK, dev)]
    check("dev_lane.py 取证纪律声明块 ≥2 处（走查+仲裁都写死）", len(idx) >= 2,
          "实见 %d 处" % len(idx))
    for i, pos in enumerate(idx[:2]):
        four_elements("dev_lane 声明块#%d" % (i + 1), dev[pos:pos + WIN])

    # integration 角色 persona：同样四要素（窗口锚取证纪律标记，缺席则全文找）
    ppos = persona.find(MARK)
    four_elements("integration 角色 persona",
                  persona[ppos:ppos + WIN] if ppos >= 0 else persona)

    # 一致性副锁：护栏侧闸口径字面与文案/声明同源（漂移即红）
    check("机械护栏面（agent_activities）闸口径字面与文案/声明同源",
          bool(re.search(r"engine\s*,\s*exclusive", aa)))

    n_fail = legs.count(False)
    print("SUMMARY t260924-09-walkthrough-copy-discipline: %d/%d 绿"
          % (len(legs) - n_fail, len(legs)))
    sys.exit(EXIT_PASS if n_fail == 0 else EXIT_FAIL)


if __name__ == "__main__":
    main()
