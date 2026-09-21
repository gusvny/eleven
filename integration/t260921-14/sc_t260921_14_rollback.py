#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-14 场景③：回退剧本机械验证（灰盒 L2，ro 池，离线秒级）。

intent（用户可感知）：宿主令「回退是硬要求」+「回退=配置改回一行」——引擎层回退
（删/注释 per-key 条目的 paths.dsh_bin 行）后行为**逐字**回到裸 dsh 现状（不残留
死键红、不残留钉态尾巴）；镜像层回退（SANDBAR_AGENT_IMAGE 指回旧 tag）立即生效
无需重建；回退剧本（ROLLBACK.md）写成文且含可执行的旧 tag/命令锚（剧本可读面
不腐烂）。

依据：①工单交付④「三层各自回退」+验收 L2④「至少引擎层配置回退有机械验证」+
宿主令④；②KI-051 锚语义（文档守卫锚「回退所需的字面锚」——此处字面即语义：
旧 tag、声明键名、旋钮名、重装包名）；③对外契约=契约 ①d「未声明=回落现行约定
行为逐字一致」+ SANDBAR_AGENT_IMAGE 旋钮既有语义（t260916-24 定稿）。

high-level steps：每条子用例独立 tmp 注册表（EnvSandbox 隔离）→直调 _prepare_agent_spawn
对拍：①A/B/A——无声明基线 B→加 paths.dsh_bin 行（钉生效前提同子用例自证）→删该行
（lib 的行级手术=「配置改回一行」的机械形态）→prepared cmd 与 B 逐元素等值+face
回 default；②注释形态子用例——`# dsh_bin: …` 行在场=声明缺席语义，同样逐字回 B；
③镜像回退子用例——docker 形态+SANDBAR_AGENT_IMAGE=旧 tag→face image_source=env、
tag 提取版本=0.1.1-rc.2（无 docker 调用：旧镜像不删不覆盖即可指回）；④文档守卫
子用例（review C4）——integration/t260921-14/ROLLBACK.md 在场且含：旧 tag 字面、
dsh_bin: 回退指令、SANDBAR_AGENT_IMAGE 旋钮、宿主全局回退命令锚（快照目录或按版
重装包名）。

intent 分工：镜像三处同步锁（DEFAULT_AGENT_IMAGE↔Dockerfile ARG↔build 脚本缺省）
归既有 L1（test_镜像版本三处同步，三处翻新自动跟进）——本条守「回退操作的行为面+
剧本可读面」，不同对象不互替；t260916-24 三条守 env 旋钮/启动链/执行面，亦不互替。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现落地前红属预期（TDD：①钉生效半边与④
文档面随 implement 落地转绿；A/B/A 的基线/回退半边应先行绿——它们锚的是现状
语义），arbitrate/merge 期必须绿；引擎模块不可导入=ENV_FAIL exit 2。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26092114 as L  # noqa: E402

C = L.Checker("t260921-14-rollback")

ROLLBACK_DOC = L.REPO / "integration" / "t260921-14" / "ROLLBACK.md"


def leg1_aba_delete_line(aa, dp):
    """①A/B/A：加声明行→删声明行，prepared cmd 逐字回基线（配置改回一行）。"""
    tmp = L.tmp_root("rb-aba")
    stub, _ = L.make_stub(tmp / "bin", "9.9.9-pin", name="dsh_pin_stub_r1.py")
    entry = L.make_registry(tmp / "registry", "sct26092114r1", dsh_bin=None)
    # B：无声明基线
    cmd_b, _, pin_b = L.run_prepare(aa, tmp, "r1a", "sct26092114r1")
    C.check(cmd_b == L.legacy_default_cmd(dp),
            "①基线 B=裸 dsh 缺省逐元素", "实得 %r" % (cmd_b,))
    # A：加声明行（钉生效前提，同子用例自证——没有 A 态的 B/A 对比无意义）
    L.rewrite_dsh_bin(entry, dsh_bin=str(stub))
    cmd_a, _, pin_a = L.run_prepare(aa, tmp, "r1b", "sct26092114r1")
    C.check(bool(cmd_a) and cmd_a[0] == str(stub),
            "①加声明行→钉生效（A 态前提）", "实得 %r" % (cmd_a,))
    # A'：删声明行=回退
    L.rewrite_dsh_bin(entry, dsh_bin=None)
    cmd_r, _, pin_r = L.run_prepare(aa, tmp, "r1c", "sct26092114r1")
    C.check(cmd_r == cmd_b,
            "①删声明行→prepared cmd 与基线逐元素等值（逐字回裸 dsh）",
            "回退后=%r 基线=%r" % (cmd_r, cmd_b))
    C.check((pin_r or {}).get("cmd_source") == "default",
            "①回退后 face cmd_source=default（不残留钉态尾巴）",
            "实得 %r" % (pin_r or {}).get("cmd_source"))


def leg2_comment_form(aa, dp):
    """②注释形态：`# dsh_bin: …` 行在场=声明缺席语义，同样逐字回基线。"""
    tmp = L.tmp_root("rb-cmt")
    stub, _ = L.make_stub(tmp / "bin", "9.9.9-pin", name="dsh_pin_stub_r2.py")
    entry = L.make_registry(tmp / "registry", "sct26092114r2", dsh_bin=None)
    cmd_b, _, _ = L.run_prepare(aa, tmp, "r2a", "sct26092114r2")
    # 先写活声明再注释掉（证明注释形态确实压过活声明语义，而非「从未声明过」）
    L.rewrite_dsh_bin(entry, dsh_bin=str(stub))
    L.comment_dsh_bin(entry)
    cmd_c, _, pin_c = L.run_prepare(aa, tmp, "r2b", "sct26092114r2")
    C.check(cmd_c == cmd_b,
            "②注释形态=声明缺席：cmd 逐字回基线（回退不留死键红）",
            "注释态=%r 基线=%r" % (cmd_c, cmd_b))
    C.check((pin_c or {}).get("cmd_source") == "default",
            "②注释形态 face cmd_source=default", "实得 %r" % (pin_c or {}).get("cmd_source"))


def leg3_image_tag_back(aa):
    """③镜像回退=tag 指回（env 立即生效，无需重建；无 docker 调用）。"""
    tmp = L.tmp_root("rb-img")
    L.make_registry(tmp / "registry", "sct26092114r3", dsh_bin=None)
    cmd, env, pin = L.run_prepare(
        aa, tmp, "r3", "sct26092114r3",
        extra_env={"SANDBAR_AGENT_RUNTIME": "docker",
                   "SANDBAR_AGENT_IMAGE": L.OLD_IMAGE_TAG})
    C.check(bool(cmd), "③docker 形态 prepare 正常产出（回退操作不炸链）",
            "cmd=%r" % (cmd,))
    C.check((pin or {}).get("image") == L.OLD_IMAGE_TAG,
            "③镜像回退：face image=旧 tag", "实得 %r" % (pin or {}).get("image"))
    C.check((pin or {}).get("image_source") == "env",
            "③image_source=env（env 指回立即生效）",
            "实得 %r" % (pin or {}).get("image_source"))
    C.check((pin or {}).get("version") == L.OLD_IMAGE_VERSION
            and (pin or {}).get("version_state") == "ok",
            "③tag 提取版本=0.1.1-rc.2（旧镜像版本面立即可判）",
            "version=%r state=%r" % ((pin or {}).get("version"),
                                     (pin or {}).get("version_state")))


def leg4_rollback_doc_guard():
    """④回退剧本文档守卫（review C4）：ROLLBACK.md 在场+四类回退锚在场。"""
    if not ROLLBACK_DOC.is_file():
        C.fail("④ROLLBACK.md 在场（回退剧本成文）",
               "缺席：%s（implement Step7 交付件）" % ROLLBACK_DOC)
        return
    text = ROLLBACK_DOC.read_text("utf-8")
    C.check(L.OLD_IMAGE_TAG in text,
            "④剧本含旧 tag 字面（镜像回退锚）", "实文无 %s" % L.OLD_IMAGE_TAG)
    C.check("dsh_bin:" in text,
            "④剧本含引擎回退指令锚（dsh_bin: 声明行删/注释语义）",
            "实文无 dsh_bin:")
    C.check("SANDBAR_AGENT_IMAGE" in text,
            "④剧本含镜像回退旋钮（SANDBAR_AGENT_IMAGE）", "实文无 SANDBAR_AGENT_IMAGE")
    C.check(("dsh-011-backup" in text) or ("@deepseek-ai/dsh" in text),
            "④剧本含宿主全局回退命令锚（事前快照或按版重装）",
            "实文无 dsh-011-backup / @deepseek-ai/dsh")


def main():
    aa, ar, dp, sb = L.import_engine()
    leg1_aba_delete_line(aa, dp)
    leg2_comment_form(aa, dp)
    leg3_image_tag_back(aa)
    leg4_rollback_doc_guard()
    return C.finish()


if __name__ == "__main__":
    sys.exit(main())
